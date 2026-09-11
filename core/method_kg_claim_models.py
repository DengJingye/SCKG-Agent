from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


ATOMIC_CLAIM_SCHEMA_VERSION = "sckg-method-kg-atomic-claim-v1"
CLAIM_RELATION_SCHEMA_VERSION = "sckg-method-kg-claim-relation-v1"

AtomicClaimPredicate = Literal[
    "supports_task",
    "consumes",
    "requires_representation",
    "produces",
    "prerequisite",
    "key_parameter",
    "limitation",
]
AtomicClaimPolarity = Literal["positive", "negative", "conditional"]
AtomicClaimScope = Literal[
    "general",
    "documented_api",
    "reported_workflow",
    "dataset_specific",
]
AtomicClaimReviewStatus = Literal[
    "candidate_pending_review",
    "reviewed",
    "verified",
    "human_reviewed",
    "rejected",
]
AtomicClaimObjectType = Literal[
    "Task",
    "Representation",
    "Parameter",
    "Limitation",
    "Method",
    "Value",
]
ClaimRelationKind = Literal["provenance", "claim_structure", "method_projection"]
ClaimRelationType = Literal[
    "SUPPORTS",
    "SUBJECT",
    "OBJECT",
    "SUPPORTS_TASK",
    "CONSUMES",
    "REQUIRES_REPRESENTATION",
    "PRODUCES",
    "PREREQUISITE",
    "KEY_PARAMETER",
    "HAS_LIMITATION",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_ID_RE = re.compile(r"^atomic-claim:[0-9a-f]{24}$")
_RELATION_ID_RE = re.compile(r"^claim-relation:[0-9a-f]{24}$")
_ENTITY_ID_RE = re.compile(
    r"^(?:method|tool|task|representation|parameter|limitation):[a-z0-9][a-z0-9_.:-]{0,126}$"
)
_EVIDENCE_SPAN_ID_RE = re.compile(r"^sourcev2:[0-9a-f]{20}$")


def _stable_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_claim_hash_payload(values: dict[str, object]) -> dict[str, object]:
    """Return the immutable semantic payload covered by ``content_hash``."""

    return {
        key: values.get(key)
        for key in (
            "schema_version",
            "subject_id",
            "subject_type",
            "predicate",
            "object_id",
            "object_value",
            "object_type",
            "claim_text",
            "polarity",
            "scope",
            "modality",
            "version",
            "source_span_id",
            "source_id",
            "source_content_hash",
        )
    }


def compute_atomic_claim_content_hash(values: dict[str, object]) -> str:
    return _stable_hash(atomic_claim_hash_payload(values))


def make_atomic_claim_id(content_hash: str) -> str:
    if not _SHA256_RE.fullmatch(content_hash):
        raise ValueError("content_hash must be a lowercase SHA-256 digest")
    return f"atomic-claim:{content_hash[:24]}"


class AtomicClaim(StrictModel):
    schema_version: Literal["sckg-method-kg-atomic-claim-v1"] = ATOMIC_CLAIM_SCHEMA_VERSION
    claim_id: str = Field(min_length=37, max_length=37)
    subject_id: str = Field(min_length=3, max_length=128)
    subject_type: Literal["Method", "Tool"]
    predicate: AtomicClaimPredicate
    object_id: str | None = Field(default=None, max_length=128)
    object_value: str | None = Field(default=None, min_length=1, max_length=320)
    object_type: AtomicClaimObjectType
    claim_text: str = Field(min_length=1, max_length=500)
    polarity: AtomicClaimPolarity = "positive"
    scope: AtomicClaimScope = "general"
    modality: list[str] = Field(min_length=1, max_length=8)
    version: str | None = Field(default=None, max_length=80)
    source_span_id: str = Field(min_length=29, max_length=29)
    source_id: str = Field(min_length=1, max_length=128)
    source_content_hash: str = Field(min_length=64, max_length=64)
    content_hash: str = Field(min_length=64, max_length=64)
    review_status: AtomicClaimReviewStatus = "candidate_pending_review"

    @model_validator(mode="after")
    def validate_atomic_claim(self) -> "AtomicClaim":
        if not _CLAIM_ID_RE.fullmatch(self.claim_id):
            raise ValueError("claim_id must use the canonical atomic-claim digest form")
        if not _ENTITY_ID_RE.fullmatch(self.subject_id):
            raise ValueError("subject_id is not a bounded canonical entity identifier")
        if (self.object_id is None) == (self.object_value is None):
            raise ValueError("exactly one of object_id or object_value is required")
        if self.object_id is not None and not _ENTITY_ID_RE.fullmatch(self.object_id):
            raise ValueError("object_id is not a bounded canonical entity identifier")
        if self.object_id is None and self.object_type != "Value":
            raise ValueError("object_value claims must use object_type=Value")
        if self.object_id is not None and self.object_type == "Value":
            raise ValueError("object_id claims cannot use object_type=Value")
        if not _EVIDENCE_SPAN_ID_RE.fullmatch(self.source_span_id):
            raise ValueError("source_span_id must reference a sourcev2 evidence span")
        if not _SHA256_RE.fullmatch(self.source_content_hash):
            raise ValueError("source_content_hash must be a lowercase SHA-256 digest")
        if not _SHA256_RE.fullmatch(self.content_hash):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        expected_hash = compute_atomic_claim_content_hash(self.model_dump())
        if self.content_hash != expected_hash:
            raise ValueError("atomic claim content_hash does not match its semantic payload")
        if self.claim_id != make_atomic_claim_id(expected_hash):
            raise ValueError("claim_id does not match content_hash")
        if len(self.modality) != len(set(self.modality)):
            raise ValueError("modality values must be unique")
        return self


def claim_relation_hash_payload(values: dict[str, object]) -> dict[str, object]:
    return {
        key: values.get(key)
        for key in (
            "schema_version",
            "relation_kind",
            "source_id",
            "source_type",
            "relation",
            "target_id",
            "target_type",
            "derived_from_claim_ids",
            "evidence_span_ids",
            "review_status",
        )
    }


def compute_claim_relation_id(values: dict[str, object]) -> str:
    return f"claim-relation:{_stable_hash(claim_relation_hash_payload(values))[:24]}"


class ClaimLinkedRelationCandidate(StrictModel):
    schema_version: Literal["sckg-method-kg-claim-relation-v1"] = CLAIM_RELATION_SCHEMA_VERSION
    relation_id: str = Field(min_length=39, max_length=39)
    relation_kind: ClaimRelationKind
    source_id: str = Field(min_length=1, max_length=128)
    source_type: Literal["EvidenceSpan", "AtomicClaim", "Method", "Tool", "Representation"]
    relation: ClaimRelationType
    target_id: str = Field(min_length=1, max_length=128)
    target_type: Literal[
        "AtomicClaim",
        "Method",
        "Tool",
        "Task",
        "Representation",
        "Parameter",
        "Limitation",
    ]
    derived_from_claim_ids: list[str] = Field(default_factory=list, max_length=8)
    evidence_span_ids: list[str] = Field(default_factory=list, max_length=8)
    review_status: AtomicClaimReviewStatus = "candidate_pending_review"

    @model_validator(mode="after")
    def validate_relation(self) -> "ClaimLinkedRelationCandidate":
        if not _RELATION_ID_RE.fullmatch(self.relation_id):
            raise ValueError("relation_id must use the canonical claim-relation digest form")
        if self.relation_id != compute_claim_relation_id(self.model_dump()):
            raise ValueError("relation_id does not match relation payload")
        if len(self.derived_from_claim_ids) != len(set(self.derived_from_claim_ids)):
            raise ValueError("derived_from_claim_ids must be unique")
        if len(self.evidence_span_ids) != len(set(self.evidence_span_ids)):
            raise ValueError("evidence_span_ids must be unique")
        for claim_id in self.derived_from_claim_ids:
            if not _CLAIM_ID_RE.fullmatch(claim_id):
                raise ValueError("derived_from_claim_ids contains an invalid claim ID")
        for span_id in self.evidence_span_ids:
            if not _EVIDENCE_SPAN_ID_RE.fullmatch(span_id):
                raise ValueError("evidence_span_ids contains an invalid span ID")

        if self.relation_kind == "provenance":
            if self.source_type != "EvidenceSpan" or self.target_type != "AtomicClaim":
                raise ValueError("provenance relation must be EvidenceSpan -> AtomicClaim")
            if self.relation != "SUPPORTS" or len(self.derived_from_claim_ids) != 1:
                raise ValueError("provenance relation must support exactly its target claim")
        elif self.relation_kind == "claim_structure":
            if self.source_type != "AtomicClaim" or self.relation not in {"SUBJECT", "OBJECT"}:
                raise ValueError("claim structure must originate at an AtomicClaim")
            if len(self.derived_from_claim_ids) != 1:
                raise ValueError("claim structure must reference exactly its owner claim")
        else:
            if self.relation in {"SUPPORTS", "SUBJECT", "OBJECT"}:
                raise ValueError("method projection cannot use provenance/structure relations")
            if not self.derived_from_claim_ids:
                raise ValueError("projected Method Graph relation requires derived_from_claim_ids")
            if not self.evidence_span_ids:
                raise ValueError("projected Method Graph relation requires evidence_span_ids")
            if self.relation == "PREREQUISITE" and len(self.derived_from_claim_ids) < 2:
                raise ValueError("derived prerequisite requires input and output AtomicClaim IDs")
        return self
