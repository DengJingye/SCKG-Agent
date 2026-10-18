"""Real AppTest + source-bound candidate checks in temporary workspaces.

The source and catalog are synthetic development fixtures. These tests establish
interaction/governance behavior, not scientific entailment or knowledge benefit.
"""
from copy import deepcopy

import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.storage import content_hash
from sckg_workbench.workflow_inputs import WorkflowInputCatalog, WorkflowInputService
from tests.test_workbench_knowledge import candidate, kb


def _render(root):
    from pathlib import Path
    from sckg_workbench.storage import Ledger, Workspace
    from sckg_workbench.workflow_inputs_ui import render_workflow_inputs
    render_workflow_inputs(Ledger(Workspace(Path(root))))


def _ui(ledger):
    return AppTest.from_function(_render, args=(str(ledger.workspace.root),), default_timeout=15).run()


def _visible(app):
    return "\n".join(str(item.value) for group in (app.text, app.caption, app.info, app.warning, app.error)
                     for item in group)


def _snapshot(ledger):
    with ledger.connect() as conn:
        return {table: [tuple(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY rowid")]
                for table in ("records", "state", "events")}


@pytest.fixture
def workflow(kb, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only workflow preview attempted a model or network call")
    monkeypatch.setattr("sckg_workbench.model_service.ModelService.invoke", forbidden)
    monkeypatch.setattr("sckg_workbench.model_service.ModelService.embed", forbidden)
    monkeypatch.setattr("sckg_workbench.sources.fetch_public_url", forbidden)
    text = "SyntheticMethod requires counts for this synthetic fixture only."
    unit, source, _ = candidate(kb, text=text, claim_updates={"typed_attributes": [{
        "name": "workflow.input", "value": "counts", "evidence_anchor_indices": [0],
        "qualifiers": ["synthetic engineering fixture, not scientific gold"]}]})
    binding = {"candidate_id": unit["id"], "candidate_hash": unit["content_hash"],
               "attribute_index": 0, "attribute_hash": content_hash(unit["claim"]["typed_attributes"][0])}
    catalog = WorkflowInputCatalog.model_validate({
        "schema_version": "development-workflow-input-catalog-v1",
        "authority": "developer_source_interpretation_not_human_review",
        "routes": [{"route_id": "synthetic_" + str(index), "label": "Synthetic route " + str(index),
                    "requirements": [{"requirement_id": "counts", "label": "Synthetic counts availability",
                                      "report_pointer": "/reported_inputs/counts", "source_bindings": [binding]}],
                    "context_candidate_ids": [], "requirements_complete": False,
                    "scope_notes": ["Fixture scope <script>not executable</script> **not reviewed**"]}
                   for index in range(5)]}).model_dump(mode="json")
    digest = content_hash(catalog)
    record_id = "synthetic-ui-workflow-catalog"
    kb.ledger.put_record("workflow_input_catalog", record_id,
                        {"id": record_id, "catalog": catalog, "catalog_hash": digest})
    configured = {"record_id": record_id, "catalog_hash": digest}
    kb.ledger.set_state("workflow_input_catalog", configured)
    kb.workflow_catalog = catalog
    kb.workflow_configured = configured
    kb.workflow_candidate = unit
    kb.workflow_source = source
    return kb


def test_no_opt_in_catalog_shows_nothing_and_changes_no_ledger_rows(workflow):
    workflow.ledger.set_state("workflow_input_catalog", None)
    before = _snapshot(workflow.ledger)
    app = _ui(workflow.ledger)
    assert not app.exception and not app.subheader and not app.button and not app.selectbox
    assert _snapshot(workflow.ledger) == before


def test_unknown_absent_and_reported_present_are_distinct_without_science_or_execution_claim(workflow, monkeypatch):
    calls = []
    original = WorkflowInputService.evaluate
    def counted(self, route_ids, profile, **kwargs):
        assert kwargs == {"review_version": "reported_input_state_v2"}
        calls.append(deepcopy(profile))
        return original(self, route_ids, profile, **kwargs)
    monkeypatch.setattr(WorkflowInputService, "evaluate", counted)
    before = _snapshot(workflow.ledger)
    app = _ui(workflow.ledger)
    assert not app.exception and len(calls) == 0
    assert app.selectbox[0].value == "未说明"
    app.button[0].click().run()
    assert not app.exception and len(calls) == 1
    assert calls[-1] == {"reported_inputs": {"counts": None}}
    assert "输入前提：状态未确认" in _visible(app)
    assert "来源事实支持：本预览不重新作科学判断（no_claim）" in _visible(app)
    assert "未授权，未执行" in _visible(app)
    app.run()
    assert not app.exception and len(calls) == 1
    app.selectbox[0].set_value("明确没有").run()
    assert "旧结果已隐藏" in _visible(app) and "输入前提：状态未确认" not in _visible(app)
    assert len(calls) == 1
    app.button[0].click().run()
    assert not app.exception and "输入前提：报告不具备" in _visible(app)
    assert "当前报告输入阻塞" in _visible(app) and calls[-1]["reported_inputs"]["counts"] is False
    app.selectbox[0].set_value("声明具备").run()
    assert "旧结果已隐藏" in _visible(app)
    app.button[0].click().run()
    assert not app.exception and "输入前提：报告具备" in _visible(app)
    assert "仅可保留条件计划" in _visible(app) and calls[-1]["reported_inputs"]["counts"] is True
    assert "完整科学适用性：尚未建立" in _visible(app)
    assert not app.success and _snapshot(workflow.ledger) == before
    assert workflow.knowledge.search("SyntheticMethod").units == []
    assert workflow.ledger.list_records("model_call") == []
    assert workflow.ledger.list_records("release") == []


@pytest.mark.parametrize("configured", [
    {"record_id": "absent", "catalog_hash": "0" * 64},
    {"record_id": "synthetic-ui-workflow-catalog", "catalog_hash": "0" * 64},
    {"record_id": "synthetic-ui-workflow-catalog", "catalog_hash": "0" * 64, "path": "/tmp/untrusted"},
])
def test_missing_tampered_or_path_based_catalog_is_unavailable_without_mutation(workflow, configured):
    workflow.ledger.set_state("workflow_input_catalog", configured)
    before = _snapshot(workflow.ledger)
    app = _ui(workflow.ledger)
    assert not app.exception and app.error and "开发输入检查不可用" in _visible(app)
    assert not app.button and not app.selectbox and _snapshot(workflow.ledger) == before


def test_route_changes_hide_old_result_and_shared_report_field_has_one_widget(workflow):
    app = _ui(workflow.ledger)
    app.button[0].click().run()
    assert "输入前提：状态未确认" in _visible(app)
    app.multiselect[0].set_value(["synthetic_0", "synthetic_1"]).run()
    assert not app.exception and "旧结果已隐藏" in _visible(app)
    assert len(app.selectbox) == 1
    app.button[0].click().run()
    assert not app.exception and _visible(app).count("本机执行：尚未绑定执行合同和数据") == 2
    app.multiselect[0].set_value([]).run()
    assert not app.exception and not app.button and "本机执行：" not in _visible(app)
    assert app.multiselect[0].proto.max_selections == 4


def test_candidate_suspension_hides_saved_result_and_recheck_refuses_it(workflow):
    app = _ui(workflow.ledger)
    app.selectbox[0].set_value("声明具备").run()
    app.button[0].click().run()
    assert "输入前提：报告具备" in _visible(app)
    workflow.knowledge.suspend("candidate", workflow.workflow_candidate["id"],
                               actor="synthetic-governance-fixture", reason="UI invalidation check")
    before = _snapshot(workflow.ledger)
    app.run()
    assert not app.exception and "旧结果已隐藏" in _visible(app)
    assert "输入前提：报告具备" not in _visible(app)
    app.button[0].click().run()
    assert not app.exception and "输入检查未完成" in _visible(app)
    assert "输入前提：报告具备" not in _visible(app) and _snapshot(workflow.ledger) == before


def test_candidate_text_is_literal_and_source_provenance_is_visible(workflow):
    before = _snapshot(workflow.ledger)
    app = _ui(workflow.ledger)
    app.button[0].click().run()
    assert not app.exception
    assert "<script>not executable</script> **not reviewed**" in _visible(app)
    assert workflow.workflow_candidate["id"] in _visible(app)
    assert workflow.workflow_source["source_revision_id"] in _visible(app)
    assert "SyntheticMethod requires counts" in _visible(app)
    assert "该来源的适用条件：Synthetic fixture only" in _visible(app)
    assert "该来源保留的未知项：No scientific validity is implied" in _visible(app)
    assert "该输入的限定：synthetic engineering fixture, not scientific gold" in _visible(app)
    assert "原文依据：SyntheticMethod requires counts" in _visible(app)
    assert all("<script>" not in str(item.value) for item in app.markdown)
    assert _snapshot(workflow.ledger) == before
