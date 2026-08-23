from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.request import Request, urlopen


CATALOG_URL = "https://www.scrna-tools.org/data/tools.json"
CATALOG_SCHEMA_VERSION = "scrna-tools-catalog-v1"
COMPATIBILITY_FIELDS = [
    "Tool",
    "Platform",
    "Code",
    "Description",
    "License",
    "Added",
    "Updated",
]
REQUIRED_FIELDS = {"Tool", "Platform", "Description", "Added", "Updated", "Categories"}


def fetch_catalog(url: str = CATALOG_URL, *, timeout: int = 30) -> tuple[List[Dict[str, Any]], str]:
    request = Request(url, headers={"User-Agent": "scKG-Agent/catalog-sync-v1"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return parse_catalog_payload(payload), hashlib.sha256(payload).hexdigest()


def load_catalog(path: Path) -> tuple[List[Dict[str, Any]], str]:
    payload = Path(path).read_bytes()
    return parse_catalog_payload(payload), hashlib.sha256(payload).hexdigest()


def parse_catalog_payload(payload: bytes) -> List[Dict[str, Any]]:
    value = json.loads(payload.decode("utf-8-sig"))
    if isinstance(value, dict):
        value = value.get("tools")
    if not isinstance(value, list):
        raise ValueError("scRNA-tools catalog must be a JSON list or a snapshot with a tools list")
    rows = [_normalize_row(row) for row in value]
    validate_catalog(rows)
    return sorted(rows, key=lambda row: row["Tool"].casefold())


def validate_catalog(rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("scRNA-tools catalog is empty")
    names: List[str] = []
    for index, row in enumerate(rows):
        missing = sorted(field for field in REQUIRED_FIELDS if field not in row)
        if missing:
            raise ValueError(f"catalog row {index} is missing fields: {', '.join(missing)}")
        name = str(row.get("Tool") or "").strip()
        if not name:
            raise ValueError(f"catalog row {index} has an empty Tool name")
        if not isinstance(row.get("Categories"), list) or not row["Categories"]:
            raise ValueError(f"catalog tool {name} has no category")
        for field in ("Publications", "Preprints"):
            if not isinstance(row.get(field), list):
                raise ValueError(f"catalog tool {name} has invalid {field}")
        names.append(name)
    duplicates = sorted(name for name, count in _counts(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate catalog tools: {', '.join(duplicates[:10])}")


def build_catalog_audit(
    rows: Sequence[Dict[str, Any]],
    *,
    current_tsv: Path,
    source_sha256: str,
    source_url: str = CATALOG_URL,
) -> Dict[str, Any]:
    current = read_compatibility_tsv(current_tsv)
    current_by_name = {row.get("Tool", "").strip(): row for row in current if row.get("Tool")}
    source_by_name = {str(row["Tool"]): row for row in rows}
    current_names = set(current_by_name)
    source_names = set(source_by_name)
    changed_fields: Dict[str, List[str]] = {field: [] for field in COMPATIBILITY_FIELDS[1:]}
    for name in sorted(current_names & source_names):
        for field in COMPATIBILITY_FIELDS[1:]:
            current_value = _compat_value(current_by_name[name].get(field))
            source_value = _compat_value(source_by_name[name].get(field))
            if current_value != source_value:
                changed_fields[field].append(name)
    references = [
        ("publication", reference)
        for row in rows
        for reference in row.get("Publications", [])
    ] + [
        ("preprint", reference)
        for row in rows
        for reference in row.get("Preprints", [])
    ]
    schema_keys = sorted({key for row in rows for key in row})
    live_only = sorted(source_names - current_names)
    local_only = sorted(current_names - source_names)
    changed_count = sum(len(names) for names in changed_fields.values())
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "source_sha256": source_sha256,
        "catalog_alignment_status": (
            "aligned" if not live_only and not local_only and changed_count == 0 else "drift_detected"
        ),
        "source_tool_count": len(rows),
        "local_tool_count": len(current),
        "shared_tool_count": len(source_names & current_names),
        "source_only_tools": live_only,
        "local_only_tools": local_only,
        "changed_compatibility_fields": {
            field: names for field, names in changed_fields.items() if names
        },
        "category_count": len({category for row in rows for category in row["Categories"]}),
        "publication_count": sum(len(row["Publications"]) for row in rows),
        "preprint_count": sum(len(row["Preprints"]) for row in rows),
        "unique_reference_count": len(
            {
                _reference_key(reference)
                for _, reference in references
                if _reference_key(reference)
            }
        ),
        "tools_with_publication_or_preprint": sum(
            bool(row["Publications"] or row["Preprints"]) for row in rows
        ),
        "tools_with_code_url": sum(_is_present(row.get("Code")) for row in rows),
        "tools_with_github": sum(bool(row.get("GitHub")) for row in rows),
        "schema_keys": schema_keys,
        "scope_boundary": (
            "Complete metadata snapshot of the upstream catalog at fetch time; "
            "not full-text evidence and not proof of scientific capability."
        ),
    }


def write_catalog_snapshot(
    rows: Sequence[Dict[str, Any]],
    *,
    snapshot_path: Path,
    compatibility_tsv: Path,
    audit_path: Path,
    source_sha256: str,
    source_url: str = CATALOG_URL,
) -> Dict[str, Any]:
    previous_audit: Dict[str, Any] = {}
    if audit_path.is_file():
        try:
            value = json.loads(audit_path.read_text(encoding="utf-8"))
            previous_audit = value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            previous_audit = {}
    audit = build_catalog_audit(
        rows,
        current_tsv=compatibility_tsv,
        source_sha256=source_sha256,
        source_url=source_url,
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    compatibility_tsv.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_sha256,
        "tool_count": len(rows),
        "tools": list(rows),
    }
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with compatibility_tsv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPATIBILITY_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _compat_value(row.get(field)) for field in COMPATIBILITY_FIELDS})
    post_apply = build_catalog_audit(
        rows,
        current_tsv=compatibility_tsv,
        source_sha256=source_sha256,
        source_url=source_url,
    )
    pre_apply_drift = {
        "source_only_tools": audit["source_only_tools"],
        "local_only_tools": audit["local_only_tools"],
        "changed_compatibility_fields": audit["changed_compatibility_fields"],
    }
    if not any(pre_apply_drift.values()) and isinstance(previous_audit.get("pre_apply_drift"), dict):
        pre_apply_drift = previous_audit["pre_apply_drift"]
    post_apply["pre_apply_drift"] = pre_apply_drift
    audit_path.write_text(json.dumps(post_apply, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return post_apply


def read_catalog_snapshot(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows, _ = load_catalog(path)
    return rows


def read_compatibility_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _normalize_row(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("catalog rows must be JSON objects")
    row = dict(value)
    for field in COMPATIBILITY_FIELDS:
        row[field] = _compat_value(row.get(field))
    row["Categories"] = _string_list(row.get("Categories"))
    row["Publications"] = _reference_list(row.get("Publications"))
    row["Preprints"] = _reference_list(row.get("Preprints"))
    for field in ("GitHub", "Bioc", "CRAN", "PyPI"):
        if field in row:
            row[field] = str(row[field] or "").strip()
            if not row[field]:
                row.pop(field, None)
    row["Citations"] = _integer(row.get("Citations"))
    row["NumPubs"] = len(row["Publications"])
    row["NumPreprints"] = len(row["Preprints"])
    return row


def _reference_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    references: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        reference = {
            "Title": str(item.get("Title") or "").strip(),
            "DOI": str(item.get("DOI") or "").strip(),
            "Citations": _integer(item.get("Citations")),
        }
        if item.get("Date"):
            reference["Date"] = str(item["Date"]).strip()
        if reference["Title"] or reference["DOI"]:
            references.append(reference)
    return references


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _compat_value(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text or "NA"


def _reference_key(reference: Dict[str, Any]) -> str:
    return str(reference.get("DOI") or reference.get("Title") or "").strip().casefold()


def _integer(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _is_present(value: Any) -> bool:
    return str(value or "").strip().casefold() not in {"", "na", "n/a", "none", "null"}


def _counts(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
