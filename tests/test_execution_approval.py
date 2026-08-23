from datetime import datetime, timedelta, timezone

from core.deterministic_router import RouterRoute
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalScope, ApprovalService, parameter_hash
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_approval_binds_full_scope_and_rejects_changes_expiration_and_revoke(tmp_path):
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    service = ApprovalService(root=tmp_path / "approvals")
    grant = service.grant_data_access(
        user_id="user-a", artifact_id="artifact-a", now=now
    )
    assert service.validate_data_access(
        grant.grant_id,
        user_id="user-a",
        artifact_id="artifact-a",
        now=now + timedelta(hours=2),
    ).code == "expired"
    scope = _scope()
    approval = service.create_execution_approval(
        scope=scope, data_grant_id=grant.grant_id, now=now
    )

    assert service.validate_execution_approval(
        approval.approval_id, expected_scope=scope, now=now
    ).allowed
    for changed in (
        scope.model_copy(update={"plan_id": "plan-other"}),
        scope.model_copy(update={"tool_name": "scDblFinder"}),
        scope.model_copy(update={"artifact_id": "artifact-other"}),
        scope.model_copy(update={"contract_version": "changed"}),
        scope.model_copy(update={"environment_id": "changed-env"}),
        scope.model_copy(update={"parameter_hash": parameter_hash({"rate": 0.2})}),
    ):
        result = service.validate_execution_approval(
            approval.approval_id, expected_scope=changed, now=now
        )
        assert result.code == "scope_mismatch"
        assert result.allowed is False

    expired = service.validate_execution_approval(
        approval.approval_id,
        expected_scope=scope,
        now=now + timedelta(hours=1),
    )
    assert expired.code == "expired"
    service.revoke_execution_approval(approval.approval_id, now=now)
    revoked = service.validate_execution_approval(
        approval.approval_id, expected_scope=scope, now=now
    )
    assert revoked.code == "revoked"
    service.revoke_data_access(grant.grant_id, now=now)
    assert service.validate_data_access(
        grant.grant_id,
        user_id="user-a",
        artifact_id="artifact-a",
        now=now,
    ).code == "revoked"


def test_orchestrator_authorization_path_never_creates_execution_request(tmp_path):
    approved_root = tmp_path / "approved"
    source = write_phase1_fixtures(approved_root)["raw_x"]
    data_registry = DataRegistry(
        approved_input_roots=[approved_root], registry_root=tmp_path / "data-registry"
    )
    artifact = data_registry.register(user_id="user-a", path=source)
    approvals = ApprovalService(root=tmp_path / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    orchestrator = ExecutionOrchestrator(
        run_root=tmp_path / "runs",
        approved_input_root=approved_root,
        package_root=tmp_path / "packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=data_registry,
        approval_service=approvals,
    )

    waiting_data = _prepare(
        orchestrator,
        artifact.artifact_id,
        parent_route_override=RouterRoute.BLOCKED,
    )
    assert waiting_data.route == RouterRoute.WAITING_DATA_AUTHORIZATION
    assert any(
        reason.startswith("parent_route_override_ignored")
        for reason in waiting_data.reasons
    )

    grant = approvals.grant_data_access(
        user_id="user-a", artifact_id=artifact.artifact_id
    )
    waiting_approval = _prepare(
        orchestrator, artifact.artifact_id, data_grant_id=grant.grant_id
    )
    assert waiting_approval.route == RouterRoute.WAITING_EXECUTION_APPROVAL
    assert waiting_approval.profile is not None and not waiting_approval.profile.is_blocked
    assert waiting_approval.plan is not None
    assert waiting_approval.plan.plan_status == "dry_run"
    approval = approvals.create_execution_approval(
        scope=waiting_approval.approval_scope,
        data_grant_id=grant.grant_id,
    )

    approved_but_disabled = _prepare(
        orchestrator,
        artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
    )
    assert approved_but_disabled.route == RouterRoute.BLOCKED
    assert approved_but_disabled.execution_approval.allowed is True
    assert approved_but_disabled.execution_request_created is False
    assert "ordinary_user_execution_disabled_by_policy" in approved_but_disabled.reasons

    changed = _prepare(
        orchestrator,
        artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        parameters={"expected_doublet_rate": 0.12},
    )
    assert changed.route == RouterRoute.BLOCKED
    assert changed.execution_approval.code == "scope_mismatch"
    approvals.revoke_execution_approval(approval.approval_id)
    revoked = _prepare(
        orchestrator,
        artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
    )
    assert revoked.route == RouterRoute.BLOCKED
    assert revoked.execution_approval.code == "revoked"


def _scope():
    return ApprovalScope(
        user_id="user-a",
        artifact_id="artifact-a",
        plan_id="plan-a",
        tool_name="Scrublet",
        tool_version="0.2.3",
        contract_version="contract-v1",
        environment_id="scRNAseq",
        parameter_hash=parameter_hash({"rate": 0.1}),
    )


def _prepare(
    orchestrator,
    artifact_id,
    *,
    data_grant_id=None,
    execution_approval_id=None,
    parameters=None,
    parent_route_override=None,
):
    return orchestrator.prepare_user_execution(
        user_id="user-a",
        artifact_id=artifact_id,
        data_grant_id=data_grant_id,
        execution_approval_id=execution_approval_id,
        request_id="phase6a-request",
        query="prepare a dry-run doublet plan",
        parameters=parameters or {},
        parent_route_override=parent_route_override,
    )
