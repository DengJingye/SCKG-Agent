from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from core.capability_pack_models import MethodBinding, compatibility_check
from core.capability_pack_registry import CapabilityPackRegistry
from core.execution_models import (
    ArtifactSpec,
    DataProfile,
    ExecutionBudget,
    ParameterProvenance,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPlan,
)
from core.representation_models import CapabilityPlanResult, RepresentationLedger
from core.research_workspace_models import StepContract, StepParameterSpec
from core.tool_contract_registry import ToolContractRegistry


class CapabilityPlanCompiler:
    """Compile a dry-run plan entirely from pack contracts and ledger state."""

    def __init__(
        self,
        registry: CapabilityPackRegistry | None = None,
        tool_registry: ToolContractRegistry | None = None,
    ) -> None:
        self.registry = registry or CapabilityPackRegistry()
        self.tool_registry = tool_registry or ToolContractRegistry()

    def compile(
        self,
        *,
        pack_id: str,
        pack_version: str,
        ledger: RepresentationLedger,
        target_representations: list[str],
        requirement_id: str,
        options: dict[str, object] | None = None,
        data_profile: DataProfile | None = None,
    ) -> tuple[WorkflowPlan, CapabilityPlanResult]:
        manifest = self.registry.load(pack_id, pack_version)
        gate = self.registry.gate(manifest)
        step_contracts = self.registry.load_step_contracts(manifest)
        options = dict(options or {})
        unknown_parameter_targets = sorted(
            key
            for key, value in options.items()
            if isinstance(value, dict) and key not in step_contracts
        )
        if unknown_parameter_targets:
            raise ValueError(
                "parameter overrides target unknown methods: "
                + ", ".join(unknown_parameter_targets)
            )
        definitions = {item.representation_id: item for item in manifest.representation_contracts}
        producers: dict[str, list[MethodBinding]] = defaultdict(list)
        for method in manifest.methods:
            for production in method.produces:
                producers[production.representation_id].append(method)
        current = {item.representation_id: item for item in ledger.records if item.status == "current" and item.validated}
        reused: set[str] = set()
        selected: list[MethodBinding] = []
        planned_outputs: set[str] = set(current)
        blockers: list[str] = list(ledger.blocking_errors)
        visiting: set[str] = set()

        def ensure(representation_id: str) -> bool:
            if representation_id in planned_outputs:
                record = current.get(representation_id)
                if record is not None:
                    reused.add(representation_id)
                return True
            if representation_id in visiting:
                blockers.append(f"representation_cycle:{representation_id}")
                return False
            visiting.add(representation_id)
            candidates = _rank_methods(producers.get(representation_id, []), options)
            if not candidates:
                blockers.append(f"no_registered_producer:{representation_id}")
                visiting.remove(representation_id)
                return False
            chosen = None
            candidate_reasons: list[str] = []
            for method in candidates:
                blocker_checkpoint = len(blockers)
                selected_checkpoint = list(selected)
                outputs_checkpoint = set(planned_outputs)
                reused_checkpoint = set(reused)
                local_ok = True
                for requirement in method.consumes:
                    if not ensure(requirement.representation_id):
                        local_ok = False
                        break
                    record = current.get(requirement.representation_id)
                    if record is not None:
                        result = compatibility_check(
                            producer=definitions[requirement.representation_id],
                            consumer=requirement,
                            producer_provenance=record.provenance,
                            producer_cell_hash=record.cell_index_hash,
                            consumer_cell_hash=ledger.cell_index_hash,
                            producer_gene_hash=record.gene_index_hash,
                            consumer_gene_hash=ledger.gene_index_hash,
                            producer_metadata=record.metadata,
                        )
                        if result.blocking_reasons:
                            candidate_reasons.extend(
                                f"{method.method_id}:{reason}" for reason in result.blocking_reasons
                            )
                            local_ok = False
                            break
                if local_ok:
                    chosen = method
                    break
                candidate_reasons.extend(blockers[blocker_checkpoint:])
                del blockers[blocker_checkpoint:]
                selected[:] = selected_checkpoint
                planned_outputs.clear()
                planned_outputs.update(outputs_checkpoint)
                reused.clear()
                reused.update(reused_checkpoint)
            if chosen is None:
                blockers.extend(candidate_reasons or [f"no_scientifically_compatible_producer:{representation_id}"])
                visiting.remove(representation_id)
                return False
            if chosen not in selected:
                selected.append(chosen)
                planned_outputs.update(item.representation_id for item in chosen.produces)
            visiting.remove(representation_id)
            return representation_id in planned_outputs

        for target in target_representations:
            ensure(target)

        nodes: list[WorkflowNode] = []
        resolved_parameter_snapshot: dict[str, dict[str, object]] = {}
        for method in selected:
            tool_name = method.tool_contract_ref.split(":", 1)[0] if method.tool_contract_ref else None
            step_contract = step_contracts[method.method_id]
            requested_parameters = (
                dict(options.get(method.method_id, {}))
                if isinstance(options.get(method.method_id), dict)
                else {}
            )
            parameters, parameter_provenance = self._resolve_parameters(
                step_contract=step_contract,
                requested_parameters=requested_parameters,
                data_profile=data_profile,
                requirement_id=requirement_id,
            )
            resolved_parameter_snapshot[method.method_id] = parameters
            nodes.append(
                WorkflowNode(
                    node_id=method.method_id,
                    name=method.method_id,
                    operation=method.method_id,
                    tool_name=tool_name,
                    tool_contract_id=method.tool_contract_ref or "human-review:1.0",
                    input_artifacts=[item.representation_id for item in method.consumes],
                    output_artifacts=[item.representation_id for item in method.produces],
                    parameters=parameters,
                    parameter_provenance=parameter_provenance,
                    preconditions=[item.requirement_id for item in method.requires],
                    failure_policy="block_and_preserve_last_valid_representation",
                    skippable=method.optional,
                )
            )
        node_by_output = {output: node.node_id for node in nodes for output in node.output_artifacts}
        edges = []
        for node in nodes:
            for input_id in node.input_artifacts:
                source = node_by_output.get(input_id)
                if source and source != node.node_id:
                    edges.append(WorkflowEdge(source_node_id=source, target_node_id=node.node_id, artifact_id=input_id))
        plan_id = "cap-plan-" + _digest(
            {
                "ledger": ledger.ledger_id,
                "targets": target_representations,
                "methods": [item.method_id for item in selected],
                "options": options,
                "resolved_parameters": resolved_parameter_snapshot,
            }
        )[:16]
        if "planning_ready" not in gate.readiness:
            blockers.append("capability_pack_not_planning_ready")
        blockers = sorted(set(blockers))
        plan = WorkflowPlan(
            plan_id=plan_id,
            requirement_id=requirement_id,
            profile_id=ledger.profile_id,
            steps=nodes,
            edges=edges,
            candidate_tools=sorted({node.tool_name for node in nodes if node.tool_name}),
            execution_budget=ExecutionBudget(),
            expected_outputs=[ArtifactSpec(artifact_id=item, artifact_type="representation", format="registered_artifact", validator_id="representation_contract_v1") for item in target_representations],
            blocking_conditions=blockers,
            execution_blockers=["capability_pack_execution_not_eligible"],
            planning_warnings=sorted(set(ledger.warnings + [f"reuse:{item}" for item in reused])),
            data_awareness="data_aware",
            execution_eligible=False,
            approval_required=True,
            plan_status="blocked" if blockers else "dry_run",
        )
        return plan, CapabilityPlanResult(
            plan_id=f"result-{plan_id}", workflow_plan_id=plan_id,
            target_representations=target_representations,
            reused_representation_ids=sorted(reused),
            planned_method_ids=[item.method_id for item in selected],
            blocked=bool(blockers), blocking_reasons=blockers,
        )

    def _resolve_parameters(
        self,
        *,
        step_contract: StepContract,
        requested_parameters: dict[str, object],
        data_profile: DataProfile | None,
        requirement_id: str,
    ) -> tuple[dict[str, object], list[ParameterProvenance]]:
        unknown = sorted(set(requested_parameters) - set(step_contract.parameters))
        if unknown:
            raise ValueError(
                f"unknown parameters for {step_contract.method_id}: "
                + ", ".join(unknown)
            )
        if not step_contract.parameters:
            return {}, []
        tool_contract = _load_tool_contract(
            self.tool_registry,
            step_contract.tool_contract_id,
        )
        parameters: dict[str, object] = {}
        provenance: list[ParameterProvenance] = []
        for parameter_name, spec in step_contract.parameters.items():
            user_supplied = parameter_name in requested_parameters
            value = (
                requested_parameters[parameter_name]
                if user_supplied
                else _adapt_parameter(spec, data_profile)
            )
            _validate_step_parameter(parameter_name, value, spec)
            if user_supplied:
                _validate_profile_bound(parameter_name, value, spec, data_profile)
            contract_parameter = spec.contract_parameter or parameter_name
            if tool_contract is not None and spec.contract_parameter is not None:
                self.tool_registry.validate_parameters(
                    tool_contract,
                    {contract_parameter: value},
                )
            parameters[parameter_name] = value
            adapted = not user_supplied and value != spec.default
            matches_contract_default = bool(
                tool_contract is not None
                and contract_parameter in tool_contract.default_parameters
                and tool_contract.default_parameters[contract_parameter] == value
            )
            provenance.append(
                ParameterProvenance(
                    parameter_name=parameter_name,
                    value_or_range=value,
                    origin_type=(
                        "user_override"
                        if user_supplied
                        else "source_bound_prior"
                        if adapted
                        else "contract_default"
                        if matches_contract_default
                        else "source_bound_prior"
                    ),
                    source_type=(
                        "user"
                        if user_supplied
                        else "policy_rule"
                        if adapted
                        else "official_default"
                        if matches_contract_default
                        else "policy_rule"
                    ),
                    source_id=(
                        requirement_id
                        if user_supplied
                        else spec.provenance
                        if adapted
                        else tool_contract.contract_id
                        if matches_contract_default
                        else spec.provenance
                    ),
                    source_span=(
                        f"default_parameters.{contract_parameter}"
                        if matches_contract_default
                        else f"parameter_schema.properties.{contract_parameter}"
                        if tool_contract is not None
                        else None
                    ),
                    tool_version=(
                        tool_contract.tool_version if tool_contract is not None else None
                    ),
                    policy_rule_id=(
                        spec.adaptive_rule
                        if adapted
                        else "reviewed_step_parameter_default"
                        if not user_supplied and not matches_contract_default
                        else None
                    ),
                    applicable_scope=(
                        f"profile:{data_profile.profile_id}"
                        if data_profile is not None
                        else "capability_plan"
                    ),
                    limitations=(
                        ["Deterministic dataset-shape bound; not an empirical optimum."]
                        if adapted
                        else ["User value remains bounded by reviewed parameter contracts."]
                        if user_supplied
                        else []
                    ),
                )
            )
        return parameters, provenance


def _rank_methods(methods: list[MethodBinding], options: dict[str, object]) -> list[MethodBinding]:
    methods = list(methods)
    preferred_ids = options.get("preferred_method_ids", [])
    preferred_order = {
        method_id: index
        for index, method_id in enumerate(preferred_ids)
        if isinstance(method_id, str)
    } if isinstance(preferred_ids, list) else {}
    methods.sort(
        key=lambda item: (
            0 if item.method_id in preferred_order else 1,
            preferred_order.get(item.method_id, len(preferred_order)),
            item.optional,
            item.method_id,
        )
    )
    return methods


def _load_tool_contract(
    registry: ToolContractRegistry,
    contract_id: str,
):
    if ":" not in contract_id or contract_id.startswith(
        ("human-review:", "method-family:", "action:")
    ):
        return None
    tool_name, tool_version = contract_id.split(":", 1)
    return registry.load(tool_name, tool_version)


def _adapt_parameter(
    spec: StepParameterSpec,
    data_profile: DataProfile | None,
) -> object:
    value = spec.default
    if data_profile is None or spec.adaptive_rule is None:
        return value
    bound = _adaptive_bound(spec, data_profile)
    return min(value, bound)


def _adaptive_bound(spec: StepParameterSpec, data_profile: DataProfile) -> int:
    if spec.adaptive_rule == "cap_by_cell_count_minus_one":
        bound = data_profile.n_cells - 1
    elif spec.adaptive_rule == "cap_by_feature_count":
        bound = max(int(spec.minimum or 1), data_profile.n_genes)
    else:
        bound = min(data_profile.n_cells - 1, data_profile.n_genes - 1)
    return bound


def _validate_profile_bound(
    parameter_name: str,
    value: object,
    spec: StepParameterSpec,
    data_profile: DataProfile | None,
) -> None:
    if data_profile is None or spec.adaptive_rule is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    if value > _adaptive_bound(spec, data_profile):
        raise ValueError(f"parameter exceeds dataset-shape bound: {parameter_name}")


def _validate_step_parameter(
    parameter_name: str,
    value: object,
    spec: StepParameterSpec,
) -> None:
    if spec.parameter_type == "boolean":
        valid_type = isinstance(value, bool)
    elif spec.parameter_type == "integer":
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    elif spec.parameter_type == "number":
        valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
    else:
        valid_type = isinstance(value, str)
    if not valid_type:
        raise ValueError(f"invalid parameter type: {parameter_name}")
    if spec.enum and value not in spec.enum:
        raise ValueError(f"parameter outside enum: {parameter_name}")
    if spec.minimum is not None and value < spec.minimum:
        raise ValueError(f"parameter below minimum: {parameter_name}")
    if spec.maximum is not None and value > spec.maximum:
        raise ValueError(f"parameter above maximum: {parameter_name}")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
