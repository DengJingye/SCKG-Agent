"""Real ledger, vault and gateway; synthetic model transport, never the network."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from sckg_workbench.chat import ChatError, ChatService, MAX_CONTEXT_TURNS
from sckg_workbench.model_service import ModelService
from sckg_workbench.maintenance import MaintenanceService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, canonical_json, content_hash, new_id


PASSPHRASE = "test-only-chat-passphrase"
BUDGET = {"max_input_tokens": 64000, "max_output_tokens": 512, "timeout_seconds": 5,
          "max_cost_usd": 1}


@pytest.fixture
def app(tmp_path):
    ledger = Ledger(Workspace(tmp_path / "isolated-chat"))
    calls = []

    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        return {"id": "synthetic-response", "model": "fixture-model-returned",
                "usage": {"prompt_tokens": 90, "completion_tokens": 12, "total_tokens": 102},
                "choices": [{"finish_reason": "stop", "message": {"content": f"探索回答 {len(calls)}，尚未核验。"}}]}

    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("fixture", "https://model.example/v1", "fixture-key", PASSPHRASE)
    profile = models.create_profile("对话", "chat", connection["id"], "fixture-model",
                                    input_usd_per_million=1, output_usd_per_million=2)
    chat = ChatService(ledger, models)
    conversation = chat.create_conversation()
    return SimpleNamespace(ledger=ledger, models=models, chat=chat, conversation=conversation,
                           connection=connection, profile=profile, calls=calls, transport=transport)


def send(app, prompt="讨论一般方法", **kwargs):
    params = dict(profile_id=app.profile["id"], passphrase=PASSPHRASE, budget=BUDGET,
                  request_id=new_id("send"))
    params.update(kwargs)
    conversation_id = params.pop("conversation_id", app.conversation["id"])
    return app.chat.send(conversation_id, prompt, **params)


def published_source(app, *, uses=None):
    """Synthetic provenance fixture; it claims no scientific validity."""
    source = SourceService(app.ledger).register_bytes("fixture.txt", b"FixtureTool supports a fictional fixture.")
    ir = SourceService(app.ledger).parse(source["id"])
    block = ir["blocks"][0]
    extraction = app.models.create_profile("fixture extractor", "extraction", app.connection["id"], "fixture")
    assessment_profile = app.models.create_profile("fixture assessor", "assessment", app.connection["id"], "fixture")
    claim = {"proposition": block["exact_text"], "subject": "FixtureTool", "predicate": "supports",
             "object": "a fictional fixture", "polarity": "positive", "conditions": ["Test only"],
             "unknowns": ["No scientific validity"], "assertion_kind": "source_assertion",
             "anchors": [{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                          "end": len(block["exact_text"]), "quote": block["exact_text"]}]}
    unit = app.chat.knowledge.add_candidate(claim, run_id="synthetic-run", profile_id=extraction["id"])
    assessment = {"relation": "support", "extent": "full", "rationale": "Synthetic test only", "limitations": []}
    call_id = new_id("synthetic-assessment")
    app.ledger.put_record("model_request", call_id, {"payload": {"messages": [
        {"role": "user", "content": canonical_json(app.chat.knowledge.assessment_input(unit["id"]))}]}})
    app.ledger.put_record("model_call", call_id, {"status": "succeeded", "profile_id": assessment_profile["id"],
                                                "structured_output_hash": content_hash(assessment)})
    assessed = app.chat.knowledge.assess(unit["id"], assessment, run_id="synthetic-assessment-run",
                                       profile_id=assessment_profile["id"], call_id=call_id)
    review = app.chat.knowledge.review(unit["id"], actor="fixture-reviewer", decision="approve",
        allowed_uses=uses or ["explanation", "recommendation"], reason="Synthetic test only",
        expected_hash=unit["content_hash"], expected_assessment_id=assessed["id"])
    release = app.chat.knowledge.publish([unit["id"]], actor="fixture-reviewer",
                                         expected_review_ids={unit["id"]: review["id"]})
    return unit, source, release


def test_empty_library_allows_real_gateway_general_chat_and_records_actual_receipt(app):
    turn = send(app)
    assert turn["status"] == "succeeded" and turn["answer"] == "探索回答 1，尚未核验。"
    assert turn["evidence_package"]["units"] == []
    assert turn["receipt"]["requested_model"] == "fixture-model"
    assert turn["receipt"]["returned_model"] == "fixture-model-returned"
    assert turn["receipt"]["usage"] == {"input_tokens": 90, "output_tokens": 12, "total_tokens": 102}
    assert turn["receipt"]["cost_known"] and turn["receipt"]["cost_usd"] == pytest.approx(0.000114)
    assert app.chat.view_turn(turn)["answer_validation"] == "not_semantically_verified"
    assert not app.ledger.list_records("candidate")
    assert app.calls[0]["model"] == "fixture-model"
    assert "不可信资料" in app.calls[0]["messages"][0]["content"]
    assert "已批准" in app.calls[0]["messages"][0]["content"]
    assert "passphrase" not in canonical_json(app.ledger.list_records("chat_request"))
    assert "fixture-key" not in canonical_json(app.chat.turns(app.conversation["id"]))


def test_restart_preserves_complete_multiturn_pairs_and_new_conversation_isolated(app):
    first = send(app, "我的目标是探索")
    app.chat = ChatService(app.ledger, app.models)
    second = send(app, "继续刚才的问题")
    assert app.calls[-1]["messages"][-3:] == [
        {"role": "user", "content": first["prompt"]}, {"role": "assistant", "content": first["answer"]},
        {"role": "user", "content": second["prompt"]}]
    assert second["context"]["included_turn_ids"] == [first["id"]]
    other = app.chat.create_conversation("独立问题")
    send(app, "从头开始", conversation_id=other["id"])
    assert len(app.calls[-1]["messages"]) == 3
    assert len(app.chat.turns(app.conversation["id"])) == 2
    assert {c["title"] for c in app.chat.list_conversations()} == {"新对话", "独立问题"}


def test_repeated_send_is_idempotent_and_conflicting_reuse_rejected(app):
    first = send(app, request_id="stable-ui-event")
    assert send(app, request_id="stable-ui-event") == first
    assert len(app.calls) == 1
    with pytest.raises(ChatError, match="different send"):
        send(app, "different", request_id="stable-ui-event")


def test_pending_is_persisted_before_outbound_and_replay_does_not_retry(app):
    def checking_transport(*args):
        stored = app.chat.turns(app.conversation["id"])
        assert len(stored) == 1 and stored[0]["status"] == "running"
        assert app.chat.view_turn(stored[0])["answer"] is None
        assert send(app, request_id="pending-event")["status"] == "running"
        with pytest.raises(ChatError, match="未确定完成"):
            send(app, "parallel request")
        return app.transport(*args)
    app.models.transport = checking_transport
    assert send(app, request_id="pending-event")["status"] == "succeeded"
    assert len(app.calls) == 1


def test_unknown_call_retains_error_and_fences_chat_without_automatic_retry(app):
    attempts = []
    def failing(*args):
        attempts.append(True)
        raise TimeoutError("synthetic timeout")
    app.models.transport = failing
    failed = send(app, "保存我的问题", request_id="failed-event")
    assert failed["status"] == "result_unknown" and failed["prompt"] == "保存我的问题"
    assert failed["error"]["outcome"] == "result_unknown" and failed["error"]["call_id"]
    assert send(app, "保存我的问题", request_id="failed-event") == failed and len(attempts) == 1
    app.models.transport = app.transport
    with pytest.raises(ChatError, match="未确定完成"):
        send(app, "不能把未知状态当作可安全重试")
    original = app.conversation["id"]
    app.conversation = app.chat.create_conversation("Explicit independent conversation")
    newer = send(app, "现在重新发送")
    assert newer["status"] == "succeeded" and newer["context"]["omitted_turn_count"] == 0
    assert not newer["context"]["included_turn_ids"]
    assert len(app.chat.turns(original)) == len(app.chat.turns(app.conversation["id"])) == 1


@pytest.mark.parametrize("response", [
    {"choices": [{"finish_reason": "length", "message": {"content": "unfinished"}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "over budget"}}],
     "usage": {"prompt_tokens": 999999, "completion_tokens": 1}},
])
def test_partial_empty_and_overbudget_answers_are_not_usable(app, response):
    app.models.transport = lambda *args: response
    turn = send(app)
    view = app.chat.view_turn(turn)
    assert turn["status"] in {"failed", "partial"}
    assert turn["error"] and not view["usable"] and view["answer"] is None


def test_wrong_profile_and_wrong_passphrase_fail_without_model_fallback(app):
    wrong = app.models.create_profile("wrong purpose", "extraction", app.connection["id"], "another-model")
    assert send(app, profile_id=wrong["id"])["status"] == "failed"
    assert send(app, passphrase="wrong")["status"] == "failed"
    assert app.calls == []


def test_context_limit_omits_whole_turns_and_reports_count(app):
    for n in range(MAX_CONTEXT_TURNS + 2):
        last = send(app, f"complete user message {n}", use_knowledge=False)
    assert len(last["context"]["included_turn_ids"]) == MAX_CONTEXT_TURNS
    assert last["context"]["omitted_turn_count"] == 1
    assert app.calls[-1]["messages"][2]["content"] == "complete user message 1"
    assert "省略了 1" in " ".join(app.chat.view_turn(last)["notices"])


def test_small_budget_drops_old_pairs_without_truncating_current_prompt(app):
    send(app, "A" * 6000, use_knowledge=False)
    turn = send(app, "current intact prompt", use_knowledge=False,
                budget={**BUDGET, "max_input_tokens": 5000})
    assert turn["status"] == "succeeded" and turn["context"]["omitted_turn_count"] == 1
    assert len(app.calls[-1]["messages"]) == 3
    assert app.calls[-1]["messages"][-1]["content"] == "current intact prompt"
    oversized = send(app, "X" * 6000, use_knowledge=False,
                     budget={**BUDGET, "max_input_tokens": 1000})
    assert oversized["status"] == "failed" and len(app.calls) == 2
    assert "未截断" in oversized["error"]["message"]


def test_unpublished_candidates_never_enter_chat_material(app):
    unit, _, release = published_source(app)
    app.chat.knowledge.publish([], actor="fixture", expected_release_id=release["id"])
    turn = send(app, "FixtureTool")
    assert turn["evidence_package"]["units"] == []
    assert unit["id"] not in canonical_json(app.calls[-1])


def test_exact_evidence_and_receipt_are_stored_then_suspension_invalidates_transitive_answers(app):
    unit, source, _ = published_source(app)
    first = send(app, "FixtureTool")
    assert first["evidence_package"]["units"][0]["evidence"][0]["source_id"] == source["id"]
    second = send(app, "继续")
    assert not second["evidence_package"]["units"]
    assert any(p["units"] for p in second["evidence_packages"])
    impact = MaintenanceService(app.ledger).impact_report("source", source["id"])
    assert impact["current_release_candidate_ids"] == [unit["id"]]
    assert [row["turn_id"] for row in impact["exposed_chat_turns"]] == [first["id"], second["id"]]
    assert {row["relationship"] for row in impact["exposed_chat_turns"]} == {"context_exposed_not_verified_citation"}
    app.chat.knowledge.suspend("source", source["id"], actor="fixture", reason="Synthetic quarantine")
    suspended_impact = MaintenanceService(app.ledger).impact_report("source", source["id"])
    assert suspended_impact["governance_version"] > impact["governance_version"]
    assert suspended_impact["exposed_chat_turns"] == impact["exposed_chat_turns"]
    for turn in [first, second]:
        view = app.chat.view_turn(turn)
        assert view["current_status"] == "evidence_invalidated" and view["answer"] is None
    third = send(app, "现在一般性讨论")
    assert first["id"] not in third["context"]["included_turn_ids"]
    assert second["id"] not in third["context"]["included_turn_ids"]
    assert unit["id"] not in canonical_json(app.calls[-1])


def test_blob_corruption_revalidated_without_governance_event(app):
    _, source, _ = published_source(app)
    turn = send(app, "FixtureTool")
    version = app.ledger.get_state("governance_version")
    path = app.ledger.workspace.artifacts_dir / "source_blobs" / source["blob_sha256"]
    path.write_bytes(b"synthetic fixture damage")
    assert app.ledger.get_state("governance_version") == version
    assert not app.chat.view_turn(turn)["usable"]


def test_disabling_knowledge_removes_prior_evidence_dependent_assistant(app):
    unit, _, _ = published_source(app)
    first = send(app, "FixtureTool")
    second = send(app, "without local material", use_knowledge=False)
    assert second["evidence_package"] is None and second["evidence_packages"] == []
    assert second["context"]["omitted_turn_count"] == 1
    assert first["id"] not in second["context"]["included_turn_ids"]
    assert unit["id"] not in canonical_json(app.calls[-1])


def test_explanation_only_material_is_not_replayed_for_recommendation(app):
    unit, _, _ = published_source(app, uses=["explanation"])
    first = send(app, "FixtureTool")
    second = send(app, "FixtureTool", purpose="recommendation")
    assert second["evidence_package"]["units"] == []
    assert first["id"] not in second["context"]["included_turn_ids"]
    assert unit["id"] not in canonical_json(app.calls[-1])


@pytest.mark.parametrize("change", ["suspend", "corrupt", "release"])
def test_evidence_changes_during_outbound_block_answer(app, change):
    _, source, release = published_source(app)
    def changing(*args):
        if change == "suspend":
            app.chat.knowledge.suspend("source", source["id"], actor="fixture", reason="Changed during call")
        elif change == "corrupt":
            (app.ledger.workspace.artifacts_dir / "source_blobs" / source["blob_sha256"]).write_bytes(b"damaged")
        else:
            app.chat.knowledge.publish([], actor="fixture", expected_release_id=release["id"])
        return app.transport(*args)
    app.models.transport = changing
    turn = send(app, "FixtureTool")
    assert turn["status"] == "blocked" and turn["receipt"]["status"] == "succeeded"
    assert app.chat.view_turn(turn)["answer"] is None


def test_unknown_usage_remains_unknown_and_invalid_view_argument_cannot_replace_answer(app):
    app.models.transport = lambda *args: {"choices": [{"finish_reason": "stop", "message": {"content": "探索"}}]}
    turn = send(app)
    assert not turn["receipt"]["cost_known"] and turn["receipt"]["cost_usd"] is None
    assert not turn["receipt"]["usage_known"]
    assert app.chat.view_turn({**turn, "answer": "forged"})["answer"] == "探索"


def test_cross_workspace_conversation_and_model_service_rejected(app, tmp_path):
    other = Ledger(Workspace(tmp_path / "other-chat"))
    with pytest.raises(ChatError, match="different workspace"):
        ChatService(other, app.models)
    foreign = ChatService(other).create_conversation()
    with pytest.raises(ChatError, match="Unknown conversation"):
        send(app, conversation_id=foreign["id"])


def test_simultaneous_replay_is_pending_and_only_one_gateway_call(app):
    entered, release = Event(), Event()
    def controlled(*args):
        entered.set()
        assert release.wait(5)
        return app.transport(*args)
    app.models.transport = controlled
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(send, app, request_id="same-click")
        assert entered.wait(5)
        try:
            replay = send(app, request_id="same-click")
            assert replay["status"] == "running"
        finally:
            release.set()
        assert future.result(timeout=5)["status"] == "succeeded"
    assert len(app.calls) == 1


def test_interrupted_pending_send_is_not_retried_after_restart(app):
    def interrupted(*args):
        raise KeyboardInterrupt("synthetic process interruption")
    app.models.transport = interrupted
    with pytest.raises(KeyboardInterrupt):
        send(app, request_id="interrupted")
    app.chat = ChatService(app.ledger, app.models)
    assert send(app, request_id="interrupted")["status"] == "result_unknown"
    assert app.chat.view_turn(app.chat.turns(app.conversation["id"])[0])["answer"] is None
    with pytest.raises(ChatError, match="未确定完成"):
        send(app)


def test_post_call_validation_exception_keeps_actual_model_usage(app, monkeypatch):
    checks = []
    def validator(*args, **kwargs):
        checks.append(True)
        if len(checks) == 2:
            raise OSError("Synthetic evidence validation failure")
    monkeypatch.setattr(app.chat, "_evidence_problem", validator)
    turn = send(app)
    assert turn["status"] == "failed"
    assert turn["receipt"]["cost_known"] and turn["receipt"]["usage"]["total_tokens"] == 102
    assert app.chat.view_turn(turn)["answer"] is None
