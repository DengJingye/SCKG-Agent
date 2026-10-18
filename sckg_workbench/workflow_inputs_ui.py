"""Explicit development preview of reported inputs against candidate workflows.

This view never releases knowledge, invokes a model, authorizes execution, or
persists its report. Its catalog must already be an immutable, hash-bound ledger
record; ordinary workspaces without the explicit state pointer show no preview.
"""
from __future__ import annotations

import streamlit as st

from .storage import canonical_json, content_hash


_CHOICES = ("未说明", "明确没有", "声明具备")
_VALUES = {"未说明": None, "明确没有": False, "声明具备": True}
_PRECONDITIONS = {
    "reported_met": "报告具备", "reported_unmet": "报告不具备", "unknown": "尚未说明",
}
_ACTIONS = {
    "conditional_plan": "仅可保留条件计划", "blocked": "当前报告输入阻塞", "needs_evidence": "仍需输入信息",
}


def _text(value):
    """Candidate text is displayed as literal text, never as HTML/Markdown."""
    st.text(str(value))


def _render_check(check):
    _text("输入前提：" + _PRECONDITIONS.get(check.get("preconditions_status"), "未知状态"))
    _text("拟议动作：" + _ACTIONS.get(check.get("action_status"), "未知状态"))
    _text("来源事实支持：本预览不重新作科学判断（no_claim）")
    _text(check.get("reason", ""))


def _render_source(source):
    """Keep limitations with their own source, and preserve complete quotes."""
    claim = source["claim"]
    _text("来源主题：" + claim["subject"])
    _text("候选断言：" + claim["proposition"])
    for attribute in claim["typed_attributes"]:
        if attribute["name"] == "workflow.input":
            _text("来源列明的输入：" + attribute["value"])
            for qualifier in attribute["qualifiers"]:
                _text("该输入的限定：" + qualifier)
    for condition in claim["conditions"]:
        _text("该来源的适用条件：" + condition)
    for unknown in claim["unknowns"]:
        _text("该来源保留的未知项：" + unknown)
    for evidence in source["evidence"]:
        _text("原文依据：" + evidence["quote"])


def render_workflow_review(result):
    """Display a review already validated by its caller; perform no new reads."""
    st.caption("本次只读输入检查；报告具备不代表科学适用或本机执行已获授权。")
    for route in result["route_results"]:
        with st.container(border=True):
            _text(route["label"])
            _render_check(route["assessment"]["decision_check"])
            _text("本机执行：尚未绑定执行合同和数据；未授权，未执行。")
            _text("完整科学适用性：尚未建立。")
            for requirement in route["requirements"]:
                with st.expander("输入前提与来源"):
                    _text(requirement["label"])
                    _render_check(requirement["check"])
                    label = ('模型提取的用户报告：' if requirement.get('report_origin') ==
                             'model_extracted_user_text_not_independently_verified' else '用户声明：')
                    _text(label + {None: "未说明", False: "明确没有", True: "声明具备"}[
                        requirement["reported_value"]])
                    for binding in requirement["source_bindings"]:
                        attribute = binding["attribute"]
                        _text("来源列明的输入：" + attribute["value"])
                        for qualifier in attribute["qualifiers"]:
                            _text("该输入的限定：" + qualifier)
            with st.expander("来源候选与范围限制"):
                for source in route["source_records"]:
                    _render_source(source)
                for note in route["scope_notes"]:
                    _text("本流程的范围限制：" + note)
                _text("输入具备不等于方法科学有效；输入未知不表示所有替代方法不可行。")
    with st.expander("本次检查的技术绑定"):
        _text("目录哈希：" + result["catalog_hash"])
        _text("输入哈希：" + result["profile_hash"])
        _text("结果哈希：" + result["result_hash"])
        for route in result["route_results"]:
            _text(canonical_json({"route_id": route["route_id"], "source_records": route["source_records"],
                                  "requirements": route["requirements"]}))


def render_workflow_inputs(ledger):
    """Render the opt-in development catalog; keep interaction results in memory."""
    configured = ledger.get_state("workflow_input_catalog")
    if configured is None:
        return

    st.subheader("开发候选流程 · 输入检查")
    st.caption("按用户声明检查输入前提。候选未发布；不证明科学适用、实际数据具备或本机可执行。")
    try:
        if not isinstance(configured, dict) or set(configured) != {"record_id", "catalog_hash"}:
            raise ValueError("开发目录配置格式不符")
        record_id, digest = configured["record_id"], configured["catalog_hash"]
        if not isinstance(record_id, str) or not isinstance(digest, str):
            raise ValueError("开发目录绑定缺失")
        record = ledger.get_record("workflow_input_catalog", record_id)
        if not isinstance(record, dict) or record.get("id") != record_id:
            raise ValueError("开发目录记录不存在或身份不符")
        catalog = record.get("catalog")
        if record.get("catalog_hash") != digest:
            raise ValueError("开发目录内容与固定哈希不符")
        from .workflow_inputs import WorkflowInputService
        service = WorkflowInputService(ledger, catalog, expected_catalog_hash=digest)
        routes = service.catalog["routes"]
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        st.error("开发输入检查不可用；未调用模型或执行器。")
        _text(str(exc))
        return

    scope = content_hash({"workspace": str(ledger.workspace.root), "catalog_hash": digest})[:20]
    prefix = "workflow_inputs_" + scope + "_"
    route_by_id = {route["route_id"]: route for route in routes}
    st.caption("每次最多选择 4 条流程。未列出的科学前提仍需另外核验。")
    route_ids = st.multiselect("要检查的流程", list(route_by_id), default=list(route_by_id)[:1],
                              format_func=lambda value: route_by_id[value]["label"],
                              max_selections=4, key=prefix + "routes")
    if not route_ids:
        st.info("选择流程后填写实际已知的信息；没有说明的输入保持未知。")
        return

    requirements = {}
    for route_id in route_ids:
        for requirement in route_by_id[route_id]["requirements"]:
            requirements.setdefault(requirement["report_pointer"], requirement)
    reported = {}
    for pointer, requirement in requirements.items():
        _text(requirement["label"])
        key = pointer.removeprefix("/reported_inputs/")
        value = st.selectbox("输入声明", _CHOICES, index=0,
                             key=prefix + "input_" + content_hash(pointer)[:20])
        reported[key] = _VALUES[value]
    profile = {"reported_inputs": reported}
    fingerprint = content_hash({"catalog_hash": digest, "route_ids": route_ids, "profile": profile,
                                "governance_version": ledger.get_state("governance_version", 0)})
    result_key = prefix + "result"
    if st.button("检查这些输入声明", key=prefix + "evaluate"):
        try:
            result = service.evaluate(route_ids, profile)
            st.session_state[result_key] = {"fingerprint": fingerprint, "result": result}
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            st.session_state.pop(result_key, None)
            st.error("输入检查未完成；没有创建执行任务。")
            _text(str(exc))

    saved = st.session_state.get(result_key)
    if saved and saved.get("fingerprint") != fingerprint:
        st.info("输入、流程或治理状态已改变，旧结果已隐藏。请重新检查。")
        return
    if not saved:
        return
    result = saved["result"]
    st.caption("本次只读检查结果；刷新页面不会重新调用模型、执行工具或保存审核记录。")
    render_workflow_review(result)
