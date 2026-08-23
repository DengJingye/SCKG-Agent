from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.execution_models import ExecutionBudget, QualificationArtifact, RequirementSpec
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.integration_probe_builder import IntegrationProbeBuilder
from execution.local_controlled_executor import LocalControlledExecutor
from execution.reproducibility_packager import ReproducibilityPackager
from execution.validators.integration import IntegrationValidator


def main() -> None:
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workspace = PROJECT_ROOT / ".sckg_exec" / "phase5_batch" / run_stamp
    probes_root = workspace / "probes"
    probes_root.mkdir(parents=True)
    builder = IntegrationProbeBuilder()
    development_probe = builder.build(
        output_dir=probes_root / "development",
        allowed_output_root=probes_root,
        split_role="development",
        random_seed=20260716,
    )
    evaluation_probe = builder.build(
        output_dir=probes_root / "evaluation",
        allowed_output_root=probes_root,
        split_role="evaluation",
        random_seed=20260717,
    )
    assert development_probe.probe_hash != evaluation_probe.probe_hash

    environments = EnvironmentRegistry()
    environment = environments.get("sckg-batch-cpu")
    contracts = ToolContractRegistry(environment_registry=environments)
    profiler = AnnDataProfiler()
    profile = profiler.profile(
        development_probe.probe_artifact_path,
        batch_key="batch",
        label_key="cell_type",
    )
    requirement = RequirementSpec(
        request_id=f"phase5-batch-{run_stamp}",
        query="Qualify Harmony and Scanorama for controlled CPU batch integration",
        task="batch_integration",
        input_path=development_probe.probe_artifact_path,
        input_object_type="AnnData",
        batch_key="batch",
        label_key="cell_type",
        output_goal="integrated embedding with batch mixing and biology conservation metrics",
        data_access_authorized=True,
    )
    compiler = ExecutionPlanCompiler(contracts)
    executor = LocalControlledExecutor(
        approved_input_root=workspace,
        environment_registry=environments,
        contract_registry=contracts,
    )
    runner = ExperimentRunner(
        executor=executor,
        contract_registry=contracts,
        validator=IntegrationValidator(),
    )
    aggregator = CandidateAggregator()
    decision_engine = ParetoDecisionEngine()

    tool_specs = [
        (
            "Harmony",
            "2.0.0",
            [
                ("harmony-default", {}, "contract_default"),
                ("harmony-theta-4", {"theta": 4.0}, "contract_searchable_range"),
            ],
        ),
        (
            "Scanorama",
            "1.7.4",
            [
                ("scanorama-default", {}, "contract_default"),
                (
                    "scanorama-exact-neighbors",
                    {"approx": False},
                    "contract_searchable_range",
                ),
            ],
        ),
    ]
    development_batches = []
    evaluation_batches = []
    development_candidates = []
    evaluation_candidates = []
    workflow_plans = []
    loaded_contracts = []
    frozen_configurations = []
    for tool_name, version, specs in tool_specs:
        contract = contracts.load(tool_name, version)
        loaded_contracts.append(contract)
        planning_gate = contracts.planning_gate(contract, data_profile=profile)
        if not planning_gate.allowed:
            raise RuntimeError(f"planning gate failed for {tool_name}: {planning_gate.reasons}")
        workflow_plans.append(
            compiler.compile(
                requirement=requirement,
                data_profile=profile,
                tool_contract=contract,
                environment=environment,
                execution_budget=ExecutionBudget(),
            )
        )
        configurations = [
            build_configuration(
                configuration_id=configuration_id,
                parameters=parameters,
                provenance={},
                source=source,
                contract=contract,
            )
            for configuration_id, parameters, source in specs
        ]
        development_artifact = _artifact(development_probe, public_dataset=False)
        development_batch = runner.run(
            experiment_id=f"phase5-{run_stamp}-{tool_name.casefold()}-development",
            configurations=configurations,
            seeds=[11, 22, 33],
            probe=development_probe,
            artifact=development_artifact,
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=workflow_plans[-1].plan_id,
        )
        development_batches.append(development_batch)
        candidates = aggregator.aggregate(batch=development_batch, contract=contract)
        development_candidates.extend(candidates)
        tool_decision = decision_engine.decide(candidates, preference="performance")
        if tool_decision.recommended_candidate_id is None:
            raise RuntimeError(f"no eligible {tool_name} configuration")
        recommended_hash = next(
            item.configuration_hash
            for item in candidates
            if item.candidate_id == tool_decision.recommended_candidate_id
        )
        frozen = next(
            item for item in configurations if item.configuration_hash == recommended_hash
        ).model_copy(update={"frozen": True})
        frozen_configurations.append(frozen)
        evaluation_artifact = _artifact(evaluation_probe, public_dataset=False)
        evaluation_batch = runner.run(
            experiment_id=f"phase5-{run_stamp}-{tool_name.casefold()}-evaluation",
            configurations=[frozen],
            seeds=[evaluation_probe.random_seed],
            probe=evaluation_probe,
            artifact=evaluation_artifact,
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=workflow_plans[-1].plan_id,
        )
        evaluation_batches.append(evaluation_batch)
        evaluation_candidates.extend(
            aggregator.aggregate(batch=evaluation_batch, contract=contract)
        )

    decision = decision_engine.decide(development_candidates, preference="performance")
    package = ReproducibilityPackager().build_batch_integration(
        package_id=f"phase5-batch-engineering-{run_stamp}",
        requirement=requirement,
        data_profile=profile,
        development_probe=development_probe,
        evaluation_probe=evaluation_probe,
        workflow_plans=workflow_plans,
        contracts=loaded_contracts,
        environment=environment,
        batches=[*development_batches, *evaluation_batches],
        candidate_evaluations=[*development_candidates, *evaluation_candidates],
        decision_result=decision,
        rerun_command="conda run -n scRNAseq python scripts/run_phase5_batch_integration_qualification.py",
    )
    all_batches = [*development_batches, *evaluation_batches]
    runs = [run for batch in all_batches for run in batch.execution_runs]
    validations = [item for batch in all_batches for item in batch.validation_results]
    summary = {
        "phase": "Phase 5 Batch Integration engineering qualification",
        "environment": environment.environment_id,
        "development_probe_hash": development_probe.probe_hash,
        "evaluation_probe_hash": evaluation_probe.probe_hash,
        "probe_hashes_differ": development_probe.probe_hash != evaluation_probe.probe_hash,
        "initial_runs": sum(batch.requested_run_count for batch in development_batches),
        "frozen_evaluation_runs": sum(batch.requested_run_count for batch in evaluation_batches),
        "successful_runs": sum(run.status == "succeeded" for run in runs),
        "failed_runs": sum(run.status != "succeeded" for run in runs),
        "validations_passed": sum(item.passed for item in validations),
        "all_runs_use_local_controlled_executor": all(
            batch.all_runs_use_local_controlled_executor for batch in all_batches
        ),
        "candidate_evaluations": [
            {
                "candidate_id": item.candidate_id,
                "eligible": item.eligible_for_decision,
                "metrics": {
                    name: summary.mean for name, summary in item.metric_summaries.items()
                },
                "stability": item.seed_stability.get("stability_score"),
            }
            for item in development_candidates
        ],
        "decision_scope": decision.decision_scope,
        "pareto_frontier": decision.pareto_candidate_ids,
        "recommended_candidate": decision.recommended_candidate_id,
        "package_path": package.package_path,
        "package_complete": package.complete,
        "manifest_hashes_valid": package.manifest_hashes_valid,
        "fixed_pair_execution_gate_qualified": all(
            contracts.execution_gate(contract).allowed for contract in loaded_contracts
        ),
        "global_execution_policy": "disabled",
        "user_execution_available": False,
        "user_data_used": any(run.user_data_used for run in runs),
    }
    (workspace / "engineering_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert summary["initial_runs"] == 12
    assert summary["frozen_evaluation_runs"] == 2
    assert summary["successful_runs"] == 14
    assert summary["validations_passed"] == 14
    assert summary["all_runs_use_local_controlled_executor"]
    assert package.complete and package.manifest_hashes_valid
    assert not summary["user_data_used"]
    print(json.dumps(summary, indent=2, sort_keys=True))


def _artifact(probe, *, public_dataset: bool) -> QualificationArtifact:
    return QualificationArtifact(
        artifact_id=f"artifact-{probe.probe_id}",
        fixture_id=probe.source_fixture_id,
        path=probe.probe_artifact_path,
        sha256=probe.probe_hash,
        synthetic=probe.synthetic,
        public_dataset=public_dataset,
        user_data=False,
        accession=None,
        allowlisted=True,
        expected_cells=probe.n_cells,
    )


if __name__ == "__main__":
    main()
