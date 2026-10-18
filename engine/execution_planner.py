from __future__ import annotations

import hashlib
import json
from typing import Optional

from core.execution_models import (
    ArtifactSpec,
    DataProfile,
    EnvironmentRecord,
    ExecutionBudget,
    ParameterProvenance,
    RequirementSpec,
    TaskDataEligibility,
    ToolContract,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPlan,
)
from core.tool_contract_registry import ToolContractRegistry
from engine.task_data_gate import TaskDataGate


PHASE2_NODE_IDS = [
    "validate_input",
    "select_count_source",
    "build_probe_plan",
    "run_scrublet_candidate",
    "validate_expected_outputs",
    "aggregate_candidate_results",
    "package_expected_artifacts",
]

BATCH_INTEGRATION_NODE_IDS = [
    "validate_input",
    "validate_batch_design",
    "select_integration_representation",
    "prepare_pca_plan",
    "run_integration_candidate",
    "validate_integration_outputs",
    "evaluate_batch_mixing",
    "evaluate_biology_conservation",
    "aggregate_candidate_results",
    "package_expected_artifacts",
]


class ExecutionPlanCompiler:
    """Compile an auditable dry-run plan without creating an execution request."""

    def __init__(
        self,
        contract_registry: ToolContractRegistry,
        *,
        task_data_gate: Optional[TaskDataGate] = None,
    ) -> None:
        self.contract_registry = contract_registry
        self.task_data_gate = task_data_gate or TaskDataGate()

    def compile(
        self,
        *,
        requirement: RequirementSpec,
        data_profile: Optional[DataProfile],
        tool_contract: ToolContract,
        environment: EnvironmentRecord,
        execution_budget: ExecutionBudget,
    ) -> WorkflowPlan:
        planning = self.contract_registry.planning_gate(
            tool_contract,
            data_profile=data_profile,
        )
        execution = self.contract_registry.execution_gate(tool_contract)
        blocking_conditions = list(planning.reasons)
        planning_warnings: list[str] = []

        if tool_contract.environment_id != environment.environment_id:
            blocking_conditions.append(
                f"environment_id_mismatch:{tool_contract.environment_id}!={environment.environment_id}"
            )
        runtime_version = environment.package_versions.get(tool_contract.tool_name.casefold())
        if tool_contract.enabled_for_execution and runtime_version != tool_contract.tool_version:
            blocking_conditions.append(
                "tool_runtime_version_mismatch:"
                f"contract={tool_contract.tool_version},environment={runtime_version or 'missing'}"
            )
        if requirement.task != tool_contract.task:
            blocking_conditions.append(
                f"task_contract_mismatch:{requirement.task}!={tool_contract.task}"
            )
        if data_profile is not None and not requirement.data_access_authorized:
            blocking_conditions.append("data_profile_present_without_data_authorization")
        eligibility: Optional[TaskDataEligibility] = None
        if data_profile is None:
            planning_warnings.append("generic_plan_without_data_profile")
        else:
            eligibility = self.task_data_gate.evaluate(requirement, data_profile)
            blocking_conditions.extend(
                f"task_data_gate:{reason}" for reason in eligibility.blocking_reasons
            )
            planning_warnings.extend(eligibility.warnings)

        execution_blockers = sorted(set(execution.reasons))
        if execution_blockers:
            planning_warnings.append("execution_gate_failed_plan_remains_dry_run")

        selected_count_source = (
            data_profile.selected_count_source if data_profile is not None else None
        )
        if requirement.task == "batch_integration":
            nodes = _build_batch_integration_nodes(
                requirement=requirement,
                data_profile=data_profile,
                eligibility=eligibility,
                contract=tool_contract,
                execution_budget=execution_budget,
            )
            node_ids = BATCH_INTEGRATION_NODE_IDS
        else:
            nodes = _build_nodes(
                requirement=requirement,
                data_profile=data_profile,
                contract=tool_contract,
                execution_budget=execution_budget,
                selected_count_source=selected_count_source,
            )
            node_ids = PHASE2_NODE_IDS
        edges = [
            WorkflowEdge(
                source_node_id=node_ids[index],
                target_node_id=node_ids[index + 1],
                artifact_id=nodes[index].output_artifacts[0],
            )
            for index in range(len(node_ids) - 1)
        ]
        plan_id = _plan_id(
            requirement=requirement,
            profile=data_profile,
            contract=tool_contract,
            budget=execution_budget,
        )
        return WorkflowPlan(
            plan_id=plan_id,
            requirement_id=requirement.request_id,
            profile_id=(
                data_profile.profile_id if data_profile is not None else "profile_not_available"
            ),
            steps=nodes,
            edges=edges,
            candidate_tools=[tool_contract.tool_name],
            selected_probe_tools=[],
            parameter_search_space={
                tool_contract.tool_name: tool_contract.searchable_parameters,
            },
            execution_budget=execution_budget,
            expected_outputs=list(tool_contract.output_artifacts)
            + [
                ArtifactSpec(
                    artifact_id="phase2_plan_manifest",
                    artifact_type="planning_manifest",
                    format="json",
                    required=True,
                    validator_id="workflow_plan_schema",
                )
            ],
            blocking_conditions=sorted(set(blocking_conditions)),
            execution_blockers=execution_blockers,
            planning_warnings=sorted(set(planning_warnings)),
            data_awareness="data_aware" if data_profile is not None else "generic",
            execution_eligible=False,
            approval_required=True,
            plan_status="blocked" if blocking_conditions else "dry_run",
        )


def _build_nodes(
    *,
    requirement: RequirementSpec,
    data_profile: Optional[DataProfile],
    contract: ToolContract,
    execution_budget: ExecutionBudget,
    selected_count_source: Optional[str],
) -> list[WorkflowNode]:
    profile_artifact = data_profile.profile_id if data_profile is not None else "future_data_profile"
    count_artifact = selected_count_source or "unresolved_count_source"
    resource_budget = requirement.resource_budget
    contract_id = contract.contract_id
    internal_tool = "scKG deterministic planning service"

    return [
        WorkflowNode(
            node_id="validate_input",
            name="Validate AnnData input requirements",
            operation="validate_input_metadata",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[requirement.input_path or "future_h5ad_input"],
            output_artifacts=[profile_artifact],
            parameters={
                "required_object_type": "AnnData",
                "data_access_authorized": requirement.data_access_authorized,
            },
            parameter_provenance=[
                _policy_provenance(
                    "required_object_type",
                    "AnnData",
                    "phase2_validate_input_object",
                    contract.tool_version,
                )
            ],
            preconditions=["input path is local when supplied", "data access is authorized before profiling"],
            resource_budget=resource_budget,
            failure_policy="block_on_missing_corrupt_or_unauthorized_input",
        ),
        WorkflowNode(
            node_id="select_count_source",
            name="Resolve raw count matrix",
            operation="select_count_source",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[profile_artifact],
            output_artifacts=[count_artifact],
            parameters={"selected_count_source": selected_count_source},
            parameter_provenance=[
                _policy_provenance(
                    "count_source_priority",
                    "explicit_user>tool_contract>layers/counts>X>raw.X>unresolved",
                    "phase2_count_source_priority",
                    contract.tool_version,
                )
            ],
            preconditions=["selected matrix must be inferred as raw_counts"],
            resource_budget=resource_budget,
            failure_policy="block_when_count_source_unresolved",
        ),
        WorkflowNode(
            node_id="build_probe_plan",
            name="Describe bounded probe configuration",
            operation="build_probe_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[count_artifact],
            output_artifacts=["planned_probe_spec"],
            parameters={
                "max_cells": resource_budget.max_cells,
                "random_seed_policy": "fixed_per_future_run",
                "max_initial_runs": execution_budget.max_initial_runs,
            },
            parameter_provenance=[
                _policy_provenance(
                    "max_cells",
                    resource_budget.max_cells,
                    "phase2_requirement_resource_budget",
                    contract.tool_version,
                )
            ],
            preconditions=["count source resolved", "plan remains dry_run"],
            resource_budget=resource_budget,
            failure_policy="do_not_materialize_probe_in_phase2",
        ),
        WorkflowNode(
            node_id="run_scrublet_candidate",
            name="Describe Scrublet candidate run",
            operation="plan_tool_candidate_only",
            tool_name=contract.tool_name,
            tool_contract_id=contract_id,
            input_artifacts=["planned_probe_spec"],
            output_artifacts=[artifact.artifact_id for artifact in contract.output_artifacts],
            parameters=dict(contract.default_parameters),
            parameter_provenance=[
                ParameterProvenance(
                    parameter_name=name,
                    value_or_range=value,
                    origin_type="contract_default",
                    source_type="official_default",
                    source_id=contract.source_refs[0] if contract.source_refs else None,
                    source_span=None,
                    tool_version=contract.tool_version,
                    applicable_scope="Phase 2 planning only",
                    limitations=[
                        "Parameter is contract-declared but has not been integration tested.",
                        "This node must not create an ExecutionRequest.",
                    ],
                )
                for name, value in sorted(contract.default_parameters.items())
            ],
            preconditions=[
                f"planning-gated contract {contract_id}",
                "execution gate must pass in a later phase",
                "explicit plan-specific user approval required before future execution",
            ],
            resource_budget=resource_budget,
            failure_policy="never_execute_in_phase2",
        ),
        WorkflowNode(
            node_id="validate_expected_outputs",
            name="Describe expected output validation",
            operation="validate_expected_outputs_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[artifact.artifact_id for artifact in contract.output_artifacts],
            output_artifacts=["planned_validation_manifest"],
            parameters={
                "validation_metrics": list(contract.validation_metrics),
                "failure_checks": list(contract.failure_checks),
            },
            parameter_provenance=[
                _policy_provenance(
                    "validation_policy",
                    list(contract.validation_metrics),
                    "phase2_contract_validation_declaration",
                    contract.tool_version,
                )
            ],
            preconditions=["future run artifacts must exist before validation"],
            resource_budget=resource_budget,
            failure_policy="block_on_missing_or_invalid_future_artifacts",
        ),
        WorkflowNode(
            node_id="aggregate_candidate_results",
            name="Describe future candidate aggregation",
            operation="aggregate_candidate_results_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=["planned_validation_manifest"],
            output_artifacts=["planned_candidate_summary"],
            parameters={"aggregation_status": "not_run"},
            parameter_provenance=[
                _policy_provenance(
                    "aggregation_status",
                    "not_run",
                    "phase2_no_candidate_evaluation",
                    contract.tool_version,
                )
            ],
            preconditions=["future validation results are terminal"],
            resource_budget=resource_budget,
            failure_policy="do_not_create_candidate_evaluation_in_phase2",
        ),
        WorkflowNode(
            node_id="package_expected_artifacts",
            name="Describe expected reproducibility artifacts",
            operation="package_expected_artifacts_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=["planned_candidate_summary"],
            output_artifacts=["phase2_plan_manifest"],
            parameters={
                "package_mode": "expected_artifacts_only",
                "execution_artifacts_present": False,
            },
            parameter_provenance=[
                _policy_provenance(
                    "package_mode",
                    "expected_artifacts_only",
                    "phase2_package_boundary",
                    contract.tool_version,
                )
            ],
            preconditions=["plan is dry_run or blocked", "no execution artifacts are claimed"],
            resource_budget=resource_budget,
            failure_policy="never_claim_reproducibility_without_future_run_artifacts",
        ),
    ]


def _build_batch_integration_nodes(
    *,
    requirement: RequirementSpec,
    data_profile: Optional[DataProfile],
    eligibility: Optional[TaskDataEligibility],
    contract: ToolContract,
    execution_budget: ExecutionBudget,
) -> list[WorkflowNode]:
    profile_artifact = data_profile.profile_id if data_profile is not None else "future_data_profile"
    selected_representation = (
        eligibility.selected_representation if eligibility is not None else "future_expression_representation"
    )
    batch_key = requirement.batch_key or "unresolved_batch_key"
    label_mode = eligibility.biology_label_mode if eligibility is not None else "degraded_no_label"
    resource_budget = requirement.resource_budget
    contract_id = contract.contract_id
    internal_tool = "scKG deterministic planning service"

    def policy(name: str, value: object, rule: str) -> list[ParameterProvenance]:
        return [_policy_provenance(name, value, rule, contract.tool_version)]

    return [
        WorkflowNode(
            node_id="validate_input",
            name="Validate AnnData structure for integration",
            operation="validate_input_metadata",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[requirement.input_path or "future_h5ad_input"],
            output_artifacts=[profile_artifact],
            parameters={"required_object_type": "AnnData", "task": "batch_integration"},
            parameter_provenance=policy("task", "batch_integration", "phase5_task_boundary"),
            preconditions=["input is AnnData", "profiling is read-only and authorized"],
            resource_budget=resource_budget,
            failure_policy="block_on_missing_corrupt_or_unauthorized_input",
        ),
        WorkflowNode(
            node_id="validate_batch_design",
            name="Validate multi-batch design",
            operation="validate_batch_design_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[profile_artifact],
            output_artifacts=["validated_batch_design"],
            parameters={
                "batch_key": batch_key,
                "minimum_batches": 2,
                "label_key": requirement.label_key,
                "biology_label_mode": label_mode,
            },
            parameter_provenance=policy("minimum_batches", 2, "phase5_multi_batch_gate"),
            preconditions=["batch key exists", "at least two non-empty batches"],
            resource_budget=resource_budget,
            failure_policy="block_on_missing_invalid_or_single_batch_design",
        ),
        WorkflowNode(
            node_id="select_integration_representation",
            name="Select source expression representation",
            operation="select_integration_representation_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[profile_artifact],
            output_artifacts=[str(selected_representation)],
            parameters={"selected_representation": selected_representation},
            parameter_provenance=policy(
                "representation_priority",
                "valid X_pca > finite X > validated count source",
                "phase5_representation_priority",
            ),
            preconditions=["selected representation is finite and cell-aligned"],
            resource_budget=resource_budget,
            failure_policy="block_when_integration_representation_unresolved",
        ),
        WorkflowNode(
            node_id="prepare_pca_plan",
            name="Prepare or reuse normalized PCA representation",
            operation="prepare_pca_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[str(selected_representation)],
            output_artifacts=["planned_X_pca"],
            parameters={
                "reuse_existing_pca": selected_representation == "obsm/X_pca",
                "normalization_if_raw": "normalize_total_then_log1p",
                "pca_status": "planned_not_executed",
            },
            parameter_provenance=policy(
                "pca_status", "planned_not_executed", "phase5_no_preprocessing_execution"
            ),
            preconditions=["preprocessing must preserve obs order", "plan remains dry_run"],
            resource_budget=resource_budget,
            failure_policy="never_execute_preprocessing_in_planning_stage",
        ),
        WorkflowNode(
            node_id="run_integration_candidate",
            name=f"Describe {contract.tool_name} integration candidate",
            operation="plan_tool_candidate_only",
            tool_name=contract.tool_name,
            tool_contract_id=contract_id,
            input_artifacts=["planned_X_pca", "validated_batch_design"],
            output_artifacts=[artifact.artifact_id for artifact in contract.output_artifacts],
            parameters=dict(contract.default_parameters),
            parameter_provenance=[
                ParameterProvenance(
                    parameter_name=name,
                    value_or_range=value,
                    origin_type="contract_default",
                    source_type="official_default",
                    source_id=contract.source_refs[0] if contract.source_refs else None,
                    tool_version=contract.tool_version,
                    applicable_scope="Phase 5 planning only",
                    limitations=["No wrapper or tool process is invoked by this node."],
                )
                for name, value in sorted(contract.default_parameters.items())
            ],
            preconditions=[
                f"planning-gated contract {contract_id}",
                "batch design validated",
                "execution qualification and plan-specific approval remain required",
            ],
            resource_budget=resource_budget,
            failure_policy="never_execute_in_phase5_planning_foundation",
        ),
        WorkflowNode(
            node_id="validate_integration_outputs",
            name="Describe integrated embedding validation",
            operation="validate_integration_outputs_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=[artifact.artifact_id for artifact in contract.output_artifacts],
            output_artifacts=["planned_integration_validation"],
            parameters={"validation_metrics": list(contract.validation_metrics)},
            parameter_provenance=policy(
                "validation_metrics", list(contract.validation_metrics), "phase5_contract_validation"
            ),
            preconditions=["embedding rows equal input cell count", "values are finite"],
            resource_budget=resource_budget,
            failure_policy="block_on_missing_misaligned_or_nonfinite_embedding",
        ),
        WorkflowNode(
            node_id="evaluate_batch_mixing",
            name="Plan batch mixing evaluation",
            operation="evaluate_batch_mixing_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=["planned_integration_validation"],
            output_artifacts=["planned_batch_mixing_metrics"],
            parameters={"required_metric_family": "batch_mixing", "status": "not_run"},
            parameter_provenance=policy(
                "required_metric_family", "batch_mixing", "phase5_acceptance_metric"
            ),
            preconditions=["validated embedding", "batch labels available"],
            resource_budget=resource_budget,
            failure_policy="do_not_claim_metric_without_evaluation_artifact",
        ),
        WorkflowNode(
            node_id="evaluate_biology_conservation",
            name="Plan biology conservation evaluation",
            operation="evaluate_biology_conservation_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=["planned_integration_validation"],
            output_artifacts=["planned_biology_conservation_metrics"],
            parameters={"label_mode": label_mode, "status": "not_run"},
            parameter_provenance=policy("label_mode", label_mode, "phase5_label_degradation_rule"),
            preconditions=["validated embedding", "label-aware metrics require label_key"],
            resource_budget=resource_budget,
            failure_policy="degrade_explicitly_when_biology_labels_are_unavailable",
            skippable=label_mode != "available",
        ),
        WorkflowNode(
            node_id="aggregate_candidate_results",
            name="Describe integration candidate aggregation",
            operation="aggregate_candidate_results_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=["planned_batch_mixing_metrics", "planned_biology_conservation_metrics"],
            output_artifacts=["planned_integration_candidate_summary"],
            parameters={"aggregation_status": "not_run", "candidate_tool": contract.tool_name},
            parameter_provenance=policy(
                "aggregation_status", "not_run", "phase5_no_candidate_evaluation"
            ),
            preconditions=["future validation and metric results are terminal"],
            resource_budget=resource_budget,
            failure_policy="do_not_create_candidate_evaluation_during_planning",
        ),
        WorkflowNode(
            node_id="package_expected_artifacts",
            name="Describe integration reproducibility package",
            operation="package_expected_artifacts_plan_only",
            tool_name=internal_tool,
            tool_contract_id=contract_id,
            input_artifacts=["planned_integration_candidate_summary"],
            output_artifacts=["phase5_plan_manifest"],
            parameters={"package_mode": "expected_artifacts_only", "execution_artifacts_present": False},
            parameter_provenance=policy(
                "package_mode", "expected_artifacts_only", "phase5_package_boundary"
            ),
            preconditions=["plan is dry_run or blocked", "no execution artifacts are claimed"],
            resource_budget=resource_budget,
            failure_policy="never_claim_reproducibility_without_future_run_artifacts",
        ),
    ]


def _policy_provenance(
    parameter_name: str,
    value: object,
    rule_id: str,
    tool_version: str,
) -> ParameterProvenance:
    return ParameterProvenance(
        parameter_name=parameter_name,
        value_or_range=value,
        origin_type="contract_default",
        source_type="policy_rule",
        policy_rule_id=rule_id,
        tool_version=tool_version,
        applicable_scope="Phase 2 dry-run planning",
        limitations=["Planning metadata only; cannot authorize execution."],
    )


def _plan_id(
    *,
    requirement: RequirementSpec,
    profile: Optional[DataProfile],
    contract: ToolContract,
    budget: ExecutionBudget,
) -> str:
    payload = {
        "requirement": requirement.model_dump(mode="json"),
        "profile_id": profile.profile_id if profile is not None else None,
        "contract_id": contract.contract_id,
        "contract_version": contract.contract_version,
        "budget": budget.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"plan_{digest[:20]}"
