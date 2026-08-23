from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from agent.research_chat_service import ResearchChatService
from core.evaluation_models import (
    EvaluationCase,
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
)
from eval.evaluation_evaluators import evaluate_classification, normalized_answer_hash


class UnifiedConversationCaseRunner:
    """Run routing and source-bound answer cases through the real Research Chat."""

    def __init__(self, *, service: ResearchChatService | None = None) -> None:
        self.service = service or ResearchChatService()

    def run(
        self,
        cases: list[EvaluationCase],
        *,
        experiment_id: str,
    ) -> tuple[list[EvaluationRunRecord], list[EvaluatorResult]]:
        records: list[EvaluationRunRecord] = []
        routing: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        citation_hits = 0
        citation_total = 0
        citation_gold_covered = 0
        citation_gold_total = 0
        citation_case_ids: list[str] = []
        clarification_values: list[bool] = []
        clarification_case_ids: list[str] = []

        for case in cases:
            query = str(case.input.get("query") or "")
            if not query:
                continue
            started = time.perf_counter()
            state = self.service.run(
                query,
                conversation_context=case.conversation_state,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            context = dict(state.get("context_pack") or {})
            route = dict(context.get("semantic_route") or {})
            constraints = dict(state.get("extracted_constraints") or {})
            observed = {
                "domain": str(state.get("domain") or route.get("domain") or ""),
                "intent": str(state.get("response_intent") or ""),
                "task": str(constraints.get("canonical_task") or ""),
                "runtime_mode": str(state.get("runtime_mode") or ""),
                "execution_request_count": int(
                    (state.get("deterministic_parent_result") or {}).get(
                        "execution_request_count", 0
                    )
                ),
                "reference_span_ids": _reference_span_ids(state),
                "claim_audit": context.get("grounded_answer_audit") or {},
            }
            failures: list[dict[str, str]] = []
            gold = dict(case.routing_gold or {})
            for field in ("domain", "intent", "task"):
                expected = gold.get(field)
                if expected is None:
                    continue
                expected_text = str(expected or "")
                observed_text = observed[field]
                routing[field].append((case.case_id, expected_text, observed_text))
                if expected_text != observed_text:
                    failures.append(
                        {
                            "stage": "gateway" if field == "domain" else "intent_parse",
                            "status": "failed",
                            "failure_type": f"{field}_mismatch",
                            "owner": "research_chat_router",
                            "expected": expected_text,
                            "observed": observed_text,
                        }
                    )
            if gold.get("intent") == "clarification":
                correct = observed["intent"] == "clarification"
                clarification_values.append(correct)
                clarification_case_ids.append(case.case_id)

            if case.answer_gold:
                citation_case_ids.append(case.case_id)
                observed_spans = set(observed["reference_span_ids"])
                expected_spans = {
                    span for claim in case.answer_gold for span in claim.source_span_ids
                }
                citation_hits += len(observed_spans.intersection(expected_spans))
                citation_total += len(observed_spans)
                covered = bool(observed_spans.intersection(expected_spans))
                citation_gold_covered += int(covered)
                citation_gold_total += 1
                if not covered:
                    failures.append(
                        {
                            "stage": "retrieval",
                            "status": "failed",
                            "failure_type": "required_source_span_missing",
                            "owner": "hybrid_retrieval",
                            "expected": ",".join(sorted(expected_spans)),
                            "observed": ",".join(sorted(observed_spans)),
                        }
                    )
                audit = dict(observed.get("claim_audit") or {})
                if audit.get("invalid_citations"):
                    failures.append(
                        {
                            "stage": "answer_compose",
                            "status": "failed",
                            "failure_type": "invalid_citation_mapping",
                            "owner": "grounded_answer_audit",
                            "observed": str(audit.get("invalid_citations")),
                        }
                    )

            report = str(state.get("final_report") or "")
            records.append(
                EvaluationRunRecord(
                    run_id=f"{experiment_id}:unified:{case.case_id}",
                    experiment_id=experiment_id,
                    case_id=case.case_id,
                    status="failed" if failures else "completed",
                    observed=observed,
                    trace=failures,
                    latency_ms=round(latency_ms, 3),
                    answer_hash=normalized_answer_hash(report),
                )
            )

        metrics: list[EvaluatorResult] = []
        for field in ("domain", "intent", "task"):
            values = routing.get(field) or []
            metrics.append(
                evaluate_classification(
                    f"routing.{field}_macro_f1",
                    [item[1] for item in values],
                    [item[2] for item in values],
                    [item[0] for item in values],
                    threshold=0.95,
                )
            )
        metrics.append(
            _ratio_metric(
                "routing.ambiguous_clarification",
                sum(clarification_values),
                len(clarification_values),
                case_ids=clarification_case_ids,
                threshold=1.0,
            )
        )
        metrics.append(
            _ratio_metric(
                "citation.precision",
                citation_hits,
                citation_total,
                case_ids=citation_case_ids,
                threshold=0.95,
            )
        )
        metrics.append(
            _ratio_metric(
                "citation.coverage",
                citation_gold_covered,
                citation_gold_total,
                case_ids=citation_case_ids,
                threshold=0.90,
            )
        )
        return records, metrics


def _reference_span_ids(state: dict[str, Any]) -> list[str]:
    values = []
    for row in state.get("references") or []:
        if not isinstance(row, dict):
            continue
        value = row.get("source_span_id") or row.get("chunk_id")
        if value:
            values.append(str(value))
    return sorted(set(values))


def _ratio_metric(
    metric_id: str,
    numerator: int,
    denominator: int,
    *,
    case_ids: list[str],
    threshold: float,
) -> EvaluatorResult:
    if denominator == 0:
        return EvaluatorResult(
            evaluator_id="unified-conversation-v1",
            metric_id=metric_id,
            status=EvaluationMetricStatus.NOT_APPLICABLE,
            denominator=0,
        )
    value = numerator / denominator
    return EvaluatorResult(
        evaluator_id="unified-conversation-v1",
        metric_id=metric_id,
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.PASSED if value >= threshold else EvaluationSignal.BLOCKED,
        value=round(value, 6),
        numerator=numerator,
        denominator=denominator,
        applicable_case_ids=case_ids,
        threshold=threshold,
        direction="higher",
    )
