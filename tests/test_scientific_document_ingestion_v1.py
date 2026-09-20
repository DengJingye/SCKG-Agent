from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ingestion.scientific_documents.models import BlockType, FinalDisposition, PropositionType, ScopeValueStatus
from ingestion.scientific_documents.pipeline import ScientificDocumentIngestionService
from ingestion.scientific_documents.pipeline import _reconstruct
from ingestion.scientific_documents.reporting import regression_checks


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/scientific_document_ingestion/synthetic_manual_pages.json"
SOUPX_SUMMARY = ROOT / "data/evaluation/scientific_document_ingestion_v1/summary.json"


def _run():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return ScientificDocumentIngestionService(ROOT).run_pages(
        filename=fixture["filename"],
        pdf_sha256=fixture["pdf_sha256"],
        pages=fixture["pages"],
        created_at="2026-09-21T00:00:00Z",
    )


def test_layout_classification_filters_toc_headers_usage_and_examples() -> None:
    result = _run()
    packets = result["packets"]
    for block_type in (BlockType.TOC, BlockType.HEADER_FOOTER, BlockType.USAGE, BlockType.EXAMPLES_CODE):
        rows = [packet for packet in packets if packet.block_type == block_type]
        assert rows
        assert all(packet.final_disposition == FinalDisposition.DROPPED for packet in rows)
        assert all(packet.raw_proposition is None and packet.canonical_statement is None for packet in rows)
    assert any("Index 2" in packet.raw_block for packet in packets if packet.block_type == BlockType.TOC)


def test_reconstruction_dehyphenates_only_line_break_hyphens_and_keeps_map() -> None:
    result = _run()
    block = next(item for item in result["reconstructed_blocks"] if "contamina-\ntion" in item.raw_text)
    assert "contamination" in block.normalized_text
    assert block.dehyphenation_count == 1
    assert any(item.operation == "DEHYPHENATED" for item in block.provenance_map)
    assert _reconstruct("nU-\nMIs")[0] == "nUMIs"
    assert _reconstruct("RNA-\nseq")[0] == "RNA-seq"


def test_truncated_proposition_is_abstained_before_canonicalization() -> None:
    packets = _run()["packets"]
    row = next(packet for packet in packets if packet.raw_proposition and packet.raw_proposition.text.endswith("and"))
    assert row.raw_proposition.is_complete is False
    assert row.final_disposition == FinalDisposition.ABSTAINED
    assert row.canonical_statement is None


def test_exact_evidence_offsets_resolve_in_the_immutable_page_stream() -> None:
    result = _run()
    pages = result["page_streams"]
    for packet in result["packets"]:
        span = packet.evidence_span
        if span is None:
            continue
        assert pages[span.page - 1][span.page_start_offset : span.page_end_offset] == span.exact_text
        assert hashlib.sha256(span.exact_text.encode("utf-8")).hexdigest() == span.content_hash


def test_return_value_is_structural_output_binding_not_scientific_statement() -> None:
    packets = _run()["packets"]
    row = next(
        packet
        for packet in packets
        if packet.raw_proposition
        and packet.raw_proposition.proposition_type == PropositionType.RETURN_VALUE
        and packet.raw_proposition.operator_name == "adjustCounts"
    )
    assert row.canonical_statement.canonical_kind == "STRUCTURAL_OUTPUT_BINDING"
    assert row.canonical_statement.predicate == "output_type"
    assert row.canonical_statement.subject_id == "output-port:v1-core:soupx:soupx__adjustcounts:output"
    assert row.canonical_statement.object_id == "representation-type:corrected_counts"
    assert row.canonical_statement.is_scientific_statement is False
    assert row.candidate_subgraph.relation_kind == "STRUCTURAL_RELATION"
    assert row.candidate_subgraph.statement_revision_id is None
    assert row.candidate_subgraph.evidence_assessment_id is None
    assert not (
        {node.record_type for node in row.candidate_subgraph.nodes}
        & {"ScientificStatement", "StatementRevision", "EvidenceAssessment"}
    )
    assert row.final_disposition == FinalDisposition.CANDIDATE_READY


def test_demo_recovery_has_four_distinct_registry_conformant_ready_candidates() -> None:
    ready = [
        packet
        for packet in _run()["packets"]
        if packet.final_disposition == FinalDisposition.CANDIDATE_READY
    ]
    spo = {
        (
            packet.canonical_statement.subject_id,
            packet.canonical_statement.predicate,
            packet.canonical_statement.object_id,
        )
        for packet in ready
    }
    assert {
        (
            "operator-revision:soupx.soupx__adjustcounts:1.6.2",
            "revision_of",
            "operator:soupx.soupx__adjustcounts",
        ),
        (
            "operator-revision:soupx.soupx__adjustcounts:1.6.2",
            "implements_method",
            "method:ambient_count_correction",
        ),
        (
            "operator-revision:soupx.soupx__adjustcounts:1.6.2",
            "supports_task",
            "task:ambient_rna_removal",
        ),
        (
            "output-port:v1-core:soupx:soupx__adjustcounts:output",
            "output_type",
            "representation-type:corrected_counts",
        ),
        (
            "operator-revision:soupx.soupx__adjustcounts:1.6.2",
            "has_requirement",
            "requirement:v1-core:soupx:soupx__adjustcounts:input2",
        ),
    } <= spo
    assert len(spo) >= 5
    for packet in ready:
        assert packet.candidate_subgraph is not None
        assert packet.candidate_subgraph.schema_conformance.valid is True
        assert packet.validation_report.structurally_conformant is True
        if packet.canonical_statement.predicate in {"implements_method", "supports_task", "has_requirement"}:
            assert packet.canonical_statement.qualifiers["software_version"] == {
                "subject_id": "operator-revision:soupx.soupx__adjustcounts:1.6.2",
                "status": "exact",
                "expression": "1.6.2",
            }


def test_scientific_candidates_materialize_the_frozen_statement_and_evidence_chain() -> None:
    scientific = [
        packet
        for packet in _run()["packets"]
        if packet.candidate_subgraph is not None
        and packet.candidate_subgraph.relation_kind == "SCIENTIFIC_STATEMENT"
    ]
    assert scientific
    expected_nodes = {
        "ScientificStatement",
        "StatementRevision",
        "EvidenceAssessment",
        "EvidenceSpan",
        "SourceWork",
        "SourceRevision",
        "SourceArtifact",
    }
    expected_links = {
        "revision_of",
        "assesses_statement",
        "uses_evidence",
        "span_in_revision",
        "span_in_artifact",
        "artifact_of",
    }
    for packet in scientific:
        graph = packet.candidate_subgraph
        assert graph.schema_conformance.valid is True
        assert {node.record_type for node in graph.nodes} >= expected_nodes
        assert {link.predicate for link in graph.links} >= expected_links
        revision = next(node.record for node in graph.nodes if node.record_type == "StatementRevision")
        assessment = next(node.record for node in graph.nodes if node.record_type == "EvidenceAssessment")
        assert revision["statement_revision_id"] == graph.statement_revision_id
        assert revision["subject_id"] == graph.primary_subject_id
        assert revision["predicate"] == graph.primary_predicate
        assert revision["object_id"] == graph.primary_object_id
        assert revision["scope_status"] == packet.scope.core_scope_status
        assert assessment["statement_revision_id"] == graph.statement_revision_id
        assert assessment["evidence_span_id"] == packet.evidence_span.evidence_span_id
        assert assessment["status"] == "draft"
        assert assessment["support_type"] == "PARTIAL_SUPPORT"


def test_parameter_preserves_operator_parameter_and_version_context_without_fuzzy_merge() -> None:
    packets = _run()["packets"]
    row = next(
        packet
        for packet in packets
        if packet.raw_proposition and packet.raw_proposition.parameter_name == "method"
    )
    assert row.raw_proposition.operator_name == "adjustCounts"
    assert row.canonical_statement.predicate == "has_parameter"
    assert row.canonical_statement.object_record["owner_operator_ref"] == "operator:soupx.soupx__adjustcounts"
    assert row.canonical_statement.object_record["value_domain"] == {
        "datatype": "string",
        "allowed_values": ["subtraction", "soupOnly"],
    }
    assert {entity.context_role for entity in row.linked_entities} == {"operator", "parameter"}
    assert all(entity.fuzzy_merge_used is False for entity in row.linked_entities)
    version = next(value for value in row.scope.values if value.dimension == "method_operator_version")
    assert version.value == "1.6.2"
    assert version.status == ScopeValueStatus.SOURCE_CONTEXT
    assert version.provenance_ref == row.source.source_revision_id
    assert row.final_disposition == FinalDisposition.NEEDS_REVIEW
    assert row.candidate_subgraph.schema_conformance.valid is True
    assert any(
        node.record_type == "ParameterDefinition"
        and node.record_id == row.canonical_statement.object_id
        for node in row.candidate_subgraph.nodes
    )


def test_unexpressible_estimated_or_specified_condition_becomes_evidence_gap() -> None:
    rows = [
        packet
        for packet in _run()["packets"]
        if packet.raw_proposition
        and packet.raw_proposition.proposition_type == PropositionType.CONDITION
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row.final_disposition == FinalDisposition.EVIDENCE_ONLY
    assert row.canonical_statement is None
    assert len(row.evidence_gaps) == 1
    gap = row.evidence_gaps[0]
    assert gap.gap_type == "ONTOLOGY_EXPRESSIVITY"
    assert gap.evidence_span_id == row.evidence_span.evidence_span_id
    assert gap.source_revision_id == row.source.source_revision_id
    assert "when=[]" in gap.missing_contract
    assert "specified alternative" in gap.missing_contract
    assert gap.id == gap.evidence_gap_id
    assert gap.schema_version == "sckg-ontology-core-5c-design-v1"
    assert gap.ontology_version == "2.0.0-core-review.1"
    assert "cannot be emitted" in gap.impact


def test_unknown_scope_is_not_hallucinated_and_has_explicit_no_provenance_state() -> None:
    for packet in _run()["packets"]:
        if packet.scope is None:
            continue
        dimensions = {value.dimension: value for value in packet.scope.values}
        assert dimensions["organism"].status == ScopeValueStatus.UNKNOWN
        assert dimensions["study_design"].status == ScopeValueStatus.UNKNOWN
        assert dimensions["organism"].value is None
        assert dimensions["study_design"].value is None
        assert packet.scope.hallucinated_value_count == 0


def test_ready_candidates_never_use_whole_segment_evidence() -> None:
    result = _run()
    ready = [packet for packet in result["packets"] if packet.final_disposition == FinalDisposition.CANDIDATE_READY]
    assert ready
    assert all(packet.evidence_span and not packet.evidence_span.whole_segment for packet in ready)
    assert result["summary"]["unbounded_ready_candidates"] == 0


def test_governance_is_pending_candidate_and_never_trusted_or_executable() -> None:
    for packet in _run()["packets"]:
        assert packet.governance.model_dump() == {
            "human_review_status": "pending",
            "knowledge_status": "candidate",
            "trusted": False,
            "production_retrieval_eligible": False,
            "execution_authorized": False,
        }


def test_synthetic_regression_checks_cover_all_quality_gates() -> None:
    checks = regression_checks(_run())
    assert checks["soupx_regression"] is True, {key: value for key, value in checks.items() if not value}


def test_hash_gate_rejects_wrong_fixture_before_pdf_parsing(tmp_path: Path) -> None:
    path = tmp_path / "fixture.pdf"
    path.write_bytes(b"not parsed because hash must fail first")
    with pytest.raises(ValueError, match="PDF_SHA256_MISMATCH"):
        ScientificDocumentIngestionService(ROOT).run_pdf(path, expected_sha256="0" * 64)


def test_frozen_registry_is_read_only_and_adapter_has_no_mutation_api() -> None:
    adapter = ScientificDocumentIngestionService(ROOT).ontology
    public = {name for name in dir(adapter) if not name.startswith("_")}
    assert {"build", "partition", "promote", "mutate", "write"}.isdisjoint(public)
    valid, reasons = adapter.validate_link("has_parameter", "OperatorRevision", "ParameterDefinition", as_statement=True)
    assert valid is True
    assert reasons == []


def test_full_schema_gate_rejects_an_incomplete_evidence_assessment() -> None:
    result = _run()
    packet = next(
        item
        for item in result["packets"]
        if item.candidate_subgraph is not None
        and item.candidate_subgraph.relation_kind == "SCIENTIFIC_STATEMENT"
    )
    payload = packet.candidate_subgraph.model_dump(mode="python")
    assessment = next(
        node
        for node in payload["nodes"]
        if node["record_type"] == "EvidenceAssessment"
    )
    del assessment["record"]["assessment_method"]
    valid, errors, _, _, _ = ScientificDocumentIngestionService(ROOT).ontology.validate_candidate_subgraph(payload)
    assert valid is False
    assert any("assessment_method" in error for error in errors)


def test_statement_revision_identity_is_stable_while_assessment_identity_is_run_specific() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    service = ScientificDocumentIngestionService(ROOT)
    first = service.run_pages(**fixture, created_at="2026-09-21T00:00:00Z")
    second = service.run_pages(**fixture, created_at="2026-09-21T00:01:00Z")

    def capability(result):
        return next(
            packet
            for packet in result["packets"]
            if packet.canonical_statement is not None
            and packet.canonical_statement.predicate == "implements_method"
        )

    first_graph = capability(first).candidate_subgraph
    second_graph = capability(second).candidate_subgraph
    assert first_graph.statement_revision_id == second_graph.statement_revision_id
    assert first_graph.evidence_assessment_id != second_graph.evidence_assessment_id
    assert first_graph.subgraph_id != second_graph.subgraph_id


def test_committed_soupx_demo_snapshot_has_five_distinct_ready_candidates() -> None:
    summary = json.loads(SOUPX_SUMMARY.read_text(encoding="utf-8"))
    assert summary["source"]["sha256"] == "dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19"
    assert summary["counts"]["CANDIDATE_READY"] == 5
    spo = {
        (row["subject"], row["predicate"], row["object"])
        for row in summary["ready_candidates"]
    }
    assert len(spo) == 5
    assert {row[1] for row in spo} == {
        "revision_of", "implements_method", "supports_task", "has_requirement", "output_type"
    }
    assert summary["unbounded_ready_candidates"] == 0
    assert summary["hallucinated_scope_count"] == 0
