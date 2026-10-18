"""Real Streamlit interactions in isolated temporary workspaces; no external calls."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import json
import re

import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.catalog import Catalog
from sckg_workbench.chat import ChatService
from sckg_workbench.model_service import ModelService
from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, canonical_json, content_hash
from sckg_workbench.tasks import TaskQueue
from sckg_workbench.ui import PAGES


APP = Path(__file__).resolve().parents[1] / "workbench_app.py"
INGEST_STAGES = ("来源与范围", "配置与抽取", "质量与分流", "合并与冲突", "变更与发布")


@pytest.fixture
def ui(monkeypatch, tmp_path):
    path = tmp_path / "isolated-workbench"
    monkeypatch.setenv("SCKG_WORKBENCH_HOME", str(path))
    def forbidden(*args, **kwargs):
        raise AssertionError("UI test attempted an external network call")
    monkeypatch.setattr("sckg_workbench.sources.fetch_public_url", forbidden)
    monkeypatch.setattr("sckg_workbench.model_service.http_transport", forbidden)
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception
    ledger = Ledger(Workspace(path))
    try:
        yield app, ledger
    finally:
        _join_chat_owner(ledger, required=False)


def _join_chat_owner(ledger, *, required=True):
    """Boundedly join only this workspace's explicitly launched real owner."""
    from sckg_workbench import chat_runs
    key = (str(ledger.workspace.root), ledger.workspace.namespace)
    with chat_runs._THREAD_LOCK:
        owner = chat_runs._THREADS.get(key)
    if required:
        assert owner is not None, "the UI send must launch its registered workspace owner"
    if owner is not None:
        owner.join(timeout=10)
        assert not owner.is_alive(), "this fixture workspace owner must finish within the bounded join"


def _finish_background_chat(app, ledger):
    _join_chat_owner(ledger)
    app.run()  # Refresh only: no explicit send and no provider retry.
    assert not app.exception


def _capture_chat_submission(monkeypatch, captured):
    """Parameter-wiring fixture: explicitly refuse launch; never fake execution.

    Real submission/authorization/owner journeys are exercised separately. A
    synthetic result_ref in these UI-only fixtures must not claim a real turn.
    """
    from sckg_workbench.chat_runs import ChatRunService

    def capture(self, conversation_id, prompt, **kwargs):
        captured.append({"conversation_id": conversation_id, "prompt": prompt, **kwargs})
        return {"id": "synthetic-ui-capture-" + str(len(captured)),
                "status": "fixture_parameter_capture_only"}

    def refuse_fixture_launch(self, turn_id, target, **kwargs):
        assert turn_id == "synthetic-ui-capture-" + str(len(captured))
        return {"dispatch_status": "fixture_refused_not_started"}

    monkeypatch.setattr(ChatService, "submit_send", capture)
    monkeypatch.setattr(ChatRunService, "launch", refuse_fixture_launch)


def widget(collection, label):
    return next(item for item in collection if item.label == label)


def page(app, value):
    app.radio(key="navigation").set_value(value).run()
    assert not app.exception


def stage(app, value):
    app.radio(key="ingest_stage").set_value(value).run()
    assert not app.exception


def test_empty_workspace_and_all_seven_pages_do_not_acquire_or_call_models(ui):
    app, ledger = ui
    assert app.radio(key="navigation").options == list(PAGES)
    for name in PAGES:
        page(app, name)
        assert not app.error
        assert any(title.value == name for title in app.title)
    assert ledger.list_records("source") == []
    assert ledger.list_records("candidate") == []
    assert ledger.list_records("model_call") == []
    assert ledger.list_records("release") == []
    assert len(Catalog(ledger).seeds()) == 16


def test_real_source_parsing_is_visible_without_scientific_promotion(ui):
    app, ledger = ui
    source = SourceService(ledger).register_bytes("fixture.md", b"# Local fixture\n\nAn explicitly synthetic document.")
    page(app, "入库工作台")
    widget(app.button, "解析所选原件").click().run()
    assert not app.exception
    irs = ledger.list_records("document_ir")
    assert len(irs) == 1 and irs[0]["source_id"] == source["id"]
    assert irs[0]["status"] == "complete"
    assert any("本次文本解析完成" in item.value for item in app.success)
    assert any("Local fixture" in item.value for item in app.code)
    assert ledger.list_records("candidate") == []


def test_url_import_requires_explicit_network_checkbox(ui):
    app, ledger = ui
    page(app, "入库工作台")
    widget(app.text_input, "公开来源 URL").set_value("https://example.com/paper.html")
    widget(app.button, "获取并登记链接").click().run()
    assert not app.exception
    assert any("allow_network" in item.value for item in app.error)
    assert ledger.list_records("source") == []


def test_connection_profile_and_session_unlock_are_real_but_do_not_call_models(ui):
    app, ledger = ui
    page(app, "设置")
    for label, value in {"连接名称": "UI test", "API base URL": "https://provider.example/v1",
                         "API key": "dummy-ui-secret", "加密口令（至少 8 位）": "ui-test-passphrase"}.items():
        widget(app.text_input, label).set_value(value)
    widget(app.button, "加密保存连接").click().run()
    assert not app.exception
    connections = ledger.list_records("model_connection")
    assert len(connections) == 1 and connections[0]["name"] == "UI test"
    assert "dummy-ui-secret" not in (ledger.workspace.root / "secrets.vault").read_text()
    widget(app.text_input, "Profile 名称").set_value("UI extraction")
    widget(app.text_input, "准确模型名称").set_value("test-only-model")
    widget(app.button, "保存不可变用途 profile").click().run()
    assert not app.exception
    profile = ledger.list_records("model_profile")[0]
    assert profile["purpose"] == "extraction" and profile["model"] == "test-only-model"
    assert profile["input_usd_per_million"] is None
    widget(app.text_input, "会话解锁口令").set_value("wrong-passphrase")
    widget(app.button, "解锁当前会话").click().run()
    assert app.error and not app.exception
    widget(app.text_input, "会话解锁口令").set_value("ui-test-passphrase")
    widget(app.button, "解锁当前会话").click().run()
    assert not app.exception
    assert app.session_state["vault_passphrase"] == "ui-test-passphrase"
    app.run()  # The sidebar reflects session state on the next render.
    widget(app.button, "锁定会话口令").click().run()
    assert "vault_passphrase" not in app.session_state
    assert ledger.list_records("model_call") == []


def test_frozen_split_shows_actual_manifest_without_gold(ui):
    app, ledger = ui
    source = SourceService(ledger).register_bytes("holdout.txt", b"Synthetic split fixture.")
    split = Catalog(ledger).freeze_split([{"source_id": source["id"], "work_family": "test-work",
                                           "partition": "holdout", "prior_development_use": False}], reviewer="test reviewer")
    page(app, "质量评测")
    assert any("评测划分已冻结" in item.value for item in app.success)
    assert any(split["id"] in item.value for item in app.json)
    assert ledger.get_record("evaluation_split", split["id"])["gold_status"] == "not_created"


def test_dataset_page_registers_and_profiles_local_fixture_without_model_call(ui, tmp_path):
    import h5py
    import numpy as np

    app, ledger = ui
    path = tmp_path / "ui-fixture.h5ad"
    with h5py.File(path, "w") as handle:
        handle.attrs["encoding-type"] = "anndata"
        handle.create_dataset("X", data=np.arange(12).reshape(3, 4))
    original = path.read_bytes()
    page(app, "数据资产")
    widget(app.text_input, "本地 .h5ad 绝对路径").set_value(str(path))
    widget(app.button, "只读登记本地数据").click().run()
    assert not app.exception
    assets = ledger.list_records("dataset_asset")
    assert len(assets) == 1 and assets[0]["storage"] == "local_reference"
    widget(app.button, "建立有界只读画像").click().run()
    assert not app.exception
    profiles = ledger.list_records("dataset_profile")
    assert len(profiles) == 1 and profiles[0]["profile"]["dimensions"] == {"n_obs": 3, "n_vars": 4}
    assert path.read_bytes() == original
    assert ledger.list_records("model_call") == []


def test_external_rights_are_never_granted_by_browsing_or_unchecked_form(ui):
    app, ledger = ui
    source = SourceService(ledger).register_bytes("rights-fixture.txt", b"Synthetic evidence only.")
    page(app, "质量评测")
    assert ledger.list_records("source_export_review") == []
    widget(app.button, "预览当前可导出的知识包").click().run()
    assert not app.exception and ledger.list_records("source_export_review") == []
    widget(app.button, "保存许可审核").click().run()
    assert not app.exception and ledger.list_records("source_export_review") == []
    widget(app.text_input, "许可依据或权限记录").set_value("synthetic fixture permission")
    widget(app.text_input, "审核人").set_value("fixture-reviewer")
    widget(app.text_area, "判断依据和适用范围").set_value("Synthetic UI governance test")
    widget(app.checkbox, "我已核对该来源版本和许可范围").set_value(True)
    widget(app.button, "保存许可审核").click().run()
    reviews = ledger.list_records("source_export_review")
    assert not app.exception and len(reviews) == 1 and reviews[0]["source_id"] == source["id"]
    assert reviews[0]["claims_allowed"] is False


def test_task_cancel_updates_persistent_queue_without_worker_execution(ui):
    app, ledger = ui
    queue = TaskQueue(ledger.workspace)
    task = queue.submit("test-only-task", {}, {}, {"max_calls": 1, "max_tokens": 1000, "max_cost": 1}, "ui-test")
    page(app, "入库工作台")
    stage(app, "配置与抽取")
    widget(app.button, "请求取消所选任务").click().run()
    assert not app.exception
    assert queue.get(task["task_id"])["status"] == "cancelled"
    assert ledger.list_records("model_call") == []


def test_real_worker_submission_only_queues_fixed_source_and_profiles(ui):
    app, ledger = ui
    source = SourceService(ledger).register_bytes("extract-fixture.txt", b"Synthetic extraction input only.")
    models = ModelService(ledger.workspace, ledger)
    connection = models.create_connection("queue-fixture", "https://provider.example/v1", "not-a-real-key", "test-passphrase")
    profiles = {}
    for purpose in ("extraction", "assessment"):
        profiles[purpose] = models.create_profile(purpose, purpose, connection["id"], "fixture-model",
            input_usd_per_million=1, output_usd_per_million=2)
    page(app, "入库工作台")
    stage(app, "配置与抽取")
    widget(app.button, "提交真实抽取任务").click().run()
    assert not app.exception
    jobs = TaskQueue(ledger.workspace).list()
    assert len(jobs) == 1 and jobs[0]["status"] == "queued"
    assert jobs[0]["input_snapshot"]["source_id"] == source["id"]
    assert jobs[0]["profile_snapshot"]["extraction"]["id"] == profiles["extraction"]["id"]
    assert widget(app.button, "执行下一项已排队任务").disabled
    assert ledger.list_records("model_call") == []


class SyntheticKnowledgeUIFixture:
    """UI contract fixture only, never persisted as scientific knowledge."""
    def __init__(self):
        self.published = None
        self.reviewed = None
        self.assessment_suffix = "-assessment"
        self.review_suffix = "-review"

    def list_candidates(self):
        return [{"id": key, "claim": {"proposition": "Synthetic UI fixture " + key},
                 "content_hash": key + "-hash", "assessment": {"id": key + self.assessment_suffix},
                 "review": {"id": key + self.review_suffix, "decision": "approve", "assessment_id": key + self.assessment_suffix,
                            "allowed_uses": ["explanation"]}, "source_ids": []} for key in ("previous", "new")]

    def current_release(self):
        return {"id": "synthetic-release", "units": [{"candidate_id": "previous"}]}

    def evidence(self, candidate_id):
        return []

    def graph(self):
        return {"nodes": [], "edges": []}

    def search(self, query, *, purpose="explanation", limit=100):
        return SimpleNamespace(units=[])

    def publish(self, candidate_ids, **kwargs):
        self.published = (candidate_ids, kwargs)
        return {"id": "synthetic-next-release"}

    def review(self, candidate_id, **kwargs):
        self.reviewed = (candidate_id, kwargs)
        return {"id": "synthetic-review"}


def test_full_release_manifest_defaults_to_preserving_existing_members(ui, monkeypatch):
    app, _ = ui
    backend = SyntheticKnowledgeUIFixture()
    monkeypatch.setattr("sckg_workbench.ui._knowledge", lambda ledger: backend)
    page(app, "知识库")
    manifest = widget(app.multiselect, "完整新版本的知识清单")
    assert manifest.value == ["previous"]
    assert widget(app.button, "发布所选知识").disabled
    assert any("未选中的旧知识" in item.value for item in app.warning)
    manifest.set_value(["previous", "new"]).run()
    widget(app.text_input, "发布人").set_value("ui tester")
    widget(app.checkbox, "已核对以上完整清单及增删影响").check().run()
    widget(app.button, "发布所选知识").click().run()
    assert not app.exception
    assert backend.published == (["previous", "new"], {"actor": "ui tester", "expected_release_id": "synthetic-release",
                                                        "expected_review_ids": {"previous": "previous-review", "new": "new-review"}})


def test_review_binds_the_exact_assessment_visible_to_reviewer(ui, monkeypatch):
    app, _ = ui
    backend = SyntheticKnowledgeUIFixture()
    monkeypatch.setattr("sckg_workbench.ui._knowledge", lambda ledger: backend)
    page(app, "知识库")
    assert widget(app.selectbox, "审核决定").value == "defer"
    widget(app.text_input, "审核人").set_value("ui reviewer")
    widget(app.text_area, "审核理由").set_value("Synthetic UI contract only")
    widget(app.selectbox, "审核决定").set_value("approve")
    widget(app.multiselect, "允许用途").set_value(["explanation"])
    backend.assessment_suffix = "-new-assessment-created-after-view"
    widget(app.button, "保存确切修订的审核决定").click().run()
    assert not app.exception
    assert backend.reviewed[1]["expected_assessment_id"] == "previous-assessment"
    assert backend.reviewed[1]["expected_hash"] == "previous-hash"


def test_identical_propositions_keep_revision_selection_and_support_extent_distinct(ui, monkeypatch):
    app, ledger = ui
    backend = SyntheticKnowledgeUIFixture()
    backend.ledger = ledger
    original_list = backend.list_candidates

    def revisions():
        rows = original_list()
        for row in rows:
            row["claim"]["proposition"] = "Identical synthetic proposition, different evidence revision"
            row["assessment"]["result"] = {"relation": "support", "extent": "partial" if row["id"] == "previous" else "full"}
        return rows

    backend.list_candidates = revisions
    ledger.put_record("candidate_revision_proposal", "synthetic-revision", {
        "id": "synthetic-revision", "old_candidate_id": "previous", "new_candidate_id": "new",
        "status": "proposed_pending_human_review", "reason": "Synthetic UI regression only"})
    monkeypatch.setattr("sckg_workbench.ui._knowledge", lambda ledger: backend)
    page(app, "入库工作台")
    stage(app, "质量与分流")
    options = widget(app.selectbox, "候选知识").options
    assert len(set(options)) == 2
    for candidate_id, expected_extent in (("new", "完整"), ("previous", "部分")):
        widget(app.selectbox, "候选知识").set_value(candidate_id).run()
        assert not app.exception
        assert widget(app.selectbox, "候选知识").value == candidate_id
        assert any(c.value == "支持范围 · " + expected_extent for c in app.caption)
    assert any("已有修订提案" in w.value for w in app.warning)
    assert ledger.list_records("review") == []


def test_advanced_evidence_redisplay_revalidates_without_governance_event(ui, monkeypatch):
    app, ledger = ui
    class ResearchFixture(SyntheticKnowledgeUIFixture):
        valid = True
        searches = 0

        def current_release(self):
            return {"id": "fixture-release", "units": []}

        def search(self, query, *, purpose="explanation", limit):
            if limit == 100:
                return SimpleNamespace(units=[])
            self.searches += 1
            return {"namespace": ledger.workspace.namespace, "release_id": "fixture-release", "governance_version": 0,
                    "purpose": purpose, "units": [{"claim": {"proposition": "Synthetic UI evidence"}}] if self.valid else [],
                    "gaps": [] if self.valid else ["Original evidence damaged"], "retrieval": {"query": query}}
    backend = ResearchFixture()
    monkeypatch.setattr("sckg_workbench.ui._knowledge", lambda ledger: backend)
    page(app, "知识库")
    assert any(item.label == "高级证据检索" for item in app.expander)
    widget(app.text_input, "研究问题").set_value("Synthetic UI query")
    widget(app.button, "检索正式证据").click().run()
    assert not app.exception and backend.searches == 1
    backend.valid = False  # No version or governance change occurred.
    app.run()
    assert not app.exception and backend.searches == 2
    assert app.session_state["last_evidence_package"]["units"] == []
    assert any("未找到可用证据" in item.value for item in app.info)


def test_broken_candidate_evidence_does_not_hide_maintenance(ui, monkeypatch):
    app, _ = ui
    backend = SyntheticKnowledgeUIFixture()
    def damaged(candidate_id):
        raise ValueError("Synthetic original has been damaged")
    backend.evidence = damaged
    monkeypatch.setattr("sckg_workbench.ui._knowledge", lambda ledger: backend)
    page(app, "知识库")
    assert any("damaged" in item.value for item in app.error)
    assert widget(app.button, "记录维护决定") is not None
    assert not app.exception


def test_publish_review_change_invalidates_previous_confirmation(ui, monkeypatch):
    app, _ = ui
    backend = SyntheticKnowledgeUIFixture()
    monkeypatch.setattr("sckg_workbench.ui._knowledge", lambda ledger: backend)
    page(app, "知识库")
    widget(app.text_input, "发布人").set_value("ui publisher")
    widget(app.checkbox, "已核对以上完整清单及增删影响").check().run()
    assert not widget(app.button, "发布所选知识").disabled
    backend.review_suffix = "-new-review-after-preview"
    widget(app.button, "发布所选知识").click().run()
    assert not app.exception
    assert backend.published is None
    assert widget(app.button, "发布所选知识").disabled
    assert any("发布清单发生变化" in item.value for item in app.error)


def test_real_unapproved_candidate_is_visible_for_review_but_never_an_answer(ui):
    app, ledger = ui
    text = "UNPUBLISHED_SYNTHETIC_FACT exists only in this governance test."
    sources = SourceService(ledger)
    source = sources.register_bytes("unapproved-fixture.txt", text.encode())
    ir = sources.parse(source["id"])
    ledger.put_record("model_profile", "fixture-extraction-profile", {
        "id": "fixture-extraction-profile", "purpose": "extraction", "name": "Synthetic test", "model": "not-a-real-model"})
    knowledge = KnowledgeService(ledger)
    candidate = knowledge.add_candidate({"proposition": text, "subject": "SyntheticTest", "predicate": "asserts",
        "object": "fixture only", "polarity": "positive", "conditions": [], "unknowns": ["No scientific validity"],
        "anchors": [{"ir_id": ir["id"], "block_id": ir["blocks"][0]["id"], "start": 0, "end": len(text), "quote": text}]},
        run_id="synthetic-test-only", profile_id="fixture-extraction-profile")
    page(app, "知识库")
    assert widget(app.selectbox, "候选知识").value == candidate["id"]
    assert widget(app.selectbox, "审核决定").value == "defer"
    assert widget(app.button, "检索正式证据").disabled
    assert "last_evidence_package" not in app.session_state
    assert knowledge.search("UNPUBLISHED_SYNTHETIC_FACT").units == []
    assert ledger.list_records("review") == [] and ledger.list_records("release") == []


def test_five_ingestion_stages_are_explicit_and_navigation_has_no_side_effects(ui):
    app, ledger = ui
    page(app, "入库工作台")
    assert app.radio(key="ingest_stage").options == list(INGEST_STAGES)
    assert app.radio(key="ingest_stage").value == "来源与范围"
    for value in INGEST_STAGES:
        stage(app, value)
        assert not app.error
        assert app.radio(key="navigation").value == "入库工作台"
        assert app.radio(key="ingest_stage").value == value
        labels = {button.label for button in app.button}
        if value == "来源与范围":
            assert {"接收文件", "获取并登记链接", "获取并登记 GitHub 文件"} <= labels
        else:
            assert not {"接收文件", "获取并登记链接", "获取并登记 GitHub 文件"} & labels
    for kind in ("source", "acquisition", "document_ir", "model_call", "candidate", "review", "release"):
        assert ledger.list_records(kind) == []
    assert TaskQueue(ledger.workspace).list() == []


def test_context_shortcuts_navigate_to_the_actual_page_and_stage(ui):
    app, ledger = ui
    widget(app.button, "模型未配置").click().run()
    assert not app.exception and app.radio(key="navigation").value == "设置"
    page(app, "研究台")
    widget(app.button, "查看知识与关系").click().run()
    assert not app.exception and app.radio(key="navigation").value == "知识库"
    assert {tab.label for tab in app.tabs} >= {"知识单元", "来源资料", "图谱探索"}
    widget(app.button, "接入新资料").click().run()
    assert not app.exception and app.radio(key="navigation").value == "入库工作台"
    widget(app.button, "配置抽取方案").click().run()
    assert not app.exception and app.radio(key="ingest_stage").value == "配置与抽取"
    page(app, "运行结果")
    widget(app.button, "查看知识处理任务").click().run()
    assert not app.exception and app.radio(key="navigation").value == "入库工作台"
    assert app.radio(key="ingest_stage").value == "配置与抽取"
    assert ledger.list_records("source") == [] and ledger.list_records("model_call") == []


def test_run_results_preflight_reports_blockers_without_executing(ui):
    app, ledger = ui
    page(app, "运行结果")
    widget(app.button, "检查执行前提").click().run()
    assert not app.exception
    report = app.session_state["scrublet_readiness_report"]
    assert report["ready"] is False
    assert report["execution_attempted"] is False
    assert report["raw_data_modified"] is False
    assert "dataset_asset_missing" in report["blockers"]
    assert ledger.list_records("source") == []


def test_invalid_local_h5ad_shows_recoverable_error(ui, tmp_path):
    app, ledger = ui
    invalid = tmp_path / "invalid.h5ad"
    invalid.write_bytes(b"not an hdf5 file")
    page(app, "数据资产")
    widget(app.text_input, "本地 .h5ad 绝对路径").set_value(str(invalid))
    widget(app.button, "只读登记本地数据").click().run()
    assert not app.exception
    assert any("操作未完成" in item.value for item in app.error)
    assert ledger.list_records("dataset_asset") == []


def test_changed_source_can_be_staged_for_review_without_publication(ui):
    from sckg_workbench.source_watch import SourceUpdateService
    from sckg_workbench.sources import FetchResult

    app, ledger = ui
    url = "https://example.org/synthetic.md"
    source = SourceService(ledger).register_url(url, allow_network=True,
        fetcher=lambda requested, **kwargs: FetchResult(b"Synthetic original.", requested, "text/markdown"))
    check = SourceUpdateService(ledger).check(source["id"], allow_network=True,
        fetcher=lambda requested, **kwargs: FetchResult(b"Synthetic changed.", requested, "text/markdown"))
    page(app, "入库工作台")
    widget(app.text_input, "登记人").set_value("fixture reviewer")
    widget(app.text_area, "登记理由").set_value("Review changed bytes")
    widget(app.button, "登记为临时新来源").click().run()
    assert not app.exception and not app.error
    stage = ledger.list_records("source_update_stage")[0]
    assert stage["source_update_candidate_id"] == check["candidate_id"]
    assert stage["base_source_id"] == source["id"]
    assert len(ledger.list_records("source")) == 2
    assert ledger.list_records("release") == []


def test_saved_source_scope_survives_step_navigation_without_promoting_trust(ui):
    app, ledger = ui
    page(app, "入库工作台")
    widget(app.text_input, "来源身份／作品线索（待核验）").set_value("Synthetic project identity hint")
    widget(app.selectbox, "材料类型").set_value("官方文档与教程")
    widget(app.text_area, "目标用途与接入理由").set_value("Synthetic UI metadata only")
    widget(app.button, "保存来源说明").click().run()
    assert not app.exception and not app.error
    assert app.session_state["source_scope"] == {
        "identity_hint": "Synthetic project identity hint", "material_type": "官方文档与教程",
        "intended_use": "Synthetic UI metadata only"}
    stage(app, "配置与抽取")
    stage(app, "来源与范围")
    assert widget(app.text_input, "来源身份／作品线索（待核验）").value == "Synthetic project identity hint"
    assert widget(app.selectbox, "材料类型").value == "官方文档与教程"
    assert widget(app.text_area, "目标用途与接入理由").value == "Synthetic UI metadata only"
    for kind in ("source", "acquisition", "model_call", "review", "release"):
        assert ledger.list_records(kind) == []


def _synthetic_assessed_ui_candidate(ledger):
    """A local test receipt bound to exact test bytes; not a scientific gold item."""
    text = "SYNTHETIC_UI_GOVERNANCE_FIXTURE has a property within this test only."
    sources = SourceService(ledger)
    source = sources.register_bytes("synthetic-ui-governance.txt", text.encode())
    ir = sources.parse(source["id"])
    for purpose in ("extraction", "assessment"):
        ledger.put_record("model_profile", "ui-fixture-" + purpose, {
            "id": "ui-fixture-" + purpose, "purpose": purpose, "name": "Synthetic UI " + purpose,
            "model": "fixture-not-a-model", "input_usd_per_million": 1, "output_usd_per_million": 1})
    knowledge = KnowledgeService(ledger)
    claim = {"proposition": text, "subject": "SYNTHETIC_UI_GOVERNANCE_FIXTURE", "predicate": "has", "object": "test property",
        "polarity": "positive", "conditions": ["Synthetic UI test only"], "unknowns": ["No scientific validity"],
        "anchors": [{"ir_id": ir["id"], "block_id": ir["blocks"][0]["id"], "start": 0, "end": len(text), "quote": text}]}
    unit = knowledge.add_candidate(claim, run_id="synthetic-ui-run", profile_id="ui-fixture-extraction")
    result = {"relation": "support", "extent": "full", "rationale": "Synthetic UI receipt only.", "limitations": ["Not scientific validation"]}
    call_id = "ui-fixture-model-receipt"
    ledger.put_record("model_request", call_id, {"payload": {"messages": [
        {"role": "user", "content": canonical_json(knowledge.assessment_input(unit["id"]))}]}})
    ledger.put_record("model_call", call_id, {"call_id": call_id, "profile_id": "ui-fixture-assessment", "status": "succeeded",
        "structured_output_hash": content_hash(result), "synthetic_fixture": True})
    assessment = knowledge.assess(unit["id"], result, run_id="synthetic-ui-assessment", profile_id="ui-fixture-assessment", call_id=call_id)
    return knowledge, unit, source, assessment


def test_ingestion_step_controls_show_only_the_selected_stage(ui):
    app, ledger = ui
    knowledge, unit, _, assessment = _synthetic_assessed_ui_candidate(ledger)
    knowledge.review(unit["id"], actor="synthetic fixture reviewer", decision="approve", allowed_uses=["explanation"],
        reason="UI fixture only", expected_hash=unit["content_hash"], expected_assessment_id=assessment["id"])
    TaskQueue(ledger.workspace).submit("ui-stage-fixture", {}, {}, {"max_calls": 1, "max_tokens": 1000, "max_cost": 1}, "ui-stage-fixture")
    expected_actions = {
        "来源与范围": {"解析所选原件", "接收文件"},
        "配置与抽取": {"提交真实抽取任务", "请求取消所选任务"},
        "质量与分流": {"保存确切修订的审核决定"},
        "合并与冲突": set(),
        "变更与发布": {"发布所选知识"},
    }
    all_actions = set().union(*expected_actions.values())
    calls_before = ledger.list_records("model_call")
    reviews_before = ledger.list_records("review")
    page(app, "入库工作台")
    for value, expected in expected_actions.items():
        stage(app, value)
        assert not app.error
        labels = {button.label for button in app.button}
        assert labels & all_actions == expected
    assert ledger.list_records("model_call") == calls_before
    assert ledger.list_records("review") == reviews_before
    assert ledger.list_records("release") == []
    assert TaskQueue(ledger.workspace).list()[0]["status"] == "queued"


def test_real_review_publish_search_and_suspend_survive_new_ingestion_layout(ui):
    app, ledger = ui
    knowledge, unit, source, assessment = _synthetic_assessed_ui_candidate(ledger)
    assert knowledge.search("SYNTHETIC_UI_GOVERNANCE_FIXTURE").units == []
    calls_before = ledger.list_records("model_call")
    page(app, "入库工作台")
    stage(app, "质量与分流")
    assert widget(app.selectbox, "候选知识").value == unit["id"]
    assert widget(app.selectbox, "审核决定").value == "defer"
    widget(app.text_input, "审核人").set_value("synthetic UI reviewer")
    widget(app.text_area, "审核理由").set_value("Synthetic UI approval; no scientific claim")
    widget(app.selectbox, "审核决定").set_value("approve")
    widget(app.multiselect, "允许用途").set_value(["explanation"])
    widget(app.button, "保存确切修订的审核决定").click().run()
    assert not app.exception
    reviewed = ledger.list_records("review")
    assert len(reviewed) == 1 and reviewed[0]["assessment_id"] == assessment["id"]
    assert knowledge.current_release() is None
    assert knowledge.search("SYNTHETIC_UI_GOVERNANCE_FIXTURE").units == []

    stage(app, "变更与发布")
    assert widget(app.button, "发布所选知识").disabled
    widget(app.multiselect, "完整新版本的知识清单").set_value([unit["id"]]).run()
    widget(app.text_input, "发布人").set_value("synthetic UI publisher")
    widget(app.checkbox, "已核对以上完整清单及增删影响").check().run()
    widget(app.button, "发布所选知识").click().run()
    assert not app.exception
    release = knowledge.current_release()
    assert release["units"][0]["candidate_id"] == unit["id"]
    assert release["units"][0]["review_id"] == reviewed[0]["id"]
    assert ledger.list_records("model_call") == calls_before

    page(app, "知识库")
    widget(app.text_input, "研究问题").set_value("SYNTHETIC_UI_GOVERNANCE_FIXTURE")
    widget(app.button, "检索正式证据").click().run()
    assert not app.exception
    package = app.session_state["last_evidence_package"]
    assert package["units"][0]["candidate_id"] == unit["id"]
    assert package["units"][0]["evidence"][0]["source_id"] == source["id"]

    knowledge.suspend("source", source["id"], actor="synthetic fixture reviewer", reason="Synthetic UI revalidation test")
    app.run()
    assert not app.exception
    assert "last_evidence_package" not in app.session_state
    widget(app.button, "检索正式证据").click().run()
    assert not app.exception
    assert app.session_state["last_evidence_package"]["units"] == []
    assert ledger.list_records("model_call") == calls_before


def _configure_synthetic_chat(ui, monkeypatch, *, unlocked=True, fail=False):
    """Use the actual gateway/vault with an in-process provider, never a network."""
    app, ledger = ui
    models = ModelService(ledger.workspace, ledger)
    connection = models.create_connection("Synthetic chat connection", "https://provider.example/v1",
        "synthetic-chat-key", "synthetic-chat-passphrase")
    profile = models.create_profile("Synthetic chat", "chat", connection["id"], "synthetic-chat-model",
        input_usd_per_million=0.1, output_usd_per_million=0.2)
    calls = []

    def transport(url, headers, payload, timeout):
        assert url == "https://provider.example/v1/chat/completions"
        assert headers["Authorization"] == "Bearer synthetic-chat-key"
        assert timeout > 0
        calls.append(deepcopy(payload))
        if fail:
            raise TimeoutError("Synthetic provider failure; no actual outbound call")
        return {"id": f"synthetic-response-{len(calls)}", "model": "synthetic-chat-model",
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
                "content": f"SYNTHETIC_CHAT_ANSWER_{len(calls)}"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 15, "total_tokens": 115}}

    monkeypatch.setattr("sckg_workbench.model_service.http_transport", transport)
    if unlocked:
        app.session_state["vault_passphrase"] = "synthetic-chat-passphrase"
    page(app, "研究台")
    return profile, calls


def test_analysis_chat_requires_explicit_dataset_context_and_keeps_prose_separate_from_execution(ui, monkeypatch, tmp_path):
    import h5py
    import numpy as np
    from sckg_workbench.datasets import DatasetService
    app, ledger = ui
    path = tmp_path / "analysis-input.h5ad"
    with h5py.File(path, "w") as handle:
        handle.attrs["encoding-type"] = "anndata"
        handle.create_dataset("X", data=np.ones((12, 10), dtype=np.int32))
    DatasetService(ledger.workspace).register_local(path)
    _configure_synthetic_chat(ui, monkeypatch)
    calls = []
    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        return {"model": "fixture", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "action": "finish", "answer": "本轮没有执行分析。"}, ensure_ascii=False)}}]}
    monkeypatch.setattr("sckg_workbench.model_service.http_transport", transport)
    app.checkbox(key="research_analysis_enabled").check().run()
    assert not app.exception and app.chat_input(key="research_prompt").disabled
    app.text_area(key="research_count_provenance").set_value("Synthetic counts fixture only").run()
    assert app.chat_input(key="research_prompt").disabled
    app.number_input(key="research_doublet_rate").set_value(0.06).run()
    assert not app.exception and not app.chat_input(key="research_prompt").disabled
    app.chat_input(key="research_prompt").set_value("先说明所选任务是否可以执行").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and len(calls) == 1
    assert ledger.list_records("chat_request")[0]["analysis_options"]["count_source"] == "X"
    assert ledger.list_records("chat_result")[0]["agent_steps"] == []
    assert any("本轮尚未执行分析" in value.value for value in app.info)
    before = len(calls)
    app.run()
    assert len(calls) == before


def test_chat_composer_is_visible_without_sources_or_models_and_explains_configuration(ui):
    app, ledger = ui
    page(app, "研究台")
    assert app.chat_input(key="research_prompt").disabled
    assert widget(app.button, "模型未配置") is not None
    assert not any(button.label == "接入第一份资料" for button in app.button)
    assert not any(item.label == "研究问题" for item in app.text_input)
    assert ledger.list_records("chat_request") == [] and ledger.list_records("model_call") == []


def test_chat_profile_still_requires_unlocked_vault_but_not_uploaded_material(ui, monkeypatch):
    app, ledger = ui
    profile, calls = _configure_synthetic_chat(ui, monkeypatch, unlocked=False)
    assert app.selectbox(key="research_chat_profile").value == profile["id"]
    assert app.chat_input(key="research_prompt").disabled
    assert any("解锁" in item.value for item in list(app.info) + list(app.caption) + list(app.warning))
    app.session_state["vault_passphrase"] = "synthetic-chat-passphrase"
    app.run()
    assert not app.exception and not app.error
    assert not app.chat_input(key="research_prompt").disabled
    assert calls == []
    assert ledger.list_records("source") == [] and ledger.list_records("release") == []
    assert ledger.list_records("model_call") == []


def test_local_env_connection_can_chat_without_vault_passphrase(ui, monkeypatch, tmp_path):
    app, ledger = ui
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("DCS_KEY=synthetic-ui-provider-key\n")
    page(app, "设置")
    widget(app.text_input, "本地连接名称").set_value("DCS fixture")
    widget(app.text_input, "本地连接 API base URL").set_value("https://provider.example/v1")
    widget(app.text_input, ".env 绝对路径").set_value(str(env_file))
    widget(app.text_input, "密钥变量名").set_value("DCS_KEY")
    widget(app.button, "保存本地凭据引用").click().run()
    assert not app.exception and not app.error
    models = ModelService(ledger.workspace, ledger)
    connection = models.list_connections()[0]
    models.create_profile("DCS fixture chat", "chat", connection["id"], "synthetic-chat-model",
                          input_usd_per_million=1, output_usd_per_million=1)
    calls = []
    def transport(url, headers, payload, timeout):
        assert headers["Authorization"] == "Bearer synthetic-ui-provider-key"
        assert payload["stream"] is False
        calls.append(payload)
        return {"model": "synthetic-chat-model", "choices": [{"finish_reason": "stop", "message": {"content": "Synthetic reply."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
    monkeypatch.setattr("sckg_workbench.model_service.http_transport", transport)
    page(app, "研究台")
    assert not app.chat_input(key="research_prompt").disabled
    app.chat_input(key="research_prompt").set_value("Synthetic hello.").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and len(calls) == 1
    assert ledger.list_records("chat_result")[0]["status"] == "succeeded"
    assert ledger.list_records("source") == [] and ledger.list_records("release") == []


def test_empty_library_chat_preserves_two_turn_history_and_rerun_does_not_send(ui, monkeypatch):
    app, ledger = ui
    profile, calls = _configure_synthetic_chat(ui, monkeypatch)
    assert app.checkbox(key="research_use_knowledge").value is True
    assert not app.chat_input(key="research_prompt").disabled
    assert calls == []
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_FIRST_QUESTION").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    assert len(calls) == 1 and calls[0]["model"] == profile["model"]
    assert calls[0]["messages"][-1] == {"role": "user", "content": "SYNTHETIC_FIRST_QUESTION"}
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_1" for item in app.markdown)
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_FOLLOW_UP").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    assert len(calls) == 2
    messages = calls[1]["messages"]
    assert messages[-1] == {"role": "user", "content": "SYNTHETIC_FOLLOW_UP"}
    assert {"role": "user", "content": "SYNTHETIC_FIRST_QUESTION"} in messages
    assert {"role": "assistant", "content": "SYNTHETIC_CHAT_ANSWER_1"} in messages
    assert len(ledger.list_records("model_call")) == 2
    assert len(ledger.list_records("chat_request")) == 2
    assert all(result["status"] == "succeeded" for result in ledger.list_records("chat_result"))
    app.run()
    assert not app.exception and len(calls) == 2
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_1" for item in app.markdown)
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_2" for item in app.markdown)
    assert ledger.list_records("source") == [] and ledger.list_records("release") == []


def test_new_chat_isolates_context_and_history_switch_does_not_invoke(ui, monkeypatch):
    app, ledger = ui
    _, calls = _configure_synthetic_chat(ui, monkeypatch)
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_OLD_CONVERSATION").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and len(calls) == 1
    old_id = app.selectbox(key="research_conversation").value
    app.button(key="research_new_chat").click().run()
    assert not app.exception and len(calls) == 1
    assert not any(item.value == "SYNTHETIC_CHAT_ANSWER_1" for item in app.markdown)
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_NEW_CONVERSATION").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and len(calls) == 2
    assert app.selectbox(key="research_conversation").value != old_id
    assert calls[1]["messages"][-1] == {"role": "user", "content": "SYNTHETIC_NEW_CONVERSATION"}
    assert not any("SYNTHETIC_OLD_CONVERSATION" in message["content"] or
        "SYNTHETIC_CHAT_ANSWER_1" in message["content"] for message in calls[1]["messages"])
    app.selectbox(key="research_conversation").set_value(old_id).run()
    assert not app.exception and len(calls) == 2
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_1" for item in app.markdown)
    assert not any(item.value == "SYNTHETIC_CHAT_ANSWER_2" for item in app.markdown)
    assert len(ledger.list_records("chat_request")) == 2


def test_research_navigation_preserves_active_chat_and_nondefault_profile(ui, monkeypatch):
    app, ledger = ui
    profile, calls = _configure_synthetic_chat(ui, monkeypatch)
    alternate = ModelService(ledger.workspace, ledger).create_profile(
        "Synthetic alternate chat", "chat", profile["connection_id"], "synthetic-alternate-model",
        input_usd_per_million=0.1, output_usd_per_million=0.2)
    app.run()
    app.selectbox(key="research_chat_profile").set_value(alternate["id"]).run()
    app.checkbox(key="research_use_knowledge").uncheck()
    app.number_input(key="research_output_limit").set_value(512).run()
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_BEFORE_NAVIGATION").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    conversation_id = app.selectbox(key="research_conversation").value
    assert conversation_id and len(calls) == 1
    assert calls[0]["model"] == alternate["model"]
    assert calls[0]["max_tokens"] == 512

    widget(app.button, "查看知识与关系").click().run()
    assert not app.exception and app.radio(key="navigation").value == "知识库"
    assert len(calls) == 1
    page(app, "研究台")
    assert not app.error
    assert app.selectbox(key="research_conversation").value == conversation_id
    assert app.selectbox(key="research_chat_profile").value == alternate["id"]
    assert app.checkbox(key="research_use_knowledge").value is False
    assert app.number_input(key="research_output_limit").value == 512
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_1" for item in app.markdown)
    assert len(calls) == 1

    app.chat_input(key="research_prompt").set_value("SYNTHETIC_AFTER_NAVIGATION").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    assert len(calls) == 2 and calls[1]["model"] == alternate["model"]
    assert calls[1]["max_tokens"] == 512
    assert {"role": "user", "content": "SYNTHETIC_BEFORE_NAVIGATION"} in calls[1]["messages"]
    assert {"role": "assistant", "content": "SYNTHETIC_CHAT_ANSWER_1"} in calls[1]["messages"]
    turns = ChatService(ledger).turns(conversation_id)
    assert len(turns) == 2 and all(turn["use_knowledge"] is False for turn in turns)


def test_chat_failure_stays_visible_without_automatic_retry(ui, monkeypatch):
    app, ledger = ui
    _, calls = _configure_synthetic_chat(ui, monkeypatch, fail=True)
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_FAILURE_REQUEST").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and len(calls) == 1
    assert any("完成状态待核对" in value.value and "不会自动重发" in value.value for value in app.warning)
    assert ledger.list_records("chat_result")[0]["status"] == "result_unknown"
    assert ledger.list_records("model_call")[0]["status"] == "failed"
    assert ledger.list_records("model_call")[0]["outcome"] == "result_unknown"
    assert not app.success and app.chat_input(key="research_prompt").disabled
    assert not any("SYNTHETIC_CHAT_ANSWER" in item.value for item in app.markdown)
    app.run()
    assert not app.exception and len(calls) == 1
    assert any("完成状态待核对" in value.value and "不会自动重发" in value.value for value in app.warning)
    assert len(ledger.list_records("chat_request")) == 1


def test_chat_knowledge_is_optional_and_suspended_source_invalidates_display_without_resend(ui, monkeypatch):
    app, ledger = ui
    knowledge, unit, source, assessment = _synthetic_assessed_ui_candidate(ledger)
    knowledge.review(unit["id"], actor="synthetic UI reviewer", decision="approve", allowed_uses=["explanation"],
        reason="Synthetic optional chat evidence fixture", expected_hash=unit["content_hash"],
        expected_assessment_id=assessment["id"])
    knowledge.publish([unit["id"]], actor="synthetic UI publisher")
    _, calls = _configure_synthetic_chat(ui, monkeypatch)
    app.checkbox(key="research_use_knowledge").uncheck().run()
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_UI_GOVERNANCE_FIXTURE").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    chat = ChatService(ledger)
    conversation_id = app.selectbox(key="research_conversation").value
    turns = chat.turns(conversation_id)
    assert len(calls) == 1 and turns[0]["use_knowledge"] is False
    assert turns[0]["evidence_package"] is None and turns[0]["evidence_packages"] == []
    assert not any("has a property within this test only" in message["content"] for message in calls[0]["messages"])

    app.checkbox(key="research_use_knowledge").check().run()
    app.chat_input(key="research_prompt").set_value("SYNTHETIC_UI_GOVERNANCE_FIXTURE").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    turns = chat.turns(conversation_id)
    assert len(calls) == 2 and turns[1]["use_knowledge"] is True
    assert turns[1]["evidence_package"]["units"][0]["candidate_id"] == unit["id"]
    assert turns[1]["evidence_package"]["units"][0]["evidence"][0]["source_id"] == source["id"]
    assert any("has a property within this test only" in message["content"] for message in calls[1]["messages"])
    assert any(expander.label == "本轮知识依据 · 1 条" for expander in app.expander)
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_2" for item in app.markdown)

    app.chat_input(key="research_prompt").set_value("zxqvfollowupunmatchedcontext").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error
    turns = chat.turns(conversation_id)
    assert len(calls) == 3 and turns[2]["evidence_package"]["units"] == []
    assert any(package["units"] for package in turns[2]["evidence_packages"])
    assert sum(expander.label == "本轮知识依据 · 1 条" for expander in app.expander) == 2
    assert any("来自此前对话上下文" in item.value for item in app.caption)
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_3" for item in app.markdown)

    knowledge.suspend("source", source["id"], actor="synthetic UI reviewer", reason="Synthetic source suspension")
    app.run()
    assert not app.exception and len(calls) == 3
    assert any(item.value == "SYNTHETIC_CHAT_ANSWER_1" for item in app.markdown)
    assert not any(item.value == "SYNTHETIC_CHAT_ANSWER_2" for item in app.markdown)
    assert not any(item.value == "SYNTHETIC_CHAT_ANSWER_3" for item in app.markdown)
    assert not any(expander.label == "本轮知识依据 · 1 条" for expander in app.expander)
    assert chat.view_turn(turns[1])["current_status"] == "evidence_invalidated"
    assert chat.view_turn(turns[2])["current_status"] == "evidence_invalidated"
    assert len(ledger.list_records("chat_request")) == 3


def _synthetic_navigation_ui(ledger, *, include_extended=False):
    from sckg_workbench.network import NetworkService

    knowledge, unit, source, assessment = _synthetic_assessed_ui_candidate(ledger)
    review = knowledge.review(unit["id"], actor="Synthetic UI reviewer", decision="approve", allowed_uses=["explanation"],
        reason="Test fixture only", expected_hash=unit["content_hash"], expected_assessment_id=assessment["id"])
    knowledge.publish([unit["id"]], actor="Synthetic publisher", expected_release_id=None,
                      expected_review_ids={unit["id"]: review["id"]})
    ledger.put_record("external_model_profile", "synthetic-navigation-profile", {
        "id": "synthetic-navigation-profile", "model_family": "Synthetic fixture", "runtime": "tests"})
    network = NetworkService(ledger)
    run = network.prepare(profile_id="synthetic-navigation-profile", agent_id="test-fixture", instructions="Synthetic navigation fixture only")
    entities = [{"id": "synthetic-method-a", "label": "Synthetic Method A", "kind": "method", "aliases": ["test alias"]},
                {"id": "synthetic-method-b", "label": "Synthetic Method B", "kind": "tool"},
                {"id": "synthetic-task", "label": "Synthetic task", "kind": "task"},
                {"id": "synthetic-modality", "label": "Synthetic modality", "kind": "modality"}]
    if include_extended:
        entities.extend([{"id": "synthetic-technology", "label": "Synthetic technology", "kind": "technology"},
                         {"id": "synthetic-benchmark", "label": "Synthetic benchmark", "kind": "benchmark"}])
    network.import_annotations(run["id"], {
        "entities": entities,
        "memberships": [{"candidate_id": unit["id"], "entity_ids": [entity["id"] for entity in entities],
                         "scope_note": "Synthetic future direction only; no delivered capability."}],
        "relations": [{"source": "synthetic-method-a", "target": "synthetic-task", "predicate": "test_association",
                       "label": "Synthetic association", "candidate_ids": [unit["id"]], "rationale": "Synthetic index; no scientific approval", "kind": "source_assertion"}],
    }, expected_input_hash=run["input_hash"])
    return knowledge, network, source


def test_published_navigation_is_readable_and_method_switch_and_scope_filters_work(ui):
    app, ledger = ui
    _, network, _ = _synthetic_navigation_ui(ledger)
    existing_records = {kind: len(ledger.list_records(kind)) for kind in ("candidate", "review", "release", "model_call", "network_projection")}
    page(app, "知识库")
    assert not app.error
    assert app.tabs[0].label == "方法与工具"
    assert widget(app.selectbox, "查看方法档案").options == ["Synthetic Method A", "Synthetic Method B"]
    assert any("条件示例" in item.proto.srcdoc for item in app.get("iframe"))
    widget(app.selectbox, "关联方法").set_value("synthetic-method-b")
    widget(app.button, "打开关联方法档案").click().run()
    assert not app.exception and not app.error
    assert widget(app.selectbox, "查看方法档案").value == "synthetic-method-b"
    widget(app.selectbox, "探索起点").set_value("synthetic-method-a").run()
    widget(app.selectbox, "关联范围").set_value(2).run()
    assert not app.exception and not app.error
    assert any("不等于" in item.value or "尚待单独核对" in item.value for item in app.caption)
    widget(app.multiselect, "显示对象类型").set_value(["method", "task"]).run()
    assert not app.exception and not app.error
    assert len(widget(app.selectbox, "查看关系的原文依据").options) == 1
    assert any("No scientific validity" in item.value for item in app.markdown)
    for kind, count in existing_records.items():
        assert len(ledger.list_records(kind)) == count
    assert network.view()["stats"]["total_entities"] == 4


def test_navigation_rerender_rechecks_suspension_instead_of_reusing_method_profile(ui):
    app, ledger = ui
    knowledge, _, source = _synthetic_navigation_ui(ledger)
    page(app, "知识库")
    assert widget(app.selectbox, "查看方法档案").options
    knowledge.suspend("source", source["id"], actor="Synthetic maintainer", reason="Synthetic suspension test")
    app.run()
    assert not app.exception and not app.error
    assert not any(item.label == "查看方法档案" for item in app.selectbox)
    assert not app.get("iframe")
    assert any("当前没有可展示的已发布证据" in item.value for item in app.caption)


def test_ui_suspension_refreshes_already_rendered_network_in_same_interaction(ui):
    app, ledger = ui
    _, _, source = _synthetic_navigation_ui(ledger)
    page(app, "知识库")
    assert app.get("iframe")
    widget(app.selectbox, "来源或候选 ID").set_value(source["id"])
    widget(app.text_input, "维护操作人").set_value("Synthetic UI maintainer")
    widget(app.text_area, "维护依据").set_value("Synthetic immediate refresh test")
    widget(app.button, "记录维护决定").click().run()
    assert not app.exception and not app.error
    assert not app.get("iframe")
    assert not any(item.label == "查看方法档案" for item in app.selectbox)
    assert any("已按最新使用状态刷新" in item.value for item in app.success)
    assert ledger.get_state("governance:source:" + source["id"])["suspended"] is True


def test_method_library_exposes_technology_benchmark_and_future_capability_boundaries(ui):
    app, ledger = ui
    _synthetic_navigation_ui(ledger, include_extended=True)
    page(app, "知识库")
    assert widget(app.selectbox, "档案类型").value == "方法与工具"
    assert len(widget(app.selectbox, "查看方法档案").options) == 2
    assert any("能力边界" in item.value for item in app.markdown)
    assert any("Synthetic future direction" in item.value for item in app.info)
    widget(app.selectbox, "档案类型").set_value("实验技术").run()
    assert not app.exception and not app.error
    assert widget(app.selectbox, "查看方法档案").options == ["Synthetic technology"]
    widget(app.selectbox, "档案类型").set_value("比较评测").run()
    assert not app.exception and not app.error
    assert widget(app.selectbox, "查看方法档案").options == ["Synthetic benchmark"]
    widget(app.selectbox, "档案类型").set_value("全部档案").run()
    assert len(widget(app.selectbox, "查看方法档案").options) == 4
    widget(app.text_input, "搜索知识单元").set_value("SYNTHETIC_UI_GOVERNANCE_FIXTURE").run()
    assert not app.exception and not app.error
    assert any("Synthetic future direction" in item.value for item in app.tabs[1].info)


def test_interactive_navigation_renderer_keeps_governance_explicit_and_escapes_source_text():
    from sckg_workbench.ui import _network_graph_html

    html = _network_graph_html({
        "focus_entity_id": "b",
        "nodes": [{"id": "a", "label": "A </script><script>unsafe()</script>", "kind": "method", "candidate_ids": ["c"]},
                  {"id": "b", "label": "Task", "kind": "task", "candidate_ids": ["c"]}],
        "edges": [{"id": "e", "source": "a", "target": "b", "label": "关联", "kind": "source_assertion", "candidate_ids": ["c"]}],
        "claims": [{"candidate_id": "c", "claim": {"conditions": ["Synthetic condition"], "unknowns": ["Synthetic limit"]}}]})
    payload = json.loads(re.search(r'<script id="graphData" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert "unsafe()</script>" not in html
    assert all(not node["governance"]["decision_eligible"] for node in payload["nodes"])
    assert all("legacy" != node["governance"]["layer"] for node in payload["nodes"])
    assert "待核对" in payload["edges"][0]["governance"]["layer"]
    assert payload["nodes"][0]["properties"]["readable"]["条件示例"] == ["Synthetic condition"]
    assert "contract-qualified" not in payload["presentation"]["overview"]
    assert "技术记录" in html and "startNodeDrag" in html and "expandNeighbors" in html
    assert payload["embedded"] is True
    assert payload["focusNodeId"] == "b"
    assert '<body class="embedded">' in html
    assert 'body.embedded .sidebar{display:none}' in html
    assert 'height:100vh;min-height:0' in html


def test_shared_graph_renderer_preserves_legacy_default_and_supports_embedded_canvas():
    from sckg_workbench.graph_renderer import build_interactive_graph_workspace_html
    from engine.interactive_graph_workspace import build_interactive_graph_workspace_html as legacy_entry

    graph = SimpleNamespace(nodes={"a": SimpleNamespace(node_id="a", label="Synthetic", kind="Tool", metadata={})},
                            edges=[], visible_node_ids=["a"], truncated=False)
    assert legacy_entry is build_interactive_graph_workspace_html
    html = legacy_entry(graph)
    payload = json.loads(re.search(r'<script id="graphData" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert payload["embedded"] is False
    assert payload["presentation"]["title"] == "scKG Decision Network"
    assert '<body class="">' in html


def test_network_type_filter_has_one_state_source_and_preserves_user_selection(ui):
    app, ledger = ui
    _synthetic_navigation_ui(ledger)
    page(app, "知识库")
    assert not any("default value" in item.value for item in app.warning)
    widget(app.multiselect, "显示对象类型").set_value(["method", "task"]).run()
    assert not app.exception and not app.error
    assert widget(app.multiselect, "显示对象类型").value == ["method", "task"]
    app.run()
    assert widget(app.multiselect, "显示对象类型").value == ["method", "task"]
    assert not any("default value" in item.value for item in app.warning)


def test_ingestion_pipeline_explains_six_stages_and_missing_automation_without_side_effects(ui):
    app, ledger = ui
    page(app, "入库工作台")
    assert any("结构化关联" in item.value and "冲突与冗余" in item.value for item in app.markdown)
    assert any("尚未配置定时调度" in item.value for item in app.caption)
    assert any("低分或相反结果不能" in item.value for item in app.caption)
    assert ledger.list_records("network_run") == []
    assert ledger.list_records("model_call") == []


def _readonly_result_selection_ui_fixture(ui, monkeypatch):
    """UI contract fixture only; service authorization has separate tests."""
    app, ledger = ui
    _, calls = _configure_synthetic_chat(ui, monkeypatch)
    chat = ChatService(ledger)
    first = chat.create_conversation("Synthetic result conversation A")
    second = chat.create_conversation("Synthetic result conversation B")
    choices = {
        first["id"]: [{"result_ref": "synthetic-result-ref-a", "task_id": "synthetic-task-a",
                       "attempt": 1, "run_id": "synthetic-run-a", "source_turn_id": "synthetic-turn-a",
                       "task_status": "succeeded"}],
        second["id"]: [{"result_ref": "synthetic-result-ref-b", "task_id": "synthetic-task-b",
                        "attempt": 2, "run_id": "synthetic-run-b", "source_turn_id": "synthetic-turn-b",
                        "task_status": "succeeded"}],
    }
    monkeypatch.setattr(ChatService, "list_result_tasks", lambda self, conversation_id: deepcopy(choices[conversation_id]))
    submitted = []

    _capture_chat_submission(monkeypatch, submitted)
    from sckg_workbench.analysis import AnalysisService

    def forbidden_execution(*args, **kwargs):
        raise AssertionError("Reading a result must not submit or execute analysis")

    monkeypatch.setattr(AnalysisService, "submit_scrublet", forbidden_execution)
    monkeypatch.setattr(AnalysisService, "run_once", forbidden_execution)
    app.run()
    app.selectbox(key="research_conversation").set_value(first["id"]).run()
    assert not app.exception
    return app, ledger, first, second, choices, submitted, calls


def test_readonly_result_ui_requires_explicit_choice_and_sends_without_execution_options(ui, monkeypatch):
    app, ledger, first, _, choices, submitted, calls = _readonly_result_selection_ui_fixture(ui, monkeypatch)
    assert not app.checkbox(key="research_result_read_enabled").disabled
    app.checkbox(key="research_result_read_enabled").check().run()
    assert not app.exception and app.chat_input(key="research_prompt").disabled
    assert app.selectbox(key="research_result_ref").value == ""
    assert not any(item.key == "research_count_provenance" for item in app.text_area)
    assert not any(item.key == "research_doublet_rate" for item in app.number_input)
    chosen = choices[first["id"]][0]["result_ref"]
    app.selectbox(key="research_result_ref").set_value(chosen).run()
    assert not app.exception and not app.chat_input(key="research_prompt").disabled
    app.chat_input(key="research_prompt").set_value("Read the existing synthetic result only").run()
    assert not app.exception and len(submitted) == 1
    assert submitted[0]["conversation_id"] == first["id"]
    assert submitted[0]["result_ref"] == chosen
    assert submitted[0]["analysis_options"] is None
    assert calls == [] and ledger.list_records("model_call") == []
    assert TaskQueue(ledger.workspace).list() == []
    app.run()
    assert len(submitted) == 1 and calls == []


def test_readonly_result_ui_clears_selection_on_conversation_switch(ui, monkeypatch):
    app, _, first, second, choices, submitted, calls = _readonly_result_selection_ui_fixture(ui, monkeypatch)
    app.checkbox(key="research_result_read_enabled").check().run()
    app.selectbox(key="research_result_ref").set_value(choices[first["id"]][0]["result_ref"]).run()
    assert not app.exception
    assert any("synthetic-run-a" in value for value in app.selectbox(key="research_result_ref").options)
    assert not any("synthetic-run-b" in value for value in app.selectbox(key="research_result_ref").options)
    app.selectbox(key="research_conversation").set_value(second["id"]).run()
    assert not app.exception and app.checkbox(key="research_result_read_enabled").value is False
    assert app.session_state["research_result_ref"] == ""
    assert not any(item.key == "research_result_ref" for item in app.selectbox)
    app.checkbox(key="research_result_read_enabled").check().run()
    assert app.selectbox(key="research_result_ref").value == ""
    assert any("synthetic-run-b" in value for value in app.selectbox(key="research_result_ref").options)
    assert not any("synthetic-run-a" in value for value in app.selectbox(key="research_result_ref").options)
    app.button(key="research_new_chat").click().run()
    assert not app.exception and app.checkbox(key="research_result_read_enabled").disabled
    assert app.checkbox(key="research_result_read_enabled").value is False
    assert submitted == [] and calls == []


def test_readonly_result_ui_and_new_execution_are_mutually_exclusive(ui, monkeypatch):
    app, _, _, _, _, submitted, calls = _readonly_result_selection_ui_fixture(ui, monkeypatch)
    from sckg_workbench.datasets import DatasetService
    monkeypatch.setattr(DatasetService, "list_assets", lambda self: [
        {"asset_id": "synthetic-selection-asset", "label": "Synthetic existing asset"}])
    app.run()
    app.checkbox(key="research_analysis_enabled").check().run()
    assert not app.exception and app.checkbox(key="research_analysis_enabled").value is True
    assert any(item.key == "research_count_provenance" for item in app.text_area)
    app.checkbox(key="research_result_read_enabled").check().run()
    assert not app.exception and app.checkbox(key="research_analysis_enabled").value is False
    assert not any(item.key == "research_count_provenance" for item in app.text_area)
    app.checkbox(key="research_analysis_enabled").check().run()
    assert not app.exception and app.checkbox(key="research_result_read_enabled").value is False
    assert not any(item.key == "research_result_ref" for item in app.selectbox)
    assert submitted == [] and calls == []


@pytest.mark.parametrize("state,label", [
    ("profile_failed", "数据画像未完成"),
    ("result_unavailable", "已有结果当前不可读取或未通过验收"),
    ("result_read", "已读取已有结果并核验产物"),
])
def test_result_outcome_ui_distinguishes_profile_failure_and_readonly_result(state, label):
    def render(view):
        from types import SimpleNamespace
        from sckg_workbench.ui import _display_chat_turn
        chat = SimpleNamespace(view_turn=lambda stored: view)
        _display_chat_turn(chat, view)

    view = {"id": "synthetic-result-view", "prompt": "Synthetic status display only",
            "status": "succeeded", "current_status": "succeeded", "answer": "Synthetic fixture only",
            "usable": True, "analysis_outcome": {"state": state, "validated_preview": False}}
    app = AppTest.from_function(render, args=(view,)).run()
    assert not app.exception
    assert any(label in item.value for item in list(app.info) + list(app.success))
    assert not any("本地分析预览已完成" in item.value for item in app.success)


def test_readonly_result_invalidated_view_does_not_show_historical_answer():
    def render(view):
        from types import SimpleNamespace
        from sckg_workbench.ui import _display_chat_turn
        _display_chat_turn(SimpleNamespace(view_turn=lambda stored: view), view)

    view = {"id": "synthetic-invalidated-result-view", "prompt": "Synthetic invalidation display",
            "status": "succeeded", "current_status": "result_invalidated", "answer": None,
            "usable": False, "analysis_outcome": {"state": "result_unavailable", "validated_preview": False},
            "agent_steps": [{"result": {"summary": {"status": "validated_preview_summary",
                "metrics": {"n_cells": 999, "predicted_doublet_count": 999, "predicted_doublet_call_rate": 1.0}}}}]}
    app = AppTest.from_function(render, args=(view,)).run()
    assert not app.exception
    assert any("这条历史回答不能作为当前结果依据" in item.value for item in app.warning)
    assert not any("本地分析预览已完成" in item.value for item in app.success)
    assert not app.metric  # An old tool receipt cannot supply current metrics.


def test_readonly_result_ui_integrates_actual_services_without_queue_get_or_execution(ui, monkeypatch, tmp_path):
    """Real UI/services with explicit synthetic receipts and gateway responses; zero fit."""
    import importlib.util
    from sckg_workbench.analysis import AnalysisService

    module_path = Path(__file__).with_name("test_workbench_result_summary.py")
    spec = importlib.util.spec_from_file_location("ui_summary_fixture_helpers", module_path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    fixture_dir = tmp_path / "readonly-summary-integration"
    fixture_dir.mkdir()
    fixture = helpers.make_summary_fixture(fixture_dir)
    app, _ = ui
    service = fixture["service"]
    ledger = service.ledger
    monkeypatch.setenv("SCKG_WORKBENCH_HOME", str(service.workspace.root))
    _configure_synthetic_chat((app, ledger), monkeypatch)
    chat = ChatService(ledger)
    conversation = chat.create_conversation("Synthetic persisted preview result")
    source_turn = "synthetic-original-analysis-turn"
    binding = {key: fixture[key] for key in ("task_id", "attempt", "run_id")}
    ledger.put_record("chat_request", source_turn, {
        "id": source_turn, "conversation_id": conversation["id"], "namespace": service.workspace.namespace,
        "sequence": 1, "prompt": "Synthetic fixture receipt, not a scientific execution",
        "status": "pending", "use_knowledge": False, "purpose": "explanation",
        "analysis_options": {"asset_id": fixture["asset"]["asset_id"], "count_source": "X",
            "count_provenance": "Synthetic validator fixture only", "expected_doublet_rate": .06}})
    ledger.put_record("chat_result", source_turn, {
        "status": "succeeded", "answer": "Synthetic stored receipt for UI tests; no computation took place.",
        "analysis_task_ids": [fixture["task_id"]], "result_bindings": [binding],
        "agent_steps": [{"action": "run_scrublet", "result": binding}]})
    calls = []

    def scripted_gateway(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        action = "read_analysis_result" if len(calls) == 1 else "finish"
        answer = "" if action == "read_analysis_result" else "Synthetic receipt: 400 rows, 4 predicted calls; no new fit."
        return {"model": "synthetic-read-result-model", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"action": action, "answer": answer})}}]}

    def forbidden_execution(*args, **kwargs):
        raise AssertionError("Read-only UI attempted queue expiry or scientific execution")

    monkeypatch.setattr("sckg_workbench.model_service.http_transport", scripted_gateway)
    monkeypatch.setattr(TaskQueue, "get", forbidden_execution)
    for symbol in ("submit_scrublet", "run_once", "_execute", "_execute_supervised"):
        monkeypatch.setattr(AnalysisService, symbol, forbidden_execution)
    original_source = fixture["source"].read_bytes()
    original_table = (fixture["outputs"] / "doublet_results.tsv").read_bytes()
    original_snapshot = service.get_task_snapshot(fixture["task_id"])
    app.run()
    app.selectbox(key="research_conversation").set_value(conversation["id"]).run()
    assert not app.exception and not app.error
    references = chat.list_result_tasks(conversation["id"])
    assert len(references) == 1 and calls == []
    app.checkbox(key="research_result_read_enabled").check().run()
    app.selectbox(key="research_result_ref").set_value(references[0]["result_ref"]).run()
    assert not app.exception and not app.chat_input(key="research_prompt").disabled
    assert not any(item.key == "research_count_provenance" for item in app.text_area)
    app.chat_input(key="research_prompt").set_value("Read this saved synthetic result without fitting").run()
    _finish_background_chat(app, ledger)
    assert not app.exception and not app.error and len(calls) == 2
    latest = chat.turns(conversation["id"])[-1]
    assert latest["status"] == "succeeded" and latest["analysis_task_ids"] == []
    assert latest["referenced_analysis_task_ids"] == [fixture["task_id"]]
    assert latest["result_selection"]["task_id"] == fixture["task_id"]
    assert chat.view_turn(latest)["analysis_outcome"]["state"] == "result_read"
    assert any("已读取已有结果并核验产物" in item.value for item in app.success)
    assert any(item.label == "结果读取与原任务状态" for item in app.expander)
    assert widget(app.metric, "预览细胞数").value == "400"
    assert widget(app.metric, "预测为双细胞").value == "4"
    assert widget(app.metric, "预测调用比例").value == "1.0%"
    assert any("不是准确率或真实双细胞率" in item.value for item in app.caption)
    assert any("阈值未记录" in item.value for item in app.caption)
    assert "private-fixture-cell" not in json.dumps(calls)
    assert service.get_task_snapshot(fixture["task_id"]) == original_snapshot
    assert fixture["source"].read_bytes() == original_source
    assert (fixture["outputs"] / "doublet_results.tsv").read_bytes() == original_table
    app.run()
    assert not app.exception and len(calls) == 2
