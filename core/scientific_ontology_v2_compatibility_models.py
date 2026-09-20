from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


COMPATIBILITY_SCHEMA_VERSION = "sckg-ontology-v2-compatibility-view-v1"
FROZEN_ONTOLOGY_VERSION = "2.0.0-core-review.1"

CompatibilityStatus = Literal[
    "DIRECT_COMPATIBLE",
    "COMPATIBLE_WITH_ADAPTER",
    "AMBIGUOUS_MAPPING",
    "NOT_MAPPABLE",
    "DEFERRED",
]
PredicateClassification = Literal[
    "AUTHORITATIVE_LINK_TYPE",
    "DERIVED_PROJECTION",
    "UNRESOLVED_PREDICATE",
]
RecordAuthority = Literal[
    "SUPPORTED_AUTHORITATIVE_RECORD",
    "CANDIDATE_RECORD",
    "LEGACY_RECORD",
    "DERIVED_RECORD",
    "UNRESOLVED",
]


class ReadOnlyCompatibilityModel(BaseModel):
    """Immutable compatibility output; never a canonical ontology record."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class CompatibilityProvenance(ReadOnlyCompatibilityModel):
    source_layer_id: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_schema_version: str | None = None
    source_graph_node_id: str | None = None


class SourceRecordProvenance(CompatibilityProvenance):
    source_status: str | None = None


class EvidenceCoreProvenance(CompatibilityProvenance):
    pass


class CompatibilityDiagnostics(ReadOnlyCompatibilityModel):
    legacy_source_status: str | None = None
    notes: tuple[str, ...] = ()


class ScopeQualifierView(ReadOnlyCompatibilityModel):
    dimension: str = Field(min_length=1)
    values_json: tuple[str, ...] = Field(min_length=1)


class ScopeCompatibilityView(ReadOnlyCompatibilityModel):
    view_type: Literal["ScopeCompatibilityView"] = "ScopeCompatibilityView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    scope_id: str = Field(min_length=1)
    source_scope_id: str = Field(min_length=1)
    scope_status: Literal["explicit", "partially_known", "unknown", "not_applicable"]
    combination: Literal["ALL_OF", "ANY_OF"]
    qualifiers: tuple[ScopeQualifierView, ...] = ()
    shared_qualifiers: tuple[ScopeQualifierView, ...] = ()
    inline_qualifiers: tuple[ScopeQualifierView, ...] = ()
    composition: Literal["SHARED_ONLY", "SHARED_AND_INLINE"] = "SHARED_ONLY"
    unknown_dimensions: tuple[str, ...] = ()
    provenance: SourceRecordProvenance


class StatementRevisionView(ReadOnlyCompatibilityModel):
    view_type: Literal["StatementRevisionView"] = "StatementRevisionView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    statement_id: str = Field(min_length=1)
    statement_revision_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    source_predicate: str = Field(min_length=1)
    object_id: str | None = None
    literal_value: str | None = None
    literal_datatype: str | None = None
    polarity: Literal["POSITIVE", "NEGATIVE"]
    qualifiers: tuple[ScopeQualifierView, ...] = ()
    scope_ref: str | None = None
    scope_status: Literal["explicit", "partially_known", "unknown", "not_applicable"]
    epistemic_status: Literal["asserted"] = "asserted"
    assertion_kind: Literal[
        "definition",
        "capability",
        "requirement",
        "recommendation",
        "empirical_observation",
        "limitation",
    ]
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_revision_ids: tuple[str, ...] = ()
    evidence_span_ids: tuple[str, ...] = ()
    activity_ref: str | None = None
    source_governance_status: str | None = None
    trusted: Literal[False] = False
    provenance: SourceRecordProvenance

    @model_validator(mode="after")
    def validate_object(self) -> "StatementRevisionView":
        if (self.object_id is None) == (self.literal_value is None):
            raise ValueError("exactly one statement object is required")
        return self


class EvidenceSpanCoreView(ReadOnlyCompatibilityModel):
    view_type: Literal["EvidenceSpanCoreView"] = "EvidenceSpanCoreView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    evidence_span_id: str = Field(min_length=1)
    source_revision_id: str | None = None
    source_artifact_id: str | None = None
    source_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    exact_text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    line_start: int | None = Field(default=None, ge=0)
    line_end: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=1)
    activity_ref: str | None = None
    provenance: EvidenceCoreProvenance

    @model_validator(mode="after")
    def validate_locator_pairs(self) -> "EvidenceSpanCoreView":
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line locators must occur as a pair")
        if self.line_start is not None and self.line_end < self.line_start:
            raise ValueError("line_end cannot precede line_start")
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("offset locators must occur as a pair")
        if self.start_offset is not None and self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class EvidenceAssessmentView(ReadOnlyCompatibilityModel):
    view_type: Literal["EvidenceAssessmentView"] = "EvidenceAssessmentView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    assessment_id: str = Field(min_length=1)
    statement_revision_id: str = Field(min_length=1)
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    source_stance: str = Field(min_length=1)
    support_type: Literal[
        "DIRECT_SUPPORT",
        "PARTIAL_SUPPORT",
        "CONTEXTUAL_SUPPORT",
        "CONTRADICTS",
        "REFUTES",
        "DOES_NOT_SUPPORT",
        "UNCERTAIN",
    ]
    subject_aligned: bool
    predicate_aligned: bool
    object_aligned: bool
    scope_alignment: Literal["aligned", "narrower", "partial", "unknown", "conflicting"]
    rationale: str = Field(min_length=1)
    assessment_method: str | None = None
    assessor_ref: str | None = None
    created_at: str | None = None
    status: str | None = None
    review_decision_ids: tuple[str, ...] = ()
    trusted: Literal[False] = False
    provenance: SourceRecordProvenance


class RequirementCompatibilityView(ReadOnlyCompatibilityModel):
    view_type: Literal["RequirementCompatibilityView"] = "RequirementCompatibilityView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    requirement_id: str = Field(min_length=1)
    strength: Literal["REQUIRED", "RECOMMENDED", "OPTIONAL", "DISCOURAGED"] | None
    combination: Literal["ALL_OF", "ANY_OF"] | None
    activation_status: Literal["specified", "unconditional", "unknown"]
    when_json: tuple[str, ...] = ()
    representation_constraint_ids: tuple[str, ...] = ()
    reference_artifact_revision_ids: tuple[str, ...] = ()
    scope_ref: str = Field(min_length=1)
    provenance: SourceRecordProvenance


class ReferenceResourceView(ReadOnlyCompatibilityModel):
    view_type: Literal["ReferenceResourceView"] = "ReferenceResourceView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    artifact_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    artifact_kind: str = Field(min_length=1)
    artifact_revision_id: str | None = None
    version: str | None = None
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    species_taxa: tuple[str, ...] = ()
    feature_namespace: str | None = None
    label_ontology_id: str | None = None
    scope_ref: str | None = None
    provenance: SourceRecordProvenance


class RepresentationTypeView(ReadOnlyCompatibilityModel):
    view_type: Literal["RepresentationTypeView"] = "RepresentationTypeView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    representation_type_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    observation_unit: str = Field(min_length=1)
    axes: tuple[str, ...] = Field(min_length=1)
    modalities: tuple[str, ...] = Field(min_length=1)
    value_semantics: str = Field(min_length=1)
    transformation_state: tuple[str, ...] = ()
    feature_namespace: str = Field(min_length=1)
    missingness_semantics: str = Field(min_length=1)
    structural_properties: tuple[str, ...] = ()
    components_json: tuple[str, ...] = ()
    provenance: SourceRecordProvenance


class RelationCompatibilityView(ReadOnlyCompatibilityModel):
    view_type: Literal["RelationCompatibilityView"] = "RelationCompatibilityView"
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    ontology_version: Literal["2.0.0-core-review.1"] = FROZEN_ONTOLOGY_VERSION
    source_relation: str = Field(min_length=1)
    canonical_predicate: str | None = None
    predicate_classification: PredicateClassification
    record_authority: RecordAuthority
    semantic_subject_id: str | None = None
    semantic_object_id: str | None = None
    trusted: Literal[False] = False
    canonical: Literal[False] = False
    provenance: SourceRecordProvenance


CompatibilityView = Union[
    StatementRevisionView,
    EvidenceSpanCoreView,
    EvidenceAssessmentView,
    ScopeCompatibilityView,
    RequirementCompatibilityView,
    ReferenceResourceView,
    RepresentationTypeView,
    RelationCompatibilityView,
]


class CompatibilityResult(ReadOnlyCompatibilityModel):
    schema_version: Literal["sckg-ontology-v2-compatibility-view-v1"] = (
        COMPATIBILITY_SCHEMA_VERSION
    )
    status: CompatibilityStatus
    reason_codes: tuple[str, ...] = Field(min_length=1)
    view: CompatibilityView | None = None
    diagnostics: CompatibilityDiagnostics | None = None
