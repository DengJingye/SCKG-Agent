from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from core.execution_models import StrictModel


MethodGraphNodeType = Literal[
    "CapabilityPack",
    "Capability",
    "Method",
    "Representation",
    "Tool",
    "ToolContract",
    "Environment",
    "ExecutionAdapter",
    "NotebookRenderer",
    "Validation",
    "Evidence",
    "GoldCase",
]

MethodGraphRelation = Literal[
    "CONTAINS",
    "PROVIDES",
    "CONSUMES",
    "PRODUCES",
    "REQUIRES",
    "PRECEDES",
    "COMPATIBLE_WITH",
    "ALTERNATIVE_TO",
    "COMPLEMENTS",
    "HAS_LIMITATION",
    "SUPPORTED_BY",
    "IMPLEMENTS",
    "BOUND_BY",
    "VALIDATED_BY",
    "RENDERED_BY",
    "RUNS_IN",
    "EVALUATED_BY",
]


class MethodGraphNode(StrictModel):
    node_id: str = Field(min_length=1)
    node_type: MethodGraphNodeType
    label: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    source_pack_id: str = Field(min_length=1)
    stable_domain_fact: bool = True


class MethodGraphEdge(StrictModel):
    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: MethodGraphRelation
    properties: dict[str, Any] = Field(default_factory=dict)
    source_pack_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def reject_self_edge(self) -> "MethodGraphEdge":
        if self.source_id == self.target_id:
            raise ValueError("Method Graph self edges are forbidden")
        return self


class MethodGraphQuality(StrictModel):
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    node_counts_by_type: dict[str, int]
    edge_counts_by_relation: dict[str, int]
    dangling_edge_count: int = Field(ge=0)
    accidental_orphan_count: int = Field(ge=0)
    unsupported_edge_count: int = Field(ge=0)
    projection_drift_count: int = Field(ge=0)
    runtime_state_fact_count: int = Field(ge=0)
    integrity_passed: bool
    warnings: list[str] = Field(default_factory=list)


class MethodGraphManifest(StrictModel):
    schema_version: Literal["sckg-method-graph-v0"] = "sckg-method-graph-v0"
    snapshot_id: str
    source_digest: str = Field(min_length=64, max_length=64)
    nodes_path: str
    edges_path: str
    quality_path: str
    nodes_sha256: str = Field(min_length=64, max_length=64)
    edges_sha256: str = Field(min_length=64, max_length=64)
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    neo4j_projection_required: Literal[False] = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MethodTransition(StrictModel):
    method_id: str
    consumes: list[str]
    produces: list[str]
    prerequisites: list[str]
    invalid_predecessors: list[str]
    supporting_evidence: list[str]
    planning_ready: bool
