from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_policy import is_main_recommendation_evidence
from core.models import Evidence, WorkflowRecommendation
from engine.evidence_rag_pipeline import build_controlled_rag_context
from engine.workflow_recommender import build_minimal_workflow_recommendation


DEFAULT_GOLD = PROJECT_ROOT / "eval" / "gold_workflow_scenarios_v0_1.jsonl"
DEFAULT_SUMMARY = PROJECT_ROOT / "eval" / "workflow_eval_v0_1_summary.json"
DEFAULT_PER_SCENARIO = PROJECT_ROOT / "eval" / "workflow_eval_v0_1_per_scenario.tsv"
DEFAULT_FAILURE_QUEUE = PROJECT_ROOT / "eval" / "workflow_eval_v0_1_failure_queue.tsv"

THRESHOLDS = {
    "required_step_recall": 0.75,
    "candidate_tool_recall": 0.60,
    "unsupported_step_rate": 0.25,
    "evidence_boundary_violation_count": 0,
}

PER_SCENARIO_FIELDS = [
    "id",
    "task",
    "modality",
    "generated_step_count",
    "required_step_recall",
    "candidate_tool_recall",
    "unsupported_step_rate",
    "evidence_boundary_violation_count",
    "source_bound_context_coverage",
    "workflow_warning_quality",
    "passed",
    "failure_reasons",
    "generated_steps",
    "observed_candidate_tools",
    "missing_step_terms",
    "missing_candidate_tools",
    "unsupported_steps",
]


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_workflow_eval(gold_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    per_scenario = [evaluate_scenario(row) for row in gold_rows]
    summary = build_summary(per_scenario)
    return {"summary": summary, "per_scenario": per_scenario}


def evaluate_scenario(row: Dict[str, Any]) -> Dict[str, Any]:
    constraints = row.get("constraints") or {}
    candidate_tools = list(row.get("candidate_tools") or row.get("expected_candidate_tools") or [])
    workflow = build_minimal_workflow_recommendation(constraints, candidate_tools=candidate_tools)
    step_texts = [workflow_step_text(step) for step in workflow.steps]
    observed_candidate_tools = sorted(
        {
            tool
            for step in workflow.steps
            for tool in step.candidate_tools
            if tool
        },
        key=str.casefold,
    )
    expected_step_terms = row.get("expected_step_terms") or []
    allowed_extra_step_terms = row.get("allowed_extra_step_terms") or []
    expected_candidate_tools = row.get("expected_candidate_tools") or []
    expected_warning_terms = row.get("expected_warning_terms") or []

    matched_step_terms = [
        item for item in expected_step_terms
        if any(term_matches_text(item, text) for text in step_texts)
    ]
    missing_step_terms = [
        stringify_term(item) for item in expected_step_terms
        if item not in matched_step_terms
    ]
    required_step_recall = len(matched_step_terms) / max(len(expected_step_terms), 1)

    observed_tool_keys = {tool_key(tool) for tool in observed_candidate_tools}
    matched_tools = [
        tool for tool in expected_candidate_tools
        if tool_key(tool) in observed_tool_keys
    ]
    missing_tools = [
        tool for tool in expected_candidate_tools
        if tool_key(tool) not in observed_tool_keys
    ]
    candidate_tool_recall = len(matched_tools) / max(len(expected_candidate_tools), 1)

    unsupported_steps = []
    support_terms = list(expected_step_terms) + list(allowed_extra_step_terms)
    for step in workflow.steps:
        text = workflow_step_text(step)
        if not any(term_matches_text(term, text) for term in support_terms):
            unsupported_steps.append(step.name)
    unsupported_step_rate = len(unsupported_steps) / max(len(workflow.steps), 1)

    boundary_violations = workflow_evidence_boundary_violations(workflow)
    rag_context = build_controlled_rag_context(
        constraints=constraints,
        tool_names=expected_candidate_tools or candidate_tools,
        max_snippets=12,
    )
    rag_boundary_violations = rag_boundary_violations_from_context(rag_context)
    source_bound_context_coverage = source_bound_context_coverage_from_context(rag_context)
    workflow_warning_quality = warning_quality(workflow.compatibility_warnings, expected_warning_terms)
    boundary_violation_count = len(boundary_violations) + len(rag_boundary_violations)

    failure_reasons = failure_reasons_for(
        required_step_recall=required_step_recall,
        candidate_tool_recall=candidate_tool_recall,
        unsupported_step_rate=unsupported_step_rate,
        evidence_boundary_violation_count=boundary_violation_count,
    )
    return {
        "id": row.get("id", ""),
        "query": row.get("query", ""),
        "task": constraints.get("task", ""),
        "modality": constraints.get("modality", ""),
        "generated_step_count": len(workflow.steps),
        "required_step_recall": round(required_step_recall, 6),
        "candidate_tool_recall": round(candidate_tool_recall, 6),
        "unsupported_step_rate": round(unsupported_step_rate, 6),
        "evidence_boundary_violation_count": boundary_violation_count,
        "source_bound_context_coverage": round(source_bound_context_coverage, 6),
        "workflow_warning_quality": round(workflow_warning_quality, 6),
        "passed": not failure_reasons,
        "failure_reasons": failure_reasons,
        "generated_steps": [step.name for step in workflow.steps],
        "observed_candidate_tools": observed_candidate_tools,
        "missing_step_terms": missing_step_terms,
        "missing_candidate_tools": missing_tools,
        "unsupported_steps": unsupported_steps,
        "rag_mode": rag_context.get("mode", ""),
        "rag_snippet_count": rag_context.get("snippet_count", 0),
        "rag_matched_tools": rag_context.get("matched_tools", []),
        "boundary_violations": boundary_violations + rag_boundary_violations,
    }


def workflow_step_text(step: Any) -> str:
    return " ".join(
        [
            str(step.name),
            str(step.task),
            " ".join(step.required_input),
            " ".join(step.produced_output),
            " ".join(step.candidate_tools),
        ]
    )


def term_matches_text(term: Any, text: str) -> bool:
    if isinstance(term, list):
        return any(term_matches_text(item, text) for item in term)
    term_text = str(term or "")
    normalized_text = normalize_text(text)
    normalized_term = normalize_text(term_text)
    if not normalized_term:
        return False
    if normalized_term in normalized_text:
        return True
    term_tokens = set(tokens(term_text))
    text_tokens = set(tokens(text))
    return bool(term_tokens) and term_tokens.issubset(text_tokens)


def stringify_term(term: Any) -> str:
    if isinstance(term, list):
        return " | ".join(str(item) for item in term)
    return str(term)


def workflow_evidence_boundary_violations(workflow: WorkflowRecommendation) -> List[str]:
    violations: List[str] = []
    for evidence in list(workflow.evidence.items) + [
        item
        for step in workflow.steps
        for item in step.evidence.items
    ]:
        violations.extend(evidence_boundary_violations(evidence))
    return violations


def evidence_boundary_violations(evidence: Evidence) -> List[str]:
    violations: List[str] = []
    if is_main_recommendation_evidence(evidence):
        violations.append(f"{evidence.evidence_id}: main_recommendation_evidence")
    if "recommendation" in evidence.use_for:
        violations.append(f"{evidence.evidence_id}: workflow_template_has_recommendation_use")
    return violations


def rag_boundary_violations_from_context(context: Dict[str, Any]) -> List[str]:
    violations: List[str] = []
    for snippet in context.get("snippets") or []:
        boundary = str(snippet.get("claim_boundary") or "").casefold()
        if not any(marker in boundary for marker in ("cannot promote", "manual review", "retrieval")):
            violations.append(str(snippet.get("record_id") or snippet.get("chunk_id") or "unknown_snippet"))
    return violations


def source_bound_context_coverage_from_context(context: Dict[str, Any]) -> float:
    snippets = context.get("snippets") or []
    if not snippets:
        return 0.0
    source_bound = [
        snippet for snippet in snippets
        if str(snippet.get("source_kind", "")).startswith("source_")
        or snippet.get("source_kind") == "document"
    ]
    return len(source_bound) / len(snippets)


def warning_quality(warnings: Sequence[str], expected_terms: Sequence[Any]) -> float:
    if not expected_terms:
        return 1.0
    warning_text = " ".join(warnings)
    matched = [
        term for term in expected_terms
        if term_matches_text(term, warning_text)
    ]
    return len(matched) / max(len(expected_terms), 1)


def failure_reasons_for(
    *,
    required_step_recall: float,
    candidate_tool_recall: float,
    unsupported_step_rate: float,
    evidence_boundary_violation_count: int,
) -> List[str]:
    reasons: List[str] = []
    if required_step_recall < THRESHOLDS["required_step_recall"]:
        reasons.append("low_required_step_recall")
    if candidate_tool_recall < THRESHOLDS["candidate_tool_recall"]:
        reasons.append("low_candidate_tool_recall")
    if unsupported_step_rate > THRESHOLDS["unsupported_step_rate"]:
        reasons.append("high_unsupported_step_rate")
    if evidence_boundary_violation_count > THRESHOLDS["evidence_boundary_violation_count"]:
        reasons.append("evidence_boundary_violation")
    return reasons


def build_summary(per_scenario: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "eval_name": "workflow_eval_v0_1",
        "scenario_count": len(per_scenario),
        "passed": all(row["passed"] for row in per_scenario),
        "pass_rate": round(rate(row["passed"] for row in per_scenario), 6),
        "required_step_recall": round(mean(row["required_step_recall"] for row in per_scenario), 6),
        "candidate_tool_recall": round(mean(row["candidate_tool_recall"] for row in per_scenario), 6),
        "unsupported_step_rate": round(mean(row["unsupported_step_rate"] for row in per_scenario), 6),
        "evidence_boundary_violation_count": sum(
            int(row["evidence_boundary_violation_count"]) for row in per_scenario
        ),
        "source_bound_context_coverage": round(mean(row["source_bound_context_coverage"] for row in per_scenario), 6),
        "workflow_warning_quality": round(mean(row["workflow_warning_quality"] for row in per_scenario), 6),
        "failure_count": sum(1 for row in per_scenario if not row["passed"]),
        "thresholds": THRESHOLDS,
        "guardrail": (
            "Workflow eval checks plan quality and evidence boundaries. It does not validate biological correctness "
            "or promote formal evidence."
        ),
    }


def write_tsv(path: Path, rows: Sequence[Dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in fields})


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def normalize_text(value: str) -> str:
    return " ".join(tokens(value))


def tokens(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def tool_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def mean(values: Iterable[float]) -> float:
    clean = [float(value) for value in values]
    return sum(clean) / len(clean) if clean else 0.0


def rate(values: Iterable[bool]) -> float:
    clean = [1 if value else 0 for value in values]
    return sum(clean) / len(clean) if clean else 0.0


def one_line(value: Any) -> str:
    if isinstance(value, (list, dict, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if value is None:
        return ""
    return " ".join(str(value).split())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scKG workflow planning eval v0.1.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--per-scenario-output", type=Path, default=DEFAULT_PER_SCENARIO)
    parser.add_argument("--failure-queue-output", type=Path, default=DEFAULT_FAILURE_QUEUE)
    args = parser.parse_args()

    results = run_workflow_eval(read_jsonl(args.gold))
    summary = {
        **results["summary"],
        "gold_path": str(args.gold.relative_to(PROJECT_ROOT)),
        "per_scenario_path": str(args.per_scenario_output.relative_to(PROJECT_ROOT)),
        "failure_queue_path": str(args.failure_queue_output.relative_to(PROJECT_ROOT)),
    }
    write_json(args.summary_output, summary)
    write_tsv(args.per_scenario_output, results["per_scenario"], PER_SCENARIO_FIELDS)
    failures = [row for row in results["per_scenario"] if not row["passed"]]
    write_tsv(args.failure_queue_output, failures, PER_SCENARIO_FIELDS)
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
