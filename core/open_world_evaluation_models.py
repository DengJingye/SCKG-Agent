from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from core.execution_models import StrictModel


class NaturalQuerySplit(str, Enum):
    DEVELOPMENT = "development"
    EVALUATION = "evaluation"
    HIDDEN = "hidden"


class NaturalQuerySourceKind(str, Enum):
    EXTERNAL_FORUM = "external_forum"
    OFFICIAL_ISSUE = "official_issue"
    REAL_HISTORY = "real_history"
    ADVERSARIAL = "adversarial"


class EvaluationGoldTier(str, Enum):
    ROUTING = "routing_gold"
    ANSWER = "answer_gold"
    SAFETY = "safety_gold"


class ExpectedAction(str, Enum):
    ALLOW = "ALLOW"
    CLARIFY = "CLARIFY"
    BLOCK = "BLOCK"


class ClaimEntailmentStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"
    NOT_APPLICABLE = "not_applicable"


class ClaimAction(str, Enum):
    KEEP = "keep"
    QUALIFY = "qualify"
    REMOVE = "remove"
    SHOW_CONFLICT = "show_conflict"
    NOT_APPLICABLE = "not_applicable"


class NaturalQueryCase(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    query: str = Field(min_length=3)
    split: NaturalQuerySplit
    source_kind: NaturalQuerySourceKind
    source_url: str = ""
    source_title: str = ""
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expected_domain: Literal["GENERAL", "SINGLE_CELL", "UNCERTAIN"]
    expected_intent: str
    expected_task: Optional[str] = None
    expected_key_facts: list[str] = Field(default_factory=list)
    allowed_source_ids: list[str] = Field(default_factory=list)
    answerable: bool = True
    expected_blockers: list[str] = Field(default_factory=list)
    conversation_context: list[dict[str, Any]] = Field(default_factory=list)
    category: str
    gold_status: Literal["adjudicated", "route_only", "needs_adjudication"] = (
        "route_only"
    )
    gold_tiers: list[EvaluationGoldTier] = Field(
        default_factory=lambda: [EvaluationGoldTier.ROUTING]
    )
    expected_action: ExpectedAction = ExpectedAction.ALLOW
    source_context: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def validate_source_and_hidden_boundary(self) -> "NaturalQueryCase":
        if self.source_kind in {
            NaturalQuerySourceKind.EXTERNAL_FORUM,
            NaturalQuerySourceKind.OFFICIAL_ISSUE,
        } and not self.source_url:
            raise ValueError("external natural queries require source_url")
        if self.answerable is False and not self.expected_blockers:
            raise ValueError("unanswerable cases require expected_blockers")
        if EvaluationGoldTier.ANSWER in self.gold_tiers and not (
            self.allowed_source_ids or self.expected_key_facts
        ):
            raise ValueError("answer gold requires source IDs or key facts")
        if self.expected_action != ExpectedAction.ALLOW and not self.expected_blockers:
            raise ValueError("clarify/block gold requires expected blockers")
        return self


class ClaimRecord(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    claim_text: str = Field(min_length=1)
    claim_type: str = "scientific"
    source_span_ids: list[str] = Field(default_factory=list)
    authority: Literal[
        "source_bound",
        "tool_contract",
        "catalog_only",
        "memory",
        "candidate",
        "migration_hypothesis",
        "none",
    ] = "none"
    entailment_status: ClaimEntailmentStatus
    action: ClaimAction
    reasons: list[str] = Field(default_factory=list)


class GroundedAnswerAuditV2(StrictModel):
    schema_version: Literal["grounded-answer-audit-v2"] = "grounded-answer-audit-v2"
    passed: bool
    scientific_answer: bool = True
    claims: list[ClaimRecord] = Field(default_factory=list)
    cited_references: list[int] = Field(default_factory=list)
    invalid_citations: list[int] = Field(default_factory=list)
    citation_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    supported_claim_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    unsupported_claim_count: int = Field(default=0, ge=0)
    execution_claim_violation: bool = False
    governance_violation_count: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)
    verifier: Literal["deterministic_v2", "external_judge", "human_review"] = (
        "deterministic_v2"
    )


class ClaimRecordV3(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    claim_text: str = Field(min_length=1)
    claim_type: str = "scientific"
    source_span_ids: list[str] = Field(default_factory=list)
    authority: Literal[
        "source_bound",
        "tool_contract",
        "catalog_only",
        "memory",
        "candidate",
        "migration_hypothesis",
        "model_knowledge_unverified",
        "none",
    ] = "none"
    lexical_support: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_mapping: Literal["valid", "missing", "invalid", "not_applicable"] = (
        "missing"
    )
    scope_match: Literal["match", "partial", "mismatch", "unknown"] = "unknown"
    numeric_scope_match: Literal[
        "match", "partial", "mismatch", "not_applicable", "unknown"
    ] = "not_applicable"
    semantic_review_status: Literal[
        "not_run", "supported", "partial", "unsupported", "conflicting"
    ] = "not_run"
    governance_action: Literal[
        "keep", "qualify", "remove", "show_conflict", "label_unverified"
    ] = "remove"
    reasons: list[str] = Field(default_factory=list)


class GroundedAnswerAuditV3(StrictModel):
    schema_version: Literal["grounded-answer-audit-v3"] = "grounded-answer-audit-v3"
    passed: bool
    scientific_answer: bool = True
    claims: list[ClaimRecordV3] = Field(default_factory=list)
    verified_claims: list[ClaimRecordV3] = Field(default_factory=list)
    unverified_model_knowledge_claims: list[ClaimRecordV3] = Field(
        default_factory=list
    )
    cited_references: list[int] = Field(default_factory=list)
    invalid_citations: list[int] = Field(default_factory=list)
    citation_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    structurally_supported_claim_rate: float = Field(
        default=0.0, ge=0.0, le=1.0
    )
    semantic_claim_correctness: Optional[float] = Field(
        default=None, ge=0.0, le=1.0
    )
    unsupported_claim_count: int = Field(default=0, ge=0)
    execution_claim_violation: bool = False
    governance_violation_count: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)
    verifier: Literal[
        "deterministic_structure_v3", "external_judge", "human_review"
    ] = "deterministic_structure_v3"


class OpenWorldCaseResult(StrictModel):
    case_id: str
    baseline: Literal[
        "deepseek_only",
        "kg_rag_only",
        "deepseek_bm25",
        "deepseek_kg_hybrid",
        "deepseek_kg_hybrid_contract",
    ]
    repetition: int = Field(default=0, ge=0)
    status: Literal["completed", "blocked", "not_run", "failed"]
    observed_domain: str = ""
    observed_intent: str = ""
    observed_task: str = ""
    answerable_decision: Optional[bool] = None
    observed_action: str = ""
    domain_correct: Optional[bool] = None
    intent_correct: Optional[bool] = None
    action_correct: Optional[bool] = None
    clarification_correct: Optional[bool] = None
    route_correct: Optional[bool] = None
    task_correct: Optional[bool] = None
    blocker_correct: Optional[bool] = None
    top_k_format_correct: Optional[bool] = None
    workflow_smoke_passed: Optional[bool] = None
    retrieval_recall_at_10: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    retrieval_mrr: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_span_hit: Optional[bool] = None
    claim_audit: Optional[GroundedAnswerAuditV2 | GroundedAnswerAuditV3] = None
    research_tool_call_count: int = Field(default=0, ge=0)
    research_tool_success_count: int = Field(default=0, ge=0)
    llm_tool_loop_completed: Optional[bool] = None
    unauthorized_execution_request_count: int = Field(default=0, ge=0)
    candidate_evidence_leakage_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_cost_usd: Optional[float] = Field(default=None, ge=0.0)
    response_hash: str = ""
    failure_stage: str = ""
    failures: list[str] = Field(default_factory=list)
    artifact_ref: str = ""


class OpenWorldAblationSummary(StrictModel):
    schema_version: Literal["sckg-open-world-ablation-v1"] = (
        "sckg-open-world-ablation-v1"
    )
    evaluation_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    corpus_digest: str
    split: NaturalQuerySplit
    case_count: int = Field(ge=0)
    requested_provider_calls: int = Field(default=0, ge=0)
    completed_provider_calls: int = Field(default=0, ge=0)
    provider_call_budget: int = Field(default=200, ge=0)
    baseline_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    paired_deltas_vs_deepseek_only: dict[str, dict[str, float]] = Field(
        default_factory=dict
    )
    failed_cases: list[dict[str, Any]] = Field(default_factory=list)
    hard_gate_passed: bool = False
    gate_failures: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
