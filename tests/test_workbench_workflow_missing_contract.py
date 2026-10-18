"""Versioned missing-item contracts, using only synthetic local gateway fixtures.

The real ModelService validates scripted responses and records their receipts;
its transport is in memory. These checks establish output shape and provenance,
not scientific extraction quality, model reliability or biological suitability.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError as TypedValidationError
import pytest

from sckg_workbench.evidence_answers import CompactMissingV3
from sckg_workbench.storage import canonical_json, content_hash
from sckg_workbench.workflow_chat import (
    EXPLICIT_MISSING_INSTRUCTIONS,
    EXPLICIT_MISSING_VERSION,
    PROMPT,
    SHARED_TEXT_INSTRUCTIONS,
    WorkflowAction,
    WorkflowChatError,
    prepare_context,
    workflow_format,
)
from tests.test_workbench_workflow_chat import (
    app,
    assert_no_execution_or_promotion,
    current_request,
    finish,
    script_success,
    send,
)


def _schema_action(missing):
    return {"action": "finish", "route_ids": [], "reports": [],
            "answer": {"d": "Synthetic format fixture only.", "s": [], "p": [],
                       "m": [deepcopy(missing)]}}


def _feedback(payload):
    return json.loads(payload["messages"][-1]["content"].partition("\n")[2])


def _two_null_reports(app, payload):
    """Both P aliases have supplied quotations, even though status is unknown."""
    request = current_request(app)
    return {"action": "evaluate_workflow_inputs",
            "route_ids": ["counts_route", "additional_route"],
            "reports": [{"report_pointer": "/reported_inputs/" + name,
                         "reported_value": None, "user_turn_id": request["id"],
                         "quote": request["prompt"]}
                        for name in ("counts", "additional")],
            "answer": None}


def _ledger_snapshot(ledger):
    """Exact stored JSON/receipt bytes and other SQL values, not a score."""
    with ledger.connect() as connection:
        return tuple(line.encode("utf-8") for line in connection.iterdump())


def _deny_writes_and_calls(app, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Read-only replay attempted a write or a model invocation")

    monkeypatch.setattr(app.models, "invoke", denied)
    for name in ("put_record", "set_state", "append_event"):
        monkeypatch.setattr(app.ledger, name, denied)


@pytest.mark.parametrize("initial,final_only", [(False, False), (True, False), (False, True)])
def test_new_schema_does_not_mutate_legacy_default_schema(initial, final_only):
    # Construct the previous default independently of the new schema branch.
    old_schema = WorkflowAction.model_json_schema()
    old_schema["properties"]["action"] = {
        "type": "string",
        "enum": ["finish"] if final_only else (
            ["evaluate_workflow_inputs"] if initial else ["evaluate_workflow_inputs", "finish"]),
    }
    expected = {"type": "json_schema", "json_schema": {
        "name": "development_workflow_action_v1", "strict": True, "schema": old_schema}}
    old_bytes = canonical_json(expected).encode("utf-8")
    assert canonical_json(workflow_format(final_only, initial=initial)).encode("utf-8") == old_bytes

    new = workflow_format(final_only, initial=initial,
                          answer_contract_version=EXPLICIT_MISSING_VERSION)
    assert new["json_schema"]["name"] == "development_workflow_action_missing_v2"
    Draft202012Validator.check_schema(new["json_schema"]["schema"])
    missing = new["json_schema"]["schema"]["$defs"]["CompactMissingV3"]
    assert missing["properties"]["p"]["uniqueItems"] is True
    assert [(branch["properties"]["k"]["const"],
             branch["properties"]["p"]["minItems"],
             branch["properties"]["p"]["maxItems"])
            for branch in missing["anyOf"]] == [
        ("not_supplied", 0, 0), ("independent_verification_missing", 1, 8),
        ("source_evidence_missing", 0, 8)]
    assert canonical_json(workflow_format(final_only, initial=initial)).encode("utf-8") == old_bytes
    assert canonical_json(workflow_format(final_only, initial=initial,
        answer_contract_version=None)).encode("utf-8") == old_bytes
    assert WorkflowAction.model_json_schema()["$defs"]["CompactMissingV3"] == \
        old_schema["$defs"]["CompactMissingV3"]


@pytest.mark.parametrize("kind,premises", [
    ("not_supplied", []),
    ("independent_verification_missing", ["P1"]),
    ("independent_verification_missing", [f"P{i}" for i in range(1, 9)]),
    ("source_evidence_missing", []),
    ("source_evidence_missing", ["P1", "P2"]),
    ("source_evidence_missing", [f"P{i}" for i in range(1, 9)]),
])
def test_missing_kinds_agree_between_typed_contract_and_new_json_schema(kind, premises):
    missing = {"k": kind, "p": premises, "t": "Synthetic shape example only."}
    assert CompactMissingV3.model_validate(missing).model_dump(mode="json") == missing
    schema = workflow_format(answer_contract_version=EXPLICIT_MISSING_VERSION)["json_schema"]["schema"]
    Draft202012Validator(schema).validate(_schema_action(missing))


@pytest.mark.parametrize("kind,premises", [
    ("not_supplied", ["P1"]),
    ("not_supplied", ["P1", "P2"]),
    ("independent_verification_missing", []),
    ("independent_verification_missing", ["P1", "P1"]),
    ("source_evidence_missing", ["P1", "P1"]),
    ("independent_verification_missing", [f"P{i}" for i in range(1, 9)] + ["P1"]),
    ("source_evidence_missing", [f"P{i}" for i in range(1, 9)] + ["P1"]),
    ("source_evidence_missing", ["P9"]),
    ("unknown_kind", []),
])
def test_invalid_missing_cross_fields_are_rejected_by_both_validators(kind, premises):
    missing = {"k": kind, "p": premises, "t": "Synthetic invalid shape."}
    with pytest.raises(TypedValidationError):
        CompactMissingV3.model_validate(missing)
    schema = workflow_format(answer_contract_version=EXPLICIT_MISSING_VERSION)["json_schema"]["schema"]
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate(_schema_action(missing))


def test_null_user_reports_are_supplied_premises_and_rules_are_explicit(app):
    app.state["actions"] = [_two_null_reports, finish]
    turn = send(app, "counts 与 additional 的真实观测状态均未确认；这里只测试结构。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    prepared = app.ledger.get_record("chat_context", turn["id"])
    assert prepared["workflow_material"]["answer_contract_version"] == EXPLICIT_MISSING_VERSION
    assert prepared["messages"][0]["content"] == \
        PROMPT + SHARED_TEXT_INSTRUCTIONS + EXPLICIT_MISSING_INSTRUCTIONS
    assert prepared["context"]["workflow_capacity_admission"]["route_subsets_checked"] == 3
    assert prepared["context"]["workflow_capacity_admission"]["actual_request_gateway_check_required"] is True
    assert all(call["response_format"]["json_schema"]["name"] ==
               "development_workflow_action_missing_v2" for call in app.calls)
    assert json.loads(app.calls[-1]["messages"][1]["content"])["answer_contract_version"] == \
        EXPLICIT_MISSING_VERSION
    contract = _feedback(app.calls[-1])["answer_contract"]
    assert contract["answer_contract_version"] == EXPLICIT_MISSING_VERSION
    assert [p["p"] for p in contract["premises"]] == ["P1", "P2"]
    assert all(p["r"] == "unknown" and p["a"] == "needs_evidence" for p in contract["premises"])
    rules = contract["missing_rules"]
    assert {kind: (rules[kind]["p_min_items"], rules[kind]["p_max_items"])
            for kind in ("not_supplied", "independent_verification_missing", "source_evidence_missing")} == {
        "not_supplied": (0, 0), "independent_verification_missing": (1, 8),
        "source_evidence_missing": (0, 8)}
    assert rules["null_reports_are_supplied_premises"] is True
    assert rules["followups_limited_to_current_question_and_selected_routes"] is True
    assert rules["examples_are_format_only"] is True
    assert [(item["k"], item["p"]) for item in contract["missing_examples"]] == [
        ("not_supplied", []), ("source_evidence_missing", []),
        ("independent_verification_missing", ["P1"])]
    assert [item["reported_value"] for item in turn["workflow_interpretations"]] == [None, None]
    assert [item["premise_id"] for item in turn["workflow_interpretations"]] == ["P1", "P2"]
    assert turn["agent_budget"]["max_model_calls"] == 3
    assert turn["agent_budget"]["max_tool_steps"] == 2
    assert app.chat.view_turn(turn)["usable"]
    assert_no_execution_or_promotion(app)


def test_no_user_reports_produce_no_fabricated_premise_example_or_unselected_requirement(app):
    app.state["actions"] = [lambda a, p: {
        "action": "evaluate_workflow_inputs", "route_ids": ["counts_route"],
        "reports": [], "answer": None}, finish]
    turn = send(app, "只讨论 counts 这条路线的输入；本 fixture 尚未报告状态。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    contract = _feedback(app.calls[-1])["answer_contract"]
    assert contract["premises"] == []
    assert contract["unknown_requirements"] == ["/reported_inputs/counts"]
    assert [item["route_id"] for item in contract["step_routes"]] == ["counts_route"]
    assert [(item["k"], item["p"]) for item in contract["missing_examples"]] == [
        ("not_supplied", []), ("source_evidence_missing", [])]
    assert contract["missing_rules"]["followups_limited_to_current_question_and_selected_routes"] is True
    assert all(item["p"] == [] for item in contract["missing_examples"])
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("bad_premises", [["P1"], ["P2"], ["P1", "P2"]])
def test_real_gateway_rejects_not_supplied_null_premises_without_retry(app, monkeypatch, bad_premises):
    def invalid_finish(a, payload):
        action = finish(a, payload)
        missing = next(item for item in action["answer"]["m"] if item["k"] == "not_supplied")
        missing["p"] = bad_premises
        return action

    never_requested = {"unexpected_third_response": True}
    app.state["actions"] = [_two_null_reports, invalid_finish, never_requested]
    prompt = "counts 与 additional 状态均未知；两项是已有用户原话，非独立观测。"
    turn = send(app, prompt)
    assert turn["status"] == "failed" and turn.get("answer") is None
    assert len(app.calls) == 2 and app.state["actions"] == [never_requested]
    assert len(turn["receipts"]) == 2 and len(turn["agent_steps"]) == 1
    first, rejected = turn["receipts"]
    assert first["status"] == "succeeded"
    assert rejected["status"] == "invalid_response"
    assert rejected == app.ledger.get_record("model_call", rejected["call_id"])
    assert rejected["usage_known"] is True
    assert app.ledger.get_record("model_request", rejected["call_id"])["payload"] == app.calls[-1]
    raw = app.ledger.get_record("model_output", rejected["call_id"])
    assert raw["text"] == json.dumps(app.state["outputs"][-1], ensure_ascii=False)
    assert raw["finish_reason"] == "stop"
    assert rejected["raw_output_record_hash"] == content_hash(raw)
    assert turn["error"]["type"] == "ModelCallError"
    assert [r["reported_value"] for r in turn["agent_steps"][0]["result"]["workflow_interpretations"]] == [None, None]
    snapshot = _ledger_snapshot(app.ledger)
    _deny_writes_and_calls(app, monkeypatch)
    assert send(app, prompt) == turn
    assert not app.chat.view_turn(turn)["usable"]
    assert len(app.calls) == 2 and _ledger_snapshot(app.ledger) == snapshot
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("encoding", ["literal_v1", "shared_text_v2"])
def test_legacy_no_marker_replays_exact_payloads_and_receipts_readonly(app, monkeypatch, encoding):
    script_success(app)
    with monkeypatch.context() as legacy:
        legacy.setattr(app.chat, "_prepare_context", lambda request: prepare_context(
            app.ledger, request, feedback_encoding=encoding, answer_contract_version=None))
        turn = send(app, "旧版本原始报告：counts 已有；仅验证兼容回放。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    saved = app.ledger.get_record("chat_context", turn["id"])
    assert "answer_contract_version" not in saved["workflow_material"]
    assert saved["messages"][0]["content"] == \
        PROMPT + (SHARED_TEXT_INSTRUCTIONS if encoding == "shared_text_v2" else "")
    assert "answer_contract_version" not in json.loads(app.calls[-1]["messages"][1]["content"])
    contract = _feedback(app.calls[-1])["answer_contract"]
    assert "answer_contract_version" not in contract
    assert "missing_rules" not in contract and "missing_examples" not in contract
    assert "missing_rules" not in turn["agent_steps"][0]["result"]["answer_contract"]
    for index, (receipt, payload) in enumerate(zip(turn["receipts"], app.calls)):
        assert payload["response_format"] == workflow_format(initial=index == 0)
        assert receipt == app.ledger.get_record("model_call", receipt["call_id"])
        assert app.ledger.get_record("model_request", receipt["call_id"])["payload"] == payload
    payload_bytes = [canonical_json(payload).encode("utf-8") for payload in app.calls]
    receipts = deepcopy(turn["receipts"])
    request = app.ledger.get_record("chat_request", turn["id"])
    assert prepare_context(app.ledger, request)["workflow_material"]["answer_contract_version"] == \
        EXPLICIT_MISSING_VERSION
    assert prepare_context(app.ledger, request) != saved
    snapshot = _ledger_snapshot(app.ledger)
    _deny_writes_and_calls(app, monkeypatch)
    view = app.chat.view_turn(turn)
    assert view["usable"] and view["workflow_answer"] == turn["workflow_answer"]
    assert view["receipts"] == receipts
    assert [canonical_json(payload).encode("utf-8") for payload in app.calls] == payload_bytes
    assert _ledger_snapshot(app.ledger) == snapshot and len(app.calls) == 2
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("damage", ["unknown_marker", "downgrade_to_legacy"])
def test_rehashed_answer_contract_marker_tampering_hides_saved_answer(app, monkeypatch, damage):
    script_success(app)
    turn = send(app)
    assert turn["status"] == "succeeded" and app.chat.view_turn(turn)["usable"]
    actual_calls = deepcopy(app.ledger.list_records("model_call"))
    actual_requests = deepcopy(app.ledger.list_records("model_request"))
    request = app.ledger.get_record("chat_request", turn["id"])
    if damage == "downgrade_to_legacy":
        # Even a fully reconstructed legacy context cannot rewrite the actual
        # new-version request/schema accepted by the immutable gateway receipt.
        prepared = prepare_context(app.ledger, request, answer_contract_version=None)
    else:
        prepared = deepcopy(app.ledger.get_record("chat_context", turn["id"]))
        prepared["workflow_material"]["answer_contract_version"] = "invented_missing_version"
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    run = result["workflow_run"]
    run["prepared_hash"] = content_hash(prepared)
    run["binding_hash"] = content_hash({key: value for key, value in run.items() if key != "binding_hash"})
    # Adversarial edits are confined to this owned temporary test ledger.
    with app.ledger.transaction() as connection:
        for kind, value in (("chat_context", prepared), ("chat_result", result)):
            changed = connection.execute(
                "UPDATE records SET payload=?,digest=? WHERE kind=? AND record_id=?",
                (canonical_json(value), content_hash(value), kind, turn["id"]))
            assert changed.rowcount == 1
    snapshot = _ledger_snapshot(app.ledger)
    _deny_writes_and_calls(app, monkeypatch)
    view = app.chat.view_turn(turn)
    assert not view["usable"] and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and view["workflow_review"] is None
    assert view["workflow_answer"] is None and view["workflow_interpretations"] == []
    assert app.ledger.list_records("model_call") == actual_calls
    assert app.ledger.list_records("model_request") == actual_requests
    assert _ledger_snapshot(app.ledger) == snapshot and len(app.calls) == 2
    assert_no_execution_or_promotion(app)


def test_unknown_answer_version_is_rejected_without_modifying_global_contract():
    before = canonical_json(workflow_format())
    with pytest.raises(WorkflowChatError, match="Unknown workflow answer contract version"):
        workflow_format(answer_contract_version="invented_missing_version")
    assert canonical_json(workflow_format()) == before
