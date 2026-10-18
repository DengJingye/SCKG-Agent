"""Pure, explicitly declared limits for the existing chat-completions wire.

An operator declaration is not remote capability verification. This module does
not transform payloads, validate a scientific schema, read credentials, access a
ledger, probe a provider, or authorize retries/fallbacks.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .storage import content_hash


CAPABILITIES_VERSION = "chat-completions-wire-capabilities-v1"
PREFLIGHT_VERSION = "model-wire-preflight-v1"
API_FAMILY = "chat_completions"
MAX_DECLARED_ITEMS = 64
FORMATS = frozenset({"text", "json_object", "json_schema"})
CAPABILITY_KEYS = frozenset({"schema_version", "api_family", "response_formats",
                            "json_schema_format_hashes"})
RECEIPT_KEYS = frozenset({"wire_capabilities_hash", "wire_response_format_hash"})
_DECLARATION_ERROR = "Invalid wire capabilities declaration"
_REQUEST_ERROR = "Invalid wire request format"
_PROFILE_ERROR = "Invalid wire profile"


def validate_wire_capabilities(value):
    """Return a detached declaration; malformed input gets a safe ValueError."""
    valid = (isinstance(value, dict) and set(value) == CAPABILITY_KEYS
             and value.get("schema_version") == CAPABILITIES_VERSION
             and value.get("api_family") == API_FAMILY)
    if not valid:
        raise ValueError(_DECLARATION_ERROR)
    formats = value["response_formats"]
    hashes = value["json_schema_format_hashes"]
    if (not isinstance(formats, list) or not 1 <= len(formats) <= MAX_DECLARED_ITEMS
            or any(type(item) is not str or item not in FORMATS for item in formats)
            or len(formats) != len(set(formats))):
        raise ValueError(_DECLARATION_ERROR)
    if (not isinstance(hashes, list) or len(hashes) > MAX_DECLARED_ITEMS
            or any(type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None
                   for item in hashes)
            or len(hashes) != len(set(hashes))
            or ("json_schema" in formats) != bool(hashes)):
        raise ValueError(_DECLARATION_ERROR)
    return deepcopy(value)


def _capabilities(profile):
    if not isinstance(profile, dict):
        raise ValueError(_PROFILE_ERROR)
    if "wire_capabilities" not in profile:
        return None
    return validate_wire_capabilities(profile["wire_capabilities"])


def _requested_format(response_format):
    if response_format is None:
        return "text"
    if (not isinstance(response_format, dict)
            or type(response_format.get("type")) is not str
            or response_format["type"] not in {"json_object", "json_schema"}):
        raise ValueError(_REQUEST_ERROR)
    return response_format["type"]


def _format_hash(response_format):
    _requested_format(response_format)
    try:
        return content_hash(response_format)
    except (TypeError, ValueError):
        raise ValueError(_REQUEST_ERROR) from None


def preflight_wire(profile, response_format=None, *, require_declared=False):
    """Check exact declared limits without changing a profile or wire format.

    Legacy invocation may remain compatible, while strict callers explicitly
    require a declaration. Neither successful branch verifies a remote system.
    """
    if type(require_declared) is not bool:
        raise ValueError("Invalid wire declaration requirement")
    capabilities = _capabilities(profile)
    requested = _requested_format(response_format)
    fingerprint = _format_hash(response_format)
    if capabilities is None:
        status = "legacy_unqualified"
        allowed = not require_declared
        reason = "declaration_required" if require_declared else "legacy_unqualified"
    elif requested not in capabilities["response_formats"]:
        status, allowed, reason = "declared_unsupported", False, "response_format_not_declared"
    elif (requested == "json_schema"
            and fingerprint not in capabilities["json_schema_format_hashes"]):
        status, allowed, reason = "declared_unsupported", False, "json_schema_format_hash_not_declared"
    else:
        status, allowed, reason = "declared_within_limits", True, "within_declared_limits"
    return {"schema_version": PREFLIGHT_VERSION,
            "profile_id": profile.get("id", profile.get("profile_id")),
            "api_family": API_FAMILY, "requested_format": requested,
            "response_format_hash": fingerprint, "capabilities_status": status,
            "dispatch_allowed": allowed, "reason": reason, "remotely_verified": False,
            "capabilities_hash": content_hash(capabilities) if capabilities is not None else None}


def wire_receipt_binding(profile, response_format):
    """Fingerprint an explicit immutable declaration, without an admission check.

    Replay uses the recorded declaration and exact format, not today's dispatch
    policy. Historical profiles keep their original marker-free receipt shape.
    """
    capabilities = _capabilities(profile)
    if capabilities is None:
        return {}
    return {"wire_capabilities_hash": content_hash(capabilities),
            "wire_response_format_hash": _format_hash(response_format)}


def wire_receipt_matches(profile, receipt, response_format):
    """Check optional recorded markers without re-running capability admission.

    If both sides have no markers, legacy compatibility remains. Full immutable
    profile/request/receipt identity is still the caller's separate obligation.
    """
    if not isinstance(profile, dict) or not isinstance(receipt, dict):
        return False
    present = RECEIPT_KEYS.intersection(receipt)
    if "wire_capabilities" not in profile:
        return not present
    if present != RECEIPT_KEYS:
        return False
    try:
        expected = wire_receipt_binding(profile, response_format)
    except (TypeError, ValueError):
        return False
    return all(receipt[key] == expected[key] for key in RECEIPT_KEYS)
