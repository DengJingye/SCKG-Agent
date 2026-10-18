"""Real queue/thread arbitration with synthetic, non-scientific execution effects."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import h5py
import numpy as np
import psutil
import pytest

from sckg_workbench.analysis import AnalysisService
from sckg_workbench import analysis_dispatch as dispatch
from sckg_workbench.storage import Workspace


def memory(gib):
    return SimpleNamespace(total=16 * 1024**3, available=gib * 1024**3)


@pytest.fixture
def analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(psutil, "virtual_memory", lambda: memory(8))
    source = tmp_path / "synthetic.h5ad"
    with h5py.File(source, "w") as handle:
        handle.attrs["encoding-type"] = "anndata"
        handle.create_dataset("X", data=np.ones((12, 4), dtype=np.int32))
    service = AnalysisService(Workspace(tmp_path / "workspace"), max_rss_mb=512)
    asset = service.datasets.register_local(source)
    task = service.submit_scrublet(asset["asset_id"], "X", "Synthetic fixture counts", .06,
        "one", execution_authorized=True, dataset_origin="synthetic")
    def forbidden(*args, **kwargs):
        pytest.fail("Dispatch tests must never execute a scientific worker")
    monkeypatch.setattr(AnalysisService, "_execute_supervised", forbidden)
    yield service, task
    join(service)


def join(service):
    with dispatch._LOCK:
        launch = dispatch._LAUNCHES.get(dispatch._key(service.workspace))
    if launch:
        launch["thread"].join(timeout=5)
        assert not launch["thread"].is_alive()


def test_concurrent_starts_claim_once_and_late_success_cannot_override_cancel(analysis, monkeypatch):
    service, task = analysis
    entered, release = Event(), Event()
    calls = []
    def synthetic_execution(current):
        calls.append(current["task_id"])
        entered.set()
        assert release.wait(5)
        return {"run_id": "synthetic-late-result", "validation": {"passed": True, "failures": []}}
    monkeypatch.setattr(service, "_execute_supervised", synthetic_execution)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: dispatch.start(service, task["task_id"]), range(4)))
        assert [r["status"] for r in results].count("started") == 1
        assert entered.wait(2) and len(calls) == 1
        before = service.get_task_snapshot(task["task_id"])
        for _ in range(3):
            assert dispatch.snapshot(service.workspace, task["task_id"])["active"]
            assert service.get_task_snapshot(task["task_id"]) == before
        service.queue.request_cancel(task["task_id"])
    finally:
        release.set()
    join(service)
    final = service.get_task_snapshot(task["task_id"])
    assert final["status"] == "cancelled" and final["attempt"] == 1
    assert service.get_result(task["task_id"])["product_completed"] is False
    assert dispatch.start(service, task["task_id"])["status"] == "not_queued"
    assert len(calls) == 1


def test_memory_is_rechecked_inside_claim_without_consuming_attempt(analysis, monkeypatch):
    service, task = analysis
    observations = iter([memory(8), memory(3)])
    monkeypatch.setattr(psutil, "virtual_memory", lambda: next(observations))
    assert dispatch.start(service, task["task_id"])["status"] == "started"
    join(service)
    final = service.get_task_snapshot(task["task_id"])
    assert final["status"] == "queued" and final["attempt"] == 0
    observation = dispatch.snapshot(service.workspace, task["task_id"])
    assert observation["status"] == "launch_error" and "可用内存" in observation["error"]
    assert service.ledger.list_records("analysis_process_started") == []


def test_admission_uses_frozen_task_budget_not_new_service_default(analysis, monkeypatch):
    service, task = analysis
    monkeypatch.setattr(psutil, "virtual_memory", lambda: memory(5))
    reloaded = AnalysisService(service.workspace)  # Its constructor defaults to 2 GiB.
    def fail_before_science(current):
        assert current["profile_snapshot"]["max_rss_mb"] == 512
        raise RuntimeError("synthetic_pre_fit_failure")
    monkeypatch.setattr(reloaded, "_execute_supervised", fail_before_science)
    assert dispatch.start(reloaded, task["task_id"])["status"] == "started"
    join(reloaded)
    assert service.get_task_snapshot(task["task_id"])["status"] == "failed"
    assert "synthetic_pre_fit_failure" in service.get_result(task["task_id"])["summary"]


def test_restart_observation_never_resumes_running_or_expired_task(analysis):
    service, task = analysis
    claimed = service.queue.claim("synthetic-original-owner", lease_seconds=1)
    restarted = AnalysisService(service.workspace)
    assert dispatch.snapshot(restarted.workspace, task["task_id"]) is None
    assert dispatch.start(restarted, task["task_id"])["status"] == "not_queued"
    service.queue._clock = lambda: claimed["lease_expires_at"] + 1
    assert service.queue.get(task["task_id"])["status"] == "result_unknown"
    assert dispatch.start(restarted, task["task_id"])["status"] == "not_queued"
    assert service.get_task_snapshot(task["task_id"])["attempt"] == 1


def test_thread_launch_failure_keeps_task_queued_and_does_not_leave_active_handle(analysis, monkeypatch):
    service, task = analysis
    def unavailable(self):
        raise RuntimeError("synthetic_thread_launch_failure")
    monkeypatch.setattr(dispatch.threading.Thread, "start", unavailable)
    with pytest.raises(RuntimeError, match="synthetic_thread_launch_failure"):
        dispatch.start(service, task["task_id"])
    assert dispatch.snapshot(service.workspace, task["task_id"]) is None
    current = service.get_task_snapshot(task["task_id"])
    assert current["status"] == "queued" and current["attempt"] == 0
