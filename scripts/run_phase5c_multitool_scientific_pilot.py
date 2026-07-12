#!/usr/bin/env python
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from run_phase3as_scientific_pilot import (  # reuses the control-plane shim
    CONTROL_DEPENDENCY_SOURCE,
    _freeze_thresholds,
    _inject_scientific_metrics,
    _scientific_evaluations,
)

from core.execution_models import (
    ExecutionBudget,
    RequirementSpec,
    ScientificDatasetManifest,
    ScientificLabelReport,
    ScientificSplitManifest,
)
from core.tool_contract_registry import ToolContractRegistry
from data_pipeline.prepare_gse108313 import DATASET_ROOT
from engine.data_profiler import AnnDataProfiler
from engine.execution_planner import ExecutionPlanCompiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.candidate_aggregator import CandidateAggregator
from execution.environment_registry import EnvironmentRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.local_controlled_executor import LocalControlledExecutor
from execution.multitool_scientific_evaluator import (
    MultitoolScientificCandidateEvaluator,
)
from execution.reproducibility_packager import ReproducibilityPackager
from execution.scientific_dataset import (
    qualification_artifact,
    scientific_pilot_limitations,
)
from execution.scientific_evaluator import ScientificEvaluator
from execution.validators.doublet import DoubletValidator
from execution.validators.scdblfinder import ScDblFinderValidator


SOURCE_PILOT_ID = "20260711T134822920584"
SOURCE_PILOT_DIR = DATASET_ROOT / "pilot" / SOURCE_PILOT_ID
EXPECTED_SPLIT_MANIFEST_HASH = (
    "0d4e8e26fc6c770631faa1c342f014c80976a8b3587337a1d834258715c77897"
)
DEVELOPMENT_SEEDS = [701, 702]
EVALUATION_SEED = [801]


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    output_dir = DATASET_ROOT / "phase5c" / token
    output_dir.mkdir(parents=True)
    dataset_manifest, label_report, split_manifest = _load_existing_pilot()
    development_artifact = qualification_artifact(split_manifest.development)
    evaluation_artifact = qualification_artifact(split_manifest.evaluation)

    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    scrublet_contract = contracts.load("Scrublet", "0.2.3")
    scdblfinder_contract = contracts.load("scDblFinder", "1.24.0")
    scrublet_environment = environments.get(scrublet_contract.environment_id)
    scdblfinder_environment = environments.get(scdblfinder_contract.environment_id)
    development_profile = AnnDataProfiler().profile(
        Path(split_manifest.development.path)
    )
    scrublet_gate = contracts.planning_gate(
        scrublet_contract, data_profile=development_profile
    )
    scdblfinder_gate = contracts.planning_gate(
        scdblfinder_contract, data_profile=development_profile
    )
    requirement = RequirementSpec(
        request_id=f"phase5c-{token}",
        query="Frozen multi-tool scientific pilot on public GSE108313 Cell Hashing PBMC",
        input_path=dataset_manifest.h5ad_path,
        input_object_type="AnnData",
        data_access_authorized=True,
        execution_authorized=False,
        resource_budget={"max_cells": split_manifest.development.n_cells, "max_runtime_seconds": 900},
    )
    compiler = ExecutionPlanCompiler(contracts)
    budget = ExecutionBudget(
        max_initial_runs=6,
        reserved_repair_runs=0,
        reserved_validation_reruns=0,
        max_total_runs=6,
        timeout_seconds=900,
    )
    workflow_plans = {
        "Scrublet": compiler.compile(
            requirement=requirement,
            data_profile=development_profile,
            tool_contract=scrublet_contract,
            environment=scrublet_environment,
            execution_budget=budget,
        ),
        "scDblFinder": compiler.compile(
            requirement=requirement,
            data_profile=development_profile,
            tool_contract=scdblfinder_contract,
            environment=scdblfinder_environment,
            execution_budget=budget,
        ),
    }

    scrublet_config = build_configuration(
        configuration_id="scrublet-contract-default",
        parameters={},
        provenance={
            "configuration_aliases": [
                "Scrublet contract default",
                "Scrublet current scientific-pilot recommendation",
            ],
            "alias_reason": "Phase 3A-S recommended the contract-default parameter hash",
        },
        source="contract_default",
        contract=scrublet_contract,
    )
    development_rate = split_manifest.development.doublet_count / split_manifest.development.n_cells
    development_dbr = round(min(0.2, max(0.02, development_rate)), 4)
    scdblfinder_configs = [
        build_configuration(
            configuration_id="scdblfinder-contract-default",
            parameters={},
            provenance={},
            source="contract_default",
            contract=scdblfinder_contract,
        ),
        build_configuration(
            configuration_id="scdblfinder-development-derived",
            parameters={"dbr": development_dbr},
            provenance={
                "dbr": {
                    "origin": "development_label_prevalence",
                    "development_split_hash": split_manifest.development.probe_hash,
                    "raw_prevalence": development_rate,
                    "clipped_to_contract_maximum": development_dbr,
                }
            },
            source="development_probe_search",
            contract=scdblfinder_contract,
        ),
    ]

    executor = LocalControlledExecutor(
        run_root=PROJECT_ROOT / ".sckg_exec" / "runs" / f"phase5c-{token}",
        approved_input_root=DATASET_ROOT,
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
    development_batches = [
        scrublet_runner.run(
            experiment_id=f"phase5c-dev-scrublet-{token}",
            configurations=[scrublet_config],
            seeds=DEVELOPMENT_SEEDS,
            probe=split_manifest.development,
            artifact=development_artifact,
            contract=scrublet_contract,
            environment=scrublet_environment,
            planning_gate=scrublet_gate,
            plan_id=workflow_plans["Scrublet"].plan_id,
        ),
        scdblfinder_runner.run(
            experiment_id=f"phase5c-dev-scdblfinder-{token}",
            configurations=scdblfinder_configs,
            seeds=DEVELOPMENT_SEEDS,
            probe=split_manifest.development,
            artifact=development_artifact,
            contract=scdblfinder_contract,
            environment=scdblfinder_environment,
            planning_gate=scdblfinder_gate,
            plan_id=workflow_plans["scDblFinder"].plan_id,
        ),
    ]

    evaluator = ScientificEvaluator()
    prediction_dir = output_dir / "predictions"
    development_results = []
    development_predictions = []
    development_candidates = []
    aggregator = CandidateAggregator()
    for index, (batch, contract) in enumerate(
        zip(development_batches, [scrublet_contract, scdblfinder_contract])
    ):
        results, predictions = _scientific_evaluations(
            batch=batch,
            evaluator=evaluator,
            prediction_dir=prediction_dir,
            split_role="development",
            thresholds={},
            bootstrap_iterations=100,
        )
        scientific_batch = _inject_scientific_metrics(batch, results)
        development_results.extend(results)
        development_predictions.extend(predictions)
        development_candidates.extend(
            aggregator.aggregate(batch=scientific_batch, contract=contract)
        )
        development_batches[index] = scientific_batch

    thresholds = {}
    for batch, contract_results in (
        (
            development_batches[0],
            [item for item in development_results if item.run_id.startswith("phase5c-dev-scrublet")],
        ),
        (
            development_batches[1],
            [item for item in development_results if item.run_id.startswith("phase5c-dev-scdblfinder")],
        ),
    ):
        thresholds.update(_freeze_thresholds(batch, contract_results))

    frozen_scrublet = scrublet_config.model_copy(update={"frozen": True})
    frozen_scdblfinder = [item.model_copy(update={"frozen": True}) for item in scdblfinder_configs]
    evaluation_batches = [
        scrublet_runner.run(
            experiment_id=f"phase5c-eval-scrublet-{token}",
            configurations=[frozen_scrublet],
            seeds=EVALUATION_SEED,
            probe=split_manifest.evaluation,
            artifact=evaluation_artifact,
            contract=scrublet_contract,
            environment=scrublet_environment,
            planning_gate=scrublet_gate,
            plan_id=workflow_plans["Scrublet"].plan_id,
        ),
        scdblfinder_runner.run(
            experiment_id=f"phase5c-eval-scdblfinder-{token}",
            configurations=frozen_scdblfinder,
            seeds=EVALUATION_SEED,
            probe=split_manifest.evaluation,
            artifact=evaluation_artifact,
            contract=scdblfinder_contract,
            environment=scdblfinder_environment,
            planning_gate=scdblfinder_gate,
            plan_id=workflow_plans["scDblFinder"].plan_id,
        ),
    ]
    evaluation_results = []
    evaluation_predictions = []
    raw_evaluation_candidates = []
    for index, (batch, contract) in enumerate(
        zip(evaluation_batches, [scrublet_contract, scdblfinder_contract])
    ):
        results, predictions = _scientific_evaluations(
            batch=batch,
            evaluator=evaluator,
            prediction_dir=prediction_dir,
            split_role="evaluation",
            thresholds=thresholds,
            bootstrap_iterations=500,
        )
        scientific_batch = _inject_scientific_metrics(batch, results)
        evaluation_batches[index] = scientific_batch
        evaluation_results.extend(results)
        evaluation_predictions.extend(predictions)
        raw_evaluation_candidates.extend(
            aggregator.aggregate(batch=scientific_batch, contract=contract)
        )

    final_candidates = MultitoolScientificCandidateEvaluator().finalize(
        development_candidates=development_candidates,
        evaluation_candidates=raw_evaluation_candidates,
    )
    decision = ParetoDecisionEngine().decide(
        final_candidates, preference="performance"
    )
    qualified_contracts = [
        scrublet_contract.model_copy(
            update={"scientific_validation_status": "scientific_pilot"}
        ),
        scdblfinder_contract.model_copy(
            update={"scientific_validation_status": "scientific_pilot"}
        ),
    ]
    configuration_catalog = _configuration_catalog(
        scrublet_config=scrublet_config,
        scdblfinder_configs=scdblfinder_configs,
        thresholds=thresholds,
        split_manifest=split_manifest,
    )
    package = ReproducibilityPackager().build_multitool_scientific_pilot(
        package_id=f"phase5c-gse108313-{token}",
        requirement=requirement,
        data_profile=development_profile,
        workflow_plans=workflow_plans,
        contracts=qualified_contracts,
        environments=[scrublet_environment, scdblfinder_environment],
        dataset_manifest=dataset_manifest,
        label_report=label_report,
        exclusion_report_path=SOURCE_PILOT_DIR / "exclusion_report.tsv",
        split_manifest=split_manifest,
        configuration_catalog=configuration_catalog,
        batches=[*development_batches, *evaluation_batches],
        scientific_evaluations=[*development_results, *evaluation_results],
        prediction_paths=[*development_predictions, *evaluation_predictions],
        candidate_evaluations=final_candidates,
        decision_result=decision,
        rerun_command="conda run -n scRNAseq python scripts/run_phase5c_multitool_scientific_pilot.py",
    )

    all_batches = [*development_batches, *evaluation_batches]
    all_runs = [run for batch in all_batches for run in batch.execution_runs]
    evaluation_runs = [run for batch in evaluation_batches for run in batch.execution_runs]
    expected_barcodes, expected_labels = _expected_evaluation_rows(
        Path(split_manifest.evaluation.path)
    )
    prediction_alignment = all(
        _prediction_rows(path) == (expected_barcodes, expected_labels)
        for path in evaluation_predictions
    )
    checks = {
        "existing_dataset_reused": dataset_manifest.accession == "GSE108313",
        "existing_split_hash_unchanged": split_manifest.manifest_hash
        == EXPECTED_SPLIT_MANIFEST_HASH,
        "evaluation_barcode_hash_unchanged": split_manifest.evaluation.barcode_hash
        == "86d9a030f4e4af76ad3ff7e01c0c17994bf53954ce0e66ed99ca25c265c0024a",
        "evaluation_input_hash_identical": len({run.input_hash for run in evaluation_runs})
        == 1
        and evaluation_runs[0].input_hash == split_manifest.evaluation.probe_hash,
        "evaluation_barcodes_and_labels_identical": prediction_alignment,
        "evaluation_configurations_frozen": all(
            item.frozen for item in [frozen_scrublet, *frozen_scdblfinder]
        ),
        "all_runs_succeeded": bool(all_runs)
        and all(run.status == "succeeded" for run in all_runs),
        "all_runs_local_controlled_executor": all(
            batch.all_runs_use_local_controlled_executor for batch in all_batches
        ),
        "all_metrics_scientific": all(
            item.metric_authority == "scientific_pilot_metric"
            for item in [*development_results, *evaluation_results, *final_candidates]
        ),
        "all_evaluation_bootstrap_500": all(
            all(interval.bootstrap_iterations == 500 for interval in item.bootstrap_ci.values())
            for item in evaluation_results
        ),
        "three_unique_evaluation_candidates": len(final_candidates) == 3,
        "all_candidates_eligible": all(
            item.eligible_for_decision for item in final_candidates
        ),
        "cross_tool_pareto": decision.decision_scope
        == "multitool_doublet_detection",
        "raw_scores_not_compared": any(
            "raw scores are never compared directly" in item
            for item in decision.limitations
        ),
        "package_complete": package.complete and package.manifest_hashes_valid,
        "no_user_data": all(not run.user_data_used for run in all_runs),
        "enabled_for_execution_false": not any(
            [
                scrublet_contract.enabled_for_execution,
                scdblfinder_contract.enabled_for_execution,
                scrublet_environment.enabled_for_execution,
                scdblfinder_environment.enabled_for_execution,
            ]
        ),
    }
    evaluation_by_candidate = {
        item.candidate_id: _evaluation_for_candidate(
            item, evaluation_results, evaluation_batches
        ).model_dump(mode="json")
        for item in final_candidates
    }
    scrublet_result = evaluation_by_candidate[
        next(
            item.candidate_id
            for item in final_candidates
            if item.tool_name == "Scrublet"
        )
    ]
    summary = {
        "ok": all(checks.values()),
        "phase": "Phase 5C multi-tool scientific pilot",
        "control_dependency_source": CONTROL_DEPENDENCY_SOURCE,
        "checks": checks,
        "dataset_manifest_path": str(DATASET_ROOT / "dataset_manifest.json"),
        "source_pilot_id": SOURCE_PILOT_ID,
        "split": split_manifest.model_dump(mode="json"),
        "configuration_catalog": configuration_catalog,
        "scrublet_requested_aliases": {
            "contract_default": scrublet_result,
            "current_scientific_pilot_recommended": scrublet_result,
            "same_parameter_hash": True,
        },
        "evaluation_metrics": evaluation_by_candidate,
        "candidates": [item.model_dump(mode="json") for item in final_candidates],
        "decision": decision.model_dump(mode="json"),
        "runs": {
            "Scrublet": _run_summary(all_runs, "Scrublet"),
            "scDblFinder": _run_summary(all_runs, "scDblFinder"),
            "total": len(all_runs),
        },
        "package": package.model_dump(mode="json"),
        "enabled_for_execution": {
            "Scrublet_contract": scrublet_contract.enabled_for_execution,
            "scDblFinder_contract": scdblfinder_contract.enabled_for_execution,
            "scRNAseq_environment": scrublet_environment.enabled_for_execution,
            "scDblFinder_R_environment": scdblfinder_environment.enabled_for_execution,
        },
        "limitations": label_report.limitations,
    }
    (output_dir / "phase5c_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _load_existing_pilot():
    dataset_manifest = ScientificDatasetManifest.model_validate_json(
        (DATASET_ROOT / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    label_report = ScientificLabelReport.model_validate_json(
        (SOURCE_PILOT_DIR / "label_report.json").read_text(encoding="utf-8")
    ).model_copy(update={"limitations": scientific_pilot_limitations()})
    split_manifest = ScientificSplitManifest.model_validate_json(
        (SOURCE_PILOT_DIR / "splits" / "split_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if split_manifest.manifest_hash != EXPECTED_SPLIT_MANIFEST_HASH:
        raise ValueError("existing split manifest hash changed")
    for split in (split_manifest.development, split_manifest.evaluation):
        path = Path(split.path)
        if _sha256(path) != split.probe_hash:
            raise ValueError(f"existing {split.split_role} artifact hash changed")
        barcodes, _ = _expected_evaluation_rows(path)
        barcode_hash = hashlib.sha256(
            "\n".join(sorted(barcodes)).encode("utf-8")
        ).hexdigest()
        if barcode_hash != split.barcode_hash:
            raise ValueError(f"existing {split.split_role} barcode hash changed")
    return dataset_manifest, label_report, split_manifest


def _configuration_catalog(*, scrublet_config, scdblfinder_configs, thresholds, split_manifest):
    return [
        {
            "labels": [
                "Scrublet contract default",
                "Scrublet current scientific-pilot recommended configuration",
            ],
            "configuration": scrublet_config.model_copy(update={"frozen": True}).model_dump(mode="json"),
            "frozen_threshold": thresholds[scrublet_config.configuration_hash],
            "deduplicated_execution": True,
            "deduplication_reason": "Both requested labels resolve to the Phase 3A-S recommended contract-default hash.",
        },
        *[
            {
                "labels": [item.configuration_id],
                "configuration": item.model_copy(update={"frozen": True}).model_dump(mode="json"),
                "frozen_threshold": thresholds[item.configuration_hash],
                "deduplicated_execution": False,
                "development_split_hash": split_manifest.development.probe_hash,
            }
            for item in scdblfinder_configs
        ],
    ]


def _evaluation_for_candidate(candidate, results, batches):
    for batch in batches:
        records = {record.run_id: record for record in batch.run_records}
        for result in results:
            record = records.get(result.run_id)
            if record and record.configuration_hash == candidate.configuration_hash:
                return result
    raise KeyError(candidate.candidate_id)


def _expected_evaluation_rows(path: Path) -> tuple[list[str], list[bool]]:
    import anndata as ad

    adata = ad.read_h5ad(path, backed="r")
    barcodes = [str(item) for item in adata.obs_names]
    labels = [bool(item) for item in adata.obs["ground_truth_doublet"]]
    adata.file.close()
    return barcodes, labels


def _prediction_rows(path: Path) -> tuple[list[str], list[bool]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return (
        [row["obs_id"] for row in rows],
        [row["gold_doublet"].casefold() == "true" for row in rows],
    )


def _run_summary(runs, tool_name):
    selected = [run for run in runs if run.tool_name == tool_name]
    succeeded = sum(run.status == "succeeded" for run in selected)
    return {
        "actual": len(selected),
        "succeeded": succeeded,
        "failed": len(selected) - succeeded,
        "success_rate": succeeded / len(selected) if selected else 0.0,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
