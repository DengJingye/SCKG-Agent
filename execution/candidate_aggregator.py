from __future__ import annotations

import statistics
from collections import defaultdict

from core.execution_models import (
    CandidateEvaluation,
    ConfigurationSpec,
    ExecutionRun,
    ExperimentBatchResult,
    MetricSummary,
    ToolContract,
    ValidationResult,
)
from execution.experiment_runner import configuration_hash


class CandidateAggregator:
    """Aggregate validated runs; a single validation can never become a decision input."""

    def aggregate(
        self,
        *,
        batch: ExperimentBatchResult,
        contract: ToolContract,
    ) -> list[CandidateEvaluation]:
        runs_by_id = _deduplicate_runs(batch.execution_runs)
        validations = {item.run_id: item for item in batch.validation_results}
        records_by_configuration = defaultdict(list)
        for record in batch.run_records:
            records_by_configuration[record.configuration_hash].append(record)

        results: list[CandidateEvaluation] = []
        for configuration in batch.configurations:
            records = records_by_configuration.get(configuration.configuration_hash, [])
            results.append(
                self._aggregate_configuration(
                    configuration=configuration,
                    records=records,
                    runs_by_id=runs_by_id,
                    validations=validations,
                    contract=contract,
                    split_role=batch.split_role,
                    duplicate_run_ids=_duplicate_run_ids(batch.execution_runs),
                )
            )
        return results

    def _aggregate_configuration(
        self,
        *,
        configuration: ConfigurationSpec,
        records,
        runs_by_id: dict[str, ExecutionRun],
        validations: dict[str, ValidationResult],
        contract: ToolContract,
        split_role: str,
        duplicate_run_ids: list[str],
    ) -> CandidateEvaluation:
        run_ids = list(dict.fromkeys(record.run_id for record in records))
        duplicate_run_ids = [
            run_id for run_id in duplicate_run_ids if run_id in run_ids
        ]
        successful: list[str] = []
        failed: list[str] = []
        scientific = any(
            validation.metric_authority == "scientific_pilot_metric"
            for validation in validations.values()
            if validation.run_id in run_ids
        )
        limitations: list[str] = [
            (
                "Scientific pilot metrics are limited to GSE108313 and the recorded preprocessing."
                if scientific
                else "Synthetic engineering metrics do not establish biological performance."
            )
        ]
        if contract.tool_name.casefold() == "scdblfinder":
            limitations.append(
                "scDblFinder requires a separately qualified R/Bioconductor environment."
            )
        metric_values: dict[str, list[float]] = defaultdict(list)
        runtimes: list[float] = []
        memories: list[float] = []
        hash_consistent = True
        for run_id in run_ids:
            run = runs_by_id.get(run_id)
            validation = validations.get(run_id)
            if run is None or validation is None:
                failed.append(run_id)
                limitations.append(f"missing_run_or_validation:{run_id}")
                continue
            observed_hash = configuration_hash(
                contract.tool_name, contract.tool_version, run.parameters
            )
            if observed_hash != configuration.configuration_hash:
                hash_consistent = False
                failed.append(run_id)
                limitations.append(f"configuration_hash_mismatch:{run_id}")
                continue
            runtimes.append(run.runtime_seconds)
            if run.peak_memory_mb is not None:
                memories.append(run.peak_memory_mb)
            artifacts_complete = bool(
                validation.artifact_checks.get("required_artifacts_present", False)
            )
            if run.status == "succeeded" and validation.passed and artifacts_complete:
                successful.append(run_id)
                for name, value in validation.task_metrics.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        metric_values[name].append(float(value))
            else:
                failed.append(run_id)

        total = len(run_ids)
        success_rate = len(successful) / total if total else 0.0
        f1_metric = (
            "scientific_pilot_f1" if scientific else "synthetic_engineering_f1"
        )
        f1_values = metric_values.get(f1_metric, [])
        f1_std = statistics.pstdev(f1_values) if len(f1_values) > 1 else None
        seed_stability = {
            "successful_seed_count": len(successful),
            "requested_seed_count": total,
            f"{f1_metric}_standard_deviation": f1_std,
            "stability_score": max(0.0, 1.0 - f1_std) if f1_std is not None else 0.0,
        }
        if len(successful) < 2:
            limitations.append("fewer_than_two_successful_seeds")
        if failed:
            limitations.append("partial_or_complete_seed_failure")
        blocked_errors = {
            run.error_type
            for run_id in run_ids
            if (run := runs_by_id.get(run_id)) is not None and run.status == "blocked"
        }
        if blocked_errors:
            limitations.extend(
                f"blocked_execution:{item}" for item in sorted(blocked_errors) if item
            )
        if duplicate_run_ids:
            limitations.append("duplicate_runs_ignored")
        eligible = (
            total >= 2
            and len(successful) >= 2
            and success_rate >= 0.5
            and hash_consistent
            and bool(f1_values)
        )
        return CandidateEvaluation(
            candidate_id=f"{contract.tool_name}:{contract.tool_version}:{configuration.configuration_hash[:16]}",
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            configuration_hash=configuration.configuration_hash,
            parameters=configuration.parameters,
            parameter_provenance=configuration.parameter_provenance,
            split_role=split_role,
            run_ids=run_ids,
            successful_run_ids=successful,
            failed_run_ids=list(dict.fromkeys(failed)),
            duplicate_run_ids=duplicate_run_ids,
            metric_summaries={
                name: _summary(values) for name, values in sorted(metric_values.items())
            },
            seed_stability=seed_stability,
            runtime_summary=_summary(runtimes),
            peak_memory_summary=_summary(memories),
            execution_success_rate=success_rate,
            limitations=sorted(set(limitations)),
            eligible_for_decision=eligible,
            metric_authority=(
                "scientific_pilot_metric" if scientific else "synthetic_engineering_metric"
            ),
        )


def _summary(values: list[float]) -> MetricSummary:
    if not values:
        return MetricSummary(count=0)
    return MetricSummary(
        count=len(values),
        mean=statistics.fmean(values),
        median=statistics.median(values),
        standard_deviation=statistics.pstdev(values) if len(values) > 1 else 0.0,
        minimum=min(values),
        maximum=max(values),
    )


def _deduplicate_runs(runs: list[ExecutionRun]) -> dict[str, ExecutionRun]:
    result: dict[str, ExecutionRun] = {}
    for run in runs:
        result.setdefault(run.run_id, run)
    return result


def _duplicate_run_ids(runs: list[ExecutionRun]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for run in runs:
        if run.run_id in seen:
            duplicates.add(run.run_id)
        seen.add(run.run_id)
    return sorted(duplicates)
