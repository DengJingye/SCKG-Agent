from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


class RepresentationStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    INVALID = "invalid"


class RepresentationRecord(StrictModel):
    representation_record_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    representation_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    schema_version: str = Field(min_length=1)
    value_state: str = Field(min_length=1)
    slot: str = Field(min_length=1)
    provenance: list[str] = Field(default_factory=list)
    cell_index_hash: str | None = Field(default=None, min_length=64, max_length=64)
    gene_index_hash: str | None = Field(default=None, min_length=64, max_length=64)
    parameter_hash: str | None = Field(default=None, min_length=64, max_length=64)
    parent_record_ids: list[str] = Field(default_factory=list)
    status: RepresentationStatus = RepresentationStatus.CURRENT
    validated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    stale_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status(self) -> "RepresentationRecord":
        if self.status == RepresentationStatus.CURRENT and self.stale_reasons:
            raise ValueError("current representation cannot contain stale reasons")
        if self.status != RepresentationStatus.CURRENT and not self.stale_reasons:
            raise ValueError("stale or invalid representation requires reasons")
        return self


class RepresentationLedger(StrictModel):
    schema_version: Literal["sckg-representation-ledger-v1"] = (
        "sckg-representation-ledger-v1"
    )
    ledger_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    source_artifact_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    cell_index_hash: str = Field(min_length=64, max_length=64)
    gene_index_hash: str = Field(min_length=64, max_length=64)
    records: list[RepresentationRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    blocking_errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_ledger(self) -> "RepresentationLedger":
        ids = [item.representation_record_id for item in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("representation record ids must be unique")
        known = set(ids)
        dangling = sorted(
            parent
            for item in self.records
            for parent in item.parent_record_ids
            if parent not in known
        )
        if dangling:
            raise ValueError("representation lineage contains dangling parents")
        return self

    def current(self, representation_id: str) -> list[RepresentationRecord]:
        return [
            item
            for item in self.records
            if item.representation_id == representation_id
            and item.status == RepresentationStatus.CURRENT
            and item.validated
        ]

    def available_ids(self) -> set[str]:
        return {item.representation_id for item in self.records if item.status == "current" and item.validated}


class RepresentationEligibility(StrictModel):
    representation_id: str
    reusable: bool
    record_id: str | None = None
    reasons: list[str] = Field(default_factory=list)


class ScientificMissingRequirement(StrictModel):
    input_port_id: str
    requirement_ids: list[str] = Field(default_factory=list)
    representation_constraint_ids: list[str] = Field(default_factory=list)
    required_representation_type_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    rejected_representation_record_ids: list[str] = Field(default_factory=list)


class ScientificEvidenceReference(StrictModel):
    claim_revision_id: str
    evidence_span_id: str
    source_revision_id: str
    locator: str
    content_hash: str = Field(min_length=64, max_length=64)


class ScientificApplicabilityResult(StrictModel):
    action_id: str
    operator_revision_id: str
    decision_scope: Literal["existing_representation_reuse", "action_applicability"]
    knowledge_status: Literal["candidate"] = "candidate"
    applicable: bool
    blocked: bool
    assessed_representation_ids: list[str] = Field(default_factory=list)
    reusable_representation_ids: list[str] = Field(default_factory=list)
    reusable_representation_record_ids: list[str] = Field(default_factory=list)
    missing_requirements: list[ScientificMissingRequirement] = Field(default_factory=list)
    incompatibility_reasons: list[str] = Field(default_factory=list)
    evidence_references: list[ScientificEvidenceReference] = Field(default_factory=list)


class CapabilityPlanResult(StrictModel):
    plan_id: str
    workflow_plan_id: str
    target_representations: list[str]
    reused_representation_ids: list[str]
    planned_method_ids: list[str]
    blocked: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    scientific_applicability_results: list[ScientificApplicabilityResult] = Field(
        default_factory=list
    )
