from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from core.settings import get_settings
from engine.workflow_decision import (
    DEFAULT_WORKFLOW_CANDIDATE_TOOLS,
    DEFAULT_WORKFLOW_QUERY,
    build_workflow_decision_response,
)
from observability.dashboard.services import EvidenceRecoveryService, ReflectionService, TraceService


_STREAMLIT_DATAFRAME = st.dataframe


def _safe_streamlit_dataframe(data: Any, *args: Any, **kwargs: Any) -> Any:
    return _STREAMLIT_DATAFRAME(_arrow_safe_dataframe(data), *args, **kwargs)


def _arrow_safe_dataframe(data: Any) -> pd.DataFrame:
    frame = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    for column in frame.columns:
        frame[column] = frame[column].map(_arrow_safe_cell)
    return frame


def _arrow_safe_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


st.dataframe = _safe_streamlit_dataframe
st.set_page_config(page_title="scKG Observability", layout="wide")


def main() -> None:
    st.title("scKG-Agent Observability")
    trace_service = TraceService()
    reflection_service = ReflectionService()
    evidence_recovery_service = EvidenceRecoveryService()
    tabs = st.tabs(
        [
            "Home / Chat",
            "Run Trace",
            "Evidence & RAG",
            "Neo4j / KG",
            "Reflection Memory",
            "Evaluation",
            "Settings",
        ]
    )
    with tabs[0]:
        render_home_chat(trace_service)
    with tabs[1]:
        render_run_trace(trace_service)
    with tabs[2]:
        render_evidence_rag(trace_service, evidence_recovery_service)
    with tabs[3]:
        render_neo4j_kg(trace_service)
    with tabs[4]:
        render_reflection_memory(reflection_service)
    with tabs[5]:
        render_evaluation()
    with tabs[6]:
        render_settings()


def render_home_chat(service: TraceService) -> None:
    overview = service.overview()
    latest = overview.get("latest_agent_run")
    kg_summary = service.kg_gate_summary(latest) if latest else {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("All Traces", overview["trace_count"])
    c2.metric("Agent Runs", overview["agent_run_count"])
    c3.metric("Avg Agent Time", f"{overview['average_agent_run_ms']:.0f} ms")
    c4.metric("Latest KG Candidates", kg_summary.get("candidate_tool_count", 0))
    if latest:
        metadata = latest.get("metadata") or {}
        st.markdown("### Latest Run")
        st.table(
            [
                {"field": "trace_id", "value": latest.get("trace_id", "")},
                {"field": "query", "value": metadata.get("query", "")},
                {"field": "architecture", "value": metadata.get("architecture", "")},
                {"field": "graph_mode", "value": "offline" if metadata.get("force_offline_graph") else "neo4j/live-or-fallback"},
                {"field": "elapsed_ms", "value": f"{float(latest.get('elapsed_ms') or 0.0):.0f}"},
            ]
        )
        st.markdown("### Current Gate")
        st.table(
            [
                {"metric": "raw_candidate_count", "value": kg_summary.get("raw_candidate_count", 0)},
                {"metric": "admitted_candidate_count", "value": kg_summary.get("candidate_tool_count", 0)},
                {"metric": "retrieval_result_count", "value": kg_summary.get("retrieval_result_count", 0)},
                {"metric": "provider", "value": kg_summary.get("provider", "")},
            ]
        )
    else:
        st.info("No agent run trace found yet. Run `python scripts/run_agent_trace_smoke.py` or send one chat query in the main app.")
    render_workflow_decision_sandbox()


def render_workflow_decision_sandbox() -> None:
    st.markdown("### Workflow Decision Sandbox")
    st.caption(
        "本地可交互入口：生成 workflow plan、step-level candidate tools、RAG snippets 和 evidence boundary。"
    )
    task_options = [
        "Workflow Planning",
        "Doublet Detection",
        "Ambient RNA Removal",
        "Data Integration",
        "Cell Type Annotation",
        "Spatial Deconvolution",
        "RNA Velocity",
        "Multiome Integration",
        "Workflow Compatibility",
        "Trajectory Differential Expression",
        "Differential Expression",
    ]
    modality_options = ["scRNA-seq", "Spatial Transcriptomics", "Multiome", "scATAC-seq"]
    with st.form("workflow_decision_form"):
        query = st.text_area("Query", value=DEFAULT_WORKFLOW_QUERY, height=92)
        c1, c2, c3 = st.columns(3)
        task = c1.selectbox("Task", task_options, index=0)
        modality = c2.selectbox("Modality", modality_options, index=0)
        species = c3.selectbox("Species", ["Human", "Mouse", "Human+Mouse", "Unknown"], index=0)
        c4, c5 = st.columns(2)
        data_object = c4.text_input("Data Object", value="raw count matrix / AnnData / SeuratObject")
        output_goal = c5.text_input(
            "Output Goal",
            value="integrated doublet-filtered annotated object with auditable report",
        )
        c6, c7 = st.columns(2)
        platform = c6.text_input("Platform", value="10x Genomics")
        noise = c7.selectbox("Noise", ["medium", "low", "high", "Unknown"], index=0)
        candidate_tools = st.multiselect(
            "Candidate Tools",
            DEFAULT_WORKFLOW_CANDIDATE_TOOLS,
            default=[
                "Scanpy",
                "Seurat",
                "Scrublet",
                "DoubletFinder",
                "Harmony",
                "scvi-tools",
                "CellTypist",
                "SingleR",
                "scVelo",
                "CellRank",
            ],
        )
        submitted = st.form_submit_button("Run Workflow Decision")

    if submitted:
        constraints = {
            "task": task,
            "modality": modality,
            "species": species,
            "platform": platform,
            "data_object": data_object,
            "noise": noise,
            "output_goal": output_goal,
            "strictness": "evidence_limited",
        }
        with st.spinner("Building evidence-governed workflow decision..."):
            st.session_state.workflow_decision_response = build_workflow_decision_response(
                query=query,
                constraints=constraints,
                candidate_tools=candidate_tools,
                max_snippets_per_step=4,
            )

    response = st.session_state.get("workflow_decision_response")
    if response:
        render_workflow_decision_response(response)


def render_workflow_decision_response(response: Dict[str, Any]) -> None:
    metrics = response.get("metrics") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Steps", metrics.get("workflow_steps", 0))
    c2.metric("Candidates", metrics.get("candidate_tool_count", 0))
    c3.metric("Snippets", metrics.get("retrieval_snippets", 0))
    c4.metric("Source Snippets", metrics.get("source_bound_retrieval_snippets", 0))
    c5.metric("Boundary Violations", metrics.get("evidence_boundary_violation_count", 0))
    if metrics.get("evidence_boundary_violation_count", 0):
        st.error("Evidence boundary violation detected. Do not use this output as recommendation support.")
    else:
        st.success("Workflow decision generated with evidence boundary intact.")
    st.caption(response.get("guardrail", ""))

    steps = response.get("workflow_steps") or []
    if steps:
        st.markdown("#### Workflow Steps")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "order": step.get("order"),
                        "step": step.get("name", ""),
                        "task": step.get("task", ""),
                        "candidate_tools": ", ".join(step.get("candidate_tools") or []),
                        "snippets": step.get("snippet_count", 0),
                        "source_snippets": step.get("source_bound_snippet_count", 0),
                        "status": step.get("status", ""),
                    }
                    for step in steps
                ]
            ),
            use_container_width=True,
        )
        for step in steps:
            with st.expander(f"{step.get('order')}. {step.get('name')}"):
                st.table(
                    [
                        {"field": "task", "value": step.get("task", "")},
                        {"field": "required_input", "value": ", ".join(step.get("required_input") or [])},
                        {"field": "produced_output", "value": ", ".join(step.get("produced_output") or [])},
                        {"field": "candidate_tools", "value": ", ".join(step.get("candidate_tools") or [])},
                        {"field": "rag_mode", "value": step.get("rag_mode", "")},
                    ]
                )
                snippets = step.get("snippets") or []
                if snippets:
                    st.dataframe(pd.DataFrame(snippets), use_container_width=True)
                else:
                    st.info("No retrieval snippets for this step yet.")

    warnings = response.get("compatibility_warnings") or []
    if warnings:
        st.markdown("#### Compatibility Warnings")
        st.dataframe(pd.DataFrame({"warning": warnings}), use_container_width=True)
    next_actions = response.get("next_actions") or []
    if next_actions:
        st.markdown("#### Next Actions")
        st.dataframe(pd.DataFrame({"action": next_actions}), use_container_width=True)
    with st.expander("Markdown Report", expanded=False):
        st.code(response.get("markdown_report", ""), language="markdown")


def render_run_trace(service: TraceService) -> None:
    traces = service.list_traces("agent_run")
    if not traces:
        st.info("No agent traces found. Run `python scripts/run_agent_trace_smoke.py` or send one chat query in the main app.")
        return
    for idx, trace in enumerate(traces):
        query = (trace.get("metadata") or {}).get("query", "")
        title = f"{query[:80] or trace.get('trace_id')} | {trace.get('elapsed_ms', 0):.0f} ms"
        with st.expander(title, expanded=idx == 0):
            render_trace_detail(service, trace, nested_in_expander=True)


def render_evidence_rag(service: TraceService, evidence_recovery_service: EvidenceRecoveryService) -> None:
    coverage_v2 = _read_json_file(
        PROJECT_ROOT / "data" / "indexes" / "retrieval_coverage_v2.json"
    )
    eval_v2 = _read_json_file(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval_eval_v2" / "summary.json"
    )
    kg_bm25 = (eval_v2.get("profiles") or {}).get("kg_bm25") or {}
    if coverage_v2:
        st.markdown("### Knowledge Intelligence v2")
        metrics = st.columns(6)
        metrics[0].metric("Source docs", coverage_v2.get("source_document_count", 0))
        metrics[1].metric("Chunks", coverage_v2.get("chunk_count", 0))
        metrics[2].metric(
            "Core coverage", f"{coverage_v2.get('core_tool_source_coverage_rate', 0) * 100:.1f}%"
        )
        metrics[3].metric("Recall@10", f"{kg_bm25.get('recall_at_10', 0) * 100:.1f}%")
        metrics[4].metric("Precision@10", f"{kg_bm25.get('precision_at_10', 0) * 100:.1f}%")
        metrics[5].metric("Warm p95", f"{kg_bm25.get('latency_p95_ms', 0):.1f} ms")
        st.caption(
            "Local KG + SQLite FTS5 BM25 is the active deterministic path. Dense and RAGAS remain optional and display not_run when unavailable."
        )
    trace = service.latest_agent_run()
    if not trace:
        st.info("No evidence trace found. Run `python scripts/run_agent_trace_smoke.py` first.")
        summary = {}
    else:
        summary = service.kg_gate_summary(trace)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Raw Candidates", summary.get("raw_candidate_count", 0))
        c2.metric("Admitted", summary.get("candidate_tool_count", 0))
        c3.metric("Retrieval Results", summary.get("retrieval_result_count", 0))
        c4.metric("Blocked Reasons", len(summary.get("blocked_reason_counts") or {}))
    st.markdown("### Evidence Boundary")
    st.table(
        [
            {"context": "formal TSV / trusted KG", "authority": "can affect ranking only through evidence gate"},
            {"context": "RAG chunks", "authority": "retrieval context only"},
            {"context": "reflection memory", "authority": "operational memory only"},
            {"context": "skill candidates", "authority": "review queue only"},
            {"context": "subagent output", "authority": "candidate context only"},
        ]
    )
    st.markdown("### Evidence Stages")
    if trace:
        render_stage_table(service.evidence_stage_rows(trace))
        diagnostics = summary.get("candidate_diagnostics") or []
        st.markdown("### Candidate Gate Diagnostics")
        if diagnostics:
            st.dataframe(pd.DataFrame(diagnostics), use_container_width=True)
        else:
            st.info("No candidate diagnostics recorded for this run.")
    else:
        st.info("No trace stage table yet. Offline Evidence/RAG artifacts are shown below.")
    render_source_coverage(evidence_recovery_service)
    render_literature_source_coverage(evidence_recovery_service)
    render_decision_workflow_demo(evidence_recovery_service)
    render_doublet_recovery_demo(evidence_recovery_service)


def render_source_coverage(service: EvidenceRecoveryService) -> None:
    st.markdown("### Core Tool Source Coverage")
    coverage = service.load_source_coverage()
    summary = coverage.get("summary") or {}
    rows = coverage.get("rows") or []
    if not rows:
        st.info(
            "No core source coverage manifest found. Run "
            "`python data_pipeline/build_core_tool_source_manifest.py` first."
        )
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Core Tools", summary.get("core_tools", 0))
    c2.metric("Covered", summary.get("covered_tools", 0))
    c3.metric("Missing", summary.get("missing_tools", 0))
    c4.metric("Source Chunks", summary.get("source_chunk_count", 0))
    c5.metric("Dense Vectors", summary.get("dense_vector_chunk_count", 0))
    st.caption(
        "Source chunks are retrieval/migration context only. They cannot promote formal TSV evidence "
        "or change recommendation rank directly."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "tool_name": row.get("tool_name", ""),
                    "coverage_status": row.get("coverage_status", ""),
                    "source_chunk_count": row.get("source_chunk_count", 0),
                    "dense_vector_chunk_count": row.get("dense_vector_chunk_count", 0),
                    "review_status": row.get("review_status", ""),
                    "source_types": row.get("source_types", ""),
                    "fetch_statuses": row.get("fetch_statuses", ""),
                    "quality_flags": row.get("quality_flags", ""),
                }
                for row in rows
            ]
        ),
        use_container_width=True,
    )
    missing = [row for row in rows if row.get("coverage_status") != "covered"]
    if missing:
        with st.expander("Missing Source Details", expanded=True):
            st.dataframe(pd.DataFrame(missing), use_container_width=True)


def render_literature_source_coverage(service: EvidenceRecoveryService) -> None:
    st.markdown("### Paper / Benchmark Source Coverage")
    coverage = service.load_literature_source_coverage()
    registry_status = service.load_source_registry_status()
    summary = coverage.get("summary") or {}
    rows = coverage.get("rows") or []
    if not rows:
        st.info(
            "No literature source coverage artifact found. Run "
            "`python data_pipeline/build_literature_source_coverage.py` first."
        )
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Source Rows", summary.get("rows", 0))
    c2.metric("Text Available", summary.get("source_text_available", 0))
    c3.metric("Too Short", summary.get("source_text_too_short", 0))
    c4.metric("Missing Text", summary.get("missing_source_text", 0))
    c5.metric("Manual Queue", summary.get("manual_queue_rows", 0))
    st.caption(summary.get("guardrail", ""))
    display_rows = [
        {
            "tool_name": row.get("tool_name", ""),
            "evidence_kind": row.get("evidence_kind", ""),
            "coverage_status": row.get("coverage_status", ""),
            "action": row.get("action", ""),
            "source_title": row.get("source_title", ""),
            "doi_or_pmid": row.get("doi_or_pmid", ""),
            "pdf_status": row.get("pdf_status", ""),
            "dashboard_status": row.get("dashboard_status", ""),
            "text_chars": row.get("text_chars", ""),
            "candidate_issue": row.get("candidate_issue", ""),
            "suggested_pdf_path": row.get("suggested_pdf_path", ""),
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(display_rows), use_container_width=True)
    missing = [row for row in rows if row.get("coverage_status") != "source_text_available"]
    if missing:
        with st.expander("Manual Acquisition / Resolution Queue", expanded=True):
            st.dataframe(pd.DataFrame(missing), use_container_width=True)
    render_source_registry_status(registry_status)


def render_source_registry_status(status: Dict[str, Any]) -> None:
    registry_rows = status.get("registry_rows") or []
    validation_rows = status.get("validation_rows") or []
    candidate_rows = status.get("candidate_rows") or []
    acquisition_summary = status.get("acquisition_summary") or {}
    extraction_summary = status.get("extraction_summary") or {}
    if not registry_rows:
        st.info(
            "No source-level registry found. Run "
            "`python data_pipeline/build_source_registry.py` to build validation artifacts."
        )
        return
    st.markdown("#### Source-Level Registry")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Source Records", acquisition_summary.get("source_records", len(registry_rows)))
    c2.metric("Shared Sources", acquisition_summary.get("shared_source_records", 0))
    c3.metric("Quarantined Candidates", acquisition_summary.get("candidate_quarantine_rows", 0))
    c4.metric("Text Sources", extraction_summary.get("source_text_available", 0))
    c5.metric("Extract Failures", extraction_summary.get("pdf_extraction_failed", 0))
    st.caption(
        "Source registry is source-level: one paper/source can be referenced by multiple tool evidence rows. "
        "Metadata mismatch rows are quarantined and cannot be ingested."
    )
    display_registry = [
        {
            "source_id": row.get("source_id", ""),
            "source_status": row.get("source_status", ""),
            "validation_status": row.get("validation_status", ""),
            "canonical_title": row.get("canonical_title", ""),
            "doi": row.get("doi", ""),
            "tools": row.get("referring_tool_names", ""),
            "records": row.get("referring_record_ids", ""),
            "local_text_path": row.get("local_text_path", ""),
            "local_pdf_path": row.get("local_pdf_path", ""),
        }
        for row in registry_rows
    ]
    st.dataframe(pd.DataFrame(display_registry), use_container_width=True)

    failures = [
        row for row in validation_rows
        if row.get("recommended_action") and row.get("recommended_action") != "none"
    ]
    if failures:
        with st.expander("Source Validation Failures", expanded=True):
            st.dataframe(pd.DataFrame(failures), use_container_width=True)

    extraction_failures = [
        row for row in registry_rows
        if row.get("validation_status") == "pdf_exists_but_extract_failed"
    ]
    if extraction_failures:
        with st.expander("PDF Extraction Failures", expanded=True):
            st.dataframe(pd.DataFrame(extraction_failures), use_container_width=True)

    quarantined = [row for row in candidate_rows if row.get("quarantine") == "true"]
    if quarantined:
        with st.expander("Quarantined PDF Candidates", expanded=True):
            st.dataframe(pd.DataFrame(quarantined), use_container_width=True)


def render_decision_workflow_demo(service: EvidenceRecoveryService) -> None:
    st.markdown("### Decision Workflow Demo")
    demo = service.load_decision_workflow_demo()
    if not demo:
        st.info(
            "No decision workflow demo artifact found. Run "
            "`python data_pipeline/build_decision_workflow_demo.py` first."
        )
        return
    scenario = demo.get("scenario") or {}
    coverage = demo.get("global_evidence_coverage") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Workflow Steps", coverage.get("workflow_steps", 0))
    c2.metric("Matched Steps", coverage.get("steps_with_any_tool_match", 0))
    c3.metric("Snippets", coverage.get("total_retrieval_snippets", 0))
    c4.metric("Source Chunks", coverage.get("source_bound_retrieval_snippets", 0))
    c5.metric("Strong Evidence", coverage.get("formal_main_recommendation_evidence_count", 0))
    st.caption(demo.get("positioning", ""))
    st.table(
        [
            {"field": "query", "value": scenario.get("user_query", "")},
            {"field": "modality", "value": scenario.get("modality", "")},
            {"field": "scale", "value": scenario.get("scale", "")},
            {"field": "status", "value": coverage.get("status", "")},
            {"field": "guardrail", "value": demo.get("guardrail", "")},
        ]
    )

    steps = demo.get("workflow_steps") or []
    if steps:
        st.markdown("#### Workflow Steps")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "order": step.get("order"),
                        "step": step.get("name", ""),
                        "task": step.get("task", ""),
                        "default_candidate": step.get("default_candidate", ""),
                        "candidate_tools": ", ".join(step.get("candidate_tools") or []),
                        "snippets": (step.get("evidence_coverage") or {}).get("snippet_count", 0),
                        "source_chunks": (step.get("evidence_coverage") or {}).get("source_bound_snippet_count", 0),
                        "status": step.get("status", ""),
                    }
                    for step in steps
                ]
            ),
            use_container_width=True,
        )
        with st.expander("Step Evidence Snippets", expanded=False):
            snippet_rows = []
            for step in steps:
                for snippet in (step.get("retrieval") or {}).get("snippets") or []:
                    snippet_rows.append(
                        {
                            "step": step.get("name", ""),
                            "tool_name": snippet.get("tool_name", ""),
                            "source_kind": snippet.get("source_kind", ""),
                            "title": snippet.get("title", ""),
                            "source_span": snippet.get("source_span", ""),
                            "claim_span": snippet.get("claim_span", ""),
                            "boundary": snippet.get("claim_boundary", ""),
                        }
                    )
            st.dataframe(pd.DataFrame(snippet_rows), use_container_width=True)

    tool_cards = demo.get("tool_cards") or []
    if tool_cards:
        with st.expander("Candidate Tool Cards", expanded=False):
            st.dataframe(pd.DataFrame(tool_cards), use_container_width=True)

    code = demo.get("code_skeletons") or {}
    if code:
        with st.expander("Executable Skeletons", expanded=False):
            if code.get("scanpy_python"):
                st.markdown("##### Scanpy Python")
                st.code(code["scanpy_python"], language="python")
            if code.get("seurat_r"):
                st.markdown("##### Seurat R")
                st.code(code["seurat_r"], language="r")


def render_doublet_recovery_demo(service: EvidenceRecoveryService) -> None:
    st.markdown("### Doublet Detection Recovery Demo")
    demo = service.load_doublet_demo()
    if not demo:
        st.info(
            "No doublet recovery demo artifact found. Run "
            "`python data_pipeline/build_doublet_recovery_demo.py` first."
        )
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Formal Rows", demo.get("formal_rows", 0))
    c2.metric("Source Texts", demo.get("source_text_available", 0))
    c3.metric("Snippets", (demo.get("retrieval") or {}).get("snippet_count", 0))
    c4.metric("Promotion Ready", demo.get("promotion_ready_count", 0))
    st.caption(demo.get("guardrail", ""))
    render_pdf_download_status(service)
    render_pdf_ingestion_status(service)
    gate = demo.get("kg_gate_snapshot") or {}
    if gate:
        st.markdown("#### Latest KG Gate Snapshot")
        st.table(
            [
                {"field": "trace_id", "value": gate.get("trace_id", "")},
                {"field": "provider", "value": gate.get("provider", "")},
                {"field": "raw_candidate_count", "value": gate.get("raw_candidate_count", 0)},
                {"field": "admitted_candidate_count", "value": gate.get("admitted_candidate_count", 0)},
                {"field": "target_tools_seen", "value": ", ".join(gate.get("target_tools_seen") or [])},
                {"field": "blocked_reason_counts", "value": gate.get("blocked_reason_counts") or {}},
            ]
        )
    status_rows = demo.get("formal_evidence_status") or []
    st.markdown("#### Formal Evidence Recovery Status")
    if status_rows:
        st.dataframe(pd.DataFrame(status_rows), use_container_width=True)
    else:
        st.info("No formal evidence status rows.")
    snippets = (demo.get("retrieval") or {}).get("snippets") or []
    st.markdown("#### Retrieval Snippets")
    if snippets:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "tool_name": item.get("tool_name", ""),
                        "source_kind": item.get("source_kind", ""),
                        "title": item.get("title", ""),
                        "doi": item.get("doi", ""),
                        "relevance_score": item.get("relevance_score", 0),
                        "review_status": item.get("review_status", ""),
                        "claim_span": item.get("claim_span", ""),
                    }
                    for item in snippets
                ]
            ),
            use_container_width=True,
        )
    else:
        st.info("No retrieval snippets found.")


def render_pdf_download_status(service: EvidenceRecoveryService) -> None:
    st.markdown("#### PDF Download Status")
    summary = service.load_pdf_download_summary()
    if not summary:
        st.info(
            "No PDF download summary found. Run "
            "`python data_pipeline/download_evidence_pdfs.py --limit 4` for discovery, "
            "then add `--live` when you want to download open PDFs."
        )
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Mode", "live" if summary.get("live") else "dry-run")
    c2.metric("Attempted", summary.get("attempted_rows", 0))
    c3.metric("Candidates", summary.get("candidate_found", 0))
    c4.metric("Downloaded", summary.get("downloaded", 0))
    c5.metric("Errors", summary.get("errors", 0))
    st.caption(summary.get("guardrail", ""))
    rows = summary.get("rows") or []
    if rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "tool_name": item.get("tool_name", ""),
                        "evidence_kind": item.get("evidence_kind", ""),
                        "record_id": item.get("record_id", ""),
                        "status": item.get("status", ""),
                        "selected_pdf_url": item.get("selected_pdf_url", ""),
                        "target_pdf": item.get("target_pdf", ""),
                        "error": item.get("error", ""),
                    }
                    for item in rows
                ]
            ),
            use_container_width=True,
        )


def render_pdf_ingestion_status(service: EvidenceRecoveryService) -> None:
    st.markdown("#### PDF Ingestion Status")
    summary = service.load_pdf_ingest_summary()
    if not summary:
        st.info(
            "No PDF ingestion summary found. Put PDFs under "
            "`data/evidence_sources/pdfs/`, then run "
            "`python data_pipeline/ingest_evidence_pdfs.py`."
        )
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("PDF Files", summary.get("pdf_files", 0))
    c2.metric("Matched Rows", summary.get("matched_rows", 0))
    c3.metric("Extracted Rows", summary.get("extracted_rows", 0))
    c4.metric("Extractor", summary.get("extractor", ""))
    rows = summary.get("rows") or []
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    suggestions = summary.get("suggested_filenames") or []
    if suggestions:
        with st.expander("Suggested PDF filenames"):
            st.dataframe(pd.DataFrame(suggestions), use_container_width=True)


def render_neo4j_kg(service: TraceService) -> None:
    trace = service.latest_agent_run()
    if not trace:
        st.info("No KG trace found. Run `python scripts/run_agent_trace_smoke.py` first.")
        return
    summary = service.kg_gate_summary(trace)
    metadata = trace.get("metadata") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Provider", summary.get("provider", "") or "unknown")
    c2.metric("Raw", summary.get("raw_candidate_count", 0))
    c3.metric("Admitted", summary.get("candidate_tool_count", 0))
    c4.metric("Offline Graph", str(bool(metadata.get("force_offline_graph"))))
    if summary.get("error"):
        st.error(summary["error"])
    st.markdown("### Blocked Reason Counts")
    blocked = summary.get("blocked_reason_counts") or {}
    if blocked:
        st.dataframe(
            pd.DataFrame(
                [{"reason": key, "count": value} for key, value in sorted(blocked.items())]
            ),
            use_container_width=True,
        )
    else:
        st.info("No blocked reason counts recorded.")
    st.markdown("### Raw Candidate Sample")
    raw_tools = summary.get("raw_candidate_tools") or []
    if raw_tools:
        st.dataframe(pd.DataFrame({"tool_name": raw_tools}), use_container_width=True)
    else:
        st.info("No raw candidates recorded.")
    st.markdown("### Admitted Candidate Tools")
    admitted_tools = summary.get("admitted_candidate_tools") or []
    if admitted_tools:
        st.dataframe(pd.DataFrame({"tool_name": admitted_tools}), use_container_width=True)
    else:
        st.info("No tool passed the main recommendation evidence gate in the latest run.")


def render_reflection_memory(service: ReflectionService) -> None:
    reflections = service.list_reflections()
    memory_events = service.list_memory_events()
    skill_candidates = service.list_skill_candidates()
    c1, c2, c3 = st.columns(3)
    c1.metric("Reflections", len(reflections))
    c2.metric("Memory Events", len(memory_events))
    c3.metric("Skill Candidates", len(skill_candidates))
    st.markdown("### Memory Events")
    if memory_events:
        st.dataframe(pd.DataFrame(memory_events), use_container_width=True)
    else:
        st.info("No reflection memory events found. Run `python scripts/run_agent_trace_smoke.py` first.")
    st.markdown("### Recent Reflections")
    for event in reflections[:20]:
        with st.expander(f"{event.get('created_at', '')[:19]} | {event.get('trace_id', '')}"):
            st.json(event)
    st.markdown("### Skill Candidates")
    if not skill_candidates:
        st.info("No skill candidates generated.")
    for candidate in skill_candidates:
        with st.expander(candidate["title"]):
            st.caption(candidate["path"])
            st.code(candidate["preview"], language="markdown")


def render_evaluation() -> None:
    render_workflow_eval_panel()
    eval_dir = PROJECT_ROOT / "eval"
    candidates = sorted(eval_dir.glob("*summary*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        st.info("No eval summary JSON found.")
        return
    st.markdown("### Eval Summary Browser")
    selected = st.selectbox("Eval summary", [str(path.relative_to(PROJECT_ROOT)) for path in candidates])
    path = PROJECT_ROOT / selected
    text = path.read_text(encoding="utf-8")
    try:
        st.json(json.loads(text))
    except json.JSONDecodeError:
        st.code(text[:5000], language="json")


def render_workflow_eval_panel() -> None:
    st.markdown("### Workflow Eval v0.1")
    summary_path = PROJECT_ROOT / "eval" / "workflow_eval_v0_1_summary.json"
    per_scenario_path = PROJECT_ROOT / "eval" / "workflow_eval_v0_1_per_scenario.tsv"
    failure_queue_path = PROJECT_ROOT / "eval" / "workflow_eval_v0_1_failure_queue.tsv"
    summary = _read_json_file(summary_path)
    if not summary:
        st.info("No workflow eval artifact found. Run `python eval/run_workflow_eval.py` first.")
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Scenarios", summary.get("scenario_count", 0))
    c2.metric("Pass Rate", _format_rate(summary.get("pass_rate")))
    c3.metric("Step Recall", _format_rate(summary.get("required_step_recall")))
    c4.metric("Tool Recall", _format_rate(summary.get("candidate_tool_recall")))
    c5.metric("Boundary Violations", summary.get("evidence_boundary_violation_count", 0))
    c6, c7, c8 = st.columns(3)
    c6.metric("Unsupported Step Rate", _format_rate(summary.get("unsupported_step_rate")))
    c7.metric("Source Context Coverage", _format_rate(summary.get("source_bound_context_coverage")))
    c8.metric("Failures", summary.get("failure_count", 0))
    if summary.get("passed"):
        st.success("Workflow Eval v0.1 passed. This validates plan shape and evidence boundaries, not biological truth.")
    else:
        st.warning("Workflow Eval v0.1 has failures. Check the failure queue before changing workflow behavior.")
    st.caption(summary.get("guardrail", ""))

    per_scenario_rows = _read_tsv_file(per_scenario_path)
    if per_scenario_rows:
        st.markdown("#### Per Scenario")
        st.dataframe(pd.DataFrame(per_scenario_rows), use_container_width=True)
    failure_rows = _read_tsv_file(failure_queue_path)
    if failure_rows:
        with st.expander("Failure Queue", expanded=True):
            st.dataframe(pd.DataFrame(failure_rows), use_container_width=True)


def render_settings() -> None:
    settings = get_settings()
    rows = [
        {"component": "LLM", "field": "api_base", "value": settings.openai_api_base or settings.chat_api_base},
        {"component": "LLM", "field": "model", "value": settings.model_name or settings.extract_model},
        {"component": "LLM", "field": "api_key", "value": _secret_status(settings.openai_api_key or settings.deepseek_api_key)},
        {"component": "Embedding", "field": "api_base", "value": settings.embedding_api_base},
        {"component": "Embedding", "field": "model", "value": settings.embedding_model},
        {"component": "Embedding", "field": "api_key", "value": _secret_status(settings.embedding_api_key)},
        {"component": "Neo4j", "field": "uri", "value": settings.neo4j_uri or ""},
        {"component": "Neo4j", "field": "user", "value": settings.neo4j_user or ""},
        {"component": "Neo4j", "field": "password", "value": _secret_status(settings.neo4j_password)},
        {"component": "Runtime", "field": "offline_llm", "value": str(settings.offline_llm)},
        {"component": "Runtime", "field": "offline_graph_fallback", "value": str(settings.offline_graph_fallback)},
        {"component": "Project", "field": "kg_version", "value": settings.kg_version},
        {"component": "Project", "field": "embedding_version", "value": settings.embedding_version},
        {"component": "Path", "field": "trace_log", "value": "logs/traces.jsonl"},
        {"component": "Path", "field": "memory_db", "value": "SCKG_HOME/state/workbench.sqlite3"},
        {"component": "Path", "field": "reflection_log", "value": "data/memory/reflection_events.jsonl"},
        {"component": "Path", "field": "skill_candidates", "value": "data/skill_candidates/"},
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


def _secret_status(value: Any) -> str:
    return "configured" if value else "missing"


def _read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_tsv_file(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _format_rate(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def render_trace_detail(service: TraceService, trace: Dict[str, Any], *, nested_in_expander: bool = False) -> None:
    st.caption(f"trace_id: {trace.get('trace_id')}")
    stages = service.stage_timings(trace)
    render_stage_table(stages, details_as_expanders=not nested_in_expander)
    if stages:
        chart_data = pd.DataFrame(
            [{"stage": stage["stage"], "elapsed_ms": stage["elapsed_ms"]} for stage in stages]
        ).set_index("stage")
        st.bar_chart(chart_data, horizontal=True)
    st.markdown("### Raw Trace")
    st.json(_compact_trace(trace))


def render_stage_table(stages: List[Dict[str, Any]], *, details_as_expanders: bool = True) -> None:
    if not stages:
        st.info("No stage detail recorded.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "stage": stage["stage"],
                    "status": stage["status"],
                    "elapsed_ms": stage["elapsed_ms"],
                    "method": stage["method"],
                    "provider": stage["provider"],
                    "warnings": "; ".join(map(str, stage["warnings"])),
                    "error": stage["error"],
                }
                for stage in stages
            ]
        ),
        use_container_width=True,
    )
    if not details_as_expanders:
        st.markdown("#### Stage Details")
        for stage in stages:
            st.markdown(f"**{stage['stage']}**")
            st.json(_stage_detail_payload(stage))
        return
    for stage in stages:
        with st.expander(f"{stage['stage']} details"):
            st.json(_stage_detail_payload(stage))


def _stage_detail_payload(stage: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "input_summary": stage["input_summary"],
        "output_summary": stage["output_summary"],
        "warnings": stage["warnings"],
        "error": stage["error"],
    }


def _compact_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    compact = dict(trace)
    compact["stages"] = [
        {
            "stage": stage.get("stage"),
            "elapsed_ms": stage.get("elapsed_ms"),
            "status": stage.get("status"),
            "data": stage.get("data"),
        }
        for stage in compact.get("stages", [])
    ]
    return compact


if __name__ == "__main__":
    main()
