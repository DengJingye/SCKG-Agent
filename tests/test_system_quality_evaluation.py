from __future__ import annotations

import json

from core.system_evaluation_models import EvaluationCommandResult
from eval.system_quality_evaluation import (
    _last_json_object,
    _sanitize,
    build_system_quality_report,
)


def _payloads(*, unauthorized=0, participants=0):
    tool = {
        "actual_runs": 2,
        "successful_runs": 2,
        "validation_passed": True,
        "candidate_evaluation_count": 1,
        "eligible_candidate_count": 1,
        "runtime_seconds_total": 1.2,
        "peak_memory_mb_max": 64.0,
        "package_complete": True,
        "manifest_hashes_valid": True,
    }
    return {
        "agent_quality": {
            "summary": {
                "task_completion_rate": 1.0,
                "tool_correctness": 1.0,
                "hallucination_rate": 0.0,
                "compliance_pass_rate": 1.0,
                "latency_p50_ms": 10.0,
                "latency_p95_ms": 20.0,
                "failure_domain_counts": {},
                "release_gate_passed": True,
            }
        },
        "retrieval_quality": {
            "case_count": 96,
            "profiles": {
                "kg_bm25": {
                    "status": "passed",
                    "recall_at_10": 0.93,
                    "precision_at_10": 0.89,
                    "mrr": 0.98,
                    "source_span_hit_rate": 0.98,
                    "false_support_rate": 0.0,
                    "parameter_legality_rate": 1.0,
                    "governance_leakage_count": 0,
                    "latency_p50_ms": 8.0,
                    "latency_p95_ms": 25.0,
                    "ragas_status": "not_run",
                },
                "dense": {"status": "not_run"},
                "kg_hybrid": {"status": "not_run"},
                "kg_hybrid_tool_contract": {"status": "not_run"},
            },
        },
        "phase6_baselines": {
            "safety": {"new_or_untrusted_generated_code_executions": 0}
        },
        "baseline_details": {
            "expected_failure_count": 2,
            "captured_failure_count": 2,
        },
        "authorization": {
            "checks": {
                "parameter_change_invalidates_approval": True,
                "cross_user_artifact_blocked": True,
                "cross_user_run_blocked": True,
                "execution_request_count_zero": True,
            }
        },
        "restricted_execution": {
            "checks": {
                "approval_replay_blocked": True,
                "parameter_change_blocked": True,
                "cross_user_package_blocked": True,
                "global_policy_default_disabled": True,
                "input_data_not_copied": True,
                "input_unchanged": True,
            },
            "scrublet": tool,
            "scdblfinder": tool,
            "replay_blocked": True,
            "parameter_change_blocked": True,
            "cancellation_passed": True,
            "input_data_copied": False,
        },
        "ui_service": {"ok": True, "checks": {"redaction": True}},
        "defense_demo": {
            "success_case": True,
            "repair_case": True,
            "blocked_case": True,
        },
        "defense_details": {
            "success_case": {
                "execution_request_count": 2,
                "package_complete": True,
            },
            "repair_case": {"lineage_complete": True, "package_complete": True},
            "blocked_case": {"route": "BLOCKED", "execution_request_count": 0},
            "trace_audit": {
                "applicable_stage_completeness": 1.0,
                "violations": {
                    "unauthorized_execution": unauthorized,
                    "path_escape": 0,
                    "repair_budget_violation": 0,
                    "evidence_boundary_violation": 0,
                },
            },
        },
        "group_trial": {
            "participant_count": participants,
            "level_1_participant_count": participants,
            "level_2_participant_count": 1 if participants >= 3 else 0,
            "level_1_completion_rate": 1.0 if participants >= 3 else 0.0,
            "help_rate": 0.0,
            "median_time_seconds": None,
            "usefulness_median": None,
        },
        "portfolio": {
            "a4_not_worse_than_a3": True,
            "completed_model_calls": 48,
            "baselines": [
                {
                    "baseline_id": "A4_kg_rag_tool_contract",
                    "hard_gate_passed": True,
                }
            ],
        },
    }


def _commands():
    return [
        EvaluationCommandResult(command_id=name, status="passed", exit_code=0)
        for name in (
            "agent_quality",
            "retrieval_quality",
            "phase6_baselines",
            "authorization",
            "restricted_execution",
            "ui_service",
            "defense_demo",
            "group_trial",
        )
    ]


def test_system_quality_gate_distinguishes_engineering_from_real_trial():
    report = build_system_quality_report(
        evaluation_id="system-quality-test",
        payloads=_payloads(participants=0),
        command_results=_commands(),
    )

    assert report.engineering_gate_passed is True
    assert report.phase6_complete_eligible is False
    assert report.recommended_status == "PHASE6_TRIAL_READY"
    assert len(report.scenarios) == 6
    assert all(item.passed for item in report.scenarios)
    usability = next(item for item in report.dimensions if item.dimension == "usability")
    assert usability.status == "partial"
    assert usability.metrics["human_trial_status"] == "not_run"


def test_safety_violation_blocks_system_quality_gate():
    report = build_system_quality_report(
        evaluation_id="system-quality-unsafe",
        payloads=_payloads(unauthorized=1, participants=3),
        command_results=_commands(),
    )

    assert report.engineering_gate_passed is False
    assert report.recommended_status == "PHASE6_BLOCKED"
    safety = next(
        item for item in report.dimensions if item.dimension == "safety_and_isolation"
    )
    assert safety.status == "failed"
    assert safety.metrics["unauthorized_execution_count"] == 1


def test_frozen_baseline_comparison_detects_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "capability_summary": {
                    "task_completion_rate": 1.0,
                    "tool_correctness": 1.0,
                    "hallucination_rate": 0.0,
                    "compliance_pass_rate": 1.0,
                }
            }
        ),
        encoding="utf-8",
    )
    payloads = _payloads(participants=0)
    payloads["agent_quality"]["summary"]["tool_correctness"] = 0.8
    report = build_system_quality_report(
        evaluation_id="system-quality-regression",
        payloads=payloads,
        command_results=_commands(),
        baseline_path=baseline,
    )

    assert report.regression_summary["status"] == "compared"
    assert report.regression_summary["regressions"]["tool_correctness"] == -0.2


def test_command_json_parsing_and_path_redaction():
    payload = _last_json_object('log line\n{"ok": true, "value": 2}\n')
    sanitized = _sanitize(
        {"path": "/Users/private-user/project/data.h5ad", "payload": payload}
    )

    assert payload == {"ok": True, "value": 2}
    assert "/Users/private-user" not in sanitized["path"]
    assert sanitized["payload"]["ok"] is True
