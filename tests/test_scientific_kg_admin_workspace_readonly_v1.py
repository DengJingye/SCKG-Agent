from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine.scientific_kg_admin import ScientificKGAdminSnapshotService


ROOT = Path(__file__).resolve().parents[1]


def _service() -> ScientificKGAdminSnapshotService:
    return ScientificKGAdminSnapshotService(ROOT)


def test_scientific_kg_counts_and_governance_match_frozen_snapshot() -> None:
    summary = _service().summary()

    assert summary["scientific_kg_nodes"] == 1651
    assert summary["scientific_kg_edges"] == 2429
    assert summary["candidate_claims"] == 380
    assert summary["reviewed_claims"] == 0
    assert summary["trusted_claims"] == 0
    assert summary["snapshot_status"] == "IDENTITY_MATCH"


def test_readiness_integrity_and_source_revision_identity_are_preserved() -> None:
    service = _service()
    summary = service.summary()
    rows = service.readiness_rows()

    assert summary["audited_operator_revisions"] == 8
    assert summary["readiness_highest_exclusive"]["L4"] == 6
    assert summary["readiness_highest_exclusive"]["L2"] == 2
    assert len(rows) == 8
    assert sum(row["highest_level"] == "L4" for row in rows) == 6
    assert sum(row["highest_level"] == "L2" for row in rows) == 2
    assert summary["hard_issues"] == 0
    assert sum(row["count"] for row in service.integrity_groups()) == 43
    assert summary["source_revision_physical"] == 6
    assert summary["source_revision_unique"] == 5


def test_legacy_and_decision_graph_counts_cannot_enter_scientific_total() -> None:
    service = _service()
    summary = service.summary()
    boundaries = service.layer_boundaries()

    assert summary["legacy_kg_nodes"] == 7537
    assert summary["scientific_kg_nodes"] != summary["legacy_kg_nodes"]
    assert {row["layer_id"] for row in boundaries} == {
        "LEGACY_TOOL_KG",
        "DECISION_GRAPH",
        "SCIENTIFIC_KG",
    }
    decision = next(row for row in boundaries if row["layer_id"] == "DECISION_GRAPH")
    assert decision["node_count"] != summary["scientific_kg_nodes"]
    assert service.total_policy() == "DO_NOT_SUM_ACROSS_LAYERS"


def test_semantic_and_relation_inventory_use_actual_snapshot_predicates() -> None:
    service = _service()
    semantics = {row["type"]: row for row in service.semantic_inventory()}
    relations = {row["relation"]: row for row in service.relation_inventory()}

    assert semantics["AtomicClaimRevision"]["count"] == 380
    assert semantics["EvidenceSpan"]["count"] == 170
    assert semantics["SourceRevision"]["count"] == 6
    assert relations["CAN_FEED"]["count"] == 80
    assert relations["SUPPORTS"]["count"] == 481
    assert "IMPLEMENTS" not in relations


def test_search_returns_scientific_identity_and_is_deterministic() -> None:
    service = _service()
    first = service.search_nodes("neighbors", node_types={"OperatorRevision"})
    second = service.search_nodes("neighbors", node_types={"OperatorRevision"})

    assert first == second
    assert first
    assert first[0]["node_type"] == "OperatorRevision"
    assert first[0]["canonical_id"].startswith("operator-revision:")
    assert first[0]["graph_node_id"].startswith(first[0]["layer"] + "::")


def test_local_graph_cap_and_one_hop_expansion_are_deterministic() -> None:
    service = _service()
    seed = service.search_nodes("neighbors", node_types={"OperatorRevision"})[0]["graph_node_id"]
    one = service.get_neighborhood(seed, hops=1, max_nodes=12)
    repeated = service.get_neighborhood(seed, hops=1, max_nodes=12)
    capped = service.get_neighborhood(seed, hops=2, max_nodes=5)

    assert one == repeated
    assert len(one["nodes"]) <= 12
    assert len(capped["nodes"]) == 5
    assert capped["truncated"] is True


def test_pca_neighbors_and_leiden_examples_are_small_real_subgraphs() -> None:
    service = _service()
    for example in ("PCA", "neighbors", "Leiden"):
        graph = service.example_graph(example, max_nodes=75)
        kinds = {graph.nodes[node_id].kind for node_id in graph.visible_node_ids}
        relations = {edge.relation for edge in graph.visible_edges}
        assert len(graph.visible_node_ids) <= 75
        assert "OperatorRevision" in kinds
        assert "AtomicClaimRevision" in kinds
        assert "EvidenceSpan" in kinds
        assert "SourceRevision" in kinds
        assert "SUPPORTS" in relations
        assert "RESOLVES_TO_SOURCE_REVISION" in relations
        source_id = next(
            node_id
            for node_id in graph.visible_node_ids
            if graph.nodes[node_id].kind == "SourceRevision"
        )
        assert service.get_node(source_id)["record"]


def test_materialized_claim_evidence_source_drilldown_resolves() -> None:
    service = _service()
    claim = service.search_nodes("pca input", node_types={"AtomicClaimRevision"})[0]
    chain = service.get_claim_evidence_chain(claim["graph_node_id"])

    assert chain["claim"]["node_type"] == "AtomicClaimRevision"
    assert chain["assessments"]
    assert chain["evidence"]
    assert all(row["materialized"] for row in chain["evidence"])
    assert all(row["source_revision"] for row in chain["evidence"])
    assert chain["complete"] is True


def test_incomplete_evidence_chain_remains_visible() -> None:
    service = _service()
    claim_id = service.first_incomplete_claim_id()
    chain = service.get_claim_evidence_chain(claim_id)

    assert chain["complete"] is False
    assert chain["incomplete_reasons"]
    assert any(not row["materialized"] or not row["source_revision"] for row in chain["evidence"])


def test_candidate_is_never_rendered_as_trusted() -> None:
    service = _service()
    claims = service.search_nodes("", node_types={"AtomicClaimRevision"}, limit=25)

    assert claims
    assert all(row["knowledge_status"] != "trusted" for row in claims)
    assert all(row["knowledge_status"] != "canonical" for row in claims)


def test_service_has_no_mutation_surface() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(ScientificKGAdminSnapshotService, inspect.isfunction)
        if not name.startswith("_")
    }
    forbidden = {"write", "upload", "extract", "promote", "reject", "merge", "supersede", "delete", "update"}

    assert not public_methods & forbidden
    assert all(not any(token in name for token in forbidden) for name in public_methods)


def test_service_reads_do_not_change_kg_corpus_or_index_files() -> None:
    protected = [
        ROOT / "data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json",
        ROOT / "data/knowledge_graph_v2/nodes.jsonl",
        ROOT / "data/decision_graph_v3/nodes.jsonl",
        ROOT / "data/indexes/retrieval_foundation_v1/evidence_chunks.jsonl",
        ROOT / "data/indexes/retrieval_foundation_v1/evidence_fts5.sqlite",
    ]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    service = _service()
    service.summary()
    service.example_graph("PCA")
    service.get_claim_evidence_chain(
        service.search_nodes("pca input", node_types={"AtomicClaimRevision"})[0]["graph_node_id"]
    )
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}

    assert before == after


def test_app_keeps_existing_admin_surfaces_and_adds_explicit_scientific_kg() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")

    for function_name in (
        "_render_graph_explorer_page",
        "_render_knowledge_review_panel",
        "_render_evidence_admin_panel",
        "_render_evaluation_admin_panel",
        "_render_architecture_admin_panel",
        "_render_scientific_kg_admin_page",
    ):
        assert f"def {function_name}" in source
    assert '("Scientific KG", "scientific_kg_admin")' in source
    assert 'current_view == "scientific_kg_admin"' in source
    assert "Admin · Scientific KG" in source
    assert "data/knowledge_graph_v2" not in inspect.getsource(ScientificKGAdminSnapshotService)


def test_scientific_kg_admin_page_renders_frozen_counts_and_three_tabs() -> None:
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Scientific KG").click().run(
        timeout=30
    )

    assert len(app.exception) == 0
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Scientific Graph",
        "Readiness & Integrity",
    ]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Scientific nodes"] == "1,651"
    assert metrics["Scientific edges"] == "2,429"
    assert metrics["Candidate claims"] == "380"
    assert metrics["Reviewed claims"] == "0"
    assert metrics["Trusted claims"] == "0"
    assert metrics["Readiness L4"] == "6/8"
