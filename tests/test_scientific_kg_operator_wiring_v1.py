from __future__ import annotations

import inspect

from engine.scientific_kg_evidence import ScientificKGEvidence, parse_scientific_query
from engine.scientific_subject_resolution import ScientificSubjectResolver


def adapter():
    return ScientificKGEvidence()


def test_exact_operator_revision_id():
    evidence = adapter()
    revision = evidence.operators[1]
    result = evidence.subject_resolver.resolve(revision.entity_id)
    assert result.status == "RESOLVED"
    assert result.selected_operator_revision_id == revision.entity_id
    assert "exact_operator_revision_id" in result.provenance


def test_exact_api_path():
    result = adapter().subject_resolver.resolve("scanpy.pp.pca input")
    assert result.status == "RESOLVED"
    assert result.selected_operator_id == "operator:scanpy.pp.pca"
    assert "registered_api_path" in result.provenance


def test_package_plus_operator():
    result = adapter().subject_resolver.resolve("Scanpy PCA input")
    assert result.status == "RESOLVED"
    assert result.selected_operator_id == "operator:scanpy.pp.pca"


def test_governed_existing_alias():
    evidence = adapter()
    parsed = parse_scientific_query("HVG input", extended=True)
    result = evidence.subject_resolver.resolve(
        "HVG input",
        parsed_operator_id=parsed["operator_id"],
    )
    assert result.status == "RESOLVED"
    assert "governed_existing_alias" in result.provenance


def test_method_to_one_operator():
    result = adapter().subject_resolver.resolve("principal component analysis input")
    assert result.status == "RESOLVED"
    assert result.resolved_method == "method:pca"


def test_method_to_multiple_operators_is_ambiguous():
    evidence = adapter()
    pca = next(item for item in evidence.operators if item.operator_id == "operator:scanpy.pp.pca")
    second = pca.model_copy(
        update={
            "entity_id": "operator-revision:other.pca:1.0.0:test",
            "operator_id": "operator:other.pca",
            "package_release_id": "package-release:other:1.0.0",
        }
    )
    resolver = ScientificSubjectResolver(
        entities=evidence.bundle.entities,
        operator_revisions=[pca, second],
    )
    result = resolver.resolve("principal component analysis input")
    assert result.status == "AMBIGUOUS"
    assert result.ambiguity_reason == "multiple_operator_candidates"


def test_explicit_version_selects_revision():
    evidence = adapter()
    pca = next(item for item in evidence.operators if item.operator_id == "operator:scanpy.pp.pca")
    second = pca.model_copy(
        update={
            "entity_id": "operator-revision:scanpy.pp.pca:1.12.0:test",
            "package_release_id": "package-release:scanpy:1.12.0",
        }
    )
    resolver = ScientificSubjectResolver(
        entities=evidence.bundle.entities,
        operator_revisions=[pca, second],
    )
    result = resolver.resolve("scanpy.pp.pca version 1.11.2", explicit_version="1.11.2")
    assert result.status == "RESOLVED"
    assert result.selected_operator_revision_id == pca.entity_id


def test_absent_version_with_multiple_revisions_is_ambiguous():
    evidence = adapter()
    pca = next(item for item in evidence.operators if item.operator_id == "operator:scanpy.pp.pca")
    second = pca.model_copy(
        update={
            "entity_id": "operator-revision:scanpy.pp.pca:1.12.0:test",
            "package_release_id": "package-release:scanpy:1.12.0",
        }
    )
    resolver = ScientificSubjectResolver(
        entities=evidence.bundle.entities,
        operator_revisions=[pca, second],
    )
    result = resolver.resolve("scanpy.pp.pca input")
    assert result.status == "AMBIGUOUS"
    assert result.ambiguity_reason == "multiple_operator_revisions_require_version"


def test_legacy_registry_identity_bridge():
    result = adapter().subject_resolver.resolve(
        "What input does this tool require?",
        subject_hints=["Harmony"],
    )
    assert result.status == "RESOLVED"
    assert result.selected_operator_id == "operator:harmony.RunHarmony"
    assert "legacy_registry_package_identity_bridge" in result.provenance


def test_unsupported_subject_is_unresolved():
    result = adapter().subject_resolver.resolve(
        "What does an unknown method output?",
        subject_hints=["UnknownTool"],
    )
    assert result.status == "UNRESOLVED"
    assert result.coverage_status == "UNKNOWN_SUBJECT"


def test_outside_direct_evidence_scope_is_explicit():
    result = adapter().subject_resolver.resolve(
        "What does this classifier output?",
        subject_hints=["CellTypist"],
    )
    assert result.status == "OUTSIDE_SCOPE"
    assert result.coverage_status == "OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE"
    assert not result.candidate_operator_revision_ids


def test_query_id_and_expected_operator_cannot_influence_resolver():
    parameters = inspect.signature(ScientificSubjectResolver.resolve).parameters
    assert "query_id" not in parameters
    assert "expected_operator" not in parameters
