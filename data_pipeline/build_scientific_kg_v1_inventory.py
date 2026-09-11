from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "data" / "evidence_candidates"
OUTPUT_ROOT = EVIDENCE_ROOT / "scientific_kg_v1_inventory"
GRAPH_PATH = OUTPUT_ROOT / "scientific_kg_v1_consolidated_graph.json"
REPORT_PATH = REPOSITORY_ROOT / "docs" / "SCIENTIFIC_KG_V1_INVENTORY.md"


@dataclass(frozen=True)
class Layer:
    layer_id: str
    directory: str
    role: str
    record_status: str
    evidence_file: str
    gap_file: str | None = None


LAYERS = (
    Layer(
        "uat_decision_rule_correction",
        "scientific_kg_v1_uat_decision_rules",
        "corrected_candidate_overlay",
        "candidate_not_promoted",
        "authoritative_evidence_spans.jsonl",
    ),
    Layer(
        "scientific_kg_v1_core",
        "scientific_kg_v1_core",
        "v1_core_candidate",
        "candidate_not_promoted",
        "evidence_spans.jsonl",
        "evidence_gaps.json",
    ),
    Layer(
        "content_expansion_v1",
        "scientific_kg_content_expansion_v1",
        "broad_coverage_reference",
        "deferred_candidate",
        "evidence_span_references.jsonl",
        "evidence_gaps.json",
    ),
    Layer(
        "scanpy_core_reference_slice",
        "scientific_knowledge_scanpy_core_v1_1",
        "reference_implementation_superseded_by_corrected_slice",
        "deferred_reference_candidate",
        "authoritative_evidence_spans.jsonl",
    ),
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_id(record: dict[str, Any]) -> str:
    for key in (
        "entity_id",
        "claim_revision_id",
        "relation_id",
        "evidence_span_id",
        "gap_id",
        "input_port_id",
        "output_port_id",
        "requirement_id",
        "constraint_id",
        "representation_type_id",
        "scope_id",
    ):
        value = record.get(key)
        if value:
            return str(value)
    raise ValueError(f"record has no stable identifier: {sorted(record)}")


def _graph_id(layer_id: str, record_id: str) -> str:
    return f"{layer_id}::{record_id}"


def _label(record: dict[str, Any], record_id: str) -> str:
    return str(
        record.get("label")
        or record.get("claim_text")
        or record.get("role")
        or record.get("missing_knowledge")
        or record_id
    )


def _ecosystem_slug(record_id: str) -> str | None:
    lowered = record_id.lower()
    aliases = (
        ("scanpy", ("scanpy",)),
        ("seurat", ("seurat",)),
        ("harmony", ("harmony",)),
        ("scvi-tools", ("scvi_tools", "scvi-tools", "scvi:")),
        ("scrublet", ("scrublet",)),
        ("soupx", ("soupx",)),
        ("celltypist", ("celltypist",)),
        ("singler", ("singler", "singler::")),
        ("edger", ("edger",)),
        ("slingshot", ("slingshot",)),
        ("scvelo", ("scvelo",)),
        ("cellrank", ("cellrank",)),
        ("mofa2", ("mofa2", "mofapy2")),
        ("pyscenic", ("pyscenic",)),
        ("scanorama", ("scanorama",)),
        ("doubletfinder", ("doubletfinder",)),
        ("scdblfinder", ("scdblfinder",)),
        ("tradeseq", ("tradeseq",)),
        ("moscot", ("moscot",)),
        ("wot", ("waddington", "wot")),
        ("cell2location", ("cell2location",)),
        ("mimosca", ("mimosca",)),
    )
    for ecosystem, needles in aliases:
        if any(needle in lowered for needle in needles):
            return ecosystem
    return None


def _load_layer(layer: Layer) -> dict[str, Any]:
    root = EVIDENCE_ROOT / layer.directory
    manifest = _read_json(root / "manifest.json")
    for name, expected in manifest.get("artifacts", {}).items():
        path = root / name
        if path.exists() and _sha256(path) != expected:
            raise ValueError(f"frozen artifact digest mismatch:{layer.directory}/{name}")
    bundle = _read_json(root / "conformance_bundle.json")
    evidence = _read_jsonl(root / layer.evidence_file)
    gaps = []
    if layer.gap_file and (root / layer.gap_file).exists():
        gap_payload = _read_json(root / layer.gap_file)
        gaps = gap_payload.get("gaps", gap_payload if isinstance(gap_payload, list) else [])
    return {
        "config": layer,
        "root": root,
        "manifest": manifest,
        "bundle": bundle,
        "evidence": evidence,
        "gaps": gaps,
    }


def _add_node(
    nodes: list[dict[str, Any]],
    node_index: set[str],
    *,
    layer: Layer,
    record_type: str,
    record: dict[str, Any],
    status: str | None = None,
) -> str:
    record_id = _record_id(record)
    graph_id = _graph_id(layer.layer_id, record_id)
    if graph_id in node_index:
        return graph_id
    node_index.add(graph_id)
    nodes.append(
        {
            "graph_node_id": graph_id,
            "record_id": record_id,
            "record_type": record_type,
            "label": _label(record, record_id),
            "ecosystem": _ecosystem_slug(record_id),
            "layer_id": layer.layer_id,
            "status": status or layer.record_status,
            "record": record,
        }
    )
    return graph_id


def _add_edge(
    edges: list[dict[str, Any]],
    *,
    layer: Layer,
    predicate: str,
    source_id: str,
    target_id: str,
    edge_id: str,
    status: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> None:
    edges.append(
        {
            "graph_edge_id": _graph_id(layer.layer_id, edge_id),
            "predicate": predicate,
            "source_record_id": source_id,
            "target_record_id": target_id,
            "source_graph_node_id": _graph_id(layer.layer_id, source_id),
            "target_graph_node_id": _graph_id(layer.layer_id, target_id),
            "layer_id": layer.layer_id,
            "status": status or layer.record_status,
            "provenance": provenance or {},
        }
    )


def _structural_graph(
    loaded_layers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    chains: list[dict[str, Any]] = []
    node_index: set[str] = set()

    for loaded in loaded_layers:
        layer: Layer = loaded["config"]
        bundle = loaded["bundle"]
        entities = bundle.get("entities", [])
        by_id = {_record_id(item): item for item in entities}
        for entity in entities:
            _add_node(
                nodes,
                node_index,
                layer=layer,
                record_type=entity["record_type"],
                record=entity,
            )
        for scope in bundle.get("scopes", []):
            _add_node(nodes, node_index, layer=layer, record_type="ApplicabilityScope", record=scope)
        for representation in bundle.get("representation_types", []):
            _add_node(nodes, node_index, layer=layer, record_type="RepresentationType", record=representation)
        for constraint in bundle.get("representation_constraints", []):
            constraint_id = _add_node(
                nodes,
                node_index,
                layer=layer,
                record_type="RepresentationConstraint",
                record=constraint,
            )
            del constraint_id
            _add_edge(
                edges,
                layer=layer,
                predicate="CONSTRAINS_TYPE",
                source_id=constraint["constraint_id"],
                target_id=constraint["representation_type_id"],
                edge_id=f"structural:constraint-type:{constraint['constraint_id']}",
            )
        for claim in bundle.get("atomic_claims", []):
            _add_node(nodes, node_index, layer=layer, record_type="AtomicClaimRevision", record=claim)
            _add_edge(
                edges,
                layer=layer,
                predicate="SUBJECT_OF_CLAIM",
                source_id=claim["subject_id"],
                target_id=claim["claim_revision_id"],
                edge_id=f"structural:claim-subject:{claim['claim_revision_id']}",
            )
            if claim.get("object_id"):
                if _graph_id(layer.layer_id, claim["object_id"]) not in node_index:
                    _add_node(
                        nodes,
                        node_index,
                        layer=layer,
                        record_type="ReferencedObject",
                        record={"entity_id": claim["object_id"], "label": claim["object_id"]},
                    )
                _add_edge(
                    edges,
                    layer=layer,
                    predicate=claim["predicate"],
                    source_id=claim["claim_revision_id"],
                    target_id=claim["object_id"],
                    edge_id=f"claim:{claim['claim_revision_id']}:{claim['predicate']}",
                    provenance={"claim_revision_id": claim["claim_revision_id"]},
                )
        for relation in bundle.get("derived_relations", []):
            for endpoint in (relation["source_id"], relation["target_id"]):
                if _graph_id(layer.layer_id, endpoint) not in node_index:
                    _add_node(
                        nodes,
                        node_index,
                        layer=layer,
                        record_type="ReferencedObject",
                        record={"entity_id": endpoint, "label": endpoint},
                    )
            _add_edge(
                edges,
                layer=layer,
                predicate=relation["relation"],
                source_id=relation["source_id"],
                target_id=relation["target_id"],
                edge_id=relation["relation_id"],
                provenance={
                    "relation_id": relation["relation_id"],
                    "derivation_type": relation["derivation_type"],
                    "derived_from_claim_revision_ids": relation.get(
                        "derived_from_claim_revision_ids", []
                    ),
                    "review_status": relation["review_status"],
                },
            )
        for evidence in loaded["evidence"]:
            evidence_status = (
                "trusted_source_evidence"
                if evidence.get("source_bound") is True
                and evidence.get("review_status") == "candidate_source_verified"
                else "source_bound_evidence_candidate"
                if evidence.get("source_bound") is True
                else "evidence_reference_candidate"
            )
            _add_node(
                nodes,
                node_index,
                layer=layer,
                record_type="EvidenceSpan",
                record=evidence,
                status=evidence_status,
            )
        for assessment in bundle.get("evidence_assessments", []):
            for evidence_id in assessment.get("evidence_span_ids", []):
                if _graph_id(layer.layer_id, evidence_id) not in node_index:
                    _add_node(
                        nodes,
                        node_index,
                        layer=layer,
                        record_type="EvidenceReference",
                        record={"evidence_span_id": evidence_id, "label": evidence_id},
                        status="evidence_reference_candidate",
                    )
                _add_edge(
                    edges,
                    layer=layer,
                    predicate="SUPPORTS",
                    source_id=evidence_id,
                    target_id=assessment["claim_revision_id"],
                    edge_id=f"evidence:{evidence_id}:supports:{assessment['claim_revision_id']}",
                    status=(
                        "candidate_support"
                        if assessment.get("stance") == "supports"
                        else "candidate_evidence_assessment"
                    ),
                    provenance={"evidence_assessment": assessment},
                )
        for gap in loaded["gaps"]:
            _add_node(
                nodes,
                node_index,
                layer=layer,
                record_type="EvidenceGap",
                record=gap,
                status="evidence_gap",
            )
        for entity in entities:
            record_type = entity["record_type"]
            entity_id = entity["entity_id"]
            links: list[tuple[str, str]] = []
            if record_type == "Package":
                links.append(("BELONGS_TO_PROJECT", entity["project_id"]))
            elif record_type == "PackageRelease":
                links.append(("REVISION_OF_PACKAGE", entity["package_id"]))
            elif record_type == "Operator":
                links.append(("BELONGS_TO_PACKAGE", entity["package_id"]))
            elif record_type == "OperatorRevision":
                links.extend(
                    [
                        ("REVISION_OF_OPERATOR", entity["operator_id"]),
                        ("BOUND_TO_PACKAGE_RELEASE", entity["package_release_id"]),
                    ]
                )
                links.extend(("IMPLEMENTS_METHOD", item) for item in entity.get("implements_method_ids", []))
                links.extend(("IMPLEMENTS_METHOD_VARIANT", item) for item in entity.get("implements_method_variant_ids", []))
            elif record_type == "MethodVariant":
                links.append(("VARIANT_OF_METHOD", entity["method_id"]))
            for predicate, target in links:
                _add_edge(
                    edges,
                    layer=layer,
                    predicate=predicate,
                    source_id=entity_id,
                    target_id=target,
                    edge_id=f"structural:{predicate.lower()}:{entity_id}:{target}",
                )
            if record_type != "OperatorRevision":
                continue
            input_ports = []
            for port in entity.get("input_ports", []):
                _add_node(nodes, node_index, layer=layer, record_type="InputPort", record=port)
                _add_edge(
                    edges,
                    layer=layer,
                    predicate="HAS_INPUT_PORT",
                    source_id=entity_id,
                    target_id=port["input_port_id"],
                    edge_id=f"structural:input-port:{entity_id}:{port['input_port_id']}",
                )
                port_constraints = []
                for requirement in port.get("requirements", []):
                    _add_node(nodes, node_index, layer=layer, record_type="Requirement", record=requirement)
                    _add_edge(
                        edges,
                        layer=layer,
                        predicate="HAS_REQUIREMENT",
                        source_id=port["input_port_id"],
                        target_id=requirement["requirement_id"],
                        edge_id=f"structural:requirement:{port['input_port_id']}:{requirement['requirement_id']}",
                    )
                    for constraint_id in requirement.get("representation_constraint_ids", []):
                        _add_edge(
                            edges,
                            layer=layer,
                            predicate="REQUIRES_CONSTRAINT",
                            source_id=requirement["requirement_id"],
                            target_id=constraint_id,
                            edge_id=f"structural:requirement-constraint:{requirement['requirement_id']}:{constraint_id}",
                        )
                        port_constraints.append(constraint_id)
                input_ports.append(
                    {
                        "input_port_id": port["input_port_id"],
                        "role": port["role"],
                        "constraint_ids": sorted(set(port_constraints)),
                    }
                )
            output_ports = []
            for port in entity.get("output_ports", []):
                _add_node(nodes, node_index, layer=layer, record_type="OutputPort", record=port)
                _add_edge(
                    edges,
                    layer=layer,
                    predicate="HAS_OUTPUT_PORT",
                    source_id=entity_id,
                    target_id=port["output_port_id"],
                    edge_id=f"structural:output-port:{entity_id}:{port['output_port_id']}",
                )
                _add_edge(
                    edges,
                    layer=layer,
                    predicate="OUTPUT_REPRESENTATION_TYPE",
                    source_id=port["output_port_id"],
                    target_id=port["representation_type_id"],
                    edge_id=f"structural:output-type:{port['output_port_id']}:{port['representation_type_id']}",
                )
                output_ports.append(
                    {
                        "output_port_id": port["output_port_id"],
                        "role": port["role"],
                        "representation_type_id": port["representation_type_id"],
                    }
                )
            operator = by_id.get(entity["operator_id"], {})
            package = by_id.get(operator.get("package_id", ""), {})
            project = by_id.get(package.get("project_id", ""), {})
            chains.append(
                {
                    "layer_id": layer.layer_id,
                    "status": layer.record_status,
                    "ecosystem": project.get("label") or _ecosystem_slug(entity_id),
                    "method_ids": entity.get("implements_method_ids", []),
                    "method_variant_ids": entity.get("implements_method_variant_ids", []),
                    "operator_id": entity["operator_id"],
                    "operator_revision_id": entity_id,
                    "package_id": operator.get("package_id"),
                    "package_release_id": entity["package_release_id"],
                    "input_ports": input_ports,
                    "output_ports": output_ports,
                }
            )
    return nodes, edges, chains


def _representative_subgraphs(chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specifications = (
        ("preprocessing", "uat_decision_rule_correction", ("highly_variable_genes", "pca", "neighbors")),
        ("integration", "uat_decision_rule_correction", ("harmony", "neighbors")),
        ("annotation", "uat_decision_rule_correction", ("singler",)),
        ("trajectory", "scientific_kg_v1_core", ("slingshot", "scvelo", "cellrank")),
        ("multi_omics", "scientific_kg_v1_core", ("mofa2", "totalvi", "multivi")),
        ("regulatory", "scientific_kg_v1_core", ("pyscenic",)),
    )
    subgraphs = []
    for domain, layer_id, needles in specifications:
        selected = [
            chain
            for chain in chains
            if chain["layer_id"] == layer_id
            and any(needle in chain["operator_revision_id"].lower() for needle in needles)
        ]
        subgraphs.append(
            {
                "domain": domain,
                "layer_id": layer_id,
                "operator_chains": selected,
            }
        )
    return subgraphs


def build_inventory() -> dict[str, Any]:
    loaded_layers = [_load_layer(layer) for layer in LAYERS]
    nodes, edges, chains = _structural_graph(loaded_layers)
    layer_summaries = []
    entity_totals: Counter[str] = Counter()
    claim_predicates: Counter[str] = Counter()
    derived_predicates: Counter[str] = Counter()
    task_labels: set[str] = set()
    ecosystems: set[str] = set()
    evidence_gap_count = 0

    for loaded in loaded_layers:
        layer: Layer = loaded["config"]
        bundle = loaded["bundle"]
        entity_counts = Counter(item["record_type"] for item in bundle.get("entities", []))
        entity_totals.update(entity_counts)
        claim_counts = Counter(item["predicate"] for item in bundle.get("atomic_claims", []))
        claim_predicates.update(claim_counts)
        relation_counts = Counter(item["relation"] for item in bundle.get("derived_relations", []))
        derived_predicates.update(relation_counts)
        task_labels.update(
            item["label"]
            for item in bundle.get("entities", [])
            if item.get("record_type") == "ScientificTask"
        )
        ecosystems.update(
            item["label"]
            for item in bundle.get("entities", [])
            if item.get("record_type") == "SoftwareProject"
        )
        evidence_gap_count += len(loaded["gaps"])
        layer_summaries.append(
            {
                "layer_id": layer.layer_id,
                "artifact_directory": f"data/evidence_candidates/{layer.directory}",
                "role": layer.role,
                "status": loaded["manifest"].get("status", layer.record_status),
                "record_status": layer.record_status,
                "manifest_schema_version": loaded["manifest"].get("schema_version"),
                "counts": {
                    "entities": len(bundle.get("entities", [])),
                    "representation_types": len(bundle.get("representation_types", [])),
                    "representation_constraints": len(bundle.get("representation_constraints", [])),
                    "scopes": len(bundle.get("scopes", [])),
                    "atomic_claims": len(bundle.get("atomic_claims", [])),
                    "derived_relations": len(bundle.get("derived_relations", [])),
                    "evidence_assessments": len(bundle.get("evidence_assessments", [])),
                    "evidence_spans": len(loaded["evidence"]),
                    "evidence_gaps": len(loaded["gaps"]),
                },
                "entity_counts": dict(sorted(entity_counts.items())),
                "claim_predicates": dict(sorted(claim_counts.items())),
                "derived_relation_predicates": dict(sorted(relation_counts.items())),
            }
        )

    status_counts = Counter(node["status"] for node in nodes)
    graph_node_counts = Counter(node["record_type"] for node in nodes)
    graph_edge_counts = Counter(edge["predicate"] for edge in edges)
    cross_tool_can_feed = [
        edge
        for edge in edges
        if edge["predicate"] == "CAN_FEED"
        and _ecosystem_slug(edge["source_record_id"])
        and _ecosystem_slug(edge["target_record_id"])
        and _ecosystem_slug(edge["source_record_id"])
        != _ecosystem_slug(edge["target_record_id"])
    ]
    inventory = {
        "physical_record_count_note": (
            "Counts preserve every frozen layer; overlapping identities are not merged "
            "without adjudicated cross-layer identity mappings."
        ),
        "graph_node_counts_by_type": dict(sorted(graph_node_counts.items())),
        "graph_edge_counts_by_predicate": dict(sorted(graph_edge_counts.items())),
        "entity_counts_by_type": dict(sorted(entity_totals.items())),
        "claim_counts_by_predicate": dict(sorted(claim_predicates.items())),
        "derived_relation_counts_by_predicate": dict(sorted(derived_predicates.items())),
        "ecosystems": sorted(ecosystems),
        "ecosystem_count": len(ecosystems),
        "tasks": sorted(task_labels),
        "task_count": len(task_labels),
        "method_operator_port_chain_count": len(chains),
        "evidence": {
            "span_or_reference_nodes": sum(
                1 for node in nodes if node["record_type"] in {"EvidenceSpan", "EvidenceReference"}
            ),
            "trusted_source_evidence_nodes": status_counts["trusted_source_evidence"],
            "source_bound_evidence_candidate_nodes": status_counts[
                "source_bound_evidence_candidate"
            ],
            "support_edges": sum(1 for edge in edges if edge["predicate"] == "SUPPORTS"),
        },
        "status": {
            "promoted_or_trusted_scientific_claims": 0,
            "candidate_claims": sum(claim_predicates.values()),
            "candidate_derived_relations": sum(derived_predicates.values()),
            "evidence_gaps": evidence_gap_count,
            "deferred_layer_nodes": sum(
                count
                for status, count in status_counts.items()
                if status.startswith("deferred")
            ),
            "node_counts_by_status": dict(sorted(status_counts.items())),
        },
    }
    return {
        "schema_version": "sckg-scientific-kg-v1-consolidated-inventory-graph-v1",
        "baseline_commit": "25d0cff7e13a537d9e051e2976a87b4fcf6419c6",
        "purpose": "inventory_view_only_no_promotion_no_scientific_content_change",
        "layer_policy": {
            "identity_merge_performed": False,
            "scientific_claim_rewrite_performed": False,
            "canonical_kg_modified": False,
            "retrieval_or_runtime_modified": False,
            "interpretation": (
                "UAT is a corrected candidate overlay; Core is the target v1 candidate; "
                "content expansion and the earlier Scanpy slice remain deferred/reference layers."
            ),
        },
        "layers": layer_summaries,
        "inventory": inventory,
        "method_operator_representation_chains": chains,
        "important_cross_tool_can_feed": cross_tool_can_feed,
        "representative_subgraphs": _representative_subgraphs(chains),
        "nodes": nodes,
        "edges": edges,
    }


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def render_report(graph: dict[str, Any]) -> str:
    inventory = graph["inventory"]
    lines = [
        "# Scientific KG v1 — Consolidated Inventory",
        "",
        f"Frozen baseline: `{graph['baseline_commit']}`.",
        "",
        "This is an inventory view, not a canonical promotion. All scientific claims and "
        "relations remain in their original frozen candidate layers. Trusted status applies "
        "only to source-verified evidence spans; promoted scientific claims remain **0**.",
        "",
        "## 1. Frozen layers",
        "",
        _table(
            ["Layer", "Role", "Entities", "Claims", "Relations", "Evidence", "Gaps"],
            [
                [
                    layer["layer_id"],
                    layer["role"],
                    layer["counts"]["entities"],
                    layer["counts"]["atomic_claims"],
                    layer["counts"]["derived_relations"],
                    layer["counts"]["evidence_spans"],
                    layer["counts"]["evidence_gaps"],
                ]
                for layer in graph["layers"]
            ],
        ),
        "",
        "> Physical totals retain overlapping records across layers. No unreviewed identity "
        "deduplication or semantic merge was performed.",
        "",
        "## 2. Entity inventory",
        "",
        "### All consolidated graph node types",
        "",
        _table(
            ["Node type", "Physical records"],
            [[key, value] for key, value in inventory["graph_node_counts_by_type"].items()],
        ),
        "",
        "### Domain entity records",
        "",
        _table(
            ["Entity type", "Physical records"],
            [[key, value] for key, value in inventory["entity_counts_by_type"].items()],
        ),
        "",
        f"Representation types: **{sum(layer['counts']['representation_types'] for layer in graph['layers'])}**; "
        f"constraints: **{sum(layer['counts']['representation_constraints'] for layer in graph['layers'])}**; "
        f"Method→OperatorRevision→Port chains: **{inventory['method_operator_port_chain_count']}**.",
        "",
        "## 3. Relation inventory",
        "",
        "### All consolidated graph edge predicates",
        "",
        _table(
            ["Predicate", "Physical edges"],
            [[key, value] for key, value in inventory["graph_edge_counts_by_predicate"].items()],
        ),
        "",
        "### Derived graph relations",
        "",
        _table(
            ["Predicate", "Physical records"],
            [[key, value] for key, value in inventory["derived_relation_counts_by_predicate"].items()],
        ),
        "",
        "### Atomic claim predicates",
        "",
        _table(
            ["Predicate", "Claims"],
            [[key, value] for key, value in inventory["claim_counts_by_predicate"].items()],
        ),
        "",
        "## 4. Ecosystem and task coverage",
        "",
        f"Ecosystems represented ({inventory['ecosystem_count']}): "
        + ", ".join(inventory["ecosystems"])
        + ".",
        "",
        f"Scientific tasks represented ({inventory['task_count']}): "
        + ", ".join(inventory["tasks"])
        + ".",
        "",
        "The v1 Core target is the 14-ecosystem `scientific_kg_v1_core` layer. "
        "The broader 19-ecosystem expansion remains a deferred coverage reference, while "
        "the UAT slice carries corrected candidate semantics for Scanpy, Harmony, Scrublet and SingleR.",
        "",
        "## 5. Method → Operator → representations",
        "",
    ]
    for layer_id in ("uat_decision_rule_correction", "scientific_kg_v1_core"):
        lines.extend([f"### {layer_id}", ""])
        selected = [
            chain
            for chain in graph["method_operator_representation_chains"]
            if chain["layer_id"] == layer_id
        ]
        lines.append(
            _table(
                ["Ecosystem", "Method", "Operator revision", "Inputs", "Outputs"],
                [
                    [
                        chain["ecosystem"],
                        ", ".join(chain["method_ids"] + chain["method_variant_ids"]),
                        chain["operator_revision_id"],
                        "; ".join(
                            f"{port['role']} → {', '.join(port['constraint_ids'])}"
                            for port in chain["input_ports"]
                        ),
                        "; ".join(
                            f"{port['role']} → {port['representation_type_id']}"
                            for port in chain["output_ports"]
                        ),
                    ]
                    for chain in selected
                ],
            )
        )
        lines.append("")
    cross_tool = graph["important_cross_tool_can_feed"]
    lines.extend(
        [
            "## 6. Cross-tool compatibility",
            "",
            (
                _table(
                    ["Layer", "Source", "Relation", "Target", "Claim provenance"],
                    [
                        [
                            edge["layer_id"],
                            edge["source_record_id"],
                            edge["predicate"],
                            edge["target_record_id"],
                            ", ".join(
                                edge["provenance"].get("derived_from_claim_revision_ids", [])
                            ),
                        ]
                        for edge in cross_tool
                    ],
                )
                if cross_tool
                else "No cross-ecosystem `CAN_FEED` relation is explicitly represented; "
                "existing compatibility is intra-ecosystem or candidate-local."
            ),
            "",
            "## 7. Evidence and status",
            "",
            _table(
                ["Status", "Count"],
                [
                    ["Promoted/trusted scientific claims", inventory["status"]["promoted_or_trusted_scientific_claims"]],
                    ["Candidate claims", inventory["status"]["candidate_claims"]],
                    ["Candidate derived relations", inventory["status"]["candidate_derived_relations"]],
                    ["Trusted source-evidence spans", inventory["evidence"]["trusted_source_evidence_nodes"]],
                    ["Other source-bound evidence candidates", inventory["evidence"]["source_bound_evidence_candidate_nodes"]],
                    ["Evidence SUPPORTS edges", inventory["evidence"]["support_edges"]],
                    ["Explicit EvidenceGaps", inventory["status"]["evidence_gaps"]],
                    ["Deferred/reference-layer nodes", inventory["status"]["deferred_layer_nodes"]],
                ],
            ),
            "",
            "## 8. Representative subgraphs",
            "",
        ]
    )
    for subgraph in graph["representative_subgraphs"]:
        lines.extend(
            [
                f"### {subgraph['domain']}",
                "",
                _table(
                    ["Ecosystem", "Method", "Operator", "Input ports", "Output representations"],
                    [
                        [
                            chain["ecosystem"],
                            ", ".join(chain["method_ids"] + chain["method_variant_ids"]),
                            chain["operator_revision_id"],
                            ", ".join(port["role"] for port in chain["input_ports"]),
                            ", ".join(
                                port["representation_type_id"] for port in chain["output_ports"]
                            ),
                        ]
                        for chain in subgraph["operator_chains"]
                    ],
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Machine-readable graph",
            "",
            "`data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json`",
            "",
            "The graph includes all frozen layer records, structural identity/port edges, AtomicClaim "
            "links, derived relations, evidence SUPPORTS links, EvidenceGaps and representative subgraph views.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    graph = build_inventory()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    GRAPH_PATH.write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(render_report(graph), encoding="utf-8")


if __name__ == "__main__":
    main()
