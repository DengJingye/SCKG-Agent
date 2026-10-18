from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from sckg_workbench.model_service import MAX_ENV_FILE_BYTES, ModelCallError, ModelService, ModelServiceError
from sckg_workbench.secrets import SecretVault, VaultError, VaultLockedError
from sckg_workbench.storage import Ledger, Workspace, content_hash


PASSPHRASE = "test-only-passphrase"
KEY = "not-a-real-provider-secret"
BUDGET = {"max_input_tokens": 4000, "max_output_tokens": 128, "timeout_seconds": 5,
          "allow_unknown_cost": True}


def setup_service(tmp_path, transport=None):
    workspace = Workspace(tmp_path / "new-workspace")
    ledger = Ledger(workspace)
    service = ModelService(workspace, ledger, transport=transport)
    connection = service.create_connection("local test", "https://provider.example/v1", KEY, PASSPHRASE)
    return service, ledger, connection


def create_profile(service, connection, **kwargs):
    return service.create_profile("extract", "extraction", connection["id"], "exact-model", **kwargs)


def answer(content='{"fact":"source-bound","extra":7}', usage=None, finish="stop"):
    response = {"id": "provider-response", "model": "exact-model-version-1", "choices": [
        {"finish_reason": finish, "message": {"content": content}}]}
    if usage is not None:
        response["usage"] = usage
    return response


def call(service, profile, **kwargs):
    options = {"passphrase": PASSPHRASE, "outbound_authorized": True, "budget": BUDGET}
    options.update(kwargs)
    return service.invoke(profile["id"], [{"role": "user", "content": "Read this fixed source."}], **options)


def test_vault_authenticated_private_locked_and_immutable(tmp_path):
    path = tmp_path / "credential.vault"
    vault = SecretVault(path)
    with pytest.raises(VaultLockedError):
        vault.get_secret("one")
    vault.set_secret("one", KEY, PASSPHRASE)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert KEY not in path.read_text() and PASSPHRASE not in path.read_text()
    assert vault.locked
    with pytest.raises(VaultLockedError):
        vault.unlock("incorrect-passphrase")
    assert vault.locked
    vault.unlock(PASSPHRASE)
    assert vault.get_secret("one") == KEY
    vault.lock()
    with pytest.raises(VaultError, match="immutable"):
        vault.set_secret("one", "replacement", PASSPHRASE)
    payload = json.loads(path.read_text())
    payload["ciphertext"] = payload["ciphertext"][:-4] + "AAAA"
    path.write_text(json.dumps(payload))
    with pytest.raises(VaultError):
        vault.unlock(PASSPHRASE)


def test_concurrent_vault_writes_do_not_lose_secrets(tmp_path):
    path = tmp_path / "vault"
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda i: SecretVault(path).set_secret(str(i), f"value-{i}", PASSPHRASE), range(3)))
    vault = SecretVault(path)
    vault.unlock(PASSPHRASE)
    assert [vault.get_secret(str(i)) for i in range(3)] == [f"value-{i}" for i in range(3)]


def test_connections_and_profiles_are_separate_immutable_revisions(tmp_path):
    service, ledger, connection = setup_service(tmp_path)
    second = service.create_connection("another", "http://localhost:11434/v1", "local-key", PASSPHRASE)
    profile = create_profile(service, connection)
    revised = service.create_profile("extract next", "extraction", second["id"], "different-model",
                                     supersedes_profile_id=profile["id"])
    assert len(service.list_connections()) == 2
    assert profile["id"] != revised["id"]
    assert ledger.get_record("model_profile", profile["id"])["model"] == "exact-model"
    with pytest.raises(ValueError, match="immutable"):
        ledger.put_record("model_profile", profile["id"], dict(profile, model="changed"))
    assert KEY not in str(service.list_connections())
    assert KEY not in str(ledger.events())


@pytest.mark.parametrize("override", [
    {"outbound_authorized": False}, {"budget": {}},
    {"budget": dict(BUDGET, max_input_tokens=2)},
    {"budget": dict(BUDGET, max_output_tokens=-1)},
    {"budget": dict(BUDGET, timeout_seconds=float("nan"))},
    {"budget": dict(BUDGET, allow_unknown_cost=False)},
    {"budget": dict(BUDGET, max_cost_usd=1)},
    {"passphrase": "incorrect-passphrase"},
])
def test_authorization_budget_and_lock_fail_before_transport(tmp_path, override):
    calls = []
    service, _, connection = setup_service(tmp_path, lambda *args: calls.append(args))
    profile = create_profile(service, connection)
    with pytest.raises((ModelServiceError, VaultError)):
        call(service, profile, **override)
    assert calls == []


def test_structured_real_transport_usage_and_configured_cost(tmp_path):
    calls = []
    def transport(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return answer(usage={"prompt_tokens": 27, "completion_tokens": 9, "total_tokens": 36})
    service, ledger, connection = setup_service(tmp_path, transport)
    profile = create_profile(service, connection, input_usd_per_million=1, output_usd_per_million=2,
                             options={"temperature": 0})
    result = call(service, profile, response_format={"type": "json_object"},
                  budget=dict(BUDGET, max_cost_usd=.01))
    assert result["structured"] == {"fact": "source-bound", "extra": 7}
    assert result["usage"] == {"input_tokens": 27, "output_tokens": 9, "total_tokens": 36}
    assert result["cost_usd"] == pytest.approx(.000045) and result["cost_known"]
    assert result["requested_model"] == "exact-model" and result["returned_model"] == "exact-model-version-1"
    assert calls[0][0] == "https://provider.example/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer " + KEY
    assert calls[0][2]["model"] == "exact-model" and calls[0][2]["max_tokens"] == 128
    receipt = ledger.get_record("model_call", result["call_id"])
    assert "text" not in receipt and "structured" not in receipt
    assert KEY not in str(ledger.events()) and "source-bound" not in str(receipt)


def test_unknown_usage_and_prices_are_not_fabricated_zero(tmp_path):
    service, _, connection = setup_service(tmp_path, lambda *args: answer())
    profile = create_profile(service, connection)
    result = call(service, profile)
    assert result["usage"] == {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    assert result["cost_usd"] is None and not result["cost_known"] and not result["usage_known"]


def test_monetary_ceiling_preflight_and_partial_result(tmp_path):
    calls = []
    def transport(*args):
        calls.append(args)
        return answer(content="unfinished", finish="length")
    service, _, connection = setup_service(tmp_path, transport)
    profile = create_profile(service, connection, input_usd_per_million=10, output_usd_per_million=20)
    with pytest.raises(ModelServiceError, match="monetary"):
        call(service, profile, budget=dict(BUDGET, max_cost_usd=.001))
    assert not calls
    assert call(service, profile)["status"] == "partial"


def test_transport_failure_is_not_fallback_or_secret_leak(tmp_path):
    calls = []
    def transport(*args):
        calls.append(args)
        raise RuntimeError(KEY)
    service, ledger, connection = setup_service(tmp_path, transport)
    profile = create_profile(service, connection)
    with pytest.raises(ModelCallError) as error:
        call(service, profile)
    assert KEY not in str(error.value) and len(calls) == 1
    assert KEY not in str(ledger.events())
    assert ledger.events()[-1]["detail"]["outcome"] == "result_unknown"


def test_timeout_receipt_preserves_unknown_billing_without_secret_diagnostics(tmp_path):
    def transport(*args):
        raise TimeoutError(KEY)
    service, ledger, connection = setup_service(tmp_path, transport)
    with pytest.raises(ModelCallError) as error:
        call(service, create_profile(service, connection))
    receipt = error.value.receipt
    assert receipt["failure_reason"] == "timeout" and receipt["http_status"] is None
    assert receipt["cost_usd"] is None and not receipt["usage_known"]
    assert receipt["usage"]["total_tokens"] is None
    assert ledger.get_record("model_call", error.value.call_id) == receipt
    assert KEY not in str(error.value) + str(ledger.events()) + str(receipt)


def test_invalid_json_is_not_silently_repaired(tmp_path):
    service, ledger, connection = setup_service(tmp_path, lambda *args: answer(content='```json\n{"x": 1}\n```'))
    profile = create_profile(service, connection)
    with pytest.raises(ModelCallError):
        call(service, profile, response_format={"type": "json_object"})
    assert ledger.list_records("model_call")[0]["status"] == "invalid_response"


@pytest.mark.parametrize("finish", ["length", "stop"])
def test_invalid_json_retains_exact_private_output_and_actual_finish_reason(tmp_path, finish):
    original = '{"decision":"unfinished'
    service, ledger, connection = setup_service(tmp_path, lambda *args: answer(content=original, finish=finish))
    with pytest.raises(ModelCallError) as error:
        call(service, create_profile(service, connection), response_format={"type": "json_object"})
    receipt = error.value.receipt
    raw = ledger.get_record("model_output", error.value.call_id)
    assert receipt["status"] == "invalid_response" and receipt["finish_reason"] == finish
    assert raw["text"] == original and raw["text_hash"] == content_hash(original)
    assert content_hash(raw) == receipt["raw_output_record_hash"]
    assert "text" not in receipt and original not in str(ledger.events())
    with pytest.raises(ValueError, match="immutable"):
        ledger.put_record("model_output", error.value.call_id, dict(raw, text=original + '"}'))


def test_schema_rejection_preserves_unmodified_extra_fields_in_raw_message(tmp_path):
    original = '{"fact":"source-bound","extra":7}'
    service, ledger, connection = setup_service(tmp_path, lambda *args: answer(content=original))
    fmt = {"type": "json_schema", "json_schema": {"name": "strict", "schema": {
        "type": "object", "properties": {"fact": {"type": "string"}},
        "required": ["fact"], "additionalProperties": False}}}
    with pytest.raises(ModelCallError) as error:
        call(service, create_profile(service, connection), response_format=fmt)
    assert ledger.get_record("model_output", error.value.call_id)["text"] == original
    assert error.value.receipt["status"] == "invalid_response"


def test_invalid_response_container_gets_unknown_usage_receipt_without_storing_body(tmp_path):
    service, ledger, connection = setup_service(tmp_path, lambda *args: [KEY])
    with pytest.raises(ModelCallError) as error:
        call(service, create_profile(service, connection))
    receipt = ledger.get_record("model_call", error.value.call_id)
    assert receipt == error.value.receipt and receipt["status"] == "invalid_response"
    assert receipt["cost_usd"] is None and not receipt["usage_known"]
    assert ledger.get_record("model_output", error.value.call_id) is None
    assert KEY not in str(receipt) + str(ledger.events())


@pytest.mark.parametrize("content", ['{"x": 1, "x": 2}', '{"x": NaN}'])
def test_ambiguous_or_nonfinite_json_is_rejected(tmp_path, content):
    service, _, connection = setup_service(tmp_path, lambda *args: answer(content=content))
    with pytest.raises(ModelCallError):
        call(service, create_profile(service, connection), response_format={"type": "json_object"})


def test_schema_validates_without_dropping_extra_fields(tmp_path):
    service, _, connection = setup_service(tmp_path, lambda *args: answer())
    profile = create_profile(service, connection)
    output_format = {"type": "json_schema", "json_schema": {"name": "fact", "schema": {
        "type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}}
    assert call(service, profile, response_format=output_format)["structured"]["extra"] == 7
    output_format["json_schema"]["schema"]["additionalProperties"] = False
    with pytest.raises(ModelCallError):
        call(service, profile, response_format=output_format)
    output_format["json_schema"]["schema"] = {"$ref": "https://example.com/schema"}
    with pytest.raises(ModelServiceError, match="local references"):
        call(service, profile, response_format=output_format)


def test_reported_budget_overrun_cannot_be_reported_success(tmp_path):
    service, _, connection = setup_service(tmp_path, lambda *args: answer(usage={"prompt_tokens": 9000, "completion_tokens": 9}))
    result = call(service, create_profile(service, connection))
    assert result["budget_exceeded"] and result["status"] == "budget_exceeded"


def test_reported_reasoning_is_counted_when_provider_exceeds_output_limit(tmp_path):
    reply = answer(content="OK", usage={"prompt_tokens": 9, "completion_tokens": 140,
        "total_tokens": 149, "completion_tokens_details": {"reasoning_tokens": 120}})
    service, ledger, connection = setup_service(tmp_path, lambda *args: reply)
    result = call(service, create_profile(service, connection))
    assert result["reported_reasoning_tokens"] == 120
    assert result["usage"]["output_tokens"] == 140
    assert result["budget_exceeded"] and result["status"] == "budget_exceeded"
    assert ledger.get_record("model_call", result["call_id"])["status"] == "budget_exceeded"


def test_embedding_is_separate_endpoint_with_real_vector_order(tmp_path):
    calls = []
    def transport(url, headers, payload, timeout):
        calls.append((url, payload))
        return {"model": "embed-v1", "data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}],
                "usage": {"prompt_tokens": 8, "total_tokens": 8}}
    service, _, connection = setup_service(tmp_path, transport)
    profile = service.create_profile("embeddings", "embedding", connection["id"], "embed-v1", input_usd_per_million=.1)
    with pytest.raises(ModelServiceError):
        call(service, profile)
    result = service.embed(profile["id"], ["one", "two"], passphrase=PASSPHRASE,
                           outbound_authorized=True, budget=BUDGET)
    assert result["embeddings"] == [[1, 0], [0, 1]]
    assert result["usage"]["output_tokens"] == 0
    assert calls == [("https://provider.example/v1/embeddings", {"input": ["one", "two"], "model": "embed-v1"})]


@pytest.mark.parametrize("url", ["http://remote.example/v1", "https://key@example.com/v1", "https://example.com/v1?key=secret"])
def test_remote_plaintext_and_embedded_endpoint_credentials_rejected(tmp_path, url):
    service, _, _ = setup_service(tmp_path)
    with pytest.raises(ModelServiceError):
        service.create_connection("bad endpoint", url, KEY, PASSPHRASE)


def setup_env_service(tmp_path, transport=None):
    workspace = Workspace(tmp_path / "env-workspace")
    ledger = Ledger(workspace)
    service = ModelService(workspace, ledger, transport=transport)
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("DCS_API_KEY=test-only-env-key\n", encoding="utf-8")
    connection = service.create_env_connection("DCS test", "https://dcsapi.dcs.cloud/api/aigress/unified/v1/",
                                               env_file, "DCS_API_KEY")
    profile = service.create_profile("DCS chat", "chat", connection["id"], "deepseek-v4-pro")
    return service, ledger, connection, profile, env_file


def test_env_reference_nonstream_dcs_path_and_rotation_never_persist_keys(tmp_path):
    calls = []
    def transport(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return answer(content="hello", usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4})
    service, ledger, connection, profile, env_file = setup_env_service(tmp_path, transport)
    assert connection["credential_source"] == "env_file"
    assert connection["env_file"] == str(env_file.absolute())
    assert connection["env_variable"] == "DCS_API_KEY" and "credential_ref" not in connection
    assert not service.profile_requires_passphrase(profile["id"])
    assert service.validate_profile_credential(profile["id"]) is None
    result = service.invoke(profile["id"], [{"role": "user", "content": "hello"}],
                            outbound_authorized=True, budget=BUDGET)
    env_file.write_text("DCS_API_KEY=test-only-rotated-key\n", encoding="utf-8")
    service.invoke(profile["id"], [{"role": "user", "content": "hello again"}],
                   outbound_authorized=True, budget=BUDGET)
    assert calls[0][0] == "https://dcsapi.dcs.cloud/api/aigress/unified/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer test-only-env-key"
    assert calls[1][1]["Authorization"] == "Bearer test-only-rotated-key"
    assert calls[0][2]["model"] == "deepseek-v4-pro" and calls[0][2]["stream"] is False
    assert result["status"] == "succeeded" and result["usage_known"] and not result["cost_known"]
    assert not (service.workspace.root / "secrets.vault").exists()
    persisted = str(service.list_connections()) + str(ledger.events()) + str(ledger.list_records("model_request")) + str(ledger.list_records("model_call"))
    assert "test-only-env-key" not in persisted and "test-only-rotated-key" not in persisted


def test_env_parser_does_not_interpolate_or_load_process_environment(tmp_path, monkeypatch):
    calls = []
    service, _, _, profile, env_file = setup_env_service(tmp_path, lambda *args: calls.append(args) or answer(content="hello"))
    monkeypatch.setenv("DCS_API_KEY", "existing-process-value")
    monkeypatch.setenv("ANOTHER_KEY", "must-not-be-substituted")
    env_file.write_text("export DCS_API_KEY='${ANOTHER_KEY}'\n", encoding="utf-8")
    service.invoke(profile["id"], [{"role": "user", "content": "hello"}],
                   outbound_authorized=True, budget=BUDGET)
    assert calls[0][1]["Authorization"] == "Bearer ${ANOTHER_KEY}"
    assert os.environ["DCS_API_KEY"] == "existing-process-value"


@pytest.mark.parametrize("source", [
    "DCS_API_KEY=\n", "OTHER_KEY=unused\n", "DCS_API_KEY\n",
    "DCS_API_KEY='test-only-malformed-key\n", "DCS_API_KEY=one\nDCS_API_KEY=two\n",
    'DCS_API_KEY="line\\nseparator"\n',
])
def test_env_rotation_parse_failure_is_redacted_before_transport(tmp_path, source, caplog):
    calls = []
    service, ledger, _, profile, env_file = setup_env_service(tmp_path, lambda *args: calls.append(args))
    env_file.write_text(source, encoding="utf-8")
    with pytest.raises(ModelServiceError) as error:
        service.invoke(profile["id"], [{"role": "user", "content": "hello"}],
                       outbound_authorized=True, budget=BUDGET)
    assert calls == [] and ledger.list_records("model_request") == []
    assert "test-only-malformed-key" not in str(error.value) + caplog.text + str(ledger.events())
    assert "Credential file" in str(error.value)


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "oversized", "missing"])
def test_env_file_must_be_bounded_regular_nonsymlink(tmp_path, kind):
    service = ModelService(Workspace(tmp_path / "invalid-workspace"), Ledger(Workspace(tmp_path / "invalid-workspace")))
    env_file = tmp_path / "invalid.env"
    if kind == "symlink":
        target = tmp_path / "target.env"
        target.write_text("DCS_API_KEY=test-only-target\n", encoding="utf-8")
        env_file.symlink_to(target)
    elif kind == "directory":
        env_file.mkdir()
    elif kind == "fifo":
        os.mkfifo(env_file)
    elif kind == "oversized":
        env_file.write_bytes(b"#" * (MAX_ENV_FILE_BYTES + 1))
    with pytest.raises(ModelServiceError, match="Credential file"):
        service.create_env_connection("DCS test", "https://dcsapi.dcs.cloud/api/aigress/unified/v1", env_file, "DCS_API_KEY")
    assert service.list_connections() == []


def test_unknown_credential_source_never_falls_back_to_vault(tmp_path):
    calls = []
    service, ledger, connection, _, _ = setup_env_service(tmp_path, lambda *args: calls.append(args))
    invalid = dict(connection, id="connection-unknown", connection_id="connection-unknown", credential_source="unknown")
    ledger.put_record("model_connection", invalid["id"], invalid)
    profile = service.create_profile("unsupported source", "chat", invalid["id"], "deepseek-v4-pro")
    with pytest.raises(ModelServiceError, match="Unsupported credential source"):
        service.profile_requires_passphrase(profile["id"])
    with pytest.raises(ModelServiceError, match="Unsupported credential source"):
        service.validate_profile_credential(profile["id"])
    with pytest.raises(ModelServiceError, match="Unsupported credential source"):
        service.invoke(profile["id"], [{"role": "user", "content": "hello"}],
                       outbound_authorized=True, budget=BUDGET)
    assert calls == []


def test_legacy_vault_connection_defaults_to_passphrase_and_remains_usable(tmp_path):
    service, ledger, connection = setup_service(tmp_path, lambda *args: answer(content="hello"))
    legacy = dict(connection, id="legacy-connection", connection_id="legacy-connection")
    legacy.pop("credential_source")
    ledger.put_record("model_connection", legacy["id"], legacy)
    profile = create_profile(service, legacy)
    assert service.profile_requires_passphrase(profile["id"])
    assert service.validate_profile_credential(profile["id"], PASSPHRASE) is None
    with pytest.raises(VaultError):
        service.validate_profile_credential(profile["id"])
    assert call(service, profile)["status"] == "succeeded"
