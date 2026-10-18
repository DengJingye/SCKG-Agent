"""Temporary Git trees and synthetic analysis receipts; no fit/provider calls."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sckg_workbench import code_provenance as cp
from sckg_workbench.analysis import AnalysisService, _attempt_key
from sckg_workbench.storage import Ledger, content_hash
from tests.test_workbench_result_summary import make_summary_fixture
from tests.test_workbench_result_export import export, unpack
from tests.test_workbench_bad_artifact_journey import journey, _run_and_finish


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "private-checkout"
    root.mkdir()
    (root / "workbench_app.py").write_text("# fixture entry\n")
    for name in cp.ROOTS:
        (root / name).mkdir()
        (root / name / "__init__.py").write_text("# fixture module\n")
    return root


def git(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "-C", str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


def bind(value):
    return cp.recorded_code_provenance({"code_provenance": value}, {"code_provenance_digest": content_hash(value)})


def inject_receipt(monkeypatch, value):
    original = Ledger.put_record
    def put(self, kind, record_id, payload, **kwargs):
        if kind == "analysis_preparation":
            payload["code_provenance"] = deepcopy(value)
        elif kind == "analysis_result":
            payload["code_provenance_digest"] = content_hash(value)
        return original(self, kind, record_id, payload, **kwargs)
    monkeypatch.setattr(Ledger, "put_record", put)


def test_real_checkout_capture_clean_dirty_staged_untracked_and_ignored_python(tree, monkeypatch):
    git(tree, "init", "-q")
    git(tree, "add", ".")
    git(tree, "commit", "-qm", "Synthetic source fixture")
    head = git(tree, "rev-parse", "HEAD")
    before_index = (tree / ".git/index").read_bytes()
    monkeypatch.setenv("GIT_DIR", "/incorrect-caller-override")
    clean = cp.capture_code_provenance(tree)
    assert clean["git"] == {"head": head, "tracked_dirty": False, "reason": None}
    assert (tree / ".git/index").read_bytes() == before_index
    assert clean["source_hash"] == content_hash(clean["files"])
    (tree / "core/__init__.py").write_text("# changed tracked code\n")
    dirty = cp.capture_code_provenance(tree)
    assert dirty["git"]["tracked_dirty"] is True and dirty["source_hash"] != clean["source_hash"]
    monkeypatch.delenv("GIT_DIR")
    git(tree, "add", "core/__init__.py")
    assert cp.capture_code_provenance(tree)["git"]["tracked_dirty"] is True
    (tree / ".git/info/exclude").write_text("ignored.py\n")
    (tree / "core/ignored.py").write_text("# ignored Python still observed\n")
    (tree / "core/untracked.py").write_text("# untracked Python still observed\n")
    value = cp.capture_code_provenance(tree)
    assert "core/ignored.py" in value["files"] and "core/untracked.py" in value["files"]
    public = bind(value)
    assert public["loaded_execution_image_verified"] is False
    assert str(tree) not in str(public) and "files" not in public


def test_archive_without_git_retains_source_identity(tree):
    value = cp.capture_code_provenance(tree)
    assert value["git"]["head"] is None and value["git"]["reason"] == "git_not_repository_root"
    assert value["source_hash"] and bind(value)["source_file_count"] == 5


@pytest.mark.parametrize("failure", [FileNotFoundError("private error"), subprocess.TimeoutExpired("git", 1)])
def test_git_absence_or_timeout_is_explicit_without_leaking_error(tree, monkeypatch, failure):
    def fail(*args, **kwargs):
        assert kwargs["timeout"] == 1
        raise failure
    monkeypatch.setattr(cp.subprocess, "run", fail)
    value = cp.capture_code_provenance(tree)
    assert value["git"] == {"head": None, "tracked_dirty": None, "reason": "git_unavailable"}
    assert value["source_hash"] and "private error" not in str(bind(value))


@pytest.mark.parametrize("fault", ["symlink_file", "symlink_directory", "fifo", "missing", "file_limit", "byte_limit", "entry_limit", "during_capture"])
def test_incomplete_or_changed_inventory_never_emits_partial_identity(tree, monkeypatch, fault):
    if fault == "symlink_file":
        (tree / "core/linked.py").symlink_to(tree / "workbench_app.py")
    elif fault == "symlink_directory":
        (tree / "core/link").symlink_to(tree / "execution", target_is_directory=True)
    elif fault == "fifo":
        os.mkfifo(tree / "core/device.py")
    elif fault == "missing":
        (tree / "workbench_app.py").unlink()
    elif fault == "file_limit":
        monkeypatch.setattr(cp, "MAX_FILES", 2)
    elif fault == "byte_limit":
        monkeypatch.setattr(cp, "MAX_BYTES", 2)
    elif fault == "entry_limit":
        monkeypatch.setattr(cp, "MAX_ENTRIES", 2)
    else:
        original = cp._inventory
        def change(*args):
            result = original(*args)
            (tree / "core/__init__.py").write_text("# changed between snapshots\n")
            return result
        monkeypatch.setattr(cp, "_inventory", change)
    value = cp.capture_code_provenance(tree)
    assert value["source_reason"] in cp.SOURCE_REASONS
    assert value["files"] is value["source_hash"] is value["source_bytes"] is None
    assert bind(value)["source_hash"] is None


@pytest.mark.parametrize("fault", ["git_identity", "capture_time", "source_hash", "source_path", "schema", "extra_field"])
def test_even_rehashed_malformed_receipt_is_rejected(tree, fault):
    value = cp.capture_code_provenance(tree)
    if fault == "git_identity":
        value["git"] = {"head": "/private/path", "tracked_dirty": False, "reason": None}
    elif fault == "capture_time":
        value["captured_at"] = "2026-10-18T10:00:00"  # Missing timezone.
    elif fault == "source_hash":
        value["source_hash"] = "0" * 64
    elif fault == "source_path":
        value["files"]["/private/path.py"] = "a" * 64
        value["source_hash"] = content_hash(value["files"])
    elif fault == "schema":
        value["schema_version"] = "unknown"
    else:
        value["unexpected"] = "/private/value"
    with pytest.raises(ValueError):
        bind(value)


def test_saved_export_survives_checkout_changes_without_reading_checkout(tree, tmp_path, monkeypatch):
    git(tree, "init", "-q"); git(tree, "add", "."); git(tree, "commit", "-qm", "Synthetic fixture")
    value = cp.capture_code_provenance(tree)
    inject_receipt(monkeypatch, value)
    fixture = make_summary_fixture(tmp_path, n_cells=12, positive_count=2)
    before = fixture["service"].workspace.db_path.read_bytes()
    first = export(fixture)
    manifest, _, files = unpack(first)
    assert manifest["code_sha"] == value["git"]["head"]
    assert "code_sha" not in manifest["missing_provenance"]
    assert manifest["code_provenance"]["source_hash"] == value["source_hash"]
    assert manifest["reproduction_complete"] is False
    assert str(tree) not in str(files) and "core/__init__.py" not in str(files)
    (tree / "core/__init__.py").write_text("# changed after saved run\n")
    monkeypatch.setattr(cp, "capture_code_provenance", lambda *a: pytest.fail("export recaptured source"))
    assert export(fixture) == first
    assert fixture["service"].workspace.db_path.read_bytes() == before
    other = AnalysisService(fixture["service"].workspace)
    assert other.get_result_export(fixture["task_id"], attempt=fixture["attempt"], expected_run_id=fixture["run_id"]) == first


@pytest.mark.parametrize("fault", ["digest", "missing_receipt", "missing_digest", "malformed_git", "malformed_time", "inventory_hash", "unknown_schema"])
def test_broken_provenance_cannot_export_as_success(tree, tmp_path, monkeypatch, fault):
    value = cp.capture_code_provenance(tree)
    inject_receipt(monkeypatch, value)
    fixture = make_summary_fixture(tmp_path, n_cells=12, positive_count=2)
    assert export(fixture)["status"] == "ready"
    original = fixture["service"].ledger.get_record
    def read(kind, key, **kwargs):
        result = deepcopy(original(kind, key, **kwargs))
        if kind == "analysis_preparation":
            code = result["code_provenance"]
            if fault == "missing_receipt":
                result.pop("code_provenance")
            elif fault == "malformed_git":
                code["git"]["head"] = "/private/path"
            elif fault == "malformed_time":
                code["captured_at"] = "/private/time"
            elif fault == "inventory_hash":
                code["files"]["workbench_app.py"] = "e" * 64
            elif fault == "unknown_schema":
                code["schema_version"] = "future-unrecognized"
            elif fault == "digest":
                code["source_bytes"] += 1
        if kind == "analysis_result" and fault == "missing_digest":
            result.pop("code_provenance_digest")
        return result
    monkeypatch.setattr(fixture["service"].ledger, "get_record", read)
    result = export(fixture)
    assert result["status"] == "unavailable" and "data" not in result


def test_current_v2_recovery_scope_binds_code_receipt(journey, tree, monkeypatch):
    value = cp.capture_code_provenance(tree)
    inject_receipt(monkeypatch, value)
    turn = _run_and_finish(journey)
    assert turn["status"] == "succeeded"
    task = journey.analysis.get_task_snapshot(turn["analysis_task_ids"][0])
    result = journey.analysis.get_result_export(task["task_id"], attempt=task["attempt"], expected_run_id=task["result"]["run_id"])
    manifest, summary, _ = unpack(result)
    assert manifest["code_provenance"]["receipt_hash"] == content_hash(value)
    assert manifest["missing_provenance"]["code_sha"] == "git_not_repository_root"
    assert summary["operational_recovery"]["status"] == "not_used"
    assert len(journey.artifacts) == 1 and len(journey.calls) == 2


def test_actual_preparation_persists_snapshot_before_any_scientific_dispatch(journey, tree, monkeypatch):
    from core.tool_contract_registry import ToolContractRegistry
    from execution.wrapper_registry import WrapperDefinition
    from execution.preview_execution_service import PreviewExecutionService
    from sckg_workbench.analysis_repair import OperationalRecovery
    value = cp.capture_code_provenance(tree)
    monkeypatch.setattr(cp, "capture_code_provenance", lambda: deepcopy(value))
    # Explicit fixture substitutions for unavailable qualification/runtime gates;
    # the real preparation path runs, then stops before scientific reservation.
    monkeypatch.setattr(ToolContractRegistry, "execution_gate", lambda *a, **k: SimpleNamespace(allowed=True, reasons=[]))
    monkeypatch.setattr(WrapperDefinition, "is_runtime_ready", lambda *a: True)
    monkeypatch.setattr(PreviewExecutionService, "execute", lambda *a, **k: pytest.fail("scientific dispatch forbidden"))
    class StopBeforeExecution(Exception):
        pass
    def stop(recovery):
        prepared = recovery.ledger.get_record("analysis_preparation", _attempt_key(task))
        assert prepared["code_provenance"] == value
        raise StopBeforeExecution()
    monkeypatch.setattr(OperationalRecovery, "reserve_initial", stop)
    submitted = journey.analysis.submit_scrublet(**journey.options, execution_authorized=True, idempotency_key="prepare-only")
    task = journey.analysis.queue.claim("prepare-fixture", expected_task_id=submitted["task_id"])
    # journey blocks _execute at class level. Restore the original method held
    # before fixture setup for this preparation-only test.
    with pytest.raises(StopBeforeExecution):
        ORIGINAL_EXECUTE(journey.analysis, task)
    assert journey.analysis.get_task_snapshot(task["task_id"])["status"] == "running"
    assert not journey.calls and not journey.artifacts


ORIGINAL_EXECUTE = AnalysisService._execute
