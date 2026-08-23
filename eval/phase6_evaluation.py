from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


TRACE_STAGES = (
    "profile",
    "plan",
    "authorization",
    "approval",
    "execution",
    "validation",
    "repair_or_stop",
    "decision",
    "package",
    "audit",
)

BASELINE_FIELDS = (
    "track",
    "baseline_id",
    "case_id",
    "status",
    "reason",
    "tool_workflow_recall",
    "parameter_legality",
    "source_coverage",
    "io_compatibility",
    "unsupported_claim",
    "blocking_correctness",
    "latency_seconds",
    "task_executable_completion",
    "artifact_completeness",
    "failure_detection",
    "repair_success",
    "runtime_seconds",
    "run_count",
    "reproducibility_level",
    "unsafe_action",
)

FAILURE_QUEUE_FIELDS = (
    "case_id",
    "run_id",
    "tool",
    "terminal_status",
    "error_type",
    "repairable",
    "repair_result",
    "blocking_reason",
    "artifact_log_reference",
    "owner_redacted",
    "created_at",
)


def audit_case_trace(
    *,
    case_id: str,
    applicable_stages: Sequence[str],
    observed_stages: Iterable[dict[str, Any]],
    unauthorized_execution_count: int = 0,
    path_escape_count: int = 0,
    repair_budget_violation_count: int = 0,
    evidence_boundary_violation_count: int = 0,
) -> dict[str, Any]:
    applicable = list(dict.fromkeys(applicable_stages))
    unknown = sorted(set(applicable) - set(TRACE_STAGES))
    if unknown:
        raise ValueError(f"unknown trace stages: {unknown}")
    observed = {str(row.get("stage")): row for row in observed_stages}
    missing = [stage for stage in applicable if stage not in observed]
    completeness = (len(applicable) - len(missing)) / max(len(applicable), 1)
    violations = {
        "unauthorized_execution": unauthorized_execution_count,
        "path_escape": path_escape_count,
        "repair_budget_violation": repair_budget_violation_count,
        "evidence_boundary_violation": evidence_boundary_violation_count,
    }
    return {
        "case_id": case_id,
        "applicable_stages": applicable,
        "observed_stages": [observed[stage] for stage in applicable if stage in observed],
        "missing_stages": missing,
        "applicable_stage_completeness": round(completeness, 6),
        "violations": violations,
        "passed": completeness == 1.0 and all(value == 0 for value in violations.values()),
    }


def build_failure_queue(
    *,
    case_id: str,
    runs: Sequence[Any],
    validations: Sequence[Any],
    repair_actions: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    validation_by_run = {item.run_id: item for item in validations}
    action_by_parent = {item.parent_run_id: item for item in repair_actions}
    rows: list[dict[str, Any]] = []
    for run in runs:
        validation = validation_by_run.get(run.run_id)
        failed = run.status not in {"succeeded"} or validation is None or not validation.passed
        if not failed:
            continue
        action = action_by_parent.get(run.run_id)
        failures = list(validation.failures) if validation is not None else []
        references = sorted(
            {
                Path(path).name
                for path in [run.stdout_path, run.stderr_path, *run.artifact_paths.values()]
                if path
            }
        )
        rows.append(
            {
                "case_id": case_id,
                "run_id": run.run_id,
                "tool": f"{run.tool_name} {run.tool_version}",
                "terminal_status": run.status,
                "error_type": run.error_type or (failures[0] if failures else "validation_failed"),
                "repairable": bool(validation and validation.repairable),
                "repair_result": (
                    f"rerun:{action.new_run_id}" if action is not None else "not_repaired"
                ),
                "blocking_reason": ";".join(failures) or run.error_message or "",
                "artifact_log_reference": ";".join(references),
                "owner_redacted": "participant" if run.owner_user_id else "maintainer",
                "created_at": run.end_time.isoformat(),
            }
        )
    return rows


def summarize_baselines(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_baseline: dict[str, dict[str, Any]] = {}
    for baseline_id in sorted({row["baseline_id"] for row in rows}):
        selected = [row for row in rows if row["baseline_id"] == baseline_id]
        statuses = sorted({row["status"] for row in selected})
        by_baseline[baseline_id] = {
            "track": selected[0]["track"],
            "status": statuses[0] if len(statuses) == 1 else "mixed",
            "case_count": len(selected),
            "reasons": sorted({row["reason"] for row in selected if row.get("reason")}),
            "metrics": _numeric_means(selected),
        }
    return {
        "schema_version": "phase6-baseline-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baselines": by_baseline,
        "safety": {
            "external_llm_or_api_calls": 0,
            "new_or_untrusted_generated_code_executions": 0,
            "unsafe_action_count": sum(int(row.get("unsafe_action") or 0) for row in rows),
        },
        "guardrail": "not_run and not_run_safety_boundary are first-class results; missing scores are never imputed.",
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_tsv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _one_line(row.get(field)) for field in fields})


def _numeric_means(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    output: dict[str, float] = {}
    for field in BASELINE_FIELDS:
        values = [row[field] for row in rows if isinstance(row.get(field), (int, float))]
        if values:
            output[field] = round(sum(float(value) for value in values) / len(values), 6)
    return output


def _one_line(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return " ".join(str(value).split())
