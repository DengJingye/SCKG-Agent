from __future__ import annotations

import json

from observability.dashboard.services import Phase6EvaluationService


def test_phase6_service_reads_and_filters_without_running_execution(tmp_path):
    summary = tmp_path / "summary.json"
    cases = tmp_path / "cases.tsv"
    failures = tmp_path / "failures.tsv"
    trace = tmp_path / "trace.json"
    telemetry = tmp_path / "telemetry.jsonl"
    summary.write_text('{"baselines":{"A1":{"status":"not_run"}}}', encoding="utf-8")
    cases.write_text("track\tstatus\tbaseline_id\nA\trun\tA2\nB\trun\tB4\n", encoding="utf-8")
    failures.write_text(
        "tool\trepairable\trun_id\nScrublet 0.2.3\tTrue\trun-1\n",
        encoding="utf-8",
    )
    trace.write_text('{"cases":[]}', encoding="utf-8")
    telemetry.write_text(json.dumps({"participant_id": "trial-" + "a" * 32}) + "\n", encoding="utf-8")
    service = Phase6EvaluationService(
        summary_path=summary,
        cases_path=cases,
        failure_queue_path=failures,
        trace_audit_path=trace,
        telemetry_path=telemetry,
    )
    assert service.list_cases(track="A")[0]["baseline_id"] == "A2"
    assert service.list_failures(repairable="True")[0]["run_id"] == "run-1"
    assert service.load_trace_audit() == {"cases": []}
    assert service.list_trial_events()[0]["participant_id"].startswith("trial-")
