from __future__ import annotations

from typing import Any, Dict

from agent.workflow import (
    generate_report_node,
    hard_constraint_node,
    mcdm_scoring_node,
    migration_reasoning_node,
    parse_intent_node,
    route_based_on_candidates,
)
from core.trace_context import TraceContext


AGENT_STAGE_ORDER = [
    "trigger",
    "gateway",
    "intent_parse",
    "kg_hard_filter",
    "evidence_retrieval",
    "mcdm_rank",
    "migration_or_workflow_plan",
    "report_generate",
    "audit",
    "reflect",
]


def run_sckg_workflow_traced(state: Dict[str, Any], trace: TraceContext) -> Dict[str, Any]:
    """Run the existing centralized workflow while recording stable stage traces."""

    trace.record_stage(
        "trigger",
        method="streamlit_or_cli_trigger",
        input_summary={"query_length": len(state.get("user_query", ""))},
        output_summary={"accepted": True},
        elapsed_ms=0.0,
    )
    trace.record_stage(
        "gateway",
        method="centralized_parent_agent_gateway",
        input_summary={
            "has_conversation_context": bool(state.get("conversation_context")),
            "has_project_memory": bool(state.get("project_memory")),
            "has_uploaded_context": bool(state.get("uploaded_context")),
        },
        output_summary={
            "architecture": "bounded_centralized_parent_agent",
            "subagent_execution": "disabled_v1",
        },
        warnings=[
            "Memory/upload context is operational context only and cannot promote evidence.",
        ],
        elapsed_ms=0.0,
    )

    with trace.stage_timer(
        "intent_parse",
        method="agent.workflow.parse_intent_node",
        provider="llm_or_deterministic_fallback",
        input_summary={"query_length": len(state.get("user_query", ""))},
    ) as payload:
        state = _merge_state(state, parse_intent_node(state))
        payload["output_summary"] = {
            "task": _constraint_value(state, "task"),
            "modality": _constraint_value(state, "modality"),
            "strictness": _constraint_value(state, "strictness"),
        }

    with trace.stage_timer(
        "kg_hard_filter",
        method="agent.workflow.hard_constraint_node",
        provider="neo4j_or_offline_graph",
        input_summary={"constraints": _compact_dict(state.get("extracted_constraints", {}))},
    ) as payload:
        state = _merge_state(state, hard_constraint_node(state))
        kg_diagnostics = state.get("kg_diagnostics") or {}
        payload["output_summary"] = {
            "provider": kg_diagnostics.get("provider"),
            "raw_candidate_count": kg_diagnostics.get("raw_candidate_count", 0),
            "candidate_tool_count": len(state.get("candidate_tools") or []),
            "tool_candidate_count": len(state.get("tool_candidates") or []),
            "retrieval_result_count": len(state.get("retrieval_results") or []),
            "admitted_candidate_tools": kg_diagnostics.get("admitted_candidate_tools", []),
            "raw_candidate_tools": kg_diagnostics.get("raw_candidate_tools", [])[:20],
            "blocked_reason_counts": kg_diagnostics.get("blocked_reason_counts", {}),
            "candidate_diagnostics": kg_diagnostics.get("candidate_diagnostics", [])[:20],
            "error": kg_diagnostics.get("error", ""),
        }

    trace.record_stage(
        "evidence_retrieval",
        method="formal_evidence_and_hybrid_context_pack",
        provider="neo4j_tsv_jsonl",
        input_summary={"candidate_tool_count": len(state.get("candidate_tools") or [])},
        output_summary={
            "retrieval_result_count": len(state.get("retrieval_results") or []),
            "retrieval_context_boundary": "retrieval_only_until_gate_passes",
        },
        warnings=[
            "RAG chunks and memory cannot directly change MCDM rank.",
        ],
        elapsed_ms=0.0,
    )

    route = route_based_on_candidates(state)
    if route == "has_candidates":
        with trace.stage_timer(
            "mcdm_rank",
            method="agent.workflow.mcdm_scoring_node",
            provider="evidence_guarded_mcdm",
            input_summary={"candidate_tool_count": len(state.get("candidate_tools") or [])},
        ) as payload:
            state = _merge_state(state, mcdm_scoring_node(state))
            payload["output_summary"] = {
                "ranked_tool_count": len(state.get("scored_tools") or []),
                "recommended_tools": [
                    item.get("tool_name")
                    for item in (state.get("scored_tools") or [])[:5]
                    if isinstance(item, dict)
                ],
            }
        trace.record_stage(
            "migration_or_workflow_plan",
            method="workflow_plan_deferred_to_report_node",
            provider="central_parent_agent",
            output_summary={"route": "ranked_tools", "migration_skipped": True},
            elapsed_ms=0.0,
        )
    else:
        trace.record_stage(
            "mcdm_rank",
            method="agent.workflow.mcdm_scoring_node",
            output_summary={"route": "no_candidates", "mcdm_skipped": True},
            elapsed_ms=0.0,
        )
        with trace.stage_timer(
            "migration_or_workflow_plan",
            method="agent.workflow.migration_reasoning_node",
            provider="profile_or_embedding_migration",
            input_summary={"constraints": _compact_dict(state.get("extracted_constraints", {}))},
        ) as payload:
            state = _merge_state(state, migration_reasoning_node(state))
            payload["output_summary"] = {
                "migration_path_count": len(state.get("migration_paths") or []),
                "retrieval_result_count": len(state.get("retrieval_results") or []),
            }

    with trace.stage_timer(
        "report_generate",
        method="agent.workflow.generate_report_node",
        provider="llm_or_structured_renderer",
        input_summary={
            "ranked_tool_count": len(state.get("scored_tools") or []),
            "migration_path_count": len(state.get("migration_paths") or []),
        },
    ) as payload:
        state = _merge_state(state, generate_report_node(state))
        payload["output_summary"] = {
            "report_chars": len(state.get("final_report") or ""),
            "workflow_count": len(state.get("workflow_recommendations") or []),
        }

    audit = state.get("hallucination_audit") or {}
    trace.record_stage(
        "audit",
        method="engine.semantic_hallucination_auditor.audit_report",
        provider="deterministic_evidence_gate",
        output_summary={
            "passed": audit.get("passed"),
            "claim_count": audit.get("claim_count"),
            "unsupported_claim_count": audit.get("unsupported_claim_count"),
            "severity_counts": audit.get("severity_counts") or {},
        },
        warnings=audit.get("warnings") or [],
        elapsed_ms=0.0,
    )
    state["trace_id"] = trace.trace_id
    return state


def _merge_state(state: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(state)
    merged.update(update or {})
    return merged


def _constraint_value(state: Dict[str, Any], key: str) -> Any:
    constraints = state.get("extracted_constraints") or {}
    if isinstance(constraints, dict):
        return constraints.get(key, "Unknown")
    return getattr(constraints, key, "Unknown")


def _compact_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_state_dict"):
        value = value.to_state_dict()
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        return {}
    keep = ["task", "task_family", "modality", "platform", "species", "strictness", "clarification_state"]
    return {key: value.get(key) for key in keep if key in value}
