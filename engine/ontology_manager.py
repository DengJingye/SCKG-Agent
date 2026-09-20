from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


class OntologyIntegrityError(RuntimeError):
    """Raised when the frozen ontology cannot be proven safe to display."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_set(values: Iterable[str] | None) -> set[str]:
    return {str(value) for value in (values or ())}


class OntologyManagerReadOnlyService:
    """Verified, read-only projection of the frozen Ontology v2 Core design.

    Construction fails closed when an artifact is missing, its manifest hash is
    wrong, or a registry is structurally inconsistent. Public methods only
    return detached display projections; this class has no mutation surface.
    """

    REQUIRED_ARTIFACTS = {
        "competency_question_coverage.json",
        "deferred_registry.json",
        "evidence_model.json",
        "extension_registry.json",
        "link_type_registry.json",
        "object_type_registry.json",
        "ontology_v2_core_human_review.csv",
        "property_registry.json",
        "qualifier_registry.json",
        "scope_policy.json",
        "statement_model.json",
        "v1_v2_mapping_draft.json",
    }

    def __init__(self, repository_root: Path | None = None) -> None:
        self._root = Path(repository_root or Path(__file__).resolve().parents[1])
        self._ontology_dir = (
            self._root / "data" / "ontology" / "scientific_decision_ontology_v2_core"
        )
        self._manifest = self._load_manifest()
        self._verified_hashes = self._verify_manifest_artifacts()
        self._objects_registry = self._load_json("object_type_registry.json")
        self._links_registry = self._load_json("link_type_registry.json")
        self._properties_registry = self._load_json("property_registry.json")
        self._qualifiers_registry = self._load_json("qualifier_registry.json")
        self._extensions_registry = self._load_json("extension_registry.json")
        self._deferred_registry = self._load_json("deferred_registry.json")
        self._cq_registry = self._load_json("competency_question_coverage.json")
        self._mapping_registry = self._load_json("v1_v2_mapping_draft.json")
        self._validate_registries()
        self._objects = self._build_object_rows()
        self._links = self._build_link_rows()

    def _load_manifest(self) -> dict[str, Any]:
        path = self._ontology_dir / "manifest.json"
        if not path.is_file():
            raise OntologyIntegrityError("missing frozen ontology manifest.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OntologyIntegrityError("invalid frozen ontology manifest.json") from exc
        if not isinstance(value, dict):
            raise OntologyIntegrityError("invalid frozen ontology manifest structure")
        return value

    def _verify_manifest_artifacts(self) -> dict[str, str]:
        artifacts = self._manifest.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != self.REQUIRED_ARTIFACTS:
            raise OntologyIntegrityError("frozen ontology manifest artifact set mismatch")
        verified: dict[str, str] = {}
        for name in sorted(self.REQUIRED_ARTIFACTS):
            if Path(name).name != name:
                raise OntologyIntegrityError(f"unsafe frozen artifact path: {name}")
            path = self._ontology_dir / name
            if not path.is_file():
                raise OntologyIntegrityError(f"missing frozen ontology artifact: {name}")
            expected = artifacts.get(name)
            actual = _sha256(path)
            if not isinstance(expected, str) or actual != expected:
                raise OntologyIntegrityError(f"frozen ontology hash mismatch: {name}")
            verified[name] = actual
        return verified

    def _load_json(self, name: str) -> dict[str, Any]:
        path = self._ontology_dir / name
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OntologyIntegrityError(f"invalid frozen ontology artifact: {name}") from exc
        if not isinstance(value, dict):
            raise OntologyIntegrityError(f"invalid frozen registry structure: {name}")
        return value

    @staticmethod
    def _require_rows(registry: dict[str, Any], key: str, name: str) -> list[dict[str, Any]]:
        rows = registry.get(key)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise OntologyIntegrityError(f"invalid {name}: {key} must be a list of objects")
        return rows

    @staticmethod
    def _unique(rows: list[dict[str, Any]], key: str, name: str) -> None:
        values = [row.get(key) for row in rows]
        if any(not isinstance(value, str) or not value for value in values):
            raise OntologyIntegrityError(f"invalid {name}: missing {key}")
        if len(values) != len(set(values)):
            raise OntologyIntegrityError(f"invalid {name}: duplicate {key}")

    def _validate_registries(self) -> None:
        schema_version = self._manifest.get("schema_version")
        ontology_version = self._manifest.get("ontology_version")
        if (
            not isinstance(schema_version, str)
            or not isinstance(ontology_version, str)
            or self._manifest.get("design_only") is not True
            or self._manifest.get("production_migration") is not False
        ):
            raise OntologyIntegrityError("frozen ontology design boundary is invalid")

        registries = (
            self._objects_registry,
            self._links_registry,
            self._properties_registry,
            self._qualifiers_registry,
            self._extensions_registry,
            self._deferred_registry,
            self._cq_registry,
            self._mapping_registry,
        )
        for registry in registries:
            if (
                registry.get("schema_version") != schema_version
                or registry.get("ontology_version") != ontology_version
                or registry.get("design_only") is not True
            ):
                raise OntologyIntegrityError("frozen ontology registry version mismatch")

        objects = self._require_rows(self._objects_registry, "objects", "object registry")
        links = self._require_rows(self._links_registry, "links", "link registry")
        properties = self._require_rows(
            self._properties_registry, "properties", "property registry"
        )
        qualifiers = self._require_rows(
            self._qualifiers_registry, "qualifiers", "qualifier registry"
        )
        extensions = self._require_rows(
            self._extensions_registry, "items", "extension registry"
        )
        deferred = self._require_rows(self._deferred_registry, "items", "deferred registry")
        questions = self._require_rows(self._cq_registry, "questions", "CQ registry")
        class_mappings = self._require_rows(
            self._mapping_registry, "class_dispositions", "v1/v2 class mapping"
        )
        predicate_mappings = self._require_rows(
            self._mapping_registry, "predicate_dispositions", "v1/v2 predicate mapping"
        )

        self._unique(objects, "item_id", "object registry")
        self._unique(links, "predicate_id", "link registry")
        self._unique(properties, "property_id", "property registry")
        self._unique(qualifiers, "qualifier_id", "qualifier registry")
        self._unique(questions, "competency_question_id", "CQ registry")
        self._unique(class_mappings, "item_id", "v1/v2 class mapping")
        self._unique(predicate_mappings, "predicate_id", "v1/v2 predicate mapping")

        modules = self._objects_registry.get("modules")
        if not isinstance(modules, dict):
            raise OntologyIntegrityError("invalid object registry modules")
        core_objects = [row for row in objects if row.get("disposition") == "CORE_OBJECT_TYPE"]
        module_members = {
            item for members in modules.values() if isinstance(members, list) for item in members
        }
        object_ids = {row["item_id"] for row in objects}
        core_object_ids = {row["item_id"] for row in core_objects}
        if module_members != core_object_ids or any(
            row.get("module") not in modules for row in core_objects
        ):
            raise OntologyIntegrityError("object registry module membership mismatch")

        for row in links:
            required = {
                "predicate_id",
                "definition",
                "domain",
                "range",
                "classification",
                "evidence_policy",
                "qualifier_policy",
                "module",
            }
            if not required <= row.keys():
                raise OntologyIntegrityError("link registry row is incomplete")
            endpoints = set(row.get("domain", ())) | set(row.get("range", ()))
            if not endpoints <= object_ids:
                raise OntologyIntegrityError(
                    f"link registry has unknown endpoint: {row['predicate_id']}"
                )
        if any(row.get("classification") not in {"AUTHORITATIVE", "DERIVED_PROJECTION"} for row in links):
            raise OntologyIntegrityError("link registry has unknown classification")

        counts = self._manifest.get("counts")
        if not isinstance(counts, dict):
            raise OntologyIntegrityError("frozen ontology manifest counts are missing")
        computed = {
            "core_object_types": len(core_objects),
            "scientific_core_object_types": sum(
                row.get("layer") == "scientific" for row in core_objects
            ),
            "runtime_bridge_object_types": sum(
                bool(row.get("runtime_bridge_only")) for row in core_objects
            ),
            "properties": len(properties),
            "qualifiers": len(qualifiers),
            "core_link_types": sum(row.get("classification") == "AUTHORITATIVE" for row in links),
            "derived_projections": sum(row.get("classification") == "DERIVED_PROJECTION" for row in links),
            "extension_object_types": sum(row.get("item_type") == "OBJECT_TYPE" for row in extensions),
            "extension_link_types": sum(row.get("item_type") == "LINK_TYPE" for row in extensions),
            "deferred_object_types": sum(
                row.get("item_type") == "OBJECT_TYPE" and row.get("disposition") == "DEFERRED"
                for row in deferred
            ),
            "deferred_or_rejected_link_types": sum(
                row.get("item_type") == "LINK_TYPE" and row.get("disposition") == "DEFERRED"
                for row in deferred
            ),
            "merged_compatibility_object_types": sum(
                row.get("item_type") == "OBJECT_TYPE" and row.get("disposition") == "MERGE"
                for row in deferred
            ),
            "merged_predicates": sum(
                row.get("item_type") == "LINK_TYPE" and row.get("disposition") == "MERGE"
                for row in deferred
            ),
            "property_or_qualifier_predicates": sum(
                row.get("item_type") == "LINK_TYPE"
                and row.get("disposition") == "PROPERTY_OR_QUALIFIER"
                for row in deferred
            ),
            "cq_total": len(questions),
        }
        for key, actual in computed.items():
            if counts.get(key) != actual:
                raise OntologyIntegrityError(f"frozen ontology count mismatch: {key}")

        all_design_objects = core_object_ids | {
            row["item_id"]
            for row in (*extensions, *deferred)
            if row.get("item_type") == "OBJECT_TYPE"
        }
        if len(all_design_objects) != counts.get("design1_classes"):
            raise OntologyIntegrityError("object type disposition coverage mismatch")
        if {row["item_id"] for row in class_mappings} != all_design_objects:
            raise OntologyIntegrityError("v1/v2 class mapping coverage mismatch")

        if len(predicate_mappings) != counts.get("design1_predicates"):
            raise OntologyIntegrityError("v1/v2 predicate mapping count mismatch")

    def _build_object_rows(self) -> list[dict[str, Any]]:
        compatibility = {
            row["item_id"]: row for row in self._mapping_registry["class_dispositions"]
        }
        rows: list[dict[str, Any]] = []
        for source in self._objects_registry["objects"]:
            if source.get("disposition") != "CORE_OBJECT_TYPE":
                continue
            row = dict(source)
            row["display_status"] = "Core"
            row["display_layer"] = (
                "runtime bridge" if source.get("runtime_bridge_only") else "scientific"
            )
            row["compatibility"] = dict(compatibility[source["item_id"]])
            rows.append(row)
        for registry, status in (
            (self._extensions_registry, "Extension"),
            (self._deferred_registry, "Deferred"),
        ):
            for source in registry["items"]:
                if source.get("item_type") != "OBJECT_TYPE":
                    continue
                if status == "Deferred" and source.get("disposition") != "DEFERRED":
                    continue
                row = dict(source)
                row["display_status"] = status
                row["display_layer"] = "scientific"
                row["required_properties"] = []
                row["optional_properties"] = []
                row["required_links"] = []
                row["required_incoming_links"] = []
                row["compatibility"] = dict(compatibility[source["item_id"]])
                rows.append(row)
        return sorted(rows, key=lambda row: (row["display_status"], row["item_id"].casefold()))

    def _build_link_rows(self) -> list[dict[str, Any]]:
        compatibility = {
            row["predicate_id"]: row
            for row in self._mapping_registry["predicate_dispositions"]
        }
        rows = []
        for source in self._links_registry["links"]:
            row = dict(source)
            mapping = compatibility.get(source["predicate_id"])
            row["compatibility"] = (
                dict(mapping)
                if mapping
                else {"status": "NOT_AVAILABLE_IN_STATIC_MAPPING"}
            )
            rows.append(row)
        return sorted(rows, key=lambda row: row["predicate_id"].casefold())

    def integrity(self) -> dict[str, Any]:
        return {
            "status": "VERIFIED",
            "artifact_count": len(self._verified_hashes),
            "verified_hashes": dict(self._verified_hashes),
            "source_directory": str(self._ontology_dir.relative_to(self._root)),
            "read_only": True,
        }

    def overview(self) -> dict[str, Any]:
        counts = self._manifest["counts"]
        return {
            "ontology_version": self._manifest["ontology_version"],
            "schema_version": self._manifest["schema_version"],
            "freeze_commit": self._manifest["current_head"],
            "core_object_type_count": counts["core_object_types"],
            "authoritative_link_count": counts["core_link_types"],
            "derived_projection_count": counts["derived_projections"],
            "property_count": counts["properties"],
            "qualifier_count": counts["qualifiers"],
            "extension_count": counts["extension_object_types"],
            "deferred_count": counts["deferred_object_types"],
            "extension_registry_item_count": len(self._extensions_registry["items"]),
            "deferred_registry_item_count": len(self._deferred_registry["items"]),
            "merged_compatibility_object_count": counts[
                "merged_compatibility_object_types"
            ],
            "design_frozen": True,
            "production_migration": self._manifest["production_migration"],
        }

    def modules(self) -> list[str]:
        return sorted({row["module"] for row in self._objects})

    def object_types(
        self,
        query: str = "",
        *,
        modules: Iterable[str] | None = None,
        statuses: Iterable[str] | None = None,
        layers: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        module_filter = _as_set(modules)
        status_filter = _as_set(statuses)
        layer_filter = _as_set(layers)
        rows = []
        for row in self._objects:
            searchable = " ".join(
                str(row.get(key, ""))
                for key in ("item_id", "module", "definition", "disposition", "reason")
            ).casefold()
            if needle and needle not in searchable:
                continue
            if module_filter and row["module"] not in module_filter:
                continue
            if status_filter and row["display_status"] not in status_filter:
                continue
            if layer_filter and row["display_layer"] not in layer_filter:
                continue
            rows.append(
                {
                    "Object Type": row["item_id"],
                    "Module": row["module"],
                    "Definition": row["definition"],
                    "Status": row["display_status"],
                    "Scientific/runtime layer": row["display_layer"],
                    "Key properties": ", ".join(
                        [*row.get("required_properties", []), *row.get("optional_properties", [])]
                    ),
                    "Relevant CQ IDs": ", ".join(row.get("supporting_cq_ids", [])),
                }
            )
        return rows

    def object_detail(self, item_id: str) -> dict[str, Any]:
        row = next((item for item in self._objects if item["item_id"] == item_id), None)
        if row is None:
            raise KeyError(f"unknown ontology object type: {item_id}")
        incoming = []
        outgoing = []
        for link in self._links:
            if item_id in link["domain"]:
                outgoing.append(link["predicate_id"])
            if item_id in link["range"]:
                incoming.append(link["predicate_id"])
        return {
            "object_type": row["item_id"],
            "module": row["module"],
            "definition": row["definition"],
            "status": row["display_status"],
            "layer": row["display_layer"],
            "required_properties": list(row.get("required_properties", [])),
            "optional_properties": list(row.get("optional_properties", [])),
            "required_links": list(row.get("required_links", [])),
            "required_incoming_links": list(row.get("required_incoming_links", [])),
            "links_out": sorted(outgoing),
            "links_in": sorted(incoming),
            "cq_support": list(row.get("supporting_cq_ids", [])),
            "v1_compatibility": dict(row["compatibility"]),
            "frozen_record": {
                key: value
                for key, value in row.items()
                if key not in {"display_status", "display_layer", "compatibility"}
            },
        }

    def link_types(
        self,
        query: str = "",
        *,
        modules: Iterable[str] | None = None,
        classifications: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        module_filter = _as_set(modules)
        classification_filter = _as_set(classifications)
        rows = []
        for row in self._links:
            searchable = " ".join(
                (
                    row["predicate_id"],
                    row["definition"],
                    row["module"],
                    " ".join(row["domain"]),
                    " ".join(row["range"]),
                )
            ).casefold()
            if needle and needle not in searchable:
                continue
            if module_filter and row["module"] not in module_filter:
                continue
            if classification_filter and row["classification"] not in classification_filter:
                continue
            rows.append(
                {
                    "Predicate": row["predicate_id"],
                    "Definition": row["definition"],
                    "Domain": ", ".join(row["domain"]),
                    "Range": ", ".join(row["range"]),
                    "Authority": row["classification"],
                    "Evidence policy": row["evidence_policy"]["rule"],
                    "Qualifier policy": row["qualifier_policy"]["rule"],
                    "Status / module": f"{row['disposition']} · {row['module']}",
                }
            )
        return rows

    def link_detail(self, predicate_id: str) -> dict[str, Any]:
        row = next((item for item in self._links if item["predicate_id"] == predicate_id), None)
        if row is None:
            raise KeyError(f"unknown ontology link type: {predicate_id}")
        return {
            "predicate": predicate_id,
            "definition": row["definition"],
            "domain": list(row["domain"]),
            "range": list(row["range"]),
            "classification": row["classification"],
            "evidence_policy": dict(row["evidence_policy"]),
            "qualifier_policy": dict(row["qualifier_policy"]),
            "status": row["disposition"],
            "module": row["module"],
            "cq_support": list(row.get("supporting_cq_ids", [])),
            "v1_compatibility": dict(row["compatibility"]),
            "frozen_record": {
                key: value for key, value in row.items() if key != "compatibility"
            },
        }

    def properties(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        rows = []
        for row in self._properties_registry["properties"]:
            searchable = " ".join(
                (
                    row["property_id"],
                    row["definition"],
                    " ".join(row["owners"]),
                    row["value_type"],
                )
            ).casefold()
            if needle and needle not in searchable:
                continue
            machine_authority = (
                "NO MACHINE AUTHORITY"
                if row.get("decision_gate_allowed") is False
                else "NOT DECLARED"
            )
            rows.append(
                {
                    "Name": row["property_id"],
                    "Definition": row["definition"],
                    "Owners": ", ".join(row["owners"]),
                    "Value kind": row["value_type"],
                    "Assertion allowed?": (
                        str(row["assertion_allowed"]).upper()
                        if "assertion_allowed" in row
                        else "NOT DECLARED"
                    ),
                    "Machine authority?": machine_authority,
                }
            )
        return rows

    def qualifiers(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        rows = []
        for row in self._qualifiers_registry["qualifiers"]:
            searchable = " ".join(
                (row["qualifier_id"], row["definition"], row["owner"], row["storage_rule"])
            ).casefold()
            if needle and needle not in searchable:
                continue
            rows.append(
                {
                    "Name": row["qualifier_id"],
                    "Definition": row["definition"],
                    "Allowed context": row["owner"],
                    "Storage policy": row["storage_rule"],
                }
            )
        return rows

    def schema_modules(self) -> list[str]:
        return sorted(
            {row["module"] for row in self._objects} | {row["module"] for row in self._links}
        )

    def schema_graph(
        self,
        *,
        modules: Iterable[str] | None = None,
        authoritative_only: bool = False,
        show_derived: bool = True,
    ) -> dict[str, Any]:
        module_filter = _as_set(modules)
        eligible_links = [
            row
            for row in self._links
            if (not module_filter or row["module"] in module_filter)
            and (not authoritative_only or row["classification"] == "AUTHORITATIVE")
            and (show_derived or row["classification"] != "DERIVED_PROJECTION")
        ]
        node_ids = {
            row["item_id"]
            for row in self._objects
            if not module_filter or row["module"] in module_filter
        }
        if module_filter:
            for row in eligible_links:
                node_ids.update(row["domain"])
                node_ids.update(row["range"])
        nodes = [row for row in self._objects if row["item_id"] in node_ids]
        edges: list[dict[str, Any]] = []
        for row in eligible_links:
            for index, (source, target) in enumerate(row["allowed_endpoint_pairs"]):
                if source not in node_ids or target not in node_ids:
                    continue
                edges.append(
                    {
                        "edge_id": f"{row['predicate_id']}:{index}:{source}:{target}",
                        "predicate": row["predicate_id"],
                        "source": source,
                        "target": target,
                        "classification": row["classification"],
                        "definition": row["definition"],
                        "module": row["module"],
                        "evidence_policy": row["evidence_policy"]["rule"],
                        "qualifier_policy": row["qualifier_policy"]["rule"],
                    }
                )
        graph_nodes = [
            {
                "id": row["item_id"],
                "label": row["item_id"],
                "module": row["module"],
                "definition": row["definition"],
                "status": row["display_status"],
                "layer": row["display_layer"],
            }
            for row in nodes
        ]
        return {
            "nodes": graph_nodes,
            "edges": edges,
            "node_count": len(graph_nodes),
            "edge_count": len(edges),
            "schema_only": True,
            "instance_nodes_loaded": 0,
            "bounded": len(graph_nodes) <= 45,
        }


def build_ontology_schema_graph_html(graph: dict[str, Any]) -> str:
    """Build a bounded schema-only SVG with clickable node and edge details."""

    nodes = [dict(row) for row in graph["nodes"]]
    edges = [dict(row) for row in graph["edges"]]
    groups: dict[str, list[dict[str, Any]]] = {
        "Core": [],
        "Runtime Bridge": [],
        "Extension": [],
        "Deferred": [],
    }
    for row in nodes:
        group = "Runtime Bridge" if row["layer"] == "runtime bridge" else row["status"]
        groups.setdefault(group, []).append(row)

    center_x, center_y = 430.0, 350.0
    ring_config = {
        "Core": (285.0, -math.pi / 2),
        "Runtime Bridge": (82.0, -math.pi / 2),
        "Extension": (175.0, -math.pi / 2),
        "Deferred": (235.0, -math.pi / 2 + 0.14),
    }
    for group_name, group_nodes in groups.items():
        radius, offset = ring_config.get(group_name, (250.0, -math.pi / 2))
        ordered = sorted(group_nodes, key=lambda row: row["label"].casefold())
        for index, row in enumerate(ordered):
            angle = offset + 2 * math.pi * index / max(1, len(ordered))
            row["x"] = round(center_x + radius * math.cos(angle), 2)
            row["y"] = round(center_y + radius * math.sin(angle), 2)
            row["visual_group"] = group_name

    payload = {"nodes": nodes, "edges": edges, "summary": {
        "node_count": graph["node_count"],
        "edge_count": graph["edge_count"],
        "instance_nodes_loaded": graph["instance_nodes_loaded"],
    }}
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,system-ui,sans-serif;color:#182235;background:#fff}}
.shell{{display:grid;grid-template-columns:minmax(0,1fr) 310px;height:720px;border:1px solid #D8E1EC;border-radius:10px;overflow:hidden}}
.canvas{{position:relative;background:#FBFCFE;background-image:radial-gradient(#D9E2EE 1px,transparent 1px);background-size:22px 22px}}
svg{{width:100%;height:100%}}.edge{{stroke:#64748B;stroke-width:1.5;stroke-opacity:.52;cursor:pointer}}.edge:hover,.edge.selected{{stroke:#0F172A;stroke-width:3;stroke-opacity:1}}
.edge.derived{{stroke:#C45A2A;stroke-dasharray:7 5;stroke-width:2.2}}.node{{cursor:pointer}}.node circle{{stroke:#fff;stroke-width:2;filter:drop-shadow(0 2px 3px #9AA8B844)}}
.node:hover circle,.node.selected circle{{stroke:#111827;stroke-width:4}}.node text{{font-size:8px;font-weight:650;fill:#263247;text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:3px;pointer-events:none}}
.legend{{position:absolute;left:12px;top:12px;display:flex;gap:8px;flex-wrap:wrap;background:#ffffffdd;padding:8px;border-radius:7px;border:1px solid #D8E1EC;font-size:10px}}
.key{{display:flex;gap:4px;align-items:center}}.dot{{width:9px;height:9px;border-radius:50%}}.line{{width:18px;border-top:2px solid #64748B}}.line.derived{{border-top:2px dashed #C45A2A}}
.inspector{{border-left:1px solid #D8E1EC;overflow:auto;background:#fff}}.head{{padding:16px;border-bottom:1px solid #E5EAF1}}.head small{{font-size:9px;text-transform:uppercase;color:#557099;font-weight:750}}.head h3{{font-size:16px;margin:5px 0;word-break:break-word}}.head p{{font-size:10px;color:#69758A;margin:0;word-break:break-word}}
.body{{padding:14px}}.card{{padding:10px;border:1px solid #E0E6EF;border-radius:7px;margin-bottom:10px}}.card b{{display:block;font-size:9px;color:#69758A;text-transform:uppercase;margin-bottom:4px}}.card span,.card pre{{font-size:10px;line-height:1.5;white-space:pre-wrap;word-break:break-word;margin:0}}.summary{{position:absolute;left:12px;bottom:12px;background:#fff;padding:7px 9px;border:1px solid #D8E1EC;border-radius:6px;font-size:10px;color:#5B687D}}
</style></head><body><div class="shell"><div class="canvas"><div class="legend">
<span class="key"><i class="dot" style="background:#3978E8"></i>Core Object Type</span><span class="key"><i class="dot" style="background:#8B63C7"></i>Runtime Bridge</span><span class="key"><i class="dot" style="background:#D18B24"></i>Extension</span><span class="key"><i class="dot" style="background:#7C8798"></i>Deferred</span><span class="key"><i class="line"></i>Authoritative Link</span><span class="key"><i class="line derived"></i>Derived Projection</span>
</div><svg viewBox="0 0 860 700" role="img" aria-label="Bounded ontology schema graph"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#64748B"/></marker></defs><g id="edges"></g><g id="nodes"></g></svg><div class="summary">Schema only · {graph['node_count']} object types · {graph['edge_count']} endpoint edges · 0 instance nodes</div></div><aside class="inspector" id="inspector"></aside></div>
<script type="application/json" id="payload">{payload_json}</script><script>
const data=JSON.parse(document.getElementById('payload').textContent),ns='http://www.w3.org/2000/svg',nodeById=new Map(data.nodes.map(n=>[n.id,n]));
const colors={{'Core':'#3978E8','Runtime Bridge':'#8B63C7','Extension':'#D18B24','Deferred':'#7C8798'}},edgeLayer=document.getElementById('edges'),nodeLayer=document.getElementById('nodes'),inspector=document.getElementById('inspector');let selected=null;
const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]));
function show(kind,row){{selected={{kind,id:kind==='node'?row.id:row.edge_id}};document.querySelectorAll('.selected').forEach(el=>el.classList.remove('selected'));const el=document.querySelector(`[data-${{kind}}-id="${{CSS.escape(selected.id)}}"]`);if(el)el.classList.add('selected');const title=kind==='node'?row.label:row.predicate,tag=kind==='node'?row.visual_group:row.classification;const details=kind==='node'?{{Module:row.module,Layer:row.layer,Definition:row.definition}}:{{From:row.source,To:row.target,Module:row.module,Definition:row.definition,'Evidence policy':row.evidence_policy,'Qualifier policy':row.qualifier_policy}};inspector.innerHTML=`<div class="head"><small>${{esc(tag)}}</small><h3>${{esc(title)}}</h3><p>${{esc(kind==='node'?row.id:row.edge_id)}}</p></div><div class="body">${{Object.entries(details).map(([k,v])=>`<div class="card"><b>${{esc(k)}}</b><span>${{esc(v)}}</span></div>`).join('')}}</div>`}}
data.edges.forEach(e=>{{const a=nodeById.get(e.source),b=nodeById.get(e.target);if(!a||!b)return;const line=document.createElementNS(ns,'line');line.setAttribute('x1',a.x);line.setAttribute('y1',a.y);line.setAttribute('x2',b.x);line.setAttribute('y2',b.y);line.setAttribute('marker-end','url(#arrow)');line.classList.add('edge');if(e.classification==='DERIVED_PROJECTION')line.classList.add('derived');line.dataset.edgeId=e.edge_id;line.addEventListener('click',ev=>{{ev.stopPropagation();show('edge',e)}});const tip=document.createElementNS(ns,'title');tip.textContent=`${{e.predicate}} · ${{e.classification}}`;line.appendChild(tip);edgeLayer.appendChild(line)}});
data.nodes.forEach(n=>{{const g=document.createElementNS(ns,'g');g.classList.add('node');g.dataset.nodeId=n.id;g.setAttribute('transform',`translate(${{n.x}} ${{n.y}})`);const c=document.createElementNS(ns,'circle');c.setAttribute('r',n.visual_group==='Runtime Bridge'?11:9);c.setAttribute('fill',colors[n.visual_group]||'#7C8798');const t=document.createElementNS(ns,'text');t.setAttribute('y','-14');t.textContent=n.label.length>24?n.label.slice(0,23)+'…':n.label;const tip=document.createElementNS(ns,'title');tip.textContent=`${{n.label}} · ${{n.visual_group}}`;g.append(c,t,tip);g.addEventListener('click',ev=>{{ev.stopPropagation();show('node',n)}});nodeLayer.appendChild(g)}});
inspector.innerHTML=`<div class="head"><small>Schema graph</small><h3>Choose a node or edge</h3><p>Click the canvas to inspect the exact frozen definition.</p></div><div class="body"><div class="card"><b>Boundary</b><span>Schema-only view. No Scientific KG instance nodes are loaded.</span></div><div class="card"><b>Authority</b><span>Dashed orange edges are derived projections and are not authoritative statements.</span></div></div>`;
</script></body></html>"""
