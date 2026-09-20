from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class FrozenOntologyConformanceAdapter:
    """Minimal, read-only adapter over the frozen Design 5C registries.

    It intentionally exposes no build, partition, promotion, or mutation API.
    """

    def __init__(self, repository_root: Path) -> None:
        self.root = repository_root / "data/ontology/scientific_decision_ontology_v2_core"
        self.manifest = _load(self.root / "manifest.json")
        if not self.manifest.get("design_only") or self.manifest.get("production_migration"):
            raise ValueError("frozen ontology must remain design-only and non-production")
        self.ontology_version = str(self.manifest["ontology_version"])
        links = _load(self.root / "link_type_registry.json")["links"]
        self.links = {str(item["predicate_id"]): item for item in links}
        self.qualifiers = {
            str(item["qualifier_id"])
            for item in _load(self.root / "qualifier_registry.json")["qualifiers"]
        }
        self.scope_statuses = set(_load(self.root / "scope_policy.json")["scope_status"])
        self.statement_model = _load(self.root / "statement_model.json")["revision"]
        self.evidence_model = _load(self.root / "evidence_model.json")

    def validate_link(
        self,
        predicate: str,
        subject_type: str,
        object_type: str,
        *,
        as_statement: bool,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        record = self.links.get(predicate)
        if record is None:
            return False, ["PREDICATE_NOT_IN_FROZEN_REGISTRY"]
        endpoint = [subject_type, object_type]
        if endpoint not in record.get("allowed_endpoint_pairs", []):
            reasons.append("ENDPOINT_PAIR_NOT_ALLOWED")
        if as_statement and not record.get("statement_predicate_allowed", False):
            reasons.append("PREDICATE_NOT_ALLOWED_FOR_STATEMENT_REVISION")
        return not reasons, reasons


class ExactIdentityIndex:
    """Exact-only lookup of candidate inventory identities; never fuzzy-merges."""

    def __init__(self, repository_root: Path) -> None:
        graph_path = (
            repository_root
            / "data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json"
        )
        graph = _load(graph_path)
        self.by_id: dict[str, dict[str, Any]] = {}
        self.by_qualified_name: dict[tuple[str, str], set[str]] = defaultdict(set)
        for node in graph["nodes"]:
            record_id = str(node["record_id"])
            record = dict(node.get("record") or {})
            item = {
                "record_id": record_id,
                "record_type": str(node["record_type"]),
                "label": str(node.get("label") or record_id),
                "record": record,
            }
            self.by_id[record_id] = item
            for field in ("qualified_name", "api_path"):
                value = str(record.get(field) or "")
                if value:
                    self.by_qualified_name[(item["record_type"], _norm(value))].add(record_id)

    def exact_id(self, record_id: str, expected_type: str) -> dict[str, Any] | None:
        item = self.by_id.get(record_id)
        if item and item["record_type"] == expected_type:
            return item
        return None

    def exact_qualified_name(self, value: str, expected_type: str) -> dict[str, Any] | None:
        ids = self.by_qualified_name.get((expected_type, _norm(value)), set())
        if len(ids) != 1:
            return None
        return self.by_id[next(iter(ids))]

    def operator_revision(self, package: str, operator: str, version: str) -> dict[str, Any] | None:
        direct_id = f"operator-revision:{package.casefold()}.{package.casefold()}__{operator.casefold()}:{version}"
        return self.exact_id(direct_id, "OperatorRevision")

    def output_binding(self, operator_revision_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        operator = self.exact_id(operator_revision_id, "OperatorRevision")
        if operator is None:
            return None
        outputs = list(operator["record"].get("output_ports") or [])
        if len(outputs) != 1:
            return None
        output_id = str(outputs[0].get("output_port_id") or "")
        representation_id = str(outputs[0].get("representation_type_id") or "")
        output = self.exact_id(output_id, "OutputPort")
        representation = self.exact_id(representation_id, "RepresentationType")
        if output and representation:
            return output, representation
        return None
