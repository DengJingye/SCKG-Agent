import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLD = PROJECT_ROOT / "eval" / "gold_migration_sealed_v0_11.jsonl"
DEFAULT_PER_QUERY = PROJECT_ROOT / "eval" / "context_pack_v0_12_full_offline_migration_eval_per_query.tsv"
DEFAULT_PREDICTIONS = PROJECT_ROOT / "eval" / "context_pack_v0_12_full_offline_predictions.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "context_pack_v0_12_failure_queue.tsv"

FIELDS = [
    "query_id",
    "case_type",
    "expected_decision",
    "predicted_type",
    "migration_tools",
    "failure_reasons",
    "forbidden_tools",
    "expected_source_tools",
    "query",
    "parsed_task",
    "parsed_modality",
    "migration_intent",
    "clarification_state",
    "missing_components",
    "candidate_action",
    "reviewer_notes",
]


def load_jsonl(path: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            records[item["id"]] = item
    return records


def load_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def bool_cell(value: str) -> bool:
    return str(value).strip().lower() == "true"


def failure_reasons(row: Dict[str, str]) -> List[str]:
    reasons: List[str] = []
    if not bool_cell(row.get("mixed_decision_hit", "")):
        reasons.append("mixed_decision_miss")
    if bool_cell(row.get("forbidden_tool_violation", "")):
        reasons.append("forbidden_tool_violation")
    if bool_cell(row.get("forbidden_claim_violation", "")):
        reasons.append("forbidden_claim_violation")
    if row.get("case_type") in {"true_negative", "needs_clarification"} and bool_cell(row.get("is_migration_output", "")):
        reasons.append("false_migration_output")
    if row.get("case_type") == "revise_only" and bool_cell(row.get("is_migration_output", "")):
        reasons.append("revise_only_leaked_migration")
    if not bool_cell(row.get("semantic_audit_pass", "True")):
        reasons.append("semantic_audit_failed")
    return reasons


def candidate_action(reasons: List[str], row: Dict[str, str]) -> str:
    case_type = row.get("case_type", "")
    tools = row.get("migration_tools", "")
    if "revise_only_leaked_migration" in reasons:
        return "tighten_migration_gate_for_revise_only_source"
    if "false_migration_output" in reasons and case_type == "needs_clarification":
        return "clarify_missing_prerequisites_before_migration"
    if "forbidden_tool_violation" in reasons:
        return "add_tool_specific_block_or_query_mechanism_filter"
    if "mixed_decision_miss" in reasons and tools:
        return "inspect_output_type_or_source_tool_routing"
    if "mixed_decision_miss" in reasons:
        return "inspect_intent_classifier"
    return "review"


def build_queue(
    gold: Dict[str, Dict[str, Any]],
    predictions: Dict[str, Dict[str, Any]],
    per_query_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    queue: List[Dict[str, str]] = []
    for row in per_query_rows:
        reasons = failure_reasons(row)
        if not reasons:
            continue
        query_id = row.get("query_id", "")
        gold_row = gold.get(query_id, {})
        prediction = predictions.get(query_id, {})
        constraints = prediction.get("parsed_constraints") or {}
        queue.append(
            {
                "query_id": query_id,
                "case_type": row.get("case_type", ""),
                "expected_decision": row.get("expected_migration_decision", ""),
                "predicted_type": row.get("predicted_type", ""),
                "migration_tools": row.get("migration_tools", ""),
                "failure_reasons": ";".join(reasons),
                "forbidden_tools": ";".join(gold_row.get("forbidden_tools") or gold_row.get("expected_blocked_tools") or []),
                "expected_source_tools": ";".join(gold_row.get("expected_source_tools") or []),
                "query": gold_row.get("query", ""),
                "parsed_task": str(constraints.get("task", "")),
                "parsed_modality": str(constraints.get("modality", "")),
                "migration_intent": str(constraints.get("migration_intent", "")),
                "clarification_state": str(constraints.get("clarification_state", "")),
                "missing_components": ";".join(prediction.get("missing_components") or []),
                "candidate_action": candidate_action(reasons, row),
                "reviewer_notes": "",
            }
        )
    return queue


def write_tsv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a focused v0.12 failure queue from migration eval outputs.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--per-query", type=Path, default=DEFAULT_PER_QUERY)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = build_queue(
        gold=load_jsonl(args.gold),
        predictions=load_jsonl(args.predictions),
        per_query_rows=load_tsv(args.per_query),
    )
    write_tsv(rows, args.output)
    print(f"wrote {len(rows)} failure rows to {args.output}")


if __name__ == "__main__":
    main()
