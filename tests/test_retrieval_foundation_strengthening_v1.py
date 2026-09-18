from __future__ import annotations

import json

from data_pipeline.build_retrieval_foundation_strengthening_v1 import (
    CORE_SPAN_BLOCK_REASON,
    OUTPUT_DIR,
    SNAPSHOT_DIR,
    _chunk_from_exact_span,
    analyze_missing_gold,
    refine_other_attribution,
)
from engine.hybrid_retrieval import HybridRetrievalService


def test_missing_gold_failures_are_deduplicated_by_scientific_identity() -> None:
    summary, records, indexable = analyze_missing_gold()

    assert summary == {
        "profile_failure_records": 105,
        "unique_affected_queries": 21,
        "unique_missing_evidence_spans": 21,
        "unique_source_revisions": 5,
        "unique_source_works": 7,
        "gap_classification": {
            "EVIDENCE_SPAN_NOT_CHUNKED": 17,
            "SOURCE_ARTIFACT_MISSING": 4,
        },
        "indexable_exact_spans": 17,
        "untouched_gaps": 4,
    }
    assert len(records) == 21
    assert len(indexable) == 17


def test_authored_candidate_excerpt_without_exact_source_artifact_is_not_indexed() -> None:
    _, records, indexable = analyze_missing_gold()
    blocked = [row for row in records if row["earliest_missing_link"] == "SOURCE_ARTIFACT_MISSING"]

    assert {row["evidence_span_id"] for row in blocked} == {
        "evidence-span:v1-core:scanpy:scanpy_pp_normalize_total:capability",
        "evidence-span:v1-core:edger:edger__dgelist:capability",
        "evidence-span:v1-core:slingshot:slingshot__slingshot:primary_method_evidence",
        "evidence-span:v1-core:pyscenic:pyscenic_grn:primary_method_evidence",
    }
    assert all(row["reason"] == CORE_SPAN_BLOCK_REASON for row in blocked)
    assert not ({row["evidence_span_id"] for row in blocked} & {row["evidence_span_id"] for row in indexable})


def test_new_exact_chunks_remain_candidate_retrieval_only() -> None:
    _, _, indexable = analyze_missing_gold()

    chunks = [_chunk_from_exact_span(item) for item in indexable]

    assert len(chunks) == 17
    assert all(chunk.source_bound for chunk in chunks)
    assert all(chunk.retrieval_status == "retrieval_only" for chunk in chunks)
    assert all(chunk.recommendation_eligible == "false" for chunk in chunks)
    assert all(chunk.source_id.startswith("source-revision:") for chunk in chunks)
    assert all(chunk.chunk_text.strip() for chunk in chunks)
    assert all("cannot authorize" in chunk.claim_boundary for chunk in chunks)


def test_other_bucket_is_refined_without_rewriting_frozen_register() -> None:
    rows = refine_other_attribution()

    assert len(rows) == 30
    assert all(row["first_cause"] == "OTHER" for row in rows)
    assert all(row["refined_first_cause"] != "UNRESOLVED_OTHER" for row in rows)
    assert {row["refined_first_cause"] for row in rows} <= {
        "INITIAL_RETRIEVAL_MISS",
        "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH",
        "RRF_RANKED_OUT",
        "DIVERSIFICATION_RANKED_OUT",
        "CANDIDATE_RANKED_OUT",
    }


def test_strengthened_snapshot_is_loadable_and_does_not_replace_default_index() -> None:
    report = json.loads((OUTPUT_DIR / "report.json").read_text())
    service = HybridRetrievalService(
        evidence_chunks_path=SNAPSHOT_DIR / "evidence_chunks.jsonl",
        catalog_chunks_path=SNAPSHOT_DIR / "scrna_tools_catalog_chunks.jsonl",
        fts_index_path=SNAPSHOT_DIR / "evidence_fts5.sqlite",
        index_manifest_path=SNAPSHOT_DIR / "evidence_index_manifest.json",
        coverage_path=SNAPSHOT_DIR / "retrieval_coverage_v2.json",
        dense_matrix_path=SNAPSHOT_DIR / "evidence_vectors.npy",
        dense_metadata_path=SNAPSHOT_DIR / "evidence_vector_metadata.json",
    )

    assert report["frozen_p0c_default_index_unchanged"] is True
    assert report["snapshot_identity"]["candidate_only"] is True
    assert report["snapshot_identity"]["canonical_promotion"] == "none"
    assert report["snapshot_identity"]["source_count_before"] == 63
    assert report["snapshot_identity"]["source_count_after"] == 68
    assert report["snapshot_identity"]["evidence_chunk_count_before"] == 783
    assert report["snapshot_identity"]["evidence_chunk_count_after"] == 800
    assert report["snapshot_identity"]["vector_count_before"] == 773
    assert report["snapshot_identity"]["vector_count_after"] == 790
    assert service._dense_matrix is not None
    assert service._dense_matrix.shape == (790, 1024)
    assert all(
        span_id in service._chunks_by_id
        for span_id in report["snapshot_identity"]["added_exact_span_ids"]
    )
