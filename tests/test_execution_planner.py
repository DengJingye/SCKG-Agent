from __future__ import annotations

import ast
import inspect

import pytest

import engine.execution_planner as planner_module
from core.execution_models import ExecutionBudget, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler, PHASE2_NODE_IDS
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase1_fixtures


@pytest.fixture()
def planning_context(tmp_path):
    paths = write_phase1_fixtures(tmp_path)
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scrublet", "0.2.3")
    environment = environments.get("scRNAseq")
    compiler = ExecutionPlanCompiler(contracts)
    profiler = AnnDataProfiler()
    return paths, contracts, contract, environment, compiler, profiler


def _requirement(path=None, *, data_access=True):
    return RequirementSpec(
        request_id=f"request_{path.name if path else 'generic'}",
        query="Create a dry-run doublet detection plan",
        input_path=str(path) if path else None,
        input_object_type="AnnData" if path else "unknown",
        data_access_authorized=data_access if path else False,
        execution_authorized=False,
    )


def _compile(compiler, contract, environment, requirement, profile):
    return compiler.compile(
        requirement=requirement,
        data_profile=profile,
        tool_contract=contract,
        environment=environment,
        execution_budget=ExecutionBudget(),
    )


def test_generic_plan_is_dry_run_without_data(planning_context):
    _, _, contract, environment, compiler, _ = planning_context
    plan = _compile(compiler, contract, environment, _requirement(), None)

    assert plan.plan_status == "dry_run"
    assert plan.data_awareness == "generic"
    assert plan.profile_id == "profile_not_available"
    assert [node.node_id for node in plan.steps] == PHASE2_NODE_IDS
    assert "generic_plan_without_data_profile" in plan.planning_warnings
    assert plan.execution_eligible is False


def test_raw_x_builds_data_aware_dry_run_plan(planning_context):
    paths, _, contract, environment, compiler, profiler = planning_context
    requirement = _requirement(paths["raw_x"])
    profile = profiler.profile(paths["raw_x"])
    plan = _compile(compiler, contract, environment, requirement, profile)

    assert plan.plan_status == "dry_run"
    assert plan.data_awareness == "data_aware"
    assert plan.blocking_conditions == []
    assert plan.execution_blockers
    assert plan.execution_eligible is False
    assert plan.approval_required is True
    count_node = next(node for node in plan.steps if node.node_id == "select_count_source")
    assert count_node.parameters["selected_count_source"] == "X"
    assert count_node.tool_contract_id == "scrublet:0.2.3"


def test_counts_layer_builds_dry_run_plan(planning_context):
    paths, _, contract, environment, compiler, profiler = planning_context
    requirement = _requirement(paths["counts_layer"])
    profile = profiler.profile(paths["counts_layer"])
    plan = _compile(compiler, contract, environment, requirement, profile)

    assert plan.plan_status == "dry_run"
    count_node = next(node for node in plan.steps if node.node_id == "select_count_source")
    assert count_node.parameters["selected_count_source"] == "layers/counts"


def test_scaled_unresolved_profile_blocks_plan(planning_context):
    paths, _, contract, environment, compiler, profiler = planning_context
    requirement = _requirement(paths["scaled"])
    profile = profiler.profile(paths["scaled"])
    plan = _compile(compiler, contract, environment, requirement, profile)

    assert plan.plan_status == "blocked"
    assert plan.execution_eligible is False
    assert any("count_source_unresolved" in reason for reason in plan.blocking_conditions)


def test_planning_gate_failure_blocks_plan(planning_context):
    _, _, contract, environment, compiler, _ = planning_context
    unreviewed = contract.model_copy(update={"source_review_status": "missing"})
    plan = _compile(compiler, unreviewed, environment, _requirement(), None)

    assert plan.plan_status == "blocked"
    assert "source_review_status_insufficient:missing" in plan.blocking_conditions


def test_execution_gate_failure_does_not_block_valid_dry_run(planning_context):
    paths, _, contract, environment, compiler, profiler = planning_context
    requirement = _requirement(paths["raw_x"])
    plan = _compile(
        compiler,
        contract,
        environment,
        requirement,
        profiler.profile(paths["raw_x"]),
    )

    assert plan.plan_status == "dry_run"
    assert "contract_execution_disabled" in plan.execution_blockers
    assert "execution_gate_failed_plan_remains_dry_run" in plan.planning_warnings


def test_every_node_is_auditable_and_planning_only(planning_context):
    paths, _, contract, environment, compiler, profiler = planning_context
    requirement = _requirement(paths["raw_x"])
    plan = _compile(
        compiler,
        contract,
        environment,
        requirement,
        profiler.profile(paths["raw_x"]),
    )

    for node in plan.steps:
        assert node.node_id
        assert node.operation
        assert node.tool_name
        assert node.input_artifacts
        assert node.output_artifacts
        assert node.parameters
        assert node.parameter_provenance
        assert node.preconditions
        assert node.resource_budget.max_runtime_seconds > 0
        assert node.failure_policy
        assert node.tool_contract_id == contract.contract_id
    planner_tree = ast.parse(inspect.getsource(planner_module))
    assert not any(
        isinstance(item, (ast.Import, ast.ImportFrom))
        and any(alias.name == "subprocess" for alias in item.names)
        for item in ast.walk(planner_tree)
    )
    assert not any(
        isinstance(item, ast.Name) and item.id == "ExecutionRequest"
        for item in ast.walk(planner_tree)
    )
