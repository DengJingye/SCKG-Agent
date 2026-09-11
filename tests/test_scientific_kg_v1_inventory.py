from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.build_scientific_kg_v1_inventory import (
    GRAPH_PATH,
    LAYERS,
    REPORT_PATH,
    build_inventory,
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_inventory_preserves_all_frozen_layers_without_identity_merge() -> None:
    graph = build_inventory()

    assert graph["baseline_commit"] == "25d0cff7e13a537d9e051e2976a87b4fcf6419c6"
    assert [item["layer_id"] for item in graph["layers"]] == [
        item.layer_id for item in LAYERS
    ]
    assert graph["layer_policy"]["identity_merge_performed"] is False
    assert graph["layer_policy"]["scientific_claim_rewrite_performed"] is False
    assert graph["layer_policy"]["canonical_kg_modified"] is False
    assert graph["inventory"]["status"]["promoted_or_trusted_scientific_claims"] == 0


def test_inventory_counts_are_exact_physical_frozen_records() -> None:
    graph = build_inventory()
    inventory = graph["inventory"]

    assert sum(inventory["entity_counts_by_type"].values()) == 411
    assert inventory["status"]["candidate_claims"] == 380
    assert inventory["status"]["candidate_derived_relations"] == 256
    assert inventory["derived_relation_counts_by_predicate"] == {
        "CAN_FEED": 80,
        "CONSUMES": 105,
        "PRODUCES": 71,
    }
    assert inventory["method_operator_port_chain_count"] == 69
    assert sum(inventory["graph_node_counts_by_type"].values()) == len(graph["nodes"])
    assert sum(inventory["graph_edge_counts_by_predicate"].values()) == len(graph["edges"])
    assert inventory["ecosystem_count"] >= 19
    assert inventory["task_count"] >= 18


def test_graph_exposes_identity_ports_claims_evidence_and_gaps() -> None:
    graph = build_inventory()
    predicates = {item["predicate"] for item in graph["edges"]}
    record_types = {item["record_type"] for item in graph["nodes"]}

    assert {
        "IMPLEMENTS_METHOD",
        "HAS_INPUT_PORT",
        "REQUIRES_CONSTRAINT",
        "HAS_OUTPUT_PORT",
        "OUTPUT_REPRESENTATION_TYPE",
        "CAN_FEED",
        "SUPPORTS",
    } <= predicates
    assert {
        "Method",
        "Operator",
        "OperatorRevision",
        "InputPort",
        "OutputPort",
        "RepresentationType",
        "AtomicClaimRevision",
        "EvidenceSpan",
        "EvidenceGap",
    } <= record_types


def test_representative_subgraphs_cover_required_scientific_domains() -> None:
    graph = build_inventory()
    subgraphs = {item["domain"]: item for item in graph["representative_subgraphs"]}

    assert set(subgraphs) == {
        "preprocessing",
        "integration",
        "annotation",
        "trajectory",
        "multi_omics",
        "regulatory",
    }
    assert all(item["operator_chains"] for item in subgraphs.values())


def test_exported_inventory_matches_builder_and_report_exists() -> None:
    exported = _json(GRAPH_PATH)

    assert exported["schema_version"] == build_inventory()["schema_version"]
    assert exported["inventory"] == build_inventory()["inventory"]
    assert REPORT_PATH.exists()
    assert "Promoted/trusted scientific claims | 0" in REPORT_PATH.read_text(
        encoding="utf-8"
    )
