from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import Field

from core.execution_models import StrictModel


class AgentMode(str, Enum):
    ASK = "ASK"
    PLAN = "PLAN"
    RUN = "RUN"


class DomainKind(str, Enum):
    GENERAL = "GENERAL"
    SINGLE_CELL = "SINGLE_CELL"
    UNCERTAIN = "UNCERTAIN"


class DomainDecision(StrictModel):
    domain: DomainKind
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["local_rule", "semantic_parser", "conversation_context"]
    reason: str
    needs_clarification: bool = False


class SemanticRouteDecision(StrictModel):
    domain: DomainKind
    intent: str
    task: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_clarification: bool = False
    source: Literal["local_rule", "semantic_parser", "conversation_context"]


class ActionSafetyDecision(StrictModel):
    verdict: Literal["ALLOW", "CLARIFY", "BLOCK"] = "ALLOW"
    reason_codes: list[str] = Field(default_factory=list)
    execution_request_allowed: bool = False
    source: Literal["deterministic_policy"] = "deterministic_policy"


class AnswerabilityDecision(StrictModel):
    verdict: Literal[
        "ANSWER_VERIFIED",
        "ANSWER_DUAL_LAYER",
        "CLARIFY",
        "BLOCK",
    ]
    reason_codes: list[str] = Field(default_factory=list)
    verified_context_available: bool = False
    unverified_model_knowledge_allowed: bool = False


class ResearchToolCall(StrictModel):
    """A bounded, read-only tool request proposed by the semantic LLM."""

    call_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    tool_name: Literal[
        "search_catalog",
        "search_evidence",
        "get_tool_contract",
        "compile_workflow",
        "discover_capabilities",
    ]
    query: str = ""
    canonical_task: str = ""
    tool_names: list[str] = Field(default_factory=list, max_length=5)
    claim_types: list[str] = Field(default_factory=list, max_length=4)
    top_k: int = Field(default=8, ge=1, le=12)
    reason: str = ""


class ResearchToolPlan(StrictModel):
    """The model may propose tools; deterministic code validates and executes them."""

    source: Literal["semantic_parser", "deterministic_fallback"]
    calls: list[ResearchToolCall] = Field(default_factory=list, max_length=4)
    answer_strategy: Literal[
        "direct",
        "grounded",
        "dual_layer",
        "workflow",
        "clarify",
    ] = "direct"
    rationale: str = ""


class ResearchToolObservation(StrictModel):
    call_id: str
    tool_name: str
    status: Literal["completed", "blocked", "failed", "skipped"]
    result_count: int = Field(default=0, ge=0)
    source_bound_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    payload: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ConversationTaskState(StrictModel):
    """Small cross-turn state; never contains matrices or full transcripts."""

    confirmed_domain: DomainKind = DomainKind.UNCERTAIN
    confirmed_task: str = ""
    referenced_tools: list[str] = Field(default_factory=list)
    last_answer_claims: list[str] = Field(default_factory=list)
    last_plan_id: Optional[str] = None
    last_action_bundle_ids: list[str] = Field(default_factory=list)
    state_epoch: int = Field(default=0, ge=0)
    runtime_build_id: str = ""


class ResearchAgentRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    conversation_id: str = Field(
        default="local-conversation",
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    user_id: str = Field(default="local-research-user", pattern=r"^[A-Za-z0-9_.-]+$")
    query: str = Field(min_length=1)
    mode: Optional[AgentMode] = None
    artifact_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    data_grant_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    execution_approval_id: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    requested_tool: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExecutionHandoff(StrictModel):
    status: Literal["not_requested", "waiting", "ready", "blocked", "completed"]
    target_view: Literal["runs_results"] = "runs_results"
    artifact_id: Optional[str] = None
    profile_id: Optional[str] = None
    plan_id: Optional[str] = None
    router_route: Optional[str] = None
    environment_id: Optional[str] = None
    run_id: Optional[str] = None
    decision_id: Optional[str] = None
    package_id: Optional[str] = None
    approval_required: bool = False
    execution_request_count: int = Field(default=0, ge=0)
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ResearchWorkspaceHandoff(StrictModel):
    status: Literal["not_applicable", "available", "blocked"] = "not_applicable"
    target_view: Literal["data_preview"] = "data_preview"
    task_family: str = ""
    tool_name: Optional[str] = None
    plan_id: Optional[str] = None
    notebook_strategy: Literal["none", "fixed_shadow", "capability_renderer"] = "none"
    stepwise_preview_available: bool = False
    pack_id: Optional[str] = None
    pack_version: Optional[str] = None
    target_representations: list[str] = Field(default_factory=list)
    preferred_method_ids: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    handoff_id: Optional[str] = None
    origin_trace_id: Optional[str] = None
    parent_request_id: Optional[str] = None
    original_plan_id: Optional[str] = None


class ResearchAgentState(StrictModel):
    request_id: str
    conversation_id: str
    user_id: str
    mode: AgentMode
    domain: DomainKind = DomainKind.UNCERTAIN
    intent: str
    task: str = ""
    modality: str = "scRNA-seq"
    artifact_id: Optional[str] = None
    profile_id: Optional[str] = None
    retrieval_route: str = ""
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    action_bundle_ids: list[str] = Field(default_factory=list)
    plan_id: Optional[str] = None
    router_route: Optional[str] = None
    approval_status: Optional[str] = None
    environment_status: Optional[str] = None
    run_id: Optional[str] = None
    decision_id: Optional[str] = None
    package_id: Optional[str] = None
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    trace_ids: list[str] = Field(default_factory=list)
    canonical_trace_id: str
    conversation_state: ConversationTaskState = Field(
        default_factory=ConversationTaskState
    )


class ResearchAgentResponse(StrictModel):
    state: ResearchAgentState
    canonical_trace_id: str
    user_query: str
    status: Literal["ANSWERED", "READY", "WAITING", "BLOCKED", "FAILED"]
    direct_answer: str
    applicability: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    candidate_tools: list[str] = Field(default_factory=list)
    tool_candidates: list[dict[str, Any]] = Field(default_factory=list)
    algorithm_cards: list[dict[str, Any]] = Field(default_factory=list)
    migration_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    workflow_plan: Optional[dict[str, Any]] = None
    workflow_code_bundle: Optional[dict[str, Any]] = None
    evidence_context_pack: dict[str, Any] = Field(default_factory=dict)
    parent_result: dict[str, Any] = Field(default_factory=dict)
    execution_handoff: ExecutionHandoff
    workspace_handoff: ResearchWorkspaceHandoff = Field(
        default_factory=ResearchWorkspaceHandoff
    )
    trace: Optional[dict[str, Any]] = None
    runtime_mode: str = "degraded_local_fallback"
    claim_audit: dict[str, Any] = Field(default_factory=dict)
    runtime_build: dict[str, Any] = Field(default_factory=dict)
    semantic_route: Optional[SemanticRouteDecision] = None
    action_safety: ActionSafetyDecision = Field(default_factory=ActionSafetyDecision)
    answerability: AnswerabilityDecision = Field(
        default_factory=lambda: AnswerabilityDecision(
            verdict="CLARIFY",
            reason_codes=["answerability_not_evaluated"],
        )
    )
    verified_claims: list[dict[str, Any]] = Field(default_factory=list)
    unverified_model_knowledge_claims: list[dict[str, Any]] = Field(
        default_factory=list
    )
