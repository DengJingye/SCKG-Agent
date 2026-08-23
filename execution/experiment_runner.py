from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from core.deterministic_router import DeterministicRouter
from core.execution_models import (
    AnnotationProbeSpec,
    AnnotationReferenceManifest,
    AnnotationSplitArtifact,
    ConfigurationSpec,
    EnvironmentRecord,
    ExecutionRequest,
    ExperimentBatchResult,
    ExperimentRunRecord,
    PlanningGateResult,
    ProbeSpec,
    IntegrationProbeSpec,
    IntegrationSplitArtifact,
    ScientificSplitArtifact,
    QualificationArtifact,
    ToolContract,
)
from core.tool_contract_registry import ToolContractRegistry
from execution.local_controlled_executor import LocalControlledExecutor
from execution.validators.doublet import DoubletValidator


MAX_CONFIGURATIONS = 4
MAX_SEEDS = 3
MAX_INITIAL_RUNS = 12


class ExperimentRunner:
    """Run bounded tool qualification experiments through the controlled executor."""

    def __init__(
        self,
        *,
        executor: LocalControlledExecutor,
        contract_registry: ToolContractRegistry,
        router: DeterministicRouter | None = None,
        validator: Any | None = None,
    ) -> None:
        self.executor = executor
        self.contract_registry = contract_registry
        self.router = router or DeterministicRouter()
        self.validator = validator or DoubletValidator()

    def run(
        self,
        *,
        experiment_id: str,
        configurations: Iterable[ConfigurationSpec],
        seeds: Iterable[int],
        probe: (
            ProbeSpec
            | ScientificSplitArtifact
            | IntegrationProbeSpec
            | IntegrationSplitArtifact
            | AnnotationProbeSpec
            | AnnotationSplitArtifact
        ),
        artifact: QualificationArtifact,
        contract: ToolContract,
        environment: EnvironmentRecord,
        planning_gate: PlanningGateResult,
        plan_id: str,
        annotation_reference: AnnotationReferenceManifest | None = None,
    ) -> ExperimentBatchResult:
        configurations = list(configurations)
        seeds = list(seeds)
        _validate_experiment_shape(configurations, seeds, probe)
        for configuration in configurations:
            self._validate_configuration(configuration, contract)

        execution_runs = []
        validation_results = []
        run_records = []
        batch_failures: list[str] = []
        for configuration in configurations:
            for seed in seeds:
                run_id = _safe_id(
                    f"{experiment_id}-{configuration.configuration_id}-seed-{seed}"
                )
                parameters = dict(configuration.parameters)
                provenance = dict(configuration.parameter_provenance)
                seed_provenance = {
                    "origin": "execution_seed",
                    "split_role": probe.split_role,
                    "seed": seed,
                    "probe_hash": probe.probe_hash,
                }
                if contract.task == "doublet_detection" and "random_state" in (
                    contract.parameter_schema.get("properties") or {}
                ):
                    parameters["random_state"] = seed
                    provenance["random_state"] = seed_provenance
                request = ExecutionRequest(
                    request_id=f"request-{run_id}",
                    run_id=run_id,
                    trace_id=f"trace-{experiment_id}",
                    plan_id=plan_id,
                    step_id="run-tool-configuration",
                    wrapper_id=contract.wrapper_id,
                    environment_id=contract.environment_id,
                    input_artifact_id=artifact.artifact_id,
                    execution_seed=seed,
                    parameters=parameters,
                    parameter_provenance=provenance,
                    timeout_seconds=int(
                        contract.resource_requirements["qualification_timeout_seconds"]
                    ),
                    actor={"actor_id": "experiment-runner", "role": "maintainer"},
                    qualification={
                        "mode": True,
                        "purpose": (
                            "scientific_pilot"
                            if isinstance(
                                probe,
                                (
                                    ScientificSplitArtifact,
                                    IntegrationSplitArtifact,
                                    AnnotationSplitArtifact,
                                ),
                            )
                            else "synthetic_qualification"
                        ),
                        "authorized": True,
                        "fixture_allowlisted": True,
                        "fixture_id": artifact.fixture_id,
                    },
                )
                decision = self.router.route_qualification(
                    request=request,
                    artifact=artifact,
                    tool_contract=contract,
                    environment=environment,
                    planning_gate=planning_gate,
                    max_timeout_seconds=int(
                        contract.resource_requirements["qualification_timeout_seconds"]
                    ),
                )
                try:
                    run = self.executor.execute(
                        request=request,
                        artifact=artifact,
                        contract=contract,
                        router_decision=decision,
                    )
                    if contract.task == "batch_integration":
                        validation = self.validator.validate(
                            run,
                            expected_cells=artifact.expected_cells,
                            expected_input_path=artifact.path,
                            contract=contract,
                        )
                    elif contract.task == "cell_type_annotation":
                        if annotation_reference is None:
                            raise ValueError(
                                "annotation experiment requires a bound reference manifest"
                            )
                        validation = self.validator.validate(
                            run,
                            expected_cells=artifact.expected_cells,
                            expected_input_path=artifact.path,
                            contract=contract,
                            reference=annotation_reference,
                        )
                    else:
                        validation = self.validator.validate(
                            run, expected_cells=artifact.expected_cells
                        )
                except Exception as exc:
                    batch_failures.append(f"{run_id}:{type(exc).__name__}:{exc}")
                    continue
                execution_runs.append(run)
                validation_results.append(validation)
                run_records.append(
                    ExperimentRunRecord(
                        run_id=run.run_id,
                        configuration_id=configuration.configuration_id,
                        configuration_hash=configuration.configuration_hash,
                        seed=seed,
                        split_role=probe.split_role,
                        probe_hash=probe.probe_hash,
                        parameters=run.parameters,
                        parameter_provenance=run.parameter_provenance,
                        run_status=run.status,
                        validation_id=validation.validation_id,
                        validation_passed=validation.passed,
                        runtime_seconds=run.runtime_seconds,
                        peak_memory_mb=run.peak_memory_mb,
                    )
                )

        requested = len(configurations) * len(seeds)
        return ExperimentBatchResult(
            experiment_id=experiment_id,
            split_role=probe.split_role,
            probe_hash=probe.probe_hash,
            configurations=configurations,
            execution_runs=execution_runs,
            validation_results=validation_results,
            run_records=run_records,
            requested_run_count=requested,
            completed_run_count=len(execution_runs),
            failures=batch_failures,
        )

    def _validate_configuration(
        self, configuration: ConfigurationSpec, contract: ToolContract
    ) -> None:
        expected_hash = configuration_hash(
            contract.tool_name, contract.tool_version, configuration.parameters
        )
        if configuration.configuration_hash != expected_hash:
            raise ValueError(
                f"configuration hash mismatch: {configuration.configuration_id}"
            )
        self.contract_registry.validate_parameters(contract, configuration.parameters)
        if configuration.source == "contract_searchable_range":
            _require_searchable_values(configuration.parameters, contract)


def build_configuration(
    *,
    configuration_id: str,
    parameters: dict,
    provenance: dict,
    source: str,
    contract: ToolContract,
    frozen: bool = False,
) -> ConfigurationSpec:
    supplied_parameters = dict(parameters)
    parameters = {**contract.default_parameters, **supplied_parameters}
    generated_provenance = {}
    for name, value in parameters.items():
        is_override = (
            name in supplied_parameters
            and value != contract.default_parameters.get(name)
        )
        generated_provenance[name] = {
            "origin": source if is_override else "contract_default",
            "value": value,
            "tool_version": contract.tool_version,
        }
    provenance = {**generated_provenance, **provenance}
    return ConfigurationSpec(
        configuration_id=configuration_id,
        configuration_hash=configuration_hash(
            contract.tool_name, contract.tool_version, parameters
        ),
        parameters=parameters,
        parameter_provenance=provenance,
        source=source,
        frozen=frozen,
    )


def configuration_hash(tool_name: str, tool_version: str, parameters: dict) -> str:
    configuration_parameters = {
        key: value for key, value in parameters.items() if key != "random_state"
    }
    payload = {
        "tool_name": tool_name,
        "tool_version": tool_version,
        "parameters": configuration_parameters,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_experiment_shape(
    configurations: list[ConfigurationSpec],
    seeds: list[int],
    probe: (
        ProbeSpec
        | ScientificSplitArtifact
        | IntegrationProbeSpec
        | IntegrationSplitArtifact
        | AnnotationProbeSpec
        | AnnotationSplitArtifact
    ),
) -> None:
    if not configurations or len(configurations) > MAX_CONFIGURATIONS:
        raise ValueError("experiment requires 1-4 configurations")
    if not seeds or len(seeds) > MAX_SEEDS or len(set(seeds)) != len(seeds):
        raise ValueError("experiment requires 1-3 unique seeds")
    if len(configurations) * len(seeds) > MAX_INITIAL_RUNS:
        raise ValueError("initial runs exceed 12")
    if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds):
        raise ValueError("seeds must be non-negative integers")
    if probe.split_role not in {"development", "evaluation"}:
        raise ValueError("experiment runner requires development or evaluation probe")
    if probe.split_role == "evaluation":
        if isinstance(probe, (ScientificSplitArtifact, AnnotationSplitArtifact)):
            if len(seeds) != 1 or not all(item.frozen for item in configurations):
                raise ValueError(
                    "scientific evaluation requires frozen configurations and one seed"
                )
        elif len(configurations) != 1 or not configurations[0].frozen:
            raise ValueError("evaluation probe requires exactly one frozen configuration")


def _require_searchable_values(parameters: dict, contract: ToolContract) -> None:
    for name, value in parameters.items():
        if name == "random_state" or value == contract.default_parameters.get(name):
            continue
        bounds = contract.searchable_parameters.get(name)
        if bounds is None:
            raise ValueError(f"parameter is not searchable: {name}")
        if value < bounds.get("minimum", value) or value > bounds.get("maximum", value):
            raise ValueError(f"parameter outside searchable range: {name}")


def _safe_id(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "_.-" else "-" for character in value)
    return safe[:120]
