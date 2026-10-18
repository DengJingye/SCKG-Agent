"""Actual chat/gateway provenance with scripted development-only interpretations.

All scientific text and model choices are synthetic fixture inputs. These tests
exercise source identity, state, receipts and interaction; they do not establish
that exact quotations mechanically prove negation, scope or biological meaning.
No network transport, scientific fit, human review or release is used here.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from sckg_workbench.chat import ChatError, ChatService
from sckg_workbench.model_service import ModelService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, canonical_json, content_hash
from sckg_workbench.workflow_inputs import WorkflowInputCatalog


PASSPHRASE = "synthetic-workflow-chat-passphrase"
BUDGET = {"max_input_tokens": 64000, "max_output_tokens": 512,
          "timeout_seconds": 5, "max_cost_usd": 1}


@pytest.fixture
def app(tmp_path):
    ledger = Ledger(Workspace(tmp_path / "isolated-workflow-chat"))
    state = {"actions": [], "calls": [], "outputs": [], "last_evaluate": None}
    app = SimpleNamespace(ledger=ledger, state=state, calls=state["calls"])

    def transport(url, headers, payload, timeout):
        state["calls"].append(deepcopy(payload))
        assert state["actions"], "Unexpected additional model request"
        action = state["actions"].pop(0)
        if isinstance(action, Exception):
            raise action
        output = action(app, payload) if callable(action) else deepcopy(action)
        state["outputs"].append(deepcopy(output))
        if isinstance(output, dict) and output.get("action") == "evaluate_workflow_inputs":
            state["last_evaluate"] = deepcopy(output)
        return {"model": "synthetic-workflow-returned", "id": "synthetic-response",
                "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                "choices": [{"finish_reason": "stop", "message": {
                    "content": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)}}]}

    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("workflow fixture", "https://provider.example/v1",
                                          "synthetic-not-a-real-key", PASSPHRASE)
    profile = models.create_profile("workflow chat fixture", "chat", connection["id"], "fixture-model",
                                    input_usd_per_million=1, output_usd_per_million=2)
    extraction = models.create_profile("fixture source author", "extraction", connection["id"], "fixture-model")
    chat = ChatService(ledger, models)
    source = SourceService(ledger).register_bytes("synthetic-method.txt",
        b"Synthetic counts are required. A separate synthetic route needs additional input.")
    ir = SourceService(ledger).parse(source["id"])
    block = ir["blocks"][0]
    claim = {"proposition": block["exact_text"], "subject": "Synthetic method input",
        "predicate": "requires", "object": "synthetic inputs", "polarity": "positive",
        "conditions": ["Synthetic development fixture only"], "unknowns": ["No biological validity implied"],
        "assertion_kind": "source_assertion", "anchors": [{"ir_id": ir["id"], "block_id": block["id"],
            "start": 0, "end": len(block["exact_text"]), "quote": block["exact_text"]}],
        "typed_attributes": [{"name": "workflow.input", "value": value,
                              "evidence_anchor_indices": [0], "qualifiers": ["Synthetic fixture"]}
                             for value in ("counts", "additional")]}
    candidate = chat.knowledge.add_candidate(claim, run_id="synthetic-fixture-authoring", profile_id=extraction["id"])
    routes = []
    for index, name in enumerate(("counts", "additional")):
        routes.append({"route_id": name + "_route", "label": "Synthetic " + name + " route",
            "requirements": [{"requirement_id": name, "label": "Synthetic " + name + " availability",
                "report_pointer": "/reported_inputs/" + name, "source_bindings": [{
                    "candidate_id": candidate["id"], "candidate_hash": candidate["content_hash"],
                    "attribute_index": index, "attribute_hash": content_hash(candidate["claim"]["typed_attributes"][index])}]}],
            "context_candidate_ids": [], "requirements_complete": False,
            "scope_notes": ["Synthetic development mapping, never a complete scientific contract"]})
    catalog = WorkflowInputCatalog.model_validate({"schema_version": "development-workflow-input-catalog-v1",
        "authority": "developer_source_interpretation_not_human_review", "routes": routes}).model_dump(mode="json")
    digest = content_hash(catalog)
    catalog_id = "synthetic-workflow-catalog-" + digest
    ledger.put_record("workflow_input_catalog", catalog_id, {"id": catalog_id, "catalog": catalog, "catalog_hash": digest})
    ledger.set_state("workflow_input_catalog", {"record_id": catalog_id, "catalog_hash": digest})
    app.__dict__.update(models=models, chat=chat, connection=connection, profile=profile,
        conversation=chat.create_conversation("Synthetic workflow chat"), source=source, candidate=candidate,
        catalog=catalog, workflow_options={"catalog_record_id": catalog_id, "catalog_hash": digest})
    app.current_conversation_id = app.conversation["id"]
    return app


def send(app, prompt="我有 counts。", **changes):
    options = {"profile_id": app.profile["id"], "passphrase": PASSPHRASE, "budget": deepcopy(BUDGET),
               "request_id": "fixed-workflow-send", "use_knowledge": False, "purpose": "explanation",
               "workflow_options": deepcopy(app.workflow_options)}
    options.update(changes)
    app.current_conversation_id = options.pop("conversation_id", app.conversation["id"])
    return app.chat.send(app.current_conversation_id, prompt, **options)


def current_request(app):
    requests = [r for r in app.ledger.list_records("chat_request")
                if r["conversation_id"] == app.current_conversation_id]
    return max(requests, key=lambda r: r["sequence"])


def evaluate(app, value=True, *, quote=None, turn_id=None, pointer="/reported_inputs/counts", routes=None):
    turn = current_request(app)
    return {"action": "evaluate_workflow_inputs", "route_ids": routes or ["counts_route"],
        "reports": [{"report_pointer": pointer, "reported_value": value,
                     "user_turn_id": turn_id or turn["id"], "quote": quote or turn["prompt"]}], "answer": None}


def finish(app, payload):
    """Render the declared synthetic choices, without inferring natural language."""
    contract = None
    for message in reversed(payload["messages"]):
        content = message.get("content", "")
        for encoded in (content, content.partition("\n")[2]):
            try:
                decoded = json.loads(encoded)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(decoded, dict) and "answer_contract" in decoded:
                contract = decoded["answer_contract"]
                break
        if contract is not None:
            break
    assert contract is not None, "Final request omitted the actual checked answer contract"
    steps = [{"i": route["step_id"], "f": "", "a": "仅保留输入检查的条件说明；未执行分析。",
              "e": route["evidence_aliases"][:1], "p": [], "k": "proposal"}
             for route in contract["step_routes"]]
    checks = deepcopy(contract["premises"])
    unknown = bool(contract["unknown_requirements"])
    missing = ([{"k": "not_supplied", "p": [], "t": "有些已列输入尚未明确报告。"}] if unknown else [])
    if checks:
        missing.append({"k": "independent_verification_missing", "p": [p["p"] for p in checks],
                        "t": "仅有用户报告，未独立测量输入。"})
    return {"action": "finish", "route_ids": [], "reports": [],
            "answer": {"d": "仅讨论开发候选的输入声明；未授权或执行分析。",
                       "s": steps, "p": checks, "m": missing}}


def script_success(app, value=True, **report_options):
    app.state["actions"] = [lambda a, p: evaluate(a, value, **report_options), finish]


def decode_scientific_feedback(feedback):
    """Independently expand the declared columns/table without text rewriting."""
    decoded = deepcopy(feedback)
    if feedback.get("encoding") != "shared_text_v2":
        return decoded
    assert feedback["source_columns"] == [
        "subject", "proposition", "typed_attributes", "conditions", "unknowns", "quotes"]
    assert feedback["attribute_columns"] == ["name", "value", "qualifiers", "evidence_anchor_indices"]
    table = feedback["text_table"]
    sources = {}
    for alias, values in feedback["candidate_sources"].items():
        source = dict(zip(feedback["source_columns"], values, strict=True))
        source["subject"] = table[source["subject"]]
        source["proposition"] = table[source["proposition"]]
        attributes = []
        for attribute_values in source["typed_attributes"]:
            attribute = dict(zip(feedback["attribute_columns"], attribute_values, strict=True))
            attribute["name"] = table[attribute["name"]]
            attribute["value"] = table[attribute["value"]]
            attribute["qualifiers"] = [table[value] for value in attribute["qualifiers"]]
            attributes.append(attribute)
        source["typed_attributes"] = attributes
        for key in ("conditions", "unknowns", "quotes"):
            source[key] = [table[value] for value in source[key]]
        sources[alias] = source
    decoded["candidate_sources"] = sources
    for route in decoded["routes"]:
        route["scope_notes"] = [table[value] for value in route["scope_notes"]]
    return decoded


def assert_no_execution_or_promotion(app):
    assert app.ledger.list_records("release") == []
    assert app.ledger.list_records("review") == []
    assert app.ledger.list_records("task_submission") == []
    with app.ledger.connect() as connection:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workbench_tasks'").fetchone():
            assert connection.execute("SELECT COUNT(*) FROM workbench_tasks").fetchone()[0] == 0
    assert app.chat.knowledge.resolve([app.candidate["id"]]).units == []


def test_actual_receipts_bind_every_user_leaf_and_replay_is_zero_call(app, monkeypatch):
    prompt = "样本甲🧬有 counts；这仅是用户报告。"
    quote = "有 counts"
    script_success(app, quote=quote)
    turn = send(app, prompt)
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    assert turn["workflow_run"] and turn["workflow_review"] and turn["workflow_answer"]
    assert len(turn["workflow_interpretations"]) == 1
    leaf = turn["workflow_interpretations"][0]
    assert leaf["report_pointer"] == "/reported_inputs/counts" and leaf["reported_value"] is True
    assert leaf["user_turn_id"] == turn["id"] and leaf["quote"] == quote and leaf["premise_id"] == "P1"
    assert leaf["call_id"] == turn["receipts"][0]["call_id"]
    assert leaf["unicode_spans"] and all(prompt[s["start"]:s["end"]] == quote for s in leaf["unicode_spans"])
    assert leaf["unicode_spans"][0]["start"] != len(prompt[:leaf["unicode_spans"][0]["start"]].encode())
    for receipt, payload, output in zip(turn["receipts"], app.calls, app.state["outputs"]):
        assert receipt == app.ledger.get_record("model_call", receipt["call_id"])
        assert receipt["structured_output_hash"] == content_hash(output)
        assert app.ledger.get_record("model_request", receipt["call_id"])["payload"] == payload
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("Replay/view dispatched another call"))
    assert send(app, prompt) == turn
    assert app.chat.view_turn(turn)["usable"]
    assert len(app.calls) == 2
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("value,status,action", [
    (True, "reported_met", "conditional_plan"), (False, "reported_unmet", "blocked"),
    (None, "unknown", "needs_evidence")])
def test_scripted_three_states_remain_user_interpretations(app, value, status, action):
    script_success(app, value)
    turn = send(app, "我明确报告这项状态；语义解释由本 fixture 指定。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    check = turn["workflow_review"]["route_results"][0]["assessment"]["decision_check"]
    assert (check["preconditions_status"], check["action_status"]) == (status, action)
    assert turn["workflow_interpretations"][0]["reported_value"] is value
    assert turn["workflow_answer"]["premise_checks"][0]["reported_status"] == status
    assert_no_execution_or_promotion(app)


def test_unmentioned_input_is_unknown_without_fabricated_user_quote(app):
    app.state["actions"] = [lambda a, p: {"action": "evaluate_workflow_inputs", "route_ids": ["counts_route"],
                                         "reports": [], "answer": None}, finish]
    turn = send(app, "先说明这个候选流程需要什么输入。")
    assert turn["status"] == "succeeded" and turn["workflow_interpretations"] == []
    requirement = turn["workflow_review"]["route_results"][0]["requirements"][0]
    assert not requirement["report_present"] and requirement["reported_value"] is None
    assert any(m["kind"] == "not_supplied" for m in turn["workflow_answer"]["typed_missing"])
    assert_no_execution_or_promotion(app)


def test_two_routes_have_distinct_steps_and_each_leaf_keeps_its_own_origin(app):
    def two_inputs(a, payload):
        turn = current_request(a)
        return {"action": "evaluate_workflow_inputs", "route_ids": ["counts_route", "additional_route"],
            "reports": [{"report_pointer": "/reported_inputs/counts", "reported_value": True,
                         "user_turn_id": turn["id"], "quote": "counts 已有"},
                        {"report_pointer": "/reported_inputs/additional", "reported_value": False,
                         "user_turn_id": turn["id"], "quote": "additional 没有"}], "answer": None}
    app.state["actions"] = [two_inputs, finish]
    turn = send(app, "对同一个样本：counts 已有，additional 没有。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    leaves = turn["workflow_interpretations"]
    assert [r["premise_id"] for r in leaves] == ["P1", "P2"]
    assert [r["reported_value"] for r in leaves] == [True, False]
    assert all(r["call_id"] == turn["receipts"][0]["call_id"] for r in leaves)
    assert [p["step_ids"] for p in turn["workflow_answer"]["premise_checks"]] == [["s1"], ["s2"]]
    assert [r["assessment"]["decision_check"]["action_status"]
            for r in turn["workflow_review"]["route_results"]] == ["conditional_plan", "blocked"]
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("damage", ["invented_quote", "invented_turn", "profile_pointer"])
def test_malformed_origin_is_rejected_without_source_repair(app, damage):
    def invalid(a, payload):
        result = evaluate(a)
        if damage == "invented_quote":
            result["reports"][0]["quote"] = "原用户没有说过的声明"
        elif damage == "invented_turn":
            result["reports"][0]["user_turn_id"] = "chat-turn-" + "f" * 64
        else:
            result["reports"][0]["profile_pointer"] = "/untrusted_conversation_context/1/content"
        return result
    app.state["actions"] = [invalid]
    turn = send(app)
    assert turn["status"] != "succeeded" and turn.get("workflow_review") is None
    assert len(app.calls) == 1 and turn.get("answer") is None
    assert_no_execution_or_promotion(app)


def test_another_conversation_user_prompt_cannot_supply_current_input(app):
    script_success(app)
    first = send(app, "旧会话的 counts 已有。")
    other = app.chat.create_conversation("Separate synthetic scope")
    app.state["actions"] = [lambda a, p: evaluate(a, quote=first["prompt"], turn_id=first["id"])]
    turn = send(app, "这里尚未报告任何数据。", conversation_id=other["id"], request_id="other-scope")
    assert turn["status"] != "succeeded" and turn.get("workflow_review") is None
    assert len(app.calls) == 3 and turn.get("answer") is None
    assert_no_execution_or_promotion(app)


def test_assistant_generated_text_is_not_promoted_to_user_report(app):
    app.state["actions"] = ["ASSISTANT_ONLY_COUNTS_AVAILABLE"]
    first = send(app, "先打个招呼。", workflow_options=None, request_id="ordinary-prefix")
    assert first["status"] == "succeeded" and first["answer"] == "ASSISTANT_ONLY_COUNTS_AVAILABLE"
    app.state["actions"] = [lambda a, p: evaluate(a, quote=first["answer"], turn_id=first["id"])]
    turn = send(app, "继续问输入条件。", request_id="workflow-after-assistant")
    assert turn["status"] != "succeeded" and turn.get("workflow_review") is None
    assert len(app.calls) == 2 and turn.get("answer") is None
    assert_no_execution_or_promotion(app)


def test_later_user_correction_replaces_report_with_new_origin(app):
    script_success(app, True)
    first = send(app, "我有 counts。", request_id="earlier-user-report")
    script_success(app, False)
    second = send(app, "更正：我没有 counts。", request_id="corrected-user-report")
    assert first["status"] == second["status"] == "succeeded" and len(app.calls) == 4
    assert first["workflow_interpretations"][0]["reported_value"] is True
    leaf = second["workflow_interpretations"][0]
    assert leaf["reported_value"] is False and leaf["user_turn_id"] == second["id"] and leaf["quote"] == second["prompt"]
    assert second["workflow_review"]["route_results"][0]["assessment"]["decision_check"]["action_status"] == "blocked"
    assert first["workflow_review"]["route_results"][0]["requirements"][0]["reported_value"] is True
    assert_no_execution_or_promotion(app)


def test_old_original_user_turn_can_be_cited_without_using_assistant_text(app):
    app.state["actions"] = ["ASSISTANT_NOT_AN_INPUT_SOURCE"]
    first = send(app, "这是原始用户报告：counts 已有。", workflow_options=None, request_id="original-report")
    script_success(app, True, quote="counts 已有", turn_id=first["id"])
    second = send(app, "按我的旧报告检查一下。", request_id="explicit-old-user-binding")
    assert second["status"] == "succeeded" and len(app.calls) == 3
    leaf = second["workflow_interpretations"][0]
    assert leaf["user_turn_id"] == first["id"] and leaf["quote"] == "counts 已有"
    assert leaf["call_id"] == second["receipts"][0]["call_id"]
    material = json.loads(app.calls[1]["messages"][1]["content"])
    assert [u["user_turn_id"] for u in material["user_turns"]] == [first["id"], second["id"]]
    assert all("ASSISTANT_NOT_AN_INPUT_SOURCE" not in u["prompt"] for u in material["user_turns"])
    assert_no_execution_or_promotion(app)


def test_candidate_workflow_turn_is_excluded_from_later_ordinary_recommendation_history(app):
    script_success(app)
    first = send(app, "DEV_CANDIDATE_ORIGINAL_PROMPT：我有 counts。")
    assert first["status"] == "succeeded"
    app.state["actions"] = ["ORDINARY_SYNTHETIC_REPLY"]
    second = send(app, "独立讨论一般方法。", workflow_options=None,
                  purpose="recommendation", request_id="ordinary-purpose-switch")
    assert second["status"] == "succeeded" and len(app.calls) == 3
    assert first["id"] not in second["context"]["included_turn_ids"]
    assert first["id"] in second["context"]["excluded_turn_ids"]
    transmitted = canonical_json(app.calls[-1]["messages"])
    assert first["prompt"] not in transmitted and first["answer"] not in transmitted
    assert app.candidate["id"] not in transmitted
    assert_no_execution_or_promotion(app)


def test_two_readonly_steps_share_the_existing_three_call_budget(app):
    app.state["actions"] = [lambda a, p: evaluate(a), lambda a, p: evaluate(a), finish]
    turn = send(app)
    assert turn["status"] == "succeeded" and len(app.calls) == 3
    assert len(turn["agent_steps"]) == 2 and len(turn["receipts"]) == 3
    assert turn["agent_budget"]["max_model_calls"] == turn["agent_budget"]["model_calls"] == 3
    assert app.calls[-1]["response_format"]["json_schema"]["schema"]["properties"]["action"]["enum"] == ["finish"]
    assert turn["workflow_interpretations"][0]["call_id"] == turn["receipts"][1]["call_id"]
    assert_no_execution_or_promotion(app)


def test_latest_tool_context_preserves_full_users_sources_and_immutable_prior_trace(app, monkeypatch):
    """A scripted route revision replaces model context, never the local trace."""
    prompt = "同一个样本甲🧬：counts 尚未确认；additional 明确没有。请按原话讨论候选输入。"
    app.state["actions"] = [
        lambda a, p: evaluate(a, None, quote="counts 尚未确认"),
        lambda a, p: evaluate(a, False, quote="additional 明确没有",
                              pointer="/reported_inputs/additional", routes=["additional_route"]),
        finish,
    ]
    turn = send(app, prompt)
    assert turn["status"] == "succeeded" and len(app.calls) == 3
    initial = json.loads(app.calls[0]["messages"][1]["content"])
    for call in app.calls[1:]:
        assert len(call["messages"]) == 4
        compact = json.loads(call["messages"][1]["content"])
        assert compact["user_turns"] == initial["user_turns"]
        assert compact["user_turns"][0]["prompt"] == prompt
        assert compact["current_user_turn_id"] == turn["id"]
        assert compact["source_snapshot_hash"] == initial["catalog"]["source_snapshot_hash"]
        assert "catalog" not in compact
        assert compact["available_route_index"] == [
            {"route_id": route["route_id"], "label": route["label"],
             "report_pointers": [requirement["report_pointer"] for requirement in route["requirements"]]}
            for route in app.catalog["routes"]]
    final_messages = app.calls[-1]["messages"]
    assert json.loads(final_messages[2]["content"]) == app.state["outputs"][1]
    previous = json.loads(app.calls[1]["messages"][-1]["content"].partition("\n")[2])
    latest = json.loads(final_messages[-1]["content"].partition("\n")[2])
    assert [route["route_id"] for route in previous["routes"]] == ["counts_route"]
    assert [route["route_id"] for route in latest["routes"]] == ["additional_route"]
    assert previous["result_hash"] != latest["result_hash"]
    assert previous["result_hash"] not in canonical_json(final_messages)
    assert latest["encoding"] == "shared_text_v2" and latest["candidate_sources"]
    restored = decode_scientific_feedback(latest)
    assert restored["routes"][0]["scope_notes"] == app.catalog["routes"][1]["scope_notes"]
    for source in restored["candidate_sources"].values():
        assert source["subject"] == app.candidate["claim"]["subject"]
        assert source["proposition"] == app.candidate["claim"]["proposition"]
        assert source["conditions"] == app.candidate["claim"]["conditions"]
        assert source["unknowns"] == app.candidate["claim"]["unknowns"]
        assert source["quotes"] == [anchor["quote"] for anchor in app.candidate["claim"]["anchors"]]
        assert source["typed_attributes"] == app.candidate["claim"]["typed_attributes"]
    assert len(turn["agent_steps"]) == 2 and len(turn["receipts"]) == 3
    for index, step in enumerate(turn["agent_steps"]):
        assert app.ledger.get_record("chat_agent_step", f"{turn['id']}:{index}") == step
    assert [step["result"]["workflow_review"]["route_results"][0]["route_id"]
            for step in turn["agent_steps"]] == ["counts_route", "additional_route"]
    for receipt in turn["receipts"]:
        assert receipt == app.ledger.get_record("model_call", receipt["call_id"])
        assert receipt["budget"]["max_input_tokens"] == BUDGET["max_input_tokens"]
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("Trace replay dispatched a call"))
    assert app.chat.view_turn(turn)["usable"]
    assert len(app.calls) == 3
    assert_no_execution_or_promotion(app)


def test_legacy_literal_context_replays_after_default_encoding_changes(app, monkeypatch):
    from sckg_workbench.workflow_chat import prepare_context

    script_success(app)
    with monkeypatch.context() as legacy:
        legacy.setattr(app.chat, "_prepare_context", lambda request: prepare_context(
            app.ledger, request, feedback_encoding="literal_v1"))
        turn = send(app, "旧格式原用户报告：counts 已有。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    saved = app.ledger.get_record("chat_context", turn["id"])
    assert "feedback_encoding" not in saved["workflow_material"]
    literal = json.loads(app.calls[-1]["messages"][-1]["content"].partition("\n")[2])
    assert "encoding" not in literal and "text_table" not in literal
    assert all(isinstance(source, dict) for source in literal["candidate_sources"].values())
    assert decode_scientific_feedback(literal) == literal
    request = app.ledger.get_record("chat_request", turn["id"])
    assert prepare_context(app.ledger, request)["workflow_material"]["feedback_encoding"] == "shared_text_v2"
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("Legacy view dispatched a call"))
    view = app.chat.view_turn(turn)
    assert view["usable"] and view["workflow_answer"] == turn["workflow_answer"]
    assert len(app.calls) == 2
    assert_no_execution_or_promotion(app)


def test_shared_text_encoding_roundtrips_all_scientific_fields_without_truncation(app, monkeypatch):
    # Distinct long end markers make dropped tails visible. This remains only
    # synthetic engineering content, not real-paper evidence or a capacity score.
    text = "FULL_QUOTE_BEGIN🧬" + "完整原文甲乙。" * 240 + "FULL_QUOTE_END"
    source = SourceService(app.ledger).register_bytes("long-synthetic-source.txt", text.encode())
    ir = SourceService(app.ledger).parse(source["id"])
    block = ir["blocks"][0]
    claim = deepcopy(app.candidate["claim"])
    claim.update(subject="FULL_SUBJECT_BEGIN" + "来源主题" * 70 + "FULL_SUBJECT_END",
        proposition=block["exact_text"],
        conditions=["CONDITION_BEGIN" + "限定条件" * 180 + "CONDITION_END", "Second complete condition"],
        unknowns=["UNKNOWN_BEGIN" + "尚未确定" * 170 + "UNKNOWN_END", "Second complete unknown"],
        anchors=[{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                  "end": len(block["exact_text"]), "quote": block["exact_text"]}])
    qualifier = "QUALIFIER_BEGIN" + "输入限定" * 140 + "QUALIFIER_END"
    for attribute in claim["typed_attributes"]:
        attribute["qualifiers"] = [qualifier, "An additional complete qualifier"]
    claim["typed_attributes"].extend([
        {"name": "workflow.action", "value": "ACTION_BEGIN" + "完整动作" * 220 + "ACTION_END",
         "qualifiers": [qualifier], "evidence_anchor_indices": [0]},
        {"name": "workflow.failure", "value": "FAILURE_BEGIN" + "失败限定" * 210 + "FAILURE_END",
         "qualifiers": ["A source failure statement, not an executed failure"], "evidence_anchor_indices": [0]},
        {"name": "implementation.note", "value": "T1", "qualifiers": ["T1 is literal source text"],
         "evidence_anchor_indices": [0]},
    ])
    candidate = app.chat.knowledge.add_candidate(claim, run_id="synthetic-long-source-fixture",
                                                profile_id=app.candidate["origin"]["profile_id"])
    catalog = deepcopy(app.catalog)
    for route in catalog["routes"]:
        route["scope_notes"].append("SCOPE_BEGIN" + "路线范围" * 150 + "SCOPE_END")
        for requirement in route["requirements"]:
            for binding in requirement["source_bindings"]:
                binding.update(candidate_id=candidate["id"], candidate_hash=candidate["content_hash"],
                    attribute_hash=content_hash(candidate["claim"]["typed_attributes"][binding["attribute_index"]]))
    digest = content_hash(catalog)
    catalog_id = "synthetic-long-workflow-catalog-" + digest
    app.ledger.put_record("workflow_input_catalog", catalog_id,
                          {"id": catalog_id, "catalog": catalog, "catalog_hash": digest})
    app.ledger.set_state("workflow_input_catalog", {"record_id": catalog_id, "catalog_hash": digest})
    app.catalog, app.candidate, app.source = catalog, candidate, source
    app.workflow_options = {"catalog_record_id": catalog_id, "catalog_hash": digest}
    script_success(app)
    turn = send(app, "counts 已有；这里只验证完整文本的可逆编码。")
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    feedback = json.loads(app.calls[-1]["messages"][-1]["content"].partition("\n")[2])
    assert feedback["encoding"] == "shared_text_v2"
    restored = decode_scientific_feedback(feedback)
    expected = {key: candidate["claim"][key]
                for key in ("subject", "proposition", "typed_attributes", "conditions", "unknowns")}
    expected["quotes"] = [anchor["quote"] for anchor in candidate["claim"]["anchors"]]
    assert list(restored["candidate_sources"].values()) == [expected]
    assert restored["routes"][0]["scope_notes"] == catalog["routes"][0]["scope_notes"]
    assert restored["candidate_sources"]["E1"]["typed_attributes"][-1]["value"] == "T1"
    assert list(feedback["text_table"].values()).count(qualifier) == 1
    assert candidate["id"] not in canonical_json(feedback)
    assert all(isinstance(alias, str) for alias in feedback["answer_contract"]["evidence_aliases"])
    assert all(set(report) == {"premise_id", "report_pointer", "reported_value", "user_turn_id", "quote"}
               for report in feedback["interpreted_user_reports"])
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("Shared-source view dispatched a call"))
    assert app.chat.view_turn(turn)["usable"] and len(app.calls) == 2
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("route_count,expected_subsets", [(2, 3), (5, 30)])
def test_complete_source_envelope_blocks_before_first_call_even_when_initial_payload_fits(
        app, monkeypatch, route_count, expected_subsets):
    from sckg_workbench.workflow_chat import prepare_context, workflow_format

    # Long non-input source fields are absent from the initial input directory.
    # Distinct sources ensure multi-route estimates cannot reuse one source's
    # text to stand in for every selectable route.
    routes, candidates = [], []
    extraction_profile = app.candidate["origin"]["profile_id"]
    for index in range(route_count):
        text = f"QUOTE_{index}_BEGIN " + (f"q{index}" * 750) + f" QUOTE_{index}_END"
        source = SourceService(app.ledger).register_bytes(f"capacity-source-{index}.txt", text.encode())
        ir = SourceService(app.ledger).parse(source["id"])
        block = ir["blocks"][0]
        claim = deepcopy(app.candidate["claim"])
        claim.update(subject=f"Synthetic capacity source {index}", proposition=block["exact_text"],
            conditions=[f"CONDITION_{index}_BEGIN " + (f"c{index}" * 600) + f" CONDITION_{index}_END"],
            unknowns=[f"UNKNOWN_{index}_BEGIN " + (f"u{index}" * 500) + f" UNKNOWN_{index}_END"],
            anchors=[{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                      "end": len(block["exact_text"]), "quote": block["exact_text"]}])
        claim["typed_attributes"].append({"name": "workflow.failure",
            "value": f"FAILURE_{index}_BEGIN " + (f"f{index}" * 700) + f" FAILURE_{index}_END",
            "qualifiers": [f"Non-input scientific source qualifier {index}"], "evidence_anchor_indices": [0]})
        candidate = app.chat.knowledge.add_candidate(claim, run_id="synthetic-capacity-fixture",
                                                    profile_id=extraction_profile)
        candidates.append(candidate)
        route = deepcopy(app.catalog["routes"][0])
        route.update(route_id=f"capacity_{index}", label=f"Synthetic capacity route {index}")
        binding = route["requirements"][0]["source_bindings"][0]
        binding.update(candidate_id=candidate["id"], candidate_hash=candidate["content_hash"],
                       attribute_hash=content_hash(candidate["claim"]["typed_attributes"][0]))
        routes.append(route)
    catalog = WorkflowInputCatalog.model_validate({**app.catalog, "routes": routes}).model_dump(mode="json")
    digest = content_hash(catalog)
    catalog_id = "synthetic-capacity-catalog-" + digest
    app.ledger.put_record("workflow_input_catalog", catalog_id,
                          {"id": catalog_id, "catalog": catalog, "catalog_hash": digest})
    app.ledger.set_state("workflow_input_catalog", {"record_id": catalog_id, "catalog_hash": digest})
    app.catalog, app.candidate = catalog, candidates[0]
    app.workflow_options = {"catalog_record_id": catalog_id, "catalog_hash": digest}
    prompt = "counts 已有。请保留完整来源；本测试只检查付费前的容量门禁。"
    request_id = "capacity-rejected-before-dispatch"
    # This unstored high-ceiling material is solely an engineering estimate.
    # The subsequently registered real send uses the lower explicit ceiling.
    probe = {"id": "chat-turn-" + content_hash([app.ledger.workspace.namespace,
                app.conversation["id"], request_id]),
             "conversation_id": app.conversation["id"], "sequence": 1, "prompt": prompt,
             "workflow_options": app.workflow_options, "budget": deepcopy(BUDGET)}
    prepared = prepare_context(app.ledger, probe)
    capacity = prepared["context"]["workflow_capacity_admission"]
    initial_proxy = len(json.dumps({"messages": prepared["messages"],
        "response_format": workflow_format(initial=True)}, ensure_ascii=False).encode()) + 256
    required_proxy = capacity["maximum_estimated_input_proxy"]
    assert capacity["route_subsets_checked"] == expected_subsets
    assert capacity["actual_request_gateway_check_required"] is True
    assert capacity["quote_utf8_bound_per_input"] == 4 * min(1000, len(prompt))
    assert prepared["workflow_material"]["user_turns"][0]["prompt"] == prompt
    assert "not measured tokens or a scientific input report" in capacity["scope"]
    assert required_proxy > initial_proxy + 2
    limit = (initial_proxy + required_proxy) // 2
    assert initial_proxy < limit < required_proxy <= BUDGET["max_input_tokens"]
    assert app.ledger.list_records("chat_request") == []
    assert app.ledger.list_records("model_request") == []
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("Capacity gate dispatched a model call"))
    turn = send(app, prompt, request_id=request_id, budget={**BUDGET, "max_input_tokens": limit})
    assert turn["status"] == "failed" and turn.get("answer") is None
    assert turn["error"]["type"] == "WorkflowChatError"
    assert "完整可选流程上下文" in turn["error"]["message"]
    assert app.calls == [] and app.ledger.list_records("model_request") == []
    assert app.ledger.list_records("model_call") == []
    assert app.ledger.get_record("chat_context", turn["id"]) is None
    assert all(app.ledger.get_record("candidate", candidate["id"]) == candidate for candidate in candidates)
    assert_no_execution_or_promotion(app)


def test_suspension_between_tool_and_final_stops_current_use(app):
    def suspend_before_finish(a, payload):
        a.chat.knowledge.suspend("source", a.source["id"], actor="synthetic-fixture-actor",
                                 reason="Synthetic source invalidation, not a human scientific review")
        return finish(a, payload)
    app.state["actions"] = [lambda a, p: evaluate(a), suspend_before_finish]
    turn = send(app)
    assert turn["status"] != "succeeded" and turn.get("answer") is None
    assert len(app.calls) == 2
    assert not app.chat.view_turn(turn)["usable"]
    assert_no_execution_or_promotion(app)


def test_timeout_keeps_actual_receipt_and_never_retries_on_replay(app):
    app.state["actions"] = [TimeoutError("Synthetic timeout, never an actual network call")]
    turn = send(app)
    assert turn["status"] == "result_unknown" and len(app.calls) == 1
    assert len(turn["receipts"]) == 1
    actual = app.ledger.get_record("model_call", turn["receipts"][0]["call_id"])
    assert actual["status"] == "failed" and actual["outcome"] == "result_unknown"
    assert send(app) == turn and len(app.calls) == 1
    assert_no_execution_or_promotion(app)


def test_new_mode_binding_is_part_of_idempotency_signature(app):
    script_success(app)
    turn = send(app)
    assert turn["status"] == "succeeded"
    with pytest.raises(ChatError, match="different send"):
        send(app, workflow_options=None)
    with pytest.raises(ValueError):
        send(app, workflow_options={**app.workflow_options, "catalog_hash": "f" * 64})
    assert len(app.calls) == 2
    assert_no_execution_or_promotion(app)


def test_rehashed_saved_interpretation_cannot_override_actual_model_output(app, monkeypatch):
    script_success(app)
    turn = send(app)
    assert turn["status"] == "succeeded"
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    result["workflow_interpretations"][0]["reported_value"] = False
    run = result["workflow_run"]
    run["workflow_interpretations"] = deepcopy(result["workflow_interpretations"])
    run["binding_hash"] = content_hash({k: v for k, v in run.items() if k != "binding_hash"})
    # Simulate an adversarial edit in this owned temporary fixture only.
    with app.ledger.transaction() as connection:
        changed = connection.execute("UPDATE records SET payload=?,digest=? WHERE kind=? AND record_id=?",
            (canonical_json(result), content_hash(result), "chat_result", turn["id"]))
        assert changed.rowcount == 1
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("View tried to repair a saved binding"))
    view = app.chat.view_turn(turn)
    assert not view["usable"] and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and view["workflow_review"] is None and len(app.calls) == 2
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("damage", ["model_calls", "reserved_tokens", "receipts", "last_receipt"])
def test_rehashed_call_accounting_projection_cannot_override_actual_receipts(app, monkeypatch, damage):
    script_success(app)
    turn = send(app)
    assert turn["status"] == "succeeded" and len(app.calls) == 2
    actual_calls = deepcopy(app.ledger.list_records("model_call"))
    result = deepcopy(app.ledger.get_record("chat_result", turn["id"]))
    unchanged_run = deepcopy(result["workflow_run"])
    if damage == "model_calls":
        result["agent_budget"]["model_calls"] = 0
    elif damage == "reserved_tokens":
        result["agent_budget"]["charged_or_reserved_tokens"] += 1
    elif damage == "receipts":
        result["receipts"] = []
    else:
        assert result["receipt"]["call_id"] != result["receipts"][0]["call_id"]
        result["receipt"] = deepcopy(result["receipts"][0])
    # Only this temporary result projection is edited. Actual gateway records
    # and the complete source-bound workflow run remain byte-for-byte values.
    with app.ledger.transaction() as connection:
        changed = connection.execute("UPDATE records SET payload=?,digest=? WHERE kind=? AND record_id=?",
            (canonical_json(result), content_hash(result), "chat_result", turn["id"]))
        assert changed.rowcount == 1
    assert app.ledger.get_record("chat_result", turn["id"])["workflow_run"] == unchanged_run
    assert app.ledger.list_records("model_call") == actual_calls
    monkeypatch.setattr(app.models, "invoke", lambda *a, **k: pytest.fail("Accounting validation dispatched a call"))
    view = app.chat.view_turn(turn)
    assert not view["usable"] and view["current_status"] == "evidence_invalidated"
    assert view["answer"] is None and view["workflow_review"] is None
    assert view["workflow_interpretations"] == [] and view["workflow_answer"] is None
    assert len(app.calls) == 2 and app.ledger.list_records("model_call") == actual_calls
    assert_no_execution_or_promotion(app)


def test_explicit_cancel_during_actual_return_preserves_receipt_without_tool_or_retry(app):
    from sckg_workbench.chat_runs import ChatRunService

    def cancel_before_return(a, payload):
        turn = current_request(a)
        ChatRunService(a.ledger).request_cancel(turn["conversation_id"], turn["id"])
        return evaluate(a)
    app.state["actions"] = [cancel_before_return]
    turn = send(app)
    assert turn["status"] in {"cancelled", "result_unknown"} and turn.get("answer") is None
    assert len(app.calls) == 1 and len(turn["receipts"]) == 1
    assert app.ledger.get_record("model_call", turn["receipts"][0]["call_id"])["status"] == "succeeded"
    assert turn.get("agent_steps", []) == [] and turn.get("workflow_review") is None
    assert send(app) == turn and len(app.calls) == 1
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("damage", ["shell", "execute_action", "finish_first"])
def test_workflow_mode_cannot_dispatch_execution_or_skip_initial_check(app, damage):
    def forbidden(a, payload):
        result = evaluate(a)
        if damage == "shell":
            result["shell"] = "touch /tmp/synthetic-must-not-run"
        elif damage == "execute_action":
            result["action"] = "run_scrublet"
        else:
            result = {"action": "finish", "route_ids": [], "reports": [],
                      "answer": {"d": "Skipped input check", "s": [], "p": [], "m": []}}
        return result
    app.state["actions"] = [forbidden]
    turn = send(app, "直接帮我执行吧。")
    assert turn["status"] != "succeeded" and len(app.calls) == 1
    assert turn.get("answer") is None and turn.get("analysis_task_ids", []) == []
    assert_no_execution_or_promotion(app)


@pytest.mark.parametrize("damage", ["wrong_status", "unknown_evidence", "drop_unknown_gap"])
def test_final_answer_must_obey_actual_tool_premises_and_scope(app, damage):
    def invalid_finish(a, payload):
        output = finish(a, payload)
        if damage == "wrong_status":
            output["answer"]["p"][0].update(r="reported_met", a="conditional_plan")
        elif damage == "unknown_evidence":
            output["answer"]["s"][0].update(f="Unsupported synthetic fact", e=["E99"], k="source_bound")
        else:
            output["answer"]["m"] = [m for m in output["answer"]["m"] if m["k"] != "not_supplied"]
        return output
    value = None if damage == "drop_unknown_gap" else False
    app.state["actions"] = [lambda a, p: evaluate(a, value), invalid_finish]
    turn = send(app, "我明确报告没有；未知项请保持未知。")
    assert turn["status"] != "succeeded" and turn.get("answer") is None
    assert len(app.calls) == 2
    assert_no_execution_or_promotion(app)
