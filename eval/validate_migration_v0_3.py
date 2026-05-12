import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROFILE_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "tool_algorithm_profiles.tsv"
REVIEW_PACKET_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "migration_hypothesis_review_packet.tsv"
GOLD_PATH = PROJECT_ROOT / "eval" / "gold_migration_queries_v0_3.jsonl"

PROFILE_FIELDS = [
    "tool_name",
    "algorithm_family",
    "model_assumption",
    "distance_metric",
    "optimization_objective",
    "input_object",
    "output_object",
    "supported_task",
    "supported_modality",
    "transferable_mechanism",
    "known_limitations",
    "review_status",
    "reviewer_notes",
]

REVIEW_PACKET_FIELDS = [
    "query_id",
    "target_task",
    "target_modality",
    "source_tool",
    "source_task",
    "transferable_mechanism",
    "vector_similarity",
    "graph_jaccard",
    "io_compatibility",
    "compatibility_gaps",
    "risk_level",
    "candidate_decision",
    "reviewer_decision",
    "reviewer_notes",
]

ALLOWED_PROFILE_REVIEW_STATUS = {"review_needed", "profile_validated"}
ALLOWED_REVIEW_DECISIONS = {
    "",
    "accept_exploratory",
    "revise_mechanism",
    "reject_incompatible",
    "needs_more_evidence",
}
REQUIRED_GOLD_FIELDS = {
    "expected_output_type",
    "expected_source_tools",
    "forbidden_claims",
    "expected_caveats",
}
FORBIDDEN_STRONG_CLAIM_TERMS = {
    "best tool",
    "empirically proven",
    "safe direct replacement",
    "benchmark-backed",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_header(rows: list[dict[str, str]], expected: list[str], path: Path) -> None:
    require(rows, f"{path} has no data rows")
    actual = list(rows[0].keys())
    require(actual == expected, f"{path} header mismatch: {actual}")


def validate_profiles() -> int:
    rows = read_tsv(PROFILE_PATH)
    assert_header(rows, PROFILE_FIELDS, PROFILE_PATH)
    bad_status = [
        row["tool_name"]
        for row in rows
        if row["review_status"] not in ALLOWED_PROFILE_REVIEW_STATUS
    ]
    require(not bad_status, f"invalid profile review_status values: {bad_status}")
    validated = [
        row["tool_name"]
        for row in rows
        if row["review_status"] == "profile_validated"
    ]
    require(validated, "expected at least one profile_validated row after human review")
    return len(rows)


def validate_review_packet() -> int:
    rows = read_tsv(REVIEW_PACKET_PATH)
    assert_header(rows, REVIEW_PACKET_FIELDS, REVIEW_PACKET_PATH)
    bad_decisions = [
        (row["query_id"], row["reviewer_decision"])
        for row in rows
        if row["reviewer_decision"] not in ALLOWED_REVIEW_DECISIONS
    ]
    require(not bad_decisions, f"invalid reviewer_decision values: {bad_decisions}")
    decision_counts: dict[str, int] = {}
    for row in rows:
        decision = row["reviewer_decision"]
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    if any(row["reviewer_decision"] for row in rows):
        require(
            decision_counts.get("accept_exploratory", 0) == 7,
            f"expected 7 accept_exploratory rows, found {decision_counts}",
        )
        require(
            decision_counts.get("revise_mechanism", 0) == 1,
            f"expected 1 revise_mechanism row, found {decision_counts}",
        )
        revise_ids = [
            row["query_id"]
            for row in rows
            if row["reviewer_decision"] == "revise_mechanism"
        ]
        require(revise_ids == ["MIG_V03_004"], f"unexpected revise_mechanism rows: {revise_ids}")
    return len(rows)


def validate_gold() -> int:
    count = 0
    bad_records: list[Any] = []
    with GOLD_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            count += 1
            missing = REQUIRED_GOLD_FIELDS - set(record)
            if missing:
                bad_records.append((record.get("id"), "missing_fields", sorted(missing)))
            if record.get("expected_output_type") != "migration_hypothesis":
                bad_records.append((record.get("id"), "expected_output_type", record.get("expected_output_type")))
            forbidden_claims = set(record.get("forbidden_claims") or [])
            if not forbidden_claims.intersection(FORBIDDEN_STRONG_CLAIM_TERMS):
                bad_records.append((record.get("id"), "missing_forbidden_strong_claim", sorted(forbidden_claims)))
            if not record.get("expected_caveats"):
                bad_records.append((record.get("id"), "missing_expected_caveats", []))
    require(count >= 8, f"expected at least 8 migration gold queries, found {count}")
    require(not bad_records, f"invalid migration gold records: {bad_records}")
    return count


def main() -> None:
    profile_count = validate_profiles()
    packet_count = validate_review_packet()
    gold_count = validate_gold()
    print(
        json.dumps(
            {
                "tool_algorithm_profiles": profile_count,
                "migration_hypothesis_review_packet": packet_count,
                "gold_migration_queries": gold_count,
                "status": "ok",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
