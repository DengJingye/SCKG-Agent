from eval.independent_retrieval_validation_v1 import aggregate, build_specs, paired_classification


def test_c7_specs_are_balanced_and_sealed_before_run() -> None:
    queries, gold, split, config = build_specs()
    assert len(queries) == len(gold) == 42
    assert split["counts"] == {"DEV_CHECK": 28, "SEALED": 14, "ALL": 42}
    assert split["sealed_validation_used_for_tuning"] is False
    assert {row["category"] for row in queries} == set("ABCDEFG")
    assert sum(row["expected_abstention"] for row in gold) == 6
    assert config["execution_policy"]["sealed_run_limit"] == 1


def test_c7_aggregate_uses_answerable_denominator_and_counts_false_certainty() -> None:
    rows = [
        {"evidence_available": True, "expected_abstention": False, "hit_at_5": 1, "hit_at_10": 1, "reciprocal_rank_at_10": 0.5, "evidence_correctness": 1, "system_abstained": False, "false_certainty_event": False},
        {"evidence_available": True, "expected_abstention": False, "hit_at_5": 0, "hit_at_10": 0, "reciprocal_rank_at_10": 0.0, "evidence_correctness": 0, "system_abstained": False, "false_certainty_event": False},
        {"evidence_available": False, "expected_abstention": True, "hit_at_5": None, "hit_at_10": None, "reciprocal_rank_at_10": None, "evidence_correctness": 0, "system_abstained": False, "false_certainty_event": True},
    ]
    value = aggregate(rows)
    assert value["hit_at_10"] == 0.5
    assert value["mrr_at_10"] == 0.25
    assert value["false_certainty_events"] == 1


def test_c7_paired_classification_detects_rank_movement() -> None:
    base = {"hit_at_10": 1, "first_gold_rank": 7}
    assert paired_classification(base, {"hit_at_10": 1, "first_gold_rank": 3}) == "HELPED"
    assert paired_classification(base, {"hit_at_10": 1, "first_gold_rank": 9}) == "HURT"
    assert paired_classification(base, dict(base)) == "NEUTRAL"
