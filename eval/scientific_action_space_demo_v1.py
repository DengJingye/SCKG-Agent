from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.representation_models import RepresentationLedger, RepresentationRecord
from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    ConformanceBundle,
    DerivedRelation,
    InputPort,
    OperatorRevision,
    RepresentationConstraint,
)
from engine.capability_planner import CapabilityPlanCompiler


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ROOT = (
    REPOSITORY_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_uat_decision_rules"
)

LEIDEN_OPERATOR = "operator-revision:scanpy.tl.leiden:1.11.2:uat-corrected"
NEIGHBORS_OPERATOR = "operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected"
HARMONY_OPERATOR = "operator-revision:harmony.RunHarmony:2.0.5:uat-corrected"
SCRUBLET_OPERATOR = (
    "operator-revision:scrublet.Scrublet.scrub_doublets:0.2.3:uat-corrected"
)


_REPRESENTATION_TYPE_BY_LEDGER_ID = {
    "raw_counts": "representation-type:raw_umi_counts",
    "filtered_counts": "representation-type:raw_umi_counts",
    "library_size_normalized": "representation-type:expression_matrix",
    "log1p_normalized": "representation-type:expression_matrix",
    "scaled_hvg": "representation-type:expression_matrix",
    "pca": "representation-type:pca_coordinates",
    "integrated_representation": "representation-type:cell_embedding",
    "neighbor_graph": "representation-type:neighbor_graph",
}

_VALUE_STATES_BY_LEDGER_ID = {
    "raw_counts": {"integer_like_counts"},
    "filtered_counts": {"integer_like_counts"},
    "library_size_normalized": {"state_declared"},
    "log1p_normalized": {"state_declared"},
    "scaled_hvg": {"state_declared"},
    "pca": {"dimension_reduced"},
    "integrated_representation": {"dimension_reduced"},
    "neighbor_graph": {"graph_constructed"},
}

_TRANSFORMATIONS_BY_LEDGER_ID = {
    "library_size_normalized": {"normalized"},
    "log1p_normalized": {"normalized", "log1p"},
    "scaled_hvg": {"normalized", "log1p", "scaled"},
    "integrated_representation": {"integrated", "batch_corrected_embedding"},
}

_ACTION_BY_OPERATOR = {
    LEIDEN_OPERATOR: "scanpy_core.leiden",
    NEIGHBORS_OPERATOR: "scanpy_core.neighbors_integrated",
    SCRUBLET_OPERATOR: "scrublet.scrub_doublets",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class _InstanceView:
    record: RepresentationRecord
    representation_type_id: str
    value_states: frozenset[str]
    transformations: frozenset[str]
    modalities: frozenset[str]
    component_roles: frozenset[str]
    metadata: dict[str, Any]
    observation_alignment: str
    feature_alignment: str


class ScientificActionSpaceDemo:
    """Evaluation-only bridge from a frozen KG candidate to the existing planner.

    The candidate controls scientific applicability. The existing
    ``CapabilityPlanCompiler`` is invoked only after that gate passes, so this
    harness demonstrates the intended boundary without promoting the candidate
    or changing production planning.
    """

    def __init__(
        self,
        *,
        candidate_root: Path = CANDIDATE_ROOT,
        planner: CapabilityPlanCompiler | None = None,
    ) -> None:
        self.candidate_root = candidate_root
        self.manifest = _read_json(candidate_root / "manifest.json")
        self._verify_frozen_artifacts()
        self.bundle = ConformanceBundle.model_validate(
            _read_json(candidate_root / "conformance_bundle.json")
        )
        self.operators = {
            item.entity_id: item
            for item in self.bundle.entities
            if isinstance(item, OperatorRevision)
        }
        self.constraints = {
            item.constraint_id: item for item in self.bundle.representation_constraints
        }
        self.scopes = {item.scope_id: item for item in self.bundle.scopes}
        self.claims = {
            item.claim_revision_id: item for item in self.bundle.atomic_claims
        }
        self.relations = {
            item.relation_id: item for item in self.bundle.derived_relations
        }
        self.bindings = {
            item["claim_revision_id"]: item
            for item in _read_jsonl(candidate_root / "exact_evidence_bindings.jsonl")
        }
        self.evidence_spans = {
            item["evidence_span_id"]: item
            for item in _read_jsonl(
                candidate_root / "authoritative_evidence_spans.jsonl"
            )
        }
        self.planner = planner or CapabilityPlanCompiler()

    def _verify_frozen_artifacts(self) -> None:
        if self.manifest.get("status") != "candidate_only_not_promoted":
            raise ValueError("scientific KG demo requires the frozen candidate-only slice")
        if any(
            self.manifest.get(flag)
            for flag in (
                "canonical_kg_modified",
                "frozen_core_modified",
                "retrieval_index_rebuilt",
                "runtime_modified",
            )
        ):
            raise ValueError("scientific KG candidate isolation invariant failed")
        for name in (
            "conformance_bundle.json",
            "exact_evidence_bindings.jsonl",
            "authoritative_evidence_spans.jsonl",
        ):
            expected = self.manifest["artifacts"][name]
            if _sha256(self.candidate_root / name) != expected:
                raise ValueError(f"frozen scientific KG artifact digest mismatch:{name}")

    def assess(
        self,
        *,
        scenario_id: str,
        operator_id: str,
        ledger: RepresentationLedger,
    ) -> dict[str, Any]:
        operator = self.operators[operator_id]
        instances = [self._instance(record, ledger) for record in ledger.records]
        port_results = [
            self._assess_port(port=port, instances=instances)
            for port in operator.input_ports
        ]
        applicable = all(result["satisfied"] for result in port_results)
        used_record_ids = {
            record_id
            for result in port_results
            for record_id in result["matched_record_ids"]
        }
        used_records = [
            record for record in ledger.records if record.representation_record_id in used_record_ids
        ]
        matching_relations = self._matching_relations(
            operator_id=operator_id,
            used_records=used_records,
        )
        claim_ids = self._consulted_claim_ids(operator_id, matching_relations)
        action_id = _ACTION_BY_OPERATOR[operator_id]
        action = {
            "action_id": action_id,
            "operator_revision_id": operator_id,
            "scope_id": operator.scope_id,
        }
        if applicable:
            action["planner_projection"] = self._planner_projection(
                operator_id=operator_id,
                ledger=ledger,
            )
            applicable_actions = [action]
            blocked_actions: list[dict[str, Any]] = []
        else:
            reason_codes = sorted(
                {
                    reason
                    for result in port_results
                    for reason in result["reason_codes"]
                }
            )
            blocked_actions = [{**action, "reason_codes": reason_codes}]
            applicable_actions = []

        return {
            "scenario_id": scenario_id,
            "input_representation_ledger_state": self._ledger_state(ledger),
            "kg_facts_requirements_consulted": {
                "operator_revision_id": operator_id,
                "scope": self._scope(self.scopes[operator.scope_id]),
                "input_ports": [
                    {
                        "input_port_id": result["input_port_id"],
                        "requirement_ids": result["requirement_ids"],
                        "constraint_ids": result["constraint_ids"],
                        "satisfied": result["satisfied"],
                    }
                    for result in port_results
                ],
                "claim_revision_ids": claim_ids,
                "derived_relation_ids": [item.relation_id for item in matching_relations],
            },
            "applicable_actions": applicable_actions,
            "blocked_actions": blocked_actions,
            "reused_representations": [
                {
                    "representation_record_id": record.representation_record_id,
                    "representation_id": record.representation_id,
                    "slot": record.slot,
                }
                for record in used_records
            ],
            "missing_requirements": [
                {
                    "input_port_id": result["input_port_id"],
                    "requirement_ids": result["requirement_ids"],
                    "constraint_ids": result["constraint_ids"],
                    "required_representation_type_ids": result[
                        "required_representation_type_ids"
                    ],
                    "reason_codes": result["reason_codes"],
                    "rejected_records": result["rejected_records"],
                }
                for result in port_results
                if not result["satisfied"]
            ],
            "evidence_provenance": self._evidence_provenance(claim_ids),
        }

    def _instance(
        self,
        record: RepresentationRecord,
        ledger: RepresentationLedger,
    ) -> _InstanceView:
        metadata = dict(record.metadata)
        representation_type_id = str(
            metadata.get("representation_type_id")
            or _REPRESENTATION_TYPE_BY_LEDGER_ID.get(record.representation_id, "")
        )
        value_states = set(metadata.get("value_states", []))
        value_states.update(_VALUE_STATES_BY_LEDGER_ID.get(record.representation_id, set()))
        if record.status == "current" and record.validated:
            value_states.add("fresh")
        transformations = set(metadata.get("transformations", []))
        transformations.update(
            _TRANSFORMATIONS_BY_LEDGER_ID.get(record.representation_id, set())
        )
        synthesized_metadata = dict(metadata)
        if record.cell_index_hash:
            synthesized_metadata.setdefault(
                "ordered_observation_ids", record.cell_index_hash
            )
        if record.gene_index_hash:
            synthesized_metadata.setdefault("ordered_feature_ids", record.gene_index_hash)
        synthesized_metadata.setdefault("source_slot", record.slot)
        if record.parameter_hash:
            synthesized_metadata.setdefault(
                "semantic_parameter_signature", record.parameter_hash
            )
        return _InstanceView(
            record=record,
            representation_type_id=representation_type_id,
            value_states=frozenset(value_states),
            transformations=frozenset(transformations),
            modalities=frozenset(metadata.get("modalities", ["rna"])),
            component_roles=frozenset(metadata.get("component_roles", [])),
            metadata=synthesized_metadata,
            observation_alignment=(
                "same_observations"
                if record.cell_index_hash == ledger.cell_index_hash
                else "misaligned"
            ),
            feature_alignment=(
                "same_features"
                if record.gene_index_hash == ledger.gene_index_hash
                else "not_applicable"
                if record.gene_index_hash is None
                else "misaligned"
            ),
        )

    def _assess_port(
        self,
        *,
        port: InputPort,
        instances: list[_InstanceView],
    ) -> dict[str, Any]:
        requirement_matches: list[tuple[str, list[str], list[_InstanceView]]] = []
        rejected: dict[str, set[str]] = {}
        for requirement in port.requirements:
            matched: list[_InstanceView] = []
            for instance in instances:
                failures = [
                    failure
                    for constraint_id in requirement.representation_constraint_ids
                    for failure in self._constraint_failures(
                        self.constraints[constraint_id], instance
                    )
                ]
                if any(
                    not self._constraint_failures(self.constraints[constraint_id], instance)
                    for constraint_id in requirement.representation_constraint_ids
                ):
                    matched.append(instance)
                else:
                    rejected.setdefault(
                        instance.record.representation_record_id, set()
                    ).update(failures)
            requirement_matches.append(
                (
                    requirement.requirement_id,
                    list(requirement.representation_constraint_ids),
                    matched,
                )
            )

        if port.min_cardinality == 0 and not instances:
            satisfied = True
            selected: list[_InstanceView] = []
        elif port.requirement_combination == "any_of":
            selected = next(
                (matched for _, _, matched in requirement_matches if matched), []
            )
            satisfied = bool(selected)
        else:
            mandatory = [
                (requirement, matched)
                for requirement, (_, _, matched) in zip(
                    port.requirements, requirement_matches, strict=True
                )
                if requirement.level != "optional"
            ]
            satisfied = all(matched for _, matched in mandatory)
            selected = [
                item
                for _, _, matches in requirement_matches
                for item in matches[:1]
            ] if satisfied else []

        reason_codes = [] if satisfied else sorted(
            {
                "missing_compatible_representation",
                *(
                    reason
                    for reasons in rejected.values()
                    for reason in reasons
                ),
            }
        )
        return {
            "input_port_id": port.input_port_id,
            "requirement_ids": [item[0] for item in requirement_matches],
            "constraint_ids": sorted(
                {constraint_id for item in requirement_matches for constraint_id in item[1]}
            ),
            "required_representation_type_ids": sorted(
                {
                    self.constraints[constraint_id].representation_type_id
                    for item in requirement_matches
                    for constraint_id in item[1]
                }
            ),
            "satisfied": satisfied,
            "matched_record_ids": sorted(
                {item.record.representation_record_id for item in selected}
            ),
            "reason_codes": reason_codes,
            "rejected_records": [
                {
                    "representation_record_id": record_id,
                    "reason_codes": sorted(reasons),
                }
                for record_id, reasons in sorted(rejected.items())
            ],
        }

    @staticmethod
    def _constraint_failures(
        constraint: RepresentationConstraint,
        instance: _InstanceView,
    ) -> list[str]:
        failures: list[str] = []
        record = instance.record
        if record.status != "current":
            failures.append("representation_stale")
        if not record.validated:
            failures.append("representation_not_validated")
        if instance.representation_type_id != constraint.representation_type_id:
            failures.append(
                f"representation_type_mismatch:{constraint.representation_type_id}"
            )
        for state in sorted(
            set(constraint.required_value_states) - set(instance.value_states)
        ):
            failures.append(f"missing_value_state:{state}")
        for transform in sorted(
            set(constraint.required_transformations) - set(instance.transformations)
        ):
            failures.append(f"missing_transformation:{transform}")
        for transform in sorted(
            set(constraint.forbidden_transformations) & set(instance.transformations)
        ):
            failures.append(f"forbidden_transformation:{transform}")
        for modality in sorted(
            set(constraint.required_modalities) - set(instance.modalities)
        ):
            failures.append(f"missing_modality:{modality}")
        for key in sorted(set(constraint.required_metadata) - set(instance.metadata)):
            failures.append(f"missing_metadata:{key}")
        for role in sorted(
            set(constraint.required_component_roles) - set(instance.component_roles)
        ):
            failures.append(f"missing_component:{role}")
        if (
            constraint.observation_alignment != "not_applicable"
            and instance.observation_alignment != constraint.observation_alignment
        ):
            failures.append("observation_identity_mismatch")
        if (
            constraint.feature_alignment != "not_applicable"
            and instance.feature_alignment != constraint.feature_alignment
        ):
            failures.append("feature_identity_mismatch")
        return failures

    def _matching_relations(
        self,
        *,
        operator_id: str,
        used_records: list[RepresentationRecord],
    ) -> list[DerivedRelation]:
        producer_ids = {
            str(record.metadata.get("producer_operator_revision_id"))
            for record in used_records
            if record.metadata.get("producer_operator_revision_id")
        }
        relations = [
            relation
            for relation in self.relations.values()
            if relation.source_id == operator_id
            and relation.relation == "CONSUMES"
        ]
        relations.extend(
            relation
            for relation in self.relations.values()
            if relation.relation == "CAN_FEED"
            and relation.target_id == operator_id
            and relation.source_id in producer_ids
        )
        return sorted(relations, key=lambda item: item.relation_id)

    def _consulted_claim_ids(
        self,
        operator_id: str,
        relations: list[DerivedRelation],
    ) -> list[str]:
        claim_ids = {
            claim.claim_revision_id
            for claim in self.claims.values()
            if claim.subject_id == operator_id
        }
        claim_ids.update(
            claim_id
            for relation in relations
            for claim_id in relation.derived_from_claim_revision_ids
        )
        return sorted(claim_ids)

    def _evidence_provenance(
        self,
        claim_ids: list[str],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for claim_id in claim_ids:
            binding = self.bindings.get(claim_id)
            if not binding:
                continue
            for span_id in binding["evidence_span_ids"]:
                span = self.evidence_spans[span_id]
                evidence.append(
                    {
                        "claim_revision_id": claim_id,
                        "claim_text": self.claims[claim_id].claim_text,
                        "evidence_span_id": span_id,
                        "source_revision_id": span["source_revision_id"],
                        "locator": span["locator"],
                        "content_hash": span["content_hash"],
                        "source_bound": span["source_bound"],
                    }
                )
        return evidence

    def _planner_projection(
        self,
        *,
        operator_id: str,
        ledger: RepresentationLedger,
    ) -> dict[str, Any]:
        if operator_id == LEIDEN_OPERATOR:
            targets = ["cluster_labels"]
            options: dict[str, object] = {}
        elif operator_id == NEIGHBORS_OPERATOR:
            targets = ["neighbor_graph"]
            options = {"preferred_method_ids": ["scanpy_core.neighbors_integrated"]}
        else:
            return {"status": "not_projected", "reason": "candidate_action_not_bound"}
        plan, result = self.planner.compile(
            pack_id="scanpy_core",
            pack_version="1.0.0",
            ledger=ledger,
            target_representations=targets,
            requirement_id=f"scientific-action-space-demo:{operator_id}",
            options=options,
        )
        return {
            "status": "planned" if not result.blocked else "blocked",
            "workflow_plan_id": plan.plan_id,
            "planned_method_ids": result.planned_method_ids,
            "reused_representation_ids": result.reused_representation_ids,
            "blocking_reasons": result.blocking_reasons,
        }

    @staticmethod
    def _scope(scope: ApplicabilityScope) -> dict[str, Any]:
        return {
            "scope_id": scope.scope_id,
            "modalities": scope.modalities,
            "observation_units": scope.observation_units,
            "task_ids": scope.task_ids,
            "study_design_constraints": scope.study_design_constraints,
            "version_constraints": [
                item.model_dump(mode="json") for item in scope.version_constraints
            ],
        }

    @staticmethod
    def _ledger_state(ledger: RepresentationLedger) -> dict[str, Any]:
        return {
            "ledger_id": ledger.ledger_id,
            "profile_id": ledger.profile_id,
            "cell_index_hash": ledger.cell_index_hash,
            "gene_index_hash": ledger.gene_index_hash,
            "records": [
                {
                    "representation_record_id": record.representation_record_id,
                    "representation_id": record.representation_id,
                    "value_state": record.value_state,
                    "slot": record.slot,
                    "status": getattr(record.status, "value", record.status),
                    "validated": record.validated,
                    "cell_index_hash": record.cell_index_hash,
                    "gene_index_hash": record.gene_index_hash,
                    "parameter_hash": record.parameter_hash,
                    "provenance": record.provenance,
                    "metadata": record.metadata,
                    "stale_reasons": record.stale_reasons,
                }
                for record in ledger.records
            ],
        }


def _record(
    representation_record_id: str,
    representation_id: str,
    value_state: str,
    *,
    cell_hash: str,
    gene_hash: str | None = None,
    parameter_hash: str | None = None,
    provenance: list[str],
    metadata: dict[str, Any],
    status: str = "current",
    validated: bool = True,
    stale_reasons: list[str] | None = None,
) -> RepresentationRecord:
    return RepresentationRecord(
        representation_record_id=representation_record_id,
        representation_id=representation_id,
        schema_version="1.0",
        value_state=value_state,
        slot=f"demo/{representation_id}",
        provenance=provenance,
        cell_index_hash=cell_hash,
        gene_index_hash=gene_hash,
        parameter_hash=parameter_hash,
        status=status,
        validated=validated,
        metadata=metadata,
        stale_reasons=stale_reasons or [],
    )


def _ledger(
    ledger_id: str,
    records: list[RepresentationRecord],
    *,
    cell_hash: str,
    gene_hash: str,
) -> RepresentationLedger:
    return RepresentationLedger(
        ledger_id=ledger_id,
        profile_id=f"profile:{ledger_id}",
        source_artifact_id=f"artifact:{ledger_id}",
        source_hash="f" * 64,
        cell_index_hash=cell_hash,
        gene_index_hash=gene_hash,
        records=records,
    )


def demo_scenarios() -> list[tuple[str, str, RepresentationLedger]]:
    cell_hash = "c" * 64
    gene_hash = "g" * 64
    parameter_hash = "p" * 64
    graph_metadata = {
        "component_roles": ["connectivities", "distances", "parameters"],
        "lineage_id": "lineage:pbmc-demo",
        "neighbors_key": "neighbors",
        "connectivities_key": "connectivities",
        "distances_key": "distances",
        "producer_operator_revision_id": NEIGHBORS_OPERATOR,
    }
    valid_graph = _record(
        "rep:demo:neighbor-graph:valid",
        "neighbor_graph",
        "graph",
        cell_hash=cell_hash,
        parameter_hash=parameter_hash,
        provenance=["neighbor_representation_bound"],
        metadata=graph_metadata,
    )
    stale_graph = _record(
        "rep:demo:neighbor-graph:stale",
        "neighbor_graph",
        "graph",
        cell_hash=cell_hash,
        parameter_hash=parameter_hash,
        provenance=["neighbor_representation_bound"],
        metadata=graph_metadata,
        status="stale",
        stale_reasons=["upstream_representation_changed"],
    )
    misaligned_graph = _record(
        "rep:demo:neighbor-graph:misaligned",
        "neighbor_graph",
        "graph",
        cell_hash="m" * 64,
        parameter_hash=parameter_hash,
        provenance=["neighbor_representation_bound"],
        metadata=graph_metadata,
    )
    harmony_embedding = _record(
        "rep:demo:harmony-embedding",
        "integrated_representation",
        "real_continuous",
        cell_hash=cell_hash,
        parameter_hash="h" * 64,
        provenance=["validated_integration_action", "harmony.RunHarmony"],
        metadata={
            "batch_key": "donor",
            "lineage_id": "lineage:pbmc-demo",
            "producer_operator_revision_id": HARMONY_OPERATOR,
        },
    )
    normalized = _record(
        "rep:demo:normalized-expression",
        "library_size_normalized",
        "nonnegative_continuous",
        cell_hash=cell_hash,
        gene_hash=gene_hash,
        provenance=["normalize_total"],
        metadata={"lineage_id": "lineage:pbmc-demo"},
    )
    integrated = _record(
        "rep:demo:integrated-expression",
        "integrated_representation",
        "real_continuous",
        cell_hash=cell_hash,
        parameter_hash="i" * 64,
        provenance=["validated_integration_action"],
        metadata={
            "batch_key": "donor",
            "lineage_id": "lineage:pbmc-demo",
        },
    )
    return [
        (
            "valid-neighbor-graph-to-leiden",
            LEIDEN_OPERATOR,
            _ledger(
                "ledger:demo:valid-graph",
                [valid_graph],
                cell_hash=cell_hash,
                gene_hash=gene_hash,
            ),
        ),
        (
            "stale-or-misaligned-graph",
            LEIDEN_OPERATOR,
            _ledger(
                "ledger:demo:invalid-graph",
                [stale_graph, misaligned_graph],
                cell_hash=cell_hash,
                gene_hash=gene_hash,
            ),
        ),
        (
            "harmony-embedding-to-neighbors",
            NEIGHBORS_OPERATOR,
            _ledger(
                "ledger:demo:harmony",
                [harmony_embedding],
                cell_hash=cell_hash,
                gene_hash=gene_hash,
            ),
        ),
        (
            "scrublet-rejects-transformed-expression",
            SCRUBLET_OPERATOR,
            _ledger(
                "ledger:demo:scrublet-block",
                [normalized, integrated],
                cell_hash=cell_hash,
                gene_hash=gene_hash,
            ),
        ),
    ]


def run_demo() -> list[dict[str, Any]]:
    demo = ScientificActionSpaceDemo()
    return [
        demo.assess(scenario_id=scenario_id, operator_id=operator_id, ledger=ledger)
        for scenario_id, operator_id, ledger in demo_scenarios()
    ]


def main() -> None:
    print(json.dumps(run_demo(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
