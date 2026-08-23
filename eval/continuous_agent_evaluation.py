from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from core.continuous_evaluation_models import (
    ArchitectureStage,
    BusinessDomain,
    BusinessDomainSummary,
    CategorySummary,
    ContinuousAgentEvaluationReport,
    ContinuousMetric,
    EvaluationCategory,
    EvaluationCoverage,
    EvaluationLane,
    FailureCluster,
    MetricDirection,
    MetricSeverity,
    MetricSignal,
    MetricStatus,
    MetricTrend,
    OptimizationPriority,
)
from core.settings import PROJECT_ROOT
from eval.evaluation_registry import EvaluationExperimentRegistry


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "continuous_agent_quality_v1"
DEFAULT_PORTFOLIO_SUMMARY = (
    PROJECT_ROOT
    / ".sckg_exec"
    / "evaluations"
    / "portfolio-v2-full-20260717"
    / "benchmark_summary.json"
)


@dataclass(frozen=True)
class EvaluationSourcePaths:
    agent_quality: Path = PROJECT_ROOT / "data/evaluation/agent_quality_v2/summary.json"
    retrieval_quality: Path = PROJECT_ROOT / "data/evaluation/retrieval_eval_v2/summary.json"
    system_quality: Path = PROJECT_ROOT / "data/evaluation/system_quality_v1/summary.json"
    phase6_baseline: Path = PROJECT_ROOT / "eval/phase6/baseline_summary.json"
    workflow_code_smoke: Path = (
        PROJECT_ROOT / "data/evaluation/workflow_code_smoke_v1/summary.json"
    )
    portfolio: Path = DEFAULT_PORTFOLIO_SUMMARY
    group_trial: Path = (
        PROJECT_ROOT
        / ".sckg_exec/evaluations/system-quality-20260721T160910Z/group_trial/trial_summary.json"
    )
    batch_decision: Path = (
        PROJECT_ROOT
        / ".sckg_exec/packages/phase5-batch-scientific-20260716T083044Z/decision_result.json"
    )
    batch_manifest: Path = (
        PROJECT_ROOT
        / ".sckg_exec/packages/phase5-batch-scientific-20260716T083044Z/reproducibility_manifest.json"
    )


class ContinuousAgentEvaluator:
    """Measure the scKG Agent system by business domain and architecture stage.

    This evaluator only reads existing structured artifacts. It never invokes an
    LLM, executes a tool, grants approval, or changes a release state.
    """

    def __init__(self, *, sources: EvaluationSourcePaths | None = None) -> None:
        self._use_experiment_registry = sources is None
        self.sources = sources or EvaluationSourcePaths()

    def evaluate(
        self,
        *,
        evaluation_id: str,
        baseline_path: Path | None = None,
    ) -> ContinuousAgentEvaluationReport:
        unified: dict[str, Any] = {}
        if self._use_experiment_registry:
            unified = EvaluationExperimentRegistry().latest("release")
            if not unified:
                unified = EvaluationExperimentRegistry().latest("nightly")
            if not unified:
                unified = EvaluationExperimentRegistry().latest("pr")
        experiment_root = (
            (PROJECT_ROOT / str(unified.get("path") or "")).resolve()
            if unified
            else None
        )
        payloads = {
            "agent": _read_json(
                experiment_root / "agent_quality/summary.json"
                if experiment_root
                else self.sources.agent_quality
            ),
            "retrieval": _read_json(
                experiment_root / "retrieval/summary.json"
                if experiment_root
                else self.sources.retrieval_quality
            ),
            "system": _read_json(self.sources.system_quality),
            "phase6": _read_json(self.sources.phase6_baseline),
            "workflow": _read_json(self.sources.workflow_code_smoke),
            "portfolio": _read_json(self.sources.portfolio),
            "trial": _read_json(self.sources.group_trial),
            "batch_decision": _read_json(self.sources.batch_decision),
            "batch_manifest": _read_json(self.sources.batch_manifest),
            "unified": unified,
        }
        metrics = _build_metrics(payloads)
        trends, regression_status = _compare_metrics(metrics, baseline_path)
        regression_count = sum(item.regressed for item in trends)
        category_summaries = _summarize_categories(metrics)
        business_domain_summaries = _summarize_domains(metrics)
        coverage = _coverage(metrics)
        zero_tolerance_violations = sum(
            metric.severity == MetricSeverity.ZERO_TOLERANCE
            and metric.signal == MetricSignal.BLOCKED
            for metric in metrics
        )
        blockers = [
            metric.metric_id
            for metric in metrics
            if metric.signal == MetricSignal.BLOCKED
        ]
        warnings = [
            "external_llm_repeat_variance_not_measured"
            if _metric(metrics, "stability.external_llm_repeat_variance").status
            != MetricStatus.MEASURED
            else "",
            "real_user_trial_not_completed"
            if _metric(metrics, "effectiveness.human_task_completion_rate").status
            != MetricStatus.MEASURED
            else "",
            "ragas_not_run_or_not_authorized"
            if _metric(metrics, "effectiveness.ragas_faithfulness").status
            != MetricStatus.MEASURED
            else "",
            "frozen_continuous_baseline_not_provided"
            if regression_status == "baseline_not_provided"
            else "",
        ]
        warnings = [item for item in warnings if item]
        if zero_tolerance_violations:
            release_signal = MetricSignal.BLOCKED
        elif regression_count or any(
            summary.signal in {MetricSignal.WATCH, MetricSignal.UNKNOWN}
            for summary in category_summaries
        ):
            release_signal = MetricSignal.WATCH
        else:
            release_signal = MetricSignal.HEALTHY
        return ContinuousAgentEvaluationReport(
            evaluation_id=evaluation_id,
            metrics=metrics,
            category_summaries=category_summaries,
            business_domain_summaries=business_domain_summaries,
            coverage=coverage,
            trends=trends,
            failure_clusters=_failure_clusters(payloads),
            optimization_priorities=_optimization_priorities(
                metrics, regression_status=regression_status
            ),
            regression_status=regression_status,
            regression_count=regression_count,
            release_signal=release_signal,
            zero_tolerance_violation_count=zero_tolerance_violations,
            blockers=blockers,
            warnings=warnings,
            limitations=[
                "Deterministic repeated cases measure regression stability, not full stochastic LLM variance.",
                "Scientific pilots remain dataset-scoped and do not prove universal tool superiority.",
                "Automated UI and maintainer rehearsal do not substitute for real participant evidence.",
                "Native controlled execution is not an OS-level sandbox.",
                "This report augments hard safety gates; it cannot authorize execution or change release state.",
            ],
        )


def _build_metrics(payloads: dict[str, dict[str, Any]]) -> list[ContinuousMetric]:
    agent = _unwrap_summary(payloads["agent"])
    retrieval = payloads["retrieval"]
    system = payloads["system"]
    phase6 = payloads["phase6"]
    workflow = payloads["workflow"]
    portfolio = payloads["portfolio"]
    trial = payloads["trial"]
    batch_decision = payloads["batch_decision"]
    batch_manifest = payloads["batch_manifest"]
    dimensions = {
        row.get("dimension"): row for row in system.get("dimensions") or []
    }
    functional = (dimensions.get("functional_correctness") or {}).get("metrics") or {}
    safety = (dimensions.get("safety_and_isolation") or {}).get("metrics") or {}
    reproducibility = (dimensions.get("reproducibility") or {}).get("metrics") or {}
    performance = (dimensions.get("performance") or {}).get("metrics") or {}
    auditability = (dimensions.get("auditability") or {}).get("metrics") or {}
    kg_bm25 = ((retrieval.get("profiles") or {}).get("kg_bm25") or {})
    dense = ((retrieval.get("profiles") or {}).get("dense") or {})
    hybrid = ((retrieval.get("profiles") or {}).get("kg_hybrid_tool_contract") or {})
    b4 = ((phase6.get("baselines") or {}).get("B4_contract_bounded_repair") or {})
    b4_metrics = b4.get("metrics") or {}
    metrics: list[ContinuousMetric] = []

    def add(
        metric_id: str,
        display_name: str,
        category: EvaluationCategory,
        domain: BusinessDomain,
        stage: ArchitectureStage,
        lane: EvaluationLane,
        value: Any,
        *,
        source: str,
        sample_size: int | None = None,
        unit: str = "ratio",
        direction: MetricDirection | None = None,
        target: float | int | None = None,
        severity: MetricSeverity = MetricSeverity.DIAGNOSTIC,
        status: MetricStatus | None = None,
        tolerance: float = 0.0,
        limitations: Iterable[str] = (),
    ) -> None:
        resolved_status = status or (
            MetricStatus.MEASURED if value is not None else MetricStatus.NOT_RUN
        )
        signal = _signal(
            value=value,
            status=resolved_status,
            direction=direction,
            target=target,
            severity=severity,
        )
        metrics.append(
            ContinuousMetric(
                metric_id=metric_id,
                display_name=display_name,
                category=category,
                business_domain=domain,
                architecture_stage=stage,
                lane=lane,
                status=resolved_status,
                signal=signal,
                severity=severity,
                value=value,
                unit=unit,
                sample_size=sample_size,
                direction=direction,
                target_value=target,
                regression_tolerance=tolerance,
                source_artifact=source,
                limitations=list(limitations),
            )
        )

    agent_cases = _as_int(agent.get("case_count"))
    agent_runs = _as_int(agent.get("run_count"))
    add("effectiveness.task_completion_rate", "Task completion rate", EvaluationCategory.EFFECTIVENESS, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("task_completion_rate"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)
    add("effectiveness.task_routing_accuracy", "Task routing accuracy", EvaluationCategory.EFFECTIVENESS, BusinessDomain.WORKFLOW_PLANNING, ArchitectureStage.GATEWAY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("task_routing_accuracy"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)
    add("effectiveness.intent_accuracy", "Response intent accuracy", EvaluationCategory.EFFECTIVENESS, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("intent_accuracy"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)
    add("effectiveness.tool_correctness", "Tool selection correctness", EvaluationCategory.EFFECTIVENESS, BusinessDomain.WORKFLOW_PLANNING, ArchitectureStage.CONTRACT, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("tool_correctness"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)
    add("effectiveness.workflow_correctness", "Workflow response correctness", EvaluationCategory.EFFECTIVENESS, BusinessDomain.WORKFLOW_PLANNING, ArchitectureStage.PLANNER, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("workflow_correctness"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)
    add("effectiveness.blocker_correctness", "Blocking correctness", EvaluationCategory.EFFECTIVENESS, BusinessDomain.AUTHORIZATION_SAFETY, ArchitectureStage.ROUTER_APPROVAL, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("blocker_correctness"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE, tolerance=0.0)
    add("effectiveness.source_coverage_rate", "Answer source coverage", EvaluationCategory.EFFECTIVENESS, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("source_coverage_rate"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)

    retrieval_cases = _as_int(retrieval.get("case_count"))
    for suffix, label, value, target in (
        ("recall_at_10", "KG + BM25 Recall@10", kg_bm25.get("recall_at_10"), 0.90),
        ("precision_at_10", "KG + BM25 Precision@10", kg_bm25.get("precision_at_10"), 0.70),
        ("mrr", "KG + BM25 MRR", kg_bm25.get("mrr"), 0.75),
        ("source_span_hit_rate", "Source span hit rate", kg_bm25.get("source_span_hit_rate"), 0.85),
    ):
        add(f"effectiveness.retrieval_{suffix}", label, EvaluationCategory.EFFECTIVENESS, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, value, source="data/evaluation/retrieval_eval_v2/summary.json", sample_size=retrieval_cases, direction=MetricDirection.HIGHER_IS_BETTER, target=target, severity=MetricSeverity.RELEASE_GATE, tolerance=0.01)

    add("effectiveness.operational_scenario_pass_rate", "Operational scenario pass rate", EvaluationCategory.EFFECTIVENESS, BusinessDomain.DOUBLET_EXECUTION, ArchitectureStage.EXECUTOR, EvaluationLane.CONTROLLED_EXECUTION, functional.get("operational_scenario_pass_rate"), source="data/evaluation/system_quality_v1/summary.json", direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("effectiveness.data_profile_gate", "Registered-data profile gate", EvaluationCategory.EFFECTIVENESS, BusinessDomain.WORKFLOW_PLANNING, ArchitectureStage.DATA_PROFILE, EvaluationLane.CONTROLLED_EXECUTION, _command_passed(system, "authorization"), source="data/evaluation/system_quality_v1/summary.json", sample_size=1, unit="boolean", direction=MetricDirection.EXACT, target=1, severity=MetricSeverity.RELEASE_GATE, limitations=["Measured through the Phase 6 authorization smoke, not an open-ended user dataset corpus."])
    add("effectiveness.tool_invocation_success_rate", "Qualified tool invocation success", EvaluationCategory.EFFECTIVENESS, BusinessDomain.DOUBLET_EXECUTION, ArchitectureStage.EXECUTOR, EvaluationLane.CONTROLLED_EXECUTION, functional.get("tool_invocation_success_rate"), source="data/evaluation/system_quality_v1/summary.json", sample_size=_as_int(functional.get("actual_tool_runs")), direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("effectiveness.validation_pass_rate", "Validation pass rate", EvaluationCategory.EFFECTIVENESS, BusinessDomain.DOUBLET_EXECUTION, ArchitectureStage.VALIDATOR, EvaluationLane.CONTROLLED_EXECUTION, functional.get("validation_pass_rate"), source="data/evaluation/system_quality_v1/summary.json", direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("effectiveness.repair_success_rate", "Bounded repair success", EvaluationCategory.EFFECTIVENESS, BusinessDomain.BOUNDED_REPAIR, ArchitectureStage.REPAIR, EvaluationLane.CONTROLLED_EXECUTION, b4_metrics.get("repair_success") if b4.get("status") == "run" else None, source="eval/phase6/baseline_summary.json", sample_size=_as_int(b4.get("case_count")), direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("effectiveness.package_integrity_rate", "Reproducibility package integrity", EvaluationCategory.EFFECTIVENESS, BusinessDomain.REPRODUCIBILITY, ArchitectureStage.PACKAGER, EvaluationLane.CONTROLLED_EXECUTION, reproducibility.get("package_integrity_rate"), source="data/evaluation/system_quality_v1/summary.json", direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("effectiveness.candidate_decision_eligibility", "Candidate decision eligibility", EvaluationCategory.EFFECTIVENESS, BusinessDomain.DOUBLET_EXECUTION, ArchitectureStage.DECISION, EvaluationLane.CONTROLLED_EXECUTION, functional.get("candidate_eligibility_rate"), source="data/evaluation/system_quality_v1/summary.json", direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    batch_ready = (
        batch_decision.get("decision_scope") == "multitool_batch_integration"
        and bool(batch_decision.get("recommended_candidate_id"))
        and batch_manifest.get("task") == "batch_integration"
        and batch_manifest.get("reproducibility_level") == "Level 2"
    )
    add("effectiveness.batch_integration_pilot_ready", "Batch integration scientific-pilot decision", EvaluationCategory.EFFECTIVENESS, BusinessDomain.BATCH_INTEGRATION_EXECUTION, ArchitectureStage.DECISION, EvaluationLane.CONTROLLED_EXECUTION, int(batch_ready) if batch_decision and batch_manifest else None, source="phase5-batch-scientific/reproducibility_manifest.json", sample_size=1 if batch_decision else None, unit="boolean", direction=MetricDirection.EXACT, target=1, severity=MetricSeverity.RELEASE_GATE, limitations=["Dataset-scoped scIB pancreas pilot; not universal superiority evidence."])
    add("effectiveness.workflow_code_smoke", "Copy-ready workflow smoke", EvaluationCategory.EFFECTIVENESS, BusinessDomain.WORKFLOW_PLANNING, ArchitectureStage.VALIDATOR, EvaluationLane.CONTROLLED_EXECUTION, int(bool(workflow.get("smoke_passed"))) if workflow else None, source="data/evaluation/workflow_code_smoke_v1/summary.json", sample_size=1 if workflow else None, direction=MetricDirection.EXACT, target=1, severity=MetricSeverity.RELEASE_GATE)

    participant_count = _as_int(trial.get("participant_count"))
    human_status = MetricStatus.MEASURED if participant_count >= 3 else MetricStatus.NOT_RUN
    add("effectiveness.human_task_completion_rate", "Real-user task completion", EvaluationCategory.EFFECTIVENESS, BusinessDomain.USER_TRIAL, ArchitectureStage.UI_TELEMETRY, EvaluationLane.HUMAN_TRIAL, trial.get("level_1_completion_rate") if human_status == MetricStatus.MEASURED else None, source="Phase6TrialStore", sample_size=participant_count, direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, severity=MetricSeverity.RELEASE_GATE, status=human_status, limitations=["Automated tests and maintainer rehearsal do not count as participant evidence."])
    ragas_value = hybrid.get("ragas_faithfulness") if hybrid.get("ragas_status") == "completed" else None
    add("effectiveness.ragas_faithfulness", "RAGAS faithfulness diagnostic", EvaluationCategory.EFFECTIVENESS, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.EXTERNAL_LLM, ragas_value, source="data/evaluation/retrieval_eval_v2/summary.json", direction=MetricDirection.HIGHER_IS_BETTER, target=0.90, status=MetricStatus.MEASURED if ragas_value is not None else MetricStatus.NOT_RUN, limitations=["RAGAS is secondary diagnosis and cannot override ID-based or evidence-governance gates."])

    add("efficiency.agent_latency_p50_ms", "Agent latency p50", EvaluationCategory.EFFICIENCY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("latency_p50_ms"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, unit="ms", direction=MetricDirection.LOWER_IS_BETTER, target=750, severity=MetricSeverity.DIAGNOSTIC, tolerance=0.20)
    add("efficiency.agent_latency_p95_ms", "Agent latency p95", EvaluationCategory.EFFICIENCY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("latency_p95_ms"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, unit="ms", direction=MetricDirection.LOWER_IS_BETTER, target=1500, severity=MetricSeverity.RELEASE_GATE, tolerance=0.20)
    add("efficiency.retrieval_latency_p50_ms", "KG + BM25 latency p50", EvaluationCategory.EFFICIENCY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, kg_bm25.get("latency_p50_ms"), source="data/evaluation/retrieval_eval_v2/summary.json", sample_size=retrieval_cases, unit="ms", direction=MetricDirection.LOWER_IS_BETTER, target=100, severity=MetricSeverity.RELEASE_GATE, tolerance=0.20)
    add("efficiency.retrieval_latency_p95_ms", "KG + BM25 latency p95", EvaluationCategory.EFFICIENCY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, kg_bm25.get("latency_p95_ms"), source="data/evaluation/retrieval_eval_v2/summary.json", sample_size=retrieval_cases, unit="ms", direction=MetricDirection.LOWER_IS_BETTER, target=250, severity=MetricSeverity.RELEASE_GATE, tolerance=0.20)
    add("efficiency.execution_runtime_seconds", "Controlled execution runtime", EvaluationCategory.EFFICIENCY, BusinessDomain.DOUBLET_EXECUTION, ArchitectureStage.EXECUTOR, EvaluationLane.CONTROLLED_EXECUTION, performance.get("execution_runtime_seconds_mean_per_tool_smoke"), source="data/evaluation/system_quality_v1/summary.json", unit="seconds", direction=MetricDirection.LOWER_IS_BETTER, severity=MetricSeverity.DIAGNOSTIC, tolerance=0.25, limitations=["Local-machine synthetic-fixture measurement."])
    add("efficiency.execution_peak_memory_mb", "Controlled execution peak memory", EvaluationCategory.EFFICIENCY, BusinessDomain.DOUBLET_EXECUTION, ArchitectureStage.EXECUTOR, EvaluationLane.CONTROLLED_EXECUTION, performance.get("execution_peak_memory_mb_max"), source="data/evaluation/system_quality_v1/summary.json", unit="MiB", direction=MetricDirection.LOWER_IS_BETTER, severity=MetricSeverity.DIAGNOSTIC, tolerance=0.25, limitations=["Local-machine synthetic-fixture measurement."])
    add("efficiency.repair_run_count", "Bounded repair run count", EvaluationCategory.EFFICIENCY, BusinessDomain.BOUNDED_REPAIR, ArchitectureStage.REPAIR, EvaluationLane.CONTROLLED_EXECUTION, b4_metrics.get("run_count") if b4.get("status") == "run" else None, source="eval/phase6/baseline_summary.json", unit="runs", direction=MetricDirection.LOWER_IS_BETTER, target=6, severity=MetricSeverity.RELEASE_GATE)

    completed_calls = _as_int(portfolio.get("completed_model_calls"))
    portfolio_baselines = portfolio.get("baselines") or []
    input_tokens = sum(_as_int(row.get("input_tokens_total")) for row in portfolio_baselines)
    output_tokens = sum(_as_int(row.get("output_tokens_total")) for row in portfolio_baselines)
    add("efficiency.external_llm_token_usage", "Frozen portfolio LLM token usage", EvaluationCategory.EFFICIENCY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.EXTERNAL_LLM, input_tokens + output_tokens if completed_calls else None, source="portfolio-v2/benchmark_summary.json", sample_size=completed_calls, unit="tokens", direction=MetricDirection.LOWER_IS_BETTER, severity=MetricSeverity.DIAGNOSTIC, status=MetricStatus.MEASURED if completed_calls else MetricStatus.NOT_RUN, limitations=["No frozen provider price was available, so cost is not inferred."])
    add("efficiency.external_llm_estimated_cost_usd", "External LLM estimated cost", EvaluationCategory.EFFICIENCY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.EXTERNAL_LLM, None, source="portfolio-v2/benchmark_summary.json", unit="USD", direction=MetricDirection.LOWER_IS_BETTER, status=MetricStatus.NOT_RUN, limitations=["Provider price was not frozen at evaluation time; cost must not be fabricated."])

    add("stability.deterministic_outcome_stability", "Repeated deterministic outcome stability", EvaluationCategory.STABILITY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("stability_rate"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE, tolerance=0.0)
    add("stability.trace_completeness", "Agent trace completeness", EvaluationCategory.STABILITY, BusinessDomain.REPRODUCIBILITY, ArchitectureStage.UI_TELEMETRY, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("trace_completeness"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("stability.operational_trace_completeness", "Execution trace stage completeness", EvaluationCategory.STABILITY, BusinessDomain.REPRODUCIBILITY, ArchitectureStage.UI_TELEMETRY, EvaluationLane.CONTROLLED_EXECUTION, auditability.get("applicable_stage_completeness"), source="data/evaluation/system_quality_v1/summary.json", direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("stability.external_llm_repeat_variance", "External LLM repeat variance", EvaluationCategory.STABILITY, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.GATEWAY, EvaluationLane.EXTERNAL_LLM, None, source="not_run", unit="variance", direction=MetricDirection.LOWER_IS_BETTER, status=MetricStatus.NOT_RUN, limitations=["Portfolio baselines are not repeated stochastic samples of the same model configuration."])
    add("stability.human_task_variance", "Human task completion variance", EvaluationCategory.STABILITY, BusinessDomain.USER_TRIAL, ArchitectureStage.UI_TELEMETRY, EvaluationLane.HUMAN_TRIAL, None, source="Phase6TrialStore", unit="variance", direction=MetricDirection.LOWER_IS_BETTER, status=MetricStatus.NOT_RUN if participant_count < 3 else MetricStatus.INSUFFICIENT_DATA, limitations=["At least three real participants and per-task samples are required."])

    add("compliance.governance_violation_rate", "Governance violation rate", EvaluationCategory.COMPLIANCE, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("governance_violation_rate", agent.get("hallucination_rate")), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.LOWER_IS_BETTER, target=0.02, severity=MetricSeverity.RELEASE_GATE, tolerance=0.005, limitations=("This metric measures evidence/action governance violations, not scientific claim correctness.",))
    add("compliance.compliance_pass_rate", "Agent compliance pass rate", EvaluationCategory.COMPLIANCE, BusinessDomain.AUTHORIZATION_SAFETY, ArchitectureStage.ROUTER_APPROVAL, EvaluationLane.DETERMINISTIC_OFFLINE, agent.get("compliance_pass_rate"), source="data/evaluation/agent_quality_v2/summary.json", sample_size=agent_runs, direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("compliance.false_support_rate", "Retrieval false-support rate", EvaluationCategory.COMPLIANCE, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, kg_bm25.get("false_support_rate"), source="data/evaluation/retrieval_eval_v2/summary.json", sample_size=retrieval_cases, direction=MetricDirection.LOWER_IS_BETTER, target=0.02, severity=MetricSeverity.RELEASE_GATE, tolerance=0.005)
    add("compliance.parameter_legality_rate", "Parameter legality", EvaluationCategory.COMPLIANCE, BusinessDomain.WORKFLOW_PLANNING, ArchitectureStage.CONTRACT, EvaluationLane.DETERMINISTIC_OFFLINE, kg_bm25.get("parameter_legality_rate"), source="data/evaluation/retrieval_eval_v2/summary.json", sample_size=retrieval_cases, direction=MetricDirection.HIGHER_IS_BETTER, target=1.0, severity=MetricSeverity.RELEASE_GATE)
    add("compliance.governance_leakage_count", "Candidate/evidence governance leakage", EvaluationCategory.COMPLIANCE, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, kg_bm25.get("governance_leakage_count"), source="data/evaluation/retrieval_eval_v2/summary.json", sample_size=retrieval_cases, unit="violations", direction=MetricDirection.EXACT, target=0, severity=MetricSeverity.ZERO_TOLERANCE)
    for metric_id, label, key, stage in (
        ("compliance.unauthorized_execution_count", "Unauthorized execution", "unauthorized_execution_count", ArchitectureStage.ROUTER_APPROVAL),
        ("compliance.path_escape_count", "Path escape", "path_escape_count", ArchitectureStage.EXECUTOR),
        ("compliance.approval_replay_violation_count", "Approval replay violation", "approval_replay_violation_count", ArchitectureStage.ROUTER_APPROVAL),
        ("compliance.cross_user_access_violation_count", "Cross-user access violation", "cross_user_access_violation_count", ArchitectureStage.ROUTER_APPROVAL),
        ("compliance.untrusted_code_execution_count", "Untrusted generated code execution", "untrusted_generated_code_execution_count", ArchitectureStage.EXECUTOR),
    ):
        add(metric_id, label, EvaluationCategory.COMPLIANCE, BusinessDomain.AUTHORIZATION_SAFETY, stage, EvaluationLane.CONTROLLED_EXECUTION, safety.get(key), source="data/evaluation/system_quality_v1/summary.json", unit="violations", direction=MetricDirection.EXACT, target=0, severity=MetricSeverity.ZERO_TOLERANCE)
    trace_violations = _trace_violations(system)
    add("compliance.repair_budget_violation_count", "Repair budget violation", EvaluationCategory.COMPLIANCE, BusinessDomain.BOUNDED_REPAIR, ArchitectureStage.REPAIR, EvaluationLane.CONTROLLED_EXECUTION, trace_violations.get("repair_budget_violation"), source="data/evaluation/system_quality_v1/summary.json", unit="violations", direction=MetricDirection.EXACT, target=0, severity=MetricSeverity.ZERO_TOLERANCE)
    add("compliance.evidence_boundary_violation_count", "Evidence boundary violation", EvaluationCategory.COMPLIANCE, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.CONTRACT, EvaluationLane.CONTROLLED_EXECUTION, trace_violations.get("evidence_boundary_violation"), source="data/evaluation/system_quality_v1/summary.json", unit="violations", direction=MetricDirection.EXACT, target=0, severity=MetricSeverity.ZERO_TOLERANCE)
    add("compliance.os_level_isolation", "OS-level execution isolation", EvaluationCategory.COMPLIANCE, BusinessDomain.AUTHORIZATION_SAFETY, ArchitectureStage.EXECUTOR, EvaluationLane.CONTROLLED_EXECUTION, None, source="docs/security/EXECUTION_SECURITY_MODEL.md", unit="boolean", direction=MetricDirection.EXACT, target=1, severity=MetricSeverity.RELEASE_GATE, status=MetricStatus.NOT_RUN, limitations=["Native Trusted Runner is application-controlled but network_not_os_isolated."])
    add("compliance.real_user_incorrect_claim_count", "User-reported incorrect claims", EvaluationCategory.COMPLIANCE, BusinessDomain.USER_TRIAL, ArchitectureStage.UI_TELEMETRY, EvaluationLane.HUMAN_TRIAL, trial.get("incorrect_claim_count") if participant_count else None, source="Phase6TrialStore", sample_size=participant_count, unit="reports", direction=MetricDirection.EXACT, target=0, severity=MetricSeverity.RELEASE_GATE, status=MetricStatus.MEASURED if participant_count else MetricStatus.NOT_RUN)
    hybrid_route_ready = (
        hybrid.get("status") == "passed"
        and bool((retrieval.get("route_decision") or {}).get("dense_default_enabled"))
    )
    add("effectiveness.dense_retrieval_gate", "Governed local hybrid retrieval gate", EvaluationCategory.EFFECTIVENESS, BusinessDomain.KNOWLEDGE_QA, ArchitectureStage.RETRIEVAL, EvaluationLane.DETERMINISTIC_OFFLINE, int(hybrid_route_ready) if hybrid else None, source="data/evaluation/retrieval_eval_v2/summary.json", unit="boolean", direction=MetricDirection.EXACT, target=1, status=MetricStatus.MEASURED if hybrid else MetricStatus.NOT_RUN, limitations=list(hybrid.get("failures") or []))
    return metrics


def write_report(
    report: ContinuousAgentEvaluationReport,
    *,
    output_dir: Path,
    history_path: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    _write_json(output_dir / "latest.json", payload)
    _write_json(output_dir / "summary.json", _compact_summary(report))
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    history = history_path or output_dir / "history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_history_row(report), ensure_ascii=False, sort_keys=True) + "\n")


def freeze_baseline(
    report: ContinuousAgentEvaluationReport,
    *,
    baseline_path: Path,
) -> None:
    if baseline_path.exists():
        raise FileExistsError(f"continuous evaluation baseline already exists: {baseline_path.name}")
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(baseline_path, report.model_dump(mode="json"))


def _signal(
    *,
    value: Any,
    status: MetricStatus,
    direction: MetricDirection | None,
    target: float | int | None,
    severity: MetricSeverity,
) -> MetricSignal:
    if status != MetricStatus.MEASURED:
        return MetricSignal.UNKNOWN
    if direction is None or target is None or not isinstance(value, (int, float, bool)):
        return MetricSignal.HEALTHY
    numeric = float(value)
    passed = (
        numeric >= float(target)
        if direction == MetricDirection.HIGHER_IS_BETTER
        else numeric <= float(target)
        if direction == MetricDirection.LOWER_IS_BETTER
        else numeric == float(target)
    )
    if passed:
        return MetricSignal.HEALTHY
    return (
        MetricSignal.BLOCKED
        if severity == MetricSeverity.ZERO_TOLERANCE
        else MetricSignal.WATCH
    )


def _summarize_categories(metrics: list[ContinuousMetric]) -> list[CategorySummary]:
    rows: list[CategorySummary] = []
    for category in EvaluationCategory:
        selected = [metric for metric in metrics if metric.category == category]
        signals = {metric.signal for metric in selected}
        unmeasured_release_metrics = any(
            metric.status != MetricStatus.MEASURED
            and metric.severity
            in {MetricSeverity.RELEASE_GATE, MetricSeverity.ZERO_TOLERANCE}
            for metric in selected
        )
        if MetricSignal.BLOCKED in signals:
            signal = MetricSignal.BLOCKED
        elif MetricSignal.WATCH in signals or unmeasured_release_metrics:
            signal = MetricSignal.WATCH
        elif not any(metric.status == MetricStatus.MEASURED for metric in selected):
            signal = MetricSignal.UNKNOWN
        else:
            signal = MetricSignal.HEALTHY
        rows.append(
            CategorySummary(
                category=category,
                signal=signal,
                measured=sum(metric.status == MetricStatus.MEASURED for metric in selected),
                not_run=sum(metric.status == MetricStatus.NOT_RUN for metric in selected),
                insufficient_data=sum(metric.status == MetricStatus.INSUFFICIENT_DATA for metric in selected),
                blocked=sum(metric.signal == MetricSignal.BLOCKED for metric in selected),
                watch=sum(metric.signal == MetricSignal.WATCH for metric in selected),
            )
        )
    return rows


def _summarize_domains(metrics: list[ContinuousMetric]) -> list[BusinessDomainSummary]:
    rows: list[BusinessDomainSummary] = []
    for domain in BusinessDomain:
        selected = [metric for metric in metrics if metric.business_domain == domain]
        measured = [metric for metric in selected if metric.status == MetricStatus.MEASURED]
        release = [
            metric
            for metric in selected
            if metric.severity
            in {MetricSeverity.RELEASE_GATE, MetricSeverity.ZERO_TOLERANCE}
        ]
        unknown_release = [
            metric.metric_id
            for metric in release
            if metric.status != MetricStatus.MEASURED
        ]
        blocked = [
            metric.metric_id
            for metric in selected
            if metric.signal == MetricSignal.BLOCKED
        ]
        watch = [
            metric.metric_id
            for metric in selected
            if metric.signal == MetricSignal.WATCH
        ]
        if blocked:
            signal = MetricSignal.BLOCKED
        elif watch or unknown_release:
            signal = MetricSignal.WATCH
        elif measured:
            signal = MetricSignal.HEALTHY
        else:
            signal = MetricSignal.UNKNOWN
        rows.append(
            BusinessDomainSummary(
                business_domain=domain,
                signal=signal,
                measured_metric_count=len(measured),
                total_metric_count=len(selected),
                release_metric_coverage=sum(
                    metric.status == MetricStatus.MEASURED for metric in release
                )
                / max(1, len(release)),
                watch_metrics=watch,
                blocked_metrics=blocked,
                unknown_release_metrics=unknown_release,
            )
        )
    return rows


def _failure_clusters(payloads: dict[str, dict[str, Any]]) -> list[FailureCluster]:
    agent = _unwrap_summary(payloads.get("agent") or {})
    system = payloads.get("system") or {}
    counts: dict[str, int] = {}
    for source in (
        agent.get("failure_domain_counts") or {},
        system.get("failure_attribution") or {},
    ):
        for owner, count in source.items():
            counts[str(owner)] = counts.get(str(owner), 0) + _as_int(count)
    recommendations = {
        "answer_router": "Expand paraphrase and multi-turn intent cases, then fix deterministic intent precedence.",
        "retrieval": "Inspect failed gold spans, ontology normalization, BM25 ranking, and governance rerank.",
        "planner": "Repair workflow schema, parameter provenance, and I/O precondition handling.",
        "executor": "Inspect wrapper, environment, timeout, and artifact lineage without relaxing gates.",
        "validator": "Add the missing invariant or correct artifact interpretation.",
        "repair_policy": "Adjust only deterministic allowlisted repair rules and budgets.",
        "ui": "Correct presentation or navigation without duplicating backend logic.",
    }
    return [
        FailureCluster(
            owner=owner,
            failure_count=count,
            source="agent_quality_and_system_quality",
            recommended_action=recommendations.get(
                owner,
                "Inspect the owning stage artifact and add a focused regression case before changing behavior.",
            ),
        )
        for owner, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 0
    ]


def _optimization_priorities(
    metrics: list[ContinuousMetric], *, regression_status: str
) -> list[OptimizationPriority]:
    priorities: list[OptimizationPriority] = []
    blocked = [metric.metric_id for metric in metrics if metric.signal == MetricSignal.BLOCKED]
    if blocked:
        priorities.append(
            OptimizationPriority(
                priority="P0",
                capability_domain="safety_and_compliance",
                owner="security_and_execution",
                reason=f"Zero-tolerance violations: {', '.join(blocked)}",
                recommended_action="Block release, preserve traces, and repair the violated gate before any feature work.",
            )
        )
    if _metric(metrics, "effectiveness.human_task_completion_rate").status != MetricStatus.MEASURED:
        priorities.append(
            OptimizationPriority(
                priority="P1",
                capability_domain="real_user_usability",
                owner="product_validation",
                reason="No qualifying 3-5 participant trial evidence is available.",
                recommended_action="Run the frozen Level 1 task bank and supervised Level 2 synthetic execution; do not substitute automated rehearsal.",
            )
        )
    if _metric(metrics, "stability.external_llm_repeat_variance").status != MetricStatus.MEASURED:
        priorities.append(
            OptimizationPriority(
                priority="P1",
                capability_domain="stochastic_agent_stability",
                owner="agent_evaluation",
                reason="Repeated stochastic sampling for the configured external model has not been run.",
                recommended_action="After explicit disclosure authorization, repeat a frozen paraphrase set across seeds and report variance and confidence intervals.",
            )
        )
    if regression_status != "compared":
        priorities.append(
            OptimizationPriority(
                priority="P1",
                capability_domain="change_risk",
                owner="release_engineering",
                reason="No frozen continuous-evaluation baseline is being compared.",
                recommended_action="Freeze the current latest.json as the release-candidate baseline and compare every subsequent change.",
            )
        )
    if _metric(metrics, "effectiveness.dense_retrieval_gate").status != MetricStatus.MEASURED:
        priorities.append(
            OptimizationPriority(
                priority="P2",
                capability_domain="hybrid_retrieval",
                owner="knowledge_retrieval",
                reason="Dense and hybrid retrieval ablations are not available.",
                recommended_action="Build the local bge-m3 vector index and run the same 96-case ID-based benchmark before enabling hybrid claims.",
            )
        )
    if _metric(metrics, "compliance.os_level_isolation").status != MetricStatus.MEASURED:
        priorities.append(
            OptimizationPriority(
                priority="P2",
                capability_domain="execution_isolation",
                owner="security_and_runtime",
                reason="Native execution remains network_not_os_isolated.",
                recommended_action="Keep arbitrary generated code disabled; qualify a container backend before claiming OS-level isolation.",
            )
        )
    return priorities


def _coverage(metrics: list[ContinuousMetric]) -> EvaluationCoverage:
    measured = [metric for metric in metrics if metric.status == MetricStatus.MEASURED]
    release = [
        metric
        for metric in metrics
        if metric.severity in {MetricSeverity.RELEASE_GATE, MetricSeverity.ZERO_TOLERANCE}
    ]
    domains = {metric.business_domain for metric in measured}
    stages = {metric.architecture_stage for metric in measured}
    lane_status: dict[str, MetricStatus] = {}
    for lane in EvaluationLane:
        selected = [metric for metric in metrics if metric.lane == lane]
        measured_count = sum(metric.status == MetricStatus.MEASURED for metric in selected)
        if measured_count == len(selected) and selected:
            lane_status[lane.value] = MetricStatus.MEASURED
        elif measured_count:
            lane_status[lane.value] = MetricStatus.INSUFFICIENT_DATA
        else:
            lane_status[lane.value] = MetricStatus.NOT_RUN
    return EvaluationCoverage(
        measured_metric_count=len(measured),
        total_metric_count=len(metrics),
        release_metric_count=len(release),
        measured_release_metric_count=sum(
            metric.status == MetricStatus.MEASURED for metric in release
        ),
        covered_business_domains=sorted(domains, key=str),
        uncovered_business_domains=sorted(set(BusinessDomain) - domains, key=str),
        covered_architecture_stages=sorted(stages, key=str),
        uncovered_architecture_stages=sorted(set(ArchitectureStage) - stages, key=str),
        lane_status=lane_status,
    )


def _compare_metrics(
    metrics: list[ContinuousMetric], baseline_path: Path | None
) -> tuple[list[MetricTrend], str]:
    if baseline_path is None:
        return [], "baseline_not_provided"
    baseline = _read_json(baseline_path)
    baseline_metrics = {
        row.get("metric_id"): row for row in baseline.get("metrics") or []
    }
    if not baseline_metrics:
        return [], "baseline_invalid"
    trends: list[MetricTrend] = []
    for metric in metrics:
        previous = baseline_metrics.get(metric.metric_id) or {}
        old = previous.get("value")
        current = metric.value
        if (
            metric.status != MetricStatus.MEASURED
            or not isinstance(current, (int, float, bool))
            or not isinstance(old, (int, float, bool))
            or metric.direction is None
        ):
            trends.append(
                MetricTrend(
                    metric_id=metric.metric_id,
                    status="not_comparable",
                    reason="metric missing, unmeasured, or non-numeric",
                )
            )
            continue
        delta = float(current) - float(old)
        tolerance = _absolute_tolerance(float(old), metric.regression_tolerance)
        regressed = (
            delta < -tolerance
            if metric.direction == MetricDirection.HIGHER_IS_BETTER
            else delta > tolerance
            if metric.direction == MetricDirection.LOWER_IS_BETTER
            else float(current) != float(old) and metric.severity == MetricSeverity.ZERO_TOLERANCE
        )
        trends.append(
            MetricTrend(
                metric_id=metric.metric_id,
                status="compared",
                baseline_value=old,
                current_value=current,
                delta=round(delta, 9),
                regressed=regressed,
            )
        )
    return trends, "compared"


def _absolute_tolerance(baseline: float, configured: float) -> float:
    if configured <= 0:
        return 0.0
    return max(configured, abs(baseline) * configured)


def _compact_summary(report: ContinuousAgentEvaluationReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "evaluation_id": report.evaluation_id,
        "generated_at": report.generated_at.isoformat(),
        "release_signal": report.release_signal,
        "zero_tolerance_violation_count": report.zero_tolerance_violation_count,
        "regression_status": report.regression_status,
        "regression_count": report.regression_count,
        "coverage": report.coverage.model_dump(mode="json"),
        "category_signals": {
            row.category: row.signal for row in report.category_summaries
        },
        "business_domain_signals": {
            row.business_domain: row.signal
            for row in report.business_domain_summaries
        },
        "optimization_priorities": [
            item.model_dump(mode="json") for item in report.optimization_priorities
        ],
        "blockers": report.blockers,
        "warnings": report.warnings,
    }


def _history_row(report: ContinuousAgentEvaluationReport) -> dict[str, Any]:
    selected = {
        metric.metric_id: metric.value
        for metric in report.metrics
        if metric.status == MetricStatus.MEASURED
        and metric.severity != MetricSeverity.DIAGNOSTIC
    }
    return {
        "evaluation_id": report.evaluation_id,
        "generated_at": report.generated_at.isoformat(),
        "release_signal": report.release_signal,
        "zero_tolerance_violation_count": report.zero_tolerance_violation_count,
        "regression_count": report.regression_count,
        "metrics": selected,
    }


def _markdown(report: ContinuousAgentEvaluationReport) -> str:
    lines = [
        "# scKG-Agent Continuous Quality Report",
        "",
        f"- Evaluation: `{report.evaluation_id}`",
        f"- Release signal: `{report.release_signal}`",
        f"- Measured metrics: `{report.coverage.measured_metric_count}/{report.coverage.total_metric_count}`",
        f"- Zero-tolerance violations: `{report.zero_tolerance_violation_count}`",
        f"- Regression status: `{report.regression_status}`",
        "",
        "## Category scorecard",
        "",
        "| Category | Signal | Measured | Not run | Insufficient | Watch | Blocked |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.category_summaries:
        lines.append(
            f"| {row.category} | {row.signal} | {row.measured} | {row.not_run} | {row.insufficient_data} | {row.watch} | {row.blocked} |"
        )
    lines.extend(
        [
            "",
            "## Business capability waterline",
            "",
            "| Domain | Signal | Measured | Total | Release coverage |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for row in report.business_domain_summaries:
        lines.append(
            f"| {row.business_domain} | {row.signal} | {row.measured_metric_count} | {row.total_metric_count} | {row.release_metric_coverage:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Metric | Domain | Stage | Lane | Status | Value | Signal |",
            "|---|---|---|---|---|---:|---|",
        ]
    )
    for metric in report.metrics:
        lines.append(
            f"| `{metric.metric_id}` | {metric.business_domain} | {metric.architecture_stage} | {metric.lane} | {metric.status} | {metric.value if metric.value is not None else '-'} | {metric.signal} |"
        )
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in report.warnings)
    if report.optimization_priorities:
        lines.extend(["", "## Optimization priorities", ""])
        lines.extend(
            f"- **{item.priority} / {item.owner} / {item.capability_domain}**: {item.reason} {item.recommended_action}"
            for item in report.optimization_priorities
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines) + "\n"


def _trace_violations(system: dict[str, Any]) -> dict[str, int | None]:
    dimensions = {
        row.get("dimension"): row for row in system.get("dimensions") or []
    }
    audit_checks = (dimensions.get("auditability") or {}).get("checks") or {}
    knowledge_checks = (dimensions.get("knowledge_quality") or {}).get("checks") or {}
    values = {
        "repair_budget_violation": 0
        if audit_checks.get("repair_budget_respected") is True
        else 1
        if audit_checks.get("repair_budget_respected") is False
        else None,
        "evidence_boundary_violation": 0
        if knowledge_checks.get("knowledge_governance_leakage_zero") is True
        else 1
        if knowledge_checks.get("knowledge_governance_leakage_zero") is False
        else None,
    }
    for scenario in system.get("scenarios") or []:
        source = str(scenario.get("source") or "")
        if "repair_budget_violation" in source:
            values["repair_budget_violation"] = int(not scenario.get("passed"))
        if "evidence_boundary_violation" in source:
            values["evidence_boundary_violation"] = int(not scenario.get("passed"))
    for warning in system.get("warnings") or []:
        if warning in values:
            values[warning] = int(values[warning] or 0) + 1
    return values


def _metric(metrics: list[ContinuousMetric], metric_id: str) -> ContinuousMetric:
    return next(metric for metric in metrics if metric.metric_id == metric_id)


def _command_passed(system: dict[str, Any], command_id: str) -> int | None:
    for row in system.get("command_results") or []:
        if row.get("command_id") == command_id:
            return int(row.get("status") == "passed" and row.get("exit_code") == 0)
    return None


def _unwrap_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else payload


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
