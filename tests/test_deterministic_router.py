from __future__ import annotations

import pytest

from core.deterministic_router import (
    DeterministicRouter,
    RouterMode,
    RouterRoute,
)
from core.execution_models import ExecutionBudget, ExecutionGateResult, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


@pytest.fixture()
def router_context(tmp_path):
    paths = write_phase1_fixtures(tmp_path)
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scrublet", "0.2.3")
    environment = environments.get("scRNAseq")
    profiler = AnnDataProfiler()
    raw_profile = profiler.profile(paths["raw_x"])
    scaled_profile = profiler.profile(paths["scaled"])
    requirement = RequirementSpec(
        request_id="request_router",
        query="Plan doublet detection",
        input_path=str(paths["raw_x"]),
        input_object_type="AnnData",
        data_access_authorized=True,
    )
    planning_gate = contracts.planning_gate(contract, data_profile=raw_profile)
    execution_gate = contracts.execution_gate(contract)
    plan = ExecutionPlanCompiler(contracts).compile(
        requirement=requirement,
        data_profile=raw_profile,
        tool_contract=contract,
        environment=environment,
        execution_budget=ExecutionBudget(),
    )
    return {
        "paths": paths,
        "contracts": contracts,
        "contract": contract,
        "raw_profile": raw_profile,
        "scaled_profile": scaled_profile,
        "requirement": requirement,
        "planning_gate": planning_gate,
        "execution_gate": execution_gate,
        "plan": plan,
    }


def test_profile_only_route(router_context):
    decision = DeterministicRouter().route(
        mode=RouterMode.PROFILE,
        requirement=router_context["requirement"],
        data_profile=router_context["raw_profile"],
    )
    assert decision.route == RouterRoute.PROFILE_ONLY


def test_no_data_plan_routes_to_plan_only(router_context):
    requirement = RequirementSpec(
        request_id="request_generic",
        query="Give me a generic dry-run plan",
    )
    planning = router_context["contracts"].planning_gate(router_context["contract"])
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=requirement,
        tool_contract=router_context["contract"],
        planning_gate=planning,
    )
    assert decision.route == RouterRoute.PLAN_ONLY


def test_unauthorized_data_routes_to_waiting_authorization(router_context):
    requirement = router_context["requirement"].model_copy(
        update={"data_access_authorized": False}
    )
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=requirement,
        tool_contract=router_context["contract"],
        planning_gate=router_context["planning_gate"],
    )
    assert decision.route == RouterRoute.WAITING_DATA_AUTHORIZATION


def test_unresolved_count_source_waits_for_user_input(router_context):
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=router_context["requirement"],
        data_profile=router_context["scaled_profile"],
        tool_contract=router_context["contract"],
        planning_gate=router_context["planning_gate"],
    )
    assert decision.route == RouterRoute.WAITING_USER_INPUT


def test_missing_contract_routes_to_evidence_recovery(router_context):
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=router_context["requirement"],
        data_profile=router_context["raw_profile"],
        tool_contract=None,
    )
    assert decision.route == RouterRoute.EVIDENCE_RECOVERY


def test_failed_planning_gate_routes_to_contract_review(router_context):
    failed_gate = router_context["planning_gate"].model_copy(
        update={"allowed": False, "reasons": ["source_review_status_insufficient:missing"]}
    )
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=router_context["requirement"],
        data_profile=router_context["raw_profile"],
        tool_contract=router_context["contract"],
        planning_gate=failed_gate,
    )
    assert decision.route == RouterRoute.CONTRACT_REVIEW


def test_execution_gate_failure_keeps_dry_run(router_context):
    decision = DeterministicRouter().route(
        mode=RouterMode.EXECUTION,
        requirement=router_context["requirement"],
        data_profile=router_context["raw_profile"],
        tool_contract=router_context["contract"],
        planning_gate=router_context["planning_gate"],
        execution_gate=router_context["execution_gate"],
        plan=router_context["plan"],
    )
    assert decision.route == RouterRoute.PLAN_ONLY
    assert decision.plan_status == "dry_run"
    assert decision.execution_allowed is False


def test_parent_agent_cannot_override_router(router_context):
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=router_context["requirement"],
        data_profile=router_context["raw_profile"],
        tool_contract=router_context["contract"],
        planning_gate=router_context["planning_gate"],
        plan=router_context["plan"],
        parent_route_override=RouterRoute.BLOCKED,
    )
    assert decision.route == RouterRoute.PLAN_ONLY
    assert decision.parent_override_ignored is True
    assert any(reason.startswith("parent_route_override_ignored") for reason in decision.reasons)


def test_execution_gate_pass_waits_for_plan_specific_approval(router_context):
    hypothetical_gate = ExecutionGateResult(
        allowed=True,
        contract_id=router_context["contract"].contract_id,
        reasons=[],
    )
    decision = DeterministicRouter().route(
        mode=RouterMode.EXECUTION,
        requirement=router_context["requirement"],
        data_profile=router_context["raw_profile"],
        tool_contract=router_context["contract"],
        planning_gate=router_context["planning_gate"],
        execution_gate=hypothetical_gate,
        plan=router_context["plan"],
    )
    assert decision.route == RouterRoute.WAITING_EXECUTION_APPROVAL
    assert decision.execution_allowed is False


def test_corrupt_profile_routes_to_blocked(router_context):
    corrupt_profile = AnnDataProfiler().profile(router_context["paths"]["corrupt"])
    decision = DeterministicRouter().route(
        mode=RouterMode.PLAN,
        requirement=router_context["requirement"],
        data_profile=corrupt_profile,
        tool_contract=router_context["contract"],
        planning_gate=router_context["planning_gate"],
    )
    assert decision.route == RouterRoute.BLOCKED
