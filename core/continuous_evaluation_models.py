from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


class EvaluationCategory(str, Enum):
    EFFECTIVENESS = "effectiveness"
    EFFICIENCY = "efficiency"
    STABILITY = "stability"
    COMPLIANCE = "compliance"


class EvaluationLane(str, Enum):
    DETERMINISTIC_OFFLINE = "deterministic_offline"
    CONTROLLED_EXECUTION = "controlled_execution"
    EXTERNAL_LLM = "external_llm"
    HUMAN_TRIAL = "human_trial"


class MetricStatus(str, Enum):
    MEASURED = "measured"
    NOT_RUN = "not_run"
    INSUFFICIENT_DATA = "insufficient_data"


class MetricSignal(str, Enum):
    HEALTHY = "healthy"
    WATCH = "watch"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class MetricSeverity(str, Enum):
    DIAGNOSTIC = "diagnostic"
    RELEASE_GATE = "release_gate"
    ZERO_TOLERANCE = "zero_tolerance"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    EXACT = "exact"


class BusinessDomain(str, Enum):
    KNOWLEDGE_QA = "knowledge_qa"
    WORKFLOW_PLANNING = "workflow_planning"
    DOUBLET_EXECUTION = "doublet_detection_execution"
    BATCH_INTEGRATION_EXECUTION = "batch_integration_execution"
    BOUNDED_REPAIR = "bounded_repair"
    AUTHORIZATION_SAFETY = "authorization_and_safety"
    REPRODUCIBILITY = "reproducibility"
    USER_TRIAL = "user_trial"


class ArchitectureStage(str, Enum):
    GATEWAY = "gateway_intent"
    RETRIEVAL = "kg_rag_retrieval"
    CONTRACT = "tool_contract_action_bundle"
    DATA_PROFILE = "data_profiler"
    PLANNER = "workflow_planner"
    ROUTER_APPROVAL = "router_approval"
    EXECUTOR = "controlled_executor"
    VALIDATOR = "validator"
    REPAIR = "repair_policy"
    DECISION = "candidate_pareto_decision"
    PACKAGER = "reproducibility_packager"
    UI_TELEMETRY = "ui_trial_telemetry"


class ContinuousMetric(StrictModel):
    metric_id: str
    display_name: str
    category: EvaluationCategory
    business_domain: BusinessDomain
    architecture_stage: ArchitectureStage
    lane: EvaluationLane
    status: MetricStatus
    signal: MetricSignal
    severity: MetricSeverity = MetricSeverity.DIAGNOSTIC
    value: float | int | str | bool | None = None
    unit: str = "ratio"
    sample_size: int | None = Field(default=None, ge=0)
    direction: MetricDirection | None = None
    target_value: float | int | None = None
    regression_tolerance: float = Field(default=0.0, ge=0.0)
    source_artifact: str
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_measurement(self) -> "ContinuousMetric":
        if self.status == MetricStatus.MEASURED and self.value is None:
            raise ValueError("measured metric must have a value")
        if self.status != MetricStatus.MEASURED and self.signal != MetricSignal.UNKNOWN:
            raise ValueError("unmeasured metric signal must be unknown")
        if self.severity == MetricSeverity.ZERO_TOLERANCE:
            if self.direction != MetricDirection.EXACT or self.target_value != 0:
                raise ValueError("zero-tolerance metrics must require exact zero")
        return self


class EvaluationCoverage(StrictModel):
    measured_metric_count: int = Field(ge=0)
    total_metric_count: int = Field(ge=0)
    release_metric_count: int = Field(ge=0)
    measured_release_metric_count: int = Field(ge=0)
    covered_business_domains: list[BusinessDomain]
    uncovered_business_domains: list[BusinessDomain]
    covered_architecture_stages: list[ArchitectureStage]
    uncovered_architecture_stages: list[ArchitectureStage]
    lane_status: dict[str, MetricStatus]


class MetricTrend(StrictModel):
    metric_id: str
    status: Literal["compared", "not_comparable"]
    baseline_value: float | int | None = None
    current_value: float | int | None = None
    delta: float | None = None
    regressed: bool = False
    reason: str = ""


class CategorySummary(StrictModel):
    category: EvaluationCategory
    signal: MetricSignal
    measured: int = Field(ge=0)
    not_run: int = Field(ge=0)
    insufficient_data: int = Field(ge=0)
    blocked: int = Field(ge=0)
    watch: int = Field(ge=0)


class BusinessDomainSummary(StrictModel):
    business_domain: BusinessDomain
    signal: MetricSignal
    measured_metric_count: int = Field(ge=0)
    total_metric_count: int = Field(ge=0)
    release_metric_coverage: float = Field(ge=0.0, le=1.0)
    watch_metrics: list[str] = Field(default_factory=list)
    blocked_metrics: list[str] = Field(default_factory=list)
    unknown_release_metrics: list[str] = Field(default_factory=list)


class FailureCluster(StrictModel):
    owner: str
    failure_count: int = Field(ge=0)
    source: str
    recommended_action: str


class OptimizationPriority(StrictModel):
    priority: Literal["P0", "P1", "P2"]
    capability_domain: str
    owner: str
    reason: str
    recommended_action: str


class ContinuousAgentEvaluationReport(StrictModel):
    schema_version: Literal["sckg-continuous-agent-eval-v1"] = (
        "sckg-continuous-agent-eval-v1"
    )
    evaluation_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_scope: str = "Phase 6 knowledge and controlled-execution quality"
    metrics: list[ContinuousMetric]
    category_summaries: list[CategorySummary]
    business_domain_summaries: list[BusinessDomainSummary]
    coverage: EvaluationCoverage
    trends: list[MetricTrend]
    failure_clusters: list[FailureCluster]
    optimization_priorities: list[OptimizationPriority]
    regression_status: Literal[
        "compared", "baseline_not_provided", "baseline_invalid"
    ]
    regression_count: int = Field(ge=0)
    release_signal: MetricSignal
    zero_tolerance_violation_count: int = Field(ge=0)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    automatic_release_decision: Literal[False] = False
