from __future__ import annotations

import hashlib
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from agent.research_chat_service import ResearchChatService
from core.privacy_policy import OutboundDisclosureService, PrivacyMode
from core.settings import PROJECT_ROOT
from eval.agent_quality_evaluation import AgentEvalCase, _judge


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "external_agent_stability_v2"
REQUIRED_CONFIRMATION = "I AUTHORIZE 60 GOVERNED EVALUATION TURNS"
REPRESENTATIVE_CASE_IDS = (
    "chat-doublet-recommend-zh-01",
    "chat-batch-recommend-01",
    "chat-scrublet-input-01",
    "chat-harmony-input-01",
    "chat-doublet-caveat-top3-01",
    "chat-batch-caveat-top2-01",
    "chat-hard-negative-protein-01",
    "chat-hard-negative-variant-01",
    "chat-hard-negative-unsupported-01",
    "chat-transition-plan-to-caveat-01",
    "chat-transition-doublet-to-unsupported-protein-01",
    "chat-transition-doublet-to-unsupported-cellphonedb-02",
    "chat-transition-doublet-to-batch-01",
    "chat-transition-doublet-to-batch-02",
    "chat-transition-batch-to-doublet-workflow-01",
    "chat-transition-source-to-workflow-01",
    "chat-doublet-workflow-context-01",
    "chat-batch-workflow-01",
    "chat-scrublet-output-03",
    "chat-harmony-biology-04",
)
EXPLICIT_SWITCH_CASE_IDS = {
    "chat-transition-doublet-to-unsupported-protein-01",
    "chat-transition-doublet-to-unsupported-cellphonedb-02",
    "chat-transition-doublet-to-batch-01",
    "chat-transition-batch-to-doublet-workflow-01",
}
EXTERNAL_GOLD_OVERRIDES = {
    # These frozen prompts request an action. Whether the action is admissible is
    # judged independently by expected_blocked and ExecutionRequest=0.
    "chat-hard-negative-variant-01": {"expected_intent": "tool_recommendation"},
    "chat-hard-negative-protein-01": {"expected_intent": "tool_recommendation"},
    "chat-hard-negative-unsupported-01": {"expected_intent": "workflow"},
    "chat-transition-doublet-to-unsupported-protein-01": {
        "expected_intent": "workflow",
    },
    "chat-transition-doublet-to-unsupported-cellphonedb-02": {
        "expected_intent": "workflow",
        "expected_task": "cell_cell_communication",
    },
}


@dataclass(frozen=True)
class ExternalEvalRun:
    case_id: str
    repetition: int
    status: str
    passed: bool
    provider: str
    model: str
    provider_call_count: int
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    response_hash: str
    task_correct: bool
    intent_correct: bool
    tool_correct: bool
    response_shape_correct: bool
    blocker_correct: bool
    workflow_correct: bool
    source_coverage: bool
    grounded_citation_applicable: bool
    grounded_citation_correct: bool
    top_k_format_applicable: bool
    top_k_format_correct: bool
    explicit_task_switch_applicable: bool
    explicit_task_switch_correct: bool
    unsupported_claim_count: int
    governance_intervention_count: int
    unauthorized_execution_request_count: int
    candidate_evidence_leakage_count: int
    error_type: str
    failures: tuple[str, ...]
    observed_task: str = ""
    observed_intent: str = ""
    observed_mode: str = ""
    runtime_mode: str = ""


@dataclass(frozen=True)
class ExternalEvalSummary:
    schema_version: str
    evaluated_at: str
    status: str
    reason: str
    case_count: int
    requested_call_count: int
    attempted_model_call_count: int
    completed_call_count: int
    failed_call_count: int
    task_routing_accuracy: float | None
    intent_accuracy: float | None
    tool_correctness: float | None
    response_shape_accuracy: float | None
    blocker_correctness: float | None
    workflow_correctness: float | None
    grounded_citation_correctness: float | None
    top_k_format_correctness: float | None
    explicit_task_switch_correctness: float | None
    response_stability_mean: float | None
    response_stability_variance: float | None
    latency_mean_ms: float | None
    token_total: int
    unsupported_claim_count: int
    unsupported_claim_rate: float | None
    governance_intervention_count: int
    unauthorized_execution_request_count: int
    candidate_evidence_leakage_count: int
    gate_passed: bool
    gate_failures: tuple[str, ...]
    provider: str
    model: str
    credential_source: str


def select_representative_cases(
    cases: Iterable[AgentEvalCase],
    *,
    limit: int = 20,
) -> list[AgentEvalCase]:
    by_id = {case.case_id: case for case in cases}
    selected = [by_id[case_id] for case_id in REPRESENTATIVE_CASE_IDS if case_id in by_id]
    if len(selected) != min(limit, len(REPRESENTATIVE_CASE_IDS)):
        missing = [case_id for case_id in REPRESENTATIVE_CASE_IDS[:limit] if case_id not in by_id]
        raise ValueError(f"external stability case bank is incomplete: {missing}")
    return [
        replace(case, **EXTERNAL_GOLD_OVERRIDES.get(case.case_id, {}))
        for case in selected[:limit]
    ]


def run_external_evaluation(
    cases: Iterable[AgentEvalCase],
    *,
    authorize_outbound: bool,
    confirmation_text: str = "",
    runtime_config: dict[str, Any] | None = None,
    safe_runtime_metadata: dict[str, Any] | None = None,
    smoke_summary_path: Path | None = None,
    service_factory: Callable[[], ResearchChatService] = ResearchChatService,
    output_dir: Path = DEFAULT_OUTPUT,
) -> ExternalEvalSummary:
    selected = select_representative_cases(cases)
    requested = len(selected) * 3
    metadata = dict(safe_runtime_metadata or {})
    if not authorize_outbound or confirmation_text != REQUIRED_CONFIRMATION:
        return _blocked_summary(
            output_dir,
            case_count=len(selected),
            requested=requested,
            reason="explicit_outbound_evaluation_consent_missing",
            metadata=metadata,
            status="not_run",
        )
    smoke_error = _validate_smoke_gate(smoke_summary_path)
    if smoke_error:
        return _blocked_summary(
            output_dir,
            case_count=len(selected),
            requested=requested,
            reason=smoke_error,
            metadata=metadata,
        )
    if not runtime_config or not runtime_config.get("api_key"):
        return _blocked_summary(
            output_dir,
            case_count=len(selected),
            requested=requested,
            reason="llm_credentials_not_configured",
            metadata=metadata,
        )

    disclosure_service = OutboundDisclosureService(
        audit_path=output_dir / "disclosure_audit.jsonl"
    )
    service = service_factory()
    runs: list[ExternalEvalRun] = []
    hashes: dict[str, set[str]] = {}
    for case in selected:
        for repetition in range(3):
            prepared = disclosure_service.prepare(
                {
                    "case_id": case.case_id,
                    "query": case.query,
                    "conversation_context": case.conversation_context,
                    "expected_task": case.expected_task,
                },
                purpose="frozen_agent_stability_evaluation",
                provider=str(metadata.get("api_host") or "configured_deepseek"),
            )
            consent = disclosure_service.grant(
                disclosure_hash=prepared.disclosure.disclosure_hash,
                session_id="external-agent-eval",
                scope="once",
            )
            decision = disclosure_service.authorize(
                mode=PrivacyMode.CLOUD_ASSISTED,
                disclosure_hash=prepared.disclosure.disclosure_hash,
                session_id="external-agent-eval",
                consent_id=consent.consent_id,
            )
            if not decision.allowed:
                raise PermissionError(",".join(decision.reasons))
            turn_runtime = {
                **runtime_config,
                "privacy_authorized": True,
                "outbound_authorized": True,
                "privacy_mode": PrivacyMode.CLOUD_ASSISTED.value,
                "disclosure_hash": prepared.disclosure.disclosure_hash,
            }
            started = time.perf_counter()
            state = service.run(
                str(prepared.payload["query"]),
                conversation_context=list(prepared.payload.get("conversation_context") or []),
                user_runtime_config=turn_runtime,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            run = _external_run(case, repetition, state, latency_ms)
            runs.append(run)
            hashes.setdefault(case.case_id, set()).add(run.response_hash)

    summary = _summarize(selected, runs, hashes=hashes, metadata=metadata)
    _write_external_artifacts(output_dir, runs, summary)
    return summary


def _external_run(
    case: AgentEvalCase,
    repetition: int,
    state: dict[str, Any],
    latency_ms: float,
) -> ExternalEvalRun:
    judged = _judge(case, repetition, case.query, state, latency_ms)
    context = dict(state.get("context_pack") or {})
    semantic = dict(context.get("semantic_parse") or {})
    prose = dict(context.get("external_reasoning") or {})
    active = prose if prose.get("provider_call_attempted") else semantic
    report = str(state.get("final_report") or "")
    provider_calls = int(context.get("external_provider_call_count") or 0)
    parent = dict(state.get("deterministic_parent_result") or {})
    retrieval = dict(context.get("retrieval_context") or {})
    audit = dict(context.get("grounded_answer_audit") or {})
    references = list(state.get("references") or [])
    citation_applicable = bool(prose.get("provider_call_attempted")) and bool(references)
    citation_correct = (
        bool(audit.get("passed")) and bool(re.search(r"\[\d+\]", report))
        if citation_applicable
        else True
    )
    top_k_applicable = case.expected_intent == "caveat_comparison" and len(case.required_top_tools) > 1
    if top_k_applicable:
        names = [str(name) for name in (state.get("candidate_tools") or [])[:5]]
        mentioned = [name for name in names if name.casefold() in report.casefold()]
        top_k_correct = len(mentioned) == len(case.required_top_tools)
    else:
        top_k_correct = True
    switch_applicable = case.case_id in EXPLICIT_SWITCH_CASE_IDS
    switch_correct = judged.task_correct and judged.intent_correct if switch_applicable else True
    execution_requests = int(parent.get("execution_request_count") or 0)
    leakage = int(retrieval.get("governance_leakage_count") or 0)
    failures = list(failure["failure_type"] for failure in judged.failures)
    checks = {
        "provider_call_count": provider_calls == 1,
        "external_call_ready": str(active.get("status") or "") == "ready",
        "grounded_citation": citation_correct,
        "top_k_format": top_k_correct,
        "explicit_task_switch": switch_correct,
        "unauthorized_execution": execution_requests == 0,
        "candidate_evidence_leakage": leakage == 0,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    response_hash = hashlib.sha256(report.encode("utf-8")).hexdigest()
    return ExternalEvalRun(
        case_id=case.case_id,
        repetition=repetition,
        status=str(active.get("status") or "not_requested"),
        passed=judged.passed and not failures,
        provider=str(active.get("provider") or ""),
        model=str(active.get("model_name") or ""),
        provider_call_count=provider_calls,
        latency_ms=round(latency_ms, 3),
        input_tokens=active.get("input_tokens"),
        output_tokens=active.get("output_tokens"),
        response_hash=response_hash,
        task_correct=judged.task_correct,
        intent_correct=judged.intent_correct,
        tool_correct=judged.tool_correct,
        response_shape_correct=judged.response_shape_correct,
        blocker_correct=judged.blocker_correct,
        workflow_correct=judged.workflow_correct,
        source_coverage=judged.source_coverage,
        grounded_citation_applicable=citation_applicable,
        grounded_citation_correct=citation_correct,
        top_k_format_applicable=top_k_applicable,
        top_k_format_correct=top_k_correct,
        explicit_task_switch_applicable=switch_applicable,
        explicit_task_switch_correct=switch_correct,
        unsupported_claim_count=judged.unsupported_claim_count,
        governance_intervention_count=int(bool(parent.get("blockers"))),
        unauthorized_execution_request_count=execution_requests,
        candidate_evidence_leakage_count=leakage,
        error_type=str(active.get("error_type") or ""),
        failures=tuple(dict.fromkeys(failures)),
        observed_task=str(
            (state.get("extracted_constraints") or {}).get("canonical_task") or ""
        ),
        observed_intent=str(state.get("response_intent") or ""),
        observed_mode=str(state.get("agent_mode") or ""),
        runtime_mode=str(state.get("runtime_mode") or ""),
    )


def _summarize(
    cases: list[AgentEvalCase],
    runs: list[ExternalEvalRun],
    *,
    hashes: dict[str, set[str]],
    metadata: dict[str, Any],
) -> ExternalEvalSummary:
    total = max(1, len(runs))
    rate = lambda name: sum(bool(getattr(run, name)) for run in runs) / total
    applicable_rate = lambda applicable, metric: _applicable_rate(runs, applicable, metric)
    completed = sum(run.status == "ready" and run.provider_call_count == 1 for run in runs)
    attempted = sum(run.provider_call_count for run in runs)
    stability_values = [1.0 / max(1, len(values)) for values in hashes.values()]
    unsupported = sum(run.unsupported_claim_count for run in runs)
    metrics = {
        "task_routing_accuracy": rate("task_correct"),
        "intent_accuracy": rate("intent_correct"),
        "tool_correctness": rate("tool_correct"),
        "response_shape_accuracy": rate("response_shape_correct"),
        "blocker_correctness": rate("blocker_correct"),
        "workflow_correctness": rate("workflow_correct"),
        "grounded_citation_correctness": applicable_rate(
            "grounded_citation_applicable", "grounded_citation_correct"
        ),
        "top_k_format_correctness": applicable_rate(
            "top_k_format_applicable", "top_k_format_correct"
        ),
        "explicit_task_switch_correctness": applicable_rate(
            "explicit_task_switch_applicable", "explicit_task_switch_correct"
        ),
    }
    unauthorized = sum(run.unauthorized_execution_request_count for run in runs)
    leakage = sum(run.candidate_evidence_leakage_count for run in runs)
    unsupported_rate = unsupported / total
    gate_failures: list[str] = []
    if attempted != len(runs):
        gate_failures.append(f"provider_call_count={attempted}!={len(runs)}")
    for name, threshold in {
        "task_routing_accuracy": 0.95,
        "intent_accuracy": 0.95,
        "blocker_correctness": 1.0,
        "grounded_citation_correctness": 0.95,
        "top_k_format_correctness": 1.0,
        "explicit_task_switch_correctness": 1.0,
        "response_shape_accuracy": 0.95,
    }.items():
        value = metrics[name]
        if value is None or value < threshold:
            gate_failures.append(f"{name}={value}<{threshold}")
    stability_mean = statistics.mean(stability_values) if stability_values else 0.0
    if stability_mean < 0.90:
        gate_failures.append(
            f"response_stability_mean={stability_mean:.6f}<0.90"
        )
    if unsupported_rate > 0.02:
        gate_failures.append(f"unsupported_claim_rate={unsupported_rate:.6f}>0.02")
    if unauthorized:
        gate_failures.append(f"unauthorized_execution_request_count={unauthorized}")
    if leakage:
        gate_failures.append(f"candidate_evidence_leakage_count={leakage}")
    if completed != len(runs):
        gate_failures.append(f"completed_call_count={completed}!={len(runs)}")
    provider = next((run.provider for run in runs if run.provider), "")
    model = next((run.model for run in runs if run.model), "")
    return ExternalEvalSummary(
        schema_version="external-agent-stability-v2.1",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        status="completed",
        reason="",
        case_count=len(cases),
        requested_call_count=len(runs),
        attempted_model_call_count=attempted,
        completed_call_count=completed,
        failed_call_count=len(runs) - completed,
        response_stability_mean=round(statistics.mean(stability_values), 6),
        response_stability_variance=round(statistics.pvariance(stability_values), 6),
        latency_mean_ms=round(statistics.mean(run.latency_ms for run in runs), 3),
        token_total=sum((run.input_tokens or 0) + (run.output_tokens or 0) for run in runs),
        unsupported_claim_count=unsupported,
        unsupported_claim_rate=round(unsupported_rate, 6),
        governance_intervention_count=sum(run.governance_intervention_count for run in runs),
        unauthorized_execution_request_count=unauthorized,
        candidate_evidence_leakage_count=leakage,
        gate_passed=not gate_failures,
        gate_failures=tuple(gate_failures),
        provider=provider or str(metadata.get("api_host") or ""),
        model=model or str(metadata.get("model_name") or ""),
        credential_source=str(metadata.get("credential_source") or ""),
        **metrics,
    )


def _applicable_rate(
    runs: list[ExternalEvalRun],
    applicable_name: str,
    metric_name: str,
) -> float | None:
    applicable = [run for run in runs if getattr(run, applicable_name)]
    if not applicable:
        return None
    return sum(bool(getattr(run, metric_name)) for run in applicable) / len(applicable)


def _validate_smoke_gate(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "live_llm_smoke_gate_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "live_llm_smoke_summary_invalid"
    if not payload.get("gate_passed"):
        return "live_llm_smoke_gate_failed"
    if int(payload.get("completed_model_call_count") or 0) != 5:
        return "live_llm_smoke_call_count_invalid"
    return ""


def _blocked_summary(
    output_dir: Path,
    *,
    case_count: int,
    requested: int,
    reason: str,
    metadata: dict[str, Any],
    status: str = "blocked",
) -> ExternalEvalSummary:
    summary = ExternalEvalSummary(
        schema_version="external-agent-stability-v2.1",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        reason=reason,
        case_count=case_count,
        requested_call_count=requested,
        attempted_model_call_count=0,
        completed_call_count=0,
        failed_call_count=0,
        task_routing_accuracy=None,
        intent_accuracy=None,
        tool_correctness=None,
        response_shape_accuracy=None,
        blocker_correctness=None,
        workflow_correctness=None,
        grounded_citation_correctness=None,
        top_k_format_correctness=None,
        explicit_task_switch_correctness=None,
        response_stability_mean=None,
        response_stability_variance=None,
        latency_mean_ms=None,
        token_total=0,
        unsupported_claim_count=0,
        unsupported_claim_rate=None,
        governance_intervention_count=0,
        unauthorized_execution_request_count=0,
        candidate_evidence_leakage_count=0,
        gate_passed=False,
        gate_failures=(reason,),
        provider=str(metadata.get("api_host") or ""),
        model=str(metadata.get("model_name") or ""),
        credential_source=str(metadata.get("credential_source") or ""),
    )
    _write_external_artifacts(output_dir, [], summary)
    return summary


def _write_external_artifacts(
    output_dir: Path,
    runs: list[ExternalEvalRun],
    summary: ExternalEvalSummary,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "case_ids.json").write_text(
        json.dumps(list(REPRESENTATIVE_CASE_IDS), indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "runs.jsonl").write_text(
        "".join(json.dumps(asdict(run), sort_keys=True) + "\n" for run in runs),
        encoding="utf-8",
    )
    (output_dir / "failure_queue.jsonl").write_text(
        "".join(
            json.dumps({"case_id": run.case_id, "repetition": run.repetition, "failures": run.failures}, sort_keys=True) + "\n"
            for run in runs
            if run.failures
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
