from __future__ import annotations

import ast
import inspect

import pytest

import engine.execution_planner as planner_module
from core.execution_models import ExecutionBudget, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import BATCH_INTEGRATION_NODE_IDS, ExecutionPlanCompiler
from engine.task_data_gate import TaskDataGate
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase5_batch_fixtures


@pytest.fixture()
def batch_context(tmp_path):
    paths = write_phase5_batch_fixtures(tmp_path)
    environments = EnvironmentRegistry()
    registry = ToolContractRegistry(environment_registry=environments)
    profiler = AnnDataProfiler()
    compiler = ExecutionPlanCompiler(registry)
    return paths, environments, registry, profiler, compiler


def _requirement(path, *, batch_key="batch", label_key="cell_type"):
    return RequirementSpec(
        request_id=f"batch_{path.stem}",
        query="Build a batch integration dry-run plan",
        task="batch_integration",
        input_path=str(path),
        input_object_type="AnnData",
        batch_key=batch_key,
        label_key=label_key,
        output_goal="integrated embedding and evaluation plan",
        data_access_authorized=True,
    )


@pytest.mark.parametrize("tool_name,version", [("Harmony", "2.0.0"), ("Scanorama", "1.7.4")])
def test_scientific_pilot_contracts_pass_planning_and_contract_execution_gate(
    batch_context,
    tool_name,
    version,
):
    _, _, registry, _, _ = batch_context
    contract = registry.load(tool_name, version)

    assert registry.planning_gate(contract).allowed is True
    execution = registry.execution_gate(contract)
    assert execution.allowed is True
    assert execution.reasons == []
    assert contract.enabled_for_execution is True


def test_valid_existing_pca_passes_task_gate(batch_context):
    paths, _, _, profiler, _ = batch_context
    requirement = _requirement(paths["valid_pca"])
    profile = profiler.profile(
        paths["valid_pca"],
        batch_key=requirement.batch_key,
        label_key=requirement.label_key,
    )
    eligibility = TaskDataGate().evaluate(requirement, profile)

    assert profile.batch_count == 3
    assert profile.batch_min_cells == 20
    assert profile.pca_n_components == 10
    assert profile.pca_finite is True
    assert eligibility.allowed is True
    assert eligibility.selected_representation == "obsm/X_pca"
    assert eligibility.biology_label_mode == "available"
    assert eligibility.checks["count_source_required"] is False


def test_log_normalized_x_without_counts_is_valid_when_pca_is_planned(batch_context):
    paths, _, _, profiler, _ = batch_context
    requirement = _requirement(paths["valid_needs_pca"])
    profile = profiler.profile(
        paths["valid_needs_pca"],
        batch_key="batch",
        label_key="cell_type",
    )
    eligibility = TaskDataGate().evaluate(requirement, profile)

    assert "count_source_unresolved" in profile.blocking_errors
    assert eligibility.allowed is True
    assert eligibility.selected_representation == "X"
    assert "pca_preprocessing_required" in eligibility.warnings


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("missing_batch_key", "batch_key_unresolved:batch"),
        ("single_batch", "at_least_two_batches_required"),
        ("missing_batch_labels", "batch_labels_missing:1"),
        ("invalid_pca", "invalid_pca_representation"),
    ],
)
def test_invalid_batch_designs_are_blocked(batch_context, fixture, expected):
    paths, _, _, profiler, _ = batch_context
    requirement = _requirement(paths[fixture])
    profile = profiler.profile(paths[fixture], batch_key="batch", label_key="cell_type")
    eligibility = TaskDataGate().evaluate(requirement, profile)

    assert eligibility.allowed is False
    assert expected in eligibility.blocking_reasons


@pytest.mark.parametrize("tool_name,version", [("Harmony", "2.0.0"), ("Scanorama", "1.7.4")])
def test_batch_integration_compiler_builds_auditable_dry_run(
    batch_context,
    tool_name,
    version,
):
    paths, environments, registry, profiler, compiler = batch_context
    requirement = _requirement(paths["valid_pca"])
    profile = profiler.profile(paths["valid_pca"], batch_key="batch", label_key="cell_type")
    contract = registry.load(tool_name, version)
    plan = compiler.compile(
        requirement=requirement,
        data_profile=profile,
        tool_contract=contract,
        environment=environments.get("sckg-batch-cpu"),
        execution_budget=ExecutionBudget(),
    )

    assert plan.plan_status == "dry_run"
    assert [node.node_id for node in plan.steps] == BATCH_INTEGRATION_NODE_IDS
    assert plan.execution_eligible is False
    assert plan.execution_blockers == []
    assert plan.approval_required is True
    assert next(node for node in plan.steps if node.node_id == "run_integration_candidate").tool_name == tool_name
    assert next(node for node in plan.steps if node.node_id == "evaluate_biology_conservation").skippable is False

    tree = ast.parse(inspect.getsource(planner_module))
    assert not any(
        isinstance(item, (ast.Import, ast.ImportFrom))
        and any(alias.name == "subprocess" for alias in item.names)
        for item in ast.walk(tree)
    )


def test_batch_plan_blocks_without_multi_batch_eligibility(batch_context):
    paths, environments, registry, profiler, compiler = batch_context
    requirement = _requirement(paths["single_batch"])
    profile = profiler.profile(paths["single_batch"], batch_key="batch", label_key="cell_type")
    contract = registry.load("Harmony", "2.0.0")
    plan = compiler.compile(
        requirement=requirement,
        data_profile=profile,
        tool_contract=contract,
        environment=environments.get("sckg-batch-cpu"),
        execution_budget=ExecutionBudget(),
    )

    assert plan.plan_status == "blocked"
    assert any("at_least_two_batches_required" in item for item in plan.blocking_conditions)
