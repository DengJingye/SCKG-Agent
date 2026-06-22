import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = PROJECT_ROOT / "docs" / "migration_eval_protocol_v0_10.md"
GOLD_PATH = PROJECT_ROOT / "eval" / "gold_migration_sealed_v0_10.jsonl"

REQUIRED_FIELDS = {
    "id",
    "case_type",
    "query",
    "expected_constraints",
    "expected_output_type",
    "expected_migration_decision",
    "expected_source_tools",
    "forbidden_tools",
    "forbidden_claims",
    "expected_caveats",
    "acceptance",
}

CASE_TYPES = {
    "true_positive",
    "revise_only",
    "true_negative",
    "needs_clarification",
    "retrieval_trap",
}

REQUIRED_CASE_COUNTS = {
    "true_positive": 12,
    "revise_only": 12,
    "true_negative": 9,
    "needs_clarification": 8,
    "retrieval_trap": 9,
}

ALLOWED_OUTPUT_TYPES = {
    "migration_hypothesis",
    "none",
    "workflow",
    "ranked_tools",
    "evidence_chain",
}

ALLOWED_DECISIONS = {
    "accept_exploratory",
    "revise_mechanism",
    "reject_incompatible",
    "needs_clarification",
    "not_migration",
}

THRESHOLD_TERMS = [
    "negative_false_migration_rate <= 0.05",
    "forbidden_tool_violation_rate <= 0.05",
    "clarification_success_rate >= 0.80",
    "positive_source_tool_hit >= 0.60",
    "mixed_decision_accuracy >= 0.75",
    "unreviewed_migration_path_rate <= 0.40",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"{path}:{line_no} invalid JSON: {exc}") from exc
            records.append(record)
    return records


def validate_protocol() -> None:
    require(PROTOCOL_PATH.exists(), f"missing protocol file: {PROTOCOL_PATH}")
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    for term in THRESHOLD_TERMS:
        require(term in text, f"protocol missing threshold: {term}")
    require("first sealed run" in text.lower(), "protocol must define first sealed run handling")
    require("v0.11" in text, "protocol must require later fixes to move to v0.11")
    require("--offline-llm --blind-migration" in text, "protocol must freeze offline blind migration run")


def validate_gold() -> dict[str, int]:
    require(GOLD_PATH.exists(), f"missing gold file: {GOLD_PATH}")
    records = load_jsonl(GOLD_PATH)
    require(len(records) == sum(REQUIRED_CASE_COUNTS.values()), f"unexpected gold size: {len(records)}")

    ids: set[str] = set()
    queries: set[str] = set()
    counts = {case: 0 for case in CASE_TYPES}
    errors: list[Any] = []
    for record in records:
        record_id = record.get("id")
        missing = REQUIRED_FIELDS - set(record)
        if missing:
            errors.append((record_id, "missing_fields", sorted(missing)))
        if not str(record_id).startswith("MIG_V10_"):
            errors.append((record_id, "bad_id_prefix"))
        if record_id in ids:
            errors.append((record_id, "duplicate_id"))
        ids.add(str(record_id))
        query = str(record.get("query", "")).strip()
        if not query:
            errors.append((record_id, "empty_query"))
        if query in queries:
            errors.append((record_id, "duplicate_query"))
        queries.add(query)

        case_type = record.get("case_type")
        if case_type not in CASE_TYPES:
            errors.append((record_id, "bad_case_type", case_type))
        else:
            counts[case_type] += 1

        output_type = record.get("expected_output_type")
        decision = record.get("expected_migration_decision")
        if output_type not in ALLOWED_OUTPUT_TYPES:
            errors.append((record_id, "bad_output_type", output_type))
        if decision not in ALLOWED_DECISIONS:
            errors.append((record_id, "bad_decision", decision))
        if not record.get("expected_caveats"):
            errors.append((record_id, "missing_caveats"))
        if not record.get("forbidden_claims"):
            errors.append((record_id, "missing_forbidden_claims"))

        if case_type == "true_positive":
            if output_type != "migration_hypothesis" or decision != "accept_exploratory":
                errors.append((record_id, "positive_contract", output_type, decision))
            if not record.get("expected_source_tools"):
                errors.append((record_id, "positive_missing_expected_source_tools"))
        if case_type == "revise_only" and decision != "revise_mechanism":
            errors.append((record_id, "revise_contract", decision))
        if case_type == "needs_clarification" and decision != "needs_clarification":
            errors.append((record_id, "clarification_contract", decision))
        if case_type == "true_negative" and decision not in {"reject_incompatible", "not_migration"}:
            errors.append((record_id, "negative_contract", decision))
        if case_type == "retrieval_trap" and decision != "not_migration":
            errors.append((record_id, "trap_contract", decision))

    require(counts == REQUIRED_CASE_COUNTS, f"case distribution mismatch: {counts}")
    require(not errors, f"invalid v0.10 migration gold records: {errors}")
    return counts


def main() -> None:
    validate_protocol()
    counts = validate_gold()
    print(
        json.dumps(
            {
                "protocol": str(PROTOCOL_PATH),
                "gold": str(GOLD_PATH),
                "case_counts": counts,
                "status": "ok",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
