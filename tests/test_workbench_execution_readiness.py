import h5py
import numpy as np
import pytest

from sckg_workbench.datasets import DatasetService
from sckg_workbench.execution_readiness import ScrubletReadinessService
from sckg_workbench.storage import Workspace


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path / "workspace")


@pytest.fixture(autouse=True)
def isolated_observers(monkeypatch):
    import sckg_workbench.execution_readiness as module
    monkeypatch.setattr(module, "_control_plane_observation", lambda: {"status": "passed", "detail": "test import only"})
    monkeypatch.setattr(module, "_legacy_observation", lambda: {
        "policy_mode": "disabled", "contract_id": "scrublet:0.2.3",
        "contract_gate_passed": True, "contract_gate_reasons": [],
        "runtime_manifest_warnings": [], "legacy_runtime_executable": "/fixture/python",
        "runtime_imports_verified": False,
    })


def asset(workspace, path, values=None):
    with h5py.File(path, "w") as f:
        f.create_dataset("X", data=np.ones((10, 20)) if values is None else values)
        f.create_group("layers").create_dataset("counts", data=np.ones((10, 20)))
    service = DatasetService(workspace)
    record = service.register_local(path)
    profile = service.profile(record["asset_id"])
    return record, profile


def test_entrypoint_and_integer_profile_never_authorize_execution(workspace, tmp_path):
    a, p = asset(workspace, tmp_path / "input.h5ad")
    service = ScrubletReadinessService(workspace)
    report = service.preflight(a["asset_id"], profile_id=p["profile_id"])
    assert report["ready"] is False
    assert report["status"] == "blocked"
    assert report["execution_attempted"] is False
    assert report["approval_created"] is False
    assert report["legacy"]["legacy_runtime_executable"] == "/fixture/python"
    for reason in ("raw_count_provenance_unverified", "execution_policy_disabled",
                   "execution_approval_and_allowlist_not_bound"):
        assert reason in report["blockers"]
    adapter = next(row for row in report["checks"] if row["check_id"] == "workbench_adapter")
    assert adapter["status"] == "observed" and adapter["blocker"] is None


def test_preflight_does_not_mutate_asset_profile_or_original(workspace, tmp_path, monkeypatch):
    path = tmp_path / "input.h5ad"
    a, p = asset(workspace, path)
    service = ScrubletReadinessService(workspace)
    original = path.read_bytes()
    before = service.datasets.ledger.events()

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not launch processes")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    report = service.preflight(a["asset_id"])
    assert report["profile_id"] == p["profile_id"]
    assert service.datasets.ledger.events() == before
    assert service.datasets.list_profiles(a["asset_id"]) == [p]
    assert path.read_bytes() == original


def test_missing_asset_is_explicit(workspace):
    report = ScrubletReadinessService(workspace).preflight()
    assert "dataset_asset_missing" in report["blockers"]
    assert report["profile_id"] is None


def test_profile_from_different_asset_is_rejected(workspace, tmp_path):
    a, _ = asset(workspace, tmp_path / "a.h5ad")
    _, other = asset(workspace, tmp_path / "b.h5ad")
    report = ScrubletReadinessService(workspace).preflight(a["asset_id"], profile_id=other["profile_id"])
    assert "dataset_profile_binding_mismatch" in report["blockers"]
    assert "dataset_profile_missing" in report["blockers"]


def test_modified_dataset_invalidates_preflight(workspace, tmp_path):
    path = tmp_path / "input.h5ad"
    a, _ = asset(workspace, path)
    with h5py.File(path, "r+") as f:
        f["X"][0, 0] = 2
    report = ScrubletReadinessService(workspace).preflight(a["asset_id"])
    assert "dataset_changed_or_unreadable" in report["blockers"]


def test_empty_matrix_blocks_execution(workspace, tmp_path):
    a, _ = asset(workspace, tmp_path / "input.h5ad", np.zeros((0, 10)))
    report = ScrubletReadinessService(workspace).preflight(a["asset_id"])
    assert "empty_dataset" in report["blockers"]


def test_broken_control_plane_is_distinct_from_available_runtime(workspace, monkeypatch):
    import sckg_workbench.execution_readiness as module
    monkeypatch.setattr(module, "_control_plane_observation", lambda: {
        "status": "blocked", "detail": "AttributeError: getpagesize", "blocker": "control_plane_import_failed"})
    report = ScrubletReadinessService(workspace).preflight()
    assert "control_plane_import_failed" in report["blockers"]
    assert report["legacy"]["legacy_runtime_executable"]
    assert report["ready"] is False


def test_registry_failure_is_reported_not_masked(workspace, monkeypatch):
    import sckg_workbench.execution_readiness as module

    def unavailable():
        raise ValueError("fixture invalid manifest")

    monkeypatch.setattr(module, "_legacy_observation", unavailable)
    report = ScrubletReadinessService(workspace).preflight()
    assert "legacy_registry_unavailable" in report["blockers"]
    assert "execution_policy_unverified" in report["blockers"]


def test_contract_failure_does_not_get_hidden_by_runtime_exists(workspace, monkeypatch):
    import sckg_workbench.execution_readiness as module
    original = module._legacy_observation

    def failed():
        result = original()
        result.update(contract_gate_passed=False, contract_gate_reasons=["contract_execution_disabled"])
        return result

    monkeypatch.setattr(module, "_legacy_observation", failed)
    report = ScrubletReadinessService(workspace).preflight()
    assert "legacy_contract_gate_failed" in report["blockers"]
    assert report["ready"] is False


def test_managed_discovery_is_visible_without_becoming_execution_readiness(workspace, monkeypatch):
    import sckg_workbench.execution_readiness as module
    previous = module._legacy_observation

    def managed():
        result = previous()
        result.update(legacy_runtime_executable=None, resolved_runtime_executable="/fixture/managed/bin/python",
                      runtime_source="managed_pack", runtime_imports_verified=False)
        return result

    monkeypatch.setattr(module, "_legacy_observation", managed)
    report = ScrubletReadinessService(workspace).preflight()
    runtime = next(row for row in report["checks"] if row["check_id"] == "runtime_entrypoint")
    assert runtime["status"] == "observed" and "managed_pack" in runtime["detail"]
    assert "not tested" in runtime["detail"]
    assert report["legacy"]["legacy_runtime_executable"] is None
    assert report["ready"] is False and report["execution_attempted"] is False
    assert report["approval_created"] is False and report["outbound_attempted"] is False
    assert "execution_approval_and_allowlist_not_bound" in report["blockers"]


def test_no_runtime_entrypoint_remains_unknown_without_claiming_an_install_scan_pass(workspace, monkeypatch):
    import sckg_workbench.execution_readiness as module
    previous = module._legacy_observation

    def unavailable():
        result = previous()
        result.update(legacy_runtime_executable=None, resolved_runtime_executable=None, runtime_source=None)
        return result

    monkeypatch.setattr(module, "_legacy_observation", unavailable)
    report = ScrubletReadinessService(workspace).preflight()
    runtime = next(row for row in report["checks"] if row["check_id"] == "runtime_entrypoint")
    assert runtime["status"] == "unknown" and "no installation attempted" in runtime["detail"]
    assert report["ready"] is False and report["execution_attempted"] is False
