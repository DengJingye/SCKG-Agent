from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.scientific_knowledge_conformance_models import (
    ConformanceBundle,
    OperatorRevision,
    ReferenceArtifact,
    ReferenceArtifactRevision,
)
from engine.scientific_ontology_v2_compatibility import (
    AUTHORITATIVE_BASE_COMMIT,
    ScientificOntologyV2CompatibilityService,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "evaluation" / "ontology_v2_compatibility_v1"
GRAPH_PATH = (
    ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_inventory"
    / "scientific_kg_v1_consolidated_graph.json"
)
FROZEN_CORE_DIR = ROOT / "data" / "ontology" / "scientific_decision_ontology_v2_core"
REFERENCE_FIXTURE = (
    ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_knowledge_schema_v1_1"
    / "fixtures"
    / "reference-and-multimodal-requirements.json"
)
OUTPUT_NAMES = (
    "mapping_summary.json",
    "compatibility_counts.json",
    "unresolved_mappings.json",
    "integrity.json",
    "test_summary.json",
)
PATCH_BASE_COMMIT = "6a7fc238676a3389c7e556b16ab8bac33d53e7bd"


class TestExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["PASS", "FAIL", "NOT_RUN", "UNVERIFIED"]
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    command: tuple[str, ...] = ()
    evidence: str | None = None

    @model_validator(mode="after")
    def validate_pass_evidence(self) -> "TestExecutionSummary":
        if self.status == "PASS" and (
            self.passed < 1
            or self.failed
            or self.errors
            or not self.command
            or not self.evidence
        ):
            raise ValueError(
                "PASS requires positive cases, zero failures/errors, a command and evidence"
            )
        if self.status == "FAIL" and not (self.failed or self.errors):
            raise ValueError("FAIL requires at least one failure or error")
        return self


def _validated_test_summary(
    value: TestExecutionSummary | Mapping[str, Any] | str | None,
) -> TestExecutionSummary:
    if isinstance(value, TestExecutionSummary):
        return value
    if value is None or (isinstance(value, str) and value.casefold() in {"not_run", "not run"}):
        return TestExecutionSummary(status="NOT_RUN")
    if isinstance(value, str):
        if value.strip().upper() in {"FAIL", "FAILED", "FAILURE"}:
            return TestExecutionSummary(
                status="FAIL",
                failed=1,
                evidence=f"unstructured failure marker: {value}",
            )
        return TestExecutionSummary(
            status="UNVERIFIED",
            evidence=f"unstructured test result rejected: {value}",
        )
    try:
        return TestExecutionSummary.model_validate(value)
    except ValidationError as exc:
        return TestExecutionSummary(
            status="UNVERIFIED",
            evidence=f"invalid structured test result: {exc.errors()[0]['type']}",
        )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _result_row(category: str, source_id: str, result: Any, layer_id: str) -> dict[str, Any]:
    return {
        "category": category,
        "layer_id": layer_id,
        "source_id": source_id,
        "status": result.status,
        "reason_codes": list(result.reason_codes),
    }


def _count_status(results: list[Any]) -> dict[str, int]:
    counts = Counter(result.status for result in results)
    return {
        status: counts.get(status, 0)
        for status in (
            "DIRECT_COMPATIBLE",
            "COMPATIBLE_WITH_ADAPTER",
            "AMBIGUOUS_MAPPING",
            "NOT_MAPPABLE",
            "DEFERRED",
        )
    }


def collect_assessments(
    edges: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    by_claim: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        assessment = edge.get("provenance", {}).get("evidence_assessment")
        if not assessment:
            continue
        identity = (edge["layer_id"], assessment["assessment_id"])
        existing = by_identity.get(identity)
        if existing is not None and existing != assessment:
            raise ValueError("conflicting_duplicate_assessment_identity")
        by_identity[identity] = assessment
    for (layer_id, _), assessment in sorted(by_identity.items()):
        by_claim[(layer_id, assessment["claim_revision_id"])].append(assessment)
    return by_identity, by_claim


def build(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    focused_tests: TestExecutionSummary | Mapping[str, Any] | str | None = None,
    regression_tests: TestExecutionSummary | Mapping[str, Any] | str | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    service = ScientificOntologyV2CompatibilityService(ROOT)
    graph = _read_json(GRAPH_PATH)
    focused_result = _validated_test_summary(focused_tests)
    regression_result = _validated_test_summary(regression_tests)

    nodes_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    node_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    record_type_by_identity: dict[tuple[str, str], str] = {}
    node_by_graph_id: dict[str, dict[str, Any]] = {}
    for node in graph["nodes"]:
        nodes_by_type[node["record_type"]].append(node)
        node_index[(node["layer_id"], node["record_type"], node["record_id"])] = node
        record_type_by_identity[(node["layer_id"], node["record_id"])] = node["record_type"]
        node_by_graph_id[node["graph_node_id"]] = node

    assessment_by_identity, assessments_by_claim = collect_assessments(graph["edges"])

    scope_results: dict[tuple[str, str], Any] = {}
    for node in nodes_by_type["ApplicabilityScope"]:
        scope_results[(node["layer_id"], node["record_id"])] = service.map_scope(
            node["record"],
            source_layer_id=node["layer_id"],
            source_graph_node_id=node["graph_node_id"],
            source_status=node["status"],
        )

    claim_results: list[Any] = []
    claim_result_index: dict[tuple[str, str], Any] = {}
    claim_rows: list[dict[str, Any]] = []
    for node in nodes_by_type["AtomicClaimRevision"]:
        scope_node = node_index.get(
            (node["layer_id"], "ApplicabilityScope", node["record"].get("scope_id", ""))
        )
        assessments = assessments_by_claim.get((node["layer_id"], node["record_id"]), [])
        result = service.map_atomic_claim(
            node["record"],
            scope=scope_node["record"] if scope_node else None,
            evidence_assessments=assessments,
            source_layer_id=node["layer_id"],
            source_graph_node_id=node["graph_node_id"],
            source_status=node["status"],
        )
        claim_results.append(result)
        claim_result_index[(node["layer_id"], node["record_id"])] = result
        claim_rows.append(_result_row("AtomicClaimRevision", node["record_id"], result, node["layer_id"]))

    span_results: list[Any] = []
    span_result_index: dict[tuple[str, str], Any] = {}
    span_rows: list[dict[str, Any]] = []
    for node in nodes_by_type["EvidenceSpan"]:
        result = service.map_evidence_span(
            node["record"],
            source_layer_id=node["layer_id"],
            source_graph_node_id=node["graph_node_id"],
            source_status=node["status"],
        )
        span_results.append(result)
        span_result_index[(node["layer_id"], node["record_id"])] = result
        span_rows.append(_result_row("EvidenceSpan", node["record_id"], result, node["layer_id"]))

    assessment_results: list[Any] = []
    assessment_rows: list[dict[str, Any]] = []
    for (layer_id, assessment_id), assessment in sorted(assessment_by_identity.items()):
        claim_revision_id = assessment["claim_revision_id"]
        claim_result = claim_result_index.get((layer_id, claim_revision_id))
        statement_revision_ids = (
            {claim_revision_id} if claim_result is not None and claim_result.view is not None else set()
        )
        layer_spans = {
            span_id: result
            for (span_layer, span_id), result in span_result_index.items()
            if span_layer == layer_id
        }
        result = service.map_evidence_assessment(
            assessment,
            statement_revision_ids=statement_revision_ids,
            evidence_spans=layer_spans,
            source_layer_id=layer_id,
            source_status="candidate_not_promoted",
        )
        assessment_results.append(result)
        assessment_rows.append(
            _result_row("EvidenceAssessment", assessment_id, result, layer_id)
        )

    known_constraints = {
        (node["layer_id"], node["record_id"])
        for node in nodes_by_type["RepresentationConstraint"]
    }
    requirement_results: list[Any] = []
    requirement_rows: list[dict[str, Any]] = []
    for node in nodes_by_type["Requirement"]:
        layer_constraints = {
            record_id for layer_id, record_id in known_constraints if layer_id == node["layer_id"]
        }
        result = service.map_requirement(
            node["record"],
            known_constraint_ids=layer_constraints,
            source_layer_id=node["layer_id"],
        )
        requirement_results.append(result)
        requirement_rows.append(_result_row("Requirement", node["record_id"], result, node["layer_id"]))

    representation_results = [
        service.map_representation_type(node["record"], source_layer_id=node["layer_id"])
        for node in nodes_by_type["RepresentationType"]
    ]
    relation_results = []
    for edge in graph["edges"]:
        relation_record = dict(edge)
        claim_revision_id = edge.get("provenance", {}).get("claim_revision_id")
        if claim_revision_id:
            claim_node = node_index.get(
                (edge["layer_id"], "AtomicClaimRevision", claim_revision_id)
            )
            if claim_node:
                relation_record["semantic_subject_id"] = claim_node["record"]["subject_id"]
                relation_record["semantic_object_id"] = claim_node["record"].get("object_id")
                relation_record["semantic_subject_type"] = record_type_by_identity.get(
                    (edge["layer_id"], claim_node["record"]["subject_id"])
                )
                relation_record["semantic_object_type"] = record_type_by_identity.get(
                    (edge["layer_id"], claim_node["record"].get("object_id", ""))
                )
        else:
            relation_record["semantic_subject_id"] = edge.get("source_record_id")
            relation_record["semantic_object_id"] = edge.get("target_record_id")
            source_node = node_by_graph_id.get(edge.get("source_graph_node_id", ""))
            target_node = node_by_graph_id.get(edge.get("target_graph_node_id", ""))
            relation_record["semantic_subject_type"] = (
                source_node["record_type"] if source_node else None
            )
            relation_record["semantic_object_type"] = (
                target_node["record_type"] if target_node else None
            )
        relation_results.append(
            service.classify_relation(
                relation_record,
                source_layer_id=edge["layer_id"],
                source_status=edge.get("status"),
            )
        )

    reference_bundle = ConformanceBundle.model_validate(_read_json(REFERENCE_FIXTURE))
    artifact = next(item for item in reference_bundle.entities if isinstance(item, ReferenceArtifact))
    revision = next(
        item for item in reference_bundle.entities if isinstance(item, ReferenceArtifactRevision)
    )
    reference_result = service.map_reference_resource(
        artifact, revision=revision, source_layer_id="v1_1_reference_qualification_fixture"
    )
    reference_requirement = next(
        requirement
        for entity in reference_bundle.entities
        if isinstance(entity, OperatorRevision)
        for port in entity.input_ports
        for requirement in port.requirements
        if requirement.reference_artifact_revision_ids
    )
    reference_requirement_result = service.map_requirement(
        reference_requirement,
        reference_revisions={revision.entity_id: reference_result},
        source_layer_id="v1_1_reference_qualification_fixture",
    )

    scope_statuses = _count_status(list(scope_results.values()))
    claim_statuses = _count_status(claim_results)
    span_statuses = _count_status(span_results)
    requirement_statuses = _count_status(requirement_results)
    predicate_classifications = Counter(
        result.view.predicate_classification
        for result in relation_results
        if result.view is not None
    )
    record_authorities = Counter(
        result.view.record_authority for result in relation_results if result.view is not None
    )
    mapping_summary = {
        "schema_version": "sckg-ontology-v2-compatibility-evaluation-v1",
        "ontology_version": "2.0.0-core-review.1",
        "source_inventory": str(GRAPH_PATH.relative_to(ROOT)),
        "inventory_record_mode": "all_physical_records_with_layer_provenance",
        "atomic_claims": {
            "inspected": len(claim_results),
            "status_counts": claim_statuses,
            "predicate_counts": dict(
                sorted(Counter(node["record"]["predicate"] for node in nodes_by_type["AtomicClaimRevision"]).items())
            ),
        },
        "evidence_spans": {
            "inspected": len(span_results),
            "status_counts": span_statuses,
            "core_views_exposed": sum(result.view is not None for result in span_results),
            "fully_compatible_views": span_statuses["DIRECT_COMPATIBLE"]
            + span_statuses["COMPATIBLE_WITH_ADAPTER"],
        },
        "evidence_assessments": {
            "inspected": len(assessment_results),
            "status_counts": _count_status(assessment_results),
            "views_exposed": sum(result.view is not None for result in assessment_results),
        },
        "scopes": {"inspected": len(scope_results), "status_counts": scope_statuses},
        "requirements": {
            "inspected": len(requirement_results),
            "status_counts": requirement_statuses,
        },
        "representations": {
            "inspected": len(representation_results),
            "status_counts": _count_status(representation_results),
        },
        "references": {
            "current_inventory_records": len(nodes_by_type["ReferenceArtifact"])
            + len(nodes_by_type["ReferenceArtifactRevision"]),
            "qualification_fixture_mappings": 1 if reference_result.view is not None else 0,
            "reference_only_requirement_qualified": reference_requirement_result.view is not None,
        },
        "relations": {
            "inspected": len(relation_results),
            "predicate_classification_counts": dict(sorted(predicate_classifications.items())),
            "record_authority_counts": dict(sorted(record_authorities.items())),
            "derived_relations_classified": predicate_classifications["DERIVED_PROJECTION"],
        },
        "interpretation": "Compatibility rate is structural mapping coverage, not scientific accuracy.",
    }
    compatibility_counts = {
        "schema_version": "sckg-ontology-v2-compatibility-counts-v1",
        "atomic_claim_revision_total_all": len(claim_results),
        **{key: claim_statuses[key] for key in claim_statuses},
        "evidence_spans_inspected": len(span_results),
        "evidence_core_views": sum(result.view is not None for result in span_results),
        "evidence_normalized_fully_compatible": span_statuses["DIRECT_COMPATIBLE"]
        + span_statuses["COMPATIBLE_WITH_ADAPTER"],
        "evidence_ambiguous": span_statuses["AMBIGUOUS_MAPPING"],
        "evidence_invalid": span_statuses["NOT_MAPPABLE"],
        "evidence_hash_rejected": sum(
            "EVIDENCE_TEXT_HASH_MISMATCH" in result.reason_codes for result in span_results
        ),
        "evidence_missing_artifact_id": sum(
            result.view is not None and result.view.source_artifact_id is None
            for result in span_results
        ),
        "evidence_missing_revision_id": sum(
            result.view is not None and result.view.source_revision_id is None
            for result in span_results
        ),
        "evidence_assessments_inspected": len(assessment_results),
        "evidence_assessment_views": sum(result.view is not None for result in assessment_results),
        "scope_mappings": sum(result.view is not None for result in scope_results.values()),
        "requirement_mappings": sum(result.view is not None for result in requirement_results),
        "reference_mappings": 1 if reference_result.view is not None else 0,
        "derived_relations_classified": predicate_classifications["DERIVED_PROJECTION"],
    }
    unresolved = sorted(
        [
            row
            for row in claim_rows + span_rows + assessment_rows + requirement_rows
            if row["status"] in {"AMBIGUOUS_MAPPING", "NOT_MAPPABLE", "DEFERRED"}
        ]
        + [
            _result_row("ApplicabilityScope", source_id, result, layer_id)
            for (layer_id, source_id), result in scope_results.items()
            if result.status in {"AMBIGUOUS_MAPPING", "NOT_MAPPABLE", "DEFERRED"}
        ],
        key=lambda row: (row["category"], row["layer_id"], row["source_id"]),
    )
    unresolved_payload = {
        "schema_version": "sckg-ontology-v2-unresolved-mappings-v1",
        "count": len(unresolved),
        "mappings": unresolved,
    }

    frozen_hashes = {
        path.name: _sha256(path)
        for path in sorted(FROZEN_CORE_DIR.iterdir())
        if path.is_file()
    }
    integrity = {
        "schema_version": "sckg-ontology-v2-compatibility-integrity-v1",
        "authoritative_base_commit": AUTHORITATIVE_BASE_COMMIT,
        "compatibility_patch_base_commit": PATCH_BASE_COMMIT,
        "frozen_ontology_version": "2.0.0-core-review.1",
        "frozen_core_artifact_hashes": frozen_hashes,
        "source_inventory": {
            "path": str(GRAPH_PATH.relative_to(ROOT)),
            "sha256": _sha256(GRAPH_PATH),
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
        },
        "reference_qualification_fixture": {
            "path": str(REFERENCE_FIXTURE.relative_to(ROOT)),
            "sha256": _sha256(REFERENCE_FIXTURE),
        },
        "read_only": True,
        "migration_performed": False,
        "scientific_kg_changed": False,
        "catalog_kg_changed": False,
        "rag_changed": False,
        "planner_changed": False,
        "production_ontology_changed": False,
        "automatic_production_wiring": False,
    }
    test_summary = {
        "schema_version": "sckg-ontology-v2-compatibility-test-summary-v1",
        "focused_tests": focused_result.model_dump(mode="json"),
        "regression_tests": regression_result.model_dump(mode="json"),
        "chat_import": "PASS" if regression_result.status == "PASS" else "UNVERIFIED",
        "chat_runtime": "PASS" if regression_result.status == "PASS" else "UNVERIFIED",
        "chat_retrieval": "PASS" if regression_result.status == "PASS" else "UNVERIFIED",
        "chat_planner": "PASS" if regression_result.status == "PASS" else "UNVERIFIED",
    }

    for name, payload in (
        ("mapping_summary.json", mapping_summary),
        ("compatibility_counts.json", compatibility_counts),
        ("unresolved_mappings.json", unresolved_payload),
        ("integrity.json", integrity),
        ("test_summary.json", test_summary),
    ):
        _write_json(output_dir / name, payload)

    artifacts = {name: _sha256(output_dir / name) for name in OUTPUT_NAMES}
    manifest = {
        "schema_version": "sckg-ontology-v2-compatibility-manifest-v1",
        "checkpoint": "5E.1-Compatibility-Safety-Patch",
        "status": (
            "PASS"
            if focused_result.status == "PASS" and regression_result.status == "PASS"
            else "NEEDS_VERIFICATION"
        ),
        "base_commit": PATCH_BASE_COMMIT,
        "accepted_ontology_commit": AUTHORITATIVE_BASE_COMMIT,
        "branch": "feature/ontology-v2-compat-v1",
        "artifacts": artifacts,
        "read_only": True,
        "fail_closed": True,
        "deterministic": True,
        "non_destructive": True,
        "scientific_content_generated": False,
        "next_recommended_action": "STOP_FOR_QA_RECHECK",
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    for prefix in ("focused", "regression"):
        parser.add_argument(
            f"--{prefix}-status",
            choices=("PASS", "FAIL", "NOT_RUN", "UNVERIFIED"),
            default="NOT_RUN",
        )
        parser.add_argument(f"--{prefix}-passed", type=int, default=0)
        parser.add_argument(f"--{prefix}-failed", type=int, default=0)
        parser.add_argument(f"--{prefix}-errors", type=int, default=0)
        parser.add_argument(f"--{prefix}-skipped", type=int, default=0)
        parser.add_argument(f"--{prefix}-command", action="append", default=[])
        parser.add_argument(f"--{prefix}-evidence")
    args = parser.parse_args()
    build(
        args.output_dir,
        focused_tests={
            "status": args.focused_status,
            "passed": args.focused_passed,
            "failed": args.focused_failed,
            "errors": args.focused_errors,
            "skipped": args.focused_skipped,
            "command": args.focused_command,
            "evidence": args.focused_evidence,
        },
        regression_tests={
            "status": args.regression_status,
            "passed": args.regression_passed,
            "failed": args.regression_failed,
            "errors": args.regression_errors,
            "skipped": args.regression_skipped,
            "command": args.regression_command,
            "evidence": args.regression_evidence,
        },
    )


if __name__ == "__main__":
    main()
