from __future__ import annotations

import copy
from pathlib import Path

import pytest

from eval import scientific_kg_contribution_v1 as evaluation


def _raw():
    return {"planner_outputs": {
        "plan": {"plan_id": "fixed-plan", "steps": [
            {"operation": "a", "parameters": {"k": 15}, "input_artifacts": ["x"], "output_artifacts": ["y"]},
            {"operation": "b", "parameters": {}, "input_artifacts": ["y"], "output_artifacts": ["z"]},
        ], "edges": [{"source_node_id": "a", "target_node_id": "b", "artifact_id": "y"}],
            "blocking_conditions": [], "missing_requirements": []},
        "result": {"blocked": False, "blocking_reasons": [], "planned_method_ids": ["a", "b"],
                   "reused_representation_ids": ["x"], "missing_requirements": []},
        "resolved_reused_ledger_records": [{"representation_record_id": "record-x", "metadata": {"fresh": True}}],
    }}


def test_frozen_spec_has_exactly_existing_four_scenarios_and_valid_sources():
    spec = evaluation.load_spec()
    assert len(spec["scenarios"]) == 4
    assert spec["options"] == {}
    assert spec["data_profile"] is None
    assert evaluation.file_hash(evaluation.SPEC_PATH) == evaluation.SPEC_SHA256
    import json
    bindings = {r["claim_revision_id"]: r for r in map(json.loads, (evaluation.ROOT / evaluation.CANDIDATE / "exact_evidence_bindings.jsonl").read_text().splitlines())}
    for row in spec["scenarios"]:
        assert row["source_basis"]
        assert all(bindings[key]["assessment"] == "supports" for key in row["support_claim_ids"])


def test_explicit_noop_does_not_construct_default_kg(monkeypatch):
    from engine import capability_planner

    def forbidden():
        pytest.fail("no-op attempted to construct production KG adapter")

    monkeypatch.setattr(capability_planner, "default_scientific_kg_applicability", forbidden)
    noop = evaluation.NoOpApplicability()
    planner = capability_planner.CapabilityPlanCompiler(scientific_applicability=noop)
    assert planner.scientific_applicability is noop
    ledger = {"sentinel": True}
    assert noop.assess(action_id="a", ledger=ledger) is None
    assert ledger == {"sentinel": True}
    assert noop.calls == ["a"]


def test_fixture_serialization_is_four_unchanged_inputs_with_distinct_copies():
    from eval.scientific_action_space_demo_v1 import demo_scenarios
    spec = evaluation.load_spec()
    requests = evaluation.frozen_requests(spec)
    assert [r["scenario_id"] for r in requests] == [x[0] for x in demo_scenarios()]
    for request, (_, _, ledger) in zip(requests, demo_scenarios()):
        expected = ledger.model_dump(mode="json")
        expected["created_at"] = evaluation.EVALUATION_LEDGER_CREATED_AT
        assert request["kwargs"]["ledger"] == expected
    requests[0]["kwargs"]["options"]["test"] = True
    assert requests[1]["kwargs"]["options"] == {}
    assert spec["options"] == {}


def test_independent_fixture_generation_is_byte_and_semantically_deterministic():
    import json

    spec = evaluation.load_spec()
    first = evaluation.frozen_requests(spec)
    second = evaluation.frozen_requests(spec)
    assert evaluation.first_difference(first, second) is None
    assert evaluation.digest(first) == evaluation.digest(second)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    assert {
        request["kwargs"]["ledger"]["created_at"] for request in first
    } == {evaluation.EVALUATION_LEDGER_CREATED_AT}


def test_only_new_scientific_result_field_is_excluded_and_raw_is_preserved():
    old = _raw()
    current = copy.deepcopy(old)
    current["planner_outputs"]["result"]["scientific_applicability_results"] = [{"missing_requirements": ["counts"]}]
    assert evaluation.first_difference(evaluation.normalize(old), evaluation.normalize(current)) is None
    assert current["planner_outputs"]["result"]["scientific_applicability_results"]


@pytest.mark.parametrize("path,value", [
    (("result", "blocked"), True),
    (("result", "blocking_reasons"), ["mismatch"]),
    (("result", "planned_method_ids"), ["b", "a"]),
    (("result", "reused_representation_ids"), []),
    (("result", "missing_requirements"), ["raw_counts"]),
    (("plan", "missing_requirements"), ["raw_counts"]),
    (("plan", "blocking_conditions"), ["missing"]),
    (("plan", "plan_id"), "different-deterministic-plan"),
    (("plan", "steps", 0, "parameters", "k"), 16),
    (("plan", "steps", 0, "input_artifacts"), ["different-input"]),
    (("plan", "steps", 0, "output_artifacts"), ["different-output"]),
    (("plan", "edges", 0, "source_node_id"), "b"),
    (("resolved_reused_ledger_records", 0, "metadata", "fresh"), False),
])
def test_equivalence_preserves_every_decision_field(path, value):
    old = _raw()
    changed = copy.deepcopy(old)
    target = changed["planner_outputs"]
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    assert evaluation.first_difference(evaluation.normalize(old), evaluation.normalize(changed)) is not None


def test_list_order_duplicates_missing_fields_and_types_are_not_normalized():
    old = _raw()
    changed = copy.deepcopy(old)
    changed["planner_outputs"]["plan"]["steps"].reverse()
    assert evaluation.first_difference(evaluation.normalize(old), evaluation.normalize(changed))
    assert evaluation.first_difference(["reason"], ["reason", "reason"])
    assert evaluation.first_difference({"missing": []}, {})
    assert evaluation.first_difference(False, 0)


def test_writes_are_exclusive(tmp_path):
    path = tmp_path / "result.json"
    evaluation.write_new(path, {"first": True})
    with pytest.raises(FileExistsError):
        evaluation.write_new(path, {"second": True})
    assert evaluation.read(path) == {"first": True}


def _gate_setup(tmp_path, monkeypatch):
    spec = evaluation.load_spec()
    snapshot = {"requests": [{"scenario_id": r["scenario_id"], "kwargs": {}} for r in spec["scenarios"]]}
    evaluation.write_new(tmp_path / "freeze.json", {"expected_spec_sha256": evaluation.SPEC_SHA256})
    evaluation.write_new(tmp_path / "input_equivalence.json", {"passed": True})
    evaluation.write_new(
        tmp_path / "frozen_requests.json",
        snapshot["requests"],
    )
    for label in ("pre_kg", "current"):
        evaluation.write_new(tmp_path / f"{label}_inputs.json", snapshot)
    monkeypatch.setattr(evaluation, "validate_tests", lambda out: {"passed": True})
    pre = Path("pre-test-only")
    monkeypatch.setattr(evaluation, "git", lambda root, *args: (spec["pre_kg_commit"] if root == pre else spec["current_commit"]) if args[0] == "rev-parse" else "")
    return pre, snapshot


def test_formal_flow_stops_on_first_decision_mismatch_before_any_kg(tmp_path, monkeypatch):
    pre, snap = _gate_setup(tmp_path, monkeypatch)
    calls = []

    def worker(root, command, payload):
        if command == "snapshot":
            return snap
        calls.append(payload["lane"])
        assert payload["lane"] != "kg"
        raw = _raw()
        if payload["lane"] == "noop":
            raw["planner_outputs"]["result"]["blocked"] = True
        return raw

    monkeypatch.setattr(evaluation, "worker", worker)
    report = evaluation.formal_run(tmp_path, pre)
    assert report["paired_status"] == "not_run"
    assert report["status"] == "NO-GO"
    assert calls == ["pre_kg", "noop"]
    assert report["first_mismatch"]["path"] == "$.result.blocked"
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 2
    assert len(list((tmp_path / "normalized").rglob("*.json"))) == 2


def test_changed_input_digest_stops_before_compile(tmp_path, monkeypatch):
    pre, snap = _gate_setup(tmp_path, monkeypatch)

    def worker(root, command, payload):
        assert command == "snapshot"
        return {**snap, "changed_contract_hash": "different"}

    monkeypatch.setattr(evaluation, "worker", worker)
    report = evaluation.formal_run(tmp_path, pre)
    assert report["paired_status"] == "not_run"
    assert not (tmp_path / "raw").exists()


def test_subprocess_import_isolation_and_safe_environment(monkeypatch):
    import subprocess
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs)
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"ok": true}')

    monkeypatch.setattr(evaluation.subprocess, "run", run)
    monkeypatch.setenv("API_KEY", "must-not-propagate")
    assert evaluation.worker(
        Path("checkout"),
        "snapshot",
        {"spec": {}, "requests": []},
    ) == {"ok": True}
    assert seen["cwd"] == Path("checkout")
    assert "API_KEY" not in seen["env"]
    assert seen["env"]["SCKG_ENV_FILE"] == "/dev/null"
    assert seen["env"]["SCKG_EXECUTION_POLICY"] == "disabled"


@pytest.mark.parametrize("before,after,eb,ea,label", [
    (False, True, False, True, "behavioral improvement"),
    (True, True, False, True, "same behavior, explanation/provenance improvement"),
    (True, True, True, True, "no observed incremental contribution"),
    (True, False, False, True, "regression"),
    (True, True, True, False, "regression"),
])
def test_behavior_and_explanation_contributions_are_separate(before, after, eb, ea, label):
    assert evaluation.classify({"obligations": {"correct": before}}, {"obligations": {"correct": after}},
                               {"metrics": {"evidence": evaluation.measure(eb)}},
                               {"metrics": {"evidence": evaluation.measure(ea)}}) == label


def test_not_applicable_has_no_denominator_and_is_not_counted_as_success():
    assert evaluation.measure(True, 0) == "not_applicable"
    assert evaluation.measure(False) == {"numerator": 0, "denominator": 1}


def test_partial_or_wrong_source_reference_does_not_receive_support_credit():
    import json
    root = evaluation.ROOT / evaluation.CANDIDATE
    spans = list(map(json.loads, (root / "authoritative_evidence_spans.jsonl").read_text().splitlines()))
    span = next(r for r in spans if r["evidence_span_id"] == "scanpy-authoritative-span:leiden.input:1.11.2")
    ref = {key: span[key] for key in ("evidence_span_id", "source_revision_id", "locator", "content_hash")}
    ref["claim_revision_id"] = "claim-revision:uat:leiden-input:v1"
    assert evaluation.evidence_checks([ref], evaluation.ROOT)[0]["supporting_frozen_assessment"]
    ref["source_revision_id"] = "wrong-source"
    assert not evaluation.evidence_checks([ref], evaluation.ROOT)[0]["resolvable"]
