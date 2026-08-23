from __future__ import annotations

import json
from pathlib import Path

from core.open_world_evaluation_models import EvaluationGoldTier, NaturalQueryCase


ROOT = Path(__file__).resolve().parents[1]


def test_open_world_bank_has_frozen_counts_and_valid_schema() -> None:
    visible = json.loads(
        (ROOT / "eval/fixtures/open_world_natural_queries_v2.json").read_text()
    )["cases"]
    hidden = json.loads(
        (ROOT / "eval/fixtures/open_world_hidden_v1.json").read_text()
    )["cases"]
    cases = [NaturalQueryCase.model_validate(row) for row in [*visible, *hidden]]
    hidden_cases = [NaturalQueryCase.model_validate(row) for row in hidden]
    assert len(cases) == 120
    assert len(visible) == 96
    assert len(hidden) == 24
    assert sum(case.source_kind in {"external_forum", "official_issue"} for case in cases) == 84
    assert sum(case.source_kind == "real_history" for case in cases) == 24
    assert sum(case.source_kind == "adversarial" for case in cases) == 12
    assert {case.split for case in hidden_cases} == {"hidden"}
    assert all(case.split != "hidden" for case in cases[: len(visible)])
    assert sum(EvaluationGoldTier.ROUTING in case.gold_tiers for case in cases[:96]) == 85
    assert sum(EvaluationGoldTier.ANSWER in case.gold_tiers for case in cases[:96]) == 11
    assert sum(EvaluationGoldTier.SAFETY in case.gold_tiers for case in cases[:96]) == 11


def test_open_world_bank_has_no_duplicate_queries_or_external_urls() -> None:
    visible = json.loads(
        (ROOT / "eval/fixtures/open_world_natural_queries_v2.json").read_text()
    )["cases"]
    hidden = json.loads(
        (ROOT / "eval/fixtures/open_world_hidden_v1.json").read_text()
    )["cases"]
    cases = [*visible, *hidden]
    queries = [row["query"].casefold() for row in cases]
    assert len(queries) == len(set(queries))
    external = [
        row for row in cases if row["source_kind"] in {"external_forum", "official_issue"}
    ]
    assert all(row["source_url"].startswith("https://") for row in external)


def test_v2_gold_separates_routing_answer_and_safety_metrics() -> None:
    rows = json.loads(
        (ROOT / "eval/fixtures/open_world_natural_queries_v2.json").read_text()
    )["cases"]
    cases = {row["case_id"]: NaturalQueryCase.model_validate(row) for row in rows}

    vague = cases["github-swolock-scrublet-66"]
    assert vague.expected_domain == "UNCERTAIN"
    assert vague.expected_action == "CLARIFY"
    assert vague.allowed_source_ids == []
    assert EvaluationGoldTier.ANSWER not in vague.gold_tiers

    replay = cases["history-approval-replay"]
    assert replay.expected_action == "BLOCK"
    assert EvaluationGoldTier.SAFETY in replay.gold_tiers
    assert EvaluationGoldTier.ANSWER not in replay.gold_tiers

    answer = cases["history-doublet-recommend"]
    assert answer.expected_action == "ALLOW"
    assert EvaluationGoldTier.ANSWER in answer.gold_tiers
    assert answer.allowed_source_ids
