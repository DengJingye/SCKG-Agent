from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.scientific_knowledge_conformance_models import (
    ConformanceBundle,
    DerivedRelation,
    MethodVariant,
    RepresentationInstanceBinding,
    ReviewDecision,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import (
    CANONICAL_PATHS,
    DEFAULT_OUTPUT_DIR,
    build,
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture(name: str) -> ConformanceBundle:
    return ConformanceBundle.model_validate(_json(DEFAULT_OUTPUT_DIR / "fixtures" / name))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generated_schemas_and_fixtures_are_deterministic_and_candidate_only(tmp_path: Path) -> None:
    canonical_before = {path: _sha256(path) for path in CANONICAL_PATHS if path.exists()}

    manifest = build(tmp_path)

    assert manifest["status"] == "candidate_only_not_promoted"
    assert manifest["canonical_kg_modified"] is False
    assert manifest["retrieval_index_rebuilt"] is False
    assert {path: _sha256(path) for path in CANONICAL_PATHS if path.exists()} == canonical_before
    expected_manifest = _json(DEFAULT_OUTPUT_DIR / "manifest.json")
    assert manifest["artifacts"] == expected_manifest["artifacts"]
    for relative_path in manifest["artifacts"]:
        assert (tmp_path / relative_path).read_bytes() == (DEFAULT_OUTPUT_DIR / relative_path).read_bytes()


def test_all_conformance_fixtures_validate_and_cover_required_semantics() -> None:
    fixture_paths = sorted((DEFAULT_OUTPUT_DIR / "fixtures").glob("*.json"))
    fixtures = [ConformanceBundle.model_validate(_json(path)) for path in fixture_paths]
    proven = {item for fixture in fixtures for item in fixture.expected_semantics}

    assert len(fixtures) == 5
    assert {
        "package_operator_method_are_distinct",
        "scope_and_parameter_conditions_are_structured",
        "representation_instance_is_ledger_owned_not_canonical_entity",
        "input_output_ports_are_canonical",
        "consumes_produces_are_port_projections",
        "can_feed_does_not_imply_requires_before",
        "reference_artifact_revision_is_a_separate_required_input",
        "multimodal_constraints_preserve_modality_axes_and_partial_pairing",
        "empirical_results_are_scoped_not_universal_superiority_edges",
        "supersession_preserves_old_and_new_revision_identity",
    } <= proven


def test_package_operator_method_and_port_projection_are_separate() -> None:
    fixture = _fixture("package-operator-method-and-ports.json")
    entity_types = {item.entity_id: item.record_type for item in fixture.entities}

    assert entity_types["package:scanpy"] == "Package"
    assert entity_types["operator:scanpy.pp.pca"] == "Operator"
    assert entity_types["method:pca"] == "Method"
    operator_revision = next(item for item in fixture.entities if item.record_type == "OperatorRevision")
    assert operator_revision.implements_method_ids == ["method:pca"]
    assert {item.relation for item in fixture.derived_relations} == {"CONSUMES", "PRODUCES"}
    assert all(item.derivation_type == "port_projection" for item in fixture.derived_relations)


def test_hvg_inputs_are_parameter_conditioned_alternatives() -> None:
    fixture = _fixture("conditional-hvg-inputs.json")
    operator_revision = next(item for item in fixture.entities if item.record_type == "OperatorRevision")
    port = operator_revision.input_ports[0]

    assert port.requirement_combination == "any_of"
    assert len(port.requirements) == 2
    assert {item.level for item in port.requirements} == {"conditional"}
    branches = {value for item in port.requirements for condition in item.when for value in condition.values}
    assert branches == {"seurat_v3", "seurat_v3_paper", "seurat", "cell_ranger"}
    assert {item.representation_type_id for item in fixture.representation_constraints} == {
        "representation-type:raw_counts",
        "representation-type:log_expression",
    }


def test_existing_ledger_instance_allows_reuse_without_mandatory_predecessor() -> None:
    fixture = _fixture("optional-upstream-reuse.json")

    assert fixture.instance_bindings == [
        RepresentationInstanceBinding.model_validate(fixture.instance_bindings[0].model_dump())
    ]
    assert fixture.instance_bindings[0].owner == "RepresentationLedger"
    assert fixture.instance_bindings[0].satisfaction == "satisfied"
    assert {item.relation for item in fixture.derived_relations} == {
        "CONSUMES",
        "PRODUCES",
        "CAN_FEED",
    }
    assert all(item.relation != "REQUIRES_BEFORE" for item in fixture.derived_relations)
    assert all(item.record_type != "RepresentationInstance" for item in fixture.entities)


def test_can_feed_and_requires_before_have_distinct_proof_obligations() -> None:
    with pytest.raises(ValidationError, match="premise relations"):
        DerivedRelation(
            relation_id="derived-relation:invalid_can_feed",
            relation="CAN_FEED",
            source_id="operator-revision:a",
            target_id="operator-revision:b",
            scope_id="scope:test",
            derivation_type="reviewed_rule",
            input_port_id="input-port:b",
            output_port_id="output-port:a",
            derivation_rule_id="rule:test",
            review_status="accepted",
        )

    with pytest.raises(ValidationError, match="high-risk review"):
        DerivedRelation(
            relation_id="derived-relation:invalid_requires_before",
            relation="REQUIRES_BEFORE",
            source_id="operator-revision:a",
            target_id="operator-revision:b",
            scope_id="scope:test",
            derivation_type="reviewed_rule",
            requirement_id="requirement:b",
            derivation_rule_id="rule:test",
            review_status="accepted",
        )


def test_candidate_can_feed_can_await_review_but_accepted_relation_cannot() -> None:
    candidate = DerivedRelation(
        relation_id="derived-relation:candidate_can_feed",
        relation="CAN_FEED",
        source_id="operator-revision:a",
        target_id="operator-revision:b",
        scope_id="scope:test",
        derivation_type="reviewed_rule",
        input_port_id="input-port:b",
        output_port_id="output-port:a",
        premise_relation_ids=["derived-relation:a_produces", "derived-relation:b_consumes"],
        derivation_rule_id="rule:test",
        review_status="candidate_pending_review",
    )

    assert candidate.review_decision_ids == []


def test_method_variant_is_a_distinct_method_child_identity() -> None:
    variant = MethodVariant(
        entity_id="method-variant:pca.scaled_hvg",
        method_id="method:pca",
        label="PCA on scaled HVG expression",
    )

    assert variant.record_type == "MethodVariant"
    assert variant.method_id == "method:pca"
    assert (DEFAULT_OUTPUT_DIR / "schemas" / "method_variant.schema.json").exists()

def test_reference_requirement_and_multimodal_constraint_are_explicit() -> None:
    fixture = _fixture("reference-and-multimodal-requirements.json")
    operators = {item.entity_id: item for item in fixture.entities if item.record_type == "OperatorRevision"}
    annotation_requirements = operators["operator-revision:fixture.annotate:1"].input_ports[0].requirements
    multivi_constraint = next(
        item
        for item in fixture.representation_constraints
        if item.constraint_id == "representation-constraint:multivi_partially_paired"
    )

    assert any(item.reference_artifact_revision_ids for item in annotation_requirements)
    assert multivi_constraint.required_modalities == ["rna", "atac"]
    assert multivi_constraint.observation_alignment == "partially_paired"
    assert multivi_constraint.feature_alignment == "explicit_mapping"
    assert multivi_constraint.allow_missing_modalities is True


def test_high_risk_review_cannot_be_satisfied_by_automation_alone() -> None:
    with pytest.raises(ValidationError, match="high-risk"):
        ReviewDecision(
            review_decision_id="review:invalid-automated-r3",
            risk_class="R3",
            reviewer_type="automated_validator",
            decision="accepted",
            reviewed_record_ids=["derived-relation:test"],
            rationale="Automation cannot approve a high-risk decision.",
            reviewed_artifact_hashes=["a" * 64],
            policy_version="risk-review-v1.1",
            decided_at="2026-09-10T00:00:00Z",
        )


def test_benchmark_results_are_scoped_and_supersession_is_revisioned() -> None:
    fixture = _fixture("benchmark-and-supersession.json")

    assert len(fixture.benchmark_studies) == 1
    assert len(fixture.evaluation_datasets) == 1
    assert len(fixture.empirical_results) == 2
    assert {item.scope_id for item in fixture.empirical_results} == {
        fixture.benchmark_studies[0].scope_id
    }
    assert {item.subject_id for item in fixture.empirical_results} == {
        "method:harmony",
        "method:scanorama",
    }
    assert not fixture.derived_relations
    supersession = fixture.supersessions[0]
    assert supersession.old_revision_id != supersession.new_revision_id
    assert supersession.derived_from_claim_revision_ids == [fixture.atomic_claims[0].claim_revision_id]


def test_legacy_crosswalk_reports_exact_non_automatic_migration_blockers() -> None:
    crosswalk = _json(DEFAULT_OUTPUT_DIR / "legacy_crosswalk.json")
    surfaces = {item["surface"] for item in crosswalk["legacy_surfaces"]}
    blockers = {item["id"] for item in crosswalk["migration_blockers"]}

    assert surfaces == {
        "MethodGraph v0",
        "DecisionGraph v3",
        "KnowledgeGraph v2",
        "AtomicClaim candidate v1",
        "RepresentationLedger v1",
    }
    assert next(
        item for item in crosswalk["legacy_surfaces"] if item["surface"] == "AtomicClaim candidate v1"
    )["record_counts"]["claims"] == 48
    assert {
        "source_bound_projection_mismatch",
        "graph_input_fingerprint_drift",
        "scanpy_contract_snapshot_missing",
        "celltypist_singler_contract_version_drift",
        "scvi_scvi_tools_identity_unresolved",
        "monocle_monocle3_identity_unresolved",
        "method_binding_semantic_split_required",
        "ports_and_scopes_missing",
        "candidate_claim_review_pending",
    } == blockers
    assert crosswalk["automatic_migration_allowed"] is False
    assert crosswalk["canonical_modified"] is False
