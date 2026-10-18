"""Independent local workbench. Opening a page never fetches sources or calls LLMs."""
from __future__ import annotations

import importlib
import hashlib
import json
import uuid
from html import escape
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

from .catalog import Catalog
from .model_service import ModelService, ModelCapabilityError, _strict_json
from .model_capabilities import API_FAMILY, CAPABILITIES_VERSION
from .sources import SourceService
from .storage import Ledger, Workspace
from .tasks import TaskQueue
from .ui_theme import inject_theme


PAGES = ("研究台", "数据资产", "知识库", "入库工作台", "运行结果", "质量评测", "设置")
INGEST_STAGES = ("来源与范围", "配置与抽取", "质量与分流", "合并与冲突", "变更与发布")
PAGE_DESCRIPTIONS = {
    "研究台": "直接提问，连续讨论；按需结合知识库中的依据。",
    "数据资产": "管理研究输入，保留原始数据与版本。",
    "知识库": "从方法、任务与模态出发，沿着关联找到有条件、有出处的知识。",
    "入库工作台": "多来源接入，可配置抽取，逐项核对后发布。",
    "运行结果": "查看研究计划、执行记录与结果产物。",
    "质量评测": "核对来源覆盖与留出边界，追踪需要修复的问题。",
    "设置": "管理模型连接、用途配置与本地凭据。",
}
PURPOSE_LABELS = {"extraction": "知识抽取", "assessment": "语义核验", "chat": "对话",
                  "evaluation": "独立评测", "embedding": "语义向量"}


def _error(exc: Exception) -> None:
    st.error(f"操作未完成：{type(exc).__name__} · {str(exc)[:500]}")


def _optional_class(module: str, name: str):
    try:
        return getattr(importlib.import_module(module), name)
    except ModuleNotFoundError as exc:
        if exc.name == module:
            return None
        raise


def _knowledge(ledger):
    factory = _optional_class("sckg_workbench.knowledge", "KnowledgeService")
    return factory(ledger) if factory else None


def _network(ledger):
    factory = _optional_class("sckg_workbench.network", "NetworkService")
    return factory(ledger) if factory else None


def _worker(ledger, models):
    factory = _optional_class("sckg_workbench.worker", "Worker")
    return factory(ledger, models=models) if factory else None


def _json(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _profile_label(profile):
    return f"{profile['name']} · {profile['model']} · {profile['id'][-8:]}"


def _source_label(source):
    metadata = source.get("metadata", {})
    title = metadata.get("title") or source["filename"]
    return " · ".join(str(v) for v in (metadata.get("manifest_id"), title) if v)


def _capture_scope_label(source):
    scope = source.get("metadata", {}).get("capture_scope")
    return {"full_text": "正文已归档", "abstract_only": "仅摘要",
            "selected_chapter": "选定章节", "documentation_page": "单页文档",
            "selected_excerpt": "选定原文片段", "publisher_page": "出版页面（正文范围待核验）",
            "metadata_only": "仅题录"}.get(scope, "所接收原件")


def _source_with_current_coverage(ledger, source):
    state = ledger.get_state("source_capture_coverage:" + source["id"])
    coverage_id = state.get("id") if isinstance(state, dict) else state
    coverage = ledger.get_record("source_capture_coverage", coverage_id) if coverage_id else None
    if coverage and coverage.get("source_revision_id") == source["source_revision_id"]:
        return {**source, "metadata": {**source.get("metadata", {}), "capture_scope": coverage["capture_scope"]},
                "capture_coverage_assessment": coverage}
    return source


def _navigate(page, stage=None):
    st.session_state["navigation"] = page
    if stage:
        st.session_state["ingest_stage"] = stage


def _empty(title, description):
    st.html(f'<div class="wb-empty"><strong>{escape(title)}</strong><span class="wb-small">{escape(description)}</span></div>')


def render_app() -> None:
    st.set_page_config(page_title="scKG · 科研知识工作台", page_icon="◈", layout="wide")
    inject_theme()
    try:
        workspace = Workspace.default()
        ledger = Ledger(workspace)
        sources = SourceService(ledger)
        models = ModelService(workspace, ledger)
        queue = TaskQueue(workspace)
    except Exception as exc:
        _error(exc)
        st.stop()
    with st.container(key="workbench_frame", gap=None):
        with st.container(key="workbench_top"):
            brand, status = st.columns([3, 2], vertical_alignment="center")
            with brand:
                st.html('<div class="wb-brand"><span class="wb-mark">sc</span><strong>scKG</strong><span class="wb-small">科研工作台</span></div>')
            with status:
                with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
                    st.html('<span class="wb-chip">本地工作空间</span>', width="content")
                    count = len(models.list_connections())
                    st.button(f"已配置 {count} 个连接" if count else "模型未配置", icon=":material/tune:",
                              on_click=_navigate, args=("设置",), key="header_models")
        with st.container(key="workbench_body", gap=None):
            nav, main = st.columns([1.6, 10], gap=None)
            with nav:
                with st.container(key="workbench_nav"):
                    st.html('<div class="wb-project"><span class="wb-small">当前工作空间</span><strong>单细胞分析研究</strong><span class="wb-small">项目数据与共享知识分开管理</span></div>')
                    page = st.radio("工作空间", PAGES, key="navigation", label_visibility="collapsed", width="stretch")
                    with st.container(key="workbench_nav_status"):
                        st.caption(f"独立知识空间 · {workspace.namespace[-8:]}")
                        if st.session_state.get("vault_passphrase"):
                            st.caption("会话口令已解锁")
                        elif any(c.get("credential_source") == "env_file" for c in models.list_connections()):
                            st.caption("已配置本地 .env 凭据引用")
                        else:
                            st.caption("会话口令已锁定")
                        if st.button("锁定会话口令", disabled=not st.session_state.get("vault_passphrase")):
                            st.session_state.pop("vault_passphrase", None)
                            models.vault.lock()
                            st.rerun()
            with main:
                with st.container(key="workbench_main"):
                    with st.container(key="workbench_heading"):
                        heading, action = st.columns([4, 1], vertical_alignment="center")
                        with heading:
                            st.title(page)
                            st.caption(PAGE_DESCRIPTIONS[page])
                        with action:
                            if page == "知识库":
                                st.button("接入新资料", type="primary", on_click=_navigate, args=("入库工作台",))
                    notice_slot = st.empty()
                    notice = st.session_state.pop("knowledge_refresh_notice", None)
                    if notice:
                        notice_slot.success(notice)
                    maintenance_error = st.session_state.pop("knowledge_maintenance_error", None)
                    if maintenance_error:
                        notice_slot.error(maintenance_error)
                    try:
                        if page == "研究台":
                            _research(ledger, models)
                        elif page == "知识库":
                            _knowledge_page(ledger)
                        elif page == "入库工作台":
                            _ingestion(ledger, sources, models, queue)
                        elif page == "数据资产":
                            _datasets(workspace)
                        elif page == "运行结果":
                            _run_results(workspace)
                        elif page == "质量评测":
                            with st.container(border=True):
                                _evaluation(ledger)
                        elif page == "设置":
                            _settings(models)
                    except Exception as exc:
                        _error(exc)
        with st.container(key="workbench_footer"):
            st.html('<div class="wb-footer"><span>本地科研工作台 · 原文可追溯</span><span>资料登记、模型处理与知识发布分别记录</span></div>')


def _new_research_conversation():
    # A new empty view does not create a stored conversation or call a model.
    st.session_state["research_conversation"] = ""
    st.session_state["research_active_conversation"] = ""


def _research_analysis_mode_changed(changed_key):
    if st.session_state.get(changed_key):
        for other in ("research_analysis_enabled", "research_result_read_enabled", "research_grounded_mode",
                      "research_workflow_enabled"):
            if other != changed_key:
                st.session_state[other] = False


def _research_knowledge_mode_changed():
    if not st.session_state.get("research_use_knowledge"):
        st.session_state["research_grounded_mode"] = False


def _workflow_wire_options(options):
    from .workflow_chat import JSON_OBJECT_CANONICAL, REPORT_PRESENCE_VERSION
    selected = st.selectbox('流程输出格式', ['JSON Schema', 'JSON 对象 + 完整本地合同'],
        key='research_workflow_wire_format',
        help='显式选择当前模型接口支持的格式。两者保留完整本地校验；失败后不会自动切换或重试。')
    result = dict(options)
    result['answer_contract_version'] = REPORT_PRESENCE_VERSION
    if selected == 'JSON 对象 + 完整本地合同':
        result['wire_mode'] = JSON_OBJECT_CANONICAL
    return result


def _workflow_catalog_options(ledger):
    """Opt in only to an explicitly bound development catalog, without release."""
    configured = ledger.get_state("workflow_input_catalog")
    if not isinstance(configured, dict) or set(configured) != {"record_id", "catalog_hash"}:
        return None
    try:
        if not isinstance(configured["record_id"], str) or not isinstance(configured["catalog_hash"], str):
            return None
        record = ledger.get_record("workflow_input_catalog", configured["record_id"])
        if (not isinstance(record, dict) or record.get("id") != configured["record_id"]
                or record.get("catalog_hash") != configured["catalog_hash"]):
            return None
        from .workflow_inputs import WorkflowInputService
        WorkflowInputService(ledger, record["catalog"], expected_catalog_hash=configured["catalog_hash"])
    except (ValueError, KeyError, TypeError, RuntimeError):
        return None
    return {"catalog_record_id": configured["record_id"], "catalog_hash": configured["catalog_hash"]}


def _research(ledger, models):
    from .chat import ChatService
    from .datasets import DatasetService

    chat = ChatService(ledger, models=models)
    conversations = {c["id"]: c for c in chat.list_conversations()}
    if "research_conversation" not in st.session_state:
        st.session_state["research_conversation"] = st.session_state.get("research_active_conversation", "")
    pending_selection = st.session_state.pop("research_selected_after_send", None)
    if pending_selection in conversations:
        st.session_state["research_conversation"] = pending_selection
    if st.session_state.get("research_conversation", "") not in {"", *conversations}:
        st.session_state["research_conversation"] = ""
    with st.container(key="research_chat_toolbar"):
        history, new = st.columns([5, 1], vertical_alignment="center")
        with history:
            selected = st.selectbox("对话历史", ["", *conversations], key="research_conversation",
                format_func=lambda key: conversations[key]["title"] if key else "新对话",
                label_visibility="collapsed")
            st.session_state["research_active_conversation"] = selected
        with new:
            st.button("新对话", icon=":material/add:", key="research_new_chat",
                      on_click=_new_research_conversation, width="stretch")

    turns = chat.turns(selected) if selected else []
    result_tasks = {item["result_ref"]: item for item in chat.list_result_tasks(selected)} if selected else {}
    if st.session_state.get("research_result_selection_conversation") != selected:
        st.session_state["research_result_selection_conversation"] = selected
        st.session_state["research_result_read_enabled"] = False
        st.session_state["research_result_ref"] = ""
    if st.session_state.get("research_result_ref", "") not in {"", *result_tasks}:
        st.session_state["research_result_ref"] = ""
    if not result_tasks:
        st.session_state["research_result_read_enabled"] = False

    profiles = {p["id"]: p for p in models.list_profiles("chat")}
    preferences = st.session_state.get("research_chat_preferences", {})
    available_workflow = _workflow_catalog_options(ledger)
    if available_workflow is None:
        st.session_state["research_workflow_enabled"] = False
    workflow_selected = bool(st.session_state.get("research_workflow_enabled", False))
    if "research_chat_profile" not in st.session_state and st.session_state.get("research_active_profile") in profiles:
        st.session_state["research_chat_profile"] = st.session_state["research_active_profile"]
    if st.session_state.get("research_chat_profile") not in profiles:
        st.session_state.pop("research_chat_profile", None)
    with st.container(key="research_chat_options"):
        model_column, knowledge_column, options_column = st.columns([3, 2, 1], vertical_alignment="center")
        with model_column:
            profile_id = st.selectbox("对话模型", list(profiles) or [""], key="research_chat_profile",
                format_func=lambda key: _profile_label(profiles[key]) if key else "尚未配置对话模型",
                disabled=not profiles, label_visibility="collapsed")
            st.session_state["research_active_profile"] = profile_id
        with knowledge_column:
            use_knowledge = st.checkbox("结合知识库", value=preferences.get("use_knowledge", True), key="research_use_knowledge",
                on_change=_research_knowledge_mode_changed,
                disabled=workflow_selected,
                help=("开发流程模式使用隔离候选目录；此开关不参与本轮。" if workflow_selected else
                      "仅检索当前可用、经过审核的知识。未找到依据时仍可对话，不会自动导入资料。"))
        profile = profiles.get(profile_id)
        price_known = bool(profile and profile.get("input_usd_per_million") is not None
                           and profile.get("output_usd_per_million") is not None)
        with options_column:
            with st.popover("对话设置", icon=":material/tune:", width="stretch"):
                if workflow_selected:
                    st.session_state["research_evidence_purpose"] = "explanation"
                purpose = st.selectbox("本地证据用途", ["explanation", "recommendation"],
                    format_func=lambda value: "解释与讨论" if value == "explanation" else "研究建议",
                    index=1 if preferences.get("purpose") == "recommendation" else 0, key="research_evidence_purpose",
                    disabled=workflow_selected)
                st.caption("研究建议只使用获准推荐用途的本地证据。模型回复本身不等于已审核结论。")
                input_limit = st.number_input("单轮输入上限", min_value=4096, max_value=131072, value=preferences.get("input_limit", 32768),
                    step=4096, key="research_input_limit")
                output_limit = st.number_input("单轮输出 token 上限", min_value=256, max_value=8192, value=preferences.get("output_limit", 2048),
                    step=256, key="research_output_limit")
                st.caption("输入以保守字节估计约束；长对话仅携带可容纳的完整轮次，并标明省略情况。")
                cost_cap = st.number_input("单轮费用预算（USD）", min_value=0.01, value=preferences.get("cost_cap", 1.0), step=0.1,
                    key="research_cost_cap", disabled=not price_known)
                allow_unknown = st.checkbox("允许费率未知的调用", value=preferences.get("allow_unknown", False), key="research_allow_unknown",
                    disabled=price_known, help="仍限制输入、输出和超时；提供方未返回用量时费用记为未知。")
                grounded_unavailable = (not use_knowledge or st.session_state.get("research_analysis_enabled", False)
                                        or st.session_state.get("research_result_read_enabled", False)
                                        or workflow_selected)
                if grounded_unavailable:
                    st.session_state["research_grounded_mode"] = False
                grounded_mode = st.checkbox("深入查证并逐条附来源", value=False, key="research_grounded_mode",
                    disabled=grounded_unavailable, on_change=_research_analysis_mode_changed,
                    args=("research_grounded_mode",),
                    help="针对问题规划检索、选择获准证据并逐条引用；本轮不执行本地分析或读取分析结果。")
                if grounded_mode:
                    st.caption("深入查证最多 3 次请求（规划检索、选择证据、回答）；每步以本轮选中的输入/输出上限为界，并遵守方法更小的上限；费用按本轮累计。普通聊天仍为单请求。")
                workflow_enabled = False
                if available_workflow is not None:
                    workflow_enabled = st.checkbox("开发流程对话：按来源检查输入", value=False,
                        key="research_workflow_enabled", on_change=_research_analysis_mode_changed,
                        args=("research_workflow_enabled",),
                        help="仅在当前隔离开发目录启用。模型从用户原话提取报告，服务检查前提；候选未发布，不执行分析。")
                    if workflow_enabled:
                        available_workflow = _workflow_wire_options(available_workflow)
                        st.caption("开发候选流程 · 仅解释与输入检查。模型提取可能不完整，用户报告尚未独立核验；本轮不使用正式知识检索开关。")
                        st.caption("本轮最多 3 次模型请求、2 次只读流程检查；每次输入与输出受当前上限约束，费用按本轮累计。")
                assets = {a["asset_id"]: a for a in DatasetService(ledger.workspace).list_assets()}
                analysis_enabled = st.checkbox("本轮使用本地分析工具", value=False,
                    key="research_analysis_enabled", disabled=not assets,
                    on_change=_research_analysis_mode_changed, args=("research_analysis_enabled",),
                    help="发送后可读取所选数据画像，并以固定合同执行小数据 Scrublet 预览；原始矩阵留在本地。")
                result_read_enabled = st.checkbox("本轮只读已有结果", value=False,
                    key="research_result_read_enabled", disabled=not result_tasks,
                    on_change=_research_analysis_mode_changed, args=("research_result_read_enabled",),
                    help="只选择本对话已经关联的分析结果；重新核验并读取汇总，不提交分析或重新拟合。")
                result_ref = None
                if result_read_enabled:
                    chosen_result = st.selectbox("本对话的已有分析结果", ["", *result_tasks],
                        key="research_result_ref", format_func=lambda value: (
                            "请选择要追问的结果" if not value else
                            f"{result_tasks[value]['run_id']} · 第 {result_tasks[value]['attempt']} 次 · {result_tasks[value]['task_status']}"))
                    result_ref = chosen_result or None
                    st.caption("发送后只读取所选任务的已验收摘要；计数来源和科学参数沿用原任务，本轮不会重新执行分析。")
                elif not result_tasks:
                    st.caption("本对话尚无关联的分析结果；已有结果会出现在这里供只读追问。")
                analysis_options = None
                if analysis_enabled and not result_read_enabled and assets:
                    execution_mode = st.selectbox("本轮分析执行方式", ["fixed_tool", "python_program_v1"],
                        key="research_execution_mode", format_func=lambda value: {
                            "fixed_tool": "固定分析工具", "python_program_v1": "受限 Python 编排与一次代码修复"}[value])
                    if execution_mode == "python_program_v1":
                        st.caption("生成并执行受限 Python 来编排所选数据画像与 Scrublet；出现可确认的代码错误时最多修复一次。科学参数沿用下方选择，产物仍须独立验收。")
                    asset_id = st.selectbox("分析数据", list(assets), key="research_analysis_asset",
                        format_func=lambda value: assets[value]["label"] + " · " + value[-12:])
                    provenance = st.text_area("X 矩阵的原始计数来源说明", key="research_count_provenance",
                        help="填写数据来源及为何 X 是未归一化计数。仅整数值或名称不能证明来源。")
                    origin = st.selectbox("数据来源声明", ["unknown", "caller_supplied", "synthetic", "published_derived"],
                        key="research_dataset_origin", format_func=lambda value: {
                            "unknown": "尚不清楚", "caller_supplied": "用户提供",
                            "synthetic": "合成测试数据", "published_derived": "公开来源的衍生数据"}[value])
                    origin_refs = st.text_area("来源 DOI 或公开链接（可选，每行一条）", key="research_dataset_origin_refs",
                        help="仅本地保存来源标识，不会自动访问链接或把来源引用送往模型；最多8条。")
                    rate = st.number_input("预期双细胞比例", min_value=0.001, max_value=0.25,
                        value=None, step=0.01, format="%.4f", key="research_doublet_rate")
                    st.caption("当前支持 X 中的计数、小于等于 1000 细胞及 10000 基因、25 MiB 文件；结果属于代表性预览。最多 3 次模型请求、2 次工具操作；输入输出上限按每次请求，费用预算按本轮累计。")
                    if provenance.strip() and rate is not None:
                        analysis_options = {"asset_id": asset_id, "count_source": "X",
                            "count_provenance": provenance, "expected_doublet_rate": float(rate),
                            "dataset_origin": origin,
                            "dataset_origin_refs": [value.strip() for value in origin_refs.splitlines() if value.strip()]}
                        if execution_mode == "python_program_v1":
                            analysis_options["execution_mode"] = execution_mode
                elif not assets:
                    st.caption("登记本地数据后可以启用分析工具。")
                st.button("模型与设置", key="research_settings", on_click=_navigate, args=("设置",))
                st.button("查看知识与关系", key="research_knowledge", on_click=_navigate, args=("知识库",))
    workflow_options = available_workflow if workflow_enabled else None
    st.session_state["research_chat_preferences"] = {"use_knowledge": use_knowledge, "purpose": purpose,
        "input_limit": input_limit, "output_limit": output_limit, "cost_cap": cost_cap, "allow_unknown": allow_unknown}

    with st.container(key="research_messages", height=480 if turns else "content", border=False, autoscroll=bool(turns)):
        if not turns:
            with st.container(key="research_chat_empty"):
                st.html('<div class="wb-chat-mark">sc</div>')
                st.subheader("今天想研究什么？")
                st.write("直接提问、讨论思路，或一起推敲分析方案。")
                st.caption("无需先上传资料或建立知识库。")
        for turn in turns:
            _display_chat_turn(chat, turn)

    unlocked = bool(profile and (not models.profile_requires_passphrase(profile_id)
                                or st.session_state.get("vault_passphrase")))
    active_turn = ledger.get_state("chat_active:" + selected) if selected else None
    pending_send = bool(active_turn)
    if active_turn:
        _render_chat_control(chat, selected, active_turn,
                             passphrase=st.session_state.get("vault_passphrase", ""))
    blocked = (not profile or not unlocked or (not price_known and not allow_unknown) or pending_send
               or (analysis_enabled and not result_read_enabled and analysis_options is None)
               or (result_read_enabled and result_ref is None))
    with st.container(key="research_composer"):
        if not profile:
            st.info("配置一个对话模型即可开始，无需接入资料。")
            st.button("配置对话模型", key="research_setup_model", on_click=_navigate, args=("设置",))
        elif not unlocked:
            st.info("模型已选择。在设置中解锁当前会话后，即可开始对话。")
            st.button("解锁模型连接", key="research_unlock_model", on_click=_navigate, args=("设置",))
        elif not price_known and not allow_unknown:
            st.info("所选模型尚未配置费率。可在对话设置中允许费率未知的调用，或在模型设置中填写费率。")
        elif pending_send:
            st.info("这段对话仍有状态未确定的请求。可点击上方“新对话”继续，系统不会自动重发旧请求。")
        elif result_read_enabled and result_ref is None:
            st.info("请在对话设置中明确选择一个已有分析结果，再发送只读追问。")
        elif analysis_enabled and analysis_options is None:
            st.info("请在对话设置中填写计数来源和预期双细胞比例，再发送分析请求。")
        prompt = st.chat_input("向 scKG 提问，Enter 发送 · Shift+Enter 换行", key="research_prompt",
                               disabled=blocked, max_chars=8000)
        st.caption("发送后，问题、必要的对话上下文及流程候选将用于模型提取与输入检查。对话保存在本地。" if workflow_options else
                   "发送后，问题、必要的对话上下文及所选知识依据将交给当前模型。对话保存在本地。")
        if prompt:
            conversation_id = selected or chat.create_conversation(title=prompt[:48])["id"]
            st.session_state["research_selected_after_send"] = conversation_id
            budget = {"max_input_tokens": int(input_limit), "max_output_tokens": int(output_limit),
                      "timeout_seconds": 60, "allow_unknown_cost": allow_unknown}
            if price_known:
                budget["max_cost_usd"] = cost_cap
            try:
                from .chat_runs import ChatRunService
                send_options = dict(profile_id=profile_id,
                    use_knowledge=use_knowledge, purpose=purpose, budget=budget,
                    request_id=uuid.uuid4().hex, analysis_options=analysis_options, result_ref=result_ref,
                    grounded_mode=bool(grounded_mode and use_knowledge and not analysis_enabled and not result_read_enabled))
                if workflow_options is not None:
                    send_options.update(workflow_options=workflow_options, use_knowledge=False, purpose="explanation")
                turn = chat.submit_send(conversation_id, prompt, **send_options)
                phrase = st.session_state.get("vault_passphrase", "")
                dispatch = ChatRunService(ledger).launch(turn["id"],
                    lambda token: chat.process_registered_send(turn["id"], token, passphrase=phrase))
                if dispatch.get("dispatch_status") == "workspace_busy_not_started":
                    st.session_state["research_dispatch_notice"] = "工作台已有运行中的发送；本次已登记但尚未启动，可稍后明确启动或取消。"
            except Exception as exc:
                # Retain an actionable error across the rerun used to select a new conversation.
                st.session_state["research_send_error"] = f"{type(exc).__name__} · {str(exc)[:400]}"
            st.rerun()
        if error := st.session_state.pop("research_send_error", None):
            st.error("消息未能发送：" + error)
        if notice := st.session_state.pop("research_dispatch_notice", None):
            st.info(notice)


def _render_chat_control(chat, conversation_id, turn_id, *, passphrase=""):
    """Only explicit buttons mutate execution; ordinary display stays read-only."""
    from .chat_runs import ChatRunService
    runs = ChatRunService(chat.ledger)
    snapshot = runs.snapshot(turn_id, conversation_id=conversation_id)
    if snapshot is None:
        st.caption("历史发送尚无可核对的执行归属记录；不会自动重新运行。")
        return
    labels = {"pending": "本次发送已登记，尚未启动", "running": "本次发送正在处理",
        "cancel_requested": "已请求停止，正在核对已发生的调用与本地任务",
        "result_unknown": "执行完成状态待核对；系统不会自动重发"}
    st.caption(labels.get(snapshot["status"], "本次发送状态：" + snapshot["status"]))
    refresh, cancel, reconcile = st.columns(3)
    if refresh.button("刷新运行状态", key="chat_refresh_" + turn_id):
        st.rerun()
    if cancel.button("停止本次发送", key="chat_cancel_" + turn_id,
                     disabled=snapshot["status"] not in {"pending", "running", "cancel_requested"}):
        runs.request_cancel(conversation_id, turn_id)
        st.rerun()
    if reconcile.button("核对中断状态", key="chat_reconcile_" + turn_id,
                        disabled=not snapshot.get("started")):
        runs.reconcile(conversation_id, turn_id)
        st.rerun()
    if snapshot["status"] == "pending" and not snapshot.get("started"):
        st.caption("尚未启动的发送不会自动排队执行。")
        if st.button("启动这次尚未执行的发送", key="chat_start_" + turn_id):
            dispatch = runs.launch(turn_id,
                lambda token: chat.process_registered_send(turn_id, token, passphrase=passphrase))
            if dispatch.get("dispatch_status") == "workspace_busy_not_started":
                st.info("工作台仍有运行中的发送，本次尚未启动。")
            else:
                st.rerun()


def _display_grounded_answer(turn, *, ledger=None):
    """Render only the usable server-bound normalized answer and citation map."""
    run = turn.get("grounded_run") or {}
    answer = run.get("normalized_answer")
    manifest = turn.get("citation_manifest") or {}
    if (not turn.get("usable") or not isinstance(answer, dict)
            or manifest.get("schema_version") != "chat-source-citations-v1"
            or manifest.get("validation") != "selected_id_binding_only_not_semantic_support"):
        return False
    items = manifest.get("items", [])
    if not isinstance(items, list):
        return False
    by_id, numbers = {}, []
    for item in items:
        if (not isinstance(item, dict) or type(item.get("number")) is not int or item["number"] < 1
                or not isinstance(item.get("candidate_id"), str) or item["candidate_id"] in by_id
                or not isinstance(item.get("unit"), dict)
                or item["unit"].get("candidate_id") != item["candidate_id"]):
            return False
        by_id[item["candidate_id"]] = item
        numbers.append(item["number"])
    if sorted(numbers) != list(range(1, len(items) + 1)):
        return False
    steps = answer.get("steps", [])
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return False
    cited = {candidate for step in steps for candidate in step.get("evidence_ids", [])}
    if cited != set(by_id):
        return False
    if "derived_reported_premises" in answer:
        st.caption("用户原话 · 模型从用户文本提取；抽取未验证，未独立测量")
        premises = answer.get("derived_reported_premises") or []
        if not premises:
            st.caption("模型未提取前提；这不代表用户未提供信息或方法不存在前提。")
        for premise in premises:
            if not isinstance(premise, dict) or not isinstance(premise.get("quote"), str):
                continue
            source = {"question": "原问题", "dataset_profile": "数据画像"}.get(premise.get("source"), "输入来源")
            st.caption(str(premise.get("premise_id", "")) + " · " + source)
            st.text(premise["quote"])
            if premise.get("source") == "question":
                spans = premise.get("unicode_spans", [])
                ranges = [f"[{span['start']}, {span['end']})" for span in spans
                          if isinstance(span, dict) and type(span.get("start")) is int and type(span.get("end")) is int]
                if ranges:
                    st.text("原问题 Unicode 字符范围：" + "、".join(ranges))
            elif premise.get("pointer"):
                st.text("数据画像 JSON Pointer：" + str(premise["pointer"]))
        checks = answer.get("premise_checks") or []
        if checks:
            st.caption("对方法前提的模型判断 · 不是测量结果或独立科学审核")
            status_labels = {"reported_met": "按用户报告满足；尚未独立测量",
                "reported_unmet": "按用户报告不满足", "unknown": "模型尚不能判断是否满足"}
            action_labels = {"conditional_plan": "条件性计划，尚未验证", "blocked": "当前行动被阻断",
                             "needs_evidence": "当前行动尚缺依据"}
            for check in checks:
                if not isinstance(check, dict):
                    continue
                st.text(str(check.get("premise_id", "")) + " · "
                    + status_labels.get(check.get("reported_status"), "状态未明确") + " · "
                    + action_labels.get(check.get("action_status"), "行动状态未明确"))
    required = ((run.get("answer_run") or {}).get("input_material") or {}).get("required_evidence")
    if isinstance(required, dict):
        coverage_labels = {
            "complete_for_declared_requirements": "模型声明的必要证据已保留在最终输入中；仅核对覆盖，不代表科学支持或充分性。",
            "not_declared": "模型未声明必要证据；这不代表该方法不存在前提。",
            "missing": "模型声明的必要证据未完整保留，当前来源不足。",
        }
        if required.get("status") in coverage_labels:
            st.caption(coverage_labels[required["status"]])
    decision_scope = answer.get("decision_scope")
    if isinstance(decision_scope, dict):
        st.caption("本轮核对范围 · 模型划分，尚未独立验证是否覆盖全部用户意图")
        core = [row["question"] for row in decision_scope.get("checks", []) if row.get("role") == "core"]
        if core:
            for question in core:
                st.text(question)
        else:
            st.caption("模型未声明核心问题；这不表示问题没有前提或已经回答完整。")
        background = [row["question"] for row in decision_scope.get("checks", []) if row.get("role") == "background"]
        if background:
            with st.expander("背景核对问题 · 不代表已逐项回答或核验"):
                for question in background:
                    st.text(question)
    st.write(answer.get("decision", ""))
    st.caption(f"本回答实际引用 {len(items)} 条证据；编号由服务端绑定。引用对应关系已核对，科学支持与可执行性尚未独立复核。")
    scope_labels = {"source_bound": "来源约束陈述", "proposal": "待验证建议", "needs_evidence": "待补证据"}
    for index, step in enumerate(steps, 1):
        with st.container(border=True):
            st.caption(f"步骤 {index} · {scope_labels.get(step.get('scope'), '范围未明确')}")
            if step.get("factual_claim"):
                st.write("事实陈述", step["factual_claim"])
            st.write("操作建议", step.get("instruction", ""))
            if step.get("preconditions"):
                st.caption("本步骤提出的前提（完整来源条件见下方原文详情）")
                st.write("；".join(step["preconditions"]))
            references = [by_id[candidate] for candidate in step.get("evidence_ids", [])]
            if references:
                st.caption("引用来源 · " + " ".join(f"[{item['number']}]" for item in references))
                for item in references:
                    with st.expander(f"来源 [{item['number']}] · 原文、完整条件与限制"):
                        _display_evidence_unit(item["unit"], ledger=ledger)
    if "typed_missing" in answer:
        missing_labels = {"not_supplied": "未提供输入", "independent_verification_missing": "用户报告待独立核验",
                          "source_evidence_missing": "缺来源依据"}
        for missing in answer.get("typed_missing") or []:
            if not isinstance(missing, dict):
                continue
            st.caption(missing_labels.get(missing.get("kind"), "待核对的缺失项"))
            st.text(str(missing.get("text", "")))
    elif answer.get("missing"):
        st.caption("仍缺少的信息与依据")
        for missing in answer["missing"]:
            st.write(missing)
    return True


def _display_workflow_review(turn):
    """Render only the authoritative ChatService view, never bless a cached run."""
    if not turn.get("usable"):
        return False
    review = turn.get("workflow_review")
    if isinstance(review, dict):
        from .workflow_inputs_ui import render_workflow_review
        render_workflow_review(review)
    else:
        st.info("本轮尚无已完成的流程输入检查；请根据追问补充信息。")
    interpretations = turn.get("workflow_interpretations") or []
    with st.expander("模型提取的用户报告 · 原话与定位"):
        st.caption("模型从用户文本提取，尚未独立核验；原话匹配不代表提取完整或语义判断正确。")
        if not interpretations:
            st.text("本轮没有可展示的已提取报告；这不表示用户没有提供信息。")
        for item in interpretations:
            st.text("输入前提：" + str(item.get("premise_id", "")) + " · " + str(item.get("report_pointer", "")))
            reported = {None: "未知", False: "报告不具备", True: "报告具备"}.get(item.get("reported_value"), "未知")
            st.text("模型提取结果：" + reported)
            st.text(str(item.get("quote", "")))
            ranges = [f"[{span['start']}, {span['end']})" for span in item.get("unicode_spans", [])]
            if ranges:
                st.text("用户原话 Unicode 字符范围：" + "、".join(ranges))
            st.text("来源轮次：" + str(item.get("user_turn_id", "未记录")))
            st.text("提取请求：" + str(item.get("call_id", "未记录")))
    return True


def _display_chat_turn(chat, stored_turn):
    turn = chat.view_turn(stored_turn)
    with st.chat_message("user"):
        st.markdown(turn["prompt"])
    with st.chat_message("assistant"):
        workflow = bool(turn.get("workflow_options") or turn.get("workflow_run"))
        if workflow:
            st.caption("开发候选流程对话 · 来源候选未发布。输入状态由只读检查给出，模型段落不是科学或执行审核。")
        if not workflow and (outcome := turn.get("analysis_outcome")):
            if outcome["state"] == "result_read":
                st.success("已读取已有结果并核验产物；本轮未执行分析，也未重新拟合。")
            elif outcome["validated_preview"]:
                st.success("本地分析预览已完成，产物通过工程验收；不代表科学效力已经验证。")
            else:
                labels = {"not_run": "本轮尚未执行分析", "profile_only": "本轮只建立了数据画像",
                    "profile_failed": "数据画像未完成；本轮尚未执行分析",
                    "failed_before_task": "分析未成功提交", "not_validated": "分析任务尚未通过产物验收",
                    "result_unavailable": "已有结果当前不可读取或未通过验收；本轮未执行分析",
                    "unverifiable": "当前无法核验分析任务与产物"}
                st.info(labels.get(outcome["state"], outcome["state"]))
            summary = outcome.get("summary") or {}
            if (summary.get("status") == "validated_preview_summary"
                    and (outcome["state"] == "result_read" or outcome["validated_preview"])):
                metrics = summary["metrics"]
                cells, doublets, rate = st.columns(3)
                cells.metric("预览细胞数", f"{metrics['n_cells']:,.0f}")
                doublets.metric("预测为双细胞", f"{metrics['predicted_doublet_count']:,.0f}")
                rate.metric("预测调用比例", f"{metrics['predicted_doublet_call_rate']:.1%}")
                st.caption("预测调用比例是本次预览中模型预测为双细胞的比例，不是准确率或真实双细胞率。")
                if summary.get("threshold", {}).get("status") == "not_recorded":
                    st.caption("阈值未记录；不能从预测调用比例或分数反推。")
                recovery = summary.get("operational_recovery") or {}
                if recovery.get("status") == "repaired_validated":
                    st.caption("首次启动失败后，系统在原预算内恢复一次；科学参数保持原样，最终产物已重新验收。")
        grounded = bool(turn.get("grounded_mode") or turn.get("grounded_run"))
        grounded_run = turn.get("grounded_run") or {}
        if grounded or workflow:
            budget = turn.get("agent_budget") or grounded_run.get("agent_budget") or {}
            recorded_calls = budget.get("actual_receipted_call_count", budget.get("model_calls"))
            if type(recorded_calls) is int and recorded_calls >= 0:
                st.caption(f"本轮模型调用：已记录 {recorded_calls} 次回执；本轮上限 3 次。")
            if budget.get("dispatch_unknown") is True:
                st.caption("另有阶段的请求发送状态尚不确定；费用可能未知，系统不会自动重发。")
        if turn.get("answer"):
            if workflow:
                if turn.get("usable"):
                    st.text(turn["answer"])
                    _display_workflow_review(turn)
                else:
                    st.warning("开发流程回答的当前来源或提取记录不可用，已隐藏内容；请查看本轮记录。")
            elif grounded:
                if not _display_grounded_answer(turn, ledger=getattr(chat, "ledger", None)):
                    st.warning("深入查证回答的当前来源映射不可用，已隐藏内容；请查看本轮记录。")
            else:
                st.markdown(turn["answer"])
        status = turn.get("current_status", turn["status"])
        if status == "pending":
            st.warning("这次请求尚无完成记录。若运行已中断，模型端结果和费用可能未知；系统不会自动重发。")
        elif status == "running":
            st.info("本次发送正在处理，可刷新状态或请求停止；刷新不会重新调用模型。")
        elif status == "cancel_requested":
            st.warning("已请求停止。正在等待已发出的请求或本地任务结束核对；已发生的费用与产物仍保留。")
        elif status == "cancelled":
            st.info("本次发送已停止，既有调用记录与产物保留。")
        elif status == "result_unknown":
            st.warning("本次执行的完成状态待核对，回答不作为当前依据；系统不会自动重发请求。")
        elif status == "result_invalidated":
            st.warning("已有分析结果当前无法重新验收，这条历史回答不能作为当前结果依据。")
        elif status in {"analysis_failed", "analysis_incomplete", "analysis_unknown"}:
            st.warning("本轮分析未能确认完整通过验收，已隐藏模型回答；已有任务和调用记录保留。")
        elif turn.get("error") or (grounded and grounded_run.get("error")):
            detail = turn.get("error")
            if grounded:
                stop = grounded_run.get("error") or detail or {}
                reason = stop.get("reason_code") if isinstance(stop, dict) else None
                labels = {
                    "required_final_evidence_missing": "最终输入未能保留模型声明的必要完整证据，已在回答调用前停止；这不代表所问命题为假。",
                    "no_published_evidence": "当前没有可用于本轮问答的已发布知识，深入查证已停止。",
                    "no_retrieved_evidence": "本轮未检索到可用来源，深入查证已停止；这不代表所问命题为假。",
                    "pricing_unknown_with_monetary_cap": "模型费率未知，无法核对本轮费用上限，深入查证已停止。",
                    "unknown_cost_not_authorized": "模型费用未知且本轮未授权未知费用，深入查证已停止。",
                    "cost_unknown_with_monetary_cap": "已有请求的费用未知，无法核对剩余费用预算，深入查证已停止。",
                    "cost_cap_exhausted": "本轮费用预算已用尽，深入查证已停止。",
                    "cumulative_token_cap": "本轮累计 token 预算不足，深入查证已停止。",
                    "model_call_limit": "本轮模型调用数已达上限，深入查证已停止。",
                    "final_usage_exceeds_or_cannot_verify_budget": "最终用量超出预算或暂时无法核验，本轮回答不作为可用结果展示。",
                    "invalid_budget": "本轮预算设置无效，深入查证未启动。",
                    "history_profile_exceeds_12000_bytes": "本轮对话上下文超过查证输入上限，深入查证已停止。",
                    "explicit_chat_profile_required": "本轮缺少有效的聊天模型配置，深入查证未启动。",
                    "planner_failed": "本轮检索规划未完成，深入查证已停止；已产生的用量保留在本轮记录中。",
                    "retrieval_failed": "本轮来源检索未完成，深入查证已停止；这不代表所问命题为假。",
                    "selector_failed": "本轮证据选择未完成，深入查证已停止；已产生的用量保留在本轮记录中。",
                    "answer_failed": "本轮有来源回答未完成，深入查证已停止；已产生的用量保留在本轮记录中。",
                    "answer_preflight_stopped": "回答请求在发送前已停止；已有规划与选择调用保留，本阶段未新增模型调用。",
                    "selector_preflight_stopped": "证据选择请求在发送前已停止；已有调用保留，本阶段未新增模型调用。",
                    "planner_preflight_stopped": "检索规划请求在发送前已停止，本阶段未新增模型调用。",
                }
                st.warning(labels.get(reason if isinstance(reason, str) else None,
                    "本轮深入查证未完成，请查看本轮状态与预算记录；系统不会自动重试。"))
            else:
                st.error("本次回复未完成：" + str(detail.get("message", detail) if isinstance(detail, dict) else detail)[:500])
        elif not turn.get("answer"):
            st.warning("这条回复当前不可用，请查看下方说明并重新提问。")
        for notice in turn.get("notices", []):
            st.caption(str(notice))
        package = turn.get("evidence_package") or {}
        current_ids = {unit["candidate_id"] for unit in package.get("units", [])}
        units_by_id = {}
        if turn.get("usable"):
            for context_package in [package, *turn.get("evidence_packages", [])]:
                for unit in context_package.get("units", []):
                    units_by_id.setdefault(unit["candidate_id"], unit)
        units = list(units_by_id.values())
        if turn.get("answer"):
            if workflow:
                st.caption("上方流程来源为隔离开发候选；用户报告、来源事实和本机执行资格分别记录。")
            elif grounded:
                st.caption(f"另附 {len(units)} 条对话上下文资料；不计为本回答实际引用。")
            else:
                st.caption(f"提供了 {len(units)} 条本地依据 · 模型回复尚未逐条核验" if units
                           else "模型一般知识与推理 · 未经本地证据核验")
        if units:
            with st.expander(f"本轮知识依据 · {len(units)} 条"):
                for index, unit in enumerate(units, 1):
                    origin = "本轮检索" if unit["candidate_id"] in current_ids else "来自此前对话上下文"
                    st.caption(f"依据 {index} · {origin}")
                    _display_evidence_unit(unit)
        if turn.get("analysis_options") or turn.get("result_selection"):
            program_mode = (turn.get("analysis_options") or {}).get("execution_mode") == "python_program_v1"
            if program_mode:
                st.caption("本轮使用受限 Python 编排；源码由模型生成，独立验收决定结果是否可用。最多执行初始程序和一次补丁。")
                with st.expander("程序源码与补丁", expanded=False):
                    for index in range(3):
                        decision = chat.ledger.get_record("chat_agent_decision", f"{turn['id']}:{index}") or {}
                        action = decision.get("action") or {}
                        if action.get("action") in {"execute_program", "repair_program"}:
                            st.caption("初始程序" if action["action"] == "execute_program" else "绑定原源码的一次补丁")
                            if action.get("parent_source_sha256"):
                                st.text("原源码 SHA256：" + action["parent_source_sha256"])
                            st.code(action.get("source", ""), language="python")
            read_only = bool(turn.get("result_selection"))
            task_ids = list(dict.fromkeys([*turn.get("analysis_task_ids", []),
                                          *turn.get("referenced_analysis_task_ids", [])]))
            st.caption(f"本轮包含 {len(turn.get('agent_steps', []))} 次本地工具操作；" + (
                "只读结果不重新提交分析，任务状态属于原分析任务。" if read_only else "分析状态以任务与产物验收为准。"))
            with st.expander("结果读取与原任务状态" if read_only else "分析操作与真实任务状态", expanded=bool(task_ids)):
                st.json(turn.get("agent_steps", []))
                from .analysis import AnalysisService
                analysis = AnalysisService(chat.ledger.workspace)
                for task_id in task_ids:
                    try:
                        task = analysis.get_task_snapshot(task_id)
                        st.write(f"分析任务 · {task['status']} · {task_id}")
                    except (KeyError, ValueError):
                        st.warning("分析任务记录缺失，不能确认完成。")
                st.button("查看分析产物", key="turn_results_" + turn["id"],
                          on_click=_navigate, args=("运行结果",))
        with st.expander("本轮记录"):
            receipt = turn.get("receipt") or {}
            st.caption("模型配置 · " + turn.get("profile_id", "未记录"))
            if receipt:
                st.caption("实际返回模型 · " + str(receipt.get("returned_model") or "提供方未报告"))
                st.write("最后一次请求用量" if turn.get("analysis_options") or turn.get("result_selection") or grounded or workflow else "用量", receipt.get("usage", {}))
                costs = turn.get("agent_budget") or receipt
                st.write("本轮费用（按配置费率估算）", costs.get("cost_usd") if costs.get("cost_known") else "未知")
            record = {"status": status, "request_id": turn.get("request_id"),
                     "release_id": package.get("release_id"), "context": turn.get("context", {}),
                     "agent_budget": turn.get("agent_budget"), "model_receipts": turn.get("receipts", [])}
            if workflow:
                record.update(workflow_run=turn.get("workflow_run"), agent_steps=turn.get("agent_steps", []))
            st.json(record)


def _research_query(ledger):
    knowledge = _knowledge(ledger)
    if knowledge is None:
        st.info("证据检索服务尚未接入。可先登记来源、配置模型和查看任务。")
        return
    release = knowledge.current_release()
    if release:
        st.caption(f"当前知识版本：{release.get('id', 'unknown')}")
    with st.form("evidence_search"):
        query = st.text_input("研究问题", placeholder="例如：在我的实验条件下，应核查哪些方法前提？")
        purpose = st.selectbox("证据用途", ["explanation", "recommendation"],
                               format_func=lambda x: "解释与了解" if x == "explanation" else "科学推荐")
        submit = st.form_submit_button("检索正式证据", disabled=not release)
    if submit:
        result = _json(knowledge.search(query, purpose=purpose, limit=10))
        st.session_state["last_evidence_package"] = result
    result = st.session_state.get("last_evidence_package")
    if result and (result.get("namespace") != ledger.workspace.namespace
                   or result.get("release_id") != (release.get("id") if release else None)
                   or result.get("governance_version") != ledger.get_state("governance_version", 0)):
        st.session_state.pop("last_evidence_package", None)
        st.info("知识版本或证据使用状态已变化，请重新检索。")
        result = None
    elif result and not submit:
        # A blob may be damaged without a governance event. Revalidate exact
        # evidence on every redisplay instead of trusting a session cache.
        result = _json(knowledge.search(result.get("retrieval", {}).get("query", ""),
                                       purpose=result["purpose"], limit=10))
        st.session_state["last_evidence_package"] = result
    if result:
        st.caption(f"本次检索固定版本：{result.get('release_id')}；用途：{result.get('purpose')}")
        if not result.get("units"):
            st.info("本次检索未找到可用证据；这不表示问题中的事实不存在。")
        for i, unit in enumerate(result.get("units", []), 1):
            with st.expander(f"证据 {i} · {str(unit.get('claim', {}).get('proposition', unit.get('candidate_id', '知识单元')))[:100]}"):
                _display_evidence_unit(unit)
        if result.get("gaps"):
            st.write("未决事项", result["gaps"])
        with st.expander("检索范围与依据"):
            st.json(result.get("retrieval", {}))


def _knowledge_page(ledger):
    knowledge = _knowledge(ledger)
    candidates = knowledge.list_candidates()
    release = knowledge.current_release()
    network = _network(ledger)
    network_view = network.view(max_nodes=500) if network else {}
    overview, units, literature, graph = st.tabs(["方法与工具", "知识单元", "来源资料", "图谱探索"])
    with overview:
        _method_library(ledger, network_view, release)
    with units:
        with st.container(border=True, key="wb_card_units"):
            st.subheader("正式知识")
            query = st.text_input("搜索知识单元", placeholder="搜索命题、适用条件或方法名称")
            package = knowledge.search(query, limit=100)
            visible_units = network_view.get("claims", []) if not query.strip() and network_view.get("claims") else package.units
            navigation_notes = {unit["candidate_id"]: unit.get("navigation_scope_note") for unit in network_view.get("claims", [])}
            visible_units = [{**unit, "navigation_scope_note": navigation_notes.get(unit.get("candidate_id"))} for unit in visible_units]
            if release:
                st.caption(f"当前版本清单 {len(release['units'])} 条 · 当前可读 {len(visible_units)} 条" + ("（关键词检索最多返回 100 条）" if query.strip() else ""))
            if not visible_units:
                _empty("暂无可用的正式知识", "新资料核验和审核后，将在这里显示命题、条件与原文依据。")
            page_count = max(1, (len(visible_units) + 11) // 12)
            if st.session_state.get("knowledge_unit_page", 1) not in range(1, page_count + 1):
                st.session_state.pop("knowledge_unit_page", None)
            chosen_page = st.selectbox("知识单元页码", list(range(1, page_count + 1)),
                                       format_func=lambda n: f"第 {n} / {page_count} 页", key="knowledge_unit_page")
            for unit in visible_units[(chosen_page - 1) * 12:chosen_page * 12]:
                with st.expander(unit["claim"]["proposition"]):
                    _display_evidence_unit(unit, ledger=ledger)
        with st.expander("候选审核"):
            _review_candidates(knowledge, candidates)
        with st.expander("变更与发布"):
            _publish_candidates(knowledge, candidates, release)
    with literature:
        with st.container(border=True, key="wb_card_literature"):
            _source_library(ledger, SourceService(ledger))
    with graph:
        with st.container(border=True, key="wb_card_graph"):
            _graph_view(knowledge, network=network, network_view=network_view, ledger=ledger)
    with st.expander("高级证据检索"):
        _research_query(ledger)
    if ledger.get_state("workflow_input_catalog") is not None:
        with st.expander("流程输入检查（开发预览）"):
            from .workflow_inputs_ui import render_workflow_inputs
            render_workflow_inputs(ledger)
    if ledger.get_state("workflow_method_catalog") is not None:
        with st.expander("方法配置与适用条件（开发预览）"):
            from .workflow_methods_ui import render_workflow_methods
            render_workflow_methods(ledger)
    if ledger.get_state("prediction_semantics_catalog") is not None:
        with st.expander("预测产物分数定义（开发预览）"):
            from .prediction_semantics_ui import render_prediction_semantics
            render_prediction_semantics(ledger)
    with st.expander("维护与版本"):
        _maintenance(ledger, knowledge, candidates)


def _locator_label(locator):
    names = {"page": "页", "page_number": "页", "section": "章节", "section_title": "章节",
             "paragraph": "段落", "paragraph_index": "段落", "line": "行", "line_start": "起始行",
             "line_end": "结束行", "heading": "标题", "table": "表", "figure": "图", "xpath": "文档路径"}
    readable = [f"{names[key]} {value}" for key, value in locator.items() if key in names and value is not None]
    return " · ".join(readable) or "精确文本锚点（完整定位见技术记录）"


def _display_evidence_unit(unit, *, ledger=None):
    claim = unit.get("claim", {})
    st.write(claim.get("proposition", ""))
    if unit.get("navigation_scope_note"):
        st.info("能力边界 · " + unit["navigation_scope_note"])
    if claim.get("assertion_kind") == "hypothesis":
        st.warning("作者假说 · 可用于解释与讨论，不能视为已证实机制。")
    uses = unit.get("allowed_uses", [])
    if uses:
        st.caption("获准用途 · " + "、".join({"explanation": "解释与讨论", "recommendation": "有条件的研究建议"}.get(value, value) for value in uses))
    st.caption("适用条件")
    st.write("；".join(claim.get("conditions", [])) or "原文未明确报告")
    if claim.get("unknowns"):
        st.caption("未知与限制")
        st.write("；".join(claim["unknowns"]))
    if claim.get("typed_attributes"):
        st.caption("可查询属性 · 每项绑定本命题原文锚点")
        st.dataframe([{"属性": item["name"], "值": item["value"],
                       "限定": "；".join(item.get("qualifiers", [])),
                       "原文锚点序号": ", ".join(str(index + 1) for index in item["evidence_anchor_indices"])}
                      for item in claim["typed_attributes"]], hide_index=True, width="stretch")
    for evidence in unit.get("evidence", []):
        source = ledger.get_record("source", evidence.get("source_id", "")) if ledger else None
        st.caption("原文依据 · " + (_source_label(source) if source else evidence.get("filename", "原文证据")))
        # Render source text as text, so embedded Markdown cannot load remote media.
        st.html('<blockquote style="white-space:pre-wrap;border-left:3px solid #d4ddd8;margin:0;padding:8px 16px;line-height:1.65">'
                + escape(evidence.get("quote", "")) + '</blockquote>')
        st.caption(_locator_label(evidence.get("locator", {})))
    with st.expander("完整记录与版本"):
        st.json(unit)


def _review_candidates(knowledge, candidates):
    if not candidates:
        st.info("尚无候选知识。来源登记和解析不会自动产生科学断言。")
    else:
        lookup = {c["id"]: c for c in candidates}
        chosen = st.selectbox("候选知识", list(lookup),
                              format_func=lambda key: str(lookup[key].get("claim", {}).get("proposition", key))[:130] + " · " + key[-12:])
        candidate = lookup[chosen]
        view_key = "review_seen:" + chosen
        displayed_binding = {"content_hash": candidate["content_hash"],
                             "assessment_id": (candidate.get("assessment") or {}).get("id")}
        previous_binding = st.session_state.get(view_key, displayed_binding)
        st.write(candidate.get("claim", {}).get("proposition", chosen))
        if candidate.get("origin", {}).get("kind") == "external_session":
            profile = knowledge.ledger.get_record("external_model_profile", candidate["origin"]["external_profile_id"]) or {}
            model = profile.get("model_variant") or profile.get("model_family", "未记录模型")
            review_status = "已有人审记录" if candidate.get("review") else "待人工审核"
            st.caption(f"{model} · {profile.get('runtime', '外部 Agent')} 会话抽取 · 用量与费用未知 · {review_status}")
        ledger = getattr(knowledge, "ledger", None)
        revisions = ledger.list_records("candidate_revision_proposal") if ledger else []
        for revision in revisions:
            if chosen == revision.get("old_candidate_id"):
                st.warning("此候选已有修订提案，旧记录保留用于追溯。请先查看修订后的候选；修订不代表人工批准。")
                st.caption("修订候选 · " + revision["new_candidate_id"])
            elif chosen == revision.get("new_candidate_id"):
                revision_review_status = "已有人工审核记录" if candidate.get("review") else "仍需人工审核"
                st.caption("修订自 · " + revision["old_candidate_id"] + " · " + revision_review_status)
            else:
                continue
            with st.expander("查看修订关系"):
                st.json(revision)
        with st.expander("原文锚点、条件与核验", expanded=True):
            claim = candidate.get("claim", {})
            st.caption("适用条件")
            st.write("；".join(claim.get("conditions", [])) or "原文未明确报告")
            if claim.get("unknowns"):
                st.caption("未知与限制")
                st.write("；".join(claim["unknowns"]))
            if claim.get("typed_attributes"):
                st.caption("可查询属性（逐项绑定下方原文）")
                st.dataframe([{"属性": item["name"], "值": item["value"],
                               "限定": "；".join(item.get("qualifiers", [])),
                               "原文锚点序号": ", ".join(str(index + 1) for index in item["evidence_anchor_indices"])}
                              for item in claim["typed_attributes"]], hide_index=True, width="stretch")
            try:
                evidence = knowledge.evidence(chosen)
                for anchor in evidence:
                    st.caption(anchor.get("filename", "绑定原文"))
                    st.code(anchor.get("quote", ""), language=None)
                    st.caption("定位 · " + json.dumps(anchor.get("locator", {}), ensure_ascii=False))
            except Exception as exc:
                _error(exc)
                st.warning("原文证据当前无法核验。可使用维护入口暂停相关来源；正式批准仍由服务端核验原件。")
            assessment = (candidate.get("assessment") or {}).get("result", {})
            relations = {"support": "支持", "refute": "反驳", "neutral": "无直接支持", "indeterminate": "尚不能确定"}
            st.caption("证据核验")
            st.write(relations.get(assessment.get("relation"), "尚未完成核验"))
            if assessment.get("extent"):
                st.caption("支持范围 · " + {"full": "完整", "partial": "部分", "none": "无"}.get(assessment["extent"], assessment["extent"]))
            if assessment.get("rationale"):
                st.write(assessment["rationale"])
            if assessment.get("limitations"):
                st.caption("核验限制 · " + "；".join(assessment["limitations"]))
            score = claim.get("model_self_score")
            st.caption(f"模型自评：{score if score is not None else '未提供'} · 未经校准，不代表正确概率")
            with st.expander("完整候选记录"):
                st.json(candidate)
        with st.form("review_candidate"):
            actor = st.text_input("审核人", key="review_actor")
            decision = st.selectbox("审核决定", ["defer", "approve", "reject"],
                                    format_func=lambda x: {"defer": "暂缓／需要补证", "approve": "批准所选用途", "reject": "拒绝"}[x])
            uses = st.multiselect("允许用途", ["explanation", "recommendation"], default=[])
            reason = st.text_area("审核理由", key="review_reason")
            submit = st.form_submit_button("保存确切修订的审核决定")
        st.session_state[view_key] = displayed_binding
        if submit:
            result = knowledge.review(chosen, actor=actor, decision=decision, allowed_uses=uses,
                                      reason=reason, expected_hash=previous_binding["content_hash"],
                                      expected_assessment_id=previous_binding["assessment_id"])
            st.session_state["knowledge_refresh_notice"] = "审核决定已保存，页面已按最新使用资格刷新；此操作未创建新的知识版本。"
            st.rerun()


def _publish_candidates(knowledge, candidates, release):
    approved = [c for c in candidates if c.get("review") and c["review"].get("decision") == "approve"]
    current_ids = [u["candidate_id"] for u in release["units"]] if release else []
    if not approved and not current_ids:
        st.info("暂无已批准候选可供发布。")
    else:
        options = list(dict.fromkeys([*current_ids, *[c["id"] for c in approved]]))
        st.warning("这里定义完整新版本：未选中的旧知识将不在新版本中。默认保留当前版本全部成员。")
        selected = st.multiselect("完整新版本的知识清单", options, default=current_ids,
                                  key="release_selection_" + (release["id"] if release else "first"))
        added, removed = sorted(set(selected) - set(current_ids)), sorted(set(current_ids) - set(selected))
        candidate_by_id = {candidate["id"]: candidate for candidate in candidates}
        manifest = []
        for candidate_id in sorted(selected):
            candidate = candidate_by_id[candidate_id]
            review = candidate.get("review") or {}
            manifest.append({"candidate_id": candidate_id, "candidate_hash": candidate["content_hash"],
                             "review_id": review.get("id"), "assessment_id": review.get("assessment_id"),
                             "allowed_uses": review.get("allowed_uses", []), "review_decision": review.get("decision")})
        a, b, c = st.columns(3)
        a.metric("新版本成员", len(selected))
        b.metric("新增", len(added))
        c.metric("移出本版本", len(removed))
        if manifest:
            st.dataframe([{"知识单元": candidate_by_id[row["candidate_id"]].get("claim", {}).get("proposition", row["candidate_id"]),
                           "允许用途": "、".join(row["allowed_uses"]), "审核版本": row["review_id"]} for row in manifest], hide_index=True)
        with st.expander("完整发布清单与版本绑定"):
            st.json({"baseline_release": release.get("id") if release else None,
                     "new_version_total": len(selected), "added": added, "removed_from_new_version": removed,
                     "reviewed_manifest": manifest})
        actor = st.text_input("发布人", key="publish_actor")
        baseline_id = release.get("id") if release else None
        displayed_receipt = {"baseline_id": baseline_id, "manifest": manifest}
        previous_receipt = st.session_state.get("publish_seen_receipt", displayed_receipt)
        st.session_state["publish_seen_receipt"] = displayed_receipt
        preview_hash = hashlib.sha256(json.dumps(displayed_receipt, sort_keys=True).encode()).hexdigest()
        confirmed = st.checkbox("已核对以上完整清单及增删影响", value=False, key="publish_confirm:" + preview_hash)
        submit = st.button("发布所选知识", disabled=not confirmed)
        if submit:
            if not confirmed or previous_receipt != displayed_receipt:
                raise ValueError("知识版本或发布清单发生变化，请重新核对后提交。")
            expected_reviews = {row["candidate_id"]: row["review_id"] for row in previous_receipt["manifest"]}
            published = knowledge.publish(selected, actor=actor, expected_release_id=previous_receipt["baseline_id"],
                                          expected_review_ids=expected_reviews)
            st.session_state["knowledge_refresh_notice"] = "发布完成，页面已切换到最新知识版本。"
            st.rerun()


_ENTITY_LABELS = {"method": "方法", "tool": "软件工具", "software": "软件工具", "software_project": "软件项目",
                  "task": "分析任务", "modality": "模态", "metric": "评价指标", "benchmark": "基准研究",
                  "dataset": "数据集", "data_representation": "数据表示", "protocol": "实验方案",
                  "assay": "实验技术", "claim": "知识单元", "source": "来源资料", "concept": "概念",
                  "data_type": "数据类型", "organism": "物种", "technology": "实验技术", "workflow": "分析流程",
                  "software_version": "软件版本", "experiment": "实验", "representation": "数据表示"}
_METHOD_KINDS = {"method", "tool", "software", "software_project"}
_PROFILE_CATEGORIES = {"方法与工具": _METHOD_KINDS, "实验技术": {"technology", "assay", "protocol"},
                       "比较评测": {"benchmark"}}


def _entity_kind(node):
    kind = str(node.get("kind", "concept")).lower()
    return _ENTITY_LABELS.get(kind, kind)


def _method_library(ledger, view, release):
    st.subheader("方法、任务与证据")
    st.write("先了解一种方法解决什么问题，再查看关联方法、适用条件和原文依据。")
    nodes = {node["id"]: node for node in view.get("nodes", [])}
    profile_kinds = set().union(*_PROFILE_CATEGORIES.values())
    methods = {key: node for key, node in nodes.items() if str(node.get("kind", "")).lower() in profile_kinds}
    stats = view.get("stats", {})
    columns = st.columns(4)
    for column, label, value in zip(columns, ["方法与工具", "任务与模态", "可用知识", "来源资料"],
        [sum(str(n.get("kind", "")).lower() in _METHOD_KINDS for n in methods.values()), sum(str(n.get("kind", "")).lower() in {"task", "modality"} for n in nodes.values()),
         stats.get("total_claims", len(release.get("units", [])) if release else 0), stats.get("total_sources", len(ledger.list_records("source")))]):
        column.metric(label, value)
    if not methods:
        _empty("方法关联索引尚未生成", "已发布知识仍可在“知识单元”中阅读。建立基于原文的实体关联后，这里将生成方法档案；不会按同名自动合并事实。")
        return
    st.caption("关联由当前知识版本派生；同任务、同模态或文中共同出现用于导航，不代表方法等价、可直接串联或独立证据数量。")
    category = st.selectbox("档案类型", [*_PROFILE_CATEGORIES, "全部档案"], key="network_profile_category")
    query = st.text_input("查找方法或工具", placeholder="输入名称或别名；实验技术、比较评测可切换档案类型", key="method_search")
    allowed_kinds = profile_kinds if category == "全部档案" else _PROFILE_CATEGORIES[category]
    options = sorted((key for key, value in methods.items() if str(value.get("kind", "")).lower() in allowed_kinds and
                      (not query.strip() or query.casefold() in " ".join([value["label"], *value.get("aliases", [])]).casefold())),
                     key=lambda key: methods[key]["label"].casefold())
    if not options:
        st.info("当前类型中没有匹配的档案；可切换“全部档案”，或在知识单元中搜索原文命题。")
        return
    if st.session_state.get("network_method") not in options:
        st.session_state.pop("network_method", None)
    chosen = st.selectbox("查看方法档案", options, format_func=lambda key: methods[key]["label"], key="network_method")
    selected = methods[chosen]
    edges = view.get("edges", [])
    direct = {e["target"] if e["source"] == chosen else e["source"] for e in edges if chosen in {e["source"], e["target"]}}
    candidate_ids = set(selected.get("candidate_ids", selected.get("claim_ids", [])))
    claims = [unit for unit in view.get("claims", []) if unit.get("candidate_id") in candidate_ids]
    with st.container(border=True):
        st.subheader(selected["label"])
        if selected.get("aliases"):
            st.caption("名称与别名 · " + "、".join(selected["aliases"]))
        scope_notes = list(dict.fromkeys(unit["navigation_scope_note"] for unit in claims if unit.get("navigation_scope_note")))
        if scope_notes:
            st.markdown("**能力边界**")
            for note in scope_notes:
                st.write("• " + note)
            st.caption("这些提示区分已报告能力、未来方向与不支持用途；关联主题本身不代表已实现能力。")
        left, right = st.columns(2)
        for column, kinds, label in [(left, {"task"}, "涉及的分析主题"), (right, {"modality"}, "关联数据模态")]:
            matches = [nodes[key]["label"] for key in sorted(direct) if key in nodes and str(nodes[key].get("kind", "")).lower() in kinds]
            column.markdown(f"**{label}**")
            column.write("、".join(matches) or "当前证据尚未建立此类关联")
        st.caption(f"档案关联 {len(claims)} 条当前可用知识；可用于理解方法，不代表本地已有可执行能力。")
        for unit in claims[:6]:
            with st.expander(unit["claim"]["proposition"]):
                _display_evidence_unit(unit, ledger=ledger)
        if len(claims) > 6:
            with st.expander(f"继续阅读其余 {len(claims) - 6} 条知识"):
                for unit in claims[6:]:
                    _display_evidence_unit(unit, ledger=ledger)
                    st.divider()
        source_ids = set(selected.get("source_ids", []))
        for unit in claims:
            source_ids.update(e.get("source_id") for e in unit.get("evidence", []) if e.get("source_id"))
        if source_ids:
            with st.expander(f"关联来源 · {len(source_ids)} 份（未经独立性去重计数）"):
                for sid in sorted(source_ids):
                    source = ledger.get_record("source", sid)
                    if source:
                        source = _source_with_current_coverage(ledger, source)
                        st.write(_source_label(source))
                        st.caption(_capture_scope_label(source))
    related = {}
    for edge in edges:
        ends = {edge["source"], edge["target"]}
        for other in ends & set(methods):
            if other == chosen:
                continue
            if chosen in ends:
                related.setdefault(other, set()).add(edge.get("label", edge.get("predicate", "文中关联")))
            for common in ends & direct:
                if common in nodes and str(nodes[common].get("kind", "")).lower() in {"task", "modality"}:
                    related.setdefault(other, set()).add("共同关联 " + nodes[common]["label"])
    if related:
        st.markdown("**继续探索关联方法**")
        related_options = sorted(related, key=lambda key: methods[key]["label"].casefold())
        if st.session_state.get("related_network_method") not in related_options:
            st.session_state.pop("related_network_method", None)
        target = st.selectbox("关联方法", related_options, key="related_network_method",
                              format_func=lambda key: methods[key]["label"] + " · " + "；".join(sorted(related[key]))[:90])
        st.button("打开关联方法档案", key="open_related_method", on_click=_select_method, args=(target,))
    else:
        st.caption("尚未建立跨方法关联；未发现关联不表示方法彼此独立。")


def _select_method(entity_id):
    st.session_state["method_search"] = ""
    st.session_state["network_profile_category"] = "全部档案"
    st.session_state["network_method"] = entity_id


def _network_graph_html(view):
    # The renderer is pure HTML/SVG; no legacy graph loader or legacy data is used.
    from .graph_renderer import build_interactive_graph_workspace_html

    nodes = {}
    claims = {unit["candidate_id"]: unit for unit in view.get("claims", [])}
    render_kinds = {"method": "Tool", "tool": "Tool", "software": "Tool", "task": "Task", "modality": "Modality",
                    "metric": "Evaluation", "dataset": "Dataset", "benchmark": "Benchmark", "source": "Source",
                    "claim": "KnowHow", "data_type": "InputArtifact", "representation": "InputArtifact"}
    for node in view.get("nodes", []):
        readable = {"对象类型": _entity_kind(node), "关联知识": len(node.get("candidate_ids", node.get("claim_ids", [])))}
        if node.get("aliases"):
            readable["名称与别名"] = node["aliases"]
        for field, label in [("conditions", "条件示例"), ("unknowns", "限制示例")]:
            values = list(dict.fromkeys(value for cid in node.get("candidate_ids", [])
                for value in claims.get(cid, {}).get("claim", {}).get(field, [])))
            if values:
                readable[label] = values[:3]
        nodes[node["id"]] = SimpleNamespace(node_id=node["id"], label=node.get("label", node["id"]),
            kind=render_kinds.get(str(node.get("kind", "concept")).lower(), "Category"), metadata={"governance_layer": "导航索引 · 关联尚待科学核对",
                "source_bound": True, "decision_eligible": False,
                "provenance_refs": node.get("candidate_ids", []), "readable": readable})
    edges = []
    for edge in view.get("edges", []):
        if edge["source"] not in nodes or edge["target"] not in nodes:
            continue
        edges.append(SimpleNamespace(source=edge["source"], target=edge["target"],
            relation=edge.get("label", edge.get("predicate", edge.get("relation", "关联"))),
            metadata={"governance_layer": "来源命题关联 · 关系解释待核对" if edge.get("kind") == "source_assertion" else "导航关联 · 不表示科学结论",
                      "provenance_refs": edge.get("candidate_ids", []), "rationale": edge.get("rationale", "")}))
    graph = SimpleNamespace(nodes=nodes, edges=edges, visible_node_ids=list(nodes), truncated=bool(view.get("stats", {}).get("truncated", view.get("truncated"))))
    return build_interactive_graph_workspace_html(graph, expansion_cap=500, embedded=True,
        focus_node_id=view.get("focus_entity_id"), presentation={
        "title": "scKG 知识网络", "subtitle": "方法 · 任务 · 模态 · 有条件的证据",
        "overview": "单击查看关联对象，双击分批展开邻居；可拖动节点、平移和缩放。导航关联用于发现资料，不代表方法等价、排名或可执行工作流。下方可按关系查看原文与适用条件。"})


def _graph_view(knowledge, *, network=None, network_view=None, ledger=None):
    import streamlit.components.v1 as components

    base = network_view or {}
    if not base.get("nodes"):
        st.info("跨方法关联索引尚未生成。当前只显示已有的来源—命题追溯关系（最多 100 条知识）；这不表示工具相互独立。")
        fallback = _json(knowledge.graph())
        if fallback.get("nodes"):
            components.html(_network_graph_html(fallback), height=720, scrolling=False)
        else:
            st.caption("当前没有可展示的已发布证据。")
        return
    st.subheader("沿着关系探索知识")
    st.caption("可切换分组、层级、圆形与径向布局，拖动、缩放、点选节点和双击展开。布局只改变摆放；层级表示关联跳数，不代表分析先后或因果。下方可查看原文依据。")
    lookup = {node["id"]: node for node in base["nodes"]}
    if st.session_state.get("network_focus", "") not in {"", *lookup}:
        st.session_state.pop("network_focus", None)
    focus_column, depth_column = st.columns([4, 1])
    focus = focus_column.selectbox("探索起点", ["", *sorted(lookup, key=lambda key: lookup[key]["label"].casefold())],
        key="network_focus", format_func=lambda key: "查看整个知识网络" if not key else lookup[key]["label"] + " · " + _entity_kind(lookup[key]))
    hops = depth_column.selectbox("关联范围", [1, 2], format_func=lambda value: f"{value} 跳", key="network_hops")
    view = network.view(entity_id=focus, hops=hops, max_nodes=500) if focus and network else base
    kinds = sorted({node.get("kind", "concept") for node in view.get("nodes", [])})
    if "network_kind_filter" not in st.session_state:
        st.session_state["network_kind_filter"] = kinds
    else:
        st.session_state["network_kind_filter"] = [kind for kind in st.session_state["network_kind_filter"] if kind in kinds]
    selected_kinds = st.multiselect("显示对象类型", kinds, key="network_kind_filter",
        format_func=lambda value: _ENTITY_LABELS.get(str(value).lower(), str(value)))
    selected_ids = {node["id"] for node in view.get("nodes", []) if node.get("kind", "concept") in selected_kinds}
    filtered = {**view, "focus_entity_id": focus or None,
                "nodes": [node for node in view.get("nodes", []) if node["id"] in selected_ids],
                "edges": [edge for edge in view.get("edges", []) if {edge["source"], edge["target"]} <= selected_ids]}
    st.caption(f"当前范围 {len(filtered['nodes'])} 个对象 · {len(filtered['edges'])} 条关联 · 连接数量不代表证据强度")
    components.html(_network_graph_html(filtered), height=720, scrolling=False)
    relations = {edge["id"]: edge for edge in filtered["edges"]}
    if relations:
        if st.session_state.get("network_relation") not in relations:
            st.session_state.pop("network_relation", None)
        relation_id = st.selectbox("查看关系的原文依据", list(relations), key="network_relation",
            format_func=lambda key: lookup.get(relations[key]["source"], {}).get("label", "对象") + " → " +
                relations[key].get("label", relations[key].get("predicate", "关联")) + " → " +
                lookup.get(relations[key]["target"], {}).get("label", "对象"))
        edge = relations[relation_id]
        st.caption("模型从来源命题提取的关联，关系解释尚待单独核对；原知识的已审用途与条件见下方。" if edge.get("kind") == "source_assertion" else
                   "导航关联：共同出现或关联到相同任务/模态，不等于已验证的兼容性、比较优势或流程衔接。")
        if edge.get("rationale"):
            st.write(edge["rationale"])
        ids = set(edge.get("candidate_ids", edge.get("claim_ids", [])))
        related_claims = [unit for unit in base.get("claims", []) if unit.get("candidate_id") in ids]
        for unit in related_claims:
            with st.expander(unit["claim"]["proposition"], expanded=len(related_claims) == 1):
                _display_evidence_unit(unit, ledger=ledger)
        if not related_claims:
            st.info("这条导航关联未提供当前可用的命题依据，不应据此作科学判断。")
    if base.get("gaps"):
        with st.expander("当前网络的覆盖缺口"):
            for gap in base["gaps"]:
                st.write(gap)
    with st.expander("索引来源与技术记录"):
        st.json({key: base.get(key) for key in ("release_id", "projection_id", "input_hash", "governance_version", "status", "stats", "provenance")})


def _apply_maintenance(knowledge, action):
    """Form callbacks run before the next page reads any evidence or graph."""
    try:
        if action == "suspend":
            knowledge.suspend(st.session_state["maintenance_kind"], st.session_state["maintenance_target"],
                actor=st.session_state["maintenance_actor"], reason=st.session_state["maintenance_reason"],
                suspended=st.session_state["maintenance_suspended"])
            st.session_state["knowledge_refresh_notice"] = "维护决定已记录，知识卡片与网络已按最新使用状态刷新。"
        else:
            knowledge.rollback(st.session_state["maintenance_release"], actor=st.session_state["rollback_actor"],
                               reason=st.session_state["rollback_reason"])
            st.session_state["knowledge_refresh_notice"] = "知识版本已恢复，页面已刷新；证据暂停决定仍然有效。"
    except Exception as exc:
        st.session_state["knowledge_maintenance_error"] = f"操作未完成：{type(exc).__name__} · {str(exc)[:500]}"


def _maintenance(ledger, knowledge, candidates):
    with st.expander("查看来源或知识变更的影响范围"):
        from .maintenance import MaintenanceService
        st.caption("列出当前发布中的知识，以及曾被送入对话上下文的证据。后者是潜在影响，不等于模型实际引用；修订后仍需复查答案并重跑原问题。")
        inspect_kind = st.selectbox("检查对象", ["source", "candidate"],
                                    format_func=lambda value: "来源" if value == "source" else "知识候选", key="impact_kind")
        inspect_records = ledger.list_records(inspect_kind)
        inspect_id = st.selectbox("选择来源或知识 ID", [row["id"] for row in inspect_records],
                                  index=None, key="impact_target")
        if inspect_id:
            impact = MaintenanceService(ledger).impact_report(inspect_kind, inspect_id)
            st.write(f"当前版本涉及 {len(impact['current_release_candidate_ids'])} 条知识；"
                     f"历史上有 {len(impact['exposed_chat_turns'])} 轮对话接收过相关证据。")
            st.json(impact)
    with st.form("suspend_evidence"):
        st.selectbox("维护对象类型", ["source", "candidate"], key="maintenance_kind")
        # Type switches inside a form only take effect on submit; show all
        # IDs explicitly and let the service verify the selected target type.
        targets = [r["id"] for r in ledger.list_records("source")] + [r["id"] for r in candidates]
        st.selectbox("来源或候选 ID", targets, index=None, key="maintenance_target")
        st.selectbox("处置", [True, False], format_func=lambda value: "暂停证据用途" if value else "恢复证据用途", key="maintenance_suspended")
        st.text_input("维护操作人", key="maintenance_actor")
        st.text_area("维护依据", key="maintenance_reason")
        st.form_submit_button("记录维护决定", disabled=not targets, on_click=_apply_maintenance, args=(knowledge, "suspend"))
    releases = ledger.list_records("release")
    if releases:
        with st.form("rollback_release"):
            st.selectbox("恢复到已发布版本", [r["id"] for r in releases], key="maintenance_release")
            st.text_input("版本恢复操作人", key="rollback_actor")
            st.text_area("版本恢复理由", key="rollback_reason")
            st.form_submit_button("恢复所选知识版本", on_click=_apply_maintenance, args=(knowledge, "rollback"))



def _source_update_checks(ledger):
    from .source_watch import SourceUpdateService

    with st.expander("检查网址来源是否变化"):
        st.caption("只进行一次受限抓取和原件哈希比较。发现变化后保存为待核验候选，不覆盖原件，也不自动改变已发布知识。固定 GitHub 提交不代表上游最新版本。")
        watched = [source for source in ledger.list_records("source") if source.get("acquisition_method") == "url"]
        if not watched:
            st.info("目前没有通过网址登记、可进行此类检查的来源。")
        else:
            lookup = {source["id"]: source for source in watched}
            with st.form("check_source_update"):
                source_id = st.selectbox("网址来源", list(lookup),
                                         format_func=lambda value: _source_label(lookup[value]))
                allow_network = st.checkbox("允许本次从原网址读取至多 25 MiB", value=False)
                submitted = st.form_submit_button("检查一次")
            if submitted:
                try:
                    receipt = SourceUpdateService(ledger).check(source_id, allow_network=allow_network)
                    if receipt["status"] == "changed":
                        st.warning("检测到原件字节变化；仅生成候选，需重新解析、核验和人工审核。")
                    elif receipt["status"] == "unchanged":
                        st.success("本次取得的字节与归档原件一致；这不等于科学内容仍有效。")
                    else:
                        st.warning(f"检查未完成：{receipt['error_code']}")
                    st.json(receipt)
                except Exception as exc:
                    _error(exc)
        receipts = ledger.list_records("source_update_check")
        if receipts:
            st.dataframe([{"来源 ID": row["source_id"], "结果": row["status"],
                           "候选 ID": row["candidate_id"], "检查时间": row["checked_at"]}
                          for row in receipts[-20:]], hide_index=True, width="stretch")
        staged_ids = {row["source_update_candidate_id"] for row in ledger.list_records("source_update_stage")}
        candidates = [row for row in ledger.list_records("source_update_candidate")
                      if row["id"] not in staged_ids]
        if candidates:
            st.markdown("**将变化原件送入入库审核**")
            st.caption("此操作会登记一份新的临时来源；旧原件和正式知识保持原样。新来源仍需解析、抽取、核验与人工审核。")
            with st.form("stage_source_update"):
                candidate_id = st.selectbox("待核验更新候选", [row["id"] for row in candidates])
                actor = st.text_input("登记人", key="source_update_actor")
                reason = st.text_area("登记理由", key="source_update_reason")
                stage_submitted = st.form_submit_button("登记为临时新来源")
            if stage_submitted:
                try:
                    result = SourceUpdateService(ledger).stage_candidate(candidate_id, actor=actor, reason=reason)
                    st.success(f"已登记临时来源 {result['source']['id']}；尚未解析、审核或发布。")
                except Exception as exc:
                    _error(exc)


def _ingestion(ledger, sources, models, queue):
    with st.expander("入库闭环 · 六个环节与当前能力"):
        st.markdown("**收集 → 清洗与质量检查 → 抽取 → 结构化关联 → 冲突与冗余 → 测试、发布与反馈**")
        st.dataframe([
            {"环节": "1 收集", "已接通": "原件归档、来源版本、单次受限更新检查", "仍需完善": "计划式定期检查与勘误/撤稿状态判断"},
            {"环节": "2 清洗与质量检查", "已接通": "解析状态、材料范围、原文定位与缺口", "仍需完善": "指标语义、单位、方向、统计层级的清洗复核"},
            {"环节": "3 抽取", "已接通": "模型配置、命题、适用条件、未知项、证据核验", "仍需完善": "图表像素与补充材料的多模态核验"},
            {"环节": "4 结构化关联", "已接通": "带证据的主语—关系—宾语；发布版本可生成方法/任务/模态导航索引", "仍需完善": "导航关联的科学审核与更细粒度本体映射"},
            {"环节": "5 冲突与冗余", "已接通": "修订保留与人工审核；原始身份独立保存", "仍需完善": "语义去重、条件化冲突判断、独立证据组归并"},
            {"环节": "6 测试、发布与反馈", "已接通": "审核发布、暂停、回滚与评测划分", "仍需完善": "科学质量评测与错误反馈的自动回归"},
        ], hide_index=True, width="stretch")
        st.caption("评价指标清洗需保留定义、方向、单位、数据集、重复层级与不确定性；低分或相反结果不能被当作噪声删除。")
        st.caption("自动维护尚未配置定时调度：新抓取的版本仍须经过相同核验与发布流程，不会自动覆盖正式知识。")
    with st.container(key="ingest_steps"):
        stage = st.radio("入库阶段", INGEST_STAGES, key="ingest_stage", horizontal=True, label_visibility="collapsed", width="stretch")
    if stage == "来源与范围":
        inputs, scope = st.columns(2, gap="medium")
        with scope:
            with st.container(border=True, key="wb_card_source_scope"):
                _source_scope()
        with inputs:
            with st.container(border=True, key="wb_card_source_input"):
                _source_inputs(sources)
        with st.container(border=True, key="wb_card_source_queue"):
            st.subheader("来源队列")
            _source_library(ledger, sources)
            _source_update_checks(ledger)
            st.button("配置抽取方案", type="primary", on_click=_navigate, args=("入库工作台", "配置与抽取"))
    elif stage == "配置与抽取":
        title, link = st.columns([3, 1], vertical_alignment="center")
        title.subheader("模型与抽取方案")
        link.button("管理模型连接", on_click=_navigate, args=("设置",))
        with st.container(border=True, key="wb_card_extraction"):
            _extraction(ledger, models)
        with st.container(border=True, key="wb_card_tasks"):
            st.subheader("处理任务")
            _tasks(ledger, models, queue)
    elif stage == "质量与分流":
        knowledge = _knowledge(ledger)
        candidates = knowledge.list_candidates()
        stats = st.columns(4)
        values = [len(candidates), sum(bool(c.get("assessment")) for c in candidates),
                  sum(not c.get("assessment") for c in candidates), sum(bool(c.get("review")) for c in candidates)]
        for column, label, value in zip(stats, ["全部候选", "已做证据判断", "待核验", "已审核"], values):
            column.metric(label, value)
        with st.container(border=True, key="wb_card_review"):
            st.subheader("知识与原文核对")
            _review_candidates(knowledge, candidates)
    elif stage == "合并与冲突":
        with st.container(border=True, key="wb_card_conflict"):
            st.subheader("跨来源关联与冲突")
            _empty("语义合并尚未接通", "现阶段保留各来源与候选的独立身份，不会仅凭同名、相似度或同一工具自动合并。")
            st.caption("后续在这里对照两侧原文、版本和条件，保留同义、补充、冲突与未决关系。")
            st.button("返回质量核对", on_click=_navigate, args=("入库工作台", "质量与分流"))
    else:
        knowledge = _knowledge(ledger)
        with st.container(border=True, key="wb_card_publish"):
            st.subheader("本次变更与发布")
            _publish_candidates(knowledge, knowledge.list_candidates(), knowledge.current_release())


def _source_scope():
    st.subheader("这批资料补充什么知识？")
    current = st.session_state.get("source_scope", {})
    with st.form("source_scope_form", border=False):
        identity = st.text_input("来源身份／作品线索（待核验）", value=current.get("identity_hint", ""), placeholder="DOI / 官方项目 / 教程作者")
        materials = ["待判断", "方法原始论文", "官方文档与教程", "比较研究 / benchmark", "其他研究资料"]
        material = st.selectbox("材料类型", materials, index=materials.index(current.get("material_type", "待判断")))
        purpose = st.text_area("目标用途与接入理由", value=current.get("intended_use", ""), placeholder="例如：补充某个版本的输入要求、适用条件或比较证据")
        save = st.form_submit_button("保存来源说明", width="stretch")
    if save:
        st.session_state["source_scope"] = {"identity_hint": identity, "material_type": material, "intended_use": purpose}
        st.success("说明已保存，将附在随后接收的本地文件或网页来源上。")
    st.caption("这些说明保留为待核验线索。材料格式与来源登记本身不代表证据质量。")


def _source_inputs(sources):
    upload, remote, github = st.tabs(["本地文件", "网页／文献链接", "GitHub 文件"])
    with upload:
        with st.form("upload_sources", clear_on_submit=True, border=False):
            files = st.file_uploader("上传资料", type=["pdf", "docx", "md", "markdown", "txt", "html", "htm", "xml"], accept_multiple_files=True, max_upload_size=25)
            parse_now = st.checkbox("接收后进行本地文本解析", value=True)
            submitted = st.form_submit_button("接收文件", type="primary")
        st.caption("每个文件最大 25 MiB；PDF 暂不提供 OCR，扫描件与未覆盖内容将记录为解析缺口。")
        if submitted:
            if not files:
                st.error("请选择至少一个文件。")
            for file in files or []:
                try:
                    record = sources.register_bytes(file.name, file.getvalue(), metadata=st.session_state.get("source_scope", {}), request_id="ui-upload-" + uuid.uuid4().hex)
                    st.success(f"已保存原件：{record['filename']} · {record['id']}")
                    if parse_now:
                        _parse_result(sources.parse(record["id"], max_pages=25, max_chars=200000))
                except Exception as exc:
                    _error(exc)
    with remote:
        with st.form("remote_source", border=False):
            url = st.text_input("公开来源 URL")
            network = st.checkbox("允许本次联网获取此来源", value=False)
            submit = st.form_submit_button("获取并登记链接")
        if submit:
            try:
                record = sources.register_url(url, allow_network=network, metadata=st.session_state.get("source_scope", {}), request_id="ui-url-" + uuid.uuid4().hex)
                st.success(f"已保存原件：{record['filename']} · {record['id']}；可到来源列表解析。")
            except Exception as exc:
                _error(exc)
    with github:
        with st.form("github_source", border=False):
            repo = st.text_input("仓库 owner/repository", placeholder="organization/repository")
            commit = st.text_input("完整 40 位 commit SHA")
            path = st.text_input("仓库内文件路径", placeholder="docs/tutorial.md")
            network = st.checkbox("允许本次联网获取固定 GitHub 文件", value=False)
            submit = st.form_submit_button("获取并登记 GitHub 文件")
        if submit:
            try:
                record = sources.register_github(repo, commit, path, allow_network=network, request_id="ui-gh-" + uuid.uuid4().hex)
                st.success(f"已保存固定版本原件：{record['filename']} · {record['id']}")
            except Exception as exc:
                _error(exc)


def _parse_result(ir):
    status = ir["status"]
    if status == "complete":
        st.success("本次文本解析完成；科学知识尚未抽取或批准。")
    elif status == "partial":
        st.warning("文本解析部分完成，请检查覆盖范围与缺口。")
    else:
        st.error("未取得完整可用正文，请检查解析缺口。")
    st.json({"id": ir["id"], "status": status, "coverage": ir["coverage"], "gaps": ir["gaps"]})


def _source_library(ledger, sources):
    records = [_source_with_current_coverage(ledger, source) for source in ledger.list_records("source")]
    st.caption(f"{len(records)} 份来源 · 原件与获取记录独立保存")
    if not records:
        _empty("还没有接入资料", "添加一份文件、网页或固定版本的 GitHub 文档，即可开始。")
        return
    st.dataframe([{"来源": _source_label(r), "材料范围": _capture_scope_label(r),
                   "大小": f"{r['size_bytes'] / 1024:.1f} KiB", "身份": "待核验", "状态": "已登记原件"}
                  for r in records], hide_index=True)
    lookup = {r["id"]: r for r in records}
    source_ids = list(lookup)
    active = st.session_state.get("active_ingest_source_id")
    choice_key = "source_library_selected_source"
    if st.session_state.get(choice_key) not in source_ids:
        st.session_state[choice_key] = active if active in source_ids else source_ids[0]
    # Keep widget identity stable across successive choices. A changing default
    # index recreated the unkeyed widget and could discard the user's next ID.
    # The separate active ID survives widget cleanup when navigating pages.
    selected = st.selectbox("查看来源", source_ids, key=choice_key,
                            format_func=lambda key: _source_label(lookup[key]) + " · " + key[-8:])
    st.session_state["active_ingest_source_id"] = selected
    material_gaps = lookup[selected].get("metadata", {}).get("material_gaps", [])
    if material_gaps:
        st.caption("材料缺口 · " + "；".join(material_gaps))
    with st.expander("来源身份与固定原件"):
        st.json(lookup[selected])
    limits = st.columns(2)
    pages = limits[0].number_input("本次 PDF 页数上限", min_value=1, max_value=200, value=25)
    chars = limits[1].number_input("本次正文字符上限", min_value=1000, max_value=1000000, value=200000, step=1000)
    if st.button("解析所选原件"):
        try:
            _parse_result(sources.parse(selected, max_pages=pages, max_chars=chars))
        except Exception as exc:
            _error(exc)
    versions = [r for r in ledger.list_records("document_ir") if r["source_id"] == selected]
    if versions:
        ir_lookup = {r["id"]: r for r in versions}
        selected_ir = st.selectbox("解析版本", list(ir_lookup))
        ir = ir_lookup[selected_ir]
        st.json({"status": ir["status"], "coverage": ir["coverage"], "gaps": ir["gaps"]})
        if ir.get("blocks"):
            block = st.selectbox("原文块", ir["blocks"], format_func=lambda row: row["id"])
            st.code(block["exact_text"], language=None)
            st.json(block["locator"])


def _extraction(ledger, models):
    worker = _worker(ledger, models)
    sources = ledger.list_records("source")
    extracting = models.list_profiles("extraction")
    assessing = models.list_profiles("assessment")
    if not sources or not extracting or not assessing:
        semantic, integrity = st.columns(2, gap="medium")
        with semantic:
            st.subheader("LLM 语义工作")
            st.caption("知识抽取模型")
            st.write("已配置" if extracting else "尚未配置")
            st.caption("证据核验模型")
            st.write("已配置" if assessing else "尚未配置")
            st.button("配置抽取与核验模型", on_click=_navigate, args=("设置",))
        with integrity:
            st.subheader("原文与质量检查")
            st.write("保留命题的条件、否定与未知项。")
            st.caption("程序检查原文位置和固定版本；模型判断语义支持。候选经审核后才能发布。")
            st.caption(f"来源资料：{len(sources)} 份已登记")
        st.info("登记来源，并在设置中分别创建知识抽取和语义核验 profile，才可提交任务。")
        return
    if worker is None:
        st.info("真实抽取 worker 尚未接入，当前不提交占位任务。")
        return
    with st.form("submit_ingestion", border=False):
        semantic, limits = st.columns(2, gap="medium")
        with semantic:
            st.subheader("来源与语义模型")
            active = st.session_state.get("active_ingest_source_id")
            source_ids = [s["id"] for s in sources]
            source = st.selectbox("抽取来源", sources, index=source_ids.index(active) if active in source_ids else 0,
                                  format_func=lambda x: x["filename"] + " · " + x["id"][-8:])
            extract = st.selectbox("知识抽取 profile", extracting, format_func=_profile_label)
            assess = st.selectbox("语义核验 profile", assessing, format_func=_profile_label)
        with limits:
            st.subheader("任务边界与预算")
            a, b = st.columns(2)
            calls = a.number_input("总调用次数上限", min_value=1, max_value=100, value=10)
            cost = b.number_input("总费用上限 USD", min_value=.01, max_value=1000., value=2., step=.1)
            tokens = st.number_input("总 token 上限", min_value=1000, max_value=2000000, value=256000, step=1000)
            with st.expander("单次调用设置"):
                input_limit = st.number_input("单次输入 token 上限", min_value=1000, max_value=500000, value=64000, step=1000)
                output_limit = st.number_input("单次输出 token 上限", min_value=100, max_value=32000, value=4000, step=100)
                timeout = st.number_input("单次超时秒数", min_value=1, max_value=600, value=60)
        st.caption("提交只进入本地队列；执行时确认模型外发并检查对应凭据。两个 profile 均须配置费率。")
        st.caption("输入预检使用 UTF-8 字节保守估计，不是实测 token；当前 worker 最多处理 50 页／12000 字符，超出范围将报告 partial。")
        submit = st.form_submit_button("提交真实抽取任务", type="primary")
    if submit:
        task = worker.submit_ingestion(source["id"], extract["id"], assess["id"],
            budget={"max_calls": calls, "max_tokens": tokens, "max_cost": cost},
            request_budget={"max_input_tokens": input_limit, "max_output_tokens": output_limit, "timeout_seconds": timeout},
            idempotency_key="ui-ingest-" + uuid.uuid4().hex)
        st.success(f"已排队：{task['task_id']}；尚未执行模型调用。")


def _tasks(ledger, models, queue):
    records = queue.list()
    if st.button("刷新任务"):
        st.rerun()
    if not records:
        st.info("暂无知识处理任务。")
        return
    st.dataframe([{k: t.get(k) for k in ("task_id", "kind", "status", "attempt", "budget_status")} for t in records], hide_index=True)
    selected = st.selectbox("查看任务", [t["task_id"] for t in records])
    task = queue.get(selected)
    with st.expander("真实状态、预算与用量", expanded=True):
        st.json(task)
    with st.expander("事件与失败记录"):
        st.json(queue.events(selected))
    a, b = st.columns(2)
    if a.button("请求取消所选任务", disabled=task["status"] not in {"queued", "running"}):
        st.json(queue.request_cancel(selected))
    confirm = st.checkbox("已核对未知结果，确认重试不会重复已完成的外部操作", value=False)
    if b.button("重试所选任务", disabled=task["status"] not in {"failed", "partial", "result_unknown"}):
        st.json(queue.retry(selected, confirm_no_duplicate=confirm))
    worker = _worker(ledger, models)
    if worker is not None:
        st.divider()
        authorized = st.checkbox("允许本次 worker 将任务固定的来源正文发送给所选模型", value=False)
        st.caption("worker 执行队列中下一项可领取任务；Vault 连接需解锁口令，本地 .env 连接直接读取指定变量。")
        credential_ready = bool(st.session_state.get("vault_passphrase")) or not worker.requires_passphrase()
        if st.button("执行下一项已排队任务", disabled=not authorized or not credential_ready):
            with st.spinner("执行真实任务，等待服务返回状态…"):
                result = worker.run_once(passphrase=st.session_state.get("vault_passphrase", ""), outbound_authorized=authorized)
            if result is None:
                st.info("没有可领取的任务。")
            elif result["status"] == "succeeded":
                st.success("任务处理完成；候选仍需知识审核。")
            else:
                st.warning(f"任务返回状态：{result['status']}。请查看结果与失败记录。")
            if result:
                st.json(result)


def _evaluation(ledger):
    from eval.workbench_snapshot import freeze_workbench_snapshot
    from .coverage import build_coverage_report, list_coverage_reviews

    coverage_tab, value_tab, external_tab, split_tab = st.tabs(["任务覆盖", "科学效果", "对外取证", "来源与留出"])
    with coverage_tab:
        snapshot = freeze_workbench_snapshot(ledger.workspace, purpose="recommendation")
        coverage = build_coverage_report(snapshot, list_coverage_reviews(ledger, snapshot))
        st.caption("首版范围：单细胞 RNA、RNA–蛋白、RNA–ATAC、配对/非配对整合、基础空间分析。30 个任务格目前是待两位领域审阅者确认的草案。")
        a, b, c = st.columns(3)
        a.metric("待审任务格", sum(cell["status"] == "scope_pending" for cell in coverage["cells"]))
        b.metric("可用于推荐的正式知识", coverage["eligible_unit_count"])
        c.metric("已判定覆盖率", "未建立" if coverage["overall_status"] == "not_established" else coverage["overall_status"])
        st.dataframe([{"任务格": cell["title"], "状态": cell["status"],
                       "发现线索（知识）": cell["discovery_candidate_count"],
                       "发现线索（来源）": cell["discovery_source_count"],
                       "审阅人数": cell["review_count"]} for cell in coverage["cells"]],
                     hide_index=True, width="stretch")
        st.caption("线索是字面检索结果，不是科学支持。每类任务达到 90% 的声明，只有范围与证据分别经两人核对后才能计算。")
        with st.expander("覆盖版本和待处理缺口"):
            st.json({key: coverage[key] for key in ("manifest_hash", "snapshot_hash", "release_id",
                                                       "governance_version", "domains", "overall_status")})
        _coverage_review_form(ledger, snapshot, coverage)
    with value_tab:
        from eval.scientific_value_registry import build_development_study, validate_study

        study_path = Path(__file__).resolve().parents[1] / "eval/fixtures/genpilot_sckg_eval_v1.json"
        case_specs = json.loads(study_path.read_text(encoding="utf-8"))["case_specs"]
        readiness = validate_study(build_development_study(snapshot, case_specs))
        st.warning("尚无有库/无库/普通检索的可比科学结果，不能据此声称知识库或 Agent 带来增益。")
        st.caption("比较需固定模型、问题、工具权限、预算、来源和数据划分；两位领域审阅者盲评关键科学决策及错误。")
        profiles = [p for p in ledger.list_records("model_profile") if p.get("purpose") in {"chat", "evaluation"}]
        st.write(f"开发题 {readiness['development_case_count']} 道、依赖组 {readiness['independent_dependency_groups']} 组；"
                 f"可选对话/评测模型配置 {len(profiles)} 个；正式对照成绩：未产生。")
        st.caption(f"测评就绪状态：{readiness['status']} · 待处理条件 {len(readiness['blockers'])} 项。")
        with st.expander("查看测评阻塞条件"):
            for blocker in readiness["blockers"]:
                st.write("• " + blocker)
        st.caption("先在开发题上做小规模 smoke，再根据成对差异计算确认集样本量。外部 Agent 和 Genpilot 的结果分别登记，不能从本地工程测试推断胜出。")
    with external_tab:
        _external_access(ledger)
    with split_tab:
        _evaluation_split(ledger)


def _external_access(ledger):
    from .external_evidence import ExternalEvidenceService, SourceExportRights

    external = ExternalEvidenceService(ledger.workspace)
    version = external.current_version()
    st.caption("对外接口只读取当前正式版本，并逐次检查暂停、审核用途与来源再分发资格。云端 Agent 获取的文本必须另经来源许可审核。")
    a, b = st.columns(2)
    a.metric("正式版本知识", version["manifest_unit_count"])
    b.metric("来源许可审核版本", version["source_export_rights_version"])
    st.caption(f"Release · {version['release_id'] or '尚未发布'} · 治理版本 {version['governance_version']}")
    if st.button("预览当前可导出的知识包", key="preview_external_evidence"):
        package = external.export_knowledge()
        st.write(f"正式资格 {package['eligible_unit_count']} 条；当前许可可导出 {len(package['units'])} 条。")
        if package["gaps"]:
            st.warning("；".join(package["gaps"][:4]))
        st.json({key: package[key] for key in ("schema_version", "release_id", "governance_version",
                                                "source_export_rights_version", "snapshot_hash",
                                                "offline_export_requires_refresh")})
        if package["units"]:
            st.download_button("下载版本固定的知识包 JSON", data=json.dumps(package, ensure_ascii=False, indent=2),
                               file_name=f"sckg-evidence-{package['snapshot_hash'][:12]}.json", mime="application/json")
    with st.expander("逐来源审核对外使用许可"):
        st.caption("科学内容已审核并不代表可向其他服务发送原文。请先核对具体来源版本与许可，再作命题和摘录的分项决定；撤回会立即影响新查询。")
        sources = ledger.list_records("source")
        if not sources:
            st.info("尚无来源。")
            return
        lookup = {source["id"]: source for source in sources}
        with st.form("source_export_rights"):
            source_id = st.selectbox("来源", list(lookup),
                                     format_func=lambda value: _source_label(lookup[value]), key="export_rights_source")
            source = lookup[source_id]
            st.caption(f"来源修订 {source['source_revision_id']} · 原件 SHA256 {source['blob_sha256']}")
            choice = st.selectbox("对外用途决定", ["deny", "claims", "claims_and_quotes"],
                                  format_func=lambda value: {"deny": "不允许对外提供", "claims": "仅允许改写命题",
                                                             "claims_and_quotes": "允许命题和定位摘录"}[value])
            license_ref = st.text_input("许可依据或权限记录")
            reviewer = st.text_input("审核人")
            reason = st.text_area("判断依据和适用范围")
            confirmed = st.checkbox("我已核对该来源版本和许可范围")
            submitted = st.form_submit_button("保存许可审核")
        if submitted:
            if not confirmed:
                st.error("请先核对该来源版本与许可范围。")
                return
            result = SourceExportRights(ledger).review(
                source_id, reviewer=reviewer, license_ref=license_ref, reason=reason,
                claims_allowed=choice != "deny", quotes_allowed=choice == "claims_and_quotes",
                expected_source_revision_id=source["source_revision_id"],
                expected_blob_sha256=source["blob_sha256"])
            st.success(f"许可决定已登记：{result['id']}。对外服务会重新检查当前版本。")


def _coverage_review_form(ledger, snapshot, coverage):
    from .coverage import build_coverage_manifest, submit_coverage_review

    with st.expander("领域审阅：确定任务范围和证据"):
        st.caption("两位领域审阅者分别提交。第二人提交前只显示已有审阅人数，不展示首位的决定或理由。身份由本地填写，尚无独立认证。")
        if not snapshot["release_id"]:
            st.info("尚无正式发布版本，不能判断任务覆盖。")
            return
        manifest = build_coverage_manifest()
        cells = {item["id"]: item for item in manifest["cells"]}
        selected_id = st.selectbox("任务格", list(cells), format_func=lambda value: cells[value]["title"],
                                   key="coverage_selected_cell")
        cell = cells[selected_id]
        status = next(row for row in coverage["cells"] if row["id"] == selected_id)
        st.write(f"当前已提交 {status['review_count']}/2 份审阅；该格状态：{status['status']}。")
        st.caption(cell["question"])
        unit_by_id = {unit["candidate_id"]: unit for unit in snapshot["units"]}
        clues = [unit_by_id[cid] for cid in status["discovery_candidate_ids"] if cid in unit_by_id]
        if clues:
            st.dataframe([{"知识 ID": unit["candidate_id"], "命题线索": unit["claim"]["proposition"]}
                          for unit in clues], hide_index=True, width="stretch")
        else:
            st.caption("字面检索尚无线索；这不证明该任务没有可用证据。")
        options = list(unit_by_id)
        labels = {cid: unit_by_id[cid]["claim"]["proposition"][:70] for cid in options}
        with st.form("coverage_domain_review"):
            reviewer = st.text_input("领域审阅者 ID")
            scope = st.selectbox("首版支持范围", ["unsure", "in", "out"],
                                 format_func=lambda value: {"unsure": "尚不确定", "in": "纳入首版", "out": "暂不纳入"}[value])
            support = st.selectbox("若纳入，证据判断", ["unknown", "supported", "unsupported"],
                                   format_func=lambda value: {"unknown": "待补证", "supported": "已有足够证据", "unsupported": "当前证据不足"}[value])
            evidence_ids = st.multiselect("支持该任务的正式知识 ID", options,
                                          format_func=lambda value: f"{value[-12:]} · {labels[value]}")
            critical = {}
            for condition in cell["critical_conditions"]:
                critical[condition] = st.multiselect(f"关键前提 · {condition}", options,
                                                     format_func=lambda value: f"{value[-12:]} · {labels[value]}")
            independence = st.checkbox("比较证据已核对独立来源与共同实验复述", value=False)
            independence_basis = st.text_area("比较证据独立性依据（如适用）")
            reason = st.text_area("审阅理由与尚存缺口")
            submitted = st.form_submit_button("提交本人的审阅")
        if submitted:
            in_scope = scope == "in"
            supported = in_scope and support == "supported"
            review = {"cell_id": selected_id, "reviewer_id": reviewer, "reviewer_role": "domain_reviewer",
                      "manifest_hash": manifest["manifest_hash"], "release_id": snapshot["release_id"],
                      "governance_version": snapshot["governance_version"], "snapshot_hash": snapshot["snapshot_hash"],
                      "scope": scope, "support": support if in_scope else None,
                      "evidence_ids": evidence_ids if supported else [],
                      "critical_evidence": critical if supported else {},
                      "independent_comparison_verified": independence if supported and cell["task"] == "comparison" else None,
                      "independence_basis": independence_basis if supported and cell["task"] == "comparison" else None,
                      "reason": reason}
            record = submit_coverage_review(ledger, snapshot, review, manifest)
            st.success(f"审阅已登记：{record['id']}。页面将按当前知识版本重新计算覆盖。")


def _evaluation_split(ledger):
    catalog = Catalog(ledger)
    st.caption("16 个来源包是待核验的发现清单；没有自动下载，没有生成金标或虚构评测分数。")
    st.dataframe(catalog.seeds(), hide_index=True, column_config={"discovery_url": st.column_config.LinkColumn("发现入口")})
    split_id = ledger.get_state("evaluation_split")
    if split_id:
        st.success("评测划分已冻结。")
        st.json(ledger.get_record("evaluation_split", split_id))
        st.caption("冻结划分不等于已有 Gold；科学标签需要独立裁定。")
        return
    records = ledger.list_records("source")
    if not records:
        st.info("登记并核对实际来源后，才能按研究工作族冻结开发／校准／留出划分。")
        return
    with st.form("freeze_split"):
        rows = [{"include": False, "source_id": r["id"], "filename": r["filename"], "work_family": "",
                 "partition": "development", "prior_development_use": False} for r in records]
        edited = st.data_editor(rows, hide_index=True, disabled=["source_id", "filename"],
            column_config={"partition": st.column_config.SelectboxColumn("partition", options=["development", "calibration", "holdout"])})
        reviewer = st.text_input("划分核对人")
        checked = st.checkbox("已逐项核对作品版本、工作族和既往开发使用情况", value=False)
        submit = st.form_submit_button("冻结所选来源划分")
    if submit:
        if not checked:
            st.error("请先核对工作族及既往开发使用情况。")
            return
        assignments = [{k: r[k] for k in ("source_id", "work_family", "partition", "prior_development_use")} for r in edited if r["include"]]
        st.json(catalog.freeze_split(assignments, reviewer=reviewer))
        st.success("划分已冻结；未创建 Gold 标签。")


def _datasets(workspace):
    from .datasets import DatasetService, MAX_UPLOAD_BYTES

    service = DatasetService(workspace)
    st.caption("分析数据独立于文献知识库；登记和画像均在本地完成，不会将原始矩阵送往模型。画像只读取有限范围，不判断全数据是否为原始计数。")
    local_tab, upload_tab = st.tabs(["登记本地 .h5ad", "上传小型 .h5ad"])
    with local_tab:
        with st.form("dataset_local_registration"):
            local_path = st.text_input("本地 .h5ad 绝对路径")
            local_label = st.text_input("资产名称（可选）")
            project_id = st.text_input("项目 ID（可选）")
            submitted = st.form_submit_button("只读登记本地数据")
        if submitted:
            try:
                asset = service.register_local(local_path, label=local_label or None, project_id=project_id or None)
                st.success(f"已登记：{asset['asset_id']}。本地文件没有被复制或改写。")
            except Exception as exc:
                _error(exc)
    with upload_tab:
        uploaded = st.file_uploader("上传 .h5ad（上限 25 MiB）", type=["h5ad"], key="dataset_upload")
        upload_label = st.text_input("上传资产名称（可选）", key="dataset_upload_label")
        if uploaded is not None:
            st.caption(f"待登记文件：{uploaded.name} · {uploaded.size} 字节")
        if st.button("归档并登记上传数据", disabled=uploaded is None, key="register_dataset_upload"):
            if uploaded.size > MAX_UPLOAD_BYTES:
                st.error("文件超过 25 MiB；请使用本地路径登记，避免整文件上传。")
            else:
                try:
                    asset = service.register_upload(uploaded.name, uploaded.getvalue(), label=upload_label or None)
                    st.success(f"已归档为独立资产：{asset['asset_id']}。未进行模型调用或科学分析。")
                except Exception as exc:
                    _error(exc)
    assets = service.list_assets()
    st.subheader("已登记数据")
    if not assets:
        st.info("尚无分析数据。研究台仍可直接对话。")
        return
    st.dataframe([{"资产 ID": asset["asset_id"], "名称": asset["label"], "存储": asset["storage"],
                   "大小（字节）": asset["stat_signature"]["size"],
                   "完整哈希": "已计算" if asset["content_sha256"] else "未计算",
                   "登记时间": asset["registered_at"]} for asset in assets], hide_index=True, width="stretch")
    lookup = {asset["asset_id"]: asset for asset in assets}
    chosen = st.selectbox("查看或画像资产", list(lookup),
                          format_func=lambda value: f"{lookup[value]['label']} · {value[-12:]}", key="dataset_selected")
    asset = lookup[chosen]
    st.caption(f"文件位置：{asset['path']} · 版本指纹：{asset['bounded_fingerprint']['fingerprint_sha256'][:16]}")
    if st.button("建立有界只读画像", key="profile_dataset"):
        try:
            record = service.profile(chosen)
            st.success(f"画像已保存：{record['profile_id']}。采样范围和未知项见下方。")
        except Exception as exc:
            _error(exc)
    profiles = service.list_profiles(chosen)
    if profiles:
        latest = profiles[-1]
        profile = latest["profile"]
        a, b = st.columns(2)
        a.metric("细胞数", profile["dimensions"]["n_obs"])
        b.metric("特征数", profile["dimensions"]["n_vars"])
        st.dataframe(profile["measurements"]["matrices"], hide_index=True, width="stretch")
        with st.expander("采样范围、未知条件与版本"):
            st.json({"profile_id": latest["profile_id"], "asset_id": chosen,
                     "sampling": profile["sampling"], "unknowns": profile["unknowns"],
                     "axis_alignment": profile["measurements"]["axis_alignment"],
                     "metadata_keys": profile["measurements"]["metadata"]})
    else:
        st.info("尚无画像；登记时没有读取完整矩阵。")


def _run_results(workspace):
    from .analysis import AnalysisService
    from .datasets import DatasetService
    from .execution_readiness import ScrubletReadinessService

    analysis = AnalysisService(workspace)
    runs = analysis.list_runs()
    if not runs:
        _empty("暂无分析运行结果", "在研究台选择数据并启用本地分析工具，可提交受控 Scrublet 预览。")
    else:
        st.dataframe([{"任务": r["task_id"], "状态": r["status"],
            "资产": r["input_snapshot"]["asset_id"], "尝试次数": r["attempt"]} for r in runs], hide_index=True)
        task_id = st.selectbox("查看分析任务", [r["task_id"] for r in runs], key="analysis_result_task")
        task = analysis.queue.get(task_id)
        if st.button("刷新分析状态", key="analysis_refresh"):
            st.rerun()
        if task["status"] in {"queued", "running"} and st.button("取消分析任务", key="analysis_cancel"):
            analysis.queue.request_cancel(task_id)
            st.rerun()
        if task["status"] == "queued" and st.button("执行已授权的分析任务", key="analysis_execute"):
            with st.spinner("执行本地分析并验收产物…"):
                analysis.run_once(task_id=task_id)
            st.rerun()
        result = analysis.get_result(task_id)
        if result:
            origin = {"unknown": "尚不清楚", "caller_supplied": "用户提供",
                      "synthetic": "合成测试数据", "published_derived": "公开来源的衍生数据"}.get(
                          result.get("dataset_origin", "unknown"), "尚不清楚")
            st.caption("数据来源声明 · " + origin + " · 尚未独立核验")
        if result and task["status"] == "succeeded" and result.get("validation", {}).get("passed"):
            st.success("分析预览与产物校验通过。此结果用于工程预览，不是科学效力证明。")
            paths = (result.get("execution_run") or {}).get("artifact_paths", {})
            for name, text in paths.items():
                path = Path(text)
                # get_result revalidates the saved run's bound paths and hashes.
                if path.is_file() and path.stat().st_size <= 25 * 1024 * 1024:
                    st.download_button("下载 " + name, path.read_bytes(), file_name=path.name,
                        key="analysis_download_" + task_id + "_" + name)
        elif result:
            st.warning("当前分析或产物验收未通过，完整错误保留在运行记录中。")
        with st.expander("分析、资源与验收记录", expanded=bool(result and not result.get("validation", {}).get("passed"))):
            st.json({"task": task, "result": result, "events": analysis.queue.events(task_id)})
    st.button("查看知识处理任务", on_click=_navigate, args=("入库工作台", "配置与抽取"))
    st.subheader("Scrublet 独立只读预检")
    st.caption("只读预检现有合同、环境和已登记数据，不创建审批、不调用执行器、不修改矩阵。预检通过也不等于结果科学有效。")
    assets = DatasetService(workspace).list_assets()
    options = [""] + [asset["asset_id"] for asset in assets]
    labels = {asset["asset_id"]: asset["label"] for asset in assets}
    selected = st.selectbox("预检数据资产", options,
                            format_func=lambda value: "暂不选择数据" if not value else f"{labels[value]} · {value[-12:]}",
                            key="run_preflight_asset")
    if st.button("检查执行前提", key="run_scrublet_preflight"):
        try:
            report = ScrubletReadinessService(workspace).preflight(selected or None)
            st.session_state["scrublet_readiness_report"] = report
        except Exception as exc:
            st.session_state.pop("scrublet_readiness_report", None)
            _error(exc)
    report = st.session_state.get("scrublet_readiness_report")
    if report and report.get("asset_id") == (selected or None):
        if report["ready"]:
            st.success("前提检查通过；仍需经正式执行路径和结果验证。")
        else:
            st.warning("当前不能执行 Scrublet。下列阻塞项需要逐项解决并重新预检。")
        st.dataframe([{"检查": row["check_id"], "状态": row["status"],
                       "说明": row["detail"]} for row in report["checks"]],
                     hide_index=True, width="stretch")
        with st.expander("预检报告与下一步"):
            st.json(report)


def _settings(models):
    st.caption("连接、用途配置与实际调用分开；保存设置不会测试网络或向模型外发。")
    with st.form("unlock_vault", clear_on_submit=True):
        phrase = st.text_input("会话解锁口令", type="password")
        unlock = st.form_submit_button("解锁当前会话", disabled=not models.vault.path.exists())
    if not models.vault.path.exists():
        st.caption("Vault 连接保存后可解锁；引用本地 .env 的连接无需 Vault 口令。")
    if unlock:
        try:
            models.vault.unlock(phrase)
            models.vault.lock()
            st.session_state["vault_passphrase"] = phrase
            st.success("当前会话已解锁；刷新进程后需要重新解锁。")
        except Exception as exc:
            st.session_state.pop("vault_passphrase", None)
            _error(exc)
    connections_tab, profiles_tab = st.tabs(["模型连接", "用途 profile"])
    with connections_tab:
        with st.expander("引用已有本地 .env 密钥"):
            st.caption("只保存文件路径和变量名，不复制密钥。每次请求读取指定变量，密钥轮换后无需改写连接。")
            with st.form("create_env_connection"):
                env_name = st.text_input("本地连接名称")
                env_url = st.text_input("本地连接 API base URL", placeholder="https://provider.example/v1")
                env_file = st.text_input(".env 绝对路径", placeholder="/absolute/path/.env")
                env_variable = st.text_input("密钥变量名", value="DEEPSEEK_API_KEY")
                env_submit = st.form_submit_button("保存本地凭据引用")
            if env_submit:
                try:
                    connection = models.create_env_connection(env_name, env_url, env_file, env_variable)
                    st.success(f"已保存连接：{connection['name']}。尚未发起网络请求。")
                except Exception as exc:
                    _error(exc)
        with st.form("create_connection", clear_on_submit=True):
            name = st.text_input("连接名称")
            url = st.text_input("API base URL", placeholder="https://provider.example/v1")
            key = st.text_input("API key", type="password")
            password = st.text_input("加密口令（至少 8 位）", type="password", help="首次保存时设置；已有 vault 必须使用同一口令。")
            submitted = st.form_submit_button("加密保存连接")
        if submitted:
            try:
                connection = models.create_connection(name, url, key, password or st.session_state.get("vault_passphrase", ""))
                st.success(f"连接已加密保存：{connection['name']}。尚未验证网络连通或模型能力。")
            except Exception as exc:
                _error(exc)
        connections = models.list_connections()
        if connections:
            st.dataframe([{**{k: c[k] for k in ("id", "name", "base_url", "created_at")},
                           "credential_source": c.get("credential_source", "vault")} for c in connections], hide_index=True)
        else:
            st.info("尚未配置模型连接。")
    with profiles_tab:
        connections = models.list_connections()
        if not connections:
            st.info("先保存一个模型连接。")
        else:
            with st.form("create_profile"):
                name = st.text_input("Profile 名称")
                purpose = st.selectbox("模型用途", list(PURPOSE_LABELS), format_func=lambda x: PURPOSE_LABELS[x])
                connection = st.selectbox("所用连接", connections, format_func=lambda x: x["name"])
                model = st.text_input("准确模型名称")
                prices = st.checkbox("我已配置该模型的输入／输出费率", value=False)
                a, b = st.columns(2)
                input_rate = a.number_input("输入 USD / 百万 token", min_value=0., value=0., step=.1)
                output_rate = b.number_input("输出 USD / 百万 token", min_value=0., value=0., step=.1)
                st.caption("未勾选则费用未知；0 仅用于你明确确认零费率的模型。修改配置应创建新的 profile。")
                with st.expander("高级：接口输出范围"):
                    declare_wire = st.checkbox("为此 profile 声明接口输出限制", key="profile_wire_declared")
                    wire_formats = st.multiselect("允许的输出格式", ["text", "json_object", "json_schema"],
                        key="profile_wire_formats")
                    wire_hashes = st.text_area("允许的完整 JSON schema 格式摘要（每行一个 SHA256）",
                        key="profile_wire_hashes")
                    st.caption("声明只限制当前 profile，不代表已验证远端支持。json_schema 必须填写完整 response_format 的摘要；更改 name、strict 或 schema 都需要新摘要。JSON 对象模式不保证符合科学合同。")
                submitted = st.form_submit_button("保存不可变用途 profile")
            if submitted:
                try:
                    capability = {"schema_version": CAPABILITIES_VERSION, "api_family": API_FAMILY,
                        "response_formats": wire_formats,
                        "json_schema_format_hashes": [line.strip() for line in wire_hashes.splitlines() if line.strip()]}
                    result = models.create_profile(name, purpose, connection["id"], model,
                        input_usd_per_million=input_rate if prices else None,
                        output_usd_per_million=output_rate if prices else None,
                        wire_capabilities=capability if declare_wire else None)
                    st.success(f"已保存 profile：{result['id']}")
                except Exception as exc:
                    _error(exc)
        profiles = models.list_profiles()
        if profiles:
            st.dataframe([{**{k: p[k] for k in ("id", "name", "purpose", "model", "input_usd_per_million", "output_usd_per_million")},
                "接口输出范围": "显式限制，未远端验收" if "wire_capabilities" in p else "未声明，沿用旧行为"}
                for p in profiles], hide_index=True)
            chat_profiles = [p for p in profiles if p["purpose"] != "embedding"]
            if chat_profiles:
                with st.expander("只读检查输出格式"):
                    selected = st.selectbox("检查用途 profile", chat_profiles, format_func=_profile_label,
                        key="wire_preflight_profile")
                    raw_format = st.text_area("待检查的 response_format JSON（留空表示纯文本）",
                        key="wire_preflight_format")
                    st.caption("此检查要求显式声明，不读取密钥、不发送模型请求。旧配置不会自动迁移；通过仅表示符合本地声明范围，科研协议仍需实际接口资格。")
                    if st.button("仅检查输出格式，不发请求", key="wire_preflight_check"):
                        try:
                            fmt = _strict_json(raw_format) if raw_format.strip() else None
                            st.json(models.preflight(selected["id"], fmt, require_declared=True))
                        except ModelCapabilityError as exc:
                            st.json(exc.preflight)
                            st.info("此格式未通过本地接口范围检查，没有发送请求。")
                        except (ValueError, TypeError):
                            st.info("检查未完成：请使用有效的输出格式和接口声明。没有发送请求。")
