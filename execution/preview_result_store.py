from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from core.research_workspace_models import (
    PreviewResultIntegrity,
    PreviewRunResult,
    PreviewRunSummary,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class PreviewResultStore:
    """Owner-scoped durable result index for representative Preview runs."""

    def __init__(self, *, workspace_root: Path, execution_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.execution_root = Path(execution_root).resolve()

    def save(self, result: PreviewRunResult) -> Path:
        result_dir = self._result_dir(
            result.user_id, result.artifact_id, result.execution_run.run_id
        )
        result_dir.mkdir(parents=True, exist_ok=False)
        result_path = result_dir / "preview_run_result.json"
        payload = (result.model_dump_json(indent=2) + "\n").encode("utf-8")
        temp_path = result_dir / ".preview_run_result.json.tmp"
        temp_path.write_bytes(payload)
        os.replace(temp_path, result_path)
        (result_dir / "preview_run_result.sha256").write_text(
            hashlib.sha256(payload).hexdigest() + "\n", encoding="ascii"
        )
        return result_path

    def list_results(
        self, *, user_id: str, artifact_id: str | None = None
    ) -> list[PreviewRunSummary]:
        self._validate_id(user_id)
        if artifact_id is not None:
            self._validate_id(artifact_id)
            roots = [
                self.workspace_root / user_id / "artifacts" / artifact_id / "preview-runs"
            ]
        else:
            roots = list(
                (self.workspace_root / user_id / "artifacts").glob("*/preview-runs")
            )
        summaries: list[PreviewRunSummary] = []
        for root in roots:
            if not root.is_dir():
                continue
            for result_path in root.glob("*/preview_run_result.json"):
                if self._is_owned_result_path(user_id, result_path):
                    summaries.append(self._summary_from_path(user_id, result_path))
        return sorted(summaries, key=lambda item: item.completed_at, reverse=True)

    def load_result(
        self, *, user_id: str, artifact_id: str, run_id: str
    ) -> PreviewRunResult:
        result_path = self._result_path(user_id, artifact_id, run_id)
        if not result_path.is_file():
            raise FileNotFoundError("owned preview result is missing")
        if not self._result_digest_valid(result_path):
            raise PermissionError("result_record_integrity_failed")
        result = PreviewRunResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        self._require_lineage(
            result,
            user_id=user_id,
            artifact_id=artifact_id,
            run_id=run_id,
        )
        return result

    def inspect_integrity(self, result: PreviewRunResult) -> PreviewResultIntegrity:
        result_path = self._result_path(
            result.user_id, result.artifact_id, result.execution_run.run_id
        )
        result_digest_valid = self._result_digest_valid(result_path)
        run_root = (
            self.execution_root
            / result.user_id
            / "runs"
            / result.execution_run.run_id
        ).resolve()
        missing: list[str] = []
        mismatches: list[str] = []
        escaped: list[str] = []
        for name, path_text in result.execution_run.artifact_paths.items():
            path = Path(path_text).resolve()
            try:
                path.relative_to(run_root)
            except ValueError:
                escaped.append(name)
                continue
            if not path.is_file():
                missing.append(name)
                continue
            expected_hash = result.execution_run.artifact_hashes.get(name)
            if not expected_hash or _sha256(path) != expected_hash:
                mismatches.append(name)
        issues: list[str] = []
        if not result_digest_valid:
            issues.append("result_record_digest_invalid")
        if escaped:
            issues.append("artifact_path_escape")
        if missing:
            issues.append("artifact_missing")
        if mismatches:
            issues.append("artifact_hash_mismatch")
        hashes_valid = not missing and not mismatches
        paths_owned = not escaped
        return PreviewResultIntegrity(
            passed=result_digest_valid and hashes_valid and paths_owned,
            result_digest_valid=result_digest_valid,
            artifact_paths_owned=paths_owned,
            artifact_hashes_valid=hashes_valid,
            missing_artifacts=sorted(missing),
            hash_mismatches=sorted(mismatches),
            escaped_artifacts=sorted(escaped),
            issues=issues,
        )

    def resolve_artifact(
        self,
        *,
        user_id: str,
        artifact_id: str,
        run_id: str,
        artifact_name: str,
    ) -> Path:
        result = self.load_result(
            user_id=user_id, artifact_id=artifact_id, run_id=run_id
        )
        integrity = self.inspect_integrity(result)
        if not integrity.passed:
            raise PermissionError("artifact_integrity_failed")
        path_text = result.execution_run.artifact_paths.get(artifact_name)
        if not path_text:
            raise FileNotFoundError("preview result artifact is missing")
        return Path(path_text).resolve()

    def _summary_from_path(self, user_id: str, result_path: Path) -> PreviewRunSummary:
        artifact_id = result_path.parents[2].name
        run_id = result_path.parent.name
        self._validate_id(artifact_id)
        self._validate_id(run_id)
        try:
            result = PreviewRunResult.model_validate_json(
                result_path.read_text(encoding="utf-8")
            )
            self._require_lineage(
                result,
                user_id=user_id,
                artifact_id=artifact_id,
                run_id=run_id,
            )
            integrity = self.inspect_integrity(result)
            status = _ui_status(result, integrity)
            failures = sorted(
                set(result.validation_result.failures + integrity.issues)
            )
            return PreviewRunSummary(
                user_id=user_id,
                artifact_id=artifact_id,
                run_id=run_id,
                preview_id=result.preview_id,
                notebook_id=result.notebook_id,
                tool_name=result.execution_run.tool_name,
                tool_version=result.execution_run.tool_version,
                status=status,
                validation_passed=result.validation_result.passed,
                runtime_seconds=result.execution_run.runtime_seconds,
                peak_memory_mb=result.execution_run.peak_memory_mb,
                artifact_count=len(result.execution_run.artifact_paths),
                integrity=integrity,
                failures=failures,
                warnings=result.validation_result.warnings,
                completed_at=result.execution_run.end_time,
            )
        except (OSError, ValueError, PermissionError):
            from datetime import datetime, timezone

            integrity = PreviewResultIntegrity(
                passed=False,
                result_digest_valid=self._result_digest_valid(result_path),
                artifact_paths_owned=False,
                artifact_hashes_valid=False,
                issues=["result_record_invalid"],
            )
            return PreviewRunSummary(
                user_id=user_id,
                artifact_id=artifact_id,
                run_id=run_id,
                preview_id="unavailable",
                notebook_id="unavailable",
                tool_name="unavailable",
                tool_version="unavailable",
                status="FAILED",
                validation_passed=False,
                runtime_seconds=0,
                artifact_count=0,
                integrity=integrity,
                failures=["result_record_invalid"],
                completed_at=datetime.fromtimestamp(
                    result_path.stat().st_mtime, tz=timezone.utc
                ),
            )

    def _result_path(self, user_id: str, artifact_id: str, run_id: str) -> Path:
        return self._result_dir(user_id, artifact_id, run_id) / "preview_run_result.json"

    def _result_dir(self, user_id: str, artifact_id: str, run_id: str) -> Path:
        for value in (user_id, artifact_id, run_id):
            self._validate_id(value)
        path = (
            self.workspace_root
            / user_id
            / "artifacts"
            / artifact_id
            / "preview-runs"
            / run_id
        ).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("preview result path escapes workspace root") from exc
        return path

    def _is_owned_result_path(self, user_id: str, result_path: Path) -> bool:
        user_root = (self.workspace_root / user_id).resolve()
        try:
            result_path.resolve().relative_to(user_root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or _SAFE_ID.fullmatch(value) is None:
            raise ValueError("unsafe preview result identifier")

    @staticmethod
    def _result_digest_valid(result_path: Path) -> bool:
        digest_path = result_path.with_name("preview_run_result.sha256")
        if not result_path.is_file() or not digest_path.is_file():
            return False
        expected = digest_path.read_text(encoding="ascii").strip()
        return len(expected) == 64 and _sha256(result_path) == expected

    @staticmethod
    def _require_lineage(
        result: PreviewRunResult, *, user_id: str, artifact_id: str, run_id: str
    ) -> None:
        if (
            result.user_id != user_id
            or result.artifact_id != artifact_id
            or result.execution_run.run_id != run_id
            or result.execution_run.owner_user_id != user_id
            or result.execution_run.execution_purpose != "representative_preview"
        ):
            raise PermissionError("preview result ownership or purpose mismatch")


def _ui_status(
    result: PreviewRunResult, integrity: PreviewResultIntegrity
) -> str:
    if not integrity.passed:
        return "FAILED"
    if result.status == "validated" and result.validation_result.passed:
        return "COMPLETED"
    if result.status == "blocked" or result.execution_run.status == "blocked":
        return "BLOCKED"
    return "FAILED"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
