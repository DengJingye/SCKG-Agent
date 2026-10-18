from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from core.execution_models import StrictModel


class PrivacyMode(str, Enum):
    STRICT_OFFLINE = "strict_offline"
    LOCAL_HYBRID = "local_hybrid"
    CLOUD_ASSISTED = "cloud_assisted"


class OutboundDisclosure(StrictModel):
    disclosure_id: str
    disclosure_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: str
    provider: str
    field_names: list[str]
    payload_bytes: int = Field(ge=0)
    prohibited_fields_removed: list[str] = Field(default_factory=list)
    path_redactions: int = Field(default=0, ge=0)
    created_at: datetime


class OutboundConsent(StrictModel):
    consent_id: str
    disclosure_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: Literal["once", "session"]
    session_id: str
    granted_at: datetime
    consumed_at: datetime | None = None


class OutboundPolicyDecision(StrictModel):
    allowed: bool
    mode: PrivacyMode
    reasons: list[str] = Field(default_factory=list)
    disclosure_hash: str | None = None


class SanitizedOutboundPayload(StrictModel):
    payload: dict[str, Any]
    disclosure: OutboundDisclosure


class OutboundDisclosureService:
    """Prepare metadata-only outbound payloads and log hashes, never plaintext."""

    PROHIBITED_KEYS = {
        "artifact_path",
        "barcodes",
        "cell_ids",
        "expression",
        "expression_matrix",
        "expression_values",
        "file_path",
        "full_path",
        "input_path",
        "matrix",
        "raw_matrix",
        "uploaded_context",
    }
    _ABSOLUTE_PATH = re.compile(r"(?<!\w)(?:/[A-Za-z0-9_. -]+){2,}")

    def __init__(self, *, audit_path: Path | None = None) -> None:
        self.audit_path = audit_path
        self._consents: dict[str, OutboundConsent] = {}

    def prepare(
        self,
        payload: dict[str, Any],
        *,
        purpose: str,
        provider: str,
    ) -> SanitizedOutboundPayload:
        removed: list[str] = []
        path_redactions = [0]
        sanitized = self._sanitize(
            payload,
            prefix="",
            removed=removed,
            path_redactions=path_redactions,
        )
        encoded = json.dumps(
            sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        disclosure = OutboundDisclosure(
            disclosure_id=f"disclosure-{uuid.uuid4().hex}",
            disclosure_hash=hashlib.sha256(encoded).hexdigest(),
            purpose=purpose,
            provider=provider,
            field_names=sorted(self._field_names(sanitized)),
            payload_bytes=len(encoded),
            prohibited_fields_removed=sorted(set(removed)),
            path_redactions=path_redactions[0],
            created_at=datetime.now(timezone.utc),
        )
        self._audit("outbound_disclosure_prepared", disclosure.model_dump(mode="json"))
        return SanitizedOutboundPayload(payload=sanitized, disclosure=disclosure)

    def grant(
        self,
        *,
        disclosure_hash: str,
        session_id: str,
        scope: Literal["once", "session"],
    ) -> OutboundConsent:
        consent = OutboundConsent(
            consent_id=f"outbound-consent-{uuid.uuid4().hex}",
            disclosure_hash=disclosure_hash,
            scope=scope,
            session_id=session_id,
            granted_at=datetime.now(timezone.utc),
        )
        self._consents[consent.consent_id] = consent
        self._audit(
            "outbound_consent_granted",
            consent.model_dump(mode="json"),
        )
        return consent

    def authorize(
        self,
        *,
        mode: PrivacyMode,
        disclosure_hash: str,
        session_id: str,
        consent_id: str | None,
    ) -> OutboundPolicyDecision:
        if mode == PrivacyMode.STRICT_OFFLINE:
            return OutboundPolicyDecision(
                allowed=False,
                mode=mode,
                reasons=["strict_offline_blocks_external_network"],
                disclosure_hash=disclosure_hash,
            )
        consent = self._consents.get(consent_id or "")
        reasons: list[str] = []
        if consent is None:
            reasons.append("outbound_consent_missing")
        else:
            if consent.session_id != session_id:
                reasons.append("outbound_consent_session_mismatch")
            if consent.disclosure_hash != disclosure_hash:
                reasons.append("outbound_disclosure_changed")
            if consent.scope == "once" and consent.consumed_at is not None:
                reasons.append("outbound_consent_consumed")
        allowed = not reasons
        if allowed and consent is not None and consent.scope == "once":
            consent = consent.model_copy(
                update={"consumed_at": datetime.now(timezone.utc)}
            )
            self._consents[consent.consent_id] = consent
            self._audit(
                "outbound_consent_consumed",
                consent.model_dump(mode="json"),
            )
        return OutboundPolicyDecision(
            allowed=allowed,
            mode=mode,
            reasons=reasons,
            disclosure_hash=disclosure_hash,
        )

    def _sanitize(
        self,
        value: Any,
        *,
        prefix: str,
        removed: list[str],
        path_redactions: list[int],
    ) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).casefold()
                field = f"{prefix}.{key}" if prefix else str(key)
                if normalized in self.PROHIBITED_KEYS:
                    removed.append(field)
                    continue
                result[str(key)] = self._sanitize(
                    item,
                    prefix=field,
                    removed=removed,
                    path_redactions=path_redactions,
                )
            return result
        if isinstance(value, (list, tuple)):
            return [
                self._sanitize(
                    item,
                    prefix=prefix,
                    removed=removed,
                    path_redactions=path_redactions,
                )
                for item in value[:100]
            ]
        if isinstance(value, str):
            redacted, count = self._ABSOLUTE_PATH.subn("[local-path-redacted]", value)
            path_redactions[0] += count
            return redacted[:12000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:1000]

    @staticmethod
    def _field_names(value: dict[str, Any]) -> set[str]:
        names: set[str] = set()

        def walk(item: Any, prefix: str = "") -> None:
            if isinstance(item, dict):
                for key, nested in item.items():
                    field = f"{prefix}.{key}" if prefix else str(key)
                    names.add(field)
                    walk(nested, field)
            elif isinstance(item, list):
                for nested in item[:5]:
                    walk(nested, prefix)

        walk(value)
        return names

    def _audit(self, event: str, model_payload: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        allowed = {
            "consent_id",
            "created_at",
            "disclosure_hash",
            "disclosure_id",
            "event",
            "field_names",
            "granted_at",
            "path_redactions",
            "payload_bytes",
            "prohibited_fields_removed",
            "provider",
            "purpose",
            "scope",
            "session_id",
            "consumed_at",
        }
        record = {"event": event}
        record.update({key: value for key, value in model_payload.items() if key in allowed})
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
