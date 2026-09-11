from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.scientific_knowledge_conformance_models import (
    ConformanceBundle,
    Limitation,
    OperatorRevision,
    ParameterDefinition,
)
from data_pipeline.build_scientific_kg_v1_core import DEFAULT_OUTPUT_DIR, ECOSYSTEMS, build
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(path: Path = DEFAULT_OUTPUT_DIR) -> ConformanceBundle:
    return ConformanceBundle.model_validate(_json(path / "conformance_bundle.json"))


def test_build_is_deterministic_and_has_no_canonical_or_runtime_side_effect(tmp_path: Path) -> None:
    before = {path: _sha(path) for path in CANONICAL_PATHS if path.exists()}
    generated = build(tmp_path)
    frozen = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert generated["artifacts"] == frozen["artifacts"]
    assert generated["canonical_before"] == generated["canonical_after"]
    assert generated["canonical_kg_modified"] is False
    assert generated["retrieval_index_rebuilt"] is False
    assert generated["runtime_modified"] is False
    assert {path: _sha(path) for path in CANONICAL_PATHS if path.exists()} == before
    for name in generated["artifacts"]:
        assert (tmp_path / name).read_bytes() == (DEFAULT_OUTPUT_DIR / name).read_bytes()


def test_frozen_scope_contains_exactly_fourteen_ecosystems_and_three_domains() -> None:
    matrix = _json(DEFAULT_OUTPUT_DIR / "readiness_matrix.json")

    assert set(ECOSYSTEMS) == {
        "scanpy", "seurat", "harmony", "scvi_tools", "scrublet", "soupx",
        "celltypist", "singler", "edger", "slingshot", "scvelo", "cellrank",
        "mofa2", "pyscenic",
    }
    assert len(matrix["rows"]) == 14
    assert set(matrix["domains"]) == {
        "foundation_integration_annotation",
        "statistical_design_trajectory",
        "multiomics_regulatory",
    }


def test_every_operator_is_version_pinned_and_has_canonical_ports() -> None:
    bundle = _bundle()
    revisions = [item for item in bundle.entities if isinstance(item, OperatorRevision)]
    release_ids = {item.entity_id for item in bundle.entities if item.record_type == "PackageRelease"}

    assert len(revisions) == 44
    assert all(item.package_release_id in release_ids for item in revisions)
    assert all(item.input_ports and item.output_ports for item in revisions)
    assert all(port.requirements for item in revisions for port in item.input_ports)
    assert all(port.lineage_input_port_ids for item in revisions for port in item.output_ports)
    assert all(not item.contract_refs for item in revisions)


def test_parameter_and_limitation_claim_endpoints_are_typed_and_resolvable() -> None:
    bundle = _bundle()
    entity_ids = {item.entity_id for item in bundle.entities}
    parameters = [item for item in bundle.entities if isinstance(item, ParameterDefinition)]
    limitations = [item for item in bundle.entities if isinstance(item, Limitation)]

    assert len(parameters) == 17
    assert len(limitations) == 13
    assert all(item.owner_operator_id in entity_ids for item in parameters)
    assert all(
        claim.object_id in entity_ids
        for claim in bundle.atomic_claims
        if claim.predicate in {"has_key_parameter", "has_limitation"}
    )


def test_all_claims_have_source_bound_assessment_hash_scope_and_risk() -> None:
    bundle = _bundle()
    spans = {row["evidence_span_id"]: row for row in _jsonl(DEFAULT_OUTPUT_DIR / "evidence_spans.jsonl")}
    assessments = {item.claim_revision_id: item for item in bundle.evidence_assessments}
    risks = {row["record_id"]: row for row in _jsonl(DEFAULT_OUTPUT_DIR / "risk_registry.jsonl")}
    scope_ids = {scope.scope_id for scope in bundle.scopes}

    assert len(bundle.atomic_claims) == 236
    assert set(assessments) == {claim.claim_revision_id for claim in bundle.atomic_claims}
    assert all(claim.scope_id in scope_ids for claim in bundle.atomic_claims)
    assert all(claim.content_hash == hashlib.sha256(claim.claim_text.encode()).hexdigest() for claim in bundle.atomic_claims)
    assert all(set(assessment.evidence_span_ids) <= set(spans) for assessment in assessments.values())
    assert all(spans[span_id]["source_bound"] is True for assessment in assessments.values() for span_id in assessment.evidence_span_ids)
    assert {claim.claim_revision_id for claim in bundle.atomic_claims} <= set(risks)


def test_sources_include_official_versioned_docs_and_primary_method_papers() -> None:
    sources = _json(DEFAULT_OUTPUT_DIR / "source_manifest.json")["sources"]
    source_types = [source["source_type"] for source in sources]

    assert source_types.count("official_api_or_package_documentation") == 14
    assert source_types.count("primary_method_paper") == 13
    assert all(source["source_uri"].startswith("https://") for source in sources)
    assert all(source["candidate_only"] is True for source in sources)


def test_derived_relations_are_port_projections_or_reviewed_exact_compatibility() -> None:
    bundle = _bundle()
    risks = {row["record_id"] for row in _jsonl(DEFAULT_OUTPUT_DIR / "risk_registry.jsonl")}

    assert all(
        relation.derivation_type == "port_projection"
        for relation in bundle.derived_relations
        if relation.relation in {"CONSUMES", "PRODUCES"}
    )
    assert all(
        relation.derivation_type == "reviewed_rule" and relation.premise_relation_ids
        for relation in bundle.derived_relations
        if relation.relation == "CAN_FEED"
    )
    assert not any(relation.relation == "REQUIRES_BEFORE" for relation in bundle.derived_relations)
    assert {relation.relation_id for relation in bundle.derived_relations} <= risks


def test_high_impact_unknowns_are_explicit_gaps_not_silent_facts() -> None:
    gaps = _json(DEFAULT_OUTPUT_DIR / "evidence_gaps.json")["gaps"]

    assert {gap["gap_id"] for gap in gaps} == {
        "evidence-gap:v1-core:celltypist:model-revision",
        "evidence-gap:v1-core:pyscenic:database-revisions",
        "evidence-gap:v1-core:soupx:droplet-profile",
        "evidence-gap:v1-core:scvi:trained-model-artifact",
        "evidence-gap:v1-core:mofa2:feature-weights",
    }
    assert all(gap["candidate_only"] is True for gap in gaps)
    assert all(gap["required_source"] for gap in gaps)


def test_semantic_quality_gates_are_real_and_candidate_promotion_is_disabled() -> None:
    report = _json(DEFAULT_OUTPUT_DIR / "semantic_quality_report.json")
    matrix = _json(DEFAULT_OUTPUT_DIR / "readiness_matrix.json")

    assert all(check["passed"] is True for check in report["checks"].values())
    assert report["promotion"] == {
        "eligible_now": False,
        "performed": False,
        "reason": "All knowledge remains candidate-only and risk-appropriate human review has not occurred.",
    }
    assert not any(row["scientific_promotion_status"] == "promoted" for row in matrix["rows"])
    assert {row["ecosystem"] for row in matrix["rows"]} == {meta["label"] for meta in ECOSYSTEMS.values()}
