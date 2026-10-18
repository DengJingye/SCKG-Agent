from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import Field, model_validator

from core.deterministic_router import DeterministicRouter
from core.execution_models import (
    CandidateEvaluation,
    DecisionResult,
    ExecutionRequest,
    ExecutionRun,
    ExperimentBatchResult,
    ExperimentRunRecord,
    QualificationArtifact,
    ReproducibilityPackageResult,
    RequirementSpec,
    RestrictedUserExecutionContext,
    StrictModel,
    ValidationResult,
)
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from engine.pareto_decision import ParetoDecisionEngine
from execution.approval_service import ApprovalService, parameter_hash
from execution.candidate_aggregator import CandidateAggregator
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import (
    ExecutionPair,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from execution.experiment_runner import build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.repair_policy import (
    RepairAction,
    RepairPolicy,
    RepairProposal,
    RepairType,
    apply_repair_parameters,
)
from execution.reproducibility_packager import ReproducibilityPackager
from execution.user_workspace import UserWorkspaceService
from execution.validators.doublet import DoubletValidator
from execution.validators.integration import IntegrationValidator
from execution.validators.scdblfinder import ScDblFinderValidator


SAFE_USER_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class LocalUserAllowance(StrictModel):
    allowance_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    allowed_pairs: list[ExecutionPair]
    allowed_artifact_ids: list[str]
    allowed_data_scopes: list[str]
    max_runs: int = Field(ge=1, le=100)
    runs_consumed: int = Field(default=0, ge=0)
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None
    local_only: bool = True

    @model_validator(mode="after")
    def validate_allowance(self) -> "LocalUserAllowance":
        if self.expires_at <= self.created_at:
            raise ValueError("local user allowance must expire after creation")
        if self.runs_consumed > self.max_runs:
            raise ValueError("local user run allowance exhausted")
        if not self.local_only:
            raise ValueError("Phase 6B does not support remote users")
        return self


class LocalUserAllowanceDecision(StrictModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


class LocalUserAllowlist:
    def __init__(
        self,
        *,
        root: Path = PROJECT_ROOT / ".sckg_exec" / "registry" / "local-users",
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_log = self.root / "audit.jsonl"
        self._lock = threading.Lock()

    def allow_user(
        self,
        *,
        user_id: str,
        allowed_pairs: list[ExecutionPair],
        allowed_artifact_ids: list[str],
        allowed_data_scopes: list[str],
        max_runs: int,
        ttl: timedelta = timedelta(hours=1),
        now: datetime | None = None,
    ) -> LocalUserAllowance:
        if not user_id or SAFE_USER_ID.fullmatch(user_id) is None:
            raise ValueError("anonymous or unsafe local user id")
        current = now or datetime.now(timezone.utc)
        allowance = LocalUserAllowance(
            allowance_id=f"local-user-{uuid.uuid4().hex}",
            user_id=user_id,
            allowed_pairs=allowed_pairs,
            allowed_artifact_ids=sorted(set(allowed_artifact_ids)),
            allowed_data_scopes=sorted(set(allowed_data_scopes)),
            max_runs=max_runs,
            expires_at=current + ttl,
            created_at=current,
        )
        self._write(allowance)
        self._audit("local_user_allowed", allowance)
        return allowance

    def validate(
        self,
        *,
        user_id: str,
        pair: ExecutionPair,
        artifact_id: str,
        data_scope: str,
        requested_runs: int = 1,
        access_origin: str = "local",
        now: datetime | None = None,
    ) -> LocalUserAllowanceDecision:
        if not user_id or access_origin != "local":
            return LocalUserAllowanceDecision(
                allowed=False, reasons=["anonymous_or_remote_user_forbidden"]
            )
        try:
            allowance = self._load(user_id)
        except KeyError:
            return LocalUserAllowanceDecision(
                allowed=False, reasons=["local_user_not_allowlisted"]
            )
        reasons: list[str] = []
        current = now or datetime.now(timezone.utc)
        if allowance.revoked_at is not None:
            reasons.append("local_user_allowance_revoked")
        if current >= allowance.expires_at:
            reasons.append("local_user_allowance_expired")
        if pair not in allowance.allowed_pairs:
            reasons.append("tool_environment_pair_not_allowed_for_user")
        if artifact_id not in allowance.allowed_artifact_ids:
            reasons.append("artifact_not_allowed_for_user")
        if data_scope not in allowance.allowed_data_scopes:
            reasons.append("data_scope_not_allowed_for_user")
        if requested_runs < 1 or allowance.runs_consumed + requested_runs > allowance.max_runs:
            reasons.append("local_user_run_budget_exceeded")
        return LocalUserAllowanceDecision(
            allowed=not reasons, reasons=sorted(set(reasons))
        )

    def consume_run(
        self,
        *,
        user_id: str,
        pair: ExecutionPair,
        artifact_id: str,
        data_scope: str,
        now: datetime | None = None,
    ) -> LocalUserAllowance:
        with self._lock:
            decision = self.validate(
                user_id=user_id,
                pair=pair,
                artifact_id=artifact_id,
                data_scope=data_scope,
                requested_runs=1,
                now=now,
            )
            if not decision.allowed:
                raise PermissionError(";".join(decision.reasons))
            allowance = self._load(user_id)
            updated = allowance.model_copy(
                update={"runs_consumed": allowance.runs_consumed + 1}
            )
            self._write(updated)
            self._audit("local_user_run_consumed", updated)
            return updated

    def revoke(self, user_id: str, *, now: datetime | None = None) -> LocalUserAllowance:
        allowance = self._load(user_id).model_copy(
            update={"revoked_at": now or datetime.now(timezone.utc)}
        )
        self._write(allowance)
        self._audit("local_user_revoked", allowance)
        return allowance

    def get(self, user_id: str) -> LocalUserAllowance:
        if not user_id or SAFE_USER_ID.fullmatch(user_id) is None:
            raise ValueError("anonymous or unsafe local user id")
        return self._load(user_id)

    def _path(self, user_id: str) -> Path:
        return self.root / f"{user_id}.json"

    def _load(self, user_id: str) -> LocalUserAllowance:
        path = self._path(user_id)
        if not path.is_file():
            raise KeyError(user_id)
        return LocalUserAllowance.model_validate_json(path.read_text(encoding="utf-8"))

    def _write(self, allowance: LocalUserAllowance) -> None:
        path = self._path(allowance.user_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(allowance.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _audit(self, event: str, allowance: LocalUserAllowance) -> None:
        payload = {
            "event": event,
            "allowance_id": allowance.allowance_id,
            "user_id": allowance.user_id,
            "runs_consumed": allowance.runs_consumed,
            "max_runs": allowance.max_runs,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.audit_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


class LocalUserExecutionResult(StrictModel):
    user_id: str
    artifact_id: str
    plan_id: str
    tool_name: str
    tool_version: str
    execution_runs: list[ExecutionRun]
    validation_results: list[ValidationResult]
    repair_proposals: list[RepairProposal]
    repair_actions: list[RepairAction]
    candidate_evaluations: list[CandidateEvaluation]
    decision_result: DecisionResult
    package_result: ReproducibilityPackageResult
    approval_uses_consumed: int = Field(ge=1)
    input_data_copied: bool = False


class LocalUserService:
    """Execute an exactly approved plan for an allowlisted local user."""

    def __init__(
        self,
        *,
        orchestrator: ExecutionOrchestrator,
        data_registry: DataRegistry,
        approval_service: ApprovalService,
        allowlist: LocalUserAllowlist,
        workspace: UserWorkspaceService,
        contract_registry: ToolContractRegistry | None = None,
        environment_registry: EnvironmentRegistry | None = None,
        router: DeterministicRouter | None = None,
        policy: ExecutionPolicy | None = None,
        aggregator: CandidateAggregator | None = None,
        pareto: ParetoDecisionEngine | None = None,
        repair_policy: RepairPolicy | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.data_registry = data_registry
        self.approval_service = approval_service
        self.allowlist = allowlist
        self.workspace = workspace
        self.environment_registry = environment_registry or orchestrator.environment_registry
        self.contract_registry = contract_registry or orchestrator.contract_registry
        self.router = router or orchestrator.router
        self.policy = policy or ExecutionPolicy()
        self.aggregator = aggregator or CandidateAggregator()
        self.pareto = pareto or ParetoDecisionEngine()
        self.repair_policy = repair_policy or RepairPolicy()

    def execute_approved_plan(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: str,
        execution_approval_id: str,
        request_id: str,
        query: str,
        parameters: dict[str, Any],
        tool_name: str,
        tool_version: str,
        package_id: str,
        requested_runs: int = 2,
        data_scope: str = "synthetic_fixture",
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> LocalUserExecutionResult:
        if not 1 <= requested_runs <= 3:
            raise ValueError("restricted local execution requires 1-3 runs")
        preparation = self.orchestrator.prepare_user_execution(
            user_id=user_id,
            artifact_id=artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=tool_name,
            tool_version=tool_version,
        )
        if (
            not preparation.data_access.allowed
            or preparation.execution_approval is None
            or not preparation.execution_approval.allowed
            or preparation.profile is None
            or preparation.plan is None
            or preparation.approval_scope is None
        ):
            raise PermissionError(";".join(preparation.reasons or ["execution_not_approved"]))

        contract = self.contract_registry.load(tool_name, tool_version)
        environment = self.environment_registry.get(contract.environment_id)
        pair = ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=environment.environment_id,
        )
        allowance_decision = self.allowlist.validate(
            user_id=user_id,
            pair=pair,
            artifact_id=artifact_id,
            data_scope=data_scope,
            requested_runs=requested_runs,
        )
        if not allowance_decision.allowed:
            raise PermissionError(";".join(allowance_decision.reasons))
        policy_decision = self.policy.authorize(
            actor_role="user",
            access_origin="local",
            user_allowlisted=True,
            contract=contract,
            environment=environment,
        )
        if not policy_decision.allowed:
            raise PermissionError(";".join(policy_decision.reasons))

        validated_parameters = self.contract_registry.validate_parameters(
            contract, parameters
        )
        if parameter_hash(validated_parameters) != preparation.approval_scope.parameter_hash:
            raise PermissionError("approval_parameter_hash_mismatch")
        registered = self.data_registry.get(artifact_id, user_id=user_id)
        input_path = self.data_registry.resolve_path(artifact_id, user_id=user_id)
        qualification_artifact = _qualification_artifact(
            input_path=input_path,
            artifact_id=artifact_id,
            sha256=registered.sha256,
        )
        if data_scope == "synthetic_fixture" and not qualification_artifact.synthetic:
            raise PermissionError("allowlisted synthetic fixture required")

        configuration = build_configuration(
            configuration_id=f"user-{contract.tool_name.casefold()}-approved",
            parameters=validated_parameters,
            provenance={},
            source=(
                "contract_default"
                if validated_parameters == contract.default_parameters
                else "development_probe_search"
            ),
            contract=contract,
            frozen=True,
        )
        executor = LocalControlledExecutor(
            run_root=self.workspace.root / user_id / "runs",
            approved_input_root=_approved_root(input_path, self.data_registry),
            wrapper_registry=self.orchestrator.executor.wrapper_registry,
            contract_registry=self.contract_registry,
            environment_registry=self.environment_registry,
            execution_policy=self.policy,
        )
        validator = _validator_for_contract(contract)
        runs: list[ExecutionRun] = []
        validations: list[ValidationResult] = []
        records: list[ExperimentRunRecord] = []
        proposals: list[RepairProposal] = []
        actions: list[RepairAction] = []
        approval_snapshot = None

        for index in range(requested_runs):
            if index > 0 and cancellation_requested is not None and cancellation_requested():
                break
            run, validation, consumed = self._execute_one(
                user_id=user_id,
                artifact_id=artifact_id,
                data_grant_id=data_grant_id,
                approval_id=execution_approval_id,
                approval_scope=preparation.approval_scope,
                allowance_pair=pair,
                data_scope=data_scope,
                contract=contract,
                environment_id=environment.environment_id,
                plan_id=preparation.plan.plan_id,
                parameters=validated_parameters,
                parameter_provenance=configuration.parameter_provenance,
                qualification_artifact=qualification_artifact,
                executor=executor,
                validator=validator,
                request_id=f"{request_id}-run-{index + 1}",
                run_id=f"{request_id}-run-{index + 1}",
            )
            approval_snapshot = consumed
            runs.append(run)
            validations.append(validation)
            records.append(
                _run_record(run, validation, configuration, registered.sha256, index)
            )

            if validation.passed or run.status == "cancelled":
                continue
            proposal = self.repair_policy.propose(
                run=run,
                validation=validation,
                contract=contract,
                expected_cells=qualification_artifact.expected_cells,
            )
            if proposal is None:
                continue
            proposals.append(proposal)
            repaired_parameters = apply_repair_parameters(run.parameters, proposal)
            if (
                proposal.repair_type != RepairType.RETRY_SAME_REQUEST_ONCE
                or parameter_hash(repaired_parameters)
                != preparation.approval_scope.parameter_hash
                or consumed.uses_consumed >= consumed.max_uses
            ):
                continue
            repair_run_id = f"{request_id}-repair-{len(actions) + 1}"
            action = self.repair_policy.apply(
                proposal=proposal, new_run_id=repair_run_id, approved=True
            )
            repair_run, repair_validation, consumed = self._execute_one(
                user_id=user_id,
                artifact_id=artifact_id,
                data_grant_id=data_grant_id,
                approval_id=execution_approval_id,
                approval_scope=preparation.approval_scope,
                allowance_pair=pair,
                data_scope=data_scope,
                contract=contract,
                environment_id=environment.environment_id,
                plan_id=preparation.plan.plan_id,
                parameters=repaired_parameters,
                parameter_provenance=configuration.parameter_provenance,
                qualification_artifact=qualification_artifact,
                executor=executor,
                validator=validator,
                request_id=repair_run_id,
                run_id=repair_run_id,
            )
            approval_snapshot = consumed
            actions.append(action)
            runs.append(repair_run)
            validations.append(repair_validation)
            records.append(
                _run_record(
                    repair_run,
                    repair_validation,
                    configuration,
                    registered.sha256,
                    requested_runs + len(actions),
                )
            )

        batch = ExperimentBatchResult(
            experiment_id=f"experiment-{request_id}",
            split_role="development",
            probe_hash=registered.sha256,
            configurations=[configuration],
            execution_runs=runs,
            validation_results=validations,
            run_records=records,
            requested_run_count=len(runs),
            completed_run_count=len(runs),
            failures=[
                f"{run.run_id}:{run.error_type or run.status}"
                for run in runs
                if run.status != "succeeded"
            ],
        )
        candidates = self.aggregator.aggregate(batch=batch, contract=contract)
        decision = self.pareto.decide(candidates)
        requirement = RequirementSpec(
            request_id=request_id,
            query=query,
            task=contract.task,
            input_path=registered.redacted_path,
            input_object_type=registered.artifact_type,
            batch_key="batch" if str(contract.task) == "batch_integration" else None,
            label_key=(
                "cell_type" if str(contract.task) == "batch_integration" else None
            ),
            output_goal=(
                "batch-corrected embedding with biology-conservation diagnostics"
                if str(contract.task) == "batch_integration"
                else "doublet scores and calls"
            ),
            data_access_authorized=True,
            execution_authorized=True,
        )
        self.workspace.reserve_package(user_id=user_id, package_id=package_id)
        packager = ReproducibilityPackager(
            package_root=self.workspace.root / user_id / "packages"
        )
        assert approval_snapshot is not None
        package = packager.build_restricted_user_execution(
            package_id=package_id,
            user_id=user_id,
            artifact_id=artifact_id,
            input_hash=registered.sha256,
            requirement=requirement,
            data_profile=preparation.profile,
            workflow_plan=preparation.plan,
            contract=contract,
            environment=environment,
            execution_runs=runs,
            validation_results=validations,
            candidate_evaluations=candidates,
            decision_result=decision,
            approval_snapshot=approval_snapshot.model_dump(mode="json"),
            repair_proposals=proposals,
            repair_actions=actions,
        )
        self.workspace.mark_completed(
            resource_type="package",
            user_id=user_id,
            resource_id=package_id,
        )
        return LocalUserExecutionResult(
            user_id=user_id,
            artifact_id=artifact_id,
            plan_id=preparation.plan.plan_id,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            execution_runs=runs,
            validation_results=validations,
            repair_proposals=proposals,
            repair_actions=actions,
            candidate_evaluations=candidates,
            decision_result=decision,
            package_result=package,
            approval_uses_consumed=approval_snapshot.uses_consumed,
        )

    def _execute_one(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: str,
        approval_id: str,
        approval_scope,
        allowance_pair: ExecutionPair,
        data_scope: str,
        contract,
        environment_id: str,
        plan_id: str,
        parameters: dict[str, Any],
        parameter_provenance: dict[str, Any],
        qualification_artifact: QualificationArtifact,
        executor: LocalControlledExecutor,
        validator,
        request_id: str,
        run_id: str,
    ):
        approval_validation = self.approval_service.validate_execution_approval(
            approval_id, expected_scope=approval_scope
        )
        route = self.router.route_user_authorization(
            data_access=self.approval_service.validate_data_access(
                data_grant_id,
                user_id=user_id,
                artifact_id=artifact_id,
            ),
            execution_approval=approval_validation,
            execution_backend_enabled=True,
        )
        if not route.execution_allowed:
            raise PermissionError(";".join(route.reasons))
        allowance = self.allowlist.consume_run(
            user_id=user_id,
            pair=allowance_pair,
            artifact_id=artifact_id,
            data_scope=data_scope,
        )
        consumed = self.approval_service.consume_execution_approval(
            approval_id,
            expected_scope=approval_scope,
            request_id=request_id,
        )
        self.workspace.reserve_run(user_id=user_id, run_id=run_id)
        request = ExecutionRequest(
            request_id=request_id,
            run_id=run_id,
            trace_id=f"trace-{run_id}",
            plan_id=plan_id,
            step_id="run-approved-local-tool",
            wrapper_id=contract.wrapper_id,
            environment_id=environment_id,
            input_artifact_id=artifact_id,
            parameters=parameters,
            parameter_provenance=parameter_provenance,
            timeout_seconds=int(
                contract.resource_requirements["qualification_timeout_seconds"]
            ),
            actor={"actor_id": user_id, "role": "user"},
            qualification={
                "mode": False,
                "purpose": "synthetic_qualification",
                "authorized": False,
                "fixture_allowlisted": False,
                "fixture_id": qualification_artifact.fixture_id,
            },
            execution_mode="restricted_local_user",
            user_execution=RestrictedUserExecutionContext(
                user_id=user_id,
                artifact_id=artifact_id,
                approval_id=approval_id,
                allowance_id=allowance.allowance_id,
                request_fingerprint=approval_scope.fingerprint,
                contract_version=contract.contract_version,
                tool_name=contract.tool_name,
                tool_version=contract.tool_version,
                environment_id=environment_id,
                parameter_hash=parameter_hash(parameters),
                approval_consumption_index=consumed.uses_consumed,
                approval_max_uses=consumed.max_uses,
            ),
        )
        self.workspace.mark_run_running(user_id=user_id, run_id=run_id)
        run = executor.execute(
            request=request,
            artifact=qualification_artifact,
            contract=contract,
            router_decision=route,
            cancellation_checker=lambda: self.workspace.cancellation_reason(
                user_id=user_id, run_id=run_id
            ),
        )
        self.workspace.mark_run_terminal(
            user_id=user_id, run_id=run_id, status=run.status
        )
        if str(contract.task) == "batch_integration":
            validation = validator.validate(
                run,
                expected_cells=qualification_artifact.expected_cells,
                expected_input_path=qualification_artifact.path,
                contract=contract,
            )
        else:
            validation = validator.validate(
                run,
                expected_cells=qualification_artifact.expected_cells,
            )
        return run, validation, consumed

def _qualification_artifact(
    *, input_path: Path, artifact_id: str, sha256: str
) -> QualificationArtifact:
    import anndata as ad

    adata = ad.read_h5ad(input_path, backed="r")
    metadata = dict(adata.uns.get("sckg_fixture") or {})
    expected_cells = int(adata.n_obs)
    adata.file.close()
    return QualificationArtifact(
        artifact_id=artifact_id,
        fixture_id=str(metadata.get("fixture_id", artifact_id)),
        path=str(input_path),
        sha256=sha256,
        synthetic=bool(metadata.get("synthetic", False)),
        public_dataset=bool(metadata.get("public_dataset", False)),
        user_data=bool(metadata.get("user_data", False)),
        accession=metadata.get("accession"),
        allowlisted=True,
        expected_cells=expected_cells,
    )


def _validator_for_contract(contract):
    if str(contract.task) == "batch_integration":
        return IntegrationValidator()
    if contract.tool_name.casefold() == "scdblfinder":
        return ScDblFinderValidator(contract)
    return DoubletValidator()


def _approved_root(path: Path, registry: DataRegistry) -> Path:
    resolved = path.resolve()
    for root in registry.approved_input_roots:
        try:
            resolved.relative_to(root)
            return root
        except ValueError:
            continue
    raise ValueError("registered path is outside approved roots")


def _run_record(
    run: ExecutionRun,
    validation: ValidationResult,
    configuration,
    probe_hash: str,
    seed: int,
) -> ExperimentRunRecord:
    return ExperimentRunRecord(
        run_id=run.run_id,
        configuration_id=configuration.configuration_id,
        configuration_hash=configuration.configuration_hash,
        seed=seed,
        split_role="development",
        probe_hash=probe_hash,
        parameters=run.parameters,
        parameter_provenance=run.parameter_provenance,
        run_status=run.status,
        validation_id=validation.validation_id,
        validation_passed=validation.passed,
        runtime_seconds=run.runtime_seconds,
        peak_memory_mb=run.peak_memory_mb,
    )
