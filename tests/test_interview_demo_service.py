from __future__ import annotations

import json
from pathlib import Path

from observability.dashboard.services import InterviewDemoService


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_interview_demo_service_handles_missing_bundle(tmp_path):
    assert InterviewDemoService(tmp_path).latest_bundle() == {}


def test_interview_demo_service_loads_four_cases_and_redacts_paths(tmp_path):
    bundle = tmp_path / "interview-20990101T000000"
    bundle.mkdir()
    _write(
        bundle / "interview_summary.json",
        {
            "status": "passed",
            "architecture": "bounded",
            "phase6_status": "PHASE6_TRIAL_READY",
            "execution_policy_default": "disabled",
            "blocked_execution_request_count": 0,
        },
    )
    for name, status in (
        ("doublet_detection_success", "COMPLETED"),
        ("batch_integration_success", "COMPLETED"),
        ("bounded_repair", "COMPLETED"),
        ("correctly_blocked", "BLOCKED"),
    ):
        _write(
            bundle / f"{name}.json",
            {
                "title": name,
                "status": status,
                "conclusion": "audited",
                "local_path": str(Path(__file__).resolve()),
                "execution_request_count": 0,
            },
        )
    _write(
        bundle / "benchmark_summary.json",
        {
            "requested_model_calls": 48,
            "completed_model_calls": 48,
            "new_model_calls": 48,
            "replayed_model_calls": 0,
            "baselines": [],
            "safety": {"governance_intervention_count": 7},
        },
    )
    _write(
        bundle / "portfolio_governance_examples.json",
        [
            {
                "case_id": "P6-SB-04",
                "raw_response": {"route": "COMPLETED"},
                "admitted_response": {"route": "BLOCKED"},
                "governance_interventions": [{"field": "route"}],
            }
        ],
    )
    _write(bundle / "trace_audit.json", {"minimum_applicable_stage_completeness": 1.0})
    _write(bundle / "package_integrity.json", {"all_complete": True})
    _write(bundle / "limitations.json", {"limitations": ["local only"]})

    result = InterviewDemoService(tmp_path).latest_bundle()

    assert len(result["cases"]) == 4
    assert result["execution_policy_default"] == "disabled"
    assert result["blocked_execution_request_count"] == 0
    assert result["benchmark_completed_calls"] == 48
    assert result["benchmark_safety"]["governance_intervention_count"] == 7
    assert result["benchmark_governance_examples"][0]["case_id"] == "P6-SB-04"
    assert all("/Users/lris/Desktop/scKG_agent/SCKG-Agent" not in json.dumps(row) for row in result["cases"])
