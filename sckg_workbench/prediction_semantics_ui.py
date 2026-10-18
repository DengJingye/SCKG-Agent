"""Opt-in Knowledge-page entry for existing prediction artifact definitions."""
import streamlit as st

from .prediction_semantics import configured_prediction_semantics_service, PredictionSemanticsError
from .storage import content_hash
from .workflow_inputs_ui import _render_source, _text


def render_prediction_semantics(ledger):
    prefix = "prediction_semantics_" + content_hash(str(ledger.workspace.root))[:20] + "_"
    saved_key = prefix + "result"
    if ledger.get_state("prediction_semantics_catalog") is None:
        st.session_state.pop(saved_key, None)
        return
    st.subheader("开发候选 · 实际预测产物的分数定义")
    st.caption("只核对已有文件身份和来源定义；不是执行验收、科学评分或校准证明。完整分数字节仅流式计算身份哈希，不解析每细胞值。")
    if not st.checkbox("显式开启只读预测解释预览", key=prefix + "opt_in"):
        st.session_state.pop(saved_key, None)
        return
    try:
        service = configured_prediction_semantics_service(ledger)
        choices = service.binding_ids()
        if not choices:
            st.info("尚未登记实际产物的开发快照；没有运行或生成任何预测。")
            st.session_state.pop(saved_key, None)
            return
        selected = st.selectbox("选择已登记的产物快照 ID", choices, key=prefix + "binding")
        # Every render rechecks actual files, exact source/package/version,
        # suspension and catalog selection, including before showing old prose.
        current = service.explain(selected)
    except (PredictionSemanticsError, ValueError, KeyError, TypeError):
        st.session_state.pop(saved_key, None)
        st.error("预测解释不可用；文件、来源或目录未通过检查。没有执行分析或调用模型。")
        return
    if st.button("解释已有产物的分数定义", key=prefix + "explain"):
        st.session_state[saved_key] = current
    saved = st.session_state.get(saved_key)
    if not saved:
        return
    if saved.get("result_hash") != current["result_hash"]:
        st.session_state.pop(saved_key, None)
        st.info("产物、来源或目录已改变；旧解释已隐藏，请重新明确选择。")
        return
    _text("运行身份：" + current["run_id"] + " · " + current["run_identity_kind"])
    _text("状态：" + current["status"])
    st.json(current["artifact_facts"])
    _text("尚缺记录：" + ", ".join(current["unknowns"]))
    _text("校准未建立；文件身份一致不等于预测正确，也不等于执行验收通过。")
    for clause in current["clauses"]:
        with st.expander(clause["label"]):
            _text("对当前产物的匹配：" + clause["scope"])
            _text("断言类型：" + clause["binding"]["expected_assertion_kind"])
            if not clause["applies_to_this_artifact"]:
                _text("以下仅为有条件的来源参考，不是已确认的当前产物定义。")
            _text(clause["attribute"]["name"] + "：" + clause["attribute"]["value"])
            for qualifier in clause["attribute"]["qualifiers"]:
                _text("来源限定：" + qualifier)
            _render_source(clause["source"])
            for attribute in clause["source"]["claim"]["typed_attributes"]:
                _text(attribute["name"] + "：" + attribute["value"])
                for qualifier in attribute["qualifiers"]:
                    _text("该属性的来源限定：" + qualifier)
            with st.expander("本条原始引文与锚点记录"):
                st.json({"candidate_id": clause["source"]["candidate_id"],
                    "candidate_hash": clause["source"]["candidate_hash"],
                    "claim": clause["source"]["claim"], "evidence": clause["source"]["evidence"]})
    with st.expander("开发快照与身份读取记录"):
        st.json({k: current[k] for k in ("binding_id", "binding_hash", "catalog_hash", "result_hash", "identity_io")})
