from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import ConfigDict, Field, model_validator

from core.execution_models import StrictModel


PortfolioCategory = Literal[
    "doublet_detection",
    "batch_integration",
    "safety_blocking",
    "retrieval_boundary",
]
PortfolioBaseline = Literal["A2_ordinary_rag", "A3_kg_rag", "A4_kg_rag_tool_contract"]
PortfolioRunStatus = Literal["completed", "not_run", "error"]


class PortfolioScenarioState(StrictModel):
    """Structured runtime facts supplied to every baseline, never gold labels."""

    task_hint: Optional[str] = None
    requested_tool: Optional[str] = None
    execution_requested: bool = False
    artifact_registered: bool = False
    data_grant_valid: bool = False
    execution_approval_valid: bool = False
    execution_approval_required: bool = False
    execution_policy_allows: bool = True
    approval_consumed: bool = False
    approval_not_expired: bool = True
    owner_scope_matches: bool = True
    approval_parameter_hash_matches: bool = True
    artifact_hash_matches: bool = True
    count_source_resolved: bool = True
    requested_wrapper_known: bool = True
    shell_command_requested: bool = False
    output_path_within_run: bool = True
    input_symlink_within_root: bool = True
    repair_scope_matches: bool = True
    reviewed_contract_available: bool = True
    retrieval_chunk_only_promotion: bool = False
    universal_claim_from_single_dataset: bool = False
    citation_only_authorization: bool = False
    legacy_embedding_only_claim: bool = False
    action_bundle_only_execution: bool = False
    qualitative_benchmark_as_numeric: bool = False
    catalog_metadata_only: bool = False
    provided_source_refs: list[str] = Field(default_factory=list)


class PortfolioCaseSpec(StrictModel):
    case_id: str = Field(pattern=r"^P6-[A-Z]{2}-\d{2}$")
    category: PortfolioCategory
    query: str = Field(min_length=3)
    expected_task: str = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    expected_route: str = Field(min_length=1)
    required_blockers: list[str] = Field(default_factory=list)
    allowed_parameter_names: list[str] = Field(default_factory=list)
    required_input_terms: list[str] = Field(default_factory=list)
    required_output_terms: list[str] = Field(default_factory=list)
    source_required: bool = True
    critical: bool = False
    representative: bool = False
    scenario_state: PortfolioScenarioState = Field(default_factory=PortfolioScenarioState)
    notes: list[str] = Field(default_factory=list)


class PortfolioMetrics(StrictModel):
    task_routing_accuracy: float = Field(ge=0.0, le=1.0)
    tool_workflow_recall_at_k: float = Field(ge=0.0, le=1.0)
    blocker_correctness: float = Field(ge=0.0, le=1.0)
    parameter_legality: float = Field(ge=0.0, le=1.0)
    io_compatibility: float = Field(ge=0.0, le=1.0)
    source_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_action_or_claim: int = Field(ge=0)
    trace_completeness: float = Field(ge=0.0, le=1.0)
    unauthorized_execution_request_count: int = Field(ge=0)


class PortfolioCaseResult(StrictModel):
    model_config = ConfigDict(protected_namespaces=())

    case_id: str
    baseline_id: PortfolioBaseline
    status: PortfolioRunStatus
    reason: str = ""
    provider: Optional[str] = None
    model_name: Optional[str] = None
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_cost_usd: Optional[float] = Field(default=None, ge=0.0)
    raw_response: Optional[dict[str, Any]] = None
    admitted_response: Optional[dict[str, Any]] = None
    governance_interventions: list[dict[str, Any]] = Field(default_factory=list)
    metrics: Optional[PortfolioMetrics] = None
    observed_task: Optional[str] = None
    observed_tools: list[str] = Field(default_factory=list)
    observed_route: Optional[str] = None
    observed_blockers: list[str] = Field(default_factory=list)
    observed_parameters: dict[str, Any] = Field(default_factory=dict)
    observed_inputs: list[str] = Field(default_factory=list)
    observed_outputs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def completed_requires_metrics(self) -> "PortfolioCaseResult":
        if self.status == "completed" and self.metrics is None:
            raise ValueError("completed portfolio result requires metrics")
        if self.status != "completed" and self.metrics is not None:
            raise ValueError("not-run or error result cannot contain scored metrics")
        return self


class PortfolioBaselineSummary(StrictModel):
    baseline_id: PortfolioBaseline
    status: Literal["completed", "partial", "not_run"]
    completed_cases: int = Field(ge=0)
    total_cases: int = Field(ge=0)
    metric_means: dict[str, float] = Field(default_factory=dict)
    raw_metric_means: dict[str, float] = Field(default_factory=dict)
    governance_delta: dict[str, float] = Field(default_factory=dict)
    latency_ms_total: float = Field(default=0.0, ge=0.0)
    input_tokens_total: int = Field(default=0, ge=0)
    output_tokens_total: int = Field(default=0, ge=0)
    estimated_cost_usd_total: Optional[float] = Field(default=None, ge=0.0)
    hard_gate_passed: Optional[bool] = None
    hard_gate_failures: list[str] = Field(default_factory=list)


class PortfolioBenchmarkSummary(StrictModel):
    benchmark_id: str
    schema_version: Literal["portfolio-benchmark-v2"] = "portfolio-benchmark-v2"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    gold_case_count: int = Field(ge=1)
    representative_case_count: int = Field(ge=1)
    requested_model_calls: int = Field(ge=0)
    completed_model_calls: int = Field(ge=0)
    new_model_calls: int = Field(default=0, ge=0)
    recovered_model_calls: int = Field(default=0, ge=0)
    replayed_model_calls: int = Field(default=0, ge=0)
    baselines: list[PortfolioBaselineSummary]
    a4_not_worse_than_a3: Optional[bool] = None
    failure_analysis: list[str] = Field(default_factory=list)
    safety: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
