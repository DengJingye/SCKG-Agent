from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constraints import parse_research_constraints
from core.evidence_policy import is_main_benchmark_evidence, is_main_publication_evidence
from data_pipeline.evidence_backfill import build_benchmark_evidence, build_publication_evidence
from engine.evidence_rag_pipeline import build_controlled_rag_context


DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_PUBLICATION_AUDIT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "formal_publication_audit.tsv"
)
DEFAULT_BENCHMARK_AUDIT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "formal_benchmark_audit.tsv"
)
DEFAULT_GOLD = PROJECT_ROOT / "eval" / "gold_queries_v0_1.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "evidence_recovery_smoke_summary.json"
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


def read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def audit_freeze_summary(publication_audit: List[Dict[str, str]], benchmark_audit: List[Dict[str, str]]) -> Dict[str, Any]:
    pub_allowed = [row for row in publication_audit if row.get("runtime_recommendation_allowed") == "true"]
    bmk_allowed = [row for row in benchmark_audit if row.get("runtime_recommendation_allowed") == "true"]
    return {
        "publication_rows": len(publication_audit),
        "benchmark_rows": len(benchmark_audit),
        "publication_runtime_allowed": len(pub_allowed),
        "benchmark_runtime_allowed": len(bmk_allowed),
        "publication_title_only_rows": count_label(publication_audit, "title_only_claim_span"),
        "publication_unclear_reviewer_rows": count_label(publication_audit, "reviewer_identity_unclear"),
        "benchmark_qualitative_only_rows": count_label(benchmark_audit, "qualitative_only"),
    }


def gate_summary(publications: List[Dict[str, str]], benchmarks: List[Dict[str, str]], tools: List[str]) -> Dict[str, Any]:
    violations: List[str] = []
    per_tool: Dict[str, Dict[str, int]] = {}
    for tool in tools:
        pub_items = build_publication_evidence(tool, publications)
        bmk_items = build_benchmark_evidence(tool, benchmarks)
        main_publications = [item for item in pub_items if is_main_publication_evidence(item)]
        main_benchmarks = [item for item in bmk_items if is_main_benchmark_evidence(item)]
        if main_publications:
            violations.append(f"{tool}: frozen publication evidence reached main gate")
        if main_benchmarks:
            violations.append(f"{tool}: frozen benchmark evidence reached main gate")
        per_tool[tool] = {
            "publication_items": len(pub_items),
            "benchmark_items": len(bmk_items),
            "main_publication_items": len(main_publications),
            "main_benchmark_items": len(main_benchmarks),
        }
    return {
        "trusted_non_main_violation_count": len(violations),
        "violations": violations,
        "per_tool": per_tool,
    }


def rag_smoke(gold_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    smoke_rows: List[Dict[str, Any]] = []
    for row in gold_rows:
        constraints = parse_research_constraints({}, row["query"]).model_dump()
        tools = row.get("expected_tools") or DEFAULT_CORE_TOOLS[:3]
        context = build_controlled_rag_context(
            constraints=constraints,
            tool_names=tools,
            max_snippets=5,
        )
        boundary_violations = [
            snippet.get("record_id") or snippet.get("chunk_id")
            for snippet in context.get("snippets", [])
            if "cannot promote" not in (snippet.get("claim_boundary") or "")
            and "manual review packet validation" not in (snippet.get("claim_boundary") or "")
        ]
        smoke_rows.append(
            {
                "id": row.get("id"),
                "expected_tools": tools,
                "mode": context.get("mode"),
                "snippet_count": context.get("snippet_count"),
                "matched_tools": context.get("matched_tools"),
                "boundary_violation_count": len(boundary_violations),
                "boundary_violations": boundary_violations,
            }
        )
    return smoke_rows


def count_label(rows: List[Dict[str, str]], label: str) -> int:
    return sum(1 for row in rows if label in (row.get("audit_labels") or "").split(";"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run conservative Evidence Recovery smoke checks.")
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--publication-audit", type=Path, default=DEFAULT_PUBLICATION_AUDIT)
    parser.add_argument("--benchmark-audit", type=Path, default=DEFAULT_BENCHMARK_AUDIT)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gold-limit", type=int, default=5)
    args = parser.parse_args()

    publication_audit = read_tsv(args.publication_audit)
    benchmark_audit = read_tsv(args.benchmark_audit)
    publications = read_tsv(args.publications)
    benchmarks = read_tsv(args.benchmarks)
    gold_rows = read_jsonl(args.gold, args.gold_limit)
    summary = {
        "audit_freeze": audit_freeze_summary(publication_audit, benchmark_audit),
        "gate": gate_summary(publications, benchmarks, DEFAULT_CORE_TOOLS),
        "rag_smoke": rag_smoke(gold_rows),
    }
    summary["passed"] = (
        summary["audit_freeze"]["publication_runtime_allowed"] == 0
        and summary["audit_freeze"]["benchmark_runtime_allowed"] == 0
        and summary["gate"]["trusted_non_main_violation_count"] == 0
        and all(row["boundary_violation_count"] == 0 for row in summary["rag_smoke"])
    )
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
