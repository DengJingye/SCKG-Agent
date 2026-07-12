from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_TOOL_CATALOG = PROJECT_ROOT / "data" / "scrna_tools.tsv"
DEFAULT_EMBEDDINGS = PROJECT_ROOT / "data" / "scKG_embeddings_backup.jsonl"
DEFAULT_AUDIT_TSV = PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_vector_audit.tsv"
DEFAULT_SUMMARY_JSON = PROJECT_ROOT / "data" / "evidence_candidates" / "algorithm_vector_audit_summary.json"

PROFILE_FIELDS = [
    "description",
    "supported_tasks",
    "supported_modalities",
    "hardware_requirements",
    "biological_resolution",
    "algorithm_features",
]


def read_catalog(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_embeddings(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"tool_name": "", "parse_error": f"line {line_no}: invalid json"})
                continue
            rows.append(row)
    return rows


def build_audit_rows(
    catalog_rows: Sequence[Dict[str, str]],
    embedding_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    embeddings_by_name: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in embedding_rows:
        embeddings_by_name[normalize_name(row.get("tool_name", ""))].append(row)

    audit_rows: List[Dict[str, Any]] = []
    seen_names = set()
    for row in catalog_rows:
        tool_name = row.get("Tool", "")
        key = normalize_name(tool_name)
        seen_names.add(key)
        vectors = embeddings_by_name.get(key, [])
        best = vectors[0] if vectors else {}
        profile = best.get("llm_extracted_data") if isinstance(best.get("llm_extracted_data"), dict) else {}
        vector = best.get("embedding") if isinstance(best.get("embedding"), list) else []
        missing_profile = missing_profile_fields(profile)
        audit_rows.append(
            {
                "tool_name": tool_name,
                "catalog_status": "in_scrna_tools",
                "has_embedding": str(bool(vector)).lower(),
                "embedding_record_count": len(vectors),
                "embedding_dim": len(vector),
                "embedding_norm": round(vector_norm(vector), 6) if vector else "",
                "profile_completeness_score": profile_completeness_score(profile),
                "missing_profile_fields": ",".join(missing_profile),
                "profile_source_status": "llm_extracted_only" if profile else "missing_profile",
                "supported_tasks": join_list(profile.get("supported_tasks")),
                "supported_modalities": join_list(profile.get("supported_modalities")),
                "algorithm_features_chars": len(str(profile.get("algorithm_features", "") or "")),
                "github_url_catalog": row.get("Code", ""),
                "github_url_embedding": best.get("github_url", ""),
                "catalog_description_chars": len(str(row.get("Description", "") or "")),
                "vector_quality_flag": vector_quality_flag(vector, profile),
            }
        )

    for key, vectors in sorted(embeddings_by_name.items()):
        if key in seen_names or not key:
            continue
        best = vectors[0]
        profile = best.get("llm_extracted_data") if isinstance(best.get("llm_extracted_data"), dict) else {}
        vector = best.get("embedding") if isinstance(best.get("embedding"), list) else []
        audit_rows.append(
            {
                "tool_name": best.get("tool_name", ""),
                "catalog_status": "embedding_not_in_scrna_tools",
                "has_embedding": str(bool(vector)).lower(),
                "embedding_record_count": len(vectors),
                "embedding_dim": len(vector),
                "embedding_norm": round(vector_norm(vector), 6) if vector else "",
                "profile_completeness_score": profile_completeness_score(profile),
                "missing_profile_fields": ",".join(missing_profile_fields(profile)),
                "profile_source_status": "llm_extracted_only" if profile else "missing_profile",
                "supported_tasks": join_list(profile.get("supported_tasks")),
                "supported_modalities": join_list(profile.get("supported_modalities")),
                "algorithm_features_chars": len(str(profile.get("algorithm_features", "") or "")),
                "github_url_catalog": "",
                "github_url_embedding": best.get("github_url", ""),
                "catalog_description_chars": "",
                "vector_quality_flag": vector_quality_flag(vector, profile),
            }
        )
    return audit_rows


def build_summary(
    catalog_rows: Sequence[Dict[str, str]],
    embedding_rows: Sequence[Dict[str, Any]],
    audit_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    catalog_names = [normalize_name(row.get("Tool", "")) for row in catalog_rows if row.get("Tool")]
    embedding_names = [normalize_name(row.get("tool_name", "")) for row in embedding_rows if row.get("tool_name")]
    dims = [
        int(row["embedding_dim"])
        for row in audit_rows
        if str(row.get("has_embedding")) == "true" and str(row.get("embedding_dim", "")).isdigit()
    ]
    quality_counts = Counter(str(row.get("vector_quality_flag", "")) for row in audit_rows)
    catalog_audit = [row for row in audit_rows if row.get("catalog_status") == "in_scrna_tools"]
    with_embedding = [row for row in catalog_audit if row.get("has_embedding") == "true"]
    missing_embedding = [row for row in catalog_audit if row.get("has_embedding") != "true"]
    return {
        "tool_catalog_path": rel(DEFAULT_TOOL_CATALOG),
        "embedding_path": rel(DEFAULT_EMBEDDINGS),
        "catalog_rows": len(catalog_rows),
        "catalog_unique_tools": len(set(catalog_names)),
        "embedding_rows": len(embedding_rows),
        "embedding_unique_tools": len(set(embedding_names)),
        "catalog_tools_with_embedding": len(with_embedding),
        "catalog_tools_missing_embedding": len(missing_embedding),
        "catalog_embedding_coverage": round(len(with_embedding) / max(len(catalog_audit), 1), 4),
        "embedding_not_in_catalog": sum(1 for row in audit_rows if row.get("catalog_status") == "embedding_not_in_scrna_tools"),
        "duplicate_catalog_tool_names": duplicate_names(catalog_names),
        "duplicate_embedding_tool_names": duplicate_names(embedding_names),
        "embedding_dim_counts": dict(Counter(dims)),
        "embedding_dim_min": min(dims) if dims else 0,
        "embedding_dim_max": max(dims) if dims else 0,
        "embedding_norm_median": round(statistics.median(float(row["embedding_norm"]) for row in with_embedding if row.get("embedding_norm") != ""), 6)
        if with_embedding
        else 0,
        "vector_quality_flag_counts": dict(quality_counts),
        "risk_assessment": [
            "Current vectors are generated from LLM-extracted profiles, not directly from source-bound evidence spans.",
            "Use the current embedding space for candidate recall/exploration only, not as proof of migration validity.",
            "Rebuild Algorithm Representation v2 from source chunks + structured ontology + graph features before relying on migration similarity.",
        ],
    }


def missing_profile_fields(profile: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in PROFILE_FIELDS:
        value = profile.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def profile_completeness_score(profile: Dict[str, Any]) -> float:
    if not profile:
        return 0.0
    present = len(PROFILE_FIELDS) - len(missing_profile_fields(profile))
    return round(present / len(PROFILE_FIELDS), 4)


def vector_quality_flag(vector: Sequence[Any], profile: Dict[str, Any]) -> str:
    if not vector:
        return "missing_embedding"
    if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in vector):
        return "invalid_numeric_embedding"
    if vector_norm(vector) == 0:
        return "zero_vector"
    if len(vector) < 128:
        return "unexpected_low_dim"
    if profile_completeness_score(profile) < 0.67:
        return "weak_profile"
    return "llm_profile_embedding_review_required"


def vector_norm(vector: Sequence[Any]) -> float:
    try:
        return math.sqrt(sum(float(value) * float(value) for value in vector))
    except Exception:
        return 0.0


def duplicate_names(names: Iterable[str]) -> Dict[str, int]:
    counts = Counter(name for name in names if name)
    return {name: count for name, count in counts.items() if count > 1}


def write_tsv(rows: Sequence[Dict[str, Any]], path: Path) -> None:
    fields = [
        "tool_name",
        "catalog_status",
        "has_embedding",
        "embedding_record_count",
        "embedding_dim",
        "embedding_norm",
        "profile_completeness_score",
        "missing_profile_fields",
        "profile_source_status",
        "supported_tasks",
        "supported_modalities",
        "algorithm_features_chars",
        "github_url_catalog",
        "github_url_embedding",
        "catalog_description_chars",
        "vector_quality_flag",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def join_list(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return str(value or "")


def normalize_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the current tool algorithm embedding backup.")
    parser.add_argument("--tool-catalog", type=Path, default=DEFAULT_TOOL_CATALOG)
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--audit-tsv", type=Path, default=DEFAULT_AUDIT_TSV)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    args = parser.parse_args()

    catalog_rows = read_catalog(args.tool_catalog)
    embedding_rows = read_embeddings(args.embeddings)
    audit_rows = build_audit_rows(catalog_rows, embedding_rows)
    summary = build_summary(catalog_rows, embedding_rows, audit_rows)
    summary["tool_catalog_path"] = rel(args.tool_catalog)
    summary["embedding_path"] = rel(args.embeddings)
    summary["audit_tsv"] = rel(args.audit_tsv)

    write_tsv(audit_rows, args.audit_tsv)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
