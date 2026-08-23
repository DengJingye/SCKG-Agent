from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache

from pydantic import Field

from core.execution_models import StrictModel
from core.settings import PROJECT_ROOT


PROCESS_STARTED_AT = datetime.now(timezone.utc)


class RuntimeBuildIdentity(StrictModel):
    schema_version: str = "runtime-build-identity-v1"
    version: str = "2.7.2-rc"
    git_head: str = "unknown"
    dirty_worktree: bool = False
    worktree_digest: str = Field(min_length=16)
    process_started_at: datetime = PROCESS_STARTED_AT
    process_id: int = Field(default_factory=os.getpid, gt=0)
    source_fingerprint: str = Field(min_length=16)


@lru_cache(maxsize=1)
def get_runtime_build_identity() -> RuntimeBuildIdentity:
    head = _git_output("rev-parse", "HEAD") or "unknown"
    status = _git_output("status", "--short", "--untracked-files=normal")
    worktree_digest = hashlib.sha256(
        f"{head}\n{status}".encode("utf-8")
    ).hexdigest()
    source_material = []
    for relative in (
        "app.py",
        "agent/research_chat_service.py",
        "agent/research_chat_reasoner.py",
        "core/research_agent_models.py",
    ):
        path = PROJECT_ROOT / relative
        try:
            source_material.append(relative.encode("utf-8") + b"\0" + path.read_bytes())
        except OSError:
            source_material.append(relative.encode("utf-8") + b"\0missing")
    source_fingerprint = hashlib.sha256(b"\n".join(source_material)).hexdigest()
    return RuntimeBuildIdentity(
        git_head=head,
        dirty_worktree=bool(status.strip()),
        worktree_digest=worktree_digest,
        source_fingerprint=source_fingerprint,
    )


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()
