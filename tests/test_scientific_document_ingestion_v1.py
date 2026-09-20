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


def _run():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return ScientificDocumentIngestionService(ROOT).run_pages(
        filename=fixture["filename"],
        pdf_sha256=fixture["pdf_sha256"],
        pages=fixture["pages"],
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
    assert row.final_disposition == FinalDisposition.CANDIDATE_READY


def test_parameter_preserves_operator_parameter_and_version_context_without_fuzzy_merge() -> None:
    packets = _run()["packets"]
    row = next(
        packet
        for packet in packets
        if packet.raw_proposition and packet.raw_proposition.parameter_name == "method"
    )
    assert row.raw_proposition.operator_name == "adjustCounts"
    assert row.canonical_statement.predicate == "has_parameter"
    assert {entity.context_role for entity in row.linked_entities} == {"operator", "parameter"}
    assert all(entity.fuzzy_merge_used is False for entity in row.linked_entities)
    version = next(value for value in row.scope.values if value.dimension == "method_operator_version")
    assert version.value == "1.6.2"
    assert version.status == ScopeValueStatus.SOURCE_CONTEXT
    assert version.provenance_ref == row.source.source_revision_id
    assert row.final_disposition == FinalDisposition.NEEDS_REVIEW


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
