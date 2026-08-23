#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from core.execution_models import QualificationArtifact, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.probe_builder import ProbeBuilder
from execution.reproducibility_packager import ReproducibilityPackager
from execution.runtime_pack_resolver import RuntimePackResolver
from execution.validators.doublet import DoubletValidator
from execution.validators.scdblfinder import ScDblFinderValidator
from tests.fixtures.anndata_factory import write_phase1_fixtures


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    root = PROJECT_ROOT / ".sckg_exec" / "phase5b" / timestamp
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
        artifact_id="phase5b-shared-probe",
        fixture_id=probe.source_fixture_id,
        path=probe.probe_artifact_path,
        sha256=probe.probe_hash,
        synthetic=True,
        allowlisted=True,
        expected_cells=probe.n_probe_cells,
    )
    requirement = RequirementSpec(
        request_id=f"phase5b-{timestamp}",
        query="maintainer multi-tool doublet qualification",
        input_path=str(fixtures["raw_x"]),
        input_object_type="AnnData",
        data_access_authorized=True,
        resource_budget={"max_cells": 40, "max_runtime_seconds": 180},
    )
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    scrublet_contract = contracts.load("Scrublet", "0.2.3")
    scdblfinder_contract = contracts.load("scDblFinder", "1.24.0")
    scrublet_environment = environments.get(scrublet_contract.environment_id)
    scdblfinder_environment = environments.get(scdblfinder_contract.environment_id)
    scrublet_gate = contracts.planning_gate(scrublet_contract, data_profile=profile)
    scdblfinder_gate = contracts.planning_gate(
        scdblfinder_contract, data_profile=profile
    )

    executor = LocalControlledExecutor(
        run_root=root / "runs",
        approved_input_root=root / "probes",
        environment_registry=environments,
        contract_registry=contracts,
    )
    scrublet_runner = ExperimentRunner(
        executor=executor,
        contract_registry=contracts,
        validator=DoubletValidator(),
    )
    scdblfinder_runner = ExperimentRunner(
        executor=executor,
        contract_registry=contracts,
        validator=ScDblFinderValidator(scdblfinder_contract),
    )
    scrublet_configs = [
        build_configuration(
            configuration_id="scrublet-rate-008",
            parameters={
                "expected_doublet_rate": 0.08,
                "min_counts": 1,
                "min_cells": 1,
                "min_gene_variability_pctl": 0.0,
                "n_prin_comps": 10,
                "use_approx_neighbors": False,
            },
            provenance={},
            source="development_probe_search",
            contract=scrublet_contract,
        ),
        build_configuration(
            configuration_id="scrublet-rate-012",
            parameters={
                "expected_doublet_rate": 0.12,
                "min_counts": 1,
                "min_cells": 1,
                "min_gene_variability_pctl": 0.0,
                "n_prin_comps": 10,
                "use_approx_neighbors": False,
            },
            provenance={},
            source="development_probe_search",
            contract=scrublet_contract,
        ),
    ]
    scdblfinder_configs = [
        build_configuration(
            configuration_id="scdblfinder-dbr-008",
            parameters={"dbr": 0.08, "clusters": False, "n_cores": 1},
            provenance={},
            source="development_probe_search",
            contract=scdblfinder_contract,
        ),
        build_configuration(
            configuration_id="scdblfinder-dbr-012",
            parameters={"dbr": 0.12, "clusters": False, "n_cores": 1},
            provenance={},
            source="development_probe_search",
            contract=scdblfinder_contract,
        ),
    ]
    seeds = [601, 602, 603]
    scrublet_batch = scrublet_runner.run(
        experiment_id=f"phase5b-scrublet-{timestamp}",
        configurations=scrublet_configs,
        seeds=seeds,
        probe=probe,
        artifact=artifact,
        contract=scrublet_contract,
        environment=scrublet_environment,
        planning_gate=scrublet_gate,
        plan_id=f"phase5b-plan-{timestamp}",
    )
    scdblfinder_batch = scdblfinder_runner.run(
        experiment_id=f"phase5b-scdblfinder-{timestamp}",
        configurations=scdblfinder_configs,
        seeds=seeds,
        probe=probe,
        artifact=artifact,
        contract=scdblfinder_contract,
        environment=scdblfinder_environment,
        planning_gate=scdblfinder_gate,
        plan_id=f"phase5b-plan-{timestamp}",
    )
    aggregator = CandidateAggregator()
    candidates = [
        *aggregator.aggregate(batch=scrublet_batch, contract=scrublet_contract),
        *aggregator.aggregate(
            batch=scdblfinder_batch, contract=scdblfinder_contract
        ),
    ]
    decision = ParetoDecisionEngine().decide(candidates, preference="performance")
    r_environment = _r_environment_check()
    actual_scrublet_runs = sum(
        run.status == "succeeded" for run in scrublet_batch.execution_runs
    )
    actual_scdblfinder_runs = sum(
        run.status == "succeeded" for run in scdblfinder_batch.execution_runs
    )
    cross_tool_complete = actual_scrublet_runs > 0 and actual_scdblfinder_runs > 0
    package = ReproducibilityPackager().build_multitool(
        package_id=f"phase5b-multitool-{timestamp}",
        requirement=requirement,
        data_profile=profile,
        shared_probe=probe,
        contracts=[scrublet_contract, scdblfinder_contract],
        environments=[scrublet_environment, scdblfinder_environment],
        batches=[scrublet_batch, scdblfinder_batch],
        candidate_evaluations=candidates,
        decision_result=decision,
        environment_check=r_environment,
        rerun_command="python scripts/run_phase5b_multitool_qualification.py",
        cross_tool_comparison_complete=cross_tool_complete,
    )
    package_contracts = json.loads(
        (Path(package.package_path) / "contract_snapshots.json").read_text(
            encoding="utf-8"
        )
    )
    checks = {
        "same_input_hash": len(
            {run.input_hash for run in [*scrublet_batch.execution_runs, *scdblfinder_batch.execution_runs]}
        )
        == 1,
        "same_input_cells": all(
            record.probe_hash == probe.probe_hash
            for record in [*scrublet_batch.run_records, *scdblfinder_batch.run_records]
        ),
        "scrublet_uses_local_executor": scrublet_batch.all_runs_use_local_controlled_executor,
        "scdblfinder_uses_local_executor": scdblfinder_batch.all_runs_use_local_controlled_executor,
        "separate_validators": all(
            item.validation_version == "doublet-validator-v1"
            for item in scrublet_batch.validation_results
        )
        and all(
            item.validation_version == "scdblfinder-validator-v1"
            for item in scdblfinder_batch.validation_results
        ),
        "scrublet_actual_runs_6": actual_scrublet_runs == 6,
        "scdblfinder_actual_runs_6": actual_scdblfinder_runs == 6,
        "all_validations_passed": all(
            item.passed
            for item in [
                *scrublet_batch.validation_results,
                *scdblfinder_batch.validation_results,
            ]
        ),
        "both_tools_have_eligible_candidate": all(
            any(
                item.eligible_for_decision and item.tool_name == tool_name
                for item in candidates
            )
            for tool_name in ("Scrublet", "scDblFinder")
        ),
        "cross_tool_comparison_complete": cross_tool_complete
        and not any(
            "incomplete" in item.casefold()
            for item in decision.limitations
        ),
        "all_scdblfinder_candidates_eligible": all(
            item.eligible_for_decision
            for item in candidates
            if item.tool_name == "scDblFinder"
        ),
        "package_contains_both_tools": set(package_contracts)
        == {"Scrublet", "scDblFinder"},
        "package_complete": package.complete and package.manifest_hashes_valid,
        "no_user_data": not any(
            run.user_data_used
            for run in [*scrublet_batch.execution_runs, *scdblfinder_batch.execution_runs]
        ),
        "all_execution_flags_false": not any(
            [
                scrublet_contract.enabled_for_execution,
                scdblfinder_contract.enabled_for_execution,
                scrublet_environment.enabled_for_execution,
                scdblfinder_environment.enabled_for_execution,
            ]
        ),
    }
    summary = {
        "ok": all(checks.values()),
        "phase": "Phase 5B real multi-tool qualification",
        "environment": r_environment,
        "checks": checks,
        "shared_probe": {
            "probe_hash": probe.probe_hash,
            "n_cells": probe.n_probe_cells,
        },
        "runs": {
            "scrublet_requested": scrublet_batch.requested_run_count,
            "scrublet_actual": actual_scrublet_runs,
            "scdblfinder_requested": scdblfinder_batch.requested_run_count,
            "scdblfinder_actual": actual_scdblfinder_runs,
            "scdblfinder_blocked": sum(
                run.status == "blocked" for run in scdblfinder_batch.execution_runs
            ),
            "succeeded": sum(
                run.status == "succeeded"
                for run in [
                    *scrublet_batch.execution_runs,
                    *scdblfinder_batch.execution_runs,
                ]
            ),
            "failed_or_blocked": sum(
                run.status != "succeeded"
                for run in [
                    *scrublet_batch.execution_runs,
                    *scdblfinder_batch.execution_runs,
                ]
            ),
        },
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "decision": decision.model_dump(mode="json"),
        "cross_tool_comparison_complete": cross_tool_complete,
        "package": package.model_dump(mode="json"),
        "enabled_for_execution": {
            "scrublet_contract": scrublet_contract.enabled_for_execution,
            "scdblfinder_contract": scdblfinder_contract.enabled_for_execution,
            "scrublet_environment": scrublet_environment.enabled_for_execution,
            "scdblfinder_environment": scdblfinder_environment.enabled_for_execution,
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _r_environment_check() -> dict:
    resolver = RuntimePackResolver()
    registered = resolver.rscript("doublet-r") if resolver.ready("doublet-r") else None
    environment = EnvironmentRegistry().get("scDblFinder-R")
    return {
        "rscript_available": bool(registered and registered.is_file()),
        "rscript_path": "[runtime-pack]/bin/Rscript" if registered else None,
        "r_version": environment.package_versions["r"],
        "scdblfinder_version": environment.package_versions["scdblfinder"],
        "SingleCellExperiment": environment.package_versions["singlecellexperiment"],
        "Matrix": environment.package_versions["matrix"],
        "jsonlite": environment.package_versions["jsonlite"],
        "status": str(environment.qualification_status),
        "integration_test_passed": environment.integration_test_passed,
        "enabled_for_execution": environment.enabled_for_execution,
    }


if __name__ == "__main__":
    raise SystemExit(main())
