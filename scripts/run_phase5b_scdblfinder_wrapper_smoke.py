#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from core.execution_models import QualificationArtifact
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.probe_builder import ProbeBuilder
from execution.validators.scdblfinder import ScDblFinderValidator
from tests.fixtures.anndata_factory import write_phase1_fixtures


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    root = PROJECT_ROOT / ".sckg_exec" / "phase5b-wrapper-smoke" / timestamp
    fixtures = write_phase1_fixtures(root / "fixtures")
    profile = AnnDataProfiler().profile(fixtures["raw_x"])
    probe = ProbeBuilder().build(
        source_path=fixtures["raw_x"],
        output_dir=root / "probes" / "shared",
        profile_id=profile.profile_id,
        fixture_id="phase1_raw_counts_x",
        max_cells=40,
        random_seed=20260712,
        split_role="development",
        pairing_strategy="mixed",
        cluster_key="batch",
        allowed_output_root=root / "probes",
    )
    artifact = QualificationArtifact(
        artifact_id="phase5b-scdblfinder-wrapper-smoke",
        fixture_id=probe.source_fixture_id,
        path=probe.probe_artifact_path,
        sha256=probe.probe_hash,
        synthetic=True,
        allowlisted=True,
        expected_cells=probe.n_probe_cells,
    )
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scDblFinder", "1.24.0")
    environment = environments.get(contract.environment_id)
    planning_gate = contracts.planning_gate(contract, data_profile=profile)
    executor = LocalControlledExecutor(
        run_root=root / "runs",
        approved_input_root=root / "probes",
        environment_registry=environments,
        contract_registry=contracts,
    )
    runner = ExperimentRunner(
        executor=executor,
        contract_registry=contracts,
        validator=ScDblFinderValidator(contract),
    )
    configuration = build_configuration(
        configuration_id="scdblfinder-wrapper-smoke-default",
        parameters={"dbr": 0.1, "clusters": False, "n_cores": 1},
        provenance={},
        source="contract_default",
        contract=contract,
    )
    batch = runner.run(
        experiment_id=f"phase5b-wrapper-smoke-{timestamp}",
        configurations=[configuration],
        seeds=[701],
        probe=probe,
        artifact=artifact,
        contract=contract,
        environment=environment,
        planning_gate=planning_gate,
        plan_id=f"phase5b-wrapper-smoke-plan-{timestamp}",
    )
    run = batch.execution_runs[0] if batch.execution_runs else None
    validation = batch.validation_results[0] if batch.validation_results else None
    checks = {
        "planning_gate_passed": planning_gate.allowed,
        "one_run_recorded": len(batch.execution_runs) == 1,
        "local_controlled_executor": batch.all_runs_use_local_controlled_executor,
        "r_wrapper_actual_execution": bool(
            run
            and run.status == "succeeded"
            and run.exit_code == 0
            and run.artifact_paths
        ),
        "artifacts_complete": bool(
            run
            and {
                "doublet_results.tsv",
                "parameters.json",
                "result_metadata.json",
            }.issubset(run.artifact_paths)
        ),
        "validator_passed": bool(validation and validation.passed),
        "synthetic_fixture": bool(run and run.synthetic_fixture),
        "user_data_used_false": bool(run and not run.user_data_used),
        "enabled_for_execution_false": not (
            contract.enabled_for_execution or environment.enabled_for_execution
        ),
    }
    summary = {
        "ok": all(checks.values()),
        "checks": checks,
        "run": run.model_dump(mode="json") if run else None,
        "validation": validation.model_dump(mode="json") if validation else None,
        "batch_failures": batch.failures,
        "contract_status_before_promotion": {
            "wrapper_status": contract.wrapper_status,
            "environment_status": contract.environment_status,
            "execution_status": contract.execution_status,
            "enabled_for_execution": contract.enabled_for_execution,
        },
        "environment_status_before_promotion": {
            "qualification_status": environment.qualification_status,
            "integration_test_passed": environment.integration_test_passed,
            "enabled_for_execution": environment.enabled_for_execution,
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
