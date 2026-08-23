from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from core.execution_models import StrictModel
from core.settings import PROJECT_ROOT


SUPPORTED_SUFFIXES = {".h5ad": "AnnData"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class RegisteredDataArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    redacted_path: str
    sha256: str = Field(min_length=64, max_length=64)
    owner_user_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    size_bytes: int = Field(ge=0)
    artifact_type: str
    registered_at: datetime


class DataRegistry:
    """Register user data without persisting its full local path or copying it."""

    def __init__(
        self,
        *,
        approved_input_roots: list[Path],
        registry_root: Path = PROJECT_ROOT / ".sckg_exec" / "registry" / "data",
    ) -> None:
        if not approved_input_roots:
            raise ValueError("at least one approved input root is required")
        self.approved_input_roots = [Path(item).resolve() for item in approved_input_roots]
        self.registry_root = Path(registry_root).resolve()
        self.registry_root.mkdir(parents=True, exist_ok=True)
        self.metadata_log = self.registry_root / "artifacts.jsonl"
        self._records: dict[str, RegisteredDataArtifact] = {}
        self._resolved_paths: dict[str, Path] = {}
        self._hash_cache: dict[str, tuple[int, int, str]] = {}
        self._load_metadata()

    def register(
        self,
        *,
        user_id: str,
        path: Path,
        artifact_id: str | None = None,
        registered_at: datetime | None = None,
    ) -> RegisteredDataArtifact:
        _validate_id(user_id, "user_id")
        raw_path = Path(path)
        if ".." in raw_path.parts:
            raise ValueError("path traversal is forbidden")
        if raw_path.is_symlink():
            raise ValueError("symlink input is forbidden")
        try:
            resolved = raw_path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("input file is missing") from exc
        if not resolved.is_file():
            raise ValueError("registered input must be a file")
        if not any(_is_within(resolved, root) for root in self.approved_input_roots):
            raise ValueError("input path is outside approved roots")
        artifact_type = SUPPORTED_SUFFIXES.get(resolved.suffix.casefold())
        if artifact_type is None:
            raise ValueError("unsupported input file type")

        digest = _sha256(resolved)
        if artifact_id is None:
            matching_record = self._matching_record(
                user_id=user_id,
                resolved=resolved,
                digest=digest,
            )
            if matching_record is not None:
                self._authorize_path(matching_record, resolved)
                return matching_record
        artifact_id = artifact_id or f"data-{digest[:12]}-{uuid.uuid4().hex[:8]}"
        _validate_id(artifact_id, "artifact_id")
        if artifact_id in self._records:
            raise ValueError("artifact_id already registered")
        record = RegisteredDataArtifact(
            artifact_id=artifact_id,
            redacted_path=f".../{resolved.name}",
            sha256=digest,
            owner_user_id=user_id,
            size_bytes=resolved.stat().st_size,
            artifact_type=artifact_type,
            registered_at=registered_at or datetime.now(timezone.utc),
        )
        self._records[artifact_id] = record
        self._authorize_path(record, resolved)
        with self.metadata_log.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        return record

    def _matching_record(
        self, *, user_id: str, resolved: Path, digest: str
    ) -> RegisteredDataArtifact | None:
        candidates = [
            record
            for record in self._records.values()
            if record.owner_user_id == user_id
            and record.sha256 == digest
            and record.size_bytes == resolved.stat().st_size
            and record.redacted_path == f".../{resolved.name}"
        ]
        return max(candidates, key=lambda item: item.registered_at, default=None)

    def _authorize_path(
        self, record: RegisteredDataArtifact, resolved: Path
    ) -> None:
        self._resolved_paths[record.artifact_id] = resolved
        stat = resolved.stat()
        self._hash_cache[record.artifact_id] = (
            stat.st_size,
            stat.st_mtime_ns,
            record.sha256,
        )

    def get(self, artifact_id: str, *, user_id: str) -> RegisteredDataArtifact:
        record = self._records.get(artifact_id)
        if record is None:
            raise KeyError(f"artifact is not registered: {artifact_id}")
        if record.owner_user_id != user_id:
            raise PermissionError("cross-user artifact access is forbidden")
        return record

    def list_for_user(self, *, user_id: str) -> list[RegisteredDataArtifact]:
        _validate_id(user_id, "user_id")
        return sorted(
            (
                record
                for record in self._records.values()
                if record.owner_user_id == user_id
            ),
            key=lambda item: (item.registered_at, item.artifact_id),
            reverse=True,
        )

    def path_authorized(self, artifact_id: str, *, user_id: str) -> bool:
        """Return whether this process has an explicitly re-authorized local path."""
        self.get(artifact_id, user_id=user_id)
        return artifact_id in self._resolved_paths

    def resolve_path(self, artifact_id: str, *, user_id: str) -> Path:
        self.get(artifact_id, user_id=user_id)
        path = self._resolved_paths.get(artifact_id)
        if path is None:
            raise RuntimeError("artifact path must be re-authorized after process restart")
        if not path.is_file() or _sha256(path) != self._records[artifact_id].sha256:
            raise ValueError("registered artifact hash changed")
        return path

    def current_hash(
        self, artifact_id: str, *, user_id: str, force: bool = False
    ) -> str | None:
        """Return the current local digest without treating drift as a read grant."""
        self.get(artifact_id, user_id=user_id)
        path = self._resolved_paths.get(artifact_id)
        if path is None:
            return None
        if not path.is_file():
            raise FileNotFoundError("registered artifact is no longer available")
        stat = path.stat()
        cached = self._hash_cache.get(artifact_id)
        if not force and cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            return cached[2]
        digest = _sha256(path)
        self._hash_cache[artifact_id] = (stat.st_size, stat.st_mtime_ns, digest)
        return digest

    def _load_metadata(self) -> None:
        if not self.metadata_log.is_file():
            return
        for line in self.metadata_log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = RegisteredDataArtifact.model_validate_json(line)
            self._records[record.artifact_id] = record


def _validate_id(value: str, label: str) -> None:
    if not value or SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"unsafe {label}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
