from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
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
from eval.build_ontology_v2_compatibility_v1 import (
    CHAT_SURFACE_NODES,
    FOCUSED_REQUIRED_NODES,
    FOCUSED_SUITE_ID,
    REGRESSION_REQUIRED_NODES,
    REGRESSION_SUITE_ID,
    build,
    collect_assessments,
)
from eval.ontology_v2_test_evidence import record_junit_result, sha256_file


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
GRAPH_PATH = (
    ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_inventory"
    / "scientific_kg_v1_consolidated_graph.json"
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


def _predicate_scope_payload(*, scope_id: str = "scope:test:compatibility") -> dict:
    payload = _scope_payload()
    payload.update(
        {
            "scope_id": scope_id,
            "task_ids": [],
            "version_constraints": [
                {
                    "subject_id": "operator-revision:test:1",
                    "status": "exact",
                    "expression": "1.0.0",
                }
            ],
            "modalities": [],
            "observation_units": [],
            "combination": "all_of",
        }
    )
    return payload


def _property_scope_payload() -> dict:
    payload = _scope_payload()
    payload.update({"task_ids": [], "combination": "all_of"})
    return payload


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
) -> None:
    claim = AtomicClaimRevision.model_validate(_claim_payload())
    assessment = EvidenceAssessment(
        assessment_id="evidence-assessment:test:claim",
        claim_revision_id=claim.claim_revision_id,
        evidence_span_ids=["evidence-span:test:1"],
        stance="supports",
        subject_aligned=True,
        predicate_aligned=True,
        object_aligned=True,
        scope_alignment="aligned",
        rationale="Explicit compatibility fixture.",
    )

    result = service.map_atomic_claim(
        claim,
        scope=_predicate_scope_payload(),
        evidence_assessments=[assessment],
        source_layer_id="test_fixture",
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
    assert result.view.evidence_span_ids == tuple(assessment.evidence_span_ids)
    assert result.view.source_governance_status == "candidate_not_promoted"
    assert result.view.trusted is False
    with pytest.raises(ValidationError):
        result.view.statement_id = "statement:mutated"


def test_literal_object_is_preserved_but_datatype_ambiguity_is_visible(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(predicate="is_sparse", literal=True),
        scope=_property_scope_payload(),
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


def test_h01_wrong_rna_to_atac_scope_identity_fails_closed(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    wrong_scope = _property_scope_payload()
    wrong_scope.update({"scope_id": "scope:test:atac", "modalities": ["atac"]})
    result = service.map_atomic_claim(
        _claim_payload(), scope=wrong_scope, source_layer_id="test_fixture"
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes[0] == "SCOPE_IDENTITY_MISMATCH"
    assert result.view is None


@pytest.mark.parametrize("richer", [False, True])
def test_h01_same_or_richer_qualifiers_with_wrong_scope_id_fail_closed(
    service: ScientificOntologyV2CompatibilityService,
    richer: bool,
) -> None:
    wrong_scope = _predicate_scope_payload(scope_id="scope:test:wrong")
    if richer:
        wrong_scope["parameter_conditions"] = [
            {"parameter_id": "parameter:test", "operator": "equals", "values": ["x"]}
        ]
    result = service.map_atomic_claim(
        _claim_payload(), scope=wrong_scope, source_layer_id="test_fixture"
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes[0] == "SCOPE_IDENTITY_MISMATCH"


def test_h01_missing_expected_scope_is_ambiguous_and_exact_scope_succeeds(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    missing = service.map_atomic_claim(
        _claim_payload(), scope=None, source_layer_id="test_fixture"
    )
    exact = service.map_atomic_claim(
        _claim_payload(), scope=_predicate_scope_payload(), source_layer_id="test_fixture"
    )
    assert missing.status == "AMBIGUOUS_MAPPING"
    assert missing.reason_codes == ("SCOPE_RECORD_UNAVAILABLE",)
    assert exact.status == "DIRECT_COMPATIBLE"
    assert isinstance(exact.view, StatementRevisionView)
    assert exact.view.scope_ref == "scope:test:compatibility"


def test_h02_inline_only_qualifier_is_preserved_as_conjunction(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    scope = _property_scope_payload()
    scope["observation_units"] = []
    result = service.map_scope(
        scope,
        inline_qualifiers={"organism_taxon": ["NCBITaxon:9606"]},
        source_layer_id="test_fixture",
    )
    assert result.view is not None
    assert result.view.composition == "SHARED_AND_INLINE"
    assert {item.dimension for item in result.view.shared_qualifiers} == {"modality"}
    assert {item.dimension for item in result.view.inline_qualifiers} == {"organism_taxon"}
    assert {item.dimension for item in result.view.qualifiers} == {
        "modality",
        "organism_taxon",
    }


def test_h02_any_of_group_and_inline_conjunction_are_not_flattened(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    scope = _scope_payload()
    scope["task_ids"] = []
    scope["observation_units"] = []
    result = service.map_scope(
        scope,
        inline_qualifiers={"organism_taxon": ["NCBITaxon:9606"]},
        source_layer_id="test_fixture",
    )
    assert result.view is not None
    assert result.view.combination == "ANY_OF"
    assert result.view.composition == "SHARED_AND_INLINE"
    assert [item.dimension for item in result.view.shared_qualifiers] == ["modality"]
    assert [item.dimension for item in result.view.inline_qualifiers] == ["organism_taxon"]


def test_h02_duplicate_inline_value_is_deduplicated_in_shared_group(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    scope = _property_scope_payload()
    result = service.map_scope(
        scope,
        inline_qualifiers={"modality": ["rna", "rna"]},
        source_layer_id="test_fixture",
    )
    assert result.view is not None
    assert result.view.composition == "SHARED_ONLY"
    assert result.view.inline_qualifiers == ()
    modality = next(item for item in result.view.shared_qualifiers if item.dimension == "modality")
    assert modality.values_json == ('"rna"',)


def test_h02_atomic_claim_retains_distinct_inline_flavors_end_to_end(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    scope = _predicate_scope_payload()
    seurat = service.map_atomic_claim(
        _claim_payload(),
        scope=scope,
        inline_qualifiers={"flavor": ["seurat_v3"]},
        source_layer_id="test_fixture",
    )
    cell_ranger = service.map_atomic_claim(
        _claim_payload(),
        scope=scope,
        inline_qualifiers={"flavor": ["cell_ranger"]},
        source_layer_id="test_fixture",
    )
    shared_only = service.map_atomic_claim(
        _claim_payload(), scope=scope, source_layer_id="test_fixture"
    )

    assert all(result.status == "DIRECT_COMPATIBLE" for result in (seurat, cell_ranger, shared_only))
    assert all(isinstance(result.view, StatementRevisionView) for result in (seurat, cell_ranger, shared_only))
    assert seurat.view.inline_qualifiers[0].values_json == ('"seurat_v3"',)
    assert cell_ranger.view.inline_qualifiers[0].values_json == ('"cell_ranger"',)
    assert seurat.view.context_composition == "SHARED_SCOPE_AND_INLINE"
    assert shared_only.view.inline_qualifiers == ()
    assert shared_only.view.context_composition == "SHARED_SCOPE_ONLY"
    assert seurat.view.model_dump() != cell_ranger.view.model_dump()
    assert seurat.view.model_dump() != shared_only.view.model_dump()


def test_h02_atomic_claim_deduplicates_or_rejects_same_dimension_inline_context(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    scope = _predicate_scope_payload()
    shared_version = json.loads(
        service.map_scope(scope, source_layer_id="test_fixture")
        .view.shared_qualifiers[0]
        .values_json[0]
    )
    duplicate = service.map_atomic_claim(
        _claim_payload(),
        scope=scope,
        inline_qualifiers={"version_constraint": [shared_version, shared_version]},
        source_layer_id="test_fixture",
    )
    conflict_version = {**shared_version, "expression": "2.0.0"}
    conflict = service.map_atomic_claim(
        _claim_payload(),
        scope=scope,
        inline_qualifiers={"version_constraint": [conflict_version]},
        source_layer_id="test_fixture",
    )

    assert isinstance(duplicate.view, StatementRevisionView)
    assert duplicate.view.inline_qualifiers == ()
    assert duplicate.view.context_composition == "SHARED_SCOPE_ONLY"
    assert conflict.status == "AMBIGUOUS_MAPPING"
    assert "INLINE_SHARED_SCOPE_CONFLICT" in conflict.reason_codes
    assert conflict.view is None


def test_h02_atomic_claim_preserves_any_of_plus_inline_and_serialization(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    scope = _predicate_scope_payload()
    scope["combination"] = "any_of"
    result = service.map_atomic_claim(
        _claim_payload(),
        scope=scope,
        inline_qualifiers={"flavor": ["seurat_v3"]},
        source_layer_id="test_fixture",
    )
    reconstructed = type(result).model_validate_json(result.model_dump_json())

    assert isinstance(result.view, StatementRevisionView)
    assert result.view.scope_ref == scope["scope_id"]
    assert result.view.context_composition == "SHARED_SCOPE_AND_INLINE"
    assert result.view.inline_qualifiers[0].values_json == ('"seurat_v3"',)
    assert reconstructed == result
    assert reconstructed.view.inline_qualifiers == result.view.inline_qualifiers


def test_statement_supersession_same_family_revision_is_preserved(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(), scope=_predicate_scope_payload(), source_layer_id="test_fixture"
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
    assert first.view.predicate_classification == "DERIVED_PROJECTION"
    assert first.view.record_authority == "DERIVED_RECORD"
    assert first.view.trusted is False


def test_h03_candidate_authoritative_predicate_remains_candidate_record(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.classify_relation(
        {
            "graph_edge_id": "edge:test:candidate-implements",
            "predicate": "implements_method",
            "semantic_subject_id": "operator-revision:test:1",
            "semantic_object_id": "method:test",
            "status": "candidate_not_promoted",
        },
        source_layer_id="test_fixture",
        source_status="candidate_not_promoted",
    )
    assert result.status == "COMPATIBLE_WITH_ADAPTER"
    assert result.view is not None
    assert result.view.predicate_classification == "AUTHORITATIVE_LINK_TYPE"
    assert result.view.record_authority == "CANDIDATE_RECORD"
    assert result.view.trusted is False
    assert result.view.canonical is False


def test_h03_wrong_domain_authoritative_predicate_is_unresolved(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.classify_relation(
        {
            "graph_edge_id": "edge:test:wrong-domain",
            "predicate": "implements_method",
            "semantic_subject_id": "method:not-an-operator-revision",
            "semantic_object_id": "method:test",
        },
        source_layer_id="test_fixture",
        source_status="candidate_not_promoted",
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes == ("INVALID_RELATION_ENDPOINT_PAIR",)
    assert result.view is not None
    assert result.view.record_authority == "UNRESOLVED"
    assert result.view.trusted is False

    legacy_alias = service.classify_relation(
        {
            "graph_edge_id": "edge:test:wrong-domain-legacy-alias",
            "predicate": "IMPLEMENTS_METHOD",
            "semantic_subject_id": "method:not-an-operator-revision",
            "semantic_object_id": "method:test",
        },
        source_layer_id="test_fixture",
        source_status="candidate_not_promoted",
    )
    assert legacy_alias.status == "NOT_MAPPABLE"
    assert legacy_alias.reason_codes == ("INVALID_RELATION_ENDPOINT_PAIR",)
    assert legacy_alias.view is not None
    assert legacy_alias.view.record_authority == "UNRESOLVED"


def test_m01_entity_predicate_and_typed_scalar_property_constraints(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    entity = service.map_atomic_claim(
        _claim_payload(), scope=_predicate_scope_payload(), source_layer_id="test_fixture"
    )
    scalar = service.map_atomic_claim(
        _claim_payload(predicate="is_sparse", literal=True),
        scope=_property_scope_payload(),
        literal_datatype="boolean",
        source_layer_id="test_fixture",
    )
    wrong_object = _claim_payload(predicate="is_sparse")
    wrong_object["subject_id"] = "representation-type:test"
    invalid = service.map_atomic_claim(
        wrong_object,
        scope=_property_scope_payload(),
        source_layer_id="test_fixture",
    )
    assert isinstance(entity.view, StatementRevisionView)
    assert scalar.status == "DIRECT_COMPATIBLE"
    assert isinstance(scalar.view, StatementRevisionView)
    assert scalar.view.literal_datatype == "boolean"
    assert invalid.status == "NOT_MAPPABLE"
    assert invalid.reason_codes[0] == "SCALAR_PROPERTY_REQUIRES_LITERAL_OBJECT"


def test_m01_disallowed_qualifier_is_reported_not_dropped(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(), scope=_scope_payload(), source_layer_id="test_fixture"
    )
    assert result.status == "AMBIGUOUS_MAPPING"
    assert result.reason_codes[0] == "PREDICATE_SCOPE_DIMENSION_NOT_ALLOWED"
    assert set(result.reason_codes[1:]) == {"modality", "observation_unit", "task"}
    assert result.view is None


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
    assert result.view.predicate_classification == "DERIVED_PROJECTION"
    assert result.view.record_authority == "DERIVED_RECORD"
    assert result.view.trusted is False


def test_candidate_claim_cannot_become_trusted(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_atomic_claim(
        _claim_payload(),
        scope=_predicate_scope_payload(),
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
    assert relation.view.predicate_classification == "UNRESOLVED_PREDICATE"
    assert relation.view.record_authority == "UNRESOLVED"
    assert relation.view.trusted is False


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


def test_m02_all_requirement_views_use_requirement_identity(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    graph = _json(GRAPH_PATH)
    constraints_by_layer: dict[str, set[str]] = {}
    for node in graph["nodes"]:
        if node["record_type"] == "RepresentationConstraint":
            constraints_by_layer.setdefault(node["layer_id"], set()).add(node["record_id"])
    views = []
    for node in graph["nodes"]:
        if node["record_type"] != "Requirement":
            continue
        result = service.map_requirement(
            node["record"],
            known_constraint_ids=constraints_by_layer[node["layer_id"]],
            source_layer_id=node["layer_id"],
        )
        if result.view is not None:
            views.append((node, result.view))
    assert len(views) == 102
    assert all(view.provenance.source_record_id == node["record_id"] for node, view in views)
    assert all(view.provenance.source_record_id.startswith("requirement:") for _, view in views)


def test_m02_all_derived_relation_views_retain_exact_edge_identity(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    graph = _json(GRAPH_PATH)
    derived = []
    for edge in graph["edges"]:
        result = service.classify_relation(
            edge,
            source_layer_id=edge["layer_id"],
            source_status=edge.get("status"),
        )
        if result.view is not None and result.view.predicate_classification == "DERIVED_PROJECTION":
            derived.append((edge, result.view))
    assert len(derived) == 331
    assert all(
        view.provenance.source_record_id == edge["graph_edge_id"] for edge, view in derived
    )
    repeated = service.classify_relation(
        graph["edges"][0],
        source_layer_id=graph["edges"][0]["layer_id"],
        source_status=graph["edges"][0].get("status"),
    )
    assert repeated.view is not None
    assert repeated.view.provenance.source_record_id == graph["edges"][0]["graph_edge_id"]


def test_m03_evidence_core_view_excludes_governance_status(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    result = service.map_evidence_span(
        _span_payload(),
        source_layer_id="test_fixture",
        source_status="trusted_source_evidence",
    )
    assert isinstance(result.view, EvidenceSpanCoreView)
    serialized_view = json.dumps(result.view.model_dump(mode="json"), sort_keys=True)
    assert "trusted_source_evidence" not in serialized_view
    assert "source_status" not in result.view.provenance.model_dump(mode="json")
    assert result.diagnostics is not None
    assert result.diagnostics.legacy_source_status == "trusted_source_evidence"


def test_m04_evidence_binding_rejects_key_to_wrong_span_object(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    wrong_payload = _span_payload()
    wrong_payload["evidence_span_id"] = "evidence-span:test:other"
    wrong = service.map_evidence_span(wrong_payload, source_layer_id="test_fixture")
    assessment = EvidenceAssessment(
        assessment_id="evidence-assessment:test:mismatch",
        claim_revision_id="claim-revision:test:compatibility:1",
        evidence_span_ids=["evidence-span:test:1"],
        stance="supports",
        subject_aligned=True,
        predicate_aligned=True,
        object_aligned=True,
        scope_alignment="aligned",
        rationale="The mapping key intentionally points to a different span object.",
    )
    result = service.map_evidence_assessment(
        assessment,
        statement_revision_ids={assessment.claim_revision_id},
        evidence_spans={"evidence-span:test:1": wrong},
        source_layer_id="test_fixture",
    )
    assert result.status == "NOT_MAPPABLE"
    assert result.reason_codes[0] == "EVIDENCE_SPAN_NOT_AVAILABLE"
    assert result.view is None


def test_m04_two_assessments_for_one_statement_are_collected_independently() -> None:
    base = {
        "claim_revision_id": "claim-revision:test:compatibility:1",
        "evidence_span_ids": ["evidence-span:test:1"],
        "object_aligned": True,
        "predicate_aligned": True,
        "rationale": "Independent assessment.",
        "review_decision_ids": [],
        "schema_version": "sckg-evidence-assessment-v1.1",
        "scope_alignment": "aligned",
        "subject_aligned": True,
    }
    first = {**base, "assessment_id": "evidence-assessment:test:support", "stance": "supports"}
    second = {**base, "assessment_id": "evidence-assessment:test:refute", "stance": "refutes"}
    edges = [
        {"layer_id": "test", "provenance": {"evidence_assessment": first}},
        {"layer_id": "test", "provenance": {"evidence_assessment": second}},
    ]
    by_identity, by_claim = collect_assessments(edges)
    assert set(by_identity) == {
        ("test", "evidence-assessment:test:support"),
        ("test", "evidence-assessment:test:refute"),
    }
    assert len(by_claim[("test", "claim-revision:test:compatibility:1")]) == 2


def test_m04_support_and_refutation_coexist_without_trust_aggregation(
    service: ScientificOntologyV2CompatibilityService,
) -> None:
    span = service.map_evidence_span(_span_payload(), source_layer_id="test_fixture")
    results = []
    for suffix, stance in (("support", "supports"), ("refute", "refutes")):
        assessment = EvidenceAssessment(
            assessment_id=f"evidence-assessment:test:{suffix}",
            claim_revision_id="claim-revision:test:compatibility:1",
            evidence_span_ids=["evidence-span:test:1"],
            stance=stance,
            subject_aligned=True,
            predicate_aligned=True,
            object_aligned=True,
            scope_alignment="aligned",
            rationale="Independent aligned assessment.",
        )
        results.append(
            service.map_evidence_assessment(
                assessment,
                statement_revision_ids={assessment.claim_revision_id},
                evidence_spans={"evidence-span:test:1": span},
                source_layer_id="test_fixture",
            )
        )
    assert [result.view.support_type for result in results] == ["DIRECT_SUPPORT", "REFUTES"]
    assert all(result.view.trusted is False for result in results)


def _test_evidence_declaration(
    root: Path,
    *,
    name: str,
    suite_id: str,
    revision: str,
    node_ids: set[str],
    command: list[str] | None = None,
    outcomes: dict[str, str] | None = None,
) -> dict:
    evidence_dir = root / "evidence"
    junit_path = evidence_dir / f"{name}.junit.xml"
    result_path = evidence_dir / f"{name}.json"
    testcase_outcomes = {node_id: (outcomes or {}).get(node_id, "PASSED") for node_id in node_ids}
    suite = ET.Element(
        "testsuite",
        name="pytest",
        tests=str(len(node_ids)),
        failures=str(sum(outcome == "FAILED" for outcome in testcase_outcomes.values())),
        errors=str(sum(outcome == "ERROR" for outcome in testcase_outcomes.values())),
        skipped=str(sum(outcome == "SKIPPED" for outcome in testcase_outcomes.values())),
    )
    for node_id in sorted(node_ids):
        module, test_name = node_id.split("::", 1)
        case = ET.SubElement(
            suite,
            "testcase",
            classname=module.removesuffix(".py").replace("/", "."),
            name=test_name,
        )
        outcome = testcase_outcomes[node_id]
        if outcome != "PASSED":
            ET.SubElement(case, outcome.casefold() if outcome != "FAILED" else "failure")
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper = ET.Element("testsuites")
    wrapper.append(suite)
    ET.ElementTree(wrapper).write(junit_path, encoding="utf-8", xml_declaration=True)
    actual_command = command or [f"pytest {name}"]
    result = record_junit_result(
        junit_path=junit_path,
        output_path=result_path,
        repository_root=root,
        suite_id=suite_id,
        tested_revision=revision,
        command=actual_command,
    )
    return {
        "status": "PASS",
        "suite_id": suite_id,
        "passed": result["passed"],
        "failed": result["failed"],
        "errors": result["errors"],
        "skipped": result["skipped"],
        "command": actual_command,
        "tested_revision": revision,
        "result_artifact": str(result_path.relative_to(root)),
        "result_artifact_sha256": sha256_file(result_path),
    }


def _mutate_junit_and_reseal_result(
    root: Path,
    declaration: dict,
    *,
    node_id: str,
    outcome_element: str | None,
    header_updates: dict[str, str] | None = None,
) -> dict:
    result_path = root / declaration["result_artifact"]
    result = _json(result_path)
    junit_path = root / result["junit_artifact"]
    tree = ET.parse(junit_path)
    module, test_name = node_id.split("::", 1)
    classname = module.removesuffix(".py").replace("/", ".")
    testcase = next(
        case
        for case in tree.getroot().iter("testcase")
        if case.attrib.get("classname") == classname and case.attrib.get("name") == test_name
    )
    if outcome_element is not None:
        ET.SubElement(testcase, outcome_element)
    suite = next(tree.getroot().iter("testsuite"))
    suite.attrib.update(header_updates or {})
    tree.write(junit_path, encoding="utf-8", xml_declaration=True)
    result["junit_artifact_sha256"] = sha256_file(junit_path)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**declaration, "result_artifact_sha256": sha256_file(result_path)}


def test_m05_failed_not_run_and_unverified_declarations_cannot_emit_pass(
    tmp_path: Path,
) -> None:
    manifest = build(
        tmp_path / "failed", focused_tests="FAILED", regression_tests="FAILED"
    )
    summary = _json(tmp_path / "failed" / "test_summary.json")
    assert manifest["status"] != "PASS"
    assert summary["focused_tests"]["declared_status"] == "FAIL"
    assert summary["focused_tests"]["verification_status"] == "FAIL"
    assert summary["regression_tests"]["verification_status"] == "FAIL"


def test_m05_false_command_failed_text_and_missing_artifact_are_unverified(
    tmp_path: Path,
) -> None:
    revision = "a" * 40
    declarations = (
        {
            "status": "PASS",
            "suite_id": FOCUSED_SUITE_ID,
            "passed": 1,
            "command": ["false"],
            "tested_revision": revision,
        },
        {
            "status": "PASS",
            "suite_id": FOCUSED_SUITE_ID,
            "passed": 1,
            "command": ["pytest"],
            "tested_revision": revision,
            "evidence": "FAILED",
        },
        {
            "status": "PASS",
            "suite_id": FOCUSED_SUITE_ID,
            "passed": 1,
            "command": ["pytest"],
            "tested_revision": revision,
            "result_artifact": "missing.json",
            "result_artifact_sha256": "0" * 64,
        },
    )
    for index, declaration in enumerate(declarations):
        output = tmp_path / f"case-{index}"
        manifest = build(
            output,
            focused_tests=declaration,
            evaluated_revision=revision,
            evidence_root=tmp_path,
        )
        summary = _json(output / "test_summary.json")
        assert manifest["status"] != "PASS"
        assert summary["focused_tests"]["verification_status"] == "UNVERIFIED"


def test_m05_wrong_hash_revision_counts_suite_and_tamper_are_unverified(
    tmp_path: Path,
) -> None:
    revision = "b" * 40
    base = _test_evidence_declaration(
        tmp_path,
        name="focused",
        suite_id=FOCUSED_SUITE_ID,
        revision=revision,
        node_ids={
            "tests/test_scientific_ontology_v2_compatibility.py::test_h01_missing_expected_scope_is_ambiguous_and_exact_scope_succeeds"
        },
    )
    wrong_suite_artifact = _test_evidence_declaration(
        tmp_path,
        name="wrong-suite",
        suite_id="wrong-suite",
        revision=revision,
        node_ids={
            "tests/test_scientific_ontology_v2_compatibility.py::test_h01_missing_expected_scope_is_ambiguous_and_exact_scope_succeeds"
        },
    )
    wrong_suite = {
        **wrong_suite_artifact,
        "suite_id": FOCUSED_SUITE_ID,
    }
    false_command = _test_evidence_declaration(
        tmp_path,
        name="false-command",
        suite_id=FOCUSED_SUITE_ID,
        revision=revision,
        node_ids=FOCUSED_REQUIRED_NODES,
        command=["false"],
    )
    cases = (
        {**base, "result_artifact_sha256": "0" * 64},
        {**base, "tested_revision": "c" * 40},
        {**base, "failed": 1},
        {**base, "passed": 0},
        wrong_suite,
        false_command,
    )
    for index, declaration in enumerate(cases):
        output = tmp_path / f"invalid-{index}"
        manifest = build(
            output,
            focused_tests=declaration,
            evaluated_revision=revision,
            evidence_root=tmp_path,
        )
        summary = _json(output / "test_summary.json")
        assert manifest["status"] != "PASS"
        assert summary["focused_tests"]["verification_status"] == "UNVERIFIED"

    tampered = dict(base)
    result_path = tmp_path / tampered["result_artifact"]
    result_path.write_text(result_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    manifest = build(
        tmp_path / "tampered",
        focused_tests=tampered,
        evaluated_revision=revision,
        evidence_root=tmp_path,
    )
    assert manifest["status"] != "PASS"
    assert (
        _json(tmp_path / "tampered" / "test_summary.json")["focused_tests"][
            "verification_status"
        ]
        == "UNVERIFIED"
    )


def test_m05_verified_artifacts_gate_checkpoint_and_chat_surfaces(tmp_path: Path) -> None:
    revision = "d" * 40
    focused = _test_evidence_declaration(
        tmp_path,
        name="focused-positive",
        suite_id=FOCUSED_SUITE_ID,
        revision=revision,
        node_ids=FOCUSED_REQUIRED_NODES,
    )
    regression = _test_evidence_declaration(
        tmp_path,
        name="regression-positive",
        suite_id=REGRESSION_SUITE_ID,
        revision=revision,
        node_ids=REGRESSION_REQUIRED_NODES,
    )
    manifest = build(
        tmp_path / "positive",
        focused_tests=focused,
        regression_tests=regression,
        evaluated_revision=revision,
        evidence_root=tmp_path,
    )
    summary = _json(tmp_path / "positive" / "test_summary.json")
    assert manifest["status"] == "PASS"
    assert summary["focused_tests"]["verification_status"] == "PASS"
    assert summary["regression_tests"]["verification_status"] == "PASS"
    assert all(summary[surface] == "PASS" for surface in CHAT_SURFACE_NODES)

    retrieval_only = _test_evidence_declaration(
        tmp_path,
        name="regression-retrieval-only",
        suite_id=REGRESSION_SUITE_ID,
        revision=revision,
        node_ids=CHAT_SURFACE_NODES["chat_retrieval"],
    )
    build(
        tmp_path / "partial-chat",
        focused_tests=focused,
        regression_tests=retrieval_only,
        evaluated_revision=revision,
        evidence_root=tmp_path,
    )
    partial = _json(tmp_path / "partial-chat" / "test_summary.json")
    assert partial["chat_retrieval"] == "UNVERIFIED"
    assert partial["chat_runtime"] == "UNVERIFIED"


def test_m05_failure_node_with_false_zero_header_is_rejected(tmp_path: Path) -> None:
    revision = "e" * 40
    runtime_node = next(iter(CHAT_SURFACE_NODES["chat_runtime"]))
    declaration = _test_evidence_declaration(
        tmp_path,
        name="regression-hidden-failure",
        suite_id=REGRESSION_SUITE_ID,
        revision=revision,
        node_ids=REGRESSION_REQUIRED_NODES,
    )
    declaration = _mutate_junit_and_reseal_result(
        tmp_path,
        declaration,
        node_id=runtime_node,
        outcome_element="failure",
    )
    build(
        tmp_path / "hidden-failure",
        regression_tests=declaration,
        evaluated_revision=revision,
        evidence_root=tmp_path,
    )
    summary = _json(tmp_path / "hidden-failure" / "test_summary.json")
    assert summary["regression_tests"]["verification_status"] == "UNVERIFIED"
    assert summary["chat_runtime"] == "UNVERIFIED"


def test_m05_required_skipped_or_error_node_cannot_cover_chat(tmp_path: Path) -> None:
    revision = "f" * 40
    runtime_node = next(iter(CHAT_SURFACE_NODES["chat_runtime"]))
    for outcome in ("SKIPPED", "ERROR"):
        declaration = _test_evidence_declaration(
            tmp_path,
            name=f"regression-runtime-{outcome.casefold()}",
            suite_id=REGRESSION_SUITE_ID,
            revision=revision,
            node_ids=REGRESSION_REQUIRED_NODES,
            outcomes={runtime_node: outcome},
        )
        build(
            tmp_path / outcome.casefold(),
            regression_tests=declaration,
            evaluated_revision=revision,
            evidence_root=tmp_path,
        )
        summary = _json(tmp_path / outcome.casefold() / "test_summary.json")
        result = _json(tmp_path / declaration["result_artifact"])
        assert runtime_node not in result["verified_node_ids"]
        assert result["testcase_outcomes"] == sorted(
            result["testcase_outcomes"], key=lambda item: item["node_id"]
        )
        assert next(
            item["outcome"]
            for item in result["testcase_outcomes"]
            if item["node_id"] == runtime_node
        ) == outcome
        assert summary["regression_tests"]["verification_status"] != "PASS"
        assert summary["chat_runtime"] == "UNVERIFIED"


def test_m05_nonrequired_skipped_node_is_not_verified_but_suite_can_pass(
    tmp_path: Path,
) -> None:
    revision = "1" * 40
    optional_node = "tests/test_optional_evidence.py::test_optional"
    declaration = _test_evidence_declaration(
        tmp_path,
        name="focused-optional-skip",
        suite_id=FOCUSED_SUITE_ID,
        revision=revision,
        node_ids=FOCUSED_REQUIRED_NODES | {optional_node},
        outcomes={optional_node: "SKIPPED"},
    )
    build(
        tmp_path / "optional-skip",
        focused_tests=declaration,
        evaluated_revision=revision,
        evidence_root=tmp_path,
    )
    summary = _json(tmp_path / "optional-skip" / "test_summary.json")
    assert summary["focused_tests"]["verification_status"] == "PASS"
    assert optional_node not in summary["focused_tests"]["verified_node_ids"]


def test_m05_junit_header_total_mismatch_is_rejected(tmp_path: Path) -> None:
    revision = "2" * 40
    node_id = next(iter(FOCUSED_REQUIRED_NODES))
    declaration = _test_evidence_declaration(
        tmp_path,
        name="focused-header-mismatch",
        suite_id=FOCUSED_SUITE_ID,
        revision=revision,
        node_ids=FOCUSED_REQUIRED_NODES,
    )
    declaration = _mutate_junit_and_reseal_result(
        tmp_path,
        declaration,
        node_id=node_id,
        outcome_element=None,
        header_updates={"tests": str(len(FOCUSED_REQUIRED_NODES) + 1)},
    )
    build(
        tmp_path / "header-mismatch",
        focused_tests=declaration,
        evaluated_revision=revision,
        evidence_root=tmp_path,
    )
    summary = _json(tmp_path / "header-mismatch" / "test_summary.json")
    assert summary["focused_tests"]["verification_status"] == "UNVERIFIED"


def test_evaluation_build_is_deterministic_and_does_not_mutate_source_data(
    tmp_path: Path,
) -> None:
    graph = GRAPH_PATH
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
    summary = _json(output / "mapping_summary.json")
    unresolved = _json(output / "unresolved_mappings.json")["mappings"]

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
    assert counts["evidence_missing_artifact_id"] == 141
    assert counts["evidence_missing_revision_id"] == 90
    assert counts["evidence_hash_rejected"] == 29
    assert summary["atomic_claims"]["status_counts"] == {
        "AMBIGUOUS_MAPPING": 317,
        "COMPATIBLE_WITH_ADAPTER": 0,
        "DEFERRED": 0,
        "DIRECT_COMPATIBLE": 0,
        "NOT_MAPPABLE": 63,
    }
    assert summary["relations"]["predicate_record_authority_counts"] == {
        "AUTHORITATIVE_LINK_TYPE + CANDIDATE_RECORD": 1099,
        "AUTHORITATIVE_LINK_TYPE + UNRESOLVED": 83,
        "DERIVED_PROJECTION + DERIVED_RECORD": 331,
        "UNRESOLVED_PREDICATE + UNRESOLVED": 916,
    }
    atomic_primary_reasons: dict[str, int] = {}
    for item in unresolved:
        if item["category"] != "AtomicClaimRevision":
            continue
        reason = item["reason_codes"][0]
        atomic_primary_reasons[reason] = atomic_primary_reasons.get(reason, 0) + 1
    assert atomic_primary_reasons == {
        "CLAIM_SCOPE_NOT_COMPATIBLE": 19,
        "INVALID_STATEMENT_ENDPOINT_PAIR": 4,
        "KNOWN_NON_STATEMENT_RELATION": 198,
        "PREDICATE_SCOPE_DIMENSION_NOT_ALLOWED": 100,
        "UNKNOWN_PREDICATE": 59,
    }
    hash_rejections = [
        item
        for item in unresolved
        if item["category"] == "EvidenceSpan"
        and item["reason_codes"][0] == "EVIDENCE_TEXT_HASH_MISMATCH"
    ]
    assert len(hash_rejections) == 29
    assert {item["layer_id"] for item in hash_rejections} == {"content_expansion_v1"}
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
