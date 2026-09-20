from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    AtomicClaimRevision,
    ConformanceBundle,
    EvidenceAssessment,
    ReferenceArtifact,
    ReferenceArtifactRevision,
    Requirement,
)
from core.scientific_ontology_v2_compatibility_models import (
    EvidenceSpanCoreView,
    ReferenceResourceView,
    StatementRevisionView,
)
from engine.scientific_ontology_v2_compatibility import (
    ScientificOntologyV2CompatibilityService,
)
from eval.build_ontology_v2_compatibility_v1 import build


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_core"
REFERENCE_FIXTURE = (
    ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_knowledge_schema_v1_1"
    / "fixtures"
    / "reference-and-multimodal-requirements.json"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def service() -> ScientificOntologyV2CompatibilityService:
    return ScientificOntologyV2CompatibilityService(ROOT)


@pytest.fixture(scope="module")
def core_bundle() -> ConformanceBundle:
    return ConformanceBundle.model_validate(_json(CORE_ROOT / "conformance_bundle.json"))


def _claim_payload(*, predicate: str = "implements_method", literal: bool = False) -> dict:
    text = "A bounded compatibility assertion."
    payload = {
        "schema_version": "sckg-atomic-claim-revision-v1.1",
        "claim_id": "claim:test:compatibility",
        "claim_revision_id": "claim-revision:test:compatibility:1",
        "subject_id": "operator-revision:test:1",
        "predicate": predicate,
        "object_id": "method:test" if not literal else None,
        "object_value": "true" if literal else None,
        "scope_id": "scope:test:compatibility",
        "claim_text": text,
        "polarity": "negative",
        "assertion_kind": "capability",
        "semantic_fingerprint": "a" * 64,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "supersedes_revision_ids": ["claim-revision:test:compatibility:0"],
        "created_by_activity_id": "activity:test",
    }
    if literal:
        payload["subject_id"] = "representation-type:test"
    return payload


def _scope_payload() -> dict:
    return {
        "schema_version": "sckg-applicability-scope-v1.1",
        "scope_id": "scope:test:compatibility",
        "task_ids": ["task:test"],
        "version_constraints": [],
        "modalities": ["rna"],
        "organism_taxa": [],
        "biological_context_ids": [],
        "observation_units": ["cell"],
        "assay_technology_ids": [],
        "study_design_constraints": [],
        "representation_constraint_ids": [],
        "parameter_conditions": [],
        "resource_constraints": [],
        "evaluation_context_ids": [],
        "scope_status": "explicit",
        "combination": "any_of",
    }


def _span_payload(*, page: int | None = None, lines: bool = False) -> dict:
    text = "Exact source text."
    payload = {
        "schema_version": "legacy-span-v1",
        "evidence_span_id": "evidence-span:test:1",
        "source_revision_id": "source-revision:test:1",
        "source_artifact_id": "source-artifact:test:1",
        "source_artifact_hash": "b" * 64,
        "exact_text": text,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "locator": "document.pdf#page=7" if page else "src/module.py#L10-L12",
    }
    if page:
        payload["page"] = page
        payload["section"] = "Methods"
    if lines:
        payload["line_start"] = 10
        payload["line_end"] = 12
    return payload


def test_atomic_claim_maps_to_read_only_statement_view_with_preserved_links(
    service: ScientificOntologyV2CompatibilityService,
    core_bundle: ConformanceBundle,
) -> None:
    claim = next(item for item in core_bundle.atomic_claims if item.predicate == "implements_method")
    scope = next(item for item in core_bundle.scopes if item.scope_id == claim.scope_id)
    assessments = [
        item for item in core_bundle.evidence_assessments if item.claim_revision_id == claim.claim_revision_id
    ]

    result = service.map_atomic_claim(
        claim,
        scope=scope,
        evidence_assessments=assessments,
        source_layer_id="scientific_kg_v1_core",
        source_status="candidate_not_promoted",
    )

    assert result.status == "DIRECT_COMPATIBLE"
    assert isinstance(result.view, StatementRevisionView)
    assert result.view.statement_id == claim.claim_id
    assert result.view.statement_revision_id == claim.claim_revision_id
    assert result.view.subject_id == claim.subject_id
    assert result.view.object_id == claim.object_id
    assert result.view.polarity == claim.polarity.upper()
    assert result.view.scope_ref == claim.scope_id
    assert result.view.semantic_fingerprint == claim.semantic_fingerprint
    assert result.view.content == claim.claim_text
    assert result.view.content_hash == claim.content_hash
    assert result.view.evidence_span_ids == tuple(assessments[0].evidence_span_ids)
    assert result.view.source_governance_status == "candidate_not_promoted"
    assert result.view.trusted is False
    with pytest.raises(ValidationError):
        result.view.statement_id = "statement:mutated"


def test_literal_object_is_preserved_but_datatype_ambiguity_is_visible(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(predicate="is_sparse", literal=True),
        scope=_scope_payload(),
        source_layer_id="test_fixture",
    )

    assert result.status == "AMBIGUOUS_MAPPING"
    assert "LITERAL_DATATYPE_UNAVAILABLE" in result.reason_codes
    assert isinstance(result.view, StatementRevisionView)
    assert result.view.literal_value == "true"
    assert result.view.object_id is None


def test_scope_preserves_any_of_without_flattening(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_scope(_scope_payload(), source_layer_id="test_fixture")

    assert result.status == "COMPATIBLE_WITH_ADAPTER"
    assert result.view is not None
    assert result.view.combination == "ANY_OF"
    assert {item.dimension for item in result.view.qualifiers} == {
        "task",
        "modality",
        "observation_unit",
    }


def test_statement_supersession_same_family_revision_is_preserved(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(), scope=_scope_payload(), source_layer_id="test_fixture"
    )

    assert isinstance(result.view, StatementRevisionView)
    assert result.view.supersedes_revision_ids == ("claim-revision:test:compatibility:0",)


def test_evidence_span_pdf_locator_maps_only_core_fields(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    payload = _span_payload(page=7)
    payload.update(
        {
            "authority": "official",
            "candidate_only": True,
            "retrieval_eligible": False,
            "review_status": "candidate_source_verified",
            "normalized_proposition": "Must not enter the core view.",
        }
    )
    result = service.map_evidence_span(payload, source_layer_id="test_fixture")

    assert result.status == "COMPATIBLE_WITH_ADAPTER"
    assert isinstance(result.view, EvidenceSpanCoreView)
    assert result.view.page == 7
    assert result.view.section == "Methods"
    assert not {
        "authority",
        "candidate_only",
        "retrieval_eligible",
        "review_status",
        "normalized_proposition",
    } & result.view.model_dump().keys()


def test_evidence_span_non_page_locator_preserves_lines_not_offsets(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_evidence_span(
        _span_payload(lines=True), source_layer_id="test_fixture"
    )

    assert isinstance(result.view, EvidenceSpanCoreView)
    assert result.view.page is None
    assert (result.view.line_start, result.view.line_end) == (10, 12)
    assert result.view.start_offset is None


@pytest.mark.parametrize(
    ("level", "strength"),
    [
        ("mandatory", "REQUIRED"),
        ("recommended", "RECOMMENDED"),
        ("optional", "OPTIONAL"),
    ],
)
def test_requirement_strength_mapping_is_explicit(
    service: ScientificOntologyV2CompatibilityService,
    level: str,
    strength: str,
) -> None:
    payload = {
        "schema_version": "sckg-requirement-v1.1",
        "requirement_id": f"requirement:test:{level}",
        "level": level,
        "representation_constraint_ids": ["representation-constraint:test"],
        "reference_artifact_revision_ids": [],
        "when": [],
        "scope_id": "scope:test:compatibility",
    }
    result = service.map_requirement(
        payload,
        known_constraint_ids={"representation-constraint:test"},
        source_layer_id="test_fixture",
    )

    assert result.status == "COMPATIBLE_WITH_ADAPTER"
    assert result.view is not None
    assert result.view.strength == strength
    assert result.view.activation_status == "unconditional"


def test_reference_only_requirement_uses_existing_fixture_without_fabrication(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    bundle = ConformanceBundle.model_validate(_json(REFERENCE_FIXTURE))
    artifact = next(item for item in bundle.entities if isinstance(item, ReferenceArtifact))
    revision = next(
        item for item in bundle.entities if isinstance(item, ReferenceArtifactRevision)
    )
    requirement = next(
        requirement
        for entity in bundle.entities
        if entity.record_type == "OperatorRevision"
        for port in entity.input_ports
        for requirement in port.requirements
        if requirement.reference_artifact_revision_ids
    )
    reference_result = service.map_reference_resource(
        artifact, revision=revision, source_layer_id="v1_1_reference_fixture"
    )
    requirement_result = service.map_requirement(
        requirement,
        reference_revisions={revision.entity_id: reference_result},
        source_layer_id="v1_1_reference_fixture",
    )

    assert isinstance(reference_result.view, ReferenceResourceView)
    assert reference_result.view.artifact_id == artifact.entity_id
    assert reference_result.view.artifact_revision_id == revision.entity_id
    assert requirement_result.status == "COMPATIBLE_WITH_ADAPTER"
    assert requirement_result.view is not None
    assert requirement_result.view.reference_artifact_revision_ids == (revision.entity_id,)
    assert not requirement_result.view.representation_constraint_ids


def test_can_feed_is_always_derived_and_mapping_is_deterministic(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    first = service.classify_relation("CAN_FEED", source_layer_id="test_fixture")
    second = service.classify_relation("CAN_FEED", source_layer_id="test_fixture")

    assert first == second
    assert first.view is not None
    assert first.view.classification == "DERIVED_PROJECTION"
    assert first.view.authoritative is False


def test_unknown_predicate_fails_closed(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(predicate="invented_predicate"),
        scope=_scope_payload(),
        source_layer_id="test_fixture",
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes[0] == "UNKNOWN_PREDICATE"
    assert result.view is None


def test_malformed_atomic_claim_with_two_objects_is_not_mappable(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    payload = _claim_payload()
    payload["object_value"] = "conflict"
    result = service.map_atomic_claim(
        payload, scope=_scope_payload(), source_layer_id="test_fixture"
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes == ("INVALID_V1_ATOMIC_CLAIM",)


def test_inline_shared_scope_conflict_is_ambiguous(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_scope(
        _scope_payload(),
        source_layer_id="test_fixture",
        inline_qualifiers={"modality": ["atac"]},
    )
    assert result.status == "AMBIGUOUS_MAPPING"
    assert result.reason_codes[0] == "INLINE_SHARED_SCOPE_CONFLICT"
    assert result.view is None


def test_unknown_requirement_strength_is_rejected(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    payload = {
        "schema_version": "sckg-requirement-v1.1",
        "requirement_id": "requirement:test:unknown",
        "level": "unknown",
        "representation_constraint_ids": ["representation-constraint:test"],
        "reference_artifact_revision_ids": [],
        "when": [],
        "scope_id": "scope:test:compatibility",
    }
    result = service.map_requirement(payload, source_layer_id="test_fixture")
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes == ("INVALID_V1_REQUIREMENT",)


def test_cross_family_reference_revision_is_rejected(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    artifact = ReferenceArtifact(
        entity_id="reference-artifact:first",
        label="first",
        artifact_kind="atlas",
    )
    revision = ReferenceArtifactRevision(
        entity_id="reference-artifact-revision:second:1",
        artifact_id="reference-artifact:second",
        version="1",
        content_digest="c" * 64,
        feature_namespace="HGNC",
        scope_id="scope:test:compatibility",
    )
    result = service.map_reference_resource(
        artifact, revision=revision, source_layer_id="test_fixture"
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes == ("CROSS_FAMILY_REFERENCE_REVISION",)


def test_missing_evidence_span_cannot_be_fabricated(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    assessment = EvidenceAssessment(
        assessment_id="evidence-assessment:test",
        claim_revision_id="claim-revision:test:compatibility:1",
        evidence_span_ids=["evidence-span:missing"],
        stance="supports",
        subject_aligned=True,
        predicate_aligned=True,
        object_aligned=True,
        scope_alignment="aligned",
        rationale="Explicit test alignment.",
    )
    result = service.map_evidence_assessment(
        assessment,
        statement_revision_ids={"claim-revision:test:compatibility:1"},
        evidence_spans={},
        source_layer_id="test_fixture",
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes[0] == "EVIDENCE_SPAN_NOT_AVAILABLE"


def test_evidence_assessment_preserves_exact_links_without_promoting_trust(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    span = service.map_evidence_span(_span_payload(page=7), source_layer_id="test_fixture")
    assessment = EvidenceAssessment(
        assessment_id="evidence-assessment:test:exact",
        claim_revision_id="claim-revision:test:compatibility:1",
        evidence_span_ids=["evidence-span:test:1"],
        stance="supports",
        subject_aligned=True,
        predicate_aligned=True,
        object_aligned=True,
        scope_alignment="aligned",
        rationale="All proposition components and scope are explicitly aligned.",
    )
    result = service.map_evidence_assessment(
        assessment,
        statement_revision_ids={"claim-revision:test:compatibility:1"},
        evidence_spans={"evidence-span:test:1": span},
        source_layer_id="test_fixture",
    )

    assert result.status == "AMBIGUOUS_MAPPING"
    assert result.view is not None
    assert result.view.statement_revision_id == assessment.claim_revision_id
    assert result.view.evidence_span_ids == tuple(assessment.evidence_span_ids)
    assert result.view.support_type == "DIRECT_SUPPORT"
    assert result.view.trusted is False
    assert result.view.assessment_method is None
    assert "V2_ASSESSMENT_AUDIT_METADATA_UNAVAILABLE" in result.reason_codes


def test_source_bound_span_does_not_synthesize_support(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    payload = _span_payload()
    payload["source_bound"] = True
    result = service.map_evidence_span(payload, source_layer_id="test_fixture")

    assert result.view is not None
    assert "support_type" not in result.view.model_dump()
    assert "source_bound" not in result.view.model_dump()


def test_unknown_scope_is_not_exposed_as_universal(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    payload = _scope_payload()
    payload.update(
        {
            "task_ids": [],
            "modalities": [],
            "observation_units": [],
            "scope_status": "unknown",
            "combination": "all_of",
        }
    )
    result = service.map_scope(payload, source_layer_id="test_fixture")

    assert result.view is not None
    assert result.view.scope_status == "unknown"
    assert result.view.qualifiers == ()


def test_representation_type_view_preserves_abstract_semantics(
    service: ScientificOntologyV2CompatibilityService,
    core_bundle: ConformanceBundle,
) -> None:
    source = core_bundle.representation_types[0]
    result = service.map_representation_type(source, source_layer_id="scientific_kg_v1_core")

    assert result.status == "COMPATIBLE_WITH_ADAPTER"
    assert result.view is not None
    assert result.view.representation_type_id == source.representation_type_id
    assert result.view.feature_namespace == source.feature_identity
    assert result.view.axes == tuple(source.axes)


def test_unsupported_reference_identity_cannot_fabricate_revision(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    requirement = Requirement(
        requirement_id="requirement:test:missing-reference",
        level="mandatory",
        reference_artifact_revision_ids=["reference-artifact-revision:missing:1"],
        scope_id="scope:test:compatibility",
    )
    result = service.map_requirement(
        requirement, reference_revisions={}, source_layer_id="test_fixture"
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes[0] == "REFERENCE_REVISION_NOT_AVAILABLE"
    assert result.view is None


def test_derived_relation_input_cannot_claim_authority(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.classify_relation(
        {"relation": "CAN_FEED", "classification": "AUTHORITATIVE_SOURCE"},
        source_layer_id="test_fixture",
    )
    assert result.view is not None
    assert result.view.classification == "DERIVED_PROJECTION"
    assert result.view.authoritative is False


def test_candidate_claim_cannot_become_trusted(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(),
        scope=_scope_payload(),
        source_layer_id="test_fixture",
        source_status="candidate_not_promoted",
    )
    assert isinstance(result.view, StatementRevisionView)
    assert result.view.source_governance_status == "candidate_not_promoted"
    assert result.view.trusted is False


def test_effect_description_cannot_gain_machine_authority(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(predicate="effect_description"),
        scope=_scope_payload(),
        source_layer_id="test_fixture",
    )
    relation = service.classify_relation(
        "effect_description", source_layer_id="test_fixture"
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes == ("EFFECT_DESCRIPTION_DISPLAY_ONLY",)
    assert relation.view is not None
    assert relation.view.classification == "UNRESOLVED"
    assert relation.view.authoritative is False


def test_current_core_records_repeat_deterministically(
    service: ScientificOntologyV2CompatibilityService,
    core_bundle: ConformanceBundle,
) -> None:
    claim = core_bundle.atomic_claims[0]
    scope = next(item for item in core_bundle.scopes if item.scope_id == claim.scope_id)
    first = service.map_atomic_claim(
        claim, scope=scope, source_layer_id="scientific_kg_v1_core"
    )
    second = service.map_atomic_claim(
        claim, scope=scope, source_layer_id="scientific_kg_v1_core"
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_real_v1_span_without_artifact_identity_is_visible_as_ambiguous(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    record = _jsonl(CORE_ROOT / "evidence_spans.jsonl")[0]
    result = service.map_evidence_span(
        record,
        source_layer_id="scientific_kg_v1_core",
        source_status="candidate_not_promoted",
    )
    assert result.status == "AMBIGUOUS_MAPPING"
    assert isinstance(result.view, EvidenceSpanCoreView)
    assert result.view.source_artifact_id is None
    assert "SOURCE_ARTIFACT_ID_UNAVAILABLE" in result.reason_codes


def test_evaluation_build_is_deterministic_and_does_not_mutate_source_data(
    tmp_path: Path,
) -> None:
    graph = (
        ROOT
        / "data"
        / "evidence_candidates"
        / "scientific_kg_v1_inventory"
        / "scientific_kg_v1_consolidated_graph.json"
    )
    before = hashlib.sha256(graph.read_bytes()).hexdigest()
    first = tmp_path / "first"
    second = tmp_path / "second"

    build(first, focused_tests="qualification", regression_tests="bounded")
    build(second, focused_tests="qualification", regression_tests="bounded")

    assert hashlib.sha256(graph.read_bytes()).hexdigest() == before
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_checked_in_evaluation_inventory_counts_and_hashes_are_consistent() -> None:
    output = ROOT / "data" / "evaluation" / "ontology_v2_compatibility_v1"
    counts = _json(output / "compatibility_counts.json")
    manifest = _json(output / "manifest.json")

    assert counts["atomic_claim_revision_total_all"] == 380
    assert sum(
        counts[key]
        for key in (
            "DIRECT_COMPATIBLE",
            "COMPATIBLE_WITH_ADAPTER",
            "AMBIGUOUS_MAPPING",
            "NOT_MAPPABLE",
            "DEFERRED",
        )
    ) == 380
    assert counts["evidence_spans_inspected"] == 170
    assert counts["evidence_core_views"] + counts["evidence_invalid"] == 170
    assert counts["evidence_normalized_fully_compatible"] == 0
    assert manifest["read_only"] is True
    assert manifest["scientific_content_generated"] is False
    assert all(
        hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
        for name, digest in manifest["artifacts"].items()
    )


def test_compatibility_service_is_not_automatically_wired_into_production_surfaces() -> None:
    protected = (
        ROOT / "app.py",
        ROOT / "agent" / "research_chat_service.py",
        ROOT / "engine" / "hybrid_retrieval.py",
        ROOT / "engine" / "scientific_kg_evidence.py",
        ROOT / "engine" / "scientific_kg_applicability.py",
        ROOT / "engine" / "capability_planner.py",
        ROOT / "engine" / "scientific_kg_admin.py",
        ROOT / "engine" / "scientific_knowledge_studio.py",
        ROOT / "core" / "representation_models.py",
        ROOT / "core" / "tool_contract_registry.py",
    )
    assert all(
        "scientific_ontology_v2_compatibility" not in path.read_text(encoding="utf-8")
        for path in protected
    )
