from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from core.capability_pack_models import MethodBinding, compatibility_check
from core.capability_pack_registry import CapabilityPackRegistry
from core.execution_models import (
    ArtifactSpec,
    ExecutionBudget,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPlan,
)
from core.representation_models import CapabilityPlanResult, RepresentationLedger


class CapabilityPlanCompiler:
    """Compile a dry-run plan entirely from pack contracts and ledger state."""

    def __init__(self, registry: CapabilityPackRegistry | None = None) -> None:
        self.registry = registry or CapabilityPackRegistry()

    def compile(
        self,
        *,
        pack_id: str,
        pack_version: str,
        ledger: RepresentationLedger,
        target_representations: list[str],
        requirement_id: str,
        options: dict[str, object] | None = None,
    ) -> tuple[WorkflowPlan, CapabilityPlanResult]:
        manifest = self.registry.load(pack_id, pack_version)
        gate = self.registry.gate(manifest)
        options = dict(options or {})
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
        for method in selected:
            tool_name = method.tool_contract_ref.split(":", 1)[0] if method.tool_contract_ref else None
            nodes.append(
                WorkflowNode(
                    node_id=method.method_id,
                    name=method.method_id,
                    operation=method.method_id,
                    tool_name=tool_name,
                    tool_contract_id=method.tool_contract_ref or "human-review:1.0",
                    input_artifacts=[item.representation_id for item in method.consumes],
                    output_artifacts=[item.representation_id for item in method.produces],
                    parameters=dict(options.get(method.method_id, {})) if isinstance(options.get(method.method_id), dict) else {},
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
        plan_id = "cap-plan-" + _digest({"ledger": ledger.ledger_id, "targets": target_representations, "methods": [item.method_id for item in selected], "options": options})[:16]
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


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
