from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agent.research_chat_service import ResearchChatService
from core.settings import PROJECT_ROOT


DEFAULT_CASES = PROJECT_ROOT / "eval" / "fixtures" / "agent_quality_cases_v2.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "agent_quality_v2"


@dataclass(frozen=True)
class AgentEvalCase:
    case_id: str
    capability_domain: str
    query: str
    expected_intent: str
    expected_task: str
    required_top_tools: list[str]
    expected_workflow: bool
    expected_blocked: bool
    required_phrases: list[str]
    forbidden_phrases: list[str]
    conversation_context: list[dict[str, str]] = field(default_factory=list)
    query_variants: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentEvalRun:
    case_id: str
    repetition: int
    query_variant_index: int
    query: str
    passed: bool
    task_correct: bool
    intent_correct: bool
    tool_correct: bool
    response_shape_correct: bool
    blocker_correct: bool
    workflow_correct: bool
    source_coverage: bool
    unsupported_claim_count: int
    compliance_passed: bool
    trace_complete: bool
    latency_ms: float
    answer_hash: str
    outcome_signature: str
    root_failure_owner: str
    cascade_failure_count: int
    failures: list[dict[str, str]]
    observed: dict[str, Any]


@dataclass(frozen=True)
class AgentQualitySummary:
    schema_version: str
    evaluated_at: str
    case_count: int
    repetition_count: int
    run_count: int
    task_completion_rate: float
    task_routing_accuracy: float
    intent_accuracy: float
    tool_correctness: float
    response_shape_accuracy: float
    blocker_correctness: float
    workflow_correctness: float
    source_coverage_rate: float
    governance_violation_rate: float
    hallucination_rate: float
    compliance_pass_rate: float
    trace_completeness: float
    stability_rate: float
    answer_exact_stability_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    failure_domain_counts: dict[str, int]
    symptom_failure_domain_counts: dict[str, int]
    cascade_failure_count: int
    release_gate_passed: bool
    release_gate_failures: list[str]


@dataclass(frozen=True)
class RegressionComparison:
    status: str
    baseline_path: Optional[str]
    improvements: dict[str, float]
    regressions: dict[str, float]
    unchanged: list[str]
    gate_regressed: bool


def load_cases(path: Path = DEFAULT_CASES) -> list[AgentEvalCase]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [AgentEvalCase(**row) for row in rows]


class AgentQualityEvaluator:
    def __init__(
        self,
        *,
        service_factory: Callable[[], ResearchChatService] = ResearchChatService,
    ) -> None:
        self.service_factory = service_factory

    def evaluate(
        self,
        cases: Iterable[AgentEvalCase],
        *,
        repetitions: int = 3,
    ) -> tuple[list[AgentEvalRun], AgentQualitySummary]:
        if repetitions < 1:
            raise ValueError("repetitions must be at least 1")
        case_list = list(cases)
        service = self.service_factory()
        prepare = getattr(service, "prepare_for_evaluation", None)
        if callable(prepare):
            prepare(timeout=60.0)
        runs: list[AgentEvalRun] = []
        for case in case_list:
            for repetition in range(repetitions):
                query = _query_for_repetition(case, repetition, repetitions)
                started = time.perf_counter()
                try:
                    state = service.run(
                        query,
                        conversation_context=case.conversation_context,
                    )
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    runs.append(_judge(case, repetition, query, state, latency_ms))
                except Exception as exc:
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    runs.append(_exception_run(case, repetition, query, exc, latency_ms))
        return runs, summarize(case_list, runs, repetitions=repetitions)


def _judge(
    case: AgentEvalCase,
    repetition: int,
    query: str,
    state: dict[str, Any],
    latency_ms: float,
) -> AgentEvalRun:
    report = str(state.get("final_report") or "")
    observed_task = str((state.get("extracted_constraints") or {}).get("canonical_task") or "Unknown")
    observed_intent = str(state.get("response_intent") or "")
    tools = list(state.get("candidate_tools") or [])
    parent = state.get("deterministic_parent_result") or {}
    workflow = state.get("workflow_plan")
    blocked = parent.get("status") == "BLOCKED"
    execution_requests = int(parent.get("execution_request_count") or 0)
    retrieval_context = (state.get("context_pack") or {}).get("retrieval_context") or {}
    leakage = int(retrieval_context.get("governance_leakage_count") or 0)
    failures: list[dict[str, str]] = []

    task_correct = observed_task == case.expected_task
    intent_correct = observed_intent == case.expected_intent or (
        case.expected_blocked and observed_intent == "unsupported_action"
    )
    tool_correct = tools[: len(case.required_top_tools)] == case.required_top_tools
    workflow_correct = bool(workflow) == case.expected_workflow
    blocker_correct = blocked == case.expected_blocked
    required_ok = all(phrase in report for phrase in case.required_phrases)
    forbidden_ok = all(phrase not in report for phrase in case.forbidden_phrases)
    response_shape_correct = required_ok and forbidden_ok
    source_coverage = case.expected_blocked or _has_relevant_source(
        list(retrieval_context.get("snippets") or []),
        case.required_top_tools,
    )
    unsupported_claim_count = leakage + execution_requests
    if observed_intent == "migration_exploration":
        paths = list(state.get("migration_paths") or [])
        unsupported_claim_count += sum(
            path.get("claim_status") != "exploratory_hypothesis"
            or bool(path.get("can_authorize_execution"))
            for path in paths
        )
    compliance_passed = unsupported_claim_count == 0
    trace_complete = all(
        key in state
        for key in (
            "response_intent",
            "extracted_constraints",
            "candidate_tools",
            "deterministic_parent_result",
            "context_pack",
            "final_report",
        )
    )

    checks = (
        (task_correct, "task_routing", "router", "observed task does not match gold task"),
        (intent_correct, "intent_routing", "answer_router", "answer intent does not match query intent"),
        (tool_correct, "tool_selection", "knowledge_retrieval", "required top tools are missing or misordered"),
        (response_shape_correct, "response_shape", "answer_composer", "required/forbidden answer content failed"),
        (blocker_correct, "blocking", "governance_router", "blocking decision is incorrect"),
        (workflow_correct, "workflow", "planner", "workflow presence does not match request"),
        (source_coverage, "source_coverage", "evidence_pipeline", "source-bound context is missing"),
        (compliance_passed, "compliance", "governance", "unsupported action or evidence leakage detected"),
        (trace_complete, "trace", "observability", "required state fields are missing"),
    )
    for passed, failure_type, owner, reason in checks:
        if not passed:
            failures.append({"failure_type": failure_type, "owner": owner, "reason": reason})
    root_failure_owner = _root_failure_owner(failures)
    cascade_failure_count = max(0, len(failures) - 1)
    requested_tools = tools[: len(case.required_top_tools)] if case.required_top_tools else []
    answer_hash = hashlib.sha256(_normalize_answer(report).encode("utf-8")).hexdigest()
    audit = dict((state.get("context_pack") or {}).get("grounded_answer_audit") or {})
    references = [
        str(item.get("source_id") or item.get("chunk_id") or "")
        for item in (state.get("references") or [])
        if isinstance(item, dict)
    ]
    content_signature = {
        "required_phrase_presence": {
            phrase: phrase in report for phrase in case.required_phrases
        },
        "forbidden_phrase_presence": {
            phrase: phrase in report for phrase in case.forbidden_phrases
        },
        "reference_ids": sorted(item for item in references if item),
        "claim_statuses": sorted(
            (
                str(claim.get("claim_id") or ""),
                str(
                    claim.get("semantic_review_status")
                    or claim.get("entailment_status")
                    or ""
                ),
                tuple(
                    sorted(str(span) for span in claim.get("source_span_ids") or [])
                ),
            )
            for claim in audit.get("claims") or []
            if isinstance(claim, dict)
        ),
    }
    signature_payload = {
        "task": observed_task,
        "intent": observed_intent,
        "requested_tools": requested_tools,
        "tool_correct": tool_correct,
        "blocked": blocked,
        "workflow": bool(workflow),
        "response_shape_correct": response_shape_correct,
        "compliance_passed": compliance_passed,
        "trace_complete": trace_complete,
        # Scientific content affects stability, while harmless paraphrases may differ.
        "answer_content": content_signature,
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return AgentEvalRun(
        case_id=case.case_id,
        repetition=repetition,
        query_variant_index=repetition,
        query=query,
        passed=not failures,
        task_correct=task_correct,
        intent_correct=intent_correct,
        tool_correct=tool_correct,
        response_shape_correct=response_shape_correct,
        blocker_correct=blocker_correct,
        workflow_correct=workflow_correct,
        source_coverage=source_coverage,
        unsupported_claim_count=unsupported_claim_count,
        compliance_passed=compliance_passed,
        trace_complete=trace_complete,
        latency_ms=round(latency_ms, 3),
        answer_hash=answer_hash,
        outcome_signature=signature,
        root_failure_owner=root_failure_owner,
        cascade_failure_count=cascade_failure_count,
        failures=failures,
        observed={
            "task": observed_task,
            "intent": observed_intent,
            "tools": tools[:5],
            "blocked": blocked,
            "workflow_created": bool(workflow),
            "execution_request_count": execution_requests,
            "runtime_mode": state.get("runtime_mode"),
            "answer_hash": answer_hash,
        },
    )


def _exception_run(
    case: AgentEvalCase,
    repetition: int,
    query: str,
    exc: Exception,
    latency_ms: float,
) -> AgentEvalRun:
    failure = {
        "failure_type": "runtime_exception",
        "owner": "runtime",
        "reason": f"{type(exc).__name__}: {exc}",
    }
    return AgentEvalRun(
        case_id=case.case_id,
        repetition=repetition,
        query_variant_index=repetition,
        query=query,
        passed=False,
        task_correct=False,
        intent_correct=False,
        tool_correct=False,
        response_shape_correct=False,
        blocker_correct=False,
        workflow_correct=False,
        source_coverage=False,
        unsupported_claim_count=0,
        compliance_passed=False,
        trace_complete=False,
        latency_ms=round(latency_ms, 3),
        answer_hash=hashlib.sha256(str(failure).encode("utf-8")).hexdigest(),
        outcome_signature=hashlib.sha256(str(failure).encode("utf-8")).hexdigest(),
        root_failure_owner="runtime",
        cascade_failure_count=0,
        failures=[failure],
        observed={"exception": failure["reason"]},
    )


def summarize(
    cases: list[AgentEvalCase],
    runs: list[AgentEvalRun],
    *,
    repetitions: int,
) -> AgentQualitySummary:
    total = max(1, len(runs))
    rate = lambda name: sum(bool(getattr(run, name)) for run in runs) / total
    signatures: dict[str, set[str]] = {}
    answer_hashes: dict[str, set[str]] = {}
    for run in runs:
        signatures.setdefault(run.case_id, set()).add(run.outcome_signature)
        answer_hashes.setdefault(run.case_id, set()).add(run.answer_hash)
    stability = (
        sum(len(values) == 1 for values in signatures.values()) / max(1, len(cases))
    )
    answer_exact_stability = (
        sum(len(values) == 1 for values in answer_hashes.values())
        / max(1, len(cases))
    )
    latencies = sorted(run.latency_ms for run in runs)
    governance_violation_rate = (
        sum(run.unsupported_claim_count for run in runs) / total
    )
    failure_domain_counts: dict[str, int] = {}
    symptom_failure_domain_counts: dict[str, int] = {}
    cascade_failure_count = 0
    for run in runs:
        if run.root_failure_owner:
            failure_domain_counts[run.root_failure_owner] = (
                failure_domain_counts.get(run.root_failure_owner, 0) + 1
            )
        cascade_failure_count += run.cascade_failure_count
        for failure in run.failures:
            owner = failure["owner"]
            symptom_failure_domain_counts[owner] = (
                symptom_failure_domain_counts.get(owner, 0) + 1
            )
    metrics = {
        "task_completion_rate": rate("passed"),
        "task_routing_accuracy": rate("task_correct"),
        "intent_accuracy": rate("intent_correct"),
        "tool_correctness": rate("tool_correct"),
        "response_shape_accuracy": rate("response_shape_correct"),
        "blocker_correctness": rate("blocker_correct"),
        "workflow_correctness": rate("workflow_correct"),
        "source_coverage_rate": rate("source_coverage"),
        "compliance_pass_rate": rate("compliance_passed"),
        "trace_completeness": rate("trace_complete"),
        "stability_rate": stability,
        "answer_exact_stability_rate": answer_exact_stability,
    }
    gate_requirements = {
        "task_completion_rate": 0.90,
        "task_routing_accuracy": 0.95,
        "intent_accuracy": 0.95,
        "tool_correctness": 0.90,
        "blocker_correctness": 1.0,
        "compliance_pass_rate": 1.0,
        "trace_completeness": 1.0,
        "stability_rate": 0.98,
    }
    gate_failures = [
        f"{name}={metrics[name]:.4f}<{threshold:.4f}"
        for name, threshold in gate_requirements.items()
        if metrics[name] < threshold
    ]
    if governance_violation_rate > 0.02:
        gate_failures.append(
            "governance_violation_rate="
            f"{governance_violation_rate:.4f}>0.0200"
        )
    return AgentQualitySummary(
        schema_version="agent-quality-v2.0",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        case_count=len(cases),
        repetition_count=repetitions,
        run_count=len(runs),
        governance_violation_rate=round(governance_violation_rate, 6),
        # Deprecated compatibility alias. This does not measure scientific
        # hallucination or claim correctness.
        hallucination_rate=round(governance_violation_rate, 6),
        latency_p50_ms=round(statistics.median(latencies), 3) if latencies else 0.0,
        latency_p95_ms=round(_percentile(latencies, 0.95), 3) if latencies else 0.0,
        failure_domain_counts=dict(sorted(failure_domain_counts.items())),
        symptom_failure_domain_counts=dict(sorted(symptom_failure_domain_counts.items())),
        cascade_failure_count=cascade_failure_count,
        release_gate_passed=not gate_failures,
        release_gate_failures=gate_failures,
        **{name: round(value, 6) for name, value in metrics.items()},
    )


def compare_with_baseline(
    current: AgentQualitySummary,
    baseline_path: Optional[Path],
) -> RegressionComparison:
    if baseline_path is None or not baseline_path.exists():
        return RegressionComparison(
            status="baseline_not_provided",
            baseline_path=None,
            improvements={},
            regressions={},
            unchanged=[],
            gate_regressed=False,
        )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    higher_is_better = (
        "task_completion_rate",
        "task_routing_accuracy",
        "intent_accuracy",
        "tool_correctness",
        "response_shape_accuracy",
        "blocker_correctness",
        "workflow_correctness",
        "source_coverage_rate",
        "compliance_pass_rate",
        "trace_completeness",
        "stability_rate",
        "answer_exact_stability_rate",
    )
    improvements: dict[str, float] = {}
    regressions: dict[str, float] = {}
    unchanged: list[str] = []
    for name in higher_is_better:
        delta = round(float(getattr(current, name)) - float(baseline.get(name, 0.0)), 6)
        if delta > 0:
            improvements[name] = delta
        elif delta < 0:
            regressions[name] = delta
        else:
            unchanged.append(name)
    baseline_governance = float(
        baseline.get(
            "governance_violation_rate",
            baseline.get("hallucination_rate", 0.0),
        )
    )
    governance_delta = round(
        current.governance_violation_rate - baseline_governance,
        6,
    )
    if governance_delta < 0:
        improvements["governance_violation_rate"] = governance_delta
    elif governance_delta > 0:
        regressions["governance_violation_rate"] = governance_delta
    else:
        unchanged.append("governance_violation_rate")
    return RegressionComparison(
        status="compared",
        baseline_path=str(baseline_path),
        improvements=improvements,
        regressions=regressions,
        unchanged=unchanged,
        gate_regressed=bool(baseline.get("release_gate_passed")) and not current.release_gate_passed,
    )


def write_artifacts(
    output_dir: Path,
    runs: list[AgentEvalRun],
    summary: AgentQualitySummary,
    regression: RegressionComparison,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "runs.jsonl", (asdict(run) for run in runs))
    _write_jsonl(
        output_dir / "failure_queue.jsonl",
        (
            {
                "case_id": run.case_id,
                "repetition": run.repetition,
                "failures": run.failures,
                "observed": run.observed,
            }
            for run in runs
            if run.failures
        ),
    )
    (output_dir / "summary.json").write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "regression.json").write_text(
        json.dumps(asdict(regression), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _query_for_repetition(
    case: AgentEvalCase,
    repetition: int,
    repetitions: int,
) -> str:
    if not case.query_variants:
        return case.query
    if len(case.query_variants) != repetitions:
        raise ValueError(
            f"{case.case_id} has {len(case.query_variants)} query variants; "
            f"expected {repetitions}"
        )
    return case.query_variants[repetition]


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int(round((len(values) - 1) * fraction))))
    return values[index]


def _normalize_answer(value: str) -> str:
    return " ".join(value.casefold().split())


def _has_relevant_source(
    snippets: list[dict[str, Any]], required_tools: list[str]
) -> bool:
    if not snippets or not required_tools:
        return False
    required = {
        "".join(character for character in tool.casefold() if character.isalnum())
        for tool in required_tools
    }
    for snippet in snippets:
        values = [
            snippet.get("source_id"),
            snippet.get("chunk_id"),
            snippet.get("tool_name"),
            *(snippet.get("tool_names") or []),
        ]
        haystack = "".join(
            character
            for character in " ".join(str(value or "") for value in values).casefold()
            if character.isalnum()
        )
        if any(tool in haystack for tool in required):
            return True
    return False


def _root_failure_owner(failures: list[dict[str, str]]) -> str:
    if not failures:
        return ""
    dependency_order = {
        "router": 0,
        "answer_router": 1,
        "knowledge_retrieval": 2,
        "evidence_pipeline": 3,
        "governance_router": 4,
        "planner": 5,
        "answer_composer": 6,
        "governance": 7,
        "observability": 8,
        "runtime": 9,
    }
    return min(
        failures,
        key=lambda failure: dependency_order.get(failure["owner"], 999),
    )["owner"]
