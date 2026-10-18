"""Synthetic provider calls only: integrity is tested, not scientific truth."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from sckg_workbench.contracts import EvidencePackage
from sckg_workbench.evidence_answers import (
    ANSWER_SYSTEM, ASSESS_SYSTEM, EvidenceAnswerError,
    assess_evidence_answer, generate_evidence_answer,
    validate_evidence_answer_run, validate_evidence_assessment_run,
    COMPACT_ANSWER_FORMAT, COMPACT_ASSESS_FORMAT,
)
from sckg_workbench.model_service import ModelService
from sckg_workbench.evidence_selection import select_evidence_for_checks
from sckg_workbench.retrieval_planning import plan_evidence_queries, retrieve_planned_evidence
from sckg_workbench.storage import Ledger, Workspace, content_hash


BUDGET = {"max_input_tokens": 32000, "max_output_tokens": 2048,
          "timeout_seconds": 5, "allow_unknown_cost": True}


def unit(cid, quote):
    return {"candidate_id": cid, "claim": {
        "proposition": "Synthetic constraint " + cid, "subject": "SyntheticMethod",
        "predicate": "requires", "object": "fixture representation",
        "conditions": ["fixture condition"], "unknowns": ["not domain gold"],
        "anchors": [{"quote": quote}], "typed_attributes": []},
        "evidence": [{"ir_id": "ir-" + cid, "block_id": "block-" + cid,
                      "start": 0, "end": len(quote), "quote": quote,
                      "source_id": "source-" + cid, "source_revision_id": "revision-" + cid,
                      "snapshot_id": "snapshot-" + cid, "blob_sha256": "f" * 64,
                      "filename": "fixture.txt", "locator": {"line": 1},
                      "parse_status": "complete", "gaps": []}],
        "allowed_uses": ["explanation"], "review_id": "synthetic-review"}


class SyntheticKnowledge:
    def __init__(self, ledger):
        self.ledger = ledger
        self.units = [unit("candidate-fixture-a", "Synthetic method requires matched cells."),
                      unit("candidate-fixture-b", "Synthetic counts model requires raw counts.")]
        self.governance = 2
        self.on_resolve = None

    def package(self, rows, purpose):
        return EvidencePackage(namespace="fixture-kb", release_id="fixture-release",
                               governance_version=self.governance, purpose=purpose,
                               units=deepcopy(rows), gaps=[], retrieval={})

    def search(self, query, *, purpose, limit):
        return self.package(self.units[:limit], purpose)

    def resolve(self, ids, *, purpose):
        if self.on_resolve:
            self.on_resolve(self)
        by_id = {row["candidate_id"]: row for row in self.units}
        return self.package([by_id[cid] for cid in ids if cid in by_id], purpose)


def answer(**changes):
    value = {"decision": "Evidence remains conditional.", "steps": [
        {"step_id": "s1", "instruction": "Check the matched-cell requirement before use.",
         "evidence_ids": ["candidate-fixture-a"], "scope": "source_bound"},
        {"step_id": "s2", "instruction": "A tentative design still needs validation.",
         "evidence_ids": [], "scope": "proposal"}], "missing": ["Representation is unknown."]}
    value.update(changes)
    return value


def assessment(**changes):
    value = {"decision_check": {"judgment": "insufficient", "reason": "Conditions remain unknown.", "quotes": []},
             "step_checks": [
                 {"step_id": "s1", "judgment": "support", "reason": "The quoted requirement supports this check.",
                  "quotes": [{"candidate_id": "candidate-fixture-a", "anchor_index": 0,
                              "quote": "requires matched cells"}]},
                 {"step_id": "s2", "judgment": "proposal", "reason": "A design is not a source observation.", "quotes": []}]}
    value.update(changes)
    return value


@pytest.fixture
def setup(tmp_path):
    ledger = Ledger(Workspace(tmp_path / "synthetic-step-answers"))
    calls = []
    state = {"output": {"goal": "Check applicability", "stated_premises": [],
                        "unknowns": ["Representation is unknown."],
                        "queries": [{"language": "en", "text": "synthetic applicability"}],
                        "evidence_checks": ["Does the input match the method?"]},
             "finish": "stop", "usage": 150}

    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        if state.get("during"):
            state["during"]()
        if state.get("error"):
            raise TimeoutError("synthetic timeout")
        return {"model": "fixture-model", "id": "fixture-response", "usage": {
            "prompt_tokens": 300, "completion_tokens": state["usage"], "total_tokens": 300 + state["usage"]},
            "choices": [{"finish_reason": state["finish"],
                         "message": {"content": state.get("raw", json.dumps(state["output"]))}}]}

    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("fixture", "https://provider.example/v1", "synthetic-secret", "fixture-passphrase")
    profile = models.create_profile("fixture", "evaluation", connection["id"], "fixture-model", options={"temperature": 0})
    knowledge = SyntheticKnowledge(ledger)
    plan = plan_evidence_queries(models, "Which applicability requirements remain unknown?",
                                 {"unknowns": ["Representation is unknown."]},
                                 profile_id=profile["id"], budget={**BUDGET, "max_input_tokens": 16000,
                                                                 "max_output_tokens": 1536},
                                 outbound_authorized=True, passphrase="fixture-passphrase")
    selection = retrieve_planned_evidence(knowledge, plan)
    calls.clear()
    state["output"] = answer()
    return SimpleNamespace(models=models, ledger=ledger, profile=profile, knowledge=knowledge,
                           selection=selection, state=state, calls=calls)


def generate(setup, **changes):
    kwargs = {"profile_id": setup.profile["id"], "budget": BUDGET,
              "outbound_authorized": True, "passphrase": "fixture-passphrase"}
    kwargs.update(changes)
    return generate_evidence_answer(setup.models, setup.knowledge, setup.selection, **kwargs)


def assess(setup, run, **changes):
    kwargs = {"profile_id": setup.profile["id"], "budget": BUDGET,
              "outbound_authorized": True, "passphrase": "fixture-passphrase"}
    kwargs.update(changes)
    return assess_evidence_answer(setup.models, setup.knowledge, run, **kwargs)


def rebind(record):
    record["binding_hash"] = content_hash({key: value for key, value in record.items() if key != "binding_hash"})


def test_generate_uses_exact_question_profile_full_records_once(setup):
    original = deepcopy(setup.selection)
    run = generate(setup)
    assert len(setup.calls) == 1
    payload = setup.calls[0]
    material = json.loads(payload["messages"][1]["content"])
    assert payload["messages"][0]["content"] == ANSWER_SYSTEM
    assert material["question"] == setup.selection["query_plan"]["input_material"]["question"]
    assert material["dataset_profile"] == {"unknowns": ["Representation is unknown."]}
    assert material["evidence_records"] == setup.selection["records"]
    assert run["answer"] == answer() and setup.selection == original
    assert run["call_receipt"] == setup.ledger.get_record("model_call", run["call_id"])
    assert run["call_request_hash"] == content_hash(payload)
    assert run["citation_valid"] is True and run["semantic_support"] == "not_assessed"
    assert run["recommendation_eligible"] is False and run["formal_scientific_accuracy"] is None


@pytest.mark.parametrize("change", [
    {"steps": [{"step_id": "s1", "instruction": "Fake claim", "evidence_ids": ["candidate-unprovided"], "scope": "source_bound"}]},
    {"decision": "See candidate-unprovided for proof."},
    {"steps": [{"step_id": "s1", "instruction": "Fake claim", "evidence_ids": [], "scope": "source_bound"}]},
    {"steps": [answer()["steps"][0], answer()["steps"][0]]},
    {"scientifically_verified": True},
])
def test_invalid_answer_does_not_trigger_retry_and_preserves_receipt(setup, change):
    setup.state["output"] = answer(**change)
    with pytest.raises(EvidenceAnswerError) as error:
        generate(setup)
    assert len(setup.calls) == 1
    assert error.value.receipt and error.value.call_id


@pytest.mark.parametrize("finish,usage", [("length", 150), ("stop", 2300)])
def test_partial_or_budget_exceeded_is_not_success(setup, finish, usage):
    setup.state.update(finish=finish, usage=usage)
    with pytest.raises(EvidenceAnswerError) as error:
        generate(setup)
    assert len(setup.calls) == 1 and error.value.receipt["status"] != "succeeded"


def test_timeout_retains_failure_receipt_without_retry(setup):
    setup.state["error"] = True
    with pytest.raises(EvidenceAnswerError) as error:
        generate(setup)
    assert len(setup.calls) == 1
    assert error.value.receipt["status"] == "failed"


@pytest.mark.parametrize("during", [False, True])
def test_pause_before_or_during_generation_rejects(setup, during):
    if during:
        setup.state["during"] = lambda: setattr(setup.knowledge, "governance", 3)
    else:
        setup.knowledge.governance = 3
    with pytest.raises(EvidenceAnswerError) as error:
        generate(setup)
    assert len(setup.calls) == int(during)
    if during:
        assert error.value.receipt["status"] == "succeeded"


def test_full_unit_metadata_change_rejects_even_when_quote_unchanged(setup):
    setup.knowledge.units[0]["review_id"] = "changed-review"
    with pytest.raises(EvidenceAnswerError):
        generate(setup)
    assert setup.calls == []


def test_context_substitution_rejected_even_after_result_hash_recomputed(setup):
    setup.selection["records"][0]["claim"]["conditions"] = ["invented condition"]
    setup.selection["result_hash"] = content_hash({k: v for k, v in setup.selection.items() if k != "result_hash"})
    with pytest.raises(EvidenceAnswerError):
        generate(setup)
    assert setup.calls == []


def test_assessment_checks_decision_and_all_steps_without_certifying(setup):
    run = generate(setup)
    setup.state["output"] = assessment()
    reviewed = assess(setup, run)
    assert len(setup.calls) == 2
    assert setup.calls[1]["messages"][0]["content"] == ASSESS_SYSTEM
    material = json.loads(setup.calls[1]["messages"][1]["content"])
    assert material["answer"] == run["answer"]
    assert material["evidence_records"] == run["selection"]["records"]
    assert reviewed["status"] == "model_assessed_not_verified"
    assert reviewed["formal_scientific_accuracy"] is None
    assert reviewed["recommendation_eligible"] is False
    assert reviewed["scientific_facts_verified"] is False
    assert reviewed["model_assessment_blocks_recommendation"] is True


@pytest.mark.parametrize("mutation", [
    "missing_step", "repeated_step", "new_step", "rewritten_quote", "wrong_anchor", "wrong_candidate",
    "source_claim_wrong_binding", "support_without_quote", "proposal_becomes_fact",
])
def test_invalid_assessment_stops_with_receipt(setup, mutation):
    run = generate(setup)
    value = assessment()
    if mutation == "missing_step":
        value["step_checks"] = value["step_checks"][:1]
    elif mutation == "repeated_step":
        value["step_checks"] = [value["step_checks"][0], value["step_checks"][0]]
    elif mutation == "new_step":
        value["step_checks"][1]["step_id"] = "s3"
    elif mutation == "rewritten_quote":
        value["step_checks"][0]["quotes"][0]["quote"] = "needs corresponding cells"
    elif mutation == "wrong_anchor":
        value["step_checks"][0]["quotes"][0]["anchor_index"] = 1
    elif mutation == "wrong_candidate":
        value["step_checks"][0]["quotes"][0]["candidate_id"] = "candidate-unprovided"
    elif mutation == "source_claim_wrong_binding":
        value["step_checks"][0]["quotes"] = [{"candidate_id": "candidate-fixture-b", "anchor_index": 0,
                                              "quote": "requires raw counts"}]
    elif mutation == "support_without_quote":
        value["step_checks"][0]["quotes"] = []
    elif mutation == "proposal_becomes_fact":
        value["step_checks"][1].update(judgment="support", quotes=value["step_checks"][0]["quotes"])
    setup.state["output"] = value
    with pytest.raises(EvidenceAnswerError) as error:
        assess(setup, run)
    assert len(setup.calls) == 2 and error.value.receipt


def test_correct_opening_cannot_hide_refuted_later_step(setup):
    setup.state["output"] = answer(steps=[
        answer()["steps"][0],
        {"step_id": "s2", "instruction": "Train the counts model on non-count input.",
         "evidence_ids": ["candidate-fixture-b"], "scope": "source_bound"}])
    run = generate(setup)
    value = assessment()
    value["decision_check"] = {"judgment": "support", "reason": "Opening caveat states a real restriction.",
                               "quotes": value["step_checks"][0]["quotes"]}
    value["step_checks"][1] = {"step_id": "s2", "judgment": "refute", "reason": "The training input violates the requirement.",
                                 "quotes": [{"candidate_id": "candidate-fixture-b", "anchor_index": 0,
                                             "quote": "counts model requires raw counts"}]}
    setup.state["output"] = value
    reviewed = assess(setup, run)
    assert reviewed["assessment"]["decision_check"]["judgment"] == "support"
    assert reviewed["assessment"]["step_checks"][1]["judgment"] == "refute"
    assert reviewed["model_assessment_blocks_recommendation"] is True
    assert reviewed["recommendation_eligible"] is False


def test_no_automatic_certification_even_when_every_source_step_supported(setup):
    setup.state["output"] = answer(steps=[answer()["steps"][0]])
    run = generate(setup)
    value = assessment(step_checks=[assessment()["step_checks"][0]])
    value["decision_check"] = {"judgment": "support", "reason": "The original quote states the condition.",
                               "quotes": value["step_checks"][0]["quotes"]}
    setup.state["output"] = value
    reviewed = assess(setup, run)
    assert reviewed["model_assessment_blocks_recommendation"] is False
    assert reviewed["recommendation_eligible"] is False
    assert reviewed["requires_domain_review"] is True


@pytest.mark.parametrize("mutation", ["answer", "input", "receipt", "profile", "request_hash"])
def test_rewritten_run_cannot_be_used_for_assessment_even_with_new_binding(setup, mutation):
    run = generate(setup)
    setup.state["output"] = assessment()
    if mutation == "answer":
        run["answer"]["steps"][0]["instruction"] = "Changed suggestion"
        run["answer_hash"] = content_hash(run["answer"])
    elif mutation == "input":
        run["input_material"]["question"] = "Another question"
        run["input_hash"] = content_hash(run["input_material"])
    elif mutation == "receipt":
        run["call_receipt"]["usage"]["input_tokens"] = 100
    elif mutation == "profile":
        run["profile_hash"] = "f" * 64
    elif mutation == "request_hash":
        run["call_request_hash"] = "f" * 64
    rebind(run)
    with pytest.raises(EvidenceAnswerError):
        assess(setup, run)
    assert len(setup.calls) == 1


def test_actual_ledger_payload_corruption_is_detected(setup, monkeypatch):
    run = generate(setup)
    original = setup.ledger.get_record

    def corrupt(kind, identity, **kwargs):
        value = original(kind, identity, **kwargs)
        if kind == "model_request" and identity == run["call_id"]:
            value["payload"]["messages"][-1]["content"] = "rewritten actual payload"
            value["request_hash"] = content_hash(value["payload"])
        return value

    monkeypatch.setattr(setup.ledger, "get_record", corrupt)
    with pytest.raises(EvidenceAnswerError):
        assess(setup, run)
    assert len(setup.calls) == 1


@pytest.mark.parametrize("during", [False, True])
def test_pause_before_or_during_assessment_rejects(setup, during):
    run = generate(setup)
    setup.state["output"] = assessment()
    if during:
        setup.state["during"] = lambda: setattr(setup.knowledge, "governance", 3)
    else:
        setup.knowledge.governance = 3
    with pytest.raises(EvidenceAnswerError) as error:
        assess(setup, run)
    assert len(setup.calls) == 1 + int(during)
    if during:
        assert error.value.receipt["status"] == "succeeded"


@pytest.mark.parametrize("budget", [
    {**BUDGET, "timeout_seconds": 61}, {**BUDGET, "max_output_tokens": 2049},
    {**BUDGET, "max_input_tokens": True}, {**BUDGET, "allow_unknown_cost": 1},
])
def test_invalid_generation_budget_never_calls_provider(setup, budget):
    with pytest.raises(EvidenceAnswerError):
        generate(setup, budget=budget)
    assert setup.calls == []


def test_explicit_authorization_required_for_both_calls(setup):
    with pytest.raises(EvidenceAnswerError):
        generate(setup, outbound_authorized=False)
    assert setup.calls == []
    run = generate(setup)
    with pytest.raises(EvidenceAnswerError):
        assess(setup, run, outbound_authorized=False)
    assert len(setup.calls) == 1


def test_resume_validators_make_no_network_calls(setup):
    run = generate(setup)
    setup.state["output"] = assessment()
    reviewed = assess(setup, run)
    assert validate_evidence_answer_run(setup.models, setup.knowledge, run) == run["answer"]
    assert validate_evidence_assessment_run(setup.models, setup.knowledge, run, reviewed) == reviewed["assessment"]
    assert len(setup.calls) == 2


def test_rehashing_assessment_cannot_turn_negative_into_positive(setup):
    run = generate(setup)
    setup.state["output"] = assessment()
    reviewed = assess(setup, run)
    reviewed["assessment"]["decision_check"].update(
        judgment="support", reason="Modified positive opinion",
        quotes=reviewed["assessment"]["step_checks"][0]["quotes"])
    reviewed["assessment_hash"] = content_hash(reviewed["assessment"])
    reviewed["model_assessment_blocks_recommendation"] = False
    rebind(reviewed)
    with pytest.raises(EvidenceAnswerError):
        validate_evidence_assessment_run(setup.models, setup.knowledge, run, reviewed)
    assert len(setup.calls) == 2


def test_resume_assessment_rechecks_pause_without_new_call(setup):
    run = generate(setup)
    setup.state["output"] = assessment()
    reviewed = assess(setup, run)
    setup.knowledge.governance += 1
    with pytest.raises(EvidenceAnswerError):
        validate_evidence_assessment_run(setup.models, setup.knowledge, run, reviewed)
    assert len(setup.calls) == 2


def test_assessment_prose_cannot_cite_unprovided_ids(setup):
    run = generate(setup)
    value = assessment()
    value["decision_check"]["reason"] = "Check candidate-unprovided for the answer."
    setup.state["output"] = value
    with pytest.raises(EvidenceAnswerError) as error:
        assess(setup, run)
    assert error.value.receipt and len(setup.calls) == 2


def test_search_catalog_is_not_scientific_answer_or_assessment_context(setup, monkeypatch):
    # This test isolates lexical metadata from scientific material. The
    # catalogue's provenance validator is tested in retrieval-planning tests;
    # actual planning/answer/assessment request receipts are still checked here.
    monkeypatch.setattr("sckg_workbench.retrieval_planning._validate_catalog", lambda ledger, catalog: None)
    original_input = setup.selection["query_plan"]["input_material"]
    setup.state["output"] = setup.selection["query_plan"]["plan"]
    plan = plan_evidence_queries(
        setup.models, original_input["question"], original_input["dataset_profile"],
        profile_id=setup.profile["id"], budget={**BUDGET, "max_input_tokens": 16000,
                                               "max_output_tokens": 1536},
        outbound_authorized=True, passphrase="fixture-passphrase",
        term_catalog={"entries": [{"label": "A lexical hint only", "term_hints": ["not a capability"]}]})
    setup.selection = retrieve_planned_evidence(setup.knowledge, plan)
    setup.state["output"] = answer()
    run = generate(setup)
    assert "available_term_catalog" in run["selection"]["query_plan"]["input_material"]
    assert "available_term_catalog" not in run["input_material"]
    assert "A lexical hint only" not in setup.calls[-1]["messages"][-1]["content"]
    assert run["input_material"]["question"] == original_input["question"]
    assert run["input_material"]["dataset_profile"] == original_input["dataset_profile"]
    setup.state["output"] = assessment()
    reviewed = assess(setup, run)
    assert "available_term_catalog" not in reviewed["input_material"]
    assert "A lexical hint only" not in setup.calls[-1]["messages"][-1]["content"]


def selected(setup):
    setup.state["output"] = {"priorities": [{"candidate_id": unit["candidate_id"],
                                             "check_indices": [0], "priority": 1,
                                             "reason": "A synthetic applicable constraint"}
                                            for unit in setup.knowledge.units],
                             "unresolved_checks": []}
    return select_evidence_for_checks(
        setup.models, setup.knowledge, setup.selection, profile_id=setup.profile["id"],
        budget=BUDGET, outbound_authorized=True, passphrase="fixture-passphrase")


def test_model_selection_actual_receipt_is_consumed_before_answer(setup):
    setup.selection = selected(setup)
    setup.state["output"] = answer()
    run = generate(setup)
    assert run["selection"]["schema_version"] == "selected-evidence-retrieval-v1"
    assert len(setup.calls) == 2


def test_rehashed_model_priorities_cannot_bypass_actual_selection_output(setup):
    setup.selection = selected(setup)
    setup.state["output"] = answer()
    selection_run = setup.selection["selection_run"]
    selection_run["selection"]["priorities"][0]["reason"] = "A substituted judgment"
    selection_run["selection_hash"] = content_hash(selection_run["selection"])
    rebind(selection_run)
    setup.selection["result_hash"] = content_hash({key: value for key, value in setup.selection.items()
                                                  if key != "result_hash"})
    with pytest.raises(EvidenceAnswerError):
        generate(setup)
    assert len(setup.calls) == 1


def test_refutation_may_use_other_selected_counterevidence_but_not_repair_support(setup):
    run = generate(setup)
    value = assessment()
    value["step_checks"][0].update(
        judgment="refute", reason="Another selected original span contradicts the concrete suggestion.",
        quotes=[{"candidate_id": "candidate-fixture-b", "anchor_index": 0,
                 "quote": "requires raw counts"}])
    setup.state["output"] = value
    reviewed = assess(setup, run)
    assert reviewed["assessment"]["step_checks"][0]["judgment"] == "refute"
    assert reviewed["model_assessment_blocks_recommendation"] is True
    assert reviewed["recommendation_eligible"] is False


COMPACT_BUDGET = {**BUDGET, "max_input_tokens": 16000, "max_output_tokens": 1024}
COMPACT_AUDIT_BUDGET = {**COMPACT_BUDGET, "max_output_tokens": 1536}


def wire_answer(**changes):
    value = {"d": "The plan is conditional on input checks.", "s": [
        {"i": "s1", "f": "The source method requires matched cells.",
         "a": "Check pairing before choosing the procedure.", "e": ["E1"],
         "p": ["Cell-level pairing"], "k": "source_bound"},
        {"i": "s2", "f": "", "a": "Seek evidence for another route.", "e": [],
         "p": ["Representation requirements"], "k": "proposal"}],
        "m": ["Representation is unknown."]}
    value.update(changes)
    return value


def wire_assessment(**changes):
    value = {"d": {"f": "insufficient", "p": "unknown", "a": "needs_evidence",
                   "r": "The whole plan still lacks applicability evidence.", "q": []},
             "s": [
                 {"i": "s1", "f": "support", "p": "unknown", "a": "conditional_plan",
                  "r": "The fact has evidence; the input premise is not measured.",
                  "q": [{"e": "E1", "n": 0, "t": "requires matched cells"}]},
                 {"i": "s2", "f": "no_claim", "p": "unknown", "a": "needs_evidence",
                  "r": "This action needs further evidence, not a source fact.", "q": []}]}
    value.update(changes)
    return value


def compact_generate(setup, **changes):
    setup.state["output"] = changes.pop("output", wire_answer())
    return generate(setup, protocol="compact_v2", budget=changes.pop("budget", COMPACT_BUDGET), **changes)


def compact_assess(setup, run, **changes):
    setup.state["output"] = changes.pop("output", wire_assessment())
    return assess(setup, run, budget=changes.pop("budget", COMPACT_AUDIT_BUDGET), **changes)


def test_compact_wire_preserves_full_facts_and_binds_actual_alias_response(setup):
    original = deepcopy(setup.selection)
    run = compact_generate(setup)
    assert run["schema_version"] == "step-evidence-answer-run-v2"
    assert run["wire_answer"] == wire_answer()
    assert run["wire_answer_hash"] == run["call_receipt"]["structured_output_hash"]
    assert run["answer_hash"] == content_hash(run["answer"])
    assert run["answer_hash"] != run["wire_answer_hash"]
    assert run["answer"]["steps"][0]["evidence_ids"] == ["candidate-fixture-a"]
    assert run["answer"]["steps"][0]["factual_claim"] == wire_answer()["s"][0]["f"]
    assert run["answer"]["steps"][0]["instruction"] == wire_answer()["s"][0]["a"]
    raw_records = json.loads(setup.calls[0]["messages"][-1]["content"])["evidence_records"]
    assert [record["candidate_id"] for record in raw_records] == ["E1", "E2"]
    for wire_record, full_record in zip(raw_records, original["records"]):
        assert {k: v for k, v in wire_record.items() if k != "candidate_id"} == {
            k: v for k, v in full_record.items() if k != "candidate_id"}
    assert original == setup.selection
    assert validate_evidence_answer_run(setup.models, setup.knowledge, run) == run["answer"]
    assert len(setup.calls) == 1


def test_compact_supported_fact_does_not_validate_proposed_action_or_execution(setup):
    value = wire_answer(s=[{**wire_answer()["s"][0], "k": "proposal"}])
    run = compact_generate(setup, output=value)
    audited = compact_assess(setup, run, output=wire_assessment(s=[wire_assessment()["s"][0]]))
    check = audited["assessment"]["step_checks"][0]
    assert check["scientific_support"] == "support"
    assert check["action_status"] == "conditional_plan" and check["preconditions_status"] == "unknown"
    assert run["answer"]["steps"][0]["scope"] == "proposal"
    assert audited["execution_status"] == "not_run" and audited["execution_verified"] is False
    assert audited["recommendation_eligible"] is False and audited["formal_scientific_accuracy"] is None
    assert audited["model_action_prerequisites_incomplete"] is True
    assert audited["model_assessment_blocks_recommendation"] is True
    assert validate_evidence_assessment_run(setup.models, setup.knowledge, run, audited) == audited["assessment"]
    assert len(setup.calls) == 2


@pytest.mark.parametrize("change", [
    {"s": [{**wire_answer()["s"][0], "e": ["E99"]}]},
    {"s": [{**wire_answer()["s"][0], "e": ["candidate-fixture-a"]}]},
    {"s": [{**wire_answer()["s"][0], "e": ["E1", "E1"]}]},
    {"s": [{**wire_answer()["s"][0], "e": []}]},
    {"d": "See candidate-" + "f" * 64},
    {"s": [wire_answer()["s"][0], wire_answer()["s"][0]]},
    {"execution_verified": True},
])
def test_compact_bad_alias_or_unsupported_claim_stops_without_retry(setup, change):
    with pytest.raises(EvidenceAnswerError) as error:
        compact_generate(setup, output=wire_answer(**change))
    assert len(setup.calls) == 1
    assert error.value.receipt and error.value.call_id


@pytest.mark.parametrize("mutation", ["normalized", "wire", "aliases", "input", "execution"])
def test_compact_rehash_cannot_change_normalization_or_actual_answer(setup, mutation):
    run = compact_generate(setup)
    if mutation == "normalized":
        run["answer"]["steps"][0]["instruction"] = "Rewritten normalized action"
        run["answer_hash"] = content_hash(run["answer"])
    elif mutation == "wire":
        run["wire_answer"]["d"] = "Rewritten actual answer"
        run["wire_answer_hash"] = content_hash(run["wire_answer"])
        run["answer"]["decision"] = run["wire_answer"]["d"]
        run["answer_hash"] = content_hash(run["answer"])
    elif mutation == "aliases":
        run["alias_manifest"]["bindings"][0]["candidate_id"] = "candidate-fixture-b"
        run["alias_manifest_hash"] = content_hash(run["alias_manifest"])
    elif mutation == "input":
        run["input_material"]["evidence_records"][0]["candidate_id"] = "E2"
        run["input_hash"] = content_hash(run["input_material"])
    elif mutation == "execution":
        run["execution_verified"] = True
    rebind(run)
    with pytest.raises(EvidenceAnswerError):
        validate_evidence_answer_run(setup.models, setup.knowledge, run)
    assert len(setup.calls) == 1


@pytest.mark.parametrize("mutation", [
    "missing_step", "repeated_step", "unprovided_alias", "wrong_quote", "wrong_anchor",
    "borrow_support", "empty_fact_supported", "fact_ignored", "claim_execution", "unmet_not_blocked",
    "support_no_quote", "missing_decision",
])
def test_compact_bad_dual_axis_assessment_retains_receipt(setup, mutation):
    run = compact_generate(setup)
    value = wire_assessment()
    if mutation == "missing_step":
        value["s"] = value["s"][:1]
    elif mutation == "repeated_step":
        value["s"] = [value["s"][0], value["s"][0]]
    elif mutation == "unprovided_alias":
        value["s"][0]["q"][0]["e"] = "E99"
    elif mutation == "wrong_quote":
        value["s"][0]["q"][0]["t"] = "requires biologically matched measurements"
    elif mutation == "wrong_anchor":
        value["s"][0]["q"][0]["n"] = 1
    elif mutation == "borrow_support":
        value["s"][0]["q"] = [{"e": "E2", "n": 0, "t": "requires raw counts"}]
    elif mutation == "empty_fact_supported":
        value["s"][1].update(f="support", q=[{"e": "E1", "n": 0, "t": "requires matched cells"}])
    elif mutation == "fact_ignored":
        value["s"][0].update(f="no_claim", q=[])
    elif mutation == "claim_execution":
        value["s"][0]["a"] = "execution_verified"
    elif mutation == "unmet_not_blocked":
        value["s"][0]["p"] = "reported_unmet"
    elif mutation == "support_no_quote":
        value["s"][0]["q"] = []
    elif mutation == "missing_decision":
        del value["d"]
    with pytest.raises(EvidenceAnswerError) as error:
        compact_assess(setup, run, output=value)
    assert len(setup.calls) == 2 and error.value.receipt


def test_compact_counterevidence_is_allowed_and_unmet_inputs_block_action(setup):
    run = compact_generate(setup)
    value = wire_assessment()
    value["s"][0].update(f="refute", p="reported_unmet", a="blocked",
                         q=[{"e": "E2", "n": 0, "t": "requires raw counts"}])
    audited = compact_assess(setup, run, output=value)
    assert audited["assessment"]["step_checks"][0]["quotes"][0]["candidate_id"] == "candidate-fixture-b"
    assert audited["model_scientific_support_incomplete"] is True
    assert audited["model_action_prerequisites_incomplete"] is True
    assert audited["execution_verified"] is False


@pytest.mark.parametrize("mutation", ["normalized", "wire", "flags", "aliases"])
def test_compact_assessment_recovery_rejects_rehashing_judgments(setup, mutation):
    run = compact_generate(setup)
    audited = compact_assess(setup, run)
    if mutation == "normalized":
        audited["assessment"]["step_checks"][0]["scientific_support"] = "refute"
        audited["assessment_hash"] = content_hash(audited["assessment"])
    elif mutation == "wire":
        audited["wire_assessment"]["s"][0]["f"] = "partial"
        audited["wire_assessment_hash"] = content_hash(audited["wire_assessment"])
        audited["assessment"]["step_checks"][0]["scientific_support"] = "partial"
        audited["assessment_hash"] = content_hash(audited["assessment"])
    elif mutation == "flags":
        audited["model_assessment_blocks_recommendation"] = False
    elif mutation == "aliases":
        audited["alias_manifest"]["bindings"][0]["full_unit_hash"] = "f" * 64
        audited["alias_manifest_hash"] = content_hash(audited["alias_manifest"])
    rebind(audited)
    with pytest.raises(EvidenceAnswerError):
        validate_evidence_assessment_run(setup.models, setup.knowledge, run, audited)
    assert len(setup.calls) == 2


@pytest.mark.parametrize("stage", ["answer_before", "answer_during", "audit_before", "audit_during", "resume"])
def test_compact_pause_rechecked_at_every_consumption(setup, stage):
    if stage == "answer_before":
        setup.knowledge.governance += 1
        with pytest.raises(EvidenceAnswerError):
            compact_generate(setup)
        assert len(setup.calls) == 0
        return
    if stage == "answer_during":
        setup.state["during"] = lambda: setattr(setup.knowledge, "governance", 3)
        with pytest.raises(EvidenceAnswerError) as error:
            compact_generate(setup)
        assert len(setup.calls) == 1 and error.value.receipt
        return
    run = compact_generate(setup)
    if stage == "audit_before":
        setup.knowledge.governance += 1
        with pytest.raises(EvidenceAnswerError):
            compact_assess(setup, run)
        assert len(setup.calls) == 1
    elif stage == "audit_during":
        setup.state["during"] = lambda: setattr(setup.knowledge, "governance", 3)
        with pytest.raises(EvidenceAnswerError) as error:
            compact_assess(setup, run)
        assert len(setup.calls) == 2 and error.value.receipt
    else:
        audited = compact_assess(setup, run)
        setup.knowledge.governance += 1
        with pytest.raises(EvidenceAnswerError):
            validate_evidence_assessment_run(setup.models, setup.knowledge, run, audited)
        assert len(setup.calls) == 2


@pytest.mark.parametrize("budget,assessment_stage", [
    ({**COMPACT_BUDGET, "max_input_tokens": 16001}, False),
    ({**COMPACT_BUDGET, "max_output_tokens": 1025}, False),
    ({**COMPACT_AUDIT_BUDGET, "max_output_tokens": 1537}, True),
])
def test_compact_budget_never_increases_to_make_protocol_pass(setup, budget, assessment_stage):
    if assessment_stage:
        run = compact_generate(setup)
        with pytest.raises(EvidenceAnswerError):
            compact_assess(setup, run, budget=budget)
        assert len(setup.calls) == 1
    else:
        with pytest.raises(EvidenceAnswerError):
            compact_generate(setup, budget=budget)
        assert len(setup.calls) == 0


def test_compact_schema_and_wire_do_not_require_long_ids_or_execution_claims(setup):
    assert len(json.dumps(COMPACT_ANSWER_FORMAT)) < 2500
    assert len(json.dumps(COMPACT_ASSESS_FORMAT)) < 2500
    run = compact_generate(setup)
    audited = compact_assess(setup, run)
    for payload in setup.calls:
        material = json.loads(payload["messages"][-1]["content"])
        assert [record["candidate_id"] for record in material["evidence_records"]] == ["E1", "E2"]
    assert audited["input_material"]["answer"]["s"][0]["e"] == ["E1"]
    assert audited["wire_assessment_hash"] == audited["call_receipt"]["structured_output_hash"]
    assert audited["assessment_hash"] != audited["wire_assessment_hash"]


def test_compact_new_raw_output_record_is_checked_if_gateway_provides_it(setup, monkeypatch):
    run = compact_generate(setup)
    receipt = run["call_receipt"]
    if "raw_output_record_hash" not in receipt:
        pytest.skip("Old gateway does not yet expose immutable raw-output records")
    record = setup.ledger.get_record("model_output", run["call_id"])
    assert record["text_hash"] == content_hash(record["text"])
    original = setup.ledger.get_record

    def corrupt(kind, identity, **kwargs):
        value = original(kind, identity, **kwargs)
        if kind == "model_output" and identity == run["call_id"]:
            value["text"] = "altered raw text"
            value["text_hash"] = content_hash(value["text"])
        return value

    monkeypatch.setattr(setup.ledger, "get_record", corrupt)
    with pytest.raises(EvidenceAnswerError):
        validate_evidence_answer_run(setup.models, setup.knowledge, run)
    assert len(setup.calls) == 1


def test_compact_card_selection_still_sends_full_original_evidence_to_answer(setup):
    setup.state["output"] = {"priorities": [
        {"alias": "E2", "check_indices": [0], "priority": 1, "reason": "The second input constraint"},
        {"alias": "E1", "check_indices": [0], "priority": 2, "reason": "The first input constraint"}],
        "unresolved_checks": []}
    setup.selection = select_evidence_for_checks(
        setup.models, setup.knowledge, setup.selection, profile_id=setup.profile["id"],
        budget=COMPACT_BUDGET, outbound_authorized=True, passphrase="fixture-passphrase",
        candidate_mode="cards", candidate_limit=32, candidate_budget_bytes=11000)
    assert setup.selection["schema_version"] == "selected-evidence-retrieval-v2"
    assert setup.selection["selection_run"]["selection"]["priorities"][0]["alias"] == "E2"
    run = compact_generate(setup)
    assert run["alias_manifest"]["bindings"][0]["candidate_id"] == "candidate-fixture-b"
    assert run["answer"]["steps"][0]["evidence_ids"] == ["candidate-fixture-b"]
    # Aliases are stage-local: selector E2 becomes answer E1 after selection.
    sent = json.loads(setup.calls[-1]["messages"][-1]["content"])["evidence_records"]
    assert sent[0]["candidate_id"] == "E1"
    assert sent[0]["evidence"][0]["quote"] == "Synthetic counts model requires raw counts."
    assert "candidate_cards" not in run["input_material"]
    assert validate_evidence_answer_run(setup.models, setup.knowledge, run) == run["answer"]


def test_compact_truncated_raw_json_is_preserved_and_never_repaired(setup):
    setup.state.update(raw='{"d":"an incomplete response', finish="length", usage=1024)
    with pytest.raises(EvidenceAnswerError) as error:
        compact_generate(setup)
    receipt = error.value.receipt
    assert len(setup.calls) == 1 and receipt["status"] == "invalid_response"
    assert receipt["finish_reason"] == "length"
    output = setup.ledger.get_record("model_output", error.value.call_id)
    assert output["text"] == setup.state["raw"]
    assert output["text_hash"] == content_hash(setup.state["raw"])
    assert receipt["raw_output_record_hash"] == content_hash(output)


def test_compact_legacy_receipts_without_raw_output_binding_remain_readable(setup, monkeypatch):
    original = setup.ledger.get_record
    invoke = setup.models.invoke

    def old_record(kind, identity, **kwargs):
        value = original(kind, identity, **kwargs)
        if kind == "model_call" and value:
            value.pop("raw_output_record_hash", None)
        return value

    def old_invoke(*args, **kwargs):
        value = invoke(*args, **kwargs)
        value.pop("raw_output_record_hash", None)
        return value

    monkeypatch.setattr(setup.ledger, "get_record", old_record)
    monkeypatch.setattr(setup.models, "invoke", old_invoke)
    # This emulates a historical ledger receipt projection, not a mutation of
    # its actual immutable records; wire/request bindings remain enforced.
    setup.selection["query_plan"]["call_receipt"].pop("raw_output_record_hash", None)
    rebind(setup.selection["query_plan"])
    setup.selection["result_hash"] = content_hash({k: v for k, v in setup.selection.items() if k != "result_hash"})
    run = compact_generate(setup)
    assert "raw_output_record_hash" not in run["call_receipt"]
    assert validate_evidence_answer_run(setup.models, setup.knowledge, run) == run["answer"]
