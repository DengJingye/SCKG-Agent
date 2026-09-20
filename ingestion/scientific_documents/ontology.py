from __future__ import annotations

import hashlib
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
        self.schema_version = str(self.manifest["schema_version"])
        links = _load(self.root / "link_type_registry.json")["links"]
        self.links = {str(item["predicate_id"]): item for item in links}
        self.qualifiers = {
            str(item["qualifier_id"])
            for item in _load(self.root / "qualifier_registry.json")["qualifiers"]
        }
        self.scope_statuses = set(_load(self.root / "scope_policy.json")["scope_status"])
        self.statement_model = _load(self.root / "statement_model.json")["revision"]
        self.evidence_model = _load(self.root / "evidence_model.json")
        object_registry = _load(self.root / "object_type_registry.json")
        self.object_types = {str(item["item_id"]): item for item in object_registry["objects"]}
        property_registry = _load(self.root / "property_registry.json")
        self.embedded_value_shapes = property_registry["embedded_value_shapes"]
        self.property_enums = {
            str(item["property_id"]): set(item.get("enum") or [])
            for item in property_registry["properties"]
        }

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

    def validate_parameter_definition(self, record: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        required = {"id", "entity_id", "schema_version", "ontology_version", "label", "value_domain", "owner_operator_ref"}
        missing = sorted(key for key in required if record.get(key) in (None, "", []))
        if missing:
            reasons.append("PARAMETER_DEFINITION_MISSING:" + ",".join(missing))
        domain = record.get("value_domain")
        shape = self.embedded_value_shapes["parameter_value_domain"]
        if not isinstance(domain, dict) or domain.get("datatype") not in shape["datatype"]:
            reasons.append("PARAMETER_VALUE_DOMAIN_INVALID_DATATYPE")
        elif "allowed_values" in domain:
            values = domain["allowed_values"]
            if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
                reasons.append("PARAMETER_VALUE_DOMAIN_INVALID_ALLOWED_VALUES")
        revisions = record.get("allowed_operator_revision_ids")
        if not isinstance(revisions, list) or len(revisions) != 1 or not revisions[0]:
            reasons.append("PARAMETER_REVISION_BINDING_MISSING")
        return not reasons, reasons

    def validate_software_version_qualifier(
        self,
        value: object,
        *,
        subject_id: str,
    ) -> tuple[bool, list[str]]:
        if not isinstance(value, dict) or set(value) != {"subject_id", "status", "expression"}:
            return False, ["SOFTWARE_VERSION_QUALIFIER_INVALID_SHAPE"]
        if value.get("subject_id") != subject_id or value.get("status") != "exact":
            return False, ["SOFTWARE_VERSION_QUALIFIER_SUBJECT_OR_STATUS_INVALID"]
        pattern = self.embedded_value_shapes["version_constraint"]["exact_pattern"]
        if not isinstance(value.get("expression"), str) or not re.fullmatch(pattern, value["expression"]):
            return False, ["SOFTWARE_VERSION_QUALIFIER_EXPRESSION_INVALID"]
        return True, []

    def validate_candidate_subgraph(
        self,
        subgraph: dict[str, Any],
    ) -> tuple[bool, list[str], list[str], list[str], list[str]]:
        """Validate a candidate subgraph against the frozen registries.

        This is intentionally a read-only conformance gate. It does not build,
        promote, partition, or write any ontology or KG state.
        """

        errors: list[str] = []
        warnings: list[str] = []
        validated_node_ids: list[str] = []
        validated_link_ids: list[str] = []
        nodes = list(subgraph.get("nodes") or [])
        links = list(subgraph.get("links") or [])
        references = list(subgraph.get("referenced_entities") or [])
        records_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
        endpoint_types: dict[str, str] = {}

        for reference in references:
            record_id = str(reference.get("record_id") or "")
            record_type = str(reference.get("record_type") or "")
            if not record_id or not record_type:
                errors.append("ENTITY_REFERENCE_MISSING_ID_OR_TYPE")
                continue
            if record_id in endpoint_types and endpoint_types[record_id] != record_type:
                errors.append(f"ENTITY_REFERENCE_TYPE_CONFLICT:{record_id}")
            endpoint_types[record_id] = record_type

        for node in nodes:
            record_id = str(node.get("record_id") or "")
            record_type = str(node.get("record_type") or "")
            record = node.get("record")
            prefix = record_id or "<missing-node-id>"
            if not record_id or not record_type or not isinstance(record, dict):
                errors.append(f"NODE_SHAPE_INVALID:{prefix}")
                continue
            if record_id in records_by_id:
                errors.append(f"DUPLICATE_NODE_ID:{record_id}")
                continue
            records_by_id[record_id] = (record_type, record)
            endpoint_types[record_id] = record_type
            schema = self.object_types.get(record_type)
            if schema is None:
                errors.append(f"OBJECT_TYPE_NOT_IN_FROZEN_REGISTRY:{record_type}")
                continue
            if record.get("id") != record_id:
                errors.append(f"NODE_ID_MISMATCH:{record_id}")
            if record.get("ontology_version") != self.ontology_version:
                errors.append(f"ONTOLOGY_VERSION_MISMATCH:{record_id}")
            if record.get("schema_version") != self.schema_version:
                errors.append(f"SCHEMA_VERSION_MISMATCH:{record_id}")
            missing = [
                name
                for name in schema.get("required_properties", [])
                if record.get(name) in (None, "", [])
            ]
            if missing:
                errors.append(f"REQUIRED_PROPERTIES_MISSING:{record_id}:{','.join(sorted(missing))}")
            validated_node_ids.append(record_id)

        link_keys: set[tuple[str, str, str]] = set()
        outgoing: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for link in links:
            link_id = str(link.get("link_id") or "")
            predicate = str(link.get("predicate") or "")
            subject_id = str(link.get("subject_id") or "")
            object_id = str(link.get("object_id") or "")
            subject_type = str(link.get("subject_type") or "")
            object_type = str(link.get("object_type") or "")
            if not all((link_id, predicate, subject_id, object_id, subject_type, object_type)):
                errors.append(f"LINK_SHAPE_INVALID:{link_id or '<missing-link-id>'}")
                continue
            key = (subject_id, predicate, object_id)
            if key in link_keys:
                errors.append(f"DUPLICATE_LINK:{subject_id}:{predicate}:{object_id}")
            link_keys.add(key)
            if endpoint_types.get(subject_id) != subject_type:
                errors.append(f"LINK_SUBJECT_TYPE_MISMATCH:{link_id}")
            if endpoint_types.get(object_id) != object_type:
                errors.append(f"LINK_OBJECT_TYPE_MISMATCH:{link_id}")
            valid, reasons = self.validate_link(predicate, subject_type, object_type, as_statement=False)
            if not valid:
                errors.extend(f"{reason}:{link_id}" for reason in reasons)
            registry_link = self.links.get(predicate)
            if registry_link and link.get("classification") != registry_link.get("classification"):
                errors.append(f"LINK_CLASSIFICATION_MISMATCH:{link_id}")
            outgoing[(subject_id, predicate)].append(link)
            validated_link_ids.append(link_id)

        for record_id, (record_type, _) in records_by_id.items():
            for predicate in self.object_types[record_type].get("required_links", []):
                required = outgoing.get((record_id, predicate), [])
                if not required:
                    errors.append(f"REQUIRED_LINK_MISSING:{record_id}:{predicate}")
                elif self.links[predicate].get("cardinality") == "1" and len(required) != 1:
                    errors.append(f"REQUIRED_LINK_CARDINALITY:{record_id}:{predicate}")

        for record_id, (record_type, record) in records_by_id.items():
            if record_type == "ScientificStatement" and record.get("statement_id") != record_id:
                errors.append(f"SCIENTIFIC_STATEMENT_ID_MISMATCH:{record_id}")
            if record_type == "SourceWork" and record.get("source_work_id") != record_id:
                errors.append(f"SOURCE_WORK_ID_MISMATCH:{record_id}")
            if record_type == "SourceRevision" and record.get("source_revision_id") != record_id:
                errors.append(f"SOURCE_REVISION_ID_MISMATCH:{record_id}")
            if record_type == "SourceArtifact":
                if record.get("source_artifact_id") != record_id:
                    errors.append(f"SOURCE_ARTIFACT_ID_MISMATCH:{record_id}")
                if not re.fullmatch(r"[a-f0-9]{64}", str(record.get("content_hash") or "")):
                    errors.append(f"SOURCE_ARTIFACT_HASH_INVALID:{record_id}")

        primary_subject_id = str(subgraph.get("primary_subject_id") or "")
        primary_subject_type = str(subgraph.get("primary_subject_type") or "")
        primary_predicate = str(subgraph.get("primary_predicate") or "")
        primary_object_id = str(subgraph.get("primary_object_id") or "")
        primary_object_type = str(subgraph.get("primary_object_type") or "")
        relation_kind = str(subgraph.get("relation_kind") or "")
        primary_valid, primary_reasons = self.validate_link(
            primary_predicate,
            primary_subject_type,
            primary_object_type,
            as_statement=relation_kind == "SCIENTIFIC_STATEMENT",
        )
        if not primary_valid:
            errors.extend(f"PRIMARY_{reason}" for reason in primary_reasons)
        for record_id, record_type, role in (
            (primary_subject_id, primary_subject_type, "SUBJECT"),
            (primary_object_id, primary_object_type, "OBJECT"),
        ):
            if endpoint_types.get(record_id) != record_type:
                errors.append(f"PRIMARY_{role}_REFERENCE_MISSING_OR_MISMATCH")

        if relation_kind == "SCIENTIFIC_STATEMENT":
            self._validate_scientific_candidate_chain(
                subgraph,
                records_by_id,
                outgoing,
                errors,
                warnings,
            )
        elif relation_kind == "STRUCTURAL_RELATION":
            if not outgoing.get((primary_subject_id, primary_predicate)) or not any(
                item.get("object_id") == primary_object_id
                for item in outgoing.get((primary_subject_id, primary_predicate), [])
            ):
                errors.append("PRIMARY_STRUCTURAL_LINK_MISSING")
            if any(record_type in {"ScientificStatement", "StatementRevision", "EvidenceAssessment"} for record_type, _ in records_by_id.values()):
                errors.append("STRUCTURAL_RELATION_CONTAINS_STATEMENT_CHAIN")
        else:
            errors.append("RELATION_KIND_INVALID")

        return not errors, sorted(set(errors)), sorted(set(warnings)), validated_node_ids, validated_link_ids

    def _validate_scientific_candidate_chain(
        self,
        subgraph: dict[str, Any],
        records_by_id: dict[str, tuple[str, dict[str, Any]]],
        outgoing: dict[tuple[str, str], list[dict[str, Any]]],
        errors: list[str],
        warnings: list[str],
    ) -> None:
        statement_revision_id = str(subgraph.get("statement_revision_id") or "")
        assessment_id = str(subgraph.get("evidence_assessment_id") or "")
        revision_entry = records_by_id.get(statement_revision_id)
        assessment_entry = records_by_id.get(assessment_id)
        if revision_entry is None or revision_entry[0] != "StatementRevision":
            errors.append("STATEMENT_REVISION_NODE_MISSING")
            return
        if assessment_entry is None or assessment_entry[0] != "EvidenceAssessment":
            errors.append("EVIDENCE_ASSESSMENT_NODE_MISSING")
            return

        revision = revision_entry[1]
        missing_revision = [
            field
            for field in self.statement_model["required_fields"]
            if revision.get(field) in (None, "", [])
        ]
        if missing_revision:
            errors.append("STATEMENT_REVISION_FIELDS_MISSING:" + ",".join(sorted(missing_revision)))
        if revision.get("id") != revision.get("statement_revision_id"):
            errors.append("STATEMENT_REVISION_ID_MISMATCH")
        targets = [field for field in self.statement_model["exactly_one"] if revision.get(field) is not None]
        if len(targets) != 1:
            errors.append("STATEMENT_REVISION_TARGET_CARDINALITY")
        if revision.get("subject_id") != subgraph.get("primary_subject_id"):
            errors.append("STATEMENT_REVISION_SUBJECT_MISMATCH")
        if revision.get("predicate") != subgraph.get("primary_predicate"):
            errors.append("STATEMENT_REVISION_PREDICATE_MISMATCH")
        if revision.get("object_id") != subgraph.get("primary_object_id"):
            errors.append("STATEMENT_REVISION_OBJECT_MISMATCH")
        if revision.get("polarity") not in self.statement_model["polarity"]:
            errors.append("STATEMENT_REVISION_POLARITY_INVALID")
        if revision.get("epistemic_status") not in self.statement_model["epistemic_status"]:
            errors.append("STATEMENT_REVISION_EPISTEMIC_STATUS_INVALID")
        if revision.get("assertion_kind") not in self.statement_model["assertion_kind"]:
            errors.append("STATEMENT_REVISION_ASSERTION_KIND_INVALID")
        if revision.get("scope_status") not in self.scope_statuses:
            errors.append("STATEMENT_REVISION_SCOPE_STATUS_INVALID")
        qualifiers = revision.get("qualifiers")
        predicate_record = self.links.get(str(revision.get("predicate") or "")) or {}
        if not isinstance(qualifiers, dict):
            errors.append("STATEMENT_REVISION_QUALIFIERS_INVALID")
        else:
            disallowed = sorted(set(qualifiers) - set(predicate_record.get("qualifier_policy", {}).get("allowed", [])))
            if disallowed:
                errors.append("STATEMENT_REVISION_QUALIFIERS_NOT_ALLOWED:" + ",".join(disallowed))
            if "software_version" in qualifiers:
                valid, reasons = self.validate_software_version_qualifier(
                    qualifiers["software_version"],
                    subject_id=str(revision.get("subject_id") or ""),
                )
                if not valid:
                    errors.extend(reasons)

        statement_links = outgoing.get((statement_revision_id, self.statement_model["identity_link"]), [])
        if not any(item.get("object_id") == revision.get("statement_id") for item in statement_links):
            errors.append("STATEMENT_REVISION_IDENTITY_LINK_MISMATCH")

        assessment = assessment_entry[1]
        assessment_model = self.evidence_model["assessment"]
        missing_assessment = [
            field
            for field in assessment_model["required_fields"]
            if assessment.get(field) in (None, "", [])
        ]
        if missing_assessment:
            errors.append("EVIDENCE_ASSESSMENT_FIELDS_MISSING:" + ",".join(sorted(missing_assessment)))
        if assessment.get("id") != assessment.get("assessment_id"):
            errors.append("EVIDENCE_ASSESSMENT_ID_MISMATCH")
        if assessment.get("statement_revision_id") != statement_revision_id:
            errors.append("EVIDENCE_ASSESSMENT_STATEMENT_MISMATCH")
        if assessment.get("status") not in assessment_model["status"]:
            errors.append("EVIDENCE_ASSESSMENT_STATUS_INVALID")
        support_types = {item["value"] for item in self.evidence_model["support_types"]}
        if assessment.get("support_type") not in support_types:
            errors.append("EVIDENCE_ASSESSMENT_SUPPORT_TYPE_INVALID")
        if assessment.get("scope_alignment") not in self.property_enums.get("scope_alignment", set()):
            errors.append("EVIDENCE_ASSESSMENT_SCOPE_ALIGNMENT_INVALID")
        for field in ("subject_aligned", "predicate_aligned", "object_aligned"):
            if not isinstance(assessment.get(field), bool):
                errors.append(f"EVIDENCE_ASSESSMENT_ALIGNMENT_FLAG_INVALID:{field}")
        if assessment.get("support_type") == "DIRECT_SUPPORT" and not (
            assessment.get("subject_aligned") is True
            and assessment.get("predicate_aligned") is True
            and assessment.get("object_aligned") is True
            and assessment.get("scope_alignment") == "aligned"
        ):
            errors.append("DIRECT_SUPPORT_ALIGNMENT_RULE_FAILED")
        evidence_span_id = str(assessment.get("evidence_span_id") or "")
        evidence_entry = records_by_id.get(evidence_span_id)
        if evidence_entry is None or evidence_entry[0] != "EvidenceSpan":
            errors.append("EVIDENCE_SPAN_NODE_MISSING")
        else:
            span = evidence_entry[1]
            missing_span = [
                field
                for field in self.evidence_model["EVIDENCE_SPAN_CORE_FIELDS"]
                if span.get(field) in (None, "", [])
            ]
            if missing_span:
                errors.append("EVIDENCE_SPAN_FIELDS_MISSING:" + ",".join(sorted(missing_span)))
            if span.get("id") != span.get("evidence_span_id"):
                errors.append("EVIDENCE_SPAN_ID_MISMATCH")
            exact_text = span.get("exact_text")
            if isinstance(exact_text, str):
                expected_hash = hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
                if span.get("content_hash") != expected_hash:
                    errors.append("EVIDENCE_SPAN_CONTENT_HASH_MISMATCH")
            if span.get("start_offset") is None or span.get("end_offset") is None:
                errors.append("EVIDENCE_SPAN_OFFSETS_MISSING")
            elif not (isinstance(span["start_offset"], int) and isinstance(span["end_offset"], int) and span["end_offset"] > span["start_offset"]):
                errors.append("EVIDENCE_SPAN_OFFSETS_INVALID")
            elif isinstance(exact_text, str) and span["end_offset"] - span["start_offset"] != len(exact_text):
                errors.append("EVIDENCE_SPAN_OFFSET_LENGTH_MISMATCH")
            if not outgoing.get((evidence_span_id, "span_in_revision")):
                errors.append("EVIDENCE_SPAN_REVISION_LINK_MISSING")
            elif not any(
                item.get("object_id") == span.get("source_revision_id")
                for item in outgoing[(evidence_span_id, "span_in_revision")]
            ):
                errors.append("EVIDENCE_SPAN_REVISION_LINK_MISMATCH")
            if not outgoing.get((evidence_span_id, "span_in_artifact")):
                errors.append("EVIDENCE_SPAN_ARTIFACT_LINK_MISSING")
            elif not any(
                item.get("object_id") == span.get("source_artifact_id")
                for item in outgoing[(evidence_span_id, "span_in_artifact")]
            ):
                errors.append("EVIDENCE_SPAN_ARTIFACT_LINK_MISMATCH")
            artifact_id = str(span.get("source_artifact_id") or "")
            if not any(
                item.get("object_id") == span.get("source_revision_id")
                for item in outgoing.get((artifact_id, "artifact_of"), [])
            ):
                errors.append("EVIDENCE_SPAN_ARTIFACT_REVISION_INCONSISTENT")

        if not any(item.get("object_id") == statement_revision_id for item in outgoing.get((assessment_id, "assesses_statement"), [])):
            errors.append("EVIDENCE_ASSESSMENT_STATEMENT_LINK_MISMATCH")
        if not any(item.get("object_id") == evidence_span_id for item in outgoing.get((assessment_id, "uses_evidence"), [])):
            errors.append("EVIDENCE_ASSESSMENT_EVIDENCE_LINK_MISMATCH")
        if assessment.get("status") == "draft":
            warnings.append("EVIDENCE_ASSESSMENT_DRAFT_PENDING_HUMAN_REVIEW")


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
            item: dict[str, Any] = {
                "record_id": record_id,
                "record_type": str(node["record_type"]),
                "label": str(node.get("label") or record_id),
                "record": record,
            }
            self.by_id.setdefault(record_id, item)
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

    def stable_operator(self, operator_revision_id: str) -> dict[str, Any] | None:
        revision = self.exact_id(operator_revision_id, "OperatorRevision")
        if revision is None:
            return None
        return self.exact_id(str(revision["record"].get("operator_id") or ""), "Operator")

    def declared_method(self, operator_revision_id: str) -> dict[str, Any] | None:
        revision = self.exact_id(operator_revision_id, "OperatorRevision")
        if revision is None:
            return None
        method_ids = list(revision["record"].get("implements_method_ids") or [])
        if len(method_ids) != 1:
            return None
        return self.exact_id(str(method_ids[0]), "Method")
