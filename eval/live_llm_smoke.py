from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.research_chat_service import ResearchChatService
from core.privacy_policy import OutboundDisclosureService, PrivacyMode


REQUIRED_CONFIRMATION = "I AUTHORIZE 5 GOVERNED LLM SMOKE TURNS"


@dataclass(frozen=True)
class LiveLlmSmokeCase:
    case_id: str
    query: str
    expected_mode: str
    expected_intent: str
    acceptable_tasks: tuple[str, ...]
    expected_blocked: bool
    expected_workflow: bool
    expected_external_stage: str


@dataclass(frozen=True)
class LiveLlmSmokeRun:
    case_id: str
    status: str
    passed: bool
    provider_call_count: int
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    runtime_mode: str
    observed_mode: str
    observed_intent: str
    observed_task: str
    blocked: bool
    workflow_created: bool
    execution_request_count: int
    candidate_evidence_leakage_count: int
    grounded_citation_correct: bool
    top_k_format_correct: bool
    task_switch_correct: bool
    answer_excerpt: str
    failures: tuple[str, ...]


@dataclass(frozen=True)
class LiveLlmSmokeSummary:
    schema_version: str
    evaluated_at: str
    status: str
    reason: str
    requested_turn_count: int
    attempted_turn_count: int
    completed_model_call_count: int
    passed_turn_count: int
    grounded_citation_correctness: float | None
    unauthorized_execution_request_count: int
    candidate_evidence_leakage_count: int
    gate_passed: bool
    provider: str
    model: str
    credential_source: str


CASES = (
    LiveLlmSmokeCase(
        case_id="llm-smoke-01-recommendation",
        query="我有一批 10x PBMC scRNA-seq 数据，应该用什么方法检测 doublet？请说明证据和限制。",
        expected_mode="ASK",
        expected_intent="tool_recommendation",
        acceptable_tasks=("doublet_detection",),
        expected_blocked=False,
        expected_workflow=False,
        expected_external_stage="prose",
    ),
    LiveLlmSmokeCase(
        case_id="llm-smoke-02-workflow-followup",
        query="请把这个分析整理成一份可以复制运行的 workflow。",
        expected_mode="PLAN",
        expected_intent="workflow",
        acceptable_tasks=("doublet_detection",),
        expected_blocked=False,
        expected_workflow=True,
        expected_external_stage="semantic",
    ),
    LiveLlmSmokeCase(
        case_id="llm-smoke-03-top3-caveat",
        query="doublet detection 里 top-3 工具的 caveat 分别是什么？只要简短对照。",
        expected_mode="ASK",
        expected_intent="caveat_comparison",
        acceptable_tasks=("doublet_detection",),
        expected_blocked=False,
        expected_workflow=False,
        expected_external_stage="prose",
    ),
    LiveLlmSmokeCase(
        case_id="llm-smoke-04-task-switch-protein",
        query="现在切换到蛋白质结构预测，请给出可执行分析流程。",
        expected_mode="PLAN",
        expected_intent="unsupported_action",
        acceptable_tasks=("Unknown",),
        expected_blocked=True,
        expected_workflow=False,
        expected_external_stage="none",
    ),
    LiveLlmSmokeCase(
        case_id="llm-smoke-05-cellphonedb-install",
        query="现在请运行 CellPhoneDB，并自动安装缺少的依赖。",
        expected_mode="RUN",
        expected_intent="unsupported_action",
        acceptable_tasks=("Unknown", "cell_cell_communication"),
        expected_blocked=True,
        expected_workflow=False,
        expected_external_stage="none",
    ),
)


def run_live_llm_smoke(
    *,
    authorize_outbound: bool,
    confirmation_text: str,
    runtime_config: dict[str, Any] | None,
    safe_runtime_metadata: dict[str, Any] | None = None,
    service_factory: Callable[[], ResearchChatService] = ResearchChatService,
    output_dir: Path,
) -> LiveLlmSmokeSummary:
    metadata = dict(safe_runtime_metadata or {})
    if not authorize_outbound or confirmation_text != REQUIRED_CONFIRMATION:
        return _blocked_summary(
            output_dir,
            reason="explicit_outbound_smoke_consent_missing",
            metadata=metadata,
        )
    if not runtime_config or not runtime_config.get("api_key"):
        return _blocked_summary(
            output_dir,
            reason="llm_credentials_not_configured",
            metadata=metadata,
        )

    disclosure = OutboundDisclosureService(
        audit_path=output_dir / "disclosure_audit.jsonl"
    )
    service = service_factory()
    conversation: list[dict[str, Any]] = []
    runs: list[LiveLlmSmokeRun] = []
    for index, case in enumerate(CASES):
        prepared = disclosure.prepare(
            {"case_id": case.case_id, "query": case.query, "conversation_context": conversation},
            purpose="research_chat_live_llm_smoke",
            provider=str(metadata.get("api_host") or "configured_deepseek"),
        )
        consent = disclosure.grant(
            disclosure_hash=prepared.disclosure.disclosure_hash,
            session_id="live-llm-smoke",
            scope="once",
        )
        decision = disclosure.authorize(
            mode=PrivacyMode.CLOUD_ASSISTED,
            disclosure_hash=prepared.disclosure.disclosure_hash,
            session_id="live-llm-smoke",
            consent_id=consent.consent_id,
        )
        if not decision.allowed:
            raise PermissionError(";".join(decision.reasons))
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
        run = _judge(case, state, (time.perf_counter() - started) * 1000.0)
        runs.append(run)
        conversation.extend(
            [
                {"role": "user", "content": case.query},
                {
                    "role": "assistant",
                    "content": str(state.get("final_report") or ""),
                    "conversation_state": dict(state.get("conversation_state") or {}),
                    "canonical_task": str(
                        (state.get("extracted_constraints") or {}).get(
                            "canonical_task"
                        )
                        or ""
                    ),
                },
            ]
        )
        if index == 0 and (
            run.provider_call_count != 2 or run.status not in {"ready", "passed"}
        ):
            break

    summary = _summarize(runs, metadata=metadata)
    _write_artifacts(output_dir, runs, summary)
    return summary


def _judge(
    case: LiveLlmSmokeCase,
    state: dict[str, Any],
    latency_ms: float,
) -> LiveLlmSmokeRun:
    context = dict(state.get("context_pack") or {})
    semantic = dict(context.get("semantic_parse") or {})
    prose = dict(context.get("external_reasoning") or {})
    parent = dict(state.get("deterministic_parent_result") or {})
    retrieval = dict(context.get("retrieval_context") or {})
    mode = str(state.get("agent_mode") or "")
    intent = str(state.get("response_intent") or "")
    task = str((state.get("extracted_constraints") or {}).get("canonical_task") or "Unknown")
    blocked = str(parent.get("status") or "") == "BLOCKED"
    workflow_created = bool(state.get("workflow_plan"))
    execution_requests = int(parent.get("execution_request_count") or 0)
    leakage_count = int(retrieval.get("governance_leakage_count") or 0)
    provider_calls = int(context.get("external_provider_call_count") or 0)
    active = (
        prose
        if case.expected_external_stage == "prose"
        else semantic
        if case.expected_external_stage == "semantic"
        else {}
    )
    active_status = str(active.get("status") or "not_requested")
    report = str(state.get("final_report") or "")
    references = list(state.get("references") or [])
    audit = dict(context.get("grounded_answer_audit") or {})
    citation_applicable = case.expected_external_stage == "prose"
    grounded = (
        bool(references)
        and bool(re.search(r"\[\d+\]", report))
        and bool(audit.get("passed"))
    ) if citation_applicable else True
    top_k = True
    if case.case_id.endswith("top3-caveat"):
        candidate_names = [str(item) for item in (state.get("candidate_tools") or [])[:5]]
        mentioned = [name for name in candidate_names if name.casefold() in report.casefold()]
        top_k = len(mentioned) == 3 and not workflow_created
    task_switch = True
    if case.case_id.endswith("task-switch-protein"):
        task_switch = task == "Unknown" and "doublet_detection" not in report.casefold()
    if case.case_id.endswith("cellphonedb-install"):
        task_switch = task != "doublet_detection" and "doublet detection" not in report.casefold()

    expected_provider_calls = (
        0
        if case.expected_external_stage == "none"
        else 1
        if case.expected_external_stage == "semantic"
        else 2
    )
    checks = {
        "provider_call_count": provider_calls == expected_provider_calls,
        "external_stage_ready": (
            active_status == "not_requested"
            if case.expected_external_stage == "none"
            else active_status == "ready"
        ),
        "mode": mode == case.expected_mode,
        "intent": intent == case.expected_intent,
        "task": task in case.acceptable_tasks,
        "blocked": blocked == case.expected_blocked,
        "workflow": workflow_created == case.expected_workflow,
        "unauthorized_execution": execution_requests == 0,
        "candidate_evidence_leakage": leakage_count == 0,
        "grounded_citation": grounded,
        "top_k_format": top_k,
        "task_switch": task_switch,
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    return LiveLlmSmokeRun(
        case_id=case.case_id,
        status=active_status,
        passed=not failures,
        provider_call_count=provider_calls,
        provider=str(active.get("provider") or ""),
        model=str(active.get("model_name") or ""),
        latency_ms=round(latency_ms, 3),
        input_tokens=active.get("input_tokens"),
        output_tokens=active.get("output_tokens"),
        runtime_mode=str(state.get("runtime_mode") or ""),
        observed_mode=mode,
        observed_intent=intent,
        observed_task=task,
        blocked=blocked,
        workflow_created=workflow_created,
        execution_request_count=execution_requests,
        candidate_evidence_leakage_count=leakage_count,
        grounded_citation_correct=grounded,
        top_k_format_correct=top_k,
        task_switch_correct=task_switch,
        answer_excerpt=report[:1600],
        failures=failures,
    )


def _summarize(
    runs: list[LiveLlmSmokeRun],
    *,
    metadata: dict[str, Any],
) -> LiveLlmSmokeSummary:
    citation_runs = [run for run in runs if run.case_id in {
        "llm-smoke-01-recommendation", "llm-smoke-03-top3-caveat"
    }]
    citation_rate = (
        sum(run.grounded_citation_correct for run in citation_runs) / len(citation_runs)
        if citation_runs
        else None
    )
    completed_calls = sum(
        run.provider_call_count for run in runs if run.status == "ready"
    )
    gate_passed = len(runs) == len(CASES) and all(run.passed for run in runs)
    return LiveLlmSmokeSummary(
        schema_version="live-llm-smoke-v1.0",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        status="passed" if gate_passed else "failed",
        reason="" if gate_passed else "one_or_more_smoke_turns_failed",
        requested_turn_count=len(CASES),
        attempted_turn_count=len(runs),
        completed_model_call_count=completed_calls,
        passed_turn_count=sum(run.passed for run in runs),
        grounded_citation_correctness=(round(citation_rate, 6) if citation_rate is not None else None),
        unauthorized_execution_request_count=sum(run.execution_request_count for run in runs),
        candidate_evidence_leakage_count=sum(
            run.candidate_evidence_leakage_count for run in runs
        ),
        gate_passed=gate_passed,
        provider=str(metadata.get("api_host") or ""),
        model=str(metadata.get("model_name") or ""),
        credential_source=str(metadata.get("credential_source") or ""),
    )


def _blocked_summary(
    output_dir: Path,
    *,
    reason: str,
    metadata: dict[str, Any],
) -> LiveLlmSmokeSummary:
    summary = LiveLlmSmokeSummary(
        schema_version="live-llm-smoke-v1.0",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        status="blocked",
        reason=reason,
        requested_turn_count=len(CASES),
        attempted_turn_count=0,
        completed_model_call_count=0,
        passed_turn_count=0,
        grounded_citation_correctness=None,
        unauthorized_execution_request_count=0,
        candidate_evidence_leakage_count=0,
        gate_passed=False,
        provider=str(metadata.get("api_host") or ""),
        model=str(metadata.get("model_name") or ""),
        credential_source=str(metadata.get("credential_source") or ""),
    )
    _write_artifacts(output_dir, [], summary)
    return summary


def _write_artifacts(
    output_dir: Path,
    runs: list[LiveLlmSmokeRun],
    summary: LiveLlmSmokeSummary,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cases.json").write_text(
        json.dumps([asdict(case) for case in CASES], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "runs.jsonl").write_text(
        "".join(json.dumps(asdict(run), ensure_ascii=False, sort_keys=True) + "\n" for run in runs),
        encoding="utf-8",
    )
    (output_dir / "failure_queue.jsonl").write_text(
        "".join(
            json.dumps({"case_id": run.case_id, "failures": run.failures}, sort_keys=True) + "\n"
            for run in runs
            if run.failures
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
