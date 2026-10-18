"""Grounded chat UI contracts; synthetic views/transports only, no provider or fit."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.chat import ChatService
from sckg_workbench.datasets import DatasetService
from tests.test_workbench_ui import (
    ui, _configure_synthetic_chat, _readonly_result_selection_ui_fixture, widget,
    _capture_chat_submission,
)


def test_grounded_mode_is_explicit_and_default_chat_send_remains_ordinary(ui, monkeypatch):
    app, ledger = ui
    _, calls = _configure_synthetic_chat(ui, monkeypatch)
    sent = []
    _capture_chat_submission(monkeypatch, sent)
    assert app.checkbox(key="research_grounded_mode").value is False
    app.chat_input(key="research_prompt").set_value("Synthetic ordinary question").run()
    assert not app.exception and len(sent) == 1
    assert sent[0]["grounded_mode"] is False
    assert sent[0]["analysis_options"] is None and sent[0]["result_ref"] is None
    assert calls == [] and ledger.list_records("model_call") == []


def test_grounded_mode_sends_explicit_flag_and_clear_budget_caption(ui, monkeypatch):
    app, _ = ui
    _, calls = _configure_synthetic_chat(ui, monkeypatch)
    sent = []
    _capture_chat_submission(monkeypatch, sent)
    app.checkbox(key="research_grounded_mode").check().run()
    assert not app.exception and app.checkbox(key="research_grounded_mode").value is True
    assert any("最多 3 次请求" in item.value and "费用按本轮累计" in item.value for item in app.caption)
    app.chat_input(key="research_prompt").set_value("Synthetic grounded question").run()
    assert not app.exception and len(sent) == 1 and sent[0]["grounded_mode"] is True
    assert sent[0]["use_knowledge"] is True and sent[0]["analysis_options"] is None
    app.run()
    assert len(sent) == 1 and calls == []


def test_disabling_knowledge_clears_grounded_mode_and_does_not_restore_it(ui, monkeypatch):
    app, _ = ui
    _configure_synthetic_chat(ui, monkeypatch)
    app.checkbox(key="research_grounded_mode").check().run()
    app.checkbox(key="research_use_knowledge").uncheck().run()
    assert not app.exception
    assert app.checkbox(key="research_grounded_mode").disabled
    assert app.checkbox(key="research_grounded_mode").value is False
    app.checkbox(key="research_use_knowledge").check().run()
    assert not app.checkbox(key="research_grounded_mode").disabled
    assert app.checkbox(key="research_grounded_mode").value is False


def test_grounded_mode_is_excluded_from_analysis_and_result_read_requests(ui, monkeypatch):
    app, _, first, _, choices, sent, calls = _readonly_result_selection_ui_fixture(ui, monkeypatch)
    monkeypatch.setattr(DatasetService, "list_assets", lambda self: [
        {"asset_id": "synthetic-ui-asset", "label": "Synthetic fixture only"}])
    app.run()
    app.checkbox(key="research_grounded_mode").check().run()
    app.checkbox(key="research_analysis_enabled").check().run()
    assert not app.exception and app.checkbox(key="research_grounded_mode").value is False
    assert app.checkbox(key="research_grounded_mode").disabled
    app.checkbox(key="research_analysis_enabled").uncheck().run()
    app.checkbox(key="research_grounded_mode").check().run()
    app.checkbox(key="research_result_read_enabled").check().run()
    assert not app.exception and app.checkbox(key="research_grounded_mode").value is False
    app.selectbox(key="research_result_ref").set_value(choices[first["id"]][0]["result_ref"]).run()
    app.chat_input(key="research_prompt").set_value("Read synthetic old result").run()
    assert not app.exception and len(sent) == 1
    assert sent[0]["grounded_mode"] is False and sent[0]["analysis_options"] is None
    assert sent[0]["result_ref"] == choices[first["id"]][0]["result_ref"]
    assert calls == []


def _grounded_view():
    unit = {"candidate_id": "synthetic-cited-unit", "allowed_uses": ["explanation"],
        "claim": {"proposition": "Synthetic author statement only",
                  "conditions": ["FULL_ORIGINAL_CONDITION_A", "FULL_ORIGINAL_CONDITION_B"],
                  "unknowns": ["FULL_ORIGINAL_UNKNOWN"], "typed_attributes": []},
        "evidence": [{"filename": "synthetic-official-source.txt", "quote": "Synthetic exact source quote.",
                      "locator": {"section": "SYNTHETIC_ORIGINAL_SECTION", "line_start": 12, "line_end": 15}}]}
    unreferenced = {"candidate_id": "synthetic-context-only", "claim": {"proposition": "Context fixture only"},
                    "evidence": []}
    normalized = {"decision": "SYNTHETIC_NORMALIZED_DECISION", "steps": [
        {"step_id": "s1", "factual_claim": "SYNTHETIC_FACT", "instruction": "SYNTHETIC_ACTION",
         "evidence_ids": [unit["candidate_id"]], "preconditions": ["SHORT_MODEL_PRECONDITION"], "scope": "source_bound"},
        {"step_id": "s2", "factual_claim": "", "instruction": "SYNTHETIC_UNVERIFIED_PROPOSAL",
         "evidence_ids": [], "preconditions": [], "scope": "proposal"}], "missing": ["SYNTHETIC_MISSING_INPUT"]}
    return {"id": "synthetic-grounded-turn", "prompt": "Synthetic question", "status": "succeeded",
            "current_status": "succeeded", "usable": True, "grounded_mode": True,
            "answer": "RAW_MODEL_TEXT_MUST_NOT_REPLACE_STRUCTURED_VIEW",
            "grounded_run": {"normalized_answer": normalized, "answer_run": {"answer": normalized}},
            "citation_manifest": {"schema_version": "chat-source-citations-v1",
                "validation": "selected_id_binding_only_not_semantic_support", "items": [
                    {"number": 1, "candidate_id": unit["candidate_id"], "alias": "E2", "unit": unit}]},
            "evidence_package": {"units": [unit, unreferenced]}, "notices": []}


def _render_grounded_view(view):
    def render(value):
        from types import SimpleNamespace
        from sckg_workbench.ui import _display_chat_turn
        _display_chat_turn(SimpleNamespace(view_turn=lambda stored: value), value)
    return AppTest.from_function(render, args=(view,)).run()


def test_grounded_render_uses_server_numbers_and_preserves_original_conditions():
    app = _render_grounded_view(_grounded_view())
    assert not app.exception
    text = "\n".join(str(item.value) for item in app.markdown)
    assert "SYNTHETIC_NORMALIZED_DECISION" in text and "SYNTHETIC_FACT" in text and "SYNTHETIC_ACTION" in text
    assert "RAW_MODEL_TEXT_MUST_NOT_REPLACE_STRUCTURED_VIEW" not in text
    assert "FULL_ORIGINAL_CONDITION_A" in text and "FULL_ORIGINAL_CONDITION_B" in text
    assert "FULL_ORIGINAL_UNKNOWN" in text and "SHORT_MODEL_PRECONDITION" in text
    assert "SYNTHETIC_MISSING_INPUT" in text
    assert any(item.label == "来源 [1] · 原文、完整条件与限制" for item in app.expander)
    assert not any(item.label.startswith("来源 [2]") for item in app.expander)
    assert any("本回答实际引用 1 条证据" in item.value for item in app.caption)
    assert any("SYNTHETIC_ORIGINAL_SECTION" in item.value and "12" in item.value for item in app.caption)
    assert any("待验证建议" in item.value for item in app.caption)


@pytest.mark.parametrize("invalid", ["unusable", "missing_manifest", "mismatched_candidate"])
def test_grounded_render_hides_invalid_or_unavailable_citation_mapping(invalid):
    view = deepcopy(_grounded_view())
    if invalid == "unusable":
        view.update(usable=False, answer=None, current_status="evidence_invalidated")
    elif invalid == "missing_manifest":
        view.pop("citation_manifest")
    else:
        view["citation_manifest"]["items"][0]["candidate_id"] = "unbound-candidate"
    app = _render_grounded_view(view)
    assert not app.exception
    text = "\n".join(str(item.value) for item in app.markdown)
    assert "SYNTHETIC_NORMALIZED_DECISION" not in text and "SYNTHETIC_FACT" not in text
    assert not any(item.label.startswith("来源 [") for item in app.expander)


def test_grounded_blocked_view_explains_missing_sources_and_shows_receipted_calls_safely():
    view = _grounded_view()
    view.update(status="blocked", current_status="blocked", usable=False, answer=None,
                error={"message": "RAW_EXCEPTION_MUST_NOT_BE_DISPLAYED"})
    view["grounded_run"] = {
        "error": {"reason_code": "no_retrieved_evidence", "message": "RAW_STOP_DETAIL_MUST_NOT_BE_DISPLAYED"},
        "agent_budget": {"model_calls": 1, "actual_receipted_call_count": 1, "max_model_calls": 3}}
    view.pop("citation_manifest")
    app = _render_grounded_view(view)
    assert not app.exception
    assert any("本轮未检索到可用来源" in item.value and "不代表所问命题为假" in item.value
               for item in app.warning)
    assert any("已记录 1 次回执" in item.value and "上限 3 次" in item.value for item in app.caption)
    visible = "\n".join(str(item.value) for group in (app.markdown, app.warning, app.error, app.caption) for item in group)
    assert "RAW_EXCEPTION_MUST_NOT_BE_DISPLAYED" not in visible
    assert "RAW_STOP_DETAIL_MUST_NOT_BE_DISPLAYED" not in visible
    assert not any(item.label.startswith("来源 [") for item in app.expander)
