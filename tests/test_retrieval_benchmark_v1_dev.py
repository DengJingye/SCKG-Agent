from __future__ import annotations

import json

import pytest

from eval.retrieval_benchmark_v1_dev import (
    EXPECTED_CORPUS_DIGEST,
    EXPECTED_MODEL_REVISION,
    PROFILES,
    _aggregate,
    _evaluate_hit_list,
    _paired_classification,
    build_frozen_specs,
    prepare,
)


def test_frozen_spec_has_separate_tracks_and_independent_gold() -> None:
    queries, gold, config = build_frozen_specs()

    assert sum(row["track"] == "R1_scientific_evidence" for row in queries) == 45
    assert sum(row["track"] == "R2_tool_method_discovery" for row in queries) == 12
    assert len({row["query_id"] for row in queries}) == 57
    assert all(row["generated_from_retrieval_output"] is False for row in gold)
    assert all(row["gold_evidence_span_ids"] for row in gold)
    assert config["frozen_foundation"]["corpus_digest"] == EXPECTED_CORPUS_DIGEST
    assert config["frozen_foundation"]["model_revision"] == EXPECTED_MODEL_REVISION
    assert [profile.profile_id for profile in PROFILES] == [
        "R0_bm25_only",
        "R1_dense_only",
        "R2_bm25_dense_rrf",
        "R3_kg_bm25_dense_rrf",
        "R4_kg_bm25_dense_rrf_governance",
    ]


def test_seed_gold_is_reviewed_source_bound_not_sut_generated() -> None:
    _, gold, _ = build_frozen_specs()
    seed = [row for row in gold if row["gold_origin"] == "midterm_core_seed_v0_project_owner_reviewed"]

    assert len(seed) == 20
    assert all(row["source_revision_ids"] or row["gold_evidence_span_ids"] for row in seed)
    assert all(row["generated_from_retrieval_output"] is False for row in seed)


def test_exact_span_metrics_treat_alternatives_as_nested_or_gold() -> None:
    query = {
        "query_id": "q1",
        "track": "R1_scientific_evidence",
        "task_family": "annotation",
        "query_type": "input_requirement",
    }
    gold = {
        "indexed_chunk_aliases": ["accepted-a", "accepted-b"],
        "source_ids": ["source-a"],
        "expected_version": "1.0",
        "expected_scope": "scope",
    }
    hits = [
        {"chunk_id": "irrelevant", "source_id": "other"},
        {"chunk_id": "accepted-b", "source_id": "source-a"},
    ]

    result = _evaluate_hit_list(query, gold, hits)

    assert result["recall_at_5"] == 1
    assert result["recall_at_10"] == 1
    assert result["first_gold_rank"] == 2
    assert result["reciprocal_rank"] == 0.5
    assert result["authoritative_source_hit"] == 1
    assert result["irrelevant_context_rate"] == 0.5


def test_not_applicable_denominators_are_explicit() -> None:
    rows = [
        {
            "recall_at_5": 1,
            "recall_at_10": 1,
            "reciprocal_rank": 1.0,
            "ndcg_at_10": 1.0,
            "authoritative_source_hit": 1,
            "correct_version_hit": None,
            "correct_scope_hit": None,
            "irrelevant_context_rate": 0.0,
        }
    ]

    aggregate = _aggregate(rows)

    assert aggregate["correct_version_hit_rate"] is None
    assert aggregate["correct_version_denominator"] == 0
    assert aggregate["correct_scope_hit_rate"] is None
    assert aggregate["correct_scope_denominator"] == 0


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ({"recall_at_10": 0, "first_gold_rank": None}, {"recall_at_10": 1, "first_gold_rank": 4}, "HELPED"),
        ({"recall_at_10": 1, "first_gold_rank": 4}, {"recall_at_10": 1, "first_gold_rank": 2}, "HELPED"),
        ({"recall_at_10": 1, "first_gold_rank": 2}, {"recall_at_10": 1, "first_gold_rank": 2}, "NEUTRAL"),
        ({"recall_at_10": 1, "first_gold_rank": 2}, {"recall_at_10": 0, "first_gold_rank": None}, "HURT"),
        ({"recall_at_10": 1, "first_gold_rank": 2}, {"recall_at_10": 1, "first_gold_rank": 5}, "HURT"),
    ],
)
def test_kg_paired_classification_is_frozen(before: dict, after: dict, expected: str) -> None:
    assert _paired_classification(before, after) == expected


def test_prepare_is_write_once_and_records_artifact_hashes(tmp_path) -> None:
    output = tmp_path / "campaign"

    manifest = prepare(output)

    assert manifest["state"] == "prepared_not_run"
    assert (output / "queries.jsonl").is_file()
    assert (output / "gold.jsonl").is_file()
    assert (output / "retrieval_config.json").is_file()
    assert json.loads((output / "pre_run_manifest.json").read_text())["gold_sha256"] == manifest["gold_sha256"]
    with pytest.raises(FileExistsError):
        prepare(output)
