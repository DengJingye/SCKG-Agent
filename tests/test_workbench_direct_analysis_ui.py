"""Direct local submission through real UI/services; never fit or call a model."""
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from sckg_workbench.analysis import AnalysisService
from sckg_workbench.datasets import DatasetService
from sckg_workbench.tasks import TaskQueue
from tests.test_workbench_ui import ui, page, widget


def _input(ui, tmp_path, *, cells=12):
    app, ledger = ui
    path = tmp_path / "explicitly-synthetic-counts.h5ad"
    with h5py.File(path, "w") as handle:
        handle.attrs["encoding-type"] = "anndata"
        handle.create_dataset("X", data=np.ones((cells, 4), dtype=np.int32))
    original = path.read_bytes()
    asset = DatasetService(ledger.workspace).register_local(path)
    page(app, "数据资产")
    widget(app.text_area, "原始计数来源说明").set_value("Explicitly synthetic untransformed counts for UI testing.")
    widget(app.number_input, "预期双细胞比例（0.06 表示 6%）").set_value(0.06)
    widget(app.selectbox, "分析数据来源").set_value("synthetic")
    widget(app.checkbox, "确认 X 为未经归一化的原始计数，并授权本次本地分析").check()
    return app, ledger, asset, path, original


def _submit(app):
    widget(app.button, "创建本地分析任务").click().run()
    assert not app.exception


def test_direct_submission_needs_no_model_and_duplicate_clicks_reuse_task(ui, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Creating or viewing a task must not execute science")
    monkeypatch.setattr(AnalysisService, "_execute_supervised", forbidden)
    app, ledger, asset, path, original = _input(ui, tmp_path)
    _submit(app)
    task = TaskQueue(ledger.workspace).list()[0]
    assert task["status"] == "queued" and task["attempt"] == 0
    assert task["input_snapshot"]["asset_id"] == asset["asset_id"]
    assert task["input_snapshot"]["expected_doublet_rate"] == .06
    assert task["input_snapshot"]["execution_authorized"] is True
    assert task["input_snapshot"]["dataset_origin"] == "synthetic"
    assert task["budget"] == {"max_calls": 0, "max_tokens": 0, "max_cost": 0}
    _submit(app)
    assert len(TaskQueue(ledger.workspace).list()) == 1
    widget(app.button, "前往运行结果").click().run()
    assert not app.exception
    assert widget(app.selectbox, "查看分析任务").value == task["task_id"]
    widget(app.button, "刷新分析状态").click().run()
    assert not app.exception and len(TaskQueue(ledger.workspace).list()) == 1
    assert ledger.list_records("model_call") == []
    assert ledger.list_records("analysis_preparation") == []
    assert path.read_bytes() == original


@pytest.mark.parametrize("missing", ["authorization", "provenance", "rate", "dimensions"])
def test_direct_submission_rejects_missing_declarations_or_oversized_matrix(ui, tmp_path, missing):
    app, ledger, _, path, original = _input(ui, tmp_path, cells=1001 if missing == "dimensions" else 12)
    if missing == "authorization":
        widget(app.checkbox, "确认 X 为未经归一化的原始计数，并授权本次本地分析").uncheck()
    elif missing == "provenance":
        widget(app.text_area, "原始计数来源说明").set_value("")
    elif missing == "rate":
        widget(app.number_input, "预期双细胞比例（0.06 表示 6%）").set_value(None)
    _submit(app)
    assert app.error and TaskQueue(ledger.workspace).list() == []
    assert path.read_bytes() == original


def test_memory_block_does_not_claim_or_execute_the_task(ui, tmp_path, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * 1024**3, available=3 * 1024**3))
    def forbidden(*args, **kwargs):
        pytest.fail("Memory refusal must happen before dispatch")
    monkeypatch.setattr(AnalysisService, "run_once", forbidden)
    app, ledger, _, _, _ = _input(ui, tmp_path)
    _submit(app)
    widget(app.button, "前往运行结果").click().run()
    widget(app.button, "执行已授权的分析任务").click().run()
    assert not app.exception and any("可用内存" in error.value for error in app.error)
    task = TaskQueue(ledger.workspace).list()[0]
    assert task["status"] == "queued" and task["attempt"] == 0
    assert ledger.list_records("analysis_process_started") == []
    assert ledger.list_records("analysis_preparation") == []


def test_queue_wait_is_visible_and_does_not_claim_success(ui, tmp_path, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * 1024**3, available=8 * 1024**3))
    app, ledger, _, _, _ = _input(ui, tmp_path)
    TaskQueue(ledger.workspace).submit("synthetic-earlier-job", {}, {},
        {"max_calls": 0, "max_tokens": 0, "max_cost": 0}, "earlier-job")
    _submit(app)
    widget(app.button, "前往运行结果").click().run()
    widget(app.button, "执行已授权的分析任务").click().run()
    assert not app.exception and any("更早的任务" in warning.value for warning in app.warning)
    assert all(task["attempt"] == 0 for task in TaskQueue(ledger.workspace).list())


def test_execution_failure_is_visible_and_refresh_never_retries(ui, tmp_path, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * 1024**3, available=8 * 1024**3))
    dispatches = []
    def fail_before_science(self, task):
        dispatches.append(task["task_id"])
        raise RuntimeError("synthetic_runtime_missing_before_fit")
    monkeypatch.setattr(AnalysisService, "_execute_supervised", fail_before_science)
    app, ledger, _, _, _ = _input(ui, tmp_path)
    _submit(app)
    widget(app.button, "前往运行结果").click().run()
    widget(app.button, "执行已授权的分析任务").click().run()
    assert not app.exception and len(dispatches) == 1
    assert any("synthetic_runtime_missing_before_fit" in item.value for item in app.text)
    assert TaskQueue(ledger.workspace).list()[0]["status"] == "failed"
    widget(app.button, "刷新分析状态").click().run()
    assert not app.exception and len(dispatches) == 1
    assert not any(button.label == "执行已授权的分析任务" for button in app.button)


def test_results_show_current_validated_metrics_and_hide_them_after_corruption(ui, tmp_path):
    from tests.test_workbench_result_summary import make_summary_fixture
    app, ledger = ui
    # Synthetic receipts exercise the actual saved-output validator, not a mocked summary.
    (tmp_path / "results").mkdir()
    fixture = make_summary_fixture(tmp_path / "results")
    import os
    previous = os.environ["SCKG_WORKBENCH_HOME"]
    os.environ["SCKG_WORKBENCH_HOME"] = str(fixture["service"].workspace.root)
    try:
        page(app, "运行结果")
        assert not app.exception
        assert widget(app.metric, "预览细胞数").value == "400"
        assert widget(app.metric, "预测为双细胞").value == "4"
        assert widget(app.metric, "预测调用比例").value == "1.0%"
        (fixture["outputs"] / "doublet_results.tsv").write_text("corrupted fixture")
        widget(app.button, "刷新分析状态").click().run()
        assert not app.exception and not app.metric
        assert any("未通过" in warning.value for warning in app.warning)
    finally:
        os.environ["SCKG_WORKBENCH_HOME"] = previous
