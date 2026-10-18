"""Read-only result follow-up boundaries; synthetic gateway, no scientific fit.

Fixtures use the real ledger, queue, saved artifacts and their actual integrity
checks. Their synthetic execution receipts are not scientific evidence.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from sckg_workbench.analysis import AnalysisService
from sckg_workbench.agent_loop import AgentLoopError, AnalysisAgentLoop
from sckg_workbench.chat import ChatService
from sckg_workbench.model_service import ModelService
from sckg_workbench.storage import canonical_json, content_hash
from sckg_workbench.tasks import TaskQueue
from tests.test_workbench_agent_loop import BUDGET, PASSPHRASE, app, send as _analysis_send
from tests.test_workbench_result_summary import make_summary_fixture, read_summary


def _forbid_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Read-only result follow-up attempted analysis execution")
    for method in ("submit_scrublet", "run_once", "_execute", "_execute_supervised"):
        monkeypatch.setattr(AnalysisService, method, forbidden)
    return forbidden


def test_unknown_registered_action_has_no_execution_fallthrough(app, monkeypatch):
    _forbid_execution(monkeypatch)
    with pytest.raises(AgentLoopError):
        AnalysisAgentLoop(app.ledger, app.models)._tool(
            "unregistered_action", {}, turn_id="synthetic-read-only-turn", index=0)
    assert not app.calls and not TaskQueue(app.ledger.workspace).list()


def test_failed_profile_stays_failed_despite_model_success_prose(app, monkeypatch):
    _forbid_execution(monkeypatch)
    app.path.write_bytes(b"changed synthetic input; do not decode")
    app.actions.extend([
        {"action": "inspect_dataset", "answer": ""},
        {"action": "finish", "answer": "Synthetic model says analysis completed successfully."},
    ])
    turn = _analysis_send(app)
    assert turn["status"] == "failed" and turn["answer"] is None
    assert turn["agent_steps"][0]["result"]["status"] == "failed"
    assert turn["analysis_task_ids"] == []
    view = app.chat.view_turn(turn)
    assert view["analysis_outcome"]["state"] == "profile_failed"
    assert view["analysis_outcome"]["validated_preview"] is False
    assert not TaskQueue(app.ledger.workspace).list()


def test_client_forged_reply_cannot_replace_stored_failed_profile(app, monkeypatch):
    _forbid_execution(monkeypatch)
    app.path.write_bytes(b"changed synthetic fixture")
    app.actions.extend([
        {"action": "inspect_dataset", "answer": ""},
        {"action": "finish", "answer": "The fixture profile failed."},
    ])
    turn = _analysis_send(app)
    forged = {**deepcopy(turn), "answer": "Everything succeeded", "analysis_task_ids": ["forged-task"],
              "analysis_outcome": {"state": "validated_preview", "validated_preview": True}}
    view = app.chat.view_turn(forged)
    assert view["analysis_outcome"]["state"] == "profile_failed"
    assert view["analysis_outcome"]["validated_preview"] is False
    assert view["answer"] == turn["answer"]


@pytest.mark.parametrize("bad_ref", ["not-a-server-result-ref", "", True, {"attempt": 999}])
def test_unknown_or_nonstring_ref_rejected_before_model_or_task(app, monkeypatch, bad_ref):
    _forbid_execution(monkeypatch)
    # A valid ordinary send proves that the app/profile/conversation fixture is
    # usable before testing the reference rejection itself.
    app.actions.append("Ordinary synthetic fixture reply.")
    baseline = _analysis_send(app, analysis_options=None, request_id="valid-baseline")
    assert baseline["status"] == "succeeded"
    before = len(app.calls)
    with pytest.raises(ValueError):
        _analysis_send(app, analysis_options=None, result_ref=bad_ref,
                       request_id="invalid-result-ref")
    assert len(app.calls) == before
    assert not TaskQueue(app.ledger.workspace).list()
    assert not app.ledger.list_records("analysis_result")


ORIGINAL_NUMERIC_PROSE = "Synthetic earlier result number 123456789; not scientific evidence."
FOLLOWUP_NUMERIC_PROSE = "Synthetic result follow-up number 987654321; not scientific evidence."


@pytest.fixture
def result_app(tmp_path, monkeypatch):
    fixture = make_summary_fixture(tmp_path, n_cells=8, positive_count=2)
    # Every counterexample starts from a result accepted by the real validator,
    # store, lineage and current-task checks, not a mocked True return value.
    assert read_summary(fixture)["status"] == "validated_preview_summary"
    service = fixture["service"]
    ledger = service.ledger
    calls, actions = [], []

    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        action = actions.pop(0)
        if callable(action):
            action = action(payload)
        return {"model": "synthetic-result-followup-model", "usage": {
                    "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "choices": [{"finish_reason": "stop", "message": {"content":
                    json.dumps(action, ensure_ascii=False) if isinstance(action, dict) else action}}]}

    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("synthetic result fixture", "https://fixture.invalid/v1",
                                          "synthetic-test-key", PASSPHRASE)
    profile = models.create_profile("synthetic chat", "chat", connection["id"], "synthetic-model",
                                    input_usd_per_million=1, output_usd_per_million=2)
    chat = ChatService(ledger, models)
    conversation = chat.create_conversation("Synthetic saved-result fixture")
    options = {"asset_id": fixture["asset"]["asset_id"], "count_source": "X",
               "count_provenance": "Synthetic validator fixture; never an actual science run",
               "expected_doublet_rate": .06, "dataset_origin": "synthetic"}
    actions.extend([{"action": "run_scrublet", "answer": ""},
                    {"action": "finish", "answer": ORIGINAL_NUMERIC_PROSE}])
    # Seed the real chat protocol with this precompleted *synthetic* task. Its
    # output verification stays real. The one setup interception is not used to
    # establish that a fit happened, and it is removed before boundary tests.
    completed = service.get_task_snapshot(fixture["task_id"])
    with monkeypatch.context() as seed:
        seed.setattr(AnalysisService, "submit_scrublet", lambda *a, **k: deepcopy(completed))
        seed.setattr(AnalysisService, "_execute_supervised",
                     lambda *a, **k: pytest.fail("Fixture must not execute scientific work"))
        original = chat.send(conversation["id"], "Synthetic precompleted fixture result", profile_id=profile["id"],
            passphrase=PASSPHRASE, use_knowledge=False, budget=BUDGET,
            request_id="synthetic-result-origin", analysis_options=options)
    assert original["status"] == "succeeded" and original["analysis_task_ids"] == [fixture["task_id"]]
    choices = chat.list_result_tasks(conversation["id"])
    assert len(choices) == 1 and choices[0]["task_id"] == fixture["task_id"]
    assert choices[0]["source_turn_id"] == original["id"]
    assert read_summary(fixture)["status"] == "validated_preview_summary"
    return SimpleNamespace(fixture=fixture, service=service, ledger=ledger, models=models,
        chat=chat, profile=profile, conversation=conversation, original=original, selection=choices[0],
        options=options, calls=calls, actions=actions)


def _result_send(app, *, request_id="read-saved-result", conversation_id=None, **overrides):
    kwargs = {"profile_id": app.profile["id"], "passphrase": PASSPHRASE, "use_knowledge": False,
              "budget": BUDGET, "request_id": request_id, "result_ref": app.selection["result_ref"]}
    kwargs.update(overrides)
    return app.chat.send(conversation_id or app.conversation["id"],
                         "Explain this selected saved result without executing analysis", **kwargs)


def _assert_no_new_analysis(app):
    assert len(app.ledger.list_records("task_submission")) == 1
    assert len(app.ledger.list_records("analysis_result")) == 1
    assert app.service.get_task_snapshot(app.fixture["task_id"])["attempt"] == app.fixture["attempt"]


def test_readonly_followup_uses_server_binding_and_aggregates_without_execution(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    before = len(a.calls)
    a.actions.extend([{"action": "read_analysis_result", "answer": ""},
                      {"action": "finish", "answer": FOLLOWUP_NUMERIC_PROSE}])
    turn = _result_send(a)
    assert turn["status"] == "succeeded" and len(a.calls) == before + 2
    assert turn["analysis_task_ids"] == []
    assert turn["referenced_analysis_task_ids"] == [a.fixture["task_id"]]
    selected = {k: v for k, v in a.selection.items() if k != "task_status"}
    assert turn["result_selection"] == selected
    assert a.ledger.get_record("chat_request", turn["id"])["result_selection"] == selected
    step = turn["agent_steps"][0]
    assert step["action"] == "read_analysis_result"
    assert step["result"]["summary"]["metrics"] == {"n_cells": 8, "predicted_doublet_count": 2,
        "predicted_non_doublet_count": 6, "predicted_doublet_call_rate": .25}
    assert step["result"]["summary"]["threshold"] == {"value": None, "status": "not_recorded"}
    assert not step["result"]["summary"]["computation_performed_by_read"]
    assert not step["result"]["summary"]["scientific_claim_allowed"]
    view = a.chat.view_turn(turn)
    assert view["usable"] and view["analysis_outcome"]["state"] == "result_read"
    assert view["analysis_outcome"]["computation_performed_by_read"] is False
    assert a.calls[before]["response_format"]["json_schema"]["schema"]["properties"]["action"]["enum"] == [
        "read_analysis_result", "finish"]
    outbound = canonical_json(a.calls[before:])
    assert str(a.fixture["source"]) not in outbound and "private-fixture-cell-" not in outbound
    _assert_no_new_analysis(a)
    assert _result_send(a) == turn and len(a.calls) == before + 2


@pytest.mark.parametrize("action", ["run_scrublet", "inspect_dataset", "unknown_action"])
def test_readonly_model_cannot_switch_to_execution_or_unknown_action(result_app, monkeypatch, action):
    a = result_app
    _forbid_execution(monkeypatch)
    before = len(a.calls)
    a.actions.append({"action": action, "answer": "Do not accept this synthetic action"})
    turn = _result_send(a)
    assert turn["status"] == "failed" and len(a.calls) == before + 1
    assert turn["receipts"][-1]["status"] == "invalid_response"
    assert turn["analysis_task_ids"] == [] and not turn["agent_steps"]
    _assert_no_new_analysis(a)


def test_same_workspace_other_conversation_cannot_read_reference(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    other = a.chat.create_conversation("No result authority here")
    before = len(a.calls)
    assert a.chat.list_result_tasks(other["id"]) == []
    with pytest.raises(ValueError):
        _result_send(a, conversation_id=other["id"])
    assert len(a.calls) == before
    _assert_no_new_analysis(a)


def test_valid_ref_and_execution_options_are_mutually_exclusive(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    before = len(a.calls)
    with pytest.raises(ValueError):
        _result_send(a, analysis_options=a.options)
    assert len(a.calls) == before
    _assert_no_new_analysis(a)


@pytest.mark.parametrize("change", [{"attempt": 2}, {"run_id": "another-run"}, {"task_id": "another-task"}])
def test_client_cannot_pass_modified_selection_dictionary(result_app, monkeypatch, change):
    a = result_app
    _forbid_execution(monkeypatch)
    before = len(a.calls)
    with pytest.raises(ValueError):
        _result_send(a, result_ref={**a.selection, **change})
    assert len(a.calls) == before
    assert read_summary(a.fixture)["status"] == "validated_preview_summary"
    _assert_no_new_analysis(a)


def test_service_wrong_attempt_or_run_never_returns_current_metrics(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    assert read_summary(a.fixture)["status"] == "validated_preview_summary"
    for override in ({"attempt": 2}, {"run_id": "not-the-selected-run"}):
        rejected = read_summary(a.fixture, **override)
        assert rejected["status"] == "unavailable" and "metrics" not in rejected
    _assert_no_new_analysis(a)


def test_assistant_task_id_prose_is_not_a_server_result_reference(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    other = a.chat.create_conversation("Only prose, no execution turn")
    a.actions.append("Synthetic assistant mentions task_id=" + a.fixture["task_id"])
    prose = a.chat.send(other["id"], "A text-only fixture", profile_id=a.profile["id"],
        passphrase=PASSPHRASE, use_knowledge=False, budget=BUDGET, request_id="text-only-prose")
    assert prose["status"] == "succeeded"
    assert a.chat.list_result_tasks(other["id"]) == []
    _assert_no_new_analysis(a)


def test_artifact_tamper_excludes_original_and_inherited_numeric_prose(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    a.actions.extend([{"action": "read_analysis_result", "answer": ""},
                      {"action": "finish", "answer": FOLLOWUP_NUMERIC_PROSE}])
    followup = _result_send(a)
    assert followup["status"] == "succeeded" and a.chat.view_turn(followup)["usable"]
    table = a.fixture["outputs"] / "doublet_results.tsv"
    table.write_bytes(table.read_bytes() + b"synthetic integrity corruption")
    assert read_summary(a.fixture)["status"] == "unavailable"
    for prior in (a.original, followup):
        view = a.chat.view_turn(prior)
        assert not view["usable"] and view["current_status"] == "result_invalidated"
        assert view["answer"] is None
    a.actions.append("Fresh synthetic answer without stale numbers.")
    ordinary = _result_send(a, request_id="after-tamper-ordinary", result_ref=None)
    assert ordinary["status"] == "succeeded"
    outbound = canonical_json(a.calls[-1]["messages"])
    assert ORIGINAL_NUMERIC_PROSE not in outbound and FOLLOWUP_NUMERIC_PROSE not in outbound
    assert {a.original["id"], followup["id"]} <= set(ordinary["context"]["excluded_turn_ids"])
    _assert_no_new_analysis(a)


def test_preexisting_bad_artifact_cannot_be_blessed_by_readonly_finish(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    assert read_summary(a.fixture)["status"] == "validated_preview_summary"
    table = a.fixture["outputs"] / "doublet_results.tsv"
    table.write_bytes(table.read_bytes() + b"changed before readonly send")
    before = len(a.calls)
    a.actions.append({"action": "finish", "answer": "Synthetic model falsely claims successful valid output"})
    turn = _result_send(a)
    view = a.chat.view_turn(turn)
    assert turn["status"] in {"blocked", "failed"} and not view["usable"]
    assert len(a.calls) == before  # Local integrity failure needs no model call.
    assert view["answer"] is None
    assert view["analysis_outcome"]["state"] == "result_unavailable"
    _assert_no_new_analysis(a)


def test_artifact_changed_during_model_reply_blocks_claimed_success(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    table = a.fixture["outputs"] / "doublet_results.tsv"

    def tamper_and_claim_success(payload):
        table.write_bytes(table.read_bytes() + b"changed inside synthetic model transport")
        return {"action": "finish", "answer": "Synthetic model says output is valid and successful"}

    before = len(a.calls)
    a.actions.extend([{"action": "read_analysis_result", "answer": ""}, tamper_and_claim_success])
    turn = _result_send(a)
    assert len(a.calls) == before + 2 and turn["status"] == "blocked"
    assert turn["agent_steps"][0]["result"]["summary"]["status"] == "validated_preview_summary"
    view = a.chat.view_turn(turn)
    assert not view["usable"] and view["answer"] is None
    assert view["analysis_outcome"]["state"] == "result_unavailable"
    _assert_no_new_analysis(a)


def test_legacy_step_without_attempt_never_loses_binding_after_retry(result_app, monkeypatch):
    a = result_app
    _forbid_execution(monkeypatch)
    assert read_summary(a.fixture)["status"] == "validated_preview_summary"
    conversation = a.chat.create_conversation("Synthetic legacy result history")
    request = deepcopy(a.ledger.get_record("chat_request", a.original["id"]))
    context = deepcopy(a.ledger.get_record("chat_context", a.original["id"]))
    result = deepcopy(a.ledger.get_record("chat_result", a.original["id"]))
    request_id = "legacy-result-fixture"
    turn_id = "chat-turn-" + content_hash([a.ledger.workspace.namespace, conversation["id"], request_id])
    request.update(id=turn_id, conversation_id=conversation["id"], request_id=request_id, sequence=1)
    signature_keys = ("conversation_id", "prompt", "profile_id", "use_knowledge", "purpose", "budget", "analysis_options")
    request["request_hash"] = content_hash({k: request[k] for k in signature_keys if k in request})
    # Model the historical serialization, before result bindings and step
    # attempts existed. These are new synthetic records, not edited old runs.
    context.pop("result_bindings", None)
    result.pop("result_bindings", None)
    result.pop("referenced_analysis_task_ids", None)
    for step in result["agent_steps"]:
        step["result"].pop("attempt", None)
        step["result"].pop("summary", None)
    a.ledger.put_record("chat_request", turn_id, request)
    a.ledger.put_record("chat_context", turn_id, context)
    a.ledger.put_record("chat_result", turn_id, result)
    assert a.chat.view_turn(turn_id)["usable"]
    assert a.chat.list_result_tasks(conversation["id"])

    # Fault injection makes the current task retryable; the actual queue then
    # creates attempt2 under its normal retry/claim rules, without executing it.
    with a.ledger.transaction() as tx:
        tx.execute("UPDATE workbench_tasks SET status='failed' WHERE task_id=?", (a.fixture["task_id"],))
    a.service.queue.retry(a.fixture["task_id"], confirm_no_duplicate=True)
    retry = a.service.queue.claim("synthetic-no-execution-retry", expected_task_id=a.fixture["task_id"])
    assert retry["attempt"] == 2 and retry["status"] == "running"
    view = a.chat.view_turn(turn_id)
    assert not view["usable"] and view["current_status"] == "result_invalidated"
    assert view["answer"] is None
    # A UI may retain an unavailable historical choice for explanation. It may
    # never silently rebind that old run to the task's newly claimed attempt.
    assert all(choice["attempt"] == 1 and choice["run_id"] == a.fixture["run_id"]
               for choice in a.chat.list_result_tasks(conversation["id"]))
    assert read_summary(a.fixture)["status"] == "unavailable"
    a.actions.append("Fresh reply that must not inherit the old numerical prose.")
    fresh = _result_send(a, conversation_id=conversation["id"], result_ref=None,
                         request_id="ordinary-after-legacy-retry")
    assert fresh["status"] == "succeeded"
    assert turn_id in fresh["context"]["excluded_turn_ids"]
    assert ORIGINAL_NUMERIC_PROSE not in canonical_json(a.calls[-1]["messages"])
    assert len(a.ledger.list_records("task_submission")) == 1
    assert len(a.ledger.list_records("analysis_result")) == 1
