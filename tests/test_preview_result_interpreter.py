from __future__ import annotations

from pathlib import Path

from core.research_workspace_models import PreviewResultIntegrity
from execution.preview_result_interpreter import (
    PreviewErrorIntelligence,
    PreviewResultInterpreter,
)
from tests.test_preview_result_store import _execute_preview


def test_completed_preview_has_bounded_plain_language_interpretation(tmp_path):
    service, result = _execute_preview(tmp_path)

    interpretation = service.interpret_result(result=result)

    assert interpretation.status == "COMPLETED"
    assert interpretation.usable_for_preview_review is True
    assert interpretation.scientific_claim_allowed is False
    assert interpretation.metric_authority == "preview_engineering_metric"
    assert interpretation.error_diagnosis is None
    assert interpretation.plot_explanation is not None
    metrics = {item.metric_id: item for item in interpretation.observed_metrics}
    assert metrics["preview_cells"].raw_value == 120
    assert 0 <= float(metrics["predicted_call_rate"].raw_value) <= 1
    assert metrics["median_score"].raw_value is not None
    assert metrics["score_p90"].raw_value is not None
    parameters = {
        item.parameter_name: item for item in interpretation.parameter_explanations
    }
    assert parameters["expected_doublet_rate"].value == 0.08
    assert parameters["n_prin_comps"].value == 10
    assert all(not item.automatic_adjustment_allowed for item in parameters.values())
    assert all(not item.automatic for item in interpretation.next_actions)
    assert any("ground truth" in item.casefold() for item in interpretation.limitations)


def test_call_rate_anomaly_is_review_guidance_not_automatic_tuning(tmp_path):
    service, result = _execute_preview(tmp_path)
    result_path = Path(result.execution_run.artifact_paths["doublet_results.tsv"])
    lines = result_path.read_text(encoding="utf-8").splitlines()
    rewritten = [lines[0]]
    for line in lines[1:]:
        columns = line.split("\t")
        columns[1] = "0.95"
        columns[2] = "true"
        rewritten.append("\t".join(columns))
    synthetic_table = tmp_path / "high-call-rate.tsv"
    synthetic_table.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    integrity = service.result_store.inspect_integrity(result)
    checkpoint = service.checkpoints.inspect_result(
        result=result, integrity=integrity
    )

    interpretation = PreviewResultInterpreter().interpret(
        result=result,
        integrity=integrity,
        checkpoint=checkpoint,
        result_table_path=synthetic_table,
    )

    assert any("2.5 times" in item for item in interpretation.warnings)
    assert all(not item.automatic for item in interpretation.next_actions)
    assert "diagnostic signal" in interpretation.plain_language_summary[1]


def test_stale_lineage_withholds_interpretation_and_points_to_rebuild(tmp_path):
    service, result = _execute_preview(tmp_path)
    source = service.data_registry.resolve_path("pbmc", user_id="alice")
    source.write_bytes(source.read_bytes() + b"changed")

    interpretation = service.interpret_result(result=result)

    assert interpretation.status == "STALE"
    assert interpretation.usable_for_preview_review is False
    assert interpretation.error_diagnosis is not None
    assert interpretation.error_diagnosis.stage == "lineage"
    assert interpretation.error_diagnosis.category == "stale_lineage"
    assert interpretation.error_diagnosis.automatic_repair_allowed is False
    assert interpretation.next_actions[0].requires_new_approval is True


def test_artifact_integrity_failure_is_critical_and_not_retryable(tmp_path):
    service, result = _execute_preview(tmp_path)
    histogram = Path(result.execution_run.artifact_paths["doublet_score_histogram.png"])
    histogram.write_bytes(histogram.read_bytes() + b"tampered")

    interpretation = service.interpret_result(result=result)

    assert interpretation.status == "FAILED"
    assert interpretation.usable_for_preview_review is False
    assert interpretation.error_diagnosis is not None
    assert interpretation.error_diagnosis.stage == "integrity"
    assert interpretation.error_diagnosis.severity == "critical"
    assert interpretation.error_diagnosis.retryable is False
    assert "artifact_hash_mismatch" in interpretation.error_diagnosis.evidence
    assert interpretation.next_actions[0].requires_new_approval is True


def test_missing_result_table_does_not_invent_score_statistics(tmp_path):
    service, result = _execute_preview(tmp_path)
    integrity = service.result_store.inspect_integrity(result)
    checkpoint = service.checkpoints.inspect_result(
        result=result, integrity=integrity
    )

    interpretation = PreviewResultInterpreter().interpret(
        result=result,
        integrity=PreviewResultIntegrity.model_validate(integrity.model_dump()),
        checkpoint=checkpoint,
        result_table_path=None,
    )

    metrics = {item.metric_id: item for item in interpretation.observed_metrics}
    assert metrics["median_score"].raw_value is None
    assert metrics["score_p90"].raw_value is None
    assert metrics["preview_cells"].display_value == "Unavailable"


def test_execution_failure_is_classified_without_running_repair(tmp_path):
    service, result = _execute_preview(tmp_path)
    failed_run = result.execution_run.model_copy(
        update={
            "status": "failed",
            "exit_code": 1,
            "error_type": "wrapper_exit_nonzero",
            "error_message": "fixed wrapper exited",
        }
    )
    failed_validation = result.validation_result.model_copy(
        update={"passed": False, "failures": ["execution_not_successful"]}
    )
    failed_result = result.model_copy(
        update={
            "status": "failed",
            "execution_run": failed_run,
            "validation_result": failed_validation,
            "error_context": result.error_context,
        }
    )
    integrity = PreviewResultIntegrity(
        passed=True,
        result_digest_valid=True,
        artifact_paths_owned=True,
        artifact_hashes_valid=True,
    )

    diagnosis = PreviewErrorIntelligence().diagnose(
        result=failed_result, integrity=integrity
    )

    assert diagnosis is not None
    assert diagnosis.category == "runtime_or_wrapper"
    assert diagnosis.automatic_repair_allowed is False
    assert diagnosis.user_actions[0].automatic is False
    assert diagnosis.user_actions[0].requires_new_approval is True
