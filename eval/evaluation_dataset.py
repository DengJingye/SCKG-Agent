from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from core.evaluation_models import (
    EvaluationCase,
    EvaluationDatasetManifest,
    EvaluationSplit,
)
from core.settings import PROJECT_ROOT


DEFAULT_REGISTRY = PROJECT_ROOT / "eval" / "datasets" / "registry.json"


def canonical_query(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class EvaluationDatasetRegistry:
    def __init__(self, registry_path: Path = DEFAULT_REGISTRY) -> None:
        self.registry_path = registry_path

    def manifests(self) -> list[EvaluationDatasetManifest]:
        if not self.registry_path.is_file():
            return []
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return [EvaluationDatasetManifest.model_validate(row) for row in payload]

    def load_cases(
        self,
        manifest: EvaluationDatasetManifest,
        *,
        include_hidden: bool = False,
    ) -> list[EvaluationCase]:
        path = (PROJECT_ROOT / manifest.case_file).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if file_sha256(path) != manifest.case_digest:
            raise ValueError(f"dataset digest mismatch: {manifest.dataset_id}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        cases = [EvaluationCase.model_validate(row) for row in rows]
        if not include_hidden:
            cases = [case for case in cases if case.split != EvaluationSplit.HIDDEN]
        validate_cases(cases)
        return cases


def validate_cases(
    cases: Iterable[EvaluationCase], *, near_duplicate_threshold: float = 0.94
) -> None:
    rows = list(cases)
    ids = [case.case_id for case in rows]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate evaluation case IDs: {duplicates}")

    normalized: list[tuple[EvaluationCase, str]] = []
    for case in rows:
        query = str(case.input.get("query") or case.input.get("request") or "")
        key = canonical_query(query)
        if key:
            normalized.append((case, key))
    for index, (left, left_key) in enumerate(normalized):
        for right, right_key in normalized[index + 1 :]:
            if left.split == right.split:
                continue
            ratio = SequenceMatcher(None, left_key, right_key).ratio()
            if left_key == right_key or ratio >= near_duplicate_threshold:
                raise ValueError(
                    "near-duplicate query crosses evaluation splits: "
                    f"{left.case_id}/{right.case_id} ({ratio:.3f})"
                )


def audit_registry(registry: EvaluationDatasetRegistry) -> dict[str, object]:
    manifests = registry.manifests()
    errors: list[str] = []
    counts: dict[str, int] = {}
    seen_ids: set[str] = set()
    for manifest in manifests:
        try:
            cases = registry.load_cases(manifest, include_hidden=False)
            counts[manifest.dataset_id] = len(cases)
            overlap = sorted(seen_ids.intersection(case.case_id for case in cases))
            if overlap:
                errors.append(f"cross-dataset duplicate IDs: {overlap}")
            seen_ids.update(case.case_id for case in cases)
        except Exception as exc:
            errors.append(f"{manifest.dataset_id}: {type(exc).__name__}: {exc}")
    return {
        "manifest_count": len(manifests),
        "visible_case_counts": counts,
        "error_count": len(errors),
        "errors": errors,
        "passed": not errors,
    }
