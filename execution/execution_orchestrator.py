from __future__ import annotations

import hashlib
import json
import uuid
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
from core.trace_context import (
    TraceCollector,
    TraceContext,
    TraceCorrelationKind,
    TraceKind,
    TraceLinkType,
    TracePrivacyError,
    TraceStage,
    TraceStatus,
    TraceValidationError,
    trace_correlation_id,
)
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.approval_service import (
    ApprovalScope,
    ApprovalService,
    AuthorizationValidation,
    parameter_hash,
)
from execution.data_registry import DataRegistry, RegisteredDataArtifact
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
    canonical_trace_id: str
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


class UserExecutionPreparation(StrictModel):
    user_id: str
    artifact: RegisteredDataArtifact
    route: RouterRoute
    reasons: list[str] = Field(default_factory=list)
    data_access: AuthorizationValidation
    execution_approval: Optional[AuthorizationValidation] = None
    profile: Optional[DataProfile] = None
    plan: Optional[WorkflowPlan] = None
    approval_scope: Optional[ApprovalScope] = None
    request_fingerprint: Optional[str] = None
    execution_request_created: bool = False


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
        data_registry: Optional[DataRegistry] = None,
        approval_service: Optional[ApprovalService] = None,
        trace_collector: Optional[TraceCollector] = None,
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
        self.data_registry = data_registry
        self.approval_service = approval_service
        self.trace_collector = trace_collector or TraceCollector()

    def prepare_user_execution(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: Optional[str],
        execution_approval_id: Optional[str],
        request_id: str,
        query: str,
        parameters: dict[str, Any],
        tool_name: str = "Scrublet",
        tool_version: str = "0.2.3",
        parent_route_override: Optional[RouterRoute] = None,
    ) -> UserExecutionPreparation:
        """Profile and plan user data, but never create an ExecutionRequest in Phase 6A."""

        if self.data_registry is None or self.approval_service is None:
            raise RuntimeError("Phase 6A data registry and approval service are required")
        artifact = self.data_registry.get(artifact_id, user_id=user_id)
        data_access = self.approval_service.validate_data_access(
            data_grant_id,
            user_id=user_id,
            artifact_id=artifact_id,
        )
        if not data_access.allowed:
            decision = self.router.route_user_authorization(
                data_access=data_access,
                execution_approval=None,
                execution_backend_enabled=False,
                parent_route_override=parent_route_override,
            )
            return UserExecutionPreparation(
                user_id=user_id,
                artifact=artifact,
                route=decision.route,
                reasons=decision.reasons,
                data_access=data_access,
            )

        contract = self.contract_registry.load(tool_name, tool_version)
        environment = self.environment_registry.get(contract.environment_id)
        validated_parameters = self.contract_registry.validate_parameters(
            contract, parameters
        )
        input_path = self.data_registry.resolve_path(artifact_id, user_id=user_id)
        is_batch_integration = str(contract.task) == "batch_integration"
        profile = self.profiler.profile(
            input_path,
            batch_key="batch" if is_batch_integration else None,
            label_key="cell_type" if is_batch_integration else None,
        )
        if profile.is_blocked and not is_batch_integration:
            return UserExecutionPreparation(
                user_id=user_id,
                artifact=artifact,
                route=RouterRoute.BLOCKED,
                reasons=list(profile.blocking_errors),
                data_access=data_access,
                profile=profile,
            )
        requirement = RequirementSpec(
            request_id=request_id,
            query=query,
            task=contract.task,
            input_path=artifact.redacted_path,
            input_object_type=artifact.artifact_type,
            batch_key="batch" if is_batch_integration else None,
            label_key="cell_type" if is_batch_integration else None,
            output_goal=(
                "batch-corrected embedding with biology-conservation diagnostics"
                if is_batch_integration
                else "doublet scores and calls"
            ),
            data_access_authorized=True,
            execution_authorized=False,
        )
        planning_gate = self.contract_registry.planning_gate(
            contract, data_profile=profile
        )
        plan = ExecutionPlanCompiler(self.contract_registry).compile(
            requirement=requirement,
            data_profile=profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=ExecutionBudget(),
        )
        if not planning_gate.allowed or plan.plan_status == "blocked":
            return UserExecutionPreparation(
                user_id=user_id,
                artifact=artifact,
                route=RouterRoute.BLOCKED,
                reasons=sorted(set(planning_gate.reasons + plan.blocking_conditions)),
                data_access=data_access,
                profile=profile,
                plan=plan,
            )
        scope = ApprovalScope(
            user_id=user_id,
            artifact_id=artifact_id,
            plan_id=plan.plan_id,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            contract_version=contract.contract_version,
            environment_id=environment.environment_id,
            parameter_hash=parameter_hash(validated_parameters),
        )
        execution_approval = self.approval_service.validate_execution_approval(
            execution_approval_id,
            expected_scope=scope,
        )
        # Phase 6A is authorization-only even after Phase 6B enables selected pairs.
        execution_backend_enabled = False
        decision = self.router.route_user_authorization(
            data_access=data_access,
            execution_approval=execution_approval,
            execution_backend_enabled=execution_backend_enabled,
            parent_route_override=parent_route_override,
        )
        return UserExecutionPreparation(
            user_id=user_id,
            artifact=artifact,
            route=decision.route,
            reasons=decision.reasons,
            data_access=data_access,
            execution_approval=execution_approval,
            profile=profile,
            plan=plan,
            approval_scope=scope,
            request_fingerprint=scope.fingerprint,
            execution_request_created=False,
        )

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
        parent_trace_id: Optional[str] = None,
        handoff_id: Optional[str] = None,
        parent_request_id: Optional[str] = None,
        original_plan_id: Optional[str] = None,
    ) -> OrchestrationResult:
        trace = _new_controlled_execution_trace(
            request_id=requirement.request_id,
            parent_trace_id=parent_trace_id,
            handoff_id=handoff_id,
            parent_request_id=parent_request_id,
            original_plan_id=original_plan_id,
        )
        with self.trace_collector.request_scope(
            trace,
            exception_error_code="controlled_execution_failed",
        ):
            result = self._run_controlled(
                orchestration_id=orchestration_id,
                requirement=requirement,
                configurations=configurations,
                seeds=seeds,
                fixture_id=fixture_id,
                package_id=package_id,
                execution_budget=execution_budget,
                actor_role=actor_role,
                qualification_approved=qualification_approved,
                fixture_allowlisted=fixture_allowlisted,
                repair_approved=repair_approved,
                probe=probe,
                artifact=artifact,
                probe_max_cells=probe_max_cells,
                pairing_strategy=pairing_strategy,
                cluster_key=cluster_key,
                rerun_command=rerun_command,
                tool_name=tool_name,
                tool_version=tool_version,
                trace=trace,
            )
            _set_controlled_execution_outcome(trace, result)
        return result

    def _run_controlled(
        self,
        *,
        orchestration_id: str,
        requirement: RequirementSpec,
        configurations: Iterable[ConfigurationSpec],
        seeds: Iterable[int],
        fixture_id: str,
        package_id: str,
        execution_budget: Optional[ExecutionBudget],
        actor_role: Literal["maintainer", "user"],
        qualification_approved: bool,
        fixture_allowlisted: bool,
        repair_approved: bool,
        probe: Optional[ScientificSplitArtifact],
        artifact: Optional[QualificationArtifact],
        probe_max_cells: Optional[int],
        pairing_strategy: Literal[
            "random", "within_cluster", "between_cluster", "mixed"
        ],
        cluster_key: Optional[str],
        rerun_command: str,
        tool_name: str,
        tool_version: str,
        trace: TraceContext,
    ) -> OrchestrationResult:
        configurations = list(configurations)
        seeds = list(seeds)
        budget = RunBudgetLedger(limits=execution_budget or ExecutionBudget())
        trace_file = self.trace_root / orchestration_id / "trace.jsonl"
        tracker = _StateTracker(orchestration_id, requirement.request_id, trace_file)
        instrumentation = trace.instrumentation()
        with instrumentation.span(
            stage=TraceStage.RUNTIME_BIND,
            component="execution_orchestrator",
            operation="resolve_controlled_runtime",
            exception_error_code="runtime_bind_failed",
        ) as runtime_span:
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
            runtime_span.add_output_ref(
                record_type="tool_contract",
                record_id=contract.contract_id,
                relation="bound",
            )
            runtime_span.add_output_ref(
                record_type="runtime_environment",
                record_id=environment.environment_id,
                relation="bound",
            )
            runtime_span.add_decision(
                decision_type="runtime_selection",
                outcome="bound",
                reason_code="reviewed_contract_environment_bound",
                rule_version="controlled_runtime_v0",
            )
            runtime_span.succeed()

        with instrumentation.span(
            stage=TraceStage.STATE_INSPECTION,
            component="execution_orchestrator",
            operation="profile_qualification_input",
            exception_error_code="state_inspection_failed",
        ) as state_span:
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
            state_span.add_output_ref(
                record_type="data_profile",
                record_id=profile.profile_id,
                relation="profiled",
                content_hash=profile.file_hash or None,
            )
            state_span.set_counter("cell_count", profile.n_cells)
            state_span.set_counter("feature_count", profile.n_genes)
            if profile.is_blocked:
                state_span.blocked(
                    decision_type="qualification_input_state",
                    outcome="blocked",
                    reason_code="data_profile_blocked",
                    rule_version="controlled_input_v0",
                )
            else:
                state_span.succeed()

        with instrumentation.span(
            stage=TraceStage.PLANNING,
            component="execution_orchestrator",
            operation="compile_qualification_plan",
            input_refs=[
                {
                    "record_type": "data_profile",
                    "record_id": profile.profile_id,
                    "relation": "planning_context",
                    "content_hash": profile.file_hash or None,
                },
                {
                    "record_type": "tool_contract",
                    "record_id": contract.contract_id,
                    "relation": "planning_context",
                },
            ],
            exception_error_code="controlled_planning_failed",
        ) as planning_span:
            planning_gate = self.contract_registry.planning_gate(
                contract,
                data_profile=profile,
            )
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
            planning_span.add_output_ref(
                record_type="workflow_plan",
                record_id=plan.plan_id,
                relation="planned",
            )
            planning_span.set_counter("planned_step_count", len(plan.steps))
            if (
                profile.is_blocked
                or not planning_gate.allowed
                or plan.plan_status == "blocked"
            ):
                planning_span.blocked(
                    decision_type="controlled_planning_gate",
                    outcome="blocked",
                    reason_code="controlled_plan_blocked",
                    rule_version="controlled_planning_v0",
                )
            else:
                planning_span.succeed()
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
        policy_issues = [
            issue
            for issue in authorization_issues
            if issue != "qualification_not_approved"
        ]
        with instrumentation.span(
            stage=TraceStage.POLICY,
            component="execution_orchestrator",
            operation="evaluate_qualification_policy",
            exception_error_code="qualification_policy_failed",
        ) as policy_span:
            if policy_issues:
                policy_span.blocked(
                    decision_type="qualification_policy",
                    outcome="blocked",
                    reason_code=policy_issues[0],
                    rule_version="qualification_policy_v0",
                )
            else:
                policy_span.add_decision(
                    decision_type="qualification_policy",
                    outcome="allowed",
                    reason_code="maintainer_fixture_policy_satisfied",
                    rule_version="qualification_policy_v0",
                )
                policy_span.succeed()
        with instrumentation.span(
            stage=TraceStage.APPROVAL,
            component="execution_orchestrator",
            operation="verify_qualification_approval",
            exception_error_code="qualification_approval_failed",
        ) as approval_span:
            if qualification_approved:
                approval_span.add_decision(
                    decision_type="qualification_approval",
                    outcome="approved",
                    reason_code="qualification_approval_present",
                    rule_version="qualification_approval_v0",
                )
                approval_span.succeed()
            else:
                approval_span.blocked(
                    decision_type="qualification_approval",
                    outcome="blocked",
                    reason_code="qualification_not_approved",
                    rule_version="qualification_approval_v0",
                )
        if authorization_issues:
            tracker.transition(
                OrchestratorState.BLOCKED,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                warnings=authorization_issues,
            )
            raise PermissionError(";".join(authorization_issues))

        with instrumentation.span(
            stage=TraceStage.EXECUTION,
            component="execution_orchestrator",
            operation="run_initial_qualification_batch",
            input_refs=[
                {
                    "record_type": "workflow_plan",
                    "record_id": plan.plan_id,
                    "relation": "executes",
                }
            ],
            exception_error_code="controlled_execution_batch_failed",
        ) as execution_span:
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
            execution_span.add_input_ref(
                record_type="qualification_artifact",
                record_id=active_artifact.artifact_id,
                relation="executes_on",
                content_hash=active_artifact.sha256,
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
            _record_execution_batch_trace(
                instrumentation=instrumentation,
                span=execution_span,
                batch=initial_batch,
            )
        batches = [initial_batch]
        with instrumentation.span(
            stage=TraceStage.VALIDATION,
            component="execution_orchestrator",
            operation="record_initial_validation_evidence",
            exception_error_code="validation_recording_failed",
        ) as validation_span:
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
            _record_validation_batch_trace(
                span=validation_span,
                batch=initial_batch,
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
            blocker_count_before = len(critical_blockers)
            with instrumentation.span(
                stage=TraceStage.REPAIR,
                component="execution_orchestrator",
                operation="evaluate_repair_candidates",
                exception_error_code="repair_evaluation_failed",
            ) as repair_span:
                for run, validation, seed in failed_pairs:
                    processed_failed_run_ids.add(run.run_id)
                    repair_span.add_input_ref(
                        record_type="validation_record",
                        record_id=validation.validation_id,
                        relation="evaluates_for_repair",
                    )
                    proposal = self.repair_policy.propose(
                        run=run,
                        validation=validation,
                        contract=contract,
                        expected_cells=active_artifact.expected_cells,
                        previous_repairs_for_parent=sum(
                            item.parent_run_id == run.run_id
                            or item.new_run_id == run.run_id
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
                    if (
                        route.route == RouterRoute.BLOCKED
                        or reason in NON_REPAIRABLE_REASONS
                    ):
                        critical_blockers.extend(route.reasons or [reason.value])
                        continue
                    if proposal is None or not budget_available:
                        continue
                    if isinstance(active_probe, ScientificSplitArtifact) and (
                        active_probe.split_role == "evaluation"
                        and proposal.repair_type != RepairType.RETRY_SAME_REQUEST_ONCE
                    ):
                        critical_blockers.append(
                            "scientific_evaluation_parameter_repair_forbidden"
                        )
                        continue
                    repair_proposals.append(proposal)
                    pending.append((run, validation, proposal, seed))
                    repair_span.add_output_ref(
                        record_type="repair_proposal",
                        record_id=proposal.proposal_id,
                        relation="proposed",
                    )
                repair_span.set_counter("failed_run_count", len(failed_pairs))
                repair_span.set_counter("proposal_count", len(pending))
                if pending:
                    repair_span.add_decision(
                        decision_type="repair_policy",
                        outcome="proposed",
                        reason_code="bounded_repair_proposed",
                        rule_version="repair_policy_v0",
                    )
                    repair_span.succeed()
                elif len(critical_blockers) > blocker_count_before:
                    repair_span.blocked(
                        decision_type="repair_policy",
                        outcome="blocked",
                        reason_code="repair_policy_blocked",
                        rule_version="repair_policy_v0",
                    )
                else:
                    repair_span.skipped(
                        decision_type="repair_policy",
                        outcome="skipped",
                        reason_code="repair_not_available",
                        rule_version="repair_policy_v0",
                    )

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
            with instrumentation.span(
                stage=TraceStage.APPROVAL,
                component="execution_orchestrator",
                operation="verify_repair_approval",
                exception_error_code="repair_approval_failed",
            ) as repair_approval_span:
                approved_pending = pending if repair_approved else []
                repair_approval_span.set_counter("proposal_count", len(pending))
                if approved_pending:
                    repair_approval_span.add_decision(
                        decision_type="repair_approval",
                        outcome="approved",
                        reason_code="repair_approval_present",
                        rule_version="repair_approval_v0",
                    )
                    repair_approval_span.succeed()
                else:
                    repair_approval_span.blocked(
                        decision_type="repair_approval",
                        outcome="blocked",
                        reason_code="repair_approval_missing",
                        rule_version="repair_approval_v0",
                    )
            if not approved_pending:
                break
            with instrumentation.span(
                stage=TraceStage.EXECUTION,
                component="execution_orchestrator",
                operation="run_repair_batch",
                exception_error_code="repair_execution_failed",
            ) as repair_execution_span:
                tracker.transition(
                    OrchestratorState.RUNNING,
                    plan_id=plan.plan_id,
                    contract=contract,
                    environment_id=environment.environment_id,
                    repair_count=len(repair_actions),
                )
                new_batches: list[ExperimentBatchResult] = []
                for index, (parent_run, _, proposal, seed) in enumerate(
                    approved_pending
                ):
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
                    experiment_id = (
                        f"{orchestration_id}-repair-{repair_round}-{index}"
                    )
                    expected_run_id = (
                        f"{experiment_id}-{repaired_config.configuration_id}-seed-{seed}"
                    )
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
                    repair_execution_span.add_input_ref(
                        record_type="repair_action",
                        record_id=action.action_id,
                        relation="executes",
                    )
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
                combined_repair_batch = _combine_batches(
                    orchestration_id=(
                        f"{orchestration_id}-repair-observation-{repair_round}"
                    ),
                    probe_hash=active_probe.probe_hash,
                    batches=new_batches,
                )
                _record_execution_batch_trace(
                    instrumentation=instrumentation,
                    span=repair_execution_span,
                    batch=combined_repair_batch,
                )
            batches.extend(new_batches)
            with instrumentation.span(
                stage=TraceStage.VALIDATION,
                component="execution_orchestrator",
                operation="record_repair_validation_evidence",
                exception_error_code="repair_validation_recording_failed",
            ) as repair_validation_span:
                _record_batch_observations(
                    tracker=tracker,
                    batch=combined_repair_batch,
                    contract=contract,
                    environment_id=environment.environment_id,
                    repair_count=len(repair_actions),
                    lineage={
                        item.new_run_id: item.parent_run_id
                        for item in repair_actions
                    },
                )
                repair_round += 1
                tracker.transition(
                    OrchestratorState.VALIDATING,
                    plan_id=plan.plan_id,
                    contract=contract,
                    environment_id=environment.environment_id,
                    repair_count=len(repair_actions),
                    warnings=[
                        failure for batch in new_batches for failure in batch.failures
                    ],
                )
                _record_validation_batch_trace(
                    span=repair_validation_span,
                    batch=combined_repair_batch,
                )

        with instrumentation.span(
            stage=TraceStage.DECISION,
            component="execution_orchestrator",
            operation="aggregate_and_select_candidate",
            exception_error_code="candidate_decision_failed",
        ) as decision_span:
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
            for candidate in candidates:
                decision_span.add_input_ref(
                    record_type="candidate_evaluation",
                    record_id=candidate.candidate_id,
                    relation="considers",
                )
            tracker.transition(
                OrchestratorState.DECIDING,
                plan_id=plan.plan_id,
                contract=contract,
                environment_id=environment.environment_id,
                repair_count=len(repair_actions),
            )
            decision = self.pareto.decide(candidates, preference="performance")
            decision_span.add_output_ref(
                record_type="decision_record",
                record_id=decision.decision_id,
                relation="decided",
            )
            decision_span.set_counter("candidate_count", len(candidates))
            if decision.recommended_candidate_id is None:
                decision_span.blocked(
                    decision_type="candidate_selection",
                    outcome="blocked",
                    reason_code="no_eligible_candidate",
                    rule_version="pareto_decision_v0",
                    record_ref={
                        "record_type": "decision_record",
                        "record_id": decision.decision_id,
                        "relation": "evidence",
                    },
                )
            else:
                decision_span.add_decision(
                    decision_type="candidate_selection",
                    outcome="selected",
                    reason_code="pareto_candidate_selected",
                    rule_version="pareto_decision_v0",
                    record_ref={
                        "record_type": "decision_record",
                        "record_id": decision.decision_id,
                        "relation": "evidence",
                    },
                )
                decision_span.succeed()

        with instrumentation.span(
            stage=TraceStage.PACKAGE,
            component="execution_orchestrator",
            operation="build_reproducibility_package",
            exception_error_code="reproducibility_package_failed",
        ) as package_span:
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
            blockers = sorted(
                set(
                    critical_blockers
                    + (["all_candidates_failed"] if all_failed else [])
                )
            )
            terminal = (
                OrchestratorState.BLOCKED
                if blockers
                else OrchestratorState.COMPLETED
            )
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
            package_span.add_input_ref(
                record_type="orchestration_record",
                record_id=orchestration_id,
                relation="packages",
            )
            package_span.add_output_ref(
                record_type="reproducibility_package",
                record_id=package.package_id,
                relation="packaged",
            )
            if package.complete and package.manifest_hashes_valid:
                package_span.succeed()
            else:
                package_span.partial(
                    decision_type="package_integrity",
                    outcome="partial",
                    reason_code="package_integrity_incomplete",
                    rule_version="reproducibility_package_v0",
                )
        return OrchestrationResult(
            orchestration_id=orchestration_id,
            canonical_trace_id=trace.trace_id,
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


def _new_controlled_execution_trace(
    *,
    request_id: str,
    parent_trace_id: Optional[str],
    handoff_id: Optional[str],
    parent_request_id: Optional[str],
    original_plan_id: Optional[str],
) -> TraceContext:
    try:
        trace_request_id = trace_correlation_id(
            request_id,
            kind=TraceCorrelationKind.REQUEST,
        )
    except (TracePrivacyError, TraceValidationError):
        trace_request_id = f"request-ref:opaque:{uuid.uuid4().hex}"
    try:
        return TraceContext.new_request(
            trace_kind=TraceKind.CONTROLLED_EXECUTION,
            request_id=trace_request_id,
            parent_trace_id=parent_trace_id,
            handoff_id=handoff_id,
            parent_request_id=parent_request_id,
            original_plan_id=original_plan_id,
        )
    except (TracePrivacyError, TraceValidationError):
        return TraceContext.new_request(
            trace_kind=TraceKind.CONTROLLED_EXECUTION,
            request_id=trace_request_id,
        )


def _set_controlled_execution_outcome(
    trace: TraceContext,
    result: OrchestrationResult,
) -> None:
    instrumentation = trace.instrumentation()
    if result.final_state == OrchestratorState.COMPLETED:
        instrumentation.set_request_outcome(TraceStatus.SUCCESS)
    elif result.final_state == OrchestratorState.BLOCKED:
        instrumentation.set_request_outcome(
            TraceStatus.BLOCKED,
            decision_type="controlled_execution_outcome",
            outcome="blocked",
            reason_code="controlled_execution_blocked",
            rule_version="controlled_execution_v0",
        )
    else:
        instrumentation.set_request_outcome(
            TraceStatus.FAILED,
            error_code="controlled_execution_failed",
        )


def _record_execution_batch_trace(
    *,
    instrumentation: Any,
    span: Any,
    batch: ExperimentBatchResult,
) -> None:
    runtime_trace_ids: set[str] = set()
    for run in batch.execution_runs:
        span.add_output_ref(
            record_type="execution_run",
            record_id=run.run_id,
            relation="executed",
        )
        if run.trace_id in runtime_trace_ids:
            continue
        runtime_trace_ids.add(run.trace_id)
        instrumentation.add_link(
            link_type=TraceLinkType.LEGACY_TRACE,
            target_type="runtime_execution_record",
            target_id=run.trace_id,
        )
    span.set_counter("requested_run_count", batch.requested_run_count)
    span.set_counter("completed_run_count", batch.completed_run_count)
    incomplete = bool(batch.failures) or any(
        run.status != "succeeded" for run in batch.execution_runs
    )
    if incomplete:
        span.partial(
            decision_type="execution_batch",
            outcome="partial",
            reason_code="execution_batch_incomplete",
            rule_version="controlled_execution_v0",
        )
    else:
        span.succeed()


def _record_validation_batch_trace(
    *,
    span: Any,
    batch: ExperimentBatchResult,
) -> None:
    for validation in batch.validation_results:
        span.add_output_ref(
            record_type="validation_record",
            record_id=validation.validation_id,
            relation="validated",
        )
    passed_count = sum(item.passed for item in batch.validation_results)
    span.set_counter("validation_count", len(batch.validation_results))
    span.set_counter("validation_passed_count", passed_count)
    if batch.validation_results and passed_count == len(batch.validation_results):
        span.succeed()
    else:
        span.partial(
            decision_type="validation_batch",
            outcome="partial",
            reason_code="validation_failures_detected",
            rule_version="controlled_validation_v0",
        )


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
