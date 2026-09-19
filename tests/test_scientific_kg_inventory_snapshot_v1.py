from __future__ import annotations

import json

from data_pipeline.build_scientific_kg_v1_inventory import build_inventory
from eval.scientific_kg_inventory_snapshot_v1 import (
    OUTPUT_DIR,
    REPORT_PATH,
    governance_counts,
    integrity_issues,
    legacy_inventory,
    load_scientific_layers,
    readiness_counts,
    semantic_counts,
)


def _json(name: str) -> dict:
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def test_legacy_tool_kg_is_separate_and_manifest_verified() -> None:
    summary, node_counts, relation_counts = legacy_inventory()

    assert summary["role"] == "discovery_and_catalog"
    assert summary["nodes"] == 7537
    assert summary["edges"] == 17667
    assert summary["entity_type_count"] == len(node_counts) == 14
    assert summary["relation_type_count"] == len(relation_counts) == 27
    assert summary["manifest_counts_match"] is True
    assert summary["duplicate_node_ids"] == 0
    assert summary["duplicate_edge_ids"] == 0
    assert summary["dangling_edges"] == 0


def test_scientific_semantic_and_governance_counts_recompute_from_layers() -> None:
    graph = build_inventory()
    layers = load_scientific_layers()
    semantic = semantic_counts(layers, graph)
    governance = governance_counts(layers, graph)

    assert len(graph["nodes"]) == 1651
    assert len(graph["edges"]) == 2429
    assert semantic == _json("semantic_counts.json")
    assert governance == _json("governance_counts.json")
    assert semantic["requested_type_counts_physical"]["AtomicClaimRevision"] == 380
    assert semantic["requested_type_counts_physical"]["EvidenceAssessment"] == 380
    assert semantic["strict_source_revision_records"] == 6
    assert semantic["strict_source_revision_distinct_ids"] == 5
    assert semantic["legacy_core_source_records"] == 27
    assert governance["candidate_claims"] == 380
    assert governance["reviewed_claims"] == 0
    assert governance["trusted_or_canonical_claims"] == 0
    assert governance["trusted_source_evidence_nodes"] == 119


def test_uat_readiness_recomputes_exact_mapping_and_public_filter() -> None:
    readiness, detail = readiness_counts()
    exported = _json("readiness_counts.json")

    assert exported == {**readiness, **detail}
    assert readiness["operator_revision_count"] == 8
    assert readiness["highest_exclusive"] == {
        "L0": 0,
        "L1": 0,
        "L2": 2,
        "L3": 0,
        "L4": 6,
    }
    assert readiness["threshold_counts"]["L4_or_higher"] == 6
    assert readiness["operator_revisions_without_any_mapped_direct_evidence"] == 2
    assert readiness["broad_candidate_coverage_is_readiness"] is False


def test_integrity_has_no_hard_errors_and_declares_reference_warnings() -> None:
    graph = build_inventory()
    layers = load_scientific_layers()
    readiness, _ = readiness_counts()
    integrity = integrity_issues(layers, graph, readiness)

    assert integrity == _json("integrity_issues.json")
    assert integrity["status"] == "PASS_WITH_DECLARED_WARNINGS"
    assert integrity["hard_issue_count"] == 0
    assert integrity["consolidated_graph_dangling_edges"] == []
    assert sum(row["referenced_spans_not_materialized"] for row in integrity["per_layer"]) == 32
    assert sum(row["materialized_spans_not_referenced"] for row in integrity["per_layer"]) == 11


def test_snapshot_artifacts_and_read_only_contract_are_complete() -> None:
    expected = {
        "manifest.json",
        "node_type_counts.json",
        "relation_type_counts.json",
        "semantic_counts.json",
        "governance_counts.json",
        "readiness_counts.json",
        "evidence_coverage.json",
        "integrity_issues.json",
        "hashes.json",
    }
    assert expected == {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
    manifest = _json("manifest.json")
    hashes = _json("hashes.json")
    assert manifest["status"] == "PASS"
    assert manifest["audit_mode"] == "read_only"
    assert manifest["legacy_and_scientific_separated"] is True
    assert manifest["broad_coverage_and_readiness_separated"] is True
    assert manifest["kg_content_changed"] is False
    assert manifest["canonical_promotion"] is False
    assert hashes["protected_unchanged"] is True
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "STOPPED=true" in report
    assert "NEXT_EARLIEST_DIVERGENCE=Checkpoint 2" in report
