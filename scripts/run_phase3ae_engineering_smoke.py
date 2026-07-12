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
        conda_root = conda_exe.parent.parent
        candidates = sorted((conda_root / "lib").glob("python3.*/site-packages"))
        if not candidates:
            raise RuntimeError("Pydantic unavailable and control-plane site-packages not found")
        source_root = candidates[-1]
        _CONTROL_DEPENDENCY_TEMP = tempfile.TemporaryDirectory(
            prefix="sckg_phase3ae_control_deps_"
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

from core.execution_models import ExecutionBudget, QualificationArtifact, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.probe_builder import ProbeBuilder
from execution.reproducibility_packager import ReproducibilityPackager
from tests.fixtures.anndata_factory import FIXTURE_SEED, write_phase1_fixtures


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    with tempfile.TemporaryDirectory(prefix="sckg_phase3ae_") as temp_dir:
        root = Path(temp_dir)
        fixtures = write_phase1_fixtures(root / "fixtures")
        profiler = AnnDataProfiler()
        profile = profiler.profile(fixtures["raw_x"])
        environments = EnvironmentRegistry()
        environment = environments.get("scRNAseq")
        contracts = ToolContractRegistry(environment_registry=environments)
        contract = contracts.load("scrublet", "0.2.3")
        planning_gate = contracts.planning_gate(contract, data_profile=profile)
        execution_gate = contracts.execution_gate(contract)
        requirement = RequirementSpec(
            request_id=f"phase3ae-{token}",
            query="Run bounded Scrublet configuration-level synthetic engineering evaluation",
            input_path=str(fixtures["raw_x"]),
            input_object_type="AnnData",
            data_access_authorized=True,
            execution_authorized=False,
        )
        workflow_plan = ExecutionPlanCompiler(contracts).compile(
            requirement=requirement,
            data_profile=profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=ExecutionBudget(
                max_initial_runs=6,
                reserved_repair_runs=0,
                reserved_validation_reruns=3,
                max_total_runs=9,
                timeout_seconds=120,
            ),
        )

        development_probe = ProbeBuilder().build(
            source_path=fixtures["raw_x"],
            output_dir=root / "probes" / "development",
            profile_id=profile.profile_id,
            fixture_id="phase1_raw_counts_x",
            random_seed=10101,
            split_role="development",
            pairing_strategy="mixed",
            cluster_key="batch",
            allowed_output_root=root / "probes",
        )
        evaluation_probe = ProbeBuilder().build(
            source_path=fixtures["raw_x"],
            output_dir=root / "probes" / "evaluation",
            profile_id=profile.profile_id,
            fixture_id="phase1_raw_counts_x",
            random_seed=20202,
            split_role="evaluation",
            pairing_strategy="between_cluster",
            cluster_key="batch",
            allowed_output_root=root / "probes",
        )
        development_artifact = _artifact(development_probe, "development-probe")
        evaluation_artifact = _artifact(evaluation_probe, "evaluation-probe")

        common_parameters = {
            "min_counts": 1,
            "min_cells": 1,
            "min_gene_variability_pctl": 0.0,
            "n_prin_comps": 10,
            "use_approx_neighbors": False,
        }
        configurations = [
            build_configuration(
                configuration_id="rate-008",
                parameters={**common_parameters, "expected_doublet_rate": 0.08},
                provenance={
                    "expected_doublet_rate": {
                        "origin": "development_probe_search",
                        "contract_searchable_range": [0.02, 0.15],
                    }
                },
                source="development_probe_search",
                contract=contract,
            ),
            build_configuration(
                configuration_id="rate-012",
                parameters={**common_parameters, "expected_doublet_rate": 0.12},
                provenance={
                    "expected_doublet_rate": {
                        "origin": "development_probe_search",
                        "contract_searchable_range": [0.02, 0.15],
                    }
                },
                source="development_probe_search",
                contract=contract,
            ),
        ]
        executor = LocalControlledExecutor(
            run_root=root / "runs",
            approved_input_root=root / "probes",
            environment_registry=environments,
        )
        runner = ExperimentRunner(
            executor=executor,
            contract_registry=contracts,
        )
        development_batch = runner.run(
            experiment_id=f"development-{token}",
            configurations=configurations,
            seeds=[301, 302, 303],
            probe=development_probe,
            artifact=development_artifact,
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=workflow_plan.plan_id,
        )
        aggregator = CandidateAggregator()
        development_candidates = aggregator.aggregate(
            batch=development_batch, contract=contract
        )
        selection_decision = ParetoDecisionEngine().decide(
            development_candidates, preference="performance"
        )
        selected = next(
            (
                configuration
                for configuration in configurations
                if selection_decision.recommended_candidate_id
                and selection_decision.recommended_candidate_id.endswith(
                    configuration.configuration_hash[:16]
                )
            ),
            None,
        )
        if selected is None:
            raise RuntimeError("development probe produced no eligible frozen configuration")
        frozen_configuration = selected.model_copy(update={"frozen": True})
        evaluation_batch = runner.run(
            experiment_id=f"evaluation-{token}",
            configurations=[frozen_configuration],
            seeds=[401, 402, 403],
            probe=evaluation_probe,
            artifact=evaluation_artifact,
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=workflow_plan.plan_id,
        )
        evaluation_candidates = aggregator.aggregate(
            batch=evaluation_batch, contract=contract
        )
        final_decision = ParetoDecisionEngine().decide(
            evaluation_candidates, preference="performance"
        )

        package = ReproducibilityPackager().build(
            package_id=f"phase3ae-smoke-{token}",
            requirement=requirement,
            data_profile=profile,
            development_probe=development_probe,
            evaluation_probe=evaluation_probe,
            workflow_plan=workflow_plan,
            contract=contract,
            environment=environment,
            batches=[development_batch, evaluation_batch],
            candidate_evaluations=[*development_candidates, *evaluation_candidates],
            decision_result=final_decision,
            rerun_command="conda run -n scRNAseq python scripts/run_phase3ae_engineering_smoke.py",
            user_data_used=False,
        )

        all_runs = [
            *development_batch.execution_runs,
            *evaluation_batch.execution_runs,
        ]
        all_validations = [
            *development_batch.validation_results,
            *evaluation_batch.validation_results,
        ]
        metadata = [_metadata(run) for run in all_runs]
        initial_runs = development_batch.requested_run_count
        checks = {
            "initial_runs_lte_12": initial_runs <= 12,
            "development_evaluation_hashes_differ": (
                development_probe.probe_hash != evaluation_probe.probe_hash
                and development_probe.ground_truth_hash
                != evaluation_probe.ground_truth_hash
            ),
            "evaluation_parameters_frozen": (
                evaluation_batch.configurations == [frozen_configuration]
                and all(
                    record.configuration_hash == frozen_configuration.configuration_hash
                    for record in evaluation_batch.run_records
                )
            ),
            "all_runs_use_local_controlled_executor": (
                development_batch.all_runs_use_local_controlled_executor
                and evaluation_batch.all_runs_use_local_controlled_executor
                and len(all_runs)
                == development_batch.requested_run_count
                + evaluation_batch.requested_run_count
            ),
            "candidate_evaluation_generated": bool(
                development_candidates and evaluation_candidates
            ),
            "decision_result_generated": final_decision.recommended_candidate_id
            is not None,
            "package_complete": package.complete,
            "manifest_hashes_valid": package.manifest_hashes_valid,
            "scrublet_actually_executed": bool(metadata)
            and all(item.get("scrublet_actually_executed") is True for item in metadata),
            "user_data_used_is_false": bool(metadata)
            and all(item.get("user_data_used") is False for item in metadata),
            "all_validations_passed": bool(all_validations)
            and all(item.passed for item in all_validations),
            "contract_execution_disabled": contract.enabled_for_execution is False,
            "environment_execution_disabled": environment.enabled_for_execution is False,
            "scientific_validation_status_controlled": contract.scientific_validation_status
            in {"not_evaluated", "scientific_pilot"},
            "execution_gate_remains_closed": not execution_gate.allowed,
        }
        summary = {
            "ok": all(checks.values()),
            "phase": "Phase 3A-E configuration engineering smoke",
            "conda_environment": os.getenv("CONDA_DEFAULT_ENV", "unknown"),
            "control_dependency_source": CONTROL_DEPENDENCY_SOURCE,
            "checks": checks,
            "experiment": {
                "configuration_count": len(configurations),
                "development_seed_count": 3,
                "evaluation_seed_count": 3,
                "initial_run_count": initial_runs,
                "total_run_count": len(all_runs),
                "successful_run_count": sum(run.status == "succeeded" for run in all_runs),
                "failed_run_count": sum(run.status != "succeeded" for run in all_runs),
                "development_probe_hash": development_probe.probe_hash,
                "evaluation_probe_hash": evaluation_probe.probe_hash,
            },
            "development_candidates": [
                candidate.model_dump(mode="json") for candidate in development_candidates
            ],
            "selection_decision": selection_decision.model_dump(mode="json"),
            "frozen_configuration": frozen_configuration.model_dump(mode="json"),
            "evaluation_candidates": [
                candidate.model_dump(mode="json") for candidate in evaluation_candidates
            ],
            "final_decision": final_decision.model_dump(mode="json"),
            "package": package.model_dump(mode="json"),
            "execution_gate": execution_gate.model_dump(mode="json"),
            "guardrail": (
                "Only maintainer-approved synthetic probes were used; no user data, UI, "
                "Agent route, scientific dataset, or execution enablement was added."
            ),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 1


def _artifact(probe, artifact_id):
    return QualificationArtifact(
        artifact_id=artifact_id,
        fixture_id=probe.source_fixture_id,
        path=probe.probe_artifact_path,
        sha256=probe.probe_hash,
        synthetic=True,
        allowlisted=True,
        expected_cells=probe.n_probe_cells,
    )


def _metadata(run) -> dict:
    path = run.artifact_paths.get("result_metadata.json")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


if __name__ == "__main__":
    raise SystemExit(main())
