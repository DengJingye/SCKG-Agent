from __future__ import annotations

import json

import pytest

from eval.retrieval_benchmark_v1_1_1_dev import first_failure_cause, prepare


PROFILES = (
    "R0_bm25_only",
    "R1_dense_only",
    "R2_bm25_dense_rrf",
    "R3_kg_bm25_dense_rrf",
    "R4_kg_bm25_dense_rrf_governance",
)


def _gold() -> dict:
    return {"expected_tools": ["ExampleTool"]}


def _diagnostic(**overrides) -> dict:
    stages = {
        "corpus_ids": ["gold"],
        "bm25_raw_rank": 20,
        "dense_raw_rank": 20,
        "bm25_common_rank": 20,
        "dense_common_rank": 20,
        "bm25_kg_rank": 20,
        "dense_kg_rank": 20,
        "profiles": {profile: {"pre_diversification_rank": 20, "final_rank": None} for profile in PROFILES},
    }
    stages.update(overrides)
    return {"inferred_tools": ["ExampleTool"], "stages": stages}


def _results(**hits) -> dict:
    return {profile: {"recall_at_10": int(hits.get(profile, False))} for profile in PROFILES}


@pytest.mark.parametrize(
    ("profile", "expected", "prohibited"),
    [
        ("R0_bm25_only", "BM25_RANKING", {"DENSE_RANKING", "KG_FALSE_FILTER", "GOVERNANCE_RERANK"}),
        ("R1_dense_only", "DENSE_RANKING", {"BM25_RANKING", "KG_FALSE_FILTER", "GOVERNANCE_RERANK"}),
        ("R2_bm25_dense_rrf", "RRF_RANKED_OUT", {"KG_FALSE_FILTER", "GOVERNANCE_RERANK"}),
        ("R3_kg_bm25_dense_rrf", "RRF_RANKED_OUT", {"GOVERNANCE_RERANK"}),
        ("R4_kg_bm25_dense_rrf_governance", "RRF_RANKED_OUT", set()),
    ],
)
def test_first_cause_can_only_name_a_stage_executed_by_profile(profile, expected, prohibited) -> None:
    cause = first_failure_cause(gold=_gold(), profile_id=profile, results=_results(), diagnostic=_diagnostic())

    assert cause == expected
    assert cause not in prohibited


def test_r3_kg_failure_requires_r2_success() -> None:
    results = _results(R2_bm25_dense_rrf=True)

    assert first_failure_cause(gold=_gold(), profile_id="R3_kg_bm25_dense_rrf", results=results, diagnostic=_diagnostic()) == "KG_FALSE_FILTER"


def test_r4_governance_failure_requires_r3_success() -> None:
    results = _results(R2_bm25_dense_rrf=True, R3_kg_bm25_dense_rrf=True)

    assert first_failure_cause(gold=_gold(), profile_id="R4_kg_bm25_dense_rrf_governance", results=results, diagnostic=_diagnostic()) == "GOVERNANCE_RERANK"


def test_r4_inherits_kg_failure_when_r3_already_failed() -> None:
    results = _results(R2_bm25_dense_rrf=True)

    assert first_failure_cause(gold=_gold(), profile_id="R4_kg_bm25_dense_rrf_governance", results=results, diagnostic=_diagnostic()) == "KG_FALSE_FILTER"


def test_diversification_is_first_cause_only_after_top10_pre_diversification_rank() -> None:
    diagnostic = _diagnostic()
    diagnostic["stages"]["profiles"]["R2_bm25_dense_rrf"] = {"pre_diversification_rank": 4, "final_rank": None}

    assert first_failure_cause(gold=_gold(), profile_id="R2_bm25_dense_rrf", results=_results(), diagnostic=diagnostic) == "DIVERSIFICATION_RANKED_OUT"


def test_prepare_freezes_same_query_gold_and_strengthened_snapshot(tmp_path) -> None:
    output = tmp_path / "campaign"

    manifest = prepare(output)

    assert manifest["query_set_sha256"] == "224384015f0df2155c55478b432941c8fb899157352b1e27d29af22aff6e3773"
    assert manifest["gold_sha256"] == "d84aff99acc9d7a4d5f0d55fb9c5c052a8eb31a9fd8d8e24797cbc3b9b14fbaa"
    assert manifest["snapshot_identity"]["build_id"] == "retrieval-foundation-v1-ff5b4829bc5943f4"
    config = json.loads((output / "retrieval_config.json").read_text())
    assert config["retrieval_tuning_after_invalid_run"] is False
    with pytest.raises(FileExistsError):
        prepare(output)
