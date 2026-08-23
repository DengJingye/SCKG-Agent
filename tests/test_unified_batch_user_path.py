from __future__ import annotations

from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.local_user_service import _validator_for_contract
from execution.validators.integration import IntegrationValidator
from tests.fixtures.anndata_factory import write_phase5_batch_fixtures


def test_registered_batch_artifact_compiles_batch_plan_after_authorization(tmp_path):
    approved_root = tmp_path / "approved"
    source = write_phase5_batch_fixtures(approved_root)["valid_pca"]
    data = DataRegistry(
        approved_input_roots=[approved_root],
        registry_root=tmp_path / "registry",
    )
    artifact = data.register(user_id="batch-user", path=source)
    approvals = ApprovalService(root=tmp_path / "approvals")
    grant = approvals.grant_data_access(
        user_id="batch-user",
        artifact_id=artifact.artifact_id,
    )
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    orchestrator = ExecutionOrchestrator(
        run_root=tmp_path / "runs",
        approved_input_root=approved_root,
        package_root=tmp_path / "packages",
        environment_registry=environments,
        contract_registry=contracts,
        data_registry=data,
        approval_service=approvals,
    )

    prepared = orchestrator.prepare_user_execution(
        user_id="batch-user",
        artifact_id=artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        request_id="batch-user-plan",
        query="Run Harmony batch integration",
        parameters={},
        tool_name="Harmony",
        tool_version="2.0.0",
    )

    assert prepared.profile is not None
    assert prepared.profile.batch_key == "batch"
    assert prepared.profile.batch_count == 3
    assert prepared.plan is not None
    assert prepared.plan.plan_status == "dry_run"
    assert any(node.node_id == "run_integration_candidate" for node in prepared.plan.steps)
    assert prepared.execution_request_created is False


def test_batch_contract_uses_integration_validator():
    environments = EnvironmentRegistry()
    contract = ToolContractRegistry(environment_registry=environments).load(
        "Scanorama",
        "1.7.4",
    )

    assert isinstance(_validator_for_contract(contract), IntegrationValidator)


def test_runs_results_ui_exposes_only_four_qualified_tools():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py").read_text()

    for label in (
        "Scrublet 0.2.3",
        "scDblFinder 1.24.0",
        "Harmony 2.0.0",
        "Scanorama 1.7.4",
    ):
        assert label in source
    assert "CellTypist 1.7.1" not in source
    assert "SingleR 2.14.0" not in source
