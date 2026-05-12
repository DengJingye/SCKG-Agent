import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REVIEW_PACKET = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "migration_hypothesis_review_packet.tsv"
)

OUTPUT_TYPE_ALIASES = {
    "migration_hypothesis": "migration",
}

ACCEPT_DECISIONS = {"accept_exploratory"}
REVISE_DECISIONS = {"revise_mechanism"}
NEGATIVE_DECISIONS = {"reject_incompatible", "not_migration"}
CLARIFICATION_DECISIONS = {"needs_clarification"}

NEGATION_MARKERS = [
    "not",
    "no",
    "without",
    "cannot",
    "can't",
    "never",
    "avoid",
    "block",
    "blocked",
    "forbid",
    "forbidden",
    "must not",
    "hard block",
    "不",
    "不是",
    "不能",
    "不得",
    "没有",
    "无",
    "禁止",
    "避免",
]

CAVEAT_MARKERS = [
    "exploratory",
    "validation",
    "validate",
    "requires",
    "require",
    "caveat",
    "limitation",
    "missing",
    "compatibility",
    "gap",
    "full_benchmark_validation",
    "downstream",
    "unsupported",
    "cannot",
    "must",
    "risk",
    "not ",
    "不得",
    "不能",
    "需要",
]

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "only",
    "task",
    "tool",
    "required",
    "requires",
    "require",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in load_jsonl(path)}


def load_review_packet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def normalize_output_type(value: str | None) -> str | None:
    if not value:
        return None
    return OUTPUT_TYPE_ALIASES.get(value, value)


def tool_key(value: str) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def mean(values: Iterable[float]) -> Optional[float]:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def rate(values: Iterable[bool | int]) -> Optional[float]:
    clean = [int(value) for value in values]
    if not clean:
        return None
    return sum(clean) / len(clean)


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def migration_tools(prediction: dict[str, Any]) -> list[str]:
    paths = prediction.get("migration_paths") or []
    if paths:
        return [path.get("tool_name", "") for path in paths if path.get("tool_name")]
    return list(prediction.get("recommended_tools") or [])


def is_migration_output(prediction: dict[str, Any]) -> bool:
    predicted_type = prediction.get("recommendation_type") or prediction.get("recommendation_kind")
    return predicted_type == "migration" and bool(prediction.get("migration_paths"))


def clarification_state(prediction: dict[str, Any]) -> str:
    parsed = prediction.get("parsed_constraints") or {}
    return str(parsed.get("clarification_state") or "")


def needs_clarification(prediction: dict[str, Any]) -> bool:
    return bool(prediction.get("clarification_needed")) or clarification_state(prediction) == "needs_clarification"


def expected_decision(record: dict[str, Any]) -> str:
    return str(record.get("expected_migration_decision") or "accept_exploratory")


def prediction_text(prediction: dict[str, Any]) -> str:
    chunks: list[str] = [str(prediction.get("final_report") or "")]
    for path in prediction.get("migration_paths") or []:
        chunks.append(str(path.get("claim_boundary") or ""))
        chunks.append(str(path.get("transferable_mechanism") or ""))
        chunks.append(" ".join(path.get("limitations") or []))
        chunks.append(" ".join(path.get("compatibility_gaps") or []))
    chunks.extend(prediction.get("missing_components") or [])
    return "\n".join(chunks)


def has_forbidden_tool(tools: list[str], forbidden_tools: list[str]) -> bool:
    observed = {tool_key(tool) for tool in tools}
    forbidden = {tool_key(tool) for tool in forbidden_tools}
    return bool(observed & forbidden)


def has_forbidden_claim(text: str, forbidden_claims: list[str]) -> bool:
    lowered = text.lower()
    for claim in forbidden_claims:
        claim_text = (claim or "").lower().strip()
        if not claim_text:
            continue
        start = lowered.find(claim_text)
        while start >= 0:
            if not is_negated_or_blocked_context(lowered, start):
                return True
            start = lowered.find(claim_text, start + len(claim_text))
    return False


def is_negated_or_blocked_context(lowered_text: str, claim_start: int) -> bool:
    window = lowered_text[max(0, claim_start - 80):claim_start]
    return any(marker in window for marker in NEGATION_MARKERS)


def has_claim_boundary(prediction: dict[str, Any]) -> bool:
    report = str(prediction.get("final_report") or "").lower()
    if "migration_claim_boundary" in report or "exploratory hypothesis only" in report:
        return True
    return any(
        bool(path.get("claim_boundary"))
        for path in prediction.get("migration_paths") or []
    )


def has_compatibility_gap(prediction: dict[str, Any]) -> bool:
    report = str(prediction.get("final_report") or "").lower()
    if "migration_compatibility_gaps" in report:
        return True
    for path in prediction.get("migration_paths") or []:
        if path.get("compatibility_gaps"):
            return True
    return False


def tokenize(value: str) -> list[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return [
        token
        for token in normalized.split()
        if len(token) >= 4 and token not in STOPWORDS
    ]


def caveat_hits(text: str, expected_caveats: list[str]) -> tuple[bool, float]:
    lowered = text.lower()
    generic_present = any(marker in lowered for marker in CAVEAT_MARKERS)
    if not expected_caveats:
        return generic_present, 1.0 if generic_present else 0.0

    hits = 0
    for caveat in expected_caveats:
        tokens = tokenize(caveat)
        if not tokens:
            continue
        if any(token in lowered for token in tokens):
            hits += 1
    hit_rate = hits / len(expected_caveats)
    return generic_present or hits > 0, hit_rate


def review_decision_maps(rows: list[dict[str, str]]) -> tuple[dict[str, set[str]], set[str]]:
    decisions_by_tool: dict[str, set[str]] = {}
    for row in rows:
        tool = row.get("source_tool", "")
        decision = row.get("reviewer_decision", "")
        if tool:
            decisions_by_tool.setdefault(tool_key(tool), set()).add(decision)
    revise_only = {
        tool
        for tool, decisions in decisions_by_tool.items()
        if "revise_mechanism" in decisions and "accept_exploratory" not in decisions
    }
    return decisions_by_tool, revise_only


def semantic_counts(prediction: dict[str, Any]) -> dict[str, int | bool]:
    audit = prediction.get("hallucination_audit") or {}
    issues = audit.get("issues") or []
    severity_counts = audit.get("severity_counts") or {}
    return {
        "has_audit": bool(audit),
        "passed": bool(audit.get("passed")) if audit else False,
        "claims": int(audit.get("claim_count") or prediction.get("claim_count") or 0),
        "high": int(severity_counts.get("high", 0)),
        "critical": int(severity_counts.get("critical", 0)),
        "unsupported_tool": len(
            [
                issue for issue in issues
                if issue.get("issue_type") == "unsupported_tool_claim"
            ]
        ),
    }


def evaluate(
    gold_records: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    review_rows: list[dict[str, str]],
) -> dict[str, Any]:
    decisions_by_tool, revise_only_tools = review_decision_maps(review_rows)
    per_query: list[dict[str, Any]] = []

    output_hits: list[bool] = []
    top_hits: list[bool] = []
    positive_source_hits: list[bool] = []
    positive_migration_outputs: list[bool] = []
    mixed_decision_hits: list[bool] = []
    negative_false_migrations: list[bool] = []
    negative_rejection_hits: list[bool] = []
    clarification_hits: list[bool] = []
    trap_hits: list[bool] = []
    revise_decision_hits: list[bool] = []
    forbidden_tool_violations: list[bool] = []
    forbidden_claim_violations: list[bool] = []
    caveat_present: list[bool] = []
    caveat_hit_rates: list[float] = []
    claim_boundary_present: list[bool] = []
    compatibility_gap_present: list[bool] = []
    audit_passes: list[bool] = []
    semantic_claim_count = 0
    high_issue_count = 0
    unsupported_tool_issue_count = 0
    path_scores: list[float] = []
    io_scores: list[float] = []
    jaccard_scores: list[float] = []
    risk_penalties: list[float] = []
    reviewed_path_accepts: list[bool] = []
    unreviewed_path_flags: list[bool] = []
    revise_block_checks: list[bool] = []
    case_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}

    for record in gold_records:
        query_id = record["id"]
        prediction = predictions.get(query_id, {})
        tools = migration_tools(prediction)
        case_type = str(record.get("case_type") or "true_positive")
        decision = expected_decision(record)
        case_counts[case_type] = case_counts.get(case_type, 0) + 1
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        migration_output = is_migration_output(prediction)
        expected_type = normalize_output_type(record.get("expected_output_type"))
        predicted_type = prediction.get("recommendation_type") or prediction.get("recommendation_kind")
        output_hit = predicted_type == expected_type
        output_hits.append(output_hit)

        expected_tools = record.get("expected_source_tools") or record.get("expected_tools") or []
        top_hit = bool(expected_tools) and any(
            tool_key(tool) in {tool_key(item) for item in tools[:3]}
            for tool in expected_tools
        )
        if expected_tools:
            top_hits.append(top_hit)

        forbidden_tool_violation = has_forbidden_tool(
            tools + list(prediction.get("recommended_tools") or []),
            record.get("forbidden_tools") or [],
        )
        forbidden_tool_violations.append(forbidden_tool_violation)

        text = prediction_text(prediction)
        forbidden_claim_violation = has_forbidden_claim(
            text,
            record.get("forbidden_claims") or [],
        )
        forbidden_claim_violations.append(forbidden_claim_violation)

        caveat, caveat_rate = caveat_hits(text, record.get("expected_caveats") or [])
        caveat_present.append(caveat)
        caveat_hit_rates.append(caveat_rate)
        boundary = has_claim_boundary(prediction)
        claim_boundary_present.append(boundary)
        gaps = has_compatibility_gap(prediction)
        compatibility_gap_present.append(gaps)

        blocked_tools = record.get("expected_blocked_tools") or []
        blocked_tools_absent = not has_forbidden_tool(tools + list(prediction.get("recommended_tools") or []), blocked_tools)
        record_revise_check = blocked_tools_absent and not forbidden_tool_violation and not forbidden_claim_violation
        record_negative_reject = (not migration_output) and not forbidden_tool_violation and not forbidden_claim_violation
        record_clarify = needs_clarification(prediction) and not migration_output
        record_trap = (not migration_output) and not forbidden_tool_violation and not forbidden_claim_violation
        if decision in ACCEPT_DECISIONS:
            positive_migration_outputs.append(migration_output)
            positive_source_hits.append(migration_output and top_hit)
            decision_success = migration_output and top_hit and not forbidden_tool_violation and not forbidden_claim_violation
        elif decision in REVISE_DECISIONS:
            revise_decision_hits.append(record_revise_check and (gaps or caveat or not migration_output))
            decision_success = revise_decision_hits[-1]
        elif decision in NEGATIVE_DECISIONS:
            negative_false_migrations.append(migration_output)
            negative_rejection_hits.append(record_negative_reject)
            decision_success = record_negative_reject
        elif decision in CLARIFICATION_DECISIONS:
            negative_false_migrations.append(migration_output)
            clarification_hits.append(record_clarify)
            decision_success = record_clarify
        else:
            decision_success = output_hit
        if case_type == "retrieval_trap":
            trap_hits.append(record_trap)
        mixed_decision_hits.append(decision_success)

        audit = semantic_counts(prediction)
        if audit["has_audit"]:
            audit_passes.append(bool(audit["passed"]))
            semantic_claim_count += int(audit["claims"])
            high_issue_count += int(audit["high"]) + int(audit["critical"])
            unsupported_tool_issue_count += int(audit["unsupported_tool"])

        paths = prediction.get("migration_paths") or []
        for path in paths:
            tool = tool_key(path.get("tool_name", ""))
            decisions = decisions_by_tool.get(tool, set())
            unreviewed_path_flags.append(not bool(decisions))
            for target, value in (
                (path_scores, path.get("score")),
                (io_scores, path.get("io_compatibility")),
                (jaccard_scores, path.get("graph_jaccard")),
                (risk_penalties, path.get("risk_penalty")),
            ):
                parsed = safe_float(value)
                if parsed is not None:
                    target.append(parsed)
            if decisions:
                reviewed_path_accepts.append("accept_exploratory" in decisions)

        expected_revise_tools = {
            tool_key(tool)
            for tool in (record.get("expected_blocked_tools") or expected_tools)
            if tool_key(tool) in revise_only_tools
        }
        if expected_revise_tools:
            surfaced = {tool_key(tool) for tool in tools}
            revise_block_checks.append(not bool(expected_revise_tools & surfaced))

        per_query.append(
            {
                "query_id": query_id,
                "case_type": case_type,
                "expected_migration_decision": decision,
                "prediction_found": bool(prediction),
                "predicted_type": predicted_type,
                "is_migration_output": migration_output,
                "migration_output_type_hit": output_hit,
                "mixed_decision_hit": decision_success,
                "top_k_source_tool_hit": top_hit,
                "forbidden_tool_violation": forbidden_tool_violation,
                "forbidden_claim_violation": forbidden_claim_violation,
                "blocked_tools_absent": blocked_tools_absent,
                "needs_clarification": needs_clarification(prediction),
                "clarification_state": clarification_state(prediction),
                "caveat_present": caveat,
                "expected_caveat_hit_rate": caveat_rate,
                "claim_boundary_present": boundary,
                "compatibility_gap_present": gaps,
                "semantic_audit_pass": bool(audit["passed"]) if audit["has_audit"] else None,
                "migration_path_count": len(paths),
                "migration_tools": ";".join(tools),
            }
        )

    metrics = [
        metric("query_count", float(len(gold_records)), "ok", "number of migration gold queries"),
        metric("true_positive_count", float(case_counts.get("true_positive", 0)), "ok", "positive migration cases"),
        metric("revise_only_count", float(case_counts.get("revise_only", 0)), "ok", "boundary cases that should block or revise direct transfer"),
        metric("true_negative_count", float(case_counts.get("true_negative", 0)), "ok", "incompatible cases that should not migrate"),
        metric("needs_clarification_count", float(case_counts.get("needs_clarification", 0)), "ok", "underspecified cases that should ask for clarification"),
        metric("retrieval_trap_count", float(case_counts.get("retrieval_trap", 0)), "ok", "keyword/name traps that should not trigger migration"),
        metric("prediction_coverage", rate([record["id"] in predictions for record in gold_records]), "ok", "gold queries with predictions"),
        metric("migration_output_type_hit", rate(output_hits), "ok", "exact output type match; mostly useful for migration-only sets"),
        metric("mixed_decision_accuracy", rate(mixed_decision_hits), "ok", "correct accept/revise/reject/clarify decision across mixed cases"),
        metric("top_k_source_tool_hit", rate(top_hits), "ok" if top_hits else "not_run", "top-3 source tools include at least one expected source where expected tools are provided"),
        metric("positive_migration_output_rate", rate(positive_migration_outputs), "ok" if positive_migration_outputs else "not_run", "positive cases that surfaced a migration hypothesis"),
        metric("positive_source_tool_hit", rate(positive_source_hits), "ok" if positive_source_hits else "not_run", "positive cases with expected source tool in top-3"),
        metric("negative_false_migration_rate", rate(negative_false_migrations), "ok" if negative_false_migrations else "not_run", "reject/clarify cases that still surfaced migration; lower is better"),
        metric("negative_rejection_success_rate", rate(negative_rejection_hits), "ok" if negative_rejection_hits else "not_run", "incompatible cases correctly not migrated"),
        metric("clarification_success_rate", rate(clarification_hits), "ok" if clarification_hits else "not_run", "underspecified cases that asked for clarification and did not force migration"),
        metric("trap_avoidance_rate", rate(trap_hits), "ok" if trap_hits else "not_run", "retrieval traps that did not trigger migration or forbidden claims"),
        metric("revise_decision_success_rate", rate(revise_decision_hits), "ok" if revise_decision_hits else "not_run", "revise-only cases that blocked direct incompatible transfer"),
        metric("forbidden_tool_violation_rate", rate(forbidden_tool_violations), "ok", "lower is better"),
        metric("forbidden_claim_violation_rate", rate(forbidden_claim_violations), "ok", "lower is better; negated boundary statements are not counted as violations"),
        metric("caveat_presence_rate", rate(caveat_present), "ok", "migration report contains explicit caveat or validation language"),
        metric("expected_caveat_hit_rate", mean(caveat_hit_rates), "ok", "average loose match against expected caveat terms"),
        metric("claim_boundary_presence_rate", rate(claim_boundary_present), "ok", "exploratory boundary is visible"),
        metric("compatibility_gap_presence_rate", rate(compatibility_gap_present), "ok", "I/O or method gaps are surfaced"),
        metric("mean_migration_plausibility_score", mean(path_scores), "ok" if path_scores else "not_run", "mean across surfaced migration paths"),
        metric("mean_io_compatibility", mean(io_scores), "ok" if io_scores else "not_run", "mean across surfaced migration paths"),
        metric("mean_graph_jaccard", mean(jaccard_scores), "ok" if jaccard_scores else "not_run", "mean across surfaced migration paths"),
        metric("mean_risk_penalty", mean(risk_penalties), "ok" if risk_penalties else "not_run", "lower is more conservative"),
        metric("semantic_audit_pass_rate", rate(audit_passes), "ok" if audit_passes else "not_run", "requires hallucination_audit in predictions"),
        metric(
            "high_hallucination_rate",
            high_issue_count / semantic_claim_count if semantic_claim_count else None,
            "ok" if semantic_claim_count else "not_run",
            "critical plus high audit issues divided by audited claims",
        ),
        metric(
            "unsupported_tool_claim_rate",
            unsupported_tool_issue_count / semantic_claim_count if semantic_claim_count else None,
            "ok" if semantic_claim_count else "not_run",
            "unsupported tool issues divided by audited claims",
        ),
        metric(
            "accepted_hypothesis_rate",
            rate(reviewed_path_accepts),
            "ok" if reviewed_path_accepts else "not_run",
            "among surfaced paths with explicit migration review rows",
        ),
        metric(
            "unreviewed_migration_path_rate",
            rate(unreviewed_path_flags),
            "ok" if unreviewed_path_flags else "ok",
            "surfaced paths that are profile-only and lack a migration-vector review row",
        ),
        metric(
            "revise_block_success_rate",
            rate(revise_block_checks),
            "ok" if revise_block_checks else "not_run",
            "queries whose revise-only source tools were not surfaced",
        ),
    ]
    return {
        "metrics": metrics,
        "per_query": per_query,
    }


def metric(name: str, value: Optional[float], status: str, reason: str) -> dict[str, str]:
    return {
        "metric": name,
        "value": "" if value is None else f"{value:.6f}",
        "status": status,
        "reason": reason,
    }


def write_summary(path: Path, metrics: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "value", "status", "reason"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(metrics)


def write_per_query(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate exploratory migration hypotheses.")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--per-query-output", type=Path)
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    args = parser.parse_args()

    gold_records = load_jsonl(args.gold)
    predictions = load_predictions(args.predictions)
    review_rows = load_review_packet(args.review_packet)
    result = evaluate(gold_records, predictions, review_rows)

    write_summary(args.output, result["metrics"])
    if args.per_query_output:
        write_per_query(args.per_query_output, result["per_query"])
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
