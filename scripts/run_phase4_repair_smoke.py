#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
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
        candidates = sorted((conda_exe.parent.parent / "lib").glob("python3.*/site-packages"))
        if not candidates:
            raise RuntimeError("Pydantic unavailable and control-plane site-packages not found")
        source_root = candidates[-1]
        _CONTROL_DEPENDENCY_TEMP = tempfile.TemporaryDirectory(
            prefix="sckg_phase4_control_deps_"
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

from core.execution_models import RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.validators.doublet import DoubletValidator
from tests.fixtures.anndata_factory import write_phase1_fixtures


class HashMismatchValidator(DoubletValidator):
    """Smoke-only fault injector; it is not registered as a production wrapper."""

    def validate(self, run, *, expected_cells):
        tampered_hashes = dict(run.artifact_hashes)
        if tampered_hashes:
            first = sorted(tampered_hashes)[0]
            tampered_hashes[first] = "0" * 64
        tampered = run.model_copy(update={"artifact_hashes": tampered_hashes})
        return super().validate(tampered, expected_cells=expected_cells)


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    smoke_root = PROJECT_ROOT / ".sckg_exec" / "phase4" / timestamp
    fixtures = write_phase1_fixtures(smoke_root / "fixtures")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scrublet", "0.2.3")
    environment = environments.get("scRNAseq")
    requirement = RequirementSpec(
        request_id=f"phase4-smoke-{timestamp}",
        query="maintainer qualification of bounded Scrublet repair",
        input_path=str(fixtures["raw_x"]),
        input_object_type="AnnData",
        data_access_authorized=True,
        resource_budget={"max_cells": 12, "max_runtime_seconds": 120},
    )
    invalid_pc = build_configuration(
        configuration_id="invalid-pc",
        parameters={
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 100,
            "use_approx_neighbors": False,
        },
        provenance={},
        source="development_probe_search",
        contract=contract,
    )
    normal = build_configuration(
        configuration_id="hash-mismatch",
        parameters={
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 10,
            "use_approx_neighbors": False,
        },
        provenance={},
        source="development_probe_search",
        contract=contract,
    )

    scenario_a = _orchestrator(
        root=smoke_root / "scenario-a",
        environments=environments,
        contracts=contracts,
    ).run(
        orchestration_id=f"phase4-repairable-{timestamp}",
        requirement=requirement,
        configurations=[invalid_pc],
        seeds=[401, 402],
        fixture_id="phase1_raw_counts_x",
        package_id=f"phase4-repairable-{timestamp}",
        probe_max_cells=12,
        pairing_strategy="mixed",
        cluster_key="batch",
    )

    scenario_b_root = smoke_root / "scenario-b"
    scenario_b_root.mkdir(parents=True, exist_ok=True)
    executor_b = LocalControlledExecutor(
        run_root=scenario_b_root / "runs",
        approved_input_root=scenario_b_root / "probes",
        environment_registry=environments,
        contract_registry=contracts,
    )
    mismatch_validator = HashMismatchValidator()
    runner_b = ExperimentRunner(
        executor=executor_b,
        contract_registry=contracts,
        validator=mismatch_validator,
    )
    scenario_b = _orchestrator(
        root=scenario_b_root,
        environments=environments,
        contracts=contracts,
        executor=executor_b,
        validator=mismatch_validator,
        experiment_runner=runner_b,
    ).run(
        orchestration_id=f"phase4-nonrepairable-{timestamp}",
        requirement=requirement.model_copy(
            update={"request_id": f"phase4-hash-smoke-{timestamp}"}
        ),
        configurations=[normal],
        seeds=[501, 502],
        fixture_id="phase1_raw_counts_x",
        package_id=f"phase4-nonrepairable-{timestamp}",
        probe_max_cells=12,
        pairing_strategy="mixed",
        cluster_key="batch",
    )

    first_action = scenario_a.repair_actions[0] if scenario_a.repair_actions else None
    checks = {
        "repairable_completed": scenario_a.final_state == "COMPLETED",
        "repair_attempted": bool(scenario_a.repair_actions),
        "repair_success": any(item.passed for item in scenario_a.validation_results),
        "repair_package_complete": scenario_a.package_result.complete,
        "hash_mismatch_blocked": scenario_b.final_state == "BLOCKED",
        "hash_mismatch_not_retried": not scenario_b.repair_actions,
        "nonrepairable_package_complete": scenario_b.package_result.complete,
        "contract_execution_disabled": not contract.enabled_for_execution,
        "environment_execution_disabled": not environment.enabled_for_execution,
        "user_data_used_false": not any(
            run.user_data_used
            for run in [*scenario_a.execution_runs, *scenario_b.execution_runs]
        ),
    }
    summary = {
        "ok": all(checks.values()),
        "phase": "Phase 4 bounded repair smoke",
        "control_dependency_source": CONTROL_DEPENDENCY_SOURCE,
        "checks": checks,
        "scenario_a": {
            "repair_attempted": bool(scenario_a.repair_actions),
            "repair_reason": first_action.reason_code if first_action else None,
            "original_run_id": first_action.parent_run_id if first_action else None,
            "new_run_id": first_action.new_run_id if first_action else None,
            "changed_parameters": first_action.new_values if first_action else {},
            "repair_success": scenario_a.final_state == "COMPLETED",
            "run_budget_used": scenario_a.budget.model_dump(mode="json"),
            "validation_result": [
                item.model_dump(mode="json") for item in scenario_a.validation_results
            ],
            "decision_result": scenario_a.decision_result.model_dump(mode="json"),
            "package_complete": scenario_a.package_result.complete,
            "package_path": scenario_a.package_result.package_path,
            "state_history": scenario_a.state_history,
        },
        "scenario_b": {
            "repair_attempted": bool(scenario_b.repair_actions),
            "repair_reason": "hash_mismatch",
            "original_run_id": scenario_b.execution_runs[0].run_id,
            "new_run_id": None,
            "changed_parameters": {},
            "repair_success": False,
            "run_budget_used": scenario_b.budget.model_dump(mode="json"),
            "validation_result": [
                item.model_dump(mode="json") for item in scenario_b.validation_results
            ],
            "package_complete": scenario_b.package_result.complete,
            "package_path": scenario_b.package_result.package_path,
            "state_history": scenario_b.state_history,
        },
        "enabled_for_execution": {
            "contract": contract.enabled_for_execution,
            "environment": environment.enabled_for_execution,
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _orchestrator(
    *,
    root,
    environments,
    contracts,
    executor=None,
    validator=None,
    experiment_runner=None,
):
    return ExecutionOrchestrator(
        run_root=root / "runs",
        approved_input_root=root / "probes",
        package_root=PROJECT_ROOT / ".sckg_exec" / "packages",
        trace_root=root / "traces",
        environment_registry=environments,
        contract_registry=contracts,
        executor=executor,
        validator=validator,
        experiment_runner=experiment_runner,
    )


if __name__ == "__main__":
    raise SystemExit(main())
