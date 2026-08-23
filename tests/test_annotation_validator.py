from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import pandas as pd

from core.execution_models import ExecutionRun
from core.tool_contract_registry import ToolContractRegistry
from execution.annotation_probe_builder import AnnotationProbeBuilder
from execution.validators.annotation import AnnotationValidator
from tests.annotation_helpers import build_reference


def test_annotation_validator_accepts_complete_ordered_artifacts(tmp_path):
    reference = build_reference(tmp_path / "reference")
    probe = AnnotationProbeBuilder().build(
        output_dir=tmp_path / "probe",
        split_role="development",
        random_seed=71,
        reference=reference,
    )
    contract = ToolContractRegistry().load("CellTypist", "1.7.1")
    run = _successful_run(tmp_path / "run", probe.probe_artifact_path, contract, reference)

    result = AnnotationValidator().validate(
        run,
        expected_cells=probe.n_cells,
        expected_input_path=probe.probe_artifact_path,
        contract=contract,
        reference=reference,
    )

    assert result.passed is True
    assert result.metric_authority == "synthetic_engineering_metric"
    assert result.task_metrics["macro_f1"] == 1.0
    assert result.task_metrics["balanced_accuracy"] == 1.0
    assert result.task_metrics["reject_rate"] == 0.0
    assert result.validation_version == "annotation-validator-v1"


def test_annotation_validator_blocks_hash_and_order_mismatch(tmp_path):
    reference = build_reference(tmp_path / "reference")
    probe = AnnotationProbeBuilder().build(
        output_dir=tmp_path / "probe",
        split_role="evaluation",
        random_seed=72,
        reference=reference,
    )
    contract = ToolContractRegistry().load("CellTypist", "1.7.1")
    run = _successful_run(tmp_path / "run", probe.probe_artifact_path, contract, reference)
    labels_path = Path(run.artifact_paths["predicted_labels.tsv"])
    labels = pd.read_csv(labels_path, sep="\t")
    labels.iloc[::-1].to_csv(labels_path, sep="\t", index=False)
    run = run.model_copy(
        update={
            "artifact_hashes": {
                **run.artifact_hashes,
                "predicted_labels.tsv": _sha256(labels_path),
            }
        }
    )

    order_result = AnnotationValidator().validate(
        run,
        expected_cells=probe.n_cells,
        expected_input_path=probe.probe_artifact_path,
        contract=contract,
        reference=reference,
    )
    assert order_result.passed is False
    assert "cell_order_mismatch" in order_result.failures

    Path(run.artifact_paths["annotation_scores.tsv"]).write_text(
        "cell_id\tB_cell\ncorrupt\tnan\n",
        encoding="utf-8",
    )
    hash_result = AnnotationValidator().validate(
        run,
        expected_cells=probe.n_cells,
        expected_input_path=probe.probe_artifact_path,
        contract=contract,
        reference=reference,
    )
    assert hash_result.passed is False
    assert "artifact_hash_mismatch" in hash_result.failures


def _successful_run(run_dir, input_path, contract, reference):
    run_dir.mkdir()
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir()
    adata = ad.read_h5ad(input_path)
    truth = adata.obs["ground_truth_cell_type"].astype(str)
    labels = pd.DataFrame(
        {
            "cell_id": adata.obs_names.astype(str),
            "predicted_label": truth.to_numpy(),
            "unknown": False,
        }
    )
    labels.to_csv(artifacts_dir / "predicted_labels.tsv", sep="\t", index=False)
    scores = pd.get_dummies(truth).astype(float)
    scores.insert(0, "cell_id", adata.obs_names.astype(str))
    scores.to_csv(artifacts_dir / "annotation_scores.tsv", sep="\t", index=False)
    parameters = contract.default_parameters
    (artifacts_dir / "parameters.json").write_text(
        json.dumps(
            {
                "parameters": parameters,
                "execution_seed": 1,
                "reference_id": reference.reference_id,
                "reference_digest": reference.sha256,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "result_metadata.json").write_text(
        json.dumps(
            {
                "tool_name": contract.tool_name,
                "tool_version": contract.tool_version,
                "input_hash": _sha256(Path(input_path)),
                "cell_count": adata.n_obs,
                "reference_id": reference.reference_id,
                "reference_digest": reference.sha256,
                "runtime_network_used": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_paths = {
        path.name: str(path)
        for path in artifacts_dir.iterdir()
        if path.is_file()
    }
    now = datetime.now(timezone.utc)
    return ExecutionRun(
        request_id="annotation-request",
        run_id="annotation-run",
        trace_id="annotation-trace",
        plan_id="annotation-plan",
        step_id="annotation-step",
        wrapper_id=contract.wrapper_id,
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        environment_id=contract.environment_id,
        command_argv_redacted=["python", "-m", contract.wrapper_id],
        parameters=parameters,
        input_hash=_sha256(Path(input_path)),
        start_time=now,
        end_time=now,
        runtime_seconds=0.2,
        peak_memory_mb=80,
        exit_code=0,
        stdout_path=str(run_dir / "stdout.log"),
        stderr_path=str(run_dir / "stderr.log"),
        artifact_paths=artifact_paths,
        artifact_hashes={
            name: _sha256(Path(path))
            for name, path in artifact_paths.items()
        },
        status="succeeded",
        fixture_id="phase27_annotation_synthetic",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
