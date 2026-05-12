import os
import time
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from agent.workflow import build_sckg_graph
from core.settings import get_settings


st.set_page_config(
    page_title="scKG Agent",
    page_icon="scKG",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        max-width: 1440px;
    }
    h1, h2, h3 {
        letter-spacing: 0;
    }
    .skg-title {
        font-size: 1.7rem;
        font-weight: 720;
        margin-bottom: 0.2rem;
    }
    .skg-subtitle {
        color: #5f6368;
        font-size: 0.95rem;
        margin-bottom: 1rem;
    }
    .status-chip {
        display: inline-block;
        border: 1px solid #d7dbe3;
        border-radius: 999px;
        padding: 0.18rem 0.55rem;
        margin: 0 0.25rem 0.35rem 0;
        background: #f7f8fa;
        color: #2f343d;
        font-size: 0.78rem;
        line-height: 1.4;
    }
    .status-chip.good {
        border-color: #b8dec8;
        background: #eef8f1;
        color: #17643a;
    }
    .status-chip.warn {
        border-color: #ead29a;
        background: #fff7df;
        color: #705000;
    }
    .status-chip.bad {
        border-color: #efb9b1;
        background: #fff1ef;
        color: #8a1f11;
    }
    .tool-card {
        border: 1px solid #dfe3ea;
        border-radius: 8px;
        padding: 0.75rem 0.85rem;
        margin-bottom: 0.65rem;
        background: #ffffff;
    }
    .tool-card-title {
        font-size: 1rem;
        font-weight: 680;
        margin-bottom: 0.15rem;
    }
    .tool-card-meta {
        color: #5f6368;
        font-size: 0.82rem;
    }
    .muted {
        color: #6b7280;
        font-size: 0.9rem;
    }
    .small-label {
        color: #6b7280;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 0.15rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


EXAMPLES = {
    "Doublet detection": "我有一批 10x scRNA-seq PBMC 数据，需要去除 doublet，最好有 benchmark 依据。",
    "Spatial deconvolution": "我有 Visium 空间转录组和 scRNA-seq reference，想估计每个 spot 的细胞类型组成。",
    "RNA velocity": "我有 spliced/unspliced count，想做 RNA velocity 并了解方法局限。",
    "Multiome integration": "我有同一个细胞的 RNA 和 ATAC 数据，想做联合表示和聚类，不想把两个模态完全分开处理。",
    "Perturbation response": "我有 Perturb-seq 扰动前后单细胞数据，想分析扰动响应和差异表达。",
}


def _initial_state(user_query: str) -> Dict[str, Any]:
    return {
        "user_query": user_query,
        "extracted_constraints": {},
        "candidate_tools": [],
        "tool_candidates": [],
        "retrieval_results": [],
        "scored_tools": [],
        "migration_paths": [],
        "workflow_recommendations": [],
        "decision_report": None,
        "final_report": "",
        "hallucination_audit": {},
        "current_step": "init",
        "error_message": None,
    }


def _run_agent(user_query: str, offline_llm: bool) -> Dict[str, Any]:
    previous = os.environ.get("SCKG_OFFLINE_LLM")
    if offline_llm:
        os.environ["SCKG_OFFLINE_LLM"] = "true"
        get_settings.cache_clear()
    try:
        app = build_sckg_graph()
        return dict(app.invoke(_initial_state(user_query)))
    finally:
        if offline_llm:
            if previous is None:
                os.environ.pop("SCKG_OFFLINE_LLM", None)
            else:
                os.environ["SCKG_OFFLINE_LLM"] = previous
            get_settings.cache_clear()


def _state_get_list(state: Dict[str, Any], key: str) -> List[Any]:
    value = state.get(key, [])
    return value if isinstance(value, list) else []


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return {}


def _tool_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for item in _state_get_list(state, "scored_tools"):
        tool = _as_dict(item)
        evidence = tool.get("evidence", {})
        breakdown = tool.get("evidence_breakdown", {})
        rows.append(
            {
                "rank": tool.get("rank", ""),
                "tool": tool.get("tool_name", "Unknown"),
                "score": round(float(tool.get("score", 0.0)), 4),
                "confidence": tool.get("recommendation_confidence", "low"),
                "evidence_coverage": round(_coverage(evidence), 3),
                "missing": ", ".join(evidence.get("missing_evidence", [])[:4]),
                "signals": ", ".join(breakdown.get("recommendation_grade_evidence", [])[:4]),
            }
        )
    if rows:
        return rows
    for item in _state_get_list(state, "migration_paths"):
        path = _as_dict(item)
        evidence = path.get("evidence", {})
        rows.append(
            {
                "rank": "",
                "tool": path.get("tool_name", "Unknown"),
                "score": round(float(path.get("score", 0.0)), 4),
                "confidence": path.get("risk_level", "exploratory"),
                "evidence_coverage": round(_coverage(evidence), 3),
                "missing": ", ".join(evidence.get("missing_evidence", [])[:4]),
                "signals": "migration_candidate",
            }
        )
    return rows


def _coverage(evidence: Dict[str, Any]) -> float:
    items = evidence.get("items", []) if isinstance(evidence, dict) else []
    missing = evidence.get("missing_evidence", []) if isinstance(evidence, dict) else []
    total = len(items) + len(missing)
    return len(items) / total if total else 0.0


def _evidence_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    seen = set()
    for item in _state_get_list(state, "scored_tools"):
        tool = _as_dict(item)
        evidence = tool.get("evidence", {})
        for ev in evidence.get("items", [])[:8]:
            ev_id = ev.get("evidence_id", "")
            key = (tool.get("tool_name"), ev_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "tool": tool.get("tool_name", ""),
                    "type": ev.get("source_type", ""),
                    "metric": ev.get("metric_name", ""),
                    "review": ev.get("review_status", ""),
                    "layer": ev.get("graph_layer", ""),
                    "url": ev.get("source_url") or "",
                }
            )
    return rows


def _audit_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    audit = state.get("hallucination_audit") or {}
    if hasattr(audit, "model_dump"):
        audit = audit.model_dump(mode="json")
    return audit if isinstance(audit, dict) else {}


def _render_chip(text: str, kind: str = "") -> None:
    st.markdown(f'<span class="status-chip {kind}">{text}</span>', unsafe_allow_html=True)


if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Describe a single-cell or spatial omics analysis need. I will return evidence-gated tool recommendations with audit status and missing evidence.",
        }
    ]


with st.sidebar:
    logo = get_settings().logo_path
    if logo.exists():
        st.image(str(logo), width=128)
    st.markdown("### scKG Agent")
    st.caption("Evidence-governed recommendation workspace")

    offline_llm = st.toggle(
        "Offline LLM mode",
        value=True,
        help="Keeps development and demos from calling DeepSeek/OpenAI.",
    )
    run_live = st.checkbox(
        "Allow paid LLM calls",
        value=False,
        disabled=offline_llm,
        help="Disable Offline LLM mode first. Use only for final evaluation.",
    )
    semantic_audit_visible = st.checkbox("Show audit details", value=True)
    debug_visible = st.checkbox("Show raw state", value=False)

    st.divider()
    selected_example = st.selectbox("Example query", ["Custom", *EXAMPLES.keys()])
    if selected_example != "Custom" and st.button("Use example", use_container_width=True):
        st.session_state.pending_query = EXAMPLES[selected_example]
        st.rerun()

    st.divider()
    _render_chip("trusted evidence gate", "good")
    _render_chip("candidate evidence isolated", "good")
    _render_chip("v0.2 frozen", "warn")
    if offline_llm:
        _render_chip("LLM calls disabled", "good")
    elif run_live:
        _render_chip("paid LLM enabled", "warn")


st.markdown('<div class="skg-title">scKG Agent</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="skg-subtitle">Scientific tool recommendation with trusted evidence, benchmark caveats, and semantic audit.</div>',
    unsafe_allow_html=True,
)

main_col, side_col = st.columns([1.55, 1], gap="large")

with main_col:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    default_query = st.session_state.pop("pending_query", "")
    query = st.chat_input("Ask for a single-cell, spatial, or multiome tool recommendation...")
    if default_query and not query:
        query = default_query

    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            started = time.perf_counter()
            with st.status("Running trusted recommendation pipeline", expanded=True) as status:
                st.write("Parsing task and constraints")
                st.write("Retrieving trusted tool evidence")
                st.write("Ranking with evidence-aware MCDM")
                st.write("Generating structured report")
                try:
                    state = _run_agent(query, offline_llm=(offline_llm or not run_live))
                    status.update(label="Recommendation complete", state="complete")
                except Exception as exc:
                    state = {
                        "final_report": f"Execution failed: {exc}",
                        "error_message": str(exc),
                        "hallucination_audit": {},
                    }
                    status.update(label="Recommendation failed", state="error")

            elapsed = time.perf_counter() - started
            report = state.get("final_report", "")
            st.markdown(report or "No report was generated.")
            st.caption(f"Runtime: {elapsed:.2f}s")
            st.session_state.latest_state = state
            st.session_state.messages.append({"role": "assistant", "content": report})

            st.download_button(
                "Download report",
                data=report,
                file_name="scKG_Agent_Report.md",
                mime="text/markdown",
                use_container_width=True,
            )

with side_col:
    st.markdown("### Recommendation")
    state = st.session_state.get("latest_state", {})
    constraints = state.get("extracted_constraints", {}) if isinstance(state, dict) else {}
    if hasattr(constraints, "model_dump"):
        constraints = constraints.model_dump(mode="json")
    if constraints:
        _render_chip(f"task: {constraints.get('task', 'Unknown')}")
        _render_chip(f"modality: {constraints.get('modality', 'Unknown')}")
        _render_chip(f"state: {constraints.get('clarification_state', 'Unknown')}")
    else:
        st.markdown('<div class="muted">Run a query to see parsed constraints.</div>', unsafe_allow_html=True)

    rows = _tool_rows(state) if isinstance(state, dict) else []
    if rows:
        for row in rows:
            st.markdown(
                f"""
<div class="tool-card">
  <div class="tool-card-title">{row['rank']}. {row['tool']}</div>
  <div class="tool-card-meta">score {row['score']} | confidence {row['confidence']} | evidence coverage {row['evidence_coverage']}</div>
  <div class="tool-card-meta">signals: {row['signals'] or 'none'}</div>
  <div class="tool-card-meta">missing: {row['missing'] or 'none'}</div>
</div>
""",
                unsafe_allow_html=True,
            )
    else:
        st.markdown('<div class="muted">No ranked tools yet.</div>', unsafe_allow_html=True)

    st.markdown("### Evidence")
    evidence_rows = _evidence_rows(state) if isinstance(state, dict) else []
    if evidence_rows:
        st.dataframe(pd.DataFrame(evidence_rows), hide_index=True, use_container_width=True)
    else:
        st.markdown('<div class="muted">Evidence rows appear after a recommendation.</div>', unsafe_allow_html=True)

    st.markdown("### Audit")
    audit = _audit_summary(state) if isinstance(state, dict) else {}
    if audit:
        passed = audit.get("passed")
        severity_counts = audit.get("severity_counts", {})
        _render_chip("pass" if passed else "needs review", "good" if passed else "bad")
        _render_chip(f"unsupported claims: {audit.get('unsupported_claim_count', 0)}")
        _render_chip(f"high: {severity_counts.get('high', 0)}")
        _render_chip(f"critical: {severity_counts.get('critical', 0)}")
        if semantic_audit_visible and audit.get("issues"):
            st.dataframe(pd.DataFrame(audit["issues"]), hide_index=True, use_container_width=True)
    else:
        st.markdown('<div class="muted">Audit runs with the recommendation pipeline.</div>', unsafe_allow_html=True)

    if debug_visible and isinstance(state, dict) and state:
        with st.expander("Raw state", expanded=False):
            st.json(state)
