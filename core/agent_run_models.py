from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


AGENT_STAGE_ORDER = (
    "trigger",
    "gateway",
    "kg_rag_action_retrieval",
    "data_profile",
    "workflow_plan",
    "deterministic_router",
    "approval_boundary",
    "controlled_execution",
    "validation",
    "bounded_repair",
    "decision",
    "reproducibility_package",
    "audit",
)


class AgentRunStage(StrictModel):
    stage: str
    authority: Literal[
        "llm_proposal",
        "deterministic_gateway",
        "knowledge_plane",
        "safety_plane",
        "execution_plane",
        "validation_plane",
        "packaging_plane",
    ]
    status: Literal["completed", "waiting", "blocked", "failed", "not_applicable"]
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class UnifiedAgentRunTrace(StrictModel):
    trace_id: str
    case_id: str
    request_id: str
    task: str
    status: Literal["COMPLETED", "WAITING", "BLOCKED", "FAILED"]
    stages: list[AgentRunStage]
    execution_request_count: int = Field(default=0, ge=0)
    unauthorized_execution_request_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stage_order(self) -> "UnifiedAgentRunTrace":
        indexes = [AGENT_STAGE_ORDER.index(stage.stage) for stage in self.stages]
        if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
            raise ValueError("unified Agent trace stages must be unique and ordered")
        if self.unauthorized_execution_request_count > self.execution_request_count:
            raise ValueError("unauthorized count cannot exceed all execution requests")
        return self

    @property
    def applicable_stage_completeness(self) -> float:
        applicable = [stage for stage in self.stages if stage.status != "not_applicable"]
        observed = [stage for stage in applicable if stage.status in {"completed", "waiting", "blocked", "failed"}]
        return len(observed) / max(len(applicable), 1)
