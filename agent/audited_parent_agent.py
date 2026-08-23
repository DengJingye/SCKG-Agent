from __future__ import annotations

import hashlib
from typing import Iterable, Optional

from agent.bounded_parent_agent import (
    BoundedParentAgent,
    ParentAgentRequest,
    ParentAgentResult,
)
from core.agent_run_models import AGENT_STAGE_ORDER, AgentRunStage, UnifiedAgentRunTrace


class AuditedParentAgent:
    """Build one ordered trace over the existing governed Agent services.

    This class does not implement another executor. It records the Parent
    planning path and accepts only structured summaries emitted by existing
    authorization, execution, validation, decision and packaging services.
    """

    def __init__(self, parent: Optional[BoundedParentAgent] = None) -> None:
        self.parent = parent or BoundedParentAgent()

    def plan(
        self,
        request: ParentAgentRequest,
        *,
        case_id: str,
    ) -> tuple[ParentAgentResult, UnifiedAgentRunTrace]:
        result = self.parent.run(request)
        trace = self.finalize(
            parent_result=result,
            case_id=case_id,
            backend_stages=[],
            final_status=("BLOCKED" if result.status == "BLOCKED" else "WAITING"),
            execution_request_count=result.execution_request_count,
        )
        return result, trace

    def finalize(
        self,
        *,
        parent_result: ParentAgentResult,
        case_id: str,
        backend_stages: Iterable[AgentRunStage],
        final_status: str,
        execution_request_count: int,
        unauthorized_execution_request_count: int = 0,
        limitations: Optional[list[str]] = None,
    ) -> UnifiedAgentRunTrace:
        stage_map = {stage.stage: stage for stage in self._parent_stages(parent_result)}
        for stage in backend_stages:
            stage_map[stage.stage] = stage
        stage_map["audit"] = AgentRunStage(
            stage="audit",
            authority="safety_plane",
            status=("blocked" if final_status == "BLOCKED" else "completed"),
            summary={
                "execution_request_count": execution_request_count,
                "unauthorized_execution_request_count": unauthorized_execution_request_count,
                "parent_route": str(parent_result.route),
            },
        )
        ordered = [stage_map[name] for name in AGENT_STAGE_ORDER if name in stage_map]
        trace_id = "agent-trace:" + hashlib.sha256(
            f"{case_id}:{parent_result.request_id}".encode("utf-8")
        ).hexdigest()[:20]
        return UnifiedAgentRunTrace(
            trace_id=trace_id,
            case_id=case_id,
            request_id=parent_result.request_id,
            task=parent_result.task,
            status=final_status,
            stages=ordered,
            execution_request_count=execution_request_count,
            unauthorized_execution_request_count=unauthorized_execution_request_count,
            limitations=limitations or [
                "LLM or semantic parsing may propose structure, but deterministic gates retain veto authority.",
                "Controlled local execution is application-level isolation, not an OS sandbox.",
            ],
        )

    @staticmethod
    def _parent_stages(result: ParentAgentResult) -> list[AgentRunStage]:
        calls_by_stage: dict[str, list] = {}
        for call in result.tool_calls:
            calls_by_stage.setdefault(call.stage, []).append(call)
        gateway_calls = calls_by_stage.get("gateway", [])
        knowledge_calls = calls_by_stage.get("knowledge", [])
        plan_calls = calls_by_stage.get("planning", [])
        policy_calls = calls_by_stage.get("policy", [])
        stages = [
            AgentRunStage(
                stage="trigger",
                authority="deterministic_gateway",
                status="completed",
                summary={"request_id": result.request_id},
            ),
            _from_calls(
                "gateway",
                "deterministic_gateway",
                gateway_calls,
                fallback={"task": result.task, "modality": result.modality},
            ),
            _from_calls(
                "kg_rag_action_retrieval",
                "knowledge_plane",
                knowledge_calls,
                fallback={
                    "candidate_count": len(result.candidate_context),
                    "action_bundle_count": len(result.action_bundles),
                },
            ),
        ]
        if result.data_profile is not None:
            stages.append(
                AgentRunStage(
                    stage="data_profile",
                    authority="safety_plane",
                    status="blocked" if result.data_profile.is_blocked else "completed",
                    summary={
                        "profile_id": result.data_profile.profile_id,
                        "selected_count_source": result.data_profile.selected_count_source,
                        "blocking_errors": result.data_profile.blocking_errors,
                    },
                )
            )
        if result.workflow_plan is not None:
            stages.append(
                _from_calls(
                    "workflow_plan",
                    "safety_plane",
                    plan_calls,
                    fallback={
                        "plan_id": result.workflow_plan.plan_id,
                        "plan_status": result.workflow_plan.plan_status,
                        "execution_eligible": result.workflow_plan.execution_eligible,
                    },
                )
            )
        stages.append(
            _from_calls(
                "deterministic_router",
                "safety_plane",
                policy_calls,
                fallback={"route": str(result.route), "blockers": result.blockers},
                forced_status=("blocked" if result.status == "BLOCKED" else "completed"),
            )
        )
        approval_status = (
            "blocked"
            if result.status == "BLOCKED"
            else "waiting"
            if result.status in {"WAITING", "READY"}
            else "failed"
        )
        stages.append(
            AgentRunStage(
                stage="approval_boundary",
                authority="safety_plane",
                status=approval_status,
                summary={
                    "route": str(result.route),
                    "execution_request_count": result.execution_request_count,
                },
                warnings=result.blockers,
            )
        )
        return stages


def _from_calls(
    stage: str,
    authority: str,
    calls: list,
    *,
    fallback: dict,
    forced_status: Optional[str] = None,
) -> AgentRunStage:
    status = forced_status or (
        "failed"
        if any(call.status == "failed" for call in calls)
        else "blocked"
        if any(call.status == "blocked" for call in calls)
        else "completed"
    )
    return AgentRunStage(
        stage=stage,
        authority=authority,
        status=status,
        elapsed_ms=round(sum(call.elapsed_ms for call in calls), 3),
        summary={
            **fallback,
            "capabilities": [call.capability for call in calls],
            "outputs": [call.output_summary for call in calls],
        },
        warnings=sorted({warning for call in calls for warning in call.warnings}),
    )
