"""Declared-limit gateway/worker checks; all transports are synthetic memory fixtures."""
from copy import deepcopy

import pytest

from sckg_workbench.contracts import ExtractionOutput
from sckg_workbench.evidence_answers import EvidenceAnswerError, _call_binding
from sckg_workbench.model_capabilities import CAPABILITIES_VERSION, API_FAMILY
from sckg_workbench.model_service import ModelCapabilityError, ModelCallError, ModelServiceError
from sckg_workbench.storage import canonical_json, content_hash
from sckg_workbench.worker import _output_format
from tests.test_workbench_models import (BUDGET, PASSPHRASE, answer, call, setup_service)
from tests.test_workbench_worker import build_fixture, submit


FORMAT = {"type": "json_schema", "json_schema": {"name": "wire_fixture", "strict": True,
    "schema": {"type": "object", "properties": {"fact": {"type": "string"}},
        "required": ["fact"], "additionalProperties": False}}}


def capability(formats=("json_schema",), hashes=None):
    return {"schema_version": CAPABILITIES_VERSION, "api_family": API_FAMILY,
        "response_formats": list(formats), "json_schema_format_hashes": (
            [content_hash(FORMAT)] if hashes is None and "json_schema" in formats else list(hashes or []))}


def declared(service, connection, limits=None):
    return service.create_profile("Declared fixture", "chat", connection["id"], "exact-model",
        wire_capabilities=capability() if limits is None else limits)


def deny(*args, **kwargs):
    pytest.fail("Local capability rejection must not read credentials or dispatch")


@pytest.mark.parametrize("damage", ["name", "strict", "schema"])
def test_exact_format_rejection_precedes_credentials_and_request_records(tmp_path, monkeypatch, damage):
    service, ledger, connection = setup_service(tmp_path, deny)
    profile = declared(service, connection)
    changed = deepcopy(FORMAT)
    if damage == "schema":
        changed["json_schema"]["schema"]["properties"]["fact"]["minLength"] = 2
    else:
        changed["json_schema"][damage] = "another_name" if damage == "name" else False
    before = ledger.events()
    monkeypatch.setattr(service, "_credential", deny)
    with pytest.raises(ModelCapabilityError) as error:
        call(service, profile, response_format=changed, passphrase="even-the-wrong-passphrase")
    assert error.value.confirmed_no_dispatch and error.value.outcome == "not_dispatched"
    assert error.value.preflight["reason"] == "json_schema_format_hash_not_declared"
    assert not ledger.list_records("model_request") and not ledger.list_records("model_call")
    assert ledger.events() == before


def test_declared_request_keeps_exact_wire_and_canonical_local_validation(tmp_path):
    calls = []
    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        return answer(usage={"prompt_tokens": 10, "completion_tokens": 9, "total_tokens": 19})
    service, ledger, connection = setup_service(tmp_path, transport)
    profile = declared(service, connection)
    # The format is declared, but the real local validator must still reject
    # this scripted provider's extra field. No weaker wire/fallback rescues it.
    with pytest.raises(ModelCallError) as error:
        call(service, profile, response_format=FORMAT)
    assert len(calls) == 1 and calls[0]["response_format"] == FORMAT
    receipt = error.value.receipt
    assert receipt["status"] == "invalid_response" and receipt["usage_known"]
    assert receipt["wire_capabilities_hash"] == content_hash(profile["wire_capabilities"])
    assert receipt["wire_response_format_hash"] == content_hash(FORMAT)
    assert ledger.get_record("model_output", receipt["call_id"])["text"] == '{"fact":"source-bound","extra":7}'


def test_explicit_receipt_replay_checks_original_declaration_without_new_admission(tmp_path, monkeypatch):
    service, ledger, connection = setup_service(tmp_path, lambda *args: answer(
        content='{"fact":"source-bound"}', usage={"prompt_tokens": 10, "completion_tokens": 9}))
    profile = declared(service, connection)
    result = call(service, profile, response_format=FORMAT)
    messages = [{"role": "user", "content": "Read this fixed source."}]
    monkeypatch.setattr(service, "preflight", deny)
    receipt, request = _call_binding(service, profile, result, messages, FORMAT, BUDGET)
    assert receipt["wire_response_format_hash"] == content_hash(request["payload"]["response_format"])
    revised = deepcopy(profile)
    revised["wire_capabilities"] = capability(("text",))
    # Corruption is deliberately confined to an owned temporary ledger.
    with ledger.transaction() as connection:
        connection.execute("UPDATE records SET payload=?,digest=? WHERE kind='model_profile' AND record_id=?",
            (canonical_json(revised), content_hash(revised), profile["id"]))
    with pytest.raises(EvidenceAnswerError):
        _call_binding(service, revised, result, messages, FORMAT, BUDGET)


def test_strict_legacy_preflight_is_readonly_while_original_invocation_stays_unqualified(tmp_path, monkeypatch):
    calls = []
    service, ledger, connection = setup_service(tmp_path, lambda *args: calls.append(args) or answer(content="hello"))
    profile = service.create_profile("Legacy fixture", "chat", connection["id"], "exact-model")
    before = deepcopy(profile), ledger.events()
    with monkeypatch.context() as guarded:
        guarded.setattr(service, "_credential", deny)
        with pytest.raises(ModelCapabilityError) as error:
            service.preflight(profile["id"], FORMAT, require_declared=True)
        assert error.value.preflight["capabilities_status"] == "legacy_unqualified"
        assert not ledger.list_records("model_request") and not calls
    assert (ledger.get_record("model_profile", profile["id"]), ledger.events()) == before
    result = call(service, profile)
    assert result["status"] == "succeeded" and len(calls) == 1
    assert not {"wire_capabilities_hash", "wire_response_format_hash"}.intersection(result)


def test_json_object_declaration_never_implicitly_authorizes_schema(tmp_path, monkeypatch):
    service, ledger, connection = setup_service(tmp_path, deny)
    profile = declared(service, connection, capability(("json_object",)))
    monkeypatch.setattr(service, "_credential", deny)
    assert service.preflight(profile["id"], {"type": "json_object"}, require_declared=True)["dispatch_allowed"]
    with pytest.raises(ModelCapabilityError):
        call(service, profile, response_format=FORMAT)
    assert ledger.list_records("model_call") == []


def test_profile_revision_copies_declaration_and_does_not_migrate_legacy(tmp_path):
    service, ledger, connection = setup_service(tmp_path)
    old = service.create_profile("Legacy fixture", "chat", connection["id"], "exact-model")
    limits = capability()
    new = service.create_profile("Declared revision", "chat", connection["id"], "exact-model",
        wire_capabilities=limits, supersedes_profile_id=old["id"])
    limits["response_formats"].clear()
    assert new["wire_capabilities"] == capability()
    assert "wire_capabilities" not in ledger.get_record("model_profile", old["id"])
    with pytest.raises(ModelServiceError):
        service.create_profile("Embedding", "embedding", connection["id"], "exact-model", wire_capabilities=capability())


def test_ingestion_checks_both_formats_before_either_credential_or_claim(tmp_path, monkeypatch):
    worker, ledger, source, _, calls = build_fixture(tmp_path)
    models = worker.models
    connection = models.list_connections()[0]
    profiles = [models.create_profile(kind, kind, connection["id"], model,
        input_usd_per_million=1, output_usd_per_million=1,
        wire_capabilities=capability(hashes=[content_hash(_output_format(ExtractionOutput.model_json_schema()))])
            if kind == "extraction" else capability(("text",)))
        for kind, model in (("extraction", "extract-fixture"), ("assessment", "assess-fixture"))]
    task = submit(worker, source, profiles)
    monkeypatch.setattr(models, "_credential", deny)
    with pytest.raises(ModelCapabilityError):
        worker.run_once(passphrase=PASSPHRASE, outbound_authorized=True)
    assert worker.queue.get(task["task_id"])["status"] == "queued"
    assert worker.queue.get(task["task_id"])["attempt"] == 0
    assert not calls and not ledger.list_records("model_request") and not ledger.list_records("model_call")


@pytest.mark.parametrize("damage", ["name", "strict", "schema"])
def test_admission_send_validation_and_receipt_use_owned_caller_snapshot(tmp_path, monkeypatch, damage):
    calls = []
    def transport(_url, _headers, payload, _timeout):
        calls.append(deepcopy(payload))
        return answer(content='{"fact":"source-bound"}')
    service, ledger, connection = setup_service(tmp_path, transport)
    profile = declared(service, connection)
    caller_format = deepcopy(FORMAT)
    caller_messages = [{"role": "user", "content": "Read the original fixed source."}]
    caller_budget = deepcopy(BUDGET)
    original_messages, original_budget = deepcopy(caller_messages), deepcopy(caller_budget)
    credential = service._credential
    def mutate_after_admission(connection, passphrase):
        if damage == "schema":
            caller_format["json_schema"]["schema"]["properties"]["injected"] = {"type": "string"}
        else:
            caller_format["json_schema"][damage] = "unadmitted_name" if damage == "name" else False
        caller_messages[0]["content"] = "Changed after admission"
        caller_budget["max_output_tokens"] = 1
        return credential(connection, passphrase)
    monkeypatch.setattr(service, "_credential", mutate_after_admission)
    result = service.invoke(profile["id"], caller_messages, response_format=caller_format,
        budget=caller_budget, passphrase=PASSPHRASE, outbound_authorized=True)
    assert caller_format != FORMAT  # Exercise mutation; do not merely compare copies.
    assert len(calls) == 1 and calls[0]["response_format"] == FORMAT
    assert calls[0]["messages"] == original_messages and result["budget"] == original_budget
    assert result["wire_response_format_hash"] == content_hash(FORMAT)
    request = ledger.get_record("model_request", result["call_id"])
    assert request["payload"] == calls[0] and request["request_hash"] == content_hash(calls[0])
