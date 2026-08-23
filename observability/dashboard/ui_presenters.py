from __future__ import annotations

import re
from typing import Any


HEX_ID = re.compile(r"^[a-f0-9]{12,64}$", re.IGNORECASE)
UUID_ID = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)


def format_conversation_title(title: Any, session_id: str, *, limit: int = 34) -> str:
    clean = " ".join(str(title or "").split())
    session_id = str(session_id or "")
    if not clean or clean == session_id or HEX_ID.fullmatch(clean) or UUID_ID.fullmatch(clean):
        suffix = session_id[:8] if session_id else "untitled"
        clean = f"Chat {suffix}"
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def normalize_ui_status(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"ready", "allowed", "dry_run", "passed", "valid"}:
        return "READY"
    if normalized in {"queued", "running", "cancel_requested"}:
        return "RUNNING"
    if normalized in {"complete", "completed", "succeeded", "success"}:
        return "COMPLETED"
    if normalized in {"stale", "outdated", "invalidated"}:
        return "STALE"
    if normalized in {"blocked", "denied", "revoked", "expired"}:
        return "BLOCKED"
    if normalized in {"failed", "failure", "error", "cancelled", "timeout"}:
        return "FAILED"
    return "WAITING"
