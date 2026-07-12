from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Sequence

from core.evidence_policy import is_main_recommendation_evidence
from engine.evidence_rag_pipeline import build_controlled_rag_context
from engine.workflow_recommender import build_minimal_workflow_recommendation


DEFAULT_WORKFLOW_CANDIDATE_TOOLS = [
    "Scanpy",
    "Seurat",
    "Scrublet",
    "DoubletFinder",
    "SoupX",
    "Harmony",
    "scvi-tools",
    "CellTypist",
    "SingleR",
    "cell2location",
    "scVelo",
    "CellRank",
    "MOFA2",
    "SeuratDisk",
    "zellkonverter",
    "sceasy",
    "tradeSeq",
]

DEFAULT_WORKFLOW_QUERY = (
    "I have multi-sample 10x PBMC scRNA-seq data and want QC, doublet detection, "
    "batch integration, cell type annotation, and optional trajectory analysis."
)


def build_workflow_decision_response(
    *,
    query: str,
    constraints: Dict[str, Any],
    candidate_tools: Sequence[str] | None = None,
    rag_fn: Callable[..., Dict[str, Any]] = build_controlled_rag_context,
    max_snippets_per_step: int = 4,
) -> Dict[str, Any]:
    """Build an auditable workflow decision payload for UI/API use.

    This is intentionally plan-first: generated workflow steps and RAG snippets
    explain the decision context, but cannot become formal recommendation
    evidence or mutate ranking by themselves.
    """

    tools = list(candidate_tools or DEFAULT_WORKFLOW_CANDIDATE_TOOLS)
    normalized_constraints = normalize_constraints(query=query, constraints=constraints)
    workflow = build_minimal_workflow_recommendation(normalized_constraints, candidate_tools=tools)
    step_rows: List[Dict[str, Any]] = []
    all_snippets: List[Dict[str, Any]] = []
    for step in workflow.steps:
        step_tool_names = step.candidate_tools or tools
        step_constraints = {
            **normalized_constraints,
            "query": query,
            "task": step.task,
            "workflow_step": step.name,
            "output_goal": step.produced_output[-1] if step.produced_output else normalized_constraints.get("output_goal", ""),
        }
        rag_context = rag_fn(
            constraints=step_constraints,
            tool_names=step_tool_names,
            max_snippets=max(max_snippets_per_step * 8, max_snippets_per_step),
        )
        snippets = select_display_snippets(rag_context.get("snippets") or [], limit=max_snippets_per_step)
        all_snippets.extend(snippets)
        step_rows.append(
            {
                "order": step.order,
                "name": step.name,
                "task": step.task,
                "required_input": step.required_input,
                "produced_output": step.produced_output,
                "candidate_tools": step.candidate_tools,
                "status": "plan_only_evidence_limited",
                "rag_mode": rag_context.get("mode", ""),
                "retrieval_pipeline": rag_context.get("pipeline", []),
                "snippet_count": len(snippets),
                "source_bound_snippet_count": sum(1 for snippet in snippets if is_source_bound_snippet(snippet)),
                "matched_tools": sorted({snippet.get("tool_name", "") for snippet in snippets if snippet.get("tool_name")}),
                "snippets": snippets,
                "missing_evidence": list(step.evidence.missing_evidence),
            }
        )

    boundary_violations = workflow_evidence_boundary_violations(workflow)
    source_bound_snippets = [snippet for snippet in all_snippets if is_source_bound_snippet(snippet)]
    response = {
        "response_type": "workflow_decision_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "constraints": normalized_constraints,
        "candidate_tools": tools,
        "workflow_name": workflow.name,
        "architecture": "centralized workflow decision sandbox; target bounded centralized agent",
        "authority": {
            "workflow_steps": "plan-only decision support",
            "rag_snippets": "retrieval context only",
            "formal_evidence": "only reviewed TSV/promotion flow can support strong recommendation claims",
            "memory": "not used for scientific authority",
        },
        "metrics": {
            "workflow_steps": len(step_rows),
            "candidate_tool_count": len(tools),
            "retrieval_snippets": len(all_snippets),
            "source_bound_retrieval_snippets": len(source_bound_snippets),
            "evidence_boundary_violation_count": len(boundary_violations),
            "formal_main_recommendation_evidence_count": 0,
            "completeness": round(workflow.completeness, 6),
        },
        "workflow_steps": step_rows,
        "compatibility_warnings": workflow.compatibility_warnings,
        "boundary_violations": boundary_violations,
        "guardrail": (
            "This output is an auditable workflow plan. It does not promote formal evidence, "
            "does not write Neo4j, and does not change MCDM ranking."
        ),
        "next_actions": next_actions_for_response(step_rows, boundary_violations),
        "markdown_report": "",
    }
    response["markdown_report"] = render_workflow_decision_markdown(response)
    return response


def normalize_constraints(*, query: str, constraints: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(constraints)
    normalized["query"] = query
    normalized.setdefault("task", infer_task_from_query(query))
    normalized.setdefault("modality", "scRNA-seq")
    normalized.setdefault("data_object", "AnnData / SeuratObject")
    normalized.setdefault("output_goal", "auditable workflow decision report")
    normalized.setdefault("strictness", "evidence_limited")
    return normalized


def infer_task_from_query(query: str) -> str:
    text = query.casefold()
    if any(term in text for term in ("workflow", "plan", "pipeline", "multi-sample", "batch integration")):
        return "Workflow Planning"
    if any(term in text for term in ("doublet", "multiplet")):
        return "Doublet Detection"
    if any(term in text for term in ("ambient", "soup", "contamination")):
        return "Ambient RNA Removal"
    if any(term in text for term in ("spatial", "deconvolution")):
        return "Spatial Deconvolution"
    if any(term in text for term in ("velocity", "spliced", "unspliced")):
        return "RNA Velocity"
    if any(term in text for term in ("multiome", "multi-ome", "atac", "cite-seq", "protein")):
        return "Multiome Integration"
    if any(term in text for term in ("convert", "conversion", "h5ad", "seuratobject")):
        return "Workflow Compatibility"
    if any(term in text for term in ("pseudotime", "trajectory", "lineage")):
        return "Trajectory Inference"
    if any(term in text for term in ("differential", "marker genes", "de genes")):
        return "Differential Expression"
    if any(term in text for term in ("annotation", "cell type", "label")):
        return "Cell Type Annotation"
    return "Workflow Planning"


def compact_rag_snippets(snippets: Sequence[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for snippet in snippets[:limit]:
        compact.append(
            {
                "tool_name": snippet.get("tool_name", ""),
                "source_kind": snippet.get("source_kind", ""),
                "title": snippet.get("title", ""),
                "source_span": snippet.get("source_span", ""),
                "claim_span": snippet.get("claim_span", ""),
                "claim_boundary": snippet.get("claim_boundary", ""),
                "relevance_score": snippet.get("relevance_score", 0),
                "record_id": snippet.get("record_id", ""),
                "chunk_id": snippet.get("chunk_id", ""),
            }
        )
    return compact


def select_display_snippets(snippets: Sequence[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for prefer_source_bound in (True, False):
        for snippet in snippets:
            if is_source_bound_snippet(snippet) != prefer_source_bound:
                continue
            snippet_id = str(snippet.get("chunk_id") or snippet.get("record_id") or repr(snippet))
            if snippet_id in seen:
                continue
            selected.append(snippet)
            seen.add(snippet_id)
            if len(selected) >= limit:
                return compact_rag_snippets(selected, limit=limit)
    return compact_rag_snippets(selected, limit=limit)


def is_source_bound_snippet(snippet: Dict[str, Any]) -> bool:
    source_kind = str(snippet.get("source_kind", ""))
    return source_kind.startswith("source_") or source_kind == "document"


def workflow_evidence_boundary_violations(workflow: Any) -> List[str]:
    violations: List[str] = []
    all_evidence = list(workflow.evidence.items)
    for step in workflow.steps:
        all_evidence.extend(step.evidence.items)
    for evidence in all_evidence:
        if is_main_recommendation_evidence(evidence):
            violations.append(f"{evidence.evidence_id}: internal_template_used_as_main_recommendation_evidence")
        if "recommendation" in evidence.use_for:
            violations.append(f"{evidence.evidence_id}: internal_template_has_recommendation_use")
    return violations


def next_actions_for_response(
    step_rows: Sequence[Dict[str, Any]],
    boundary_violations: Sequence[str],
) -> List[str]:
    actions: List[str] = []
    if boundary_violations:
        actions.append("Fix evidence boundary violations before treating any output as recommendation support.")
    if any(step.get("snippet_count", 0) == 0 for step in step_rows):
        actions.append("Add source chunks for steps with zero retrieval snippets.")
    if any(step.get("source_bound_snippet_count", 0) == 0 for step in step_rows):
        actions.append("Improve source-bound coverage for steps currently backed only by formal/fallback snippets.")
    actions.append("Use the workflow plan as decision support; keep formal recommendation wording evidence-limited.")
    return actions


def render_workflow_decision_markdown(response: Dict[str, Any]) -> str:
    lines = [
        "# scKG Workflow Decision Report",
        "",
        f"Query: {response.get('query', '')}",
        "",
        "## Boundary",
        "",
        response.get("guardrail", ""),
        "",
        "## Metrics",
        "",
    ]
    for key, value in (response.get("metrics") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Workflow", ""])
    for step in response.get("workflow_steps") or []:
        lines.extend(
            [
                f"### {step.get('order')}. {step.get('name')}",
                "",
                f"- Task: {step.get('task', '')}",
                f"- Candidate tools: {', '.join(step.get('candidate_tools') or []) or 'none'}",
                f"- Produced output: {', '.join(step.get('produced_output') or []) or 'none'}",
                f"- Retrieval snippets: {step.get('snippet_count', 0)}",
                f"- Source-bound snippets: {step.get('source_bound_snippet_count', 0)}",
                f"- Status: {step.get('status', '')}",
                "",
            ]
        )
    lines.extend(["## Next Actions", ""])
    for action in response.get("next_actions") or []:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)
