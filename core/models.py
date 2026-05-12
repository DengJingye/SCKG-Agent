from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator, model_validator


UNKNOWN = "Unknown"

EvidenceSourceType = Literal[
    "paper",
    "github",
    "benchmark",
    "docs",
    "human_review",
    "llm_extracted",
    "derived",
    "missing",
]
EvidenceStrength = Literal["strong", "medium", "weak", "exploratory", "missing"]
ReviewStatus = Literal["unreviewed", "auto_checked", "human_reviewed", "rejected"]
TrustLevel = Literal["verified", "source_based", "model_extracted", "inferred", "missing"]
GraphLayer = Literal["trusted_core", "review_needed", "experimental"]
RecommendationKind = Literal["direct_tool", "workflow", "migration"]
PredictionRecommendationType = Literal[
    "ranked_tools",
    "workflow",
    "migration",
    "evidence_chain",
    "none",
]
RiskLevel = Literal["low", "medium", "high", "exploratory", "unknown"]
ExecutionStatus = Literal["ok", "partial", "error"]
PredictionExecutionMode = Literal[
    "deterministic",
    "agent",
    "pure_llm",
    "evidence_gate",
    "evidence_gate_auditor",
    "full_kg_pipeline",
]


class ScientificBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class Evidence(ScientificBaseModel):
    """Auditable evidence object. Recommendations must bind to Evidence."""

    evidence_id: str
    source_type: EvidenceSourceType
    source_url: Optional[str] = None
    source_title: str = UNKNOWN
    metric_name: str = UNKNOWN
    metric_value: Optional[Any] = None
    metric_unit: str = UNKNOWN
    benchmark_type: str = ""
    dataset_scope: str = UNKNOWN
    evidence_strength: EvidenceStrength = "weak"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    trust_level: TrustLevel = "model_extracted"
    graph_layer: GraphLayer = "review_needed"
    use_for: List[str] = Field(default_factory=lambda: ["retrieval"])
    extraction_method: str = UNKNOWN
    extraction_model: str = UNKNOWN
    extraction_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    review_status: ReviewStatus = "unreviewed"
    kg_version: str = "v0.1"
    human_review_decision: str = ""
    canonical_scope: str = ""
    evidence_category: str = ""
    recommendation_eligible: Optional[bool] = None
    authority_tier: str = ""
    audit_support_level: str = ""

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, "", UNKNOWN):
            return None
        # Use pydantic's URL parser for validation while storing a plain string.
        TypeAdapter(HttpUrl).validate_python(value)
        return value

    @property
    def is_missing(self) -> bool:
        return self.source_type == "missing" or self.evidence_strength == "missing"

    @property
    def can_support_recommendation(self) -> bool:
        if self.recommendation_eligible is False:
            return False
        return (
            self.trust_level in {"verified", "source_based"}
            and self.graph_layer in {"trusted_core", "review_needed"}
            and self.review_status != "rejected"
            and "recommendation" in self.use_for
        )

    @property
    def is_experimental(self) -> bool:
        return self.graph_layer == "experimental" or self.trust_level in {"model_extracted", "inferred"}


class EvidenceBundle(ScientificBaseModel):
    items: List[Evidence] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        total = len(self.items) + len(self.missing_evidence)
        if total == 0:
            return 0.0
        present = len([item for item in self.items if not item.is_missing])
        return present / total

    @property
    def recommendation_coverage(self) -> float:
        total = len(self.items) + len(self.missing_evidence)
        if total == 0:
            return 0.0
        present = len([item for item in self.items if item.can_support_recommendation])
        return present / total

    @property
    def experimental_count(self) -> int:
        return len([item for item in self.items if item.is_experimental])


class ToolCandidate(ScientificBaseModel):
    tool_name: str
    description: str = UNKNOWN
    github_stars: int = 0
    language: str = UNKNOWN
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    feasibility_reasons: List[str] = Field(default_factory=list)


class ScoredTool(ScientificBaseModel):
    tool_name: str
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    evidence: EvidenceBundle
    evidence_breakdown: Dict[str, Any] = Field(default_factory=dict)
    recommendation_confidence: Literal["high", "medium", "low"] = "low"

    @model_validator(mode="after")
    def require_evidence(self) -> "ScoredTool":
        if not self.evidence.items and not self.evidence.missing_evidence:
            raise ValueError("ScoredTool requires explicit evidence or missing evidence")
        return self


class RetrievalResult(ScientificBaseModel):
    query: str
    result_type: Literal["hard_constraint", "mcdm", "migration", "workflow"]
    tool_candidates: List[ToolCandidate] = Field(default_factory=list)
    scored_tools: List[ScoredTool] = Field(default_factory=list)
    evidence_coverage: float = 0.0
    warnings: List[str] = Field(default_factory=list)


class WorkflowStep(ScientificBaseModel):
    name: str
    order: int = Field(ge=1)
    task: str
    required_input: List[str] = Field(default_factory=list)
    produced_output: List[str] = Field(default_factory=list)
    candidate_tools: List[str] = Field(default_factory=list)
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    is_optional: bool = False


class WorkflowRecommendation(ScientificBaseModel):
    name: str
    steps: List[WorkflowStep] = Field(default_factory=list)
    input_signature: List[str] = Field(default_factory=list)
    output_signature: List[str] = Field(default_factory=list)
    compatibility_warnings: List[str] = Field(default_factory=list)
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)

    @property
    def completeness(self) -> float:
        if not self.steps:
            return 0.0
        supported = [
            step for step in self.steps
            if step.candidate_tools or step.evidence.items
        ]
        return len(supported) / len(self.steps)


class MigrationPath(ScientificBaseModel):
    tool_name: str
    score: float = Field(ge=0.0, le=1.0)
    cos_sim: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    features: str = ""
    risk_level: RiskLevel = "exploratory"
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    limitations: List[str] = Field(default_factory=list)
    source_task: str = UNKNOWN
    target_task: str = UNKNOWN
    transferable_mechanism: str = ""
    graph_jaccard: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    io_compatibility: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_support: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    novelty_relevance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    risk_penalty: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    compatibility_gaps: List[str] = Field(default_factory=list)
    claim_boundary: str = (
        "Exploratory MigrationHypothesis only; not a formal recommendation "
        "and not benchmark-backed performance evidence."
    )


class Recommendation(ScientificBaseModel):
    kind: RecommendationKind
    title: str
    rationale: str
    evidence: EvidenceBundle
    tool: Optional[ScoredTool] = None
    workflow: Optional[WorkflowRecommendation] = None
    migration: Optional[MigrationPath] = None
    risk_level: RiskLevel = "unknown"

    @model_validator(mode="after")
    def require_bound_payload(self) -> "Recommendation":
        bound = [self.tool is not None, self.workflow is not None, self.migration is not None]
        if sum(bound) != 1:
            raise ValueError("Recommendation must bind exactly one tool, workflow, or migration")
        if not self.evidence.items and not self.evidence.missing_evidence:
            raise ValueError("Recommendation requires explicit evidence or missing evidence")
        return self


class DecisionReport(ScientificBaseModel):
    user_query: str
    constraints: Dict[str, Any]
    recommendations: List[Recommendation] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    uncertainty: List[str] = Field(default_factory=list)
    final_report: str = ""

    @property
    def evidence_coverage(self) -> float:
        if not self.recommendations:
            return 0.0
        return sum(rec.evidence.coverage for rec in self.recommendations) / len(self.recommendations)


class PredictionRecord(ScientificBaseModel):
    """Stable machine-readable output for one gold query run."""

    id: str
    query_id: str
    user_query: str
    parsed_constraints: Dict[str, Any]
    candidate_tools: List[Dict[str, Any]] = Field(default_factory=list)
    scored_tools: List[Dict[str, Any]] = Field(default_factory=list)
    migration_paths: List[Dict[str, Any]] = Field(default_factory=list)
    recommendation_type: PredictionRecommendationType = "none"
    recommendation_kind: PredictionRecommendationType = "none"
    evidence_bundle: EvidenceBundle = Field(default_factory=EvidenceBundle)
    workflow_recommendation: Optional[WorkflowRecommendation] = None
    final_report: str = ""
    missing_components: List[str] = Field(default_factory=list)
    clarification_needed: bool = True
    execution_status: ExecutionStatus = "partial"
    execution_mode: PredictionExecutionMode = "deterministic"
    candidate_tool_count: int = Field(default=0, ge=0)
    scored_tool_count: int = Field(default=0, ge=0)
    migration_path_count: int = Field(default=0, ge=0)
    output_truncated: bool = False
    recommended_tools: List[str] = Field(default_factory=list)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    workflow_steps: List[str] = Field(default_factory=list)
    claim_count: int = Field(default=0, ge=0)
    unsupported_claims: int = Field(default=0, ge=0)
    semantic_hallucination_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    hallucination_audit: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_eval_fields(self) -> "PredictionRecord":
        if self.id != self.query_id:
            raise ValueError("PredictionRecord id and query_id must match")
        if self.recommendation_kind != self.recommendation_type:
            raise ValueError("recommendation_kind must mirror recommendation_type")
        return self


def missing_evidence(metric_name: str, kg_version: str = "v0.1") -> Evidence:
    return Evidence(
        evidence_id=f"missing:{metric_name}",
        source_type="missing",
        metric_name=metric_name,
        evidence_strength="missing",
        confidence=0.0,
        trust_level="missing",
        graph_layer="experimental",
        use_for=[],
        extraction_method="system_missing_evidence_marker",
        review_status="auto_checked",
        kg_version=kg_version,
    )


def derived_evidence(
    evidence_id: str,
    metric_name: str,
    metric_value: Any,
    extraction_method: str,
    source_title: str,
    confidence: float = 0.7,
    kg_version: str = "v0.1",
    dataset_scope: str = UNKNOWN,
    trust_level: TrustLevel = "inferred",
    graph_layer: GraphLayer = "experimental",
    evidence_strength: EvidenceStrength = "exploratory",
    use_for: Optional[List[str]] = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type="derived",
        source_title=source_title,
        metric_name=metric_name,
        metric_value=metric_value,
        dataset_scope=dataset_scope,
        evidence_strength=evidence_strength,
        confidence=confidence,
        trust_level=trust_level,
        graph_layer=graph_layer,
        use_for=use_for or ["retrieval"],
        extraction_method=extraction_method,
        review_status="auto_checked",
        kg_version=kg_version,
    )


def github_evidence(
    tool_name: str,
    metric_name: str,
    metric_value: Any,
    source_url: Optional[str] = None,
    kg_version: str = "v0.1",
) -> Evidence:
    return Evidence(
        evidence_id=f"github:{tool_name}:{metric_name}",
        source_type="github",
        source_url=source_url,
        source_title=f"GitHub metadata for {tool_name}",
        metric_name=metric_name,
        metric_value=metric_value,
        dataset_scope="global_repository",
        evidence_strength="medium",
        confidence=0.8,
        trust_level="source_based",
        graph_layer="trusted_core",
        use_for=["retrieval", "ranking", "recommendation"],
        extraction_method="github_crawler.py",
        review_status="auto_checked",
        kg_version=kg_version,
    )
