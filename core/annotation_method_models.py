from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


class AnnotationMethodFamily(str, Enum):
    MARKER_EVIDENCE = "marker_evidence_based"
    REFERENCE_BASED = "reference_based"


class AnnotationCandidateStatus(str, Enum):
    CANDIDATE = "candidate"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class MarkerEvidenceCandidate(StrictModel):
    cluster_id: str = Field(min_length=1)
    candidate_label: str = Field(min_length=1)
    marker_genes: list[str] = Field(min_length=1)
    evidence_source_ids: list[str] = Field(min_length=1)
    conflicting_labels: list[str] = Field(default_factory=list)
    status: AnnotationCandidateStatus = AnnotationCandidateStatus.CANDIDATE


class AnnotationCandidate(StrictModel):
    cluster_id: str = Field(min_length=1)
    candidate_label: str = Field(min_length=1)
    method_family: AnnotationMethodFamily
    status: AnnotationCandidateStatus
    evidence_source_ids: list[str] = Field(default_factory=list)
    reference_id: str | None = None
    limitations: list[str] = Field(default_factory=list)


class AnnotationMethodFamilyResult(StrictModel):
    result_id: str = Field(min_length=1)
    method_family: AnnotationMethodFamily
    method_binding_id: str | None = None
    candidates: list[AnnotationCandidate] = Field(default_factory=list)
    produces_representation_id: Literal["annotation_candidates"] = (
        "annotation_candidates"
    )
    candidate_set_hash: str | None = Field(default=None, min_length=64, max_length=64)
    eligible_for_confirmation: bool = False
    confirmation_required: Literal[True] = True
    execution_eligible: bool = False
    execution_request_count: Literal[0] = 0
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "AnnotationMethodFamilyResult":
        if self.eligible_for_confirmation and (
            not self.candidates or self.blocking_reasons or not self.candidate_set_hash
        ):
            raise ValueError("confirmable annotation candidates require a clean candidate set")
        if not self.eligible_for_confirmation and self.candidate_set_hash and not self.candidates:
            raise ValueError("candidate hash requires candidates")
        return self


class HumanAnnotationConfirmation(StrictModel):
    confirmation_id: str = Field(min_length=1)
    candidate_set_hash: str = Field(min_length=64, max_length=64)
    confirmed_labels: dict[str, str] = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    source: Literal["explicit_human_review"] = "explicit_human_review"
    produces_representation_id: Literal["confirmed_annotation"] = (
        "confirmed_annotation"
    )
    scientific_authority: Literal["human_confirmed_candidate_review"] = (
        "human_confirmed_candidate_review"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
