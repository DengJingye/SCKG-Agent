from agent.bounded_parent_agent import BoundedParentAgent, ParentAgentRequest
from core.deterministic_router import RouterRoute
from tests.execution_ui_helpers import build_ui_harness


def test_generic_doublet_request_compiles_governed_dry_run_plan():
    result = BoundedParentAgent().run(
        ParentAgentRequest(
            request_id="agent-generic",
            query="Plan doublet detection for an scRNA-seq AnnData dataset",
        )
    )

    assert result.status == "READY"
    assert result.route == RouterRoute.PLAN_ONLY
    assert result.selected_tool in {"Scrublet", "scDblFinder"}
    assert result.workflow_plan is not None
    assert result.workflow_plan.plan_status == "dry_run"
    assert result.workflow_plan.execution_eligible is False
    assert result.execution_request_count == 0
    assert result.action_bundles
    assert all(bundle.action_id == "action:doublet-detection" for bundle in result.action_bundles)
    assert all(bundle.execution_allowed is False for bundle in result.action_bundles)
    assert [call.capability for call in result.tool_calls] == [
        "deterministic_requirement_parser",
        "evidence_graph_query.rank_tools",
        "action_bundle_retriever.retrieve",
        "tool_contract_registry.load",
        "environment_registry.get",
        "execution_plan_compiler.compile",
        "deterministic_router.route",
    ]


def test_annotation_task_returns_planning_only_bundles_without_execution():
    result = BoundedParentAgent().run(
        ParentAgentRequest(
            request_id="agent-annotation",
            query="Annotate cell types in an scRNA-seq dataset",
        )
    )

    assert result.status == "BLOCKED"
    assert result.route == RouterRoute.CONTRACT_REVIEW
    assert result.workflow_plan is None
    assert result.execution_request_count == 0
    assert {bundle.tool_name for bundle in result.action_bundles} == {
        "CellTypist",
        "SingleR",
    }
    assert all(bundle.readiness == "planning_only" for bundle in result.action_bundles)
    assert all(bundle.planning_allowed for bundle in result.action_bundles)
    assert all(
        not bundle.execution_contract_qualified for bundle in result.action_bundles
    )
    assert {item["candidate_basis"] for item in result.candidate_context} == {
        "catalog_metadata"
    }
    readiness = {
        item["tool_name"]: item["decision_readiness"]
        for item in result.candidate_context
    }
    assert readiness["CellTypist"] == "planning_only"
    assert readiness["SingleR"] == "planning_only"


def test_batch_integration_with_cell_type_labels_is_not_misrouted_to_annotation():
    result = BoundedParentAgent().run(
        ParentAgentRequest(
            request_id="agent-batch-labels",
            query="Plan batch integration for three scRNA-seq batches with cell-type labels.",
        )
    )

    assert result.status == "READY"
    assert result.route == RouterRoute.PLAN_ONLY
    assert result.task == "batch integration"
    assert {bundle.tool_name for bundle in result.action_bundles} == {
        "Harmony",
        "Scanorama",
    }


def test_named_batch_tools_route_to_batch_integration_action_space():
    agent = BoundedParentAgent()

    scanorama = agent.run(
        ParentAgentRequest(
            request_id="agent-scanorama",
            query="Create a Scanorama dry-run plan with exact neighbors.",
            requested_tool="Scanorama",
        )
    )
    comparison = agent.run(
        ParentAgentRequest(
            request_id="agent-batch-compare",
            query="Compare Harmony and Scanorama using batch mixing and biology conservation.",
        )
    )

    assert scanorama.route == RouterRoute.PLAN_ONLY
    assert scanorama.selected_tool == "Scanorama"
    assert comparison.route == RouterRoute.PLAN_ONLY
    assert {bundle.tool_name for bundle in comparison.action_bundles} == {
        "Harmony",
        "Scanorama",
    }


def test_registered_artifact_is_not_profiled_without_data_grant(tmp_path):
    harness = build_ui_harness(tmp_path / "agent")
    result = BoundedParentAgent(orchestrator=harness.orchestrator).run(
        ParentAgentRequest(
            request_id="agent-no-grant",
            user_id="user-a",
            query="Run doublet detection on this scRNA-seq AnnData",
            artifact_id=harness.artifact.artifact_id,
        )
    )

    assert result.status == "WAITING"
    assert result.route == RouterRoute.WAITING_DATA_AUTHORIZATION
    assert result.data_profile is None
    assert result.workflow_plan is None
    assert result.execution_request_count == 0
    assert result.action_bundles
    assert result.action_bundles[0].data_compatibility == "generic"
    assert result.action_bundles[0].execution_allowed is False


def test_authorized_artifact_is_profiled_but_waits_for_exact_approval(tmp_path):
    harness = build_ui_harness(tmp_path / "agent")
    grant = harness.approvals.grant_data_access(
        user_id="user-a", artifact_id=harness.artifact.artifact_id
    )
    result = BoundedParentAgent(orchestrator=harness.orchestrator).run(
        ParentAgentRequest(
            request_id="agent-approved-profile",
            user_id="user-a",
            query="Run doublet detection on this scRNA-seq AnnData",
            artifact_id=harness.artifact.artifact_id,
            data_grant_id=grant.grant_id,
        )
    )

    assert result.status == "WAITING"
    assert result.route == RouterRoute.WAITING_EXECUTION_APPROVAL
    assert result.data_profile is not None
    assert result.data_profile.selected_count_source is not None
    assert result.workflow_plan is not None
    assert result.workflow_plan.data_awareness == "data_aware"
    assert result.execution_request_count == 0
    assert result.action_bundles
    assert result.action_bundles[0].data_compatibility == "compatible"
    assert result.action_bundles[0].execution_allowed is False
    assert "approval" in result.final_summary.casefold()
