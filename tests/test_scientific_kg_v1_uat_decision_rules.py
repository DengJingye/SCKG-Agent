from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from core.scientific_knowledge_conformance_models import ConformanceBundle, OperatorRevision
from data_pipeline.build_scientific_kg_v1_uat_decision_rules import (
    DEFAULT_OUTPUT_DIR,
    FROZEN_CORE_DIR,
    build,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(path: Path = DEFAULT_OUTPUT_DIR) -> ConformanceBundle:
    return ConformanceBundle.model_validate(_json(path / "conformance_bundle.json"))


def _revisions() -> dict[str, OperatorRevision]:
    return {
        item.operator_id: item
        for item in _bundle().entities
        if isinstance(item, OperatorRevision)
    }


def test_build_is_deterministic_candidate_only_and_does_not_touch_frozen_or_canonical(tmp_path: Path) -> None:
    canonical_before = {path: _sha(path) for path in CANONICAL_PATHS if path.exists()}
    frozen_before = {path.name: _sha(path) for path in FROZEN_CORE_DIR.iterdir() if path.is_file()}

    generated = build(tmp_path)
    frozen = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert generated["artifacts"] == frozen["artifacts"]
    assert generated["status"] == "candidate_only_not_promoted"
    assert generated["base_commit"] == "22489bd12ea0d0259dcf4c30ab74f4c8e209bf17"
    assert generated["canonical_kg_modified"] is False
    assert generated["frozen_core_modified"] is False
    assert generated["retrieval_index_rebuilt"] is False
    assert generated["runtime_modified"] is False
    assert {path: _sha(path) for path in CANONICAL_PATHS if path.exists()} == canonical_before
    assert {path.name: _sha(path) for path in FROZEN_CORE_DIR.iterdir() if path.is_file()} == frozen_before
    for name in generated["artifacts"]:
        assert (tmp_path / name).read_bytes() == (DEFAULT_OUTPUT_DIR / name).read_bytes()


def test_slice_contains_only_the_eight_adjudicated_operator_revisions() -> None:
    revisions = _revisions()

    assert set(revisions) == {
        "operator:scanpy.pp.highly_variable_genes",
        "operator:scanpy.pp.pca",
        "operator:scanpy.pp.neighbors",
        "operator:scanpy.tl.umap",
        "operator:scanpy.tl.leiden",
        "operator:harmony.RunHarmony",
        "operator:scrublet.Scrublet.scrub_doublets",
        "operator:SingleR::SingleR",
    }
    assert len(revisions) == 8


def test_hvg_requirements_branch_on_flavor_without_cross_acceptance() -> None:
    revision = _revisions()["operator:scanpy.pp.highly_variable_genes"]
    port = revision.input_ports[0]
    constraints = {item.constraint_id: item for item in _bundle().representation_constraints}

    assert port.requirement_combination == "any_of"
    assert {item.level for item in port.requirements} == {"conditional"}
    branches = {
        value
        for requirement in port.requirements
        for condition in requirement.when
        for value in condition.values
    }
    assert branches == {"seurat", "cell_ranger", "seurat_v3", "seurat_v3_paper"}
    assert constraints["representation-constraint:uat:hvg-log"].required_transformations == ["log1p"]
    assert set(constraints["representation-constraint:uat:hvg-counts"].forbidden_transformations) == {
        "normalized", "log1p", "scaled", "integrated"
    }


def test_pca_upstream_fact_is_generic_and_scaled_hvg_is_project_profile_only() -> None:
    bundle = _bundle()
    revision = _revisions()["operator:scanpy.pp.pca"]
    profile_claim = next(item for item in bundle.atomic_claims if item.claim_id == "claim:uat:pca-project-profile")
    universal_claims = [item for item in bundle.atomic_claims if item.subject_id == revision.entity_id]

    assert revision.input_ports[0].requirements[0].representation_constraint_ids == [
        "representation-constraint:uat:pca-expression"
    ]
    assert revision.input_ports[1].min_cardinality == 0
    assert revision.input_ports[1].requirements[0].level == "optional"
    assert profile_claim.subject_id == "method-variant:pca.sckg-scaled-hvg-profile"
    assert profile_claim.scope_id == "scope:uat:profile:scanpy-pca-scaled-hvg:1.0.0"
    assert profile_claim.object_id == "representation-constraint:uat:pca-profile-scaled-hvg"
    assert all("scaled HVG" not in item.claim_text for item in universal_claims)


def test_neighbors_accepts_x_pca_or_governed_obsm_with_representation_specific_reuse_checks() -> None:
    bundle = _bundle()
    revision = _revisions()["operator:scanpy.pp.neighbors"]
    port = revision.input_ports[0]
    constraints = {
        item.constraint_id: item
        for item in bundle.representation_constraints
        if item.constraint_id.startswith("representation-constraint:uat:neighbors-")
    }

    assert port.requirement_combination == "any_of"
    assert {item.representation_type_id for item in constraints.values()} == {
        "representation-type:expression_matrix",
        "representation-type:pca_coordinates",
        "representation-type:cell_embedding",
    }
    assert "ordered_feature_ids" in constraints["representation-constraint:uat:neighbors-x"].required_metadata
    assert "ordered_feature_ids" not in constraints["representation-constraint:uat:neighbors-pca"].required_metadata
    assert "ordered_feature_ids" not in constraints["representation-constraint:uat:neighbors-embedding"].required_metadata
    assert all("fresh" in item.required_value_states for item in constraints.values())
    assert all("lineage_id" in item.required_metadata for item in constraints.values())
    assert all("semantic_parameter_signature" in item.required_metadata for item in constraints.values())


def test_umap_and_leiden_use_real_graph_components_and_leiden_does_not_require_umap() -> None:
    bundle = _bundle()
    constraints = {item.constraint_id: item for item in bundle.representation_constraints}
    umap = _revisions()["operator:scanpy.tl.umap"]
    leiden = _revisions()["operator:scanpy.tl.leiden"]

    umap_constraint = constraints["representation-constraint:uat:neighbor-graph-reuse"]
    assert set(umap_constraint.required_component_roles) == {"connectivities", "distances", "parameters"}
    assert {"neighbors_key", "connectivities_key", "distances_key"} <= set(umap_constraint.required_metadata)
    assert leiden.input_ports[0].requirement_combination == "any_of"
    assert {constraint_id for req in leiden.input_ports[0].requirements for constraint_id in req.representation_constraint_ids} == {
        "representation-constraint:uat:leiden-neighbor-graph",
        "representation-constraint:uat:leiden-adjacency",
    }
    assert all("umap" not in req.requirement_id for req in leiden.input_ports[0].requirements)
    assert not any(item.relation == "REQUIRES_BEFORE" for item in bundle.derived_relations)


def test_harmony_interfaces_are_distinct_and_output_is_embedding_only() -> None:
    revision = _revisions()["operator:harmony.RunHarmony"]
    bundle = _bundle()
    constraints = {item.constraint_id: item for item in bundle.representation_constraints}

    assert set(revision.implements_method_variant_ids) == {
        "method-variant:harmony.pca-default",
        "method-variant:harmony.generic-embedding",
    }
    assert revision.input_ports[0].requirement_combination == "any_of"
    assert constraints["representation-constraint:uat:harmony-pca"].representation_type_id == "representation-type:pca_coordinates"
    assert constraints["representation-constraint:uat:harmony-generic"].representation_type_id == "representation-type:cell_embedding"
    assert revision.output_ports[0].representation_type_id == "representation-type:cell_embedding"
    assert "batch_corrected_embedding" in revision.output_ports[0].transforms
    assert all("count" not in item for item in revision.output_ports[0].transforms)


def test_scrublet_requires_preserved_raw_counts_and_records_review_guardrails() -> None:
    bundle = _bundle()
    revision = _revisions()["operator:scrublet.Scrublet.scrub_doublets"]
    constraint = next(item for item in bundle.representation_constraints if item.constraint_id == "representation-constraint:uat:scrublet-raw")
    claims = {item.claim_id: item for item in bundle.atomic_claims}
    assessments = {item.claim_revision_id: item for item in bundle.evidence_assessments}

    assert constraint.representation_type_id == "representation-type:raw_umi_counts"
    assert "capture_unit_id" in constraint.required_metadata
    assert {"normalized", "log1p", "scaled", "integrated"} <= set(constraint.forbidden_transformations)
    assert revision.output_ports[0].representation_type_id == "representation-type:doublet_assessment"
    assert claims["claim:uat:scrublet-sample-scope"].assertion_kind == "limitation"
    assert claims["claim:uat:scrublet-threshold"].assertion_kind == "limitation"
    guardrail = claims["claim:uat:scrublet-no-delete"]
    assert guardrail.assertion_kind == "recommendation"
    assert assessments[guardrail.claim_revision_id].stance == "partial_support"


def test_singler_accepts_raw_query_but_requires_labelled_aligned_applicable_reference() -> None:
    bundle = _bundle()
    revision = _revisions()["operator:SingleR::SingleR"]
    constraints = {item.constraint_id: item for item in bundle.representation_constraints}

    assert len(revision.input_ports) == 3
    query = revision.input_ports[0]
    assert query.requirement_combination == "any_of"
    assert {constraint_id for req in query.requirements for constraint_id in req.representation_constraint_ids} == {
        "representation-constraint:uat:singler-query-raw",
        "representation-constraint:uat:singler-query-log",
    }
    ref = constraints["representation-constraint:uat:singler-reference-expression"]
    assert {"ordered_reference_ids", "ordered_feature_ids", "feature_namespace", "biological_applicability_confirmed", "organism_taxon"} <= set(ref.required_metadata)
    assert ref.feature_alignment == "intersection"
    labels = constraints["representation-constraint:uat:singler-reference-labels"]
    assert "ordered_reference_ids" in labels.required_metadata
    assert any("non-empty feature intersection" in item for item in query.cross_port_alignment_constraints)


def test_can_feed_relations_use_explicit_claim_scoped_proofs_not_type_equality() -> None:
    bundle = _bundle()
    relations = [item for item in bundle.derived_relations if item.relation == "CAN_FEED"]
    proofs = _json(DEFAULT_OUTPUT_DIR / "derived_relation_proofs.json")["proofs"]
    relation_counts = Counter(item.relation for item in bundle.derived_relations)

    assert relation_counts == Counter({"CONSUMES": 17, "PRODUCES": 8, "CAN_FEED": 4})
    assert len(relations) == 4
    assert all(item.derivation_rule_id == "rule:v1.1:claim-scoped-port-compatibility" for item in relations)
    assert all(item.premise_relation_ids and item.derived_from_claim_revision_ids for item in relations)
    assert all(row["type_equality_only"] is False for row in proofs)
    assert all({"observation_identity", "lineage_compatibility", "semantic_parameter_compatibility", "staleness"} <= set(row["checks"]) for row in proofs)


def test_high_risk_claims_use_resolvable_hashed_exact_source_bindings() -> None:
    spans = {row["evidence_span_id"]: row for row in _jsonl(DEFAULT_OUTPUT_DIR / "authoritative_evidence_spans.jsonl")}
    bindings = _jsonl(DEFAULT_OUTPUT_DIR / "exact_evidence_bindings.jsonl")
    risks = {row["record_id"]: row for row in _jsonl(DEFAULT_OUTPUT_DIR / "risk_registry.jsonl")}

    assert all("source_local_excerpt" not in row for row in spans.values())
    assert all(row["source_bound"] is True for row in spans.values())
    assert all(row["content_hash"] == hashlib.sha256(row["source_excerpt"].encode()).hexdigest() for row in spans.values())
    assert all(set(row["evidence_span_ids"]) <= set(spans) for row in bindings)
    assert all(row["evidence_locators"] and row["source_file_sha256"] and row["evidence_excerpt_sha256"] for row in bindings)
    high_risk = {record_id for record_id, row in risks.items() if row["record_type"] == "AtomicClaimRevision" and row["risk_class"] in {"R3", "R4"}}
    assert high_risk <= {row["claim_revision_id"] for row in bindings}


def test_all_explicit_decision_uats_pass_and_promotion_classes_remain_separate() -> None:
    uats = _json(DEFAULT_OUTPUT_DIR / "decision_uat_results.json")
    promotion = _json(DEFAULT_OUTPUT_DIR / "promotion_preflight.json")
    quality = _json(DEFAULT_OUTPUT_DIR / "semantic_quality_report.json")

    assert uats["passed"] is True
    assert len(uats["results"]) == 9
    assert all(item["passed"] is True for item in uats["results"])
    assert promotion["promotion_performed"] is False
    assert promotion["promotion_ready"]
    assert promotion["review_required"]
    assert promotion["scoped_profile_only"] == ["claim-revision:uat:pca-project-profile:v1"]
    assert len(promotion["execution_only_blockers"]) == 3
    assert all(quality["checks"].values())
