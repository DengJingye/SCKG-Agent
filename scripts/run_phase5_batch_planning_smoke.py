from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.execution_models import ExecutionBudget, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.task_data_gate import TaskDataGate
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import write_phase5_batch_fixtures


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sckg-phase5-plan-") as temp_dir:
        fixtures = write_phase5_batch_fixtures(Path(temp_dir))
        environments = EnvironmentRegistry()
        contracts = ToolContractRegistry(environment_registry=environments)
        profiler = AnnDataProfiler()
        compiler = ExecutionPlanCompiler(contracts)
        environment = environments.get("sckg-batch-cpu")

        requirement = RequirementSpec(
            request_id="phase5_batch_planning_smoke",
            query="Plan CPU batch integration candidates",
            task="batch_integration",
            input_path=str(fixtures["valid_pca"]),
            input_object_type="AnnData",
            batch_key="batch",
            label_key="cell_type",
            output_goal="integrated embedding with batch and biology evaluation",
            data_access_authorized=True,
        )
        profile = profiler.profile(
            fixtures["valid_pca"],
            batch_key="batch",
            label_key="cell_type",
        )
        eligibility = TaskDataGate().evaluate(requirement, profile)
        plans = {}
        for tool_name, version in (("Harmony", "2.0.0"), ("Scanorama", "1.7.4")):
            contract = contracts.load(tool_name, version)
            plan = compiler.compile(
                requirement=requirement,
                data_profile=profile,
                tool_contract=contract,
                environment=environment,
                execution_budget=ExecutionBudget(),
            )
            plans[tool_name] = {
                "plan_status": plan.plan_status,
                "node_count": len(plan.steps),
                "planning_gate": contracts.planning_gate(contract, data_profile=profile).allowed,
                "execution_gate": contracts.execution_gate(contract).allowed,
                "execution_blockers": plan.execution_blockers,
                "enabled_for_execution": contract.enabled_for_execution,
            }
            assert plan.plan_status == "dry_run"
            assert plan.execution_eligible is False
            assert contract.enabled_for_execution is True
            assert contracts.execution_gate(contract).allowed is True

        blocked_requirement = requirement.model_copy(
            update={"request_id": "phase5_single_batch", "input_path": str(fixtures["single_batch"])}
        )
        blocked_profile = profiler.profile(
            fixtures["single_batch"], batch_key="batch", label_key="cell_type"
        )
        blocked = TaskDataGate().evaluate(blocked_requirement, blocked_profile)
        assert not blocked.allowed
        assert "at_least_two_batches_required" in blocked.blocking_reasons

        print(
            json.dumps(
                {
                    "phase": "Phase 5 qualified dry-run planning",
                    "task": "batch_integration",
                    "batch_profile": {
                        "cells": profile.n_cells,
                        "genes": profile.n_genes,
                        "batch_count": profile.batch_count,
                        "batch_min_cells": profile.batch_min_cells,
                        "pca_components": profile.pca_n_components,
                        "biology_label_mode": eligibility.biology_label_mode,
                    },
                    "task_gate_allowed": eligibility.allowed,
                    "selected_representation": eligibility.selected_representation,
                    "plans": plans,
                    "single_batch_blocked": not blocked.allowed,
                    "single_batch_reasons": blocked.blocking_reasons,
                    "tool_process_executed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
