from __future__ import annotations

import json

import pytest

from eval.retrieval_benchmark_v1_1_dev import (
    EXPECTED_GOLD_SHA,
    EXPECTED_QUERY_SHA,
    _accepted_ids,
    _aggregate,
    _cohorts,
    _evaluate_hit_list,
    prepare,
)


def test_v1_1_reuses_byte_identical_frozen_queries_and_gold(tmp_path) -> None:
    output = tmp_path / "v1_1"
    manifest = prepare(output)

    assert manifest["query_set_sha256"] == EXPECTED_QUERY_SHA
    assert manifest["gold_sha256"] == EXPECTED_GOLD_SHA
    assert json.loads((output / "retrieval_config.json").read_text())["top_k"] == 10
    with pytest.raises(FileExistsError):
        prepare(output)


def test_strengthening_cohorts_are_independent_of_v1_1_outputs() -> None:
    cohorts = _cohorts()

    assert len(cohorts["previous_gold_source_not_indexed"]) == 21
    assert len(cohorts["repaired"]) == 17
    assert len(cohorts["still_blocked"]) == 4
    assert len(cohorts["unaffected_r1"]) == 24
    assert len(cohorts["original_governance_hurt"]) == 12
    assert not set(cohorts["repaired"]).intersection(cohorts["still_blocked"])


def test_v1_1_resolves_exact_span_identity_without_changing_gold() -> None:
    gold = {
        "gold_evidence_span_ids": ["newly-indexed-exact-span"],
        "indexed_chunk_aliases": [],
        "source_ids": ["source"],
        "expected_version": "",
        "expected_scope": "",
    }
    query = {"query_id": "q", "track": "R1_scientific_evidence", "task_family": "hvg", "query_type": "input_requirement"}

    result = _evaluate_hit_list(query, gold, [{"chunk_id": "newly-indexed-exact-span", "source_id": "source"}])

    assert _accepted_ids(gold) == {"newly-indexed-exact-span"}
    assert result["recall_at_5"] == 1
    assert result["first_gold_rank"] == 1


def test_aggregate_reports_raw_numerators_and_denominators() -> None:
    base = {
        "reciprocal_rank": 1.0, "ndcg_at_10": 1.0,
        "authoritative_source_hit": 1, "correct_version_hit": None,
        "correct_scope_hit": None, "irrelevant_context_rate": 0.2,
    }
    rows = [dict(base, recall_at_5=1, recall_at_10=1), dict(base, recall_at_5=0, recall_at_10=1)]

    result = _aggregate(rows)

    assert result["recall_at_5"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert result["recall_at_10"] == {"numerator": 2, "denominator": 2, "rate": 1.0}
    assert result["correct_version_hit_rate"]["rate"] is None
