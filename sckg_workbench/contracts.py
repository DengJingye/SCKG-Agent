"""Open scientific envelopes; no legacy ontology instances or defaults."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceAnchor(Contract):
    ir_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def bounds(self):
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("anchor is a zero-based Unicode [start,end) exact quote")
        return self


class ClaimAttribute(Contract):
    """Optional, source-bound fact; open keys avoid a premature fixed ontology."""

    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)
    evidence_anchor_indices: list[int] = Field(min_length=1)
    qualifiers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_anchors(self):
        if len(self.evidence_anchor_indices) != len(set(self.evidence_anchor_indices)) or any(
            index < 0 for index in self.evidence_anchor_indices
        ):
            raise ValueError("attribute evidence anchors must be distinct zero-based indices")
        return self


class OpenClaim(Contract):
    proposition: str = Field(min_length=1, max_length=12000)
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    polarity: Literal["positive", "negative"]
    conditions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    assertion_kind: Literal["source_assertion", "synthesis", "hypothesis"] = "source_assertion"
    anchors: list[EvidenceAnchor] = Field(min_length=1)
    proposed_terms: list[str] = Field(default_factory=list)
    typed_attributes: list[ClaimAttribute] = Field(default_factory=list)
    model_self_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def attribute_anchors_exist(self):
        if any(index >= len(self.anchors) for attribute in self.typed_attributes
               for index in attribute.evidence_anchor_indices):
            raise ValueError("attribute evidence must point to an exact claim anchor")
        return self


class ExtractionOutput(Contract):
    units: list[OpenClaim] = Field(default_factory=list, max_length=100)
    gaps: list[str] = Field(default_factory=list)
    source_summary: str = ""


class SemanticAssessment(Contract):
    relation: Literal["support", "refute", "neutral", "indeterminate"]
    extent: Literal["full", "partial", "unknown", "not_applicable"]
    rationale: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class EvidencePackage(Contract):
    namespace: str
    release_id: str | None
    governance_version: int
    purpose: Literal["explanation", "recommendation"]
    units: list[dict[str, Any]]
    gaps: list[str]
    retrieval: dict[str, Any]


class DatasetProfile(Contract):
    artifact_id: str
    # Bounded local profiling does not imply that the entire file was hashed.
    content_sha256: str | None
    dimensions: dict[str, int]
    measurements: dict[str, Any]
    sampling: dict[str, Any]
    unknowns: list[str]
    raw_data_modified: Literal[False] = False


class ResearchPlan(Contract):
    goal: str
    evidence_release_id: str | None
    dataset_profile_id: str | None = None
    steps: list[dict[str, Any]]
    missing_conditions: list[str]
    status: Literal["proposal", "blocked", "ready_for_review"] = "proposal"


class CapabilitySpec(Contract):
    capability_id: str
    implementation_version: str
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    environment: dict[str, Any]
    validation_record_ids: list[str]
    status: Literal["discovered", "planning_only", "validated"]

    @model_validator(mode="after")
    def actual_validation(self):
        if self.status == "validated" and not self.validation_record_ids:
            raise ValueError("validated capability requires actual validation records")
        return self
