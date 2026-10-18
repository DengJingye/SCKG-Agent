"""Synthetic saved receipts only: no scientific fitting or model calls."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.analysis import AnalysisService
from sckg_workbench.result_export import EXPORT_SCHEMA
from tests.test_workbench_result_summary import make_summary_fixture, sha


@pytest.fixture
def fixture(tmp_path):
    return make_summary_fixture(tmp_path, n_cells=12, positive_count=2)


def export(fixture, **overrides):
    selection = {"attempt": fixture["attempt"], "expected_run_id": fixture["run_id"], **overrides}
    return fixture["service"].get_result_export(fixture["task_id"], **selection)


def unpack(result):
    assert result["status"] == "ready"
    assert hashlib.sha256(result["data"]).hexdigest() == result["sha256"]
    with zipfile.ZipFile(io.BytesIO(result["data"])) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"manifest.json", "result_summary.json", "SHA256SUMS"}
        files = {name: archive.read(name) for name in archive.namelist()}
    for row in files["SHA256SUMS"].decode().splitlines():
        digest, name = row.split("  ")
        assert hashlib.sha256(files[name]).hexdigest() == digest
    manifest, summary = json.loads(files["manifest.json"]), json.loads(files["result_summary.json"])
    assert manifest["files"] == {"result_summary.json": hashlib.sha256(files["result_summary.json"]).hexdigest()}
    return manifest, summary, files


def test_export_download_bytes_bind_exact_receipts_and_disclose_missing_provenance(fixture):
    result = export(fixture)
    manifest, summary, files = unpack(result)
    assert result["schema_version"] == manifest["schema_version"] == EXPORT_SCHEMA
    assert result["filename"].startswith("sckg-preview-") and result["filename"].endswith(".zip")
    assert manifest["task_id"] == fixture["task_id"]
    assert manifest["attempt"] == fixture["attempt"] and manifest["run_id"] == fixture["run_id"]
    assert manifest["dataset_hash"] == sha(fixture["source"])
    assert manifest["preview_hash"] == sha(fixture["preview"])
    assert manifest["parameters"] == {"expected_doublet_rate": .06}
    assert manifest["execution_seed"] == 0
    assert manifest["budget"] == fixture["service"].get_task_snapshot(fixture["task_id"])["budget"]
    assert manifest["dataset_origin"] == "synthetic"
    assert manifest["authority"] == summary["authority"] == "preview_engineering_only"
    assert manifest["scientific_truth_verified"] is manifest["scientific_claim_allowed"] is False
    assert manifest["reproduction_complete"] is False
    for field in ("parent_run_id", "code_sha", "model_actual_identity", "model_config_hash",
                  "prompt_hash", "corpus_snapshot", "index_hash", "tool_registry_hash"):
        assert manifest[field] is None and manifest["missing_provenance"][field] == "not_recorded_in_analysis_receipt"
    assert summary["metrics"]["predicted_doublet_count"] == 2
    assert summary["metrics"]["n_cells"] == 12
    body = b"".join(files.values()).decode()
    assert not any(value in body for value in (str(fixture["source"]), str(fixture["outputs"]),
                   "private-fixture-cell", "test_fixture_no_execution", "work:synthetic-test-fixture"))
    for name, digest in manifest["original_artifact_hashes"].items():
        assert digest == sha(fixture["outputs"] / name)


def test_repeat_export_and_service_reentry_are_identical_and_read_only(fixture, monkeypatch):
    service = fixture["service"]
    def forbidden(*args, **kwargs):
        pytest.fail("export attempted execution or mutation")
    for symbol in ("submit_scrublet", "run_once", "_execute", "_execute_supervised"):
        monkeypatch.setattr(AnalysisService, symbol, forbidden)
    monkeypatch.setattr(service.ledger, "put_record", forbidden)
    monkeypatch.setattr(service.queue, "get", forbidden)
    before = service.workspace.db_path.read_bytes()
    source = sha(fixture["source"])
    first = export(fixture)
    assert first["status"] == "ready"
    assert export(fixture) == first
    assert AnalysisService(service.workspace).get_result_export(fixture["task_id"],
        attempt=fixture["attempt"], expected_run_id=fixture["run_id"]) == first
    assert service.workspace.db_path.read_bytes() == before
    assert sha(fixture["source"]) == source


@pytest.mark.parametrize("target", ["source", "preview", "notebook", "result_path",
                                  "doublet_results.tsv", "parameters.json", "result_metadata.json"])
def test_no_export_after_evidence_changes(fixture, target):
    assert export(fixture)["status"] == "ready"
    path = fixture.get(target, fixture["outputs"] / target)
    path.write_bytes(path.read_bytes() + b"corrupted_test_fixture")
    result = export(fixture)
    assert result["status"] == "unavailable"
    assert "data" not in result and "sha256" not in result


@pytest.mark.parametrize("state", ["queued", "running", "cancel_requested", "cancelled", "failed", "result_unknown"])
def test_late_valid_result_cannot_export_for_noncompleted_task(fixture, state):
    service = fixture["service"]
    with service.ledger.transaction() as tx:
        tx.execute("UPDATE workbench_tasks SET status=? WHERE task_id=?", (state, fixture["task_id"]))
    assert export(fixture)["reason_code"] == "task_not_current_completed"


@pytest.mark.parametrize("selection", [{"attempt": 0}, {"attempt": True}, {"attempt": 2}, {"expected_run_id": "other-run"}])
def test_selection_must_match_current_attempt_and_run(fixture, selection):
    result = export(fixture, **selection)
    assert result["status"] == "unavailable" and "data" not in result


def test_completion_change_during_read_rejects_export(fixture, monkeypatch):
    service = fixture["service"]
    original = service.get_task_snapshot
    reads = []
    def changed(task_id):
        task = original(task_id)
        reads.append(task_id)
        return {**task, "status": "cancelled"} if len(reads) >= 3 else task
    monkeypatch.setattr(service, "get_task_snapshot", changed)
    assert export(fixture)["reason_code"] == "task_not_current_completed"


def test_results_page_serves_exact_zip_and_removes_export_after_corruption(fixture, monkeypatch):
    from sckg_workbench import ui
    original = ui.st.download_button
    served = []
    def capture(label, data, **kwargs):
        if label == "下载结果摘要与复现清单（ZIP）":
            served.append({"data": data, **kwargs})
        return original(label, data, **kwargs)
    monkeypatch.setattr(ui.st, "download_button", capture)
    script = "from sckg_workbench.ui import _run_results\nfrom sckg_workbench.storage import Workspace\nfrom pathlib import Path\n_run_results(Workspace(Path(" + repr(str(fixture["service"].workspace.root)) + ")))\n"
    app = AppTest.from_string(script, default_timeout=15).run()
    assert not app.exception and not app.error
    assert len(served) == 1 and served[0]["data"] == export(fixture)["data"]
    assert served[0]["mime"] == "application/zip"
    assert any(node.proto.label == "下载结果摘要与复现清单（ZIP）" and node.proto.url
               for node in app.get("download_button"))
    app.run()
    assert not app.exception and len(served) == 2
    assert served[0]["data"] == served[1]["data"]
    fixture["source"].write_bytes(b"invalidated source fixture")
    app.run()
    assert not app.exception and len(served) == 2
    assert not any(node.proto.label == "下载结果摘要与复现清单（ZIP）" for node in app.get("download_button"))
    assert app.warning
