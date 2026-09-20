"""Read-only adapter for the human-approved Scientific KG v2 snapshot."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from engine.knowledge_graph_view import GraphEdge, GraphNode, KnowledgeGraphView


EXPECTED_APPROVED_KG_SHA256 = (
    "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
)
SNAPSHOT_ID = "approved-scientific-kg-v2-01"

FOCUS_PRESETS = {
    "Scanpy HVG": (
        "operator-revision:python:scanpy:scanpy.pp.highly_variable_genes:1.11.2",
    ),
    "Scanpy PCA": ("operator-revision:python:scanpy:scanpy.pp.pca:1.11.2",),
    "Scrublet": (
        "operator-revision:python:scrublet:scrublet.Scrublet.scrub_doublets:0.2.3",
        "method:scrublet",
    ),
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _short(value: Any, limit: int = 46) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class ApprovedScientificKGV2Service:
    """Immutable repository-local projection of approved Scientific KG v2."""

    def __init__(self, repository_root: Path | None = None) -> None:
        self._root = Path(repository_root or Path(__file__).resolve().parents[1])
        self._snapshot = (
            self._root
            / "reconstruction"
            / "promotion_v2"
            / "snapshots"
            / "approved-v2-01"
        )
        self._graph_path = self._snapshot / "approved_kg.json"
        self._graph_bytes = self._graph_path.read_bytes()
        self._hash = hashlib.sha256(self._graph_bytes).hexdigest()
        self._manifest = _json(self._snapshot / "promotion_manifest.json")
        self._graph = json.loads(self._graph_bytes)
        self._held = _json(self._snapshot / "held_out_statements.json")
        self._cautions = _json(self._snapshot / "caution_context_index.json")

        self._entities = {row["id"]: row for row in self._graph["entities"]}
        self._statements = {
            row["statement_revision_id"]: row for row in self._graph["statements"]
        }
        self._governance = {row["record_id"]: row for row in self._graph["governance"]}
        self._assessments = {
            row["assessment_id"]: row for row in self._graph["evidence_assessments"]
        }
        self._spans = {
            row["evidence_span_id"]: row for row in self._graph["evidence_spans"]
        }
        self._caution_by_id = {row["caution_id"]: row for row in self._cautions}
        self._validate_snapshot()
        self._full_graph = self._build_graph()
        self._adjacency = self._build_adjacency(self._full_graph.edges)

    def _validate_snapshot(self) -> None:
        approved_ids = set(self._statements)
        manifest_ids = set(self._manifest["approved_statement_revision_ids"])
        held_ids = set(self._held["statement_revision_ids"])
        if self._hash != EXPECTED_APPROVED_KG_SHA256:
            raise ValueError(f"Approved Scientific KG v2 hash mismatch: {self._hash}")
        if self._manifest["approved_kg_sha256"] != self._hash:
            raise ValueError("promotion manifest does not match approved_kg.json")
        if self._manifest["snapshot_id"] != SNAPSHOT_ID:
            raise ValueError("unexpected Approved Scientific KG v2 snapshot id")
        if approved_ids != manifest_ids or len(approved_ids) != 121:
            raise ValueError("approved statement inventory does not match manifest")
        if approved_ids & held_ids or len(held_ids) != 1:
            raise ValueError("held statement leaked into approved statement inventory")
        if any(
            row.get("execution_authorized") is not False
            for row in self._governance.values()
        ):
            raise ValueError("approved knowledge must not authorize execution")

    def summary(self) -> dict[str, Any]:
        return {
            "snapshot_id": SNAPSHOT_ID,
            "approved_kg_sha256": self._hash,
            "hash_verified": True,
            "approved_statements": len(self._statements),
            "held_statements": len(self._held["statement_revision_ids"]),
            "held_statement_revision_ids": list(self._held["statement_revision_ids"]),
            "cautions": len(self._cautions),
            "execution_authorized": False,
            "ontology_version": self._graph["ontology_version"],
        }

    def semantic_inventory(self) -> list[dict[str, Any]]:
        counts = Counter(node.kind for node in self._full_graph.nodes.values())
        return [
            {"type": kind, "count": count}
            for kind, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    def relation_inventory(self) -> list[dict[str, Any]]:
        counts = Counter(edge.relation for edge in self._full_graph.edges)
        return [
            {"relation": relation, "count": count}
            for relation, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    def global_graph(self, *, max_nodes: int = 2000) -> KnowledgeGraphView:
        cap = max(1, min(int(max_nodes), 2000))
        ids = list(self._full_graph.visible_node_ids[:cap])
        return self._subgraph(ids, truncated=len(ids) < len(self._full_graph.nodes))

    def example_graph(self, name: str, *, max_nodes: int = 100) -> KnowledgeGraphView:
        return self.focus_graph(name, max_nodes=max_nodes)

    def focus_graph(self, name: str, *, max_nodes: int = 100) -> KnowledgeGraphView:
        if name not in FOCUS_PRESETS:
            raise KeyError(f"unknown Approved Scientific KG v2 focus view: {name}")
        seeds = set(FOCUS_PRESETS[name])
        selected = set(seeds)
        selected_statements: set[str] = set()

        for _ in range(2):
            frontier = set(selected)
            for statement_id, row in self._statements.items():
                if row["subject_id"] in frontier or row["object_id"] in frontier:
                    selected_statements.add(statement_id)
                    selected.update(
                        (
                            statement_id,
                            row["statement_id"],
                            row["subject_id"],
                            row["object_id"],
                        )
                    )

        for row in self._graph["links"]:
            if row["subject_id"] in selected or row["object_id"] in selected:
                selected.update((row["subject_id"], row["object_id"]))

        for assessment_id, row in self._assessments.items():
            if row["statement_revision_id"] not in selected_statements:
                continue
            selected.update((assessment_id, row["evidence_span_id"]))
            span = self._spans[row["evidence_span_id"]]
            selected.update((span["source_revision_id"], span["source_artifact_id"]))

        focus_subjects = selected & set(self._entities)
        for row in self._cautions:
            if not focus_subjects.intersection(row.get("subject_ids", [])):
                continue
            selected.add(row["caution_id"])
            for evidence in row.get("evidence", []):
                span_id = evidence["evidence_span_id"]
                selected.update(
                    (
                        span_id,
                        evidence["source_revision_id"],
                        evidence["source_artifact_id"],
                    )
                )

        priority = sorted(
            selected,
            key=lambda node_id: (
                0 if node_id in seeds else 1,
                0 if node_id in selected_statements else 1,
                (
                    0
                    if self._full_graph.nodes.get(node_id, GraphNode("", "", "")).kind
                    == "Requirement"
                    else 1
                ),
                node_id,
            ),
        )
        cap = max(25, min(int(max_nodes), 160))
        chosen = priority[:cap]
        return self._subgraph(chosen, truncated=len(chosen) < len(selected))

    def search_nodes(
        self,
        query: str,
        *,
        node_types: set[str] | None = None,
        allowed_statuses: set[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        terms = query.casefold().split()
        results = []
        for node_id in self._full_graph.visible_node_ids:
            node = self._full_graph.nodes[node_id]
            if node_types and node.kind not in node_types:
                continue
            metadata = dict(node.metadata)
            status = str(
                metadata.get("status") or metadata.get("knowledge_status") or ""
            )
            if allowed_statuses and status not in allowed_statuses:
                continue
            text = " ".join(
                (node.label, node.kind, json.dumps(metadata, default=str))
            ).casefold()
            if terms and not all(term in text for term in terms):
                continue
            results.append(self._detail(node_id))
        results.sort(key=lambda row: (row["label"].casefold(), row["graph_node_id"]))
        return results[: max(1, min(int(limit), 250))]

    def neighborhood_graph(
        self, graph_node_id: str, *, hops: int = 1, max_nodes: int = 100
    ) -> KnowledgeGraphView:
        if graph_node_id not in self._full_graph.nodes:
            raise KeyError(f"unknown Approved Scientific KG v2 node: {graph_node_id}")
        hop_cap = max(0, min(int(hops), 2))
        node_cap = max(1, min(int(max_nodes), 160))
        queue: deque[tuple[str, int]] = deque([(graph_node_id, 0)])
        seen = {graph_node_id}
        ordered: list[str] = []
        while queue and len(ordered) < node_cap:
            node_id, depth = queue.popleft()
            ordered.append(node_id)
            if depth >= hop_cap:
                continue
            for neighbor in self._adjacency.get(node_id, []):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return self._subgraph(
            ordered, truncated=bool(queue) or len(seen) > len(ordered)
        )

    def get_node(self, graph_node_id: str) -> dict[str, Any] | None:
        if graph_node_id not in self._full_graph.nodes:
            return None
        return self._detail(graph_node_id)

    def get_claim_evidence_chain(self, statement_revision_id: str) -> dict[str, Any]:
        if statement_revision_id not in self._statements:
            raise KeyError(
                f"not an approved StatementRevision: {statement_revision_id}"
            )
        assessments = [
            row
            for row in self._assessments.values()
            if row["statement_revision_id"] == statement_revision_id
        ]
        evidence = []
        incomplete: list[str] = []
        for assessment in assessments:
            span = self._spans.get(assessment["evidence_span_id"])
            source = self._entities.get(span["source_revision_id"]) if span else None
            if not span:
                incomplete.append(f"missing span {assessment['evidence_span_id']}")
            if span and not source:
                incomplete.append(
                    f"missing source revision {span['source_revision_id']}"
                )
            evidence.append(
                {
                    "evidence_span_id": assessment["evidence_span_id"],
                    "materialized": span is not None,
                    "source_revision": source,
                    "source_status": "resolved" if source else "MISSING",
                    "assessment": assessment,
                    "span": span,
                }
            )
        return {
            "claim": self._detail(statement_revision_id),
            "assessments": assessments,
            "evidence": evidence,
            "complete": bool(assessments) and not incomplete,
            "incomplete_reasons": incomplete
            or ([] if assessments else ["no evidence assessment"]),
        }

    def _build_graph(self) -> KnowledgeGraphView:
        nodes: dict[str, GraphNode] = {}
        for node_id, row in self._entities.items():
            caution = self._caution_by_id.get(node_id)
            metadata = dict(row)
            if caution:
                metadata.update(caution)
            metadata.update(
                self._display_metadata(row["record_type"], row, caution=caution)
            )
            nodes[node_id] = GraphNode(
                node_id=node_id,
                label=self._label(row),
                kind=row["record_type"],
                metadata=metadata,
            )

        for index, (statement_id, row) in enumerate(
            sorted(self._statements.items()), 1
        ):
            governance = dict(self._governance[statement_id])
            display = (
                f"S{index} · {_short(self._label_by_id(row['subject_id']), 16)} → "
                f"{_short(row['predicate'], 20)} → {_short(self._label_by_id(row['object_id']), 22)}"
            )
            metadata = {
                **row,
                **governance,
                "ontology_type": "StatementRevision",
                "viewer_group": "statement",
                "display_label": display,
                "full_label": (
                    f"{self._label_by_id(row['subject_id'])} → {row['predicate']} → "
                    f"{self._label_by_id(row['object_id'])}"
                ),
                "status": "APPROVED",
                "candidate_state": "APPROVED",
            }
            nodes[statement_id] = GraphNode(
                statement_id, metadata["full_label"], "StatementRevision", metadata
            )

        for assessment_id, row in self._assessments.items():
            metadata = {
                **row,
                "ontology_type": "EvidenceAssessment",
                "viewer_group": "evidence",
                "display_label": f"Assessment · {row['support_type']}",
                "full_label": row["rationale"],
                "status": row["status"],
                "execution_authorized": False,
            }
            nodes[assessment_id] = GraphNode(
                assessment_id, row["rationale"], "EvidenceAssessment", metadata
            )

        for index, (span_id, row) in enumerate(sorted(self._spans.items()), 1):
            metadata = {
                **row,
                "ontology_type": "EvidenceSpan",
                "viewer_group": "evidence",
                "display_label": f"E{index} · {_short(row['locator'].get('value'), 18)}",
                "full_label": row["exact_text"],
                "status": "EVIDENCE",
                "execution_authorized": False,
            }
            nodes[span_id] = GraphNode(
                span_id, row["exact_text"], "EvidenceSpan", metadata
            )

        edges: list[GraphEdge] = []
        for index, row in enumerate(self._graph["links"]):
            edges.append(
                GraphEdge(
                    row["subject_id"],
                    row["object_id"],
                    row["predicate"],
                    {
                        **row,
                        "edge_id": f"approved-link:{index}",
                        "status": "STRUCTURAL",
                    },
                )
            )
        for statement_id, row in self._statements.items():
            common = {
                "statement_revision_id": statement_id,
                "scope_status": row["scope_status"],
                "qualifiers": row["qualifiers"],
                "status": "APPROVED",
                "execution_authorized": False,
            }
            edges.extend(
                (
                    GraphEdge(
                        row["subject_id"], row["object_id"], row["predicate"], common
                    ),
                    GraphEdge(row["subject_id"], statement_id, "SUBJECT_REF", common),
                    GraphEdge(statement_id, row["object_id"], "OBJECT_REF", common),
                    GraphEdge(statement_id, row["statement_id"], "REVISION_OF", common),
                )
            )
        for assessment_id, row in self._assessments.items():
            common = {
                "assessment_id": assessment_id,
                "support_type": row["support_type"],
                "status": row["status"],
                "execution_authorized": False,
                "reason": row["rationale"],
            }
            edges.extend(
                (
                    GraphEdge(
                        row["statement_revision_id"],
                        assessment_id,
                        "EVIDENCE_ASSESSMENT",
                        common,
                    ),
                    GraphEdge(
                        assessment_id,
                        row["evidence_span_id"],
                        row["support_type"],
                        common,
                    ),
                )
            )
        for span_id, row in self._spans.items():
            common = {
                "evidence_span_id": span_id,
                "status": "EVIDENCE",
                "execution_authorized": False,
            }
            edges.extend(
                (
                    GraphEdge(
                        span_id,
                        row["source_revision_id"],
                        "SOURCE_REVISION_REF",
                        common,
                    ),
                    GraphEdge(
                        span_id,
                        row["source_artifact_id"],
                        "SOURCE_ARTIFACT_REF",
                        common,
                    ),
                )
            )
        for row in self._cautions:
            common = {
                "caution_id": row["caution_id"],
                "status": row["status"],
                "execution_authorized": False,
                "reason": row["routing_basis"],
                "semantic_boundary": "context routing only; not an ontology assertion",
            }
            for subject_id in row.get("subject_ids", []):
                edges.append(
                    GraphEdge(
                        row["caution_id"], subject_id, "CAUTION_SUBJECT_REF", common
                    )
                )
            for evidence in row.get("evidence", []):
                edges.append(
                    GraphEdge(
                        row["caution_id"],
                        evidence["evidence_span_id"],
                        "CAUTION_EVIDENCE",
                        common,
                    )
                )

        ordered = sorted(nodes, key=lambda node_id: (nodes[node_id].kind, node_id))
        return KnowledgeGraphView(
            nodes=nodes,
            edges=edges,
            visible_node_ids=ordered,
            visible_edges=edges,
            inventory=dict(Counter(node.kind for node in nodes.values())),
            truncated=False,
        )

    def _display_metadata(
        self, record_type: str, row: dict[str, Any], *, caution: dict[str, Any] | None
    ) -> dict[str, Any]:
        if caution or record_type == "EvidenceGap":
            return {
                "ontology_type": "EvidenceGap",
                "viewer_group": "caution",
                "display_label": f"Caution · {_short((caution or row).get('description'), 34)}",
                "full_label": (caution or row).get("description") or self._label(row),
                "status": (caution or row).get("status", "UNASSERTED_CAUTION"),
                "candidate_state": "CAUTION",
                "execution_authorized": False,
            }
        group = (
            "source"
            if record_type in {"SourceWork", "SourceRevision", "SourceArtifact"}
            else (
                "constraint"
                if record_type
                in {
                    "Requirement",
                    "ParameterDefinition",
                    "OutputPort",
                    "RepresentationConstraint",
                }
                else (
                    "statement_identity"
                    if record_type == "ScientificStatement"
                    else "entity"
                )
            )
        )
        return {
            "ontology_type": record_type,
            "viewer_group": group,
            "display_label": _short(self._label(row), 40),
            "full_label": self._label(row),
            "status": "SNAPSHOT_ENTITY",
            "execution_authorized": False,
        }

    def _label(self, row: dict[str, Any]) -> str:
        for field in (
            "label",
            "qualified_name",
            "api_path",
            "role",
            "work_identifier",
            "description",
        ):
            if row.get(field):
                return str(row[field])
        return str(row.get("id") or row.get("record_type") or "Scientific KG node")

    def _label_by_id(self, node_id: str) -> str:
        row = self._entities.get(node_id)
        return self._label(row) if row else node_id

    def _detail(self, node_id: str) -> dict[str, Any]:
        node = self._full_graph.nodes[node_id]
        metadata = dict(node.metadata)
        return {
            "graph_node_id": node_id,
            "canonical_id": node_id,
            "label": str(metadata.get("display_label") or node.label),
            "node_type": node.kind,
            "layer": SNAPSHOT_ID,
            "status": str(metadata.get("status") or "SNAPSHOT_ENTITY"),
            "knowledge_status": str(metadata.get("knowledge_status") or "context_only"),
            "ecosystem": metadata.get("ecosystem"),
            "record": metadata,
        }

    def _subgraph(self, node_ids: list[str], *, truncated: bool) -> KnowledgeGraphView:
        ids = [node_id for node_id in node_ids if node_id in self._full_graph.nodes]
        selected = set(ids)
        edges = [
            edge
            for edge in self._full_graph.edges
            if edge.source in selected and edge.target in selected
        ]
        nodes = {node_id: self._full_graph.nodes[node_id] for node_id in ids}
        return KnowledgeGraphView(
            nodes=nodes,
            edges=edges,
            visible_node_ids=ids,
            visible_edges=edges,
            inventory=dict(Counter(node.kind for node in nodes.values())),
            truncated=truncated,
        )

    @staticmethod
    def _build_adjacency(edges: list[GraphEdge]) -> dict[str, list[str]]:
        adjacency: defaultdict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)
        return {node_id: sorted(neighbors) for node_id, neighbors in adjacency.items()}
