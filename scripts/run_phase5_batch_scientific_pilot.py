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
from data_pipeline.prepare_scib_pancreas import DATASET_ROOT, prepare_scib_pancreas
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.integration_scientific_dataset import build_integration_scientific_split
from execution.integration_scientific_evaluator import bootstrap_integration_metrics
from execution.local_controlled_executor import LocalControlledExecutor
from execution.reproducibility_packager import ReproducibilityPackager
from execution.validators.integration import IntegrationValidator


def main() -> None:
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dataset = prepare_scib_pancreas()
    split_dir = DATASET_ROOT / "processed" / "splits" / "fixed-v1"
    if (split_dir / "split_manifest.json").is_file():
        from core.execution_models import IntegrationSplitManifest

        split = IntegrationSplitManifest.model_validate_json(
            (split_dir / "split_manifest.json").read_text(encoding="utf-8")
        )
    else:
        split = build_integration_scientific_split(
            dataset=dataset,
            output_dir=split_dir,
            split_seed=20260718,
            cells_per_split=3000,
        )
    if split.cell_overlap_count != 0:
        raise RuntimeError("scientific split overlap detected")

    environments = EnvironmentRegistry()
    environment = environments.get("sckg-batch-cpu")
    contracts = ToolContractRegistry(environment_registry=environments)
    profiler = AnnDataProfiler()
    profile = profiler.profile(
        split.development.path, batch_key="batch", label_key="cell_type"
    )
    requirement = RequirementSpec(
        request_id=f"phase5-scientific-{run_stamp}",
        query="Scientific pilot of Harmony and Scanorama on scIB pancreas",
        task="batch_integration",
        input_path=split.development.path,
        input_object_type="AnnData",
        batch_key="batch",
        label_key="cell_type",
        output_goal="frozen-parameter integration comparison on independent cells",
        data_access_authorized=True,
    )
    compiler = ExecutionPlanCompiler(contracts)
    executor = LocalControlledExecutor(
        approved_input_root=DATASET_ROOT,
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
    workflows = []
    loaded_contracts = []
    confidence_intervals = {}

    for tool_name, version, specs in tool_specs:
        contract = contracts.load(tool_name, version)
        loaded_contracts.append(contract)
        planning_gate = contracts.planning_gate(contract, data_profile=profile)
        if not planning_gate.allowed:
            raise RuntimeError(f"planning gate failed for {tool_name}: {planning_gate.reasons}")
        plan = compiler.compile(
            requirement=requirement,
            data_profile=profile,
            tool_contract=contract,
            environment=environment,
            execution_budget=ExecutionBudget(),
        )
        workflows.append(plan)
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
        development_batch = runner.run(
            experiment_id=f"phase5-science-{run_stamp}-{tool_name.casefold()}-development",
            configurations=configurations,
            seeds=[101, 202],
            probe=split.development,
            artifact=_artifact(split.development),
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=plan.plan_id,
        )
        development_batches.append(development_batch)
        candidates = aggregator.aggregate(batch=development_batch, contract=contract)
        development_candidates.extend(candidates)
        tool_decision = decision_engine.decide(candidates, preference="performance")
        if tool_decision.recommended_candidate_id is None:
            raise RuntimeError(f"no eligible scientific development candidate for {tool_name}")
        selected = next(
            item for item in candidates if item.candidate_id == tool_decision.recommended_candidate_id
        )
        frozen = next(
            item
            for item in configurations
            if item.configuration_hash == selected.configuration_hash
        ).model_copy(update={"frozen": True})
        evaluation_batch = runner.run(
            experiment_id=f"phase5-science-{run_stamp}-{tool_name.casefold()}-evaluation",
            configurations=[frozen],
            seeds=[split.split_seed],
            probe=split.evaluation,
            artifact=_artifact(split.evaluation),
            contract=contract,
            environment=environment,
            planning_gate=planning_gate,
            plan_id=plan.plan_id,
        )
        evaluation_batches.append(evaluation_batch)
        evaluated = aggregator.aggregate(batch=evaluation_batch, contract=contract)[0]
        evaluated = evaluated.model_copy(
            update={
                "seed_stability": {
                    **selected.seed_stability,
                    "stability_source": "scientific_development_runs",
                },
                "limitations": sorted(
                    set(
                        evaluated.limitations
                        + ["seed stability is transferred from the development split"]
                    )
                ),
            }
        )
        evaluation_candidates.append(evaluated)
        evaluation_run = evaluation_batch.execution_runs[0]
        confidence_intervals[evaluated.candidate_id] = bootstrap_integration_metrics(
            evaluation_run.artifact_paths["integrated_embedding.tsv"],
            iterations=500,
            seed=split.split_seed,
        )

    decision = decision_engine.decide(evaluation_candidates, preference="performance")
    package = ReproducibilityPackager().build_batch_integration(
        package_id=f"phase5-batch-scientific-{run_stamp}",
        requirement=requirement,
        data_profile=profile,
        development_probe=split.development,
        evaluation_probe=split.evaluation,
        workflow_plans=workflows,
        contracts=loaded_contracts,
        environment=environment,
        batches=[*development_batches, *evaluation_batches],
        candidate_evaluations=[*development_candidates, *evaluation_candidates],
        decision_result=decision,
        rerun_command="conda run -n scRNAseq python scripts/run_phase5_batch_scientific_pilot.py",
        dataset_manifest=dataset,
        split_manifest=split,
        bootstrap_intervals=confidence_intervals,
    )
    all_batches = [*development_batches, *evaluation_batches]
    runs = [item for batch in all_batches for item in batch.execution_runs]
    validations = [item for batch in all_batches for item in batch.validation_results]
    summary = {
        "phase": "Phase 5 Batch Integration scientific pilot",
        "dataset": dataset.accession,
        "dataset_cells": dataset.n_cells,
        "dataset_batches": dataset.n_batches,
        "dataset_cell_types": dataset.n_labels,
        "development_cells": split.development.n_cells,
        "evaluation_cells": split.evaluation.n_cells,
        "split_manifest_hash": split.manifest_hash,
        "cell_overlap_count": split.cell_overlap_count,
        "development_runs": sum(batch.requested_run_count for batch in development_batches),
        "evaluation_runs": sum(batch.requested_run_count for batch in evaluation_batches),
        "successful_runs": sum(item.status == "succeeded" for item in runs),
        "failed_runs": sum(item.status != "succeeded" for item in runs),
        "validations_passed": sum(item.passed for item in validations),
        "evaluation_candidates": [
            {
                "candidate_id": item.candidate_id,
                "metrics": {
                    name: metric.mean for name, metric in item.metric_summaries.items()
                },
                "bootstrap_ci": confidence_intervals[item.candidate_id],
                "runtime_seconds": item.runtime_summary.median,
                "peak_memory_mb": item.peak_memory_summary.median,
            }
            for item in evaluation_candidates
        ],
        "pareto_frontier": decision.pareto_candidate_ids,
        "recommended_candidate": decision.recommended_candidate_id,
        "package_path": package.package_path,
        "package_complete": package.complete,
        "manifest_hashes_valid": package.manifest_hashes_valid,
        "metric_authority": "scientific_pilot_metric",
        "fixed_pair_execution_gate_qualified": all(
            contracts.execution_gate(contract).allowed for contract in loaded_contracts
        ),
        "global_execution_policy": "disabled",
        "user_execution_available": False,
        "limitations": [
            "The pilot covers only the registered scIB pancreas dataset and source PCA.",
            "Batch labels represent technologies/studies and are not interchangeable with biology labels.",
            "The pilot subset contains 3000 development and 3000 independent evaluation cells.",
            "Results do not establish that either tool is universally optimal.",
        ],
    }
    summary_path = DATASET_ROOT / f"scientific_pilot_summary_{run_stamp}.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert summary["cell_overlap_count"] == 0
    assert summary["development_runs"] == 8
    assert summary["evaluation_runs"] == 2
    assert summary["successful_runs"] == 10
    assert summary["validations_passed"] == 10
    assert decision.recommended_candidate_id is not None
    assert package.complete and package.manifest_hashes_valid
    assert not any(run.user_data_used for run in runs)
    print(json.dumps(summary, indent=2, sort_keys=True))


def _artifact(split) -> QualificationArtifact:
    return QualificationArtifact(
        artifact_id=split.artifact_id,
        fixture_id=split.fixture_id,
        path=split.path,
        sha256=split.probe_hash,
        synthetic=False,
        public_dataset=True,
        user_data=False,
        accession=split.accession,
        allowlisted=True,
        expected_cells=split.n_cells,
    )


if __name__ == "__main__":
    main()
