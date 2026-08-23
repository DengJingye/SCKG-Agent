from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.deterministic_router import DeterministicRouter
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_policy import (
    ExecutionPair,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from execution.local_user_service import LocalUserAllowlist
from execution.preview_execution_service import PreviewExecutionService
from execution.preview_result_store import PreviewResultStore
from execution.research_workspace_service import ResearchWorkspaceService
from execution.user_workspace import UserWorkspaceService
from scripts.run_path_to_preview_notebook_smoke import _write_smoke_fixture


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sckg-preview-run-smoke-") as temporary:
        root = Path(temporary)
        source = _write_smoke_fixture(root / "inputs" / "pbmc.h5ad")
        source_hash_before = _sha256(source)
        registry = DataRegistry(
            approved_input_roots=[root / "inputs"], registry_root=root / "registry"
        )
        approvals = ApprovalService(root=root / "approvals")
        environments = EnvironmentRegistry()
        contracts = ToolContractRegistry(environment_registry=environments)
        workspace = UserWorkspaceService(root=root / "users")
        allowlist = LocalUserAllowlist(root=root / "allowlist")
        policy = ExecutionPolicy(mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS)
        research = ResearchWorkspaceService(
            data_registry=registry,
            approval_service=approvals,
            workspace_root=root / "research",
        )
        artifact = registry.register(
            user_id="smoke-user", path=source, artifact_id="pbmc-preview"
        )
        grant = approvals.grant_data_access(
            user_id="smoke-user", artifact_id=artifact.artifact_id
        )
        profile = research.profile(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            data_grant_id=grant.grant_id,
        )
        preview = research.build_preview(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            profile=profile,
            data_grant_id=grant.grant_id,
            max_cells=120,
            random_seed=20260812,
            stratify_key="batch",
        )
        notebook = research.compile_notebook(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            profile=profile,
            preview=preview,
            data_grant_id=grant.grant_id,
            parameters={"expected_doublet_rate": 0.08, "n_prin_comps": 10},
        )
        contract = contracts.load("Scrublet", "0.2.3")
        allowlist.allow_user(
            user_id="smoke-user",
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
            max_runs=1,
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
        preparation = service.prepare(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
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
        result = service.execute(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
            request_id="preview-smoke-request",
        )
        recovered_store = PreviewResultStore(
            workspace_root=research.workspace_root,
            execution_root=workspace.root,
        )
        recovered_summary = recovered_store.list_results(
            user_id="smoke-user", artifact_id=artifact.artifact_id
        )[0]
        recovered_result = recovered_store.load_result(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            run_id=result.execution_run.run_id,
        )
        checkpoint = service.checkpoints.inspect_result(
            result=recovered_result,
            integrity=recovered_summary.integrity,
        )
        interpretation = service.interpret_result(result=recovered_result)
        source_hash_after = _sha256(source)
        summary = {
            "source_unchanged": source_hash_before == source_hash_after,
            "preview_cells": preview.n_preview_cells,
            "fixed_wrapper_executed": result.execution_run.status == "succeeded",
            "execution_purpose": result.execution_run.execution_purpose,
            "user_data_preview_used": result.execution_run.user_data_used,
            "validation_passed": result.validation_result.passed,
            "step_events": [
                {"step_id": item.step_id, "status": item.status}
                for item in result.step_events
            ],
            "validation_authority": result.validation_result.metric_authority,
            "histogram_generated": "doublet_score_histogram.png"
            in result.execution_run.artifact_paths,
            "scientific_claim_allowed": result.scientific_claim_allowed,
            "original_data_copied": result.original_data_copied,
            "approval_uses_consumed": approvals._load_approval(
                approval.approval_id
            ).uses_consumed,
            "result_recovered_after_restart": (
                recovered_result.execution_run.run_id == result.execution_run.run_id
            ),
            "result_integrity_valid": recovered_summary.integrity.passed,
            "history_status": recovered_summary.status,
            "checkpoint_status": checkpoint.overall_status,
            "checkpoint_execution_request_count": checkpoint.execution_request_count,
            "interpretation_status": interpretation.status,
            "interpretation_usable_for_preview_review": (
                interpretation.usable_for_preview_review
            ),
            "interpretation_scientific_claim_allowed": (
                interpretation.scientific_claim_allowed
            ),
            "interpretation_has_plot_guidance": (
                interpretation.plot_explanation is not None
            ),
            "interpretation_has_next_actions": bool(interpretation.next_actions),
            "interpretation_auto_actions": sum(
                1 for item in interpretation.next_actions if item.automatic
            ),
            "default_execution_policy": ExecutionPolicy().mode,
        }
        expected = {
            "source_unchanged": True,
            "fixed_wrapper_executed": True,
            "execution_purpose": "representative_preview",
            "user_data_preview_used": True,
            "validation_passed": True,
            "step_events": [
                {"step_id": "run_tool", "status": "COMPLETED"},
                {"step_id": "validate_outputs", "status": "COMPLETED"},
            ],
            "validation_authority": "preview_engineering_metric",
            "histogram_generated": True,
            "scientific_claim_allowed": False,
            "original_data_copied": False,
            "approval_uses_consumed": 1,
            "result_recovered_after_restart": True,
            "result_integrity_valid": True,
            "history_status": "COMPLETED",
            "checkpoint_status": "CURRENT",
            "checkpoint_execution_request_count": 0,
            "interpretation_status": "COMPLETED",
            "interpretation_usable_for_preview_review": True,
            "interpretation_scientific_claim_allowed": False,
            "interpretation_has_plot_guidance": True,
            "interpretation_has_next_actions": True,
            "interpretation_auto_actions": 0,
            "default_execution_policy": "disabled",
        }
        for key, value in expected.items():
            if summary[key] != value:
                raise AssertionError(summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
