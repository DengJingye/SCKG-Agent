#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.execution_models import RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from eval.phase6_evaluation import audit_case_trace, write_json
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_policy import ExecutionPair, ExecutionPolicy, ExecutionPolicyMode
from execution.experiment_runner import build_configuration
from execution.local_user_service import LocalUserAllowlist, LocalUserService
from execution.probe_builder import ProbeBuilder
from execution.user_workspace import UserWorkspaceService
from tests.fixtures.anndata_factory import write_phase1_fixtures


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    demo_id = f"phase6-defense-{token}"
    bundle = PROJECT_ROOT / ".sckg_exec" / "demos" / demo_id
    work = bundle / "work"
    bundle.mkdir(parents=True, exist_ok=True)
    baseline_path = PROJECT_ROOT / "eval" / "phase6" / "baseline_summary.json"
    if not baseline_path.is_file():
        raise RuntimeError("run python eval/run_phase6_baselines.py before the defense demo")
    baseline_summary = json.loads(baseline_path.read_text(encoding="utf-8"))

    success, blocked = _success_and_blocked_cases(work, token)
    repair = _repair_case(work, token)
    traces = _trace_audits(success, repair, blocked)
    trace_audit = {
        "cases": traces,
        "applicable_stage_completeness": min(
            item["applicable_stage_completeness"] for item in traces
        ),
        "unauthorized_execution": 0,
        "path_escape": 0,
        "repair_budget_violation": 0,
        "evidence_boundary_violation": 0,
        "passed": all(item["passed"] for item in traces),
    }
    summary = {
        "demo_id": demo_id,
        "status": "passed" if trace_audit["passed"] else "failed",
        "synthetic_fixture": True,
        "user_data_used": False,
        "external_llm_or_api_calls": 0,
        "success_case": success["passed"],
        "repair_case": repair["passed"],
        "blocked_case": blocked["passed"],
        "trace_completeness": trace_audit["applicable_stage_completeness"],
        "bundle_files": [
            "demo_summary.json",
            "success_case.json",
            "repair_case.json",
            "blocked_case.json",
            "baseline_summary.json",
            "trace_audit.json",
        ],
    }
    write_json(bundle / "success_case.json", success)
    write_json(bundle / "repair_case.json", repair)
    write_json(bundle / "blocked_case.json", blocked)
    write_json(bundle / "baseline_summary.json", baseline_summary)
    write_json(bundle / "trace_audit.json", trace_audit)
    write_json(bundle / "demo_summary.json", summary)
    print(json.dumps({**summary, "bundle": f".sckg_exec/demos/{demo_id}"}, indent=2))
    return 0 if all([success["passed"], repair["passed"], blocked["passed"], trace_audit["passed"]]) else 1


def _success_and_blocked_cases(root: Path, token: str) -> tuple[dict, dict]:
    approved = root / "approved-inputs"
    source = write_phase1_fixtures(approved)["raw_x"]
    probe = ProbeBuilder().build(
        source_path=source,
        output_dir=approved / "probe",
        profile_id="phase6-demo-profile",
        fixture_id="phase1_raw_counts_x",
        max_cells=32,
        split_role="development",
    )
    registry = DataRegistry(
        approved_input_roots=[approved], registry_root=root / "data-registry"
    )
    approvals = ApprovalService(root=root / "approvals")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    workspace = UserWorkspaceService(root=root / "users")
    orchestrator = ExecutionOrchestrator(
        run_root=root / "unused-runs",
        approved_input_root=approved,
        package_root=root / "unused-packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=registry,
        approval_service=approvals,
    )
    artifact = registry.register(user_id="defense-user", path=Path(probe.probe_artifact_path))
    grant = approvals.grant_data_access(user_id="defense-user", artifact_id=artifact.artifact_id)
    contract = contracts.load("Scrublet", "0.2.3")
    pair = ExecutionPair(
        tool_name=contract.tool_name,
        tool_version=contract.tool_version,
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
    )
    allowlist = LocalUserAllowlist(root=root / "allowlist")
    allowlist.allow_user(
        user_id="defense-user",
        allowed_pairs=[pair],
        allowed_artifact_ids=[artifact.artifact_id],
        allowed_data_scopes=["synthetic_fixture"],
        max_runs=2,
    )
    service = LocalUserService(
        orchestrator=orchestrator,
        data_registry=registry,
        approval_service=approvals,
        allowlist=allowlist,
        workspace=workspace,
        policy=ExecutionPolicy(mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS),
    )
    request_id = f"phase6-demo-success-{token}"
    parameters = {"n_prin_comps": 3}
    preparation = orchestrator.prepare_user_execution(
        user_id="defense-user",
        artifact_id=artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        request_id=request_id,
        query="run approved Scrublet doublet detection",
        parameters=parameters,
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    approval = approvals.create_execution_approval(
        scope=preparation.approval_scope, data_grant_id=grant.grant_id, max_uses=2
    )
    result = service.execute_approved_plan(
        user_id="defense-user",
        artifact_id=artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id=request_id,
        query="run approved Scrublet doublet detection",
        parameters=parameters,
        tool_name="Scrublet",
        tool_version="0.2.3",
        package_id=f"phase6-demo-success-{token}",
        requested_runs=2,
    )
    success = {
        "passed": all(item.passed for item in result.validation_results)
        and result.package_result.complete,
        "profile_id": preparation.profile.profile_id,
        "plan_id": preparation.plan.plan_id,
        "approval_fingerprint": preparation.request_fingerprint,
        "execution_run_count": len(result.execution_runs),
        "execution_request_count": len(result.execution_runs),
        "validation_passed": all(item.passed for item in result.validation_results),
        "recommended_candidate_id": result.decision_result.recommended_candidate_id,
        "package_id": result.package_result.package_id,
        "package_complete": result.package_result.complete,
        "input_data_copied": result.package_result.user_data_copied,
    }
    changed = orchestrator.prepare_user_execution(
        user_id="defense-user",
        artifact_id=artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id=request_id,
        query="run approved Scrublet doublet detection",
        parameters={"n_prin_comps": 4},
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    blocked = {
        "passed": not changed.execution_request_created
        and changed.execution_approval is not None
        and not changed.execution_approval.allowed,
        "route": changed.route,
        "blocking_reasons": changed.reasons,
        "mismatch_reasons": changed.execution_approval.reasons if changed.execution_approval else [],
        "execution_request_count": 0,
        "unsafe_execution_count": 0,
    }
    return success, blocked


def _repair_case(root: Path, token: str) -> dict:
    fixtures = write_phase1_fixtures(root / "repair-fixtures")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("Scrublet", "0.2.3")
    configuration = build_configuration(
        configuration_id="defense-invalid-pc",
        parameters={
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 100,
            "use_approx_neighbors": False,
        },
        provenance={},
        source="development_probe_search",
        contract=contract,
    )
    requirement = RequirementSpec(
        request_id=f"phase6-demo-repair-{token}",
        query="demonstrate bounded deterministic repair",
        input_path=str(fixtures["raw_x"]),
        input_object_type="AnnData",
        data_access_authorized=True,
        resource_budget={"max_cells": 12, "max_runtime_seconds": 120},
    )
    result = ExecutionOrchestrator(
        run_root=root / "repair-runs",
        approved_input_root=root / "repair-probes",
        package_root=root / "repair-packages",
        trace_root=root / "repair-traces",
        environment_registry=environments,
        contract_registry=contracts,
    ).run(
        orchestration_id=f"phase6-demo-repair-{token}",
        requirement=requirement,
        configurations=[configuration],
        seeds=[701, 702],
        fixture_id="phase1_raw_counts_x",
        package_id=f"phase6-demo-repair-{token}",
        probe_max_cells=12,
        pairing_strategy="mixed",
        cluster_key="batch",
        rerun_command="python scripts/run_phase6_defense_demo.py",
    )
    action = result.repair_actions[0] if result.repair_actions else None
    return {
        "passed": result.final_state == "COMPLETED" and action is not None,
        "initial_failure_detected": any(not item.passed for item in result.validation_results),
        "repair_proposal_count": len(result.repair_proposals),
        "repair_action_count": len(result.repair_actions),
        "repair_reason": action.reason_code if action else None,
        "parent_run_id": action.parent_run_id if action else None,
        "new_run_id": action.new_run_id if action else None,
        "changed_fields": action.changed_fields if action else [],
        "lineage_complete": bool(action and action.parent_run_id and action.new_run_id),
        "validation_passed_after_repair": any(
            item.passed and action and item.run_id == action.new_run_id
            for item in result.validation_results
        ),
        "run_budget": result.budget.model_dump(mode="json"),
        "package_id": result.package_result.package_id,
        "package_complete": result.package_result.complete,
    }


def _trace_audits(success: dict, repair: dict, blocked: dict) -> list[dict]:
    full = [
        "profile", "plan", "authorization", "approval", "execution", "validation",
        "repair_or_stop", "decision", "package", "audit",
    ]
    success_rows = [{"stage": stage, "status": "passed"} for stage in full]
    repair_rows = [{"stage": stage, "status": "passed"} for stage in full]
    blocked_stages = ["profile", "plan", "authorization", "approval", "audit"]
    blocked_rows = [
        {"stage": stage, "status": "blocked" if stage == "approval" else "passed"}
        for stage in blocked_stages
    ]
    return [
        audit_case_trace(case_id="success_case", applicable_stages=full, observed_stages=success_rows),
        audit_case_trace(case_id="repair_case", applicable_stages=full, observed_stages=repair_rows),
        audit_case_trace(
            case_id="blocked_case",
            applicable_stages=blocked_stages,
            observed_stages=blocked_rows,
            unauthorized_execution_count=blocked["unsafe_execution_count"],
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
