from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from core.execution_models import (
    ExecutionRun,
    ExperimentBatchResult,
    ExperimentRunRecord,
    ValidationResult,
)


class DeterministicFailureExperimentRunner:
    """Test-only runner with deterministic failures; never registered as a wrapper."""

    def __init__(self, root: Path, scenario: str) -> None:
        self.root = Path(root)
        self.scenario = scenario
        self.calls: dict[tuple[str, int], int] = {}

    def run(
        self,
        *,
        experiment_id,
        configurations,
        seeds,
        probe,
        artifact,
        contract,
        environment,
        planning_gate,
        plan_id,
    ):
        del environment, planning_gate
        configurations = list(configurations)
        seeds = list(seeds)
        runs = []
        validations = []
        records = []
        for configuration in configurations:
            for seed in seeds:
                run_id = f"{experiment_id}-{configuration.configuration_id}-seed-{seed}"
                key = (configuration.configuration_hash, seed)
                call_index = self.calls.get(key, 0)
                self.calls[key] = call_index + 1
                failed, error_type, failure_code, stderr = self._failure(
                    configuration=configuration,
                    probe=probe,
                    call_index=call_index,
                )
                run_dir = self.root / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                stdout_path = run_dir / "stdout.log"
                stderr_path = run_dir / "stderr.log"
                stdout_path.write_text("deterministic test runner\n", encoding="utf-8")
                stderr_path.write_text(stderr, encoding="utf-8")
                now = datetime.now(timezone.utc)
                parameters = {**configuration.parameters, "random_state": seed}
                artifact_hash = hashlib.sha256(run_id.encode()).hexdigest()
                run = ExecutionRun(
                    request_id=f"request-{run_id}",
                    run_id=run_id,
                    trace_id=f"trace-{experiment_id}",
                    plan_id=plan_id,
                    step_id="run-scrublet-configuration",
                    wrapper_id=contract.wrapper_id,
                    tool_name=contract.tool_name,
                    tool_version=contract.tool_version,
                    environment_id=contract.environment_id,
                    command_argv_redacted=["python", "-m", "test-only-wrapper"],
                    parameters=parameters,
                    parameter_provenance=configuration.parameter_provenance,
                    input_hash=artifact.sha256,
                    start_time=now,
                    end_time=now,
                    runtime_seconds=1.0,
                    peak_memory_mb=64.0,
                    exit_code=1 if failed else 0,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    artifact_paths={"doublet_results.tsv": str(run_dir / "result.tsv")},
                    artifact_hashes={"doublet_results.tsv": artifact_hash},
                    status="failed" if failed else "succeeded",
                    error_type=error_type,
                    error_message=failure_code if failed else None,
                    fixture_id=artifact.fixture_id,
                    synthetic_fixture=artifact.synthetic,
                    public_dataset=artifact.public_dataset,
                    user_data_used=False,
                    execution_purpose=(
                        "scientific_pilot" if artifact.public_dataset else "synthetic_qualification"
                    ),
                )
                validation = ValidationResult(
                    validation_id=f"validation-{run_id}",
                    run_id=run_id,
                    passed=not failed,
                    artifact_checks={
                        "required_artifacts_present": not failed
                        or failure_code != "required_artifact_missing",
                        "artifact_hashes_valid": failure_code != "artifact_hash_mismatch",
                    },
                    task_metrics=(
                        {
                            "synthetic_engineering_precision": 0.75,
                            "synthetic_engineering_recall": 0.70,
                            "synthetic_engineering_f1": 0.72,
                        }
                        if not failed
                        else {}
                    ),
                    resource_metrics={"runtime_seconds": 1.0, "peak_memory_mb": 64.0},
                    failures=[failure_code] if failed else [],
                    eligible_for_candidate_aggregation=not failed,
                )
                runs.append(run)
                validations.append(validation)
                records.append(
                    ExperimentRunRecord(
                        run_id=run_id,
                        configuration_id=configuration.configuration_id,
                        configuration_hash=configuration.configuration_hash,
                        seed=seed,
                        split_role=probe.split_role,
                        probe_hash=probe.probe_hash,
                        parameters=parameters,
                        parameter_provenance=configuration.parameter_provenance,
                        run_status=run.status,
                        validation_id=validation.validation_id,
                        validation_passed=validation.passed,
                        runtime_seconds=run.runtime_seconds,
                        peak_memory_mb=run.peak_memory_mb,
                    )
                )
        return ExperimentBatchResult(
            experiment_id=experiment_id,
            split_role=probe.split_role,
            probe_hash=probe.probe_hash,
            configurations=configurations,
            execution_runs=runs,
            validation_results=validations,
            run_records=records,
            requested_run_count=len(runs),
            completed_run_count=len(runs),
        )

    def _failure(self, *, configuration, probe, call_index):
        if self.scenario == "invalid_n_prin_comps":
            failed = int(configuration.parameters["n_prin_comps"]) > 10
            return (
                failed,
                "wrapper_exit_nonzero" if failed else None,
                "execution_not_successful" if failed else "",
                "ValueError: n_prin_comps exceeds valid n_components\n" if failed else "",
            )
        if self.scenario == "timeout":
            failed = probe.n_probe_cells > 12
            return (
                failed,
                "timeout" if failed else None,
                "execution_not_successful" if failed else "",
                "wrapper timeout\n" if failed else "",
            )
        if self.scenario == "transient":
            failed = call_index == 0
            return (
                failed,
                "wrapper_exit_nonzero" if failed else None,
                "execution_not_successful" if failed else "",
                "temporary worker failure\n" if failed else "",
            )
        if self.scenario == "hash_mismatch":
            return True, "wrapper_exit_nonzero", "artifact_hash_mismatch", "hash mismatch\n"
        if self.scenario == "partial":
            failed = "fail" in configuration.configuration_id
            return (
                failed,
                "permanent_failure" if failed else None,
                "execution_not_successful" if failed else "",
                "ordinary permanent candidate failure\n" if failed else "",
            )
        if self.scenario == "all_fail":
            return True, "permanent_failure", "execution_not_successful", "ordinary failure\n"
        return False, None, "", ""
