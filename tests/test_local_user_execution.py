from __future__ import annotations

import pytest

from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import ExecutionPair, ExecutionPolicy
from execution.local_user_service import LocalUserAllowlist, LocalUserService
from execution.user_workspace import UserWorkspaceService
from tests.fixtures.anndata_factory import write_phase1_fixtures


def test_default_policy_blocks_local_user_before_execution_and_scope_is_exact(tmp_path):
    approved_root = tmp_path / "inputs"
    source = write_phase1_fixtures(approved_root)["raw_x"]
    registry = DataRegistry(
        approved_input_roots=[approved_root], registry_root=tmp_path / "data-registry"
    )
    approvals = ApprovalService(root=tmp_path / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    orchestrator = ExecutionOrchestrator(
        run_root=tmp_path / "unused-runs",
        approved_input_root=approved_root,
        package_root=tmp_path / "unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=registry,
        approval_service=approvals,
    )
    artifact = registry.register(user_id="user-a", path=source)
    grant = approvals.grant_data_access(
        user_id="user-a", artifact_id=artifact.artifact_id
    )
    preparation = orchestrator.prepare_user_execution(
        user_id="user-a",
        artifact_id=artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        request_id="local-user-plan",
        query="plan doublet detection",
        parameters={},
    )
    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope,
        data_grant_id=grant.grant_id,
        max_uses=2,
    )
    contract = contracts.load("Scrublet", "0.2.3")
    pair = ExecutionPair(
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
    )
    allowlist = LocalUserAllowlist(root=tmp_path / "allowlist")
    allowlist.allow_user(
        user_id="user-a",
        allowed_pairs=[pair],
        allowed_artifact_ids=[artifact.artifact_id],
        allowed_data_scopes=["synthetic_fixture"],
        max_runs=2,
    )
    workspace = UserWorkspaceService(root=tmp_path / "users")
    service = LocalUserService(
        orchestrator=orchestrator,
        data_registry=registry,
        approval_service=approvals,
        allowlist=allowlist,
        workspace=workspace,
        policy=ExecutionPolicy(),
    )

    with pytest.raises(PermissionError, match="execution_policy_disabled"):
        service.execute_approved_plan(
            user_id="user-a",
            artifact_id=artifact.artifact_id,
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            request_id="local-user-plan",
            query="plan doublet detection",
            parameters={},
            tool_name="Scrublet",
            tool_version="0.2.3",
            package_id="package-local-user",
        )
    assert not list((tmp_path / "users").glob("*/runs/*"))
    with pytest.raises(PermissionError, match="cross-user"):
        registry.get(artifact.artifact_id, user_id="user-b")

    changed = orchestrator.prepare_user_execution(
        user_id="user-a",
        artifact_id=artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id="local-user-plan",
        query="plan doublet detection",
        parameters={"expected_doublet_rate": 0.12},
    )
    assert changed.execution_approval.code == "scope_mismatch"
