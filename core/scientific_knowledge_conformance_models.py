from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from core.execution_models import StrictModel


SCHEMA_VERSION = "sckg-scientific-knowledge-conformance-v1.1"


class VersionConstraint(StrictModel):
    subject_id: str = Field(min_length=1)
    status: Literal["exact", "range", "unknown", "version_independent", "not_applicable"]
    expression: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_expression(self) -> "VersionConstraint":
        if self.status in {"exact", "range"} and not self.expression:
            raise ValueError("exact/range version constraints require an expression")
        if self.status in {"unknown", "version_independent", "not_applicable"} and self.expression:
            raise ValueError("non-specific version constraints cannot carry an expression")
        return self


class ParameterCondition(StrictModel):
    parameter_id: str = Field(min_length=1)
    operator: Literal["equals", "in", "not_in", "present"]
    values: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_values(self) -> "ParameterCondition":
        if self.operator == "present" and self.values:
            raise ValueError("present conditions cannot carry values")
        if self.operator != "present" and not self.values:
            raise ValueError("comparison conditions require values")
        return self


class ApplicabilityScope(StrictModel):
    schema_version: Literal["sckg-applicability-scope-v1.1"] = "sckg-applicability-scope-v1.1"
    scope_id: str = Field(pattern=r"^scope:[a-z0-9][a-z0-9_.:-]{0,126}$")
    task_ids: list[str] = Field(default_factory=list, max_length=16)
    version_constraints: list[VersionConstraint] = Field(default_factory=list, max_length=16)
    modalities: list[str] = Field(default_factory=list, max_length=8)
    organism_taxa: list[str] = Field(default_factory=list, max_length=8)
    biological_context_ids: list[str] = Field(default_factory=list, max_length=16)
    observation_units: list[str] = Field(default_factory=list, max_length=8)
    assay_technology_ids: list[str] = Field(default_factory=list, max_length=16)
    study_design_constraints: list[str] = Field(default_factory=list, max_length=16)
    representation_constraint_ids: list[str] = Field(default_factory=list, max_length=16)
    parameter_conditions: list[ParameterCondition] = Field(default_factory=list, max_length=16)
    resource_constraints: list[str] = Field(default_factory=list, max_length=16)
    evaluation_context_ids: list[str] = Field(default_factory=list, max_length=16)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    scope_status: Literal["explicit", "partially_known", "unknown", "not_applicable"]
    combination: Literal["all_of", "any_of"] = "all_of"

    @model_validator(mode="after")
    def validate_scope(self) -> "ApplicabilityScope":
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        dimensions = (
            self.task_ids
            or self.version_constraints
            or self.modalities
            or self.organism_taxa
            or self.biological_context_ids
            or self.observation_units
            or self.assay_technology_ids
            or self.study_design_constraints
            or self.representation_constraint_ids
            or self.parameter_conditions
            or self.resource_constraints
            or self.evaluation_context_ids
            or self.valid_from
            or self.valid_to
        )
        if self.scope_status == "explicit" and not dimensions:
            raise ValueError("explicit applicability scope requires at least one dimension")
        if self.scope_status == "not_applicable" and dimensions:
            raise ValueError("not_applicable scope cannot carry applicability dimensions")
        return self


class RepresentationComponent(StrictModel):
    role: str = Field(min_length=1, max_length=80)
    kind: Literal["matrix", "vector", "mapping", "metadata"]
    axes: list[str] = Field(default_factory=list, max_length=8)
    value_semantics: str = Field(min_length=1, max_length=160)
    storage_semantics: str = Field(min_length=1, max_length=200)
    required: bool = True


class RepresentationType(StrictModel):
    schema_version: Literal["sckg-representation-type-v1.1"] = "sckg-representation-type-v1.1"
    representation_type_id: str = Field(pattern=r"^representation-type:[a-z0-9][a-z0-9_.:-]{0,126}$")
    label: str = Field(min_length=1, max_length=160)
    observation_unit: str = Field(min_length=1, max_length=80)
    axes: list[str] = Field(min_length=1, max_length=8)
    modalities: list[str] = Field(min_length=1, max_length=8)
    value_semantics: str = Field(min_length=1, max_length=120)
    transformation_state: list[str] = Field(default_factory=list, max_length=16)
    feature_identity: str = Field(min_length=1, max_length=160)
    missingness_semantics: str = Field(min_length=1, max_length=160)
    structural_properties: list[str] = Field(default_factory=list, max_length=16)
    components: list[RepresentationComponent] = Field(default_factory=list, max_length=16)


class RepresentationConstraint(StrictModel):
    schema_version: Literal["sckg-representation-constraint-v1.1"] = "sckg-representation-constraint-v1.1"
    constraint_id: str = Field(pattern=r"^representation-constraint:[a-z0-9][a-z0-9_.:-]{0,126}$")
    representation_type_id: str = Field(pattern=r"^representation-type:")
    required_value_states: list[str] = Field(default_factory=list, max_length=16)
    required_transformations: list[str] = Field(default_factory=list, max_length=16)
    forbidden_transformations: list[str] = Field(default_factory=list, max_length=16)
    required_provenance_method_ids: list[str] = Field(default_factory=list, max_length=16)
    required_modalities: list[str] = Field(default_factory=list, max_length=8)
    required_metadata: list[str] = Field(default_factory=list, max_length=16)
    required_component_roles: list[str] = Field(default_factory=list, max_length=16)
    observation_alignment: Literal[
        "not_applicable", "same_observations", "explicit_mapping", "paired", "partially_paired"
    ] = "not_applicable"
    feature_alignment: Literal[
        "not_applicable", "same_features", "intersection", "explicit_mapping"
    ] = "not_applicable"
    allow_missing_modalities: bool = False
    scope_id: str = Field(pattern=r"^scope:")

    @model_validator(mode="after")
    def validate_constraint(self) -> "RepresentationConstraint":
        overlap = set(self.required_transformations) & set(self.forbidden_transformations)
        if overlap:
            raise ValueError("representation transformations cannot be both required and forbidden")
        if self.allow_missing_modalities and len(self.required_modalities) < 2:
            raise ValueError("missing modalities are meaningful only for multimodal constraints")
        return self


class ScientificTask(StrictModel):
    schema_version: Literal["sckg-scientific-task-v1.1"] = "sckg-scientific-task-v1.1"
    record_type: Literal["ScientificTask"] = "ScientificTask"
    entity_id: str = Field(pattern=r"^task:")
    label: str = Field(min_length=1)


class Method(StrictModel):
    schema_version: Literal["sckg-method-v1.1"] = "sckg-method-v1.1"
    record_type: Literal["Method"] = "Method"
    entity_id: str = Field(pattern=r"^method:")
    label: str = Field(min_length=1)


class MethodVariant(StrictModel):
    schema_version: Literal["sckg-method-variant-v1.1"] = "sckg-method-variant-v1.1"
    record_type: Literal["MethodVariant"] = "MethodVariant"
    entity_id: str = Field(pattern=r"^method-variant:")
    method_id: str = Field(pattern=r"^method:")
    label: str = Field(min_length=1)
    defining_parameter_conditions: list[ParameterCondition] = Field(default_factory=list, max_length=16)


class ParameterDefinition(StrictModel):
    schema_version: Literal["sckg-parameter-definition-v1.1"] = "sckg-parameter-definition-v1.1"
    record_type: Literal["ParameterDefinition"] = "ParameterDefinition"
    entity_id: str = Field(pattern=r"^parameter:")
    label: str = Field(min_length=1)
    owner_operator_id: str = Field(pattern=r"^operator:")
    value_domain: str = Field(min_length=1, max_length=240)
    unit: str | None = Field(default=None, max_length=80)


class Limitation(StrictModel):
    schema_version: Literal["sckg-limitation-v1.1"] = "sckg-limitation-v1.1"
    record_type: Literal["Limitation"] = "Limitation"
    entity_id: str = Field(pattern=r"^limitation:")
    label: str = Field(min_length=1)


class SoftwareProject(StrictModel):
    schema_version: Literal["sckg-software-project-v1.1"] = "sckg-software-project-v1.1"
    record_type: Literal["SoftwareProject"] = "SoftwareProject"
    entity_id: str = Field(pattern=r"^software-project:")
    label: str = Field(min_length=1)


class Package(StrictModel):
    schema_version: Literal["sckg-package-v1.1"] = "sckg-package-v1.1"
    record_type: Literal["Package"] = "Package"
    entity_id: str = Field(pattern=r"^package:")
    project_id: str = Field(pattern=r"^software-project:")
    ecosystem: str = Field(min_length=1)
    distribution_name: str = Field(min_length=1)


class PackageRelease(StrictModel):
    schema_version: Literal["sckg-package-release-v1.1"] = "sckg-package-release-v1.1"
    record_type: Literal["PackageRelease"] = "PackageRelease"
    entity_id: str = Field(pattern=r"^package-release:")
    package_id: str = Field(pattern=r"^package:")
    version: str = Field(min_length=1)
    immutable_release_ref: str = Field(min_length=1)


class Operator(StrictModel):
    schema_version: Literal["sckg-operator-v1.1"] = "sckg-operator-v1.1"
    record_type: Literal["Operator"] = "Operator"
    entity_id: str = Field(pattern=r"^operator:")
    package_id: str = Field(pattern=r"^package:")
    qualified_name: str = Field(min_length=1)


class Requirement(StrictModel):
    schema_version: Literal["sckg-requirement-v1.1"] = "sckg-requirement-v1.1"
    requirement_id: str = Field(pattern=r"^requirement:")
    level: Literal["mandatory", "conditional", "optional", "recommended"]
    representation_constraint_ids: list[str] = Field(default_factory=list, max_length=8)
    reference_artifact_revision_ids: list[str] = Field(default_factory=list, max_length=8)
    when: list[ParameterCondition] = Field(default_factory=list, max_length=8)
    scope_id: str = Field(pattern=r"^scope:")

    @model_validator(mode="after")
    def validate_requirement(self) -> "Requirement":
        if not self.representation_constraint_ids and not self.reference_artifact_revision_ids:
            raise ValueError("requirement must constrain a representation or reference artifact")
        if self.level == "conditional" and not self.when:
            raise ValueError("conditional requirement requires a when clause")
        if self.level != "conditional" and self.when:
            raise ValueError("only conditional requirements may carry when clauses")
        return self


class InputPort(StrictModel):
    schema_version: Literal["sckg-input-port-v1.1"] = "sckg-input-port-v1.1"
    input_port_id: str = Field(pattern=r"^input-port:")
    role: str = Field(min_length=1)
    min_cardinality: int = Field(ge=0)
    max_cardinality: int | None = Field(default=None, ge=1)
    requirements: list[Requirement] = Field(min_length=1, max_length=16)
    requirement_combination: Literal["all_of", "any_of"] = "all_of"
    cross_port_alignment_constraints: list[str] = Field(default_factory=list, max_length=16)
    scope_id: str = Field(pattern=r"^scope:")

    @model_validator(mode="after")
    def validate_cardinality(self) -> "InputPort":
        if self.max_cardinality is not None and self.max_cardinality < self.min_cardinality:
            raise ValueError("max cardinality cannot be less than min cardinality")
        return self


class OutputPort(StrictModel):
    schema_version: Literal["sckg-output-port-v1.1"] = "sckg-output-port-v1.1"
    output_port_id: str = Field(pattern=r"^output-port:")
    role: str = Field(min_length=1)
    representation_type_id: str = Field(pattern=r"^representation-type:")
    production_conditions: list[ParameterCondition] = Field(default_factory=list, max_length=8)
    lineage_input_port_ids: list[str] = Field(default_factory=list, max_length=8)
    preserves: list[str] = Field(default_factory=list, max_length=16)
    transforms: list[str] = Field(default_factory=list, max_length=16)
    invalidates: list[str] = Field(default_factory=list, max_length=16)
    irreversible: bool = False
    scope_id: str = Field(pattern=r"^scope:")


class OperatorRevision(StrictModel):
    schema_version: Literal["sckg-operator-revision-v1.1"] = "sckg-operator-revision-v1.1"
    record_type: Literal["OperatorRevision"] = "OperatorRevision"
    entity_id: str = Field(pattern=r"^operator-revision:")
    operator_id: str = Field(pattern=r"^operator:")
    package_release_id: str = Field(pattern=r"^package-release:")
    implements_method_ids: list[str] = Field(min_length=1, max_length=8)
    implements_method_variant_ids: list[str] = Field(default_factory=list, max_length=8)
    input_ports: list[InputPort] = Field(default_factory=list, max_length=16)
    output_ports: list[OutputPort] = Field(default_factory=list, max_length=16)
    contract_refs: list[str] = Field(default_factory=list, max_length=8)
    scope_id: str = Field(pattern=r"^scope:")

    @model_validator(mode="after")
    def validate_ports(self) -> "OperatorRevision":
        port_ids = [p.input_port_id for p in self.input_ports] + [p.output_port_id for p in self.output_ports]
        if len(port_ids) != len(set(port_ids)):
            raise ValueError("operator port identifiers must be unique")
        known_input_ids = {p.input_port_id for p in self.input_ports}
        dangling = {
            source
            for port in self.output_ports
            for source in port.lineage_input_port_ids
            if source not in known_input_ids
        }
        if dangling:
            raise ValueError("output lineage references unknown input ports")
        return self


class ReferenceArtifact(StrictModel):
    schema_version: Literal["sckg-reference-artifact-v1.1"] = "sckg-reference-artifact-v1.1"
    record_type: Literal["ReferenceArtifact"] = "ReferenceArtifact"
    entity_id: str = Field(pattern=r"^reference-artifact:")
    label: str = Field(min_length=1)
    artifact_kind: Literal["atlas", "label_mapping", "pretrained_model", "feature_mapping"]


class ReferenceArtifactRevision(StrictModel):
    schema_version: Literal["sckg-reference-artifact-revision-v1.1"] = (
        "sckg-reference-artifact-revision-v1.1"
    )
    record_type: Literal["ReferenceArtifactRevision"] = "ReferenceArtifactRevision"
    entity_id: str = Field(pattern=r"^reference-artifact-revision:")
    artifact_id: str = Field(pattern=r"^reference-artifact:")
    version: str = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    species_taxa: list[str] = Field(default_factory=list)
    feature_namespace: str = Field(min_length=1)
    label_ontology_id: str | None = None
    scope_id: str = Field(pattern=r"^scope:")


EntityRecord = Annotated[
    Union[
        ScientificTask,
        Method,
        MethodVariant,
        ParameterDefinition,
        Limitation,
        SoftwareProject,
        Package,
        PackageRelease,
        Operator,
        OperatorRevision,
        ReferenceArtifact,
        ReferenceArtifactRevision,
    ],
    Field(discriminator="record_type"),
]


class RepresentationInstanceBinding(StrictModel):
    schema_version: Literal["sckg-representation-instance-binding-v1.1"] = (
        "sckg-representation-instance-binding-v1.1"
    )
    binding_id: str = Field(pattern=r"^representation-instance-binding:")
    owner: Literal["RepresentationLedger"] = "RepresentationLedger"
    ledger_id: str = Field(min_length=1)
    representation_record_id: str = Field(min_length=1)
    representation_type_id: str = Field(pattern=r"^representation-type:")
    constraint_id: str = Field(pattern=r"^representation-constraint:")
    satisfaction: Literal["satisfied", "unsatisfied", "unknown", "conflicting"]
    reason_codes: list[str] = Field(default_factory=list, max_length=16)


class AtomicClaimRevision(StrictModel):
    schema_version: Literal["sckg-atomic-claim-revision-v1.1"] = "sckg-atomic-claim-revision-v1.1"
    claim_id: str = Field(pattern=r"^claim:")
    claim_revision_id: str = Field(pattern=r"^claim-revision:")
    subject_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_id: str | None = None
    object_value: str | None = Field(default=None, max_length=320)
    scope_id: str = Field(pattern=r"^scope:")
    claim_text: str = Field(min_length=1, max_length=500)
    polarity: Literal["positive", "negative"]
    assertion_kind: Literal[
        "definition", "capability", "requirement", "recommendation", "empirical_observation", "limitation"
    ]
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_revision_ids: list[str] = Field(default_factory=list, max_length=8)
    created_by_activity_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_object(self) -> "AtomicClaimRevision":
        if (self.object_id is None) == (self.object_value is None):
            raise ValueError("exactly one claim object is required")
        return self


class EvidenceAssessment(StrictModel):
    schema_version: Literal["sckg-evidence-assessment-v1.1"] = "sckg-evidence-assessment-v1.1"
    assessment_id: str = Field(pattern=r"^evidence-assessment:")
    claim_revision_id: str = Field(pattern=r"^claim-revision:")
    evidence_span_ids: list[str] = Field(min_length=1, max_length=8)
    stance: Literal["supports", "refutes", "partial_support", "mentions_only", "not_supporting"]
    subject_aligned: bool
    predicate_aligned: bool
    object_aligned: bool
    scope_alignment: Literal["aligned", "narrower", "partial", "unknown", "conflicting"]
    rationale: str = Field(min_length=1, max_length=500)
    review_decision_ids: list[str] = Field(default_factory=list, max_length=8)


class ReviewDecision(StrictModel):
    schema_version: Literal["sckg-review-decision-v1.1"] = "sckg-review-decision-v1.1"
    review_decision_id: str = Field(pattern=r"^review:")
    risk_class: Literal["R0", "R1", "R2", "R3", "R4"]
    reviewer_type: Literal["automated_validator", "qualified_human", "designated_owner"]
    decision: Literal["accepted", "rejected", "needs_revision"]
    reviewed_record_ids: list[str] = Field(min_length=1, max_length=16)
    rationale: str = Field(min_length=1, max_length=500)
    reviewed_artifact_hashes: list[str] = Field(min_length=1, max_length=16)
    policy_version: str = Field(min_length=1)
    decided_at: datetime
    independent_second_review_ids: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_assurance(self) -> "ReviewDecision":
        if self.risk_class in {"R3", "R4"} and self.reviewer_type == "automated_validator":
            raise ValueError("high-risk decisions require qualified human or designated-owner review")
        if (
            self.risk_class == "R4"
            and self.reviewer_type != "designated_owner"
            and not self.independent_second_review_ids
        ):
            raise ValueError("R4 decisions require a designated owner or independent second review")
        return self


class DerivedRelation(StrictModel):
    schema_version: Literal["sckg-derived-relation-v1.1"] = "sckg-derived-relation-v1.1"
    relation_id: str = Field(pattern=r"^derived-relation:")
    relation: Literal["CONSUMES", "PRODUCES", "CAN_FEED", "REQUIRES_BEFORE"]
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    scope_id: str = Field(pattern=r"^scope:")
    derivation_type: Literal["port_projection", "reviewed_rule"]
    input_port_id: str | None = None
    output_port_id: str | None = None
    requirement_id: str | None = None
    premise_relation_ids: list[str] = Field(default_factory=list, max_length=8)
    derived_from_claim_revision_ids: list[str] = Field(default_factory=list, max_length=16)
    derivation_rule_id: str = Field(min_length=1)
    review_status: Literal["candidate_pending_review", "accepted", "rejected"]
    review_decision_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_derivation(self) -> "DerivedRelation":
        if self.relation == "CONSUMES":
            if self.derivation_type != "port_projection" or not self.input_port_id or self.output_port_id:
                raise ValueError("CONSUMES must be projected from exactly one input port")
        elif self.relation == "PRODUCES":
            if self.derivation_type != "port_projection" or not self.output_port_id or self.input_port_id:
                raise ValueError("PRODUCES must be projected from exactly one output port")
        elif self.relation == "CAN_FEED":
            if self.derivation_type != "reviewed_rule" or not self.input_port_id or not self.output_port_id:
                raise ValueError("CAN_FEED requires reviewed input/output port premises")
            if not self.premise_relation_ids:
                raise ValueError("CAN_FEED requires premise relations")
            if self.review_status == "accepted" and not self.review_decision_ids:
                raise ValueError("CAN_FEED requires risk-appropriate review")
        else:
            if self.derivation_type != "reviewed_rule" or not self.requirement_id:
                raise ValueError("REQUIRES_BEFORE requires a reviewed requirement premise")
            if self.review_status == "accepted" and not self.review_decision_ids:
                raise ValueError("REQUIRES_BEFORE requires explicit high-risk review")
        return self


class MetricDefinition(StrictModel):
    schema_version: Literal["sckg-metric-definition-v1.1"] = "sckg-metric-definition-v1.1"
    metric_id: str = Field(pattern=r"^metric:")
    label: str = Field(min_length=1)
    direction: Literal["higher_is_better", "lower_is_better", "target_value", "descriptive"]
    unit: str | None = None


class EvaluationDataset(StrictModel):
    schema_version: Literal["sckg-evaluation-dataset-v1.1"] = "sckg-evaluation-dataset-v1.1"
    dataset_id: str = Field(pattern=r"^evaluation-dataset:")
    revision: str = Field(min_length=1)
    modalities: list[str] = Field(min_length=1)
    organism_taxa: list[str] = Field(default_factory=list)
    observation_unit: str = Field(min_length=1)
    study_design: list[str] = Field(min_length=1)
    split_definition: str = Field(min_length=1)
    leakage_controls: list[str] = Field(min_length=1)
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_id: str = Field(pattern=r"^scope:")


class BenchmarkStudy(StrictModel):
    schema_version: Literal["sckg-benchmark-study-v1.1"] = "sckg-benchmark-study-v1.1"
    benchmark_id: str = Field(pattern=r"^benchmark-study:")
    revision: str = Field(min_length=1)
    task_id: str = Field(pattern=r"^task:")
    scope_id: str = Field(pattern=r"^scope:")
    evaluated_subject_ids: list[str] = Field(min_length=1)
    dataset_ids: list[str] = Field(min_length=1)
    metric_ids: list[str] = Field(min_length=1)
    comparison_protocol: str = Field(min_length=1, max_length=500)
    evidence_span_ids: list[str] = Field(min_length=1)


class EmpiricalResult(StrictModel):
    schema_version: Literal["sckg-empirical-result-v1.1"] = "sckg-empirical-result-v1.1"
    result_id: str = Field(pattern=r"^empirical-result:")
    benchmark_id: str = Field(pattern=r"^benchmark-study:")
    dataset_id: str = Field(pattern=r"^evaluation-dataset:")
    subject_id: str = Field(min_length=1)
    metric_id: str = Field(pattern=r"^metric:")
    value: float
    uncertainty: str | None = Field(default=None, max_length=120)
    aggregation_unit: str = Field(min_length=1)
    scope_id: str = Field(pattern=r"^scope:")
    evidence_span_ids: list[str] = Field(min_length=1)
    status: Literal["reported", "verified_local", "not_comparable"]


class SupersessionRecord(StrictModel):
    schema_version: Literal["sckg-supersession-v1.1"] = "sckg-supersession-v1.1"
    supersession_id: str = Field(pattern=r"^supersession:")
    old_revision_id: str = Field(min_length=1)
    new_revision_id: str = Field(min_length=1)
    relation: Literal["SUPERSEDES", "DEPRECATED_BY"]
    scope_id: str = Field(pattern=r"^scope:")
    reason: str = Field(min_length=1, max_length=500)
    effective_at: datetime
    derived_from_claim_revision_ids: list[str] = Field(min_length=1)
    review_decision_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_self_supersession(self) -> "SupersessionRecord":
        if self.old_revision_id == self.new_revision_id:
            raise ValueError("a revision cannot supersede itself")
        return self


class ConformanceBundle(StrictModel):
    schema_version: Literal["sckg-scientific-knowledge-conformance-bundle-v1.1"] = (
        "sckg-scientific-knowledge-conformance-bundle-v1.1"
    )
    fixture_id: str = Field(pattern=r"^conformance-fixture:")
    description: str = Field(min_length=1)
    scopes: list[ApplicabilityScope] = Field(default_factory=list)
    representation_types: list[RepresentationType] = Field(default_factory=list)
    representation_constraints: list[RepresentationConstraint] = Field(default_factory=list)
    entities: list[EntityRecord] = Field(default_factory=list)
    instance_bindings: list[RepresentationInstanceBinding] = Field(default_factory=list)
    atomic_claims: list[AtomicClaimRevision] = Field(default_factory=list)
    evidence_assessments: list[EvidenceAssessment] = Field(default_factory=list)
    review_decisions: list[ReviewDecision] = Field(default_factory=list)
    derived_relations: list[DerivedRelation] = Field(default_factory=list)
    metrics: list[MetricDefinition] = Field(default_factory=list)
    evaluation_datasets: list[EvaluationDataset] = Field(default_factory=list)
    benchmark_studies: list[BenchmarkStudy] = Field(default_factory=list)
    empirical_results: list[EmpiricalResult] = Field(default_factory=list)
    supersessions: list[SupersessionRecord] = Field(default_factory=list)
    expected_semantics: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "ConformanceBundle":
        scope_ids = {item.scope_id for item in self.scopes}
        constraint_ids = {item.constraint_id for item in self.representation_constraints}
        representation_ids = {item.representation_type_id for item in self.representation_types}
        entity_ids = {item.entity_id for item in self.entities}
        input_port_ids = {
            port.input_port_id
            for item in self.entities
            if isinstance(item, OperatorRevision)
            for port in item.input_ports
        }
        output_port_ids = {
            port.output_port_id
            for item in self.entities
            if isinstance(item, OperatorRevision)
            for port in item.output_ports
        }
        requirement_ids = {
            requirement.requirement_id
            for item in self.entities
            if isinstance(item, OperatorRevision)
            for port in item.input_ports
            for requirement in port.requirements
        }
        relation_ids = {item.relation_id for item in self.derived_relations}
        review_ids = {item.review_decision_id for item in self.review_decisions}
        metric_ids = {item.metric_id for item in self.metrics}
        dataset_ids = {item.dataset_id for item in self.evaluation_datasets}
        benchmark_ids = {item.benchmark_id for item in self.benchmark_studies}
        if any(item.scope_id not in scope_ids for item in self.representation_constraints):
            raise ValueError("representation constraint references unknown scope")
        if any(item.representation_type_id not in representation_ids for item in self.representation_constraints):
            raise ValueError("representation constraint references unknown type")
        representation_by_id = {
            item.representation_type_id: item for item in self.representation_types
        }
        for constraint in self.representation_constraints:
            known_roles = {
                component.role
                for component in representation_by_id[constraint.representation_type_id].components
            }
            if not set(constraint.required_component_roles) <= known_roles:
                raise ValueError("representation constraint references unknown component role")
        if any(
            constraint_id not in constraint_ids
            for scope in self.scopes
            for constraint_id in scope.representation_constraint_ids
        ):
            raise ValueError("applicability scope references unknown representation constraint")
        if any(item.constraint_id not in constraint_ids for item in self.instance_bindings):
            raise ValueError("runtime binding references unknown constraint")
        if any(item.representation_type_id not in representation_ids for item in self.instance_bindings):
            raise ValueError("runtime binding references unknown representation type")
        for entity in self.entities:
            if isinstance(entity, MethodVariant) and entity.method_id not in entity_ids:
                raise ValueError("method variant references unknown method")
            if isinstance(entity, Package) and entity.project_id not in entity_ids:
                raise ValueError("package references unknown project")
            if isinstance(entity, PackageRelease) and entity.package_id not in entity_ids:
                raise ValueError("package release references unknown package")
            if isinstance(entity, Operator) and entity.package_id not in entity_ids:
                raise ValueError("operator references unknown package")
            if isinstance(entity, ParameterDefinition) and entity.owner_operator_id not in entity_ids:
                raise ValueError("parameter definition references unknown operator")
            if isinstance(entity, OperatorRevision):
                if entity.operator_id not in entity_ids or entity.package_release_id not in entity_ids:
                    raise ValueError("operator revision identity chain is incomplete")
                if not set(entity.implements_method_ids) <= entity_ids:
                    raise ValueError("operator revision references unknown method")
                if not set(entity.implements_method_variant_ids) <= entity_ids:
                    raise ValueError("operator revision references unknown method variant")
                if entity.scope_id not in scope_ids:
                    raise ValueError("operator revision references unknown scope")
                for port in entity.input_ports:
                    if port.scope_id not in scope_ids:
                        raise ValueError("input port references unknown scope")
                    for requirement in port.requirements:
                        if requirement.scope_id not in scope_ids:
                            raise ValueError("input requirement references unknown scope")
                        if not set(requirement.representation_constraint_ids) <= constraint_ids:
                            raise ValueError("input requirement references unknown representation constraint")
                        if not set(requirement.reference_artifact_revision_ids) <= entity_ids:
                            raise ValueError("input requirement references unknown reference artifact revision")
                for port in entity.output_ports:
                    if port.scope_id not in scope_ids:
                        raise ValueError("output port references unknown scope")
                    if port.representation_type_id not in representation_ids:
                        raise ValueError("output port references unknown representation type")
            if isinstance(entity, ReferenceArtifactRevision) and entity.artifact_id not in entity_ids:
                raise ValueError("reference artifact revision references unknown artifact")
        all_scoped = [
            *self.atomic_claims,
            *self.derived_relations,
            *self.evaluation_datasets,
            *self.benchmark_studies,
            *self.empirical_results,
            *self.supersessions,
        ]
        if any(item.scope_id not in scope_ids for item in all_scoped):
            raise ValueError("record references unknown applicability scope")
        claim_ids = {item.claim_revision_id for item in self.atomic_claims}
        if any(item.subject_id not in entity_ids for item in self.atomic_claims):
            raise ValueError("atomic claim references unknown subject")
        if any(item.claim_revision_id not in claim_ids for item in self.evidence_assessments):
            raise ValueError("evidence assessment references unknown claim")
        if any(
            review_id not in review_ids
            for assessment in self.evidence_assessments
            for review_id in assessment.review_decision_ids
        ):
            raise ValueError("evidence assessment references unknown review decision")
        for relation in self.derived_relations:
            if relation.input_port_id and relation.input_port_id not in input_port_ids:
                raise ValueError("derived relation references unknown input port")
            if relation.output_port_id and relation.output_port_id not in output_port_ids:
                raise ValueError("derived relation references unknown output port")
            if relation.requirement_id and relation.requirement_id not in requirement_ids:
                raise ValueError("derived relation references unknown requirement")
            if not set(relation.premise_relation_ids) <= relation_ids:
                raise ValueError("derived relation references unknown premise relation")
            if not set(relation.derived_from_claim_revision_ids) <= claim_ids:
                raise ValueError("derived relation references unknown claim premise")
            if not set(relation.review_decision_ids) <= review_ids:
                raise ValueError("derived relation references unknown review decision")
        for study in self.benchmark_studies:
            if study.task_id not in entity_ids:
                raise ValueError("benchmark references unknown task")
            if not set(study.evaluated_subject_ids) <= entity_ids:
                raise ValueError("benchmark references unknown evaluated subject")
            if not set(study.dataset_ids) <= dataset_ids or not set(study.metric_ids) <= metric_ids:
                raise ValueError("benchmark references unknown dataset or metric")
        for result in self.empirical_results:
            if result.benchmark_id not in benchmark_ids or result.dataset_id not in dataset_ids:
                raise ValueError("empirical result references unknown benchmark or dataset")
            if result.subject_id not in entity_ids or result.metric_id not in metric_ids:
                raise ValueError("empirical result references unknown subject or metric")
        for supersession in self.supersessions:
            if supersession.old_revision_id not in entity_ids or supersession.new_revision_id not in entity_ids:
                raise ValueError("supersession references unknown revisions")
            if not set(supersession.derived_from_claim_revision_ids) <= claim_ids:
                raise ValueError("supersession references unknown claim premise")
            if not set(supersession.review_decision_ids) <= review_ids:
                raise ValueError("supersession references unknown review decision")
        return self
