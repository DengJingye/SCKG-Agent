"""Workflow chat rendering and opt-in controls with synthetic development text.

These are component AppTests. They do not establish a full installed-workbench
journey, provider execution, model interpretation accuracy or scientific benefit.
"""
import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.ui import _workflow_catalog_options
from sckg_workbench.workflow_inputs import WorkflowInputService
from tests.test_workbench_workflow_inputs_ui import _snapshot, kb, workflow


def _show_turn(view):
    from types import SimpleNamespace
    from sckg_workbench.ui import _display_chat_turn
    chat = SimpleNamespace(view_turn=lambda unused: view)
    _display_chat_turn(chat, view["id"])


def _visible(app):
    return "\n".join(str(item.value) for group in (app.text, app.caption, app.info, app.warning, app.error)
                     for item in group)


def _view(workflow, value):
    options = _workflow_catalog_options(workflow.ledger)
    result = WorkflowInputService(workflow.ledger, workflow.workflow_catalog,
                                 expected_catalog_hash=options["catalog_hash"]).evaluate(
                                     ["synthetic_0"], {"reported_inputs": {"counts": value}})
    quote = {None: "合成用户原话：counts 是否具备尚未说明", False: "合成用户原话：没有 counts",
             True: "合成用户原话：有 counts"}[value]
    return {"id": "synthetic-ui-display-only", "prompt": quote,
        "status": "succeeded", "current_status": "succeeded", "usable": True,
        "answer": "<script>not executable</script> **合成显示段落，未执行分析**",
        "workflow_options": options,
        "workflow_run": {"scope": "synthetic renderer input, not a model run"},
        "workflow_review": result,
        "workflow_interpretations": [{"premise_id": "P1", "report_pointer": "/reported_inputs/counts",
            "reported_value": value, "user_turn_id": "synthetic-original-user-turn", "quote": quote,
            "unicode_spans": [{"start": 0, "end": len(quote)}],
            "call_id": "synthetic-renderer-no-provider-call",
            "semantic_origin": "model_extracted_user_text_not_independently_verified"}],
        "agent_budget": {"actual_receipted_call_count": 0}, "agent_steps": [], "receipts": [],
        "evidence_package": {"units": []}, "profile_id": "synthetic-display-only-profile"}


@pytest.mark.parametrize("value,precondition,action", [
    (None, "尚未说明", "仍需输入信息"),
    (False, "报告不具备", "当前报告输入阻塞"),
    (True, "报告具备", "仅可保留条件计划"),
])
def test_workflow_chat_renders_actual_review_states_separately_from_safe_prose(workflow, value, precondition, action):
    view = _view(workflow, value)
    before = _snapshot(workflow.ledger)
    app = AppTest.from_function(_show_turn, args=(view,)).run()
    assert not app.exception and not app.error and not app.success
    assert "输入前提：" + precondition in _visible(app)
    assert "拟议动作：" + action in _visible(app)
    assert "未授权，未执行" in _visible(app)
    assert "完整科学适用性：尚未建立" in _visible(app)
    assert "来源事实支持：本预览不重新作科学判断（no_claim）" in _visible(app)
    assert view["answer"] in _visible(app)
    assert all(view["answer"] != str(item.value) for item in app.markdown)
    assert "模型一般知识与推理 · 未经本地证据核验" not in _visible(app)
    assert "synthetic-original-user-turn" in _visible(app)
    assert "synthetic-renderer-no-provider-call" in _visible(app)
    assert "[0, " + str(len(view["prompt"])) + ")" in _visible(app)
    app.run()
    app.run()
    assert not app.exception and not app.success and _snapshot(workflow.ledger) == before


def test_unusable_workflow_view_hides_even_present_cached_review_prose_and_interpretations(workflow):
    view = _view(workflow, False)
    view.update(usable=False, current_status="evidence_invalidated")
    app = AppTest.from_function(_show_turn, args=(view,)).run()
    assert not app.exception and not app.success
    assert "已隐藏内容" in _visible(app)
    assert view["answer"] not in _visible(app)
    assert "Synthetic route 0" not in _visible(app)
    assert "synthetic-original-user-turn" not in _visible(app)
    assert "输入前提：报告不具备" not in _visible(app)


def test_valid_hash_bound_catalog_options_do_not_create_release_or_model_activity(workflow):
    before = _snapshot(workflow.ledger)
    assert _workflow_catalog_options(workflow.ledger) == {
        "catalog_record_id": workflow.workflow_configured["record_id"],
        "catalog_hash": workflow.workflow_configured["catalog_hash"]}
    assert _snapshot(workflow.ledger) == before
    assert workflow.ledger.list_records("release") == []
    assert workflow.ledger.list_records("review") == []
    assert workflow.ledger.list_records("model_request") == []


@pytest.mark.parametrize("configuration", [None, "not-a-pointer", {},
    {"record_id": "absent", "catalog_hash": "0" * 64},
    {"record_id": "synthetic-ui-workflow-catalog", "catalog_hash": "0" * 64},
    {"record_id": "synthetic-ui-workflow-catalog", "catalog_hash": "0" * 64, "path": "/tmp/not-a-catalog"},
])
def test_missing_or_changed_catalog_cannot_enable_workflow_chat(workflow, configuration):
    workflow.ledger.set_state("workflow_input_catalog", configuration)
    before = _snapshot(workflow.ledger)
    assert _workflow_catalog_options(workflow.ledger) is None
    assert _snapshot(workflow.ledger) == before


def _mode_controls():
    import streamlit as st
    from sckg_workbench.ui import _research_analysis_mode_changed
    for key in ("research_grounded_mode", "research_analysis_enabled", "research_result_read_enabled", "research_workflow_enabled"):
        st.checkbox(key, key=key, on_change=_research_analysis_mode_changed, args=(key,))


@pytest.mark.parametrize("selected", ["research_grounded_mode", "research_analysis_enabled",
                                     "research_result_read_enabled", "research_workflow_enabled"])
def test_workflow_and_existing_mode_callbacks_are_mutually_exclusive(selected):
    app = AppTest.from_function(_mode_controls).run()
    for key in ("research_workflow_enabled", "research_grounded_mode", selected):
        app.checkbox(key=key).check().run()
        assert not app.exception
        assert all(widget.value is (widget.key == key) for widget in app.checkbox)
