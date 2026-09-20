from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.scientific_knowledge_studio_models import (
    AtomicClaimProposal,
    CandidateDiff,
    DocumentSegment,
    EntityProposal,
    EvidenceSpanProposal,
    KnowledgeStudioRunManifest,
    ProposalGraph,
    RelationProposal,
    ScopeDimensionProposal,
    ScopeProposal,
    SourceRevisionProposal,
)
from engine.scientific_knowledge_studio import (
    PROMPT_VERSION,
    SEMANTIC_SCHEMA_VERSION,
    PagePreservingPDFAdapter,
    RawEntity,
    RawRelation,
    ScientificIdentityResolver,
    ScientificKnowledgeStudioService,
    SemanticResponse,
    StructuredLLMProposalExtractor,
)


ROOT = Path(__file__).resolve().parents[1]
PDF_BYTES = b"%PDF-1.7 deterministic-test-fixture"
PAGES = [
    (
        "Package SoupX. Description SoupX implements a method to quantify and remove ambient "
        "mRNA contamination from droplet based single cell RNA-seq experiments. Version 1.6.2. "
        "The method requires a raw count matrix as input and produces corrected counts as output."
    ),
    (
        "Arguments. Clustering information is highly recommended because without groups it is "
        "difficult and usually impossible to distinguish background contamination from endogenous expression."
    ),
]


def _run(tmp_path: Path, *, pages=PAGES, name: str = "run"):
    return ScientificKnowledgeStudioService(ROOT).run_from_pages(
        original_filename="soupx.pdf",
        original_bytes=PDF_BYTES,
        pages=pages,
        metadata={"title": "SoupX: Single Cell mRNA Soup eXterminator"},
        run_id=f"knowledge-studio:{name}",
        output_dir=tmp_path / name,
    )


def _source(**updates):
    payload = {
        "proposal_id": "proposal:source-revision:" + "a" * 16,
        "source_work_candidate_id": "source-work-candidate:test",
        "source_revision_candidate_id": "source-revision-candidate:test",
        "identity_status": "SOURCE_IDENTITY_NEW",
        "title": "Test PDF",
        "original_filename": "test.pdf",
        "file_size": 20,
        "pdf_sha256": "b" * 64,
        "page_count": 1,
        "ingestion_run_id": "knowledge-studio:test",
        "parser_name": "pypdf",
        "parser_version": "5.0.0",
        "created_at": "2026-09-20T00:00:00Z",
    }
    payload.update(updates)
    return SourceRevisionProposal.model_validate(payload)


def _span(**updates):
    payload = {
        "proposal_id": "proposal:evidence-span:" + "c" * 24,
        "source_revision_proposal_id": "proposal:source-revision:" + "a" * 16,
        "source_pdf_sha256": "b" * 64,
        "page_number": 1,
        "segment_id": "segment:" + "d" * 32,
        "start_offset": 0,
        "end_offset": 8,
        "exact_text": "evidence",
        "text_sha256": hashlib.sha256(b"evidence").hexdigest(),
        "extraction_method": "test",
        "validation_status": "VALID",
    }
    payload.update(updates)
    return EvidenceSpanProposal.model_validate(payload)


def test_01_source_revision_proposal_schema_is_candidate_only() -> None:
    source = _source()
    assert source.proposal_status == "candidate_proposal"
    assert source.source_type == "local_scientific_pdf"


def test_02_evidence_span_schema_enforces_offsets() -> None:
    assert _span().end_offset == 8
    with pytest.raises(ValidationError, match="offsets must bound"):
        _span(end_offset=9)


def test_03_entity_relation_claim_and_scope_schemas_are_strict() -> None:
    entity = EntityProposal(
        entity_proposal_id="proposal:entity:" + "1" * 24,
        entity_type="SoftwareProject",
        raw_label="SoupX",
        normalized_label="soupx",
        supporting_evidence_span_ids=[_span().proposal_id],
        identity_resolution_status="EXACT_EXISTING_IDENTITY",
        existing_candidate_ids=["software-project:soupx"],
        validation_status="VALID",
    )
    scope = ScopeProposal(
        scope_proposal_id="proposal:scope:" + "2" * 24,
        supporting_evidence_span_ids=[_span().proposal_id],
        dimensions={"modality": ScopeDimensionProposal(value="scRNA-seq", status="EXPLICIT")},
        validation_status="VALID",
    )
    relation = RelationProposal(
        relation_proposal_id="proposal:relation:" + "3" * 24,
        source_entity_ref=entity.entity_proposal_id,
        predicate="IMPLEMENTS_METHOD",
        target_entity_ref="proposal:entity:" + "4" * 24,
        supporting_evidence_span_ids=[_span().proposal_id],
        origin="PDF_EXTRACTED",
        validation_status="VALID",
    )
    claim = AtomicClaimProposal(
        claim_proposal_id="proposal:claim:" + "5" * 24,
        claim_text="SoupX removes ambient RNA contamination.",
        claim_type="capability",
        subject_ref=entity.entity_proposal_id,
        object_or_requirement="ambient RNA contamination",
        supporting_evidence_span_ids=[_span().proposal_id],
        scope_proposal_id=scope.scope_proposal_id,
        validation_status="VALID",
    )
    assert {entity.proposal_status, relation.proposal_status, claim.knowledge_status, scope.proposal_status} == {"candidate_proposal"}


def test_04_candidate_diff_arithmetic_rejects_inconsistent_identity_buckets() -> None:
    with pytest.raises(ValidationError, match="identity buckets"):
        CandidateDiff(
            current_nodes=1,
            current_edges=1,
            current_candidate_claims=1,
            entity_proposals=2,
            relation_proposals=0,
            atomic_claim_proposals=0,
            evidence_span_proposals=0,
            new_candidates=1,
            exact_existing_identity_matches=0,
            possible_matches=0,
            ambiguous=0,
            unresolved=0,
            valid=0,
            needs_review=0,
            invalid=0,
        )


def test_05_run_manifest_has_exact_ordered_stage_schema(tmp_path: Path) -> None:
    result = _run(tmp_path)
    manifest = KnowledgeStudioRunManifest.model_validate(result["manifest"].model_dump())
    assert [row.stage for row in manifest.stages] == [
        "UPLOAD", "SOURCE_IDENTITY", "PARSE", "EVIDENCE_PROPOSAL",
        "SEMANTIC_EXTRACTION", "IDENTITY_RESOLUTION", "VALIDATION", "PREVIEW",
    ]


def test_06_pdf_hash_and_page_count_are_stable(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result["manifest"].pdf_sha256 == hashlib.sha256(PDF_BYTES).hexdigest()
    assert result["manifest"].page_count == 2


def test_07_same_pdf_produces_same_segment_ids_on_second_run(tmp_path: Path) -> None:
    first = _run(tmp_path, name="first")
    second = _run(tmp_path, name="second")
    assert [row.segment_id for row in first["segments"]] == [row.segment_id for row in second["segments"]]


def test_08_exact_spans_resolve_to_their_segments(tmp_path: Path) -> None:
    result = _run(tmp_path)
    segments = {row.segment_id: row for row in result["segments"]}
    for span in result["evidence"]:
        segment = segments[span.segment_id]
        assert segment.exact_text[span.start_offset : span.end_offset] == span.exact_text
        assert span.validation_status == "VALID"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"exact_text": "fabricated", "end_offset": 10, "text_sha256": hashlib.sha256(b"fabricated").hexdigest()}, "INVALID_EVIDENCE_BINDING"),
        ({"page_number": 2}, "WRONG_PAGE_BINDING"),
        ({"source_pdf_sha256": "f" * 64}, "WRONG_PDF_HASH"),
    ],
)
def test_09_to_11_fabricated_wrong_page_and_wrong_hash_are_rejected(change, reason) -> None:
    service = ScientificKnowledgeStudioService(ROOT)
    source = _source()
    segment = DocumentSegment(
        segment_id="segment:" + "d" * 32,
        page_number=1,
        segment_index=0,
        exact_text="evidence plus bounded context",
        text_sha256=hashlib.sha256(b"evidence plus bounded context").hexdigest(),
        source_pdf_sha256="b" * 64,
        parser_name="pypdf",
        parser_version="test",
    )
    validated = service._validate_evidence(source, [segment], [_span(**change)])[0]
    assert validated.validation_status == "INVALID"
    assert reason in validated.validation_reasons


def test_12_parser_failure_creates_parse_gap() -> None:
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    parsed = PagePreservingPDFAdapter().parse_pages(
        [PAGES[0], RuntimeError("broken page")], pdf_sha256=digest
    )
    assert parsed.page_count == 2
    assert len(parsed.gaps) == 1
    assert parsed.gaps[0].page == 2
    assert "broken page" in parsed.gaps[0].reason


def test_13_ontology_is_loaded_from_current_snapshot() -> None:
    contract = ScientificKnowledgeStudioService(ROOT).ontology_contract()
    assert "Method" in contract["entity_types"]
    assert "OperatorRevision" in contract["entity_types"]
    assert "IMPLEMENTS_METHOD" in contract["predicates"]
    assert "REQUIRES_RAW_DATA" not in contract["predicates"]


def test_14_invalid_entity_type_is_rejected_by_validation(tmp_path: Path) -> None:
    service = ScientificKnowledgeStudioService(ROOT)
    result = _run(tmp_path)
    response = SemanticResponse(
        schema_version=SEMANTIC_SCHEMA_VERSION,
        entity_proposals=[RawEntity(entity_type="InventedClass", raw_label="Fake", supporting_evidence_span_ids=[result["evidence"][0].proposal_id])],
        relation_proposals=[], atomic_claim_proposals=[], scope_proposals=[],
    )
    row = service._entity_proposals(response, result["evidence"])[0]
    assert row.validation_status == "INVALID"
    assert "UNKNOWN_ENTITY_TYPE" in row.validation_reasons


@pytest.mark.parametrize("predicate", ["REQUIRES_RAW_DATA", "WORKS_WITH", "BEST_FOR", "SIMILAR_TO"])
def test_15_to_18_unknown_predicates_are_not_silently_created(tmp_path: Path, predicate: str) -> None:
    service = ScientificKnowledgeStudioService(ROOT)
    result = _run(tmp_path)
    entities = result["entities"][:2]
    response = SemanticResponse(
        schema_version=SEMANTIC_SCHEMA_VERSION,
        entity_proposals=[],
        relation_proposals=[RawRelation(
            source_label=entities[0].raw_label,
            predicate=predicate,
            target_label=entities[1].raw_label,
            supporting_evidence_span_ids=[result["evidence"][0].proposal_id],
            origin="PDF_EXTRACTED",
        )],
        atomic_claim_proposals=[], scope_proposals=[],
    )
    row = service._relation_proposals(response, result["evidence"], entities)[0]
    assert row.validation_status == "INVALID"
    assert "UNSUPPORTED_RELATION_PROPOSAL" in row.validation_reasons


def test_19_invalid_endpoint_types_are_rejected_and_valid_pair_is_known() -> None:
    ontology = ScientificKnowledgeStudioService(ROOT).ontology
    assert ontology.relation_valid("IMPLEMENTS_METHOD", "OperatorRevision", "Method") is True
    assert ontology.relation_valid("IMPLEMENTS_METHOD", "SoftwareProject", "RepresentationType") is False


def test_20_exact_existing_identity_resolves_without_fuzzy_merge() -> None:
    resolver = ScientificIdentityResolver(ROOT, {"SoftwareProject", "Method"})
    status, ids, reasons = resolver.resolve("SoftwareProject", "SoupX")
    assert status == "EXACT_EXISTING_IDENTITY"
    assert ids == ["software-project:soupx"]
    assert "exact_normalized_label" in reasons


def test_21_governed_alias_path_resolves_when_present() -> None:
    resolver = ScientificIdentityResolver(ROOT, {"SoftwareProject"})
    resolver.by_alias[("SoftwareProject", "soupx alias")] = {"software-project:soupx"}
    status, ids, reasons = resolver.resolve("SoftwareProject", "SoupX Alias")
    assert status == "EXACT_EXISTING_IDENTITY"
    assert ids == ["software-project:soupx"]
    assert "governed_alias" in reasons


def test_22_multiple_exact_candidates_remain_ambiguous() -> None:
    resolver = ScientificIdentityResolver(ROOT, {"Method"})
    resolver.by_label[("Method", "same method")] = {"method:a", "method:b"}
    status, ids, _ = resolver.resolve("Method", "Same Method")
    assert status == "AMBIGUOUS"
    assert ids == ["method:a", "method:b"]


def test_23_unknown_identity_is_new_candidate_and_no_fuzzy_merge() -> None:
    resolver = ScientificIdentityResolver(ROOT, {"Method"})
    status, ids, reasons = resolver.resolve("Method", "Almost but not quite PCA")
    assert status == "NEW_CANDIDATE"
    assert ids == []
    assert "fuzzy_merge_disabled" in reasons


def test_24_version_conflict_is_retained_as_possible_match() -> None:
    resolver = ScientificIdentityResolver(ROOT, {"SoftwareProject"})
    status, ids, reasons = resolver.resolve("SoftwareProject", "SoupX", version="999.0")
    assert status == "POSSIBLE_EXISTING_IDENTITY"
    assert ids == ["software-project:soupx"]
    assert "version_conflict_retained" in reasons


def test_25_evidence_free_claim_cannot_validate_at_model_boundary() -> None:
    with pytest.raises(ValidationError):
        AtomicClaimProposal(
            claim_proposal_id="proposal:claim:" + "5" * 24,
            claim_text="Unsupported claim",
            claim_type="general",
            subject_ref="proposal:entity:" + "1" * 24,
            object_or_requirement="none",
            supporting_evidence_span_ids=[],
            scope_proposal_id="proposal:scope:" + "2" * 24,
            validation_status="VALID",
        )


def test_26_unspecified_scope_is_not_universal() -> None:
    dimension = ScopeDimensionProposal(value=None, status="UNSPECIFIED")
    assert dimension.value is None
    with pytest.raises(ValidationError, match="cannot imply a universal value"):
        ScopeDimensionProposal(value="all", status="UNSPECIFIED")


@pytest.mark.parametrize("unsafe", ["trusted", "canonical", "reviewed"])
def test_27_to_29_unsafe_status_escalation_is_rejected(unsafe: str) -> None:
    payload = _source().model_dump(mode="json")
    payload["proposal_status"] = unsafe
    with pytest.raises(ValidationError):
        SourceRevisionProposal.model_validate(payload)


def test_30_all_real_run_scientific_objects_remain_candidate_proposals(tmp_path: Path) -> None:
    result = _run(tmp_path)
    rows = [result["source"], *result["evidence"], *result["entities"], *result["relations"], *result["claims"], *result["scopes"]]
    assert all(row.proposal_status == "candidate_proposal" for row in rows)
    assert all(getattr(row, "knowledge_status", "candidate_proposal") == "candidate_proposal" for row in rows)


def test_31_run_has_no_production_mutation_or_authority(tmp_path: Path) -> None:
    result = _run(tmp_path)
    manifest = result["manifest"]
    assert manifest.scientific_kg_mutated is False
    assert manifest.production_rag_indexed is False
    assert manifest.planner_consumed is False
    assert manifest.review_decision_created is False
    assert manifest.canonical_promotion == "none"
    assert manifest.trusted_knowledge_created is False


def test_32_invalid_llm_json_and_extra_fields_are_rejected_with_bounded_retry() -> None:
    calls = []
    responses = ["not-json", json.dumps({"schema_version": SEMANTIC_SCHEMA_VERSION, "entity_proposals": [], "relation_proposals": [], "atomic_claim_proposals": [], "scope_proposals": [], "extra": True})]
    extractor = StructuredLLMProposalExtractor(lambda _: calls.append(1) or responses.pop(0), max_retries=1)
    with pytest.raises(ValueError, match="bounded retry"):
        extractor.extract("prompt")
    assert len(calls) == 2


def test_33_valid_strict_llm_fixture_is_accepted_and_retry_count_recorded() -> None:
    payload = {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "entity_proposals": [], "relation_proposals": [],
        "atomic_claim_proposals": [], "scope_proposals": [],
    }
    extractor = StructuredLLMProposalExtractor(lambda _: json.dumps(payload), max_retries=2)
    response, raw, retries = extractor.extract("prompt")
    assert response.schema_version == SEMANTIC_SCHEMA_VERSION
    assert json.loads(raw) == payload
    assert retries == 0


def test_34_hallucinated_llm_evidence_id_is_rejected(tmp_path: Path) -> None:
    service = ScientificKnowledgeStudioService(ROOT)
    result = _run(tmp_path)
    response = SemanticResponse(
        schema_version=SEMANTIC_SCHEMA_VERSION,
        entity_proposals=[RawEntity(entity_type="SoftwareProject", raw_label="SoupX", supporting_evidence_span_ids=["proposal:evidence-span:" + "9" * 24])],
        relation_proposals=[], atomic_claim_proposals=[], scope_proposals=[],
    )
    row = service._entity_proposals(response, result["evidence"])[0]
    assert row.validation_status == "INVALID"
    assert "HALLUCINATED_EVIDENCE_ID" in row.validation_reasons


def test_35_proposal_graph_is_bounded_to_run_and_has_resolvable_edges(tmp_path: Path) -> None:
    result = _run(tmp_path)
    graph = ProposalGraph.model_validate(result["proposal_graph"].model_dump())
    assert graph.bounded_to_run is True
    assert len(graph.nodes) < 100
    ids = {row.node_id for row in graph.nodes}
    assert all(edge.source in ids and edge.target in ids for edge in graph.edges)


def test_36_current_metrics_come_from_frozen_snapshot(tmp_path: Path) -> None:
    result = _run(tmp_path)
    snapshot = ScientificKnowledgeStudioService(ROOT).admin.summary()
    diff = result["candidate_diff"]
    assert (diff.current_nodes, diff.current_edges, diff.current_candidate_claims) == (
        snapshot["scientific_kg_nodes"], snapshot["scientific_kg_edges"], snapshot["candidate_claims"]
    )


def test_37_run_is_write_once_and_does_not_store_pdf_binary(tmp_path: Path) -> None:
    _run(tmp_path)
    assert not list((tmp_path / "run").glob("*.pdf"))
    with pytest.raises(FileExistsError, match="write-once"):
        _run(tmp_path)


def test_38_manifest_artifact_hashes_resolve(tmp_path: Path) -> None:
    result = _run(tmp_path)
    for name, expected in result["manifest"].artifact_hashes.items():
        actual = hashlib.sha256((result["run_dir"] / name).read_bytes()).hexdigest()
        assert actual == expected


def test_39_local_extraction_is_not_misreported_as_llm(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result["manifest"].llm.status == "NOT_RUN"
    assert result["manifest"].llm.model == "none"
    semantic_stage = next(row for row in result["manifest"].stages if row.stage == "SEMANTIC_EXTRACTION")
    assert semantic_stage.reason == "local_deterministic_ontology_extractor_v1"
    assert semantic_stage.reason != PROMPT_VERSION
