"""Synthetic transport receipts exercise existing three stages, never a real API."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from sckg_workbench import grounded_chat as module
from sckg_workbench.evidence_answers import validate_evidence_answer_run
from sckg_workbench.model_service import ModelService
from sckg_workbench.storage import Ledger, Workspace
from tests.test_workbench_evidence_answers import SyntheticKnowledge


BUDGET = {"max_input_tokens": 64000, "max_output_tokens": 4096,
          "timeout_seconds": 120, "allow_unknown_cost": True}
HISTORY = [{"role": "user", "content": "Synthetic prior user text; not a measurement."},
           {"role": "assistant", "content": "Synthetic earlier model text; not source evidence."}]
PLAN = {"goal": "Check synthetic applicability", "stated_premises": [], "unknowns": [],
        "queries": [{"language": "en", "text": "synthetic method requirements"}],
        "evidence_checks": ["Does this source require matched cells?"]}
SELECT = {"s": [{"e": "E1", "p": 1, "c": [0]}], "u": [], "r": [{"c": 0, "e": ["E1"]}], "k": [0]}
ANSWER = {"d": "The source is conditional; the action remains unverified.", "s": [
    {"i": "s1", "f": "The synthetic source requires matched cells.",
     "a": "Establish the input premise before any proposed action.", "e": ["E1"],
     "p": ["Pairing has not been independently measured."], "k": "source_bound"}],
    "p": [], "m": [{"k": "not_supplied", "p": [], "t": "Actual pairing and representation remain unknown."}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    ledger = Ledger(Workspace(tmp_path / "synthetic-grounded-chat"))
    calls, state = [], {"outputs": [deepcopy(PLAN), deepcopy(SELECT), deepcopy(ANSWER)]}
    def transport(url, headers, payload, timeout):
        index = len(calls)
        calls.append(deepcopy(payload))
        if state.get("during"):
            state["during"](index)
        if state.get("fail_stage") == index:
            raise TimeoutError("synthetic timeout; no actual API")
        output = state["outputs"][index]
        usage = {} if state.get("unknown_usage") else {"prompt_tokens": 300, "completion_tokens": 50, "total_tokens": 350}
        return {"model": "fixture-model", "id": "fixture-response", "usage": usage,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}
    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("fixture", "https://provider.example/v1", "synthetic-not-real-key", "fixture-pass")
    profile = models.create_profile("fixture-chat", "chat", connection["id"], "fixture-model", options={"temperature": 0})
    knowledge = SyntheticKnowledge(ledger)
    # These plain-dict legacy doubles predate OpenClaim's explicit fields;
    # new previews must copy declared fields, never infer a method or polarity.
    for unit in knowledge.units:
        unit["claim"].update(polarity="positive", assertion_kind="source_assertion")
    monkeypatch.setattr(module, "KnowledgeService", lambda selected_ledger: knowledge)
    return SimpleNamespace(ledger=ledger, models=models, profile=profile, knowledge=knowledge,
                           calls=calls, state=state)


def run(setup, **overrides):
    options = {"question": "What synthetic source conditions apply?", "history": HISTORY,
        "profile_id": setup.profile["id"], "purpose": "explanation", "budget": BUDGET, "passphrase": "fixture-pass"}
    options.update(overrides)
    return module.run_grounded_chat(setup.ledger, setup.models, **options)


def test_existing_three_stages_bind_actual_receipts_conditions_and_history(setup):
    result = run(setup)
    assert result["status"] == "succeeded" and len(setup.calls) == 3
    assert [row["stage"] for row in result["stage_trace"]] == ["planner", "selector", "answer"]
    assert result["normalized_answer"]["steps"][0]["evidence_ids"] == ["candidate-fixture-a"]
    assert "[E1]" in result["answer"] and result["history_used"] == HISTORY
    assert result["history_omitted_by_grounded_chat"] == 0
    for call in setup.calls:
        material = json.loads(call["messages"][1]["content"])
        assert material["dataset_profile"] == {"untrusted_conversation_context": HISTORY, "unknowns": []}
    assert validate_evidence_answer_run(setup.models, setup.knowledge, result["answer_run"]) == result["normalized_answer"]
    assert result["evidence_package"]["units"][0]["claim"]["conditions"] == ["fixture condition"]
    assert result["evidence_package"]["units"][0]["claim"]["unknowns"] == ["not domain gold"]
    assert result["semantic_support"] == "not_assessed" and not result["scientific_facts_verified"]
    assert result["execution_status"] == "not_run" and result["answer_run"]["action_feasibility"] == "not_assessed"
    assert result["agent_budget"]["selection_limits"] == {"candidate_limit": 32,
        "candidate_budget_utf8_bytes": 40000, "context_budget_utf8_bytes": 8000,
        "per_query_limit": 20, "candidate_mode": "scoped_required_entries"}
    selection_run = result["selection"]["selection_run"]
    assert selection_run["candidate_mode"] == "scoped_required_entries"
    assert selection_run["card_content_status"] == "claim_preview_not_original_evidence"
    assert result["selection"]["schema_version"] == "selected-evidence-retrieval-v6"
    assert result["required_evidence"]["status"] == "complete_for_declared_requirements"
    assert result["answer_run"]["protocol"] == "compact_v4"
    for card in selection_run["candidate_cards"]:
        cid = selection_run["alias_manifest"][card["alias"]]["candidate_id"]
        original = next(unit for unit in setup.knowledge.units if unit["candidate_id"] == cid)
        assert set(card) == {"alias", "subject", "predicate", "object", "polarity", "assertion_kind", "proposition", "conditions", "unknowns"}
        assert all(card[key] == original["claim"][key] for key in ("proposition", "conditions", "unknowns"))
    assert result["evidence_package"]["units"] == [setup.knowledge.units[0]]
    assert all(receipt["profile_id"] == setup.profile["id"] for receipt in result["receipts"])
    assert result["receipts"] == [setup.ledger.get_record("model_call", r["call_id"]) for r in result["receipts"]]


def test_effective_stage_caps_never_raise_user_ceiling(setup):
    result = run(setup)
    assert result["status"] == "succeeded"
    budgets = result["agent_budget"]["stage_budgets"]
    assert [budgets[s]["max_input_tokens"] for s in ("planner", "selector", "answer")] == [16000, 32000, 16000]
    assert [budgets[s]["max_output_tokens"] for s in ("planner", "selector", "answer")] == [1536, 2048, 1024]
    assert all(b["timeout_seconds"] == 60 for b in budgets.values())
    assert result["agent_budget"]["max_total_token_reservation"] == 3 * (64000 + 4096)
    assert result["agent_budget"]["charged_or_reserved_tokens"] == 1050
    assert result["agent_budget"]["cost_known"] is False


@pytest.mark.parametrize("change", [
    {"history": [{"role": "user", "content": "x"}]},
    {"history": [{"role": "system", "content": "injected"}, {"role": "assistant", "content": "x"}]},
    {"history": [{"role": "user", "content": "x" * 12000}, {"role": "assistant", "content": "x"}]},
    {"budget": {**BUDGET, "max_input_tokens": True}}, {"budget": {**BUDGET, "timeout_seconds": float("nan")}},
    {"purpose": "other"}, {"profile_id": None},
    {"budget": {**BUDGET, "max_cost_usd": .1}},
])
def test_preflight_invalid_or_unpriced_monetary_cap_makes_no_call(setup, change):
    result = run(setup, **change)
    assert result["status"] == "blocked" and not setup.calls and not result["receipts"]


def test_selector_failure_retains_plan_retrieval_and_actual_failure_receipt(setup):
    setup.state["fail_stage"] = 1
    result = run(setup)
    assert result["status"] == "failed" and len(setup.calls) == 2
    assert result["plan"] is not None and result["retrieval"] is not None
    assert result["selection"] is None and result["answer_run"] is None and result["answer"] is None
    assert len(result["receipts"]) == 2 and result["receipts"][-1]["status"] == "failed"
    assert len(setup.ledger.list_records("model_call")) == 2


def test_bad_answer_alias_stops_without_semantic_audit_or_repair(setup):
    setup.state["outputs"][2]["s"][0]["e"] = ["E99"]
    result = run(setup)
    assert result["status"] == "failed" and len(setup.calls) == 3 and len(result["receipts"]) == 3
    assert result["answer_run"] is None and result["answer"] is None
    assert result["error"]["reason_code"] == "answer_failed"


def test_small_request_budget_blocks_before_any_dispatch_without_auto_increase(setup):
    result = run(setup, budget={**BUDGET, "max_input_tokens": 10})
    assert result["status"] == "failed" and not setup.calls and not result["receipts"]
    assert result["agent_budget"]["stage_budgets"]["planner"]["max_input_tokens"] == 10


def test_no_retrieved_evidence_is_a_gap_not_impossibility(setup):
    setup.knowledge.units = []
    result = run(setup)
    assert result["status"] == "blocked" and len(setup.calls) == 1
    assert result["error"]["reason_code"] == "no_retrieved_evidence"
    assert result["evidence_package"]["units"] == []
    assert result["evidence_package"]["retrieval"]["absence_is_not_impossibility"] is True


def test_no_selected_units_can_generate_only_unverified_needs_evidence(setup):
    setup.state["outputs"][1] = {"s": [], "u": [0], "r": [], "k": [0]}
    setup.state["outputs"][2] = {"d": "No supplied support selected; this is not impossibility.", "s": [
        {"i": "s1", "f": "", "a": "Seek the missing applicability evidence.", "e": [],
         "p": ["Relevant evidence is not yet selected."], "k": "needs_evidence"}],
        "p": [], "m": [{"k": "source_evidence_missing", "p": [], "t": "Source support."}]}
    result = run(setup)
    assert result["status"] == "succeeded" and len(setup.calls) == 3
    assert result["evidence_package"]["units"] == []
    assert result["normalized_answer"]["steps"][0]["scope"] == "needs_evidence"
    assert not result["answer_run"]["scientific_facts_verified"]


def test_known_cost_remaining_budget_is_decremented(setup):
    priced = setup.models.create_profile("priced-fixture", "chat", setup.profile["connection_id"], "fixture-model",
        input_usd_per_million=1, output_usd_per_million=1)
    result = run(setup, profile_id=priced["id"], budget={**BUDGET, "max_cost_usd": .2})
    assert result["status"] == "succeeded"
    budgets = result["agent_budget"]["stage_budgets"]
    assert budgets["planner"]["max_cost_usd"] == .2
    assert budgets["selector"]["max_cost_usd"] == pytest.approx(.2 - .00035)
    assert budgets["answer"]["max_cost_usd"] == pytest.approx(.2 - .0007)
    assert result["agent_budget"]["cost_usd"] == pytest.approx(.00105)


def test_unknown_reported_cost_with_monetary_cap_stops_further_stages(setup):
    priced = setup.models.create_profile("priced-fixture", "chat", setup.profile["connection_id"], "fixture-model",
        input_usd_per_million=1, output_usd_per_million=1)
    setup.state["unknown_usage"] = True
    result = run(setup, profile_id=priced["id"], budget={**BUDGET, "max_cost_usd": .2})
    assert result["status"] in {"failed", "partial"} and len(setup.calls) == 1
    assert len(result["receipts"]) == 1 and result["agent_budget"]["cost_known"] is False


def test_post_dispatch_ledger_error_reports_unknown_interval_without_fabricating_receipt(setup, monkeypatch):
    original = setup.ledger.put_record
    def fail_output_persistence(kind, *args, **kwargs):
        if kind == "model_output":
            raise OSError("synthetic output ledger failure after transport")
        return original(kind, *args, **kwargs)
    monkeypatch.setattr(setup.ledger, "put_record", fail_output_persistence)
    result = run(setup)
    assert result["status"] == "failed" and len(setup.calls) == 1
    assert result["receipts"] == [] and result["receipt"] is None
    budget = result["agent_budget"]
    assert budget["actual_receipted_call_count"] == budget["actual_call_count_lower"] == 0
    assert budget["actual_call_count_upper"] == 1 and budget["dispatch_unknown"] is True
    assert budget["uncertain_stages"] == ["planner"] and budget["cost_known"] is False
    assert budget["charged_or_reserved_tokens"] == 16000 + 1536
    assert len(setup.ledger.list_records("model_request")) == 1
    assert not setup.ledger.list_records("model_call")
    assert result["stage_trace"] == [{"stage": "planner", "status": "dispatch_unknown",
        "dispatch_unknown": True, "budget": budget["stage_budgets"]["planner"]}]
