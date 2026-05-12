import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constraints import parse_research_constraints
from core.evidence_policy import (
    RECOMMENDATION_EVIDENCE_METRICS,
    is_main_benchmark_evidence,
    is_main_publication_evidence,
)
from core.models import Evidence


DEFAULT_FIELDS = [
    "task",
    "modality",
    "platform",
    "data_object",
    "scale",
    "noise",
    "species",
    "output_goal",
    "strictness",
]


OUTPUT_TYPE_ALIASES = {
    "migration_hypothesis": "migration",
}


class MetricResult(BaseModel):
    name: str
    value: float | None = None
    status: str = "ok"
    reason: str = ""


class EvalPrediction(BaseModel):
    id: str
    query_id: str | None = None
    parsed_constraints: Dict[str, Any] = Field(default_factory=dict)
    recommendation_type: str | None = None
    recommendation_kind: str | None = None
    recommended_tools: List[str] = Field(default_factory=list)
    candidate_tools: List[Dict[str, Any]] = Field(default_factory=list)
    scored_tools: List[Dict[str, Any]] = Field(default_factory=list)
    migration_paths: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_bundle: Dict[str, Any] = Field(default_factory=dict)
    evidence_coverage: float | None = None
    workflow_steps: List[str] = Field(default_factory=list)
    workflow_recommendation: Dict[str, Any] | None = None
    final_report: str = ""
    missing_components: List[str] = Field(default_factory=list)
    clarification_needed: bool | None = None
    execution_status: str | None = None
    unsupported_claims: int = 0
    claim_count: int = 0
    semantic_hallucination_rate: float | None = None
    hallucination_audit: Dict[str, Any] = Field(default_factory=dict)


class EvalReport(BaseModel):
    mode: str
    gold_path: str
    prediction_path: str | None = None
    query_count: int
    metrics: Dict[str, MetricResult]
    per_query: List[Dict[str, Any]]


def load_gold_queries(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_predictions(path: Path | None) -> Dict[str, EvalPrediction]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        predictions = [
            EvalPrediction.model_validate(json.loads(line))
            for line in handle
            if line.strip()
        ]
    return {prediction.id: prediction for prediction in predictions}


def normalize_expected_output_type(value: str | None) -> str | None:
    if not value:
        return None
    return OUTPUT_TYPE_ALIASES.get(value, value)


def score_constraint_fields(
    predicted: Dict[str, Any],
    expected: Dict[str, Any],
    fields: Iterable[str],
) -> Dict[str, Any]:
    field_results = {}
    correct = 0
    total = 0

    for field in fields:
        total += 1
        pred_value = predicted.get(field)
        exp_value = expected.get(field)
        is_correct = pred_value == exp_value
        correct += int(is_correct)
        field_results[field] = {
            "predicted": pred_value,
            "expected": exp_value,
            "correct": is_correct,
        }

    return {
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total else 0.0,
        "fields": field_results,
    }


def run_constraint_eval(gold_path: Path, prediction_path: Path | None = None) -> EvalReport:
    records = load_gold_queries(gold_path)
    predictions = load_predictions(prediction_path)
    per_query = []
    total_correct = 0
    total_fields = 0
    clarification_flags = 0
    recommendation_type_hits = []
    top_k_hits = []
    forbidden_tool_violations = []
    evidence_coverages = []
    workflow_completeness_scores = []
    unsupported_claims = 0
    claim_count = 0
    semantic_claim_count = 0
    semantic_issue_count = 0
    semantic_eval_count = 0
    semantic_pass_count = 0
    semantic_critical_count = 0
    semantic_high_count = 0
    blocked_report_count = 0
    unsupported_tool_issue_count = 0
    recommendation_evidence_coverages = []
    main_tool_recommendation_evidence_coverages = []
    main_tool_publication_evidence_coverages = []
    main_tool_benchmark_evidence_coverages = []
    experimental_evidence_rates = []
    field_error_counts = {field: 0 for field in DEFAULT_FIELDS}
    field_totals = {field: 0 for field in DEFAULT_FIELDS}
    clarification_state_counts: Dict[str, int] = {}
    execution_status_counts: Dict[str, int] = {}
    retrieval_error_counts = {
        "empty_candidate_set": 0,
        "empty_scored_tools": 0,
        "empty_evidence_bundle": 0,
        "empty_workflow_for_workflow_query": 0,
        "empty_migration_for_migration_query": 0,
    }

    for record in records:
        prediction = predictions.get(record["id"])
        if prediction and prediction.parsed_constraints:
            predicted = prediction.parsed_constraints
            predicted_model = parse_research_constraints(predicted, record["query"])
        else:
            predicted_model = parse_research_constraints({}, record["query"])
            predicted = predicted_model.model_dump()
        expected = record["expected_constraints"]
        scored = score_constraint_fields(predicted, expected, DEFAULT_FIELDS)
        total_correct += scored["correct"]
        total_fields += scored["total"]
        for field, result in scored["fields"].items():
            field_totals[field] += 1
            field_error_counts[field] += int(not result["correct"])
        clarification_needed = (
            prediction.clarification_needed
            if prediction and prediction.clarification_needed is not None
            else predicted_model.needs_human_clarification
        )
        clarification_flags += int(clarification_needed)
        clarification_state = predicted.get("clarification_state", predicted_model.clarification_state)
        clarification_state_counts[clarification_state] = clarification_state_counts.get(clarification_state, 0) + 1
        query_eval = {
            "id": record["id"],
            "accuracy": scored["accuracy"],
            "valid_constraint_count": predicted.get("valid_constraint_count", predicted_model.valid_constraint_count),
            "needs_human_clarification": clarification_needed,
            "clarification_state": clarification_state,
            "field_results": scored["fields"],
        }

        if prediction:
            if prediction.execution_status:
                execution_status_counts[prediction.execution_status] = (
                    execution_status_counts.get(prediction.execution_status, 0) + 1
                )
            raw_expected_output_type = record.get("expected_output_type")
            expected_output_type = normalize_expected_output_type(raw_expected_output_type)
            if expected_output_type:
                predicted_kind = prediction.recommendation_type or prediction.recommendation_kind
                recommendation_type_hits.append(
                    int(predicted_kind == expected_output_type)
                )
                query_eval["recommendation_type_hit"] = (
                    predicted_kind == expected_output_type
                )
                query_eval["expected_output_type"] = raw_expected_output_type
                query_eval["normalized_expected_output_type"] = expected_output_type

            expected_tools = record.get("expected_tools", [])
            if expected_tools:
                hit = any(tool in prediction.recommended_tools[:3] for tool in expected_tools)
                top_k_hits.append(int(hit))
                query_eval["top_k_hit"] = hit
            forbidden_tools = record.get("forbidden_tools", [])
            if forbidden_tools:
                violation = _has_forbidden_tool(prediction.recommended_tools[:10], forbidden_tools)
                forbidden_tool_violations.append(int(violation))
                query_eval["forbidden_tool_violation"] = violation

            if prediction.evidence_coverage is not None:
                evidence_coverages.append(prediction.evidence_coverage)
                query_eval["evidence_coverage"] = prediction.evidence_coverage
                rec_coverage, experimental_rate = _evidence_quality_metrics(prediction)
                recommendation_evidence_coverages.append(rec_coverage)
                experimental_evidence_rates.append(experimental_rate)
                query_eval["recommendation_evidence_coverage"] = rec_coverage
                query_eval["experimental_evidence_rate"] = experimental_rate
                main_tool_metrics = _main_tool_recommendation_evidence_metrics(prediction)
                main_tool_recommendation_evidence_coverages.append(
                    main_tool_metrics["main_tool_recommendation_evidence_coverage"]
                )
                main_tool_publication_evidence_coverages.append(
                    main_tool_metrics["main_tool_publication_evidence_coverage"]
                )
                main_tool_benchmark_evidence_coverages.append(
                    main_tool_metrics["main_tool_benchmark_evidence_coverage"]
                )
                query_eval.update(main_tool_metrics)

            if expected_output_type == "workflow":
                complete = _workflow_completeness(prediction)
                workflow_completeness_scores.append(complete)
                query_eval["workflow_completeness"] = complete
            _update_retrieval_errors(
                counters=retrieval_error_counts,
                prediction=prediction,
                expected_output_type=expected_output_type,
            )
            blocked_report = _is_blocked_report(prediction)
            blocked_report_count += int(blocked_report)
            query_eval["blocked_report"] = blocked_report

            unsupported_claims += prediction.unsupported_claims
            claim_count += prediction.claim_count
            audit_payload = prediction.hallucination_audit or {}
            if audit_payload:
                issues = audit_payload.get("issues", [])
                severity_counts = audit_payload.get("severity_counts") or _count_audit_severities(issues)
                semantic_eval_count += 1
                semantic_pass_count += int(bool(audit_payload.get("passed")))
                semantic_claim_count += int(audit_payload.get("claim_count") or prediction.claim_count)
                semantic_issue_count += len(issues)
                semantic_critical_count += int(severity_counts.get("critical", 0))
                semantic_high_count += int(severity_counts.get("high", 0))
                unsupported_tool_issue_count += len(
                    [
                        issue for issue in issues
                        if issue.get("issue_type") == "unsupported_tool_claim"
                    ]
                )
                query_eval["semantic_hallucination_rate"] = audit_payload.get(
                    "hallucination_rate",
                    prediction.semantic_hallucination_rate,
                )
                query_eval["semantic_issue_count"] = len(issues)
                query_eval["semantic_critical_issues"] = int(severity_counts.get("critical", 0))
                query_eval["semantic_high_issues"] = int(severity_counts.get("high", 0))

        per_query.append({
            **query_eval,
        })

    has_predictions = bool(predictions)
    metrics = {
        "constraint_parse_accuracy": MetricResult(
            name="constraint_parse_accuracy",
            value=total_correct / total_fields if total_fields else 0.0,
        ),
        "needs_human_clarification_rate": MetricResult(
            name="needs_human_clarification_rate",
            value=clarification_flags / len(records) if records else 0.0,
        ),
        "recommendation_type_accuracy": _mean_metric(
            "recommendation_type_accuracy",
            recommendation_type_hits,
            has_predictions,
            "requires predictions with recommendation_kind",
        ),
        "top_k_hit": _mean_metric(
            "top_k_hit",
            top_k_hits,
            has_predictions,
            "requires predictions and gold expected_tools",
        ),
        "forbidden_tool_violation_rate": _mean_metric(
            "forbidden_tool_violation_rate",
            forbidden_tool_violations,
            has_predictions,
            "requires predictions and gold forbidden_tools",
        ),
        "evidence_coverage": _mean_metric(
            "evidence_coverage",
            evidence_coverages,
            has_predictions,
            "requires predictions with evidence_coverage",
        ),
        "recommendation_evidence_coverage": _mean_metric(
            "recommendation_evidence_coverage",
            recommendation_evidence_coverages,
            has_predictions,
            "requires predictions with evidence_bundle",
        ),
        "main_tool_recommendation_evidence_coverage": _mean_metric(
            "main_tool_recommendation_evidence_coverage",
            main_tool_recommendation_evidence_coverages,
            has_predictions,
            "requires predictions with scored_tools evidence",
        ),
        "main_tool_publication_evidence_coverage": _mean_metric(
            "main_tool_publication_evidence_coverage",
            main_tool_publication_evidence_coverages,
            has_predictions,
            "requires predictions with scored_tools evidence",
        ),
        "main_tool_benchmark_evidence_coverage": _mean_metric(
            "main_tool_benchmark_evidence_coverage",
            main_tool_benchmark_evidence_coverages,
            has_predictions,
            "requires predictions with scored_tools evidence",
        ),
        "experimental_evidence_rate": _mean_metric(
            "experimental_evidence_rate",
            experimental_evidence_rates,
            has_predictions,
            "requires predictions with evidence_bundle",
        ),
        "workflow_completeness": _mean_metric(
            "workflow_completeness",
            workflow_completeness_scores,
            has_predictions,
            "requires workflow predictions with workflow_steps",
        ),
        "hallucination_rate": MetricResult(
            name="hallucination_rate",
            value=(unsupported_claims / claim_count if claim_count else None),
            status=("ok" if claim_count else "not_run"),
            reason="" if claim_count else "requires predictions with claim_count and unsupported_claims",
        ),
        "semantic_hallucination_issue_rate": MetricResult(
            name="semantic_hallucination_issue_rate",
            value=(semantic_issue_count / semantic_claim_count if semantic_claim_count else None),
            status=("ok" if semantic_claim_count else "not_run"),
            reason="" if semantic_claim_count else "requires predictions with hallucination_audit",
        ),
        "critical_hallucination_rate": MetricResult(
            name="critical_hallucination_rate",
            value=(semantic_critical_count / semantic_claim_count if semantic_claim_count else None),
            status=("ok" if semantic_claim_count else "not_run"),
            reason="" if semantic_claim_count else "requires predictions with hallucination_audit",
        ),
        "high_hallucination_rate": MetricResult(
            name="high_hallucination_rate",
            value=(semantic_high_count / semantic_claim_count if semantic_claim_count else None),
            status=("ok" if semantic_claim_count else "not_run"),
            reason="" if semantic_claim_count else "requires predictions with hallucination_audit",
        ),
        "unsupported_tool_claim_rate": MetricResult(
            name="unsupported_tool_claim_rate",
            value=(unsupported_tool_issue_count / semantic_claim_count if semantic_claim_count else None),
            status=("ok" if semantic_claim_count else "not_run"),
            reason="" if semantic_claim_count else "requires predictions with hallucination_audit",
        ),
        "semantic_audit_pass_rate": MetricResult(
            name="semantic_audit_pass_rate",
            value=(semantic_pass_count / semantic_eval_count if semantic_eval_count else None),
            status=("ok" if semantic_eval_count else "not_run"),
            reason="" if semantic_eval_count else "requires predictions with hallucination_audit",
        ),
        "blocked_report_rate": MetricResult(
            name="blocked_report_rate",
            value=(blocked_report_count / len(records) if has_predictions and records else None),
            status="ok" if has_predictions else "not_run",
            reason="" if has_predictions else "requires --predictions JSONL",
        ),
        "partial_resolved_rate": MetricResult(
            name="partial_resolved_rate",
            value=(
                clarification_state_counts.get("partial_resolved", 0) / len(records)
                if records else 0.0
            ),
        ),
        "resolved_rate": MetricResult(
            name="resolved_rate",
            value=(
                clarification_state_counts.get("resolved", 0) / len(records)
                if records else 0.0
            ),
        ),
        "needs_clarification_state_rate": MetricResult(
            name="needs_clarification_state_rate",
            value=(
                clarification_state_counts.get("needs_clarification", 0) / len(records)
                if records else 0.0
            ),
        ),
    }
    for field in DEFAULT_FIELDS:
        total = field_totals[field]
        errors = field_error_counts[field]
        metrics[f"constraint_error_{field}"] = MetricResult(
            name=f"constraint_error_{field}",
            value=errors / total if total else 0.0,
        )
    for name, count in retrieval_error_counts.items():
        metrics[name] = MetricResult(
            name=name,
            value=count / len(records) if records else 0.0,
            status="ok" if has_predictions else "not_run",
            reason="" if has_predictions else "requires --predictions JSONL",
        )

    return EvalReport(
        mode="offline_regression_eval",
        gold_path=str(gold_path),
        prediction_path=str(prediction_path) if prediction_path else None,
        query_count=len(records),
        metrics=metrics,
        per_query=per_query,
    )


def _workflow_completeness(prediction: EvalPrediction) -> float:
    if prediction.workflow_steps:
        return 1.0
    workflow = prediction.workflow_recommendation or {}
    steps = workflow.get("steps") if isinstance(workflow, dict) else None
    if steps:
        return 1.0
    return 0.0


def _count_audit_severities(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for issue in issues:
        severity = issue.get("severity")
        if severity:
            counts[severity] = counts.get(severity, 0) + 1
    return counts


def _is_blocked_report(prediction: EvalPrediction) -> bool:
    report_text = (prediction.final_report or "").lower()
    if "blocked_by_semantic_auditor" in report_text:
        return True
    if "blocked_by: semantic_auditor" in report_text:
        return True
    if "report_status: blocked" in report_text:
        return True
    audit_payload = prediction.hallucination_audit or {}
    if str(audit_payload.get("report_status", "")).lower() == "blocked_by_semantic_auditor":
        return True
    if str(audit_payload.get("blocked_by", "")).lower() == "semantic_auditor":
        return True
    return False


def _has_forbidden_tool(recommended_tools: List[str], forbidden_tools: List[str]) -> bool:
    recommended = {_tool_key(tool) for tool in recommended_tools}
    forbidden = {_tool_key(tool) for tool in forbidden_tools}
    return bool(recommended & forbidden)


def _tool_key(tool_name: str) -> str:
    return "".join(ch for ch in (tool_name or "").lower() if ch.isalnum())


def _evidence_quality_metrics(prediction: EvalPrediction) -> tuple[float, float]:
    bundle = prediction.evidence_bundle or {}
    items = bundle.get("items", [])
    missing = bundle.get("missing_evidence", [])
    total = len(items) + len(missing)
    if total == 0:
        return 0.0, 0.0
    recommendation_grade = [
        item for item in items
        if item.get("trust_level") in {"verified", "source_based"}
        and item.get("graph_layer") in {"trusted_core", "review_needed"}
        and item.get("review_status") != "rejected"
        and "recommendation" in item.get("use_for", [])
        and item.get("metric_name") in RECOMMENDATION_EVIDENCE_METRICS
    ]
    experimental = [
        item for item in items
        if item.get("graph_layer") == "experimental"
        or item.get("trust_level") in {"model_extracted", "inferred"}
    ]
    return len(recommendation_grade) / total, len(experimental) / max(len(items), 1)


def _main_tool_recommendation_evidence_metrics(
    prediction: EvalPrediction,
    top_k: int = 3,
) -> Dict[str, float]:
    """Measure trusted paper/benchmark support for visible primary recommendations.

    The older recommendation_evidence_coverage metric intentionally looks at the
    whole evidence bundle, including workflow gaps and retrieval/ranking traces.
    This metric is narrower: each top-k scored tool gets one publication slot
    and one benchmark slot. It answers whether the tools being shown to the user
    have the two evidence types expected for recommendation-grade claims.
    """
    scored_tools = sorted(
        prediction.scored_tools or [],
        key=lambda item: _safe_rank(item.get("rank")),
    )[:top_k]
    if not scored_tools:
        return {
            "main_tool_recommendation_evidence_coverage": 0.0,
            "main_tool_publication_evidence_coverage": 0.0,
            "main_tool_benchmark_evidence_coverage": 0.0,
        }

    publication_hits = 0
    benchmark_hits = 0
    for tool in scored_tools:
        evidence = tool.get("evidence") or {}
        items = evidence.get("items") or []
        publication_hits += int(any(_is_main_publication_evidence(item) for item in items))
        benchmark_hits += int(any(_is_main_benchmark_evidence(item) for item in items))

    denominator = len(scored_tools)
    publication_coverage = publication_hits / denominator
    benchmark_coverage = benchmark_hits / denominator
    return {
        "main_tool_recommendation_evidence_coverage": (
            (publication_hits + benchmark_hits) / (2 * denominator)
        ),
        "main_tool_publication_evidence_coverage": publication_coverage,
        "main_tool_benchmark_evidence_coverage": benchmark_coverage,
    }


def _safe_rank(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10_000


def _is_main_publication_evidence(item: Dict[str, Any]) -> bool:
    evidence = _evidence_from_dict(item)
    if evidence is None:
        return False
    return is_main_publication_evidence(evidence)


def _is_main_benchmark_evidence(item: Dict[str, Any]) -> bool:
    evidence = _evidence_from_dict(item)
    if evidence is None:
        return False
    return is_main_benchmark_evidence(evidence)


def _is_recommendation_grade_item(item: Dict[str, Any]) -> bool:
    if item.get("recommendation_eligible") is False:
        return False
    return (
        item.get("trust_level") in {"verified", "source_based"}
        and item.get("graph_layer") == "trusted_core"
        and item.get("review_status") != "rejected"
        and "recommendation" in (item.get("use_for") or [])
        and item.get("metric_name") in RECOMMENDATION_EVIDENCE_METRICS
    )


def _evidence_from_dict(item: Dict[str, Any]) -> Evidence | None:
    try:
        return Evidence.model_validate(item)
    except Exception:
        return None


def _update_retrieval_errors(
    counters: Dict[str, int],
    prediction: EvalPrediction,
    expected_output_type: str | None,
) -> None:
    if not prediction.candidate_tools:
        counters["empty_candidate_set"] += 1
    if not prediction.scored_tools and expected_output_type == "ranked_tools":
        counters["empty_scored_tools"] += 1
    evidence_items = prediction.evidence_bundle.get("items", [])
    if not evidence_items:
        counters["empty_evidence_bundle"] += 1
    if expected_output_type == "workflow" and not prediction.workflow_steps:
        counters["empty_workflow_for_workflow_query"] += 1
    if expected_output_type == "migration" and not prediction.migration_paths:
        counters["empty_migration_for_migration_query"] += 1


def _mean_metric(
    name: str,
    values: List[float],
    has_predictions: bool,
    missing_reason: str,
) -> MetricResult:
    if values:
        return MetricResult(name=name, value=sum(values) / len(values))
    return MetricResult(
        name=name,
        value=None,
        status="not_run",
        reason=missing_reason if has_predictions else "requires --predictions JSONL",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scKG-Atlas offline evals.")
    parser.add_argument(
        "--gold",
        type=Path,
        default=PROJECT_ROOT / "eval" / "gold_queries.jsonl",
        help="Path to gold query JSONL file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON result instead of concise summary.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Optional prediction JSONL file for retrieval/report metrics.",
    )
    args = parser.parse_args()

    result = run_constraint_eval(args.gold, args.predictions)
    if args.json:
        print(result.model_dump_json(indent=2))
        return

    print("scKG-Atlas offline eval")
    print(f"gold queries: {result.query_count}")
    for metric in result.metrics.values():
        if metric.value is None:
            print(f"{metric.name}: {metric.status} ({metric.reason})")
        else:
            print(f"{metric.name}: {metric.value:.3f}")


if __name__ == "__main__":
    main()
