from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from core.execution_models import (
    DataProfile,
    ExecutionGateResult,
    StrictModel,
    WorkflowPlan,
)
from core.runtime_pack_models import (
    EnvironmentProvisioningApproval,
    EnvironmentProvisioningPlan,
    PackInstallationRecord,
    RuntimeCapabilityProbe,
)
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import (
    ApprovalScope,
    ApprovalService,
    AuthorizationValidation,
    ExecutionApproval,
)
from execution.data_registry import DataRegistry, RegisteredDataArtifact
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import (
    ExecutionPair,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from execution.local_user_service import (
    LocalUserAllowlist,
    LocalUserExecutionResult,
    LocalUserService,
)
from execution.runtime_pack_manager import RuntimePackManager
from execution.user_workspace import UserWorkspaceService


APPROVAL_CONFIRMATIONS = {
    "data_confirmed",
    "tool_confirmed",
    "parameters_confirmed",
    "environment_confirmed",
}

LOCAL_PREVIEW_RECOVERABLE_BLOCKERS = frozenset(
    {
        "execution_policy_disabled",
        "local_user_not_allowlisted",
        "local_user_allowance_expired",
        "local_user_allowance_revoked",
        "tool_environment_pair_not_allowed_for_user",
        "artifact_not_allowed_for_user",
        "data_scope_not_allowed_for_user",
        "local_user_run_budget_exceeded",
    }
)


def local_preview_allowance_can_be_reissued(blockers: list[str]) -> bool:
    """Return true only when a new exact-scope allowance resolves every blocker."""
    unique = set(blockers)
    return bool(unique) and unique.issubset(LOCAL_PREVIEW_RECOVERABLE_BLOCKERS)


class ExecutionUIContext(StrictModel):
    user_id: str
    artifact: RegisteredDataArtifact
    tool_name: str
    tool_version: str
    environment_id: str
    policy_mode: ExecutionPolicyMode
    allowlisted: bool
    data_access: AuthorizationValidation
    execution_approval: AuthorizationValidation | None = None
    profile: DataProfile | None = None
    plan: WorkflowPlan | None = None
    approval_scope: ApprovalScope | None = None
    approval_fingerprint: str | None = None
    execution_gate: ExecutionGateResult
    runtime_pack: RuntimeCapabilityProbe | None = None
    runtime_route: str | None = None
    button_enabled: bool = False
    button_blockers: list[str] = Field(default_factory=list)


class ExecutionUIResultView(StrictModel):
    user_id: str
    tool_name: str
    run_statuses: list[dict[str, Any]]
    validation_results: list[dict[str, Any]]
    candidate_evaluations: list[dict[str, Any]]
    decision_result: dict[str, Any]
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    package_manifest: dict[str, Any] = Field(default_factory=dict)
    package_path_redacted: str
    package_complete: bool
    manifest_hashes_valid: bool
    input_data_copied: bool = False


class ExecutionUIJobStatus(StrictModel):
    job_id: str
    state: Literal[
        "queued", "running", "completed", "failed", "cancel_requested", "cancelled"
    ]
    expected_run_ids: list[str]
    result: LocalUserExecutionResult | None = None
    error_summary: str | None = None


class LocalPreviewEnablement(StrictModel):
    enabled: bool
    user_id: str
    artifact_id: str
    policy_mode: ExecutionPolicyMode
    tool_name: str = "Scrublet"
    environment_id: str = "scRNAseq"
    expires_at: str | None = None
    max_runs: int = 1
    blockers: list[str] = Field(default_factory=list)


class LocalPreviewApprovalResult(StrictModel):
    enablement: LocalPreviewEnablement
    approval: ExecutionApproval


@dataclass
class _ExecutionJob:
    job_id: str
    user_id: str
    expected_run_ids: list[str]
    future: Future[LocalUserExecutionResult]
    cancel_event: threading.Event
    cancel_requested: bool = False


class ExecutionUIService:
    """Thin local UI facade over the Phase 6A/6B authorization backend."""

    def __init__(
        self,
        *,
        data_registry: DataRegistry,
        approval_service: ApprovalService,
        execution_policy: ExecutionPolicy,
        local_user_service: LocalUserService,
        orchestrator: ExecutionOrchestrator,
        workspace: UserWorkspaceService,
        allowlist: LocalUserAllowlist,
        contract_registry: ToolContractRegistry,
        environment_registry: EnvironmentRegistry,
        runtime_pack_manager: RuntimePackManager | None = None,
        pool: ThreadPoolExecutor | None = None,
    ) -> None:
        self.data_registry = data_registry
        self.approval_service = approval_service
        self.execution_policy = execution_policy
        self.local_user_service = local_user_service
        self.orchestrator = orchestrator
        self.workspace = workspace
        self.allowlist = allowlist
        self.contract_registry = contract_registry
        self.environment_registry = environment_registry
        self.runtime_pack_manager = runtime_pack_manager or RuntimePackManager()
        self._pool = pool or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="sckg-local-execution"
        )
        self._jobs: dict[str, _ExecutionJob] = {}
        self._job_lock = threading.Lock()

    def list_artifacts(self, *, user_id: str) -> list[RegisteredDataArtifact]:
        return self.data_registry.list_for_user(user_id=user_id)

    def register_local_artifact(
        self, *, user_id: str, local_path: str
    ) -> RegisteredDataArtifact:
        return self.data_registry.register(user_id=user_id, path=Path(local_path))

    def artifact_path_authorized(self, *, user_id: str, artifact_id: str) -> bool:
        return self.data_registry.path_authorized(artifact_id, user_id=user_id)

    def user_allowlisted(self, *, user_id: str) -> bool:
        try:
            allowance = self.allowlist.get(user_id)
        except (KeyError, ValueError):
            return False
        return allowance.revoked_at is None and allowance.expires_at > _utc_now()

    def grant_profile_access(
        self, *, user_id: str, artifact_id: str
    ):
        self.data_registry.get(artifact_id, user_id=user_id)
        return self.approval_service.grant_data_access(
            user_id=user_id, artifact_id=artifact_id
        )

    def enable_local_preview(
        self,
        *,
        user_id: str,
        artifact_id: str,
        actor_role: str,
        ttl_minutes: int = 30,
        max_runs: int = 1,
    ) -> LocalPreviewEnablement:
        """Enable one fixed local Preview pair; this never approves a run."""
        self.data_registry.get(artifact_id, user_id=user_id)
        blockers: list[str] = []
        if actor_role != "maintainer":
            blockers.append("maintainer_role_required")
        if ttl_minutes < 5 or ttl_minutes > 120:
            blockers.append("preview_allowance_ttl_out_of_range")
        if max_runs < 1 or max_runs > 3:
            blockers.append("preview_run_budget_out_of_range")
        if blockers:
            return LocalPreviewEnablement(
                enabled=False,
                user_id=user_id,
                artifact_id=artifact_id,
                policy_mode=self.execution_policy.mode,
                max_runs=max_runs,
                blockers=blockers,
            )
        contract = self.contract_registry.load("Scrublet", "0.2.3")
        environment = self.environment_registry.get(contract.environment_id)
        pair = ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=environment.environment_id,
        )
        allowance = self.allowlist.allow_user(
            user_id=user_id,
            allowed_pairs=[pair],
            allowed_artifact_ids=[artifact_id],
            allowed_data_scopes=["representative_preview"],
            max_runs=max_runs,
            ttl=timedelta(minutes=ttl_minutes),
        )
        self.execution_policy.mode = ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS
        return LocalPreviewEnablement(
            enabled=True,
            user_id=user_id,
            artifact_id=artifact_id,
            policy_mode=self.execution_policy.mode,
            environment_id=environment.environment_id,
            expires_at=allowance.expires_at.isoformat(),
            max_runs=max_runs,
        )

    def approve_local_preview(
        self,
        *,
        scope: ApprovalScope,
        data_grant_id: str,
        confirmation_text: str,
        actor_role: str,
        ttl_minutes: int = 30,
    ) -> LocalPreviewApprovalResult:
        """Issue one exact Preview approval and its short-lived local allowance."""
        expected = f"APPROVE PREVIEW {scope.fingerprint[:12]}"
        if confirmation_text.strip() != expected:
            raise PermissionError("preview approval confirmation text mismatch")

        contract = self.contract_registry.load("Scrublet", "0.2.3")
        expected_scope = {
            "tool_name": contract.tool_name,
            "tool_version": contract.tool_version,
            "contract_version": contract.contract_version,
            "environment_id": contract.environment_id,
        }
        actual_scope = {
            "tool_name": scope.tool_name,
            "tool_version": scope.tool_version,
            "contract_version": scope.contract_version,
            "environment_id": scope.environment_id,
        }
        if actual_scope != expected_scope:
            raise PermissionError("preview approval scope is not the fixed Scrublet pair")

        approval = self.approval_service.create_execution_approval(
            scope=scope,
            data_grant_id=data_grant_id,
            ttl=timedelta(minutes=ttl_minutes),
            max_uses=1,
        )
        enablement = self.enable_local_preview(
            user_id=scope.user_id,
            artifact_id=scope.artifact_id,
            actor_role=actor_role,
            ttl_minutes=ttl_minutes,
            max_runs=1,
        )
        if not enablement.enabled:
            self.approval_service.revoke_execution_approval(approval.approval_id)
            raise PermissionError(";".join(enablement.blockers))
        return LocalPreviewApprovalResult(
            enablement=enablement,
            approval=approval,
        )

    def prepare(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: str | None,
        execution_approval_id: str | None,
        request_id: str,
        query: str,
        parameters: dict[str, Any],
        tool_name: str,
        tool_version: str,
        requested_runs: int = 2,
        data_scope: str = "synthetic_fixture",
    ) -> ExecutionUIContext:
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
        contract = self.contract_registry.load(tool_name, tool_version)
        environment = self.environment_registry.get(contract.environment_id)
        runtime_manifest = self.runtime_pack_manager.registry.for_environment(
            environment.environment_id
        )
        runtime_probe = self.runtime_pack_manager.probe(runtime_manifest.pack_id)
        runtime_route = self.orchestrator.router.route_runtime_pack(probe=runtime_probe)
        execution_gate = self.contract_registry.execution_gate(contract)
        pair = ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=environment.environment_id,
        )
        allowlist_decision = self.allowlist.validate(
            user_id=user_id,
            pair=pair,
            artifact_id=artifact_id,
            data_scope=data_scope,
            requested_runs=requested_runs,
        )
        policy_decision = self.execution_policy.authorize(
            actor_role="user",
            access_origin="local",
            user_allowlisted=allowlist_decision.allowed,
            contract=contract,
            environment=environment,
        )
        blockers = [
            reason
            for reason in preparation.reasons
            if reason != "ordinary_user_execution_disabled_by_policy"
        ]
        if not preparation.data_access.allowed:
            blockers.extend(preparation.data_access.reasons)
        if preparation.execution_approval is None:
            blockers.append("execution_approval_missing")
        elif not preparation.execution_approval.allowed:
            blockers.extend(preparation.execution_approval.reasons)
        blockers.extend(allowlist_decision.reasons)
        blockers.extend(policy_decision.reasons)
        blockers.extend(execution_gate.reasons)
        if not runtime_probe.ready:
            blockers.extend(runtime_route.reasons)
        if preparation.plan is None:
            blockers.append("workflow_plan_missing")
        elif preparation.plan.plan_status != "dry_run":
            blockers.extend(preparation.plan.blocking_conditions)
        button_enabled = bool(
            preparation.data_access.allowed
            and preparation.execution_approval is not None
            and preparation.execution_approval.allowed
            and preparation.plan is not None
            and preparation.plan.plan_status == "dry_run"
            and allowlist_decision.allowed
            and policy_decision.allowed
            and execution_gate.allowed
            and runtime_probe.ready
        )
        return ExecutionUIContext(
            user_id=user_id,
            artifact=preparation.artifact,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            environment_id=environment.environment_id,
            policy_mode=self.execution_policy.mode,
            allowlisted=allowlist_decision.allowed,
            data_access=preparation.data_access,
            execution_approval=preparation.execution_approval,
            profile=preparation.profile,
            plan=preparation.plan,
            approval_scope=preparation.approval_scope,
            approval_fingerprint=preparation.request_fingerprint,
            execution_gate=execution_gate,
            runtime_pack=runtime_probe,
            runtime_route=str(runtime_route.route),
            button_enabled=button_enabled,
            button_blockers=sorted(set(blockers)),
        )

    def list_runtime_packs(self) -> list[RuntimeCapabilityProbe]:
        return self.runtime_pack_manager.inventory()

    def create_environment_plan(
        self, *, user_id: str, pack_id: str
    ) -> EnvironmentProvisioningPlan:
        return self.runtime_pack_manager.create_plan(pack_id=pack_id, user_id=user_id)

    def approve_environment_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
        confirmation_text: str,
    ) -> EnvironmentProvisioningApproval:
        return self.runtime_pack_manager.approvals.approve(
            plan_id=plan_id,
            user_id=user_id,
            confirmation_text=confirmation_text,
        )

    def install_environment_plan(
        self, *, plan_id: str, approval_id: str
    ) -> PackInstallationRecord:
        return self.runtime_pack_manager.provision(
            plan_id=plan_id, approval_id=approval_id
        )

    def remove_runtime_pack(
        self, *, pack_id: str, confirmation_text: str
    ) -> bool:
        return self.runtime_pack_manager.remove(
            pack_id=pack_id, confirmation_text=confirmation_text
        )

    def create_plan_approval(
        self,
        *,
        context: ExecutionUIContext,
        data_grant_id: str,
        confirmations: dict[str, bool],
        confirmation_text: str,
        max_uses: int = 2,
    ) -> ExecutionApproval:
        if context.approval_scope is None or context.approval_fingerprint is None:
            raise ValueError("profile and dry-run plan are required before approval")
        if set(confirmations) != APPROVAL_CONFIRMATIONS or not all(
            confirmations.values()
        ):
            raise PermissionError("all approval confirmations are required")
        if confirmation_text.strip() != self.confirmation_text(context):
            raise PermissionError("approval confirmation text mismatch")
        return self.approval_service.create_execution_approval(
            scope=context.approval_scope,
            data_grant_id=data_grant_id,
            max_uses=max_uses,
        )

    @staticmethod
    def confirmation_text(context: ExecutionUIContext) -> str:
        if not context.approval_fingerprint:
            return ""
        return f"APPROVE {context.approval_fingerprint[:12]}"

    def start_execution(
        self,
        *,
        context: ExecutionUIContext,
        data_grant_id: str,
        execution_approval_id: str,
        request_id: str,
        query: str,
        parameters: dict[str, Any],
        package_id: str,
        requested_runs: int = 2,
        data_scope: str = "synthetic_fixture",
    ) -> ExecutionUIJobStatus:
        current = self.prepare(
            user_id=context.user_id,
            artifact_id=context.artifact.artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=context.tool_name,
            tool_version=context.tool_version,
            requested_runs=requested_runs,
            data_scope=data_scope,
        )
        if current.approval_fingerprint != context.approval_fingerprint:
            raise PermissionError("plan_or_parameter_fingerprint_changed")
        if not current.button_enabled:
            raise PermissionError(";".join(current.button_blockers))
        job_id = f"ui-job-{uuid.uuid4().hex}"
        expected_run_ids = [
            f"{request_id}-run-{index + 1}" for index in range(requested_runs)
        ]
        cancel_event = threading.Event()
        future = self._pool.submit(
            self.local_user_service.execute_approved_plan,
            user_id=context.user_id,
            artifact_id=context.artifact.artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=context.tool_name,
            tool_version=context.tool_version,
            package_id=package_id,
            requested_runs=requested_runs,
            data_scope=data_scope,
            cancellation_requested=cancel_event.is_set,
        )
        with self._job_lock:
            self._jobs[job_id] = _ExecutionJob(
                job_id=job_id,
                user_id=context.user_id,
                expected_run_ids=expected_run_ids,
                future=future,
                cancel_event=cancel_event,
            )
        return ExecutionUIJobStatus(
            job_id=job_id,
            state="queued",
            expected_run_ids=expected_run_ids,
        )

    def poll_job(self, *, user_id: str, job_id: str) -> ExecutionUIJobStatus:
        job = self._owned_job(user_id=user_id, job_id=job_id)
        if not job.future.done():
            return ExecutionUIJobStatus(
                job_id=job_id,
                state="cancel_requested" if job.cancel_requested else "running",
                expected_run_ids=job.expected_run_ids,
            )
        try:
            result = job.future.result()
        except Exception as exc:
            return ExecutionUIJobStatus(
                job_id=job_id,
                state="failed",
                expected_run_ids=job.expected_run_ids,
                error_summary=self.redact_text(str(exc)),
            )
        state = (
            "cancelled"
            if job.cancel_requested
            and any(run.status == "cancelled" for run in result.execution_runs)
            else "completed"
        )
        return ExecutionUIJobStatus(
            job_id=job_id,
            state=state,
            expected_run_ids=job.expected_run_ids,
            result=result,
        )

    def cancel_job(
        self, *, user_id: str, job_id: str, wait_seconds: float = 2.0
    ) -> bool:
        job = self._owned_job(user_id=user_id, job_id=job_id)
        job.cancel_requested = True
        job.cancel_event.set()
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while not job.future.done() and time.monotonic() <= deadline:
            for run_id in job.expected_run_ids:
                try:
                    record = self.workspace.get_record(
                        resource_type="run", user_id=user_id, resource_id=run_id
                    )
                except KeyError:
                    continue
                if record.status == "running":
                    self.workspace.request_cancellation(
                        user_id=user_id, run_id=run_id
                    )
                    return True
                if record.status == "cancellation_requested":
                    return True
            time.sleep(0.05)
        return False

    def result_view(
        self, *, user_id: str, result: LocalUserExecutionResult
    ) -> ExecutionUIResultView:
        if result.user_id != user_id:
            raise PermissionError("cross-user result access is forbidden")
        self.workspace.get_package_directory(
            user_id=user_id, package_id=result.package_result.package_id
        )
        return ExecutionUIResultView(
            user_id=user_id,
            tool_name=result.tool_name,
            run_statuses=[
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "runtime_seconds": run.runtime_seconds,
                    "peak_memory_mb": run.peak_memory_mb,
                    "exit_code": run.exit_code,
                    "error_type": run.error_type,
                    "error_summary": self.redact_text(run.error_message or ""),
                    "stdout_summary": self._log_summary(run.stdout_path),
                    "stderr_summary": self._log_summary(run.stderr_path),
                }
                for run in result.execution_runs
            ],
            validation_results=[
                item.model_dump(mode="json") for item in result.validation_results
            ],
            candidate_evaluations=[
                item.model_dump(mode="json")
                for item in result.candidate_evaluations
            ],
            decision_result=result.decision_result.model_dump(mode="json"),
            repair_history=[
                {
                    "action_id": item.action_id,
                    "parent_run_id": item.parent_run_id,
                    "new_run_id": item.new_run_id,
                    "reason_code": item.reason_code,
                    "changed_fields": item.changed_fields,
                    "old_values": item.old_values,
                    "new_values": item.new_values,
                    "approved": item.approved,
                }
                for item in result.repair_actions
            ],
            package_manifest={
                "package_id": result.package_result.package_id,
                "reproducibility_level": result.package_result.reproducibility_level,
                "complete": result.package_result.complete,
                "manifest_hashes_valid": result.package_result.manifest_hashes_valid,
                "artifact_hashes": result.package_result.artifact_hashes,
                "input_data_copied": result.package_result.user_data_copied,
            },
            package_path_redacted=self.redact_path(result.package_result.package_path),
            package_complete=result.package_result.complete,
            manifest_hashes_valid=result.package_result.manifest_hashes_valid,
            input_data_copied=result.package_result.user_data_copied,
        )

    def redact_path(self, path_text: str) -> str:
        path = Path(path_text).resolve()
        for root, label in (
            (PROJECT_ROOT, "[project]"),
            (self.workspace.root, "[user-workspace]"),
            *(
                (root, "[approved-input]")
                for root in self.data_registry.approved_input_roots
            ),
        ):
            try:
                relative = path.relative_to(root)
                return str(Path(label) / relative)
            except ValueError:
                continue
        return f".../{path.name}"

    def redact_text(self, text: str) -> str:
        redacted = str(text)
        roots = [
            PROJECT_ROOT,
            self.workspace.root,
            *self.data_registry.approved_input_roots,
            Path.home(),
        ]
        for root in sorted({str(item.resolve()) for item in roots}, key=len, reverse=True):
            redacted = redacted.replace(root, "[local-path]")
        return redacted

    def _log_summary(self, path_text: str, *, max_chars: int = 2000) -> str:
        path = Path(path_text)
        try:
            value = path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError:
            value = ""
        return self.redact_text(value[-max_chars:])

    def _owned_job(self, *, user_id: str, job_id: str) -> _ExecutionJob:
        with self._job_lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError("execution job not found")
        if job.user_id != user_id:
            raise PermissionError("cross-user job access is forbidden")
        return job


def build_execution_ui_service() -> ExecutionUIService:
    """Build the local service from maintainer-controlled process configuration."""

    approved_roots = _approved_roots_from_environment()
    data_registry = DataRegistry(approved_input_roots=approved_roots)
    approval_service = ApprovalService()
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    workspace = UserWorkspaceService()
    allowlist = LocalUserAllowlist()
    policy = ExecutionPolicy(mode=_configured_policy_mode())
    runtime_packs = RuntimePackManager()
    orchestrator = ExecutionOrchestrator(
        run_root=PROJECT_ROOT / ".sckg_exec" / "ui-unused-runs",
        approved_input_root=approved_roots[0],
        package_root=PROJECT_ROOT / ".sckg_exec" / "ui-unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=data_registry,
        approval_service=approval_service,
    )
    local_service = LocalUserService(
        orchestrator=orchestrator,
        data_registry=data_registry,
        approval_service=approval_service,
        allowlist=allowlist,
        workspace=workspace,
        policy=policy,
    )
    return ExecutionUIService(
        data_registry=data_registry,
        approval_service=approval_service,
        execution_policy=policy,
        local_user_service=local_service,
        orchestrator=orchestrator,
        workspace=workspace,
        allowlist=allowlist,
        contract_registry=contracts,
        environment_registry=environments,
        runtime_pack_manager=runtime_packs,
    )


def configured_local_user_id() -> str:
    return os.environ.get("SCKG_LOCAL_USER_ID", "local-user").strip() or "local-user"


def _approved_roots_from_environment() -> list[Path]:
    configured = os.environ.get("SCKG_APPROVED_INPUT_ROOTS", "")
    roots = [Path(item).expanduser() for item in configured.split(os.pathsep) if item]
    if not roots:
        roots = [PROJECT_ROOT / ".sckg_exec" / "approved-inputs"]
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
    return [root.resolve() for root in roots]


def _configured_policy_mode() -> ExecutionPolicyMode:
    value = os.environ.get("SCKG_EXECUTION_POLICY", "disabled").strip().casefold()
    try:
        return ExecutionPolicyMode(value)
    except ValueError:
        return ExecutionPolicyMode.DISABLED


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
