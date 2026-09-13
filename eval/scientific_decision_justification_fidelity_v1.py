"""Evaluation-only verifier for frozen scientific decision justifications.

The module deliberately has no formal-run command.  It loads the frozen
preregistration, constructs a structured projection from the four existing
planner scenarios, and verifies that projection in the preregistered
first-cause order.  Production planning and knowledge artifacts are read-only.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "eval/specs/scientific_decision_justification_fidelity_v1.expected.json"
PREREGISTRATION_PATH = ROOT / "eval/specs/scientific_decision_justification_fidelity_v1.preregistration.json"
SPEC_SHA256 = "989bdf9b51a5e0529174a5a7b2da0bfe9735a6142fecbac9d985306cf6f61a85"
CANDIDATE_ROOT = ROOT / "data/evidence_candidates/scientific_kg_v1_uat_decision_rules"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_frozen_preregistration() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and integrity-check the immutable spec, manifest, and 13 sources."""

    if _file_hash(SPEC_PATH) != SPEC_SHA256:
        raise ValueError("frozen_expected_spec_digest_mismatch")
    spec = _read_json(SPEC_PATH)
    manifest = _read_json(PREREGISTRATION_PATH)
    if manifest["baseline_commit"] != "d05e8b71649bb46dba004bfca91fe4d32ea2894b":
        raise ValueError("frozen_baseline_commit_mismatch")
    if manifest["expected_spec"]["sha256"] != SPEC_SHA256:
        raise ValueError("preregistration_expected_spec_digest_mismatch")
    if not len(spec["atoms"]) == manifest["counts"]["atom_count"] == 12:
        raise ValueError("frozen_atom_count_mismatch")
    if not len(spec["negative_controls"]) == manifest["counts"]["negative_control_count"] == 8:
        raise ValueError("frozen_mutation_count_mismatch")
    sources = manifest["source_artifact_digests"]
    if len(sources) != 13:
        raise ValueError("frozen_source_digest_count_mismatch")
    for source in sources:
        path = ROOT / source["path"]
        if not path.is_file() or _file_hash(path) != source["sha256"]:
            raise ValueError(f"frozen_source_artifact_digest_mismatch:{source['path']}")
    if manifest["formal_evaluation_run"] is not False:
        raise ValueError("formal_evaluation_already_recorded")
    return spec, manifest


@dataclass(frozen=True)
class FrozenKnowledgeRegistry:
    claims: dict[str, dict[str, Any]]
    claims_by_hash: dict[str, dict[str, Any]]
    spans: dict[str, dict[str, Any]]
    sources: frozenset[str]
    bindings: dict[str, dict[str, Any]]
    scopes: dict[str, dict[str, Any]]

    @classmethod
    def load(cls) -> "FrozenKnowledgeRegistry":
        claims = {
            row["claim_revision_id"]: row
            for row in _read_jsonl(CANDIDATE_ROOT / "atomic_claims.jsonl")
        }
        for row in claims.values():
            if hashlib.sha256(row["claim_text"].encode()).hexdigest() != row["content_hash"]:
                raise ValueError(f"claim_content_integrity_failure:{row['claim_revision_id']}")
        spans = {
            row["evidence_span_id"]: row
            for row in _read_jsonl(CANDIDATE_ROOT / "authoritative_evidence_spans.jsonl")
        }
        for row in spans.values():
            if hashlib.sha256(row["source_excerpt"].encode()).hexdigest() != row["content_hash"]:
                raise ValueError(f"evidence_span_content_integrity_failure:{row['evidence_span_id']}")
        bindings = {
            row["claim_revision_id"]: row
            for row in _read_jsonl(CANDIDATE_ROOT / "exact_evidence_bindings.jsonl")
        }
        bundle = _read_json(CANDIDATE_ROOT / "conformance_bundle.json")
        return cls(
            claims=claims,
            claims_by_hash={row["content_hash"]: row for row in claims.values()},
            spans=spans,
            sources=frozenset(row["source_revision_id"] for row in spans.values()),
            bindings=bindings,
            scopes={row["scope_id"]: row for row in bundle["scopes"]},
        )

    def enrich_reference(self, reference: dict[str, Any]) -> dict[str, Any]:
        claim = self.claims.get(reference["claim_revision_id"])
        return {
            "claim_revision_id": reference["claim_revision_id"],
            "claim_content_hash": claim["content_hash"] if claim else "0" * 64,
            "evidence_span_id": reference["evidence_span_id"],
            "source_revision_id": reference["source_revision_id"],
            "locator": reference["locator"],
            "content_hash": reference["content_hash"],
        }

    def resolution_failure(self, reference: dict[str, Any]) -> str | None:
        """Validate referenced objects independently, before checking relations."""

        claim = self.claims.get(reference.get("claim_revision_id"))
        claim_hash_object = self.claims_by_hash.get(reference.get("claim_content_hash"))
        span = self.spans.get(reference.get("evidence_span_id"))
        if claim is None or claim_hash_object is None or span is None:
            return "missing_claim_hash_or_span_object"
        if reference.get("source_revision_id") not in self.sources:
            return "missing_source_revision_object"
        if hashlib.sha256(claim["claim_text"].encode()).hexdigest() != claim["content_hash"]:
            return "claim_integrity_failure"
        if hashlib.sha256(span["source_excerpt"].encode()).hexdigest() != span["content_hash"]:
            return "span_content_integrity_failure"
        if reference.get("locator") not in {row["locator"] for row in self.spans.values()}:
            return "unresolvable_locator"
        if reference.get("content_hash") not in {row["content_hash"] for row in self.spans.values()}:
            return "unresolvable_span_content_hash"
        return None

    def binding_valid(self, reference: dict[str, Any]) -> bool:
        """Check the frozen relation only after all tuple members resolve."""

        claim = self.claims[reference["claim_revision_id"]]
        span = self.spans[reference["evidence_span_id"]]
        binding = self.bindings.get(reference["claim_revision_id"])
        return bool(
            binding
            and reference["claim_content_hash"] == claim["content_hash"]
            and reference["claim_content_hash"] == binding["claim_content_hash"]
            and reference["evidence_span_id"] in binding["evidence_span_ids"]
            and reference["locator"] in binding["evidence_locators"]
            and reference["content_hash"] in binding["evidence_excerpt_sha256"]
            and span["source_revision_id"] == reference["source_revision_id"]
            and span["locator"] == reference["locator"]
            and span["content_hash"] == reference["content_hash"]
            and span["source_file_sha256"] in binding["source_file_sha256"]
        )


@dataclass(frozen=True)
class Failure:
    code: str
    scenario_id: str
    atom_id: str | None
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    first_failure: str | None
    failures: tuple[Failure, ...]
    atom_count: int


class JustificationVerifier:
    """Verify structured justification atoms in the frozen taxonomy order."""

    def __init__(self, spec: dict[str, Any] | None = None) -> None:
        frozen, _ = load_frozen_preregistration()
        self.spec = frozen if spec is None else spec
        self.registry = FrozenKnowledgeRegistry.load()
        self.expected_atoms = {row["atom_id"]: row for row in self.spec["atoms"]}
        self.precedence = self.spec["first_cause_failure_taxonomy"]["precedence"]

    def verify(self, cases: Iterable[dict[str, Any]]) -> VerificationResult:
        cases = list(cases)
        record_registry = {
            row["representation_record_id"]: row
            for case in cases
            for row in case.get("ledger", {}).get("records", [])
        }
        actual_atoms = {
            atom["atom_id"]: (case, atom)
            for case in cases
            for atom in case["emitted_atoms"]
        }
        failures: list[Failure] = []
        self._behavior_failures(cases, failures)
        for atom_id, expected in self.expected_atoms.items():
            if atom_id not in actual_atoms:
                failures.append(Failure("EXPECTED_ATOM_MISSING", expected["scenario_id"], atom_id, "atom absent"))
        for atom_id, (case, _) in actual_atoms.items():
            if atom_id not in self.expected_atoms:
                failures.append(Failure("UNEXPECTED_ATOM", case["scenario_id"], atom_id, "atom outside frozen set"))

        for atom_id, expected in self.expected_atoms.items():
            if atom_id not in actual_atoms:
                continue
            case, atom = actual_atoms[atom_id]
            self._owner_failures(expected, atom, failures)
            self._reference_failures(expected, atom, failures)
            self._scope_failures(expected, atom, failures)
            self._representation_failures(expected, atom, case, record_registry, failures)
            if atom.get("knowledge_status") != expected["expected_epistemic_state"]:
                failures.append(Failure("EPISTEMIC_STATUS_CONFLATION", case["scenario_id"], atom_id, "epistemic state differs"))

        self._extra_reference_failures(cases, failures)
        order = {code: index for index, code in enumerate(self.precedence)}
        failures.sort(key=lambda item: (order[item.code], item.scenario_id, item.atom_id or "", item.detail))
        return VerificationResult(
            passed=not failures,
            first_failure=failures[0].code if failures else None,
            failures=tuple(failures),
            atom_count=len(actual_atoms),
        )

    @staticmethod
    def _behavior_failures(cases: list[dict[str, Any]], failures: list[Failure]) -> None:
        for case in cases:
            if case["behavior_digest"] != case["expected_behavior_digest"]:
                failures.append(Failure("BEHAVIOR_MUTATED", case["scenario_id"], None, "canonical behavior digest differs"))

    @staticmethod
    def _owner_failures(expected: dict[str, Any], atom: dict[str, Any], failures: list[Failure]) -> None:
        if atom.get("primary_owner") != expected["primary_owner"]:
            failures.append(Failure("OWNER_MISATTRIBUTION", expected["scenario_id"], expected["atom_id"], "primary owner differs"))
        if expected.get("forbid_scientific_evidence") and atom.get("scientific_evidence_bindings"):
            failures.append(Failure("OWNER_MISATTRIBUTION", expected["scenario_id"], expected["atom_id"], "scientific evidence attached to runtime fact"))

    def _reference_failures(self, expected: dict[str, Any], atom: dict[str, Any], failures: list[Failure]) -> None:
        references = atom.get("scientific_evidence_bindings", [])
        if expected.get("scientific_evidence_expected") and not references:
            failures.append(Failure("EXPECTED_ATOM_MISSING", expected["scenario_id"], expected["atom_id"], "required evidence binding absent"))
            return
        accepted = {_binding_key(row) for row in expected["expected_evidence_bindings"]}
        for reference in references:
            problem = self.registry.resolution_failure(reference)
            if problem:
                failures.append(Failure("EVIDENCE_UNRESOLVABLE", expected["scenario_id"], expected["atom_id"], problem))
                continue
            if not self.registry.binding_valid(reference):
                failures.append(Failure("CLAIM_SOURCE_BINDING_MISMATCH", expected["scenario_id"], expected["atom_id"], "individually valid objects have invalid frozen binding"))
                continue
            if expected.get("scientific_evidence_expected") and _binding_key(reference) not in accepted:
                failures.append(Failure("EVIDENCE_DOES_NOT_SUPPORT_DECISION_ATOM", expected["scenario_id"], expected["atom_id"], "valid binding does not support frozen atom"))

    def _extra_reference_failures(self, cases: list[dict[str, Any]], failures: list[Failure]) -> None:
        expected_by_scenario: dict[str, set[tuple[str, ...]]] = {}
        for atom in self.expected_atoms.values():
            if atom.get("scientific_evidence_expected"):
                expected_by_scenario.setdefault(atom["scenario_id"], set()).update(
                    _binding_key(row) for row in atom["expected_evidence_bindings"]
                )
        for case in cases:
            seen: set[tuple[str, ...]] = set()
            for reference in case.get("scenario_scientific_references", []):
                key = _binding_key(reference)
                if key in seen:
                    continue
                seen.add(key)
                if self.registry.resolution_failure(reference) or not self.registry.binding_valid(reference):
                    continue
                if key not in expected_by_scenario.get(case["scenario_id"], set()):
                    failures.append(Failure("EXTRA_NON_DECISION_EVIDENCE", case["scenario_id"], None, ":".join(key[:3])))

    @staticmethod
    def _scope_failures(expected: dict[str, Any], atom: dict[str, Any], failures: list[Failure]) -> None:
        expected_scope = expected["expected_scope"]
        actual_scope = atom.get("scope", {})
        if expected_scope.get("overall_state") == "not_applicable":
            if actual_scope.get("overall_state") != "not_applicable":
                failures.append(Failure("SCOPE_MISMATCH", expected["scenario_id"], expected["atom_id"], "runtime atom has scientific scope"))
            return
        if actual_scope.get("scope_id") != expected_scope.get("scope_id"):
            failures.append(Failure("SCOPE_MISMATCH", expected["scenario_id"], expected["atom_id"], "scope identity differs"))
        for name, wanted in expected_scope["dimensions"].items():
            observed = actual_scope.get(name)
            if observed is None:
                failures.append(Failure("SCOPE_MISMATCH", expected["scenario_id"], expected["atom_id"], f"scope dimension absent:{name}"))
                continue
            wanted_state = wanted["state"]
            observed_state = observed.get("state")
            if wanted_state == "unknown":
                if observed_state == "compatible":
                    failures.append(Failure("SCOPE_SILENTLY_WIDENED", expected["scenario_id"], expected["atom_id"], name))
                elif observed_state != "unknown" or observed.get("evaluation") != wanted.get("evaluation"):
                    failures.append(Failure("SCOPE_MISMATCH", expected["scenario_id"], expected["atom_id"], name))
            elif observed_state != wanted_state:
                failures.append(Failure("SCOPE_MISMATCH", expected["scenario_id"], expected["atom_id"], name))

    @staticmethod
    def _representation_failures(
        expected: dict[str, Any],
        atom: dict[str, Any],
        case: dict[str, Any],
        record_registry: dict[str, dict[str, Any]],
        failures: list[Failure],
    ) -> None:
        atom_id = expected["atom_id"]
        scenario_id = expected["scenario_id"]
        obligations = expected.get("representation_obligations", [])
        identity = next((o.get("expected") for o in obligations if o["field"] == "record_id"), None)
        if identity:
            actual = atom.get("representation_record_id")
            if actual is None:
                failures.append(Failure("REPRESENTATION_LINK_MISSING", scenario_id, atom_id, "record link absent"))
            elif actual not in record_registry:
                failures.append(Failure("REPRESENTATION_LINK_MISSING", scenario_id, atom_id, "record link does not resolve"))
            elif actual != identity:
                failures.append(Failure("REPRESENTATION_LINK_WRONG", scenario_id, atom_id, f"{actual}!={identity}"))
            elif not _record_satisfies_obligations(record_registry[actual], case["ledger"], obligations):
                failures.append(Failure("EXPECTED_ATOM_MISSING", scenario_id, atom_id, "linked record does not establish proposition"))
        elif any("expected_absent" in o for o in obligations):
            expected_absent = next(o["expected_absent"] for o in obligations if "expected_absent" in o)
            absence = atom.get("representation_absence")
            actual_count = sum(
                _representation_type(record) == expected_absent
                for record in case["ledger"]["records"]
            )
            if not absence:
                failures.append(Failure("REPRESENTATION_LINK_MISSING", scenario_id, atom_id, "absence linkage missing"))
            elif (
                absence.get("representation_type_id") != expected_absent
                or absence.get("matching_record_count") != 0
                or actual_count != 0
            ):
                failures.append(Failure("REPRESENTATION_LINK_WRONG", scenario_id, atom_id, "absence linkage differs"))
        else:
            required = set(expected.get("context_representation_record_ids", []))
            actual = set(atom.get("representation_record_ids", []))
            if required and not actual:
                failures.append(Failure("REPRESENTATION_LINK_MISSING", scenario_id, atom_id, "scientific decision record links absent"))
            elif any(record_id not in record_registry for record_id in actual):
                failures.append(Failure("REPRESENTATION_LINK_MISSING", scenario_id, atom_id, "scientific decision record does not resolve"))
            elif not required.issubset(actual):
                failures.append(Failure("REPRESENTATION_LINK_WRONG", scenario_id, atom_id, "scientific decision links wrong records"))


def _binding_key(reference: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(reference.get(field, ""))
        for field in (
            "claim_revision_id",
            "claim_content_hash",
            "evidence_span_id",
            "source_revision_id",
            "locator",
            "content_hash",
        )
    )


def _flat_scope(expected_scope: dict[str, Any]) -> dict[str, Any]:
    if expected_scope.get("overall_state") == "not_applicable":
        return {"overall_state": "not_applicable"}
    return {
        "scope_id": expected_scope["scope_id"],
        "overall_state": expected_scope["overall_state"],
        **{
            name: {
                key: value
                for key, value in dimension.items()
                if key in {"state", "evaluation"}
            }
            for name, dimension in expected_scope["dimensions"].items()
        },
    }


def _record_field(record: dict[str, Any], field: str) -> Any:
    value: Any = record
    for part in field.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _record_satisfies_obligations(record: dict[str, Any], ledger: dict[str, Any], obligations: list[dict[str, Any]]) -> bool:
    for obligation in obligations:
        field = obligation["field"]
        if field == "record_id":
            value = record.get("representation_record_id")
        else:
            value = _record_field(record, field)
        if "expected" in obligation and value != obligation["expected"]:
            return False
        if "expected_contains" in obligation and obligation["expected_contains"] not in (value or []):
            return False
        relation = obligation.get("expected_relation")
        if relation == "equals_ledger_cell_index_hash" and value != ledger["cell_index_hash"]:
            return False
        if relation == "not_equal_to_ledger_cell_index_hash" and value == ledger["cell_index_hash"]:
            return False
    return True


def _representation_type(record: dict[str, Any]) -> str:
    explicit = record.get("metadata", {}).get("representation_type_id")
    if explicit:
        return explicit
    return {
        "raw_counts": "representation-type:raw_umi_counts",
        "filtered_counts": "representation-type:raw_umi_counts",
        "library_size_normalized": "representation-type:expression_matrix",
        "log1p_normalized": "representation-type:expression_matrix",
        "scaled_hvg": "representation-type:expression_matrix",
        "integrated_representation": "representation-type:cell_embedding",
        "neighbor_graph": "representation-type:neighbor_graph",
    }.get(record["representation_id"], "")


def _positive_atom(expected: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any] | None:
    atom = {
        "atom_id": expected["atom_id"],
        "scenario_id": expected["scenario_id"],
        "proposition": expected["proposition"],
        "primary_owner": expected["primary_owner"],
        "scientific_evidence_bindings": copy.deepcopy(expected["expected_evidence_bindings"]),
        "scope": _flat_scope(expected["expected_scope"]),
        "knowledge_status": expected["expected_epistemic_state"],
    }
    obligations = expected.get("representation_obligations", [])
    if obligations and any("expected_absent" in item for item in obligations):
        required_type = next(item["expected_absent"] for item in obligations if "expected_absent" in item)
        count = sum(_representation_type(record) == required_type for record in ledger["records"])
        atom["representation_absence"] = {
            "representation_type_id": required_type,
            "matching_record_count": count,
        }
    elif obligations:
        identity = next((item["expected"] for item in obligations if item["field"] == "record_id"), None)
        record = next((row for row in ledger["records"] if row["representation_record_id"] == identity), None)
        if record is None or not _record_satisfies_obligations(record, ledger, obligations):
            return None
        atom["representation_record_id"] = record["representation_record_id"]
    elif expected.get("context_representation_record_ids"):
        available = {row["representation_record_id"] for row in ledger["records"]}
        atom["representation_record_ids"] = [
            record_id
            for record_id in expected["context_representation_record_ids"]
            if record_id in available
        ]
    return atom


def build_positive_control_cases() -> list[dict[str, Any]]:
    """Materialize the frozen positive controls against the real Ledger fixtures."""

    spec, _ = load_frozen_preregistration()
    from eval.scientific_action_space_demo_v1 import demo_scenarios

    ledgers = {scenario_id: ledger.model_dump(mode="json") for scenario_id, _, ledger in demo_scenarios()}
    cases: list[dict[str, Any]] = []
    for scenario_id in spec["scope"]["scenario_ids"]:
        atoms = [
            atom
            for expected in spec["atoms"]
            if expected["scenario_id"] == scenario_id
            for atom in [_positive_atom(expected, ledgers[scenario_id])]
            if atom is not None
        ]
        references = [
            copy.deepcopy(reference)
            for atom in atoms
            for reference in atom["scientific_evidence_bindings"]
        ]
        behavior = _digest({"scenario_id": scenario_id, "frozen_behavior": True})
        cases.append(
            {
                "scenario_id": scenario_id,
                "ledger": copy.deepcopy(ledgers[scenario_id]),
                "behavior_digest": behavior,
                "expected_behavior_digest": behavior,
                "emitted_atoms": atoms,
                "scenario_scientific_references": references,
            }
        )
    return cases


def _actual_scope(
    expected: dict[str, Any],
    registry: FrozenKnowledgeRegistry,
    ledger: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the preregistered dimensions from candidate scope and context."""

    expected_scope = expected["expected_scope"]
    claim_id = expected["expected_evidence_bindings"][0]["claim_revision_id"]
    claim = registry.claims[claim_id]
    scope = registry.scopes[claim["scope_id"]]
    records = [
        row
        for row in ledger["records"]
        if row["representation_record_id"]
        in {
            *decision.get("reusable_representation_record_ids", []),
            *(
                record_id
                for missing in decision.get("missing_requirements", [])
                for record_id in missing.get("rejected_representation_record_ids", [])
            ),
        }
    ]
    dimensions: dict[str, dict[str, str]] = {}
    for name in expected_scope["dimensions"]:
        if name == "version":
            versions = [row["expression"] for row in scope["version_constraints"]]
            state = "compatible" if any(version in decision["operator_revision_id"] for version in versions) else "incompatible"
            dimensions[name] = {"state": state}
        elif name == "task":
            action_task = {
                "scanpy_core.leiden": "task:clustering",
                "scanpy_core.neighbors_integrated": "task:neighbor_graph",
                "scanpy_core.doublet_detection_action": "task:doublet_detection",
            }.get(decision["action_id"])
            dimensions[name] = {"state": "compatible" if action_task in scope["task_ids"] else "incompatible"}
        elif name == "modality":
            modalities = {
                modality
                for record in records
                for modality in record.get("metadata", {}).get("modalities", ["rna"])
            } or {"rna"}
            dimensions[name] = {"state": "compatible" if modalities.intersection(scope["modalities"]) else "incompatible"}
        elif name == "observation_unit":
            dimensions[name] = {"state": "compatible" if ledger.get("cell_index_hash") and "cell" in scope["observation_units"] else "incompatible"}
        elif name == "interface":
            values = {record.get("metadata", {}).get("return_object") for record in records}
            if values <= {None}:
                dimensions[name] = {"state": "unknown", "evaluation": "not_evaluated"}
            else:
                dimensions[name] = {"state": "compatible", "evaluation": "evaluated"}
        elif name == "representation_type":
            types = {_representation_type(record) for record in records}
            dimensions[name] = {"state": "compatible" if "representation-type:cell_embedding" in types else "incompatible"}
        elif name == "named_representation_selection":
            dimensions[name] = {"state": "compatible" if decision["action_id"] == "scanpy_core.neighbors_integrated" else "incompatible"}
        elif name == "required_representation":
            types = {_representation_type(record) for record in ledger["records"]}
            dimensions[name] = {"state": "compatible" if "representation-type:raw_umi_counts" in types else "missing"}
        elif name == "capture_or_sample_unit":
            if records and all(record.get("metadata", {}).get("capture_unit_id") for record in records):
                dimensions[name] = {"state": "compatible", "evaluation": "evaluated"}
            else:
                dimensions[name] = {"state": "unknown", "evaluation": "not_evaluated"}
        elif name == "droplet_umi_study_design":
            if records and all(record.get("metadata", {}).get("study_design") for record in records):
                dimensions[name] = {"state": "compatible", "evaluation": "evaluated"}
            else:
                dimensions[name] = {"state": "unknown", "evaluation": "not_evaluated"}
        else:
            dimensions[name] = {"state": "unknown", "evaluation": "not_evaluated"}
    states = {value["state"] for value in dimensions.values()}
    overall = "incompatible" if "incompatible" in states else "partially_resolved" if states.intersection({"unknown", "missing"}) else "compatible"
    return {"scope_id": claim["scope_id"], "overall_state": overall, **dimensions}


def collect_current_cases() -> list[dict[str, Any]]:
    """Collect the real current Planner projection without writing run artifacts.

    This function is the formal-run input boundary.  Calling it is deliberately
    left to the separately authorized formal-run checkpoint.
    """

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
        noop = compile_request(request, "noop")
        ledger = copy.deepcopy(request["kwargs"]["ledger"])
        decisions = kg["planner_outputs"]["result"].get("scientific_applicability_results", [])
        all_references = [
            registry.enrich_reference(reference)
            for decision in decisions
            for reference in decision["evidence_references"]
        ]
        atoms: list[dict[str, Any]] = []
        for expected in (row for row in spec["atoms"] if row["scenario_id"] == scenario_id):
            if not expected.get("scientific_evidence_expected"):
                atom = _positive_atom(expected, ledger)
                if atom is not None:
                    atoms.append(atom)
                continue
            expected_claim_ids = {
                row["claim_revision_id"] for row in expected["expected_evidence_bindings"]
            }
            decision = next(
                (
                    row
                    for row in decisions
                    if expected_claim_ids.intersection(
                        reference["claim_revision_id"] for reference in row["evidence_references"]
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
                    for record_id in missing.get("rejected_representation_record_ids", [])
                ),
            }
            atom = {
                "atom_id": expected["atom_id"],
                "scenario_id": scenario_id,
                "proposition": registry.claims[next(iter(expected_claim_ids))]["claim_text"],
                "primary_owner": "SCIENTIFIC_KG",
                "scientific_evidence_bindings": references,
                "scope": _actual_scope(expected, registry, ledger, decision),
                "knowledge_status": decision["knowledge_status"],
                "representation_record_ids": [
                    record_id
                    for record_id in expected.get("context_representation_record_ids", [])
                    if record_id in linked
                ],
            }
            atoms.append(atom)
        cases.append(
            {
                "scenario_id": scenario_id,
                "ledger": ledger,
                "behavior_digest": _digest(normalize(kg)),
                "expected_behavior_digest": _digest(normalize(noop)),
                "emitted_atoms": atoms,
                "scenario_scientific_references": all_references,
                "raw_planner_output": kg,
            }
        )
    return cases


def apply_frozen_mutation(cases: list[dict[str, Any]], mutation_id: str) -> list[dict[str, Any]]:
    """Apply one preregistered single-fault mutation to a positive projection."""

    spec, _ = load_frozen_preregistration()
    mutation = next(row for row in spec["negative_controls"] if row["mutation_id"] == mutation_id)
    result = copy.deepcopy(cases)
    atom = next(
        atom
        for case in result
        for atom in case["emitted_atoms"]
        if atom["atom_id"] == mutation["target_atom_id"]
    )
    operation = mutation["application"]["operation"]
    replacement = copy.deepcopy(mutation["replacement_binding"])
    if operation == "replace_complete_reference_tuple":
        atom["scientific_evidence_bindings"][0] = replacement
    elif operation == "replace_scalar_only":
        if "claim_revision_id" in replacement:
            atom["scientific_evidence_bindings"][0]["claim_revision_id"] = replacement["claim_revision_id"]
        elif "representation_record_id" in replacement:
            atom["representation_record_id"] = replacement["representation_record_id"]
        elif "knowledge_status" in replacement:
            atom["knowledge_status"] = replacement["knowledge_status"]
        elif "primary_owner" in replacement:
            atom["primary_owner"] = replacement["primary_owner"]
        else:
            raise ValueError(f"unsupported_scalar_mutation:{mutation_id}")
    elif operation == "replace_scope_dimension_only":
        atom["scope"]["capture_or_sample_unit"] = replacement
    elif operation == "append_complete_reference_tuple":
        atom["scientific_evidence_bindings"].extend(replacement["scientific_evidence_bindings"])
    else:
        raise ValueError(f"unsupported_mutation_operation:{operation}")
    # The scenario-level reference denominator follows emitted attachments.
    target_case = next(case for case in result if case["scenario_id"] == atom["scenario_id"])
    target_case["scenario_scientific_references"] = [
        copy.deepcopy(reference)
        for emitted in target_case["emitted_atoms"]
        for reference in emitted["scientific_evidence_bindings"]
    ]
    return result


def mutation_changes_only_declared_dimension(
    before: list[dict[str, Any]], after: list[dict[str, Any]], mutation_id: str
) -> bool:
    """Prove behavior and every field outside the declared target are fixed."""

    spec, _ = load_frozen_preregistration()
    mutation = next(row for row in spec["negative_controls"] if row["mutation_id"] == mutation_id)
    before_copy, after_copy = copy.deepcopy(before), copy.deepcopy(after)
    before_atom = next(atom for case in before_copy for atom in case["emitted_atoms"] if atom["atom_id"] == mutation["target_atom_id"])
    after_atom = next(atom for case in after_copy for atom in case["emitted_atoms"] if atom["atom_id"] == mutation["target_atom_id"])
    operation = mutation["application"]["operation"]
    if operation == "replace_complete_reference_tuple":
        before_atom["scientific_evidence_bindings"][0] = None
        after_atom["scientific_evidence_bindings"][0] = None
    elif operation == "append_complete_reference_tuple":
        before_atom["scientific_evidence_bindings"] = []
        after_atom["scientific_evidence_bindings"] = []
    elif operation == "replace_scope_dimension_only":
        before_atom["scope"]["capture_or_sample_unit"] = None
        after_atom["scope"]["capture_or_sample_unit"] = None
    else:
        key = next(iter(mutation["replacement_binding"]))
        if key == "claim_revision_id":
            before_atom["scientific_evidence_bindings"][0][key] = None
            after_atom["scientific_evidence_bindings"][0][key] = None
        else:
            before_atom[key] = None
            after_atom[key] = None
    # Scenario reference lists are derived mirrors, not a second semantic change.
    for cases in (before_copy, after_copy):
        for case in cases:
            case["scenario_scientific_references"] = [
                copy.deepcopy(reference)
                for atom in case["emitted_atoms"]
                for reference in atom["scientific_evidence_bindings"]
            ]
    return before_copy == after_copy
