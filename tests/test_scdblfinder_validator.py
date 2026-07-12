import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad

from core.execution_models import ExecutionRun
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from execution.environment_registry import EnvironmentRegistry
from execution.probe_builder import ProbeBuilder
from execution.validators.scdblfinder import ScDblFinderValidator
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_scdblfinder_validator_accepts_unified_outputs(tmp_path):
    contract, probe, run = _case(tmp_path, corrupt=False)
    result = ScDblFinderValidator(contract).validate(
        run, expected_cells=probe.n_probe_cells
    )
    assert result.passed is True
    assert result.metric_authority == "synthetic_engineering_metric"
    assert result.task_metrics["synthetic_engineering_auprc"] > 0.0
    assert result.sanity_checks["cell_id_order_matches"] is True
    assert result.sanity_checks["parameters_match_contract_and_run"] is True


def test_scdblfinder_validator_rejects_order_nan_and_hash_mismatch(tmp_path):
    contract, probe, run = _case(tmp_path, corrupt=True)
    result = ScDblFinderValidator(contract).validate(
        run, expected_cells=probe.n_probe_cells
    )
    assert result.passed is False
    assert "artifact_hash_mismatch" in result.failures
    assert "cell_id_order_mismatch" in result.failures
    assert "score_non_finite_or_out_of_range" in result.failures


def _case(tmp_path, *, corrupt):
    fixtures = write_phase1_fixtures(tmp_path / "fixtures")
    profile = AnnDataProfiler().profile(fixtures["raw_x"])
    probe = ProbeBuilder().build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "probes" / "validation",
        profile_id=profile.profile_id,
        fixture_id="phase1_raw_counts_x",
        max_cells=12,
        random_seed=901,
        split_role="development",
        pairing_strategy="mixed",
        cluster_key="batch",
        allowed_output_root=tmp_path / "probes",
    )
    contract = ToolContractRegistry(environment_registry=EnvironmentRegistry()).load(
        "scDblFinder", "not_installed"
    )
    parameters = {**contract.default_parameters, "random_state": 901}
    run_dir = tmp_path / "run"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    input_path = Path(probe.probe_artifact_path)
    adata = ad.read_h5ad(input_path)
    ids = [str(item) for item in adata.obs_names]
    truth = [bool(item) for item in adata.obs["ground_truth_doublet"]]
    if corrupt:
        ids = list(reversed(ids))
    rows = ["cell_id\tdoublet_score\tpredicted_doublet"]
    for index, (cell_id, actual) in enumerate(zip(ids, truth)):
        score = "nan" if corrupt and index == 0 else ("0.9" if actual else "0.1")
        rows.append(f"{cell_id}\t{score}\t{'true' if actual else 'false'}")
    (artifacts / "doublet_results.tsv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    (artifacts / "parameters.json").write_text(
        json.dumps(parameters, sort_keys=True) + "\n", encoding="utf-8"
    )
    (artifacts / "result_metadata.json").write_text(
        json.dumps(
            {
                "fixture_id": probe.source_fixture_id,
                "input_hash": probe.probe_hash,
                "qualification_mode": True,
                "scdblfinder_actually_executed": True,
                "scdblfinder_version": "not_installed",
                "synthetic_fixture": True,
                "user_data_used": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "worker_request.json").write_text(
        json.dumps(
            {
                "input_path": str(input_path),
                "expected_input_hash": probe.probe_hash,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in artifacts.iterdir()
    }
    if corrupt:
        hashes["doublet_results.tsv"] = "0" * 64
    now = datetime.now(timezone.utc)
    run = ExecutionRun(
        request_id="request-scdblfinder",
        run_id="run-scdblfinder",
        trace_id="trace-scdblfinder",
        plan_id="plan-scdblfinder",
        step_id="run-tool-configuration",
        wrapper_id=contract.wrapper_id,
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        environment_id=contract.environment_id,
        command_argv_redacted=["python", "-m", "execution.wrappers.scdblfinder"],
        parameters=parameters,
        input_hash=probe.probe_hash,
        start_time=now,
        end_time=now,
        runtime_seconds=0.5,
        peak_memory_mb=32.0,
        exit_code=0,
        stdout_path=str(run_dir / "stdout.log"),
        stderr_path=str(run_dir / "stderr.log"),
        artifact_paths={path.name: str(path) for path in artifacts.iterdir()},
        artifact_hashes=hashes,
        status="succeeded",
        fixture_id=probe.source_fixture_id,
    )
    return contract, probe, run
