from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


KGNodeType = Literal[
    "Tool",
    "Task",
    "Category",
    "Modality",
    "Publication",
    "Benchmark",
    "Source",
    "SourceChunk",
    "ToolContract",
    "Environment",
    "Dataset",
    "Evaluation",
    "Language",
    "RuntimePlatform",
    "Hardware",
    "Resolution",
    "AlgorithmFamily",
]
KGGovernanceLayer = Literal[
    "trusted_core",
    "execution_verified",
    "retrieval_only",
    "frozen",
    "quarantined",
]


class KnowledgeGraphBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KGGovernance(KnowledgeGraphBaseModel):
    layer: KGGovernanceLayer
    recommendation_eligible: bool = False
    source_bound: bool = False
    audit_status: str = "not_applicable"
    reason_codes: List[str] = Field(default_factory=list)
    provenance_refs: List[str] = Field(default_factory=list)

    @field_validator("reason_codes", "provenance_refs")
    @classmethod
    def normalize_values(cls, values: List[str]) -> List[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @model_validator(mode="after")
    def enforce_evidence_boundary(self) -> "KGGovernance":
        if self.recommendation_eligible and self.layer not in {"trusted_core"}:
            raise ValueError("only trusted_core records may be recommendation eligible")
        if self.recommendation_eligible and not self.source_bound:
            raise ValueError("recommendation-eligible records must be source bound")
        return self


class KGNodeRecord(KnowledgeGraphBaseModel):
    node_id: str = Field(min_length=1)
    node_type: KGNodeType
    label: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    governance: KGGovernance


class KGEdgeRecord(KnowledgeGraphBaseModel):
    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    properties: Dict[str, Any] = Field(default_factory=dict)
    governance: KGGovernance

    @model_validator(mode="after")
    def reject_self_edges(self) -> "KGEdgeRecord":
        if self.source_id == self.target_id:
            raise ValueError("self edges are not allowed")
        return self


class KGQualityReport(KnowledgeGraphBaseModel):
    snapshot_version: str
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    node_counts_by_type: Dict[str, int] = Field(default_factory=dict)
    node_counts_by_layer: Dict[str, int] = Field(default_factory=dict)
    edge_counts_by_relation: Dict[str, int] = Field(default_factory=dict)
    dangling_edge_count: int = Field(ge=0)
    duplicate_node_count: int = Field(ge=0)
    duplicate_edge_count: int = Field(ge=0)
    frozen_recommendation_leakage_count: int = Field(ge=0)
    trusted_source_bound_rate: float = Field(ge=0.0, le=1.0)
    recommendation_source_bound_rate: float = Field(ge=0.0, le=1.0)
    formal_publication_allowed_count: int = Field(ge=0)
    formal_benchmark_allowed_count: int = Field(ge=0)
    catalog_tool_count: int = Field(ge=0)
    canonical_tool_node_count: int = Field(default=0, ge=0)
    connected_tool_count: int = Field(ge=0)
    isolated_tool_count: int = Field(ge=0)
    execution_verified_tool_count: int = Field(ge=0)
    connected_component_count: int = Field(ge=0)
    largest_component_node_count: int = Field(ge=0)
    largest_component_ratio: float = Field(ge=0.0, le=1.0)
    isolated_node_count: int = Field(ge=0)
    tool_relation_coverage_rate: float = Field(ge=0.0, le=1.0)
    tool_semantic_coverage_rate: float = Field(ge=0.0, le=1.0)
    catalog_snapshot_available: bool = False
    catalog_category_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    catalog_reference_tool_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    catalog_publication_count: int = Field(default=0, ge=0)
    catalog_preprint_count: int = Field(default=0, ge=0)
    hypothesis_edge_count: int = Field(ge=0)
    hypothesis_recommendation_leakage_count: int = Field(ge=0)
    catalog_connectivity_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    source_bound_semantic_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    contract_qualified_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    formal_evidence_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    qualified_tool_governed_path_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    junk_task_count: int = Field(default=0, ge=0)
    unsupported_capability_edge_count: int = Field(default=0, ge=0)
    integrity_passed: bool
    warnings: List[str] = Field(default_factory=list)


class KGSnapshotManifest(KnowledgeGraphBaseModel):
    snapshot_id: str
    snapshot_version: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nodes_path: str
    edges_path: str
    quality_report_path: str
    nodes_sha256: str
    edges_sha256: str
    input_fingerprints: Dict[str, str] = Field(default_factory=dict)
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    neo4j_imported: bool = False
    neo4j_import_status: str = "not_attempted"
    canonical_snapshot_id: str = ""
    source_digest: str = ""


class KGToolExplanation(KnowledgeGraphBaseModel):
    tool_name: str
    tool_node_id: str
    trusted_tasks: List[str] = Field(default_factory=list)
    retrieval_tasks: List[str] = Field(default_factory=list)
    catalog_categories: List[Dict[str, Any]] = Field(default_factory=list)
    catalog_references: List[Dict[str, Any]] = Field(default_factory=list)
    contracts: List[Dict[str, Any]] = Field(default_factory=list)
    environments: List[Dict[str, Any]] = Field(default_factory=list)
    evaluations: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    frozen_or_quarantined: List[Dict[str, Any]] = Field(default_factory=list)
    modalities: List[Dict[str, Any]] = Field(default_factory=list)
    languages: List[Dict[str, Any]] = Field(default_factory=list)
    runtime_platforms: List[Dict[str, Any]] = Field(default_factory=list)
    algorithm_families: List[Dict[str, Any]] = Field(default_factory=list)
    hardware: List[Dict[str, Any]] = Field(default_factory=list)
    resolutions: List[Dict[str, Any]] = Field(default_factory=list)
    paths: List[List[str]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class KGToolMatch(KnowledgeGraphBaseModel):
    tool_name: str
    tool_node_id: str
    graph_score: float = Field(ge=0.0)
    candidate_basis: Literal["execution_verified", "catalog_metadata", "graph_hypothesis"]
    matched_task: str
    matched_modality: str
    paths: List[Dict[str, Any]] = Field(default_factory=list)
    contract_available: bool = False
    scientific_pilot_available: bool = False
    source_chunk_count: int = Field(default=0, ge=0)
    warnings: List[str] = Field(default_factory=list)
