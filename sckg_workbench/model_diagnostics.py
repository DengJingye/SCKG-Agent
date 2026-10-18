"""Allowlisted metadata from an HTTP error's existing in-memory headers.

No response body, exception message, URL or raw header value is retained. Status
categories describe HTTP status only; they establish neither remote completion,
billing, nor the cause of a provider's schema rejection. The caller owns closing
the HTTPError response stream after this pure projection.
"""
from __future__ import annotations

from email.message import Message
import hashlib
import re
from urllib.error import HTTPError


_SCHEMA_VERSION = "provider-error-metadata-v1"
_REQUEST_ID_HEADERS = ("x-request-id", "request-id", "x-amzn-requestid")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", flags=re.ASCII)
_STATUS_CATEGORIES = {
    400: "bad_request",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    408: "request_timeout",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "unprocessable_content",
    429: "rate_limited",
}


def _category(error):
    try:
        status = error.code
        if type(status) is not int or not 100 <= status <= 599:
            return "unknown_http_status"
        if status in _STATUS_CATEGORIES:
            return _STATUS_CATEGORIES[status]
        if status >= 500:
            return "server_error"
        if status >= 400:
            return "client_error"
        if status >= 300:
            return "redirect"
        return "other_http_status"
    except Exception:
        return "unknown_http_status"


def _single_request_id(headers):
    values = []
    if isinstance(headers, Message):
        for name in _REQUEST_ID_HEADERS:
            found = headers.get_all(name)
            if found is not None:
                if type(found) not in (list, tuple) or len(found) != 1:
                    return None
                values.append(found[0])
    elif type(headers) is dict:
        # Inspect only recognized names and their values. Arbitrary mappings
        # and dict subclasses may execute custom accessors and are rejected.
        for name in headers:
            if type(name) is str and name.lower() in _REQUEST_ID_HEADERS:
                values.append(headers[name])
    else:
        return None
    if len(values) != 1:
        return None
    value = values[0]
    if type(value) is not str or not _REQUEST_ID.fullmatch(value):
        return None
    return value


def _contains_forbidden(value, forbidden_values):
    if type(forbidden_values) is str:
        forbidden_values = (forbidden_values,)
    elif type(forbidden_values) not in (tuple, list, set, frozenset):
        # Do not invoke arbitrary iterators or stringify credential objects.
        return True
    for forbidden in forbidden_values:
        if forbidden is None:
            continue
        if type(forbidden) is not str:
            return True
        if not forbidden:
            continue
        if forbidden.casefold() in value.casefold():
            return True
    return False


def safe_http_error_metadata(error, *, forbidden_values=()):
    """Return a safe minimal dict, optionally with a request-id SHA256.

    Only actual HTTPError instances are eligible. No body accessor, private
    socket, network call, background worker, retry or stream close is used.
    IDs are one to 128 ASCII letters/digits/underscores/hyphens, beginning
    with a letter or digit. More than one recognized header value is rejected.
    Unknown/malformed headers or ordinary extraction failures omit the ID.
    """
    if not isinstance(error, HTTPError):
        return {}
    metadata = {"schema_version": _SCHEMA_VERSION, "category": _category(error)}
    try:
        request_id = _single_request_id(error.headers)
        if request_id is not None and not _contains_forbidden(request_id, forbidden_values):
            metadata["provider_request_id_sha256"] = hashlib.sha256(request_id.encode("ascii")).hexdigest()
    except Exception:
        # Diagnostics must not replace the original failed call or expose the
        # exception from a header object. Keep only the closed local category.
        pass
    return metadata
