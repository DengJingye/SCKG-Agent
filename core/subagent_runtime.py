from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from core.models import SubagentRequest, SubagentResult, SubagentTaskType


@dataclass(frozen=True)
class SubagentBudget:
    max_depth: int = 2
    max_subagents_per_run: int = 3
    max_tool_calls_per_subagent: int = 8


READ_ONLY_TASKS: set[SubagentTaskType] = {
    "evidence_search",
    "benchmark_span_check",
    "workflow_compatibility_check",
    "report_critique",
}


class SubagentController:
    """Bounded centralized specialist contract.

    v1 keeps execution disabled by default. The Parent Agent may construct
    requests and receive blocked/read-only candidate context, but subagents
    cannot mutate evidence, rank, memory, or formal TSVs.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        budget: SubagentBudget | None = None,
    ) -> None:
        self.enabled = enabled
        self.budget = budget or SubagentBudget()
        self.spawned_count = 0

    def build_request(
        self,
        *,
        parent_trace_id: str,
        task_type: SubagentTaskType,
        query: str,
        depth: int = 1,
        candidate_context: Dict[str, Any] | None = None,
    ) -> SubagentRequest:
        return SubagentRequest(
            request_id=f"subagent_{uuid.uuid4().hex}",
            parent_trace_id=parent_trace_id,
            task_type=task_type,
            query=query,
            depth=depth,
            max_tool_calls=self.budget.max_tool_calls_per_subagent,
            candidate_context=candidate_context or {},
        )

    def spawn(self, request: SubagentRequest) -> SubagentResult:
        warnings: List[str] = []
        if request.task_type not in READ_ONLY_TASKS:
            warnings.append("subagent_task_not_allowed")
        if request.depth > self.budget.max_depth:
            warnings.append("subagent_depth_budget_exceeded")
        if self.spawned_count >= self.budget.max_subagents_per_run:
            warnings.append("subagent_count_budget_exceeded")
        if not self.enabled:
            warnings.append("subagent_execution_disabled_v1")
        if warnings:
            return self._blocked(request, warnings)
        self.spawned_count += 1
        return SubagentResult(
            request_id=request.request_id,
            parent_trace_id=request.parent_trace_id,
            task_type=request.task_type,
            status="ok",
            candidate_context={
                "query": request.query,
                "input_candidate_context": request.candidate_context,
                "subagent_output_boundary": "read_only_candidate_context",
            },
            warnings=[
                "Subagent output is candidate context only. Parent Agent must apply evidence gate.",
            ],
            depth=request.depth,
            tool_call_count=0,
        )

    def _blocked(self, request: SubagentRequest, warnings: List[str]) -> SubagentResult:
        return SubagentResult(
            request_id=request.request_id,
            parent_trace_id=request.parent_trace_id,
            task_type=request.task_type,
            status="blocked",
            candidate_context={
                "query": request.query,
                "input_candidate_context": request.candidate_context,
                "subagent_output_boundary": "blocked_or_read_only_candidate_context",
            },
            warnings=warnings
            + [
                "Blocked subagent results cannot update recommendation rank, formal TSVs, or trusted evidence.",
            ],
            depth=request.depth,
            tool_call_count=0,
        )
