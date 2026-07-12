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
    label_key: Optional[str] = None
    has_pca: bool = False
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


class QualificationContext(StrictModel):
    mode: bool = False
    purpose: Literal["synthetic_qualification", "scientific_pilot"] = (
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


class ExecutionRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    trace_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    step_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    wrapper_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    input_artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    parameters: Dict[str, Any]
    parameter_provenance: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(gt=0, le=900)
    artifact_policy_id: Literal["default_run_artifacts"] = "default_run_artifacts"
    actor: ActorContext
    qualification: QualificationContext


class ProcessCleanup(StrictModel):
    timeout_triggered: bool = False
    terminate_sent: bool = False
    kill_sent: bool = False
    child_processes_seen: int = Field(default=0, ge=0)
    residual_processes: List[int] = Field(default_factory=list)


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
    status: Literal["queued", "running", "succeeded", "failed", "timeout", "blocked"]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    process_cleanup: ProcessCleanup = Field(default_factory=ProcessCleanup)
    qualification_mode: bool = True
    fixture_id: str
    synthetic_fixture: bool = True
    public_dataset: bool = False
    user_data_used: bool = False
    execution_purpose: Literal["synthetic_qualification", "scientific_pilot"] = (
        "synthetic_qualification"
    )


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
        "synthetic_engineering_metric", "scientific_pilot_metric"
    ] = (
        "synthetic_engineering_metric"
    )
    validation_version: str = "doublet-validator-v1"


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
        "scrublet_configuration", "multitool_doublet_detection"
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
