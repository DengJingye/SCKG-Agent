from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from core.execution_models import StrictModel


ActionReadiness = Literal[
    "decision_ready",
    "contract_verified",
    "planning_only",
    "blocked",
]
DataCompatibility = Literal["generic", "compatible", "blocked"]


class ActionParameter(StrictModel):
    name: str = Field(min_length=1)
    default: Any = None
    parameter_schema: Dict[str, Any] = Field(default_factory=dict)
    searchable_range: Optional[Dict[str, Any]] = None
    provenance: Literal["contract_default", "contract_searchable_range"]


class ActionBundle(StrictModel):
    """A source-bound planning package; it is never an execution approval."""

    bundle_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    action_name: str = Field(min_length=1)
    task: str = Field(min_length=1)
    modality: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    environment_id: str = Field(min_length=1)
    readiness: ActionReadiness
    data_compatibility: DataCompatibility
    data_profile_id: Optional[str] = None
    planning_allowed: bool
    execution_contract_qualified: bool
    execution_allowed: Literal[False] = False
    input_requirements: List[str] = Field(default_factory=list)
    output_artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    preconditions: List[Dict[str, Any]] = Field(default_factory=list)
    parameters: List[ActionParameter] = Field(default_factory=list)
    failure_modes: List[str] = Field(default_factory=list)
    validation_rules: List[str] = Field(default_factory=list)
    know_how: List[Dict[str, Any]] = Field(default_factory=list)
    source_material: List[Dict[str, Any]] = Field(default_factory=list)
    evaluations: List[Dict[str, Any]] = Field(default_factory=list)
    planning_blockers: List[str] = Field(default_factory=list)
    execution_gate_blockers: List[str] = Field(default_factory=list)
    execution_requirements: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    provenance_refs: List[str] = Field(min_length=1)
    retrieval_score: float = Field(ge=0.0)

    @model_validator(mode="after")
    def enforce_authority_boundary(self) -> "ActionBundle":
        if self.data_compatibility == "blocked" and self.planning_allowed:
            raise ValueError("blocked data cannot produce a planning-allowed ActionBundle")
        if self.execution_allowed:
            raise ValueError("ActionBundle cannot authorize execution")
        return self


class ActionBundleSet(StrictModel):
    retrieval_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    modality: str = Field(min_length=1)
    data_profile_id: Optional[str] = None
    retrieval_mode: Literal["decision_graph_contract_grounded"] = (
        "decision_graph_contract_grounded"
    )
    bundles: List[ActionBundle] = Field(default_factory=list)
    blocked_candidates: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    execution_request_count: Literal[0] = 0
