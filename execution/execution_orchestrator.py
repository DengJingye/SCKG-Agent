from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from pydantic import Field

from core.deterministic_router import DeterministicRouter, RouterRoute
from core.execution_models import (
    CandidateEvaluation,
    ConfigurationSpec,
    DataProfile,
    DecisionResult,
    ExecutionBudget,
    ExecutionRun,
    ExperimentBatchResult,
    ExperimentRunRecord,
    QualificationArtifact,
    ReproducibilityPackageResult,
    RequirementSpec,
    ScientificSplitArtifact,
    StrictModel,
    ToolContract,
    ValidationResult,
    WorkflowPlan,
)
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import (
    ExperimentRunner,
    build_configuration,
)
from execution.local_controlled_executor import LocalControlledExecutor
from execution.probe_builder import ProbeBuilder
from execution.repair_policy import (
    NON_REPAIRABLE_REASONS,
    RepairAction,
    RepairPolicy,
    RepairProposal,
    RepairType,
    RunBudgetLedger,
    apply_repair_parameters,
)
from execution.reproducibility_packager import ReproducibilityPackager
from execution.validators.doublet import DoubletValidator
from execution.validators.scdblfinder import ScDblFinderValidator


class OrchestratorState(str, Enum):
    CREATED = "CREATED"
    PROFILED = "PROFILED"
    PLANNED = "PLANNED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    REPAIR_PENDING = "REPAIR_PENDING"
    AGGREGATING = "AGGREGATING"
    DECIDING = "DECIDING"
    PACKAGING = "PACKAGING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


LEGAL_TRANSITIONS = {
    OrchestratorState.CREATED: {
        OrchestratorState.PROFILED,
        OrchestratorState.BLOCKED,
        OrchestratorState.FAILED,
    },
    OrchestratorState.PROFILED: {
        OrchestratorState.PLANNED,
        OrchestratorState.BLOCKED,
        OrchestratorState.FAILED,
    },
    OrchestratorState.PLANNED: {
        OrchestratorState.WAITING_APPROVAL,
        OrchestratorState.BLOCKED,
    },
    OrchestratorState.WAITING_APPROVAL: {
        OrchestratorState.RUNNING,
        OrchestratorState.BLOCKED,
    },
    OrchestratorState.RUNNING: {
        OrchestratorState.VALIDATING,
        OrchestratorState.BLOCKED,
        OrchestratorState.FAILED,
    },
    OrchestratorState.VALIDATING: {
        OrchestratorState.REPAIR_PENDING,
        OrchestratorState.AGGREGATING,
        OrchestratorState.BLOCKED,
    },
    OrchestratorState.REPAIR_PENDING: {
        OrchestratorState.RUNNING,
        OrchestratorState.AGGREGATING,
        OrchestratorState.BLOCKED,
    },
    OrchestratorState.AGGREGATING: {
        OrchestratorState.DECIDING,
        OrchestratorState.BLOCKED,
    },
    OrchestratorState.DECIDING: {OrchestratorState.PACKAGING},
    OrchestratorState.PACKAGING: {
        OrchestratorState.COMPLETED,
        OrchestratorState.BLOCKED,
        OrchestratorState.FAILED,
    },
    OrchestratorState.COMPLETED: set(),
    OrchestratorState.BLOCKED: set(),
    OrchestratorState.FAILED: set(),
}


class OrchestratorTraceEvent(StrictModel):
    sequence: int = Field(ge=1)
    request_id: str
    plan_id: Optional[str] = None
    run_id: Optional[str] = None
    candidate_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    state_before: OrchestratorState
    state_after: OrchestratorState
    contract_version: Optional[str] = None
    environment_id: Optional[str] = None
    input_hash: Optional[str] = None
    parameter_hash: Optional[str] = None
    repair_count: int = Field(default=0, ge=0)
    validation_result: Optional[dict[str, Any]] = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    decision_result: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)


class OrchestrationResult(StrictModel):
    orchestration_id: str
    final_state: OrchestratorState
    state_history: list[OrchestratorState]
    trace_path: str
    profile: DataProfile
    plan: WorkflowPlan
    batches: list[ExperimentBatchResult]
    execution_runs: list[ExecutionRun]
    validation_results: list[ValidationResult]
    repair_proposals: list[RepairProposal]
    repair_actions: list[RepairAction]
    budget: RunBudgetLedger
    candidate_evaluations: list[CandidateEvaluation]
    decision_result: DecisionResult
    package_result: ReproducibilityPackageResult
    blockers: list[str] = Field(default_factory=list)


class ExecutionOrchestrator:
    """Central state machine for bounded maintainer qualification execution."""

    def __init__(
        self,
        *,
        run_root: Path,
        approved_input_root: Path,
        package_root: Path,
        trace_root: Optional[Path] = None,
        profiler: Optional[AnnDataProfiler] = None,
        contract_registry: Optional[ToolContractRegistry] = None,
        environment_registry: Optional[EnvironmentRegistry] = None,
        router: Optional[DeterministicRouter] = None,
        probe_builder: Optional[ProbeBuilder] = None,
        executor: Optional[LocalControlledExecutor] = None,
        validator: Optional[DoubletValidator] = None,
        experiment_runner: Optional[ExperimentRunner] = None,
        aggregator: Optional[CandidateAggregator] = None,
        pareto: Optional[ParetoDecisionEngine] = None,
        packager: Optional[ReproducibilityPackager] = None,
        repair_policy: Optional[RepairPolicy] = None,
    ) -> None:
        self.run_root = Path(run_root).resolve()
        self.approved_input_root = Path(approved_input_root).resolve()
        self.trace_root = Path(trace_root or self.run_root.parent / "orchestrations").resolve()
        self.environment_registry = environment_registry or EnvironmentRegistry()
        self.contract_registry = contract_registry or ToolContractRegistry(
            environment_registry=self.environment_registry
        )
        self.profiler = profiler or AnnDataProfiler()
        self.router = router or DeterministicRouter()
        self.probe_builder = probe_builder or ProbeBuilder()
        self.validator = validator or DoubletValidator()
        self.executor = executor or LocalControlledExecutor(
            run_root=self.run_root,
            approved_input_root=self.approved_input_root,
            environment_registry=self.environment_registry,
            contract_registry=self.contract_registry,
        )
        self._experiment_runner_injected = experiment_runner is not None
        self.experiment_runner = experiment_runner or ExperimentRunner(
            executor=self.executor,
            contract_registry=self.contract_registry,
            router=self.router,
            validator=self.validator,
        )
        self.aggregator = aggregator or CandidateAggregator()
        self.pareto = pareto or ParetoDecisionEngine()
        self.packager = packager or ReproducibilityPackager(package_root=package_root)
        self.repair_policy = repair_policy or RepairPolicy()

    def run(
        self,
        *,
        orchestration_id: str,
        requirement: RequirementSpec,
        configurations: Iterable[ConfigurationSpec],
        seeds: Iterable[int],
        fixture_id: str,
        package_id: str,
        execution_budget: Optional[ExecutionBudget] = None,
        actor_role: Literal["maintainer", "user"] = "maintainer",
        qualification_approved: bool = True,
        fixture_allowlisted: bool = True,
        repair_approved: bool = True,
        probe: Optional[ScientificSplitArtifact] = None,
        artifact: Optional[QualificationArtifact] = None,
        probe_max_cells: Optional[int] = None,
        pairing_strategy: Literal[
            "random", "within_cluster", "between_cluster", "mixed"
        ] = "mixed",
        cluster_key: Optional[str] = None,
        rerun_command: str = "conda run -n scRNAseq python scripts/run_phase4_repair_smoke.py",
        tool_name: str = "Scrublet",
        tool_version: str = "0.2.3",
    ) -> OrchestrationResult:
        configurations = list(configurations)
        seeds = list(seeds)
        budget = RunBudgetLedger(limits=execution_budget or ExecutionBudget())
        trace_file = self.trace_root / orchestration_id / "trace.jsonl"
        tracker = _StateTracker(orchestration_id, requirement.request_id, trace_file)
        contract = self.contract_registry.load(tool_name, tool_version)
        environment = self.environment_registry.get(contract.environment_id)
        experiment_runner = self.experiment_runner
        if (
            not self._experiment_runner_injected
            and contract.tool_name.casefold() == "scdblfinder"
        ):
            experiment_runner = ExperimentRunner(
                executor=self.executor,
                contract_registry=self.contract_registry,
                router=self.router,
                validator=ScDblFinderValidator(contract),
            )

        profile = self.profiler.profile(
            requirement.input_path or "",
            batch_key=requirement.batch_key,
            label_key=requirement.label_key,
            max_cells=requirement.resource_budget.max_cells,
        )
        tracker.transition(
            OrchestratorState.PROFILED,
            contract=contract,
            environment_id=environment.environment_id,
            input_hash=profile.file_hash or None,
            warnings=profile.blocking_errors,
        )
        planning_gate = self.contract_registry.planning_gate(contract, data_profile=profile)
        plan = ExecutionPlanCompiler(self.contract_registry).compile(
            requirement=requirement,
            data_profile=profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=budget.limits,
        )
        tracker.transition(
            OrchestratorState.PLANNED,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            input_hash=profile.file_hash or None,
            warnings=plan.blocking_conditions,
        )
        if profile.is_blocked or not planning_gate.allowed or plan.plan_status == "blocked":
            tracker.transition(
                OrchestratorState.BLOCKED,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                warnings=sorted(set(profile.blocking_errors + planning_gate.reasons)),
            )
            raise ValueError("orchestration blocked before execution")

        tracker.transition(
            OrchestratorState.WAITING_APPROVAL,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
        )
        authorization_issues = []
        if actor_role != "maintainer":
            authorization_issues.append("qualification_requires_maintainer")
        if not qualification_approved:
            authorization_issues.append("qualification_not_approved")
        if not fixture_allowlisted:
            authorization_issues.append("fixture_not_allowlisted")
        if authorization_issues:
            tracker.transition(
                OrchestratorState.BLOCKED,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                warnings=authorization_issues,
            )
            raise PermissionError(";".join(authorization_issues))

        active_probe, active_artifact = self._materialize_artifact(
            requirement=requirement,
            profile=profile,
            fixture_id=fixture_id,
            probe=probe,
            artifact=artifact,
            probe_max_cells=probe_max_cells,
            pairing_strategy=pairing_strategy,
            cluster_key=cluster_key,
            output_suffix="initial",
        )
        budget = budget.reserve_initial(len(configurations) * len(seeds))
        tracker.transition(
            OrchestratorState.RUNNING,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            input_hash=active_artifact.sha256,
        )
        initial_batch = experiment_runner.run(
            experiment_id=f"{orchestration_id}-initial",
            configurations=configurations,
            seeds=seeds,
            probe=active_probe,
            artifact=active_artifact,
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=plan.plan_id,
        )
        batches = [initial_batch]
        _record_batch_observations(
            tracker=tracker,
            batch=initial_batch,
            contract=contract,
            environment_id=environment.environment_id,
            repair_count=0,
            lineage={},
        )
        tracker.transition(
            OrchestratorState.VALIDATING,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            input_hash=active_artifact.sha256,
            warnings=initial_batch.failures,
        )

        repair_proposals: list[RepairProposal] = []
        repair_actions: list[RepairAction] = []
        processed_failed_run_ids: set[str] = set()
        critical_blockers: list[str] = []
        repair_round = 0
        while True:
            failed_pairs = _failed_pairs(batches, processed_failed_run_ids)
            if not failed_pairs:
                break
            pending: list[tuple[ExecutionRun, ValidationResult, RepairProposal, int]] = []
            for run, validation, seed in failed_pairs:
                processed_failed_run_ids.add(run.run_id)
                proposal = self.repair_policy.propose(
                    run=run,
                    validation=validation,
                    contract=contract,
                    expected_cells=active_artifact.expected_cells,
                    previous_repairs_for_parent=sum(
                        item.parent_run_id == run.run_id or item.new_run_id == run.run_id
                        for item in repair_actions
                    ),
                )
                if proposal is not None and not validation.repairable:
                    validation = validation.model_copy(update={"repairable": True})
                    _replace_validation(batches, validation)
                reason = self.repair_policy.classify(run, validation)
                budget_available = (
                    budget.repair_runs_used < budget.limits.reserved_repair_runs
                    and budget.total_runs_used < budget.limits.max_total_runs
                )
                route = self.router.route_repair(
                    validation=validation,
                    proposal=proposal,
                    repair_approved=None,
                    budget_available=budget_available,
                )
                if route.route == RouterRoute.BLOCKED or reason in NON_REPAIRABLE_REASONS:
                    critical_blockers.extend(route.reasons or [reason.value])
                    continue
                if proposal is None or not budget_available:
                    continue
                if isinstance(active_probe, ScientificSplitArtifact) and (
                    active_probe.split_role == "evaluation"
                    and proposal.repair_type != RepairType.RETRY_SAME_REQUEST_ONCE
                ):
                    critical_blockers.append("scientific_evaluation_parameter_repair_forbidden")
                    continue
                repair_proposals.append(proposal)
                pending.append((run, validation, proposal, seed))

            if not pending:
                break
            tracker.transition(
                OrchestratorState.REPAIR_PENDING,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                repair_count=len(repair_actions),
                warnings=[item[2].reason_code for item in pending],
            )
            approved_pending = pending if repair_approved else []
            if not approved_pending:
                break
            tracker.transition(
                OrchestratorState.RUNNING,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                repair_count=len(repair_actions),
            )
            new_batches: list[ExperimentBatchResult] = []
            for index, (parent_run, _, proposal, seed) in enumerate(approved_pending):
                try:
                    budget = budget.reserve_repair()
                except ValueError:
                    break
                repaired_probe = active_probe
                repaired_artifact = active_artifact
                if proposal.repair_type == RepairType.REDUCE_PROBE_SIZE:
                    repaired_probe, repaired_artifact = self._materialize_artifact(
                        requirement=requirement,
                        profile=profile,
                        fixture_id=fixture_id,
                        probe=None,
                        artifact=None,
                        probe_max_cells=int(proposal.new_values["probe_max_cells"]),
                        pairing_strategy=pairing_strategy,
                        cluster_key=cluster_key,
                        output_suffix=f"repair-{repair_round}-{index}",
                    )
                repaired_parameters = apply_repair_parameters(
                    parent_run.parameters, proposal
                )
                repaired_provenance = dict(parent_run.parameter_provenance)
                for field in proposal.changed_fields:
                    if field in repaired_parameters:
                        repaired_provenance[field] = {
                            "origin": "repair_action",
                            "policy_rule_id": proposal.provenance["policy_version"],
                            "parent_run_id": parent_run.run_id,
                            "old_value": proposal.old_values[field],
                            "new_value": proposal.new_values[field],
                        }
                repaired_config = build_configuration(
                    configuration_id=f"repair-{repair_round}-{index}",
                    parameters=repaired_parameters,
                    provenance=repaired_provenance,
                    source="development_probe_search",
                    contract=contract,
                    frozen=False,
                )
                experiment_id = f"{orchestration_id}-repair-{repair_round}-{index}"
                expected_run_id = f"{experiment_id}-{repaired_config.configuration_id}-seed-{seed}"
                action = self.repair_policy.apply(
                    proposal=proposal,
                    new_run_id=expected_run_id,
                    approved=True,
                )
                route = self.router.route_repair(
                    validation=validation,
                    proposal=proposal,
                    repair_approved=True,
                    budget_available=True,
                )
                if route.route != RouterRoute.QUALIFICATION_EXECUTION:
                    critical_blockers.extend(route.reasons)
                    continue
                repair_actions.append(action)
                new_batches.append(
                    experiment_runner.run(
                        experiment_id=experiment_id,
                        configurations=[repaired_config],
                        seeds=[seed],
                        probe=repaired_probe,
                        artifact=repaired_artifact,
                        contract=contract,
                        environment=environment,
                        planning_gate=planning_gate,
                        plan_id=plan.plan_id,
                    )
                )
            batches.extend(new_batches)
            _record_batch_observations(
                tracker=tracker,
                batch=_combine_batches(
                    orchestration_id=f"{orchestration_id}-repair-observation-{repair_round}",
                    probe_hash=active_probe.probe_hash,
                    batches=new_batches,
                ),
                contract=contract,
                environment_id=environment.environment_id,
                repair_count=len(repair_actions),
                lineage={item.new_run_id: item.parent_run_id for item in repair_actions},
            )
            repair_round += 1
            tracker.transition(
                OrchestratorState.VALIDATING,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                repair_count=len(repair_actions),
                warnings=[failure for batch in new_batches for failure in batch.failures],
            )

        tracker.transition(
            OrchestratorState.AGGREGATING,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            repair_count=len(repair_actions),
            warnings=critical_blockers,
        )
        combined = _combine_batches(
            orchestration_id=orchestration_id,
            probe_hash=active_probe.probe_hash,
            batches=batches,
        )
        candidates = self.aggregator.aggregate(batch=combined, contract=contract)
        tracker.transition(
            OrchestratorState.DECIDING,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            repair_count=len(repair_actions),
        )
        decision = self.pareto.decide(candidates, preference="performance")
        tracker.transition(
            OrchestratorState.PACKAGING,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            repair_count=len(repair_actions),
            decision_result=decision,
        )
        package = self.packager.build_orchestrated(
            package_id=package_id,
            requirement=requirement,
            data_profile=profile,
            workflow_plan=plan,
            contract=contract,
            environment=environment,
            batches=batches,
            candidate_evaluations=candidates,
            decision_result=decision,
            repair_proposals=repair_proposals,
            repair_actions=repair_actions,
            trace_events=tracker.events,
            rerun_command=rerun_command,
        )
        all_failed = decision.recommended_candidate_id is None
        blockers = sorted(set(critical_blockers + (["all_candidates_failed"] if all_failed else [])))
        terminal = OrchestratorState.BLOCKED if blockers else OrchestratorState.COMPLETED
        tracker.transition(
            terminal,
            plan_id=plan.plan_id,
            contract=contract,
            environment_id=environment.environment_id,
            repair_count=len(repair_actions),
            decision_result=decision,
            warnings=blockers,
        )
        package = self.packager.refresh_orchestrated_trace(
            package_result=package,
            trace_events=tracker.events,
        )
        return OrchestrationResult(
            orchestration_id=orchestration_id,
            final_state=terminal,
            state_history=[OrchestratorState.CREATED]
            + [
                event.state_after
                for event in tracker.events
                if event.state_before != event.state_after
            ],
            trace_path=str(trace_file),
            profile=profile,
            plan=plan,
            batches=batches,
            execution_runs=[run for batch in batches for run in batch.execution_runs],
            validation_results=[
                validation for batch in batches for validation in batch.validation_results
            ],
            repair_proposals=repair_proposals,
            repair_actions=repair_actions,
            budget=budget,
            candidate_evaluations=candidates,
            decision_result=decision,
            package_result=package,
            blockers=blockers,
        )

    def _materialize_artifact(
        self,
        *,
        requirement: RequirementSpec,
        profile: DataProfile,
        fixture_id: str,
        probe: Optional[ScientificSplitArtifact],
        artifact: Optional[QualificationArtifact],
        probe_max_cells: Optional[int],
        pairing_strategy: str,
        cluster_key: Optional[str],
        output_suffix: str,
    ) -> tuple[Any, QualificationArtifact]:
        if probe is not None or artifact is not None:
            if probe is None or artifact is None:
                raise ValueError("scientific probe and artifact must be supplied together")
            if artifact.user_data or not artifact.public_dataset or artifact.accession != "GSE108313":
                raise ValueError("only registered GSE108313 scientific artifact is allowed")
            return probe, artifact
        output_dir = self.approved_input_root / "phase4" / output_suffix
        built = self.probe_builder.build(
            source_path=requirement.input_path or "",
            output_dir=output_dir,
            profile_id=profile.profile_id,
            fixture_id=fixture_id,
            max_cells=probe_max_cells or min(requirement.resource_budget.max_cells, profile.n_cells),
            random_seed=20260713,
            split_role="development",
            pairing_strategy=pairing_strategy,
            cluster_key=cluster_key,
            allowed_output_root=self.approved_input_root,
        )
        return built, QualificationArtifact(
            artifact_id=f"phase4-{output_suffix}",
            fixture_id=fixture_id,
            path=built.probe_artifact_path,
            sha256=built.probe_hash,
            synthetic=True,
            allowlisted=True,
            expected_cells=built.n_probe_cells,
        )


class _StateTracker:
    def __init__(self, orchestration_id: str, request_id: str, trace_path: Path) -> None:
        self.orchestration_id = orchestration_id
        self.request_id = request_id
        self.trace_path = trace_path
        self.state = OrchestratorState.CREATED
        self.events: list[OrchestratorTraceEvent] = []
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def transition(
        self,
        target: OrchestratorState,
        *,
        plan_id: Optional[str] = None,
        run: Optional[ExecutionRun] = None,
        candidate_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        contract: Optional[ToolContract] = None,
        environment_id: Optional[str] = None,
        input_hash: Optional[str] = None,
        parameters: Optional[dict[str, Any]] = None,
        repair_count: int = 0,
        validation_result: Optional[ValidationResult] = None,
        decision_result: Optional[DecisionResult] = None,
        warnings: Optional[list[Any]] = None,
    ) -> None:
        if target not in LEGAL_TRANSITIONS[self.state]:
            raise ValueError(f"illegal orchestrator transition: {self.state}->{target}")
        event = OrchestratorTraceEvent(
            sequence=len(self.events) + 1,
            request_id=self.request_id,
            plan_id=plan_id,
            run_id=run.run_id if run else None,
            candidate_id=candidate_id,
            parent_run_id=parent_run_id,
            state_before=self.state,
            state_after=target,
            contract_version=contract.contract_version if contract else None,
            environment_id=environment_id,
            input_hash=input_hash or (run.input_hash if run else None),
            parameter_hash=_parameter_hash(parameters or (run.parameters if run else {})),
            repair_count=repair_count,
            validation_result=(
                validation_result.model_dump(mode="json") if validation_result else None
            ),
            artifact_hashes=run.artifact_hashes if run else {},
            decision_result=decision_result.model_dump(mode="json") if decision_result else None,
            warnings=[str(item) for item in warnings or []],
        )
        self.events.append(event)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        self.state = target

    def observe(
        self,
        *,
        plan_id: str,
        run: ExecutionRun,
        candidate_id: Optional[str],
        parent_run_id: Optional[str],
        contract: ToolContract,
        environment_id: str,
        repair_count: int,
        validation_result: ValidationResult,
    ) -> None:
        event = OrchestratorTraceEvent(
            sequence=len(self.events) + 1,
            request_id=self.request_id,
            plan_id=plan_id,
            run_id=run.run_id,
            candidate_id=candidate_id,
            parent_run_id=parent_run_id,
            state_before=self.state,
            state_after=self.state,
            contract_version=contract.contract_version,
            environment_id=environment_id,
            input_hash=run.input_hash,
            parameter_hash=_parameter_hash(run.parameters),
            repair_count=repair_count,
            validation_result=validation_result.model_dump(mode="json"),
            artifact_hashes=run.artifact_hashes,
        )
        self.events.append(event)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")


def _failed_pairs(
    batches: list[ExperimentBatchResult], processed: set[str]
) -> list[tuple[ExecutionRun, ValidationResult, int]]:
    results = []
    for batch in batches:
        runs = {run.run_id: run for run in batch.execution_runs}
        seeds = {record.run_id: record.seed for record in batch.run_records}
        for validation in batch.validation_results:
            if validation.passed or validation.run_id in processed:
                continue
            run = runs.get(validation.run_id)
            if run is not None:
                results.append((run, validation, seeds.get(run.run_id, 0)))
    return results


def _replace_validation(
    batches: list[ExperimentBatchResult], replacement: ValidationResult
) -> None:
    for index, batch in enumerate(batches):
        if not any(item.run_id == replacement.run_id for item in batch.validation_results):
            continue
        validations = [
            replacement if item.run_id == replacement.run_id else item
            for item in batch.validation_results
        ]
        batches[index] = batch.model_copy(update={"validation_results": validations})
        return


def _record_batch_observations(
    *,
    tracker: _StateTracker,
    batch: ExperimentBatchResult,
    contract: ToolContract,
    environment_id: str,
    repair_count: int,
    lineage: dict[str, str],
) -> None:
    validations = {item.run_id: item for item in batch.validation_results}
    records = {item.run_id: item for item in batch.run_records}
    for run in batch.execution_runs:
        validation = validations.get(run.run_id)
        if validation is None:
            continue
        record = records.get(run.run_id)
        candidate_id = None
        if record is not None:
            candidate_id = (
                f"{contract.tool_name}:{contract.tool_version}:"
                f"{record.configuration_hash[:16]}"
            )
        tracker.observe(
            plan_id=run.plan_id,
            run=run,
            candidate_id=candidate_id,
            parent_run_id=lineage.get(run.run_id),
            contract=contract,
            environment_id=environment_id,
            repair_count=repair_count,
            validation_result=validation,
        )


def _combine_batches(
    *, orchestration_id: str, probe_hash: str, batches: list[ExperimentBatchResult]
) -> ExperimentBatchResult:
    configurations: dict[str, ConfigurationSpec] = {}
    runs: list[ExecutionRun] = []
    validations: list[ValidationResult] = []
    records: list[ExperimentRunRecord] = []
    failures: list[str] = []
    for batch in batches:
        for configuration in batch.configurations:
            configurations.setdefault(configuration.configuration_hash, configuration)
        runs.extend(batch.execution_runs)
        validations.extend(batch.validation_results)
        records.extend(batch.run_records)
        failures.extend(batch.failures)
    return ExperimentBatchResult(
        experiment_id=f"{orchestration_id}-combined",
        split_role="development",
        probe_hash=probe_hash,
        configurations=list(configurations.values()),
        execution_runs=runs,
        validation_results=validations,
        run_records=records,
        requested_run_count=len(runs),
        completed_run_count=len(runs),
        failures=failures,
    )


def _parameter_hash(parameters: dict[str, Any]) -> Optional[str]:
    if not parameters:
        return None
    return hashlib.sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
