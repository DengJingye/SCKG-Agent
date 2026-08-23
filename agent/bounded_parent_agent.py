from __future__ import annotations

import time
from typing import Any, Callable, Literal, Optional

from pydantic import Field

from core.action_space_models import ActionBundle
from core.deterministic_router import DeterministicRouter, RouterMode, RouterRoute
from core.execution_models import (
    DataProfile,
    ExecutionBudget,
    ExecutionGateResult,
    PlanningGateResult,
    RequirementSpec,
    StrictModel,
    WorkflowPlan,
)
from core.kg_ontology import normalize_modality, normalize_task
from core.settings import PROJECT_ROOT
from core.tool_contract_registry import ToolContractRegistry
from engine.decision_graph_query import DecisionGraphQuery
from engine.action_bundle_retriever import ActionBundleRetriever
from engine.evidence_graph_query import EvidenceGraphQuery
from engine.execution_planner import ExecutionPlanCompiler
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator


class ParentAgentRequest(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    user_id: str = Field(default="local-demo", pattern=r"^[A-Za-z0-9_.-]+$")
    query: str = Field(min_length=1)
    artifact_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    data_grant_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    execution_approval_id: Optional[str] = Field(
        default=None, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    requested_tool: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentToolCall(StrictModel):
    call_id: str
    stage: str
    capability: str
    status: Literal["completed", "blocked", "failed"]
    elapsed_ms: float = Field(ge=0.0)
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ParentAgentResult(StrictModel):
    request_id: str
    status: Literal["READY", "WAITING", "BLOCKED", "FAILED"]
    route: RouterRoute
    task: str
    modality: str
    selected_tool: Optional[str] = None
    candidate_context: list[dict[str, Any]] = Field(default_factory=list)
    action_bundles: list[ActionBundle] = Field(default_factory=list)
    data_profile: Optional[DataProfile] = None
    workflow_plan: Optional[WorkflowPlan] = None
    planning_gate: Optional[PlanningGateResult] = None
    execution_gate: Optional[ExecutionGateResult] = None
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    execution_request_count: int = 0
    final_summary: str


class BoundedParentAgent:
    """Plan-first Parent Agent that cannot bypass data or execution policy.

    The semantic parser is deterministic in this offline runtime. A future LLM
    parser may propose the same structured fields, but the graph, contract,
    authorization and router tools remain authoritative.
    """

    def __init__(
        self,
        *,
        graph_query: Optional[EvidenceGraphQuery] = None,
        decision_graph_query: Optional[DecisionGraphQuery] = None,
        contract_registry: Optional[ToolContractRegistry] = None,
        environment_registry: Optional[EnvironmentRegistry] = None,
        router: Optional[DeterministicRouter] = None,
        orchestrator: Optional[ExecutionOrchestrator] = None,
        action_bundle_retriever: Optional[ActionBundleRetriever] = None,
    ) -> None:
        self.environment_registry = environment_registry or EnvironmentRegistry()
        self.contract_registry = contract_registry or ToolContractRegistry(
            environment_registry=self.environment_registry
        )
        self.graph_query = graph_query or EvidenceGraphQuery()
        self.decision_graph_query = decision_graph_query or DecisionGraphQuery(
            PROJECT_ROOT / "data" / "decision_graph_v3"
        )
        self.router = router or DeterministicRouter()
        self.orchestrator = orchestrator
        self.compiler = ExecutionPlanCompiler(self.contract_registry)
        self.action_bundle_retriever = action_bundle_retriever or ActionBundleRetriever(
            graph_query=self.decision_graph_query,
            contract_registry=self.contract_registry,
            environment_registry=self.environment_registry,
        )

    def run(self, request: ParentAgentRequest) -> ParentAgentResult:
        calls: list[AgentToolCall] = []
        intent = self._call(
            calls,
            stage="gateway",
            capability="deterministic_requirement_parser",
            input_summary={"query_chars": len(request.query)},
            function=lambda: self._parse_intent(request.query),
            summarize=lambda value: value,
        )
        task = intent["task"]
        modality = intent["modality"]
        matches = self._call(
            calls,
            stage="knowledge",
            capability="evidence_graph_query.rank_tools",
            input_summary={"task": task, "modality": modality},
            function=lambda: self.graph_query.rank_tools(
                task=task, modality=modality, limit=15
            ),
            summarize=lambda value: {
                "candidate_count": len(value),
                "verified_candidates": [
                    item.tool_name
                    for item in value
                    if item.candidate_basis == "execution_verified"
                ],
                "hypothesis_candidates": sum(
                    item.candidate_basis == "graph_hypothesis" for item in value
                ),
                "catalog_candidates": sum(
                    item.candidate_basis == "catalog_metadata" for item in value
                ),
            },
        )
        action_context = self._call(
            calls,
            stage="knowledge",
            capability="action_bundle_retriever.retrieve",
            input_summary={"task": task, "modality": modality, "data_profile": False},
            function=lambda: self.action_bundle_retriever.retrieve(
                task=task,
                modality=modality,
                requested_tool=request.requested_tool,
            ),
            summarize=lambda value: {
                "action_bundle_count": len(value.bundles),
                "decision_ready": [
                    item.tool_name
                    for item in value.bundles
                    if item.readiness == "decision_ready"
                ],
                "contract_verified": [
                    item.tool_name
                    for item in value.bundles
                    if item.execution_contract_qualified
                ],
                "execution_request_count": value.execution_request_count,
            },
        )
        bundle_by_tool = {
            item.tool_name.casefold(): item for item in action_context.bundles
        }
        candidate_context = []
        for item in matches:
            row = item.model_dump(mode="json")
            bundle = bundle_by_tool.get(item.tool_name.casefold())
            row.update(
                {
                    "decision_readiness": bundle.readiness if bundle else "catalog_seed",
                    "decision_match_basis": "contract" if bundle else "none",
                    "action_id": bundle.action_id if bundle else None,
                    "action_bundle_id": bundle.bundle_id if bundle else None,
                    "data_compatibility": (
                        bundle.data_compatibility if bundle else "unknown"
                    ),
                    "decision_blockers": bundle.planning_blockers
                    if bundle
                    else ["verified_task_contract_missing"],
                }
            )
            candidate_context.append(row)
        allowed_tools = {
            item.tool_name.casefold()
            for item in action_context.bundles
            if item.planning_allowed
            and item.readiness in {"decision_ready", "contract_verified"}
        }
        selected = self._select_candidate(
            matches,
            request.requested_tool,
            allowed_tools=allowed_tools,
            action_bundles=action_context.bundles,
        )
        if selected is None:
            planning_only = [
                bundle for bundle in action_context.bundles if bundle.planning_allowed
            ]
            if planning_only:
                route = RouterRoute.CONTRACT_REVIEW
                reasons = sorted(
                    {
                        "planning_only_action_bundle_cannot_create_executable_plan",
                        *(
                            reason
                            for bundle in planning_only
                            for reason in bundle.execution_gate_blockers
                        ),
                    }
                )
                next_actions = [
                    "Use the planning-only ActionBundle for source-grounded requirements review.",
                    "Complete wrapper, environment, engineering qualification, and scientific pilot before execution.",
                ]
                final_summary = (
                    "Source-bound planning contracts are available, but no tool in this "
                    "task family has execution qualification. Planning context is returned; "
                    "no executable WorkflowPlan or ExecutionRequest was created."
                )
            else:
                route = RouterRoute.EVIDENCE_RECOVERY
                reasons = [
                    "reviewed_tool_contract_missing_for_requested_task",
                    "retrieval_only_graph_candidate_cannot_create_executable_plan",
                ]
                next_actions = [
                    "Recover source-bound evidence for a core candidate.",
                    "Review a versioned ToolContract before planning execution.",
                ]
                final_summary = (
                    "GraphRAG found exploratory candidates, but none has a reviewed "
                    "execution contract for this task. No executable plan was created."
                )
            calls.append(
                AgentToolCall(
                    call_id=f"{request.request_id}:contract",
                    stage="contract",
                    capability="tool_contract_registry",
                    status="blocked",
                    elapsed_ms=0.0,
                    input_summary={"requested_tool": request.requested_tool or "auto"},
                    output_summary={
                        "contract_found": bool(planning_only),
                        "planning_only_tools": [
                            bundle.tool_name for bundle in planning_only
                        ],
                        "execution_qualified": False,
                    },
                    warnings=reasons,
                )
            )
            return ParentAgentResult(
                request_id=request.request_id,
                status="BLOCKED",
                route=route,
                task=task,
                modality=modality,
                candidate_context=candidate_context,
                action_bundles=action_context.bundles,
                tool_calls=calls,
                blockers=reasons,
                next_actions=next_actions,
                final_summary=final_summary,
            )

        contract = self._call(
            calls,
            stage="contract",
            capability="tool_contract_registry.load",
            input_summary={"tool_name": selected.tool_name},
            function=lambda: self._contract_for_tool(selected.tool_name),
            summarize=lambda value: {
                "contract_id": value.contract_id,
                "contract_version": value.contract_version,
                "environment_id": value.environment_id,
            },
        )
        environment = self._call(
            calls,
            stage="contract",
            capability="environment_registry.get",
            input_summary={"environment_id": contract.environment_id},
            function=lambda: self.environment_registry.get(contract.environment_id),
            summarize=lambda value: {
                "environment_id": value.environment_id,
                "qualification_status": value.qualification_status,
            },
        )
        execution_gate = self.contract_registry.execution_gate(contract)

        if request.artifact_id is not None:
            if self.orchestrator is None:
                return self._failed_result(
                    request=request,
                    task=task,
                    modality=modality,
                    selected_tool=selected.tool_name,
                    candidate_context=candidate_context,
                    action_bundles=action_context.bundles,
                    calls=calls,
                    execution_gate=execution_gate,
                    reason="user_data_orchestrator_not_configured",
                )
            preparation = self._call(
                calls,
                stage="profile_plan_authorize",
                capability="execution_orchestrator.prepare_user_execution",
                input_summary={
                    "artifact_id": request.artifact_id,
                    "data_grant_supplied": bool(request.data_grant_id),
                    "execution_approval_supplied": bool(request.execution_approval_id),
                },
                function=lambda: self.orchestrator.prepare_user_execution(
                    user_id=request.user_id,
                    artifact_id=request.artifact_id or "",
                    data_grant_id=request.data_grant_id,
                    execution_approval_id=request.execution_approval_id,
                    request_id=request.request_id,
                    query=request.query,
                    parameters=request.parameters,
                    tool_name=contract.tool_name,
                    tool_version=contract.tool_version,
                ),
                summarize=lambda value: {
                    "route": value.route,
                    "profile_created": value.profile is not None,
                    "plan_created": value.plan is not None,
                    "execution_request_created": value.execution_request_created,
                },
            )
            planning_gate = (
                self.contract_registry.planning_gate(contract, data_profile=preparation.profile)
                if preparation.profile is not None
                else None
            )
            data_action_context = action_context
            if preparation.profile is not None:
                data_action_context = self._call(
                    calls,
                    stage="knowledge",
                    capability="action_bundle_retriever.retrieve_data_aware",
                    input_summary={
                        "task": task,
                        "modality": modality,
                        "data_profile": True,
                        "tool_name": selected.tool_name,
                    },
                    function=lambda: self.action_bundle_retriever.retrieve(
                        task=task,
                        modality=modality,
                        data_profile=preparation.profile,
                        requested_tool=selected.tool_name,
                    ),
                    summarize=lambda value: {
                        "action_bundle_count": len(value.bundles),
                        "compatible": [
                            item.tool_name
                            for item in value.bundles
                            if item.data_compatibility == "compatible"
                        ],
                        "blocked_candidates": value.blocked_candidates,
                        "execution_request_count": value.execution_request_count,
                    },
                )
            status = self._status_for_route(preparation.route)
            return ParentAgentResult(
                request_id=request.request_id,
                status=status,
                route=preparation.route,
                task=task,
                modality=modality,
                selected_tool=selected.tool_name,
                candidate_context=candidate_context,
                action_bundles=data_action_context.bundles,
                data_profile=preparation.profile,
                workflow_plan=preparation.plan,
                planning_gate=planning_gate,
                execution_gate=execution_gate,
                tool_calls=calls,
                blockers=list(preparation.reasons),
                next_actions=self._next_actions(preparation.route),
                execution_request_count=0,
                final_summary=self._summary_for_route(preparation.route),
            )

        requirement = RequirementSpec(
            request_id=request.request_id,
            query=request.query,
            task=(
                "batch_integration"
                if intent["task_id"] in {"batch_correction", "batch_integration"}
                else "doublet_detection"
            ),
            data_access_authorized=False,
            execution_authorized=False,
        )
        planning_gate = self.contract_registry.planning_gate(contract)
        plan = self._call(
            calls,
            stage="planning",
            capability="execution_plan_compiler.compile",
            input_summary={
                "tool_name": contract.tool_name,
                "data_profile_available": False,
            },
            function=lambda: self.compiler.compile(
                requirement=requirement,
                data_profile=None,
                tool_contract=contract,
                environment=environment,
                execution_budget=ExecutionBudget(),
            ),
            summarize=lambda value: {
                "plan_id": value.plan_id,
                "plan_status": value.plan_status,
                "step_count": len(value.steps),
                "execution_eligible": value.execution_eligible,
            },
        )
        decision = self.router.route(
            mode=RouterMode.PLAN,
            requirement=requirement,
            tool_contract=contract,
            planning_gate=planning_gate,
            execution_gate=execution_gate,
            plan=plan,
        )
        calls.append(
            AgentToolCall(
                call_id=f"{request.request_id}:router",
                stage="policy",
                capability="deterministic_router.route",
                status="completed" if decision.route == RouterRoute.PLAN_ONLY else "blocked",
                elapsed_ms=0.0,
                output_summary={
                    "route": decision.route,
                    "execution_allowed": decision.execution_allowed,
                },
                warnings=decision.reasons,
            )
        )
        return ParentAgentResult(
            request_id=request.request_id,
            status=self._status_for_route(decision.route),
            route=decision.route,
            task=task,
            modality=modality,
            selected_tool=selected.tool_name,
            candidate_context=candidate_context,
            action_bundles=action_context.bundles,
            workflow_plan=plan,
            planning_gate=planning_gate,
            execution_gate=execution_gate,
            tool_calls=calls,
            blockers=decision.reasons,
            next_actions=[
                "Register an AnnData artifact and grant profile/plan access.",
                "Re-run the same Parent Agent request to build a data-aware plan.",
            ],
            execution_request_count=0,
            final_summary=(
                f"A generic dry-run {contract.tool_name} plan was compiled from a governed "
                "GraphRAG path and versioned contract. Data profiling and execution were not started."
            ),
        )

    @staticmethod
    def _parse_intent(query: str) -> dict[str, str]:
        task = normalize_task(query)
        modality = normalize_modality(query)
        if modality.matched_rule == "modality_fallback":
            modality = normalize_modality("scRNA-seq")
        return {
            "task": task.label,
            "task_id": task.canonical_id,
            "task_rule": task.matched_rule,
            "modality": modality.label,
            "modality_id": modality.canonical_id,
            "modality_rule": modality.matched_rule,
        }

    @staticmethod
    def _select_candidate(
        matches,
        requested_tool: Optional[str],
        *,
        allowed_tools: set[str],
        action_bundles: list[ActionBundle],
    ):
        if requested_tool:
            evidence_match = next(
                (
                    item
                    for item in matches
                    if item.tool_name.casefold() == requested_tool.casefold()
                    and item.tool_name.casefold() in allowed_tools
                ),
                None,
            )
            if evidence_match is not None:
                return evidence_match
            return next(
                (
                    item
                    for item in action_bundles
                    if item.tool_name.casefold() == requested_tool.casefold()
                    and item.tool_name.casefold() in allowed_tools
                ),
                None,
            )
        evidence_match = next(
            (
                item
                for item in matches
                if item.candidate_basis == "execution_verified"
                and item.tool_name.casefold() in allowed_tools
            ),
            None,
        )
        if evidence_match is not None:
            return evidence_match
        return next(
            (
                item
                for item in action_bundles
                if item.tool_name.casefold() in allowed_tools
            ),
            None,
        )

    def _contract_for_tool(self, tool_name: str):
        matches = [
            contract
            for contract in self.contract_registry.load_all()
            if contract.tool_name.casefold() == tool_name.casefold()
        ]
        if not matches:
            raise KeyError(f"reviewed contract not found for tool: {tool_name}")
        return sorted(matches, key=lambda item: item.tool_version, reverse=True)[0]

    @staticmethod
    def _call(
        calls: list[AgentToolCall],
        *,
        stage: str,
        capability: str,
        input_summary: dict[str, Any],
        function: Callable[[], Any],
        summarize: Callable[[Any], dict[str, Any]],
    ) -> Any:
        started = time.perf_counter()
        value = function()
        calls.append(
            AgentToolCall(
                call_id=f"call-{len(calls) + 1:02d}",
                stage=stage,
                capability=capability,
                status="completed",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                input_summary=input_summary,
                output_summary=summarize(value),
            )
        )
        return value

    @staticmethod
    def _status_for_route(route: RouterRoute) -> Literal[
        "READY", "WAITING", "BLOCKED", "FAILED"
    ]:
        if route == RouterRoute.PLAN_ONLY:
            return "READY"
        if route in {
            RouterRoute.WAITING_DATA_AUTHORIZATION,
            RouterRoute.WAITING_EXECUTION_APPROVAL,
            RouterRoute.WAITING_USER_INPUT,
        }:
            return "WAITING"
        return "BLOCKED"

    @staticmethod
    def _next_actions(route: RouterRoute) -> list[str]:
        if route == RouterRoute.WAITING_DATA_AUTHORIZATION:
            return ["Create a scoped data access grant before profiling."]
        if route == RouterRoute.WAITING_EXECUTION_APPROVAL:
            return ["Review the unchanged dry-run plan and create an exact approval."]
        return ["Resolve the listed deterministic blockers; Parent Agent cannot override them."]

    @staticmethod
    def _summary_for_route(route: RouterRoute) -> str:
        if route == RouterRoute.WAITING_DATA_AUTHORIZATION:
            return "The registered artifact was not read because no valid data access grant exists."
        if route == RouterRoute.WAITING_EXECUTION_APPROVAL:
            return "Data profiling and dry-run planning completed; execution is waiting for exact approval."
        return "The deterministic policy gate blocked the request before execution."

    @staticmethod
    def _failed_result(
        *,
        request: ParentAgentRequest,
        task: str,
        modality: str,
        selected_tool: str,
        candidate_context: list[dict[str, Any]],
        action_bundles: list[ActionBundle],
        calls: list[AgentToolCall],
        execution_gate: ExecutionGateResult,
        reason: str,
    ) -> ParentAgentResult:
        return ParentAgentResult(
            request_id=request.request_id,
            status="FAILED",
            route=RouterRoute.BLOCKED,
            task=task,
            modality=modality,
            selected_tool=selected_tool,
            candidate_context=candidate_context,
            action_bundles=action_bundles,
            execution_gate=execution_gate,
            tool_calls=calls,
            blockers=[reason],
            next_actions=["Configure the authorization-aware orchestrator."],
            execution_request_count=0,
            final_summary="Parent Agent stopped because the required backend service was unavailable.",
        )
