import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_REPORT = PROJECT_ROOT / "data" / "evidence_candidates" / "kg_quality_audit_report.tsv"
DEFAULT_ACTIONS = PROJECT_ROOT / "data" / "evidence_candidates" / "kg_quality_review_actions.tsv"

APPROVED_REVIEW_STATUSES = {"reviewed", "verified", "human_reviewed"}
REJECTED_REVIEW_STATUSES = {"rejected", "deprecated"}
TRUSTED_CORE = "trusted_core"
HIGH_DEGREE_THRESHOLD = 8
TASK_PLACEHOLDERS = {
    "",
    "-",
    "na",
    "n/a",
    "none",
    "null",
    "unknown",
    "unspecified",
    "not specified",
    "tbd",
}

REPORT_FIELDS = [
    "severity",
    "issue_type",
    "table_name",
    "record_id",
    "tool_name",
    "field_name",
    "field_value",
    "issue_detail",
    "suggested_action",
    "recommendation_grade_risk",
]

ACTION_FIELDS = [
    "review_priority",
    "action_type",
    "table_name",
    "record_id",
    "tool_name",
    "issue_types",
    "current_value",
    "recommended_action",
    "formal_table_mutation_allowed",
    "reviewer_decision",
    "reviewer_notes",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only KG quality audit for formal evidence TSVs.")
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--actions", type=Path, default=DEFAULT_ACTIONS)
    args = parser.parse_args()

    publication_rows = load_tsv(args.publications)
    benchmark_rows = load_tsv(args.benchmarks)
    issues: List[Dict[str, str]] = []

    audit_rows("tool_publications", publication_rows, "publication_id", issues)
    audit_rows("tool_benchmarks", benchmark_rows, "benchmark_id", issues)
    audit_duplicates("tool_publications", publication_rows, "publication_id", ["doi", "title"], issues)
    audit_duplicates("tool_benchmarks", benchmark_rows, "benchmark_id", ["paper_doi", "paper_title"], issues)
    audit_edge_support(publication_rows, benchmark_rows, issues)
    audit_duplicate_evidence_edges(publication_rows, benchmark_rows, issues)
    audit_default_trunk_isolation(publication_rows, benchmark_rows, issues)

    issues.sort(key=issue_sort_key)
    actions = build_review_actions(issues)
    write_tsv(args.report, issues, REPORT_FIELDS)
    write_tsv(args.actions, actions, ACTION_FIELDS)

    print(f"kg_quality_audit_report={args.report}")
    print(f"kg_quality_review_actions={args.actions}")
    print(f"issue_count={len(issues)}")
    print(f"review_action_count={len(actions)}")


def audit_rows(
    table_name: str,
    rows: Sequence[Dict[str, str]],
    id_field: str,
    issues: List[Dict[str, str]],
) -> None:
    for row in rows:
        record_id = clean(row.get(id_field)) or "<missing_id>"
        tool_name = clean(row.get("tool_name"))
        status = clean(row.get("review_status")).lower()
        trust = clean(row.get("trust_level")).lower()
        task_value = clean(row.get("task"))

        if has_candidate_marker(row, id_field):
            add_issue(
                issues,
                "medium",
                "candidate_marker_in_formal_table",
                table_name,
                record_id,
                tool_name,
                id_field,
                row.get(id_field, ""),
                "Formal evidence row still carries candidate-origin markers such as CAND_* or candidate_only notes.",
                "Review provenance wording and decide whether to normalize record IDs/notes without changing evidence meaning.",
                "medium",
            )
        if is_placeholder_task(task_value):
            add_issue(
                issues,
                "medium",
                "empty_task_node",
                table_name,
                record_id,
                tool_name,
                "task",
                row.get("task", ""),
                "Task value is blank or placeholder-like, so the row cannot become a meaningful Tool-Task node in the default trunk.",
                "Either supply a reviewed task label or keep the record evidence-only until task mapping is approved.",
                "medium",
            )
        if status not in APPROVED_REVIEW_STATUSES:
            severity = "critical" if status in REJECTED_REVIEW_STATUSES else "high"
            add_issue(
                issues,
                severity,
                "unapproved_review_status",
                table_name,
                record_id,
                tool_name,
                "review_status",
                row.get("review_status", ""),
                "Formal graph rows must use reviewed, verified, or human_reviewed status.",
                "Keep outside trusted graph until human review status is approved.",
                "high",
            )
        if trust and trust != TRUSTED_CORE:
            add_issue(
                issues,
                "high",
                "non_trusted_core_in_formal_table",
                table_name,
                record_id,
                tool_name,
                "trust_level",
                row.get("trust_level", ""),
                "Formal KG view expects trusted_core records only.",
                "Downgrade to candidate/retrieval-only pathway or re-review before trusted display.",
                "high",
            )
        for field in required_fields(table_name):
            if not clean(row.get(field)):
                add_issue(
                    issues,
                    missing_field_severity(field),
                    f"missing_{field}",
                    table_name,
                    record_id,
                    tool_name,
                    field,
                    "",
                    f"Required or governance-significant field is blank: {field}.",
                    suggested_missing_action(table_name, field),
                    missing_field_risk(field),
                )


def audit_duplicates(
    table_name: str,
    rows: Sequence[Dict[str, str]],
    id_field: str,
    fields: Iterable[str],
    issues: List[Dict[str, str]],
) -> None:
    for field in fields:
        grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        for row in rows:
            value = normalize_key(row.get(field, ""))
            if value:
                grouped[value].append(row)
        for value, group in grouped.items():
            if len(group) <= 1:
                continue
            ids = ";".join(clean(row.get(id_field)) for row in group)
            tools = ";".join(sorted({clean(row.get("tool_name")) for row in group if clean(row.get("tool_name"))}))
            for row in group:
                add_issue(
                    issues,
                    "medium",
                    f"duplicate_{field}",
                    table_name,
                    clean(row.get(id_field)),
                    clean(row.get("tool_name")),
                    field,
                    clean(row.get(field)),
                    f"{field} appears in multiple formal rows: {ids}; tools={tools}.",
                    "Review whether rows should share work_group_id or be marked non-canonical/supporting.",
                    "medium",
                )


def audit_edge_support(
    publication_rows: Sequence[Dict[str, str]],
    benchmark_rows: Sequence[Dict[str, str]],
    issues: List[Dict[str, str]],
) -> None:
    edges = []
    for row in publication_rows:
        for task in split_terms(row.get("task")):
            edges.append(("tool_publications", clean(row.get("publication_id")), clean(row.get("tool_name")), task))
    for row in benchmark_rows:
        for task in split_terms(row.get("task")):
            edges.append(("tool_benchmarks", clean(row.get("benchmark_id")), clean(row.get("tool_name")), task))

    edge_counter = Counter((tool, task) for _, _, tool, task in edges if tool and task)
    for (tool, task), count in edge_counter.items():
        if count <= 1:
            continue
        add_issue(
            issues,
            "low",
            "duplicate_tool_task_edge",
            "graph_edges",
            f"{safe_id(tool)}__{safe_id(task)}",
            tool,
            "tool_task",
            task,
            f"Tool-task relation is supported by {count} formal rows; graph should preserve provenance without visual edge inflation.",
            "Keep one visual edge and expose provenance count/details in node or edge metadata.",
            "low",
        )

    degree = Counter()
    for _, _, tool, task in edges:
        if tool:
            degree[f"Tool:{tool}"] += 1
        if task:
            degree[f"Task:{task}"] += 1
    for node_id, count in degree.items():
        if count < HIGH_DEGREE_THRESHOLD:
            continue
        kind, value = node_id.split(":", 1)
        add_issue(
            issues,
            "low",
            "high_degree_hub",
            "graph_nodes",
            safe_id(node_id),
            value if kind == "Tool" else "",
            "degree",
            str(count),
            f"{kind} node has high degree and may dominate default visualization.",
            "Use default Tool-Task trunk, search-first expansion, or per-kind limits to reduce visual hub effects.",
            "low",
        )


def audit_duplicate_evidence_edges(
    publication_rows: Sequence[Dict[str, str]],
    benchmark_rows: Sequence[Dict[str, str]],
    issues: List[Dict[str, str]],
) -> None:
    publication_edges: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    for row in publication_rows:
        tool = clean(row.get("tool_name"))
        publication_key = publication_edge_key(row)
        if tool and publication_key:
            publication_edges[(tool, publication_key)].append(row)

    for (tool, publication_key), group in publication_edges.items():
        if len(group) <= 1:
            continue
        ids = ";".join(clean(row.get("publication_id")) for row in group)
        for row in group:
            add_issue(
                issues,
                "medium",
                "duplicate_tool_publication_edge",
                "tool_publications",
                clean(row.get("publication_id")),
                tool,
                "tool_publication_edge",
                f"{tool}->{publication_key}",
                f"Multiple formal publication rows create the same Tool-Publication edge: {ids}.",
                "Keep one edge, merge provenance into metadata, and review whether rows belong to the same work_group_id.",
                "medium",
            )

    benchmark_edges: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    for row in benchmark_rows:
        tool = clean(row.get("tool_name"))
        benchmark_key = benchmark_edge_key(row)
        if tool and benchmark_key:
            benchmark_edges[(tool, benchmark_key)].append(row)

    for (tool, benchmark_key), group in benchmark_edges.items():
        if len(group) <= 1:
            continue
        ids = ";".join(clean(row.get("benchmark_id")) for row in group)
        for row in group:
            add_issue(
                issues,
                "medium",
                "duplicate_tool_benchmark_edge",
                "tool_benchmarks",
                clean(row.get("benchmark_id")),
                tool,
                "tool_benchmark_edge",
                f"{tool}->{benchmark_key}",
                f"Multiple formal benchmark rows create the same Tool-Benchmark edge: {ids}.",
                "Keep one edge, merge provenance into metadata, and review whether rows belong to the same work_group_id.",
                "medium",
            )


def audit_default_trunk_isolation(
    publication_rows: Sequence[Dict[str, str]],
    benchmark_rows: Sequence[Dict[str, str]],
    issues: List[Dict[str, str]],
) -> None:
    for row in publication_rows:
        tool = clean(row.get("tool_name"))
        tasks = split_terms(row.get("task"))
        if tool and not tasks:
            add_issue(
                issues,
                "medium",
                "default_trunk_isolated_tool",
                "tool_publications",
                clean(row.get("publication_id")),
                tool,
                "task",
                row.get("task", ""),
                "This tool will not appear in the default Tool-Task trunk because no reviewed task edge can be drawn.",
                "Add a reviewed task mapping, or keep the row evidence-only until the task relationship is approved.",
                "medium",
            )

    for row in benchmark_rows:
        tool = clean(row.get("tool_name"))
        tasks = split_terms(row.get("task"))
        if tool and not tasks:
            add_issue(
                issues,
                "medium",
                "default_trunk_isolated_tool",
                "tool_benchmarks",
                clean(row.get("benchmark_id")),
                tool,
                "task",
                row.get("task", ""),
                "This tool will not appear in the default Tool-Task trunk because no reviewed task edge can be drawn.",
                "Add a reviewed task mapping, or keep the row evidence-only until the task relationship is approved.",
                "medium",
            )


def build_review_actions(issues: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    grouped: Dict[tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for issue in issues:
        key = (issue["table_name"], issue["record_id"], issue["tool_name"])
        grouped[key].append(issue)

    actions = []
    for (table_name, record_id, tool_name), group in grouped.items():
        severities = [item["severity"] for item in group]
        issue_types = sorted({item["issue_type"] for item in group})
        actions.append(
            {
                "review_priority": priority_from_severity(severities),
                "action_type": action_type(issue_types),
                "table_name": table_name,
                "record_id": record_id,
                "tool_name": tool_name,
                "issue_types": ";".join(issue_types),
                "current_value": "; ".join(
                    f"{item['field_name']}={item['field_value']}" for item in group[:8]
                ),
                "recommended_action": "; ".join(unique(item["suggested_action"] for item in group))[:900],
                "formal_table_mutation_allowed": "false",
                "reviewer_decision": "",
                "reviewer_notes": "",
            }
        )
    actions.sort(key=action_sort_key)
    return actions


def required_fields(table_name: str) -> List[str]:
    if table_name == "tool_publications":
        return [
            "work_group_id",
            "canonical_flag",
            "tool_name",
            "title",
            "doi",
            "pmid",
            "task",
            "review_status",
            "trust_level",
            "canonical_scope",
            "evidence_category",
            "recommendation_eligible",
            "authority_tier",
        ]
    return [
        "work_group_id",
        "canonical_flag",
        "benchmark_name",
        "task",
        "tool_name",
        "metric",
        "paper_doi",
        "paper_pmid",
        "review_status",
        "trust_level",
    ]


def missing_field_severity(field: str) -> str:
    if field in {"work_group_id", "review_status", "trust_level", "canonical_flag"}:
        return "high"
    if field in {"task", "doi", "paper_doi", "metric"}:
        return "medium"
    return "low"


def missing_field_risk(field: str) -> str:
    if field in {"review_status", "trust_level", "canonical_flag", "work_group_id"}:
        return "high"
    if field in {"task", "doi", "paper_doi"}:
        return "medium"
    return "low"


def suggested_missing_action(table_name: str, field: str) -> str:
    if field == "work_group_id":
        return "Assign conservative work_group_id through human-reviewed canonical grouping."
    if field in {"pmid", "paper_pmid"}:
        return "Lookup PMID where available; if no PMID exists, record explicit no_pmid reason in review notes."
    if field == "task":
        return "Add reviewed task mapping or keep record evidence-only without Tool-Task visual edge."
    if field in {"canonical_scope", "evidence_category", "authority_tier", "recommendation_eligible"}:
        return "Complete governance fields before using as recommendation-grade evidence."
    return f"Review and fill {field} if supported by source metadata."


def has_candidate_marker(row: Dict[str, str], id_field: str) -> bool:
    fields = [id_field, "source_record_id", "notes", "extraction_method"]
    values = " ".join(row.get(field, "") or "" for field in fields)
    lowered = values.lower()
    return (
        "cand" in lowered
        or "candidate" in lowered
        or "candidate_only" in lowered
        or "candidate extraction" in lowered
    )


def is_placeholder_task(value: str) -> bool:
    lowered = clean(value).lower()
    return lowered in TASK_PLACEHOLDERS or lowered.startswith("unknown") or lowered.startswith("not ")


def publication_edge_key(row: Dict[str, str]) -> str:
    return normalize_key(row.get("doi", "")) or normalize_key(row.get("title", "")) or clean(row.get("publication_id"))


def benchmark_edge_key(row: Dict[str, str]) -> str:
    return normalize_key(row.get("paper_doi", "")) or normalize_key(row.get("paper_title", "")) or clean(row.get("benchmark_id"))


def add_issue(
    issues: List[Dict[str, str]],
    severity: str,
    issue_type: str,
    table_name: str,
    record_id: str,
    tool_name: str,
    field_name: str,
    field_value: str,
    issue_detail: str,
    suggested_action: str,
    recommendation_grade_risk: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "issue_type": issue_type,
            "table_name": table_name,
            "record_id": record_id,
            "tool_name": tool_name,
            "field_name": field_name,
            "field_value": one_line(field_value),
            "issue_detail": one_line(issue_detail),
            "suggested_action": one_line(suggested_action),
            "recommendation_grade_risk": recommendation_grade_risk,
        }
    )


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Iterable[Dict[str, str]], fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in fields})


def split_terms(value: str) -> List[str]:
    return [part for part in (clean(part) for part in clean(value).split(";")) if part and not is_placeholder_task(part)]


def clean(value: str | None) -> str:
    return " ".join(str(value or "").split())


def one_line(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", clean(value)).strip("_") or "unknown"


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def priority_from_severity(severities: Sequence[str]) -> str:
    if "critical" in severities:
        return "P0"
    if "high" in severities:
        return "P1"
    if "medium" in severities:
        return "P2"
    return "P3"


def action_type(issue_types: Sequence[str]) -> str:
    if any(issue.startswith("missing_work_group_id") or issue.startswith("duplicate_") for issue in issue_types):
        return "canonical_group_review"
    if "candidate_marker_in_formal_table" in issue_types:
        return "formal_provenance_cleanup_review"
    if any(issue.startswith("missing_") for issue in issue_types):
        return "metadata_completion_review"
    if "high_degree_hub" in issue_types:
        return "visualization_policy_review"
    return "quality_review"


def issue_sort_key(issue: Dict[str, str]) -> tuple[int, str, str, str]:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return (
        severity_order.get(issue["severity"], 9),
        issue["issue_type"],
        issue["table_name"],
        issue["record_id"],
    )


def action_sort_key(action: Dict[str, str]) -> tuple[str, str, str]:
    return (action["review_priority"], action["table_name"], action["record_id"])


if __name__ == "__main__":
    main()
