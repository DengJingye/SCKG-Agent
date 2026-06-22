from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import (  # noqa: E402
    EvidenceBundle,
    EvidenceContextPack,
    MigrationPath,
    ScoredTool,
    ToolCandidate,
    WorkflowRecommendation,
)
from engine.context_pack_builder import build_evidence_context_pack  # noqa: E402


DEFAULT_PREDICTIONS = PROJECT_ROOT / "eval" / "migration_sealed_v0_11_first_run_predictions.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "context_pack_v0_12_audit_v0_11_first_run.tsv"
DEFAULT_SUMMARY = PROJECT_ROOT / "eval" / "context_pack_v0_12_audit_v0_11_first_run_summary.json"

FIELDS = [
    "query_id",
    "recommendation_type",
    "execution_mode",
    "context_pack_present",
    "context_pack_rebuilt",
    "trusted_ranked_tool_count",
    "trusted_evidence_count",
    "trusted_non_main_count",
    "trusted_disallowed_source_count",
    "retrieval_evidence_count",
    "formal_rag_snippet_count",
    "formal_rag_publication_count",
    "formal_rag_benchmark_count",
    "formal_rag_missing_claim_span_count",
    "retrieval_rankable_count",
    "retrieval_recommendation_grade_flag",
    "migration_context_path_count",
    "migration_bad_decision_count",
    "excluded_migration_path_count",
    "blocked_tools_count",
    "guardrail_warning_count",
    "auditor_risk_count",
    "missing_evidence_count",
    "policy_forbidden_count",
    "policy_required_caveat_count",
    "audit_status",
    "issues",
    "missing_evidence",
]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_tsv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _cell(row.get(field, "")) for field in FIELDS})


def audit_predictions(
    records: Iterable[Dict[str, Any]],
    rebuild_missing: bool = True,
    force_rebuild: bool = False,
) -> List[Dict[str, Any]]:
    return [
        audit_record(record, rebuild_missing=rebuild_missing, force_rebuild=force_rebuild)
        for record in records
    ]


def audit_record(record: Dict[str, Any], rebuild_missing: bool, force_rebuild: bool) -> Dict[str, Any]:
    query_id = record.get("query_id") or record.get("id") or ""
    context_pack_present = bool(record.get("context_pack"))
    context_pack_rebuilt = False
    issues: List[str] = []

    try:
        if force_rebuild:
            pack = _rebuild_context_pack(record)
            context_pack_rebuilt = True
        elif context_pack_present:
            pack = EvidenceContextPack.model_validate(record["context_pack"])
        elif rebuild_missing:
            pack = _rebuild_context_pack(record)
            context_pack_rebuilt = True
        else:
            issues.append("missing_context_pack")
            return _error_row(record, query_id, context_pack_present, issues)
    except Exception as exc:
        issues.append(f"context_pack_build_failed:{type(exc).__name__}:{exc}")
        return _error_row(record, query_id, context_pack_present, issues)

    trusted_items = _list(pack.trusted_recommendation_context.get("evidence_items"))
    retrieval_items = _list(pack.retrieval_context.get("evidence_items"))
    formal_rag = pack.retrieval_context.get("formal_rag_context") or {}
    formal_snippets = _list(formal_rag.get("snippets"))
    migration_paths = _list(pack.migration_context.get("paths"))
    excluded_migrations = _list(pack.migration_context.get("excluded_paths"))
    blocked_context = pack.blocked_context or {}

    trusted_non_main = [
        item for item in trusted_items
        if not bool(item.get("source_is_main_recommendation_evidence"))
    ]
    trusted_disallowed_source = [
        item for item in trusted_items
        if item.get("source_type") not in {"paper", "benchmark"}
    ]
    retrieval_rankable = [
        item for item in retrieval_items
        if bool(item.get("context_can_rank"))
    ]
    retrieval_grade_flag = bool(pack.retrieval_context.get("recommendation_grade"))
    formal_missing_claim_span = [
        item for item in formal_snippets
        if not item.get("claim_span")
    ]
    migration_bad_decisions = [
        item for item in migration_paths
        if item.get("reviewer_decision") != "accept_exploratory"
    ]

    if trusted_non_main:
        issues.append("trusted_context_contains_non_main_evidence")
    if trusted_disallowed_source:
        issues.append("trusted_context_contains_non_paper_or_benchmark")
    if retrieval_rankable:
        issues.append("retrieval_context_contains_rankable_evidence")
    if retrieval_grade_flag:
        issues.append("retrieval_context_marked_recommendation_grade")
    if formal_missing_claim_span:
        issues.append("formal_rag_snippet_missing_claim_span")
    if migration_bad_decisions:
        issues.append("migration_context_contains_non_accept_exploratory")

    status = "pass" if not issues else "fail"
    if context_pack_rebuilt and status == "pass":
        status = "pass_rebuilt"

    return {
        "query_id": query_id,
        "recommendation_type": record.get("recommendation_type", pack.recommendation_type),
        "execution_mode": record.get("execution_mode", ""),
        "context_pack_present": context_pack_present,
        "context_pack_rebuilt": context_pack_rebuilt,
        "trusted_ranked_tool_count": len(_list(pack.trusted_recommendation_context.get("ranked_tools"))),
        "trusted_evidence_count": len(trusted_items),
        "trusted_non_main_count": len(trusted_non_main),
        "trusted_disallowed_source_count": len(trusted_disallowed_source),
        "retrieval_evidence_count": len(retrieval_items),
        "formal_rag_snippet_count": len(formal_snippets),
        "formal_rag_publication_count": sum(1 for item in formal_snippets if item.get("source_kind") == "publication"),
        "formal_rag_benchmark_count": sum(1 for item in formal_snippets if item.get("source_kind") == "benchmark"),
        "formal_rag_missing_claim_span_count": len(formal_missing_claim_span),
        "retrieval_rankable_count": len(retrieval_rankable),
        "retrieval_recommendation_grade_flag": retrieval_grade_flag,
        "migration_context_path_count": len(migration_paths),
        "migration_bad_decision_count": len(migration_bad_decisions),
        "excluded_migration_path_count": len(excluded_migrations),
        "blocked_tools_count": len(_list(blocked_context.get("blocked_tools"))),
        "guardrail_warning_count": len(_list(blocked_context.get("guardrail_warnings"))),
        "auditor_risk_count": len(_list(blocked_context.get("auditor_risks"))),
        "missing_evidence_count": len(pack.missing_evidence),
        "policy_forbidden_count": len(_list(pack.prompt_policy.get("forbidden"))),
        "policy_required_caveat_count": len(_list(pack.prompt_policy.get("required_caveats"))),
        "audit_status": status,
        "issues": ";".join(issues),
        "missing_evidence": ";".join(pack.missing_evidence),
    }


def _rebuild_context_pack(record: Dict[str, Any]) -> EvidenceContextPack:
    scored_tools = [
        ScoredTool.model_validate(item)
        for item in _list(record.get("scored_tools"))
    ]
    tool_candidates = [
        ToolCandidate.model_validate(item)
        for item in _list(record.get("candidate_tools"))
    ]
    migration_paths = [
        MigrationPath.model_validate(item)
        for item in _list(record.get("migration_paths"))
    ]
    workflow = _workflow(record.get("workflow_recommendation"))
    evidence_bundle = EvidenceBundle.model_validate(record.get("evidence_bundle") or {})
    return build_evidence_context_pack(
        user_query=record.get("user_query", ""),
        constraints=record.get("parsed_constraints") or {},
        recommendation_type=record.get("recommendation_type", "none"),
        scored_tools=scored_tools,
        tool_candidates=tool_candidates,
        workflow=workflow,
        migration_paths=migration_paths,
        evidence_bundle=evidence_bundle,
        missing_components=_list(record.get("missing_components")),
        hallucination_audit=record.get("hallucination_audit") or {},
    )


def _workflow(value: Any) -> Optional[WorkflowRecommendation]:
    if not value:
        return None
    return WorkflowRecommendation.model_validate(value)


def _error_row(
    record: Dict[str, Any],
    query_id: str,
    context_pack_present: bool,
    issues: List[str],
) -> Dict[str, Any]:
    return {
        "query_id": query_id,
        "recommendation_type": record.get("recommendation_type", ""),
        "execution_mode": record.get("execution_mode", ""),
        "context_pack_present": context_pack_present,
        "context_pack_rebuilt": False,
        "audit_status": "error",
        "issues": ";".join(issues),
    }


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    query_count = len(rows)
    statuses = {}
    for row in rows:
        statuses[row.get("audit_status", "unknown")] = statuses.get(row.get("audit_status", "unknown"), 0) + 1
    return {
        "query_count": query_count,
        "status_counts": statuses,
        "context_pack_present_rate": _rate(rows, "context_pack_present"),
        "context_pack_rebuilt_count": sum(1 for row in rows if row.get("context_pack_rebuilt")),
        "mean_trusted_evidence_count": _mean_count(rows, "trusted_evidence_count"),
        "mean_retrieval_evidence_count": _mean_count(rows, "retrieval_evidence_count"),
        "mean_formal_rag_snippet_count": _mean_count(rows, "formal_rag_snippet_count"),
        "total_formal_rag_publication_count": _sum_count(rows, "formal_rag_publication_count"),
        "total_formal_rag_benchmark_count": _sum_count(rows, "formal_rag_benchmark_count"),
        "total_formal_rag_missing_claim_span_count": _sum_count(rows, "formal_rag_missing_claim_span_count"),
        "total_migration_context_paths": _sum_count(rows, "migration_context_path_count"),
        "total_excluded_migration_paths": _sum_count(rows, "excluded_migration_path_count"),
        "total_retrieval_rankable_violations": _sum_count(rows, "retrieval_rankable_count"),
        "total_trusted_non_main_violations": _sum_count(rows, "trusted_non_main_count"),
        "total_migration_bad_decision_violations": _sum_count(rows, "migration_bad_decision_count"),
        "failed_query_count": sum(1 for row in rows if str(row.get("audit_status", "")).startswith(("fail", "error"))),
    }


def _rate(rows: List[Dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(field) is True) / len(rows)


def _mean_count(rows: List[Dict[str, Any]], field: str) -> float:
    values = [_to_int(row.get(field)) for row in rows]
    return round(mean(values), 4) if values else 0.0


def _sum_count(rows: List[Dict[str, Any]], field: str) -> int:
    return sum(_to_int(row.get(field)) for row in rows)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _cell(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return ""
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit EvidenceContextPack layering without LLM, Neo4j writes, or evidence promotion."
    )
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--no-rebuild-missing",
        action="store_true",
        help="Report missing context_pack as an error instead of rebuilding from prediction payloads.",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Ignore stored context_pack and rebuild it from the prediction payload with current code.",
    )
    args = parser.parse_args()

    records = load_jsonl(args.predictions)
    rows = audit_predictions(
        records,
        rebuild_missing=not args.no_rebuild_missing,
        force_rebuild=args.force_rebuild,
    )
    write_tsv(rows, args.output)
    summary = summarize(rows)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"audit_output: {args.output}")
    print(f"summary_output: {args.summary_output}")


if __name__ == "__main__":
    main()
