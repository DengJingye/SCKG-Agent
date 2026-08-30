from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from core.capability_composition_models import CapabilityCompositionResult
from core.execution_models import DataProfile, StrictModel, WorkflowPlan
from core.representation_models import RepresentationLedger


class CapabilityWorkspaceRequest(StrictModel):
    request_id: str = Field(min_length=1)
    origin_trace_id: str | None = None
    handoff_id: str | None = None
    parent_request_id: str | None = None
    original_plan_id: str | None = None
    user_id: str = Field(min_length=1)
    artifact_id: str
    pack_id: str
    pack_version: str
    mode: Literal["ASK", "PLAN", "RUN"] = "PLAN"
    requirement_id: str
    target_representations: list[str] = Field(min_length=1)
    preferred_method_ids: list[str] = Field(default_factory=list)
    parameter_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    batch_key: str | None = None
    enable_doublet_detection: bool = False
    exclude_predicted_doublets: bool = False
    doublet_selection_hash: str | None = Field(default=None, min_length=64, max_length=64)
    enable_batch_integration: bool = False


class CapabilityWorkspaceResult(StrictModel):
    request_id: str
    canonical_trace_id: str
    pack_id: str
    pack_version: str
    status: Literal[
        "discovered",
        "planned",
        "waiting_execution_approval",
        "blocked",
    ]
    readiness: list[str] = Field(default_factory=list)
    data_profile: DataProfile | None = None
    representation_ledger: RepresentationLedger | None = None
    workflow_plan: WorkflowPlan | None = None
    composition: CapabilityCompositionResult | None = None
    notebook_artifact: dict[str, Any] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    execution_request_count: Literal[0] = 0
    execution_policy: Literal["disabled"] = "disabled"
