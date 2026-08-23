#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_CONTROL_DEPENDENCY_TEMP: tempfile.TemporaryDirectory[str] | None = None


def _ensure_control_plane_dependencies() -> str:
    global _CONTROL_DEPENDENCY_TEMP
    try:
        import pydantic  # noqa: F401

        return "active_environment"
    except ModuleNotFoundError:
        conda_exe = Path(os.environ.get("CONDA_EXE", "/opt/anaconda3/bin/conda"))
        conda_root = conda_exe.parent.parent
        candidates = sorted((conda_root / "lib").glob("python3.*/site-packages"))
        if not candidates:
            raise RuntimeError("Pydantic unavailable and control-plane site-packages not found")
        source_root = candidates[-1]
        _CONTROL_DEPENDENCY_TEMP = tempfile.TemporaryDirectory(
            prefix="sckg_phase2_control_deps_"
        )
        isolated_root = Path(_CONTROL_DEPENDENCY_TEMP.name)
        for package_name in ("annotated_types", "dotenv", "pydantic", "pydantic_core"):
            source = source_root / package_name
            if not source.exists():
                raise RuntimeError(f"Missing control-plane dependency: {source}")
            (isolated_root / package_name).symlink_to(source, target_is_directory=True)
        sys.path.append(str(isolated_root))
        import pydantic  # noqa: F401

        return f"isolated_pydantic_from:{source_root}"


CONTROL_DEPENDENCY_SOURCE = _ensure_control_plane_dependencies()

from core.execution_models import ExecutionBudget, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
import engine.execution_planner as planner_module
from engine.execution_planner import ExecutionPlanCompiler
from execution.environment_registry import EnvironmentRegistry
from tests.fixtures.anndata_factory import FIXTURE_SEED, write_phase1_fixtures


def _requirement(path: Path) -> RequirementSpec:
    return RequirementSpec(
        request_id=f"phase2_smoke_{path.stem}",
        query="Compile a dry-run Scrublet planning workflow",
        input_path=str(path),
        input_object_type="AnnData",
        data_access_authorized=True,
        execution_authorized=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sckg_phase2_") as temp_dir:
        paths = write_phase1_fixtures(Path(temp_dir))
        environments = EnvironmentRegistry()
        contracts = ToolContractRegistry(environment_registry=environments)
        contract = contracts.load("scrublet", "0.2.3")
        environment = environments.get("scRNAseq")
        compiler = ExecutionPlanCompiler(contracts)
        profiler = AnnDataProfiler()

        raw_profile = profiler.profile(paths["raw_x"])
        layer_profile = profiler.profile(paths["counts_layer"])
        scaled_profile = profiler.profile(paths["scaled"])
        raw_plan = compiler.compile(
            requirement=_requirement(paths["raw_x"]),
            data_profile=raw_profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=ExecutionBudget(),
        )
        layer_plan = compiler.compile(
            requirement=_requirement(paths["counts_layer"]),
            data_profile=layer_profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=ExecutionBudget(),
        )
        scaled_plan = compiler.compile(
            requirement=_requirement(paths["scaled"]),
            data_profile=scaled_profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=ExecutionBudget(),
        )
        planning_gate = contracts.planning_gate(contract, data_profile=raw_profile)
        execution_gate = contracts.execution_gate(contract)

        checks = {
            "raw_x_dry_run": raw_plan.plan_status == "dry_run",
            "counts_layer_dry_run": layer_plan.plan_status == "dry_run",
            "scaled_unresolved_blocked": scaled_plan.plan_status == "blocked",
            "planning_gate_passed": planning_gate.allowed,
            "execution_gate_status_recorded": execution_gate.gate == "execution",
            "execution_gate_cannot_promote_dry_run": (
                raw_plan.plan_status == "dry_run"
                and raw_plan.execution_eligible is False
                and raw_plan.approval_required is True
            ),
            "scrublet_not_imported_or_executed": "scrublet" not in sys.modules,
            "planner_contains_no_subprocess_reference": "subprocess"
            not in Path(planner_module.__file__).read_text(encoding="utf-8"),
            "all_nodes_present": [node.node_id for node in raw_plan.steps]
            == [
                "validate_input",
                "select_count_source",
                "build_probe_plan",
                "run_scrublet_candidate",
                "validate_expected_outputs",
                "aggregate_candidate_results",
                "package_expected_artifacts",
            ],
        }
        summary = {
            "ok": all(checks.values()),
            "phase": "Phase 2 dry-run planning smoke",
            "conda_environment": os.getenv("CONDA_DEFAULT_ENV", "unknown"),
            "python": sys.version.split()[0],
            "fixture_seed": FIXTURE_SEED,
            "control_dependency_source": CONTROL_DEPENDENCY_SOURCE,
            "checks": checks,
            "plans": {
                "raw_x": {
                    "plan_id": raw_plan.plan_id,
                    "status": raw_plan.plan_status,
                    "selected_count_source": raw_profile.selected_count_source,
                    "node_ids": [node.node_id for node in raw_plan.steps],
                    "execution_eligible": raw_plan.execution_eligible,
                },
                "counts_layer": {
                    "plan_id": layer_plan.plan_id,
                    "status": layer_plan.plan_status,
                    "selected_count_source": layer_profile.selected_count_source,
                    "execution_eligible": layer_plan.execution_eligible,
                },
                "scaled": {
                    "plan_id": scaled_plan.plan_id,
                    "status": scaled_plan.plan_status,
                    "blocking_conditions": scaled_plan.blocking_conditions,
                    "execution_eligible": scaled_plan.execution_eligible,
                },
            },
            "planning_gate": planning_gate.model_dump(mode="json"),
            "execution_gate": execution_gate.model_dump(mode="json"),
            "guardrail": "Plans are dry-run or blocked; no ExecutionRequest or tool process exists.",
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
