from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Sequence

from core.settings import PROJECT_ROOT
from core.system_evaluation_models import (
    EvaluationCommandResult,
    EvaluationScenarioResult,
    QualityDimensionResult,
    SystemQualityReport,
)


DEFAULT_STABLE_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "system_quality_v1"
DEFAULT_PORTFOLIO_SUMMARY = (
    PROJECT_ROOT
    / ".sckg_exec"
    / "evaluations"
    / "portfolio-v2-full-20260717"
    / "benchmark_summary.json"
)
_ABSOLUTE_PATH = re.compile(
    r"(?:(?:/Users|/home|/private|/var|/tmp)/[^\s,;\]\[\}\{\"']+|[A-Za-z]:\\[^\s,;\]\[\}\{\"']+)"
)


@dataclass(frozen=True)
class EvaluationCommandSpec:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int = 420


@dataclass
class CommandObservation:
    result: EvaluationCommandResult
    payload: dict[str, Any]


CommandRunner = Callable[[EvaluationCommandSpec], CommandObservation]


class SystemQualityEvaluator:
    """Aggregate existing scKG gates without copying execution or safety logic."""

    def __init__(
        self,
        *,
        output_root: Path,
        stable_output: Path = DEFAULT_STABLE_OUTPUT,
        command_runner: CommandRunner | None = None,
        baseline_path: Path | None = None,
        resume: bool = False,
    ) -> None:
        self.output_root = Path(output_root)
        self.stable_output = Path(stable_output)
        self.command_runner = command_runner or self._run_command
        self.baseline_path = Path(baseline_path) if baseline_path else None
        self.resume = resume

    def run(self) -> SystemQualityReport:
        self.output_root.mkdir(parents=True, exist_ok=True)
        payloads: dict[str, dict[str, Any]] = {}
        command_results: list[EvaluationCommandResult] = []
        previous_results = self._previous_command_results() if self.resume else {}
        for spec in self.command_specs():
            input_path = self.output_root / "inputs" / f"{spec.command_id}.json"
            previous = previous_results.get(spec.command_id)
            if previous is not None and previous.status == "passed" and input_path.is_file():
                observation = CommandObservation(
                    result=previous,
                    payload=_read_json(input_path),
                )
            else:
                observation = self.command_runner(spec)
            command_results.append(observation.result)
            payloads[spec.command_id] = observation.payload
            self._write_json(
                self.output_root / "inputs" / f"{spec.command_id}.json",
                _sanitize(observation.payload),
            )
        payloads["portfolio"] = _read_json(DEFAULT_PORTFOLIO_SUMMARY)
        payloads["defense_details"] = _load_defense_details(
            payloads.get("defense_demo") or {}
        )
        payloads["baseline_details"] = _load_baseline_details()
        report = build_system_quality_report(
            evaluation_id=self.output_root.name,
            payloads=payloads,
            command_results=command_results,
            baseline_path=self.baseline_path,
        )
        self._write_outputs(report)
        return report

    def _previous_command_results(self) -> dict[str, EvaluationCommandResult]:
        previous = _read_json(self.output_root / "summary.json")
        results: dict[str, EvaluationCommandResult] = {}
        for payload in previous.get("command_results") or []:
            try:
                result = EvaluationCommandResult.model_validate(payload)
            except (TypeError, ValueError):
                continue
            results[result.command_id] = result
        return results

    def command_specs(self) -> tuple[EvaluationCommandSpec, ...]:
        py = sys.executable
        return (
            EvaluationCommandSpec(
                "agent_quality",
                (
                    py,
                    "eval/run_agent_quality_evaluation.py",
                    "--output",
                    str(self.output_root / "agent_quality"),
                    "--repetitions",
                    "3",
                ),
            ),
            EvaluationCommandSpec(
                "retrieval_quality",
                (
                    py,
                    "eval/run_retrieval_evaluation_v2.py",
                    "--output",
                    str(self.output_root / "retrieval_quality"),
                ),
            ),
            EvaluationCommandSpec(
                "phase6_baselines", (py, "eval/run_phase6_baselines.py")
            ),
            EvaluationCommandSpec(
                "authorization", (py, "scripts/run_phase6a_authorization_smoke.py")
            ),
            EvaluationCommandSpec(
                "restricted_execution",
                (py, "scripts/run_phase6b_restricted_execution_smoke.py"),
            ),
            EvaluationCommandSpec(
                "ui_service", (py, "scripts/run_phase6c_ui_service_smoke.py")
            ),
            EvaluationCommandSpec(
                "defense_demo", (py, "scripts/run_phase6_defense_demo.py")
            ),
            EvaluationCommandSpec(
                "group_trial",
                (
                    py,
                    "scripts/summarize_phase6_group_trial.py",
                    "--output-dir",
                    str(self.output_root / "group_trial"),
                ),
            ),
        )

    def _run_command(self, spec: EvaluationCommandSpec) -> CommandObservation:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(spec.argv),
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                check=False,
            )
            payload = _last_json_object(completed.stdout)
            status = "passed" if completed.returncode == 0 else "failed"
            error = "" if status == "passed" else _sanitize_text(completed.stderr[-1200:])
            digest = _digest(payload) if payload else None
            return CommandObservation(
                result=EvaluationCommandResult(
                    command_id=spec.command_id,
                    status=status,
                    exit_code=completed.returncode,
                    runtime_seconds=round(time.monotonic() - started, 6),
                    payload_digest=digest,
                    error_summary=error,
                ),
                payload=payload,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandObservation(
                result=EvaluationCommandResult(
                    command_id=spec.command_id,
                    status="failed",
                    exit_code=None,
                    runtime_seconds=round(time.monotonic() - started, 6),
                    error_summary=f"timeout_after_{spec.timeout_seconds}s:{type(exc).__name__}",
                ),
                payload={},
            )

    def _write_outputs(self, report: SystemQualityReport) -> None:
        payload = report.model_dump(mode="json")
        for root in (self.output_root, self.stable_output):
            self._write_json(root / "summary.json", payload)
            self._write_jsonl(
                root / "scenarios.jsonl",
                [item.model_dump(mode="json") for item in report.scenarios],
            )
            self._write_jsonl(root / "failure_queue.jsonl", _failure_rows(report))
            (root / "report.md").write_text(_markdown_report(report), encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )


def build_system_quality_report(
    *,
    evaluation_id: str,
    payloads: dict[str, dict[str, Any]],
    command_results: list[EvaluationCommandResult],
    baseline_path: Path | None = None,
) -> SystemQualityReport:
    agent = (payloads.get("agent_quality") or {}).get("summary") or {}
    retrieval = payloads.get("retrieval_quality") or {}
    kg_bm25 = (retrieval.get("profiles") or {}).get("kg_bm25") or {}
    baselines = payloads.get("phase6_baselines") or {}
    baseline_details = payloads.get("baseline_details") or {}
    auth = payloads.get("authorization") or {}
    execution = payloads.get("restricted_execution") or {}
    ui = payloads.get("ui_service") or {}
    defense = payloads.get("defense_demo") or {}
    defense_details = payloads.get("defense_details") or {}
    trace = defense_details.get("trace_audit") or {}
    trial = payloads.get("group_trial") or {}
    portfolio = payloads.get("portfolio") or {}

    scenarios = _scenario_results(defense, defense_details, execution)
    scenario_rate = sum(item.passed for item in scenarios) / max(1, len(scenarios))
    tool_rows = [execution.get("scrublet") or {}, execution.get("scdblfinder") or {}]
    actual_runs = sum(int(row.get("actual_runs") or 0) for row in tool_rows)
    successful_runs = sum(int(row.get("successful_runs") or 0) for row in tool_rows)
    candidate_count = sum(int(row.get("candidate_evaluation_count") or 0) for row in tool_rows)
    eligible_count = sum(int(row.get("eligible_candidate_count") or 0) for row in tool_rows)
    validations_passed = all(bool(row.get("validation_passed")) for row in tool_rows)
    functional_checks = {
        "agent_release_gate": bool(agent.get("release_gate_passed")),
        "all_six_operational_outcomes_correct": scenario_rate == 1.0,
        "tool_runs_succeeded": actual_runs > 0 and actual_runs == successful_runs,
        "validators_passed": validations_passed,
        "candidate_evaluations_eligible": candidate_count > 0
        and candidate_count == eligible_count,
    }
    functional = QualityDimensionResult(
        dimension="functional_correctness",
        status=_status(functional_checks),
        metrics={
            "agent_task_completion_rate": agent.get("task_completion_rate"),
            "agent_tool_correctness": agent.get("tool_correctness"),
            "operational_scenario_pass_rate": scenario_rate,
            "tool_invocation_success_rate": successful_runs / max(1, actual_runs),
            "validation_pass_rate": 1.0 if validations_passed else 0.0,
            "candidate_eligibility_rate": eligible_count / max(1, candidate_count),
            "actual_tool_runs": actual_runs,
        },
        checks=functional_checks,
        evidence_sources=[
            "agent_quality/summary.json",
            "restricted_execution smoke",
            "defense demo",
        ],
    )

    violations = trace.get("violations") or {
        key: trace.get(key, 0)
        for key in (
            "unauthorized_execution",
            "path_escape",
            "repair_budget_violation",
            "evidence_boundary_violation",
        )
    }
    auth_checks = auth.get("checks") or {}
    exec_checks = execution.get("checks") or {}
    baseline_safety = baselines.get("safety") or {}
    safety_checks = {
        "unauthorized_execution_zero": int(violations.get("unauthorized_execution") or 0)
        == 0,
        "path_escape_zero": int(violations.get("path_escape") or 0) == 0,
        "approval_replay_blocked": bool(exec_checks.get("approval_replay_blocked")),
        "parameter_change_blocked": bool(
            exec_checks.get("parameter_change_blocked")
            or auth_checks.get("parameter_change_invalidates_approval")
        ),
        "cross_user_access_blocked": bool(
            exec_checks.get("cross_user_package_blocked")
            and auth_checks.get("cross_user_artifact_blocked")
            and auth_checks.get("cross_user_run_blocked")
        ),
        "default_policy_disabled": bool(
            exec_checks.get("global_policy_default_disabled")
            or exec_checks.get("global_default_policy_disabled")
        ),
        "untrusted_generated_code_execution_zero": int(
            baseline_safety.get("new_or_untrusted_generated_code_executions") or 0
        )
        == 0,
        "authorization_prevents_execution_request": bool(
            auth_checks.get("execution_request_count_zero")
        ),
    }
    safety = QualityDimensionResult(
        dimension="safety_and_isolation",
        status=_status(safety_checks),
        metrics={
            "unauthorized_execution_count": int(
                violations.get("unauthorized_execution") or 0
            ),
            "path_escape_count": int(violations.get("path_escape") or 0),
            "approval_replay_violation_count": 0
            if safety_checks["approval_replay_blocked"]
            else 1,
            "cross_user_access_violation_count": 0
            if safety_checks["cross_user_access_blocked"]
            else 1,
            "untrusted_generated_code_execution_count": int(
                baseline_safety.get("new_or_untrusted_generated_code_executions") or 0
            ),
        },
        checks=safety_checks,
        warnings=["native_runner_network_not_os_isolated"],
        evidence_sources=["authorization smoke", "restricted execution smoke", "trace audit"],
    )

    knowledge_checks = {
        "kg_bm25_gate_passed": kg_bm25.get("status") == "passed",
        "knowledge_governance_leakage_zero": int(
            kg_bm25.get("governance_leakage_count") or 0
        )
        == 0,
        "false_support_within_gate": float(kg_bm25.get("false_support_rate") or 0.0)
        <= 0.02,
        "parameter_legality_full": kg_bm25.get("parameter_legality_rate") == 1.0,
        "agent_hallucination_gate": float(agent.get("hallucination_rate") or 0.0) == 0.0,
    }
    knowledge = QualityDimensionResult(
        dimension="knowledge_quality",
        status=_status(knowledge_checks),
        metrics={
            "retrieval_case_count": retrieval.get("case_count"),
            "recall_at_10": kg_bm25.get("recall_at_10"),
            "precision_at_10": kg_bm25.get("precision_at_10"),
            "mrr": kg_bm25.get("mrr"),
            "source_span_hit_rate": kg_bm25.get("source_span_hit_rate"),
            "false_support_rate": kg_bm25.get("false_support_rate"),
            "knowledge_governance_leakage_count": kg_bm25.get(
                "governance_leakage_count"
            ),
            "ragas_status": kg_bm25.get("ragas_status", "not_run"),
        },
        checks=knowledge_checks,
        warnings=[
            "dense_and_hybrid_profiles_not_run"
            if any(
                (retrieval.get("profiles") or {}).get(name, {}).get("status") == "not_run"
                for name in ("dense", "kg_hybrid", "kg_hybrid_tool_contract")
            )
            else ""
        ],
        evidence_sources=["retrieval_quality/summary.json", "agent quality gate"],
    )
    knowledge.warnings = [item for item in knowledge.warnings if item]

    ui_checks = ui.get("checks") or {}
    participant_count = int(trial.get("participant_count") or 0)
    usability_checks = {
        "ui_service_smoke_passed": bool(ui.get("ok")),
        "page_redaction_passed": bool(ui_checks.get("redaction")),
        "real_level_1_trial_complete": int(trial.get("level_1_participant_count") or 0)
        >= 3,
        "real_level_2_trial_complete": int(trial.get("level_2_participant_count") or 0)
        >= 1,
    }
    human_trial_complete = all(
        usability_checks[key]
        for key in ("real_level_1_trial_complete", "real_level_2_trial_complete")
    )
    usability = QualityDimensionResult(
        dimension="usability",
        status=(
            "passed"
            if all(usability_checks.values())
            else "partial"
            if usability_checks["ui_service_smoke_passed"]
            else "failed"
        ),
        metrics={
            "participant_count": participant_count,
            "level_1_participant_count": int(trial.get("level_1_participant_count") or 0),
            "level_2_participant_count": int(trial.get("level_2_participant_count") or 0),
            "human_task_completion_rate": trial.get("level_1_completion_rate"),
            "human_help_rate": trial.get("help_rate"),
            "human_median_time_seconds": trial.get("median_time_seconds"),
            "human_usefulness_median": trial.get("usefulness_median"),
            "human_trial_status": "passed" if human_trial_complete else "not_run",
        },
        checks=usability_checks,
        blockers=[] if human_trial_complete else ["real_participant_trial_not_completed"],
        warnings=["maintainer_rehearsal_is_not_counted_as_user_evidence"],
        evidence_sources=["UI service smoke", "Phase6TrialStore"],
    )

    package_checks = [
        bool(row.get("package_complete") and row.get("manifest_hashes_valid"))
        for row in tool_rows
    ]
    reproducibility_checks = {
        "tool_packages_complete": bool(package_checks) and all(package_checks),
        "input_data_not_copied": bool(exec_checks.get("input_data_not_copied")),
        "input_unchanged": bool(exec_checks.get("input_unchanged")),
        "defense_packages_complete": bool(
            (defense_details.get("success_case") or {}).get("package_complete")
            and (defense_details.get("repair_case") or {}).get("package_complete")
        ),
    }
    reproducibility = QualityDimensionResult(
        dimension="reproducibility",
        status=_status(reproducibility_checks),
        metrics={
            "package_integrity_rate": sum(package_checks) / max(1, len(package_checks)),
            "reproducibility_level": "Level 2",
            "input_data_copied": bool(execution.get("input_data_copied")),
        },
        checks=reproducibility_checks,
        evidence_sources=["restricted execution packages", "defense demo packages"],
    )

    runtimes = [
        float(row.get("runtime_seconds_total"))
        for row in tool_rows
        if isinstance(row.get("runtime_seconds_total"), (int, float))
    ]
    memories = [
        float(row.get("peak_memory_mb_max"))
        for row in tool_rows
        if isinstance(row.get("peak_memory_mb_max"), (int, float))
    ]
    performance_checks = {
        "agent_latency_recorded": agent.get("latency_p95_ms") is not None,
        "retrieval_latency_recorded": kg_bm25.get("latency_p95_ms") is not None,
        "execution_runtime_recorded": bool(runtimes),
        "execution_memory_recorded": bool(memories),
    }
    performance = QualityDimensionResult(
        dimension="performance",
        status=_status(performance_checks),
        metrics={
            "agent_latency_p50_ms": agent.get("latency_p50_ms"),
            "agent_latency_p95_ms": agent.get("latency_p95_ms"),
            "kg_bm25_latency_p50_ms": kg_bm25.get("latency_p50_ms"),
            "kg_bm25_latency_p95_ms": kg_bm25.get("latency_p95_ms"),
            "execution_runtime_seconds_mean_per_tool_smoke": fmean(runtimes)
            if runtimes
            else None,
            "execution_peak_memory_mb_max": max(memories) if memories else None,
            "execution_tool_call_count": actual_runs,
        },
        checks=performance_checks,
        warnings=["performance_is_local_machine_and_synthetic_fixture_scoped"],
        evidence_sources=["agent quality", "retrieval quality", "restricted execution smoke"],
    )

    expected_failures = int(baseline_details.get("expected_failure_count") or 0)
    captured_failures = int(baseline_details.get("captured_failure_count") or 0)
    failure_coverage = captured_failures / max(1, expected_failures)
    repair_case = defense_details.get("repair_case") or {}
    audit_checks = {
        "trace_stage_completeness_full": trace.get("applicable_stage_completeness") == 1.0,
        "failure_queue_coverage_full": expected_failures > 0
        and captured_failures >= expected_failures,
        "repair_lineage_complete": bool(repair_case.get("lineage_complete")),
        "repair_budget_respected": int(violations.get("repair_budget_violation") or 0)
        == 0,
    }
    auditability = QualityDimensionResult(
        dimension="auditability",
        status=_status(audit_checks),
        metrics={
            "applicable_stage_completeness": trace.get(
                "applicable_stage_completeness"
            ),
            "failure_queue_coverage": failure_coverage,
            "captured_failure_count": captured_failures,
            "expected_failure_count": expected_failures,
            "repair_lineage_complete": bool(repair_case.get("lineage_complete")),
        },
        checks=audit_checks,
        evidence_sources=["trace audit", "Phase 6 failure queue", "repair case"],
    )

    regression = _regression_summary(agent, baseline_path)
    portfolio_a4 = _portfolio_baseline(portfolio, "A4_kg_rag_tool_contract")
    change_checks = {
        "current_agent_gate_passed": bool(agent.get("release_gate_passed")),
        "portfolio_a4_not_worse_than_a3": portfolio.get("a4_not_worse_than_a3") is True,
        "frozen_system_baseline_available": regression.get("status") == "compared",
    }
    change_risk = QualityDimensionResult(
        dimension="change_risk",
        status=(
            "passed"
            if all(change_checks.values()) and not regression.get("regressions")
            else "partial"
            if change_checks["current_agent_gate_passed"]
            else "failed"
        ),
        metrics={
            "regression_status": regression.get("status"),
            "regression_count": len(regression.get("regressions") or {}),
            "portfolio_a4_hard_gate_passed": portfolio_a4.get("hard_gate_passed"),
            "portfolio_completed_model_calls": portfolio.get("completed_model_calls"),
        },
        checks=change_checks,
        blockers=[]
        if change_checks["frozen_system_baseline_available"]
        else ["frozen_system_quality_baseline_not_provided"],
        warnings=["portfolio_is_a_frozen_engineering_benchmark_not_scientific_proof"],
        evidence_sources=["agent quality regression", "Portfolio Benchmark v2"],
    )

    dimensions = [
        functional,
        safety,
        knowledge,
        usability,
        reproducibility,
        performance,
        auditability,
        change_risk,
    ]
    command_failures = [item.command_id for item in command_results if item.status != "passed"]
    engineering_dimensions = [
        functional,
        safety,
        knowledge,
        reproducibility,
        performance,
        auditability,
    ]
    engineering_gate = not command_failures and all(
        item.status == "passed" for item in engineering_dimensions
    )
    phase6_complete_eligible = engineering_gate and human_trial_complete
    recommended = (
        "PHASE6_BLOCKED"
        if not engineering_gate
        else "PHASE6_COMPLETE_REVIEW_REQUIRED"
        if phase6_complete_eligible
        else "PHASE6_TRIAL_READY"
    )
    blockers = [f"command_failed:{item}" for item in command_failures]
    if not engineering_gate:
        blockers.extend(
            f"dimension_failed:{item.dimension}"
            for item in engineering_dimensions
            if item.status != "passed"
        )
    if not human_trial_complete:
        blockers.append("real_group_trial_not_completed")
    failure_attribution = dict(agent.get("failure_domain_counts") or {})
    for item in command_failures:
        failure_attribution["evaluation_runtime"] = (
            failure_attribution.get("evaluation_runtime", 0) + 1
        )
    return SystemQualityReport(
        evaluation_id=evaluation_id,
        scope={
            "task_families": ["doublet_detection", "batch_integration"],
            "qualified_tools": ["Scrublet", "scDblFinder", "Harmony", "Scanorama"],
            "fresh_execution_smoke_tools": ["Scrublet", "scDblFinder"],
            "data_policy": "synthetic fixtures and frozen public evaluation artifacts only",
            "execution_policy_default": "disabled",
            "native_runner_boundary": "network_not_os_isolated",
        },
        command_results=command_results,
        scenarios=scenarios,
        dimensions=dimensions,
        capability_summary={
            "task_completion_rate": agent.get("task_completion_rate"),
            "tool_correctness": agent.get("tool_correctness"),
            "hallucination_rate": agent.get("hallucination_rate"),
            "compliance_pass_rate": agent.get("compliance_pass_rate"),
            "operational_scenario_pass_rate": scenario_rate,
            "knowledge_retrieval_gate": kg_bm25.get("status"),
        },
        regression_summary=regression,
        failure_attribution=failure_attribution,
        engineering_gate_passed=engineering_gate,
        phase6_complete_eligible=phase6_complete_eligible,
        recommended_status=recommended,
        blockers=sorted(set(blockers)),
        warnings=[
            "real_user_usability_metrics_are_not_available",
            "dense_hybrid_and_ragas_are_not_run",
            "no_os_level_container_isolation",
        ],
        limitations=[
            "Agent Quality v1 is a 12-case deterministic regression suite, not open-world proof.",
            "Fresh user execution smoke covers the two doublet tools; batch tools rely on their existing qualification and scientific-pilot artifacts.",
            "Scientific pilots are dataset-scoped and do not establish universal tool superiority.",
            "Maintainer rehearsal and automated UI smoke cannot substitute for 3-5 real participants.",
            "Native LocalControlledExecutor is not an OS sandbox and cannot run arbitrary generated code.",
        ],
    )


def _scenario_results(
    defense: dict[str, Any],
    details: dict[str, Any],
    execution: dict[str, Any],
) -> list[EvaluationScenarioResult]:
    blocked_detail = details.get("blocked_case") or {}
    definitions = (
        (
            "success-closure",
            "success",
            bool(defense.get("success_case")),
            "validated execution and complete package",
            "completed",
            int((details.get("success_case") or {}).get("execution_request_count") or 0),
            "defense demo",
        ),
        (
            "bounded-repair",
            "repair",
            bool(defense.get("repair_case")),
            "repair proposal, rerun, validation and lineage",
            "repaired_and_completed" if defense.get("repair_case") else "failed",
            None,
            "defense demo",
        ),
        (
            "correctly-blocked",
            "blocked",
            bool(defense.get("blocked_case"))
            and int(blocked_detail.get("execution_request_count") or 0) == 0,
            "BLOCKED with ExecutionRequest=0",
            str(blocked_detail.get("route") or "unknown"),
            int(blocked_detail.get("execution_request_count") or 0),
            "defense demo",
        ),
        (
            "approval-replay",
            "approval_replay",
            bool(execution.get("replay_blocked")),
            "replayed approval rejected",
            "blocked" if execution.get("replay_blocked") else "not_blocked",
            0 if execution.get("replay_blocked") else 1,
            "restricted execution smoke",
        ),
        (
            "parameter-change",
            "parameter_change",
            bool(execution.get("parameter_change_blocked")),
            "old approval invalid after parameter change",
            "blocked" if execution.get("parameter_change_blocked") else "not_blocked",
            0 if execution.get("parameter_change_blocked") else 1,
            "restricted execution smoke",
        ),
        (
            "cancellation",
            "cancellation",
            bool(execution.get("cancellation_passed")),
            "process tree terminated and run excluded from success",
            "cancelled" if execution.get("cancellation_passed") else "failed",
            None,
            "restricted execution smoke",
        ),
    )
    return [
        EvaluationScenarioResult(
            scenario_id=row[0],
            category=row[1],
            passed=row[2],
            expected_outcome=row[3],
            observed_outcome=row[4],
            execution_request_count=row[5],
            source=row[6],
        )
        for row in definitions
    ]


def _status(checks: dict[str, bool]) -> str:
    return "passed" if checks and all(checks.values()) else "failed"


def _portfolio_baseline(payload: dict[str, Any], baseline_id: str) -> dict[str, Any]:
    for row in payload.get("baselines") or []:
        if row.get("baseline_id") == baseline_id:
            return row
    return {}


def _regression_summary(
    current: dict[str, Any], baseline_path: Path | None
) -> dict[str, Any]:
    if baseline_path is None or not baseline_path.is_file():
        return {
            "status": "baseline_not_provided",
            "baseline_path": None,
            "improvements": {},
            "regressions": {},
        }
    baseline_payload = _read_json(baseline_path)
    baseline = baseline_payload.get("capability_summary") or baseline_payload
    current_metrics = {
        key: current.get(key)
        for key in (
            "task_completion_rate",
            "tool_correctness",
            "hallucination_rate",
            "compliance_pass_rate",
        )
    }
    improvements: dict[str, float] = {}
    regressions: dict[str, float] = {}
    for key, value in current_metrics.items():
        old = baseline.get(key)
        if not isinstance(value, (int, float)) or not isinstance(old, (int, float)):
            continue
        delta = float(value) - float(old)
        if key == "hallucination_rate":
            delta = -delta
        if delta > 1e-9:
            improvements[key] = round(delta, 6)
        elif delta < -1e-9:
            regressions[key] = round(delta, 6)
    return {
        "status": "compared",
        "baseline_path": baseline_path.name,
        "improvements": improvements,
        "regressions": regressions,
    }


def _load_defense_details(payload: dict[str, Any]) -> dict[str, Any]:
    relative = payload.get("bundle")
    if not relative:
        return {}
    root = (PROJECT_ROOT / str(relative)).resolve()
    allowed = (PROJECT_ROOT / ".sckg_exec" / "demos").resolve()
    if not root.is_relative_to(allowed):
        return {}
    return {
        name.removesuffix(".json"): _read_json(root / name)
        for name in (
            "success_case.json",
            "repair_case.json",
            "blocked_case.json",
            "trace_audit.json",
        )
    }


def _load_baseline_details() -> dict[str, Any]:
    summary = _read_json(PROJECT_ROOT / "eval" / "phase6" / "baseline_summary.json")
    expected = int(
        (((summary.get("baselines") or {}).get("B3_contract_no_repair") or {}).get("metrics") or {}).get("run_count")
        or 0
    )
    queue_path = PROJECT_ROOT / "eval" / "phase6" / "failure_queue.tsv"
    captured = 0
    if queue_path.is_file():
        with queue_path.open("r", encoding="utf-8", newline="") as handle:
            captured = sum(1 for _ in csv.DictReader(handle, delimiter="\t"))
    return {"expected_failure_count": expected, "captured_failure_count": captured}


def _last_json_object(value: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, character in enumerate(value):
        if character != "{":
            continue
        try:
            payload, end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and not value[index + end :].strip():
            return payload
        if isinstance(payload, dict):
            candidates.append(payload)
    return candidates[-1] if candidates else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    text = str(value).replace(str(PROJECT_ROOT), "<PROJECT_ROOT>")
    return _ABSOLUTE_PATH.sub("<redacted-path>", text)


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _failure_rows(report: SystemQualityReport) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in report.scenarios:
        if not scenario.passed:
            rows.append(
                {
                    "failure_id": f"scenario:{scenario.scenario_id}",
                    "owner": "execution_or_governance",
                    "severity": "P0" if scenario.category in {"blocked", "approval_replay"} else "P1",
                    "reason": scenario.observed_outcome,
                }
            )
    for dimension in report.dimensions:
        if dimension.status == "failed":
            rows.append(
                {
                    "failure_id": f"dimension:{dimension.dimension}",
                    "owner": _dimension_owner(dimension.dimension),
                    "severity": "P0" if dimension.dimension == "safety_and_isolation" else "P1",
                    "reason": ";".join(dimension.blockers)
                    or "one_or_more_release_checks_failed",
                }
            )
    return rows


def _dimension_owner(dimension: str) -> str:
    return {
        "functional_correctness": "agent_or_execution",
        "safety_and_isolation": "security_governance",
        "knowledge_quality": "knowledge_retrieval",
        "usability": "product_ui",
        "reproducibility": "execution_packaging",
        "performance": "runtime",
        "auditability": "observability",
        "change_risk": "release_engineering",
    }.get(dimension, "unknown")


def _markdown_report(report: SystemQualityReport) -> str:
    lines = [
        "# scKG-Agent System Quality Report",
        "",
        f"- Evaluation: `{report.evaluation_id}`",
        f"- Status: `{report.recommended_status}`",
        f"- Engineering gate: `{str(report.engineering_gate_passed).lower()}`",
        f"- Phase 6 completion eligible: `{str(report.phase6_complete_eligible).lower()}`",
        "",
        "## Dimensions",
        "",
        "| Dimension | Status | Key metrics |",
        "| --- | --- | --- |",
    ]
    for item in report.dimensions:
        metrics = "; ".join(
            f"{key}={value}" for key, value in list(item.metrics.items())[:5]
        )
        lines.append(f"| {item.dimension} | {item.status} | {metrics} |")
    lines.extend(["", "## Operational scenarios", ""])
    for item in report.scenarios:
        lines.append(
            f"- `{item.scenario_id}`: {'PASS' if item.passed else 'FAIL'} - {item.observed_outcome}"
        )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in report.blockers)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines) + "\n"
