from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_INPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_prefilled.tsv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_ai_reviewed.tsv"
)
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_ai_review_summary.json"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_review_packet_v1_ai_review_report.md"
)

AI_FIELDS = [
    "ai_review_status",
    "ai_reviewed_by",
    "ai_review_time",
    "ai_confidence",
    "ai_rationale",
    "ai_suggested_decision",
    "ai_suggested_source_span",
    "ai_suggested_claim_text",
    "ai_suggested_metric",
    "ai_suggested_rank",
    "ai_suggested_score",
    "ai_suggested_normalized_score",
    "ai_suggested_rank_scope",
    "ai_suggested_n_tools_compared",
    "ai_suggested_caveat_type",
    "ai_missing_for_promotion",
    "ai_promotion_ready_suggestion",
]

PROMPT = """You are an evidence review assistant for a single-cell bioinformatics knowledge graph.

Your job is to review ONE evidence recovery row against the provided source span.

Rules:
- Be conservative.
- Do not invent facts beyond the source span.
- Publication evidence can support "this is a real/canonical tool paper" only if the span says enough about the tool/method.
- Benchmark evidence can be promotion-ready only if the span includes a metric-like result and a rank, score, normalized score, or explicit comparison scope.
- If benchmark evidence is qualitative only, mark it as caveat_or_retrieval_only.
- If the span is boilerplate, title-only, or too thin, mark insufficient.
- This is AI-assisted review, not human review.

Return strict JSON only, with these keys:
{
  "ai_review_status": "support_as_publication_candidate | support_as_numeric_benchmark_candidate | caveat_or_retrieval_only | insufficient",
  "ai_confidence": "0.00-1.00",
  "ai_rationale": "short reason",
  "ai_suggested_decision": "keep_retrieval_only | needs_human_confirmation | reject",
  "ai_suggested_source_span": "short exact or near-exact span from input",
  "ai_suggested_claim_text": "claim supported by the span, or empty",
  "ai_suggested_metric": "metric name, or empty",
  "ai_suggested_rank": "rank, or empty",
  "ai_suggested_score": "score, or empty",
  "ai_suggested_normalized_score": "normalized score, or empty",
  "ai_suggested_rank_scope": "comparison scope, or empty",
  "ai_suggested_n_tools_compared": "number, or empty",
  "ai_suggested_caveat_type": "none | qualitative_only | self_reported_or_unclear | negative_control_caveat | source_too_thin",
  "ai_missing_for_promotion": ["missing item 1", "missing item 2"],
  "ai_promotion_ready_suggestion": false
}
"""


def read_tsv(path: Path) -> tuple[List[Dict[str, str]], List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def write_tsv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in fields})


def review_rows(
    rows: List[Dict[str, str]],
    *,
    mode: str,
    limit: int | None,
) -> Dict[str, Any]:
    model_label = model_reviewer_label(mode)
    summary: Dict[str, Any] = {
        "mode": mode,
        "rows": len(rows),
        "eligible_rows": 0,
        "reviewed_rows": 0,
        "skipped_rows": 0,
        "errors": [],
        "status_counts": {},
        "output_is_promotion_input": False,
    }
    llm = load_llm() if mode == "live" else None
    reviewed = 0
    for row in rows:
        ensure_ai_fields(row)
        if not clean(row.get("source_span")):
            row["ai_review_status"] = "skipped_no_source_span"
            row["ai_reviewed_by"] = model_label
            row["ai_review_time"] = now_iso()
            summary["skipped_rows"] += 1
            count_status(summary, row["ai_review_status"])
            continue
        summary["eligible_rows"] += 1
        if limit is not None and reviewed >= limit:
            row["ai_review_status"] = "skipped_limit"
            row["ai_reviewed_by"] = model_label
            row["ai_review_time"] = now_iso()
            summary["skipped_rows"] += 1
            count_status(summary, row["ai_review_status"])
            continue
        try:
            result = dry_run_review(row) if mode == "dry-run" else live_review(llm, row)
            apply_ai_result(row, result, model_label)
            reviewed += 1
            summary["reviewed_rows"] += 1
            count_status(summary, row.get("ai_review_status", ""))
        except Exception as exc:  # pragma: no cover - exercised by CLI integration.
            row["ai_review_status"] = "error"
            row["ai_reviewed_by"] = model_label
            row["ai_review_time"] = now_iso()
            row["ai_rationale"] = str(exc)
            summary["errors"].append(f"{row.get('record_id', '')}: {exc}")
            count_status(summary, "error")
    return summary


def dry_run_review(row: Dict[str, str]) -> Dict[str, Any]:
    missing = base_missing_items(row)
    return {
        "ai_review_status": "dry_run_not_reviewed",
        "ai_confidence": "0.00",
        "ai_rationale": "Dry-run mode did not call an LLM.",
        "ai_suggested_decision": "needs_human_confirmation",
        "ai_suggested_source_span": compact(row.get("source_span", ""), 320),
        "ai_suggested_claim_text": clean(row.get("claim_text")),
        "ai_suggested_metric": clean(row.get("metric")),
        "ai_suggested_rank": clean(row.get("rank")),
        "ai_suggested_score": clean(row.get("score")),
        "ai_suggested_normalized_score": clean(row.get("normalized_score")),
        "ai_suggested_rank_scope": clean(row.get("rank_scope")),
        "ai_suggested_n_tools_compared": clean(row.get("n_tools_compared")),
        "ai_suggested_caveat_type": "source_too_thin" if "source_span" in missing else "none",
        "ai_missing_for_promotion": missing,
        "ai_promotion_ready_suggestion": False,
    }


def live_review(llm: Any, row: Dict[str, str]) -> Dict[str, Any]:
    response = llm.invoke(
        [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": row_prompt(row)},
        ]
    )
    content = response.content if hasattr(response, "content") else str(response)
    result = parse_json_object(content)
    return normalize_ai_result(result, row)


def row_prompt(row: Dict[str, str]) -> str:
    keys = [
        "evidence_kind",
        "tool_name",
        "record_id",
        "source_title",
        "source_url",
        "doi_or_pmid",
        "task",
        "modality",
        "current_audit_labels",
        "recovery_goal",
        "source_span",
        "claim_text",
        "metric",
        "rank",
        "score",
        "normalized_score",
        "rank_scope",
        "n_tools_compared",
        "caveat_type",
    ]
    payload = {key: clean(row.get(key)) for key in keys}
    return json.dumps(payload, indent=2, ensure_ascii=False)


def normalize_ai_result(result: Dict[str, Any], row: Dict[str, str]) -> Dict[str, Any]:
    normalized = dict(result)
    normalized["ai_review_status"] = choose(
        normalized.get("ai_review_status"),
        {
            "support_as_publication_candidate",
            "support_as_numeric_benchmark_candidate",
            "caveat_or_retrieval_only",
            "insufficient",
        },
        "insufficient",
    )
    normalized["ai_suggested_decision"] = choose(
        normalized.get("ai_suggested_decision"),
        {"keep_retrieval_only", "needs_human_confirmation", "reject"},
        "needs_human_confirmation",
    )
    normalized["ai_suggested_caveat_type"] = choose(
        normalized.get("ai_suggested_caveat_type"),
        {
            "none",
            "qualitative_only",
            "self_reported_or_unclear",
            "negative_control_caveat",
            "source_too_thin",
        },
        "source_too_thin",
    )
    normalized["ai_confidence"] = normalize_confidence(normalized.get("ai_confidence"))
    normalized["ai_promotion_ready_suggestion"] = False
    if not normalized.get("ai_missing_for_promotion"):
        normalized["ai_missing_for_promotion"] = base_missing_items(row)
    return normalized


def apply_ai_result(row: Dict[str, str], result: Dict[str, Any], model_label: str) -> None:
    row["ai_review_status"] = clean(result.get("ai_review_status"))
    row["ai_reviewed_by"] = model_label
    row["ai_review_time"] = now_iso()
    row["ai_confidence"] = clean(result.get("ai_confidence"))
    row["ai_rationale"] = clean(result.get("ai_rationale"))
    row["ai_suggested_decision"] = clean(result.get("ai_suggested_decision"))
    row["ai_suggested_source_span"] = compact(result.get("ai_suggested_source_span", ""), 600)
    row["ai_suggested_claim_text"] = compact(result.get("ai_suggested_claim_text", ""), 600)
    row["ai_suggested_metric"] = clean(result.get("ai_suggested_metric"))
    row["ai_suggested_rank"] = clean(result.get("ai_suggested_rank"))
    row["ai_suggested_score"] = clean(result.get("ai_suggested_score"))
    row["ai_suggested_normalized_score"] = clean(result.get("ai_suggested_normalized_score"))
    row["ai_suggested_rank_scope"] = compact(result.get("ai_suggested_rank_scope", ""), 200)
    row["ai_suggested_n_tools_compared"] = clean(result.get("ai_suggested_n_tools_compared"))
    row["ai_suggested_caveat_type"] = clean(result.get("ai_suggested_caveat_type"))
    row["ai_missing_for_promotion"] = "; ".join(as_list(result.get("ai_missing_for_promotion")))
    row["ai_promotion_ready_suggestion"] = "false"
    row["promotion_ready"] = "false"


def base_missing_items(row: Dict[str, str]) -> List[str]:
    missing: List[str] = []
    if not clean(row.get("source_span")):
        missing.append("source_span")
    if not clean(row.get("claim_text")):
        missing.append("claim_text")
    if not clean(row.get("verified_task")):
        missing.append("verified_task")
    if not clean(row.get("verified_modality")):
        missing.append("verified_modality")
    if clean(row.get("evidence_kind")) == "benchmark":
        if not clean(row.get("metric")):
            missing.append("metric")
        if not any(clean(row.get(field)) for field in ("rank", "score", "normalized_score")):
            missing.append("rank_or_score_or_normalized_score")
        if not (clean(row.get("rank_scope")) or clean(row.get("n_tools_compared"))):
            missing.append("rank_scope_or_n_tools_compared")
    elif clean(row.get("evidence_kind")) == "publication":
        if not clean(row.get("canonical_scope")):
            missing.append("canonical_scope")
        if not clean(row.get("authority_tier")):
            missing.append("authority_tier")
    missing.append("traceable_non_ai_reviewer_confirmation")
    return dedupe(missing)


def parse_json_object(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response JSON must be an object")
    return value


def write_report(path: Path, rows: Sequence[Dict[str, str]], summary: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Evidence Review Packet v1 AI Review",
        "",
        f"- mode: {summary.get('mode')}",
        f"- reviewed_rows: {summary.get('reviewed_rows')}",
        f"- skipped_rows: {summary.get('skipped_rows')}",
        f"- output_is_promotion_input: {summary.get('output_is_promotion_input')}",
        "",
    ]
    for row in rows:
        status = clean(row.get("ai_review_status"))
        if not status or status.startswith("skipped"):
            continue
        lines.extend(
            [
                f"## {clean(row.get('tool_name'))} / {clean(row.get('record_id'))}",
                "",
                f"- evidence_kind: {clean(row.get('evidence_kind'))}",
                f"- ai_review_status: {status}",
                f"- ai_confidence: {clean(row.get('ai_confidence'))}",
                f"- ai_suggested_decision: {clean(row.get('ai_suggested_decision'))}",
                f"- ai_rationale: {clean(row.get('ai_rationale'))}",
                f"- missing_for_promotion: {clean(row.get('ai_missing_for_promotion'))}",
                f"- suggested_claim: {clean(row.get('ai_suggested_claim_text'))}",
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def model_reviewer_label(mode: str) -> str:
    if mode == "dry-run":
        return "ai_review_dry_run"
    from core.settings import get_settings

    settings = get_settings()
    model = clean(settings.model_name or settings.extract_model or "unknown_model")
    safe_model = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in model)
    return f"ai_assisted_{safe_model}_{datetime.now(timezone.utc).strftime('%Y_%m')}"


def load_llm() -> Any:
    from core.llm_client import get_llm

    return get_llm()


def ensure_ai_fields(row: Dict[str, str]) -> None:
    for field in AI_FIELDS:
        row.setdefault(field, "")


def count_status(summary: Dict[str, Any], status: str) -> None:
    counts = summary.setdefault("status_counts", {})
    counts[status] = counts.get(status, 0) + 1


def choose(value: object, allowed: set[str], default: str) -> str:
    text = clean(value)
    return text if text in allowed else default


def normalize_confidence(value: object) -> str:
    try:
        number = float(clean(value))
    except ValueError:
        number = 0.0
    number = max(0.0, min(1.0, number))
    return f"{number:.2f}"


def as_list(value: object) -> List[str]:
    if isinstance(value, list):
        return [clean(item) for item in value if clean(item)]
    if clean(value):
        return [clean(value)]
    return []


def dedupe(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact(value: object, limit: int) -> str:
    text = one_line(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def clean(value: object) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI-assisted review over an evidence recovery packet.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--mode",
        choices=["dry-run", "live"],
        default="dry-run",
        help="dry-run writes scaffolding only; live calls the configured LLM.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Maximum rows to review. Use -1 for all eligible rows.",
    )
    args = parser.parse_args()

    rows, fields = read_tsv(args.input)
    output_fields = list(fields)
    for field in AI_FIELDS:
        if field not in output_fields:
            output_fields.append(field)
    limit = None if args.limit is not None and args.limit < 0 else args.limit
    summary = review_rows(rows, mode=args.mode, limit=limit)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "report_output": str(args.report_output),
        "limit": limit,
        **summary,
    }
    write_tsv(args.output, rows, output_fields)
    write_report(args.report_output, rows, summary)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
