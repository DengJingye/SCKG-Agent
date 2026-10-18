"""Small synthetic receipts and H5AD fixtures; no Scrublet/model execution."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from core.execution_models import ExecutionRun
from core.research_workspace_models import PreviewLineageSnapshot, PreviewRunResult
from execution.preview_result_store import PreviewResultStore
from execution.validators.doublet import DoubletValidator
from sckg_workbench.analysis import (AnalysisService, PUBLIC_SUMMARY_SCHEMA, _attempt_directory,
                                    _attempt_key, _strict_summary_rows, validate_outputs)
from sckg_workbench.dataset_origin import origin_from_snapshot
from sckg_workbench.storage import Workspace, content_hash


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_summary_fixture(tmp_path, *, n_cells=400, positive_count=4):
    """Create truthful *test* receipts, not an actual execution or approval."""
    source = tmp_path / "source.h5ad"
    ids = [f"private-fixture-cell-{i}" for i in range(n_cells)]
    ad.AnnData(np.ones((n_cells, 4), dtype=np.int32), obs=pd.DataFrame(index=ids)).write_h5ad(source)
    service = AnalysisService(Workspace(tmp_path / "workspace"))
    asset = service.datasets.register_local(source)
    # This fixture represents an already saved historical v1 result. Keep its
    # historical profile explicit; do not pretend it has the new v2 run chain.
    submit = service.queue.submit
    def historical_submit(kind, snapshot, profile, budget, idempotency_key, **kwargs):
        profile = {k: v for k, v in profile.items()
                   if k not in {"execution_budget", "operational_recovery_policy"}}
        return submit(kind, snapshot, {**profile, "skill": "scrublet-preview-v1"},
                      budget, idempotency_key, **kwargs)
    with patch.object(service.queue, "submit", side_effect=historical_submit):
        submitted = service.submit_scrublet(asset["asset_id"], "X", "test_fixture only; no science run",
            .06, "summary-fixture", execution_authorized=True, dataset_origin="synthetic",
            dataset_origin_refs=["work:synthetic-test-fixture"])
    task = service.queue.claim("fixture-only", expected_task_id=submitted["task_id"])
    local = service.workspace.artifacts_dir / "analysis" / _attempt_directory(task)
    owner, artifact, run_id = "workbench-local", "asset-" + content_hash(asset["asset_id"])[:24], "fixture-preview-run"
    research, execution = local / "research", local / "users"
    research.mkdir(parents=True)
    preview, notebook_path = research / "preview.h5ad", research / "notebook.ipynb"
    shutil.copyfile(source, preview)
    notebook_path.write_text('{"test_fixture":"not executable"}')
    outputs = execution / owner / "runs" / run_id
    outputs.mkdir(parents=True)
    parameters = {"expected_doublet_rate": .06}
    (outputs / "parameters.json").write_text(json.dumps(parameters))
    metadata = {"fixture_id": "fixture-preview", "input_hash": sha(preview), "n_cells": n_cells,
        "n_genes": 4, "scrublet_version": "0.2.3", "execution_seed": 0,
        "execution_purpose": "representative_preview", "scrublet_actually_executed": True,
        "user_data_used": True, "qualification_mode": False, "preview_only": True,
        "scientific_claim_allowed": False, "synthetic_fixture": False, "public_dataset": False,
        "fixture_notice": "synthetic receipt for validator tests; no actual execution"}
    (outputs / "result_metadata.json").write_text(json.dumps(metadata))
    (outputs / "doublet_score_histogram.png").write_bytes(b"test_fixture:not_a_real_plot")
    table = "obs_id\tdoublet_score\tpredicted_doublet\tground_truth_doublet\n"
    table += "".join(f"{cell}\t{.8 if i < positive_count else .1}\t{'true' if i < positive_count else 'false'}\t\n"
                     for i, cell in enumerate(ids))
    (outputs / "doublet_results.tsv").write_text(table)
    now = datetime.now(timezone.utc)
    run = ExecutionRun(request_id="fixture-request", run_id=run_id, trace_id="fixture-trace", plan_id="fixture-plan",
        step_id="fixture-step", wrapper_id="scrublet_v0_2_3", tool_name="Scrublet", tool_version="0.2.3",
        environment_id="scRNAseq", command_argv_redacted=["test_fixture_no_execution"], parameters=parameters,
        input_hash=sha(preview), start_time=now, end_time=now, runtime_seconds=0, peak_memory_mb=1,
        exit_code=0, stdout_path="fixture-not-a-path", stderr_path="fixture-not-a-path", status="succeeded",
        fixture_id="fixture-preview", artifact_paths={p.name: str(p) for p in outputs.iterdir()},
        artifact_hashes={p.name: sha(p) for p in outputs.iterdir()}, qualification_mode=False,
        synthetic_fixture=False, user_data_used=True, execution_purpose="representative_preview",
        owner_user_id=owner, approval_id="fixture-approval")
    parameter_digest = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    notebook = {"notebook_id": "fixture-notebook", "parameter_hash": parameter_digest,
        "step_contract_id": "fixture-step", "step_contract_version": "1", "step_template_digest": "c" * 64,
        "tool_contract_version": "1"}
    frozen = {"source_sha256": sha(source), "preview_sha256": sha(preview), "preview_id": "fixture-preview",
        "profile_id": "fixture-profile", "notebook_id": "fixture-notebook", "notebook_sha256": sha(notebook_path),
        "notebook_path": str(notebook_path), "parameters": parameters, "expected_cells": n_cells,
        "contract_digest": "d" * 64, "environment_digest": "e" * 64}
    lineage = PreviewLineageSnapshot(source_hash=sha(source), profile_id=frozen["profile_id"],
        preview_id=frozen["preview_id"], preview_hash=sha(preview), notebook_id=frozen["notebook_id"],
        notebook_hash=sha(notebook_path), parameter_hash=parameter_digest, step_contract_id="fixture-step",
        step_contract_version="1", step_template_digest="c" * 64, tool_contract_id="scrublet:0.2.3",
        tool_contract_version="1", tool_contract_digest="d" * 64, environment_id="scRNAseq",
        environment_digest="e" * 64, approval_fingerprint="f" * 64)
    legacy = PreviewRunResult(user_id=owner, artifact_id=artifact, preview_id=frozen["preview_id"],
        notebook_id=frozen["notebook_id"], plan_id=run.plan_id, status="validated", execution_run=run,
        validation_result=DoubletValidator().validate(run, expected_cells=n_cells), lineage=lineage)
    prepared = {"frozen": frozen, "preview_path": str(preview), "source_path": str(source),
        "output_root": str(execution), "notebook": notebook, "profile": {"profile_id": "fixture-profile"},
        "preview": {"preview_id": "fixture-preview"},
        "approval": {"approval_id": "fixture-approval", "request_fingerprint": "f" * 64}}
    validation = validate_outputs(run, preview_path=preview, source_path=source, frozen=frozen, output_root=execution)
    assert validation["passed"] and legacy.validation_result.passed
    saved = {"task_id": task["task_id"], "attempt": task["attempt"], "asset_id": asset["asset_id"],
        "run_id": run_id, "status": "validated", "validation": validation,
        "execution_run": run.model_dump(mode="json"), "legacy_preview_result": legacy.model_dump(mode="json"),
        **origin_from_snapshot(task["input_snapshot"])}
    store = PreviewResultStore(workspace_root=research, execution_root=execution)
    result_path = store.save(legacy)
    service.ledger.put_record("analysis_preparation", _attempt_key(task), prepared)
    service.ledger.put_record("analysis_result", _attempt_key(task), saved)
    service.queue.finish(task["task_id"], task["fencing_token"], "succeeded", result=saved)
    return {"service": service, "task_id": task["task_id"], "attempt": task["attempt"], "run_id": run_id,
        "source": source, "preview": preview, "notebook": notebook_path, "outputs": outputs,
        "result_path": result_path, "ids": ids, "legacy": legacy, "prepared": prepared,
        "store": store, "saved": saved, "asset": asset}


@pytest.fixture
def summary_fixture(tmp_path):
    return make_summary_fixture(tmp_path)


def read_summary(fixture, **overrides):
    options = {k: fixture[k] for k in ("attempt", "run_id")}
    options.update(overrides)
    return fixture["service"].get_public_result_summary(fixture["task_id"],
        attempt=options["attempt"], expected_run_id=options["run_id"])


def test_real_store_strict_summary_is_stable_aggregate_only_and_never_executes(summary_fixture, monkeypatch):
    fixture = summary_fixture
    for symbol in ("submit_scrublet", "run_once", "_execute", "_execute_supervised"):
        monkeypatch.setattr(fixture["service"], symbol, lambda *a, **k: pytest.fail("read attempted execution"))
    monkeypatch.setattr(fixture["service"].ledger, "put_record", lambda *a, **k: pytest.fail("read attempted write"))
    monkeypatch.setattr(fixture["service"].queue, "get", lambda *a, **k: pytest.fail("read attempted queue expiry"))
    first = read_summary(fixture)
    assert first["status"] == "validated_preview_summary"
    assert first["metrics"] == {"n_cells": 400, "predicted_doublet_count": 4,
        "predicted_non_doublet_count": 396, "predicted_doublet_call_rate": .01}
    assert first["threshold"] == {"value": None, "status": "not_recorded"}
    assert first["configuration"] == {"expected_doublet_rate": .06}
    assert first["dataset_origin"] == "synthetic" and not first["scientific_claim_allowed"]
    assert read_summary(fixture) == first
    assert not fixture["service"].ledger.list_records("analysis_public_summary")
    assert first["summary_sha256"] == content_hash({k: v for k, v in first.items() if k != "summary_sha256"})
    encoded = json.dumps(first)
    assert not any(x in encoded for x in (str(fixture["source"]), "private-fixture-cell", "work:synthetic", fixture["task_id"], fixture["run_id"]))
    assert set(first) == {"schema_version", "status", "method", "authority", "metrics", "configuration",
        "threshold", "validation", "dataset_origin", "dataset_origin_verification", "scientific_truth_verified",
        "scientific_claim_allowed", "computation_performed_by_read", "summary_sha256"}


@pytest.mark.parametrize("target", ["source", "preview", "notebook", "result_path", "doublet_results.tsv", "parameters.json", "result_metadata.json"])
def test_saved_summary_never_survives_changed_required_evidence(summary_fixture, target):
    assert read_summary(summary_fixture)["status"] == "validated_preview_summary"
    path = summary_fixture.get(target, summary_fixture["outputs"] / target)
    path.write_bytes(path.read_bytes() + b"test_fixture_corruption")
    result = read_summary(summary_fixture)
    assert result["status"] == "unavailable" and result["reason_code"] == "integrity_failed"
    assert "metrics" not in result


@pytest.mark.parametrize("selection", [{"run_id": "other-run"}, {"attempt": 0}, {"attempt": True}, {"attempt": 2}])
def test_mismatched_selection_has_no_metrics(summary_fixture, selection):
    result = read_summary(summary_fixture, **selection)
    assert result["status"] == "unavailable" and "metrics" not in result


@pytest.mark.parametrize("state", ["queued", "running", "failed", "cancelled", "result_unknown"])
def test_noncompleted_current_task_does_not_expose_valid_table(summary_fixture, state):
    service = summary_fixture["service"]
    with service.ledger.transaction() as tx:
        tx.execute("UPDATE workbench_tasks SET status=? WHERE task_id=?", (state, summary_fixture["task_id"]))
    assert read_summary(summary_fixture)["reason_code"] == "task_not_current_completed"


@pytest.mark.parametrize("mutate", [
    lambda text: text.replace("\ttrue\t", "\tTRUE\t", 1),
    lambda text: text.replace("\t0.8\t", "\tnan\t", 1),
    lambda text: text.replace("\t0.8\t", "\tinf\t", 1),
    lambda text: text.replace("\t0.8\t", "\t1.1\t", 1),
    lambda text: text.replace("private-fixture-cell-1\t", "private-fixture-cell-0\t", 1),
    lambda text: "\n".join(text.splitlines()[:-1]) + "\n",
    lambda text: text + "\n",
])
def test_parser_rejects_each_bad_row_without_skipping(summary_fixture, mutate):
    fixture = summary_fixture
    payload = (fixture["outputs"] / "doublet_results.tsv").read_text()
    with pytest.raises((ValueError, UnicodeError)):
        _strict_summary_rows(mutate(payload).encode(), expected_cells=400, axis_digest=content_hash(fixture["ids"]))


def test_post_validation_table_swap_is_rejected_by_snapshot_hash(summary_fixture, monkeypatch):
    service = summary_fixture["service"]
    real_get = service.get_result
    def swapped(*args, **kwargs):
        result = real_get(*args, **kwargs)
        path = summary_fixture["outputs"] / "doublet_results.tsv"
        path.write_bytes(path.read_bytes().replace(b"\ttrue\t", b"\tfalse\t", 1))
        return result
    monkeypatch.setattr(service, "get_result", swapped)
    assert read_summary(summary_fixture)["reason_code"] == "integrity_failed"


def test_sidecar_loss_and_symlink_fail_closed(summary_fixture, tmp_path):
    assert read_summary(summary_fixture)["status"] == "validated_preview_summary"
    sidecar = summary_fixture["result_path"].with_suffix(".sha256")
    sentinel = tmp_path / "private-sentinel"
    sentinel.write_text("never disclose sentinel")
    sidecar.unlink(); sidecar.symlink_to(sentinel)
    result = read_summary(summary_fixture)
    assert result["status"] == "unavailable" and "sentinel" not in json.dumps(result)


def test_result_read_does_not_expire_unrelated_leases_or_write_records(summary_fixture, monkeypatch):
    service = summary_fixture["service"]
    other = service.queue.submit("fixture-other", {}, {}, {"max_calls": 0, "max_tokens": 0, "max_cost": 0}, "other")
    clock = [100.0]
    service.queue._clock = lambda: clock[0]
    claimed = service.queue.claim("fixture-other", lease_seconds=1, expected_task_id=other["task_id"])
    clock[0] += 2
    before = service.ledger.workspace.db_path.read_bytes()
    assert read_summary(summary_fixture)["status"] == "validated_preview_summary"
    assert service.get_task_snapshot(claimed["task_id"])["status"] == "running"
    assert service.ledger.workspace.db_path.read_bytes() == before
