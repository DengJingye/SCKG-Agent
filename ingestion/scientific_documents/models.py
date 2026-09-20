from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlockType(StrEnum):
    DOCUMENT_METADATA = "DOCUMENT_METADATA"
    TOC = "TOC"
    HEADER_FOOTER = "HEADER_FOOTER"
    OPERATOR_HEADING = "OPERATOR_HEADING"
    DESCRIPTION = "DESCRIPTION"
    USAGE = "USAGE"
    ARGUMENTS = "ARGUMENTS"
    PARAMETER_DESCRIPTION = "PARAMETER_DESCRIPTION"
    DETAILS = "DETAILS"
    RETURN_VALUE = "RETURN_VALUE"
    EXAMPLES_CODE = "EXAMPLES_CODE"
    REFERENCES = "REFERENCES"
    UNKNOWN = "UNKNOWN"


class PropositionType(StrEnum):
    DESCRIPTION = "DESCRIPTION"
    DETAIL = "DETAIL"
    PARAMETER_DESCRIPTION = "PARAMETER_DESCRIPTION"
    RETURN_VALUE = "RETURN_VALUE"


class FinalDisposition(StrEnum):
    RAW_PROPOSAL = "RAW_PROPOSAL"
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    ABSTAINED = "ABSTAINED"
    DROPPED = "DROPPED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    CANDIDATE_READY = "CANDIDATE_READY"


class StageName(StrEnum):
    TEXT_QUALITY = "TEXT_QUALITY"
    BLOCK_CLASSIFICATION = "BLOCK_CLASSIFICATION"
    CLAIM_LIKENESS = "CLAIM_LIKENESS"
    ENTITY_LINKING = "ENTITY_LINKING"
    CANONICALIZATION = "CANONICALIZATION"
    SCOPE_RESOLUTION = "SCOPE_RESOLUTION"
    EVIDENCE_BINDING = "EVIDENCE_BINDING"
    SEMANTIC_VALIDATION = "SEMANTIC_VALIDATION"


class StageOutcome(StrEnum):
    PASS = "PASS"
    DROPPED = "DROPPED"
    ABSTAINED = "ABSTAINED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    FAIL = "FAIL"


class ScopeValueStatus(StrEnum):
    EXPLICIT = "EXPLICIT"
    SOURCE_CONTEXT = "SOURCE_CONTEXT"
    INHERITED = "INHERITED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONFLICTING = "CONFLICTING"


class SourceDocument(StrictModel):
    source_artifact_id: str
    source_revision_id: str
    filename: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1)
    title: str = ""
    software_name: str | None = None
    software_version: str | None = None
    parser_name: str
    parser_version: str


class LayoutBlock(StrictModel):
    block_id: str
    page: int = Field(ge=1)
    block_index: int = Field(ge=0)
    raw_text: str = Field(min_length=1)
    page_start_offset: int = Field(ge=0)
    page_end_offset: int = Field(gt=0)
    section_label: str | None = None
    operator_name: str | None = None
    document_version: str | None = None
    structural_hint: BlockType = BlockType.UNKNOWN

    @model_validator(mode="after")
    def offsets_bound_raw_text(self) -> "LayoutBlock":
        if self.page_end_offset - self.page_start_offset != len(self.raw_text):
            raise ValueError("layout offsets must bound raw_text in the page stream")
        return self


class ProvenanceMapEntry(StrictModel):
    normalized_start: int = Field(ge=0)
    normalized_end: int = Field(ge=0)
    raw_start: int = Field(ge=0)
    raw_end: int = Field(ge=0)
    operation: Literal["COPY", "WHITESPACE_COLLAPSED", "DEHYPHENATED"]


class ReconstructedBlock(StrictModel):
    block_id: str
    raw_text: str
    normalized_text: str
    provenance_map: list[ProvenanceMapEntry]
    dehyphenation_count: int = Field(ge=0)
    page: int = Field(ge=1)
    section_label: str | None = None
    operator_name: str | None = None
    document_version: str | None = None


class SemanticBlock(StrictModel):
    semantic_block_id: str
    layout_block_id: str
    page: int = Field(ge=1)
    raw_text: str
    normalized_text: str
    block_type: BlockType
    claim_eligible: bool
    content_raw_start: int = Field(ge=0)
    content_raw_end: int = Field(ge=0)
    operator_name: str | None = None
    parameter_name: str | None = None
    document_version: str | None = None


class RawProposition(StrictModel):
    proposition_id: str
    semantic_block_id: str
    proposition_type: PropositionType
    text: str
    operator_name: str | None = None
    parameter_name: str | None = None
    is_complete: bool
    abstention_reasons: list[str] = Field(default_factory=list)
    raw_start: int = Field(ge=0)
    raw_end: int = Field(gt=0)


class BoundedEvidenceSpanCandidate(StrictModel):
    evidence_span_id: str
    source_revision_id: str
    source_artifact_id: str
    exact_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str
    page: int = Field(ge=1)
    section: str | None = None
    page_start_offset: int = Field(ge=0)
    page_end_offset: int = Field(gt=0)
    block_start_offset: int = Field(ge=0)
    block_end_offset: int = Field(gt=0)
    layout_block_id: str
    bounded: bool = True
    whole_segment: bool = False
    schema_version: str = "sckg-evidence-span-candidate-v2"
    ontology_version: str

    @model_validator(mode="after")
    def validate_bounds_and_hash(self) -> "BoundedEvidenceSpanCandidate":
        if self.page_end_offset - self.page_start_offset != len(self.exact_text):
            raise ValueError("page offsets must bound exact evidence")
        if self.block_end_offset - self.block_start_offset != len(self.exact_text):
            raise ValueError("block offsets must bound exact evidence")
        digest = hashlib.sha256(self.exact_text.encode("utf-8")).hexdigest()
        if digest != self.content_hash:
            raise ValueError("evidence content_hash must hash exact_text")
        return self


class LinkedEntityCandidate(StrictModel):
    mention: str
    entity_type: str
    candidate_id: str
    resolution_status: Literal["EXACT_EXISTING_IDENTITY", "NEW_CANDIDATE", "UNRESOLVED"]
    match_basis: Literal["EXACT_ID", "EXACT_QUALIFIED_NAME", "SOURCE_CONTEXT", "NONE"]
    context_role: str
    fuzzy_merge_used: Literal[False] = False


class CanonicalStatementCandidate(StrictModel):
    canonical_candidate_id: str
    canonical_kind: Literal["STATEMENT_REVISION", "STRUCTURAL_OUTPUT_BINDING"]
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    assertion_kind: str | None = None
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    conditions: list[str] = Field(default_factory=list)
    complete: bool
    registry_conformant: bool
    is_scientific_statement: bool
    conformance_reasons: list[str] = Field(default_factory=list)


class ScopeValue(StrictModel):
    dimension: str
    value: str | None = None
    status: ScopeValueStatus
    provenance_kind: Literal["EVIDENCE_SPAN", "SOURCE_METADATA", "INHERITED_CONTEXT", "NONE"]
    provenance_ref: str | None = None
    rationale: str

    @model_validator(mode="after")
    def validate_known_and_unknown(self) -> "ScopeValue":
        if self.status in {ScopeValueStatus.EXPLICIT, ScopeValueStatus.SOURCE_CONTEXT, ScopeValueStatus.INHERITED}:
            if not self.value or not self.provenance_ref:
                raise ValueError("known scope values require a value and provenance")
        if self.status in {ScopeValueStatus.UNKNOWN, ScopeValueStatus.NOT_APPLICABLE} and self.value is not None:
            raise ValueError("unknown/not-applicable scope cannot carry a value")
        return self


class ResolvedScope(StrictModel):
    scope_id: str
    core_scope_status: Literal["explicit", "partially_known", "unknown", "not_applicable"]
    values: list[ScopeValue]
    conflicts: list[str] = Field(default_factory=list)
    hallucinated_value_count: int = Field(default=0, ge=0)


class ValidationReport(StrictModel):
    stage_status: dict[StageName, StageOutcome]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ontology_registry_version: str
    structurally_conformant: bool
    scientific_validity_assessed: Literal[False] = False
    final_disposition: FinalDisposition

    @model_validator(mode="after")
    def every_stage_is_present(self) -> "ValidationReport":
        if set(self.stage_status) != set(StageName):
            raise ValueError("validation report must retain all ingestion stage statuses")
        return self


class Governance(StrictModel):
    human_review_status: Literal["pending"] = "pending"
    knowledge_status: Literal["candidate"] = "candidate"
    trusted: Literal[False] = False
    production_retrieval_eligible: Literal[False] = False
    execution_authorized: Literal[False] = False


class HumanReviewPacket(StrictModel):
    packet_id: str
    source: SourceDocument
    raw_block: str
    normalized_block: str
    block_type: BlockType
    raw_proposition: RawProposition | None = None
    linked_entities: list[LinkedEntityCandidate] = Field(default_factory=list)
    canonical_statement: CanonicalStatementCandidate | None = None
    scope: ResolvedScope | None = None
    evidence_span: BoundedEvidenceSpanCandidate | None = None
    validation_report: ValidationReport
    governance: Governance = Field(default_factory=Governance)
    final_disposition: FinalDisposition

    @model_validator(mode="after")
    def disposition_matches_validation(self) -> "HumanReviewPacket":
        if self.final_disposition != self.validation_report.final_disposition:
            raise ValueError("packet disposition must match validation report")
        if self.final_disposition == FinalDisposition.CANDIDATE_READY:
            if self.evidence_span is None or not self.evidence_span.bounded or self.evidence_span.whole_segment:
                raise ValueError("CANDIDATE_READY requires bounded non-whole-segment evidence")
            if self.canonical_statement is None or not self.canonical_statement.complete:
                raise ValueError("CANDIDATE_READY requires complete canonicalization")
        return self
