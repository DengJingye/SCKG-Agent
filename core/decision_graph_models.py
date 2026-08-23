from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DecisionNodeType = Literal[
    "Tool",
    "Task",
    "Action",
    "InputArtifact",
    "OutputArtifact",
    "DataAssumption",
    "ToolContract",
    "Environment",
    "Parameter",
    "FailureMode",
    "ValidationRule",
    "KnowHow",
    "SourceChunk",
    "Dataset",
    "Evaluation",
]
DecisionGovernanceTier = Literal[
    "contract_verified",
    "evaluation_scoped",
    "source_material",
    "catalog_seed",
    "blocked",
]


class DecisionGraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionGovernance(DecisionGraphModel):
    tier: DecisionGovernanceTier
    source_bound: bool = True
    decision_eligible: bool = False
    scope: str = ""
    limitations: List[str] = Field(default_factory=list)
    provenance_refs: List[str] = Field(min_length=1)

    @field_validator("limitations", "provenance_refs")
    @classmethod
    def normalize_values(cls, values: List[str]) -> List[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @model_validator(mode="after")
    def enforce_decision_boundary(self) -> "DecisionGovernance":
        if self.decision_eligible and self.tier not in {
            "contract_verified",
            "evaluation_scoped",
        }:
            raise ValueError("only verified contracts or scoped evaluations may be decision eligible")
        if self.decision_eligible and not self.source_bound:
            raise ValueError("decision-eligible records must be source bound")
        return self


class DecisionNode(DecisionGraphModel):
    node_id: str = Field(min_length=1)
    node_type: DecisionNodeType
    label: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    governance: DecisionGovernance


class DecisionEdge(DecisionGraphModel):
    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    governance: DecisionGovernance

    @model_validator(mode="after")
    def reject_invalid_edge(self) -> "DecisionEdge":
        if self.source_id == self.target_id:
            raise ValueError("decision graph self edges are not allowed")
        if self.relation.startswith("HYPOTHESIZED_"):
            raise ValueError("hypothesis edges are forbidden in Decision Graph v3")
        return self


class DecisionGraphQuality(DecisionGraphModel):
    snapshot_version: str
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    node_counts_by_type: Dict[str, int] = Field(default_factory=dict)
    edge_counts_by_relation: Dict[str, int] = Field(default_factory=dict)
    catalog_tool_count: int = Field(ge=0)
    scoped_tool_count: int = Field(ge=0)
    source_material_tool_count: int = Field(ge=0)
    source_rich_tool_count: int = Field(ge=0)
    contract_verified_tool_count: int = Field(ge=0)
    evaluation_scoped_tool_count: int = Field(ge=0)
    decision_ready_tool_count: int = Field(ge=0)
    action_count: int = Field(default=0, ge=0)
    action_implementation_count: int = Field(default=0, ge=0)
    action_bundle_count: int = Field(default=0, ge=0)
    hypothesis_edge_count: int = Field(ge=0)
    dangling_edge_count: int = Field(ge=0)
    duplicate_edge_count: int = Field(ge=0)
    edge_provenance_coverage: float = Field(ge=0.0, le=1.0)
    decision_edge_source_bound_rate: float = Field(ge=0.0, le=1.0)
    contract_io_coverage_rate: float = Field(ge=0.0, le=1.0)
    connected_component_count: int = Field(ge=0)
    isolated_node_count: int = Field(ge=0)
    integrity_passed: bool
    warnings: List[str] = Field(default_factory=list)


class DecisionGraphManifest(DecisionGraphModel):
    snapshot_id: str
    snapshot_version: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nodes_path: str
    edges_path: str
    quality_path: str
    nodes_sha256: str
    edges_sha256: str
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    action_bundles_path: str = ""
    action_bundles_sha256: str = ""
    action_bundle_count: int = Field(default=0, ge=0)
    canonical_snapshot_id: str = ""
    source_digest: str = ""
    input_fingerprints: Dict[str, str] = Field(default_factory=dict)


class DecisionToolCandidate(DecisionGraphModel):
    tool_name: str
    tool_node_id: str
    readiness: Literal[
        "decision_ready",
        "contract_verified",
        "planning_only",
        "source_material",
        "catalog_seed",
        "blocked",
    ]
    matched_task: str
    match_basis: Literal["contract", "source_metadata", "none"]
    source_chunk_count: int = Field(ge=0)
    contract_available: bool = False
    evaluation_available: bool = False
    execution_condition: str = "not_execution_eligible"
    blockers: List[str] = Field(default_factory=list)


class DecisionToolDossier(DecisionGraphModel):
    tool_name: str
    tool_node_id: str
    readiness: str
    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    inputs: List[Dict[str, Any]] = Field(default_factory=list)
    outputs: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    contracts: List[Dict[str, Any]] = Field(default_factory=list)
    environments: List[Dict[str, Any]] = Field(default_factory=list)
    parameters: List[Dict[str, Any]] = Field(default_factory=list)
    failure_modes: List[Dict[str, Any]] = Field(default_factory=list)
    validation_rules: List[Dict[str, Any]] = Field(default_factory=list)
    know_how: List[Dict[str, Any]] = Field(default_factory=list)
    source_material: List[Dict[str, Any]] = Field(default_factory=list)
    evaluations: List[Dict[str, Any]] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
