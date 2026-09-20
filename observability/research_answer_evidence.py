"""Decision-local evidence UI; no retrieval, inference, or authority mutation."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from agent.scientific_response_context import decision_local_projection
from observability.research_source_links import source_links


def render_answer_evidence(st, state: dict, *, source_manifest: Path) -> None:
    context = state.get("context_pack") or {}
    provenance = context.get("answer_provenance") or decision_local_projection(
        state.get("final_report", ""), state.get("references", []))
    refs = provenance.get("references", [])
    if not refs and not context.get("response_context"):
        return
    facts = provenance.get("kg_facts_used", [])
    links = {row["index"]: row for row in source_links(refs, source_manifest)}
    for ref in refs:
        url = str(ref.get("source_url") or "")
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and not any(ord(c) < 32 for c in url):
            links[ref["index"]] = {"url": url}
    if refs:
        cols = st.columns(min(len(refs), 4))
        for offset, ref in enumerate(refs):
            with cols[offset % len(cols)].popover(f"[{ref['index']}] 原文"):
                st.markdown(ref.get("title") or ref.get("source_id"))
                st.caption(str(ref.get("source_span") or "定位不可用"))
                st.text(ref.get("exact_excerpt") or ref.get("claim_text") or "摘录不可用")
                if ref["index"] in links:
                    st.link_button("打开登记来源", links[ref["index"]]["url"])
    kg_context = context.get("response_context", {}).get("scientific_kg", {})
    identity = kg_context.get("identity", "Scientific KG")
    st.caption("本次依据：" + (identity + " · " if facts else identity + " 暂无直接支持 · ")
               + ("来源证据" if refs else "本地证据不足")
               + (" · 含模型通识" if "MODEL_KNOWLEDGE" in provenance.get("knowledge_sources", []) else ""))
    with st.expander("为什么这样建议？ · 本次使用的知识", expanded=False):
        if not facts:
            st.write("当前 Scientific KG 未提供可直接支撑本回答的 Statement；来源检索与模型通识会分别标明。")
        for fact in facts:
            st.markdown(f"- [{fact['citation_index']}] {fact.get('statement') or fact['predicate']}")
            st.caption("已人工批准 · 是否适用仍取决于范围条件 · 不授予执行权限。" if fact.get("knowledge_status") == "approved"
                       else "KG 候选知识 · 已匹配原文绑定，尚不代表人工审核或可执行许可。")
            st.write({"适用范围": fact.get("scope"), "输入约束": fact.get("constraints")})
        for caution in provenance.get("caution_context_used", []):
            st.write(caution["description"])
            st.caption("Caution / EvidenceGap：提醒上下文，非科学断言；untrusted，无执行阻断或授权权限。")
        for claim in provenance.get("claims", []):
            if claim.get("knowledge_source") == "USER_CLARIFICATION":
                continue
            st.markdown(claim["text"])
            st.caption(claim["knowledge_source"])
        st.caption("数据状态：" + str((context.get("response_context", {}).get("data_state") or {}).get("status", "not_inspected")))
        st.caption("引用与摘录通过结构检查；未进行独立语义评审。")
    if not refs:
        return
    with st.expander("科学证据 · 查看引用原文", expanded=False):
        for ref in refs:
            index = ref["index"]
            st.markdown(f"**[{index}] {ref.get('title') or ref.get('source_id')}**")
            st.caption(str(ref.get("source_span") or "原文定位不可用"))
            st.caption(str(ref.get("source_type") or "source_bound_excerpt"))
            st.text(ref.get("exact_excerpt") or ref.get("claim_text") or "原文摘录不可用")
            for claim in provenance.get("claims", []):
                if any(c.get("index") == index for c in claim.get("citations", [])):
                    st.caption("支持本轮结论：" + claim["text"])
            for fact in ref.get("kg_statements", []):
                st.code(" → ".join([fact["statement_id"], *fact.get("assessment_ids", []),
                                   fact["evidence_span_id"], fact["source_revision_id"]]), language=None)
                if fact.get("assessments"):
                    st.write({"EvidenceAssessment": fact["assessments"]})
            if ref.get("source_revision"):
                st.write({"SourceRevision": ref["source_revision"]})
            if ref.get("caution_context"):
                st.code(" → ".join([ref["caution_context"]["caution_id"], ref["source_span_id"], ref["source_id"]]), language=None)
                st.caption("提醒证据，不属于 approved scientific assertion。")
            if index in links:
                st.link_button(f"打开来源 [{index}]", links[index]["url"])
