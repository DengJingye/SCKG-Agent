#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from core.deterministic_router import RouterRoute
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import ExecutionPolicy, ExecutionPolicyMode
from execution.user_workspace import UserWorkspaceService
from tests.fixtures.anndata_factory import write_phase1_fixtures


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    root = PROJECT_ROOT / ".sckg_exec" / "phase6a" / token
    approved_root = root / "approved-inputs"
    source = write_phase1_fixtures(approved_root)["raw_x"]
    source_hash_before = _sha256(source)
    data_registry = DataRegistry(
        approved_input_roots=[approved_root], registry_root=root / "data-registry"
    )
    approval_service = ApprovalService(root=root / "approvals")
    workspace = UserWorkspaceService(root=PROJECT_ROOT / ".sckg_exec" / "users")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    orchestrator = ExecutionOrchestrator(
        run_root=root / "unused-runs",
        approved_input_root=approved_root,
        package_root=root / "unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=data_registry,
        approval_service=approval_service,
    )

    artifact = data_registry.register(user_id="phase6a-user", path=source)
    before_grant = _prepare(orchestrator, artifact.artifact_id)
    grant = approval_service.grant_data_access(
        user_id="phase6a-user", artifact_id=artifact.artifact_id
    )
    before_approval = _prepare(
        orchestrator, artifact.artifact_id, data_grant_id=grant.grant_id
    )
    approval = approval_service.create_execution_approval(
        scope=before_approval.approval_scope,
        data_grant_id=grant.grant_id,
    )
    approved_but_disabled = _prepare(
        orchestrator,
        artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
    )
    changed_parameters = _prepare(
        orchestrator,
        artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        parameters={"expected_doublet_rate": 0.12},
    )
    approval_service.revoke_execution_approval(approval.approval_id)
    revoked = _prepare(
        orchestrator,
        artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
    )

    run_dir = workspace.create_run_directory(
        user_id="phase6a-user", run_id=f"run-{token}"
    )
    package_dir = workspace.create_package_directory(
        user_id="phase6a-user", package_id=f"package-{token}"
    )
    workspace.write_package_manifest(
        user_id="phase6a-user",
        package_id=package_dir.name,
        artifact_id=artifact.artifact_id,
        input_hash=artifact.sha256,
        plan_id=before_approval.plan.plan_id,
    )
    cross_user_blocked = False
    try:
        data_registry.get(artifact.artifact_id, user_id="other-user")
    except PermissionError:
        cross_user_blocked = True
    run_cross_user_blocked = False
    try:
        workspace.get_run_directory(user_id="other-user", run_id=run_dir.name)
    except PermissionError:
        run_cross_user_blocked = True

    metadata_text = (root / "data-registry" / "artifacts.jsonl").read_text(
        encoding="utf-8"
    )
    checks = {
        "registered_artifact": artifact.sha256 == source_hash_before,
        "data_path_redacted": str(source.resolve()) not in metadata_text,
        "authorized_profile": before_approval.profile is not None
        and not before_approval.profile.is_blocked,
        "dry_run_plan_generated": before_approval.plan is not None
        and before_approval.plan.plan_status == "dry_run",
        "blocked_before_data_authorization": before_grant.route
        == RouterRoute.WAITING_DATA_AUTHORIZATION,
        "blocked_before_execution_approval": before_approval.route
        == RouterRoute.WAITING_EXECUTION_APPROVAL,
        "plan_specific_approval_created": approval.request_fingerprint
        == before_approval.request_fingerprint,
        "approved_but_user_execution_disabled": approved_but_disabled.route
        == RouterRoute.BLOCKED
        and approved_but_disabled.execution_approval.allowed,
        "parameter_change_invalidates_approval": changed_parameters.execution_approval.code
        == "scope_mismatch",
        "revocation_blocks_execution": revoked.execution_approval.code == "revoked",
        "cross_user_artifact_blocked": cross_user_blocked,
        "cross_user_run_blocked": run_cross_user_blocked,
        "execution_request_count_zero": not any(
            item.execution_request_created
            for item in [
                before_grant,
                before_approval,
                approved_but_disabled,
                changed_parameters,
                revoked,
            ]
        ),
        "input_data_not_copied": not list(
            (PROJECT_ROOT / ".sckg_exec" / "users" / "phase6a-user").rglob("*.h5ad")
        ),
        "original_input_unchanged": _sha256(source) == source_hash_before,
        "global_execution_policy_disabled": ExecutionPolicy().mode
        == ExecutionPolicyMode.DISABLED,
    }
    summary = {
        "ok": all(checks.values()),
        "checks": checks,
        "artifact": artifact.model_dump(mode="json"),
        "routes": {
            "before_data_grant": before_grant.route,
            "before_execution_approval": before_approval.route,
            "approval_valid_but_execution_disabled": approved_but_disabled.route,
            "parameter_changed": changed_parameters.route,
            "approval_revoked": revoked.route,
        },
        "approval_scope": before_approval.approval_scope.model_dump(mode="json"),
        "request_fingerprint": approval.request_fingerprint,
        "execution_request_created": False,
        "user_run_root": str(run_dir.relative_to(PROJECT_ROOT)),
        "user_package_root": str(package_dir.relative_to(PROJECT_ROOT)),
        "input_data_copied": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _prepare(
    orchestrator,
    artifact_id,
    *,
    data_grant_id=None,
    execution_approval_id=None,
    parameters=None,
):
    return orchestrator.prepare_user_execution(
        user_id="phase6a-user",
        artifact_id=artifact_id,
        data_grant_id=data_grant_id,
        execution_approval_id=execution_approval_id,
        request_id="phase6a-smoke-request",
        query="prepare a user-specific doublet detection plan",
        parameters=parameters or {},
    )


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
