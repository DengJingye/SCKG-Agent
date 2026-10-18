"""Caller-declared dataset origin, separate from legacy qualification routing.

References are bounded local metadata. Nothing is fetched, resolved or verified.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit


DATASET_ORIGINS = frozenset({"unknown", "caller_supplied", "synthetic", "published_derived"})
ORIGIN_FIELDS = frozenset({"dataset_origin", "dataset_origin_refs", "dataset_origin_verification"})
_DOI = re.compile(r"^(?:doi:)?10\.\d{4,9}/\S+$", re.I)
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*(?::[A-Za-z0-9_.-]+)*$")


def _reference(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("dataset origin references must be nonempty strings of at most 2000 characters")
    value = value.strip()
    if any(ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("dataset origin references may not contain control characters or local paths")
    if _DOI.fullmatch(value):
        return value
    if value.lower().startswith(("http://", "https://")):
        try:
            url = urlsplit(value)
            host = (url.hostname or "").rstrip(".")
            if (not host or url.username is not None or url.password is not None
                    or host.lower() in {"localhost", "local"}
                    or host.lower().endswith((".localhost", ".local", ".internal"))):
                raise ValueError("reference must be a non-local URL without credentials")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError("reference must not use a local/private IP address")
            if address is None and ("." not in host or re.fullmatch(r"[0-9.]+", host) or ":" in host):
                raise ValueError("invalid reference host")
            url.port  # Reject malformed ports without contacting the host.
        except ValueError as exc:
            raise ValueError("dataset origin reference must be a non-local HTTP(S) URL") from exc
        return value
    if (_IDENTIFIER.fullmatch(value) and not re.match(r"^[A-Za-z]:", value)
            and value.split(":", 1)[0].lower() not in {"file", "smb", "ssh", "ftp", "s3", "gs"}):
        return value
    raise ValueError("dataset origin reference must be a non-local source identifier, DOI or HTTP(S) URL")


def origin_context(dataset_origin="unknown", dataset_origin_refs=None) -> dict:
    if not isinstance(dataset_origin, str) or dataset_origin not in DATASET_ORIGINS:
        raise ValueError("dataset_origin must be unknown, caller_supplied, synthetic or published_derived")
    refs = [] if dataset_origin_refs is None else dataset_origin_refs
    if not isinstance(refs, list) or len(refs) > 8:
        raise ValueError("dataset_origin_refs must be a list of at most 8 references")
    return {"dataset_origin": dataset_origin, "dataset_origin_refs": [_reference(v) for v in refs],
            "dataset_origin_verification": "caller_declared_not_independently_verified"}


def origin_from_snapshot(snapshot: dict) -> dict:
    # Deliberately ignore provenance prose and every legacy qualification flag.
    return origin_context(snapshot.get("dataset_origin", "unknown"), snapshot.get("dataset_origin_refs"))
