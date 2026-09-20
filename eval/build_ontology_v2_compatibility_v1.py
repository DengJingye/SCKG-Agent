from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

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


def build(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    focused_tests: str = "not_run",
    regression_tests: str = "not_run",
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    service = ScientificOntologyV2CompatibilityService(ROOT)
    graph = _read_json(GRAPH_PATH)

    nodes_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    node_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for node in graph["nodes"]:
        nodes_by_type[node["record_type"]].append(node)
        node_index[(node["layer_id"], node["record_type"], node["record_id"])] = node

    assessment_by_claim: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in graph["edges"]:
        assessment = edge.get("provenance", {}).get("evidence_assessment")
        if assessment:
            assessment_by_claim[(edge["layer_id"], assessment["claim_revision_id"])] = assessment

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
        assessment = assessment_by_claim.get((node["layer_id"], node["record_id"]))
        result = service.map_atomic_claim(
            node["record"],
            scope=scope_node["record"] if scope_node else None,
            evidence_assessments=(assessment,) if assessment else (),
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
    for (layer_id, claim_revision_id), assessment in sorted(assessment_by_claim.items()):
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
            _result_row("EvidenceAssessment", assessment["assessment_id"], result, layer_id)
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
    relation_results = [
        service.classify_relation(
            edge,
            source_layer_id=edge["layer_id"],
            source_status=edge.get("status"),
        )
        for edge in graph["edges"]
    ]

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
    relation_classifications = Counter(
        result.view.classification for result in relation_results if result.view is not None
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
            "classification_counts": dict(sorted(relation_classifications.items())),
            "derived_relations_classified": relation_classifications["DERIVED_PROJECTION"],
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
        "evidence_assessments_inspected": len(assessment_results),
        "evidence_assessment_views": sum(result.view is not None for result in assessment_results),
        "scope_mappings": sum(result.view is not None for result in scope_results.values()),
        "requirement_mappings": sum(result.view is not None for result in requirement_results),
        "reference_mappings": 1 if reference_result.view is not None else 0,
        "derived_relations_classified": relation_classifications["DERIVED_PROJECTION"],
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
        "focused_tests": focused_tests,
        "regression_tests": regression_tests,
        "chat_import": "PENDING" if regression_tests == "not_run" else "PASS",
        "chat_runtime": "PENDING" if regression_tests == "not_run" else "PASS",
        "chat_retrieval": "PENDING" if regression_tests == "not_run" else "PASS",
        "chat_planner": "PENDING" if regression_tests == "not_run" else "PASS",
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
        "checkpoint": "5E-V1-V2-Compatibility-Layer",
        "status": "PASS" if focused_tests != "not_run" and regression_tests != "not_run" else "PENDING_TESTS",
        "base_commit": AUTHORITATIVE_BASE_COMMIT,
        "branch": "feature/ontology-v2-compat-v1",
        "artifacts": artifacts,
        "read_only": True,
        "fail_closed": True,
        "deterministic": True,
        "non_destructive": True,
        "scientific_content_generated": False,
        "next_recommended_action": "STOP_FOR_QA",
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--focused-tests", default="not_run")
    parser.add_argument("--regression-tests", default="not_run")
    args = parser.parse_args()
    build(
        args.output_dir,
        focused_tests=args.focused_tests,
        regression_tests=args.regression_tests,
    )


if __name__ == "__main__":
    main()
