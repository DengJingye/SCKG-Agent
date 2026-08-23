from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from core.execution_models import StrictModel


EvaluationStatus = Literal["passed", "failed", "partial", "not_run"]


class EvaluationCommandResult(StrictModel):
    command_id: str
    status: Literal["passed", "failed", "not_run"]
    exit_code: int | None = None
    runtime_seconds: float = Field(default=0.0, ge=0.0)
    payload_digest: str | None = None
    error_summary: str = ""


class EvaluationScenarioResult(StrictModel):
    scenario_id: str
    category: Literal[
        "success",
        "repair",
        "blocked",
        "approval_replay",
        "parameter_change",
        "cancellation",
    ]
    expected_outcome: str
    observed_outcome: str
    passed: bool
    execution_request_count: int | None = Field(default=None, ge=0)
    source: str


class QualityDimensionResult(StrictModel):
    dimension: Literal[
        "functional_correctness",
        "safety_and_isolation",
        "knowledge_quality",
        "usability",
        "reproducibility",
        "performance",
        "auditability",
        "change_risk",
    ]
    status: EvaluationStatus
    metrics: dict[str, Any] = Field(default_factory=dict)
    checks: dict[str, bool] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)


class SystemQualityReport(StrictModel):
    schema_version: Literal["sckg-system-quality-v1"] = "sckg-system-quality-v1"
    evaluation_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_phase: Literal["Phase 6"] = "Phase 6"
    scope: dict[str, Any]
    command_results: list[EvaluationCommandResult]
    scenarios: list[EvaluationScenarioResult]
    dimensions: list[QualityDimensionResult]
    capability_summary: dict[str, Any]
    regression_summary: dict[str, Any]
    failure_attribution: dict[str, int]
    engineering_gate_passed: bool
    phase6_complete_eligible: bool
    recommended_status: Literal[
        "PHASE6_TRIAL_READY", "PHASE6_COMPLETE_REVIEW_REQUIRED", "PHASE6_BLOCKED"
    ]
    automatic_status_change: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
