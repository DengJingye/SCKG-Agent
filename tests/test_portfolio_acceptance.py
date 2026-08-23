from __future__ import annotations

import json

from eval.portfolio_acceptance import (
    PortfolioAcceptanceCheck,
    _redact_text,
    evaluate_portfolio_artifacts,
)
from scripts.run_interview_demo import _sanitize_artifact


def _check(check_id: str, metrics: dict) -> PortfolioAcceptanceCheck:
    return PortfolioAcceptanceCheck(check_id=check_id, status="passed", metrics=metrics)


def test_portfolio_acceptance_requires_all_engineering_gates(tmp_path):
    checks = [
        _check("pytest", {"passed_count": 358}),
        _check(
            "mainline",
            {
                "case_count": 6,
                "passed_case_count": 6,
                "hard_gate_passed": True,
                "unauthorized_execution_request_count": 0,
                "candidate_evidence_leakage_count": 0,
            },
        ),
        _check(
            "retrieval",
            {
                "profiles": {
                    "kg_hybrid_tool_contract": {
                        "recall_at_10": 0.98,
                        "precision_at_10": 0.92,
                        "mrr": 0.995,
                        "source_span_hit_rate": 1.0,
                        "governance_leakage_count": 0,
                    }
                }
            },
        ),
        _check(
            "agent_quality",
            {
                "release_gate_passed": True,
                "task_routing_accuracy": 1.0,
                "intent_accuracy": 1.0,
                "tool_correctness": 1.0,
                "blocker_correctness": 1.0,
                "latency_p95_ms": 150.0,
            },
        ),
        _check(
            "memory",
            {"release_gate_passed": True, "scientific_authority_violation_count": 0},
        ),
        _check(
            "interview_demo",
            {
                "status": "passed",
                "case_count": 4,
                "trace_completeness": 1.0,
                "blocked_execution_request_count": 0,
                "package_integrity": {"all_complete": True},
            },
        ),
        _check(
            "git_integrity",
            {
                "tracked_dataless_flag_count": 7,
                "tracked_dataless_content_verified_count": 7,
                "tracked_dataless_unreadable_or_mismatch_count": 0,
            },
        ),
        _check("release_privacy", {"privacy_issue_count": 0}),
    ]
    result = evaluate_portfolio_artifacts(
        output_root=tmp_path,
        checks=checks,
        git_snapshot={
            "head": "a" * 40,
            "branch": "main",
            "dirty": True,
            "tracked_modified_count": 48,
            "untracked_count": 456,
        },
        release_report={"issues": [], "file_hashes": {"README.md": "b" * 64}},
    )

    assert result.hard_gate_passed is True
    assert result.portfolio_status == "RC_READY_FOR_USER_REVIEW"
    assert result.phase6_status == "PHASE6_TRIAL_READY"
    assert result.execution_policy == "disabled"
    assert result.real_trial_participants == 0
    assert result.git_dirty is True
    assert len(result.worktree_digest) == 64
    assert {row.check_id for row in result.checks} >= {
        "external_llm_stability",
        "ragas",
        "real_user_trial",
    }
    assert "7 tracked hidden files" in result.limitations[-1]


def test_portfolio_acceptance_blocks_metric_regression(tmp_path):
    checks = [
        _check("pytest", {"passed_count": 358}),
        _check(
            "mainline",
            {
                "case_count": 6,
                "passed_case_count": 6,
                "hard_gate_passed": True,
                "unauthorized_execution_request_count": 0,
                "candidate_evidence_leakage_count": 0,
            },
        ),
        _check(
            "retrieval",
            {
                "profiles": {
                    "kg_hybrid_tool_contract": {
                        "recall_at_10": 0.80,
                        "precision_at_10": 0.92,
                        "mrr": 0.995,
                        "source_span_hit_rate": 1.0,
                        "governance_leakage_count": 0,
                    }
                }
            },
        ),
        _check("agent_quality", {}),
        _check("memory", {}),
        _check("interview_demo", {}),
        _check("git_integrity", {}),
        _check("release_privacy", {}),
    ]
    result = evaluate_portfolio_artifacts(
        output_root=tmp_path,
        checks=checks,
        git_snapshot={"head": "a" * 40, "branch": "main", "dirty": False},
        release_report={"issues": [], "file_hashes": {}},
    )

    assert result.hard_gate_passed is False
    assert result.portfolio_status == "RC_BLOCKED"
    hard_gate = next(row for row in result.checks if row.check_id == "hard_gate")
    assert hard_gate.metrics["retrieval"] is False


def test_portfolio_acceptance_json_does_not_require_local_paths(tmp_path):
    result = evaluate_portfolio_artifacts(
        output_root=tmp_path,
        checks=[PortfolioAcceptanceCheck(check_id="pytest", status="failed")],
        git_snapshot={"head": "a" * 40, "branch": "main", "dirty": False},
        release_report={"issues": ["privacy"], "file_hashes": {}},
    )
    payload = json.loads(result.model_dump_json())

    assert "/Users/" not in json.dumps(payload)
    assert payload["real_trial_participants"] == 0


def test_portfolio_artifact_redaction_removes_local_paths():
    value = {
        "stderr": "/opt/anaconda3/envs/scRNAseq/lib/python3.12/warning.py: bad",
        "input": "/Users/example/private/data.h5ad",
    }

    sanitized = _sanitize_artifact(value)
    log = _redact_text(json.dumps(value))

    assert "/opt/anaconda3/" not in json.dumps(sanitized)
    assert "/Users/" not in json.dumps(sanitized)
    assert "/opt/anaconda3/" not in log
    assert "/Users/" not in log
