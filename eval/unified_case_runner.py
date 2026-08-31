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
from eval.citation_adjudication import (
    CITATION_EVALUATOR_VERSION,
    CitationAdjudicationContract,
    CitationReference,
)
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
        citation_contract: CitationAdjudicationContract | None = None,
    ) -> None:
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.citation_contract = citation_contract
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
        exact_chunk_covered = 0
        relevant_source_covered = 0
        supported_claim_covered = 0
        supported_reference_count = 0
        adjudicable_reference_count = 0
        citation_v2_case_ids: list[str] = []
        citation_hard_failure_case_ids: list[str] = []
        grounded_claim_values: list[bool] = []
        grounded_claim_case_ids: list[str] = []
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
            diagnostic_retrieval = getattr(self.service, "retrieval", None)
            begin_diagnostic = getattr(
                diagnostic_retrieval,
                "begin_citation_diagnostic_case",
                None,
            )
            end_diagnostic = getattr(
                diagnostic_retrieval,
                "end_citation_diagnostic_case",
                None,
            )
            if callable(begin_diagnostic):
                begin_diagnostic(case.case_id)
            try:
                state = self.service.run(
                    query,
                    conversation_context=case.conversation_state,
                )
            finally:
                if callable(end_diagnostic):
                    end_diagnostic()
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
                if self.citation_contract is None and not covered:
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
                hard_failure = False
                if self.citation_contract is not None:
                    citation_v2_case_ids.append(case.case_id)
                    citation_evaluation = self.citation_contract.evaluate(
                        case.case_id,
                        _citation_references(state, audit=audit),
                    )
                    observed["citation_evaluation"] = citation_evaluation.to_dict()
                    exact_chunk_covered += int(
                        citation_evaluation.exact_chunk_match
                    )
                    relevant_source_covered += int(
                        citation_evaluation.relevant_source_match
                    )
                    supported_claim_covered += int(
                        citation_evaluation.supported_evidence_match
                    )
                    supported_reference_count += len(
                        citation_evaluation.supported_evidence_ids
                    )
                    adjudicable_reference_count += len(
                        citation_evaluation.adjudicable_evidence_ids
                    )
                    if citation_evaluation.unknown_evidence_ids:
                        hard_failure = True
                        failures.append(
                            _citation_failure(
                                "fabricated_or_unknown_citation",
                                observed=citation_evaluation.unknown_evidence_ids,
                            )
                        )
                    if citation_evaluation.source_metadata_conflicts:
                        hard_failure = True
                        failures.append(
                            _citation_failure(
                                "citation_source_metadata_conflict",
                                observed=citation_evaluation.source_metadata_conflicts,
                            )
                        )
                    if citation_evaluation.wrong_source_evidence_ids:
                        hard_failure = True
                        failures.append(
                            _citation_failure(
                                "unsupported_wrong_source_evidence",
                                observed=citation_evaluation.wrong_source_evidence_ids,
                            )
                        )
                    if not citation_evaluation.supported_evidence_match:
                        failures.append(
                            {
                                "stage": "answer_compose",
                                "status": "failed",
                                "failure_type": "supported_evidence_missing",
                                "owner": "citation_evaluator_v2",
                                "observed": ",".join(
                                    citation_evaluation.cited_evidence_ids
                                ),
                            }
                        )
                if audit.get("invalid_citations"):
                    hard_failure = self.citation_contract is not None or hard_failure
                    failures.append(
                        {
                            "stage": "answer_compose",
                            "status": "failed",
                            "failure_type": "invalid_citation_mapping",
                            "owner": "grounded_answer_audit",
                            "observed": str(audit.get("invalid_citations")),
                        }
                    )
                if self.citation_contract is not None and isinstance(
                    audit.get("passed"), bool
                ):
                    grounded_passed = bool(audit["passed"])
                    grounded_claim_values.append(grounded_passed)
                    grounded_claim_case_ids.append(case.case_id)
                    if not grounded_passed:
                        hard_failure = True
                        failures.append(
                            {
                                "stage": "answer_compose",
                                "status": "failed",
                                "failure_type": (
                                    "unsupported_or_conflicting_scientific_claim"
                                ),
                                "owner": "grounded_answer_audit",
                                "observed": "grounded_answer_audit_rejected",
                            }
                        )
                if hard_failure:
                    citation_hard_failure_case_ids.append(case.case_id)
            elif self.citation_contract is not None:
                observed["citation_evaluation"] = {
                    "evaluator_version": CITATION_EVALUATOR_VERSION,
                    "status": "not_applicable",
                }

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
        if self.citation_contract is not None:
            metrics.extend(
                [
                    _diagnostic_ratio_metric(
                        "citation.exact_chunk_coverage",
                        exact_chunk_covered,
                        len(citation_v2_case_ids),
                        case_ids=citation_v2_case_ids,
                    ),
                    _diagnostic_ratio_metric(
                        "citation.relevant_source_coverage",
                        relevant_source_covered,
                        len(citation_v2_case_ids),
                        case_ids=citation_v2_case_ids,
                    ),
                    _ratio_metric(
                        "citation.supported_claim_coverage",
                        supported_claim_covered,
                        len(citation_v2_case_ids),
                        case_ids=citation_v2_case_ids,
                        threshold=0.90,
                        evaluator_id=CITATION_EVALUATOR_VERSION,
                    ),
                    _ratio_metric(
                        "citation.supported_precision",
                        supported_reference_count,
                        adjudicable_reference_count,
                        case_ids=citation_v2_case_ids,
                        threshold=0.95,
                        evaluator_id=CITATION_EVALUATOR_VERSION,
                    ),
                    _count_metric(
                        "citation.hard_failure_count",
                        len(set(citation_hard_failure_case_ids)),
                        case_ids=citation_v2_case_ids,
                        counted_case_ids=citation_hard_failure_case_ids,
                    ),
                    _ratio_metric(
                        "answer.grounded_claim_pass_rate",
                        sum(grounded_claim_values),
                        len(citation_v2_case_ids),
                        case_ids=citation_v2_case_ids,
                        threshold=1.0,
                        evaluator_id=CITATION_EVALUATOR_VERSION,
                    ),
                ]
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


def _citation_references(
    state: dict[str, Any],
    *,
    audit: dict[str, Any],
) -> list[CitationReference]:
    values: list[CitationReference] = []
    cited_indexes = audit.get("cited_references")
    cited_index_set = (
        {
            int(value)
            for value in cited_indexes
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if isinstance(cited_indexes, list)
        else None
    )
    for row in state.get("references") or []:
        if not isinstance(row, dict):
            continue
        if cited_index_set is not None and row.get("index") not in cited_index_set:
            continue
        evidence_id = row.get("source_span_id") or row.get("chunk_id")
        if not evidence_id:
            continue
        values.append(
            CitationReference(
                evidence_id=str(evidence_id),
                declared_source_id=str(row.get("source_id") or ""),
            )
        )
    return values


def _citation_failure(
    failure_type: str,
    *,
    observed: tuple[str, ...],
) -> dict[str, str]:
    return {
        "stage": "answer_compose",
        "status": "failed",
        "failure_type": failure_type,
        "owner": "citation_evaluator_v2",
        "observed": ",".join(observed),
    }


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
    evaluator_id: str = "unified-conversation-v1",
) -> EvaluatorResult:
    if denominator == 0:
        return EvaluatorResult(
            evaluator_id=evaluator_id,
            metric_id=metric_id,
            status=EvaluationMetricStatus.NOT_APPLICABLE,
            denominator=0,
        )
    value = numerator / denominator
    return EvaluatorResult(
        evaluator_id=evaluator_id,
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


def _count_metric(
    metric_id: str,
    value: int,
    *,
    case_ids: list[str],
    counted_case_ids: list[str] | None = None,
) -> EvaluatorResult:
    denominator = max(1, len(case_ids))
    return EvaluatorResult(
        evaluator_id=CITATION_EVALUATOR_VERSION,
        metric_id=metric_id,
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.PASSED if value == 0 else EvaluationSignal.BLOCKED,
        value=value,
        numerator=value,
        denominator=denominator,
        applicable_case_ids=case_ids,
        threshold=0,
        direction="exact",
        details={"counted_case_ids": sorted(set(counted_case_ids or []))},
    )


def _diagnostic_ratio_metric(
    metric_id: str,
    numerator: int,
    denominator: int,
    *,
    case_ids: list[str],
) -> EvaluatorResult:
    if denominator == 0:
        return EvaluatorResult(
            evaluator_id=CITATION_EVALUATOR_VERSION,
            metric_id=metric_id,
            status=EvaluationMetricStatus.NOT_APPLICABLE,
        )
    return EvaluatorResult(
        evaluator_id=CITATION_EVALUATOR_VERSION,
        metric_id=metric_id,
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.UNKNOWN,
        value=round(numerator / denominator, 6),
        numerator=numerator,
        denominator=denominator,
        applicable_case_ids=case_ids,
        direction="higher",
        details={"release_gate_role": "diagnostic_only"},
    )
