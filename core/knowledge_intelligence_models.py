from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeIntelligenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class CanonicalTaskDefinition(KnowledgeIntelligenceModel):
    task_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    label: str = Field(min_length=1)
    aliases: List[str] = Field(default_factory=list)
    stage_order: int = Field(ge=1)
    parent_task_id: Optional[str] = None
    preceding_task_ids: List[str] = Field(default_factory=list)
    expected_input_types: List[str] = Field(default_factory=list)
    expected_output_types: List[str] = Field(default_factory=list)

    @field_validator(
        "aliases",
        "preceding_task_ids",
        "expected_input_types",
        "expected_output_types",
    )
    @classmethod
    def normalize_lists(cls, values: List[str]) -> List[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


class SourceDocumentRecord(KnowledgeIntelligenceModel):
    schema_version: str = "source-document-v2"
    source_id: str = Field(min_length=1)
    canonical_title: str = Field(min_length=1)
    doi: str = ""
    source_url: str = ""
    source_type: str = ""
    source_status: Literal[
        "source_text_available",
        "metadata_only",
        "extraction_failed",
        "quarantined",
    ]
    validation_status: str = ""
    validation_issue: str = ""
    local_text_path: str = ""
    local_pdf_path: str = ""
    content_hash: str = ""
    text_chars: int = Field(default=0, ge=0)
    referring_record_ids: List[str] = Field(default_factory=list)
    referring_tool_names: List[str] = Field(default_factory=list)
    evidence_kinds: List[str] = Field(default_factory=list)
    source_spans_available: bool = False
    retrieval_only: bool = True

    @field_validator(
        "referring_record_ids", "referring_tool_names", "evidence_kinds"
    )
    @classmethod
    def normalize_references(cls, values: List[str]) -> List[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @model_validator(mode="after")
    def enforce_quarantine_boundary(self) -> "SourceDocumentRecord":
        if self.source_status == "quarantined" and self.retrieval_only is False:
            raise ValueError("quarantined sources cannot leave the retrieval-only boundary")
        if self.source_status == "source_text_available" and not self.content_hash:
            raise ValueError("available source text requires a content hash")
        return self


class HybridRetrievalRequest(KnowledgeIntelligenceModel):
    query: str = Field(min_length=1)
    tool_names: List[str] = Field(default_factory=list)
    canonical_tasks: List[str] = Field(default_factory=list)
    claim_types: List[str] = Field(default_factory=list)
    source_types: List[str] = Field(default_factory=list)
    top_k: int = Field(default=12, ge=1, le=100)
    include_catalog: bool = True
    enable_sparse: bool = True
    enable_dense: bool = True
    nonblocking_dense: bool = False
    use_kg: bool = True
    use_governance_rerank: bool = True
    use_contract_gate: bool = False


class HybridRetrievalHit(KnowledgeIntelligenceModel):
    chunk_id: str
    source_id: str
    tool_name: str = ""
    tool_names: List[str] = Field(default_factory=list)
    canonical_task: str = ""
    claim_type: str = "general"
    source_span: str = ""
    title: str = ""
    text: str = ""
    score: float
    sparse_rank: Optional[int] = None
    dense_rank: Optional[int] = None
    governance_status: str = "retrieval_only"
    source_bound: bool = False
    recommendation_eligible: bool = False


class ChatStageTiming(KnowledgeIntelligenceModel):
    stage: Literal[
        "intent",
        "kg_filter",
        "bm25",
        "dense_encode",
        "fusion",
        "parent_planning",
        "answer_compose",
    ]
    elapsed_ms: float = Field(ge=0.0)
    status: Literal["completed", "skipped", "fallback", "failed"] = "completed"
    detail: str = ""


class AdaptiveRetrievalDecision(KnowledgeIntelligenceModel):
    route: Literal[
        "bm25",
        "kg_bm25",
        "kg_hybrid",
        "kg_hybrid_contract",
    ]
    enable_dense: bool
    reason: str = Field(min_length=1)
    escalated: bool = False
    source_bound_hits_before_escalation: int = Field(default=0, ge=0)
    deterministic: bool = True


class EmbeddingWorkerStatus(KnowledgeIntelligenceModel):
    state: Literal["not_started", "warming", "ready", "failed", "stopped"]
    model: str = ""
    model_revision: str = ""
    source_digest: str = ""
    started_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    failure_reason: str = ""


class HybridRetrievalResult(KnowledgeIntelligenceModel):
    schema_version: str = "hybrid-retrieval-v2"
    query: str
    mode: Literal["bm25", "dense", "bm25_dense", "kg_bm25", "kg_dense", "kg_bm25_dense"]
    hits: List[HybridRetrievalHit] = Field(default_factory=list)
    latency_ms: float = Field(ge=0.0)
    index_build_id: str = ""
    embedding_model: str = ""
    dense_status: str = "not_requested"
    pipeline: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    governance_leakage_count: int = Field(default=0, ge=0)
    stage_timings: List[ChatStageTiming] = Field(default_factory=list)
    scientific_evidence: Optional[Dict[str, Any]] = None


class RetrievalCoverageReport(KnowledgeIntelligenceModel):
    schema_version: str = "retrieval-coverage-v2"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    build_id: str
    chunk_count: int = Field(ge=0)
    catalog_chunk_count: int = Field(ge=0)
    source_document_count: int = Field(ge=0)
    source_bound_tool_count: int = Field(ge=0)
    qualified_tool_count: int = Field(ge=0)
    qualified_tool_source_coverage_rate: float = Field(ge=0.0, le=1.0)
    core_tool_source_coverage_rate: float = Field(ge=0.0, le=1.0)
    chunks_by_claim_type: Dict[str, int] = Field(default_factory=dict)
    chunks_by_task: Dict[str, int] = Field(default_factory=dict)
    missing_qualified_tools: List[str] = Field(default_factory=list)
    missing_core_tools: List[str] = Field(default_factory=list)
    embedding_model: str = ""
    dense_vector_count: int = Field(default=0, ge=0)
    quality_flags: List[str] = Field(default_factory=list)


class RetrievalEvalCase(KnowledgeIntelligenceModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    split: Literal["development", "evaluation"]
    category: Literal[
        "tool_discovery",
        "input_requirement",
        "parameter",
        "output",
        "failure_mode",
        "metric",
        "workflow_relation",
        "ambiguous",
        "hard_negative",
    ]
    query: str = Field(min_length=1)
    expected_tool_names: List[str] = Field(default_factory=list)
    relevant_chunk_ids: List[str] = Field(default_factory=list)
    relevant_source_ids: List[str] = Field(default_factory=list)
    expected_canonical_tasks: List[str] = Field(default_factory=list)
    must_block: bool = False
    notes: str = ""


class RetrievalEvalSummary(KnowledgeIntelligenceModel):
    schema_version: str = "retrieval-eval-v2"
    status: Literal["passed", "failed", "not_run"]
    case_count: int = Field(ge=0)
    recall_at_10: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    precision_at_10: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    mrr: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_span_hit_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    false_support_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    parameter_legality_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    governance_leakage_count: int = Field(default=0, ge=0)
    latency_p50_ms: Optional[float] = Field(default=None, ge=0.0)
    latency_p95_ms: Optional[float] = Field(default=None, ge=0.0)
    metric_authority: str = "deterministic_id_based"
    thresholds: Dict[str, float] = Field(default_factory=dict)
    failures: List[str] = Field(default_factory=list)
    ragas_status: str = "not_run"
    ragas_reason: str = "optional evaluator not configured"


class CanonicalKnowledgeSnapshot(KnowledgeIntelligenceModel):
    schema_version: str = "canonical-knowledge-v1"
    snapshot_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_digest: str
    catalog_graph_manifest: str
    decision_graph_manifest: str
    source_document_manifest: str
    evidence_index_manifest: str
    task_count: int = Field(ge=0)
    catalog_tool_count: int = Field(ge=0)
    canonical_tool_node_count: int = Field(default=0, ge=0)
    qualified_tool_count: int = Field(ge=0)
    source_document_count: int = Field(ge=0)
    evidence_chunk_count: int = Field(ge=0)
    projection_drift_count: int = Field(ge=0)
    junk_task_count: int = Field(ge=0)
    unsupported_capability_edge_count: int = Field(ge=0)
    qualified_tool_governed_path_rate: float = Field(ge=0.0, le=1.0)
    integrity_passed: bool
    warnings: List[str] = Field(default_factory=list)


class MemoryRetrievalContext(KnowledgeIntelligenceModel):
    user_id: str
    explicit_preferences: Dict[str, Any] = Field(default_factory=dict)
    confirmed_inferences: Dict[str, Any] = Field(default_factory=dict)
    episodic_runs: List[Dict[str, Any]] = Field(default_factory=list)
    reflection_lessons: List[Dict[str, Any]] = Field(default_factory=list)
    skill_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    can_affect_scientific_authority: bool = False
