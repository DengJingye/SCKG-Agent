import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import AgentRunEvalMetric, AgentRunEvalReport


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_agent_eval(
    *,
    predictions_path: Path,
    gold_path: Optional[Path] = None,
) -> AgentRunEvalReport:
    predictions = load_jsonl(predictions_path)
    gold_by_id = {record["id"]: record for record in load_jsonl(gold_path)} if gold_path else {}
    per_query = [_score_prediction(prediction, gold_by_id.get(prediction.get("id", ""))) for prediction in predictions]
    query_count = len(per_query)
    metrics = {
        "query_count": _metric(query_count, "number of prediction records"),
        "task_success_rate": _metric(_mean_bool(row["task_success"] for row in per_query), "execution_status == ok"),
        "progress_rate": _metric(_mean(row["progress_score"] for row in per_query), "partial credit across constraints, evidence, workflow/migration, report, audit"),
        "pass_at_1": _metric(_mean_bool(row["task_success"] for row in per_query), "single-run success proxy"),
        "tool_call_accuracy": _metric(_tool_call_accuracy(per_query), "non-failed tool calls divided by tool calls"),
        "trajectory_match_rate": _metric(_mean_bool(row["trajectory_match"] for row in per_query), "observed governed roles cover expected route"),
        "invalid_action_rate": _metric(_mean(row["invalid_action_rate"] for row in per_query), "invalid/repeated actions per tool call"),
        "average_steps": _metric(_mean(row["tool_call_count"] for row in per_query), "mean traced tool calls per query"),
        "mean_latency_ms": _metric(_mean(row["mean_tool_latency_ms"] for row in per_query), "mean tool latency from trace summary"),
        "ttft_ms": _metric(None, "placeholder until streaming telemetry is captured"),
        "token_cost_usd": _metric(None, "placeholder until LLM token accounting is captured"),
        "cost_per_successful_task_usd": _metric(None, "placeholder until token/price telemetry is captured"),
        "high_critical_hallucination_rate": _metric(_high_critical_rate(per_query), "high+critical audit issues divided by audited claims"),
        "unsupported_tool_claim_rate": _metric(_unsupported_tool_rate(per_query), "unsupported tool issues divided by audited claims"),
        "blocked_report_rate": _metric(_mean_bool(row["blocked_by_guardrail"] for row in per_query), "reports vetoed or blocked by guardrail"),
        "recovery_success_rate": _metric(_mean_bool(row["recovery_success"] for row in per_query), "failed tools with non-error final status"),
    }
    return AgentRunEvalReport(
        gold_path=str(gold_path) if gold_path else "",
        prediction_path=str(predictions_path),
        query_count=query_count,
        metrics=metrics,
        per_query=per_query,
    )


def _score_prediction(prediction: Dict[str, Any], gold: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    trace_summary = prediction.get("agent_trace_summary") or {}
    tool_calls = int(prediction.get("tool_call_count") or trace_summary.get("tool_call_count") or 0)
    failed_tool_calls = int(prediction.get("failed_tool_call_count") or trace_summary.get("failed_tool_call_count") or 0)
    invalid_actions = int(prediction.get("invalid_action_count") or trace_summary.get("invalid_action_count") or 0)
    blocked = bool(prediction.get("blocked_by_guardrail") or trace_summary.get("blocked_by_guardrail"))
    status = prediction.get("execution_status") or "partial"
    audit = prediction.get("hallucination_audit") or {}
    severity_counts = audit.get("severity_counts") or {}
    claim_count = int(prediction.get("claim_count") or audit.get("claim_count") or 0)
    roles = trace_summary.get("roles") or []
    expected_type = _normalize_expected_type(gold.get("expected_output_type") if gold else None)
    trajectory_match = _trajectory_match(roles, expected_type)
    progress = _progress_score(prediction, expected_type)
    return {
        "query_id": prediction.get("id") or prediction.get("query_id") or "",
        "execution_status": status,
        "task_success": status == "ok",
        "progress_score": progress,
        "tool_call_count": tool_calls,
        "failed_tool_call_count": failed_tool_calls,
        "tool_call_success_rate": (tool_calls - failed_tool_calls) / tool_calls if tool_calls else None,
        "invalid_action_count": invalid_actions,
        "invalid_action_rate": invalid_actions / tool_calls if tool_calls else 0.0,
        "mean_tool_latency_ms": float(prediction.get("mean_tool_latency_ms") or trace_summary.get("mean_tool_latency_ms") or 0.0),
        "trajectory_match": trajectory_match,
        "roles": ";".join(roles),
        "blocked_by_guardrail": blocked,
        "claim_count": claim_count,
        "high_critical_issue_count": int(severity_counts.get("high", 0)) + int(severity_counts.get("critical", 0)),
        "unsupported_tool_issue_count": len(audit.get("unsupported_tools") or []),
        "recovery_success": failed_tool_calls > 0 and status in {"ok", "partial"},
        "recommendation_type": prediction.get("recommendation_type") or "",
        "expected_output_type": expected_type or "",
    }


def _progress_score(prediction: Dict[str, Any], expected_type: Optional[str]) -> float:
    score = 0.0
    if prediction.get("parsed_constraints"):
        score += 0.2
    if prediction.get("context_pack"):
        score += 0.2
    if prediction.get("final_report"):
        score += 0.2
    if prediction.get("hallucination_audit"):
        score += 0.2
    if expected_type == "workflow":
        score += 0.2 if prediction.get("workflow_steps") or prediction.get("workflow_recommendation") else 0.0
    elif expected_type == "migration":
        score += 0.2 if prediction.get("migration_paths") else 0.0
    elif expected_type in {"ranked_tools", "evidence_chain"}:
        score += 0.2 if prediction.get("recommended_tools") or prediction.get("scored_tools") or expected_type == "evidence_chain" else 0.0
    else:
        score += 0.2 if prediction.get("execution_status") in {"ok", "partial"} else 0.0
    return round(min(score, 1.0), 4)


def _trajectory_match(roles: List[str], expected_type: Optional[str]) -> bool:
    required = {"IntentAgent", "RetrievalAgent", "EvidenceGateAgent", "ReportAgent", "AuditorAgent"}
    if expected_type == "workflow":
        required.add("WorkflowPlannerAgent")
    if expected_type == "migration":
        required.add("MigrationAgent")
    if expected_type in {"ranked_tools", "workflow", "evidence_chain"}:
        required.add("RankingAgent")
    return required.issubset(set(roles))


def _normalize_expected_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value == "migration_hypothesis":
        return "migration"
    return value


def _tool_call_accuracy(rows: List[Dict[str, Any]]) -> Optional[float]:
    calls = sum(int(row["tool_call_count"]) for row in rows)
    if calls == 0:
        return None
    failed = sum(int(row["failed_tool_call_count"]) for row in rows)
    return (calls - failed) / calls


def _high_critical_rate(rows: List[Dict[str, Any]]) -> float:
    claims = sum(int(row["claim_count"]) for row in rows)
    if claims == 0:
        return 0.0
    issues = sum(int(row["high_critical_issue_count"]) for row in rows)
    return issues / claims


def _unsupported_tool_rate(rows: List[Dict[str, Any]]) -> float:
    claims = sum(int(row["claim_count"]) for row in rows)
    if claims == 0:
        return 0.0
    issues = sum(int(row["unsupported_tool_issue_count"]) for row in rows)
    return issues / claims


def _mean(values: Any) -> Optional[float]:
    items = [value for value in values if value is not None]
    if not items:
        return None
    return sum(float(value) for value in items) / len(items)


def _mean_bool(values: Any) -> Optional[float]:
    items = list(values)
    if not items:
        return None
    return sum(1 for value in items if value) / len(items)


def _metric(value: Optional[float], reason: str) -> AgentRunEvalMetric:
    return AgentRunEvalMetric(
        name="",
        value=round(float(value), 6) if value is not None else None,
        status="ok" if value is not None else "not_available",
        reason=reason,
    )


def write_outputs(report: AgentRunEvalReport, json_path: Path, tsv_path: Path, per_query_path: Path) -> None:
    payload = report.model_dump(mode="json")
    for name, metric in payload["metrics"].items():
        metric["name"] = name
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "status", "reason"], delimiter="\t")
        writer.writeheader()
        for name, metric in payload["metrics"].items():
            writer.writerow(
                {
                    "metric": name,
                    "value": "" if metric["value"] is None else metric["value"],
                    "status": metric["status"],
                    "reason": metric["reason"],
                }
            )
    fieldnames = sorted({key for row in payload["per_query"] for key in row})
    with per_query_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in payload["per_query"]:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate production-style AgentRun traces from prediction JSONL.")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=Path("eval/agent_run_eval_summary.json"))
    parser.add_argument("--output", type=Path, default=Path("eval/agent_run_eval_summary.tsv"))
    parser.add_argument("--per-query-output", type=Path, default=Path("eval/agent_run_eval_per_query.tsv"))
    args = parser.parse_args()

    report = run_agent_eval(predictions_path=args.predictions, gold_path=args.gold)
    write_outputs(report, args.json_output, args.output, args.per_query_output)
    print(f"agent_run_eval_summary={args.output}")
    print(f"agent_run_eval_summary_json={args.json_output}")
    print(f"agent_run_eval_per_query={args.per_query_output}")
    for name, metric in report.metrics.items():
        print(f"{name}={metric.value} ({metric.status})")


if __name__ == "__main__":
    main()
