from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.evidence_policy import (
    audit_evidence,
    evidence_guardrail_warnings,
    is_main_recommendation_evidence,
)
from core.models import (
    ContextEvidenceItem,
    Evidence,
    EvidenceBundle,
    EvidenceContextPack,
    MigrationPath,
    ScoredTool,
    ToolCandidate,
    WorkflowRecommendation,
)
from engine.formal_evidence_rag import build_formal_rag_context


def build_evidence_context_pack(
    *,
    user_query: str = "",
    constraints: Dict[str, Any],
    recommendation_type: str,
    scored_tools: Iterable[ScoredTool] = (),
    tool_candidates: Iterable[ToolCandidate] = (),
    workflow: Optional[WorkflowRecommendation] = None,
    migration_paths: Iterable[MigrationPath] = (),
    evidence_bundle: Optional[EvidenceBundle] = None,
    missing_components: Iterable[str] = (),
    blocked_tools: Iterable[str] = (),
    hallucination_audit: Optional[Dict[str, Any]] = None,
) -> EvidenceContextPack:
    """Build the minimal Hybrid KG-RAG context visible to reports/LLMs.

    This function is deliberately read-only: it does not rank tools, mutate
    evidence, promote candidates, or write Neo4j. It only separates already
    available evidence into recommendation-grade, retrieval-only, exploratory
    migration, and blocked/guardrail layers.
    """

    scored_tool_list = list(scored_tools)
    candidate_list = list(tool_candidates)
    migration_list = list(migration_paths)
    bundle = evidence_bundle or _combine_visible_evidence(
        scored_tools=scored_tool_list,
        tool_candidates=candidate_list,
        workflow=workflow,
        migration_paths=migration_list,
    )
    missing = sorted(set(list(bundle.missing_evidence) + list(missing_components)))

    trusted_items = _trusted_recommendation_items(scored_tool_list, workflow)
    retrieval_items = _retrieval_items(
        bundle=bundle,
        scored_tools=scored_tool_list,
        tool_candidates=candidate_list,
        workflow=workflow,
        migration_paths=migration_list,
    )
    accepted_migrations = [
        path for path in migration_list
        if _migration_is_accepted_exploratory(path)
    ]
    blocked_migrations = [
        path for path in migration_list
        if not _migration_is_accepted_exploratory(path)
    ]
    retrieval_tool_names = _all_tool_names(
        scored_tools=scored_tool_list,
        tool_candidates=candidate_list,
        workflow=workflow,
        migration_paths=accepted_migrations,
    )
    formal_rag_context = build_formal_rag_context(
        constraints=constraints,
        tool_names=retrieval_tool_names,
    )

    return EvidenceContextPack(
        user_query=user_query,
        parsed_constraints=dict(constraints),
        recommendation_type=_normalize_recommendation_type(recommendation_type),
        trusted_recommendation_context={
            "context_role": "trusted_recommendation",
            "description": (
                "Trusted-core publication/benchmark evidence allowed to support "
                "primary recommendation wording and ranking explanations."
            ),
            "can_rank": True,
            "ranked_tools": [
                _tool_context(tool, trusted_only=True)
                for tool in scored_tool_list
            ],
            "workflow": _workflow_context(workflow, trusted_only=True),
            "evidence_items": [item.model_dump(mode="json") for item in trusted_items],
        },
        retrieval_context={
            "context_role": "retrieval",
            "description": (
                "RAG/documentation/provenance context for explanation only. "
                "These items cannot change MCDM score or promote a tool."
            ),
            "can_rank": False,
            "recommendation_grade": False,
            "evidence_items": [item.model_dump(mode="json") for item in retrieval_items],
            "formal_rag_context": formal_rag_context,
        },
        migration_context={
            "context_role": "migration",
            "description": (
                "Accepted exploratory MigrationHypothesis items only. They are "
                "innovation routes, not formal recommendations."
            ),
            "can_rank": False,
            "recommendation_grade": False,
            "accepted_decisions": ["accept_exploratory"],
            "paths": [_migration_context(path) for path in accepted_migrations],
            "excluded_paths": [_blocked_migration_context(path) for path in blocked_migrations],
        },
        blocked_context={
            "context_role": "blocked",
            "blocked_tools": sorted(set(blocked_tools)),
            "pending_constraints": list(constraints.get("pending_constraints", []) or []),
            "clarification_questions": list(constraints.get("clarification_questions", []) or []),
            "needs_human_clarification": bool(
                constraints.get("needs_human_clarification", False)
            ),
            "clarification_state": constraints.get("clarification_state", "needs_clarification"),
            "guardrail_warnings": evidence_guardrail_warnings(bundle),
            "auditor_risks": _audit_risks(hallucination_audit),
            "blocked_migration_paths": [
                _blocked_migration_context(path) for path in blocked_migrations
            ],
        },
        missing_evidence=missing,
        prompt_policy=_prompt_policy(),
    )


def _combine_visible_evidence(
    *,
    scored_tools: List[ScoredTool],
    tool_candidates: List[ToolCandidate],
    workflow: Optional[WorkflowRecommendation],
    migration_paths: List[MigrationPath],
) -> EvidenceBundle:
    items: List[Evidence] = []
    missing: List[str] = []
    for candidate in tool_candidates:
        items.extend(candidate.evidence.items)
        missing.extend(candidate.evidence.missing_evidence)
    for tool in scored_tools:
        items.extend(tool.evidence.items)
        missing.extend(tool.evidence.missing_evidence)
    for path in migration_paths:
        items.extend(path.evidence.items)
        missing.extend(path.evidence.missing_evidence)
    if workflow:
        items.extend(workflow.evidence.items)
        missing.extend(workflow.evidence.missing_evidence)
        for step in workflow.steps:
            items.extend(step.evidence.items)
            missing.extend(step.evidence.missing_evidence)
    deduped = {item.evidence_id: item for item in items}
    return EvidenceBundle(
        items=list(deduped.values()),
        missing_evidence=sorted(set(missing)),
    )


def _trusted_recommendation_items(
    scored_tools: List[ScoredTool],
    workflow: Optional[WorkflowRecommendation],
) -> List[ContextEvidenceItem]:
    items: List[ContextEvidenceItem] = []
    for tool in scored_tools:
        for evidence in tool.evidence.items:
            if is_main_recommendation_evidence(evidence):
                items.append(_context_evidence_item(evidence, "trusted_recommendation", tool.tool_name))
    if workflow:
        for step in workflow.steps:
            for evidence in step.evidence.items:
                if is_main_recommendation_evidence(evidence):
                    items.append(_context_evidence_item(evidence, "trusted_recommendation", step.name))
        for evidence in workflow.evidence.items:
            if is_main_recommendation_evidence(evidence):
                items.append(_context_evidence_item(evidence, "trusted_recommendation", workflow.name))
    return _dedupe_context_items(items)


def _retrieval_items(
    *,
    bundle: EvidenceBundle,
    scored_tools: List[ScoredTool],
    tool_candidates: List[ToolCandidate],
    workflow: Optional[WorkflowRecommendation],
    migration_paths: List[MigrationPath],
) -> List[ContextEvidenceItem]:
    tool_by_evidence = _tool_name_by_evidence(
        scored_tools=scored_tools,
        tool_candidates=tool_candidates,
        workflow=workflow,
        migration_paths=migration_paths,
    )
    items = []
    for evidence in bundle.items:
        items.append(
            _context_evidence_item(
                evidence,
                "retrieval",
                tool_by_evidence.get(evidence.evidence_id, ""),
            )
        )
    return _dedupe_context_items(items)


def _tool_name_by_evidence(
    *,
    scored_tools: List[ScoredTool],
    tool_candidates: List[ToolCandidate],
    workflow: Optional[WorkflowRecommendation],
    migration_paths: List[MigrationPath],
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for candidate in tool_candidates:
        for evidence in candidate.evidence.items:
            mapping.setdefault(evidence.evidence_id, candidate.tool_name)
    for tool in scored_tools:
        for evidence in tool.evidence.items:
            mapping.setdefault(evidence.evidence_id, tool.tool_name)
    for path in migration_paths:
        for evidence in path.evidence.items:
            mapping.setdefault(evidence.evidence_id, path.tool_name)
    if workflow:
        for evidence in workflow.evidence.items:
            mapping.setdefault(evidence.evidence_id, workflow.name)
        for step in workflow.steps:
            for evidence in step.evidence.items:
                mapping.setdefault(evidence.evidence_id, step.name)
    return mapping


def _all_tool_names(
    *,
    scored_tools: List[ScoredTool],
    tool_candidates: List[ToolCandidate],
    workflow: Optional[WorkflowRecommendation],
    migration_paths: List[MigrationPath],
) -> List[str]:
    names: List[str] = []
    for tool in scored_tools:
        names.append(tool.tool_name)
    for candidate in tool_candidates:
        names.append(candidate.tool_name)
    for path in migration_paths:
        names.append(path.tool_name)
    if workflow:
        names.append(workflow.name)
        for step in workflow.steps:
            names.extend(step.candidate_tools)
    deduped: List[str] = []
    seen = set()
    for name in names:
        key = "".join(ch for ch in (name or "").lower() if ch.isalnum())
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(name)
    return deduped


def _context_evidence_item(
    evidence: Evidence,
    context_role: str,
    tool_name: str,
) -> ContextEvidenceItem:
    main_evidence = is_main_recommendation_evidence(evidence)
    return ContextEvidenceItem(
        context_role=context_role,
        tool_name=tool_name,
        evidence_id=evidence.evidence_id,
        source_type=evidence.source_type,
        source_title=evidence.source_title,
        source_url=evidence.source_url,
        metric_name=evidence.metric_name,
        metric_value=evidence.metric_value,
        metric_unit=evidence.metric_unit,
        benchmark_type=evidence.benchmark_type,
        dataset_scope=evidence.dataset_scope,
        evidence_strength=evidence.evidence_strength,
        confidence=evidence.confidence,
        trust_level=evidence.trust_level,
        graph_layer=evidence.graph_layer,
        review_status=evidence.review_status,
        use_for=list(evidence.use_for),
        source_is_main_recommendation_evidence=main_evidence,
        context_can_rank=context_role == "trusted_recommendation" and main_evidence,
        explanation_only=context_role != "trusted_recommendation",
        claim_boundary=(
            "May support recommendation/ranking wording."
            if context_role == "trusted_recommendation" and main_evidence
            else "Explanation/provenance only; cannot promote or rank tools."
        ),
    )


def _dedupe_context_items(items: List[ContextEvidenceItem]) -> List[ContextEvidenceItem]:
    deduped: Dict[str, ContextEvidenceItem] = {}
    for item in items:
        deduped.setdefault(item.evidence_id, item)
    return list(deduped.values())


def _tool_context(tool: ScoredTool, trusted_only: bool) -> Dict[str, Any]:
    evidence_items = [
        evidence for evidence in tool.evidence.items
        if not trusted_only or is_main_recommendation_evidence(evidence)
    ]
    audit = audit_evidence(EvidenceBundle(items=evidence_items, missing_evidence=tool.evidence.missing_evidence))
    return {
        "tool_name": tool.tool_name,
        "rank": tool.rank,
        "mcdm_score": tool.score,
        "recommendation_confidence": tool.recommendation_confidence,
        "missing_evidence": list(tool.evidence.missing_evidence),
        "trusted_evidence_count": len(audit.main_recommendation_evidence),
        "evidence_ids": [evidence.evidence_id for evidence in evidence_items],
        "evidence_breakdown": dict(tool.evidence_breakdown),
    }


def _workflow_context(
    workflow: Optional[WorkflowRecommendation],
    trusted_only: bool,
) -> Optional[Dict[str, Any]]:
    if not workflow:
        return None
    steps = []
    for step in workflow.steps:
        evidence_items = [
            evidence for evidence in step.evidence.items
            if not trusted_only or is_main_recommendation_evidence(evidence)
        ]
        steps.append(
            {
                "name": step.name,
                "order": step.order,
                "task": step.task,
                "candidate_tools": list(step.candidate_tools),
                "evidence_ids": [evidence.evidence_id for evidence in evidence_items],
                "missing_evidence": list(step.evidence.missing_evidence),
            }
        )
    return {
        "name": workflow.name,
        "input_signature": list(workflow.input_signature),
        "output_signature": list(workflow.output_signature),
        "compatibility_warnings": list(workflow.compatibility_warnings),
        "steps": steps,
    }


def _migration_is_accepted_exploratory(path: MigrationPath) -> bool:
    decision = (path.reviewer_decision or "").strip().lower()
    return decision == "accept_exploratory"


def _migration_context(path: MigrationPath) -> Dict[str, Any]:
    return {
        "source_tool": path.tool_name,
        "source_task": path.source_task,
        "target_task": path.target_task,
        "migration_plausibility_score": path.score,
        "vector_similarity": path.cos_sim,
        "graph_jaccard": path.graph_jaccard,
        "io_compatibility": path.io_compatibility,
        "evidence_support": path.evidence_support,
        "novelty_relevance": path.novelty_relevance,
        "risk_penalty": path.risk_penalty,
        "risk_level": path.risk_level,
        "reviewer_decision": path.reviewer_decision,
        "transferable_mechanism": path.transferable_mechanism or path.features,
        "compatibility_gaps": list(path.compatibility_gaps),
        "limitations": list(path.limitations),
        "claim_boundary": path.claim_boundary,
        "recommendation_grade": False,
        "can_rank": False,
        "required_output_wording": "exploratory hypothesis",
    }


def _blocked_migration_context(path: MigrationPath) -> Dict[str, Any]:
    return {
        "source_tool": path.tool_name,
        "target_task": path.target_task,
        "reviewer_decision": path.reviewer_decision or "not_accept_exploratory",
        "risk_level": path.risk_level,
        "compatibility_gaps": list(path.compatibility_gaps),
        "blocked_reason": (
            "Migration path is not human-reviewed as accept_exploratory "
            "or carries unresolved compatibility risk."
        ),
    }


def _audit_risks(hallucination_audit: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not hallucination_audit:
        return []
    issues = hallucination_audit.get("issues", []) or []
    risks = []
    for issue in issues:
        severity = str(issue.get("severity", "unknown"))
        if severity in {"critical", "high", "medium"}:
            risks.append(
                {
                    "severity": severity,
                    "claim": issue.get("claim", ""),
                    "issue_type": issue.get("issue_type", ""),
                    "explanation": issue.get("explanation", ""),
                }
            )
    return risks


def _prompt_policy() -> Dict[str, List[str]]:
    return {
        "allowed": [
            "Explain tools using trusted_recommendation_context evidence.",
            "Cite DOI, source_url, source_title, metric_name, or claim span when present.",
            "Use retrieval_context only for explanation, provenance, caveats, or missing-evidence discussion.",
            "Describe migration_context as exploratory hypotheses with compatibility gaps and validation plans.",
            "Mention missing evidence instead of filling gaps from general model knowledge.",
        ],
        "forbidden": [
            "Do not access unfiltered candidate pools or evidence_candidates directly.",
            "Do not let retrieval_context change MCDM scores or ranking.",
            "Do not promote docs, GitHub, candidate, or experimental evidence into trusted evidence.",
            "Do not call migration outputs best tools, direct replacements, empirically proven, or benchmark-backed.",
            "Do not invent benchmark ranks, metric values, thresholds, workflow transitions, or literature claims.",
            "Do not recommend blocked tools or omit missing prerequisite constraints.",
        ],
        "required_caveats": [
            "State when audit was not run or when evidence is missing.",
            "State that MigrationHypothesis outputs require downstream validation.",
            "State benchmark/publication/protocol gaps when present.",
        ],
    }


def _normalize_recommendation_type(value: str) -> str:
    allowed = {"ranked_tools", "workflow", "migration", "evidence_chain", "none"}
    return value if value in allowed else "none"
