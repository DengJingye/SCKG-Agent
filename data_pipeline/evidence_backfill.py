import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.graph_client import Neo4jClient
from core.evidence_schemas import APPROVED_REVIEW_STATUSES, REJECTED_REVIEW_STATUSES
from core.models import Evidence, ReviewStatus
from core.settings import get_settings
from data_pipeline.github_crawler import GitHubCrawler


DEFAULT_QUEUE = PROJECT_ROOT / "eval" / "review_queue_organized.jsonl"
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "scrna_tools.tsv"
DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_PLAN_OUTPUT = PROJECT_ROOT / "eval" / "evidence_backfill_plan.jsonl"

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
RECOMMENDATION_USE = ["retrieval", "ranking", "recommendation"]
RETRIEVAL_USE = ["retrieval"]
RECOMMENDATION_ELIGIBLE_SCOPES = {"core_tool", "major_version"}
RECOMMENDATION_ELIGIBLE_CATEGORIES = {"architectural_core"}
RECOMMENDATION_ELIGIBLE_AUTHORITY_TIERS = {"canonical_primary", "canonical_secondary"}
BENCHMARK_CONTEXT_FIELDS = ["task", "dataset", "metric", "direction", "evaluation_protocol"]
BENCHMARK_RESULT_FIELDS = ["rank", "score", "normalized_score"]
BENCHMARK_QUALITATIVE_RESULT_FIELDS = ["result_text"]
BENCHMARK_COMPARISON_FIELDS = ["n_tools_compared", "rank_scope"]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def evidence_safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", value.strip())
    return cleaned.strip("_") or "unknown"


def select_tools(queue: List[Dict[str, Any]], max_tools: int) -> List[str]:
    tool_rows = [
        row for row in queue
        if row.get("item_type") == "tool"
        and row.get("review_bucket") == "evidence_backfill"
    ]
    tool_rows.sort(
        key=lambda row: (
            PRIORITY_ORDER.get(row.get("priority", "medium"), 2),
            -int(row.get("hit_count", 0)),
            row.get("tool_name", ""),
        )
    )
    selected: List[str] = []
    seen = set()
    for row in tool_rows:
        tool_name = row.get("tool_name")
        if not tool_name or tool_name in seen:
            continue
        selected.append(tool_name)
        seen.add(tool_name)
        if len(selected) >= max_tools:
            break
    return selected


def include_formal_evidence_tools(
    selected: List[str],
    publication_rows: Iterable[Dict[str, str]],
    benchmark_rows: Iterable[Dict[str, str]],
    max_tools: int,
) -> List[str]:
    """Extend backfill selection with tools that already have formal evidence."""
    merged = list(selected)
    seen = {normalize_name(tool) for tool in merged}
    for row in [*publication_rows, *benchmark_rows]:
        tool_name = clean_optional(row.get("tool_name"))
        if not tool_name or not is_approved_for_ingest(row):
            continue
        key = normalize_name(tool_name)
        if key in seen:
            continue
        merged.append(tool_name)
        seen.add(key)
        if len(merged) >= max_tools:
            break
    return merged


def select_formal_evidence_tools(
    publication_rows: Iterable[Dict[str, str]],
    benchmark_rows: Iterable[Dict[str, str]],
    max_tools: int,
) -> List[str]:
    """Select tools with approved formal publication or benchmark evidence only."""
    selected: List[str] = []
    seen = set()
    for row in [*publication_rows, *benchmark_rows]:
        tool_name = clean_optional(row.get("tool_name"))
        if not tool_name or not is_approved_for_ingest(row):
            continue
        key = normalize_name(tool_name)
        if key in seen:
            continue
        selected.append(tool_name)
        seen.add(key)
        if len(selected) >= max_tools:
            break
    return selected


def build_catalog_index(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    index: Dict[str, Dict[str, str]] = {}
    for row in rows:
        name = (row.get("Tool") or row.get("tool_name") or "").strip()
        if not name:
            continue
        index[name] = row
        index[normalize_name(name)] = row
    return index


def get_catalog_row(tool_name: str, catalog_index: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    return catalog_index.get(tool_name) or catalog_index.get(normalize_name(tool_name)) or {}


def build_docs_evidence(tool_name: str, catalog_row: Dict[str, str]) -> Optional[Evidence]:
    source_url = clean_optional(catalog_row.get("Code"))
    description = clean_optional(catalog_row.get("Description"))
    if not source_url and not description:
        return None
    return Evidence(
        evidence_id=f"docs:{evidence_safe_id(tool_name)}:catalog_entry",
        source_type="docs",
        source_url=source_url,
        source_title=f"scrna-tools catalog entry for {tool_name}",
        metric_name="official_docs_support",
        metric_value="present",
        metric_unit="boolean",
        dataset_scope="tool_metadata_catalog",
        evidence_strength="medium",
        confidence=0.75,
        trust_level="source_based",
        graph_layer="trusted_core",
        use_for=RECOMMENDATION_USE,
        extraction_method="data_pipeline/evidence_backfill.py:catalog_entry",
        review_status="auto_checked",
        kg_version=get_settings().kg_version,
    )


def build_github_evidence(
    tool_name: str,
    github_url: str,
    metrics: Dict[str, Any],
) -> List[Evidence]:
    if metrics.get("error"):
        return []
    source_url = metrics.get("repo_url") or github_url
    specs = [
        ("github_stars", metrics.get("github_stars"), "count", RECOMMENDATION_USE),
        ("last_updated", metrics.get("last_updated"), "date", RECOMMENDATION_USE),
        ("maintenance_status", metrics.get("maintenance_status"), "category", RECOMMENDATION_USE),
        ("forks", metrics.get("forks"), "count", RETRIEVAL_USE),
        ("open_issues", metrics.get("open_issues"), "count", RETRIEVAL_USE),
        ("archived", metrics.get("archived"), "boolean", RETRIEVAL_USE),
        ("default_branch", metrics.get("default_branch"), "branch", RETRIEVAL_USE),
        ("license", metrics.get("license"), "spdx", RETRIEVAL_USE),
    ]
    evidence_items: List[Evidence] = []
    for metric_name, metric_value, metric_unit, use_for in specs:
        if metric_value is None or metric_value == "":
            continue
        evidence_items.append(
            Evidence(
                evidence_id=f"github:{evidence_safe_id(tool_name)}:{metric_name}",
                source_type="github",
                source_url=source_url,
                source_title=f"GitHub repository metadata for {tool_name}",
                metric_name=metric_name,
                metric_value=metric_value,
                metric_unit=metric_unit,
                dataset_scope="global_repository",
                evidence_strength="medium",
                confidence=0.9,
                trust_level="source_based",
                graph_layer="trusted_core",
                use_for=use_for,
                extraction_method="data_pipeline/evidence_backfill.py:github_api",
                review_status="auto_checked",
                kg_version=get_settings().kg_version,
            )
        )
    return evidence_items


def build_publication_evidence(
    tool_name: str,
    rows: Iterable[Dict[str, str]],
) -> List[Evidence]:
    evidence_items: List[Evidence] = []
    for row in rows:
        if not same_tool(tool_name, row.get("tool_name", "")):
            continue
        if not is_approved_for_ingest(row):
            continue
        citations = parse_number(row.get("citations"))
        metric_name = "citations" if citations is not None else "paper_support"
        metric_value: Any = citations if citations is not None else "present"
        identifier = (
            row.get("publication_id")
            or row.get("pmid")
            or row.get("doi")
            or row.get("title")
            or metric_name
        )
        paper_url = (
            clean_optional(row.get("paper_url"))
            or clean_optional(row.get("source_url"))
            or doi_url(row.get("doi"))
        )
        graph_trust, graph_layer, use_for = trust_policy(row)
        evidence_items.append(
            Evidence(
                evidence_id=f"paper:{evidence_safe_id(tool_name)}:{evidence_safe_id(identifier)}",
                source_type="paper",
                source_url=paper_url,
                source_title=clean_optional(row.get("title")) or f"Publication evidence for {tool_name}",
                metric_name=metric_name,
                metric_value=metric_value,
                metric_unit="count" if citations is not None else "boolean",
                dataset_scope=publication_dataset_scope(row),
                evidence_strength="strong" if citations is not None else "medium",
                confidence=parse_float(row.get("confidence"), 0.9),
                trust_level=graph_trust,
                graph_layer=graph_layer,
                use_for=use_for,
                extraction_method=clean_optional(row.get("extraction_method"))
                or "data_pipeline/evidence_backfill.py:curated_publications_tsv",
                review_status=review_status(row.get("review_status"), "human_reviewed"),
                kg_version=get_settings().kg_version,
                human_review_decision=clean_optional(row.get("human_review_decision")) or "",
                canonical_scope=clean_optional(row.get("canonical_scope")) or "",
                evidence_category=clean_optional(row.get("evidence_category")) or "",
                recommendation_eligible=parse_bool(row.get("recommendation_eligible")),
                authority_tier=clean_optional(row.get("authority_tier")) or "",
                audit_support_level=clean_optional(row.get("audit_support_level")) or "",
            )
        )
    return evidence_items


def build_benchmark_evidence(
    tool_name: str,
    rows: Iterable[Dict[str, str]],
) -> List[Evidence]:
    evidence_items: List[Evidence] = []
    for row in rows:
        if not same_tool(tool_name, row.get("tool_name", "")):
            continue
        if not is_approved_for_ingest(row):
            continue
        rank = parse_number(row.get("rank"))
        score = parse_number(row.get("normalized_score"))
        if score is None:
            score = parse_number(row.get("score"))
        source_url = clean_optional(row.get("source_url"))
        benchmark_name = (
            clean_optional(row.get("benchmark_name"))
            or clean_optional(row.get("benchmark_id"))
            or "benchmark"
        )
        benchmark_type = clean_optional(row.get("benchmark_type")) or ""
        dataset_scope = benchmark_dataset_scope(row)
        graph_trust, graph_layer, use_for = benchmark_trust_policy(row)
        if rank is not None:
            evidence_items.append(
                benchmark_evidence_item(
                    tool_name=tool_name,
                    benchmark_name=benchmark_name,
                    source_url=source_url,
                    dataset_scope=dataset_scope,
                    metric_name="benchmark_rank",
                    metric_value=rank,
                    metric_unit="rank",
                    benchmark_type=benchmark_type,
                    confidence=parse_float(row.get("confidence"), 0.9),
                    review=row.get("review_status"),
                    graph_trust=graph_trust,
                    graph_layer=graph_layer,
                    use_for=use_for,
                    extraction_method=clean_optional(row.get("extraction_method")),
                )
            )
        if score is not None:
            evidence_items.append(
                benchmark_evidence_item(
                    tool_name=tool_name,
                    benchmark_name=benchmark_name,
                    source_url=source_url,
                    dataset_scope=dataset_scope,
                    metric_name="benchmark_score",
                    metric_value=score,
                    metric_unit=clean_optional(row.get("metric")) or "score",
                    benchmark_type=benchmark_type,
                    confidence=parse_float(row.get("confidence"), 0.9),
                    review=row.get("review_status"),
                    graph_trust=graph_trust,
                    graph_layer=graph_layer,
                    use_for=use_for,
                    extraction_method=clean_optional(row.get("extraction_method")),
                )
            )
        result_text = clean_optional(row.get("result_text"))
        if rank is None and score is None and result_text:
            evidence_items.append(
                benchmark_evidence_item(
                    tool_name=tool_name,
                    benchmark_name=benchmark_name,
                    source_url=source_url,
                    dataset_scope=dataset_scope,
                    metric_name="benchmark_result",
                    metric_value=result_text,
                    metric_unit=clean_optional(row.get("metric")) or "qualitative_result",
                    benchmark_type=benchmark_type,
                    confidence=parse_float(row.get("confidence"), 0.9),
                    review=row.get("review_status"),
                    graph_trust=graph_trust,
                    graph_layer=graph_layer,
                    use_for=use_for,
                    extraction_method=clean_optional(row.get("extraction_method")),
                )
            )
    return evidence_items


def benchmark_evidence_item(
    tool_name: str,
    benchmark_name: str,
    source_url: Optional[str],
    dataset_scope: str,
    metric_name: str,
    metric_value: Any,
    metric_unit: str,
    benchmark_type: str,
    confidence: float,
    review: Optional[str],
    graph_trust: str = "verified",
    graph_layer: str = "trusted_core",
    use_for: Optional[List[str]] = None,
    extraction_method: Optional[str] = None,
) -> Evidence:
    return Evidence(
        evidence_id=(
            f"benchmark:{evidence_safe_id(tool_name)}:"
            f"{evidence_safe_id(benchmark_name)}:{metric_name}"
        ),
        source_type="benchmark",
        source_url=source_url,
        source_title=benchmark_name,
        metric_name=metric_name,
        metric_value=metric_value,
        metric_unit=metric_unit,
        benchmark_type=benchmark_type,
        dataset_scope=dataset_scope,
        evidence_strength="strong",
        confidence=confidence,
        trust_level=graph_trust,
        graph_layer=graph_layer,
        use_for=use_for or RECOMMENDATION_USE,
        extraction_method=extraction_method
        or "data_pipeline/evidence_backfill.py:curated_benchmarks_tsv",
        review_status=review_status(review, "human_reviewed"),
        kg_version=get_settings().kg_version,
    )


def benchmark_has_minimum_context(row: Dict[str, str]) -> bool:
    has_context = all(clean_optional(row.get(field)) for field in BENCHMARK_CONTEXT_FIELDS)
    has_numeric_result = any(parse_number(row.get(field)) is not None for field in BENCHMARK_RESULT_FIELDS)
    has_qualitative_result = any(clean_optional(row.get(field)) for field in BENCHMARK_QUALITATIVE_RESULT_FIELDS)
    has_result = has_numeric_result or has_qualitative_result
    has_comparison = any(clean_optional(row.get(field)) for field in BENCHMARK_COMPARISON_FIELDS)
    return has_context and has_result and has_comparison


def benchmark_trust_policy(row: Dict[str, str]) -> tuple[str, str, List[str]]:
    if not benchmark_has_minimum_context(row):
        return "source_based", "review_needed", RETRIEVAL_USE
    trust = (clean_optional(row.get("trust_level")) or "review_needed").lower()
    if trust == "trusted_core":
        return "verified", "trusted_core", RECOMMENDATION_USE
    if trust == "review_needed":
        return "source_based", "review_needed", RETRIEVAL_USE
    if trust == "retrieval_only":
        return "inferred", "experimental", RETRIEVAL_USE
    return "model_extracted", "experimental", RETRIEVAL_USE


def same_tool(left: str, right: str) -> bool:
    return normalize_name(left) == normalize_name(right)


def clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped or stripped.lower() in {"na", "nan", "none", "unknown"}:
        return None
    return stripped


def parse_number(value: Optional[str]) -> Optional[float | int]:
    stripped = clean_optional(value)
    if stripped is None:
        return None
    try:
        as_float = float(stripped)
    except ValueError:
        return None
    if as_float.is_integer():
        return int(as_float)
    return as_float


def parse_float(value: Optional[str], default: float) -> float:
    parsed = parse_number(value)
    if parsed is None:
        return default
    return max(0.0, min(float(parsed), 1.0))


def parse_bool(value: Optional[str]) -> Optional[bool]:
    stripped = clean_optional(value)
    if stripped is None:
        return None
    normalized = stripped.lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    return None


def is_approved_for_ingest(row: Dict[str, str]) -> bool:
    status = (clean_optional(row.get("review_status")) or "").lower()
    if status in REJECTED_REVIEW_STATUSES:
        return False
    return status in APPROVED_REVIEW_STATUSES


def trust_policy(row: Dict[str, str]) -> tuple[str, str, List[str]]:
    recommendation_eligible = (clean_optional(row.get("recommendation_eligible")) or "").lower()
    audit_support = (clean_optional(row.get("audit_support_level")) or "").lower()
    canonical_scope = (clean_optional(row.get("canonical_scope")) or "").lower()
    evidence_category = (clean_optional(row.get("evidence_category")) or "").lower()
    authority_tier = (clean_optional(row.get("authority_tier")) or "").lower()
    if recommendation_eligible in {"false", "no", "0"}:
        if audit_support == "provenance_only":
            return "inferred", "experimental", RETRIEVAL_USE
        return "verified", "trusted_core", RETRIEVAL_USE
    if (
        canonical_scope
        and evidence_category
        and (
            canonical_scope not in RECOMMENDATION_ELIGIBLE_SCOPES
            or evidence_category not in RECOMMENDATION_ELIGIBLE_CATEGORIES
            or authority_tier not in RECOMMENDATION_ELIGIBLE_AUTHORITY_TIERS
        )
    ):
        if audit_support == "provenance_only":
            return "inferred", "experimental", RETRIEVAL_USE
        return "verified", "trusted_core", RETRIEVAL_USE

    trust = (clean_optional(row.get("trust_level")) or "trusted_core").lower()
    if trust == "trusted_core":
        return "verified", "trusted_core", RECOMMENDATION_USE
    if trust == "review_needed":
        return "source_based", "review_needed", RECOMMENDATION_USE
    if trust == "retrieval_only":
        return "inferred", "experimental", RETRIEVAL_USE
    return "model_extracted", "experimental", RETRIEVAL_USE


def publication_dataset_scope(row: Dict[str, str]) -> str:
    parts = [
        clean_optional(row.get("task")),
        clean_optional(row.get("modality")),
        clean_optional(row.get("species")),
        clean_optional(row.get("technology")),
        clean_optional(row.get("dataset_names")),
    ]
    return " | ".join(part for part in parts if part) or clean_optional(row.get("venue")) or "publication_record"


def benchmark_dataset_scope(row: Dict[str, str]) -> str:
    parts = [
        clean_optional(row.get("task")),
        clean_optional(row.get("subtask")),
        clean_optional(row.get("modality")),
        clean_optional(row.get("species")),
        clean_optional(row.get("technology")),
        clean_optional(row.get("dataset")),
        clean_optional(row.get("rank_scope")),
    ]
    return " | ".join(part for part in parts if part) or "benchmark_dataset"


def review_status(value: Optional[str], default: ReviewStatus) -> ReviewStatus:
    raw = (clean_optional(value) or default).lower()
    status_map = {
        "pending": "unreviewed",
        "reviewed": "human_reviewed",
        "verified": "human_reviewed",
        "deprecated": "rejected",
    }
    candidate = status_map.get(raw, raw)
    if candidate in {"unreviewed", "auto_checked", "human_reviewed", "rejected"}:
        return candidate  # type: ignore[return-value]
    return default


def doi_url(value: Optional[str]) -> Optional[str]:
    doi = clean_optional(value)
    if not doi:
        return None
    if doi.startswith("http://") or doi.startswith("https://"):
        return doi
    return f"https://doi.org/{doi}"


def write_plan(records: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def backfill(args: argparse.Namespace) -> Dict[str, Any]:
    publication_rows = load_tsv(args.publications)
    benchmark_rows = load_tsv(args.benchmarks)
    if args.formal_only:
        tools = select_formal_evidence_tools(
            publication_rows,
            benchmark_rows,
            args.max_tools,
        )
    else:
        queue = load_jsonl(args.review_queue)
        tools = select_tools(queue, args.max_tools)
    catalog_index = {} if args.formal_only else build_catalog_index(load_tsv(args.catalog))
    if args.include_formal_evidence_tools and not args.formal_only:
        tools = include_formal_evidence_tools(
            tools,
            publication_rows,
            benchmark_rows,
            args.max_tools,
        )
    crawler = None if args.skip_github or args.formal_only else GitHubCrawler()
    client = None if not args.apply else Neo4jClient()
    if client and client.offline_store is not None:
        client.close()
        raise RuntimeError(
            "Refusing to apply evidence into the offline graph store. "
            "Set OFFLINE_GRAPH_FALLBACK=false and ensure AuraDB is reachable."
        )
    plan_records: List[Dict[str, Any]] = []
    summary = {
        "selected_tools": len(tools),
        "tools_with_catalog": 0,
        "github_errors": 0,
        "evidence_items": 0,
        "applied": bool(args.apply),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        for index, tool_name in enumerate(tools, start=1):
            catalog_row = get_catalog_row(tool_name, catalog_index)
            if catalog_row:
                summary["tools_with_catalog"] += 1
            github_url = clean_optional(catalog_row.get("Code"))
            evidence_items: List[Evidence] = []

            if not args.formal_only:
                docs = build_docs_evidence(tool_name, catalog_row)
                if docs:
                    evidence_items.append(docs)

            github_metrics: Dict[str, Any] = {}
            if crawler and github_url and "github.com" in github_url:
                github_metrics = crawler.fetch_repo_metrics(github_url)
                if github_metrics.get("error"):
                    summary["github_errors"] += 1
                else:
                    evidence_items.extend(
                        build_github_evidence(tool_name, github_url, github_metrics)
                    )
                if args.github_sleep > 0 and index < len(tools):
                    time.sleep(args.github_sleep)

            evidence_items.extend(build_publication_evidence(tool_name, publication_rows))
            evidence_items.extend(build_benchmark_evidence(tool_name, benchmark_rows))
            summary["evidence_items"] += len(evidence_items)

            plan_record = {
                "tool_name": tool_name,
                "catalog_url": github_url,
                "github_status": github_metrics.get("error", "ok" if github_metrics else "skipped"),
                "evidence_ids": [item.evidence_id for item in evidence_items],
                "metric_names": [item.metric_name for item in evidence_items],
                "evidence_count": len(evidence_items),
            }
            plan_records.append(plan_record)

            if client:
                for evidence in evidence_items:
                    client.upsert_evidence(tool_name, evidence)
        if client:
            verified = client.fetch_tool_evidence(tools)
            summary["verified_tools_with_evidence"] = len(verified)
            summary["verified_evidence_items"] = sum(len(items) for items in verified.values())
    finally:
        if client:
            client.close()

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_plan(plan_records, args.plan_output)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill auditable Evidence nodes for high-priority scKG tools."
    )
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--plan-output", type=Path, default=DEFAULT_PLAN_OUTPUT)
    parser.add_argument("--max-tools", type=int, default=50)
    parser.add_argument("--github-sleep", type=float, default=0.2)
    parser.add_argument(
        "--include-formal-evidence-tools",
        action="store_true",
        help="Also backfill tools that appear in reviewed publication or benchmark TSVs.",
    )
    parser.add_argument(
        "--formal-only",
        action="store_true",
        help="Only backfill approved formal publication and benchmark TSV evidence.",
    )
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Do not call the GitHub API; useful for offline dry-runs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write Evidence nodes to Neo4j/AuraDB. Omit for dry-run plan only.",
    )
    args = parser.parse_args()

    summary = backfill(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"plan_output: {args.plan_output}")
    if not args.apply:
        print("dry_run: no AuraDB writes performed; rerun with --apply to write evidence nodes.")


if __name__ == "__main__":
    main()
