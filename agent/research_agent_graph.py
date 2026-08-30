from __future__ import annotations

from typing import Any, Callable, TypedDict

from core.research_agent_models import AgentMode, ResearchAgentResponse
from core.trace_context import TraceContext

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # The local control plane must remain useful without LangGraph.
    END = "__end__"
    StateGraph = None


class ResearchGraphPayload(TypedDict, total=False):
    request: Any
    trace_context: TraceContext
    trace_correlation_degraded: bool
    project_memory: dict[str, Any]
    uploaded_context: dict[str, Any]
    conversation_context: list[dict[str, Any]]
    user_runtime_config: dict[str, Any]
    turn: dict[str, Any]
    retrieval: dict[str, Any]
    parent: dict[str, Any]
    legacy_result: dict[str, Any]
    response: ResearchAgentResponse
    visited_nodes: list[str]


class ResearchAgentGraph:
    """One high-level graph over the shared ResearchChatService node functions.

    LangGraph is the preferred scheduler. The deterministic scheduler invokes the
    exact same node callables when the optional package is absent, so dependency
    availability cannot change product behavior or evidence authority.
    """

    def __init__(self, service: Any) -> None:
        self.service = service
        self.runtime = "langgraph" if StateGraph is not None else "deterministic_graph"
        self._compiled = self._compile_langgraph() if StateGraph is not None else None

    def invoke(self, payload: ResearchGraphPayload) -> ResearchGraphPayload:
        initial = {**payload, "visited_nodes": []}
        if self._compiled is not None:
            return self._compiled.invoke(initial)
        return self._invoke_deterministically(initial)

    def _compile_langgraph(self) -> Any:
        graph = StateGraph(ResearchGraphPayload)
        graph.add_node("gateway", self._node("gateway", self.service._graph_gateway))
        graph.add_node(
            "requirement_parse",
            self._node("requirement_parse", self.service._graph_requirement_parse),
        )
        graph.add_node(
            "action_retrieval",
            self._node("action_retrieval", self.service._graph_action_retrieval),
        )
        graph.add_node(
            "plan_compile",
            self._node("plan_compile", self.service._graph_plan_compile),
        )
        graph.add_node(
            "deterministic_route",
            self._node("deterministic_route", self.service._graph_deterministic_route),
        )
        graph.add_node(
            "answer_or_handoff",
            self._node("answer_or_handoff", self.service._graph_answer_or_handoff),
        )
        graph.set_entry_point("gateway")
        graph.add_edge("gateway", "requirement_parse")
        graph.add_edge("requirement_parse", "action_retrieval")
        graph.add_conditional_edges(
            "action_retrieval",
            self._route_after_retrieval,
            {"answer": "answer_or_handoff", "plan": "plan_compile"},
        )
        graph.add_edge("plan_compile", "deterministic_route")
        graph.add_edge("deterministic_route", "answer_or_handoff")
        graph.add_edge("answer_or_handoff", END)
        return graph.compile()

    def _invoke_deterministically(
        self,
        payload: ResearchGraphPayload,
    ) -> ResearchGraphPayload:
        state = payload
        for name, function in (
            ("gateway", self.service._graph_gateway),
            ("requirement_parse", self.service._graph_requirement_parse),
            ("action_retrieval", self.service._graph_action_retrieval),
        ):
            state = {**state, **self._node(name, function)(state)}
        if self._route_after_retrieval(state) == "plan":
            for name, function in (
                ("plan_compile", self.service._graph_plan_compile),
                ("deterministic_route", self.service._graph_deterministic_route),
            ):
                state = {**state, **self._node(name, function)(state)}
        return {
            **state,
            **self._node(
                "answer_or_handoff",
                self.service._graph_answer_or_handoff,
            )(state),
        }

    @staticmethod
    def _route_after_retrieval(payload: ResearchGraphPayload) -> str:
        mode = payload.get("turn", {}).get("mode", AgentMode.ASK.value)
        return "answer" if mode == AgentMode.ASK.value else "plan"

    @staticmethod
    def _node(
        name: str,
        function: Callable[[ResearchGraphPayload], dict[str, Any]],
    ) -> Callable[[ResearchGraphPayload], dict[str, Any]]:
        def invoke(payload: ResearchGraphPayload) -> dict[str, Any]:
            update = function(payload)
            return {
                **update,
                "visited_nodes": [*payload.get("visited_nodes", []), name],
            }

        return invoke
