from __future__ import annotations

from core.research_agent_models import AgentMode, ResearchAgentRequest
from tests.test_research_chat_service import _service


def test_ask_mode_answers_without_compiling_or_handoff(tmp_path):
    service = _service(tmp_path)
    response = service.run_request(
        ResearchAgentRequest(
            request_id="entry-ask",
            query="What raw count input does Scrublet require?",
            mode=AgentMode.ASK,
        )
    )

    assert response.state.mode == AgentMode.ASK
    assert response.status == "ANSWERED"
    assert response.workflow_plan is None
    assert response.execution_handoff.status == "not_requested"
    assert response.execution_handoff.execution_request_count == 0
    assert response.workspace_handoff.status == "not_applicable"
    assert response.canonical_trace_id == response.state.canonical_trace_id


def test_plan_mode_compiles_dry_run_without_execution(tmp_path):
    service = _service(tmp_path)
    response = service.run_request(
        ResearchAgentRequest(
            request_id="entry-plan",
            query="Build a doublet detection workflow.",
            mode=AgentMode.PLAN,
        )
    )

    assert response.state.mode == AgentMode.PLAN
    assert response.workflow_plan["plan_status"] == "dry_run"
    assert response.execution_handoff.status == "not_requested"
    assert response.execution_handoff.execution_request_count == 0
    assert response.workspace_handoff.status == "available"
    assert response.workspace_handoff.task_family == "doublet_detection"
    assert response.workspace_handoff.tool_name == "Scrublet"
    assert response.workspace_handoff.notebook_strategy == "fixed_shadow"
    assert response.workspace_handoff.stepwise_preview_available is True
    assert response.workspace_handoff.origin_trace_id == response.canonical_trace_id
    assert response.workspace_handoff.parent_request_id == response.state.request_id


def test_run_mode_without_registered_data_waits_and_never_executes(tmp_path):
    service = _service(tmp_path)
    response = service.run_request(
        ResearchAgentRequest(
            request_id="entry-run",
            query="Run doublet detection on my data.",
            mode=AgentMode.RUN,
        )
    )

    assert response.state.mode == AgentMode.RUN
    assert response.status == "WAITING"
    assert "registered_artifact_required_for_run" in response.state.blockers
    assert response.execution_handoff.approval_required is True
    assert response.execution_handoff.execution_request_count == 0
    assert response.direct_answer.startswith("**尚未执行。**")
    assert "ExecutionRequest：`0`" in response.direct_answer


def test_same_graph_nodes_are_used_without_optional_langgraph(tmp_path):
    state = _service(tmp_path).run("Build a doublet detection workflow.")
    graph = state["context_pack"]["application_graph"]

    assert graph["same_business_nodes_with_or_without_langgraph"] is True
    assert graph["visited_nodes"] == [
        "gateway",
        "requirement_parse",
        "action_retrieval",
        "plan_compile",
        "deterministic_route",
        "answer_or_handoff",
    ]


def test_main_ui_does_not_import_legacy_workflow_runtime():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py").read_text()

    assert "run_sckg_workflow_traced" not in source
    assert source.count('(\"Research Workspace\", \"chat\")') == 1
    assert source.count('(\"Runs & Results\", \"execution_ui\")') == 1
    assert source.count('(\"Graph Explorer\", \"graph_explorer\")') == 1
    assert "research_agent_mode" not in source
    assert "AUTO intent routing" in source
    assert "DEGRADED LOCAL FALLBACK" in source
    assert "LLM FAILED · {model}" in source
    assert "Provider: {provider} · failure: {error}" in source
    assert "加密保存并解锁" in source
    assert "解锁已保存配置" in source
    assert "本地加密口令（由你自己设置）" in source
    assert "它不是 API key，也不是 DeepSeek 密码" in source
    assert 'mode == "system_info_local"' in source
    assert 'mode == "product_capabilities_local"' in source
    assert 'mode == "external_general_reasoning"' in source
    assert "本会话启用 DeepSeek" in source
    assert "保存 key 本身不等于允许外发" in source
    assert "KG+RAG USED" in source
    assert "CLAIM AUDIT ·" in source
    assert "BUILD ·" in source
    assert 'mode == "clarification_required"' in source
