from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.scientific_knowledge_conformance_models import (
    ConformanceBundle,
    MethodVariant,
    OperatorRevision,
)
from data_pipeline.build_scanpy_core_identity_port_candidate_v1_1 import (
    DEFAULT_OUTPUT_DIR,
    build,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(root: Path = DEFAULT_OUTPUT_DIR) -> ConformanceBundle:
    return ConformanceBundle.model_validate(_json(root / "conformance_bundle.json"))


def test_candidate_build_is_deterministic_and_does_not_touch_canonical_or_retrieval(tmp_path: Path) -> None:
    canonical_before = {path: _sha256(path) for path in CANONICAL_PATHS if path.exists()}

    generated = build(tmp_path)
    frozen = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert generated["status"] == "candidate_only_not_promoted"
    assert generated["canonical_kg_modified"] is False
    assert generated["retrieval_index_rebuilt"] is False
    assert generated["runtime_modified"] is False
    assert generated["artifacts"] == frozen["artifacts"]
    assert {path: _sha256(path) for path in CANONICAL_PATHS if path.exists()} == canonical_before
    for relative_path in generated["artifacts"]:
        assert (tmp_path / relative_path).read_bytes() == (DEFAULT_OUTPUT_DIR / relative_path).read_bytes()


def test_scanpy_identity_chain_separates_project_package_release_operator_method_and_variant() -> None:
    bundle = _bundle()
    entity_types = {item.entity_id: item.record_type for item in bundle.entities}

    assert entity_types["software-project:scanpy"] == "SoftwareProject"
    assert entity_types["package:scanpy"] == "Package"
    assert entity_types["package-release:scanpy:1.11.2"] == "PackageRelease"
    assert entity_types["operator:scanpy.pp.pca"] == "Operator"
    assert entity_types["method:pca"] == "Method"
    assert entity_types["method-variant:pca.scaled_hvg"] == "MethodVariant"
    assert entity_types["method-variant:pca.log_hvg"] == "MethodVariant"
    variants = [item for item in bundle.entities if isinstance(item, MethodVariant)]
    assert len(variants) == 8
    assert all(item.method_id in entity_types for item in variants)


def test_exact_five_operator_revisions_implement_methods_and_variants() -> None:
    revisions = [item for item in _bundle().entities if isinstance(item, OperatorRevision)]

    assert {item.operator_id for item in revisions} == {
        "operator:scanpy.pp.highly_variable_genes",
        "operator:scanpy.pp.pca",
        "operator:scanpy.pp.neighbors",
        "operator:scanpy.tl.umap",
        "operator:scanpy.tl.leiden",
    }
    assert all(item.package_release_id == "package-release:scanpy:1.11.2" for item in revisions)
    assert all(item.implements_method_ids for item in revisions)
    assert all(item.implements_method_variant_ids for item in revisions)


def test_hvg_and_pca_ports_preserve_conditional_and_alternative_requirements() -> None:
    revisions = {
        item.operator_id: item
        for item in _bundle().entities
        if isinstance(item, OperatorRevision)
    }
    hvg = revisions["operator:scanpy.pp.highly_variable_genes"].input_ports[0]
    pca = revisions["operator:scanpy.pp.pca"].input_ports[0]

    assert hvg.requirement_combination == "any_of"
    assert {value for requirement in hvg.requirements for condition in requirement.when for value in condition.values} == {
        "seurat",
        "cell_ranger",
        "seurat_v3",
        "seurat_v3_paper",
    }
    assert pca.requirement_combination == "any_of"
    assert {len(item.representation_constraint_ids) for item in pca.requirements} == {1, 2}
    assert any("same ordered gene identity" in item for item in pca.cross_port_alignment_constraints)


def test_neighbors_accepts_pca_or_integrated_coordinates_without_flattening_variants() -> None:
    bundle = _bundle()
    neighbors = next(
        item
        for item in bundle.entities
        if isinstance(item, OperatorRevision) and item.operator_id == "operator:scanpy.pp.neighbors"
    )
    constraint_ids = {
        constraint_id
        for requirement in neighbors.input_ports[0].requirements
        for constraint_id in requirement.representation_constraint_ids
    }

    assert neighbors.input_ports[0].requirement_combination == "any_of"
    assert constraint_ids == {
        "representation-constraint:scanpy_neighbors_pca",
        "representation-constraint:scanpy_neighbors_integrated",
    }
    assert set(neighbors.implements_method_variant_ids) == {
        "method-variant:neighbors.pca",
        "method-variant:neighbors.integrated",
    }


def test_consumes_and_produces_are_port_projections_and_workflow_edges_are_only_can_feed() -> None:
    relations = _bundle().derived_relations

    assert sum(item.relation == "CONSUMES" for item in relations) == 9
    assert sum(item.relation == "PRODUCES" for item in relations) == 5
    assert sum(item.relation == "CAN_FEED" for item in relations) == 4
    assert all(item.relation != "REQUIRES_BEFORE" for item in relations)
    assert all(
        item.derivation_type == "port_projection"
        for item in relations
        if item.relation in {"CONSUMES", "PRODUCES"}
    )
    assert all(
        item.review_status == "candidate_pending_review" and not item.review_decision_ids
        for item in relations
        if item.relation == "CAN_FEED"
    )


def test_legacy_precedes_edges_are_reclassified_without_creating_mandatory_order() -> None:
    result = _json(DEFAULT_OUTPUT_DIR / "legacy_edge_reclassification.json")
    rows = result["legacy_precedes_reclassification"]

    assert len(rows) == 7
    assert {item["classification"] for item in rows} == {"CAN_FEED"}
    assert all(item["is_genuine_requires_before"] is False for item in rows)
    assert result["genuine_requires_before"] == []
    assert result["rejected_workflow_or_ui_order"] == [
        {
            "source": "operator-revision:scanpy.tl.umap:1.11.2",
            "target": "operator-revision:scanpy.tl.leiden:1.11.2",
            "classification": "REJECT",
            "reason": "No port dependency exists; both independently consume the neighbor graph, so display order cannot become scientific prerequisite truth.",
        }
    ]


def test_all_claims_have_version_pinned_authoritative_provenance_but_none_are_promoted() -> None:
    bundle = _bundle()
    report = _json(DEFAULT_OUTPUT_DIR / "conformance_report.json")
    assessment_claims = {item.claim_revision_id for item in bundle.evidence_assessments}

    assert len(bundle.atomic_claims) == 27
    assert assessment_claims == {item.claim_revision_id for item in bundle.atomic_claims}
    assert sum(item.stance == "supports" for item in bundle.evidence_assessments) == 23
    assert sum(item.stance == "partial_support" for item in bundle.evidence_assessments) == 4
    assert report["checks"]["repository_span_resolvability"]["passed"] is True
    assert report["checks"]["authoritative_evidence_span_resolvability"]["passed"] is True
    assert report["checks"]["version_pinned_official_api_claim_support"]["passed"] is True
    assert report["promotion_eligibility"]["eligible"] is False
    assert report["promotion_eligibility"]["eligible_claim_revision_ids"] == []


def test_representation_instances_remain_outside_candidate_kg() -> None:
    bundle = _bundle()
    port_model = _json(DEFAULT_OUTPUT_DIR / "port_representation_model.json")

    assert bundle.instance_bindings == []
    assert port_model["runtime_representation_instance_owner"] == "RepresentationLedger"
    assert port_model["runtime_representation_instances_in_candidate_kg"] == 0


def test_closed_semantic_items_and_remaining_promotion_blockers_are_explicit() -> None:
    ambiguities = _json(DEFAULT_OUTPUT_DIR / "unresolved_ambiguities.json")
    blocker_ids = {item["id"] for item in ambiguities["items"]}
    resolved_ids = {item["id"] for item in ambiguities["resolved_items"]}

    assert {
        "official_api_spans_version_pinned",
        "pca_namespace_identity_resolved",
        "hvg_flavor_inputs_resolved",
        "neighbor_graph_composite_resolved",
    } == resolved_ids
    assert {
        "scanpy_contract_snapshot_missing",
        "governed_profiles_require_scope_review",
        "parameter_semantics_out_of_slice",
        "candidate_claim_review_pending",
    } == blocker_ids


def test_authoritative_snapshot_is_release_and_commit_pinned() -> None:
    source = _json(DEFAULT_OUTPUT_DIR / "authoritative_source_manifest.json")
    spans = [json.loads(line) for line in (DEFAULT_OUTPUT_DIR / "authoritative_evidence_spans.jsonl").read_text(encoding="utf-8").splitlines()]

    assert source["release"] == "1.11.2"
    assert source["git_commit"] == "5400eb87ef7d4e9f6f5a9256d98a7927723456fa"
    assert source["pypi_sdist_sha256"] == "cde3a142aa12bd3a6894756d50c245cd6ec7776bba4b244c5099b0666f7455bd"
    assert len(source["source_files"]) == 9
    assert len(spans) == 19
    assert all(item["version_pin"]["git_commit"] == source["git_commit"] for item in spans)
    assert all(item["candidate_only"] and not item["retrieval_eligible"] for item in spans)
    assert all(
        item["content_hash"] == hashlib.sha256(item["source_excerpt"].encode("utf-8")).hexdigest()
        for item in spans
    )


def test_pca_primary_operator_and_historical_alias_are_version_resolved() -> None:
    identity = _json(DEFAULT_OUTPUT_DIR / "identity_graph.json")
    aliases = [item for item in identity["nodes"] if item["type"] == "OperatorAlias"]
    alias_edges = [item for item in identity["edges"] if item["relation"] == "ALIAS_OF"]

    assert aliases[0]["id"] == "operator-alias:scanpy.tl.pca:1.11.2"
    assert alias_edges == [
        {
            "source": "operator-alias:scanpy.tl.pca:1.11.2",
            "relation": "ALIAS_OF",
            "target": "operator:scanpy.pp.pca",
            "scope_id": "scope:scanpy-pca-1.11.2",
            "derived_from_evidence_span_ids": [
                "scanpy-authoritative-span:pca.pp_export:1.11.2",
                "scanpy-authoritative-span:pca.tl_alias:1.11.2",
            ],
            "derived_from_claim_revision_ids": [],
        }
    ]


def test_neighbor_graph_is_a_structured_three_component_output() -> None:
    bundle = _bundle()
    graph_type = next(
        item
        for item in bundle.representation_types
        if item.representation_type_id == "representation-type:neighbor_graph"
    )
    constraints = {item.constraint_id: item for item in bundle.representation_constraints}

    assert {item.role for item in graph_type.components} == {"connectivities", "distances", "metadata"}
    assert all(item.required for item in graph_type.components)
    assert constraints["representation-constraint:scanpy_umap_neighbor_graph"].required_component_roles == [
        "connectivities",
        "metadata",
    ]
    assert constraints["representation-constraint:scanpy_leiden_neighbor_graph"].required_component_roles == [
        "connectivities"
    ]


def test_four_can_feed_derivations_are_evidence_reassessed_not_promoted() -> None:
    changes = _json(DEFAULT_OUTPUT_DIR / "claim_assessment_changes.json")

    assert len(changes["can_feed_derivations"]) == 4
    assert all(
        item["evidence_result"] == "supported_by_version_pinned_port_premises"
        and item["review_status"] == "candidate_pending_review"
        for item in changes["can_feed_derivations"]
    )


def test_promotion_preflight_applies_v1_1_risk_policy_without_promoting() -> None:
    preflight = _json(DEFAULT_OUTPUT_DIR / "promotion_preflight.json")

    assert preflight["status"] == "preflight_complete_no_promotion_performed"
    assert preflight["summary"] == {
        "atomic_claims": 27,
        "can_feed_derivations": 4,
        "promotion_ready_r2_claims": 10,
        "r3_claims_or_relations_requiring_human_review": 17,
        "r3_project_profile_claims_requiring_human_review": 4,
        "r4_records": 0,
        "scientific_promotion_eligible_now": 0,
    }
    assert preflight["canonical_kg_modified"] is False
    assert preflight["retrieval_index_rebuilt"] is False
    assert preflight["execution_eligibility_changed"] is False


def test_promotion_ready_set_contains_only_source_backed_r2_method_and_output_claims() -> None:
    preflight = _json(DEFAULT_OUTPUT_DIR / "promotion_preflight.json")
    ready = preflight["promotion_ready_claims"]

    assert len(ready) == 10
    assert {item["predicate"] for item in ready} == {"implements_method", "produces"}
    assert all(item["risk_class"] == "R2" for item in ready)
    assert all(item["evidence_stance"] == "supports" for item in ready)
    assert all(item["scientific_promotion_eligible_now"] is False for item in ready)
    assert {item["required_gate"] for item in ready} == {
        "one_qualified_review_or_approved_deterministic_rule"
    }


def test_r3_input_variant_and_can_feed_records_require_human_review() -> None:
    preflight = _json(DEFAULT_OUTPUT_DIR / "promotion_preflight.json")
    review = preflight["claims_requiring_human_review"]

    assert len(review) == 17
    assert all(item["risk_class"] == "R3" for item in review)
    assert sum(item["record_type"] == "AtomicClaimRevision" for item in review) == 13
    assert sum(item["record_type"] == "DerivedRelation" for item in review) == 4
    assert all(item["required_gate"] == "qualified_human_review" for item in review)


def test_four_pca_governed_profile_claims_are_not_upstream_scanpy_facts() -> None:
    preflight = _json(DEFAULT_OUTPUT_DIR / "promotion_preflight.json")
    profiles = preflight["scoped_profile_only_claims"]

    assert len(profiles) == 4
    assert all(item["subject_id"] == "operator-revision:scanpy.pp.pca:1.11.2" for item in profiles)
    assert all(item["knowledge_layer"] == "project_profile" for item in profiles)
    assert all(item["upstream_scanpy_fact"] is False for item in profiles)
    assert {item["evidence_stance"] for item in profiles} == {"partial_support"}


def test_contract_snapshot_is_execution_only_and_coverage_gaps_do_not_block_promotion() -> None:
    preflight = _json(DEFAULT_OUTPUT_DIR / "promotion_preflight.json")
    blockers = {item["id"]: item for item in preflight["execution_only_blockers"]}

    assert blockers["scanpy_contract_snapshot_missing"]["blocks_scientific_knowledge_promotion"] is False
    assert blockers["scanpy_contract_snapshot_missing"]["blocks_execution_eligibility"] is True
    assert blockers["execution_policy_disabled"]["blocks_scientific_knowledge_promotion"] is False
    assert all(item["blocks_current_claim_promotion"] is False for item in preflight["non_blocking_coverage_gaps"])
