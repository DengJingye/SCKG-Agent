from datetime import datetime, timezone

from core.execution_models import ExecutionRun
from execution.scientific_evaluator import ScientificEvaluator


def test_scientific_evaluator_freezes_threshold_and_bootstraps(tmp_path):
    result_path = tmp_path / "doublet_results.tsv"
    result_path.write_text(
        "obs_id\tdoublet_score\tpredicted_doublet\tground_truth_doublet\n"
        "a\t0.05\tfalse\tfalse\n"
        "b\t0.20\tfalse\tfalse\n"
        "c\t0.80\ttrue\ttrue\n"
        "d\t0.95\ttrue\ttrue\n",
        encoding="utf-8",
    )
    run = _run(result_path)
    evaluator = ScientificEvaluator()
    development = evaluator.evaluate(
        run=run,
        configuration_hash="a" * 64,
        split_role="development",
        bootstrap_iterations=50,
        predictions_output=tmp_path / "development_predictions.tsv",
    )
    evaluation = evaluator.evaluate(
        run=run.model_copy(update={"run_id": "evaluation-run"}),
        configuration_hash="a" * 64,
        split_role="evaluation",
        frozen_threshold=development.threshold,
        bootstrap_iterations=50,
    )

    assert development.metrics["auprc"] == 1.0
    assert development.metrics["auroc"] == 1.0
    assert development.metrics["f1"] == 1.0
    assert evaluation.threshold == development.threshold
    assert evaluation.threshold_source == "frozen_from_development"
    assert evaluation.metric_authority == "scientific_pilot_metric"
    assert set(evaluation.bootstrap_ci) == {"auprc", "auroc", "precision", "recall", "f1"}
    assert all(item.bootstrap_iterations == 50 for item in evaluation.bootstrap_ci.values())


def _run(result_path):
    now = datetime.now(timezone.utc)
    return ExecutionRun(
        request_id="request", run_id="development-run", trace_id="trace", plan_id="plan",
        step_id="step", wrapper_id="scrublet_v0_2_3", tool_name="Scrublet",
        tool_version="0.2.3", environment_id="scRNAseq",
        command_argv_redacted=["python", "-m", "execution.wrappers.scrublet"],
        parameters={}, input_hash="a" * 64, start_time=now, end_time=now,
        runtime_seconds=1.0, peak_memory_mb=100.0, exit_code=0,
        stdout_path="stdout", stderr_path="stderr",
        artifact_paths={"doublet_results.tsv": str(result_path)},
        artifact_hashes={}, status="succeeded", fixture_id="GSE108313-development",
        synthetic_fixture=False, public_dataset=True, user_data_used=False,
        execution_purpose="scientific_pilot",
    )
