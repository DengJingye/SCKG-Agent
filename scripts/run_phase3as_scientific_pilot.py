#!/usr/bin/env python
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
from collections import defaultdict
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
            prefix="sckg_phase3as_control_deps_"
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
from data_pipeline.prepare_gse108313 import DATASET_ROOT, prepare_gse108313
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.reproducibility_packager import ReproducibilityPackager
from execution.scientific_dataset import GSE108313Dataset, qualification_artifact
from execution.scientific_evaluator import ScientificEvaluator


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    dataset_manifest = prepare_gse108313(dataset_root=DATASET_ROOT)
    pilot_dir = DATASET_ROOT / "pilot" / token
    pilot_dir.mkdir(parents=True)
    labeled_path, label_report = GSE108313Dataset().label_and_filter(
        input_h5ad=Path(dataset_manifest.h5ad_path),
        output_h5ad=pilot_dir / "GSE108313_labeled.h5ad",
        exclusion_path=pilot_dir / "exclusion_report.tsv",
        report_path=pilot_dir / "label_report.json",
    )
    split_manifest = GSE108313Dataset().split(
        labeled_h5ad=labeled_path,
        output_dir=pilot_dir / "splits",
    )
    development_artifact = qualification_artifact(split_manifest.development)
    evaluation_artifact = qualification_artifact(split_manifest.evaluation)

    environments = EnvironmentRegistry()
    environment = environments.get("scRNAseq")
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scrublet", "0.2.3")
    development_profile = AnnDataProfiler().profile(
        Path(split_manifest.development.path)
    )
    planning_gate = contracts.planning_gate(contract, data_profile=development_profile)
    execution_gate = contracts.execution_gate(contract)
    requirement = RequirementSpec(
        request_id=f"phase3as-{token}",
        query="Scientific pilot of Scrublet on public Cell Hashing PBMC GSE108313",
        input_path=dataset_manifest.h5ad_path,
        input_object_type="AnnData",
        data_access_authorized=True,
        execution_authorized=False,
    )
    workflow_plan = ExecutionPlanCompiler(contracts).compile(
        requirement=requirement,
        data_profile=development_profile,
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

    observed_rate = label_report.doublet_count / (
        label_report.singlet_count + label_report.doublet_count
    )
    prevalence_rate = round(min(0.15, max(0.02, observed_rate)), 4)
    configurations = [
        build_configuration(
            configuration_id="contract-default",
            parameters={},
            provenance={},
            source="contract_default",
            contract=contract,
        ),
        build_configuration(
            configuration_id="phase3ae-recommended",
            parameters={
                "expected_doublet_rate": 0.12,
                "min_counts": 1,
                "min_cells": 1,
                "min_gene_variability_pctl": 0.0,
                "n_prin_comps": 10,
                "use_approx_neighbors": False,
            },
            provenance={
                "expected_doublet_rate": {
                    "origin": "development_probe_search",
                    "source": "Phase 3A-E frozen recommendation",
                }
            },
            source="development_probe_search",
            contract=contract,
        ),
        build_configuration(
            configuration_id="development-prevalence",
            parameters={
                "expected_doublet_rate": prevalence_rate,
                "n_prin_comps": 40,
            },
            provenance={
                "expected_doublet_rate": {
                    "origin": "development_probe_search",
                    "source": "GSE108313 development label prevalence clipped to contract search range",
                },
                "n_prin_comps": {
                    "origin": "development_probe_search",
                    "source": "contract searchable range",
                },
            },
            source="development_probe_search",
            contract=contract,
        ),
    ]
    executor = LocalControlledExecutor(
        run_root=PROJECT_ROOT / ".sckg_exec" / "runs" / f"phase3as-{token}",
        approved_input_root=DATASET_ROOT,
        environment_registry=environments,
    )
    runner = ExperimentRunner(executor=executor, contract_registry=contracts)
    development_batch = runner.run(
        experiment_id=f"scientific-development-{token}",
        configurations=configurations,
        seeds=[701, 702],
        probe=split_manifest.development,
        artifact=development_artifact,
        contract=contract,
        environment=environment,
        planning_gate=planning_gate,
        plan_id=workflow_plan.plan_id,
    )

    evaluator = ScientificEvaluator()
    prediction_dir = pilot_dir / "predictions"
    development_scientific, development_predictions = _scientific_evaluations(
        batch=development_batch,
        evaluator=evaluator,
        prediction_dir=prediction_dir,
        split_role="development",
        thresholds={},
        bootstrap_iterations=100,
    )
    development_batch = _inject_scientific_metrics(
        development_batch, development_scientific
    )
    aggregator = CandidateAggregator()
    development_candidates = aggregator.aggregate(
        batch=development_batch, contract=contract
    )
    decision = ParetoDecisionEngine().decide(
        development_candidates, preference="performance"
    )
    thresholds = _freeze_thresholds(development_batch, development_scientific)
    frozen_configurations = [item.model_copy(update={"frozen": True}) for item in configurations]

    evaluation_batch = runner.run(
        experiment_id=f"scientific-evaluation-{token}",
        configurations=frozen_configurations,
        seeds=[801],
        probe=split_manifest.evaluation,
        artifact=evaluation_artifact,
        contract=contract,
        environment=environment,
        planning_gate=planning_gate,
        plan_id=workflow_plan.plan_id,
    )
    evaluation_scientific, evaluation_predictions = _scientific_evaluations(
        batch=evaluation_batch,
        evaluator=evaluator,
        prediction_dir=prediction_dir,
        split_role="evaluation",
        thresholds=thresholds,
        bootstrap_iterations=500,
    )
    evaluation_batch = _inject_scientific_metrics(
        evaluation_batch, evaluation_scientific
    )
    evaluation_candidates = aggregator.aggregate(
        batch=evaluation_batch, contract=contract
    )

    frozen_snapshot = [
        {
            "configuration": item.model_dump(mode="json"),
            "frozen_threshold": thresholds[item.configuration_hash],
            "selected_on_development": (
                decision.recommended_candidate_id is not None
                and decision.recommended_candidate_id.endswith(item.configuration_hash[:16])
            ),
        }
        for item in frozen_configurations
    ]
    package = ReproducibilityPackager().build_scientific_pilot(
        package_id=f"phase3as-gse108313-{token}",
        requirement=requirement,
        data_profile=development_profile,
        workflow_plan=workflow_plan,
        contract=contract,
        environment=environment,
        dataset_manifest=dataset_manifest,
        label_report=label_report,
        exclusion_report_path=pilot_dir / "exclusion_report.tsv",
        split_manifest=split_manifest,
        frozen_configurations=frozen_snapshot,
        batches=[development_batch, evaluation_batch],
        scientific_evaluations=[
            *development_scientific,
            *evaluation_scientific,
        ],
        prediction_paths=[*development_predictions, *evaluation_predictions],
        candidate_evaluations=[
            *development_candidates,
            *evaluation_candidates,
        ],
        decision_result=decision,
        rerun_command="conda run -n scRNAseq python scripts/run_phase3as_scientific_pilot.py",
    )

    all_runs = [*development_batch.execution_runs, *evaluation_batch.execution_runs]
    evaluation_by_config = {
        _configuration_id(evaluation_batch, result.run_id): result
        for result in evaluation_scientific
    }
    checks = {
        "dataset_accession_correct": dataset_manifest.accession == "GSE108313",
        "no_fastq": dataset_manifest.fastq_downloaded is False,
        "raw_counts_preserved": dataset_manifest.raw_counts_preserved,
        "barcode_overlap_zero": split_manifest.barcode_overlap_count == 0,
        "evaluation_parameters_frozen": all(item.frozen for item in frozen_configurations),
        "three_evaluation_configurations": len(evaluation_scientific) == 3,
        "all_runs_succeeded": bool(all_runs)
        and all(run.status == "succeeded" for run in all_runs),
        "all_runs_scientific_pilot": all(
            run.execution_purpose == "scientific_pilot" for run in all_runs
        ),
        "user_data_used_false": all(not run.user_data_used for run in all_runs),
        "package_complete": package.complete,
        "manifest_hashes_valid": package.manifest_hashes_valid,
        "contract_execution_disabled": contract.enabled_for_execution is False,
        "environment_execution_disabled": environment.enabled_for_execution is False,
        "execution_gate_closed": execution_gate.allowed is False,
    }
    summary = {
        "ok": all(checks.values()),
        "phase": "Phase 3A-S scientific pilot",
        "control_dependency_source": CONTROL_DEPENDENCY_SOURCE,
        "checks": checks,
        "dataset": dataset_manifest.model_dump(mode="json"),
        "labels": label_report.model_dump(mode="json"),
        "split": split_manifest.model_dump(mode="json"),
        "development_candidates": [
            item.model_dump(mode="json") for item in development_candidates
        ],
        "frozen_thresholds": thresholds,
        "evaluation_metrics": {
            config_id: result.model_dump(mode="json")
            for config_id, result in evaluation_by_config.items()
        },
        "decision": decision.model_dump(mode="json"),
        "runs": {
            "success": sum(run.status == "succeeded" for run in all_runs),
            "failed": sum(run.status != "succeeded" for run in all_runs),
            "total": len(all_runs),
        },
        "package": package.model_dump(mode="json"),
        "enabled_for_execution": {
            "contract": contract.enabled_for_execution,
            "environment": environment.enabled_for_execution,
        },
        "limitations": label_report.limitations,
    }
    (pilot_dir / "scientific_pilot_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _scientific_evaluations(
    *,
    batch,
    evaluator,
    prediction_dir,
    split_role,
    thresholds,
    bootstrap_iterations,
):
    records = {record.run_id: record for record in batch.run_records}
    results = []
    predictions = []
    for run in batch.execution_runs:
        record = records[run.run_id]
        prediction_path = prediction_dir / f"{run.run_id}.tsv"
        result = evaluator.evaluate(
            run=run,
            configuration_hash=record.configuration_hash,
            split_role=split_role,
            frozen_threshold=thresholds.get(record.configuration_hash),
            bootstrap_iterations=bootstrap_iterations,
            predictions_output=prediction_path,
        )
        results.append(result)
        predictions.append(prediction_path)
    return results, predictions


def _inject_scientific_metrics(batch, scientific_results):
    by_run = {item.run_id: item for item in scientific_results}
    validations = []
    for validation in batch.validation_results:
        scientific = by_run.get(validation.run_id)
        if scientific is None:
            validations.append(validation)
            continue
        metrics = {
            f"scientific_pilot_{name}": value
            for name, value in scientific.metrics.items()
        }
        validations.append(
            validation.model_copy(
                update={
                    "task_metrics": metrics,
                    "metric_authority": "scientific_pilot_metric",
                }
            )
        )
    return batch.model_copy(update={"validation_results": validations})


def _freeze_thresholds(batch, scientific_results):
    records = {record.run_id: record for record in batch.run_records}
    values = defaultdict(list)
    for result in scientific_results:
        values[records[result.run_id].configuration_hash].append(result.threshold)
    return {
        configuration_hash: float(statistics.median(thresholds))
        for configuration_hash, thresholds in values.items()
    }


def _configuration_id(batch, run_id):
    return next(record.configuration_id for record in batch.run_records if record.run_id == run_id)


if __name__ == "__main__":
    raise SystemExit(main())
