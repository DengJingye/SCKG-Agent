"""Strict preview-only models for Scientific Knowledge Studio v1."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProposalStatus = Literal["candidate_proposal"]
ValidationStatus = Literal["VALID", "NEEDS_REVIEW", "INVALID"]
IdentityResolutionStatus = Literal[
    "EXACT_EXISTING_IDENTITY",
    "POSSIBLE_EXISTING_IDENTITY",
    "NEW_CANDIDATE",
    "AMBIGUOUS",
    "UNRESOLVED",
]
SourceIdentityStatus = Literal[
    "SOURCE_IDENTITY_EXACT",
    "SOURCE_IDENTITY_POSSIBLE_MATCH",
    "SOURCE_IDENTITY_NEW",
    "SOURCE_IDENTITY_AMBIGUOUS",
]
DimensionStatus = Literal["EXPLICIT", "DOCUMENT_CONTEXT", "UNSPECIFIED", "AMBIGUOUS"]


class StrictStudioModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRevisionProposal(StrictStudioModel):
    schema_version: Literal["sckg-source-revision-proposal-v1"] = "sckg-source-revision-proposal-v1"
    proposal_status: ProposalStatus = "candidate_proposal"
    proposal_id: str = Field(pattern=r"^proposal:source-revision:[a-f0-9]{16}$")
    source_work_candidate_id: str = Field(min_length=1)
    source_revision_candidate_id: str = Field(min_length=1)
    identity_status: SourceIdentityStatus
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    doi: str | None = None
    source_type: Literal["local_scientific_pdf"] = "local_scientific_pdf"
    original_filename: str = Field(min_length=1)
    file_size: int = Field(ge=1)
    pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1)
    ingestion_run_id: str = Field(min_length=1)
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    created_at: datetime


class DocumentSegment(StrictStudioModel):
    schema_version: Literal["sckg-document-segment-v1"] = "sckg-document-segment-v1"
    segment_id: str = Field(pattern=r"^segment:[a-f0-9]{32}$")
    page_number: int = Field(ge=1)
    segment_index: int = Field(ge=0)
    section: str = "document"
    exact_text: str = Field(min_length=1, max_length=2400)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)


class ParseGap(StrictStudioModel):
    schema_version: Literal["sckg-parse-gap-v1"] = "sckg-parse-gap-v1"
    page: int = Field(ge=1)
    reason: str = Field(min_length=1)
    parser: str = Field(min_length=1)


class EvidenceSpanProposal(StrictStudioModel):
    schema_version: Literal["sckg-evidence-span-proposal-v1"] = "sckg-evidence-span-proposal-v1"
    proposal_status: ProposalStatus = "candidate_proposal"
    proposal_id: str = Field(pattern=r"^proposal:evidence-span:[a-f0-9]{24}$")
    source_revision_proposal_id: str = Field(pattern=r"^proposal:source-revision:")
    source_pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_number: int = Field(ge=1)
    segment_id: str = Field(pattern=r"^segment:")
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_text: str = Field(min_length=1, max_length=1000)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_type: Literal["scientific_text_span"] = "scientific_text_span"
    extraction_method: str = Field(min_length=1)
    validation_status: ValidationStatus
    validation_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_offsets(self) -> "EvidenceSpanProposal":
        if self.end_offset <= self.start_offset:
            raise ValueError("EvidenceSpanProposal end_offset must exceed start_offset")
        if self.end_offset - self.start_offset != len(self.exact_text):
            raise ValueError("EvidenceSpanProposal offsets must bound exact_text")
        return self


class EntityProposal(StrictStudioModel):
    schema_version: Literal["sckg-entity-proposal-v1"] = "sckg-entity-proposal-v1"
    proposal_status: ProposalStatus = "candidate_proposal"
    entity_proposal_id: str = Field(pattern=r"^proposal:entity:[a-f0-9]{24}$")
    entity_type: str = Field(min_length=1)
    raw_label: str = Field(min_length=1)
    normalized_label: str = Field(min_length=1)
    description: str = ""
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    identity_resolution_status: IdentityResolutionStatus
    existing_candidate_ids: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus
    validation_reasons: list[str] = Field(default_factory=list)
    version: str | None = None


class RelationProposal(StrictStudioModel):
    schema_version: Literal["sckg-relation-proposal-v1"] = "sckg-relation-proposal-v1"
    proposal_status: ProposalStatus = "candidate_proposal"
    relation_proposal_id: str = Field(pattern=r"^proposal:relation:[a-f0-9]{24}$")
    source_entity_ref: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    target_entity_ref: str = Field(min_length=1)
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    origin: Literal["PDF_EXTRACTED", "INFERRED_FROM_EXISTING_KG"]
    validation_status: ValidationStatus
    validation_reasons: list[str] = Field(default_factory=list)


class ScopeDimensionProposal(StrictStudioModel):
    value: str | list[str] | None = None
    status: DimensionStatus

    @model_validator(mode="after")
    def unspecified_is_not_a_value(self) -> "ScopeDimensionProposal":
        if self.status == "UNSPECIFIED" and self.value not in (None, "", []):
            raise ValueError("UNSPECIFIED scope dimension cannot imply a universal value")
        if self.status in {"EXPLICIT", "DOCUMENT_CONTEXT"} and self.value in (None, "", []):
            raise ValueError(f"{self.status} scope dimension requires a value")
        return self


class ScopeProposal(StrictStudioModel):
    schema_version: Literal["sckg-scope-proposal-v1"] = "sckg-scope-proposal-v1"
    proposal_status: ProposalStatus = "candidate_proposal"
    scope_proposal_id: str = Field(pattern=r"^proposal:scope:[a-f0-9]{24}$")
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    dimensions: dict[
        Literal[
            "modality",
            "organism",
            "assay",
            "observation_unit",
            "study_design",
            "representation_constraint",
            "method_operator_version",
            "flavor",
            "evaluation_context",
        ],
        ScopeDimensionProposal,
    ]
    validation_status: ValidationStatus
    validation_reasons: list[str] = Field(default_factory=list)


class AtomicClaimProposal(StrictStudioModel):
    schema_version: Literal["sckg-atomic-claim-proposal-v1"] = "sckg-atomic-claim-proposal-v1"
    proposal_status: ProposalStatus = "candidate_proposal"
    knowledge_status: ProposalStatus = "candidate_proposal"
    claim_proposal_id: str = Field(pattern=r"^proposal:claim:[a-f0-9]{24}$")
    claim_text: str = Field(min_length=1, max_length=1200)
    claim_type: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    object_or_requirement: str = Field(min_length=1)
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    scope_proposal_id: str = Field(pattern=r"^proposal:scope:")
    version_conditions: list[str] = Field(default_factory=list)
    flavor_conditions: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus
    validation_reasons: list[str] = Field(default_factory=list)


class CandidateDiff(StrictStudioModel):
    schema_version: Literal["sckg-candidate-diff-v1"] = "sckg-candidate-diff-v1"
    wording: Literal["If accepted, proposed delta would be…"] = "If accepted, proposed delta would be…"
    current_nodes: int = Field(ge=0)
    current_edges: int = Field(ge=0)
    current_candidate_claims: int = Field(ge=0)
    entity_proposals: int = Field(ge=0)
    relation_proposals: int = Field(ge=0)
    atomic_claim_proposals: int = Field(ge=0)
    evidence_span_proposals: int = Field(ge=0)
    new_candidates: int = Field(ge=0)
    exact_existing_identity_matches: int = Field(ge=0)
    possible_matches: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    valid: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    invalid: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_identity_arithmetic(self) -> "CandidateDiff":
        total = (
            self.new_candidates
            + self.exact_existing_identity_matches
            + self.possible_matches
            + self.ambiguous
            + self.unresolved
        )
        if total != self.entity_proposals:
            raise ValueError("CandidateDiff identity buckets must sum to entity_proposals")
        return self


class ProposalGraphNode(StrictStudioModel):
    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    visual_class: Literal[
        "EXISTING_KG",
        "NEW_PROPOSAL",
        "AMBIGUOUS_PROPOSAL",
        "INVALID_PROPOSAL",
        "EVIDENCE_SPAN",
        "SOURCE",
    ]
    detail: dict[str, Any] = Field(default_factory=dict)


class ProposalGraphEdge(StrictStudioModel):
    source: str
    target: str
    relation: str
    origin: Literal["PDF_EXTRACTED", "INFERRED_FROM_EXISTING_KG", "PROPOSAL_BINDING"]


class ProposalGraph(StrictStudioModel):
    schema_version: Literal["sckg-proposal-graph-v1"] = "sckg-proposal-graph-v1"
    nodes: list[ProposalGraphNode]
    edges: list[ProposalGraphEdge]
    bounded_to_run: Literal[True] = True

    @model_validator(mode="after")
    def validate_endpoints(self) -> "ProposalGraph":
        ids = {node.node_id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("ProposalGraph node IDs must be unique")
        if any(edge.source not in ids or edge.target not in ids for edge in self.edges):
            raise ValueError("ProposalGraph edge references missing node")
        return self


class RunStageRecord(StrictStudioModel):
    stage: Literal[
        "UPLOAD",
        "SOURCE_IDENTITY",
        "PARSE",
        "EVIDENCE_PROPOSAL",
        "SEMANTIC_EXTRACTION",
        "IDENTITY_RESOLUTION",
        "VALIDATION",
        "PREVIEW",
    ]
    timestamp: datetime
    status: Literal["WAITING", "RUNNING", "DONE", "WARNING", "BLOCKED"]
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    reason: str = ""
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class LLMRunMetadata(StrictStudioModel):
    status: Literal["NOT_RUN", "COMPLETED", "FAILED"]
    provider: str
    model: str
    api_base_category: str
    temperature: float = Field(ge=0, le=0.3)
    prompt_version: str
    schema_version: str
    retry_count: int = Field(ge=0, le=2)
    response_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class KnowledgeStudioRunManifest(StrictStudioModel):
    schema_version: Literal["sckg-knowledge-studio-run-v1"] = "sckg-knowledge-studio-run-v1"
    run_id: str = Field(pattern=r"^knowledge-studio:[A-Za-z0-9_.:-]+$")
    proposal_status: ProposalStatus = "candidate_proposal"
    created_at: datetime
    original_filename: str
    pdf_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1)
    parsed_pages: int = Field(ge=0)
    parse_gap_count: int = Field(ge=0)
    stages: list[RunStageRecord]
    llm: LLMRunMetadata
    artifact_hashes: dict[str, str]
    scientific_kg_mutated: Literal[False] = False
    production_rag_indexed: Literal[False] = False
    planner_consumed: Literal[False] = False
    review_decision_created: Literal[False] = False
    canonical_promotion: Literal["none"] = "none"
    trusted_knowledge_created: Literal[False] = False

    @model_validator(mode="after")
    def validate_stage_set(self) -> "KnowledgeStudioRunManifest":
        expected = [
            "UPLOAD",
            "SOURCE_IDENTITY",
            "PARSE",
            "EVIDENCE_PROPOSAL",
            "SEMANTIC_EXTRACTION",
            "IDENTITY_RESOLUTION",
            "VALIDATION",
            "PREVIEW",
        ]
        if [row.stage for row in self.stages] != expected:
            raise ValueError("KnowledgeStudioRunManifest requires the ordered eight-stage trace")
        return self
