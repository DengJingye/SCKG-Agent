from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_PUBLICATION_AUDIT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "formal_publication_audit.tsv"
)
DEFAULT_BENCHMARK_AUDIT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "formal_benchmark_audit.tsv"
)
DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1.tsv"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_summary.json"
)
DEFAULT_CORE_TOOLS = [
    "Seurat",
    "Scanpy",
    "Harmony",
    "scvi-tools",
    "CellTypist",
    "SingleR",
    "cell2location",
    "scVelo",
    "CellRank",
    "Scrublet",
]

FIELDNAMES = [
    "priority",
    "evidence_kind",
    "tool_name",
    "record_id",
    "source_title",
    "source_url",
    "doi_or_pmid",
    "task",
    "modality",
    "current_audit_labels",
    "current_recommended_action",
    "recovery_goal",
    "required_review_fields",
    "suggested_source_lookup",
    "decision",
    "reviewed_by",
    "review_time",
    "reviewer_notes",
    "source_section",
    "source_figure_or_table",
    "source_span",
    "claim_text",
    "verified_task",
    "verified_modality",
    "canonical_scope",
    "authority_tier",
    "recommendation_eligible",
    "metric",
    "rank",
    "score",
    "normalized_score",
    "rank_scope",
    "n_tools_compared",
    "caveat_type",
    "promotion_ready",
]

PUBLICATION_REQUIRED = [
    "decision",
    "reviewed_by",
    "source_span",
    "claim_text",
    "verified_task",
    "verified_modality",
    "canonical_scope",
    "authority_tier",
    "recommendation_eligible",
]
BENCHMARK_REQUIRED = [
    "decision",
    "reviewed_by",
    "source_span",
    "metric",
    "rank_or_score_or_normalized_score",
    "rank_scope_or_n_tools_compared",
    "verified_task",
    "verified_modality",
    "caveat_type",
]


def read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in FIELDNAMES})


def build_packet(
    publication_audit: Iterable[Dict[str, str]],
    benchmark_audit: Iterable[Dict[str, str]],
    publication_rows: Iterable[Dict[str, str]],
    benchmark_rows: Iterable[Dict[str, str]],
    core_tools: Sequence[str],
) -> List[Dict[str, str]]:
    tool_priority = {normalize(tool): index + 1 for index, tool in enumerate(core_tools)}
    publications_by_id = {
        row.get("publication_id", ""): row
        for row in publication_rows
        if row.get("publication_id")
    }
    benchmarks_by_id = {
        row.get("benchmark_id", ""): row
        for row in benchmark_rows
        if row.get("benchmark_id")
    }
    rows: List[Dict[str, str]] = []
    for audit in publication_audit:
        key = normalize(audit.get("tool_name", ""))
        if key not in tool_priority:
            continue
        source = publications_by_id.get(audit.get("publication_id", ""), {})
        rows.append(publication_packet_row(audit, source, tool_priority[key]))
    for audit in benchmark_audit:
        key = normalize(audit.get("tool_name", ""))
        if key not in tool_priority:
            continue
        source = benchmarks_by_id.get(audit.get("benchmark_id", ""), {})
        rows.append(benchmark_packet_row(audit, source, tool_priority[key]))
    rows.sort(
        key=lambda row: (
            int(row["priority"]),
            row["tool_name"].lower(),
            0 if row["evidence_kind"] == "publication" else 1,
            row["record_id"],
        )
    )
    return rows


def publication_packet_row(audit: Dict[str, str], source: Dict[str, str], priority: int) -> Dict[str, str]:
    return {
        "priority": str(priority),
        "evidence_kind": "publication",
        "tool_name": audit.get("tool_name", ""),
        "record_id": audit.get("publication_id", ""),
        "source_title": audit.get("title", ""),
        "source_url": audit.get("source_url", "") or audit.get("paper_url", ""),
        "doi_or_pmid": audit.get("doi", "") or audit.get("pmid", "") or source.get("arxiv_id", ""),
        "task": audit.get("task", ""),
        "modality": audit.get("modality", ""),
        "current_audit_labels": audit.get("audit_labels", ""),
        "current_recommended_action": audit.get("recommended_action", ""),
        "recovery_goal": (
            "Verify this is a canonical method paper and add a source span beyond the title."
        ),
        "required_review_fields": ";".join(PUBLICATION_REQUIRED),
        "suggested_source_lookup": audit.get("source_url", "") or audit.get("paper_url", ""),
        "decision": "needs_manual_review",
        "reviewed_by": "",
        "review_time": "",
        "reviewer_notes": "",
        "source_section": "",
        "source_figure_or_table": "",
        "source_span": "",
        "claim_text": "",
        "verified_task": audit.get("task", ""),
        "verified_modality": audit.get("modality", ""),
        "canonical_scope": source.get("canonical_scope", audit.get("canonical_scope", "")),
        "authority_tier": source.get("authority_tier", audit.get("authority_tier", "")),
        "recommendation_eligible": source.get("recommendation_eligible", audit.get("recommendation_eligible", "")),
        "promotion_ready": "false",
    }


def benchmark_packet_row(audit: Dict[str, str], source: Dict[str, str], priority: int) -> Dict[str, str]:
    return {
        "priority": str(priority),
        "evidence_kind": "benchmark",
        "tool_name": audit.get("tool_name", ""),
        "record_id": audit.get("benchmark_id", ""),
        "source_title": audit.get("benchmark_name", "") or source.get("paper_title", ""),
        "source_url": audit.get("source_url", ""),
        "doi_or_pmid": audit.get("paper_doi", ""),
        "task": audit.get("task", ""),
        "modality": audit.get("modality", ""),
        "current_audit_labels": audit.get("audit_labels", ""),
        "current_recommended_action": audit.get("recommended_action", ""),
        "recovery_goal": (
            "Recover numeric/source-bound benchmark evidence, or keep as caveat/retrieval only."
        ),
        "required_review_fields": ";".join(BENCHMARK_REQUIRED),
        "suggested_source_lookup": audit.get("source_url", ""),
        "decision": "needs_manual_review",
        "reviewed_by": "",
        "review_time": "",
        "reviewer_notes": "",
        "source_section": "",
        "source_figure_or_table": "",
        "source_span": "",
        "claim_text": source.get("result_text", ""),
        "verified_task": audit.get("task", ""),
        "verified_modality": audit.get("modality", ""),
        "metric": audit.get("metric", ""),
        "rank": audit.get("rank", ""),
        "score": audit.get("score", ""),
        "normalized_score": audit.get("normalized_score", ""),
        "rank_scope": audit.get("rank_scope", ""),
        "n_tools_compared": audit.get("n_tools_compared", ""),
        "caveat_type": "caveat" if "negative_control_caveat" in audit.get("audit_labels", "") else "",
        "promotion_ready": "false",
    }


def summarize(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    by_kind: Dict[str, int] = {}
    by_tool: Dict[str, int] = {}
    for row in rows:
        by_kind[row["evidence_kind"]] = by_kind.get(row["evidence_kind"], 0) + 1
        by_tool[row["tool_name"]] = by_tool.get(row["tool_name"], 0) + 1
    return {"rows": len(rows), "by_kind": by_kind, "by_tool": by_tool}


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def normalize(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Evidence Recovery Sprint v1 review packet.")
    parser.add_argument("--publication-audit", type=Path, default=DEFAULT_PUBLICATION_AUDIT)
    parser.add_argument("--benchmark-audit", type=Path, default=DEFAULT_BENCHMARK_AUDIT)
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--tools", nargs="*", default=DEFAULT_CORE_TOOLS)
    args = parser.parse_args()

    rows = build_packet(
        read_tsv(args.publication_audit),
        read_tsv(args.benchmark_audit),
        read_tsv(args.publications),
        read_tsv(args.benchmarks),
        args.tools,
    )
    write_tsv(args.output, rows)
    summary = {"output": str(args.output), **summarize(rows)}
    args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
