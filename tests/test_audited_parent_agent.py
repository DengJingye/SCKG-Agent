from agent.audited_parent_agent import AuditedParentAgent
from agent.bounded_parent_agent import ParentAgentRequest


def test_parent_routes_both_qualified_task_families_to_dry_run_plans():
    agent = AuditedParentAgent()
    doublet, _ = agent.plan(
        ParentAgentRequest(request_id="portfolio-doublet", query="Detect scRNA-seq doublets"),
        case_id="doublet",
    )
    integration, trace = agent.plan(
        ParentAgentRequest(
            request_id="portfolio-integration",
            query="Integrate three scRNA-seq batches with Harmony",
        ),
        case_id="integration",
    )

    assert doublet.selected_tool == "Scrublet"
    assert doublet.workflow_plan.plan_status == "dry_run"
    assert integration.selected_tool == "Harmony"
    assert integration.task == "batch integration"
    assert integration.workflow_plan.plan_status == "dry_run"
    assert [row.tool_name for row in integration.action_bundles] == ["Harmony", "Scanorama"]
    assert trace.execution_request_count == 0
    assert trace.applicable_stage_completeness == 1.0


def test_evidence_limited_task_is_blocked_before_execution():
    result, trace = AuditedParentAgent().plan(
        ParentAgentRequest(
            request_id="portfolio-evidence-block",
            query="Execute CellPhoneDB for cell-cell communication now",
            requested_tool="CellPhoneDB",
        ),
        case_id="evidence-block",
    )

    assert result.status == "BLOCKED"
    assert result.execution_request_count == 0
    assert trace.status == "BLOCKED"
    assert trace.execution_request_count == 0
