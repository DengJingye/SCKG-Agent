#!/usr/bin/env python
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import (
    ExecutionPair,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from execution.local_user_service import LocalUserAllowlist, LocalUserService
from execution.probe_builder import ProbeBuilder
from execution.user_workspace import UserWorkspaceService
from tests.fixtures.anndata_factory import write_phase1_fixtures
from tests.test_user_execution_cancellation import (
    test_local_user_cancellation_terminates_process_tree_and_preserves_logs,
)


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    root = PROJECT_ROOT / ".sckg_exec" / "phase6b" / token
    approved_root = root / "approved-inputs"
    source = write_phase1_fixtures(approved_root)["raw_x"]
    probe = ProbeBuilder().build(
        source_path=source,
        output_dir=approved_root / "user-probe",
        profile_id="phase6b-profile",
        fixture_id="phase1_raw_counts_x",
        max_cells=32,
        split_role="development",
    )
    input_hash_before = _sha256(Path(probe.probe_artifact_path))
    data_registry = DataRegistry(
        approved_input_roots=[approved_root], registry_root=root / "data-registry"
    )
    approvals = ApprovalService(root=root / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    workspace = UserWorkspaceService(root=PROJECT_ROOT / ".sckg_exec" / "users")
    orchestrator = ExecutionOrchestrator(
        run_root=root / "unused-runs",
        approved_input_root=approved_root,
        package_root=root / "unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=data_registry,
        approval_service=approvals,
    )
    artifact = data_registry.register(
        user_id="phase6b-user-a", path=Path(probe.probe_artifact_path)
    )
    grant = approvals.grant_data_access(
        user_id="phase6b-user-a", artifact_id=artifact.artifact_id
    )
    pairs = [
        _pair(contracts.load("Scrublet", "0.2.3")),
        _pair(contracts.load("scDblFinder", "1.24.0")),
    ]
    allowlist = LocalUserAllowlist(root=root / "local-user-allowlist")
    allowlist.allow_user(
        user_id="phase6b-user-a",
        allowed_pairs=pairs,
        allowed_artifact_ids=[artifact.artifact_id],
        allowed_data_scopes=["synthetic_fixture"],
        max_runs=4,
    )
    policy = ExecutionPolicy(mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS)
    service = LocalUserService(
        orchestrator=orchestrator,
        data_registry=data_registry,
        approval_service=approvals,
        allowlist=allowlist,
        workspace=workspace,
        policy=policy,
    )

    scrublet = _run_tool(
        service=service,
        orchestrator=orchestrator,
        approvals=approvals,
        grant_id=grant.grant_id,
        artifact_id=artifact.artifact_id,
        tool_name="Scrublet",
        tool_version="0.2.3",
        request_id=f"phase6b-scrublet-{token}",
        package_id=f"phase6b-scrublet-{token}",
        parameters={"n_prin_comps": 3},
    )
    scdblfinder = _run_tool(
        service=service,
        orchestrator=orchestrator,
        approvals=approvals,
        grant_id=grant.grant_id,
        artifact_id=artifact.artifact_id,
        tool_name="scDblFinder",
        tool_version="1.24.0",
        request_id=f"phase6b-scdblfinder-{token}",
        package_id=f"phase6b-scdblfinder-{token}",
        parameters={},
    )

    replay_blocked = _blocked_call(
        service,
        scrublet["approval_id"],
        grant.grant_id,
        artifact.artifact_id,
        scrublet["request_id"],
        scrublet["query"],
        {"n_prin_comps": 3},
        "Scrublet",
        "0.2.3",
        f"phase6b-replay-{token}",
    )
    parameter_change_blocked = _blocked_call(
        service,
        scrublet["approval_id"],
        grant.grant_id,
        artifact.artifact_id,
        scrublet["request_id"],
        scrublet["query"],
        {"n_prin_comps": 3, "expected_doublet_rate": 0.12},
        "Scrublet",
        "0.2.3",
        f"phase6b-parameter-change-{token}",
    )
    cross_user_blocked = False
    try:
        workspace.get_package_directory(
            user_id="phase6b-user-b",
            package_id=scrublet["result"].package_result.package_id,
        )
    except PermissionError:
        cross_user_blocked = True

    with tempfile.TemporaryDirectory(prefix="phase6b-cancel-") as directory:
        test_local_user_cancellation_terminates_process_tree_and_preserves_logs(
            Path(directory)
        )
        cancellation_passed = True

    results = [scrublet["result"], scdblfinder["result"]]
    checks = {
        "scrublet_actual_execution": all(
            run.status == "succeeded" for run in scrublet["result"].execution_runs
        ),
        "scdblfinder_actual_execution": all(
            run.status == "succeeded" for run in scdblfinder["result"].execution_runs
        ),
        "validators_passed": all(
            validation.passed
            for result in results
            for validation in result.validation_results
        ),
        "approval_consumed_once_per_run": all(
            result.approval_uses_consumed == 2 for result in results
        ),
        "approval_replay_blocked": replay_blocked,
        "parameter_change_blocked": parameter_change_blocked,
        "cancellation_terminates_process_tree": cancellation_passed,
        "cross_user_package_blocked": cross_user_blocked,
        "packages_in_user_workspace": all(
            Path(result.package_result.package_path).is_relative_to(
                PROJECT_ROOT / ".sckg_exec" / "users" / "phase6b-user-a" / "packages"
            )
            for result in results
        ),
        "packages_complete": all(
            result.package_result.complete
            and result.package_result.manifest_hashes_valid
            for result in results
        ),
        "input_data_not_copied": all(
            not list(Path(result.package_result.package_path).rglob("*.h5ad"))
            for result in results
        ),
        "input_unchanged": _sha256(Path(probe.probe_artifact_path))
        == input_hash_before,
        "global_policy_default_disabled": ExecutionPolicy().mode
        == ExecutionPolicyMode.DISABLED,
        "restricted_pair_flags_enabled": all(
            [
                contracts.load("Scrublet", "0.2.3").enabled_for_execution,
                contracts.load("scDblFinder", "1.24.0").enabled_for_execution,
                environments.get("scRNAseq").enabled_for_execution,
                environments.get("scDblFinder-R").enabled_for_execution,
            ]
        ),
    }
    summary = {
        "ok": all(checks.values()),
        "checks": checks,
        "execution_policy": {
            "global_default": ExecutionPolicy().mode,
            "smoke_mode": policy.mode,
            "allowed_pairs": [item.model_dump(mode="json") for item in pairs],
        },
        "artifact_id": artifact.artifact_id,
        "scrublet": _result_summary(scrublet["result"]),
        "scdblfinder": _result_summary(scdblfinder["result"]),
        "replay_blocked": replay_blocked,
        "parameter_change_blocked": parameter_change_blocked,
        "cross_user_blocked": cross_user_blocked,
        "cancellation_passed": cancellation_passed,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _run_tool(
    *,
    service,
    orchestrator,
    approvals,
    grant_id,
    artifact_id,
    tool_name,
    tool_version,
    request_id,
    package_id,
    parameters,
):
    query = f"run approved {tool_name} doublet detection"
    preparation = orchestrator.prepare_user_execution(
        user_id="phase6b-user-a",
        artifact_id=artifact_id,
        data_grant_id=grant_id,
        execution_approval_id=None,
        request_id=request_id,
        query=query,
        parameters=parameters,
        tool_name=tool_name,
        tool_version=tool_version,
    )
    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope,
        data_grant_id=grant_id,
        max_uses=2,
    )
    result = service.execute_approved_plan(
        user_id="phase6b-user-a",
        artifact_id=artifact_id,
        data_grant_id=grant_id,
        execution_approval_id=approval.approval_id,
        request_id=request_id,
        query=query,
        parameters=parameters,
        tool_name=tool_name,
        tool_version=tool_version,
        package_id=package_id,
        requested_runs=2,
    )
    return {
        "result": result,
        "approval_id": approval.approval_id,
        "request_id": request_id,
        "query": query,
    }


def _blocked_call(
    service,
    approval_id,
    grant_id,
    artifact_id,
    request_id,
    query,
    parameters,
    tool_name,
    tool_version,
    package_id,
):
    try:
        service.execute_approved_plan(
            user_id="phase6b-user-a",
            artifact_id=artifact_id,
            data_grant_id=grant_id,
            execution_approval_id=approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=tool_name,
            tool_version=tool_version,
            package_id=package_id,
            requested_runs=1,
        )
    except PermissionError:
        return True
    return False


def _pair(contract):
    return ExecutionPair(
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
    )


def _result_summary(result):
    runtimes = [run.runtime_seconds for run in result.execution_runs]
    memories = [
        run.peak_memory_mb
        for run in result.execution_runs
        if run.peak_memory_mb is not None
    ]
    return {
        "actual_runs": len(result.execution_runs),
        "successful_runs": sum(
            run.status == "succeeded" for run in result.execution_runs
        ),
        "validation_passed": all(item.passed for item in result.validation_results),
        "approval_uses_consumed": result.approval_uses_consumed,
        "candidate_ids": [item.candidate_id for item in result.candidate_evaluations],
        "candidate_evaluation_count": len(result.candidate_evaluations),
        "eligible_candidate_count": sum(
            item.eligible_for_decision for item in result.candidate_evaluations
        ),
        "recommended_candidate_id": result.decision_result.recommended_candidate_id,
        "runtime_seconds_total": round(sum(runtimes), 6),
        "runtime_seconds_mean": round(sum(runtimes) / len(runtimes), 6)
        if runtimes
        else None,
        "peak_memory_mb_max": round(max(memories), 3) if memories else None,
        "package_path": result.package_result.package_path,
        "package_complete": result.package_result.complete,
        "manifest_hashes_valid": result.package_result.manifest_hashes_valid,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
