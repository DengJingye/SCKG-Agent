from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from core.knowledge_graph_models import KGEdgeRecord, KGNodeRecord


NODE_LABELS = {
    "Tool": "KGv2Tool",
    "Task": "KGv2Task",
    "Category": "KGv2Category",
    "Modality": "KGv2Modality",
    "Publication": "KGv2Publication",
    "Benchmark": "KGv2Benchmark",
    "Source": "KGv2Source",
    "SourceChunk": "KGv2SourceChunk",
    "ToolContract": "KGv2ToolContract",
    "Environment": "KGv2Environment",
    "Dataset": "KGv2Dataset",
    "Evaluation": "KGv2Evaluation",
    "Language": "KGv2Language",
    "RuntimePlatform": "KGv2RuntimePlatform",
    "Hardware": "KGv2Hardware",
    "Resolution": "KGv2Resolution",
    "AlgorithmFamily": "KGv2AlgorithmFamily",
}


@dataclass(frozen=True)
class KGv2ImportResult:
    snapshot_version: str
    expected_nodes: int
    expected_edges: int
    imported_nodes: int
    imported_edges: int
    node_count_matches: bool
    edge_count_matches: bool
    namespace: str = "KGv2Node/KG_V2_REL"

    @property
    def passed(self) -> bool:
        return self.node_count_matches and self.edge_count_matches


class Neo4jKGv2Importer:
    """Non-destructive shadow importer for a governed JSONL snapshot.

    Existing legacy Tool/Task/Algorithm nodes are untouched. Re-import marks
    prior records in the KG v2 namespace inactive before activating the current
    deterministic snapshot.
    """

    def __init__(
        self,
        execute_query: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
        *,
        batch_size: int = 1000,
    ) -> None:
        self.execute_query = execute_query
        self.batch_size = batch_size

    def import_snapshot(self, graph_dir: Path) -> KGv2ImportResult:
        graph_dir = Path(graph_dir)
        manifest = json.loads((graph_dir / "manifest.json").read_text(encoding="utf-8"))
        snapshot_version = str(manifest["snapshot_version"])
        nodes = [KGNodeRecord.model_validate(row) for row in _read_jsonl(graph_dir / "nodes.jsonl")]
        edges = [KGEdgeRecord.model_validate(row) for row in _read_jsonl(graph_dir / "edges.jsonl")]
        self._ensure_indexes()
        self._mark_previous_inactive(snapshot_version)
        for batch in _batches(nodes, self.batch_size):
            self._import_nodes(snapshot_version, batch)
        for node_type, label in NODE_LABELS.items():
            self.execute_query(
                f"MATCH (n:KGv2Node {{snapshot_version: $snapshot_version, node_type: $node_type}}) SET n:{label}",
                {"snapshot_version": snapshot_version, "node_type": node_type},
            )
        for batch in _batches(edges, self.batch_size):
            self._import_edges(snapshot_version, batch)
        counts = self.execute_query(
            """
            MATCH (n:KGv2Node {snapshot_version: $snapshot_version, active: true})
            WITH count(n) AS nodes
            OPTIONAL MATCH ()-[r:KG_V2_REL {snapshot_version: $snapshot_version, active: true}]->()
            RETURN nodes, count(r) AS edges
            """,
            {"snapshot_version": snapshot_version},
        )
        row = counts[0] if counts else {}
        imported_nodes = int(row.get("nodes", 0))
        imported_edges = int(row.get("edges", 0))
        return KGv2ImportResult(
            snapshot_version=snapshot_version,
            expected_nodes=len(nodes),
            expected_edges=len(edges),
            imported_nodes=imported_nodes,
            imported_edges=imported_edges,
            node_count_matches=imported_nodes == len(nodes),
            edge_count_matches=imported_edges == len(edges),
        )

    def _mark_previous_inactive(self, snapshot_version: str) -> None:
        self.execute_query(
            "MATCH (n:KGv2Node) SET n.active = false",
            {"snapshot_version": snapshot_version},
        )
        self.execute_query(
            "MATCH ()-[r:KG_V2_REL]->() SET r.active = false",
            {"snapshot_version": snapshot_version},
        )

    def _ensure_indexes(self) -> None:
        self.execute_query(
            "CREATE INDEX kgv2_node_identity IF NOT EXISTS "
            "FOR (n:KGv2Node) ON (n.node_id, n.snapshot_version)",
            {},
        )
        self.execute_query(
            "CREATE INDEX kgv2_rel_identity IF NOT EXISTS "
            "FOR ()-[r:KG_V2_REL]-() ON (r.edge_id, r.snapshot_version)",
            {},
        )
        self.execute_query("CALL db.awaitIndexes(300)", {})

    def _import_nodes(self, snapshot_version: str, nodes: List[KGNodeRecord]) -> None:
        rows = []
        for node in nodes:
            rows.append(
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "display_label": node.label,
                    "properties_json": json.dumps(node.properties, ensure_ascii=False, sort_keys=True),
                    "governance_layer": node.governance.layer,
                    "recommendation_eligible": node.governance.recommendation_eligible,
                    "source_bound": node.governance.source_bound,
                    "audit_status": node.governance.audit_status,
                    "reason_codes": node.governance.reason_codes,
                    "provenance_refs": node.governance.provenance_refs,
                }
            )
        self.execute_query(
            """
            UNWIND $rows AS row
            MERGE (n:KGv2Node {node_id: row.node_id, snapshot_version: $snapshot_version})
            SET n += row, n.active = true
            """,
            {"snapshot_version": snapshot_version, "rows": rows},
        )

    def _import_edges(self, snapshot_version: str, edges: List[KGEdgeRecord]) -> None:
        rows = []
        for edge in edges:
            rows.append(
                {
                    "edge_id": edge.edge_id,
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "relation": edge.relation,
                    "properties_json": json.dumps(edge.properties, ensure_ascii=False, sort_keys=True),
                    "governance_layer": edge.governance.layer,
                    "recommendation_eligible": edge.governance.recommendation_eligible,
                    "source_bound": edge.governance.source_bound,
                    "audit_status": edge.governance.audit_status,
                    "reason_codes": edge.governance.reason_codes,
                    "provenance_refs": edge.governance.provenance_refs,
                }
            )
        self.execute_query(
            """
            UNWIND $rows AS row
            MATCH (source:KGv2Node {node_id: row.source_id, snapshot_version: $snapshot_version})
            MATCH (target:KGv2Node {node_id: row.target_id, snapshot_version: $snapshot_version})
            MERGE (source)-[r:KG_V2_REL {edge_id: row.edge_id, snapshot_version: $snapshot_version}]->(target)
            SET r += row, r.active = true
            """,
            {"snapshot_version": snapshot_version, "rows": rows},
        )


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def _batches(values: List[Any], batch_size: int) -> Iterable[List[Any]]:
    for index in range(0, len(values), batch_size):
        yield values[index : index + batch_size]
