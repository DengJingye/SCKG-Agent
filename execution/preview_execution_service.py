from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from core.deterministic_router import DeterministicRouter
from core.execution_models import (
    ExecutionRequest,
    QualificationArtifact,
    RestrictedUserExecutionContext,
)
from core.research_workspace_models import (
    DataAssetProfile,
    ErrorContext,
    NotebookShadowBundle,
    PreviewRunPreparation,
    PreviewRunRequest,
    PreviewRunResult,
    PreviewStepEvent,
    RepresentativePreviewManifest,
)
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalScope, ApprovalService, parameter_hash
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_policy import ExecutionPair, ExecutionPolicy
from execution.local_controlled_executor import LocalControlledExecutor
from execution.local_user_service import LocalUserAllowlist
from execution.preview_result_store import PreviewResultStore
from execution.preview_result_interpreter import PreviewResultInterpreter
from execution.research_workspace_service import ResearchWorkspaceService
from execution.user_workspace import UserWorkspaceService
from execution.validators.doublet import DoubletValidator
from execution.wrapper_registry import WrapperRegistry
from execution.workspace_checkpoint import WorkspaceCheckpointService


class PreviewExecutionService:
    """Run a fixed Scrublet StepTemplate on a governed representative preview."""

    def __init__(
        self,
        *,
        research_workspace: ResearchWorkspaceService,
        data_registry: DataRegistry,
        approval_service: ApprovalService,
        allowlist: LocalUserAllowlist,
        workspace: UserWorkspaceService,
        execution_policy: ExecutionPolicy,
        contract_registry: ToolContractRegistry | None = None,
        environment_registry: EnvironmentRegistry | None = None,
        router: DeterministicRouter | None = None,
        wrapper_registry: WrapperRegistry | None = None,
    ) -> None:
        self.research_workspace = research_workspace
        self.data_registry = data_registry
        self.approval_service = approval_service
        self.allowlist = allowlist
        self.workspace = workspace
        self.execution_policy = execution_policy
        self.environment_registry = environment_registry or EnvironmentRegistry()
        self.contract_registry = contract_registry or ToolContractRegistry(
            environment_registry=self.environment_registry
        )
        self.router = router or DeterministicRouter()
        self.wrapper_registry = wrapper_registry or WrapperRegistry()
        self.result_store = PreviewResultStore(
            workspace_root=self.research_workspace.workspace_root,
            execution_root=self.workspace.root,
        )
        self.result_interpreter = PreviewResultInterpreter()
        self.checkpoints = WorkspaceCheckpointService(
            data_registry=self.data_registry,
            approval_service=self.approval_service,
            research_workspace=self.research_workspace,
            contract_registry=self.contract_registry,
            environment_registry=self.environment_registry,
        )

    def prepare(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: str,
        execution_approval_id: str | None,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
    ) -> PreviewRunPreparation:
        blockers: list[str] = []
        data_access = self.approval_service.validate_data_access(
            data_grant_id, user_id=user_id, artifact_id=artifact_id
        )
        if not data_access.allowed:
            blockers.extend(data_access.reasons)
        self._validate_lineage(
            user_id=user_id,
            artifact_id=artifact_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
        )
        parameters = self.research_workspace.notebook_parameters(
            user_id=user_id, artifact_id=artifact_id, bundle=notebook
        )
        contract = self.contract_registry.load("Scrublet", "0.2.3")
        parameters = self.contract_registry.validate_parameters(contract, parameters)
        environment = self.environment_registry.get(contract.environment_id)
        wrapper = self.wrapper_registry.get(contract.wrapper_id)
        plan_id = _preview_plan_id(preview, notebook)
        scope = ApprovalScope(
            user_id=user_id,
            artifact_id=artifact_id,
            plan_id=plan_id,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            contract_version=contract.contract_version,
            environment_id=environment.environment_id,
            parameter_hash=parameter_hash(parameters),
        )
        pair = ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=environment.environment_id,
        )
        allowance = self.allowlist.validate(
            user_id=user_id,
            pair=pair,
            artifact_id=artifact_id,
            data_scope="representative_preview",
            requested_runs=1,
        )
        blockers.extend(allowance.reasons)
        policy = self.execution_policy.authorize(
            actor_role="user",
            access_origin="local",
            user_allowlisted=allowance.allowed,
            contract=contract,
            environment=environment,
        )
        blockers.extend(policy.reasons)
        if not wrapper.is_runtime_ready():
            blockers.append("runtime_pack_not_ready")
        approval = self.approval_service.validate_execution_approval(
            execution_approval_id, expected_scope=scope
        )
        if not approval.allowed:
            blockers.extend(approval.reasons)
        blockers = sorted(set(blockers))
        return PreviewRunPreparation(
            user_id=user_id,
            artifact_id=artifact_id,
            preview_id=preview.preview_id,
            notebook_id=notebook.notebook_id,
            plan_id=plan_id,
            environment_id=environment.environment_id,
            parameter_hash=scope.parameter_hash,
            approval_scope=scope,
            approval_fingerprint=scope.fingerprint,
            policy_mode=str(self.execution_policy.mode),
            runtime_ready=wrapper.is_runtime_ready(),
            approval_ready=approval.allowed,
            approval_blockers=approval.reasons,
            ready=not blockers,
            blockers=blockers,
        )

    def execute(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: str,
        execution_approval_id: str,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
        request_id: str,
    ) -> PreviewRunResult:
        preview_request = self.build_request(
            user_id=user_id,
            artifact_id=artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
            request_id=request_id,
        )
        return self.execute_request(
            request=preview_request,
            profile=profile,
            preview=preview,
            notebook=notebook,
        )

    def list_results(self, *, user_id: str, artifact_id: str | None = None):
        summaries = self.result_store.list_results(
            user_id=user_id, artifact_id=artifact_id
        )
        enriched = []
        for summary in summaries:
            if not summary.integrity.result_digest_valid:
                enriched.append(summary)
                continue
            try:
                result = self.load_result(
                    user_id=user_id,
                    artifact_id=summary.artifact_id,
                    run_id=summary.run_id,
                )
                checkpoint = self.checkpoints.inspect_result(
                    result=result, integrity=summary.integrity
                )
                status = (
                    checkpoint.overall_status
                    if checkpoint.overall_status != "INCOMPLETE"
                    else "WAITING"
                )
                if status == "CURRENT":
                    status = "COMPLETED"
                enriched.append(
                    summary.model_copy(
                        update={"status": status, "checkpoint": checkpoint}
                    )
                )
            except Exception:
                enriched.append(summary)
        return enriched

    def load_result(self, *, user_id: str, artifact_id: str, run_id: str):
        return self.result_store.load_result(
            user_id=user_id, artifact_id=artifact_id, run_id=run_id
        )

    def resolve_result_artifact(
        self,
        *,
        user_id: str,
        artifact_id: str,
        run_id: str,
        artifact_name: str,
    ) -> Path:
        return self.result_store.resolve_artifact(
            user_id=user_id,
            artifact_id=artifact_id,
            run_id=run_id,
            artifact_name=artifact_name,
        )

    def interpret_result(self, *, result: PreviewRunResult):
        integrity = self.result_store.inspect_integrity(result)
        checkpoint = self.checkpoints.inspect_result(
            result=result, integrity=integrity
        )
        result_table_path = None
        if integrity.passed:
            try:
                result_table_path = self.result_store.resolve_artifact(
                    user_id=result.user_id,
                    artifact_id=result.artifact_id,
                    run_id=result.execution_run.run_id,
                    artifact_name="doublet_results.tsv",
                )
            except (FileNotFoundError, PermissionError):
                result_table_path = None
        return self.result_interpreter.interpret(
            result=result,
            integrity=integrity,
            checkpoint=checkpoint,
            result_table_path=result_table_path,
        )

    def build_request(
        self,
        *,
        user_id: str,
        artifact_id: str,
        data_grant_id: str,
        execution_approval_id: str,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
        request_id: str,
    ) -> PreviewRunRequest:
        preparation = self.prepare(
            user_id=user_id,
            artifact_id=artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
        )
        if not preparation.ready:
            raise PermissionError(";".join(preparation.blockers))
        return PreviewRunRequest(
            request_id=request_id,
            user_id=user_id,
            artifact_id=artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            profile_id=profile.profile_id,
            preview_id=preview.preview_id,
            preview_hash=preview.preview_hash,
            notebook_id=notebook.notebook_id,
            notebook_hash=notebook.notebook_hash,
            plan_id=preparation.plan_id,
            parameter_hash=preparation.parameter_hash,
            step_contract_id=notebook.step_contract_id,
            step_contract_version=notebook.step_contract_version,
        )

    def execute_request(
        self,
        *,
        request: PreviewRunRequest,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
    ) -> PreviewRunResult:
        self._validate_request_lineage(
            request=request, profile=profile, preview=preview, notebook=notebook
        )
        preparation = self.prepare(
            user_id=request.user_id,
            artifact_id=request.artifact_id,
            data_grant_id=request.data_grant_id,
            execution_approval_id=request.execution_approval_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
        )
        if not preparation.ready:
            raise PermissionError(";".join(preparation.blockers))

        preview_path = self.research_workspace.preview_path(
            user_id=request.user_id,
            artifact_id=request.artifact_id,
            preview=preview,
        )
        if _sha256(preview_path) != preview.preview_hash:
            raise PermissionError("preview_hash_changed_before_execution")
        parameters = self.research_workspace.notebook_parameters(
            user_id=request.user_id,
            artifact_id=request.artifact_id,
            bundle=notebook,
        )
        contract = self.contract_registry.load("Scrublet", "0.2.3")
        parameters = self.contract_registry.validate_parameters(contract, parameters)
        environment = self.environment_registry.get(contract.environment_id)
        pair = ExecutionPair(
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            wrapper_id=contract.wrapper_id,
            environment_id=environment.environment_id,
        )
        route = self.router.route_user_authorization(
            data_access=self.approval_service.validate_data_access(
                request.data_grant_id,
                user_id=request.user_id,
                artifact_id=request.artifact_id,
            ),
            execution_approval=self.approval_service.validate_execution_approval(
                request.execution_approval_id,
                expected_scope=preparation.approval_scope,
            ),
            execution_backend_enabled=True,
        )
        if not route.execution_allowed:
            raise PermissionError(";".join(route.reasons))

        allowance = self.allowlist.consume_run(
            user_id=request.user_id,
            pair=pair,
            artifact_id=request.artifact_id,
            data_scope="representative_preview",
        )
        consumed = self.approval_service.consume_execution_approval(
            request.execution_approval_id,
            expected_scope=preparation.approval_scope,
            request_id=request.request_id,
        )
        run_id = f"preview-run-{uuid.uuid4().hex}"
        self.workspace.reserve_run(user_id=request.user_id, run_id=run_id)
        artifact = QualificationArtifact(
            artifact_id=request.artifact_id,
            fixture_id=preview.preview_id,
            path=str(preview_path),
            sha256=preview.preview_hash,
            synthetic=False,
            public_dataset=False,
            user_data=True,
            allowlisted=True,
            expected_cells=preview.n_preview_cells,
        )
        preview_request = request
        execution_request = ExecutionRequest(
            request_id=preview_request.request_id,
            run_id=run_id,
            trace_id=f"trace-{run_id}",
            plan_id=preview_request.plan_id,
            step_id="doublet.scrublet.preview",
            wrapper_id=contract.wrapper_id,
            environment_id=environment.environment_id,
            input_artifact_id=preview_request.artifact_id,
            execution_seed=preview.random_seed,
            parameters=parameters,
            parameter_provenance={
                "source": "maintainer_step_template",
                "notebook_id": notebook.notebook_id,
                "step_contract_version": notebook.step_contract_version,
            },
            timeout_seconds=int(
                contract.resource_requirements["qualification_timeout_seconds"]
            ),
            actor={"actor_id": preview_request.user_id, "role": "user"},
            qualification={
                "mode": False,
                "purpose": "representative_preview",
                "authorized": False,
                "fixture_allowlisted": False,
                "fixture_id": preview.preview_id,
            },
            execution_mode="restricted_local_user",
            user_execution=RestrictedUserExecutionContext(
                user_id=preview_request.user_id,
                artifact_id=preview_request.artifact_id,
                approval_id=preview_request.execution_approval_id,
                allowance_id=allowance.allowance_id,
                request_fingerprint=preparation.approval_fingerprint,
                contract_version=contract.contract_version,
                tool_name=contract.tool_name,
                tool_version=contract.tool_version,
                environment_id=environment.environment_id,
                parameter_hash=parameter_hash(parameters),
                approval_consumption_index=consumed.uses_consumed,
                approval_max_uses=consumed.max_uses,
            ),
        )
        executor = LocalControlledExecutor(
            run_root=self.workspace.root / preview_request.user_id / "runs",
            approved_input_root=self.research_workspace.artifact_workspace_root(
                user_id=preview_request.user_id,
                artifact_id=preview_request.artifact_id,
            ),
            wrapper_registry=self.wrapper_registry,
            contract_registry=self.contract_registry,
            environment_registry=self.environment_registry,
            execution_policy=self.execution_policy,
        )
        self.workspace.mark_run_running(user_id=preview_request.user_id, run_id=run_id)
        run = executor.execute(
            request=execution_request,
            artifact=artifact,
            contract=contract,
            router_decision=route,
            cancellation_checker=lambda: self.workspace.cancellation_reason(
                user_id=request.user_id, run_id=run_id
            ),
        )
        self.workspace.mark_run_terminal(
            user_id=preview_request.user_id, run_id=run_id, status=run.status
        )
        validation = DoubletValidator().validate(
            run, expected_cells=preview.n_preview_cells
        )
        error = _error_context(run, validation, self.research_workspace.workspace_root)
        result = PreviewRunResult(
            user_id=preview_request.user_id,
            artifact_id=preview_request.artifact_id,
            preview_id=preview.preview_id,
            notebook_id=notebook.notebook_id,
            plan_id=preparation.plan_id,
            status=(
                "validated"
                if validation.passed
                else ("blocked" if run.status == "blocked" else "failed")
            ),
            execution_run=run,
            validation_result=validation,
            error_context=error,
            step_events=[
                PreviewStepEvent(
                    event_id=f"{run_id}-execute",
                    step_id="run_tool",
                    status=(
                        "COMPLETED"
                        if run.status == "succeeded"
                        else ("BLOCKED" if run.status == "blocked" else "FAILED")
                    ),
                    message=(
                        "The fixed Scrublet wrapper completed."
                        if run.status == "succeeded"
                        else (run.error_message or f"Execution ended with {run.status}.")
                    ),
                    run_id=run_id,
                    recorded_at=run.end_time,
                ),
                PreviewStepEvent(
                    event_id=f"{run_id}-validate",
                    step_id="validate_outputs",
                    status="COMPLETED" if validation.passed else "FAILED",
                    message=(
                        "Output artifacts passed the DoubletValidator."
                        if validation.passed
                        else ";".join(validation.failures)
                        or "Output validation failed."
                    ),
                    run_id=run_id,
                    recorded_at=run.end_time,
                ),
            ],
            lineage=self.checkpoints.capture_lineage(
                profile=profile,
                preview=preview,
                notebook=notebook,
                approval_fingerprint=preparation.approval_fingerprint,
            ),
        )
        self.result_store.save(result)
        return result

    @staticmethod
    def _validate_request_lineage(
        *,
        request: PreviewRunRequest,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
    ) -> None:
        mismatches = []
        expected = {
            "profile_id": profile.profile_id,
            "preview_id": preview.preview_id,
            "preview_hash": preview.preview_hash,
            "notebook_id": notebook.notebook_id,
            "notebook_hash": notebook.notebook_hash,
            "parameter_hash": notebook.parameter_hash,
            "step_contract_id": notebook.step_contract_id,
            "step_contract_version": notebook.step_contract_version,
        }
        for field, value in expected.items():
            if getattr(request, field) != value:
                mismatches.append(field)
        if request.user_id != profile.owner_user_id or request.artifact_id != profile.artifact_id:
            mismatches.append("owner_or_artifact")
        if mismatches:
            raise PermissionError(
                "preview_run_request_lineage_mismatch:" + ",".join(sorted(mismatches))
            )

    @staticmethod
    def _validate_lineage(
        *,
        user_id: str,
        artifact_id: str,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
    ) -> None:
        expected = (user_id, artifact_id, profile.profile_id, preview.preview_id)
        actual = (
            profile.owner_user_id,
            profile.artifact_id,
            notebook.profile_id,
            notebook.preview_id,
        )
        if actual != expected:
            raise PermissionError("preview_notebook_lineage_mismatch")
        if preview.owner_user_id != user_id or preview.artifact_id != artifact_id:
            raise PermissionError("preview_owner_mismatch")
        if preview.profile_id != profile.profile_id:
            raise PermissionError("preview_profile_mismatch")
        if notebook.preview_hash != preview.preview_hash:
            raise PermissionError("notebook_preview_hash_mismatch")


def _preview_plan_id(
    preview: RepresentativePreviewManifest, notebook: NotebookShadowBundle
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "preview_id": preview.preview_id,
                "preview_hash": preview.preview_hash,
                "notebook_id": notebook.notebook_id,
                "notebook_hash": notebook.notebook_hash,
                "parameter_hash": notebook.parameter_hash,
                "step_contract_id": notebook.step_contract_id,
                "step_contract_version": notebook.step_contract_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"preview-plan-{digest[:24]}"


def _error_context(run, validation, redaction_root: Path) -> ErrorContext | None:
    if validation.passed:
        return None
    if run.status == "blocked":
        stage = "preflight"
        code = run.error_type or "preview_preflight_blocked"
        message = run.error_message or "preview execution was blocked before process start"
    elif run.status != "succeeded":
        stage = "execution"
        code = run.error_type or "preview_execution_failed"
        message = run.error_message or "preview wrapper did not complete"
    else:
        stage = "validation"
        code = validation.failures[0] if validation.failures else "preview_validation_failed"
        message = ";".join(validation.failures) or "preview output validation failed"
    stderr = _read_tail(run.stderr_path)
    stderr = stderr.replace(str(redaction_root), "[local-workspace]")
    return ErrorContext(
        stage=stage,
        error_code=code,
        message=message.replace(str(redaction_root), "[local-workspace]"),
        retryable=code in {"timeout", "wrapper_exit_nonzero"},
        user_action=(
            "Review the governed parameters and runtime log; create a new approval before retrying."
            if code in {"timeout", "wrapper_exit_nonzero"}
            else "Review the blocker and rebuild the affected preview or notebook artifact."
        ),
        run_id=run.run_id,
        stderr_summary=stderr or None,
    )


def _read_tail(path_text: str, max_chars: int = 2000) -> str:
    path = Path(path_text)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")[-max_chars:]
    except OSError:
        return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
