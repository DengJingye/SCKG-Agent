from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


class CapabilityPackStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    QUALIFIED = "qualified"


class CapabilityReadiness(str, Enum):
    DISCOVERED = "discovered"
    PLANNING_READY = "planning_ready"
    NOTEBOOK_READY = "notebook_ready"
    VALIDATION_READY = "validation_ready"
    QUALIFICATION_PASSED = "qualification_passed"
    EXECUTION_ELIGIBLE = "execution_eligible"


class RepresentationValueState(str, Enum):
    NONNEGATIVE_INTEGER = "nonnegative_integer"
    NONNEGATIVE_CONTINUOUS = "nonnegative_continuous"
    REAL_CONTINUOUS = "real_continuous"
    BOOLEAN_MASK = "boolean_mask"
    CATEGORICAL = "categorical"
    GRAPH = "graph"
    TABLE = "table"


class RepresentationDefinition(StrictModel):
    representation_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    kind: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    axes: list[Literal["cell", "gene", "component", "edge", "cluster", "record"]]
    value_state: RepresentationValueState
    required_provenance: list[str] = Field(default_factory=list)
    require_cell_hash: bool = False
    require_gene_hash: bool = False
    required_metadata: list[str] = Field(default_factory=list)
    scientific_constraints: list[str] = Field(default_factory=list)


class RepresentationRequirement(StrictModel):
    representation_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    accepted_schema_versions: list[str] = Field(min_length=1)
    accepted_value_states: list[RepresentationValueState] = Field(min_length=1)
    required_provenance: list[str] = Field(default_factory=list)
    require_cell_hash: bool = False
    require_gene_hash: bool = False
    required_metadata: list[str] = Field(default_factory=list)
    scientific_requirements: list[str] = Field(default_factory=list)


class RepresentationProduction(StrictModel):
    representation_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    output_slot: str = Field(min_length=1)
    preserves_cell_hash: bool = True
    preserves_gene_hash: bool = True
    irreversible: bool = False


class RepresentationCompatibilityResult(StrictModel):
    producer_representation_id: str
    consumer_representation_id: str
    structural_compatible: bool
    scientific_compatible: bool
    provenance_compatible: bool
    hash_compatible: bool
    blocking_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reasons(self) -> "RepresentationCompatibilityResult":
        compatible = (
            self.structural_compatible
            and self.scientific_compatible
            and self.provenance_compatible
            and self.hash_compatible
        )
        if compatible and self.blocking_reasons:
            raise ValueError("compatible representations cannot have blocking reasons")
        if not compatible and not self.blocking_reasons:
            raise ValueError("incompatible representations require blocking reasons")
        return self


class StateRequirement(StrictModel):
    requirement_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    blocking: bool = True


class ValidationPipelineBinding(StrictModel):
    generic_primitives: list[str] = Field(min_length=1)
    scientific_validator_id: str = Field(min_length=1)


class ExecutionAdapterBinding(StrictModel):
    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    runtime_kind: Literal["python_module", "rscript", "container"]
    entrypoint: list[str] = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    allowlisted: bool = False


class NotebookRendererBinding(StrictModel):
    renderer_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    renderer_version: str = Field(min_length=1)
    maintainer_reviewed: bool = False


class EvidenceBinding(StrictModel):
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    source_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_span: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    authority: Literal["official_documentation", "primary_publication", "benchmark"]
    review_status: Literal["candidate", "reviewed"] = "candidate"


class GoldCaseBinding(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    dataset_ref: str = Field(min_length=1)
    split: Literal["development", "evaluation", "hidden"]
    applicable_metrics: list[str] = Field(min_length=1)


class MethodBinding(StrictModel):
    method_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    implementation_kind: Literal[
        "tool", "human_review", "composed_action", "method_family"
    ]
    consumes: list[RepresentationRequirement] = Field(default_factory=list)
    produces: list[RepresentationProduction] = Field(min_length=1)
    requires: list[StateRequirement] = Field(default_factory=list)
    invalid_predecessors: list[str] = Field(default_factory=list)
    tool_contract_ref: str | None = None
    action_bundle_ref: str | None = None
    step_contract_ref: str = Field(min_length=1)
    environment_id: str | None = None
    execution_adapter_id: str | None = None
    notebook_renderer_id: str | None = None
    validation_pipeline: ValidationPipelineBinding
    evidence_ids: list[str] = Field(default_factory=list)
    gold_case_ids: list[str] = Field(default_factory=list)
    optional: bool = False


class CapabilityDefinition(StrictModel):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    task_family: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ComposedActionBinding(StrictModel):
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    action_bundle_ref: str = Field(min_length=1)
    method_ids: list[str] = Field(min_length=1)
    placement_after: str
    placement_before: str
    changes_cell_set: bool = False
    explicit_confirmation_required: bool = False


class MethodImplementationBinding(StrictModel):
    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    method_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    tool_contract_ref: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    execution_adapter_ref: str | None = None
    status: Literal["candidate", "planning_only", "qualified"]
    evidence_ids: list[str] = Field(min_length=1)
    execution_eligible: bool = False

    @model_validator(mode="after")
    def validate_execution_claim(self) -> "MethodImplementationBinding":
        if self.execution_eligible and self.status != "qualified":
            raise ValueError("only qualified method bindings can be execution eligible")
        return self


class CapabilityPackManifest(StrictModel):
    schema_version: Literal["sckg-capability-pack-v1"] = "sckg-capability-pack-v1"
    pack_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    pack_version: str = Field(min_length=1)
    status: CapabilityPackStatus = CapabilityPackStatus.DRAFT
    task_families: list[str] = Field(min_length=1)
    workspace_targets: list[str] = Field(default_factory=list)
    capabilities: list[CapabilityDefinition] = Field(min_length=1)
    representation_contracts: list[RepresentationDefinition] = Field(min_length=1)
    methods: list[MethodBinding] = Field(min_length=1)
    composed_actions: list[ComposedActionBinding] = Field(default_factory=list)
    implementation_bindings: list[MethodImplementationBinding] = Field(
        default_factory=list
    )
    execution_adapters: list[ExecutionAdapterBinding] = Field(default_factory=list)
    notebook_renderers: list[NotebookRendererBinding] = Field(default_factory=list)
    evidence_bindings: list[EvidenceBinding] = Field(default_factory=list)
    gold_case_bindings: list[GoldCaseBinding] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    content_digest: str = Field(min_length=64, max_length=64)


class CapabilityPackGateResult(StrictModel):
    pack_id: str
    pack_version: str
    readiness: list[CapabilityReadiness]
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    content_digest_valid: bool
    execution_eligible: bool = False
    qualification_claimed: bool = False

    @model_validator(mode="after")
    def validate_execution_gate(self) -> "CapabilityPackGateResult":
        if self.execution_eligible and (
            not self.passed
            or CapabilityReadiness.QUALIFICATION_PASSED not in self.readiness
        ):
            raise ValueError("execution eligibility requires qualification")
        return self


class CapabilityDiscoveryRecord(StrictModel):
    pack_id: str
    pack_version: str
    capability_id: str
    method_ids: list[str]
    readiness: list[CapabilityReadiness]
    execution_eligible: bool
    blockers: list[str] = Field(default_factory=list)


def compatibility_check(
    *,
    producer: RepresentationDefinition,
    consumer: RepresentationRequirement,
    producer_provenance: list[str] | None = None,
    producer_cell_hash: str | None = None,
    consumer_cell_hash: str | None = None,
    producer_gene_hash: str | None = None,
    consumer_gene_hash: str | None = None,
    producer_metadata: dict[str, Any] | None = None,
) -> RepresentationCompatibilityResult:
    reasons: list[str] = []
    structural = producer.schema_version in consumer.accepted_schema_versions
    if not structural:
        reasons.append("representation_schema_incompatible")
    if producer.value_state not in consumer.accepted_value_states:
        structural = False
        reasons.append("representation_value_state_incompatible")
    provenance = set(consumer.required_provenance) <= set(producer_provenance or [])
    if not provenance:
        reasons.append("required_provenance_missing")
    metadata = set((producer_metadata or {}).keys())
    scientific = set(consumer.required_metadata) <= metadata
    if not scientific:
        reasons.append("required_scientific_metadata_missing")
    if not set(consumer.scientific_requirements) <= set(producer.scientific_constraints):
        scientific = False
        reasons.append("scientific_constraints_unverified")
    hash_compatible = True
    if consumer.require_cell_hash:
        hash_compatible = bool(
            producer_cell_hash
            and consumer_cell_hash
            and producer_cell_hash == consumer_cell_hash
        )
        if not hash_compatible:
            reasons.append("cell_index_hash_mismatch")
    if consumer.require_gene_hash:
        gene_match = bool(
            producer_gene_hash
            and consumer_gene_hash
            and producer_gene_hash == consumer_gene_hash
        )
        hash_compatible = hash_compatible and gene_match
        if not gene_match:
            reasons.append("gene_index_hash_mismatch")
    return RepresentationCompatibilityResult(
        producer_representation_id=producer.representation_id,
        consumer_representation_id=consumer.representation_id,
        structural_compatible=structural,
        scientific_compatible=scientific,
        provenance_compatible=provenance,
        hash_compatible=hash_compatible,
        blocking_reasons=sorted(set(reasons)),
    )
