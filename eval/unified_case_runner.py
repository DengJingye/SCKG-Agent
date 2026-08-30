from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.research_chat_service import ResearchChatService
from core.evaluation_models import (
    EvaluationCase,
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
)
from core.trace_context import TraceCollector
from eval.evaluation_evaluators import (
    canonical_trace_complete,
    canonical_trace_trajectory,
    evaluate_classification,
    evaluate_trajectory,
    load_canonical_trace,
    normalized_answer_hash,
)


class UnifiedConversationCaseRunner:
    """Run routing and source-bound answer cases through the real Research Chat."""

    def __init__(
        self,
        *,
        service: ResearchChatService | None = None,
        trace_path: Path | None = None,
    ) -> None:
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.service = service or ResearchChatService(
            trace_collector=(
                TraceCollector(self.trace_path) if self.trace_path is not None else None
            )
        )

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
        trace_complete_values: list[bool] = []
        trace_case_ids: list[str] = []
        trajectory_values: dict[str, list[bool]] = defaultdict(list)
        trajectory_case_ids: dict[str, list[str]] = defaultdict(list)

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
            retrieval_context = dict(context.get("retrieval_context") or {})
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
                "candidate_tools": _candidate_tool_names(state),
                "retrieval_route": str(
                    (retrieval_context.get("adaptive_decision") or {}).get("route")
                    or ""
                ),
                "retrieval_pipeline": [
                    str(item) for item in retrieval_context.get("pipeline") or []
                ],
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
            canonical_trace_id = str(state.get("canonical_trace_id") or "")
            canonical_row = (
                load_canonical_trace(self.trace_path, canonical_trace_id)
                if self.trace_path is not None
                else None
            )
            canonical_trajectory = canonical_trace_trajectory(canonical_row or {})
            trace_complete = canonical_trace_complete(
                canonical_row,
                trace_id=canonical_trace_id,
            )
            trace_complete_values.append(trace_complete)
            trace_case_ids.append(case.case_id)
            if case.expected_trajectory is not None:
                trajectory_result = evaluate_trajectory(
                    case.expected_trajectory,
                    canonical_trajectory,
                )
                for metric_id, value in (
                    (
                        "trajectory.required_steps",
                        bool(trajectory_result["required_step_subset"]),
                    ),
                    (
                        "trajectory.forbidden_steps",
                        int(trajectory_result["forbidden_step_count"]) == 0,
                    ),
                    (
                        "trajectory.ordering",
                        bool(trajectory_result["ordering_correct"]),
                    ),
                    (
                        "trajectory.stop_correctness",
                        bool(trajectory_result["stop_correctness"]),
                    ),
                ):
                    trajectory_values[metric_id].append(value)
                    trajectory_case_ids[metric_id].append(case.case_id)
            records.append(
                EvaluationRunRecord(
                    run_id=f"{experiment_id}:unified:{case.case_id}",
                    experiment_id=experiment_id,
                    case_id=case.case_id,
                    status="failed" if failures else "completed",
                    observed=observed,
                    canonical_trace_id=canonical_trace_id,
                    trace=canonical_trajectory,
                    evaluation_failures=failures,
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
        metrics.append(
            _ratio_metric(
                "trace.completeness",
                sum(trace_complete_values),
                len(trace_complete_values),
                case_ids=trace_case_ids,
                threshold=1.0,
            )
        )
        for metric_id in (
            "trajectory.required_steps",
            "trajectory.forbidden_steps",
            "trajectory.ordering",
            "trajectory.stop_correctness",
        ):
            values = trajectory_values.get(metric_id) or []
            metrics.append(
                _ratio_metric(
                    metric_id,
                    sum(values),
                    len(values),
                    case_ids=trajectory_case_ids.get(metric_id) or [],
                    threshold=1.0,
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


def _candidate_tool_names(state: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for row in state.get("candidate_tools") or []:
        if isinstance(row, dict):
            value = row.get("tool_name") or row.get("name")
        else:
            value = row
        if value:
            values.append(str(value))
    return list(dict.fromkeys(values))


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
