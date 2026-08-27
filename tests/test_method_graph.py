import json

from core.method_graph_models import MethodGraphQuality
from engine.method_graph import (
    MethodGraphBuilder,
    MethodGraphQuery,
    OptionalNeo4jMethodGraphProjector,
)


def test_method_graph_builds_canonical_projection_without_runtime_facts(tmp_path):
    manifest = MethodGraphBuilder().build(tmp_path / "method-graph")
    quality = MethodGraphQuality.model_validate_json(
        (tmp_path / "method-graph" / manifest.quality_path).read_text(encoding="utf-8")
    )

    assert manifest.neo4j_projection_required is False
    assert quality.integrity_passed is True
    assert quality.dangling_edge_count == 0
    assert quality.accidental_orphan_count == 0
    assert quality.unsupported_edge_count == 0
    assert quality.projection_drift_count == 0
    assert quality.runtime_state_fact_count == 0
    assert quality.node_counts_by_type["CapabilityPack"] == 2
    assert quality.node_counts_by_type["Method"] >= 17


def test_method_graph_uses_typed_representation_edges_not_ui_order(tmp_path):
    MethodGraphBuilder().build(tmp_path)
    query = MethodGraphQuery(tmp_path)
    umap = query.transition("scanpy_core.umap")
    leiden = query.transition("scanpy_core.leiden")
    marker = query.transition("scanpy_core.rank_markers")

    assert umap.consumes == ["neighbor_graph"]
    assert leiden.consumes == ["neighbor_graph"]
    assert "scanpy_core.umap" not in leiden.prerequisites
    assert "scanpy_core.leiden" not in umap.prerequisites
    assert marker.consumes == ["cluster_labels", "log1p_normalized"]
    assert "scaled_hvg" in marker.invalid_predecessors
    assert set(query.methods_consuming("neighbor_graph")) == {
        "scanpy_core.leiden",
        "scanpy_core.umap",
    }


def test_method_graph_keeps_mock_r_binding_in_same_schema(tmp_path):
    MethodGraphBuilder().build(tmp_path)
    query = MethodGraphQuery(tmp_path)
    transition = query.transition("mock_r.identity")

    assert transition.consumes == ["mock_r_input"]
    assert transition.produces == ["mock_r_table"]
    adapter = query.nodes["adapter:mock_rscript_adapter"]
    assert adapter.properties["runtime_kind"] == "rscript"


def test_neo4j_is_optional_and_query_remains_available(tmp_path):
    MethodGraphBuilder().build(tmp_path)
    projector = OptionalNeo4jMethodGraphProjector()

    assert projector.available is False
    assert projector.project(tmp_path) == {
        "status": "not_available",
        "projected": False,
        "reason": "neo4j_driver_unavailable",
    }
    assert MethodGraphQuery(tmp_path).available is True


def test_canonical_graph_contains_no_ledger_or_trace_state(tmp_path):
    MethodGraphBuilder().build(tmp_path)
    text = (tmp_path / "nodes.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]

    forbidden = {"run_id", "artifact_hash", "cell_index_hash", "gene_index_hash", "runtime_seconds"}
    assert all(not (forbidden & set(row["properties"])) for row in rows)
