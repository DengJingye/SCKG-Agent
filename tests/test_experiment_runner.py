from datetime import datetime, timezone

import pytest

from core.execution_models import ExecutionRun, ValidationResult
from core.tool_contract_registry import ToolContractRegistry
from execution.experiment_runner import ExperimentRunner, build_configuration
from execution.probe_builder import ProbeBuilder
from tests.fixtures.anndata_factory import write_phase1_fixtures
from tests.qualification_helpers import build_qualification_case


class RecordingExecutor:
    def __init__(self, fail_seed=None):
        self.requests = []
        self.fail_seed = fail_seed

    def execute(self, *, request, artifact, contract, router_decision):
        del router_decision
        self.requests.append(request)
        now = datetime.now(timezone.utc)
        failed = request.parameters["random_state"] == self.fail_seed
        return ExecutionRun(
            request_id=request.request_id,
            run_id=request.run_id,
            trace_id=request.trace_id,
            plan_id=request.plan_id,
            step_id=request.step_id,
            wrapper_id=request.wrapper_id,
            tool_name=contract.tool_name,
            tool_version=contract.tool_version,
            environment_id=request.environment_id,
            command_argv_redacted=["python", "-m", "execution.wrappers.scrublet"],
            parameters={**contract.default_parameters, **request.parameters},
            parameter_provenance=request.parameter_provenance,
            input_hash=artifact.sha256,
            start_time=now,
            end_time=now,
            runtime_seconds=1.0,
            peak_memory_mb=100.0,
            exit_code=1 if failed else 0,
            stdout_path="stdout.log",
            stderr_path="stderr.log",
            status="failed" if failed else "succeeded",
            fixture_id=artifact.fixture_id,
        )


class RecordingValidator:
    def validate(self, run, *, expected_cells):
        del expected_cells
        passed = run.status == "succeeded"
        return ValidationResult(
            validation_id=f"validation-{run.run_id}",
            run_id=run.run_id,
            passed=passed,
            artifact_checks={"required_artifacts_present": passed},
            task_metrics={"synthetic_engineering_f1": 0.7} if passed else {},
            resource_metrics={
                "runtime_seconds": run.runtime_seconds,
                "peak_memory_mb": run.peak_memory_mb,
            },
            failures=[] if passed else ["execution_not_successful"],
        )


def test_experiment_runner_bounds_runs_and_continues_after_failure(tmp_path):
    case, probe, artifact = _development_case(tmp_path)
    configurations = [
        build_configuration(
            configuration_id="default",
            parameters={"min_gene_variability_pctl": 0.0, "n_prin_comps": 10, "use_approx_neighbors": False, "min_counts": 1, "min_cells": 1},
            provenance={},
            source="development_probe_search",
            contract=case["contract"],
        ),
        build_configuration(
            configuration_id="rate-08",
            parameters={"expected_doublet_rate": 0.08, "min_gene_variability_pctl": 0.0, "n_prin_comps": 10, "use_approx_neighbors": False, "min_counts": 1, "min_cells": 1},
            provenance={"expected_doublet_rate": {"origin": "contract_searchable_range"}},
            source="development_probe_search",
            contract=case["contract"],
        ),
    ]
    assert (
        configurations[0].parameter_provenance["n_prin_comps"]["origin"]
        == "development_probe_search"
    )
    executor = RecordingExecutor(fail_seed=2)
    runner = ExperimentRunner(
        executor=executor,
        contract_registry=case["contract_registry"],
        validator=RecordingValidator(),
    )
    batch = runner.run(
        experiment_id="development-test",
        configurations=configurations,
        seeds=[1, 2, 3],
        probe=probe,
        artifact=artifact,
        contract=case["contract"],
        environment=case["environment_registry"].get("scRNAseq"),
        planning_gate=case["planning_gate"],
        plan_id="plan-test",
    )

    assert batch.requested_run_count == 6
    assert batch.completed_run_count == 6
    assert len(executor.requests) == 6
    assert sum(run.status == "failed" for run in batch.execution_runs) == 2
    assert all(record.probe_hash == probe.probe_hash for record in batch.run_records)
    assert all(request.actor.role == "maintainer" for request in executor.requests)


def test_experiment_runner_rejects_budget_range_and_unfrozen_evaluation(tmp_path):
    case, probe, artifact = _development_case(tmp_path)
    config = build_configuration(
        configuration_id="default",
        parameters={"min_gene_variability_pctl": 0.0, "n_prin_comps": 10, "use_approx_neighbors": False, "min_counts": 1, "min_cells": 1},
        provenance={},
        source="development_probe_search",
        contract=case["contract"],
    )
    runner = ExperimentRunner(
        executor=RecordingExecutor(),
        contract_registry=case["contract_registry"],
        validator=RecordingValidator(),
    )
    with pytest.raises(ValueError, match="1-3 unique seeds"):
        runner.run(
            experiment_id="too-many-seeds",
            configurations=[config],
            seeds=[1, 2, 3, 4],
            probe=probe,
            artifact=artifact,
            contract=case["contract"],
            environment=case["environment_registry"].get("scRNAseq"),
            planning_gate=case["planning_gate"],
            plan_id="plan-test",
        )
    invalid = config.model_copy(
        update={"parameters": {**config.parameters, "expected_doublet_rate": 0.9}}
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        runner.run(
            experiment_id="invalid-range",
            configurations=[invalid],
            seeds=[1],
            probe=probe,
            artifact=artifact,
            contract=case["contract"],
            environment=case["environment_registry"].get("scRNAseq"),
            planning_gate=case["planning_gate"],
            plan_id="plan-test",
        )
    evaluation_probe = probe.model_copy(update={"split_role": "evaluation"})
    with pytest.raises(ValueError, match="frozen"):
        runner.run(
            experiment_id="evaluation-unfrozen",
            configurations=[config],
            seeds=[1, 2],
            probe=evaluation_probe,
            artifact=artifact,
            contract=case["contract"],
            environment=case["environment_registry"].get("scRNAseq"),
            planning_gate=case["planning_gate"],
            plan_id="plan-test",
        )


def _development_case(tmp_path):
    case = build_qualification_case(tmp_path)
    case["contract_registry"] = ToolContractRegistry(
        environment_registry=case["environment_registry"]
    )
    fixtures = write_phase1_fixtures(tmp_path / "development-fixtures")
    probe = ProbeBuilder().build(
        source_path=fixtures["raw_x"],
        output_dir=tmp_path / "development-probe",
        profile_id=case["profile"].profile_id,
        fixture_id="phase1_raw_counts_x",
        random_seed=101,
        split_role="development",
        pairing_strategy="mixed",
        cluster_key="batch",
    )
    artifact = case["artifact"].model_copy(
        update={
            "path": probe.probe_artifact_path,
            "sha256": probe.probe_hash,
            "expected_cells": probe.n_probe_cells,
        }
    )
    return case, probe, artifact
