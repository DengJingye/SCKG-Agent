from __future__ import annotations

from datetime import datetime, timezone

from core.evaluation_models import (
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
    ExperimentManifest,
    RegressionReport,
    ReleaseGateDecision,
)
from eval.evaluation_pipeline import EvaluationPipeline


def test_pipeline_writes_the_single_required_artifact_contract(tmp_path):
    pipeline = EvaluationPipeline(output_root=tmp_path)
    experiment = tmp_path / "exp"
    experiment.mkdir()
    manifest = ExperimentManifest(
        experiment_id="exp",
        suite="pr",
        completed_at=datetime.now(timezone.utc),
        git_head="head",
        worktree_dirty=True,
        dataset_digests={"dataset": "digest"},
        prompt_digest="prompt",
        evaluator_digest="evaluator",
    )
    metric = EvaluatorResult(
        evaluator_id="test",
        metric_id="code.pytest",
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.PASSED,
        value=True,
        numerator=1,
        denominator=1,
        threshold=1,
        direction="exact",
    )
    gate = ReleaseGateDecision(
        experiment_id="exp", status=EvaluationSignal.PASSED, checks=[]
    )
    pipeline._write_artifacts(
        experiment,
        manifest=manifest,
        case_results=[
            EvaluationRunRecord(
                run_id="run",
                experiment_id="exp",
                case_id="case",
                status="completed",
                canonical_trace_id="trace_11111111111111111111111111111111",
            )
        ],
        metrics=[metric],
        failures=[],
        regression=RegressionReport(
            current_experiment_id="exp", comparable=False, reason="baseline_not_provided"
        ),
        release_gate=gate,
    )
    expected = {
        "experiment_manifest.json",
        "case_results.jsonl",
        "evaluator_scores.jsonl",
        "failure_queue.jsonl",
        "regression_report.json",
        "release_gate.json",
        "report.md",
    }
    assert expected.issubset({path.name for path in experiment.iterdir()})
    case_row = (experiment / "case_results.jsonl").read_text(encoding="utf-8")
    assert "trace_11111111111111111111111111111111" in case_row


def test_experiment_manifest_rejects_inverted_timestamps():
    completed = datetime.now(timezone.utc)
    try:
        ExperimentManifest(
            experiment_id="exp-inverted",
            suite="pr",
            started_at=completed.replace(year=completed.year + 1),
            completed_at=completed,
            git_head="head",
            worktree_dirty=False,
            dataset_digests={"dataset": "digest"},
            prompt_digest="prompt",
            evaluator_digest="evaluator",
        )
    except ValueError as exc:
        assert "completed_at cannot be earlier" in str(exc)
    else:
        raise AssertionError("inverted experiment timestamps must be rejected")
