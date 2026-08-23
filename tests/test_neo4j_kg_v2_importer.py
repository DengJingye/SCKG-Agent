from pathlib import Path

from engine.evidence_graph_builder import EvidenceGraphBuilder
from engine.neo4j_kg_v2_importer import Neo4jKGv2Importer
from tests.test_knowledge_graph_v2 import _graph_fixture


class FakeNeo4j:
    def __init__(self) -> None:
        self.calls = []
        self.node_count = 0
        self.edge_count = 0

    def execute(self, query, parameters):
        self.calls.append((query, parameters))
        if "MERGE (n:KGv2Node" in query:
            self.node_count += len(parameters["rows"])
        if "MERGE (source)-[r:KG_V2_REL" in query:
            self.edge_count += len(parameters["rows"])
        if "RETURN nodes, count(r) AS edges" in query:
            return [{"nodes": self.node_count, "edges": self.edge_count}]
        return []


def test_shadow_import_uses_isolated_namespace_and_preserves_counts(tmp_path: Path):
    data, contracts, environments, _ = _graph_fixture(tmp_path)
    graph_dir = data / "knowledge_graph_v2"
    nodes, edges, _ = EvidenceGraphBuilder(
        data_dir=data,
        contract_root=contracts,
        environment_root=environments,
        package_root=tmp_path / "packages",
        output_dir=graph_dir,
    ).build(write=True)
    fake = FakeNeo4j()

    result = Neo4jKGv2Importer(fake.execute, batch_size=2).import_snapshot(graph_dir)

    assert result.passed is True
    assert result.imported_nodes == len(nodes)
    assert result.imported_edges == len(edges)
    queries = "\n".join(query for query, _ in fake.calls)
    assert "KGv2Node" in queries
    assert "KG_V2_REL" in queries
    assert "CREATE INDEX kgv2_node_identity" in queries
    assert "CREATE INDEX kgv2_rel_identity" in queries
    assert "DETACH DELETE" not in queries
    assert "MATCH (n:Tool)" not in queries
