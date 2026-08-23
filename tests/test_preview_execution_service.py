from __future__ import annotations

from pathlib import Path

import pytest

from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRun, ValidationResult
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_policy import ExecutionPair, ExecutionPolicy, ExecutionPolicyMode
from execution.local_user_service import LocalUserAllowlist
from execution.preview_execution_service import PreviewExecutionService, _error_context
from execution.research_workspace_service import ResearchWorkspaceService
from execution.user_workspace import UserWorkspaceService
from scripts.run_path_to_preview_notebook_smoke import _write_smoke_fixture


def _harness(tmp_path: Path):
    input_root = tmp_path / "inputs"
    source = _write_smoke_fixture(input_root / "pbmc.h5ad")
    registry = DataRegistry(
        approved_input_roots=[input_root], registry_root=tmp_path / "registry"
    )
    approvals = ApprovalService(root=tmp_path / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    workspace = UserWorkspaceService(root=tmp_path / "users")
    allowlist = LocalUserAllowlist(root=tmp_path / "allowlist")
    policy = ExecutionPolicy(mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS)
    artifact = registry.register(user_id="alice", path=source, artifact_id="pbmc")
    grant = approvals.grant_data_access(user_id="alice", artifact_id="pbmc")
    research = ResearchWorkspaceService(
        data_registry=registry,
        approval_service=approvals,
        workspace_root=tmp_path / "research",
    )
    profile = research.profile(
        user_id="alice", artifact_id="pbmc", data_grant_id=grant.grant_id
    )
    preview = research.build_preview(
        user_id="alice",
        artifact_id="pbmc",
        profile=profile,
        data_grant_id=grant.grant_id,
        max_cells=120,
        random_seed=19,
        stratify_key="batch",
    )
    notebook = research.compile_notebook(
        user_id="alice",
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        data_grant_id=grant.grant_id,
        parameters={"expected_doublet_rate": 0.08, "n_prin_comps": 10},
    )
    contract = contracts.load("Scrublet", "0.2.3")
    allowlist.allow_user(
        user_id="alice",
        allowed_pairs=[
            ExecutionPair(
                tool_name=contract.tool_name,
                tool_version=contract.tool_version,
                wrapper_id=contract.wrapper_id,
                environment_id=contract.environment_id,
            )
        ],
        allowed_artifact_ids=[artifact.artifact_id],
        allowed_data_scopes=["representative_preview"],
        max_runs=4,
    )
    service = PreviewExecutionService(
        research_workspace=research,
        data_registry=registry,
        approval_service=approvals,
        allowlist=allowlist,
        workspace=workspace,
        execution_policy=policy,
        contract_registry=contracts,
        environment_registry=environments,
        router=DeterministicRouter(),
    )
    return service, approvals, grant, profile, preview, notebook


def test_preview_requires_exact_approval_and_parameter_change_invalidates_it(tmp_path):
    service, approvals, grant, profile, preview, notebook = _harness(tmp_path)
    preparation = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        profile=profile,
        preview=preview,
        notebook=notebook,
    )
    assert preparation.ready is False
    assert preparation.execution_request_count == 0
    assert "execution_approval_missing" in preparation.blockers

    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope,
        data_grant_id=grant.grant_id,
    )
    ready = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        profile=profile,
        preview=preview,
        notebook=notebook,
    )
    assert ready.ready is True

    changed_notebook = service.research_workspace.compile_notebook(
        user_id="alice",
        artifact_id="pbmc",
        profile=profile,
        preview=preview,
        data_grant_id=grant.grant_id,
        parameters={"expected_doublet_rate": 0.12, "n_prin_comps": 10},
    )
    changed = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        profile=profile,
        preview=preview,
        notebook=changed_notebook,
    )
    assert changed.ready is False
    assert "approval_scope_or_fingerprint_mismatch" in changed.blockers
    assert changed.approval_ready is False
    assert changed.approval_blockers == ["approval_scope_or_fingerprint_mismatch"]

    tampered_manifest = notebook.model_copy(update={"parameter_hash": "f" * 64})
    with pytest.raises(ValueError, match="notebook parameter hash changed"):
        service.prepare(
            user_id="alice",
            artifact_id="pbmc",
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            profile=profile,
            preview=preview,
            notebook=tampered_manifest,
        )


def test_preview_executes_fixed_wrapper_and_returns_unified_validation(tmp_path):
    service, approvals, grant, profile, preview, notebook = _harness(tmp_path)
    preparation = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        profile=profile,
        preview=preview,
        notebook=notebook,
    )
    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope,
        data_grant_id=grant.grant_id,
    )
    preview_request = service.build_request(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        profile=profile,
        preview=preview,
        notebook=notebook,
        request_id="preview-request-1",
    )
    assert preview_request.preview_hash == preview.preview_hash
    assert preview_request.notebook_hash == notebook.notebook_hash
    assert preview_request.parameter_hash == preparation.parameter_hash
    result = service.execute(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        profile=profile,
        preview=preview,
        notebook=notebook,
        request_id="preview-request-1",
    )

    assert result.status == "validated"
    assert result.execution_run.status == "succeeded"
    assert result.execution_run.execution_purpose == "representative_preview"
    assert result.execution_run.user_data_used is True
    assert result.validation_result.passed is True
    assert result.validation_result.metric_authority == "preview_engineering_metric"
    assert result.validation_result.validation_version == "doublet-preview-validator-v1"
    assert result.scientific_claim_allowed is False
    assert result.original_data_copied is False
    assert result.error_context is None
    assert result.execution_run.artifact_paths["doublet_score_histogram.png"]
    assert result.validation_result.artifact_checks[
        "preview_histogram_present_and_hashed"
    ] is True
    assert [item.step_id for item in result.step_events] == [
        "run_tool",
        "validate_outputs",
    ]
    assert [item.status for item in result.step_events] == [
        "COMPLETED",
        "COMPLETED",
    ]
    assert approvals.validate_execution_approval(
        approval.approval_id, expected_scope=preparation.approval_scope
    ).code == "consumed"

    with pytest.raises(PermissionError, match="fully_consumed"):
        service.execute(
            user_id="alice",
            artifact_id="pbmc",
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
            request_id="preview-request-2",
        )


def test_preview_hash_tamper_blocks_before_approval_consumption_or_process(tmp_path):
    service, approvals, grant, profile, preview, notebook = _harness(tmp_path)
    preparation = service.prepare(
        user_id="alice",
        artifact_id="pbmc",
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        profile=profile,
        preview=preview,
        notebook=notebook,
    )
    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope,
        data_grant_id=grant.grant_id,
    )
    preview_path = service.research_workspace.preview_path(
        user_id="alice", artifact_id="pbmc", preview=preview
    )
    preview_path.write_bytes(preview_path.read_bytes() + b"tampered")

    with pytest.raises((FileNotFoundError, PermissionError), match="preview"):
        service.execute(
            user_id="alice",
            artifact_id="pbmc",
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
            request_id="preview-tampered",
        )
    stored = approvals._load_approval(approval.approval_id)
    assert stored.uses_consumed == 0
    assert not list((tmp_path / "users").glob("alice/runs/*/execution_run.json"))


def test_preview_error_context_is_structured_and_redacts_workspace(tmp_path):
    from datetime import datetime, timezone

    workspace = tmp_path / "private-workspace"
    stderr = workspace / "stderr.log"
    stderr.parent.mkdir(parents=True)
    stderr.write_text(f"failed while reading {workspace}/secret.h5ad\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    run = ExecutionRun(
        request_id="request-1",
        run_id="run-1",
        trace_id="trace-run-1",
        plan_id="plan-1",
        step_id="preview-step",
        wrapper_id="scrublet_v0_2_3",
        tool_name="Scrublet",
        tool_version="0.2.3",
        environment_id="scRNAseq",
        command_argv_redacted=["python", "-m", "execution.wrappers.scrublet"],
        parameters={},
        input_hash="a" * 64,
        start_time=now,
        end_time=now,
        runtime_seconds=0,
        peak_memory_mb=0,
        exit_code=1,
        stdout_path=str(workspace / "stdout.log"),
        stderr_path=str(stderr),
        status="failed",
        error_type="wrapper_exit_nonzero",
        error_message=f"wrapper failed under {workspace}",
        qualification_mode=False,
        fixture_id="preview-fixture",
        synthetic_fixture=False,
        user_data_used=True,
        execution_purpose="representative_preview",
    )
    validation = ValidationResult(
        validation_id="validation-run-1",
        run_id="run-1",
        passed=False,
        failures=["execution_not_successful"],
        metric_authority="preview_engineering_metric",
    )
    context = _error_context(run, validation, workspace)

    assert context is not None
    assert context.stage == "execution"
    assert context.retryable is True
    assert str(workspace) not in context.message
    assert str(workspace) not in (context.stderr_summary or "")
    assert "[local-workspace]" in (context.stderr_summary or "")
