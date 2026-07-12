import json
from pathlib import Path

from execution.validators.doublet import DoubletValidator
from tests.qualification_helpers import build_qualification_case


def test_doublet_validator_accepts_complete_synthetic_artifacts(tmp_path):
    case = build_qualification_case(tmp_path)
    run_dir = tmp_path / "fake-run"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    results = artifacts / "doublet_results.tsv"
    results.write_text(
        "obs_id\tdoublet_score\tpredicted_doublet\tground_truth_doublet\n"
        "a\t0.1\tfalse\tfalse\n"
        "b\t0.9\ttrue\ttrue\n",
        encoding="utf-8",
    )
    parameters = artifacts / "parameters.json"
    parameters.write_text("{}\n", encoding="utf-8")
    metadata = artifacts / "result_metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "scrublet_actually_executed": True,
                "synthetic_fixture": True,
                "user_data_used": False,
                "qualification_mode": True,
            }
        ),
        encoding="utf-8",
    )
    from hashlib import sha256
    hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in artifacts.iterdir()}
    run = _fake_run(case, artifacts, hashes)

    result = DoubletValidator().validate(run, expected_cells=2)
    assert result.passed is True
    assert result.metric_authority == "synthetic_engineering_metric"
    assert result.task_metrics["synthetic_engineering_f1"] == 1.0
    assert result.eligible_for_candidate_aggregation is False


def test_doublet_validator_rejects_nan_length_and_hash_mismatch(tmp_path):
    case = build_qualification_case(tmp_path)
    artifacts = tmp_path / "bad" / "artifacts"
    artifacts.mkdir(parents=True)
    results = artifacts / "doublet_results.tsv"
    results.write_text(
        "obs_id\tdoublet_score\tpredicted_doublet\tground_truth_doublet\n"
        "a\tnan\tmaybe\tfalse\n",
        encoding="utf-8",
    )
    parameters = artifacts / "parameters.json"
    parameters.write_text("{}", encoding="utf-8")
    metadata = artifacts / "result_metadata.json"
    metadata.write_text("{}", encoding="utf-8")
    run = _fake_run(case, artifacts, {path.name: "0" * 64 for path in artifacts.iterdir()})

    result = DoubletValidator().validate(run, expected_cells=2)
    assert result.passed is False
    assert "artifact_hash_mismatch" in result.failures
    assert "score_non_finite_or_out_of_range" in result.failures
    assert "score_label_count_mismatch" in result.failures


def _fake_run(case, artifacts: Path, hashes: dict[str, str]):
    from datetime import datetime, timezone
    from core.execution_models import ExecutionRun

    now = datetime.now(timezone.utc)
    return ExecutionRun(
        request_id="request-fake",
        run_id="run-fake",
        trace_id="trace-fake",
        plan_id="plan-fake",
        step_id="step-fake",
        wrapper_id="scrublet_v0_2_3",
        tool_name="Scrublet",
        tool_version="0.2.3",
        environment_id="scRNAseq",
        command_argv_redacted=["python", "-m", "execution.wrappers.scrublet"],
        parameters={},
        input_hash=case["artifact"].sha256,
        start_time=now,
        end_time=now,
        runtime_seconds=0.1,
        peak_memory_mb=1.0,
        exit_code=0,
        stdout_path=str(artifacts.parent / "stdout.log"),
        stderr_path=str(artifacts.parent / "stderr.log"),
        artifact_paths={path.name: str(path) for path in artifacts.iterdir()},
        artifact_hashes=hashes,
        status="succeeded",
        fixture_id=case["artifact"].fixture_id,
    )
