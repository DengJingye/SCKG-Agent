"""DEV-only C7 loader.

Record IDs are extracted from raw JSONL bytes before JSON decoding. Records not
listed in DEV_CHECK are discarded without deserializing their payload.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_QUERY_ID = re.compile(br'"query_id"\s*:\s*"([^"]+)"')


@dataclass(frozen=True)
class DevOnlyLoadAudit:
    source_record_count: int
    decoded_dev_ids: tuple[str, ...]
    skipped_record_ids: tuple[str, ...]
    sealed_payload_accessed: bool = False
    decode_policy: str = "query_id_byte_filter_before_json_deserialization"


def load_dev_jsonl(
    path: Path,
    dev_ids: set[str],
    *,
    decoder: Callable[[str], Any] = json.loads,
) -> tuple[list[dict[str, Any]], DevOnlyLoadAudit]:
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    source_count = 0
    with Path(path).open("rb") as handle:
        for raw_record in handle:
            source_count += 1
            match = _QUERY_ID.search(raw_record)
            if match is None:
                raise ValueError("record_missing_query_id")
            query_id = match.group(1).decode("ascii")
            if query_id not in dev_ids:
                skipped.append(query_id)
                continue
            row = decoder(raw_record.decode("utf-8"))
            if row.get("query_id") != query_id:
                raise ValueError("query_id_changed_during_decode")
            rows.append(row)
    decoded_ids = tuple(row["query_id"] for row in rows)
    if set(decoded_ids) != dev_ids or len(decoded_ids) != len(dev_ids):
        raise ValueError("dev_id_coverage_mismatch")
    return rows, DevOnlyLoadAudit(
        source_record_count=source_count,
        decoded_dev_ids=decoded_ids,
        skipped_record_ids=tuple(skipped),
    )


def load_dev_pair(
    query_path: Path,
    gold_path: Path,
    split_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    split = json.loads(Path(split_path).read_text())
    dev_ids = set(split["DEV_CHECK"])
    queries, query_audit = load_dev_jsonl(query_path, dev_ids)
    gold, gold_audit = load_dev_jsonl(gold_path, dev_ids)
    return queries, gold, {
        "query": query_audit.__dict__,
        "gold": gold_audit.__dict__,
        "sealed_payload_accessed": False,
        "quarantine": {
            query_id: "QUARANTINED_AFTER_DISCLOSURE"
            for query_id in split["SEALED"]
        },
    }
