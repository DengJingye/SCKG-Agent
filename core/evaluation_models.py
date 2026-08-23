from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


class EvaluationSuite(str, Enum):
    PR = "pr"
    NIGHTLY = "nightly"
    RELEASE = "release"


class EvaluationDatasetKind(str, Enum):
    COMPONENT = "component"
    CONVERSATION = "conversation"
    EXECUTION = "execution"


class EvaluationSplit(str, Enum):
    DEVELOPMENT = "development"
    EVALUATION = "evaluation"
    HIDDEN = "hidden"


class EvaluationMetricStatus(str, Enum):
    MEASURED = "measured"
    NOT_RUN = "not_run"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class EvaluationSignal(str, Enum):
    PASSED = "passed"
    WATCH = "watch"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ReferenceClaim(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    claim_text: str = Field(min_length=1)
    claim_type: Literal[
        "scientific", "parameter", "input_output", "benchmark", "capability", "safety"
    ] = "scientific"
    source_span_ids: list[str] = Field(min_length=1)
    scope: str = Field(min_length=1)
    importance: Literal["critical", "major", "minor"] = "major"
    allowed_uncertainty: list[str] = Field(default_factory=list)


class ExpectedToolCall(StrictModel):
    tool_name: str = Field(min_length=1)
    required_arguments: dict[str, Any] = Field(default_factory=dict)
    optional_arguments: list[str] = Field(default_factory=list)


class ExpectedTrajectory(StrictModel):
    required_steps: list[str] = Field(default_factory=list)
    forbidden_steps: list[str] = Field(default_factory=list)
    ordered_steps: list[str] = Field(default_factory=list)
    required_tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    max_redundant_actions: int = Field(default=0, ge=0)
    must_stop_after: str = ""


class EvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    dataset_version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    split: EvaluationSplit
    input: dict[str, Any]
    conversation_state: list[dict[str, Any]] = Field(default_factory=list)
    applicable_metrics: list[str] = Field(min_length=1)
    routing_gold: dict[str, Any] | None = None
    answer_gold: list[ReferenceClaim] = Field(default_factory=list)
    safety_gold: dict[str, Any] | None = None
    expected_trajectory: ExpectedTrajectory | None = None
    expected_artifacts: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_gold_applicability(self) -> "EvaluationCase":
        applies_answer = any(
            metric.startswith(("answer.", "claim.", "citation."))
            for metric in self.applicable_metrics
        )
        if applies_answer and not self.answer_gold:
            raise ValueError(
                "answer/claim/citation metrics require atomic reference claims with source spans"
            )
        applies_trajectory = any(
            metric.startswith("trajectory.") for metric in self.applicable_metrics
        )
        if applies_trajectory and self.expected_trajectory is None:
            raise ValueError("trajectory metrics require expected_trajectory")
        applies_safety = any(
            metric.startswith("safety.") for metric in self.applicable_metrics
        )
        if applies_safety and self.safety_gold is None:
            raise ValueError("safety metrics require safety_gold")
        return self


class EvaluationDatasetManifest(StrictModel):
    schema_version: Literal["sckg-evaluation-dataset-v1"] = (
        "sckg-evaluation-dataset-v1"
    )
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    dataset_version: str = Field(min_length=1)
    kind: EvaluationDatasetKind
    description: str
    case_file: str
    case_count: int = Field(ge=0)
    split_counts: dict[str, int] = Field(default_factory=dict)
    case_digest: str
    hidden_digest: str = ""
    source_digests: dict[str, str] = Field(default_factory=dict)
    adjudication_status: Literal["draft", "partial", "adjudicated"] = "draft"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JudgeRuntimeConfig(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_base: str = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=0.3)
    prompt_digest: str = Field(min_length=1)
    calibration_case_count: int = Field(default=0, ge=0)
    calibration_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_kappa: float | None = Field(default=None, ge=-1.0, le=1.0)

    def is_independent_from(self, *, provider: str, model: str) -> bool:
        return not (
            self.provider.casefold() == provider.casefold()
            and self.model.casefold() == model.casefold()
        )

    def is_calibrated(self) -> bool:
        return (
            self.calibration_case_count >= 20
            and (self.calibration_accuracy or 0.0) >= 0.80
            and (self.calibration_kappa or -1.0) >= 0.70
        )


class ExperimentManifest(StrictModel):
    schema_version: Literal["sckg-evaluation-experiment-v1"] = (
        "sckg-evaluation-experiment-v1"
    )
    experiment_id: str
    suite: EvaluationSuite
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    git_head: str
    worktree_dirty: bool
    dataset_digests: dict[str, str]
    prompt_digest: str
    generator_provider: str = "local_deterministic"
    generator_model: str = "none"
    corpus_digest: str = ""
    contract_digest: str = ""
    environment_digest: str = ""
    evaluator_digest: str
    judge: JudgeRuntimeConfig | None = None
    outbound_calls_allowed: bool = False
    hidden_cases_included: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_judge_independence(self) -> "ExperimentManifest":
        if (
            self.completed_at is not None
            and "started_at" in self.model_fields_set
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot be earlier than started_at")
        if self.judge and not self.judge.is_independent_from(
            provider=self.generator_provider, model=self.generator_model
        ):
            raise ValueError("generator and independent judge cannot be the same model")
        return self


class EvaluationRunRecord(StrictModel):
    run_id: str
    experiment_id: str
    case_id: str
    repetition: int = Field(default=0, ge=0)
    status: Literal["completed", "blocked", "failed", "not_run"]
    observed: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    latency_ms: float | None = Field(default=None, ge=0.0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    answer_hash: str = ""
    error: str = ""


class EvaluatorResult(StrictModel):
    evaluator_id: str
    metric_id: str
    status: EvaluationMetricStatus
    signal: EvaluationSignal = EvaluationSignal.UNKNOWN
    value: float | int | bool | str | None = None
    numerator: float | int | None = None
    denominator: int = Field(default=0, ge=0)
    applicable_case_ids: list[str] = Field(default_factory=list)
    threshold: float | int | None = None
    direction: Literal["higher", "lower", "exact"] | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metric_state(self) -> "EvaluatorResult":
        if self.status == EvaluationMetricStatus.MEASURED:
            if self.value is None or self.denominator == 0:
                raise ValueError("measured metrics require a value and non-zero denominator")
        elif self.value is not None:
            raise ValueError("unmeasured metrics cannot carry a synthetic value")
        return self


class FailureAttribution(StrictModel):
    case_id: str
    run_id: str
    root_stage: str
    root_error_type: str
    downstream_symptoms: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    owner_module: str
    recommended_action: str


class MetricDelta(StrictModel):
    metric_id: str
    status: Literal["compared", "not_comparable"]
    baseline_value: float | int | None = None
    current_value: float | int | None = None
    delta: float | None = None
    confidence_interval_low: float | None = None
    confidence_interval_high: float | None = None
    regressed: bool = False
    reason: str = ""


class RegressionReport(StrictModel):
    baseline_experiment_id: str | None = None
    current_experiment_id: str
    comparable: bool
    reason: str = ""
    metric_deltas: list[MetricDelta] = Field(default_factory=list)
    regressed_case_ids: list[str] = Field(default_factory=list)
    improved_case_ids: list[str] = Field(default_factory=list)


class GateCheck(StrictModel):
    gate_id: str
    status: EvaluationSignal
    observed: float | int | bool | str | None = None
    requirement: str
    reason: str = ""
    source_metric_id: str = ""


class ReleaseGateDecision(StrictModel):
    schema_version: Literal["sckg-release-gate-v1"] = "sckg-release-gate-v1"
    experiment_id: str
    status: EvaluationSignal
    checks: list[GateCheck]
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    automatic_release: Literal[False] = False
