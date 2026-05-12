import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CORE_TOOLS = PROJECT_ROOT / "data" / "evidence_candidates" / "core_50_tools.tsv"
DEFAULT_CANDIDATES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_tool_benchmark_candidates.tsv"
)
DEFAULT_REVIEW_ACTIONS = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_tool_benchmark_review_actions.tsv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_benchmark_review_packet.tsv"
)

TARGET_TIERS = {"P0", "P1"}
TIER_ORDER = {"P0": 0, "P1": 1}
DECISION_ORDER = {
    "ready_for_review": 0,
    "needs_manual_extraction": 1,
    "needs_field_completion": 2,
    "likely_shell": 3,
    "hold_candidate": 4,
    "no_candidate_found": 5,
}

SOURCE_FIELDS = ["benchmark_name", "source_url", "paper_title"]
CONTEXT_FIELDS = ["task", "dataset", "metric", "direction", "evaluation_protocol", "n_tools_compared"]
RESULT_FIELDS = ["rank", "score", "normalized_score"]
PLACEHOLDER_BENCHMARK_MARKERS = {
    "supplemental information",
    "supplementary information",
    "supplementary",
    "supplement",
    "appendix",
    "supporting information",
    "additional file",
    "table s",
    "figure s",
    "unknown",
    "placeholder",
}
BENCHMARK_SOURCE_MARKERS = {
    "benchmark",
    "benchmarking",
    "comparative",
    "comparison",
    "compare",
    "evaluation",
    "evaluate",
    "assessment",
    "atlas",
}
SECONDARY_SOURCE_MARKERS = {
    "editor's evaluation",
    "faculty opinions",
    "conference abstract",
    "abstract ",
    "commentary",
    "news",
}

PACKET_FIELDS = [
    "priority_tier",
    "tool_name",
    "benchmark_id",
    "work_group_id",
    "canonical_flag",
    "duplicate_of",
    "benchmark_name",
    "benchmark_type",
    "paper_title",
    "paper_doi",
    "paper_pmid",
    "source_url",
    "source_type",
    "task",
    "subtask",
    "modality",
    "species",
    "technology",
    "dataset",
    "metric",
    "metric_definition",
    "direction",
    "rank",
    "score",
    "normalized_score",
    "rank_scope",
    "n_tools_compared",
    "evaluation_protocol",
    "result_text",
    "claim_span",
    "review_bucket",
    "review_action",
    "suggested_decision",
    "proposed_trust_level_after_review",
    "proposed_recommendation_use",
    "risk_notes",
    "missing_fields",
    "recommended_review_status",
    "recommended_trust_level",
    "trust_level",
    "review_status",
    "confidence",
    "extraction_method",
    "record_type",
    "source_record_id",
    "notes",
]


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PACKET_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in PACKET_FIELDS})


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def evidence_safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", (value or "").strip())
    return cleaned.strip("_") or "unknown"


def target_tools(core_rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    tools = []
    seen = set()
    for row in core_rows:
        tool_name = one_line(row.get("tool_name", ""))
        tier = one_line(row.get("priority_tier", ""))
        key = normalize_name(tool_name)
        if not tool_name or tier not in TARGET_TIERS or key in seen:
            continue
        tools.append({"tool_name": tool_name, "priority_tier": tier})
        seen.add(key)
    return tools


def index_review_actions(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("benchmark_id", ""): row for row in rows if row.get("benchmark_id")}


def build_packet(
    core_tools: List[Dict[str, str]],
    candidates: List[Dict[str, str]],
    review_actions: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    tier_by_tool = {normalize_name(row["tool_name"]): row["priority_tier"] for row in core_tools}
    tool_name_by_key = {normalize_name(row["tool_name"]): row["tool_name"] for row in core_tools}
    tool_position = {normalize_name(row["tool_name"]): index for index, row in enumerate(core_tools)}
    candidates_by_tool: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in candidates:
        key = normalize_name(row.get("tool_name", ""))
        if key in tier_by_tool:
            candidates_by_tool[key].append(row)

    packet_rows: List[Dict[str, str]] = []
    for tool in core_tools:
        key = normalize_name(tool["tool_name"])
        tool_candidates = candidates_by_tool.get(key, [])
        if not tool_candidates:
            packet_rows.append(no_candidate_row(tool))
            continue
        for candidate in tool_candidates:
            action = review_actions.get(candidate.get("benchmark_id", ""), {})
            packet_rows.append(packet_row(tool, candidate, action))

    packet_rows.sort(
        key=lambda row: (
            TIER_ORDER.get(row["priority_tier"], 9),
            tool_position.get(normalize_name(row["tool_name"]), 999),
            DECISION_ORDER.get(row["suggested_decision"], 9),
            row.get("benchmark_name", ""),
            row.get("paper_title", ""),
        )
    )

    for row in packet_rows:
        key = normalize_name(row.get("tool_name", ""))
        if key in tool_name_by_key:
            row["tool_name"] = tool_name_by_key[key]
    return packet_rows


def no_candidate_row(tool: Dict[str, str]) -> Dict[str, str]:
    tool_name = tool["tool_name"]
    return {
        "priority_tier": tool["priority_tier"],
        "tool_name": tool_name,
        "benchmark_id": f"NO_CAND_BMK_{evidence_safe_id(tool_name)}",
        "review_action": "manual_benchmark_source_lookup_required",
        "suggested_decision": "no_candidate_found",
        "proposed_trust_level_after_review": "retrieval_only",
        "proposed_recommendation_use": "none",
        "risk_notes": (
            "candidate_only; no benchmark candidate found for P0/P1 tool; "
            "manual benchmark source lookup required before formal ingest"
        ),
        "missing_fields": ";".join(SOURCE_FIELDS + CONTEXT_FIELDS + ["rank_or_score"]),
    }


def packet_row(tool: Dict[str, str], candidate: Dict[str, str], action: Dict[str, str]) -> Dict[str, str]:
    missing = merged_missing_fields(candidate, action)
    risk_notes = build_risk_notes(candidate, action, missing)
    decision = suggested_decision(candidate, action, missing, risk_notes)
    row = {field: one_line(candidate.get(field, "")) for field in PACKET_FIELDS}
    row.update(
        {
            "priority_tier": tool["priority_tier"],
            "tool_name": tool["tool_name"],
            "review_bucket": one_line(action.get("review_bucket", "")),
            "review_action": review_action_value(action),
            "suggested_decision": decision,
            "proposed_trust_level_after_review": proposed_trust_level(decision),
            "proposed_recommendation_use": proposed_recommendation_use(decision),
            "risk_notes": "; ".join(risk_notes),
            "missing_fields": ";".join(missing),
            "recommended_review_status": one_line(action.get("recommended_review_status", "")),
            "recommended_trust_level": one_line(action.get("recommended_trust_level", "")),
        }
    )
    return row


def merged_missing_fields(candidate: Dict[str, str], action: Dict[str, str]) -> List[str]:
    missing = split_list(action.get("missing_fields", ""))
    for field in SOURCE_FIELDS + CONTEXT_FIELDS:
        if not one_line(candidate.get(field, "")):
            missing.append(field)
    if not any(one_line(candidate.get(field, "")) for field in RESULT_FIELDS):
        missing.append("rank_or_score")
    return dedupe_preserve_order(missing)


def split_list(value: str) -> List[str]:
    return [part.strip() for part in re.split(r"[;,]", value or "") if part.strip()]


def review_action_value(action: Dict[str, str]) -> str:
    action_type = one_line(action.get("action_type", ""))
    proposed_state = one_line(action.get("proposed_state", ""))
    if action_type or proposed_state:
        return ":".join(part for part in [action_type, proposed_state] if part)
    return "manual_review"


def build_risk_notes(
    candidate: Dict[str, str],
    action: Dict[str, str],
    missing: List[str],
) -> List[str]:
    notes = [
        "candidate_only",
        "requires_human_review_before_formal_ingest",
        "do_not_invent_rank_score_metric_or_protocol",
    ]
    action_reason = one_line(action.get("reason", ""))
    if action_reason:
        notes.append(action_reason)
    if placeholder_benchmark(candidate):
        notes.append("benchmark_shell_or_supplement_placeholder")
    if secondary_source(candidate):
        notes.append("secondary_or_editorial_source_not_benchmark_fact")
    if not action:
        notes.append("missing_review_action_row")
    if candidate.get("canonical_flag") == "false" or one_line(candidate.get("duplicate_of", "")):
        notes.append("duplicate_or_noncanonical_candidate")
    if benchmark_source_like(candidate) and missing:
        notes.append("benchmark_like_source_requires_manual_metric_extraction")
    if not benchmark_source_like(candidate):
        notes.append("weak_benchmark_source_signal")
    if missing:
        notes.append(f"missing_fields:{','.join(missing)}")
    return dedupe_preserve_order(notes)


def suggested_decision(
    candidate: Dict[str, str],
    action: Dict[str, str],
    missing: List[str],
    risk_notes: List[str],
) -> str:
    if not missing and not placeholder_benchmark(candidate) and not secondary_source(candidate):
        return "ready_for_review"
    if placeholder_benchmark(candidate):
        return "likely_shell"
    bucket = one_line(action.get("review_bucket", ""))
    if bucket == "needs_field_completion":
        return "needs_field_completion"
    if benchmark_source_like(candidate) and not secondary_source(candidate):
        return "needs_manual_extraction"
    if bucket == "needs_manual_benchmark_extraction":
        return "needs_manual_extraction"
    if "missing_review_action_row" in risk_notes:
        return "needs_manual_extraction"
    return "hold_candidate"


def proposed_trust_level(decision: str) -> str:
    if decision == "ready_for_review":
        return "trusted_core_if_human_reviewed"
    if decision in {"needs_manual_extraction", "needs_field_completion"}:
        return "review_needed_until_completed"
    return "retrieval_only"


def proposed_recommendation_use(decision: str) -> str:
    if decision == "ready_for_review":
        return "recommendation_after_human_review"
    if decision in {"needs_manual_extraction", "needs_field_completion"}:
        return "none_until_completed"
    return "none"


def placeholder_benchmark(candidate: Dict[str, str]) -> bool:
    value = one_line(candidate.get("benchmark_name", "")).lower()
    if not value:
        return True
    return any(marker in value for marker in PLACEHOLDER_BENCHMARK_MARKERS)


def benchmark_source_like(candidate: Dict[str, str]) -> bool:
    text = " ".join(
        [
            candidate.get("benchmark_name", ""),
            candidate.get("paper_title", ""),
            candidate.get("benchmark_type", ""),
            candidate.get("evaluation_protocol", ""),
            candidate.get("result_text", ""),
            candidate.get("notes", ""),
        ]
    ).lower()
    return any(marker in text for marker in BENCHMARK_SOURCE_MARKERS)


def secondary_source(candidate: Dict[str, str]) -> bool:
    text = " ".join([candidate.get("benchmark_name", ""), candidate.get("paper_title", "")]).lower()
    return any(marker in text for marker in SECONDARY_SOURCE_MARKERS)


def dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    deduped = []
    for value in values:
        cleaned = one_line(value)
        if not cleaned or cleaned in seen:
            continue
        deduped.append(cleaned)
        seen.add(cleaned)
    return deduped


def summary(rows: List[Dict[str, str]]) -> Dict[str, object]:
    return {
        "rows": len(rows),
        "tiers": dict(Counter(row["priority_tier"] for row in rows)),
        "tools": len({row["tool_name"] for row in rows}),
        "suggested_decisions": dict(Counter(row["suggested_decision"] for row in rows)),
        "review_buckets": dict(Counter(row["review_bucket"] for row in rows if row.get("review_bucket"))),
        "no_candidate_rows": sum(1 for row in rows if row["suggested_decision"] == "no_candidate_found"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a conservative P0/P1 benchmark review packet from candidate-only evidence."
    )
    parser.add_argument("--core-tools", type=Path, default=DEFAULT_CORE_TOOLS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--review-actions", type=Path, default=DEFAULT_REVIEW_ACTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    core_tools = target_tools(load_tsv(args.core_tools))
    candidates = load_tsv(args.candidates)
    review_actions = index_review_actions(load_tsv(args.review_actions))
    rows = build_packet(core_tools, candidates, review_actions)
    write_tsv(rows, args.output)

    print(
        json.dumps(
            {
                "output": str(args.output),
                **summary(rows),
                "formal_benchmark_table_written": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
