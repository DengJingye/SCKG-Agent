"""Versioned model configuration and one-request, explicitly authorized gateway."""
from __future__ import annotations

import json
import math
import os
import re
import stat
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from dotenv import dotenv_values
from dotenv.parser import parse_stream

from .secrets import SecretVault
from .storage import canonical_json, content_hash
from .model_capabilities import (
    preflight_wire, validate_wire_capabilities, wire_receipt_binding,
)
from .model_diagnostics import safe_http_error_metadata


PURPOSES = frozenset({"extraction", "assessment", "chat", "evaluation", "embedding"})
MAX_ENV_FILE_BYTES = 64 * 1024
Transport = Callable[[str, dict, dict, float], dict]


class ModelServiceError(ValueError):
    pass


class ModelCapabilityError(ModelServiceError):
    """A local policy rejection; no credential or remote request is needed."""
    confirmed_no_dispatch = True
    outcome = "not_dispatched"

    def __init__(self, report):
        super().__init__("Model output is outside its declared wire capabilities; no request was sent")
        self.preflight = report


class ModelCallError(RuntimeError):
    def __init__(self, message, *, call_id=None, receipt=None, outcome="result_unknown"):
        super().__init__(message)
        self.call_id = call_id
        self.receipt = receipt
        self.outcome = outcome


def _strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = item
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite JSON number")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _validate_local_schema(schema):
    # Schema validation must never fetch remote documents or local files.
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in {"$ref", "$dynamicRef"} and (not isinstance(value, str) or not value.startswith("#")):
                raise ModelServiceError("Structured schemas may use local references only")
            _validate_local_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _validate_local_schema(value)


def _validate_response_format(response_format):
    if response_format is None:
        return
    if not isinstance(response_format, dict) or response_format.get("type") not in {"json_object", "json_schema"}:
        raise ModelServiceError("Structured format must be json_object or json_schema")
    if response_format["type"] == "json_schema":
        specification = response_format.get("json_schema")
        if not isinstance(specification, dict):
            raise ModelServiceError("json_schema format requires a schema object")
        if not isinstance(specification.get("name"), str) or not specification["name"] or "schema" not in specification:
            raise ModelServiceError("Structured schema requires a name and schema")
        _validate_local_schema(specification["schema"])
        try:
            Draft202012Validator.check_schema(specification["schema"])
        except SchemaError:
            raise ModelServiceError("Invalid structured output schema") from None


def output_contract_request(messages, response_format, validation_format=None):
    """Bind an explicit JSON-object wire to a complete local schema.

    This is an opt-in configuration, never an error fallback. The canonical
    schema is sent verbatim in a system message and counted by the same input
    budget as all other messages. Historical requests remain byte-compatible.
    """
    messages, response_format, validation_format = deepcopy((
        messages, response_format, validation_format))
    _validate_response_format(response_format)
    if validation_format is not None:
        specification = (validation_format.get('json_schema')
                         if isinstance(validation_format, dict) else None)
        if (response_format != {"type": "json_object"}
                or not isinstance(validation_format, dict)
                or validation_format.get("type") != "json_schema"
                or not isinstance(specification, dict)
                or specification.get("strict") is not True):
            raise ModelServiceError("Local validation requires explicit JSON-object wire and strict JSON Schema")
        _validate_response_format(validation_format)
        messages = [{"role": "system", "content":
            "Return exactly one JSON object satisfying this complete canonical output contract. "
            "The application independently validates every constraint; invalid output stops the run. "
            "Do not omit or weaken constraints. Canonical contract JSON:\n" +
            canonical_json(validation_format)}, *messages]
    return messages, response_format, validation_format


def local_validation_matches(request, receipt, validation_format=None):
    """Replay the original local contract without inferring one from today's code."""
    if validation_format is None:
        return ('local_validation_format' not in request
                and 'local_validation_format_hash' not in receipt)
    return (request.get('local_validation_format') == validation_format
            and receipt.get('local_validation_format_hash') == content_hash(validation_format))


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ModelServiceError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ModelServiceError(f"{name} is out of range")
    return float(value)


def _token_limit(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2_000_000:
        raise ModelServiceError(f"{name} must be an integer between 1 and 2000000")
    return value


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ModelServiceError("Endpoint requires an http(s) host without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ModelServiceError("Endpoint cannot contain a query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ModelServiceError("Remote model endpoints require HTTPS")
    return value.rstrip("/")


def _env_reference(env_file, env_variable):
    if not isinstance(env_file, (str, Path)) or not str(env_file).strip():
        raise ModelServiceError("An explicit credential file path is required")
    if not isinstance(env_variable, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_variable):
        raise ModelServiceError("A valid credential variable name is required")
    # Do not resolve symlinks: the reader must be able to reject the supplied path.
    return str(Path(env_file).expanduser().absolute()), env_variable


def _read_env_credential(env_file, env_variable):
    """Read one explicit credential without modifying the process environment."""
    path, variable = _env_reference(env_file, env_variable)
    try:
        # NOFOLLOW closes the final-component symlink race; NONBLOCK prevents
        # a nonregular file such as a FIFO from blocking before fstat.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_ENV_FILE_BYTES:
                raise ValueError("credential file type or size")
            raw = handle.read(MAX_ENV_FILE_BYTES + 1)
        if len(raw) > MAX_ENV_FILE_BYTES:
            raise ValueError("credential file size")
        source = raw.decode("utf-8-sig")
        bindings = list(parse_stream(StringIO(source)))
        if any(binding.error for binding in bindings):
            raise ValueError("credential file parse")
        if sum(binding.key == variable for binding in bindings) > 1:
            raise ValueError("ambiguous credential variable")
        values = dotenv_values(stream=StringIO(source), interpolate=False)
        value = values.get(variable)
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
            raise ValueError("credential value")
        return value.strip()
    except Exception:
        # Parser and OS diagnostics may contain file contents or credential
        # material. Never propagate them into a UI, event, or model receipt.
        raise ModelServiceError("Credential file could not be read or its selected key is invalid") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelCallError("Model endpoint redirects are not followed")


def http_transport(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    request = Request(url, json.dumps(payload).encode(), headers=headers, method="POST")
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ModelCallError("Model response exceeds gateway limit")
        result = _strict_json(raw)
    if not isinstance(result, dict):
        raise ModelCallError("Model response must be an object")
    return result


class ModelService:
    def __init__(self, workspace, ledger, transport: Transport | None = None):
        self.workspace = workspace
        self.ledger = ledger
        self.vault = SecretVault(workspace.root / "secrets.vault")
        self.transport = transport or http_transport

    def create_connection(self, name: str, base_url: str, api_key: str, passphrase: str) -> dict:
        if not isinstance(name, str) or not name.strip():
            raise ModelServiceError("Connection name is required")
        base_url = _base_url(base_url)
        connection_id = _id("connection")
        credential_ref = _id("credential")
        self.vault.set_secret(credential_ref, api_key, passphrase)
        record = {"id": connection_id, "connection_id": connection_id, "name": name.strip(),
                  "provider": "openai_compatible", "base_url": base_url,
                  "credential_source": "vault", "credential_ref": credential_ref, "created_at": _now()}
        with self.ledger.transaction() as conn:
            self.ledger.put_record("model_connection", connection_id, record, conn=conn)
            self.ledger.append_event("model_connection_created", connection_id, {}, conn=conn)
        return record

    def create_env_connection(self, name: str, base_url: str, env_file: str | Path, env_variable: str) -> dict:
        if not isinstance(name, str) or not name.strip():
            raise ModelServiceError("Connection name is required")
        base_url = _base_url(base_url)
        env_file, env_variable = _env_reference(env_file, env_variable)
        # Validate before persisting a reference. Only its path and variable
        # name enter the immutable record; the current value is discarded.
        _read_env_credential(env_file, env_variable)
        connection_id = _id("connection")
        record = {"id": connection_id, "connection_id": connection_id, "name": name.strip(),
                  "provider": "openai_compatible", "base_url": base_url,
                  "credential_source": "env_file", "env_file": env_file,
                  "env_variable": env_variable, "created_at": _now()}
        with self.ledger.transaction() as conn:
            self.ledger.put_record("model_connection", connection_id, record, conn=conn)
            self.ledger.append_event("model_connection_created", connection_id, {}, conn=conn)
        return record

    def profile_requires_passphrase(self, profile_id: str) -> bool:
        connection = self._profile_connection(profile_id)
        source = connection.get("credential_source", "vault")
        if source not in {"vault", "env_file"}:
            raise ModelServiceError("Unsupported credential source")
        return source == "vault"

    def _profile_connection(self, profile_id: str) -> dict:
        profile = self.ledger.get_record("model_profile", profile_id)
        if profile is None:
            raise ModelServiceError("Unknown profile")
        connection = self.ledger.get_record("model_connection", profile["connection_id"])
        if connection is None:
            raise ModelServiceError("Profile connection does not exist")
        return connection

    def _credential(self, connection: dict, passphrase: str) -> str:
        source = connection.get("credential_source", "vault")
        if source == "env_file":
            return _read_env_credential(connection.get("env_file"), connection.get("env_variable"))
        if source != "vault":
            raise ModelServiceError("Unsupported credential source")
        # Each call unlocks its own short-lived view; concurrent calls cannot
        # clear another call's decrypted credential map.
        call_vault = SecretVault(self.vault.path)
        call_vault.unlock(passphrase)
        try:
            return call_vault.get_secret(connection["credential_ref"])
        finally:
            call_vault.lock()

    def validate_profile_credential(self, profile_id: str, passphrase: str = "") -> None:
        # The secret is used only for validation and never returned to callers.
        self._credential(self._profile_connection(profile_id), passphrase)

    def list_connections(self) -> list[dict]:
        return self.ledger.list_records("model_connection")

    def create_profile(self, name: str, purpose: str, connection_id: str, model: str, *,
                       input_usd_per_million: float | None = None,
                       output_usd_per_million: float | None = None,
                       options: dict | None = None, supersedes_profile_id: str | None = None,
                       wire_capabilities: dict | None = None) -> dict:
        if purpose not in PURPOSES or not isinstance(name, str) or not name.strip() or not isinstance(model, str) or not model.strip():
            raise ModelServiceError("Valid purpose, profile name and model are required")
        if self.ledger.get_record("model_connection", connection_id) is None:
            raise ModelServiceError("Unknown connection")
        if supersedes_profile_id:
            previous = self.ledger.get_record("model_profile", supersedes_profile_id)
            if previous is None or previous["purpose"] != purpose:
                raise ModelServiceError("Superseded profile must exist with the same purpose")
        for field, value in [("input rate", input_usd_per_million), ("output rate", output_usd_per_million)]:
            if value is not None:
                _number(value, field)
        options = dict(options or {})
        if set(options) - {"temperature", "top_p", "seed", "reasoning_effort"}:
            raise ModelServiceError("Unsupported profile option")
        for field, maximum in [("temperature", 2), ("top_p", 1)]:
            if field in options and _number(options[field], field) > maximum:
                raise ModelServiceError(f"Invalid {field}")
        if "seed" in options and (isinstance(options["seed"], bool) or not isinstance(options["seed"], int)):
            raise ModelServiceError("seed must be an integer")
        if "reasoning_effort" in options and options["reasoning_effort"] not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            raise ModelServiceError("Unsupported reasoning effort")
        if wire_capabilities is not None:
            if purpose == "embedding":
                raise ModelServiceError("Chat wire capabilities do not apply to embedding profiles")
            try:
                wire_capabilities = validate_wire_capabilities(wire_capabilities)
            except ValueError:
                raise ModelServiceError("Invalid wire capability declaration") from None
        profile_id = _id("profile")
        record = {"id": profile_id, "profile_id": profile_id, "name": name.strip(), "purpose": purpose,
                  "connection_id": connection_id, "model": model.strip(), "options": options,
                  "input_usd_per_million": input_usd_per_million,
                  "output_usd_per_million": output_usd_per_million,
                  "supersedes_profile_id": supersedes_profile_id, "created_at": _now()}
        if wire_capabilities is not None:
            record["wire_capabilities"] = wire_capabilities
        with self.ledger.transaction() as conn:
            self.ledger.put_record("model_profile", profile_id, record, conn=conn)
            self.ledger.append_event("model_profile_created", profile_id, {"purpose": purpose}, conn=conn)
        return record

    def list_profiles(self, purpose: str | None = None) -> list[dict]:
        return [p for p in self.ledger.list_records("model_profile") if purpose is None or p["purpose"] == purpose]

    def preflight(self, profile_id: str, response_format: dict | None = None, *,
                  require_declared: bool = False) -> dict:
        """Check local output limits without reading credentials or sending data.

        Declarations are operator limits, not proof of remote enforcement.
        Existing profiles without them remain unqualified; strict scientific
        qualification must explicitly require a declaration before any request.
        """
        _validate_response_format(response_format)
        profile = self.ledger.get_record("model_profile", profile_id)
        if profile is None or profile.get("purpose") == "embedding":
            raise ModelServiceError("A compatible chat-output profile is required")
        if self.ledger.get_record("model_connection", profile["connection_id"]) is None:
            raise ModelServiceError("Profile connection does not exist")
        try:
            report = preflight_wire(profile, response_format, require_declared=require_declared)
        except ValueError:
            raise ModelServiceError("Invalid wire capability declaration") from None
        if not report["dispatch_allowed"]:
            raise ModelCapabilityError(report)
        return report

    def invoke(self, profile_id: str, messages: list[dict], *, passphrase: str = "",
               outbound_authorized: bool, budget: dict, response_format: dict | None = None,
               validation_format: dict | None = None) -> dict:
        if not isinstance(messages, list) or not messages:
            raise ModelServiceError("At least one text message is required")
        # Caller-owned objects can change while credentials are unlocked or
        # transport code runs. Admission, sizing, validation and receipts must
        # all use the same private input, rather than a later caller mutation.
        messages, response_format, validation_format = output_contract_request(
            messages, response_format, validation_format)
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in {"system", "developer", "user", "assistant"} or not isinstance(message["content"], str):
                raise ModelServiceError("M0 accepts text messages with role and content only")
        payload = {"messages": messages}
        if response_format is not None:
            payload["response_format"] = response_format
        return self._call(profile_id, payload, passphrase, outbound_authorized, budget,
                          embedding=False, validation_format=validation_format)

    def embed(self, profile_id: str, texts: list[str], *, passphrase: str = "",
              outbound_authorized: bool, budget: dict) -> dict:
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) and t for t in texts):
            raise ModelServiceError("Embedding inputs must be nonempty strings")
        return self._call(profile_id, {"input": list(texts)}, passphrase, outbound_authorized, budget, embedding=True)

    def _call(self, profile_id, payload, passphrase, outbound_authorized, budget, *, embedding,
              validation_format=None):
        if outbound_authorized is not True:
            raise ModelServiceError("Explicit outbound authorization is required")
        if not isinstance(budget, dict):
            raise ModelServiceError("An explicit request budget is required")
        budget = deepcopy(budget)
        if set(budget) - {"max_input_tokens", "max_output_tokens", "timeout_seconds", "max_cost_usd", "allow_unknown_cost"}:
            raise ModelServiceError("Unknown request budget field")
        input_limit = _token_limit(budget.get("max_input_tokens"), "max_input_tokens")
        output_limit = 0 if embedding else _token_limit(budget.get("max_output_tokens"), "max_output_tokens")
        timeout = _number(budget.get("timeout_seconds"), "timeout_seconds", positive=True)
        if timeout > 600:
            raise ModelServiceError("Request timeout cannot exceed 600 seconds")
        profile = self.ledger.get_record("model_profile", profile_id)
        if profile is None or (profile["purpose"] == "embedding") != embedding:
            raise ModelServiceError("Unknown profile or incompatible profile purpose")
        connection = self.ledger.get_record("model_connection", profile["connection_id"])
        if connection is None:
            raise ModelServiceError("Profile connection does not exist")
        if not embedding:
            # This is also called by invoke, not only by optional inspection UI.
            # Explicit limits are always enforced. No wire projection or retry.
            self.preflight(profile_id, payload.get("response_format"))
        # A deliberately conservative UTF-8 sizing estimate, not measured token usage.
        estimated_input = len(json.dumps(payload, ensure_ascii=False).encode()) + 256
        if estimated_input > input_limit:
            raise ModelServiceError("Estimated input exceeds the request token budget")
        input_rate = profile["input_usd_per_million"]
        output_rate = 0 if embedding else profile["output_usd_per_million"]
        price_known = input_rate is not None and output_rate is not None
        cost_cap = budget.get("max_cost_usd")
        if cost_cap is not None:
            _number(cost_cap, "max_cost_usd", positive=True)
            if not price_known:
                raise ModelServiceError("A monetary cap requires configured pricing")
            if (input_limit * input_rate + output_limit * output_rate) / 1_000_000 > cost_cap:
                raise ModelServiceError("Configured token ceilings exceed the monetary budget")
        if not price_known and budget.get("allow_unknown_cost") is not True:
            raise ModelServiceError("Pricing is unknown; explicitly allow token-bounded unknown cost")
        # Keep the canonical local validation snapshot separate from the
        # mutable dict handed to the transport implementation.
        request_payload = deepcopy(payload)
        request_payload["model"] = profile["model"]
        if not embedding:
            request_payload.update(profile["options"])
            request_payload["max_tokens"] = output_limit
            request_payload["stream"] = False
        if validation_format is not None:
            # New explicit mode admits the entire final wire body, including
            # model/options/stream/output ceiling. Keep legacy estimates intact.
            estimated_input = len(json.dumps(request_payload, ensure_ascii=False,
                                            allow_nan=False).encode()) + 256
            if estimated_input > input_limit:
                raise ModelServiceError("Estimated input exceeds the request token budget")
        api_key = self._credential(connection, passphrase)
        run_id = _id("model-call")
        call_meta = {"profile_id": profile_id, "connection_id": connection["connection_id"],
                     "requested_model": profile["model"], "estimated_input_tokens": estimated_input,
                     "input_estimate_method": "utf8_bytes_plus_256_not_tokenizer", "budget": dict(budget)}
        if not embedding:
            call_meta.update(wire_receipt_binding(profile, payload.get("response_format")))
        # Store exactly the bounded request sent, excluding headers and credentials.
        # Scientific assessments can then bind a receipt to the actual evidence.
        request_record = {"id": run_id, "payload": request_payload,
                          "request_hash": content_hash(request_payload)}
        if validation_format is not None:
            request_record['local_validation_format'] = deepcopy(validation_format)
            call_meta['local_validation_format_hash'] = content_hash(validation_format)
        self.ledger.put_record("model_request", run_id, request_record)
        self.ledger.append_event("model_call_started", run_id, call_meta)
        try:
            response = self.transport(connection["base_url"] + ("/embeddings" if embedding else "/chat/completions"),
                                      {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}, request_payload, timeout)
        except Exception as error:
            # Record useful failure categories without propagating provider
            # bodies, URLs, exception messages, or credentials.
            is_http_error = isinstance(error, HTTPError)
            http_status = None
            if is_http_error:
                try:
                    value = error.code
                    if type(value) is int and 100 <= value <= 599:
                        http_status = value
                except Exception:
                    pass
            try:
                is_timeout = isinstance(error, TimeoutError) or (
                    isinstance(error, URLError) and isinstance(error.reason, TimeoutError))
            except Exception:
                is_timeout = False
            reason = ("timeout" if is_timeout else "http_error" if is_http_error
                      else "network_error" if isinstance(error, URLError) else "transport_error")
            failure = dict(call_meta, call_id=run_id, status="failed", outcome="result_unknown",
                           failure_reason=reason, http_status=http_status,
                           usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
                           usage_known=False, cost_known=False, cost_usd=None)
            metadata = safe_http_error_metadata(error, forbidden_values=(api_key, passphrase))
            if metadata:
                failure["error_metadata"] = metadata
            if isinstance(error, HTTPError):
                try:
                    error.close()
                except Exception:
                    pass  # Diagnostics/cleanup cannot replace the original failure.
            self.ledger.put_record("model_call", run_id, failure)
            self.ledger.append_event("model_call_failed", run_id, failure)
            raise ModelCallError(f"Model request failed ({reason}); remote completion and billing may be unknown",
                                 call_id=run_id, receipt=failure) from None
        finally:
            api_key = None
        if not isinstance(response, dict):
            failure = dict(call_meta, call_id=run_id, status="invalid_response",
                           failure_reason="invalid_response_container", outcome="invalid_response",
                           usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
                           usage_known=False, cost_known=False, cost_usd=None)
            self.ledger.put_record("model_call", run_id, failure)
            self.ledger.append_event("model_call_failed", run_id,
                                     {"status": "invalid_response", "cost_known": False})
            raise ModelCallError("Provider returned an invalid response", call_id=run_id,
                                 receipt=failure, outcome="invalid_response")
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        input_tokens = _usage_count(usage.get("prompt_tokens", usage.get("input_tokens")))
        output_tokens = 0 if embedding else _usage_count(usage.get("completion_tokens", usage.get("output_tokens")))
        cost_known = price_known and input_tokens is not None and output_tokens is not None
        cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000 if cost_known else None
        result = dict(call_meta, call_id=run_id, returned_model=response.get("model"), provider_response_id=response.get("id"),
                      usage={"input_tokens": input_tokens, "output_tokens": output_tokens,
                             "total_tokens": _usage_count(usage.get("total_tokens"))},
                      reported_reasoning_tokens=_usage_count((usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))
                      if isinstance(usage.get("completion_tokens_details"), dict) else None,
                      usage_known=input_tokens is not None and output_tokens is not None,
                      cost_known=cost_known, cost_usd=cost,
                      cost_basis="configured_rates_times_reported_usage" if cost_known else "unknown",
                      budget_exceeded=(input_tokens is not None and input_tokens > input_limit)
                      or (output_tokens is not None and output_tokens > output_limit)
                      or (cost is not None and cost_cap is not None and cost > cost_cap))
        try:
            if embedding:
                data = response["data"]
                if not isinstance(data, list) or len(data) != len(payload["input"]):
                    raise ValueError("embedding count")
                ordered = sorted(data, key=lambda row: row["index"])
                if [row["index"] for row in ordered] != list(range(len(data))):
                    raise ValueError("embedding indices")
                vectors = [row["embedding"] for row in ordered]
                if not vectors or not all(isinstance(v, list) and len(v) == len(vectors[0]) and v and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in v) for v in vectors):
                    raise ValueError("embedding vectors")
                result.update(embeddings=vectors, status="succeeded")
            else:
                choice = response["choices"][0]
                content = choice["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("content")
                finish_reason = choice.get("finish_reason")
                # Keep the exact message before JSON/schema parsing. A failed
                # parse must not erase the output or the provider's stop cause.
                # This private immutable record excludes transport headers and
                # error bodies; only its digest enters the usage receipt.
                raw_output = {"id": run_id, "text": content,
                              "text_hash": content_hash(content), "finish_reason": finish_reason}
                self.ledger.put_record("model_output", run_id, raw_output)
                result.update(finish_reason=finish_reason,
                              raw_output_record_hash=content_hash(raw_output))
                structured = _strict_json(content) if "response_format" in payload else None
                if "response_format" in payload and not isinstance(structured, dict):
                    raise ValueError("structured object")
                if payload.get("response_format", {}).get("type") == "json_schema":
                    Draft202012Validator(payload["response_format"]["json_schema"]["schema"]).validate(structured)
                if validation_format is not None:
                    Draft202012Validator(validation_format['json_schema']['schema']).validate(structured)
                result.update(text=content, structured=structured, finish_reason=finish_reason,
                              structured_output_hash=content_hash(structured),
                              status="succeeded" if finish_reason == "stop" else "partial")
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            result.update(status="invalid_response")
            self.ledger.put_record("model_call", run_id, result)
            self.ledger.append_event("model_call_failed", run_id, {"status": result["status"], "cost_known": cost_known, "cost_usd": cost})
            raise ModelCallError("Provider output is incomplete or does not match the requested format", call_id=run_id,
                                 receipt=result, outcome="invalid_response") from None
        if result["budget_exceeded"]:
            result["status"] = "budget_exceeded"
        # Receipts contain usage and digests. Message text is kept separately in
        # the private output record, never in events or usage summaries.
        receipt = {k: v for k, v in result.items() if k not in {"text", "structured", "embeddings"}}
        with self.ledger.transaction() as conn:
            self.ledger.put_record("model_call", run_id, receipt, conn=conn)
            self.ledger.append_event("model_call_completed", run_id, {"status": result["status"], "cost_known": cost_known, "cost_usd": cost}, conn=conn)
        return result


def _usage_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
