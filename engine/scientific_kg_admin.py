from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from engine.knowledge_graph_view import GraphEdge, GraphNode, KnowledgeGraphView


_LAYER_CONFIG = (
    (
        "uat_decision_rule_correction",
        "scientific_kg_v1_uat_decision_rules",
        "corrected candidate overlay",
        "authoritative_evidence_spans.jsonl",
        "authoritative_source_manifest.json",
    ),
    (
        "scientific_kg_v1_core",
        "scientific_kg_v1_core",
        "v1 core candidate",
        "evidence_spans.jsonl",
        "source_manifest.json",
    ),
    (
        "content_expansion_v1",
        "scientific_kg_content_expansion_v1",
        "broad coverage reference",
        "evidence_span_references.jsonl",
        None,
    ),
    (
        "scanpy_core_reference_slice",
        "scientific_knowledge_scanpy_core_v1_1",
        "superseded reference implementation",
        "authoritative_evidence_spans.jsonl",
        "authoritative_source_manifest.json",
    ),
)
_LAYER_PRIORITY = {row[0]: index for index, row in enumerate(_LAYER_CONFIG)}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


class ScientificKGAdminSnapshotService:
    """Read-only projection over the frozen Scientific KG inventory snapshot.

    This service deliberately exposes inspection methods only. It reads the
    checkpoint-1 snapshot and its frozen source layers without changing or
    promoting any knowledge record.
    """

    def __init__(self, repository_root: Path | None = None) -> None:
        self._root = Path(repository_root or Path(__file__).resolve().parents[1])
        self._snapshot_dir = (
            self._root / "data" / "evaluation" / "scientific_kg_inventory_snapshot_v1"
        )
        self._evidence_root = self._root / "data" / "evidence_candidates"
        self._graph_path = (
            self._evidence_root
            / "scientific_kg_v1_inventory"
            / "scientific_kg_v1_consolidated_graph.json"
        )
        self._graph = _json(self._graph_path)
        self._nodes = {row["graph_node_id"]: row for row in self._graph["nodes"]}
        self._edges = list(self._graph["edges"])
        self._adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for edge in self._edges:
            source = edge["source_graph_node_id"]
            target = edge["target_graph_node_id"]
            self._adjacency[source].append((target, edge))
            self._adjacency[target].append((source, edge))
        for links in self._adjacency.values():
            links.sort(key=lambda item: (item[1]["predicate"], item[0]))

        self._semantic = _json(self._snapshot_dir / "semantic_counts.json")
        self._node_counts = _json(self._snapshot_dir / "node_type_counts.json")
        self._relation_counts = _json(self._snapshot_dir / "relation_type_counts.json")
        self._readiness = _json(self._snapshot_dir / "readiness_counts.json")
        self._integrity = _json(self._snapshot_dir / "integrity_issues.json")
        self._governance = _json(self._snapshot_dir / "governance_counts.json")
        self._hashes = _json(self._snapshot_dir / "hashes.json")
        self._layers = self._load_layers()

    def summary(self) -> dict[str, Any]:
        legacy_nodes = sum(self._node_counts["legacy_tool_kg"].values())
        legacy_edges = sum(self._relation_counts["legacy_tool_kg"].values())
        physical = self._semantic["requested_type_counts_physical"]
        return {
            "scientific_kg_nodes": len(self._nodes),
            "scientific_kg_edges": len(self._edges),
            "legacy_kg_nodes": legacy_nodes,
            "legacy_kg_edges": legacy_edges,
            "decision_graph_nodes": _line_count(
                self._root / "data" / "decision_graph_v3" / "nodes.jsonl"
            ),
            "decision_graph_edges": _line_count(
                self._root / "data" / "decision_graph_v3" / "edges.jsonl"
            ),
            "candidate_claims": self._governance["candidate_claims"],
            "reviewed_claims": self._governance["reviewed_claims"],
            "trusted_claims": self._governance["trusted_or_canonical_claims"],
            "evidence_spans": physical["EvidenceSpan"],
            "evidence_gaps": physical["EvidenceGap"],
            "source_revision_physical": physical["SourceRevision"],
            "source_revision_unique": self._semantic["strict_source_revision_distinct_ids"],
            "audited_operator_revisions": self._readiness["operator_revision_count"],
            "readiness_highest_exclusive": self._readiness["highest_exclusive"],
            "hard_issues": self._integrity["hard_issue_count"],
            "warnings": self._integrity["warning_count"],
            "snapshot_status": self._snapshot_identity(),
        }

    def layer_boundaries(self) -> list[dict[str, Any]]:
        summary = self.summary()
        return [
            {
                "layer_id": "LEGACY_TOOL_KG",
                "name": "Legacy Tool KG",
                "node_count": summary["legacy_kg_nodes"],
                "edge_count": summary["legacy_kg_edges"],
                "meaning": "tool catalog, publications, tasks, and retrieval source records",
                "source": "knowledge graph v2 frozen files",
            },
            {
                "layer_id": "DECISION_GRAPH",
                "name": "Decision Graph",
                "node_count": summary["decision_graph_nodes"],
                "edge_count": summary["decision_graph_edges"],
                "meaning": "decision-time action, dossier, and governance projection",
                "source": "decision graph v3 frozen files",
            },
            {
                "layer_id": "SCIENTIFIC_KG",
                "name": "Scientific KG",
                "node_count": summary["scientific_kg_nodes"],
                "edge_count": summary["scientific_kg_edges"],
                "meaning": "candidate scientific semantics, evidence, scope, and readiness",
                "source": "checkpoint-1 consolidated inventory",
            },
        ]

    def total_policy(self) -> str:
        return "DO_NOT_SUM_ACROSS_LAYERS"

    def semantic_inventory(self) -> list[dict[str, Any]]:
        physical = self._semantic["requested_type_counts_physical"]
        distinct = self._semantic["requested_type_counts_distinct_id"]
        return [
            {"type": key, "count": value, "distinct_id_count": distinct.get(key, value)}
            for key, value in sorted(physical.items())
        ]

    def relation_inventory(self) -> list[dict[str, Any]]:
        return [
            {"relation": key, "count": value}
            for key, value in sorted(self._relation_counts["scientific_kg"].items())
        ]

    def readiness_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._readiness["operators"]]

    def integrity_groups(self) -> list[dict[str, Any]]:
        return [
            {
                "severity": "WARNING",
                "layer_id": row["layer_id"],
                "issue_type": row["type"],
                "count": row["count"],
                "ids": list(row.get("ids", [])),
            }
            for row in self._integrity["warnings"]
        ]

    def search_nodes(
        self,
        query: str,
        *,
        node_types: set[str] | None = None,
        statuses: set[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        terms = tuple(part for part in needle.split() if part)
        allowed_types = set(node_types or ())
        allowed_statuses = set(statuses or ())
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for node in self._nodes.values():
            if allowed_types and node["record_type"] not in allowed_types:
                continue
            if allowed_statuses and node["status"] not in allowed_statuses:
                continue
            searchable = " ".join(
                (
                    str(node.get("label", "")),
                    str(node.get("record_id", "")),
                    json.dumps(node.get("record", {}), sort_keys=True),
                )
            ).casefold()
            if terms and not all(term in searchable for term in terms):
                continue
            exact_label = 0 if needle and needle == str(node.get("label", "")).casefold() else 1
            starts = 0 if needle and str(node.get("label", "")).casefold().startswith(needle) else 1
            rank = (
                exact_label,
                starts,
                _LAYER_PRIORITY.get(node["layer_id"], 99),
                str(node.get("label", "")).casefold(),
                node["graph_node_id"],
            )
            ranked.append((rank, self._node_projection(node)))
        ranked.sort(key=lambda item: item[0])
        return [item[1] for item in ranked[: max(1, min(int(limit), 250))]]

    def get_node(self, graph_node_id: str) -> dict[str, Any] | None:
        node = self._nodes.get(graph_node_id)
        if node:
            return self._node_projection(node)
        prefix = "source-record::"
        if graph_node_id.startswith(prefix):
            remainder = graph_node_id[len(prefix) :]
            layer_id, separator, source_id = remainder.partition("::")
            layer = self._layers.get(layer_id)
            source = layer["sources"].get(source_id) if layer and separator else None
            if source:
                return {
                    "graph_node_id": graph_node_id,
                    "canonical_id": source_id,
                    "label": source_id,
                    "node_type": "SourceRevision",
                    "layer": layer_id,
                    "status": "candidate_source_record",
                    "knowledge_status": "source_evidence",
                    "ecosystem": None,
                    "record": source,
                }
        return None

    def get_neighborhood(
        self, graph_node_id: str, *, hops: int = 1, max_nodes: int = 75
    ) -> dict[str, Any]:
        if graph_node_id not in self._nodes:
            raise KeyError(f"unknown Scientific KG node: {graph_node_id}")
        hops = max(0, min(int(hops), 2))
        cap = max(1, min(int(max_nodes), 100))
        queue: deque[tuple[str, int]] = deque([(graph_node_id, 0)])
        selected: list[str] = []
        seen = {graph_node_id}
        discovered_beyond_cap = False
        while queue:
            node_id, depth = queue.popleft()
            if len(selected) >= cap:
                discovered_beyond_cap = True
                break
            selected.append(node_id)
            if depth >= hops:
                continue
            for neighbor_id, _edge in self._adjacency.get(node_id, []):
                if neighbor_id not in seen:
                    seen.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))
        selected_set = set(selected)
        visible_edges = [
            edge
            for edge in self._edges
            if edge["source_graph_node_id"] in selected_set
            and edge["target_graph_node_id"] in selected_set
        ]
        return {
            "seed_id": graph_node_id,
            "hops": hops,
            "nodes": [self._node_projection(self._nodes[node_id]) for node_id in selected],
            "edges": [self._edge_projection(edge) for edge in visible_edges],
            "truncated": discovered_beyond_cap or len(seen) > len(selected),
        }

    def example_graph(self, name: str, *, max_nodes: int = 75) -> KnowledgeGraphView:
        matches = self.search_nodes(name, node_types={"OperatorRevision"}, limit=25)
        if not matches:
            raise KeyError(f"no OperatorRevision example for {name!r}")
        preferred = next(
            (row for row in matches if row["layer"] == "uat_decision_rule_correction"),
            matches[0],
        )
        neighborhood = self.get_neighborhood(
            preferred["graph_node_id"], hops=2, max_nodes=max_nodes
        )
        return self._with_source_projections(
            self._knowledge_graph_view(neighborhood), max_nodes=max_nodes
        )

    def neighborhood_graph(
        self, graph_node_id: str, *, hops: int = 1, max_nodes: int = 75
    ) -> KnowledgeGraphView:
        return self._knowledge_graph_view(
            self.get_neighborhood(graph_node_id, hops=hops, max_nodes=max_nodes)
        )

    def global_graph(self, *, max_nodes: int = 2000) -> KnowledgeGraphView:
        """Return a deterministic read-only projection of the frozen instance graph."""

        cap = max(1, min(int(max_nodes), 2000))
        ordered = sorted(
            self._nodes.values(),
            key=lambda row: (
                _LAYER_PRIORITY.get(row["layer_id"], 99),
                row["record_type"],
                str(row.get("label", "")).casefold(),
                row["graph_node_id"],
            ),
        )
        selected = ordered[:cap]
        selected_ids = {row["graph_node_id"] for row in selected}
        edges = [
            row
            for row in self._edges
            if row["source_graph_node_id"] in selected_ids
            and row["target_graph_node_id"] in selected_ids
        ]
        return self._knowledge_graph_view(
            {
                "nodes": [self._node_projection(row) for row in selected],
                "edges": [self._edge_projection(row) for row in edges],
                "truncated": len(selected) < len(self._nodes),
            }
        )

    def get_claim_evidence_chain(self, claim_graph_node_id: str) -> dict[str, Any]:
        claim_node = self._nodes.get(claim_graph_node_id)
        if not claim_node or claim_node["record_type"] != "AtomicClaimRevision":
            raise KeyError(f"not an AtomicClaimRevision: {claim_graph_node_id}")
        layer_id = claim_node["layer_id"]
        layer = self._layers[layer_id]
        claim_id = claim_node["record_id"]
        assessments = [
            dict(row)
            for row in layer["assessments"]
            if row.get("claim_revision_id") == claim_id
        ]
        evidence_ids = sorted(
            {
                str(span_id)
                for row in assessments
                for span_id in row.get("evidence_span_ids", [])
            }
        )
        evidence = []
        incomplete: list[str] = []
        for span_id in evidence_ids:
            span = layer["evidence"].get(span_id)
            source = self._source_for_span(layer, span) if span else None
            if span is None:
                incomplete.append(f"evidence span is referenced but not materialized: {span_id}")
            elif source is None:
                incomplete.append(f"evidence span has no resolvable source record: {span_id}")
            evidence.append(
                {
                    "evidence_span_id": span_id,
                    "materialized": span is not None,
                    "evidence_span": span,
                    "source_revision": source,
                    "source_status": "resolved" if source else "missing",
                }
            )
        if not assessments:
            incomplete.append("claim has no evidence assessment")
        if assessments and not evidence_ids:
            incomplete.append("evidence assessment has no evidence span binding")
        scope_id = claim_node["record"].get("scope_id")
        scope = layer["scopes"].get(str(scope_id)) if scope_id else None
        if scope_id and scope is None:
            incomplete.append(f"scope is not materialized in layer: {scope_id}")
        return {
            "claim": self._node_projection(claim_node),
            "scope": scope,
            "assessments": assessments,
            "evidence": evidence,
            "complete": not incomplete,
            "incomplete_reasons": incomplete,
            "governance_note": (
                "Candidate claim status is independent of source authority; source evidence "
                "does not promote the claim."
            ),
        }

    def first_incomplete_claim_id(self) -> str:
        claim_ids = sorted(
            (
                node["graph_node_id"]
                for node in self._nodes.values()
                if node["record_type"] == "AtomicClaimRevision"
            ),
            key=lambda graph_id: (
                _LAYER_PRIORITY.get(self._nodes[graph_id]["layer_id"], 99), graph_id
            ),
        )
        for claim_id in claim_ids:
            chain = self.get_claim_evidence_chain(claim_id)
            if not chain["complete"]:
                return claim_id
        raise LookupError("the frozen snapshot contains no incomplete claim-evidence chain")

    def _snapshot_identity(self) -> str:
        expected = self._hashes["generated_artifact_sha256"]
        for name, digest in expected.items():
            path = self._snapshot_dir / name
            if not path.exists() or _sha256(path) != digest:
                return "IDENTITY_MISMATCH"
        graph_counts = self._node_counts["scientific_kg"]
        if Counter(row["record_type"] for row in self._nodes.values()) != Counter(graph_counts):
            return "IDENTITY_MISMATCH"
        if sum(self._relation_counts["scientific_kg"].values()) != len(self._edges):
            return "IDENTITY_MISMATCH"
        return "IDENTITY_MATCH"

    def _load_layers(self) -> dict[str, dict[str, Any]]:
        layers: dict[str, dict[str, Any]] = {}
        for layer_id, directory, role, evidence_file, source_file in _LAYER_CONFIG:
            root = self._evidence_root / directory
            bundle = _json(root / "conformance_bundle.json")
            evidence_rows = _jsonl(root / evidence_file)
            assessments = _jsonl(root / "evidence_assessments.jsonl")
            if not assessments:
                assessments = list(bundle.get("evidence_assessments", []))
            source_rows: list[dict[str, Any]] = []
            if source_file and (root / source_file).exists():
                payload = _json(root / source_file)
                source_rows = list(payload.get("sources", [payload]))
            sources: dict[str, dict[str, Any]] = {}
            for row in source_rows:
                for key in ("source_revision_id", "source_id"):
                    if row.get(key):
                        sources[str(row[key])] = row
            scopes = {str(row["scope_id"]): row for row in bundle.get("scopes", [])}
            layers[layer_id] = {
                "role": role,
                "assessments": assessments,
                "evidence": {
                    str(row["evidence_span_id"]): row
                    for row in evidence_rows
                    if row.get("evidence_span_id")
                },
                "sources": sources,
                "scopes": scopes,
            }
        return layers

    def _source_for_span(
        self, layer: dict[str, Any], span: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not span:
            return None
        for key in ("source_revision_id", "source_id", "source_record_id"):
            source_id = span.get(key)
            if source_id and str(source_id) in layer["sources"]:
                return dict(layer["sources"][str(source_id)])
        return None

    def _node_projection(self, node: dict[str, Any]) -> dict[str, Any]:
        status = str(node["status"])
        knowledge_status = (
            "candidate"
            if node["record_type"] == "AtomicClaimRevision"
            else "source_evidence" if status == "trusted_source_evidence" else status
        )
        return {
            "graph_node_id": node["graph_node_id"],
            "canonical_id": node["record_id"],
            "label": node["label"],
            "node_type": node["record_type"],
            "layer": node["layer_id"],
            "status": status,
            "knowledge_status": knowledge_status,
            "ecosystem": node.get("ecosystem"),
            "record": node["record"],
        }

    def _edge_projection(self, edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "graph_edge_id": edge["graph_edge_id"],
            "source": edge["source_graph_node_id"],
            "target": edge["target_graph_node_id"],
            "relation": edge["predicate"],
            "layer": edge["layer_id"],
            "status": edge["status"],
            "provenance": edge.get("provenance", {}),
        }

    def _knowledge_graph_view(self, payload: dict[str, Any]) -> KnowledgeGraphView:
        nodes = {
            row["graph_node_id"]: GraphNode(
                node_id=row["graph_node_id"],
                label=row["label"],
                kind=row["node_type"],
                metadata={
                    "canonical_id": row["canonical_id"],
                    "ontology_type": row["node_type"],
                    "layer": row["layer"],
                    "status": row["status"],
                    "knowledge_status": row["knowledge_status"],
                    "ecosystem": row["ecosystem"],
                },
            )
            for row in payload["nodes"]
        }
        edges = [
            GraphEdge(
                source=row["source"],
                target=row["target"],
                relation=row["relation"],
                metadata={
                    "edge_id": row.get("graph_edge_id"),
                    "layer": row["layer"],
                    "status": row["status"],
                    "provenance": row.get("provenance", {}),
                    "reason": "real frozen Scientific KG relation",
                },
            )
            for row in payload["edges"]
        ]
        ordered = list(nodes)
        return KnowledgeGraphView(
            nodes=nodes,
            edges=edges,
            visible_node_ids=ordered,
            visible_edges=edges,
            inventory=dict(Counter(node.kind for node in nodes.values())),
            truncated=bool(payload["truncated"]),
        )

    def _with_source_projections(
        self, graph: KnowledgeGraphView, *, max_nodes: int
    ) -> KnowledgeGraphView:
        """Add real manifest SourceRevisions as clearly marked display nodes."""

        nodes = dict(graph.nodes)
        edges = list(graph.edges)
        visible_ids = list(graph.visible_node_ids)
        visible_edges = list(graph.visible_edges)
        edge_keys = {(edge.source, edge.target, edge.relation) for edge in visible_edges}
        for claim_id in list(visible_ids):
            if nodes[claim_id].kind != "AtomicClaimRevision":
                continue
            chain = self.get_claim_evidence_chain(claim_id)
            layer_id = chain["claim"]["layer"]
            for row in chain["evidence"]:
                source = row["source_revision"]
                span_node_id = f"{layer_id}::{row['evidence_span_id']}"
                if not source or span_node_id not in nodes:
                    continue
                source_id = str(source.get("source_revision_id") or source.get("source_id"))
                projected_id = f"source-record::{layer_id}::{source_id}"
                if projected_id not in nodes:
                    if len(visible_ids) >= max(1, min(int(max_nodes), 100)):
                        continue
                    nodes[projected_id] = GraphNode(
                        node_id=projected_id,
                        label=source_id,
                        kind="SourceRevision",
                        metadata={
                            "canonical_id": source_id,
                            "layer": layer_id,
                            "status": "candidate_source_record",
                            "display_projection": "source manifest record; excluded from physical graph totals",
                            "authority": source.get("authority"),
                            "release": source.get("release") or source.get("version"),
                        },
                    )
                    visible_ids.append(projected_id)
                key = (span_node_id, projected_id, "RESOLVES_TO_SOURCE_REVISION")
                if key not in edge_keys:
                    edge = GraphEdge(
                        source=span_node_id,
                        target=projected_id,
                        relation="RESOLVES_TO_SOURCE_REVISION",
                        metadata={
                            "display_projection": "EvidenceSpan source_revision_id/source_id field"
                        },
                    )
                    edges.append(edge)
                    visible_edges.append(edge)
                    edge_keys.add(key)
        return KnowledgeGraphView(
            nodes=nodes,
            edges=edges,
            visible_node_ids=visible_ids,
            visible_edges=visible_edges,
            inventory=dict(Counter(node.kind for node in nodes.values())),
            truncated=graph.truncated,
        )
