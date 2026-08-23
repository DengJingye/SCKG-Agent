from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry, RegisteredDataArtifact
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import (
    ExecutionPair,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from execution.execution_ui_service import ExecutionUIService
from execution.local_user_service import LocalUserAllowlist, LocalUserService
from execution.probe_builder import ProbeBuilder
from execution.user_workspace import UserWorkspaceService
from tests.fixtures.anndata_factory import write_phase1_fixtures


@dataclass
class UIHarness:
    service: ExecutionUIService
    registry: DataRegistry
    approvals: ApprovalService
    allowlist: LocalUserAllowlist
    workspace: UserWorkspaceService
    orchestrator: ExecutionOrchestrator
    artifact: RegisteredDataArtifact


def build_ui_harness(
    root: Path,
    *,
    mode: ExecutionPolicyMode = ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS,
    allow_user: bool = True,
) -> UIHarness:
    approved_root = root / "inputs"
    source = write_phase1_fixtures(approved_root)["raw_x"]
    probe = ProbeBuilder().build(
        source_path=source,
        output_dir=approved_root / "probe",
        profile_id="ui-profile",
        fixture_id="phase1_raw_counts_x",
        max_cells=24,
        split_role="development",
    )
    registry = DataRegistry(
        approved_input_roots=[approved_root], registry_root=root / "data-registry"
    )
    artifact = registry.register(
        user_id="user-a", path=Path(probe.probe_artifact_path)
    )
    approvals = ApprovalService(root=root / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    workspace = UserWorkspaceService(root=root / "users")
    allowlist = LocalUserAllowlist(root=root / "allowlist")
    pairs = [
        _pair(contracts.load("Scrublet", "0.2.3")),
        _pair(contracts.load("scDblFinder", "1.24.0")),
    ]
    if allow_user:
        allowlist.allow_user(
            user_id="user-a",
            allowed_pairs=pairs,
            allowed_artifact_ids=[artifact.artifact_id],
            allowed_data_scopes=["synthetic_fixture"],
            max_runs=12,
        )
    policy = ExecutionPolicy(mode=mode)
    orchestrator = ExecutionOrchestrator(
        run_root=root / "unused-runs",
        approved_input_root=approved_root,
        package_root=root / "unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=registry,
        approval_service=approvals,
    )
    local_service = LocalUserService(
        orchestrator=orchestrator,
        data_registry=registry,
        approval_service=approvals,
        allowlist=allowlist,
        workspace=workspace,
        policy=policy,
    )
    service = ExecutionUIService(
        data_registry=registry,
        approval_service=approvals,
        execution_policy=policy,
        local_user_service=local_service,
        orchestrator=orchestrator,
        workspace=workspace,
        allowlist=allowlist,
        contract_registry=contracts,
        environment_registry=environments,
    )
    return UIHarness(
        service=service,
        registry=registry,
        approvals=approvals,
        allowlist=allowlist,
        workspace=workspace,
        orchestrator=orchestrator,
        artifact=artifact,
    )


def prepare_context(
    harness: UIHarness,
    *,
    approval_id: str | None = None,
    parameters: dict | None = None,
    tool_name: str = "Scrublet",
    tool_version: str = "0.2.3",
    request_id: str = "ui-request",
    query: str = "run approved local doublet detection",
):
    grant = harness.approvals.grant_data_access(
        user_id="user-a", artifact_id=harness.artifact.artifact_id
    )
    context = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval_id,
        request_id=request_id,
        query=query,
        parameters=parameters or {},
        tool_name=tool_name,
        tool_version=tool_version,
    )
    return grant, context


def approval_confirmations() -> dict[str, bool]:
    return {
        "data_confirmed": True,
        "tool_confirmed": True,
        "parameters_confirmed": True,
        "environment_confirmed": True,
    }


def _pair(contract) -> ExecutionPair:
    return ExecutionPair(
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
    )
