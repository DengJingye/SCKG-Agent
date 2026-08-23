from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from core.settings import get_settings
from core.user_store import (
    DEFAULT_STORE_PATH,
    ApiConfigError,
    has_saved_api_config,
    load_api_config,
)


PASSPHRASE_ENV = "SCKG_API_CONFIG_PASSPHRASE"


@dataclass(frozen=True)
class LiveLlmRuntimeResolution:
    status: str
    reason: str
    runtime_config: dict[str, Any]
    safe_metadata: dict[str, Any]


def resolve_live_llm_runtime(
    *,
    passphrase: str | None = None,
    db_path: Path = DEFAULT_STORE_PATH,
    credential_source: Literal["auto", "encrypted", "environment"] = "auto",
) -> LiveLlmRuntimeResolution:
    """Resolve credentials without ever returning them in serializable metadata."""

    if credential_source not in {"auto", "encrypted", "environment"}:
        raise ValueError("credential_source must be auto, encrypted, or environment")

    config: dict[str, Any] = {}
    source = ""
    saved_config_exists = has_saved_api_config(db_path=db_path)
    use_encrypted = credential_source == "encrypted" or (
        credential_source == "auto" and saved_config_exists
    )
    if use_encrypted:
        if not saved_config_exists:
            return _blocked(
                "encrypted_api_config_missing",
                source="encrypted_local_store",
            )
        secret = passphrase if passphrase is not None else os.getenv(PASSPHRASE_ENV, "")
        if not secret:
            return _blocked("encrypted_api_config_locked", source="encrypted_local_store")
        try:
            config = load_api_config(secret, db_path=db_path)
        except ApiConfigError as exc:
            return _blocked(
                "encrypted_api_config_unlock_failed",
                source="encrypted_local_store",
                detail=type(exc).__name__,
            )
        source = "encrypted_local_store"
    else:
        settings = get_settings()
        api_key = settings.deepseek_api_key or settings.openai_api_key
        if api_key:
            config = {
                "provider": "openai_compatible",
                "api_base": settings.openai_api_base or settings.chat_api_base,
                "api_key": api_key.get_secret_value(),
                "model_name": settings.model_name or settings.extract_model,
            }
            source = "environment"

    api_base = str(config.get("api_base") or "").strip()
    model_name = str(config.get("model_name") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    if not api_key or not api_base or not model_name:
        return _blocked("llm_credentials_not_configured", source=source or "none")
    parsed = urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _blocked("llm_api_base_invalid", source=source or "unknown")

    runtime_config = {
        **config,
        "privacy_authorized": True,
        "outbound_authorized": True,
        "privacy_mode": "cloud_assisted",
    }
    return LiveLlmRuntimeResolution(
        status="ready",
        reason="",
        runtime_config=runtime_config,
        safe_metadata={
            "credential_source": source,
            "provider": str(config.get("provider") or "openai_compatible"),
            "api_host": parsed.netloc,
            "model_name": model_name,
            "api_key_present": True,
        },
    )


def _blocked(reason: str, *, source: str, detail: str = "") -> LiveLlmRuntimeResolution:
    return LiveLlmRuntimeResolution(
        status="blocked",
        reason=reason,
        runtime_config={},
        safe_metadata={
            "credential_source": source,
            "api_key_present": False,
            "detail": detail,
        },
    )
