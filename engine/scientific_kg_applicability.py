from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.representation_models import (
    RepresentationLedger,
    RepresentationRecord,
    ScientificApplicabilityResult,
    ScientificEvidenceReference,
    ScientificMissingRequirement,
)
from core.scientific_knowledge_conformance_models import (
    ConformanceBundle,
    DerivedRelation,
    InputPort,
    OperatorRevision,
    RepresentationConstraint,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_ROOT = (
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


@dataclass(frozen=True)
class _ActionBinding:
    operator_revision_id: str
    representation_ids: frozenset[str]
    decision_scope: str


_ACTION_BINDINGS = {
    "scanpy_core.leiden": _ActionBinding(
        operator_revision_id=LEIDEN_OPERATOR,
        representation_ids=frozenset({"neighbor_graph"}),
        decision_scope="existing_representation_reuse",
    ),
    "scanpy_core.neighbors_integrated": _ActionBinding(
        operator_revision_id=NEIGHBORS_OPERATOR,
        representation_ids=frozenset({"integrated_representation"}),
        decision_scope="existing_representation_reuse",
    ),
    "scanpy_core.doublet_detection_action": _ActionBinding(
        operator_revision_id=SCRUBLET_OPERATOR,
        representation_ids=frozenset(
            {
                "raw_counts",
                "filtered_counts",
                "library_size_normalized",
                "log1p_normalized",
                "scaled_hvg",
                "integrated_representation",
            }
        ),
        decision_scope="action_applicability",
    ),
}

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


class ScientificKGApplicability:
    """Narrow candidate-KG adapter for validated planner decisions.

    Returning ``None`` means the candidate slice does not govern that action or
    that a legacy representation lacks the explicit binding metadata required
    by the validated slice. In that case the existing Capability Pack behavior
    remains authoritative.
    """

    def __init__(self, *, candidate_root: Path = DEFAULT_CANDIDATE_ROOT) -> None:
        self.candidate_root = Path(candidate_root)
        manifest = _read_json(self.candidate_root / "manifest.json")
        _verify_candidate(manifest, self.candidate_root)
        bundle = ConformanceBundle.model_validate(
            _read_json(self.candidate_root / "conformance_bundle.json")
        )
        self.operators = {
            item.entity_id: item
            for item in bundle.entities
            if isinstance(item, OperatorRevision)
        }
        self.constraints = {
            item.constraint_id: item for item in bundle.representation_constraints
        }
        self.claims = {
            item.claim_revision_id: item for item in bundle.atomic_claims
        }
        self.relations = {
            item.relation_id: item for item in bundle.derived_relations
        }
        self.bindings = {
            item["claim_revision_id"]: item
            for item in _read_jsonl(
                self.candidate_root / "exact_evidence_bindings.jsonl"
            )
        }
        self.evidence_spans = {
            item["evidence_span_id"]: item
            for item in _read_jsonl(
                self.candidate_root / "authoritative_evidence_spans.jsonl"
            )
        }

    def assess(
        self,
        *,
        action_id: str,
        ledger: RepresentationLedger,
    ) -> ScientificApplicabilityResult | None:
        binding = _ACTION_BINDINGS.get(action_id)
        if binding is None:
            return None
        records = [
            record
            for record in ledger.records
            if record.representation_id in binding.representation_ids
        ]
        if not records or not _candidate_binding_is_explicit(action_id, records, ledger):
            return None

        operator = self.operators[binding.operator_revision_id]
        instances = [self._instance(record, ledger) for record in records]
        port_results = [
            self._assess_port(port=port, instances=instances)
            for port in operator.input_ports
        ]
        applicable = all(item["satisfied"] for item in port_results)
        reusable_record_ids = sorted(
            {
                record_id
                for item in port_results
                for record_id in item["matched_record_ids"]
            }
        )
        reusable_records = [
            record
            for record in records
            if record.representation_record_id in reusable_record_ids
        ]
        relations = self._matching_relations(
            operator_revision_id=binding.operator_revision_id,
            used_records=reusable_records,
        )
        claim_ids = self._decision_claim_ids(
            binding.operator_revision_id,
            relations,
        )
        missing = [
            ScientificMissingRequirement(
                input_port_id=item["input_port_id"],
                requirement_ids=item["requirement_ids"],
                representation_constraint_ids=item["constraint_ids"],
                required_representation_type_ids=item[
                    "required_representation_type_ids"
                ],
                reason_codes=item["reason_codes"],
                rejected_representation_record_ids=sorted(
                    item["rejected_records"]
                ),
            )
            for item in port_results
            if not item["satisfied"]
        ]
        reasons = sorted(
            {
                reason
                for item in missing
                for reason in item.reason_codes
            }
        )
        return ScientificApplicabilityResult(
            action_id=action_id,
            operator_revision_id=binding.operator_revision_id,
            decision_scope=binding.decision_scope,
            applicable=applicable,
            blocked=not applicable,
            assessed_representation_ids=sorted(
                {record.representation_id for record in records}
            ),
            reusable_representation_ids=sorted(
                {record.representation_id for record in reusable_records}
            ),
            reusable_representation_record_ids=reusable_record_ids,
            missing_requirements=missing,
            incompatibility_reasons=reasons,
            evidence_references=self._evidence_references(claim_ids),
        )

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
        value_states.update(
            _VALUE_STATES_BY_LEDGER_ID.get(record.representation_id, set())
        )
        if record.status == "current" and record.validated:
            value_states.add("fresh")
        transformations = set(metadata.get("transformations", []))
        transformations.update(
            _TRANSFORMATIONS_BY_LEDGER_ID.get(record.representation_id, set())
        )
        synthesized = dict(metadata)
        if record.cell_index_hash:
            synthesized.setdefault("ordered_observation_ids", record.cell_index_hash)
        if record.gene_index_hash:
            synthesized.setdefault("ordered_feature_ids", record.gene_index_hash)
        synthesized.setdefault("source_slot", record.slot)
        if record.parameter_hash:
            synthesized.setdefault(
                "semantic_parameter_signature", record.parameter_hash
            )
        return _InstanceView(
            record=record,
            representation_type_id=representation_type_id,
            value_states=frozenset(value_states),
            transformations=frozenset(transformations),
            modalities=frozenset(metadata.get("modalities", ["rna"])),
            component_roles=frozenset(metadata.get("component_roles", [])),
            metadata=synthesized,
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
        matches: list[tuple[str, list[str], list[_InstanceView]]] = []
        rejected: dict[str, set[str]] = {}
        for requirement in port.requirements:
            matched: list[_InstanceView] = []
            for instance in instances:
                by_constraint = [
                    self._constraint_failures(
                        self.constraints[constraint_id], instance
                    )
                    for constraint_id in requirement.representation_constraint_ids
                ]
                if any(not failures for failures in by_constraint):
                    matched.append(instance)
                else:
                    rejected.setdefault(
                        instance.record.representation_record_id, set()
                    ).update(
                        failure
                        for failures in by_constraint
                        for failure in failures
                    )
            matches.append(
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
            selected = next((items for _, _, items in matches if items), [])
            satisfied = bool(selected)
        else:
            mandatory = [
                matched
                for requirement, (_, _, matched) in zip(
                    port.requirements, matches, strict=True
                )
                if requirement.level != "optional"
            ]
            satisfied = all(mandatory)
            selected = [item for _, _, items in matches for item in items[:1]] if satisfied else []

        reasons = [] if satisfied else sorted(
            {
                "missing_compatible_representation",
                *(reason for values in rejected.values() for reason in values),
            }
        )
        return {
            "input_port_id": port.input_port_id,
            "requirement_ids": [item[0] for item in matches],
            "constraint_ids": sorted(
                {constraint_id for item in matches for constraint_id in item[1]}
            ),
            "required_representation_type_ids": sorted(
                {
                    self.constraints[constraint_id].representation_type_id
                    for item in matches
                    for constraint_id in item[1]
                }
            ),
            "satisfied": satisfied,
            "matched_record_ids": sorted(
                {item.record.representation_record_id for item in selected}
            ),
            "reason_codes": reasons,
            "rejected_records": {
                record_id: sorted(values)
                for record_id, values in sorted(rejected.items())
            },
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
        failures.extend(
            f"missing_value_state:{state}"
            for state in sorted(
                set(constraint.required_value_states) - set(instance.value_states)
            )
        )
        failures.extend(
            f"missing_transformation:{transform}"
            for transform in sorted(
                set(constraint.required_transformations)
                - set(instance.transformations)
            )
        )
        failures.extend(
            f"forbidden_transformation:{transform}"
            for transform in sorted(
                set(constraint.forbidden_transformations)
                & set(instance.transformations)
            )
        )
        failures.extend(
            f"missing_modality:{modality}"
            for modality in sorted(
                set(constraint.required_modalities) - set(instance.modalities)
            )
        )
        failures.extend(
            f"missing_metadata:{key}"
            for key in sorted(
                set(constraint.required_metadata) - set(instance.metadata)
            )
        )
        failures.extend(
            f"missing_component:{role}"
            for role in sorted(
                set(constraint.required_component_roles)
                - set(instance.component_roles)
            )
        )
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
        operator_revision_id: str,
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
            if relation.source_id == operator_revision_id
            and relation.relation == "CONSUMES"
        ]
        relations.extend(
            relation
            for relation in self.relations.values()
            if relation.relation == "CAN_FEED"
            and relation.target_id == operator_revision_id
            and relation.source_id in producer_ids
        )
        return sorted(relations, key=lambda item: item.relation_id)

    def _decision_claim_ids(
        self,
        operator_revision_id: str,
        relations: list[DerivedRelation],
    ) -> list[str]:
        """Project evidence for the decision-bearing proposition only.

        Input/requirement claims owned by the target operator establish local
        applicability.  A cross-ecosystem CAN_FEED bridge additionally needs
        the producer's output claim.  Merely sharing an operator with the
        action is not enough: output, limitation, and project-guardrail claims
        do not justify an input-side applicability decision.
        """

        input_predicates = {
            "accepts_optional_representation",
            "accepts_representation",
            "requires_compatibility",
            "requires_representation",
        }
        claim_ids = {
            claim.claim_revision_id
            for claim in self.claims.values()
            if claim.subject_id == operator_revision_id
            and claim.predicate in input_predicates
        }
        claim_ids.update(
            claim_id
            for relation in relations
            if relation.relation == "CAN_FEED"
            and _operator_ecosystem(relation.source_id)
            != _operator_ecosystem(relation.target_id)
            for claim_id in relation.derived_from_claim_revision_ids
            if (
                (claim := self.claims.get(claim_id)) is not None
                and claim.subject_id == relation.source_id
                and claim.predicate == "produces"
            )
        )
        return sorted(claim_ids)

    def _evidence_references(
        self,
        claim_ids: list[str],
    ) -> list[ScientificEvidenceReference]:
        references: list[ScientificEvidenceReference] = []
        for claim_id in claim_ids:
            binding = self.bindings.get(claim_id)
            if not binding:
                continue
            for span_id in binding["evidence_span_ids"]:
                span = self.evidence_spans[span_id]
                if not span["source_bound"]:
                    continue
                references.append(
                    ScientificEvidenceReference(
                        claim_revision_id=claim_id,
                        evidence_span_id=span_id,
                        source_revision_id=span["source_revision_id"],
                        locator=span["locator"],
                        content_hash=span["content_hash"],
                    )
                )
        return sorted(
            references,
            key=lambda item: (item.claim_revision_id, item.evidence_span_id),
        )


@lru_cache(maxsize=1)
def default_scientific_kg_applicability() -> ScientificKGApplicability:
    return ScientificKGApplicability()


def _operator_ecosystem(operator_revision_id: str) -> str:
    identity = operator_revision_id.removeprefix("operator-revision:")
    return identity.split(".", 1)[0].split(":", 1)[0]


def _candidate_binding_is_explicit(
    action_id: str,
    records: list[RepresentationRecord],
    ledger: RepresentationLedger,
) -> bool:
    if action_id == "scanpy_core.doublet_detection_action":
        raw_records = [
            record
            for record in records
            if record.representation_id in {"raw_counts", "filtered_counts"}
        ]
        if not raw_records:
            return True
        return any(
            record.metadata.get("capture_unit_id")
            and record.cell_index_hash == ledger.cell_index_hash
            and record.gene_index_hash == ledger.gene_index_hash
            for record in raw_records
        )
    if any(
        record.status != "current"
        or not record.validated
        or record.cell_index_hash != ledger.cell_index_hash
        for record in records
    ):
        return True
    if action_id == "scanpy_core.leiden":
        return any(
            record.parameter_hash
            and record.metadata.get("lineage_id")
            and record.metadata.get("neighbors_key")
            and record.metadata.get("connectivities_key")
            for record in records
        )
    if action_id == "scanpy_core.neighbors_integrated":
        return any(
            record.parameter_hash
            and record.metadata.get("lineage_id")
            and record.metadata.get("producer_operator_revision_id") == HARMONY_OPERATOR
            for record in records
        )
    return False


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


def _verify_candidate(manifest: dict[str, Any], root: Path) -> None:
    if manifest.get("status") != "candidate_only_not_promoted":
        raise ValueError("scientific applicability requires the frozen candidate slice")
    if any(
        manifest.get(flag)
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
        if _sha256(root / name) != manifest["artifacts"][name]:
            raise ValueError(f"frozen scientific KG artifact digest mismatch:{name}")
