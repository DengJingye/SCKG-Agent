from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from eval.phase6_evaluation import audit_case_trace, build_failure_queue, summarize_baselines


def test_trace_audit_requires_all_applicable_stages_and_zero_violations():
    result = audit_case_trace(
        case_id="blocked",
        applicable_stages=["profile", "plan", "authorization", "approval", "audit"],
        observed_stages=[
            {"stage": "profile"},
            {"stage": "plan"},
            {"stage": "authorization"},
            {"stage": "approval", "status": "blocked"},
            {"stage": "audit"},
        ],
    )
    assert result["applicable_stage_completeness"] == 1.0
    assert result["passed"] is True


def test_failure_queue_is_owner_and_path_redacted():
    validation = SimpleNamespace(
        run_id="run-1", passed=False, failures=["invalid_n_prin_comps"], repairable=True
    )
    run = SimpleNamespace(
        run_id="run-1",
        tool_name="Scrublet",
        tool_version="0.2.3",
        status="failed",
        error_type="wrapper_exit_nonzero",
        error_message="failed",
        stdout_path="/private/path/stdout.log",
        stderr_path="/private/path/stderr.log",
        artifact_paths={"partial": "/private/path/result.json"},
        owner_user_id="secret-user",
        end_time=datetime.now(timezone.utc),
    )
    rows = build_failure_queue(case_id="case", runs=[run], validations=[validation])
    assert rows[0]["owner_redacted"] == "participant"
    assert "/private/path" not in rows[0]["artifact_log_reference"]
    assert rows[0]["repairable"] is True


def test_not_run_is_preserved_without_imputed_metrics():
    summary = summarize_baselines(
        [
            {
                "track": "A",
                "baseline_id": "A1_llm_only",
                "case_id": "not_applicable",
                "status": "not_run",
                "reason": "no frozen artifact",
                "unsafe_action": 0,
            }
        ]
    )
    baseline = summary["baselines"]["A1_llm_only"]
    assert baseline["status"] == "not_run"
    assert "tool_workflow_recall" not in baseline["metrics"]
    assert summary["safety"]["external_llm_or_api_calls"] == 0
