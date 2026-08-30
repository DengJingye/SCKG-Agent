from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from core.execution_models import (
    ApprovalScope,
    ExecutionRun,
    MatrixState,
    StrictModel,
    ValidationResult,
)
from core.capability_pack_models import (
    RepresentationProduction,
    RepresentationRequirement,
    StateRequirement,
)


class DataAssetMatrixSummary(StrictModel):
    matrix_id: str = Field(min_length=1)
    shape: tuple[int, int]
    dtype: str
    is_sparse: bool
    inferred_state: MatrixState = MatrixState.UNKNOWN
    sampled_value_count: int = Field(default=0, ge=0)
    sample_method: Literal["bounded_backed_rows", "metadata_only"]
    min_value: float | None = None
    max_value: float | None = None
    nonzero_integer_fraction: float | None = Field(default=None, ge=0, le=1)
    negative_fraction: float | None = Field(default=None, ge=0, le=1)
    nonfinite_fraction: float | None = Field(default=None, ge=0, le=1)


class DataAssetProfile(StrictModel):
    schema_version: Literal["sckg-data-asset-profile-v1"] = (
        "sckg-data-asset-profile-v1"
    )
    profile_id: str = Field(min_length=1)
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    owner_user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    redacted_path: str
    source_hash: str = Field(min_length=64, max_length=64)
    adapter_type: Literal["anndata_h5ad_v1"] = "anndata_h5ad_v1"
    object_type: Literal["AnnData"] = "AnnData"
    modality: Literal["scRNA-seq"] = "scRNA-seq"
    storage_mode: Literal["backed_read_only"] = "backed_read_only"
    file_size_bytes: int = Field(ge=0)
    estimated_dense_memory_bytes: int = Field(ge=0)
    n_cells: int = Field(ge=0)
    n_genes: int = Field(ge=0)
    matrices: list[DataAssetMatrixSummary] = Field(default_factory=list)
    selected_count_source: str | None = None
    obs_keys: list[str] = Field(default_factory=list)
    var_keys: list[str] = Field(default_factory=list)
    obsm_keys: list[str] = Field(default_factory=list)
    obsp_keys: list[str] = Field(default_factory=list)
    layer_keys: list[str] = Field(default_factory=list)
    batch_candidates: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking_errors: list[str] = Field(default_factory=list)
    preview_capability: Literal["supported", "blocked"]
    full_matrix_materialized: Literal[False] = False
    reader_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_count_source(self) -> "DataAssetProfile":
        by_id = {item.matrix_id: item for item in self.matrices}
        if self.selected_count_source:
            selected = by_id.get(self.selected_count_source)
            if selected is None or selected.inferred_state != MatrixState.RAW_COUNTS:
                raise ValueError("selected_count_source must be a raw-count matrix")
        if self.preview_capability == "blocked" and not self.blocking_errors:
            raise ValueError("blocked preview capability requires a blocking error")
        return self


class RepresentativePreviewManifest(StrictModel):
    schema_version: Literal["sckg-representative-preview-v1"] = (
        "sckg-representative-preview-v1"
    )
    preview_id: str = Field(min_length=1)
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    owner_user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    profile_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    preview_hash: str = Field(min_length=64, max_length=64)
    selected_obs_indices_hash: str = Field(min_length=64, max_length=64)
    selected_obs_ids_hash: str = Field(min_length=64, max_length=64)
    preview_path_redacted: str
    n_source_cells: int = Field(ge=0)
    n_preview_cells: int = Field(ge=0)
    n_genes: int = Field(ge=0)
    random_seed: int = Field(ge=0)
    policy: Literal["all_cells", "stratified_v1"]
    stratify_key: str | None = None
    source_strata_counts: dict[str, int] = Field(default_factory=dict)
    preview_strata_counts: dict[str, int] = Field(default_factory=dict)
    selected_count_source: str = Field(min_length=1)
    source_unchanged: bool
    original_data_copied: Literal[False] = False
    scientific_claim_allowed: Literal[False] = False
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StepParameterSpec(StrictModel):
    parameter_type: Literal["integer", "number", "boolean", "string"]
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    enum: list[Any] = Field(default_factory=list)
    provenance: str = Field(min_length=1)
    contract_parameter: str | None = None
    adaptive_rule: Literal[
        "cap_by_cell_count_minus_one",
        "cap_by_feature_count",
        "cap_by_min_cells_features_minus_one",
    ] | None = None
    user_confirmation_required: bool = False


class StepContract(StrictModel):
    schema_version: Literal["sckg-step-contract-v1", "sckg-step-contract-v2"] = (
        "sckg-step-contract-v1"
    )
    step_id: str = Field(min_length=1)
    step_version: str = Field(min_length=1)
    task_family: str = Field(default="doublet_detection", min_length=1)
    capability_id: str = Field(default="doublet_detection", min_length=1)
    method_id: str = Field(default="scrublet", min_length=1)
    operation: str = Field(default="scrublet_preview", min_length=1)
    implementation_kind: Literal[
        "tool", "human_review", "composed_action", "method_family"
    ] = "tool"
    tool_contract_id: str = Field(default="scrublet:0.2.3", min_length=1)
    tool_contract_version: str = Field(min_length=1)
    requires_object_type: str = Field(default="AnnData", min_length=1)
    requires_matrix_state: str = Field(default="raw_counts", min_length=1)
    consumes: list[RepresentationRequirement] = Field(default_factory=list)
    produces: list[RepresentationProduction] = Field(default_factory=list)
    requires: list[StateRequirement] = Field(default_factory=list)
    invalid_predecessors: list[str] = Field(default_factory=list)
    environment_id: str | None = None
    execution_adapter_id: str | None = None
    notebook_renderer_id: str | None = None
    scientific_validator_id: str | None = None
    gold_case_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, StepParameterSpec]
    input_artifacts: list[str]
    output_artifacts: list[str]
    validators: list[str]
    source_refs: list[str] = Field(default_factory=list)
    invalidates_downstream: list[str] = Field(default_factory=list)
    template_digest: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_versioned_contract(self) -> "StepContract":
        if self.schema_version == "sckg-step-contract-v2":
            if not self.consumes or not self.produces:
                raise ValueError("v2 step contracts require typed consumes and produces")
            if not self.notebook_renderer_id:
                raise ValueError("v2 step contracts require a renderer binding")
            if self.implementation_kind == "tool" and not self.execution_adapter_id:
                raise ValueError("v2 tool steps require an execution adapter binding")
            if not self.scientific_validator_id:
                raise ValueError("v2 step contracts require a scientific validator")
        return self


class StepParameterChange(StrictModel):
    parameter_name: str = Field(min_length=1)
    old_value: Any
    new_value: Any
    provenance: Literal["user_reviewed_contract_parameter"] = (
        "user_reviewed_contract_parameter"
    )
    requires_new_approval: Literal[True] = True


class StepParameterPatch(StrictModel):
    schema_version: Literal["sckg-step-parameter-patch-v1"] = (
        "sckg-step-parameter-patch-v1"
    )
    patch_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    step_version: str = Field(min_length=1)
    base_parameter_hash: str = Field(min_length=64, max_length=64)
    proposed_parameter_hash: str = Field(min_length=64, max_length=64)
    parameters: dict[str, Any]
    changes: list[StepParameterChange] = Field(default_factory=list)
    requires_rebuild: bool
    invalidates: list[Literal["notebook", "approval", "result"]] = Field(
        default_factory=list
    )
    execution_request_count: Literal[0] = 0


class NotebookCellTrustRecord(StrictModel):
    cell_id: str = Field(min_length=1)
    cell_role: str = Field(min_length=1)
    source_digest: str = Field(min_length=64, max_length=64)
    expected_source_digest: str | None = Field(default=None, min_length=64, max_length=64)
    status: Literal["VERIFIED", "MODIFIED", "UNTRACKED"]


class NotebookTrustReport(StrictModel):
    schema_version: Literal["sckg-notebook-trust-report-v1"] = (
        "sckg-notebook-trust-report-v1"
    )
    notebook_id: str = Field(min_length=1)
    notebook_hash_matches: bool
    system_verified: bool
    cells: list[NotebookCellTrustRecord]
    modified_cell_ids: list[str] = Field(default_factory=list)
    untracked_cell_ids: list[str] = Field(default_factory=list)
    execution_allowed: Literal[False] = False
    issues: list[str] = Field(default_factory=list)


class NotebookShadowBundle(StrictModel):
    schema_version: Literal["sckg-notebook-shadow-v2"] = "sckg-notebook-shadow-v2"
    notebook_id: str = Field(min_length=1)
    owner_user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    preview_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=64, max_length=64)
    notebook_path_redacted: str
    notebook_hash: str = Field(min_length=64, max_length=64)
    preview_hash: str = Field(min_length=64, max_length=64)
    step_contract_id: str = Field(min_length=1)
    step_contract_version: str = Field(min_length=1)
    tool_contract_version: str = Field(min_length=1)
    step_template_digest: str = Field(min_length=64, max_length=64)
    parameter_hash: str = Field(min_length=64, max_length=64)
    parameter_snapshot: dict[str, Any] = Field(default_factory=dict)
    parameter_provenance: dict[str, str] = Field(default_factory=dict)
    task_context: dict[str, str | None] = Field(default_factory=dict)
    task_context_digest: str | None = Field(default=None, min_length=64, max_length=64)
    cell_source_digests: dict[str, str] = Field(default_factory=dict)
    cell_count: int = Field(gt=0)
    code_cell_count: int = Field(gt=0)
    shadow_mode: Literal[True] = True
    trusted_code_source: Literal["maintainer_step_template"] = (
        "maintainer_step_template"
    )
    executed: Literal[False] = False
    execution_request_count: Literal[0] = 0
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


ManagedStepStatus = Literal[
    "CURRENT", "READY", "WAITING", "RUNNING", "COMPLETED", "STALE", "BLOCKED", "FAILED"
]


class ManagedStepNode(StrictModel):
    step_id: Literal[
        "register_data",
        "profile_data",
        "build_preview",
        "compile_notebook",
        "approve_execution",
        "run_tool",
        "validate_outputs",
        "review_result",
    ]
    label: str = Field(min_length=1)
    status: ManagedStepStatus
    depends_on: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    user_action: str = Field(min_length=1)


class ManagedStepRuntimeSnapshot(StrictModel):
    schema_version: Literal["sckg-managed-step-runtime-v1"] = (
        "sckg-managed-step-runtime-v1"
    )
    task_family: Literal["doublet_detection"] = "doublet_detection"
    tool_name: Literal["Scrublet"] = "Scrublet"
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    committed_parameter_hash: str | None = Field(default=None, min_length=64, max_length=64)
    proposed_parameter_hash: str | None = Field(default=None, min_length=64, max_length=64)
    parameter_patch_required: bool = False
    steps: list[ManagedStepNode]
    current_step_id: str | None = None
    next_action: str = Field(min_length=1)
    execution_request_count: Literal[0] = 0


class ErrorContext(StrictModel):
    schema_version: Literal["sckg-error-context-v1"] = "sckg-error-context-v1"
    stage: Literal["preflight", "execution", "validation"]
    error_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False
    user_action: str = Field(min_length=1)
    run_id: str | None = None
    stderr_summary: str | None = None


class PreviewStepEvent(StrictModel):
    event_id: str = Field(min_length=1)
    step_id: Literal["run_tool", "validate_outputs"]
    status: Literal["RUNNING", "COMPLETED", "BLOCKED", "FAILED"]
    message: str = Field(min_length=1)
    run_id: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreviewObservedMetric(StrictModel):
    metric_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    display_value: str = Field(min_length=1)
    raw_value: float | int | str | None = None
    meaning: str = Field(min_length=1)


class PreviewParameterExplanation(StrictModel):
    parameter_name: str = Field(min_length=1)
    value: Any
    effect: str = Field(min_length=1)
    review_guidance: str = Field(min_length=1)
    automatic_adjustment_allowed: Literal[False] = False


class PreviewPlotExplanation(StrictModel):
    artifact_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    x_axis: str = Field(min_length=1)
    y_axis: str = Field(min_length=1)
    how_to_read: list[str] = Field(default_factory=list)
    caution: str = Field(min_length=1)


class PreviewNextAction(StrictModel):
    priority: int = Field(ge=1, le=9)
    action_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requires_new_approval: bool = False
    automatic: Literal[False] = False


class PreviewErrorDiagnosis(StrictModel):
    schema_version: Literal["sckg-preview-error-diagnosis-v1"] = (
        "sckg-preview-error-diagnosis-v1"
    )
    stage: Literal["lineage", "preflight", "execution", "validation", "integrity"]
    category: Literal[
        "stale_lineage",
        "authorization_or_policy",
        "runtime_or_wrapper",
        "resource_limit",
        "parameter_or_input",
        "output_validation",
        "artifact_integrity",
        "unknown",
    ]
    error_code: str = Field(min_length=1)
    severity: Literal["info", "warning", "error", "critical"]
    retryable: bool = False
    likely_causes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    user_actions: list[PreviewNextAction] = Field(default_factory=list)
    automatic_repair_allowed: Literal[False] = False


class PreviewResultInterpretation(StrictModel):
    schema_version: Literal["sckg-preview-result-interpretation-v1"] = (
        "sckg-preview-result-interpretation-v1"
    )
    run_id: str = Field(min_length=1)
    status: Literal["COMPLETED", "STALE", "BLOCKED", "FAILED"]
    headline: str = Field(min_length=1)
    plain_language_summary: list[str] = Field(default_factory=list)
    observed_metrics: list[PreviewObservedMetric] = Field(default_factory=list)
    parameter_explanations: list[PreviewParameterExplanation] = Field(
        default_factory=list
    )
    plot_explanation: PreviewPlotExplanation | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_actions: list[PreviewNextAction] = Field(default_factory=list)
    error_diagnosis: PreviewErrorDiagnosis | None = None
    metric_authority: Literal["preview_engineering_metric"] = (
        "preview_engineering_metric"
    )
    output_authority: Literal["preview_engineering_only"] = (
        "preview_engineering_only"
    )
    scientific_claim_allowed: Literal[False] = False
    usable_for_preview_review: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreviewRunPreparation(StrictModel):
    schema_version: Literal["sckg-preview-run-preparation-v1"] = (
        "sckg-preview-run-preparation-v1"
    )
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    preview_id: str = Field(min_length=1)
    notebook_id: str = Field(min_length=1)
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    tool_name: Literal["Scrublet"] = "Scrublet"
    tool_version: Literal["0.2.3"] = "0.2.3"
    environment_id: str = Field(min_length=1)
    parameter_hash: str = Field(min_length=64, max_length=64)
    approval_scope: ApprovalScope
    approval_fingerprint: str = Field(min_length=64, max_length=64)
    policy_mode: str
    runtime_ready: bool
    approval_ready: bool = False
    approval_blockers: list[str] = Field(default_factory=list)
    ready: bool
    blockers: list[str] = Field(default_factory=list)
    execution_request_count: Literal[0] = 0


class PreviewRunRequest(StrictModel):
    schema_version: Literal["sckg-preview-run-request-v1"] = (
        "sckg-preview-run-request-v1"
    )
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    data_grant_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    execution_approval_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    profile_id: str = Field(min_length=1)
    preview_id: str = Field(min_length=1)
    preview_hash: str = Field(min_length=64, max_length=64)
    notebook_id: str = Field(min_length=1)
    notebook_hash: str = Field(min_length=64, max_length=64)
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    parameter_hash: str = Field(min_length=64, max_length=64)
    step_contract_id: str = Field(min_length=1)
    step_contract_version: str = Field(min_length=1)
    user_confirmed_preview_boundary: Literal[True] = True


class PreviewLineageSnapshot(StrictModel):
    schema_version: Literal["sckg-preview-lineage-v1"] = "sckg-preview-lineage-v1"
    source_hash: str = Field(min_length=64, max_length=64)
    profile_id: str = Field(min_length=1)
    preview_id: str = Field(min_length=1)
    preview_hash: str = Field(min_length=64, max_length=64)
    notebook_id: str = Field(min_length=1)
    notebook_hash: str = Field(min_length=64, max_length=64)
    parameter_hash: str = Field(min_length=64, max_length=64)
    step_contract_id: str = Field(min_length=1)
    step_contract_version: str = Field(min_length=1)
    step_template_digest: str = Field(min_length=64, max_length=64)
    tool_contract_id: str = Field(min_length=1)
    tool_contract_version: str = Field(min_length=1)
    tool_contract_digest: str = Field(min_length=64, max_length=64)
    environment_id: str = Field(min_length=1)
    environment_digest: str = Field(min_length=64, max_length=64)
    approval_fingerprint: str = Field(min_length=64, max_length=64)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreviewRunResult(StrictModel):
    schema_version: Literal[
        "sckg-preview-run-result-v2", "sckg-preview-run-result-v3"
    ] = (
        "sckg-preview-run-result-v3"
    )
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    preview_id: str = Field(min_length=1)
    notebook_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    status: Literal["validated", "failed", "blocked"]
    execution_run: ExecutionRun
    validation_result: ValidationResult
    error_context: ErrorContext | None = None
    original_data_copied: Literal[False] = False
    scientific_claim_allowed: Literal[False] = False
    output_authority: Literal["preview_engineering_only"] = "preview_engineering_only"
    lineage: PreviewLineageSnapshot | None = None
    step_events: list[PreviewStepEvent] = Field(default_factory=list)


WorkspaceCheckpointStage = Literal[
    "source", "profile", "preview", "notebook", "approval", "result"
]
WorkspaceCheckpointStatus = Literal[
    "CURRENT", "MISSING", "WAITING", "STALE", "BLOCKED", "FAILED"
]


class WorkspaceCheckpointNode(StrictModel):
    stage: WorkspaceCheckpointStage
    status: WorkspaceCheckpointStatus
    reasons: list[str] = Field(default_factory=list)
    rebuild_from: WorkspaceCheckpointStage | None = None
    user_action: str
    recorded_digest: str | None = None
    current_digest: str | None = None
    propagated: bool = False


class WorkspaceCheckpointReport(StrictModel):
    schema_version: Literal["sckg-workspace-checkpoint-v1"] = (
        "sckg-workspace-checkpoint-v1"
    )
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    overall_status: Literal[
        "CURRENT", "INCOMPLETE", "WAITING", "STALE", "BLOCKED", "FAILED"
    ]
    nodes: list[WorkspaceCheckpointNode]
    first_invalid_stage: WorkspaceCheckpointStage | None = None
    rebuild_from: WorkspaceCheckpointStage | None = None
    user_action: str
    execution_request_count: Literal[0] = 0
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def node(self, stage: WorkspaceCheckpointStage) -> WorkspaceCheckpointNode:
        return next(item for item in self.nodes if item.stage == stage)


class PreviewResultIntegrity(StrictModel):
    schema_version: Literal["sckg-preview-result-integrity-v1"] = (
        "sckg-preview-result-integrity-v1"
    )
    passed: bool
    result_digest_valid: bool
    artifact_paths_owned: bool
    artifact_hashes_valid: bool
    missing_artifacts: list[str] = Field(default_factory=list)
    hash_mismatches: list[str] = Field(default_factory=list)
    escaped_artifacts: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class PreviewRunSummary(StrictModel):
    schema_version: Literal["sckg-preview-run-summary-v1"] = (
        "sckg-preview-run-summary-v1"
    )
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    preview_id: str = Field(min_length=1)
    notebook_id: str = Field(min_length=1)
    tool_name: str
    tool_version: str
    status: Literal["COMPLETED", "CURRENT", "WAITING", "STALE", "BLOCKED", "FAILED"]
    validation_passed: bool
    runtime_seconds: float = Field(ge=0)
    peak_memory_mb: float | None = Field(default=None, ge=0)
    artifact_count: int = Field(ge=0)
    integrity: PreviewResultIntegrity
    checkpoint: WorkspaceCheckpointReport | None = None
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    completed_at: datetime
    scientific_claim_allowed: Literal[False] = False
