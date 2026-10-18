"""Bounded checkout observations, not attestation of the loaded execution image.

Capture only in the authorized worker. Historical views use the saved receipt;
they never inspect today's checkout to fill missing execution metadata.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from .storage import content_hash, utcnow


SCHEMA = "analysis-code-provenance-v1"
ROOTS = ("sckg_workbench", "core", "engine", "execution")
SCOPE = "workbench-python-source-v1"
MAX_FILES, MAX_BYTES = 512, 8 * 1024 * 1024
MAX_ENTRIES = 4096
SOURCE_REASONS = {"source_unavailable_or_unsafe", "source_limit_exceeded", "source_changed_during_capture"}
GIT_REASONS = {"git_unavailable", "git_not_repository_root", "git_metadata_incomplete", "git_head_changed"}


def _inventory(root: Path, deadline: float) -> tuple[dict, int]:
    files, total, entries = {}, 0, 0

    def read(path):
        nonlocal total
        if time.monotonic() >= deadline or len(files) >= MAX_FILES:
            raise ValueError("source_limit_exceeded")
        # Never follow links or wait on devices/FIFOs while collecting metadata.
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("source_unavailable_or_unsafe")
            payload = stream.read(MAX_BYTES - total + 1)
            after = os.fstat(stream.fileno())
        total += len(payload)
        if total > MAX_BYTES:
            raise ValueError("source_limit_exceeded")
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("source_changed_during_capture")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(payload).hexdigest()

    def walk(directory):
        nonlocal entries
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("source_unavailable_or_unsafe")
        # Do not materialize an arbitrarily large directory before applying
        # limits. Canonical JSON, not enumeration order, defines the hash.
        with os.scandir(directory) as children:
            for entry in children:
                entries += 1
                if entries > MAX_ENTRIES or time.monotonic() >= deadline:
                    raise ValueError("source_limit_exceeded")
                path = Path(entry.path)
                if path.name == "__pycache__":
                    continue
                if path.is_symlink():
                    raise ValueError("source_unavailable_or_unsafe")
                if path.is_dir():
                    walk(path)
                elif path.suffix == ".py":
                    read(path)

    read(root / "workbench_app.py")
    for name in ROOTS:
        walk(root / name)
    return files, total


def _git_observation(root: Path) -> dict:
    # Ignore caller GIT_DIR/GIT_WORK_TREE and global config; do not refresh or
    # lock the index. Only HEAD and tracked/index dirtiness are observed here.
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "LANG") if k in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    def git(*args):
        return subprocess.run(["git", "--no-optional-locks", *args], cwd=root, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=1, check=False, text=True)
    result = {"head": None, "tracked_dirty": None, "reason": None}
    try:
        top = git("rev-parse", "--show-toplevel")
        if top.returncode or Path(top.stdout.strip()).resolve() != root:
            return {**result, "reason": "git_not_repository_root"}
        head = git("rev-parse", "--verify", "HEAD")
        dirty = git("diff-index", "--quiet", "--no-ext-diff", "HEAD", "--")
        final = git("rev-parse", "--verify", "HEAD")
        if head.returncode or final.returncode or dirty.returncode not in (0, 1) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", head.stdout.strip()):
            return {**result, "reason": "git_metadata_incomplete"}
        if head.stdout != final.stdout:
            return {**result, "reason": "git_head_changed"}
        return {"head": head.stdout.strip(), "tracked_dirty": dirty.returncode == 1, "reason": None}
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return {**result, "reason": "git_unavailable"}


def capture_code_provenance(root: Path | None = None) -> dict:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    receipt = {"schema_version": SCHEMA, "captured_at": utcnow(), "scope": SCOPE,
               "files": None, "source_hash": None, "source_bytes": None, "source_reason": None,
               "git": _git_observation(root)}
    try:
        deadline = time.monotonic() + 2
        files, size = _inventory(root, deadline)
        repeated, repeated_size = _inventory(root, deadline)
        if files != repeated or size != repeated_size:
            raise ValueError("source_changed_during_capture")
        receipt.update(files=files, source_hash=content_hash(files), source_bytes=size)
    except (OSError, ValueError, RecursionError) as exc:
        receipt["source_reason"] = str(exc) if str(exc) in SOURCE_REASONS else "source_unavailable_or_unsafe"
    return receipt


def recorded_code_provenance(prepared: dict, saved: dict) -> dict | None:
    """Validate binding and project only closed, non-path metadata for export."""
    if "code_provenance" not in prepared and "code_provenance_digest" not in saved:
        return None  # Historical record; never backfill from this checkout.
    value = prepared["code_provenance"]
    if content_hash(value) != saved["code_provenance_digest"]:
        raise ValueError("code provenance binding mismatch")
    if set(value) != {"schema_version", "captured_at", "scope", "files", "source_hash", "source_bytes", "source_reason", "git"} or value["schema_version"] != SCHEMA or value["scope"] != SCOPE:
        raise ValueError("invalid code provenance schema")
    # Do not project arbitrary strings from a receipt into a public download.
    from datetime import datetime
    captured = datetime.fromisoformat(value["captured_at"])
    if captured.tzinfo is None:
        raise ValueError("capture time must have timezone")
    files, reason = value["files"], value["source_reason"]
    if reason is None:
        if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES or type(value["source_bytes"]) is not int or not 0 <= value["source_bytes"] <= MAX_BYTES:
            raise ValueError("invalid source inventory")
        for name, digest in files.items():
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts or path.suffix != ".py"
                    or (name != "workbench_app.py" and path.parts[0] not in ROOTS)
                    or not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest)):
                raise ValueError("invalid source inventory entry")
        if content_hash(files) != value["source_hash"]:
            raise ValueError("source inventory hash mismatch")
    elif reason not in SOURCE_REASONS or any(value[k] is not None for k in ("files", "source_hash", "source_bytes")):
        raise ValueError("invalid missing source metadata")
    git = value["git"]
    if set(git) != {"head", "tracked_dirty", "reason"}:
        raise ValueError("invalid git metadata")
    if git["reason"] is None:
        if not isinstance(git["head"], str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", git["head"]) or type(git["tracked_dirty"]) is not bool:
            raise ValueError("invalid git identity")
    elif git["reason"] not in GIT_REASONS or git["head"] is not None or git["tracked_dirty"] is not None:
        raise ValueError("invalid missing git metadata")
    return {"schema_version": SCHEMA, "captured_at": captured.isoformat(), "scope": SCOPE,
            "source_hash": value["source_hash"], "source_file_count": len(files) if files else None,
            "source_bytes": value["source_bytes"], "source_reason": reason, "git": dict(git),
            "receipt_hash": content_hash(value), "capture_stage": "before_analysis_preparation",
            "git_dirty_scope": "tracked_and_index_only",
            "untracked_python_files_in_source_inventory": True,
            "loaded_execution_image_verified": False,
            "scope_excludes": ["third_party_packages", "non_python_assets", "outside_source_roots",
                               "loaded_bytecode", "changes_after_capture"]}
