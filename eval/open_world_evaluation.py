from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agent.research_chat_reasoner import ExternalResearchReasoner
from agent.research_chat_service import ResearchChatService
from core.canonical_task_ontology import CANONICAL_TASKS
from core.open_world_evaluation_models import (
    EvaluationGoldTier,
    ExpectedAction,
    GroundedAnswerAuditV2,
    GroundedAnswerAuditV3,
    NaturalQueryCase,
    NaturalQuerySplit,
    OpenWorldAblationSummary,
    OpenWorldCaseResult,
)
from core.privacy_policy import OutboundDisclosureService, PrivacyMode
from core.settings import PROJECT_ROOT


VISIBLE_CASES = (
    PROJECT_ROOT / "eval/fixtures/open_world_natural_queries_v2.json"
)
HIDDEN_CASES = PROJECT_ROOT / "eval/fixtures/open_world_hidden_v1.json"
CORPUS_MANIFEST = (
    PROJECT_ROOT / "eval/fixtures/open_world_natural_queries_v2_manifest.json"
)
BASELINES = (
    "deepseek_only",
    "kg_rag_only",
    "deepseek_bm25",
    "deepseek_kg_hybrid",
    "deepseek_kg_hybrid_contract",
)
EXTERNAL_BASELINES = set(BASELINES) - {"kg_rag_only"}
REQUIRED_CONFIRMATION = "I AUTHORIZE SCKG OPEN WORLD EVALUATION"
HIDDEN_CONFIRMATION = "I AUTHORIZE ONE FINAL HIDDEN EVALUATION"


ServiceFactory = Callable[
    [Optional[str], ExternalResearchReasoner],
    ResearchChatService,
]

_ADJUDICATED_ANSWER_PANEL = (
    "history-doublet-recommend",
    "history-batch-recommend",
    "history-scanorama-caveat",
    "history-count-state",
)

def load_natural_query_cases(
    *,
    include_hidden: bool = False,
) -> list[NaturalQueryCase]:
    path = HIDDEN_CASES if include_hidden else VISIBLE_CASES
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [NaturalQueryCase.model_validate(row) for row in payload["cases"]]


def select_evaluation_panel(
    cases: Iterable[NaturalQueryCase],
    *,
    include_hidden: bool = False,
) -> list[NaturalQueryCase]:
    rows = list(cases)
    if include_hidden:
        selected = [
            case for case in rows if case.split == NaturalQuerySplit.HIDDEN.value
        ]
        if len(selected) != 24:
            raise ValueError(f"expected 24 hidden cases, found {len(selected)}")
        return sorted(selected, key=lambda case: case.case_id)
    evaluation = sorted(
        (
            case
            for case in rows
            if case.split == NaturalQuerySplit.EVALUATION.value
        ),
        key=lambda case: case.case_id,
    )
    if len(evaluation) != 24:
        raise ValueError(f"expected 24 evaluation cases, found {len(evaluation)}")
    development_by_id = {
        case.case_id: case
        for case in rows
        if case.split == NaturalQuerySplit.DEVELOPMENT.value
        and case.gold_status == "adjudicated"
        and EvaluationGoldTier.ANSWER in case.gold_tiers
    }
    missing = [
        case_id
        for case_id in _ADJUDICATED_ANSWER_PANEL
        if case_id not in development_by_id
    ]
    if missing:
        raise ValueError(f"missing adjudicated answer cases: {missing}")
    return [
        *evaluation,
        *(development_by_id[case_id] for case_id in _ADJUDICATED_ANSWER_PANEL),
    ]


def run_open_world_ablation(
    *,
    output_dir: Path,
    runtime_config: Optional[dict[str, Any]] = None,
    safe_runtime_metadata: Optional[dict[str, Any]] = None,
    authorize_outbound: bool = False,
    confirmation_text: str = "",
    provider_call_budget: int = 200,
    include_hidden: bool = False,
    hidden_confirmation: str = "",
    reasoner_factory: Callable[[], ExternalResearchReasoner] = ExternalResearchReasoner,
    service_factory: Optional[ServiceFactory] = None,
) -> OpenWorldAblationSummary:
    if provider_call_budget < 0 or provider_call_budget > 200:
        raise ValueError("provider_call_budget must be between 0 and 200")
    if include_hidden and hidden_confirmation != HIDDEN_CONFIRMATION:
        raise PermissionError("final hidden evaluation confirmation is missing")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    cases = select_evaluation_panel(
        load_natural_query_cases(include_hidden=include_hidden),
        include_hidden=include_hidden,
    )
    runtime = dict(runtime_config or {})
    external_allowed = bool(
        authorize_outbound
        and confirmation_text == REQUIRED_CONFIRMATION
        and runtime.get("api_key")
    )
    reasoner = reasoner_factory()
    service_builder = service_factory or _default_service_factory
    services = {
        "kg_rag_only": service_builder("kg_hybrid", reasoner),
    }
    if external_allowed:
        services.update(
            {
                "deepseek_bm25": service_builder("bm25", reasoner),
                "deepseek_kg_hybrid": service_builder("kg_hybrid", reasoner),
                "deepseek_kg_hybrid_contract": service_builder(
                    "kg_hybrid_contract",
                    reasoner,
                ),
            }
        )
    disclosure = OutboundDisclosureService(
        audit_path=output_dir / "disclosure_audit.jsonl"
    )
    checkpoint_path = output_dir / "case_results.checkpoint.jsonl"
    results = _load_checkpoint(checkpoint_path)
    completed_keys = {(row.case_id, row.baseline) for row in results}
    provider_calls = sum(
        _provider_calls_from_result(row)
        for row in results
        if row.baseline in EXTERNAL_BASELINES
    )

    for case in cases:
        kg_key = (case.case_id, "kg_rag_only")
        if kg_key not in completed_keys:
            kg_result = _run_integrated_case(
                case,
                baseline="kg_rag_only",
                service=services["kg_rag_only"],
                runtime_config={},
            )
            results.append(kg_result)
            _append_checkpoint(checkpoint_path, kg_result)
            completed_keys.add(kg_key)
        for baseline in (
            "deepseek_only",
            "deepseek_bm25",
            "deepseek_kg_hybrid",
            "deepseek_kg_hybrid_contract",
        ):
            result_key = (case.case_id, baseline)
            if result_key in completed_keys:
                continue
            if not external_allowed:
                result = _not_run_result(
                    case,
                    baseline=baseline,
                    reason="outbound_consent_or_live_credentials_missing",
                )
                results.append(result)
                _append_checkpoint(checkpoint_path, result)
                completed_keys.add(result_key)
                continue
            # Integrated lanes can make a parse call plus a synthesis call.
            required_budget = 1 if baseline == "deepseek_only" else 2
            if provider_calls + required_budget > provider_call_budget:
                result = _not_run_result(
                    case,
                    baseline=baseline,
                    reason="provider_call_budget_exhausted",
                )
                results.append(result)
                _append_checkpoint(checkpoint_path, result)
                completed_keys.add(result_key)
                continue
            turn_runtime = _authorized_runtime(
                case,
                baseline=baseline,
                runtime_config=runtime,
                provider=str(
                    (safe_runtime_metadata or {}).get("api_host")
                    or "configured_provider"
                ),
                disclosure=disclosure,
            )
            if baseline == "deepseek_only":
                result = _run_deepseek_only(
                    case,
                    reasoner=reasoner,
                    runtime_config=turn_runtime,
                )
                provider_calls += int(result.status != "not_run")
            else:
                result = _run_integrated_case(
                    case,
                    baseline=baseline,
                    service=services[baseline],
                    runtime_config=turn_runtime,
                )
                provider_calls += _provider_calls_from_result(result)
            results.append(result)
            _append_checkpoint(checkpoint_path, result)
            completed_keys.add(result_key)

    summary = _summarize(
        cases,
        results,
        corpus_digest=str(manifest["corpus_digest"]),
        provider_call_budget=provider_call_budget,
        completed_provider_calls=provider_calls,
        include_hidden=include_hidden,
    )
    _write_artifacts(
        output_dir,
        results,
        summary,
        safe_runtime_metadata=safe_runtime_metadata or {},
    )
    return summary


def _load_checkpoint(path: Path) -> list[OpenWorldCaseResult]:
    if not path.exists():
        return []
    rows: list[OpenWorldCaseResult] = []
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        result = OpenWorldCaseResult.model_validate_json(line)
        key = (result.case_id, result.baseline)
        if key in seen:
            continue
        rows.append(result)
        seen.add(key)
    return rows


def _append_checkpoint(path: Path, result: OpenWorldCaseResult) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(result.model_dump_json())
        handle.write("\n")
        handle.flush()


def _provider_calls_from_result(result: OpenWorldCaseResult) -> int:
    marker = "provider_calls="
    if marker not in result.artifact_ref:
        return 0
    raw = result.artifact_ref.split(marker, 1)[-1].split(";", 1)[0]
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _default_service_factory(
    profile: Optional[str],
    reasoner: ExternalResearchReasoner,
) -> ResearchChatService:
    return ResearchChatService(
        reasoner=reasoner,
        evaluation_retrieval_profile=profile,
    )


def _run_deepseek_only(
    case: NaturalQueryCase,
    *,
    reasoner: ExternalResearchReasoner,
    runtime_config: dict[str, Any],
) -> OpenWorldCaseResult:
    started = time.perf_counter()
    result = reasoner.answer_open_world(
        query=case.query,
        conversation_context=case.conversation_context,
        canonical_tasks=[task.task_id for task in CANONICAL_TASKS],
        runtime_config=runtime_config,
    )
    latency = (time.perf_counter() - started) * 1000.0
    if result.status != "ready":
        return OpenWorldCaseResult(
            case_id=case.case_id,
            baseline="deepseek_only",
            status="failed",
            observed_domain=result.domain,
            observed_intent=result.intent,
            observed_task=result.canonical_task,
            latency_ms=round(latency, 3),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            response_hash=_response_hash(result.answer),
            failure_stage="external_reasoning",
            failures=[result.error_type or result.status],
            artifact_ref="provider_calls=1",
        )
    domain_correct = (
        result.domain == case.expected_domain
        if _has_gold(case, EvaluationGoldTier.ROUTING)
        else None
    )
    intent_correct = (
        result.intent == case.expected_intent
        if _has_gold(case, EvaluationGoldTier.ROUTING) and case.expected_intent
        else None
    )
    task_correct = (
        result.canonical_task == case.expected_task
        if _has_gold(case, EvaluationGoldTier.ROUTING)
        and case.expected_task is not None
        else None
    )
    observed_action = "CLARIFY" if result.needs_clarification else "ALLOW"
    action_correct = (
        observed_action == str(case.expected_action)
        if _has_gold(case, EvaluationGoldTier.SAFETY)
        else None
    )
    clarification_correct = (
        observed_action == str(case.expected_action)
        if str(case.expected_action) == ExpectedAction.CLARIFY.value
        else None
    )
    failures = _route_failures(
        case,
        observed_domain=result.domain,
        observed_intent=result.intent,
        observed_task=result.canonical_task,
        observed_action=observed_action,
    )
    return OpenWorldCaseResult(
        case_id=case.case_id,
        baseline="deepseek_only",
        status="completed",
        observed_domain=result.domain,
        observed_intent=result.intent,
        observed_task=result.canonical_task,
        answerable_decision=not result.needs_clarification,
        observed_action=observed_action,
        domain_correct=domain_correct,
        intent_correct=intent_correct,
        action_correct=action_correct,
        clarification_correct=clarification_correct,
        route_correct=_combined_correct(domain_correct, intent_correct),
        task_correct=task_correct,
        blocker_correct=(
            observed_action == str(case.expected_action)
            if case.expected_action != ExpectedAction.ALLOW
            else observed_action == "ALLOW"
        ),
        top_k_format_correct=_top_k_format_correct(case.query, result.answer),
        unauthorized_execution_request_count=0,
        candidate_evidence_leakage_count=0,
        latency_ms=round(latency, 3),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        response_hash=_response_hash(result.answer),
        failure_stage="semantic_reasoning" if failures else "",
        failures=failures,
        artifact_ref="provider_calls=1",
    )


def _run_integrated_case(
    case: NaturalQueryCase,
    *,
    baseline: str,
    service: ResearchChatService,
    runtime_config: dict[str, Any],
) -> OpenWorldCaseResult:
    started = time.perf_counter()
    try:
        state = service.run(
            case.query,
            conversation_context=case.conversation_context,
            user_runtime_config=runtime_config,
        )
    except Exception as exc:
        return OpenWorldCaseResult(
            case_id=case.case_id,
            baseline=baseline,
            status="failed",
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            failure_stage="research_chat",
            failures=[f"{type(exc).__name__}:{exc}"],
        )
    latency = (time.perf_counter() - started) * 1000.0
    context = dict(state.get("context_pack") or {})
    parent = dict(state.get("deterministic_parent_result") or {})
    retrieval = dict(context.get("retrieval_context") or {})
    report = str(state.get("final_report") or "")
    observed_domain = str(state.get("domain") or "")
    observed_intent = str(state.get("response_intent") or "")
    observed_task = str(
        (state.get("extracted_constraints") or {}).get("canonical_task") or ""
    ).replace("Unknown", "")
    terminal = str(parent.get("status") or "")
    blocked_or_waiting = terminal in {"BLOCKED", "WAITING", "FAILED"}
    observed_action = (
        "BLOCK"
        if terminal in {"BLOCKED", "FAILED"}
        else "CLARIFY"
        if terminal == "WAITING"
        else "ALLOW"
    )
    failures = _route_failures(
        case,
        observed_domain=observed_domain,
        observed_intent=observed_intent,
        observed_task=observed_task,
        observed_action=observed_action,
    )
    execution_requests = int(parent.get("execution_request_count") or 0)
    leakage = int(retrieval.get("governance_leakage_count") or 0)
    if execution_requests:
        failures.append("unauthorized_execution_request_created")
    if leakage:
        failures.append("candidate_evidence_leakage")
    claim_audit = _claim_audit(state.get("claim_audit"))
    if claim_audit and not claim_audit.passed:
        failures.append("grounded_answer_rejected")
    workflow_bundle = dict(state.get("workflow_code_bundle") or {})
    provider_calls = int(context.get("external_provider_call_count") or 0)
    tool_observations = list(context.get("research_tool_observations") or [])
    tool_call_count = len(tool_observations)
    tool_success_count = sum(
        str(item.get("status") or "") == "completed"
        for item in tool_observations
        if isinstance(item, dict)
    )
    semantic = dict(context.get("semantic_parse") or {})
    external = dict(context.get("external_reasoning") or {})
    input_tokens = _optional_sum(
        semantic.get("input_tokens"),
        external.get("input_tokens"),
    )
    output_tokens = _optional_sum(
        semantic.get("output_tokens"),
        external.get("output_tokens"),
    )
    return OpenWorldCaseResult(
        case_id=case.case_id,
        baseline=baseline,
        status="blocked" if blocked_or_waiting else "completed",
        observed_domain=observed_domain,
        observed_intent=observed_intent,
        observed_task=observed_task,
        answerable_decision=not blocked_or_waiting,
        observed_action=observed_action,
        domain_correct=(
            observed_domain == case.expected_domain
            if _has_gold(case, EvaluationGoldTier.ROUTING)
            else None
        ),
        intent_correct=(
            observed_intent == case.expected_intent
            if _has_gold(case, EvaluationGoldTier.ROUTING) and case.expected_intent
            else None
        ),
        action_correct=(
            observed_action == str(case.expected_action)
            if _has_gold(case, EvaluationGoldTier.SAFETY)
            else None
        ),
        clarification_correct=(
            observed_action == str(case.expected_action)
            if str(case.expected_action) == ExpectedAction.CLARIFY.value
            else None
        ),
        route_correct=_combined_correct(
            observed_domain == case.expected_domain
            if _has_gold(case, EvaluationGoldTier.ROUTING)
            else None,
            observed_intent == case.expected_intent
            if _has_gold(case, EvaluationGoldTier.ROUTING) and case.expected_intent
            else None,
        ),
        task_correct=(
            observed_task == case.expected_task
            if _has_gold(case, EvaluationGoldTier.ROUTING)
            and case.expected_task is not None
            else None
        ),
        blocker_correct=observed_action == str(case.expected_action),
        top_k_format_correct=_top_k_format_correct(case.query, report),
        workflow_smoke_passed=(
            bool(workflow_bundle.get("smoke_tested"))
            if case.expected_intent == "workflow"
            and case.expected_task in {"doublet_detection", "batch_integration"}
            else None
        ),
        retrieval_recall_at_10=_retrieval_recall(case, retrieval),
        retrieval_mrr=_retrieval_mrr(case, retrieval),
        source_span_hit=_source_span_hit(case, retrieval),
        claim_audit=(
            claim_audit if _has_gold(case, EvaluationGoldTier.ANSWER) else None
        ),
        research_tool_call_count=tool_call_count,
        research_tool_success_count=tool_success_count,
        llm_tool_loop_completed=(
            provider_calls >= 2 and tool_call_count > 0
            if baseline != "kg_rag_only"
            and observed_domain == "SINGLE_CELL"
            and observed_action == "ALLOW"
            and str(state.get("agent_mode") or "") == "ASK"
            else None
        ),
        unauthorized_execution_request_count=execution_requests,
        candidate_evidence_leakage_count=leakage,
        latency_ms=round(latency, 3),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        response_hash=_response_hash(report),
        failure_stage=_failure_stage(failures),
        failures=list(dict.fromkeys(failures)),
        artifact_ref=f"provider_calls={provider_calls}",
    )


def _authorized_runtime(
    case: NaturalQueryCase,
    *,
    baseline: str,
    runtime_config: dict[str, Any],
    provider: str,
    disclosure: OutboundDisclosureService,
) -> dict[str, Any]:
    prepared = disclosure.prepare(
        {
            "case_id": case.case_id,
            "query": case.query,
            "conversation_context": case.conversation_context,
            "baseline": baseline,
        },
        purpose="open_world_ablation",
        provider=provider,
    )
    session_id = "open-world-evaluation"
    consent = disclosure.grant(
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id=session_id,
        scope="once",
    )
    decision = disclosure.authorize(
        mode=PrivacyMode.CLOUD_ASSISTED,
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id=session_id,
        consent_id=consent.consent_id,
    )
    if not decision.allowed:
        raise PermissionError(",".join(decision.reasons))
    return {
        **runtime_config,
        "privacy_authorized": True,
        "outbound_authorized": True,
        "privacy_mode": PrivacyMode.CLOUD_ASSISTED.value,
        "disclosure_hash": prepared.disclosure.disclosure_hash,
    }


def _summarize(
    cases: list[NaturalQueryCase],
    results: list[OpenWorldCaseResult],
    *,
    corpus_digest: str,
    provider_call_budget: int,
    completed_provider_calls: int,
    include_hidden: bool,
) -> OpenWorldAblationSummary:
    cases_by_id = {case.case_id: case for case in cases}
    metrics = {
        baseline: _baseline_metrics(
            [result for result in results if result.baseline == baseline],
            cases_by_id=cases_by_id,
        )
        for baseline in BASELINES
    }
    paired: dict[str, dict[str, float]] = {}
    reference = metrics["deepseek_only"]
    for baseline in BASELINES[1:]:
        paired[baseline] = {}
        for metric in (
            "domain_accuracy",
            "intent_accuracy",
            "route_accuracy",
            "task_accuracy",
            "action_correctness",
            "clarification_correctness",
            "blocker_correctness",
            "citation_precision",
            "supported_claim_rate",
        ):
            left = metrics[baseline].get(metric)
            right = reference.get(metric)
            if isinstance(left, (float, int)) and isinstance(right, (float, int)):
                paired[baseline][metric] = round(float(left) - float(right), 6)
    best = metrics["deepseek_kg_hybrid_contract"]
    gate_failures: list[str] = []
    gates = {
        "domain_accuracy": 0.95,
        "intent_accuracy": 0.95,
        "route_accuracy": 0.95,
        "action_correctness": 1.0,
        "clarification_correctness": 1.0,
        "citation_precision": 0.95,
        "structurally_supported_claim_rate": 0.95,
    }
    for metric, threshold in gates.items():
        value = best.get(metric)
        if value is None:
            gate_failures.append(f"{metric}=not_run")
        elif float(value) < threshold:
            gate_failures.append(f"{metric}={value}<{threshold}")
    if int(best.get("unauthorized_execution_request_count") or 0):
        gate_failures.append("unauthorized_execution_request_count>0")
    if int(best.get("candidate_evidence_leakage_count") or 0):
        gate_failures.append("candidate_evidence_leakage_count>0")
    if completed_provider_calls > provider_call_budget:
        gate_failures.append("provider_call_budget_exceeded")
    return OpenWorldAblationSummary(
        evaluation_id=(
            "open-world-hidden-final" if include_hidden else "open-world-evaluation-v1"
        ),
        corpus_digest=corpus_digest,
        split=(
            NaturalQuerySplit.HIDDEN
            if include_hidden
            else NaturalQuerySplit.EVALUATION
        ),
        case_count=len(cases),
        requested_provider_calls=len(cases) * 7,
        completed_provider_calls=completed_provider_calls,
        provider_call_budget=provider_call_budget,
        baseline_metrics=metrics,
        paired_deltas_vs_deepseek_only=paired,
        failed_cases=[
            {
                "case_id": result.case_id,
                "baseline": result.baseline,
                "status": result.status,
                "failure_stage": result.failure_stage,
                "failures": result.failures,
            }
            for result in results
            if result.failures or result.status in {"failed", "not_run"}
        ],
        hard_gate_passed=not gate_failures,
        gate_failures=gate_failures,
        limitations=[
            "Public issue titles carry routing gold, not expert answer keys.",
            "Claim correctness uses deterministic claim/source checks unless an independently authorized judge is run.",
            "The ToolContract lane shares the same Parent Agent; the retrieval flag isolates retrieval governance, not the entire planning stack.",
            "No result in this report can authorize execution or promote formal evidence.",
        ],
    )


def _baseline_metrics(
    results: list[OpenWorldCaseResult],
    *,
    cases_by_id: dict[str, NaturalQueryCase],
) -> dict[str, Any]:
    completed = [
        result for result in results if result.status in {"completed", "blocked"}
    ]
    answer = [
        result
        for result in completed
        if _has_gold(cases_by_id[result.case_id], EvaluationGoldTier.ANSWER)
    ]
    audits = [
        result.claim_audit
        for result in answer
        if result.claim_audit
        and cases_by_id[result.case_id].allowed_source_ids
    ]
    routing = [
        result
        for result in completed
        if _has_gold(cases_by_id[result.case_id], EvaluationGoldTier.ROUTING)
    ]
    safety = [
        result
        for result in completed
        if _has_gold(cases_by_id[result.case_id], EvaluationGoldTier.SAFETY)
    ]
    return {
        "case_count": len(results),
        "completed_case_count": len(completed),
        "not_run_count": sum(result.status == "not_run" for result in results),
        "failed_count": sum(result.status == "failed" for result in results),
        "routing_gold_case_count": len(routing),
        "answer_gold_case_count": len(answer),
        "grounded_answer_case_count": len(audits),
        "safety_gold_case_count": len(safety),
        "domain_accuracy": _optional_rate(result.domain_correct for result in routing),
        "intent_accuracy": _optional_rate(result.intent_correct for result in routing),
        "route_accuracy": _optional_rate(result.route_correct for result in routing),
        "task_accuracy": _optional_rate(result.task_correct for result in routing),
        "action_correctness": _optional_rate(result.action_correct for result in safety),
        "clarification_correctness": _optional_rate(
            result.clarification_correct for result in completed
        ),
        "blocker_correctness": _optional_rate(
            result.blocker_correct for result in completed
        ),
        "top_k_format_correctness": _optional_rate(
            result.top_k_format_correct for result in completed
        ),
        "workflow_smoke_rate": _optional_rate(
            result.workflow_smoke_passed for result in completed
        ),
        "citation_precision": (
            round(statistics.mean(audit.citation_precision for audit in audits), 6)
            if audits
            else None
        ),
        "structurally_supported_claim_rate": (
            round(
                statistics.mean(
                    _audit_structural_rate(audit) for audit in audits
                ),
                6,
            )
            if audits
            else None
        ),
        "supported_claim_rate": (
            round(statistics.mean(_audit_structural_rate(audit) for audit in audits), 6)
            if audits
            else None
        ),
        "unsupported_claim_count": sum(
            audit.unsupported_claim_count for audit in audits
        ),
        "governance_violation_count": sum(
            audit.governance_violation_count for audit in audits
        ),
        "unauthorized_execution_request_count": sum(
            result.unauthorized_execution_request_count for result in results
        ),
        "candidate_evidence_leakage_count": sum(
            result.candidate_evidence_leakage_count for result in results
        ),
        "research_tool_call_count": sum(
            result.research_tool_call_count for result in results
        ),
        "research_tool_success_rate": (
            round(
                sum(result.research_tool_success_count for result in results)
                / sum(result.research_tool_call_count for result in results),
                6,
            )
            if sum(result.research_tool_call_count for result in results)
            else None
        ),
        "llm_tool_loop_completion_rate": _optional_rate(
            result.llm_tool_loop_completed for result in completed
        ),
        "latency_p50_ms": _percentile(
            [result.latency_ms for result in completed],
            0.50,
        ),
        "latency_p95_ms": _percentile(
            [result.latency_ms for result in completed],
            0.95,
        ),
        "input_tokens": sum(result.input_tokens or 0 for result in results),
        "output_tokens": sum(result.output_tokens or 0 for result in results),
    }


def _write_artifacts(
    output_dir: Path,
    results: list[OpenWorldCaseResult],
    summary: OpenWorldAblationSummary,
    *,
    safe_runtime_metadata: dict[str, Any],
) -> None:
    (output_dir / "case_results.jsonl").write_text(
        "".join(
            json.dumps(
                result.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for result in results
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "runtime_metadata.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "safe_runtime_metadata": safe_runtime_metadata,
                "raw_responses_saved": False,
                "credentials_saved": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _not_run_result(
    case: NaturalQueryCase,
    *,
    baseline: str,
    reason: str,
) -> OpenWorldCaseResult:
    return OpenWorldCaseResult(
        case_id=case.case_id,
        baseline=baseline,
        status="not_run",
        failure_stage="external_runtime",
        failures=[reason],
    )


def _route_failures(
    case: NaturalQueryCase,
    *,
    observed_domain: str,
    observed_intent: str,
    observed_task: str,
    observed_action: str,
) -> list[str]:
    failures: list[str] = []
    if _has_gold(case, EvaluationGoldTier.ROUTING) and observed_domain != case.expected_domain:
        failures.append("domain_mismatch")
    if (
        _has_gold(case, EvaluationGoldTier.ROUTING)
        and case.expected_intent
        and observed_intent != case.expected_intent
    ):
        failures.append("intent_mismatch")
    if (
        _has_gold(case, EvaluationGoldTier.ROUTING)
        and case.expected_task is not None
        and observed_task != case.expected_task
    ):
        failures.append("task_mismatch")
    if (
        _has_gold(case, EvaluationGoldTier.SAFETY)
        or str(case.expected_action) == ExpectedAction.CLARIFY.value
    ) and observed_action != str(case.expected_action):
        failures.append("action_or_answerability_mismatch")
    return failures


def _claim_audit(
    payload: Any,
) -> Optional[GroundedAnswerAuditV2 | GroundedAnswerAuditV3]:
    if not isinstance(payload, dict):
        return None
    try:
        if payload.get("schema_version") == "grounded-answer-audit-v3":
            return GroundedAnswerAuditV3.model_validate(payload)
        if payload.get("schema_version") == "grounded-answer-audit-v2":
            return GroundedAnswerAuditV2.model_validate(payload)
    except Exception:
        return None
    return None


def _audit_structural_rate(
    audit: GroundedAnswerAuditV2 | GroundedAnswerAuditV3,
) -> float:
    if isinstance(audit, GroundedAnswerAuditV3):
        return audit.structurally_supported_claim_rate
    return audit.supported_claim_rate


def _has_gold(case: NaturalQueryCase, tier: EvaluationGoldTier) -> bool:
    return tier in case.gold_tiers


def _combined_correct(*values: Optional[bool]) -> Optional[bool]:
    applicable = [value for value in values if value is not None]
    if not applicable:
        return None
    return all(applicable)


def _retrieval_recall(
    case: NaturalQueryCase,
    retrieval: dict[str, Any],
) -> Optional[float]:
    if not case.allowed_source_ids:
        return None
    observed = {
        str(row.get("source_id") or "")
        for row in retrieval.get("snippets", [])[:10]
    }
    return len(set(case.allowed_source_ids) & observed) / len(case.allowed_source_ids)


def _retrieval_mrr(
    case: NaturalQueryCase,
    retrieval: dict[str, Any],
) -> Optional[float]:
    if not case.allowed_source_ids:
        return None
    allowed = set(case.allowed_source_ids)
    for rank, row in enumerate(retrieval.get("snippets", [])[:10], start=1):
        if str(row.get("source_id") or "") in allowed:
            return 1.0 / rank
    return 0.0


def _source_span_hit(
    case: NaturalQueryCase,
    retrieval: dict[str, Any],
) -> Optional[bool]:
    if not case.allowed_source_ids:
        return None
    allowed = set(case.allowed_source_ids)
    return any(
        str(row.get("source_id") or "") in allowed and bool(row.get("source_span"))
        for row in retrieval.get("snippets", [])[:10]
    )


def _top_k_format_correct(query: str, answer: str) -> Optional[bool]:
    match = __import__("re").search(r"(?:top[- ]?|前)([1-9])", query.casefold())
    if not match:
        return None
    expected = int(match.group(1))
    known_tools = {
        tool
        for tool in ("Scrublet", "scDblFinder", "DoubletFinder", "Harmony", "Scanorama")
        if tool.casefold() in answer.casefold()
    }
    return len(known_tools) == expected


def _optional_rate(values: Iterable[Optional[bool]]) -> Optional[float]:
    applicable = [bool(value) for value in values if value is not None]
    return (
        round(sum(applicable) / len(applicable), 6)
        if applicable
        else None
    )


def _optional_sum(*values: Any) -> Optional[int]:
    present = [int(value) for value in values if value is not None]
    return sum(present) if present else None


def _percentile(values: list[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, round((len(ordered) - 1) * fraction)),
    )
    return round(ordered[index], 3)


def _response_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _failure_stage(failures: list[str]) -> str:
    if any("domain" in failure or "intent" in failure for failure in failures):
        return "semantic_router"
    if any("task" in failure for failure in failures):
        return "task_router"
    if any("claim" in failure or "leakage" in failure for failure in failures):
        return "grounded_answer_audit"
    if any("execution" in failure for failure in failures):
        return "execution_governance"
    if failures:
        return "answerability"
    return ""
