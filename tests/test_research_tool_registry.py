from __future__ import annotations

from agent.research_chat_reasoner import _validated_tool_calls
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from tests.test_research_chat_service import _service


def test_llm_tool_call_validation_drops_unknown_and_duplicate_calls():
    calls = _validated_tool_calls(
        [
            {
                "tool_name": "search_evidence",
                "query": "Scrublet raw counts",
                "canonical_task": "doublet_detection",
                "tool_names": ["Scrublet"],
            },
            {
                "tool_name": "search_evidence",
                "query": "duplicate",
                "canonical_task": "doublet_detection",
                "tool_names": ["Scrublet"],
            },
            {"tool_name": "run_shell", "query": "rm -rf /"},
        ],
        fallback_query="doublet detection",
        canonical_tasks={"doublet_detection"},
    )

    assert [call.tool_name for call in calls] == ["search_evidence"]
    assert calls[0].canonical_task == "doublet_detection"


def test_read_only_tool_registry_returns_evidence_and_contract(tmp_path):
    service = _service(tmp_path)
    plan = ResearchToolPlan(
        source="semantic_parser",
        answer_strategy="grounded",
        calls=[
            ResearchToolCall(
                call_id="search-1",
                tool_name="search_evidence",
                query="Scrublet raw count input",
                canonical_task="doublet_detection",
                tool_names=["Scrublet"],
                claim_types=["input_requirement"],
            ),
            ResearchToolCall(
                call_id="contract-1",
                tool_name="get_tool_contract",
                canonical_task="doublet_detection",
                tool_names=["Scrublet"],
            ),
        ],
    )

    result = service._research_tools.execute(
        plan,
        fallback_query="doublet detection",
        fallback_task="doublet_detection",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    )

    assert [item.status for item in result.observations] == ["completed", "completed"]
    assert result.retrieval is not None
    assert result.retrieval.hits[0].source_bound is True
    assert result.contract_context[0]["tool_name"] == "Scrublet"
    assert result.contract_context[0]["planning_allowed"] is True
    assert result.contract_context[0]["contract_id"] == "scrublet:0.2.3"


def test_unqualified_workflow_tool_is_blocked_without_execution(tmp_path):
    service = _service(tmp_path)
    plan = ResearchToolPlan(
        source="semantic_parser",
        answer_strategy="workflow",
        calls=[
            ResearchToolCall(
                call_id="workflow-1",
                tool_name="compile_workflow",
                canonical_task="cell_cell_communication",
            )
        ],
    )

    result = service._research_tools.execute(
        plan,
        fallback_query="CellPhoneDB workflow",
        fallback_task="cell_cell_communication",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    )

    assert result.observations[0].status == "blocked"
    assert result.workflow_bundles == []


def test_read_only_tool_registry_discovers_capability_pack_without_execution(tmp_path):
    service = _service(tmp_path)
    plan = ResearchToolPlan(
        source="semantic_parser",
        answer_strategy="grounded",
        calls=[
            ResearchToolCall(
                call_id="capability-1",
                tool_name="discover_capabilities",
                query="Scanpy core workflow",
                canonical_task="",
            )
        ],
    )

    result = service._research_tools.execute(
        plan,
        fallback_query="Scanpy core workflow",
        fallback_task="",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    )

    assert result.observations[0].status == "completed"
    assert result.capability_context
    assert {item["pack_id"] for item in result.capability_context} == {"scanpy_core"}
    assert all(item["execution_eligible"] is False for item in result.capability_context)
