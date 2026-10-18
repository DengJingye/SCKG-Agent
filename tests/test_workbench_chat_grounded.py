"""Actual chat/KB/gateway integration with explicitly synthetic local evidence.

No provider, fit or scientific adjudication. Fixture review records are synthetic
test inputs in a temporary workspace, never production human-review assertions.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from sckg_workbench import grounded_chat
from sckg_workbench.chat import ChatError, ChatService
from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import canonical_json, content_hash, new_id
from tests.test_workbench_grounded_chat import setup, BUDGET, PLAN, ANSWER


def _eligible_local_unit(ledger, models, knowledge, connection_id, suffix):
    """Reuse the established real local source/candidate/review fixture pattern."""
    sources = SourceService(ledger)
    source = sources.register_bytes(f"fixture-{suffix}.txt",
        f"FixtureTool synthetic method supports fictional fixture {suffix}.".encode())
    ir = sources.parse(source["id"])
    block = ir["blocks"][0]
    extraction = models.create_profile(f"fixture-extract-{suffix}", "extraction", connection_id, "fixture")
    assessment_profile = models.create_profile(f"fixture-assess-{suffix}", "assessment", connection_id, "fixture")
    claim = {"proposition": block["exact_text"], "subject": "FixtureTool", "predicate": "supports",
        "object": "fictional fixture " + suffix, "polarity": "positive", "assertion_kind": "source_assertion",
        "conditions": ["Synthetic test condition " + suffix], "unknowns": ["Not scientific gold " + suffix],
        "anchors": [{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                     "end": len(block["exact_text"]), "quote": block["exact_text"]}]}
    unit = knowledge.add_candidate(claim, run_id="synthetic-fixture-input", profile_id=extraction["id"])
    assessment = {"relation": "support", "extent": "full", "rationale": "Synthetic fixture only", "limitations": []}
    call_id = new_id("synthetic-assessment-fixture")
    ledger.put_record("model_request", call_id, {"payload": {"messages": [
        {"role": "user", "content": canonical_json(knowledge.assessment_input(unit["id"]))}]}})
    ledger.put_record("model_call", call_id, {"status": "succeeded", "profile_id": assessment_profile["id"],
                                             "structured_output_hash": content_hash(assessment)})
    assessed = knowledge.assess(unit["id"], assessment, run_id="synthetic-fixture-assessment", 
        profile_id=assessment_profile["id"], call_id=call_id)
    review = knowledge.review(unit["id"], actor="synthetic fixture reviewer", decision="approve",
        allowed_uses=["explanation"], reason="Synthetic test record, not scientific human review",
        expected_hash=unit["content_hash"], expected_assessment_id=assessed["id"])
    return unit, source, review


@pytest.fixture
def case(setup, monkeypatch):
    # Reuse the existing fixture's actual gateway and explicit scripted outputs,
    # replacing its in-memory knowledge double with the real local KB boundary.
    monkeypatch.setattr(grounded_chat, "KnowledgeService", KnowledgeService)
    chat = ChatService(setup.ledger, setup.models)
    knowledge = chat.knowledge
    rows = [_eligible_local_unit(setup.ledger, setup.models, knowledge,
                                setup.profile["connection_id"], suffix) for suffix in ("A", "B")]
    release = knowledge.publish([unit["id"] for unit, _, _ in rows], actor="synthetic fixture publisher",
        expected_review_ids={unit["id"]: review["id"] for unit, _, review in rows})
    plan = deepcopy(PLAN)
    plan["queries"] = [{"language": "en", "text": "FixtureTool synthetic fictional fixture"}]
    plan["evidence_checks"] = ["Which explicit fictional test condition applies?"]
    # Cards identify only the aliases sent in this selector request. Real IDs,
    # complete evidence and anchors are restored by the existing selection code.
    selection = {"s": [{"e": f"E{index}", "p": index, "c": [0]}
                       for index in range(1, len(rows) + 1)], "u": [], "r": [{"c": 0, "e": ["E1"]}], "k": [0]}
    answer = deepcopy(ANSWER)
    answer["s"][0].update(f="The selected source describes a fictional fixture.", e=["E2"])
    setup.state["outputs"] = [deepcopy(plan), deepcopy(selection), deepcopy(answer)]
    return SimpleNamespace(**vars(setup), chat=chat, real_knowledge=knowledge,
        conversation=chat.create_conversation("Synthetic grounded chat"), rows=rows, release=release,
        outputs=[plan, selection, answer])


def send(case, prompt="Which fictional FixtureTool conditions apply?", **changes):
    options = {"profile_id": case.profile["id"], "passphrase": "fixture-pass", "budget": deepcopy(BUDGET),
               "request_id": "fixed-grounded-send", "grounded_mode": True}
    options.update(changes)
    return case.chat.send(case.conversation["id"], prompt, **options)


def test_actual_chat_three_stages_final_selection_and_pure_server_citations(case, monkeypatch):
    turn = send(case)
    assert turn["status"] == "succeeded" and len(case.calls) == 3
    run = turn["grounded_run"]
    assert [step["stage"] for step in run["stage_trace"]] == ["planner", "selector", "answer"]
    assert len(turn["receipts"]) == 3 and turn["agent_budget"]["model_calls"] == 3
    assert turn["evidence_packages"][-1] == run["evidence_package"]
    assert turn["evidence_package"] == run["evidence_package"]
    assert len(run["selection"]["units"]) == 2
    assert run["agent_budget"]["selection_limits"]["candidate_mode"] == "scoped_required_entries"
    assert run["agent_budget"]["selection_limits"]["candidate_limit"] == 32
    selected = run["selection"]
    selector = selected["selection_run"]
    assert selected["schema_version"] == "selected-evidence-retrieval-v6"
    assert selector["schema_version"] == "evidence-selection-run-v6"
    assert selector["candidate_mode"] == "scoped_required_entries"
    assert selector["card_content_status"] == "claim_preview_not_original_evidence"
    assert selector["selection"] == case.outputs[1]
    assert all(set(row) == {"e", "p", "c"} for row in selector["selection"]["s"])
    full_by_id = {unit["candidate_id"]: unit for unit in selected["units"]}
    for card in selector["candidate_cards"]:
        assert set(card) == {"alias", "subject", "predicate", "object", "polarity", "assertion_kind", "proposition", "conditions", "unknowns"}
        cid = selector["alias_manifest"][card["alias"]]["candidate_id"]
        full = full_by_id[cid]
        assert {key: card[key] for key in ("proposition", "conditions", "unknowns")} == {
            key: full["claim"][key] for key in ("proposition", "conditions", "unknowns")}
        assert full["evidence"] and full["claim"]["anchors"]
    cited = run["normalized_answer"]["steps"][0]["evidence_ids"]
    assert len(cited) == 1
    with monkeypatch.context() as guard:
        guard.setattr(case.models, "invoke", lambda *a, **k: pytest.fail("view attempted a model request"))
        view = case.chat.view_turn(turn)
    manifest = view["citation_manifest"]
    assert view["usable"] and manifest["schema_version"] == "chat-source-citations-v1"
    assert manifest["validation"] == "selected_id_binding_only_not_semantic_support"
    assert len(manifest["items"]) == 1
    item = manifest["items"][0]
    assert item["number"] == 1 and item["alias"] == "E2" and item["candidate_id"] == cited[0]
    original = next(unit for unit in run["selection"]["units"] if unit["candidate_id"] == cited[0])
    assert item["unit"] == original and item["unit"]["claim"]["conditions"]
    assert item["unit"]["claim"]["unknowns"] and item["unit"]["evidence"][0]["locator"]
    assert run["semantic_support"] == "not_assessed" and not run["scientific_facts_verified"]
    assert len(case.calls) == 3


def test_manifest_number_order_is_selected_unit_order_not_model_reference_order(case):
    case.state["outputs"][2]["s"][0]["e"] = ["E2", "E1"]
    turn = send(case)
    assert turn["status"] == "succeeded"
    items = case.chat.view_turn(turn)["citation_manifest"]["items"]
    assert [item["number"] for item in items] == [1, 2]
    assert [item["candidate_id"] for item in items] == [
        unit["candidate_id"] for unit in turn["grounded_run"]["selection"]["units"]]
    assert [item["alias"] for item in items] == ["E1", "E2"]


def test_grounded_same_request_replay_is_zero_call_and_mode_change_conflicts(case):
    first = send(case)
    assert first["status"] == "succeeded" and len(case.calls) == 3
    assert send(case) == first and len(case.calls) == 3
    with pytest.raises(ChatError, match="different send"):
        send(case, grounded_mode=False)
    assert len(case.calls) == 3


@pytest.mark.parametrize("change", [{"use_knowledge": False}, {"analysis_options": {}},
                                    {"result_ref": "not-a-free-target"}, {"grounded_mode": "true"}])
def test_grounded_conflicts_fail_before_any_request_record_or_dispatch(case, change):
    with pytest.raises(ChatError):
        send(case, **change)
    assert case.calls == [] and case.ledger.list_records("chat_request") == []


def test_default_and_explicit_false_keep_ordinary_hash_and_single_request(case):
    case.state["outputs"] = ["Synthetic ordinary answer"]
    options = {"profile_id": case.profile["id"], "passphrase": "fixture-pass", "budget": deepcopy(BUDGET),
               "request_id": "ordinary-legacy-hash", "use_knowledge": False}
    prompt = "Synthetic ordinary discussion"
    first = case.chat.send(case.conversation["id"], prompt, **options)
    assert first["status"] == "succeeded" and len(case.calls) == 1 and "grounded_run" not in first
    saved = case.ledger.get_record("chat_request", first["id"])
    assert "grounded_mode" not in saved
    assert saved["request_hash"] == content_hash({"conversation_id": case.conversation["id"], "prompt": prompt,
        "profile_id": case.profile["id"], "use_knowledge": False, "purpose": "explanation", "budget": BUDGET})
    assert case.chat.send(case.conversation["id"], prompt, grounded_mode=False, **options) == first
    assert len(case.calls) == 1


@pytest.mark.parametrize("damage", ["blob", "release"])
def test_changed_source_or_release_invalidates_view_and_excludes_future_history(case, damage, monkeypatch):
    first = send(case)
    assert first["status"] == "succeeded" and case.chat.view_turn(first)["usable"]
    if damage == "blob":
        source = case.rows[0][1]
        (case.ledger.workspace.artifacts_dir / "source_blobs" / source["blob_sha256"]).write_bytes(b"synthetic corruption")
    else:
        case.real_knowledge.publish([], actor="synthetic fixture withdrawal", expected_release_id=case.release["id"])
    with monkeypatch.context() as guard:
        guard.setattr(case.models, "invoke", lambda *a, **k: pytest.fail("view retried generation"))
        view = case.chat.view_turn(first)
    assert not view["usable"] and view["answer"] is None and view["current_status"] == "evidence_invalidated"
    assert "citation_manifest" not in view and len(case.calls) == 3
    case.state["outputs"].append("Synthetic later general answer")
    later = send(case, "zxqv unmatched general discussion", grounded_mode=False, request_id="later-explicit-send")
    assert later["status"] == "succeeded" and len(case.calls) == 4
    assert first["id"] not in later["context"]["included_turn_ids"]
    assert first["id"] in later["context"]["excluded_turn_ids"]
    assert first["answer"] not in canonical_json(case.calls[-1])


def test_selector_failure_preserves_receipts_reservations_and_replay_does_not_retry(case):
    case.state["fail_stage"] = 1
    turn = send(case)
    assert turn["status"] == "result_unknown" and len(case.calls) == 2
    assert len(turn["receipts"]) == 2 and turn["receipts"][-1]["status"] == "failed"
    assert turn["grounded_run"]["plan"] is not None and turn["grounded_run"]["answer_run"] is None
    budget = turn["agent_budget"]
    assert budget["model_calls"] == 2 and not budget["cost_known"] and budget["cost_usd"] is None
    failed_stage = budget["stage_budgets"]["selector"]
    assert budget["charged_or_reserved_tokens"] == 350 + failed_stage["max_input_tokens"] + failed_stage["max_output_tokens"]
    for receipt in turn["receipts"]:
        assert case.ledger.get_record("model_call", receipt["call_id"]) == receipt
    assert send(case) == turn and len(case.calls) == 2
    assert not case.chat.view_turn(turn)["usable"]


def test_compact_alias_failure_keeps_all_three_receipts_without_repair(case):
    case.state["outputs"][2]["s"][0]["e"] = ["E99"]
    turn = send(case)
    assert turn["status"] == "failed" and len(case.calls) == 3 and len(turn["receipts"]) == 3
    assert turn["grounded_run"]["answer_run"] is None and turn["answer"] is None
    assert not case.chat.view_turn(turn)["usable"]


def test_grounded_history_trims_whole_pairs_before_planner_without_truncating_current_question(case):
    case.state["outputs"] = ["FIRST_SYNTHETIC_REPLY", "SECOND_SYNTHETIC_REPLY", *deepcopy(case.outputs)]
    first = send(case, "OLDER_MARKER_" + "a" * 6500, grounded_mode=False, use_knowledge=False, request_id="old-1")
    second = send(case, "KEPT_MARKER_" + "b" * 6500, grounded_mode=False, use_knowledge=False, request_id="old-2")
    question = "CURRENT_QUESTION_STAYS_INTACT: Which fictional fixture conditions apply?"
    current = send(case, question, request_id="grounded-with-history")
    assert current["status"] == "succeeded" and len(case.calls) == 5
    assert current["context"]["included_turn_ids"] == [second["id"]]
    assert current["context"]["omitted_turn_count"] == 1
    expected = [{"role": "user", "content": second["prompt"]}, {"role": "assistant", "content": second["answer"]}]
    assert current["grounded_run"]["history_used"] == expected
    planner_material = json.loads(case.calls[2]["messages"][1]["content"])
    assert planner_material["dataset_profile"]["untrusted_conversation_context"] == expected
    assert question in canonical_json(planner_material) and first["prompt"] not in canonical_json(planner_material)


def test_oversized_current_grounded_question_stops_without_dispatch_or_silent_truncation(case):
    turn = send(case, "q" * 7000, budget={**BUDGET, "max_input_tokens": 5000})
    assert turn["status"] == "failed" and case.calls == []
    assert "未截断" in turn["error"]["message"]


def test_post_answer_validation_exception_retains_completed_grounded_trace_and_budget(case, monkeypatch):
    original = case.chat._evidence_problem

    def fail_after_three_returns(*args, **kwargs):
        if len(case.calls) == 3:
            raise OSError("Synthetic post-answer evidence revalidation failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(case.chat, "_evidence_problem", fail_after_three_returns)
    turn = send(case)
    assert turn["status"] == "failed" and turn["error"]["type"] == "OSError"
    assert len(case.calls) == 3 and len(turn["receipts"]) == 3
    assert turn["grounded_run"]["status"] == "succeeded"
    assert turn["grounded_run"]["answer_run"] is not None
    assert turn["receipts"] == turn["grounded_run"]["receipts"]
    assert turn["agent_budget"] == turn["grounded_run"]["agent_budget"]
    assert turn["agent_budget"]["model_calls"] == 3
    assert turn["agent_budget"]["charged_or_reserved_tokens"] == 1050
    for receipt in turn["receipts"]:
        assert case.ledger.get_record("model_call", receipt["call_id"]) == receipt
    assert send(case) == turn and len(case.calls) == 3
    assert not case.chat.view_turn(turn)["usable"]


def _replace_own_test_record(ledger, kind, identity, value):
    """Simulate rehashed tampering in this temporary test DB, never production."""
    with ledger.transaction() as connection:
        cursor = connection.execute("UPDATE records SET payload=?,digest=? WHERE kind=? AND record_id=?",
            (canonical_json(value), content_hash(value), kind, identity))
        assert cursor.rowcount == 1


def test_plain_followup_inherits_grounded_raw_output_invalidation_and_is_excluded_later(case, monkeypatch):
    first = send(case)
    assert first["status"] == "succeeded" and len(case.calls) == 3
    case.state["outputs"].append("Synthetic ordinary followup answer")
    followup = send(case, "Continue the prior fictional condition discussion", grounded_mode=False,
                    request_id="inherited-grounded-followup")
    assert followup["status"] == "succeeded" and len(case.calls) == 4
    assert first["id"] in followup["grounded_context_turn_ids"]
    assert case.chat.view_turn(followup)["usable"]
    call_id = first["grounded_run"]["answer_run"]["call_id"]
    damaged = case.ledger.get_record("model_output", call_id)
    damaged["text"] = "Synthetic corrupted original model output"
    damaged["text_hash"] = content_hash(damaged["text"])
    _replace_own_test_record(case.ledger, "model_output", call_id, damaged)
    with monkeypatch.context() as guard:
        guard.setattr(case.models, "invoke", lambda *a, **k: pytest.fail("view retried a model request"))
        first_view = case.chat.view_turn(first)
        followup_view = case.chat.view_turn(followup)
    assert not first_view["usable"] and not followup_view["usable"]
    assert followup_view["current_status"] == "evidence_invalidated" and followup_view["answer"] is None
    assert "citation_manifest" not in followup_view and len(case.calls) == 4
    case.state["outputs"].append("Synthetic later independent discussion")
    later = send(case, "zxqv unmatched later discussion", grounded_mode=False, request_id="after-transitive-invalidation")
    assert later["status"] == "succeeded" and len(case.calls) == 5
    for previous in (first, followup):
        assert previous["id"] not in later["context"]["included_turn_ids"]
        assert previous["id"] in later["context"]["excluded_turn_ids"]
        assert previous["answer"] not in canonical_json(case.calls[-1])


def test_second_view_validation_failure_returns_unusable_without_propagating_exception(case, monkeypatch):
    turn = send(case)
    assert turn["status"] == "succeeded" and len(case.calls) == 3
    original = case.chat._validated_grounded_answer
    validations = []

    def source_disappears_on_second_validation(value):
        validations.append(value["id"])
        if len(validations) == 2:
            raise OSError("Synthetic source disappearance between validation and display")
        return original(value)

    monkeypatch.setattr(case.chat, "_validated_grounded_answer", source_disappears_on_second_validation)
    view = case.chat.view_turn(turn)
    assert len(validations) == 2
    assert not view["usable"] and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and "citation_manifest" not in view
    assert len(case.calls) == 3


def test_valid_grounded_trace_cannot_be_swapped_into_a_different_question_turn(case, monkeypatch):
    first = send(case, "FIRST distinct FixtureTool applicability question")
    case.state["outputs"].extend(deepcopy(case.outputs))
    second = send(case, "SECOND different FixtureTool applicability question", request_id="different-grounded-turn")
    assert first["status"] == second["status"] == "succeeded" and len(case.calls) == 6
    substituted = case.ledger.get_record("chat_result", second["id"])
    for key in ("grounded_run", "answer", "receipts", "receipt", "agent_budget"):
        substituted[key] = deepcopy(first[key])
    _replace_own_test_record(case.ledger, "chat_result", second["id"], substituted)
    with monkeypatch.context() as guard:
        guard.setattr(case.models, "invoke", lambda *a, **k: pytest.fail("view attempted to repair swapped trace"))
        view = case.chat.view_turn(second)
    assert not view["usable"] and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and "citation_manifest" not in view and len(case.calls) == 6
