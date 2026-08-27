from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class TaskName(str, Enum):
    DOUBLET_DETECTION = "doublet_detection"
    BATCH_INTEGRATION = "batch_integration"
    CELL_TYPE_ANNOTATION = "cell_type_annotation"


class ModalityName(str, Enum):
    SCRNA_SEQ = "scRNA-seq"


class InputObjectType(str, Enum):
    ANNDATA = "AnnData"
    UNKNOWN = "unknown"


class Strictness(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    EXPLORATORY = "exploratory"


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    REVOKED = "revoked"


class MatrixState(str, Enum):
    RAW_COUNTS = "raw_counts"
    NORMALIZED = "normalized"
    LOG_NORMALIZED = "log_normalized"
    SCALED = "scaled"
    UNKNOWN = "unknown"


class InferenceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CountSourceMethod(str, Enum):
    EXPLICIT_USER = "explicit_user"
    TOOL_CONTRACT = "tool_contract"
    EXPLICIT_LAYER_NAME = "explicit_layer_name"
    DETERMINISTIC_RULE = "deterministic_rule"
    UNRESOLVED = "unresolved"


class ContractLanguage(str, Enum):
    PYTHON = "python"
    R = "r"


class SchemaStatus(str, Enum):
    DRAFT = "draft"
    VALID = "valid"
    INVALID = "invalid"


class SourceReviewStatus(str, Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    REVIEWED = "reviewed"


class WrapperStatus(str, Enum):
    MISSING = "missing"
    IMPLEMENTED = "implemented"
    SMOKE_PASSED = "smoke_passed"


class ContractEnvironmentStatus(str, Enum):
    MISSING = "missing"
    AVAILABLE = "available"
    SMOKE_PASSED = "smoke_passed"


class ContractExecutionStatus(str, Enum):
    UNTESTED = "untested"
    INTEGRATION_PASSED = "integration_passed"


class ScientificValidationStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    SYNTHETIC_ONLY = "synthetic_only"
    SCIENTIFIC_PILOT = "scientific_pilot"
    EXTERNALLY_EVALUATED = "externally_evaluated"


class PlanStatus(str, Enum):
    DRY_RUN = "dry_run"
    READY = "ready"
    BLOCKED = "blocked"
    APPROVED = "approved"


class EnvironmentQualificationStatus(str, Enum):
    MISSING = "missing"
    AVAILABLE = "available"
    IMPORT_QUALIFIED = "import_qualified"
    INTEGRATION_PASSED = "integration_passed"


class ResourceBudget(StrictModel):
    max_cells: int = Field(default=10_000, gt=0)
    max_runtime_seconds: int = Field(default=900, gt=0)
    max_memory_mb: Optional[int] = Field(default=None, gt=0)
    memory_enforcement: Literal["monitor_only", "hard_limit"] = "monitor_only"
    gpu_allowed: bool = False


class UserApproval(StrictModel):
    approval_state: ApprovalState = ApprovalState.PENDING
    approved_plan_id: Optional[str] = None
    approved_plan_hash: Optional[str] = None
    approved_budget_snapshot: Optional[Dict[str, Any]] = None
    approved_at: Optional[datetime] = None
    approval_revoked_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_approval_binding(self) -> "UserApproval":
        if self.approval_state == ApprovalState.APPROVED:
            required = {
                "approved_plan_id": self.approved_plan_id,
                "approved_plan_hash": self.approved_plan_hash,
                "approved_budget_snapshot": self.approved_budget_snapshot,
                "approved_at": self.approved_at,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("approved plan must bind: " + ", ".join(missing))
        if self.approval_state == ApprovalState.REVOKED and self.approval_revoked_at is None:
            raise ValueError("revoked approval requires approval_revoked_at")
        return self


class RequirementSpec(StrictModel):
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    task: TaskName = TaskName.DOUBLET_DETECTION
    modality: ModalityName = ModalityName.SCRNA_SEQ
    species: str = "unknown"
    platform: str = "unknown"
    input_path: Optional[str] = None
    input_object_type: InputObjectType = InputObjectType.UNKNOWN
    batch_key: Optional[str] = None
    label_key: Optional[str] = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    output_goal: str = "doublet scores and calls"
    strictness: Strictness = Strictness.CONSERVATIVE
    data_access_authorized: bool = False
    execution_authorized: bool = False
    user: UserApproval = Field(default_factory=UserApproval)

    @model_validator(mode="after")
    def validate_execution_approval(self) -> "RequirementSpec":
        if self.user.approval_state == ApprovalState.APPROVED and not self.execution_authorized:
            raise ValueError("plan approval requires execution_authorized=true")
        return self


class DataStateEvidence(StrictModel):
    state_name: str = Field(min_length=1)
    value: Any
    method: str = Field(min_length=1)
    sample_size: int = Field(default=0, ge=0)
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class MatrixProfile(StrictModel):
    matrix_id: str = Field(min_length=1)
    shape: tuple[int, int]
    dtype: str
    is_sparse: bool
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    negative_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    nonzero_integer_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    nan_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    inf_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    inferred_state: MatrixState = MatrixState.UNKNOWN
    inference_confidence: InferenceConfidence = InferenceConfidence.LOW
    state_evidence: List[DataStateEvidence] = Field(default_factory=list)
    eligible_tasks: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)

    @field_validator("shape")
    @classmethod
    def validate_shape(cls, value: tuple[int, int]) -> tuple[int, int]:
        if len(value) != 2 or any(item < 0 for item in value):
            raise ValueError("matrix shape must contain two non-negative dimensions")
        return value

    @field_validator("min_value", "max_value")
    @classmethod
    def validate_finite_extrema(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("matrix extrema must be finite or null")
        return value


class CountSourceSelection(StrictModel):
    method: CountSourceMethod = CountSourceMethod.UNRESOLVED
    evidence: List[str] = Field(default_factory=list)


class DataProfile(StrictModel):
    profile_id: str = Field(min_length=1)
    file_path_redacted: str
    file_hash: str = ""
    file_size_bytes: int = Field(default=0, ge=0)
    object_type: InputObjectType = InputObjectType.UNKNOWN
    n_cells: int = Field(default=0, ge=0)
    n_genes: int = Field(default=0, ge=0)
    raw_exists: bool = False
    layers: List[str] = Field(default_factory=list)
    obsm_keys: List[str] = Field(default_factory=list)
    obsp_keys: List[str] = Field(default_factory=list)
    obs_keys: List[str] = Field(default_factory=list)
    var_keys: List[str] = Field(default_factory=list)
    batch_key: Optional[str] = None
    batch_count: Optional[int] = Field(default=None, ge=0)
    batch_missing_count: int = Field(default=0, ge=0)
    batch_min_cells: Optional[int] = Field(default=None, ge=0)
    batch_max_cells: Optional[int] = Field(default=None, ge=0)
    batch_imbalance_ratio: Optional[float] = Field(default=None, ge=1.0)
    label_key: Optional[str] = None
    label_count: Optional[int] = Field(default=None, ge=0)
    label_missing_count: int = Field(default=0, ge=0)
    has_pca: bool = False
    pca_n_components: Optional[int] = Field(default=None, ge=0)
    pca_finite: Optional[bool] = None
    has_neighbors: bool = False
    has_clustering: bool = False
    matrix_profiles: List[MatrixProfile] = Field(default_factory=list)
    selected_count_source: Optional[str] = None
    count_source_selection: CountSourceSelection = Field(default_factory=CountSourceSelection)
    warnings: List[str] = Field(default_factory=list)
    blocking_errors: List[str] = Field(default_factory=list)
    profile_version: str = "anndata-profiler-v1"

    @model_validator(mode="after")
    def validate_count_source(self) -> "DataProfile":
        by_id = {profile.matrix_id: profile for profile in self.matrix_profiles}
        if self.selected_count_source is not None:
            selected = by_id.get(self.selected_count_source)
            if selected is None:
                raise ValueError("selected_count_source must identify a matrix profile")
            if selected.inferred_state != MatrixState.RAW_COUNTS:
                raise ValueError("selected_count_source must be inferred as raw_counts")
        if self.count_source_selection.method == CountSourceMethod.UNRESOLVED:
            if self.selected_count_source is not None:
                raise ValueError("unresolved count source cannot select a matrix")
            if "count_source_unresolved" not in self.blocking_errors:
                raise ValueError("unresolved count source must be blocking")
        return self

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocking_errors)


class AnnotationDataProfile(StrictModel):
    profile_id: str = Field(min_length=1)
    file_path_redacted: str
    file_hash: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(ge=0)
    n_genes: int = Field(ge=0)
    expression_source: str = Field(min_length=1)
    expression_state: Literal[
        "raw_counts",
        "log1p_normalized",
        "scaled",
        "unknown",
    ]
    normalization_target: Literal[
        "ready_log1p_10000",
        "normalize_log1p_10000",
        "rank_based_compatible",
        "blocked",
    ]
    gene_identifier_type: Literal[
        "gene_symbol",
        "ensembl_human",
        "ensembl_mouse",
        "mixed",
        "unknown",
    ]
    species: Literal["human", "mouse", "unknown"]
    duplicate_gene_count: int = Field(default=0, ge=0)
    reference_id: str = ""
    reference_digest: str = ""
    reference_gene_count: int = Field(default=0, ge=0)
    overlapping_gene_count: int = Field(default=0, ge=0)
    gene_overlap_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: List[str] = Field(default_factory=list)
    blocking_errors: List[str] = Field(default_factory=list)
    profile_version: str = "annotation-profiler-v1"

    @model_validator(mode="after")
    def validate_annotation_profile(self) -> "AnnotationDataProfile":
        if self.normalization_target == "blocked" and not self.blocking_errors:
            raise ValueError("blocked annotation profile requires a blocking reason")
        if self.reference_id and not self.reference_digest:
            raise ValueError("selected annotation reference requires a digest")
        if self.reference_gene_count == 0 and self.overlapping_gene_count:
            raise ValueError("gene overlap requires a reference gene set")
        return self

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocking_errors)


class AnnotationReferenceManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    reference_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    tool_name: Literal["CellTypist", "SingleR"]
    reference_type: Literal["celltypist_model", "singler_reference"]
    version: str = Field(min_length=1)
    species: Literal["human", "mouse"]
    tissue_scope: List[str] = Field(default_factory=list)
    label_ontology_version: str = Field(min_length=1)
    gene_identifier_type: Literal["gene_symbol", "ensembl_human", "ensembl_mouse"]
    gene_count: int = Field(gt=0)
    labels: List[str] = Field(min_length=1)
    local_path: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    gene_list_path: str = Field(min_length=1)
    gene_list_sha256: str = Field(min_length=64, max_length=64)
    source_url: str = Field(min_length=1)
    license: str = Field(min_length=1)
    runtime_network_allowed: bool = False
    qualification_status: Literal["manifest_only", "verified", "pilot_passed"] = (
        "manifest_only"
    )


class AnnotationLabelMapping(StrictModel):
    mapping_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    version: str = Field(min_length=1)
    source_labels: List[str] = Field(default_factory=list)
    canonical_labels: List[str] = Field(default_factory=list)
    mapping: Dict[str, str] = Field(default_factory=dict)
    unknown_label: str = "unknown"
    mapping_digest: str = Field(min_length=64, max_length=64)
    ai_generated: bool = False


class TaskDataEligibility(StrictModel):
    task: TaskName
    allowed: bool
    selected_representation: Optional[str] = None
    batch_key: Optional[str] = None
    batch_count: Optional[int] = Field(default=None, ge=0)
    biology_label_mode: Literal["available", "degraded_no_label", "not_applicable"] = (
        "not_applicable"
    )
    blocking_reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    checks: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_allowed_state(self) -> "TaskDataEligibility":
        if self.allowed and self.blocking_reasons:
            raise ValueError("allowed task eligibility cannot contain blocking reasons")
        if not self.allowed and not self.blocking_reasons:
            raise ValueError("blocked task eligibility requires a reason")
        return self


class ContractRule(StrictModel):
    rule_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    operator: Literal["exists", "equals", "in", "gte", "lte", "matrix_state"]
    expected: Any = None
    blocking: bool = True
    message: str = ""


class ArtifactSpec(StrictModel):
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    format: str = Field(min_length=1)
    required: bool = True
    validator_id: str = Field(min_length=1)


class ParameterProvenance(StrictModel):
    parameter_name: str
    value_or_range: Any
    origin_type: Literal[
        "contract_default",
        "source_bound_prior",
        "user_override",
        "empirical_search",
        "repair_action",
    ]
    source_type: Literal[
        "official_default",
        "official_tutorial",
        "primary_paper",
        "benchmark",
        "internal_run",
        "user",
        "policy_rule",
    ]
    source_id: Optional[str] = None
    source_span: Optional[str] = None
    tool_version: Optional[str] = None
    run_id: Optional[str] = None
    policy_rule_id: Optional[str] = None
    applicable_scope: str = ""
    limitations: List[str] = Field(default_factory=list)


class ToolContract(StrictModel):
    contract_id: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    task: str = Field(min_length=1)
    language: ContractLanguage
    environment_id: str = Field(min_length=1)
    wrapper_id: str = Field(min_length=1)
    input_object: InputObjectType
    required_fields: List[str] = Field(default_factory=list)
    optional_fields: List[str] = Field(default_factory=list)
    preconditions: List[ContractRule] = Field(default_factory=list)
    not_supported: List[str] = Field(default_factory=list)
    output_artifacts: List[ArtifactSpec] = Field(default_factory=list)
    parameter_schema: Dict[str, Any]
    default_parameters: Dict[str, Any] = Field(default_factory=dict)
    paper_parameters: List[ParameterProvenance] = Field(default_factory=list)
    searchable_parameters: Dict[str, Any] = Field(default_factory=dict)
    failure_checks: List[str] = Field(default_factory=list)
    validation_metrics: List[str] = Field(default_factory=list)
    resource_requirements: Dict[str, Any] = Field(default_factory=dict)
    source_refs: List[str] = Field(default_factory=list)
    execution_critical_review: Dict[str, Any] = Field(default_factory=dict)
    schema_status: SchemaStatus = SchemaStatus.DRAFT
    source_review_status: SourceReviewStatus = SourceReviewStatus.MISSING
    execution_critical_fields_reviewed: bool = False
    wrapper_status: WrapperStatus = WrapperStatus.MISSING
    environment_status: ContractEnvironmentStatus = ContractEnvironmentStatus.MISSING
    execution_status: ContractExecutionStatus = ContractExecutionStatus.UNTESTED
    scientific_validation_status: ScientificValidationStatus = ScientificValidationStatus.NOT_EVALUATED
    action_space_registration: Literal["candidate", "admitted"] = "admitted"
    enabled_for_execution: bool = False

    @model_validator(mode="after")
    def validate_contract_consistency(self) -> "ToolContract":
        if self.input_object != InputObjectType.ANNDATA:
            raise ValueError("Phase 1 tool contracts only support AnnData")
        if self.parameter_schema.get("type") != "object":
            raise ValueError("parameter_schema must be a JSON object schema")
        properties = self.parameter_schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("parameter_schema.properties must be an object")
        unknown_defaults = sorted(set(self.default_parameters) - set(properties))
        if unknown_defaults:
            raise ValueError("default parameters absent from schema: " + ", ".join(unknown_defaults))
        if self.enabled_for_execution and not self.execution_gate_fields_satisfied:
            raise ValueError("enabled_for_execution requires every execution gate field")
        return self

    @property
    def planning_gate_fields_satisfied(self) -> bool:
        return (
            self.schema_status == SchemaStatus.VALID
            and self.source_review_status in {SourceReviewStatus.PARTIAL, SourceReviewStatus.REVIEWED}
            and bool(self.wrapper_id)
            and self.parameter_schema.get("type") == "object"
            and isinstance(self.parameter_schema.get("properties"), dict)
        )

    @property
    def execution_gate_fields_satisfied(self) -> bool:
        return (
            self.schema_status == SchemaStatus.VALID
            and self.source_review_status == SourceReviewStatus.REVIEWED
            and self.execution_critical_fields_reviewed
            and self.wrapper_status == WrapperStatus.SMOKE_PASSED
            and self.environment_status == ContractEnvironmentStatus.SMOKE_PASSED
            and self.execution_status == ContractExecutionStatus.INTEGRATION_PASSED
        )


class ExecutionBudget(StrictModel):
    max_initial_runs: int = Field(default=12, ge=0)
    reserved_repair_runs: int = Field(default=4, ge=0)
    reserved_validation_reruns: int = Field(default=2, ge=0)
    max_total_runs: int = Field(default=18, gt=0)
    max_concurrent_runs: int = Field(default=1, gt=0)
    timeout_seconds: int = Field(default=900, gt=0)

    @model_validator(mode="after")
    def validate_total(self) -> "ExecutionBudget":
        allocated = self.max_initial_runs + self.reserved_repair_runs + self.reserved_validation_reruns
        if allocated > self.max_total_runs:
            raise ValueError("allocated run budget exceeds max_total_runs")
        return self


class WorkflowNode(StrictModel):
    node_id: str
    name: str
    operation: str
    tool_name: Optional[str] = None
    tool_contract_id: str
    input_artifacts: List[str] = Field(default_factory=list)
    output_artifacts: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    parameter_provenance: List[ParameterProvenance] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    failure_policy: str = "block"
    skippable: bool = False


class WorkflowEdge(StrictModel):
    source_node_id: str
    target_node_id: str
    artifact_id: Optional[str] = None


class WorkflowPlan(StrictModel):
    plan_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    steps: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    candidate_tools: List[str] = Field(default_factory=list)
    selected_probe_tools: List[str] = Field(default_factory=list)
    parameter_search_space: Dict[str, Any] = Field(default_factory=dict)
    execution_budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    expected_outputs: List[ArtifactSpec] = Field(default_factory=list)
    blocking_conditions: List[str] = Field(default_factory=list)
    execution_blockers: List[str] = Field(default_factory=list)
    planning_warnings: List[str] = Field(default_factory=list)
    data_awareness: Literal["generic", "data_aware"] = "generic"
    execution_eligible: bool = False
    approval_required: bool = True
    plan_status: PlanStatus = PlanStatus.DRY_RUN

    @model_validator(mode="after")
    def validate_plan_state(self) -> "WorkflowPlan":
        if self.blocking_conditions and self.plan_status != PlanStatus.BLOCKED:
            raise ValueError("plans with blocking_conditions must be blocked")
        if self.plan_status == PlanStatus.APPROVED and self.approval_required:
            raise ValueError("approved plan cannot still require approval")
        if self.execution_eligible and self.plan_status in {PlanStatus.DRY_RUN, PlanStatus.BLOCKED}:
            raise ValueError("dry-run or blocked plan cannot be execution eligible")
        return self


class ProbeSpec(StrictModel):
    probe_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    profile_id: str
    source_fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    sampling_strategy: Literal["random"] = "random"
    max_cells: int = Field(gt=0)
    random_seed: int = Field(ge=0)
    selected_obs_indices_hash: str = Field(min_length=64, max_length=64)
    synthetic_doublet_ratio: float = Field(gt=0.0, le=1.0)
    synthetic_generation_method: Literal["count_sum"] = "count_sum"
    synthetic_generation_version: str = "count-sum-v1"
    pairing_strategy: Literal[
        "random", "within_cluster", "between_cluster", "mixed"
    ] = "random"
    split_role: Literal["engineering", "development", "evaluation"] = "engineering"
    cluster_key: Optional[str] = None
    ground_truth_available: bool = True
    ground_truth_type: Literal["synthetic"] = "synthetic"
    ground_truth_hash: Optional[str] = Field(default=None, min_length=64, max_length=64)
    n_source_cells: int = Field(gt=0)
    n_synthetic_doublets: int = Field(gt=0)
    n_probe_cells: int = Field(gt=0)
    probe_artifact_path: str
    probe_hash: str = Field(min_length=64, max_length=64)
    metadata_path: str
    source_input_hash: str = Field(min_length=64, max_length=64)
    source_unchanged: bool = True
    scientific_claim_allowed: bool = False


class ActorContext(StrictModel):
    actor_id: str = Field(min_length=1)
    role: Literal["maintainer", "user"]


class ApprovalScope(StrictModel):
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    parameter_hash: str = Field(min_length=64, max_length=64)

    @property
    def fingerprint(self) -> str:
        import hashlib
        import json

        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


class QualificationContext(StrictModel):
    mode: bool = False
    purpose: Literal[
        "synthetic_qualification", "scientific_pilot", "representative_preview"
    ] = (
        "synthetic_qualification"
    )
    authorized: bool = False
    fixture_allowlisted: bool = False
    fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")


class QualificationArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    path: str
    sha256: str = Field(min_length=64, max_length=64)
    synthetic: bool
    public_dataset: bool = False
    user_data: bool = False
    accession: Optional[str] = None
    allowlisted: bool
    expected_cells: int = Field(gt=0)


class RestrictedUserExecutionContext(StrictModel):
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    approval_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    allowance_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    request_fingerprint: str = Field(min_length=64, max_length=64)
    contract_version: str
    tool_name: str
    tool_version: str
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    parameter_hash: str = Field(min_length=64, max_length=64)
    approval_consumption_index: int = Field(ge=1)
    approval_max_uses: int = Field(ge=1)
    access_origin: Literal["local"] = "local"
    approval_consumed: bool = True


class ExecutionRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    trace_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    step_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    wrapper_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    input_artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    execution_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    parameters: Dict[str, Any]
    parameter_provenance: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(gt=0, le=900)
    artifact_policy_id: Literal["default_run_artifacts"] = "default_run_artifacts"
    actor: ActorContext
    qualification: QualificationContext
    execution_mode: Literal["qualification", "restricted_local_user"] = "qualification"
    user_execution: Optional[RestrictedUserExecutionContext] = None

    @model_validator(mode="after")
    def validate_execution_mode(self) -> "ExecutionRequest":
        if self.execution_mode == "restricted_local_user":
            if self.actor.role != "user" or self.user_execution is None:
                raise ValueError("restricted user execution requires user actor and context")
            if self.qualification.mode:
                raise ValueError("restricted user execution cannot claim qualification mode")
        elif self.user_execution is not None:
            raise ValueError("qualification request cannot contain user execution context")
        return self


class ProcessCleanup(StrictModel):
    timeout_triggered: bool = False
    terminate_sent: bool = False
    kill_sent: bool = False
    child_processes_seen: int = Field(default=0, ge=0)
    residual_processes: List[int] = Field(default_factory=list)
    cancellation_triggered: bool = False
    cancellation_reason: Optional[str] = None


class ExecutionRun(StrictModel):
    request_id: str
    run_id: str
    trace_id: str
    plan_id: str
    step_id: str
    wrapper_id: str
    tool_name: str
    tool_version: str
    environment_id: str
    command_argv_redacted: List[str]
    parameters: Dict[str, Any]
    execution_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    parameter_provenance: Dict[str, Any] = Field(default_factory=dict)
    input_hash: str
    start_time: datetime
    end_time: datetime
    runtime_seconds: float = Field(ge=0.0)
    peak_memory_mb: Optional[float] = Field(default=None, ge=0.0)
    memory_enforcement: Literal["monitor_only"] = "monitor_only"
    exit_code: Optional[int] = None
    stdout_path: str
    stderr_path: str
    artifact_paths: Dict[str, str] = Field(default_factory=dict)
    artifact_hashes: Dict[str, str] = Field(default_factory=dict)
    status: Literal[
        "queued", "running", "succeeded", "failed", "timeout", "cancelled", "blocked"
    ]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    process_cleanup: ProcessCleanup = Field(default_factory=ProcessCleanup)
    qualification_mode: bool = True
    fixture_id: str
    synthetic_fixture: bool = True
    public_dataset: bool = False
    user_data_used: bool = False
    execution_purpose: Literal[
        "synthetic_qualification", "scientific_pilot", "representative_preview"
    ] = (
        "synthetic_qualification"
    )
    owner_user_id: Optional[str] = None
    approval_id: Optional[str] = None


class ValidationResult(StrictModel):
    validation_id: str
    run_id: str
    passed: bool
    artifact_checks: Dict[str, Any] = Field(default_factory=dict)
    task_metrics: Dict[str, Any] = Field(default_factory=dict)
    sanity_checks: Dict[str, Any] = Field(default_factory=dict)
    stability_metrics: Dict[str, Any] = Field(default_factory=dict)
    resource_metrics: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)
    eligible_for_candidate_aggregation: bool = False
    repairable: bool = False
    metric_authority: Literal[
        "synthetic_engineering_metric",
        "scientific_pilot_metric",
        "preview_engineering_metric",
    ] = (
        "synthetic_engineering_metric"
    )
    validation_version: str = "doublet-validator-v1"


class AnnotationValidationResult(ValidationResult):
    validation_version: Literal["annotation-validator-v1"] = "annotation-validator-v1"


class ConfigurationSpec(StrictModel):
    configuration_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    configuration_hash: str = Field(min_length=64, max_length=64)
    parameters: Dict[str, Any]
    parameter_provenance: Dict[str, Any]
    source: Literal[
        "contract_default", "contract_searchable_range", "development_probe_search"
    ]
    frozen: bool = False


class ExperimentRunRecord(StrictModel):
    run_id: str
    configuration_id: str
    configuration_hash: str = Field(min_length=64, max_length=64)
    seed: int = Field(ge=0)
    split_role: Literal["development", "evaluation"]
    probe_hash: str = Field(min_length=64, max_length=64)
    parameters: Dict[str, Any]
    parameter_provenance: Dict[str, Any]
    run_status: str
    validation_id: Optional[str] = None
    validation_passed: bool = False
    runtime_seconds: float = Field(ge=0.0)
    peak_memory_mb: Optional[float] = Field(default=None, ge=0.0)


class ExperimentBatchResult(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    split_role: Literal["development", "evaluation"]
    probe_hash: str = Field(min_length=64, max_length=64)
    configurations: List[ConfigurationSpec]
    execution_runs: List[ExecutionRun]
    validation_results: List[ValidationResult]
    run_records: List[ExperimentRunRecord]
    requested_run_count: int = Field(ge=0, le=18)
    completed_run_count: int = Field(ge=0, le=18)
    failures: List[str] = Field(default_factory=list)
    all_runs_use_local_controlled_executor: bool = True


class MetricSummary(StrictModel):
    count: int = Field(ge=0)
    mean: Optional[float] = None
    median: Optional[float] = None
    standard_deviation: Optional[float] = Field(default=None, ge=0.0)
    minimum: Optional[float] = None
    maximum: Optional[float] = None


class CandidateEvaluation(StrictModel):
    candidate_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    tool_name: str
    tool_version: str
    configuration_hash: str = Field(min_length=64, max_length=64)
    parameters: Dict[str, Any]
    parameter_provenance: Dict[str, Any]
    split_role: Literal["development", "evaluation"]
    run_ids: List[str]
    successful_run_ids: List[str]
    failed_run_ids: List[str]
    duplicate_run_ids: List[str] = Field(default_factory=list)
    metric_summaries: Dict[str, MetricSummary]
    seed_stability: Dict[str, Any]
    runtime_summary: MetricSummary
    peak_memory_summary: MetricSummary
    execution_success_rate: float = Field(ge=0.0, le=1.0)
    limitations: List[str]
    eligible_for_decision: bool = False
    metric_authority: Literal[
        "synthetic_engineering_metric", "scientific_pilot_metric"
    ] = (
        "synthetic_engineering_metric"
    )
    reproducibility_level: Literal["Level 2"] = "Level 2"


class PreferenceProfile(str, Enum):
    PERFORMANCE = "performance"
    STABILITY = "stability"
    RESOURCE = "resource"
    FAST_LOCAL = "fast_local"


class DecisionResult(StrictModel):
    decision_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    decision_scope: Literal[
        "scrublet_configuration",
        "multitool_doublet_detection",
        "batch_integration_configuration",
        "multitool_batch_integration",
        "cell_type_annotation_configuration",
        "multitool_cell_type_annotation",
    ] = "scrublet_configuration"
    eligible_candidate_ids: List[str]
    pareto_candidate_ids: List[str]
    recommended_candidate_id: Optional[str]
    alternative_candidate_ids: List[str]
    elimination_reasons: Dict[str, List[str]]
    preference_profile: PreferenceProfile
    decision_flip_conditions: List[str]
    limitations: List[str]


class ReproducibilityPackageResult(StrictModel):
    package_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    package_path: str
    reproducibility_level: Literal["Level 2"] = "Level 2"
    required_files: List[str]
    artifact_hashes: Dict[str, str]
    complete: bool
    manifest_hashes_valid: bool
    user_data_copied: bool = False


class ScientificDatasetManifest(StrictModel):
    dataset_id: Literal["GSE108313"] = "GSE108313"
    accession: Literal["GSE108313"] = "GSE108313"
    doi: Literal["10.1186/s13059-018-1603-1"] = "10.1186/s13059-018-1603-1"
    title: str
    source_urls: Dict[str, str]
    raw_files: List[Dict[str, Any]]
    processed_files: List[Dict[str, Any]]
    download_date: str
    h5ad_path: str
    h5ad_sha256: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(ge=0)
    n_genes: int = Field(ge=0)
    raw_counts_preserved: bool
    fastq_downloaded: bool = False
    user_data: bool = False


class ScientificLabelReport(StrictModel):
    accession: Literal["GSE108313"] = "GSE108313"
    label_method: str
    positive_fraction_threshold: float = Field(gt=0.0, lt=1.0)
    ambiguous_margin: float = Field(ge=0.0, lt=1.0)
    aligned_barcodes: int = Field(ge=0)
    singlet_count: int = Field(ge=0)
    doublet_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    exclusion_reasons: Dict[str, int]
    label_mapping: Dict[str, str]
    cross_sample_doublets_only: bool = True
    limitations: List[str]


class ScientificSplitArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    accession: Literal["GSE108313"] = "GSE108313"
    split_role: Literal["development", "evaluation"]
    path: str
    probe_hash: str = Field(min_length=64, max_length=64)
    barcode_hash: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(gt=0)
    singlet_count: int = Field(gt=0)
    doublet_count: int = Field(gt=0)
    split_seed: int = Field(ge=0)
    public_dataset: bool = True
    user_data: bool = False
    scientific_claim_scope: Literal["pilot"] = "pilot"


class ScientificSplitManifest(StrictModel):
    accession: Literal["GSE108313"] = "GSE108313"
    split_seed: int = Field(ge=0)
    stratification_fields: List[str]
    development: ScientificSplitArtifact
    evaluation: ScientificSplitArtifact
    barcode_overlap_count: int = Field(ge=0)
    manifest_hash: str = Field(min_length=64, max_length=64)


class BootstrapInterval(StrictModel):
    metric: str
    estimate: float
    lower: float
    upper: float
    confidence_level: float = Field(gt=0.0, lt=1.0)
    bootstrap_iterations: int = Field(gt=0)


class ScientificEvaluationResult(StrictModel):
    evaluation_id: str
    run_id: str
    configuration_hash: str = Field(min_length=64, max_length=64)
    split_role: Literal["development", "evaluation"]
    threshold: float
    threshold_source: Literal["development_optimized", "frozen_from_development"]
    metrics: Dict[str, float]
    confusion_matrix: Dict[str, int]
    bootstrap_ci: Dict[str, BootstrapInterval]
    runtime_seconds: float = Field(ge=0.0)
    peak_memory_mb: Optional[float] = Field(default=None, ge=0.0)
    failed: bool = False
    metric_authority: Literal["scientific_pilot_metric"] = "scientific_pilot_metric"
    limitations: List[str]


class IntegrationProbeSpec(StrictModel):
    probe_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    profile_id: str = Field(min_length=1)
    source_fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    split_role: Literal["development", "evaluation"]
    random_seed: int = Field(ge=0)
    n_cells: int = Field(gt=0)
    n_features: int = Field(gt=1)
    n_batches: int = Field(gt=1)
    n_biology_labels: int = Field(gt=1)
    batch_key: str = "batch"
    label_key: str = "cell_type"
    selected_obs_indices_hash: str = Field(min_length=64, max_length=64)
    probe_artifact_path: str
    probe_hash: str = Field(min_length=64, max_length=64)
    metadata_path: str
    source_input_hash: str = Field(min_length=64, max_length=64)
    source_unchanged: bool = True
    synthetic: bool = True
    scientific_claim_allowed: bool = False


class AnnotationProbeSpec(StrictModel):
    probe_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    profile_id: str = Field(min_length=1)
    source_fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    split_role: Literal["development", "evaluation"]
    random_seed: int = Field(ge=0)
    n_cells: int = Field(gt=0)
    n_genes: int = Field(gt=1)
    n_cell_types: int = Field(gt=1)
    expression_state: Literal["log1p_normalized"]
    gene_identifier_type: Literal["gene_symbol"]
    species: Literal["human", "mouse"]
    reference_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    reference_digest: str = Field(min_length=64, max_length=64)
    selected_cell_hash: str = Field(min_length=64, max_length=64)
    ground_truth_hash: str = Field(min_length=64, max_length=64)
    probe_artifact_path: str
    probe_hash: str = Field(min_length=64, max_length=64)
    metadata_path: str
    source_input_hash: str = Field(min_length=64, max_length=64)
    source_unchanged: bool = True
    synthetic: bool = True
    scientific_claim_allowed: bool = False


class AnnotationSplitArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    accession: Literal["Zheng68K"] = "Zheng68K"
    split_role: Literal["development", "evaluation"]
    path: str
    probe_hash: str = Field(min_length=64, max_length=64)
    cell_id_hash: str = Field(min_length=64, max_length=64)
    label_hash: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(gt=0)
    n_labels: int = Field(gt=1)
    split_seed: int = Field(ge=0)
    reference_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    reference_digest: str = Field(min_length=64, max_length=64)
    label_mapping_digest: str = Field(min_length=64, max_length=64)
    public_dataset: bool = True
    user_data: bool = False
    scientific_claim_scope: Literal["pilot"] = "pilot"


class AnnotationDatasetManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: Literal["Zheng68K"] = "Zheng68K"
    accession: Literal["Zheng68K"] = "Zheng68K"
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    license: str = Field(min_length=1)
    processed_h5ad_path: str = Field(min_length=1)
    processed_h5ad_sha256: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(gt=0)
    n_genes: int = Field(gt=0)
    label_key: str = Field(min_length=1)
    source_label_count: int = Field(gt=1)
    raw_counts_preserved: bool
    frozen: bool = True
    user_data: bool = False


class AnnotationSplitManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    accession: Literal["Zheng68K"] = "Zheng68K"
    dataset_sha256: str = Field(min_length=64, max_length=64)
    split_seed: int = Field(ge=0)
    label_key: str = Field(min_length=1)
    label_mapping_digest: str = Field(min_length=64, max_length=64)
    stratification_fields: List[str] = Field(default_factory=lambda: ["canonical_label"])
    development: AnnotationSplitArtifact
    evaluation: AnnotationSplitArtifact
    cell_overlap_count: int = Field(ge=0)
    manifest_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_annotation_split(self) -> "AnnotationSplitManifest":
        if self.development.probe_hash == self.evaluation.probe_hash:
            raise ValueError("annotation development and evaluation artifacts must differ")
        if self.cell_overlap_count:
            raise ValueError("annotation split cannot contain overlapping cells")
        if self.development.label_mapping_digest != self.label_mapping_digest:
            raise ValueError("development split label mapping digest mismatch")
        if self.evaluation.label_mapping_digest != self.label_mapping_digest:
            raise ValueError("evaluation split label mapping digest mismatch")
        return self


class AnnotationScientificEvaluationResult(StrictModel):
    evaluation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    tool_name: Literal["CellTypist", "SingleR"]
    tool_version: str = Field(min_length=1)
    configuration_hash: str = Field(min_length=64, max_length=64)
    split_role: Literal["development", "evaluation"]
    split_hash: str = Field(min_length=64, max_length=64)
    label_mapping_digest: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(gt=0)
    metrics: Dict[str, float]
    per_class_metrics: Dict[str, Dict[str, float]]
    confusion_matrix: Dict[str, Dict[str, int]]
    bootstrap_ci: Dict[str, BootstrapInterval]
    runtime_seconds: float = Field(ge=0.0)
    peak_memory_mb: Optional[float] = Field(default=None, ge=0.0)
    metric_authority: Literal["scientific_pilot_metric"] = "scientific_pilot_metric"
    limitations: List[str] = Field(default_factory=list)


class IntegrationDatasetManifest(StrictModel):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    accession: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    license: str = Field(min_length=1)
    downloaded_at: str
    source_file_path: str
    source_file_sha256: str = Field(min_length=64, max_length=64)
    processed_h5ad_path: str
    processed_h5ad_sha256: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(gt=0)
    n_genes: int = Field(gt=0)
    batch_key: str
    label_key: str
    n_batches: int = Field(gt=1)
    n_labels: int = Field(gt=1)
    user_data: bool = False


class IntegrationSplitArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    fixture_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    accession: str = Field(min_length=1)
    split_role: Literal["development", "evaluation"]
    path: str
    probe_hash: str = Field(min_length=64, max_length=64)
    cell_id_hash: str = Field(min_length=64, max_length=64)
    n_cells: int = Field(gt=0)
    n_batches: int = Field(gt=1)
    n_labels: int = Field(gt=1)
    split_seed: int = Field(ge=0)
    public_dataset: bool = True
    user_data: bool = False
    scientific_claim_scope: Literal["pilot"] = "pilot"


class IntegrationSplitManifest(StrictModel):
    accession: str = Field(min_length=1)
    split_seed: int = Field(ge=0)
    stratification_fields: List[str]
    development: IntegrationSplitArtifact
    evaluation: IntegrationSplitArtifact
    cell_overlap_count: int = Field(ge=0)
    manifest_hash: str = Field(min_length=64, max_length=64)


class EnvironmentRecord(StrictModel):
    environment_id: str = Field(min_length=1)
    environment_type: Literal["conda", "venv", "system"] = "conda"
    platform: str
    architecture: str
    python_version: str
    package_versions: Dict[str, str] = Field(default_factory=dict)
    cache_environment: Dict[str, str] = Field(default_factory=dict)
    qualification_status: EnvironmentQualificationStatus = EnvironmentQualificationStatus.MISSING
    import_smoke_passed: bool = False
    integration_test_passed: bool = False
    enabled_for_execution: bool = False
    qualification_evidence: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_environment_state(self) -> "EnvironmentRecord":
        if self.qualification_status == EnvironmentQualificationStatus.IMPORT_QUALIFIED:
            if not self.import_smoke_passed:
                raise ValueError("import_qualified requires import_smoke_passed=true")
        if self.qualification_status == EnvironmentQualificationStatus.INTEGRATION_PASSED:
            if not self.integration_test_passed:
                raise ValueError("integration_passed requires integration_test_passed=true")
        if self.enabled_for_execution and not (
            self.qualification_status == EnvironmentQualificationStatus.INTEGRATION_PASSED
            and self.import_smoke_passed
            and self.integration_test_passed
        ):
            raise ValueError("execution-enabled environment must pass import and integration qualification")
        return self


class PlanningGateResult(StrictModel):
    gate: Literal["planning"] = "planning"
    allowed: bool
    contract_id: str
    reasons: List[str] = Field(default_factory=list)


class ExecutionGateResult(StrictModel):
    gate: Literal["execution"] = "execution"
    allowed: bool
    contract_id: str
    reasons: List[str] = Field(default_factory=list)
