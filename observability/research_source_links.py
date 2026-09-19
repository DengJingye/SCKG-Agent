"""Presentation-only links resolved by exact persisted source identity.

This does not assess support, alter answers, or promote source authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit


def source_links(references: list[dict], source_manifest: Path) -> list[dict]:
    wanted = {ref.get("source_id") for ref in references if ref.get("source_id")}
    if not wanted or not source_manifest.is_file():
        return []
    sources = {}
    ambiguous = set()
    try:
        for line in source_manifest.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            identity = row.get("source_id")
            if identity not in wanted:
                continue
            if identity in sources and sources[identity] != row:
                ambiguous.add(identity)
            sources[identity] = row
    except (OSError, ValueError):
        return []
    result = []
    for ref in references:
        identity = ref.get("source_id")
        row = sources.get(identity)
        if not row or identity in ambiguous:
            continue
        url = str(row.get("source_url") or "")
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or any(ord(c) < 32 for c in url)):
            continue
        result.append({"index": ref.get("index"), "source_id": identity,
                       "title": row.get("canonical_title") or identity,
                       "url": url, "locator": ref.get("source_span") or ""})
    return result
