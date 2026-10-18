"""Bounded final-format regeneration through the real local gateway and owner.

Only the provider transport and explicit fault boundaries are scripted. Real
ModelService requests, raw outputs, receipts, ChatService persistence and saved
replay remain authoritative. Synthetic source/answer text is not scientific gold,
provider reliability evidence, an actual native model run or a knowledge score.
"""
from copy import deepcopy
import json

import pytest

from sckg_workbench.chat_runs import ChatRunService
from sckg_workbench.storage import canonical_json, content_hash
from sckg_workbench.workflow_chat import (
    PHASE_CONTRACT_VERSION, REPORT_PRESENCE_VERSION,
    validate_turn, workflow_format,
)
from tests.test_workbench_workflow_chat import (
    BUDGET, app, assert_no_execution_or_promotion, current_request,
    decode_scientific_feedback, evaluate, send,
)
from tests.test_workbench_workflow_report_presence import finish


POLICY = "final_format_once_v1"
RUN_SCHEMA = "development-workflow-chat-format-repair-v1"
RESERVATION_KIND = "workflow_format_repair_reservation"
PRIVATE_BAD_MARKER = "REJECTED_PRIVATE_FINAL_TEXT_"


def options(app, *, repair=True, wire="json_object", version=REPORT_PRESENCE_VERSION):
    value = {**app.workflow_options, "answer_contract_version": version}
    if wire == "json_object":
        value["wire_mode"] = "json_object_canonical_v1"
    if repair:
        value["repair_policy"] = POLICY
    return value


def bad_finish(app, payload):
    value = finish(app, payload)
    value["answer"]["d"] = PRIVATE_BAD_MARKER + "长" * (206 - len(PRIVATE_BAD_MARKER))
    assert len(value["answer"]["d"]) == 206
    return value


def script_repair(app, *, repair=finish):
    app.state["actions"] = [lambda a, p: evaluate(a, None), bad_finish, repair]


def provider_effect(app, monkeypatch, effect):
    """Change an actual local provider response before gateway validation."""
    original = app.models.transport

    def transport(url, headers, payload, timeout):
        response = original(url, headers, payload, timeout)
        effect(len(app.calls) - 1, response, payload)
        return response

    monkeypatch.setattr(app.models, "transport", transport)


def tool_feedback(payload):
    for message in reversed(payload["messages"]):
        text = message.get("content", "")
        for encoded in (text, text.partition("\n")[2]):
            try:
                value = json.loads(encoded)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and "candidate_sources" in value:
                return value
    raise AssertionError("Actual full tool feedback absent from outbound payload")


def actual_receipts(app, turn, statuses):
    assert len(app.calls) == len(turn["receipts"]) == len(statuses)
    assert len(app.ledger.list_records("model_call")) == len(statuses)
    assert len(app.ledger.list_records("model_request")) == len(statuses)
    call_ids = [receipt["call_id"] for receipt in turn["receipts"]]
    assert len(call_ids) == len(set(call_ids))
    for receipt, payload, status in zip(turn["receipts"], app.calls, statuses, strict=True):
        assert receipt == app.ledger.get_record("model_call", receipt["call_id"])
        assert receipt["status"] == status
        request = app.ledger.get_record("model_request", receipt["call_id"])
        assert request["id"] == receipt["call_id"] and request["payload"] == payload
        assert request["request_hash"] == content_hash(payload)
        raw = app.ledger.get_record("model_output", receipt["call_id"])
        if raw is not None:
            assert raw["id"] == receipt["call_id"]
            assert raw["text_hash"] == content_hash(raw["text"])
            assert receipt["raw_output_record_hash"] == content_hash(raw)
        if status == "invalid_response":
            assert "structured_output_hash" not in receipt
    assert_no_execution_or_promotion(app)
    return call_ids


def deny_calls_and_writes(app, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Saved repair replay attempted a model call or ledger write")

    monkeypatch.setattr(app.models, "invoke", denied)
    for name in ("put_record", "set_state", "append_event"):
        monkeypatch.setattr(app.ledger, name, denied)


def overwrite_owned_test_record(app, kind, record_id, value):
    """Adversarial edit only in this test's tmp_path ledger, never production."""
    with app.ledger.transaction() as connection:
        result = connection.execute(
            "UPDATE records SET payload=?,digest=? WHERE kind=? AND record_id=?",
            (canonical_json(value), content_hash(value), kind, record_id),
        )
        assert result.rowcount == 1


@pytest.mark.parametrize("wire", ["json_object", "json_schema"])
def test_one_actual_invalid_finish_and_one_repair_use_three_receipts_and_saved_replay(app, monkeypatch, wire):
    script_repair(app)
    turn = send(app, "合成报告：counts 状态未知；只讨论方案，不执行。", workflow_options=options(app, wire=wire))
    assert turn["status"] == "succeeded" and app.chat.view_turn(turn)["usable"] is True
    call_ids = actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    run = turn["workflow_run"]
    assert run["schema_version"] == RUN_SCHEMA and run["repair_policy"] == POLICY
    assert len(run["calls"]) == 2 and len(turn["agent_steps"]) == 1
    assert [call["call_id"] for call in run["calls"]] == [call_ids[0], call_ids[2]]
    assert [call["attempt_index"] for call in run["calls"]] == [0, 2]
    attempts = run["attempts"]
    assert [attempt["attempt_index"] for attempt in attempts] == [0, 1, 2]
    assert [attempt["call_id"] for attempt in attempts] == call_ids
    assert [attempt["outcome"] for attempt in attempts] == ["accepted_action", "known_format_rejected", "accepted_action"]
    assert "wire" not in attempts[1]
    assert attempts[2]["final_only"] is True and attempts[2]["repair_of_call_id"] == call_ids[1]
    reservation = app.ledger.get_record(RESERVATION_KIND, turn["id"])
    assert reservation is not None and run["repair_reservation"] == reservation
    assert len(app.ledger.list_records(RESERVATION_KIND)) == 1
    rejected = app.ledger.get_record("model_output", call_ids[1])
    assert json.loads(rejected["text"])["answer"]["d"] == app.state["outputs"][1]["answer"]["d"]
    assert PRIVATE_BAD_MARKER not in canonical_json(app.calls[2])
    assert rejected["text"] not in canonical_json(app.calls[2])
    assert tool_feedback(app.calls[1]) == tool_feedback(app.calls[2])
    assert decode_scientific_feedback(tool_feedback(app.calls[2]))["candidate_sources"]
    final_format = workflow_format(final_only=True, answer_contract_version=REPORT_PRESENCE_VERSION)
    final_request = app.ledger.get_record("model_request", call_ids[2])
    if wire == "json_object":
        assert final_request["local_validation_format"] == final_format
    else:
        assert final_request["payload"]["response_format"] == final_format
    budget = turn["agent_budget"]
    assert budget["model_calls"] == budget["max_model_calls"] == 3
    assert budget["charged_or_reserved_tokens"] == 390
    assert budget["cost_known"] is True and budget["cost_usd"] == pytest.approx(.00048)
    full_proxies = [len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()) + 256
        for payload in app.calls]
    assert [attempt["full_input_proxy"] for attempt in attempts] == full_proxies
    assert budget["input_proxy_plus_output_reservations"] == sum(
        proxy + receipt["budget"]["max_output_tokens"]
        for proxy, receipt in zip(full_proxies, turn["receipts"], strict=True)
    )
    before = app.ledger.events()
    deny_calls_and_writes(app, monkeypatch)
    validate_turn(app.ledger, app.models, app.ledger.get_record("chat_request", turn["id"]), turn)
    assert app.chat.view_turn(turn)["usable"] is True
    assert send(app, turn["prompt"], workflow_options=options(app, wire=wire)) == turn
    assert app.ledger.events() == before and len(app.calls) == 3


def test_no_policy_keeps_original_failed_v4_and_its_trace_shape(app):
    script_repair(app)
    turn = send(app, workflow_options=options(app, repair=False))
    assert turn["status"] == "failed" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded", "invalid_response"])
    assert turn["workflow_run"]["schema_version"] == "development-workflow-chat-run-v1"
    assert "attempts" not in turn["workflow_run"] and "repair_policy" not in turn["workflow_run"]
    assert app.ledger.list_records(RESERVATION_KIND) == [] and len(app.state["actions"]) == 1


@pytest.mark.parametrize("change", ["v3", "unknown_policy"])
def test_policy_cannot_be_applied_to_v3_or_unknown_policy_before_dispatch(app, change):
    selected = options(app)
    if change == "v3":
        selected["answer_contract_version"] = PHASE_CONTRACT_VERSION
    else:
        selected["repair_policy"] = "unbounded_retry_not_allowed"
    with pytest.raises(ValueError):
        send(app, workflow_options=selected)
    assert app.calls == [] and app.ledger.list_records("model_call") == []


def test_invalid_initial_response_cannot_reserve_or_repair(app):
    app.state["actions"] = [{"action": "finish", "route_ids": [], "reports": [],
        "answer": {"d": "长" * 206, "s": [], "p": [], "m": []}}, finish]
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["invalid_response"])
    assert turn["agent_steps"] == [] and app.ledger.list_records(RESERVATION_KIND) == []


@pytest.mark.parametrize("shape", ["evaluate", "parse", "duplicate_key", "nonempty_routes", "nonempty_reports", "missing_action"])
def test_known_invalid_output_without_strict_final_intent_is_not_repaired(app, shape):
    def wrong(a, p):
        value = bad_finish(a, p)
        if shape == "evaluate":
            value["action"] = "evaluate_workflow_inputs"
            value["route_ids"] = ["counts_route"]
        elif shape == "parse":
            return '{"action":"finish","answer":'
        elif shape == "duplicate_key":
            encoded = json.dumps(value, ensure_ascii=False)
            return encoded.replace('"action": "finish"', '"action":"finish","action":"finish"', 1)
        elif shape == "nonempty_routes":
            value["route_ids"] = ["counts_route"]
        elif shape == "nonempty_reports":
            value["reports"] = evaluate(a, None)["reports"]
        else:
            value.pop("action")
        return value
    app.state["actions"] = [lambda a, p: evaluate(a, None), wrong, finish]
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded", "invalid_response"])
    assert app.ledger.list_records(RESERVATION_KIND) == [] and len(app.state["actions"]) == 1


@pytest.mark.parametrize("usage", [None, {"prompt_tokens": None, "completion_tokens": 30},
    {"prompt_tokens": 100, "completion_tokens": True}, {"prompt_tokens": 100, "completion_tokens": -1}])
def test_unknown_or_malformed_usage_never_enters_repair(app, monkeypatch, usage):
    script_repair(app)
    def effect(index, response, payload):
        if index == 1:
            if usage is None:
                response.pop("usage")
            else:
                response["usage"] = deepcopy(usage)
    provider_effect(app, monkeypatch, effect)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded"
    actual_receipts(app, turn, ["succeeded", "invalid_response"])
    assert turn["receipts"][1]["usage_known"] is False
    assert app.ledger.list_records(RESERVATION_KIND) == []


@pytest.mark.parametrize("bad_outcome", ["length", "over_budget", "timeout"])
def test_partial_over_budget_or_unknown_remote_outcome_cannot_repair(app, monkeypatch, bad_outcome):
    script_repair(app)
    if bad_outcome == "timeout":
        app.state["actions"][1] = TimeoutError("Synthetic fixture only; no network request")
    else:
        def effect(index, response, payload):
            if index == 1:
                if bad_outcome == "length":
                    response["choices"][0]["finish_reason"] = "length"
                else:
                    response["usage"]["completion_tokens"] = BUDGET["max_output_tokens"] + 1
        provider_effect(app, monkeypatch, effect)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and len(app.calls) == 2 and len(turn["receipts"]) == 2
    expected = "failed" if bad_outcome == "timeout" else "invalid_response"
    actual_receipts(app, turn, ["succeeded", expected])
    assert app.ledger.list_records(RESERVATION_KIND) == []
    if bad_outcome == "timeout":
        assert turn["receipts"][1]["outcome"] == "result_unknown"
    elif bad_outcome == "over_budget":
        assert turn["receipts"][1]["budget_exceeded"] is True


def test_third_attempt_failure_cannot_get_a_fourth_call(app):
    app.state["actions"] = [lambda a, p: evaluate(a, None), lambda a, p: evaluate(a, None), bad_finish, finish]
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded", "succeeded", "invalid_response"])
    assert len(turn["agent_steps"]) == 2 and app.ledger.list_records(RESERVATION_KIND) == []
    assert len(app.state["actions"]) == 1


def test_bad_repair_is_terminal_after_three_calls_and_retains_both_bad_outputs(app):
    script_repair(app, repair=bad_finish)
    app.state["actions"].append(finish)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    call_ids = actual_receipts(app, turn, ["succeeded", "invalid_response", "invalid_response"])
    assert len(app.ledger.list_records(RESERVATION_KIND)) == 1 and len(turn["agent_steps"]) == 1
    assert all(PRIVATE_BAD_MARKER in app.ledger.get_record("model_output", call_id)["text"] for call_id in call_ids[1:])
    assert len(app.state["actions"]) == 1


@pytest.mark.parametrize("changed_index", [1, 2])
def test_failed_or_repaired_returned_model_drift_cannot_become_usable(app, monkeypatch, changed_index):
    script_repair(app)
    def effect(index, response, payload):
        if index == changed_index:
            response["model"] = "synthetic-other-model-version"
    provider_effect(app, monkeypatch, effect)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and app.chat.view_turn(turn)["usable"] is False
    assert len(app.calls) == changed_index + 1 and len(turn["receipts"]) == len(app.calls)
    assert turn["receipts"][-1]["returned_model"] == "synthetic-other-model-version"


@pytest.mark.parametrize("boundary", ["source_change", "cancel", "trace_write", "existing_reservation"])
def test_repair_reservation_respects_sources_owner_trace_and_existing_slot(app, monkeypatch, boundary):
    script_repair(app)
    original_put = app.ledger.put_record
    if boundary == "trace_write":
        def put(kind, record_id, payload, *, conn=None):
            if kind == RESERVATION_KIND:
                raise OSError("Synthetic repair trace failure")
            return original_put(kind, record_id, payload, conn=conn)
        monkeypatch.setattr(app.ledger, "put_record", put)
    def effect(index, response, payload):
        if index != 1:
            return
        request = current_request(app)
        if boundary == "source_change":
            app.chat.knowledge.suspend("candidate", app.candidate["id"], actor="synthetic-test", reason="Controlled source change")
        elif boundary == "cancel":
            ChatRunService(app.ledger).request_cancel(request["conversation_id"], request["id"])
        elif boundary == "existing_reservation":
            original_put(RESERVATION_KIND, request["id"], {"synthetic_fixture": "already held; cannot spend again"})
    provider_effect(app, monkeypatch, effect)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and len(app.calls) == 2 and len(turn["receipts"]) == 2
    actual_receipts(app, turn, ["succeeded", "invalid_response"])
    assert len(app.ledger.list_records(RESERVATION_KIND)) == (1 if boundary == "existing_reservation" else 0)


def test_insufficient_original_monetary_remainder_stops_before_third_transport(app):
    script_repair(app)
    budget = deepcopy(BUDGET)
    per_dispatch_ceiling = (budget["max_input_tokens"] + 2 * budget["max_output_tokens"]) / 1_000_000
    budget["max_cost_usd"] = per_dispatch_ceiling + .00024
    turn = send(app, workflow_options=options(app), budget=budget)
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded", "invalid_response"])


def test_token_bounded_unknown_price_remains_unknown_during_repair(app):
    app.profile = app.models.create_profile("unknown-price repair fixture", "chat", app.connection["id"], "fixture-model")
    budget = deepcopy(BUDGET)
    budget.pop("max_cost_usd")
    budget["allow_unknown_cost"] = True
    script_repair(app)
    turn = send(app, workflow_options=options(app), budget=budget)
    assert turn["status"] == "succeeded"
    actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    assert turn["agent_budget"]["cost_known"] is False and turn["agent_budget"]["cost_usd"] is None
    assert turn["agent_budget"]["charged_or_reserved_tokens"] == 390


def test_schema_valid_repair_with_missing_v4_coverage_is_not_repaired_again(app):
    def invalid_semantics(a, p):
        value = finish(a, p)
        value["answer"]["m"] = []
        return value
    script_repair(app, repair=invalid_semantics)
    app.state["actions"].append(finish)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    assert len(app.state["actions"]) == 1 and app.chat.view_turn(turn)["usable"] is False


@pytest.mark.parametrize("damage", ["drop_failed", "reorder", "duplicate_call", "index_gap", "repair_of", "failed_status", "raw_hash", "remove_policy"])
def test_rehashed_attempt_tampering_cannot_hide_or_rescue_failed_dispatch(app, monkeypatch, damage):
    script_repair(app)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] == "succeeded"
    actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    run = result["workflow_run"]
    if damage == "drop_failed":
        run["attempts"].pop(1)
        result["receipts"].pop(1)
        result["agent_budget"]["model_calls"] = 2
    elif damage == "reorder":
        run["attempts"][1], run["attempts"][2] = run["attempts"][2], run["attempts"][1]
        for index, attempt in enumerate(run["attempts"]):
            attempt["attempt_index"] = index
    elif damage == "duplicate_call":
        run["attempts"][2]["call_id"] = run["attempts"][1]["call_id"]
    elif damage == "index_gap":
        run["attempts"][2]["attempt_index"] = 3
    elif damage == "repair_of":
        run["attempts"][2]["repair_of_call_id"] = run["attempts"][0]["call_id"]
    elif damage == "failed_status":
        run["attempts"][1]["receipt"]["status"] = "succeeded"
    elif damage == "raw_hash":
        run["attempts"][1]["receipt"]["raw_output_record_hash"] = "f" * 64
    else:
        run.pop("repair_policy")
    run["binding_hash"] = content_hash({k: v for k, v in run.items() if k != "binding_hash"})
    overwrite_owned_test_record(app, "chat_result", turn["id"], result)
    deny_calls_and_writes(app, monkeypatch)
    view = app.chat.view_turn(turn["id"])
    assert view["usable"] is False and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and view["workflow_review"] is None and len(app.calls) == 3


def test_rehashed_valid_raw_cannot_masquerade_as_a_known_format_rejection(app, monkeypatch):
    script_repair(app)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] == "succeeded"
    call_ids = actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    # Replace only owned temporary records, making all local digest projections
    # agree. The binder must still recompute the supposed format failure.
    failed_id = call_ids[1]
    changed_raw = deepcopy(app.ledger.get_record("model_output", failed_id))
    changed_raw["text"] = json.dumps(app.state["outputs"][2], ensure_ascii=False)
    changed_raw["text_hash"] = content_hash(changed_raw["text"])
    changed_receipt = deepcopy(app.ledger.get_record("model_call", failed_id))
    changed_receipt["raw_output_record_hash"] = content_hash(changed_raw)
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    result["receipts"][1] = deepcopy(changed_receipt)
    run = result["workflow_run"]
    run["attempts"][1]["receipt"] = deepcopy(changed_receipt)
    if "raw_output_record_hash" in run["attempts"][1]:
        run["attempts"][1]["raw_output_record_hash"] = content_hash(changed_raw)
    run["binding_hash"] = content_hash({k: v for k, v in run.items() if k != "binding_hash"})
    overwrite_owned_test_record(app, "model_output", failed_id, changed_raw)
    overwrite_owned_test_record(app, "model_call", failed_id, changed_receipt)
    overwrite_owned_test_record(app, "chat_result", turn["id"], result)
    deny_calls_and_writes(app, monkeypatch)
    view = app.chat.view_turn(turn["id"])
    assert view["usable"] is False and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and len(app.calls) == 3


def test_cancel_committed_with_reservation_prevents_its_dispatch_and_reuse(app, monkeypatch):
    script_repair(app)
    original_put = app.ledger.put_record

    def put(kind, record_id, payload, *, conn=None):
        result = original_put(kind, record_id, payload, conn=conn)
        if kind == RESERVATION_KIND:
            assert conn is not None and conn.in_transaction
            # Controlled cancellation at this exact boundary in the owned test
            # transaction. No child task exists in a readonly workflow turn.
            key = "chat_run:" + record_id
            control = app.ledger.get_state(key, conn=conn)
            assert control["status"] == "running" and not control["cancel_requested"]
            control.update(status="cancel_requested", cancel_requested=True)
            app.ledger.set_state(key, control, conn=conn)
        return result

    monkeypatch.setattr(app.ledger, "put_record", put)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded", "invalid_response"])
    assert len(app.ledger.list_records(RESERVATION_KIND)) == 1
    assert send(app, turn["prompt"], workflow_options=options(app)) == turn
    assert len(app.calls) == 2 and len(app.state["actions"]) == 1


def test_successful_evaluate_with_unknown_usage_stops_before_any_next_provider_call(app, monkeypatch):
    script_repair(app)
    def effect(index, response, payload):
        if index == 0:
            response["usage"].pop("completion_tokens")
    provider_effect(app, monkeypatch, effect)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded"])
    assert turn["receipts"][0]["usage_known"] is False
    assert turn["agent_budget"]["charged_or_reserved_tokens"] == BUDGET["max_input_tokens"] + BUDGET["max_output_tokens"]
    assert turn["agent_budget"]["cost_known"] is False and turn["agent_budget"]["cost_usd"] is None
    assert len(app.state["actions"]) == 2 and app.ledger.list_records(RESERVATION_KIND) == []


@pytest.mark.parametrize("wire", ["json_object", "json_schema"])
def test_rehashed_failed_input_estimate_must_still_bind_the_actual_gateway_payload(app, monkeypatch, wire):
    script_repair(app)
    turn = send(app, workflow_options=options(app, wire=wire))
    assert turn["status"] == "succeeded"
    call_ids = actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    failed_id = call_ids[1]
    changed_receipt = deepcopy(app.ledger.get_record("model_call", failed_id))
    changed_receipt["estimated_input_tokens"] += 1
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    result["receipts"][1] = deepcopy(changed_receipt)
    run = result["workflow_run"]
    run["attempts"][1]["receipt"] = deepcopy(changed_receipt)
    run["binding_hash"] = content_hash({k: v for k, v in run.items() if k != "binding_hash"})
    # Every rewritten receipt projection agrees. Only reconstruction of the
    # unchanged real request under its original estimate rule can reject it.
    overwrite_owned_test_record(app, "model_call", failed_id, changed_receipt)
    overwrite_owned_test_record(app, "chat_result", turn["id"], result)
    deny_calls_and_writes(app, monkeypatch)
    view = app.chat.view_turn(turn["id"])
    assert view["usable"] is False and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and len(app.calls) == 3


@pytest.mark.parametrize("wire", ["json_object", "json_schema"])
@pytest.mark.parametrize("accepted_phase", [0, 2], ids=["evaluate", "repair"])
def test_every_policy_accepted_receipt_keeps_raw_binding_despite_rehashed_projections(app, monkeypatch, wire, accepted_phase):
    script_repair(app)
    turn = send(app, workflow_options=options(app, wire=wire))
    assert turn["status"] == "succeeded"
    call_ids = actual_receipts(app, turn, ["succeeded", "invalid_response", "succeeded"])
    changed_id = call_ids[accepted_phase]
    changed_receipt = deepcopy(app.ledger.get_record("model_call", changed_id))
    original_raw = deepcopy(app.ledger.get_record("model_output", changed_id))
    changed_receipt.pop("raw_output_record_hash")
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    result["receipts"][accepted_phase] = deepcopy(changed_receipt)
    if accepted_phase == 2:
        result["receipt"] = deepcopy(changed_receipt)
    run = result["workflow_run"]
    run["attempts"][accepted_phase]["receipt"] = deepcopy(changed_receipt)
    run["attempts"][accepted_phase]["raw_output_record_hash"] = None
    accepted_call = next(call for call in run["calls"] if call["call_id"] == changed_id)
    accepted_call["receipt"] = deepcopy(changed_receipt)
    run["binding_hash"] = content_hash({k: v for k, v in run.items() if k != "binding_hash"})
    decision_id = f"{turn['id']}:{accepted_phase}"
    decision = deepcopy(app.ledger.get_record("chat_agent_decision", decision_id))
    assert decision["receipt"]["call_id"] == changed_id
    decision["receipt"] = deepcopy(changed_receipt)
    overwrite_owned_test_record(app, "model_call", changed_id, changed_receipt)
    overwrite_owned_test_record(app, "chat_agent_decision", decision_id, decision)
    overwrite_owned_test_record(app, "chat_result", turn["id"], result)
    # The actual raw output is retained. The policy must reject compatibility
    # downgrade even though every receipt projection now agrees without a hash.
    assert app.ledger.get_record("model_output", changed_id) == original_raw
    deny_calls_and_writes(app, monkeypatch)
    view = app.chat.view_turn(turn["id"])
    assert view["usable"] is False and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and len(app.calls) == 3


@pytest.mark.parametrize("returned_model", [None, "", "   "], ids=["missing", "empty", "whitespace"])
def test_missing_first_returned_model_identity_stops_before_tool_or_next_call(app, monkeypatch, returned_model):
    script_repair(app)
    def effect(index, response, payload):
        if index == 0:
            response["model"] = returned_model
    provider_effect(app, monkeypatch, effect)
    turn = send(app, workflow_options=options(app))
    assert turn["status"] != "succeeded" and turn["answer"] is None
    actual_receipts(app, turn, ["succeeded"])
    assert turn["receipts"][0]["returned_model"] == returned_model
    assert turn["receipts"][0]["usage_known"] is True
    assert turn["agent_steps"] == [] and app.ledger.list_records(RESERVATION_KIND) == []
    assert app.chat.view_turn(turn)["usable"] is False and len(app.state["actions"]) == 2
