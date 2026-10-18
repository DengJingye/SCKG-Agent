"""Versioned report presence rendering over source-bound synthetic fixtures.

AppTest checks UI semantics and read-only behavior, not model extraction accuracy
or scientific applicability. No provider, network or analysis call is allowed.
"""
import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.storage import content_hash
from sckg_workbench.workflow_inputs import WorkflowInputService, REPORTED_INPUT_STATE_VERSION
from tests.test_workbench_workflow_inputs_ui import workflow, _snapshot, _ui, _visible
from tests.test_workbench_knowledge import kb


STRUCTURED = "explicit_structured_user_report_not_measurement"
MODEL = "model_extracted_user_text_not_independently_verified"


def _render(result):
    from sckg_workbench.workflow_inputs_ui import render_workflow_review
    render_workflow_review(result)


def _result(workflow, present, value, origin, *, new=True):
    service = WorkflowInputService(workflow.ledger, workflow.workflow_catalog,
        expected_catalog_hash=content_hash(workflow.workflow_catalog))
    profile = {"reported_inputs": {"counts": value} if present else {}}
    options = {"review_version": REPORTED_INPUT_STATE_VERSION} if new else {}
    return service.evaluate(["synthetic_0"], profile, report_origin=origin, **options)


@pytest.fixture(autouse=True)
def forbid_execution(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Report presence rendering must not dispatch or execute")
    monkeypatch.setattr("sckg_workbench.analysis.AnalysisService.submit_scrublet", denied)
    monkeypatch.setattr("sckg_workbench.analysis.AnalysisService.run_once", denied)
    monkeypatch.setattr("sckg_workbench.worker.Worker.run_once", denied)


@pytest.mark.parametrize("origin,present,value,expected", [
    (STRUCTURED, False, None, "结构化输入声明：本次结构化报告未提交该字段（状态未确认）"),
    (STRUCTURED, True, None, "结构化输入声明：该项已提交，状态未确认"),
    (STRUCTURED, True, False, "结构化输入声明：明确没有"),
    (STRUCTURED, True, True, "结构化输入声明：声明具备"),
    (MODEL, False, None, "模型提取状态：本次检查尚未绑定该项报告（状态未确认）"),
    (MODEL, True, None, "模型提取状态：已提交该项提取，输入状态未确认"),
    (MODEL, True, False, "模型提取状态：明确没有"),
    (MODEL, True, True, "模型提取状态：声明具备"),
])
def test_new_review_separates_report_presence_state_and_origin(workflow, origin, present, value, expected):
    before = _snapshot(workflow.ledger)
    result = _result(workflow, present, value, origin)
    assert result["schema_version"] == "workflow-reported-input-review-v2"
    app = AppTest.from_function(_render, args=(result,)).run()
    visible = _visible(app)
    assert not app.exception and expected in visible
    state = "状态未确认" if value is None else "报告具备" if value else "报告不具备"
    assert "输入前提：" + state in visible
    if value is None:
        assert "至少一项已列输入状态未确认；需补充信息。" in visible
        assert "尚未明确报告" not in visible and "输入前提：尚未说明" not in visible
        assert "用户没有提供" not in visible and "没有原话" not in visible
        assert "原话缺失" not in visible
        if present:
            assert "尚未绑定该项报告" not in visible and "未提交该字段" not in visible
    if origin == MODEL:
        assert "提取状态尚未独立核验" in visible
        assert "用户声明：" not in visible
    else:
        assert "模型提取状态：" not in visible
    assert "未授权，未执行" in visible and "完整科学适用性：尚未建立" in visible
    assert result["model_calls"] == result["scientific_fits"] == 0
    app.run()
    app.run()
    assert not app.exception and _snapshot(workflow.ledger) == before
    assert not workflow.ledger.list_records("model_call") and not workflow.ledger.list_records("release")


@pytest.mark.parametrize("origin", [STRUCTURED, MODEL])
@pytest.mark.parametrize("present", [True, False])
def test_legacy_review_keeps_historical_unknown_wording_and_reasons(workflow, origin, present):
    before = _snapshot(workflow.ledger)
    result = _result(workflow, present, None, origin, new=False)
    assert result["schema_version"] == "workflow-reported-input-review-v1"
    app = AppTest.from_function(_render, args=(result,)).run()
    assert not app.exception
    visible = _visible(app)
    assert "输入前提：尚未说明" in visible
    assert "至少一项已列输入尚未明确报告；需补充信息。" in visible
    assert ("模型提取的用户报告：未说明" if origin == MODEL else "用户声明：未说明") in visible
    assert "输入前提：状态未确认" not in visible
    assert _snapshot(workflow.ledger) == before


def test_new_review_preserves_full_source_conditions_unknowns_and_identity(workflow):
    result = _result(workflow, True, None, STRUCTURED)
    before = _snapshot(workflow.ledger)
    app = AppTest.from_function(_render, args=(result,)).run()
    visible = _visible(app)
    assert not app.exception
    assert "原文依据：SyntheticMethod requires counts" in visible
    assert "该来源的适用条件：Synthetic fixture only" in visible
    assert "该来源保留的未知项：No scientific validity is implied" in visible
    assert "该输入的限定：synthetic engineering fixture, not scientific gold" in visible
    assert "<script>not executable</script> **not reviewed**" in visible
    assert workflow.workflow_candidate["id"] in visible
    assert workflow.workflow_source["source_revision_id"] in visible
    assert "结果哈希：" + result["result_hash"] in visible
    assert all("<script>" not in str(item.value) for item in app.markdown)
    assert _snapshot(workflow.ledger) == before


def test_new_preview_refresh_and_invalidation_never_recheck_or_dispatch(workflow, monkeypatch):
    calls = []
    original = WorkflowInputService.evaluate
    def counted(self, routes, profile, **kwargs):
        assert kwargs == {"review_version": REPORTED_INPUT_STATE_VERSION}
        calls.append((routes, profile))
        return original(self, routes, profile, **kwargs)
    monkeypatch.setattr(WorkflowInputService, "evaluate", counted)
    before = _snapshot(workflow.ledger)
    app = _ui(workflow.ledger)
    assert not app.exception and calls == []
    app.button[0].click().run()
    assert not app.exception and len(calls) == 1
    assert "结构化输入声明：该项已提交，状态未确认" in _visible(app)
    assert "模型提取状态：" not in _visible(app)
    app.run()
    app.run()
    assert len(calls) == 1 and _snapshot(workflow.ledger) == before
    app.selectbox[0].set_value("声明具备").run()
    assert "旧结果已隐藏" in _visible(app)
    assert "结构化输入声明：该项已提交，状态未确认" not in _visible(app)
    assert len(calls) == 1 and _snapshot(workflow.ledger) == before
    app.button[0].click().run()
    assert not app.exception and len(calls) == 2
    assert "结构化输入声明：声明具备" in _visible(app)
    workflow.knowledge.suspend("candidate", workflow.workflow_candidate["id"],
        actor="synthetic-presence-ui-fixture", reason="read-only stale preview check")
    after_suspend = _snapshot(workflow.ledger)
    app.run()
    app.run()
    assert not app.exception and "旧结果已隐藏" in _visible(app)
    assert "结构化输入声明：声明具备" not in _visible(app)
    assert len(calls) == 2 and _snapshot(workflow.ledger) == after_suspend
