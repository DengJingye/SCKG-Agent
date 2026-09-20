from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from eval.ontology_v2_test_evidence import SCHEMA_VERSION as TEST_RESULT_SCHEMA_VERSION
from eval.ontology_v2_test_evidence import parse_junit, sha256_file


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
PATCH_BASE_COMMIT = "392c5d9c0b2140abdaf5b952f7fce1cee29f4554"
FOCUSED_SUITE_ID = "ontology-v2-compatibility-focused-5e2"
REGRESSION_SUITE_ID = "ontology-v2-compatibility-bounded-regression-5e2"
FOCUSED_REQUIRED_NODES = {
    "tests/test_scientific_ontology_v2_compatibility.py::test_h01_missing_expected_scope_is_ambiguous_and_exact_scope_succeeds",
    "tests/test_scientific_ontology_v2_compatibility.py::test_h02_atomic_claim_retains_distinct_inline_flavors_end_to_end",
    "tests/test_scientific_ontology_v2_compatibility.py::test_h02_atomic_claim_deduplicates_or_rejects_same_dimension_inline_context",
    "tests/test_scientific_ontology_v2_compatibility.py::test_h02_atomic_claim_preserves_any_of_plus_inline_and_serialization",
    "tests/test_scientific_ontology_v2_compatibility.py::test_h03_candidate_authoritative_predicate_remains_candidate_record",
    "tests/test_scientific_ontology_v2_compatibility.py::test_h03_wrong_domain_authoritative_predicate_is_unresolved",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m01_entity_predicate_and_typed_scalar_property_constraints",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m01_disallowed_qualifier_is_reported_not_dropped",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m02_all_requirement_views_use_requirement_identity",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m02_all_derived_relation_views_retain_exact_edge_identity",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m03_evidence_core_view_excludes_governance_status",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m04_evidence_binding_rejects_key_to_wrong_span_object",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m04_two_assessments_for_one_statement_are_collected_independently",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m04_support_and_refutation_coexist_without_trust_aggregation",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m05_failed_not_run_and_unverified_declarations_cannot_emit_pass",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m05_false_command_failed_text_and_missing_artifact_are_unverified",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m05_wrong_hash_revision_counts_suite_and_tamper_are_unverified",
    "tests/test_scientific_ontology_v2_compatibility.py::test_m05_verified_artifacts_gate_checkpoint_and_chat_surfaces",
}
CHAT_SURFACE_NODES = {
    "chat_import": {
        "tests/test_research_shell.py::test_chat_rerun_emits_theme_first_without_hidden_image_or_workbench"
    },
    "chat_runtime": {
        "tests/test_research_agent_entrypoint.py::test_ask_mode_answers_without_compiling_or_handoff"
    },
    "chat_retrieval": {
        "tests/test_research_chat_service.py::test_research_chat_answers_without_langgraph_dense_or_neo4j"
    },
    "chat_planner": {
        "tests/test_research_agent_entrypoint.py::test_run_mode_without_registered_data_waits_and_never_executes"
    },
}
REGRESSION_REQUIRED_NODES = set().union(*CHAT_SURFACE_NODES.values()) | {
    "tests/test_research_shell.py::test_chat_rerun_emits_theme_first_without_hidden_image_or_workbench",
    "tests/test_hybrid_retrieval_v2.py::test_fts5_bm25_prefers_source_bound_chunk_and_dense_falls_back",
    "tests/test_hybrid_retrieval_v2.py::test_index_is_reused_without_reparsing_jsonl",
    "tests/test_capability_workspace_service.py::test_workspace_minimal_scanpy_plan_is_registry_driven_and_never_executes",
    "tests/test_scientific_kg_evidence_retrieval_v1.py::test_research_product_evidence_entry_and_frozen_integrity",
    "tests/test_representation_ledger.py::test_profiler_records_coexisting_anndata_states_without_mutation",
    "tests/test_tool_contracts.py::test_scrublet_contract_is_qualified_for_restricted_execution_policy",
    "tests/test_scientific_kg_admin_workspace_readonly_v1.py::test_scientific_kg_counts_and_governance_match_frozen_snapshot",
    "tests/test_scientific_knowledge_studio_v1.py::test_01_source_revision_proposal_schema_is_candidate_only",
}


class TestExecutionDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["PASS", "FAIL", "NOT_RUN", "UNVERIFIED"]
    suite_id: str | None = None
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    command: tuple[str, ...] = ()
    tested_revision: str | None = None
    result_artifact: str | None = None
    result_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _validated_test_declaration(
    value: TestExecutionDeclaration | Mapping[str, Any] | str | None,
) -> tuple[TestExecutionDeclaration, tuple[str, ...]]:
    if isinstance(value, TestExecutionDeclaration):
        return value, ()
    if value is None or (isinstance(value, str) and value.casefold() in {"not_run", "not run"}):
        return TestExecutionDeclaration(status="NOT_RUN"), ()
    if isinstance(value, str):
        if value.strip().upper() in {"FAIL", "FAILED", "FAILURE"}:
            return TestExecutionDeclaration(
                status="FAIL",
                failed=1,
            ), ()
        return TestExecutionDeclaration(status="UNVERIFIED"), (
            "UNSTRUCTURED_TEST_DECLARATION",
        )
    try:
        return TestExecutionDeclaration.model_validate(value), ()
    except ValidationError as exc:
        return TestExecutionDeclaration(status="UNVERIFIED"), (
            f"INVALID_TEST_DECLARATION:{exc.errors()[0]['type']}",
        )


def _safe_artifact_path(evidence_root: Path, relative_path: str) -> Path | None:
    root = evidence_root.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _verification_payload(
    declaration: TestExecutionDeclaration,
    *,
    verification_status: Literal["PASS", "FAIL", "UNVERIFIED"],
    reasons: list[str],
    verified_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = declaration.model_dump(mode="json")
    payload["declared_status"] = payload.pop("status")
    payload["verification_status"] = verification_status
    payload["verification_reason_codes"] = reasons
    payload["verified_node_ids"] = verified_node_ids or []
    return payload


def verify_test_evidence(
    declaration: TestExecutionDeclaration,
    *,
    declaration_errors: tuple[str, ...] = (),
    expected_suite_id: str,
    expected_revision: str,
    evidence_root: Path,
    required_node_ids: set[str],
) -> dict[str, Any]:
    if declaration_errors:
        return _verification_payload(
            declaration,
            verification_status="UNVERIFIED",
            reasons=list(declaration_errors),
        )
    if declaration.status == "FAIL":
        return _verification_payload(
            declaration,
            verification_status="FAIL",
            reasons=["DECLARED_TEST_FAILURE"],
        )
    if declaration.status != "PASS":
        return _verification_payload(
            declaration,
            verification_status="UNVERIFIED",
            reasons=[f"DECLARED_{declaration.status}"],
        )

    reasons: list[str] = []
    if declaration.passed < 1:
        reasons.append("NO_PASSED_TESTS")
    if declaration.failed or declaration.errors:
        reasons.append("DECLARED_FAILURES_OR_ERRORS")
    if not declaration.command:
        reasons.append("COMMAND_PROVENANCE_MISSING")
    elif not any("pytest" in part for part in declaration.command):
        reasons.append("COMMAND_IS_NOT_BOUNDED_PYTEST")
    if declaration.suite_id != expected_suite_id:
        reasons.append("DECLARED_SUITE_ID_MISMATCH")
    if declaration.tested_revision != expected_revision:
        reasons.append("DECLARED_TESTED_REVISION_MISMATCH")
    if not declaration.result_artifact or not declaration.result_artifact_sha256:
        reasons.append("RESULT_ARTIFACT_REFERENCE_MISSING")
    if reasons:
        return _verification_payload(
            declaration, verification_status="UNVERIFIED", reasons=reasons
        )

    artifact_path = _safe_artifact_path(evidence_root, declaration.result_artifact)
    if artifact_path is None:
        reasons.append("RESULT_ARTIFACT_OUTSIDE_EVIDENCE_ROOT")
    elif not artifact_path.is_file():
        reasons.append("RESULT_ARTIFACT_NOT_FOUND")
    elif sha256_file(artifact_path) != declaration.result_artifact_sha256:
        reasons.append("RESULT_ARTIFACT_SHA256_MISMATCH")
    if reasons:
        return _verification_payload(
            declaration, verification_status="UNVERIFIED", reasons=reasons
        )

    try:
        result = _read_json(artifact_path)
    except (OSError, json.JSONDecodeError):
        return _verification_payload(
            declaration,
            verification_status="UNVERIFIED",
            reasons=["RESULT_ARTIFACT_INVALID_JSON"],
        )
    expected_fields = {
        "schema_version": TEST_RESULT_SCHEMA_VERSION,
        "suite_id": expected_suite_id,
        "tested_revision": expected_revision,
        "passed": declaration.passed,
        "failed": declaration.failed,
        "errors": declaration.errors,
        "skipped": declaration.skipped,
        "command": list(declaration.command),
    }
    for key, expected in expected_fields.items():
        if result.get(key) != expected:
            reasons.append(f"RESULT_ARTIFACT_{key.upper()}_MISMATCH")
    if result.get("status") != "PASS":
        reasons.append("RESULT_ARTIFACT_NOT_PASS")
    junit_ref = result.get("junit_artifact")
    junit_sha = result.get("junit_artifact_sha256")
    if not isinstance(junit_ref, str) or not isinstance(junit_sha, str):
        reasons.append("JUNIT_REFERENCE_MISSING")
    if reasons:
        verification_status: Literal["FAIL", "UNVERIFIED"] = (
            "FAIL" if "RESULT_ARTIFACT_NOT_PASS" in reasons else "UNVERIFIED"
        )
        return _verification_payload(
            declaration, verification_status=verification_status, reasons=reasons
        )

    junit_path = _safe_artifact_path(evidence_root, junit_ref)
    if junit_path is None:
        reasons.append("JUNIT_ARTIFACT_OUTSIDE_EVIDENCE_ROOT")
    elif not junit_path.is_file():
        reasons.append("JUNIT_ARTIFACT_NOT_FOUND")
    elif sha256_file(junit_path) != junit_sha:
        reasons.append("JUNIT_ARTIFACT_SHA256_MISMATCH")
    if reasons:
        return _verification_payload(
            declaration, verification_status="UNVERIFIED", reasons=reasons
        )
    try:
        parsed_junit = parse_junit(junit_path)
    except (OSError, ET.ParseError, ValueError):
        return _verification_payload(
            declaration,
            verification_status="UNVERIFIED",
            reasons=["JUNIT_ARTIFACT_INVALID"],
        )
    for key in ("status", "passed", "failed", "errors", "skipped", "test_node_ids"):
        if result.get(key) != parsed_junit.get(key):
            reasons.append(f"JUNIT_{key.upper()}_MISMATCH")
    missing_required_nodes = sorted(required_node_ids - set(parsed_junit["test_node_ids"]))
    if missing_required_nodes:
        reasons.append("REQUIRED_TEST_NODES_MISSING")
    if reasons:
        return _verification_payload(
            declaration, verification_status="UNVERIFIED", reasons=reasons
        )
    return _verification_payload(
        declaration,
        verification_status="PASS",
        reasons=["RESULT_AND_JUNIT_ARTIFACTS_VERIFIED"],
        verified_node_ids=parsed_junit["test_node_ids"],
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
    focused_tests: TestExecutionDeclaration | Mapping[str, Any] | str | None = None,
    regression_tests: TestExecutionDeclaration | Mapping[str, Any] | str | None = None,
    evaluated_revision: str = PATCH_BASE_COMMIT,
    evidence_root: Path = ROOT,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    service = ScientificOntologyV2CompatibilityService(ROOT)
    graph = _read_json(GRAPH_PATH)
    focused_declaration, focused_errors = _validated_test_declaration(focused_tests)
    regression_declaration, regression_errors = _validated_test_declaration(regression_tests)
    focused_result = verify_test_evidence(
        focused_declaration,
        declaration_errors=focused_errors,
        expected_suite_id=FOCUSED_SUITE_ID,
        expected_revision=evaluated_revision,
        evidence_root=evidence_root,
        required_node_ids=FOCUSED_REQUIRED_NODES,
    )
    regression_result = verify_test_evidence(
        regression_declaration,
        declaration_errors=regression_errors,
        expected_suite_id=REGRESSION_SUITE_ID,
        expected_revision=evaluated_revision,
        evidence_root=evidence_root,
        required_node_ids=REGRESSION_REQUIRED_NODES,
    )

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
    predicate_record_authorities = Counter(
        (result.view.predicate_classification, result.view.record_authority)
        for result in relation_results
        if result.view is not None
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
            "predicate_record_authority_counts": {
                f"{predicate} + {authority}": count
                for (predicate, authority), count in sorted(predicate_record_authorities.items())
            },
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
        "evaluated_revision": evaluated_revision,
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
        "schema_version": "sckg-ontology-v2-compatibility-test-summary-v2",
        "evaluated_revision": evaluated_revision,
        "focused_tests": focused_result,
        "regression_tests": regression_result,
    }
    verified_regression_nodes = set(regression_result["verified_node_ids"])
    for surface, required_nodes in CHAT_SURFACE_NODES.items():
        test_summary[surface] = (
            "PASS"
            if regression_result["verification_status"] == "PASS"
            and required_nodes <= verified_regression_nodes
            else "UNVERIFIED"
        )

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
        "checkpoint": "5E.2-Final-Compatibility-Closure",
        "status": (
            "PASS"
            if focused_result["verification_status"] == "PASS"
            and regression_result["verification_status"] == "PASS"
            else "NEEDS_VERIFICATION"
        ),
        "base_commit": PATCH_BASE_COMMIT,
        "evaluated_revision": evaluated_revision,
        "accepted_ontology_commit": AUTHORITATIVE_BASE_COMMIT,
        "branch": "feature/ontology-v2-compat-v1",
        "artifacts": artifacts,
        "read_only": True,
        "fail_closed": True,
        "deterministic": True,
        "non_destructive": True,
        "scientific_content_generated": False,
        "next_recommended_action": "STOP_FOR_FINAL_QA",
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--evaluated-revision", default=PATCH_BASE_COMMIT)
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
        parser.add_argument(f"--{prefix}-suite-id")
        parser.add_argument(f"--{prefix}-tested-revision")
        parser.add_argument(f"--{prefix}-result-artifact")
        parser.add_argument(f"--{prefix}-result-artifact-sha256")
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
            "suite_id": args.focused_suite_id,
            "tested_revision": args.focused_tested_revision,
            "result_artifact": args.focused_result_artifact,
            "result_artifact_sha256": args.focused_result_artifact_sha256,
        },
        regression_tests={
            "status": args.regression_status,
            "passed": args.regression_passed,
            "failed": args.regression_failed,
            "errors": args.regression_errors,
            "skipped": args.regression_skipped,
            "command": args.regression_command,
            "suite_id": args.regression_suite_id,
            "tested_revision": args.regression_tested_revision,
            "result_artifact": args.regression_result_artifact,
            "result_artifact_sha256": args.regression_result_artifact_sha256,
        },
        evaluated_revision=args.evaluated_revision,
    )


if __name__ == "__main__":
    main()
