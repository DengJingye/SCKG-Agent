"""Read-only dashboard projections. Never import a builder, retriever or scorer."""
from __future__ import annotations

import ast
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UNKNOWN = "UNKNOWN"
NOT_MEASURED = "NOT_MEASURED"
LEGACY_BOUNDARY = "历史工具/来源匹配工程回归，非当前科学证据问答准确率"


def read_artifact(path: Path, kind: str = "json", required_columns: tuple = ()) -> tuple[Any, dict]:
    """Missing/unreadable is not an empty dataset; mtime is not generation time."""
    info = {"file": str(path.resolve()), "generated_at": UNKNOWN, "build_id": UNKNOWN,
            "run_id": UNKNOWN, "mtime_utc": UNKNOWN, "sha256": UNKNOWN,
            "status": UNKNOWN, "freshness": UNKNOWN}
    try:
        raw = path.read_bytes()
        info.update(sha256=hashlib.sha256(raw).hexdigest(),
                    mtime_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
        text = raw.decode("utf-8-sig")
        if kind == "jsonl":
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
            if not all(isinstance(row, dict) for row in data):
                raise ValueError("JSONL rows must be objects")
        elif kind == "tsv":
            reader = csv.DictReader(text.splitlines(), delimiter="\t")
            if not reader.fieldnames or not set(required_columns).issubset(reader.fieldnames):
                raise ValueError(f"Missing TSV columns: {required_columns}")
            data = list(reader)
        elif kind == "text":
            data = text
        else:
            data = json.loads(text)
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected JSON object or array")
        info["status"] = "READABLE"
        if isinstance(data, dict):
            for field in ("build_id", "run_id"):
                info[field] = data.get(field) or UNKNOWN
            info["generated_at"] = next((data[k] for k in ("generated_at", "completed_at", "created_at") if data.get(k)), UNKNOWN)
        if info["generated_at"] != UNKNOWN:
            try:
                date = datetime.fromisoformat(info["generated_at"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - date).days
                info["freshness"] = "STALE (>30 days)" if age > 30 else "RECORDED (not a live measurement)"
            except (ValueError, TypeError):
                info["freshness"] = "UNKNOWN (invalid timestamp)"
        return data, info
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        info["status"] = f"UNKNOWN: {type(exc).__name__}: {exc}"
        return None, info


def field_value(field: str, value: Any) -> str:
    """Display-only interpretation; never convert an absent check into PASS."""
    if value is not None and str(value).strip().lower() not in {"", "none", "null"}:
        return str(value)
    if field == "notes":
        return "无备注"
    if field in {"validation_issue", "candidate_issue", "quality_flags", "failure_reason"}:
        return "无登记问题（不代表校验通过）"
    if field in {"action", "recommended_action"}:
        return "无需处理（登记为 none；不代表通过）" if isinstance(value, str) and value.strip().lower() == "none" else "UNKNOWN · 未登记动作，是否需处理未知"
    if field in {"validation_status", "review_status", "check_status"}:
        return f"{NOT_MEASURED} · 未登记校验结果"
    if field in {"local_text_path", "pdf_path", "local_pdf_path"}:
        return f"{UNKNOWN} · 未登记文件"
    return UNKNOWN


def display_rows(rows: list[dict]) -> list[dict]:
    return [{key: field_value(key, value) for key, value in row.items()} for row in rows]


class EvidenceDashboardData:
    def __init__(self, root: Path, data_dir: Path | None = None):
        self.root = Path(root).resolve()
        self.data_dir = Path(data_dir).resolve() if data_dir else self.root / "data"

    def snapshots(self) -> dict[str, Path]:
        base = self.data_dir / "indexes"
        # Include default even when absent so absence stays visible.
        result = {"indexes (default artifacts)": base}
        for path in sorted(base.glob("*/evidence_index_manifest.json")):
            result[path.parent.name] = path.parent
        return result

    def cohorts(self) -> tuple[dict, dict]:
        path = self.root / "engine/source_corpus_v2.py"
        source, info = read_artifact(path, "text")
        groups = {}
        if source is not None:
            try:
                for node in ast.parse(source).body:
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id in {"CORE_TOOLS", "QUALIFIED_TOOLS"}:
                                values = ast.literal_eval(node.value)
                                if not isinstance(values, (tuple, list)) or not all(isinstance(v, str) for v in values):
                                    raise ValueError("Invalid tool cohort")
                                groups[target.id] = list(values)
            except (ValueError, SyntaxError, TypeError) as exc:
                info["status"] = f"UNKNOWN: {exc}"
                groups = {}
        return groups, info

    def snapshot(self, directory: Path) -> dict:
        directory = Path(directory)
        provenance, errors = [], []
        def read(name, kind="json"):
            value, info = read_artifact(directory / name, kind)
            provenance.append(info)
            if value is None:
                errors.append(info["status"])
            return value
        manifest = read("evidence_index_manifest.json")
        chunks = read("evidence_chunks.jsonl", "jsonl")
        metadata = read("evidence_vector_metadata.json")
        manifest = manifest if isinstance(manifest, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        chunk_map = None
        if chunks is not None:
            ids = [row.get("chunk_id") for row in chunks]
            if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
                errors.append("Invalid or duplicate chunk_id in selected snapshot")
            else:
                chunk_map = dict(zip(ids, chunks))
        # Declared hashes bind the files to a build when available.
        integrity_failed = False
        artifacts = manifest.get("artifacts") or {}
        for info in provenance:
            expected = artifacts.get(Path(info["file"]).name)
            if expected and expected != info["sha256"]:
                errors.append(f"Snapshot hash mismatch: {info['file']}")
                integrity_failed = True
        if chunk_map is not None and manifest.get("evidence_chunk_count") not in (None, len(chunk_map)):
            errors.append("Manifest evidence_chunk_count differs from selected chunks")
            integrity_failed = True
        if chunk_map is not None and any(row.get("content_hash") and row["content_hash"] != hashlib.sha256(str(row.get("chunk_text", "")).encode()).hexdigest() for row in chunk_map.values()):
            errors.append("Chunk text differs from recorded content_hash")
            integrity_failed = True
        if chunk_map is not None and manifest.get("chunk_digest"):
            payload = "\n".join(f"{cid}:{row.get('content_hash') or hashlib.sha256(str(row.get('chunk_text', '')).encode()).hexdigest()}" for cid, row in chunk_map.items())
            if hashlib.sha256(payload.encode()).hexdigest() != manifest["chunk_digest"]:
                errors.append("Manifest chunk_digest differs from selected chunks")
                integrity_failed = True
        if integrity_failed:
            chunk_map = None
        vector_ids = metadata.get("chunk_ids")
        vector_valid = isinstance(vector_ids, list) and all(isinstance(v, str) and v for v in vector_ids)
        if not vector_valid:
            errors.append("metadata.chunk_ids missing or malformed; vectors NOT_MEASURED")
        elif len(vector_ids) != len(set(vector_ids)):
            vector_valid = False
            errors.append("Duplicate vector chunk IDs")
        if vector_valid and (chunk_map is None or set(vector_ids) - set(chunk_map)):
            unresolved = sorted(set(vector_ids) - set(chunk_map or {}))
            errors.append(f"Vector IDs cannot resolve in selected chunks: {unresolved[:8]}")
            vector_valid = False
        shape = metadata.get("shape")
        if not isinstance(shape, list) or len(shape) != 2 or not vector_valid or shape[0] != len(vector_ids):
            errors.append("Vector metadata shape/ID count unavailable or inconsistent")
            vector_valid = False
        if not manifest.get("build_id") or not metadata.get("build_id"):
            errors.append("Build identity missing; vector snapshot association UNKNOWN")
            vector_valid = False
        elif metadata["build_id"] != manifest["build_id"]:
            errors.append("Vector build_id differs from selected snapshot")
            vector_valid = False
        matrix_path = directory / "evidence_vectors.npy"
        matrix_info = {"file": str(matrix_path.resolve()), "generated_at": UNKNOWN,
                       "build_id": UNKNOWN, "run_id": UNKNOWN, "mtime_utc": UNKNOWN,
                       "sha256": UNKNOWN, "status": UNKNOWN, "freshness": UNKNOWN}
        try:
            import numpy as np
            matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
            if not isinstance(shape, list) or list(matrix.shape) != shape:
                raise ValueError(f"Matrix shape {matrix.shape} differs from metadata {shape}")
            del matrix
            matrix_info.update(status="READABLE · shape verified",
                               sha256=hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
                               mtime_utc=datetime.fromtimestamp(matrix_path.stat().st_mtime, timezone.utc).isoformat())
            if artifacts.get(matrix_path.name) and artifacts[matrix_path.name] != matrix_info["sha256"]:
                raise ValueError("Matrix artifact hash mismatch")
        except (OSError, ValueError, ImportError) as exc:
            vector_valid = False
            matrix_info["status"] = f"UNKNOWN: {exc}"
            errors.append(matrix_info["status"])
        provenance.append(matrix_info)
        groups, group_info = self.cohorts()
        provenance.append(group_info)
        associations, available, names = {}, {}, {}
        associations_known = chunk_map is not None
        source_known = chunk_map is not None
        for cid, row in (chunk_map or {}).items():
            tool_names = row.get("tool_names")
            if not isinstance(tool_names, list):
                tool_names = [row["tool_name"]] if row.get("tool_name") else None
            if not tool_names or not all(isinstance(t, str) and t for t in tool_names):
                associations_known = False
                source_known = False
                continue
            # Explicit source association and nonempty text; no quality/qualification claim.
            bound = row.get("source_bound")
            if bound not in (True, False, "true", "false"):
                source_known = False
            usable = bound in (True, "true") and bool(str(row.get("chunk_text") or "").strip()) and bool(row.get("source_id")) and row.get("retrieval_status") != "catalog_only"
            for tool in set(tool_names):
                key = tool.casefold()
                names[key] = tool
                associations.setdefault(key, set()).add(cid)
                if usable:
                    available.setdefault(key, set()).add(cid)
        if not associations_known:
            errors.append("Chunk tool association missing; per-tool counts UNKNOWN")
        if not source_known:
            errors.append("Chunk source association missing; coverage UNKNOWN")
        for values in groups.values():
            names.update({name.casefold(): name for name in values})
        rows = []
        for key in sorted(names):
            rows.append({"tool": names[key],
                         "source_chunk_count": len(available.get(key, set())) if source_known else UNKNOWN,
                         "vector_count": len(associations.get(key, set()) & set(vector_ids)) if vector_valid and associations_known else UNKNOWN,
                         "source_association": ("有可用来源关联" if available.get(key) else "无可用来源关联") if source_known else UNKNOWN,
                         "core_reference_cohort": names[key].casefold() in {v.casefold() for v in groups.get("CORE_TOOLS", [])},
                         "legacy_qualified_cohort": names[key].casefold() in {v.casefold() for v in groups.get("QUALIFIED_TOOLS", [])}})
        coverage = {}
        for group in ("CORE_TOOLS", "QUALIFIED_TOOLS"):
            members = groups.get(group)
            coverage[group] = (f"{sum(bool(available.get(t.casefold())) for t in members)}/{len(members)}"
                               if members and source_known else UNKNOWN)
        return {"directory": str(directory), "build_id": manifest.get("build_id") or UNKNOWN,
                "chunk_count": len(chunk_map) if chunk_map is not None else UNKNOWN,
                "vector_count": len(vector_ids) if vector_valid else UNKNOWN,
                "vector_id_status": "RESOLVED · matrix shape verified" if vector_valid else UNKNOWN,
                "coverage": coverage, "cohorts": groups, "rows": rows,
                "provenance": provenance, "errors": errors}

    def campaigns(self) -> dict[str, Path]:
        result = {"retrieval_eval_v2 · HISTORICAL": self.data_dir / "evaluation/retrieval_eval_v2/summary.json"}
        for path in sorted((self.root / "eval_v2").glob("*retrieval*dev/report.json")):
            result[f"{path.parent.name} · DEVELOPMENT"] = path
        return result

    def campaign(self, path: Path) -> dict:
        report, info = read_artifact(path)
        report = report if isinstance(report, dict) else {}
        legacy = path.parent.name == "retrieval_eval_v2"
        provenance = [info]
        for name in ("pre_run_manifest.json", "manifest.json", "run_started.json", "run_completed.json"):
            if (path.parent / name).exists():
                _, entry = read_artifact(path.parent / name)
                provenance.append(entry)
        invalidation = None
        invalidation_path = self.root / "docs/status" / f"{path.parent.name.upper()}_INVALIDATION.md"
        if invalidation_path.exists():
            invalidation, entry = read_artifact(invalidation_path, "text")
            provenance.append(entry)
        return {"invalidation": invalidation, "kind": "HISTORICAL" if legacy else "DEVELOPMENT", "legacy": legacy,
                "boundary": LEGACY_BOUNDARY if legacy else "开发实验存档；仅适用其固定数据、划分、gold、scorer 和索引，不代表当前所选快照的测量。",
                "report": report, "provenance": provenance}

    def source_audit(self) -> dict:
        base = self.data_dir / "evidence_candidates"
        definitions = {"registry": ("source_registry.tsv", "tsv"),
                       "validation": ("source_validation_report.tsv", "tsv"),
                       "candidates": ("pdf_candidate_registry.tsv", "tsv"),
                       "literature": ("core_literature_source_coverage.tsv", "tsv"),
                       "acquisition": ("source_acquisition_summary.json", "json"),
                       "extraction": ("source_extraction_summary.json", "json"),
                       "quarantine": ("source_quarantine_v2.json", "json")}
        data, provenance = {}, []
        for key, (name, kind) in definitions.items():
            required = ("source_id", "source_status") if key == "registry" else ()
            data[key], info = read_artifact(base / name, kind, required_columns=required)
            provenance.append(info)
        rows = data["registry"]
        valid = rows is not None and all(row.get("source_id") for row in rows) and len({row["source_id"] for row in rows}) == len(rows)
        counts = Counter((row.get("source_status") or UNKNOWN) for row in rows) if valid else None
        # No fallback to summaries: registered source-level rows are the denominator.
        errors = []
        if not valid:
            errors.append("Source registry missing/unreadable/duplicate source IDs; counts UNKNOWN")
        for key in ("acquisition", "extraction"):
            summary = data[key] if isinstance(data[key], dict) else {}
            if valid and summary.get("source_records") not in (None, len(rows)):
                errors.append(f"{key} source_records differs from registry; artifacts may be from different runs")
            for status, value in counts.items() if counts is not None else []:
                recorded = summary.get("source_status_counts", {}).get(status) if key == "acquisition" else summary.get(status)
                if recorded is not None and recorded != value:
                    errors.append(f"{key}.{status} differs from registry")
        quarantine = data["quarantine"]
        data.update(total=len(rows) if valid else UNKNOWN, counts=dict(counts) if counts is not None else None,
                    quarantine_source_groups=len(quarantine["records"]) if isinstance(quarantine, dict) and isinstance(quarantine.get("records"), list) else UNKNOWN,
                    provenance=provenance, errors=errors)
        return data
