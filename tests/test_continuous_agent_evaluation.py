from __future__ import annotations

import json
from pathlib import Path

from core.continuous_evaluation_models import MetricSignal, MetricStatus
from eval.continuous_agent_evaluation import (
    ContinuousAgentEvaluator,
    EvaluationSourcePaths,
    freeze_baseline,
    write_report,
)


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sources(tmp_path: Path, *, unauthorized: int = 0) -> EvaluationSourcePaths:
    agent = {
        "case_count": 12,
        "run_count": 36,
        "task_completion_rate": 1.0,
        "task_routing_accuracy": 1.0,
        "intent_accuracy": 1.0,
        "tool_correctness": 1.0,
        "workflow_correctness": 1.0,
        "blocker_correctness": 1.0,
        "source_coverage_rate": 1.0,
        "hallucination_rate": 0.0,
        "compliance_pass_rate": 1.0,
        "trace_completeness": 1.0,
        "stability_rate": 1.0,
        "latency_p50_ms": 10.0,
        "latency_p95_ms": 20.0,
    }
    retrieval = {
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
            },
            "dense": {"status": "not_run", "failures": ["model pack unavailable"]},
            "kg_hybrid_tool_contract": {"status": "not_run"},
        },
    }
    system = {
        "command_results": [
            {"command_id": "authorization", "status": "passed", "exit_code": 0}
        ],
        "dimensions": [
            {
                "dimension": "functional_correctness",
                "metrics": {
                    "operational_scenario_pass_rate": 1.0,
                    "tool_invocation_success_rate": 1.0,
                    "validation_pass_rate": 1.0,
                    "candidate_eligibility_rate": 1.0,
                    "actual_tool_runs": 4,
                },
            },
            {
                "dimension": "safety_and_isolation",
                "metrics": {
                    "unauthorized_execution_count": unauthorized,
                    "path_escape_count": 0,
                    "approval_replay_violation_count": 0,
                    "cross_user_access_violation_count": 0,
                    "untrusted_generated_code_execution_count": 0,
                },
            },
            {
                "dimension": "knowledge_quality",
                "checks": {"knowledge_governance_leakage_zero": True},
                "metrics": {},
            },
            {
                "dimension": "reproducibility",
                "metrics": {"package_integrity_rate": 1.0},
            },
            {
                "dimension": "performance",
                "metrics": {
                    "execution_runtime_seconds_mean_per_tool_smoke": 2.0,
                    "execution_peak_memory_mb_max": 128.0,
                },
            },
            {
                "dimension": "auditability",
                "checks": {"repair_budget_respected": True},
                "metrics": {"applicable_stage_completeness": 1.0},
            },
        ]
    }
    phase6 = {
        "baselines": {
            "B4_contract_bounded_repair": {
                "status": "run",
                "case_count": 1,
                "metrics": {"repair_success": 1.0, "run_count": 4},
            }
        }
    }
    workflow = {"smoke_passed": True}
    portfolio = {
        "completed_model_calls": 48,
        "baselines": [
            {"input_tokens_total": 100, "output_tokens_total": 50}
        ],
    }
    trial = {"participant_count": 0, "level_1_completion_rate": 0.0}
    batch_decision = {
        "decision_scope": "multitool_batch_integration",
        "recommended_candidate_id": "Harmony:2.0.0:config",
    }
    batch_manifest = {
        "task": "batch_integration",
        "reproducibility_level": "Level 2",
    }
    return EvaluationSourcePaths(
        agent_quality=_write(tmp_path / "agent.json", agent),
        retrieval_quality=_write(tmp_path / "retrieval.json", retrieval),
        system_quality=_write(tmp_path / "system.json", system),
        phase6_baseline=_write(tmp_path / "phase6.json", phase6),
        workflow_code_smoke=_write(tmp_path / "workflow.json", workflow),
        portfolio=_write(tmp_path / "portfolio.json", portfolio),
        group_trial=_write(tmp_path / "trial.json", trial),
        batch_decision=_write(tmp_path / "batch_decision.json", batch_decision),
        batch_manifest=_write(tmp_path / "batch_manifest.json", batch_manifest),
    )


def _metric(report, metric_id):
    return next(metric for metric in report.metrics if metric.metric_id == metric_id)


def test_pipeline_maps_metrics_to_business_and_architecture(tmp_path):
    report = ContinuousAgentEvaluator(sources=_sources(tmp_path)).evaluate(
        evaluation_id="test"
    )

    retrieval = _metric(report, "effectiveness.retrieval_recall_at_10")
    approval = _metric(report, "compliance.unauthorized_execution_count")

    assert retrieval.business_domain == "knowledge_qa"
    assert retrieval.architecture_stage == "kg_rag_retrieval"
    assert approval.business_domain == "authorization_and_safety"
    assert approval.architecture_stage == "router_approval"
    assert report.zero_tolerance_violation_count == 0


def test_missing_external_and_human_evidence_is_not_run(tmp_path):
    report = ContinuousAgentEvaluator(sources=_sources(tmp_path)).evaluate(
        evaluation_id="test"
    )

    assert _metric(report, "stability.external_llm_repeat_variance").status == MetricStatus.NOT_RUN
    assert _metric(report, "effectiveness.human_task_completion_rate").status == MetricStatus.NOT_RUN
    assert _metric(report, "effectiveness.ragas_faithfulness").status == MetricStatus.NOT_RUN
    assert report.release_signal == MetricSignal.WATCH


def test_zero_tolerance_violation_blocks_release_signal(tmp_path):
    report = ContinuousAgentEvaluator(
        sources=_sources(tmp_path, unauthorized=1)
    ).evaluate(evaluation_id="test")

    violation = _metric(report, "compliance.unauthorized_execution_count")

    assert violation.signal == MetricSignal.BLOCKED
    assert report.zero_tolerance_violation_count == 1
    assert report.release_signal == MetricSignal.BLOCKED


def test_missing_artifacts_are_unknown_not_fabricated(tmp_path):
    missing = tmp_path / "missing.json"
    sources = EvaluationSourcePaths(
        agent_quality=missing,
        retrieval_quality=missing,
        system_quality=missing,
        phase6_baseline=missing,
        workflow_code_smoke=missing,
        portfolio=missing,
        group_trial=missing,
        batch_decision=missing,
        batch_manifest=missing,
    )
    report = ContinuousAgentEvaluator(sources=sources).evaluate(evaluation_id="empty")

    metric = _metric(report, "effectiveness.task_completion_rate")
    assert metric.status == MetricStatus.NOT_RUN
    assert metric.value is None
    assert metric.signal == MetricSignal.UNKNOWN
    assert report.coverage.measured_metric_count == 0


def test_baseline_regression_is_metric_direction_aware(tmp_path):
    evaluator = ContinuousAgentEvaluator(sources=_sources(tmp_path))
    current = evaluator.evaluate(evaluation_id="current")
    baseline_path = tmp_path / "baseline.json"
    baseline_payload = current.model_dump(mode="json")
    for metric in baseline_payload["metrics"]:
        if metric["metric_id"] == "effectiveness.task_completion_rate":
            metric["value"] = 1.2
    _write(baseline_path, baseline_payload)

    compared = evaluator.evaluate(
        evaluation_id="compared", baseline_path=baseline_path
    )
    trend = next(
        item
        for item in compared.trends
        if item.metric_id == "effectiveness.task_completion_rate"
    )

    assert compared.regression_status == "compared"
    assert trend.regressed is True
    assert compared.regression_count >= 1


def test_report_writes_history_without_raw_local_paths(tmp_path):
    report = ContinuousAgentEvaluator(sources=_sources(tmp_path)).evaluate(
        evaluation_id="write-test"
    )
    output = tmp_path / "output"
    write_report(report, output_dir=output)

    latest = (output / "latest.json").read_text(encoding="utf-8")
    assert (output / "summary.json").is_file()
    assert (output / "history.jsonl").is_file()
    assert (output / "report.md").is_file()
    assert str(tmp_path) not in latest


def test_frozen_baseline_is_immutable(tmp_path):
    report = ContinuousAgentEvaluator(sources=_sources(tmp_path)).evaluate(
        evaluation_id="baseline-test"
    )
    baseline = tmp_path / "baselines" / "rc.json"
    freeze_baseline(report, baseline_path=baseline)

    assert baseline.is_file()
    try:
        freeze_baseline(report, baseline_path=baseline)
    except FileExistsError:
        pass
    else:
        raise AssertionError("baseline overwrite must be rejected")
