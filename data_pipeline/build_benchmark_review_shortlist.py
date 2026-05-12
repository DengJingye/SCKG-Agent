import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKET = PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_review_packet.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_review_shortlist.tsv"
DEFAULT_SOURCE_REVIEW = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_source_human_review.tsv"
)

OUTPUT_FIELDS = [
    "review_priority",
    "priority_tier",
    "tool_name",
    "human_action",
    "candidate_decision",
    "benchmark_id",
    "benchmark_name",
    "paper_doi",
    "source_url",
    "why_review",
    "fields_to_extract",
    "formal_ingest_allowed_now",
    "recommendation_use_allowed_now",
]

HIGH_VALUE_TOOLS = {
    "scib",
    "celltypist",
    "scvelo",
    "harmony",
    "scgpt",
    "scanpy",
    "seurat",
    "scrublet",
    "doubletfinder",
    "soupx",
    "tradeseq",
}


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_optional_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    return load_tsv(path)


def write_tsv(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})


def normalize_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def shortlist_rows(
    packet_rows: List[Dict[str, str]],
    source_review_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    reviewed_by_benchmark = {
        row.get("benchmark_id", ""): row
        for row in source_review_rows
        if row.get("benchmark_id")
    }
    grouped = defaultdict(list)
    for row in packet_rows:
        grouped[normalize_name(row.get("tool_name", ""))].append(row)

    rows = []
    for tool_key, tool_rows in grouped.items():
        rows.extend(shortlist_tool(tool_key, tool_rows, reviewed_by_benchmark))

    rows.sort(
        key=lambda row: (
            priority_order(row["review_priority"]),
            {"P0": 0, "P1": 1}.get(row["priority_tier"], 9),
            row["tool_name"].lower(),
            row["candidate_decision"],
        )
    )
    return rows


def shortlist_tool(
    tool_key: str,
    rows: List[Dict[str, str]],
    reviewed_by_benchmark: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    reviewed = [
        (row, reviewed_by_benchmark[row.get("benchmark_id", "")])
        for row in rows
        if row.get("benchmark_id", "") in reviewed_by_benchmark
    ]
    if reviewed:
        return [shortlist_reviewed_row(row, review) for row, review in reviewed]

    concrete = [
        row for row in rows
        if row.get("suggested_decision") in {"needs_manual_extraction", "needs_field_completion", "ready_for_review"}
    ]
    if concrete:
        return [shortlist_row(row, tool_key) for row in concrete]

    representative = rows[0]
    if tool_key in HIGH_VALUE_TOOLS:
        return [manual_source_lookup_row(representative, "P1_manual_benchmark_source_lookup")]

    if any(row.get("suggested_decision") == "hold_candidate" for row in rows):
        hold = [row for row in rows if row.get("suggested_decision") == "hold_candidate"][0]
        return [shortlist_row(hold, tool_key)]

    return [quarantine_shell_row(representative)]


def shortlist_reviewed_row(row: Dict[str, str], review: Dict[str, str]) -> Dict[str, str]:
    if review.get("extraction_allowed") == "true":
        priority = "P1_extract_if_source_is_relevant"
        action = "Human source review allows metric extraction; extract source-supported facts only."
        candidate_decision = "source_review_allows_extraction"
    elif review.get("source_review_decision") == "manual_benchmark_source_lookup":
        priority = "P1_manual_benchmark_source_lookup"
        action = "Human source review found no usable candidate; manually find a trusted benchmark source."
        candidate_decision = "manual_benchmark_source_lookup"
    else:
        priority = "P3_quarantine_or_ignore"
        action = "Human source review blocks extraction; keep provenance only."
        candidate_decision = review.get("source_review_decision", "blocked_by_source_review")

    return {
        "review_priority": priority,
        "priority_tier": row.get("priority_tier", ""),
        "tool_name": row.get("tool_name", ""),
        "human_action": action,
        "candidate_decision": candidate_decision,
        "benchmark_id": row.get("benchmark_id", ""),
        "benchmark_name": row.get("benchmark_name", ""),
        "paper_doi": row.get("paper_doi", ""),
        "source_url": row.get("source_url", ""),
        "why_review": review.get("reviewer_notes", ""),
        "fields_to_extract": required_fields_text(row) if review.get("extraction_allowed") == "true" else "",
        "formal_ingest_allowed_now": "false",
        "recommendation_use_allowed_now": "false",
    }


def shortlist_row(row: Dict[str, str], tool_key: str) -> Dict[str, str]:
    decision = row.get("suggested_decision", "")
    if decision == "ready_for_review":
        review_priority = "P0_extract_and_verify"
        action = "Extract exact metric/dataset/protocol, then human-review before formal ingest."
    elif decision in {"needs_manual_extraction", "needs_field_completion"}:
        review_priority = "P1_extract_if_source_is_relevant" if tool_key in HIGH_VALUE_TOOLS else "P2_optional_extraction"
        action = "Open source and extract benchmark facts only if the paper directly evaluates this tool/task."
    else:
        review_priority = "P3_quarantine_or_ignore"
        action = "Do not formalize; keep as retrieval/provenance only unless a reviewer finds a real metric table."

    return {
        "review_priority": review_priority,
        "priority_tier": row.get("priority_tier", ""),
        "tool_name": row.get("tool_name", ""),
        "human_action": action,
        "candidate_decision": decision,
        "benchmark_id": row.get("benchmark_id", ""),
        "benchmark_name": row.get("benchmark_name", ""),
        "paper_doi": row.get("paper_doi", ""),
        "source_url": row.get("source_url", ""),
        "why_review": row.get("risk_notes", ""),
        "fields_to_extract": required_fields_text(row),
        "formal_ingest_allowed_now": "false",
        "recommendation_use_allowed_now": "false",
    }


def manual_source_lookup_row(row: Dict[str, str], priority: str) -> Dict[str, str]:
    return {
        "review_priority": priority,
        "priority_tier": row.get("priority_tier", ""),
        "tool_name": row.get("tool_name", ""),
        "human_action": "Ignore the current shell candidate and manually find a trusted benchmark source for this tool/task.",
        "candidate_decision": "manual_benchmark_source_lookup",
        "benchmark_id": f"MANUAL_LOOKUP_BMK_{row.get('tool_name', '')}",
        "benchmark_name": "",
        "paper_doi": "",
        "source_url": "",
        "why_review": "No useful benchmark candidate is available; current candidates are shells or insufficient records.",
        "fields_to_extract": "benchmark_name;source_url;task;dataset;metric;direction;rank_or_score;n_tools_compared;evaluation_protocol",
        "formal_ingest_allowed_now": "false",
        "recommendation_use_allowed_now": "false",
    }


def quarantine_shell_row(row: Dict[str, str]) -> Dict[str, str]:
    return {
        "review_priority": "P3_quarantine_shell",
        "priority_tier": row.get("priority_tier", ""),
        "tool_name": row.get("tool_name", ""),
        "human_action": "Quarantine for now; do not spend reviewer time unless this tool becomes benchmark-critical.",
        "candidate_decision": "likely_shell",
        "benchmark_id": row.get("benchmark_id", ""),
        "benchmark_name": row.get("benchmark_name", ""),
        "paper_doi": row.get("paper_doi", ""),
        "source_url": row.get("source_url", ""),
        "why_review": "Supplement or placeholder benchmark shell with no extracted task/dataset/metric/result.",
        "fields_to_extract": required_fields_text(row),
        "formal_ingest_allowed_now": "false",
        "recommendation_use_allowed_now": "false",
    }


def required_fields_text(row: Dict[str, str]) -> str:
    missing = row.get("missing_fields", "")
    if missing:
        return missing
    return "benchmark_name;source_url;task;dataset;metric;direction;rank_or_score;n_tools_compared;evaluation_protocol"


def priority_order(value: str) -> int:
    if value.startswith("P0"):
        return 0
    if value.startswith("P1"):
        return 1
    if value.startswith("P2"):
        return 2
    return 3


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact human benchmark review shortlist.")
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--source-review", type=Path, default=DEFAULT_SOURCE_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    packet_rows = load_tsv(args.packet)
    source_review_rows = load_optional_tsv(args.source_review)
    rows = shortlist_rows(packet_rows, source_review_rows)
    write_tsv(args.output, rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(rows),
                "priorities": dict(Counter(row["review_priority"] for row in rows)),
                "formal_ingest_allowed_now": False,
                "recommendation_use_allowed_now": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
