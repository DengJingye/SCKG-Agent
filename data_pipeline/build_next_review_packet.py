import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_CANDIDATES = PROJECT_ROOT / "data" / "evidence_candidates"

DEFAULT_CORE_TOOLS = EVIDENCE_CANDIDATES / "core_50_tools.tsv"
DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_PUBLICATION_PACKET = EVIDENCE_CANDIDATES / "core50_publication_review_packet.tsv"
DEFAULT_BENCHMARK_SHORTLIST = EVIDENCE_CANDIDATES / "core50_benchmark_review_shortlist.tsv"
DEFAULT_OUTPUT = EVIDENCE_CANDIDATES / "core50_next_batch_review_packet.tsv"

APPROVED_REVIEW_STATUSES = {"reviewed", "verified", "human_reviewed"}
TARGET_TIERS = {"P0", "P1"}

OUTPUT_FIELDS = [
    "review_priority",
    "issue_type",
    "priority_tier",
    "tool_name",
    "current_publication_status",
    "current_benchmark_status",
    "current_graph_status",
    "formal_publication_ids",
    "formal_benchmark_ids",
    "candidate_publication_ids",
    "candidate_benchmark_ids",
    "suggested_action",
    "suggested_decision",
    "reviewer_needed_fields",
    "risk_notes",
    "formal_ingest_allowed_now",
    "recommendation_use_allowed_now",
    "reviewer_decision",
    "reviewer_notes",
]


PUBLICATION_GAP_POLICY = {
    "maestro": (
        "manual_publication_anchor_lookup",
        "Find and review the canonical MAESTRO method/workflow paper. Avoid secondary/editorial records.",
        "title;doi;publication_year;venue;authors;source_url;canonical_scope;evidence_category;authority_tier",
        "Current candidates include non-primary/secondary records; do not formalize shells.",
    ),
    "mimosca": (
        "boundary_review_keep_candidate",
        "Review whether MIMOSCA should remain candidate-only because tool/method/assay boundaries are mixed.",
        "scope_boundary;canonical_tool_name;primary_publication;doi;review_decision",
        "Perturbation framework boundary is ambiguous; conservative default is keep_candidate.",
    ),
    "mofa": (
        "legacy_or_provenance_review",
        "Decide whether MOFA v1 needs a formal legacy/provenance row or whether MOFA2 fully covers recommendation authority.",
        "legacy_status;primary_publication;doi;canonical_scope;recommendation_eligible",
        "MOFA2 is already formalized; avoid duplicate authority inflation across versions.",
    ),
    "singler": (
        "manual_publication_anchor_lookup",
        "Find and review the canonical SingleR primary paper or official citation.",
        "title;doi;publication_year;venue;authors;source_url;canonical_scope;evidence_category;authority_tier",
        "Current candidate pool contained non-primary abstract/noise; title/name collisions are possible.",
    ),
    "seurat": (
        "manual_major_version_anchor_lookup",
        "Add reviewed Seurat core/major-version anchors separately from wrapper/protocol ecosystem records.",
        "version_scope;title;doi;publication_year;venue;authors;source_url;canonical_scope;authority_tier",
        "Existing Seurat candidates are wrappers/protocols/extensions; core Seurat anchors must be manually injected.",
    ),
    "velociraptor": (
        "keep_no_candidate_or_wrapper_review",
        "Confirm whether velociraptor should stay wrapper/retrieval-only instead of canonical method evidence.",
        "tool_scope;wrapper_scope;primary_reference_if_any;review_decision",
        "Likely Bioconductor/interface wrapper; do not force canonical promotion.",
    ),
}

BENCHMARK_GAP_POLICY = {
    "scvelo": (
        "manual_benchmark_source_lookup",
        "Find a direct RNA velocity benchmark source evaluating scVelo or velocity methods with extractable metrics.",
        "benchmark_name;source_url;task;dataset;metric;direction;result_text_or_rank;comparison_set;evaluation_protocol",
        "Previous GRouNdGAN candidate was not a scVelo benchmark.",
    ),
    "scib": (
        "benchmark_framework_role_review",
        "Decide whether scIB should get benchmark evidence as a framework/source rather than as a tool being ranked.",
        "benchmark_role;benchmark_name;source_url;task;dataset;metric;direction;evaluation_protocol",
        "scIB is often the benchmark framework, not the evaluated tool; avoid self-benchmark confusion.",
    ),
    "singler": (
        "manual_benchmark_source_lookup",
        "Find a direct cell annotation benchmark that evaluates SingleR.",
        "benchmark_name;source_url;task;dataset;metric;direction;result_text_or_rank;n_tools_compared;evaluation_protocol",
        "Needed for annotation recommendation coverage alongside CellTypist.",
    ),
    "cellrank": (
        "manual_benchmark_source_lookup",
        "Find a direct fate-mapping/trajectory benchmark or reviewable comparative evaluation for CellRank.",
        "benchmark_name;source_url;task;dataset;metric;direction;result_text_or_rank;comparison_set;evaluation_protocol",
        "Current benchmark candidate was a shell; do not formalize without extractable facts.",
    ),
    "cell2location": (
        "manual_benchmark_source_lookup",
        "Find a direct spatial deconvolution/cell mapping benchmark evaluating cell2location.",
        "benchmark_name;source_url;task;dataset;metric;direction;result_text_or_rank;n_tools_compared;evaluation_protocol",
        "Spatial recommendation coverage needs benchmark support, not only primary method paper.",
    ),
    "scvi-tools": (
        "manual_benchmark_source_lookup",
        "Find benchmark evidence for scVI/scANVI/scvi-tools on integration/latent modeling tasks.",
        "benchmark_name;source_url;task;dataset;metric;direction;result_text_or_rank;comparison_set;evaluation_protocol",
        "Current benchmark candidate was a shell; avoid using GitHub/docs as scientific performance evidence.",
    ),
}


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: clean_cell(row.get(field, "")) for field in OUTPUT_FIELDS})


def clean_cell(value: str) -> str:
    return " ".join(str(value or "").split())


def normalize_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def approved(row: Dict[str, str]) -> bool:
    return (row.get("review_status") or "").strip().lower() in APPROVED_REVIEW_STATUSES


def target_core_tools(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    selected = []
    seen: Set[str] = set()
    for row in rows:
        tool_name = row.get("tool_name", "").strip()
        tier = row.get("priority_tier", "").strip()
        if not tool_name or tier not in TARGET_TIERS or normalize_name(tool_name) in seen:
            continue
        selected.append(row)
        seen.add(normalize_name(tool_name))
    return selected


def ids_by_tool(rows: List[Dict[str, str]], id_field: str) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        if not approved(row):
            continue
        tool_name = row.get("tool_name", "")
        evidence_id = row.get(id_field, "")
        if tool_name and evidence_id:
            grouped[normalize_name(tool_name)].append(evidence_id)
    return grouped


def candidate_publications_by_tool(rows: List[Dict[str, str]]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        tool_name = row.get("tool_name", "")
        publication_id = row.get("publication_id", "")
        decision = row.get("suggested_decision", "")
        if not tool_name or not publication_id or decision in {"likely_noise", "likely_duplicate"}:
            continue
        grouped[normalize_name(tool_name)].append(publication_id)
    return grouped


def candidate_benchmarks_by_tool(rows: List[Dict[str, str]]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        tool_name = row.get("tool_name", "")
        benchmark_id = row.get("benchmark_id", "")
        decision = row.get("candidate_decision", "")
        if not tool_name or not benchmark_id or decision == "likely_shell":
            continue
        grouped[normalize_name(tool_name)].append(benchmark_id)
    return grouped


def base_status(
    tool_key: str,
    formal_publications: Dict[str, List[str]],
    formal_benchmarks: Dict[str, List[str]],
    graph_gaps: Set[str],
) -> Dict[str, str]:
    return {
        "current_publication_status": "formal_present" if formal_publications.get(tool_key) else "missing_formal",
        "current_benchmark_status": "formal_present" if formal_benchmarks.get(tool_key) else "missing_formal",
        "current_graph_status": "tool_node_missing" if tool_key in graph_gaps else "not_checked_or_ok",
        "formal_publication_ids": ";".join(formal_publications.get(tool_key, [])),
        "formal_benchmark_ids": ";".join(formal_benchmarks.get(tool_key, [])),
    }


def build_rows(
    core_tools: List[Dict[str, str]],
    formal_publications: Dict[str, List[str]],
    formal_benchmarks: Dict[str, List[str]],
    candidate_publications: Dict[str, List[str]],
    candidate_benchmarks: Dict[str, List[str]],
    graph_gaps: Set[str],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for tool in core_tools:
        tool_name = tool.get("tool_name", "")
        tier = tool.get("priority_tier", "")
        key = normalize_name(tool_name)
        status = base_status(key, formal_publications, formal_benchmarks, graph_gaps)

        if key in graph_gaps:
            rows.append({
                **status,
                "review_priority": "P0",
                "issue_type": "graph_tool_node_missing",
                "priority_tier": tier,
                "tool_name": tool_name,
                "candidate_publication_ids": ";".join(candidate_publications.get(key, [])),
                "candidate_benchmark_ids": ";".join(candidate_benchmarks.get(key, [])),
                "suggested_action": "Create or sync the Tool node from data/scrna_tools.tsv, then rerun formal-only evidence backfill.",
                "suggested_decision": "fix_graph_tool_node",
                "reviewer_needed_fields": "tool_name;description;github_url;language;license",
                "risk_notes": "Formal evidence exists locally but cannot affect recommendations until it is attached to a Tool node.",
                "formal_ingest_allowed_now": "false",
                "recommendation_use_allowed_now": "false",
            })

        if not formal_publications.get(key):
            decision, action, fields, notes = PUBLICATION_GAP_POLICY.get(
                key,
                (
                    "manual_publication_anchor_lookup",
                    "Find and review a canonical publication anchor before formal ingestion.",
                    "title;doi;publication_year;venue;authors;source_url;canonical_scope;evidence_category;authority_tier",
                    "No approved formal publication evidence is present.",
                ),
            )
            rows.append({
                **status,
                "review_priority": "P0" if tier == "P0" else "P1",
                "issue_type": "publication_anchor_missing",
                "priority_tier": tier,
                "tool_name": tool_name,
                "candidate_publication_ids": ";".join(candidate_publications.get(key, [])),
                "candidate_benchmark_ids": ";".join(candidate_benchmarks.get(key, [])),
                "suggested_action": action,
                "suggested_decision": decision,
                "reviewer_needed_fields": fields,
                "risk_notes": notes,
                "formal_ingest_allowed_now": "false",
                "recommendation_use_allowed_now": "false",
            })

        if not formal_benchmarks.get(key):
            decision, action, fields, notes = BENCHMARK_GAP_POLICY.get(
                key,
                (
                    "manual_benchmark_source_lookup",
                    "Find a direct benchmark source only if this tool is recommendation-critical for a gold-query task.",
                    "benchmark_name;source_url;task;dataset;metric;direction;result_text_or_rank;n_tools_compared;evaluation_protocol",
                    "No approved formal benchmark evidence is present; current candidates may be shells or non-target sources.",
                ),
            )
            rows.append({
                **status,
                "review_priority": "P1" if tier in {"P0", "P1"} else "P2",
                "issue_type": "benchmark_source_missing",
                "priority_tier": tier,
                "tool_name": tool_name,
                "candidate_publication_ids": ";".join(candidate_publications.get(key, [])),
                "candidate_benchmark_ids": ";".join(candidate_benchmarks.get(key, [])),
                "suggested_action": action,
                "suggested_decision": decision,
                "reviewer_needed_fields": fields,
                "risk_notes": notes,
                "formal_ingest_allowed_now": "false",
                "recommendation_use_allowed_now": "false",
            })

    rows.sort(
        key=lambda row: (
            {"P0": 0, "P1": 1, "P2": 2}.get(row["review_priority"], 9),
            {"graph_tool_node_missing": 0, "publication_anchor_missing": 1, "benchmark_source_missing": 2}.get(row["issue_type"], 9),
            {"P0": 0, "P1": 1}.get(row["priority_tier"], 9),
            row["tool_name"].lower(),
        )
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the next human review packet after formal publication/benchmark backfill."
    )
    parser.add_argument("--core-tools", type=Path, default=DEFAULT_CORE_TOOLS)
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--publication-packet", type=Path, default=DEFAULT_PUBLICATION_PACKET)
    parser.add_argument("--benchmark-shortlist", type=Path, default=DEFAULT_BENCHMARK_SHORTLIST)
    parser.add_argument("--graph-node-gap", action="append", default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    core_tools = target_core_tools(load_tsv(args.core_tools))
    formal_publications = ids_by_tool(load_tsv(args.publications), "publication_id")
    formal_benchmarks = ids_by_tool(load_tsv(args.benchmarks), "benchmark_id")
    candidate_publications = candidate_publications_by_tool(load_tsv(args.publication_packet))
    candidate_benchmarks = candidate_benchmarks_by_tool(load_tsv(args.benchmark_shortlist))
    graph_gaps = {normalize_name(item) for item in args.graph_node_gap}

    rows = build_rows(
        core_tools=core_tools,
        formal_publications=formal_publications,
        formal_benchmarks=formal_benchmarks,
        candidate_publications=candidate_publications,
        candidate_benchmarks=candidate_benchmarks,
        graph_gaps=graph_gaps,
    )
    write_tsv(args.output, rows)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": len(rows),
                "by_issue_type": {
                    issue: sum(1 for row in rows if row["issue_type"] == issue)
                    for issue in sorted({row["issue_type"] for row in rows})
                },
                "formal_ingest_allowed_now": False,
                "recommendation_use_allowed_now": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
