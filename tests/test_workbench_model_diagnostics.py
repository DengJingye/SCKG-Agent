"""Offline metadata/privacy fixtures; no provider request or error-body read."""
from __future__ import annotations

from email.message import Message
import hashlib
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from sckg_workbench.model_diagnostics import safe_http_error_metadata
from sckg_workbench.model_service import ModelCallError, ModelService
from sckg_workbench.storage import Ledger, Workspace


KEY = "not-a-real-provider-secret"
PASSPHRASE = "test-only-passphrase"
REQUEST_ID = "req_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MINIMAL = {"schema_version": "provider-error-metadata-v1", "category": "bad_request"}
BUDGET = {"max_input_tokens": 4000, "max_output_tokens": 128, "timeout_seconds": 5,
          "allow_unknown_cost": True}


class NoBodyReads(io.BytesIO):
    def __init__(self):
        super().__init__(("provider body must remain unread: " + KEY).encode())
        self.read_attempts = []
        self.close_attempts = 0

    def read(self, *args, **kwargs):
        self.read_attempts.append("read")
        raise AssertionError("Error body must not be read")

    def read1(self, *args, **kwargs):
        self.read_attempts.append("read1")
        raise AssertionError("Error body must not be read1")

    def readline(self, *args, **kwargs):
        self.read_attempts.append("readline")
        raise AssertionError("Error body must not be read line by line")

    def readinto(self, *args, **kwargs):
        self.read_attempts.append("readinto")
        raise AssertionError("Error body must not be read into a buffer")

    def close(self):
        self.close_attempts += 1
        return super().close()


def headers(*pairs):
    result = Message()
    for name, value in pairs:
        result[name] = value
    return result


def error_with(header_values=None, *, code=400):
    stream = NoBodyReads()
    error = HTTPError("https://provider.invalid/" + KEY, code, "private reason " + KEY,
                      header_values, stream)
    return error, stream


@pytest.mark.parametrize("code, category", [
    (400, "bad_request"), (401, "authentication_required"), (403, "permission_denied"),
    (404, "not_found"), (408, "request_timeout"), (409, "conflict"),
    (413, "payload_too_large"), (415, "unsupported_media_type"), (422, "unprocessable_content"),
    (429, "rate_limited"), (451, "client_error"), (500, "server_error"), (599, "server_error"),
    (302, "redirect"), (200, "other_http_status"), (True, "unknown_http_status"),
    (None, "unknown_http_status"), (KEY, "unknown_http_status"), (600, "unknown_http_status"),
])
def test_http_category_is_closed_local_status_mapping(code, category):
    error, stream = error_with(code=code)
    assert safe_http_error_metadata(error) == dict(MINIMAL, category=category)
    assert stream.read_attempts == [] and not stream.closed
    error.close()


def test_non_http_errors_are_not_reflected():
    class UntrustedException(RuntimeError):
        @property
        def headers(self):
            raise AssertionError("Do not inspect non-HTTP metadata")

    assert safe_http_error_metadata(UntrustedException(KEY)) == {}
    assert safe_http_error_metadata(None) == {}


@pytest.mark.parametrize("name", ["X-Request-Id", "request-id", "X-Amzn-RequestId"])
@pytest.mark.parametrize("header_kind", ["message", "dict"])
def test_single_recognized_id_is_hashed_without_body_or_raw_header(name, header_kind):
    values = headers((name, REQUEST_ID), ("Authorization", KEY)) if header_kind == "message" else {
        name: REQUEST_ID, "Authorization": KEY}
    error, stream = error_with(values)
    result = safe_http_error_metadata(error, forbidden_values=(KEY, PASSPHRASE))
    assert result == dict(MINIMAL, provider_request_id_sha256=hashlib.sha256(REQUEST_ID.encode()).hexdigest())
    assert stream.read_attempts == [] and stream.close_attempts == 0
    serialized = json.dumps(result)
    assert KEY not in serialized and REQUEST_ID not in serialized and name not in serialized
    assert "private reason" not in serialized and "provider.invalid" not in serialized
    assert set(result) == {"schema_version", "category", "provider_request_id_sha256"}
    error.close()


@pytest.mark.parametrize("value", ["", " " + REQUEST_ID, REQUEST_ID + " ", "x" * 129,
    "req_\u00e9", "req_\u0391", "req_\u200bhidden", "req_\r\ninjected", "req_\0hidden",
    "https://provider.invalid/request", "file:///private/key", "user@example.com", "www.example.com",
    "req_first,req_second", "req_first;extra", "req/a", "req%2Fsecret", "req?secret"])
def test_invalid_or_injected_id_never_survives(value):
    error, stream = error_with({"x-request-id": value})
    assert safe_http_error_metadata(error) == MINIMAL
    assert stream.read_attempts == []
    error.close()


@pytest.mark.parametrize("value", ["x", "x" * 128, "550e8400-e29b-41d4-a716-446655440000"])
def test_allowed_ascii_id_length_boundaries(value):
    error, _ = error_with({"request-id": value})
    assert safe_http_error_metadata(error)["provider_request_id_sha256"] == hashlib.sha256(value.encode()).hexdigest()
    error.close()


@pytest.mark.parametrize("pairs", [
    (("x-request-id", REQUEST_ID), ("x-request-id", REQUEST_ID)),
    (("x-request-id", REQUEST_ID), ("X-Request-Id", "req_other")),
    (("x-request-id", REQUEST_ID), ("request-id", REQUEST_ID)),
    (("x-request-id", REQUEST_ID), ("x-amzn-requestid", "req_other")),
])
def test_multiple_or_duplicate_header_values_are_ambiguous(pairs):
    error, _ = error_with(headers(*pairs))
    assert safe_http_error_metadata(error) == MINIMAL
    error.close()


@pytest.mark.parametrize("values", [
    {"x-request-id": [REQUEST_ID]}, {"x-request-id": 123}, {"x-request-id": None},
    {"x-request-id": REQUEST_ID, "X-Request-Id": REQUEST_ID},
    {"x-request-id": REQUEST_ID, "request-id": REQUEST_ID},
])
def test_dictionary_values_must_be_exact_single_strings(values):
    error, _ = error_with(values)
    assert safe_http_error_metadata(error) == MINIMAL
    error.close()


@pytest.mark.parametrize("secret", [KEY, PASSPHRASE])
@pytest.mark.parametrize("wrap", [False, True])
def test_known_credential_or_passphrase_substring_is_discarded(secret, wrap):
    value = "req_" + secret + "_suffix" if wrap else secret
    error, _ = error_with({"x-request-id": value})
    result = safe_http_error_metadata(error, forbidden_values=(KEY, PASSPHRASE))
    assert result == MINIMAL and secret not in json.dumps(result)
    error.close()


def test_case_changed_secret_and_single_string_forbidden_argument_fail_closed():
    error, _ = error_with({"x-request-id": "req_" + KEY.upper()})
    assert safe_http_error_metadata(error, forbidden_values=KEY) == MINIMAL
    assert safe_http_error_metadata(error, forbidden_values=object()) == MINIMAL
    error.close()


def test_unknown_forbidden_objects_are_not_compared_or_stringified():
    class SecretObject:
        def __eq__(self, other):
            raise AssertionError("Do not compare an unknown secret object")

        def __str__(self):
            raise AssertionError("Do not stringify an unknown secret object")

    error, _ = error_with({"x-request-id": REQUEST_ID})
    assert safe_http_error_metadata(error, forbidden_values=(SecretObject(),)) == MINIMAL
    error.close()


def test_hashing_failure_keeps_only_safe_minimal_metadata(monkeypatch):
    def broken_hash(*args, **kwargs):
        raise RuntimeError(KEY)

    monkeypatch.setattr("sckg_workbench.model_diagnostics.hashlib", SimpleNamespace(sha256=broken_hash))
    error, stream = error_with({"x-request-id": REQUEST_ID})
    assert safe_http_error_metadata(error) == MINIMAL
    assert stream.read_attempts == []
    error.close()


def test_unknown_header_objects_and_failing_public_accessors_are_ignored():
    class UnknownHeaders:
        def get_all(self, name):
            raise AssertionError("Unknown header type must not be used")

    class BrokenHeaders(Message):
        def get_all(self, name, failobj=None):
            raise RuntimeError(KEY)

    class UntrustedDict(dict):
        def __iter__(self):
            raise AssertionError("Dict subclasses must not be used")

    for values in (None, UnknownHeaders(), BrokenHeaders(), UntrustedDict(), {"unrecognized-id": REQUEST_ID}):
        error, stream = error_with(values)
        assert safe_http_error_metadata(error, forbidden_values=(KEY,)) == MINIMAL
        assert stream.read_attempts == []
        error.close()


def test_http_header_and_status_access_errors_never_replace_original_failure():
    class BrokenAccess(HTTPError):
        def __getattribute__(self, name):
            if name in {"headers", "code"}:
                raise RuntimeError(KEY)
            return super().__getattribute__(name)

    error = BrokenAccess("https://provider.invalid", 400, KEY, None, NoBodyReads())
    assert safe_http_error_metadata(error) == dict(MINIMAL, category="unknown_http_status")
    error.close()


def test_real_model_service_http_failure_preserves_unknown_usage_and_closes_without_reading(tmp_path, caplog):
    # Root integrates the helper into the existing ModelService catch before
    # running this test. This is a local transport fixture, never a provider.
    original, stream = error_with(headers(("x-request-id", REQUEST_ID)))
    calls = []

    def transport(*args):
        calls.append(args)
        raise original

    workspace = Workspace(tmp_path / "isolated-workspace")
    ledger = Ledger(workspace)
    service = ModelService(workspace, ledger, transport=transport)
    connection = service.create_connection("offline HTTP error fixture", "https://provider.invalid/v1", KEY, PASSPHRASE)
    profile = service.create_profile("offline fixture", "chat", connection["id"], "exact-model")
    with pytest.raises(ModelCallError) as raised:
        service.invoke(profile["id"], [{"role": "user", "content": "Fixed engineering test input."}],
            passphrase=PASSPHRASE, outbound_authorized=True, budget=BUDGET)
    receipt = raised.value.receipt
    assert len(calls) == 1 and receipt == ledger.get_record("model_call", raised.value.call_id)
    assert receipt["error_metadata"] == dict(MINIMAL, provider_request_id_sha256=hashlib.sha256(REQUEST_ID.encode()).hexdigest())
    assert receipt["status"] == "failed" and receipt["outcome"] == "result_unknown"
    assert receipt["failure_reason"] == "http_error" and receipt["http_status"] == 400
    assert receipt["usage_known"] is False and receipt["cost_known"] is False and receipt["cost_usd"] is None
    assert all(value is None for value in receipt["usage"].values())
    assert len(ledger.list_records("model_request")) == len(ledger.list_records("model_call")) == 1
    assert ledger.list_records("model_output") == []
    assert stream.read_attempts == [] and stream.closed and stream.close_attempts >= 1
    persisted = json.dumps(receipt) + json.dumps(ledger.events()) + str(raised.value) + caplog.text
    assert KEY not in persisted and PASSPHRASE not in persisted and REQUEST_ID not in persisted
    assert "private reason" not in persisted and "provider.invalid/" + KEY not in persisted


@pytest.mark.parametrize("secret", [KEY, PASSPHRASE])
def test_real_model_service_passes_loaded_secret_and_passphrase_as_forbidden_values(tmp_path, secret):
    original, stream = error_with({"request-id": "req_" + secret + "_suffix"})

    def transport(*args):
        raise original

    ledger = Ledger(Workspace(tmp_path / "isolated-workspace"))
    service = ModelService(ledger.workspace, ledger, transport=transport)
    connection = service.create_connection("offline fixture", "https://provider.invalid/v1", KEY, PASSPHRASE)
    profile = service.create_profile("offline fixture", "chat", connection["id"], "exact-model")
    with pytest.raises(ModelCallError) as raised:
        service.invoke(profile["id"], [{"role": "user", "content": "Fixed input."}],
            passphrase=PASSPHRASE, outbound_authorized=True, budget=BUDGET)
    assert raised.value.receipt["error_metadata"] == MINIMAL
    assert stream.closed and stream.read_attempts == []


def test_real_model_service_close_exception_cannot_replace_original_http_failure(tmp_path, caplog):
    class CloseFailsOnce(NoBodyReads):
        def close(self):
            if not self.closed:
                super().close()
                raise RuntimeError(KEY)

    stream = CloseFailsOnce()
    original = HTTPError("https://provider.invalid", 400, "private reason " + KEY,
                         {"x-request-id": REQUEST_ID}, stream)

    def transport(*args):
        raise original

    ledger = Ledger(Workspace(tmp_path / "isolated-workspace"))
    service = ModelService(ledger.workspace, ledger, transport=transport)
    connection = service.create_connection("offline fixture", "https://provider.invalid/v1", KEY, PASSPHRASE)
    profile = service.create_profile("offline fixture", "chat", connection["id"], "exact-model")
    with pytest.raises(ModelCallError) as raised:
        service.invoke(profile["id"], [{"role": "user", "content": "Fixed input."}],
            passphrase=PASSPHRASE, outbound_authorized=True, budget=BUDGET)
    assert raised.value.receipt["http_status"] == 400
    assert raised.value.receipt["outcome"] == "result_unknown"
    assert raised.value.receipt["error_metadata"] == dict(MINIMAL,
        provider_request_id_sha256=hashlib.sha256(REQUEST_ID.encode()).hexdigest())
    assert stream.closed and stream.read_attempts == [] and stream.close_attempts == 1
    assert KEY not in str(raised.value) + str(ledger.events()) + caplog.text


@pytest.mark.parametrize("bad_code", [KEY, True, "broken_getter"])
def test_gateway_http_status_itself_is_sanitized_before_receipt(tmp_path, bad_code):
    class BrokenCode(HTTPError):
        def __getattribute__(self, name):
            if name == "code":
                raise RuntimeError(KEY)
            return super().__getattribute__(name)

    stream = NoBodyReads()
    original = (BrokenCode if bad_code == "broken_getter" else HTTPError)(
        "https://provider.invalid", 400 if bad_code == "broken_getter" else bad_code,
        "private reason " + KEY, {}, stream)
    def transport(*args):
        raise original
    ledger = Ledger(Workspace(tmp_path / "isolated-workspace"))
    service = ModelService(ledger.workspace, ledger, transport=transport)
    connection = service.create_connection("offline fixture", "https://provider.invalid/v1", KEY, PASSPHRASE)
    profile = service.create_profile("offline fixture", "chat", connection["id"], "exact-model")
    with pytest.raises(ModelCallError) as raised:
        service.invoke(profile["id"], [{"role": "user", "content": "Fixed input."}],
            passphrase=PASSPHRASE, outbound_authorized=True, budget=BUDGET)
    assert raised.value.receipt["http_status"] is None
    assert raised.value.receipt["failure_reason"] == "http_error"
    assert raised.value.receipt["outcome"] == "result_unknown"
    assert not raised.value.receipt["usage_known"] and stream.closed and not stream.read_attempts
    assert KEY not in json.dumps(raised.value.receipt) + json.dumps(ledger.events()) + str(raised.value)
