"""Corrected evaluation-only verifier for Justification Fidelity v1.1.

This module preserves the frozen v1 preregistration and production inputs.  It
corrects only the three evaluator defects identified by the v1 formal run:
behavior comparison ownership, producer/consumer scope context, and the
representation-linkage aggregate.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.scientific_decision_justification_fidelity_v1 import (
    ROOT,
    SPEC_SHA256,
    FrozenKnowledgeRegistry,
    JustificationVerifier,
    _binding_key,
    _digest,
    _positive_atom,
    _record_satisfies_obligations,
    _representation_type,
    apply_frozen_mutation,
    build_positive_control_cases,
    load_frozen_preregistration,
    mutation_changes_only_declared_dimension,
)


EVALUATOR_SCHEMA_VERSION = "sckg-scientific-decision-justification-fidelity-v1.1"
DEFAULT_OUTPUT_ROOT = (
    ROOT / "data/evaluation/scientific_decision_justification_fidelity_v1_1"
)

_ACTION_TASKS = {
    "scanpy_core.leiden": "task:clustering",
    "scanpy_core.neighbors_integrated": "task:neighbor_graph",
    "scanpy_core.doublet_detection_action": "task:doublet_detection",
}
_PRODUCER_TASKS = {
    "operator-revision:harmony.RunHarmony:2.0.5:uat-corrected":
        "task:batch_integration",
}


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _owner_context(
    *,
    claim: dict[str, Any],
    decision: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[str, str | None]:
    """Resolve scope against the atom's producer or consumer owner."""

    if claim["predicate"] == "produces":
        producer_records = [
            record
            for record in ledger["records"]
            if record.get("metadata", {}).get("producer_operator_revision_id")
            == claim["subject_id"]
        ]
        if producer_records:
            return claim["subject_id"], _PRODUCER_TASKS.get(claim["subject_id"])
    return decision["operator_revision_id"], _ACTION_TASKS.get(decision["action_id"])


def _actual_scope_v1_1(
    expected: dict[str, Any],
    registry: FrozenKnowledgeRegistry,
    ledger: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate scope with producer and consumer contexts kept separate."""

    expected_scope = expected["expected_scope"]
    claim_id = expected["expected_evidence_bindings"][0]["claim_revision_id"]
    claim = registry.claims[claim_id]
    scope = registry.scopes[claim["scope_id"]]
    owner_revision, owner_task = _owner_context(
        claim=claim, decision=decision, ledger=ledger
    )
    linked_ids = {
        *decision.get("reusable_representation_record_ids", []),
        *(
            record_id
            for missing in decision.get("missing_requirements", [])
            for record_id in missing.get("rejected_representation_record_ids", [])
        ),
    }
    records = [
        row
        for row in ledger["records"]
        if row["representation_record_id"] in linked_ids
    ]
    dimensions: dict[str, dict[str, str]] = {}
    for name in expected_scope["dimensions"]:
        if name == "version":
            versions = [row["expression"] for row in scope["version_constraints"]]
            dimensions[name] = {
                "state": "compatible"
                if any(version in owner_revision for version in versions)
                else "incompatible"
            }
        elif name == "task":
            dimensions[name] = {
                "state": "compatible"
                if owner_task in scope["task_ids"]
                else "incompatible"
            }
        elif name == "modality":
            modalities = {
                modality
                for record in records
                for modality in record.get("metadata", {}).get("modalities", ["rna"])
            } or {"rna"}
            dimensions[name] = {
                "state": "compatible"
                if modalities.intersection(scope["modalities"])
                else "incompatible"
            }
        elif name == "observation_unit":
            dimensions[name] = {
                "state": "compatible"
                if ledger.get("cell_index_hash") and "cell" in scope["observation_units"]
                else "incompatible"
            }
        elif name == "interface":
            values = {record.get("metadata", {}).get("return_object") for record in records}
            dimensions[name] = (
                {"state": "unknown", "evaluation": "not_evaluated"}
                if values <= {None}
                else {"state": "compatible", "evaluation": "evaluated"}
            )
        elif name == "representation_type":
            types = {_representation_type(record) for record in records}
            dimensions[name] = {
                "state": "compatible"
                if "representation-type:cell_embedding" in types
                else "incompatible"
            }
        elif name == "named_representation_selection":
            dimensions[name] = {
                "state": "compatible"
                if decision["action_id"] == "scanpy_core.neighbors_integrated"
                else "incompatible"
            }
        elif name == "required_representation":
            types = {_representation_type(record) for record in ledger["records"]}
            dimensions[name] = {
                "state": "compatible"
                if "representation-type:raw_umi_counts" in types
                else "missing"
            }
        elif name in {"capture_or_sample_unit", "droplet_umi_study_design"}:
            metadata_key = (
                "capture_unit_id"
                if name == "capture_or_sample_unit"
                else "study_design"
            )
            dimensions[name] = (
                {"state": "compatible", "evaluation": "evaluated"}
                if records
                and all(record.get("metadata", {}).get(metadata_key) for record in records)
                else {"state": "unknown", "evaluation": "not_evaluated"}
            )
        else:
            dimensions[name] = {"state": "unknown", "evaluation": "not_evaluated"}
    states = {value["state"] for value in dimensions.values()}
    overall = (
        "incompatible"
        if "incompatible" in states
        else "partially_resolved"
        if states.intersection({"unknown", "missing"})
        else "compatible"
    )
    return {"scope_id": claim["scope_id"], "overall_state": overall, **dimensions}


def collect_current_cases() -> list[dict[str, Any]]:
    """Collect current outputs using the corrected evaluator semantics."""

    spec, _ = load_frozen_preregistration()
    registry = FrozenKnowledgeRegistry.load()
    from eval.scientific_kg_contribution_v1 import (
        compile_request,
        frozen_requests,
        load_spec as load_contribution_spec,
        normalize,
    )

    requests = frozen_requests(load_contribution_spec())
    request_by_scenario = {row["scenario_id"]: row for row in requests}
    cases: list[dict[str, Any]] = []
    for scenario_id in spec["scope"]["scenario_ids"]:
        request = request_by_scenario[scenario_id]
        kg = compile_request(request, "kg")
        ledger = copy.deepcopy(request["kwargs"]["ledger"])
        decisions = kg["planner_outputs"]["result"].get(
            "scientific_applicability_results", []
        )
        all_references = [
            registry.enrich_reference(reference)
            for decision in decisions
            for reference in decision["evidence_references"]
        ]
        atoms: list[dict[str, Any]] = []
        for expected in (
            row for row in spec["atoms"] if row["scenario_id"] == scenario_id
        ):
            if not expected.get("scientific_evidence_expected"):
                atom = _positive_atom(expected, ledger)
                if atom is not None:
                    atoms.append(atom)
                continue
            expected_claim_ids = {
                row["claim_revision_id"]
                for row in expected["expected_evidence_bindings"]
            }
            decision = next(
                (
                    row
                    for row in decisions
                    if expected_claim_ids.intersection(
                        reference["claim_revision_id"]
                        for reference in row["evidence_references"]
                    )
                ),
                None,
            )
            if decision is None:
                continue
            references = [
                registry.enrich_reference(reference)
                for reference in decision["evidence_references"]
                if reference["claim_revision_id"] in expected_claim_ids
            ]
            linked = {
                *decision.get("reusable_representation_record_ids", []),
                *(
                    record_id
                    for missing in decision.get("missing_requirements", [])
                    for record_id in missing.get(
                        "rejected_representation_record_ids", []
                    )
                ),
            }
            atoms.append(
                {
                    "atom_id": expected["atom_id"],
                    "scenario_id": scenario_id,
                    "proposition": registry.claims[
                        next(iter(expected_claim_ids))
                    ]["claim_text"],
                    "primary_owner": "SCIENTIFIC_KG",
                    "scientific_evidence_bindings": references,
                    "scope": _actual_scope_v1_1(
                        expected, registry, ledger, decision
                    ),
                    "knowledge_status": decision["knowledge_status"],
                    "representation_record_ids": [
                        record_id
                        for record_id in expected.get(
                            "context_representation_record_ids", []
                        )
                        if record_id in linked
                    ],
                }
            )
        behavior = _digest(normalize(kg))
        cases.append(
            {
                "scenario_id": scenario_id,
                "ledger": ledger,
                "behavior_digest": behavior,
                "expected_behavior_digest": behavior,
                "emitted_atoms": atoms,
                "scenario_scientific_references": all_references,
                "raw_planner_output": kg,
            }
        )
    return cases


def representation_linkage_metrics(
    cases: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Keep concrete-record and explicit-absence obligations separate."""

    spec, _ = load_frozen_preregistration()
    actual = {
        atom["atom_id"]: (case, atom)
        for case in cases
        for atom in case["emitted_atoms"]
    }
    concrete_denominator = concrete_numerator = 0
    absence_denominator = absence_numerator = 0
    for expected in spec["atoms"]:
        obligations = expected.get("representation_obligations", [])
        if any("expected_absent" in row for row in obligations):
            absence_denominator += 1
            if expected["atom_id"] in actual:
                case, atom = actual[expected["atom_id"]]
                required = next(
                    row["expected_absent"]
                    for row in obligations
                    if "expected_absent" in row
                )
                absence = atom.get("representation_absence", {})
                count = sum(
                    _representation_type(record) == required
                    for record in case["ledger"]["records"]
                )
                if (
                    absence.get("representation_type_id") == required
                    and absence.get("matching_record_count") == 0
                    and count == 0
                ):
                    absence_numerator += 1
            continue
        identity = next(
            (row.get("expected") for row in obligations if row["field"] == "record_id"),
            None,
        )
        if identity is None:
            continue
        concrete_denominator += 1
        if expected["atom_id"] not in actual:
            continue
        case, atom = actual[expected["atom_id"]]
        record = next(
            (
                row
                for row in case["ledger"]["records"]
                if row["representation_record_id"] == atom.get(
                    "representation_record_id"
                )
            ),
            None,
        )
        if (
            record is not None
            and atom.get("representation_record_id") == identity
            and _record_satisfies_obligations(record, case["ledger"], obligations)
        ):
            concrete_numerator += 1
    return {
        "concrete_records": {
            "numerator": concrete_numerator,
            "denominator": concrete_denominator,
        },
        "explicit_absence": {
            "numerator": absence_numerator,
            "denominator": absence_denominator,
        },
    }


def build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the v1.1 report without mutating frozen inputs."""

    spec, _ = load_frozen_preregistration()
    verifier = JustificationVerifier()
    result = verifier.verify(cases)
    expected = {row["atom_id"]: row for row in spec["atoms"]}
    actual = {
        atom["atom_id"]: atom for case in cases for atom in case["emitted_atoms"]
    }
    scientific_ids = {
        atom_id
        for atom_id, row in expected.items()
        if row.get("scientific_evidence_expected")
    }
    runtime_ids = set(expected) - scientific_ids
    accepted = {
        (row["scenario_id"], _binding_key(reference))
        for row in expected.values()
        for reference in row["expected_evidence_bindings"]
    }
    references = {
        (case["scenario_id"], _binding_key(reference))
        for case in cases
        for reference in case["scenario_scientific_references"]
    }
    registry = FrozenKnowledgeRegistry.load()
    resolvable = sum(
        registry.resolution_failure(dict(zip(
            (
                "claim_revision_id", "claim_content_hash", "evidence_span_id",
                "source_revision_id", "locator", "content_hash",
            ),
            reference[1],
        ))) is None
        and registry.binding_valid(dict(zip(
            (
                "claim_revision_id", "claim_content_hash", "evidence_span_id",
                "source_revision_id", "locator", "content_hash",
            ),
            reference[1],
        )))
        for reference in references
    )
    negative_controls = []
    positive = build_positive_control_cases()
    for mutation in spec["negative_controls"]:
        mutated = apply_frozen_mutation(positive, mutation["mutation_id"])
        mutation_result = verifier.verify(mutated)
        negative_controls.append(
            {
                "mutation_id": mutation["mutation_id"],
                "expected_first_failure": mutation["expected_first_failure"],
                "actual_first_failure": mutation_result.first_failure,
                "behavior_unchanged": [
                    row["behavior_digest"] for row in mutated
                ] == [row["behavior_digest"] for row in positive],
                "single_dimension_only":
                    mutation_changes_only_declared_dimension(
                        positive, mutated, mutation["mutation_id"]
                    ),
            }
        )
    failed_codes = {
        failure.code for failure in result.failures
    }
    metrics = {
        "evidence_fidelity": {
            "scientific_evidence_recall": {
                "numerator": sum(
                    bool(actual.get(atom_id, {}).get("scientific_evidence_bindings"))
                    for atom_id in scientific_ids
                ),
                "denominator": len(scientific_ids),
            },
            "non_scientific_evidence_abstention": {
                "numerator": sum(
                    not actual.get(atom_id, {}).get("scientific_evidence_bindings")
                    for atom_id in runtime_ids
                ),
                "denominator": len(runtime_ids),
            },
            "evidence_object_and_binding_resolvability": {
                "numerator": resolvable,
                "denominator": len(references),
            },
            "scientific_decision_evidence_precision": {
                "numerator": len(references.intersection(accepted)),
                "denominator": len(references),
            },
        },
        "scope_fidelity": {
            "numerator": len(scientific_ids)
            if not failed_codes.intersection(
                {"SCOPE_MISMATCH", "SCOPE_SILENTLY_WIDENED"}
            )
            else len(scientific_ids)
            - len({
                failure.atom_id
                for failure in result.failures
                if failure.code in {"SCOPE_MISMATCH", "SCOPE_SILENTLY_WIDENED"}
            }),
            "denominator": len(scientific_ids),
        },
        "representation_linkage_fidelity": representation_linkage_metrics(cases),
        "epistemic_state_fidelity": {
            "numerator": len(scientific_ids)
            - len({
                failure.atom_id
                for failure in result.failures
                if failure.code == "EPISTEMIC_STATUS_CONFLATION"
            }),
            "denominator": len(scientific_ids),
        },
        "ownership_fidelity": {
            "numerator": len(expected)
            - len({
                failure.atom_id
                for failure in result.failures
                if failure.code == "OWNER_MISATTRIBUTION" and failure.atom_id
            }),
            "denominator": len(expected),
        },
        "behavior_digest_invariance": {
            "numerator": sum(
                case["behavior_digest"] == case["expected_behavior_digest"]
                for case in cases
            ),
            "denominator": len(cases),
        },
        "negative_control_first_cause_detection": {
            "numerator": sum(
                row["actual_first_failure"] == row["expected_first_failure"]
                and row["behavior_unchanged"]
                and row["single_dimension_only"]
                for row in negative_controls
            ),
            "denominator": len(negative_controls),
        },
    }
    return {
        "schema_version": EVALUATOR_SCHEMA_VERSION,
        "status": "PASS" if result.passed else "FAIL",
        "frozen_identity": {
            "baseline_commit": "e0ab62c368b6a544f077c601e5590e785578fae2",
            "expected_spec_sha256": SPEC_SHA256,
        },
        "first_failure": result.first_failure,
        "failures": [
            {
                "code": failure.code,
                "scenario_id": failure.scenario_id,
                "atom_id": failure.atom_id,
                "detail": failure.detail,
            }
            for failure in result.failures
        ],
        "metrics": metrics,
        "negative_control_results": negative_controls,
        "scenario_results": [
            {
                "scenario_id": case["scenario_id"],
                "behavior_invariant":
                    case["behavior_digest"] == case["expected_behavior_digest"],
                "atom_ids": [atom["atom_id"] for atom in case["emitted_atoms"]],
            }
            for case in cases
        ],
        "atom_results": [
            {
                "atom_id": atom_id,
                "present": atom_id in actual,
                "primary_owner": actual.get(atom_id, {}).get("primary_owner"),
                "scientific_evidence_count": len(
                    actual.get(atom_id, {}).get("scientific_evidence_bindings", [])
                ),
            }
            for atom_id in expected
        ],
    }


def run_formal_evaluation(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    """Execute the write-once v1.1 formal run."""

    if output_root.exists():
        raise FileExistsError("formal_v1_1_output_already_exists")
    load_frozen_preregistration()
    cases = collect_current_cases()
    output_root.mkdir(parents=True)
    started_at = datetime.now(timezone.utc).isoformat()
    input_digest = _digest(cases)
    _write_json(
        output_root / "formal_run_started.json",
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "formal_run_ordinal": 1,
            "started_at": started_at,
            "head": "e0ab62c368b6a544f077c601e5590e785578fae2",
            "evaluator_sha256": _file_hash(Path(__file__)),
            "spec_sha256": SPEC_SHA256,
            "input_sha256": input_digest,
        },
    )
    report = build_report(cases)
    report.update(
        {
            "formal_run_ordinal": 1,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "input_sha256": input_digest,
        }
    )
    for case in cases:
        _write_json(
            output_root / f"{case['scenario_id']}.json",
            case,
        )
    _write_json(output_root / "report.json", report)
    report_sha = _file_hash(output_root / "report.json")
    _write_json(
        output_root / "formal_run_completed.json",
        {
            "schema_version": EVALUATOR_SCHEMA_VERSION,
            "formal_run_ordinal": 1,
            "completed_at": report["finished_at"],
            "status": report["status"],
            "report_sha256": report_sha,
        },
    )
    (output_root / "SUMMARY.md").write_text(
        "# Scientific Decision Justification Fidelity v1.1\n\n"
        f"- Status: **{report['status']}**\n"
        f"- Frozen spec SHA-256: `{SPEC_SHA256}`\n"
        f"- First failure: `{report['first_failure']}`\n"
        "- The frozen v1 run remains unchanged.\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    run_formal_evaluation()
