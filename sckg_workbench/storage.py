"""Explicit workspace identity, immutable records and a transactional ledger."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterator
import uuid


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    @classmethod
    def default(cls) -> "Workspace":
        # No reuse of SCKG_HOME, legacy .sckg_user, or repository data directories.
        path = os.environ.get("SCKG_WORKBENCH_HOME")
        return cls(Path(path) if path else Path.home() / ".local/share/sckg-workbench")

    @property
    def db_path(self) -> Path:
        return self.root / "ledger.sqlite3"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def namespace(self) -> str:
        marker = self.root / "workspace.json"
        if not marker.exists():
            raise RuntimeError("workspace has not been initialized")
        return json.loads(marker.read_text())["namespace"]

    @contextmanager
    def initialization_lock(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.root.parent / ("." + self.root.name + ".sckg-init.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    def initialize(self) -> None:
        with self.initialization_lock():
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        marker = self.root / "workspace.json"
        for child in (marker, self.db_path, self.artifacts_dir, self.root / "releases",
                      self.root / "ledger.sqlite3-wal", self.root / "ledger.sqlite3-shm"):
            if child.is_symlink():
                raise ValueError("workspace paths must not be symlinks")
        if not marker.exists():
            # Never quietly adopt a legacy or arbitrary populated directory.
            if any(self.root.iterdir()):
                raise ValueError("new workspace must be empty; legacy migration is forbidden")
            payload = {"format": "sckg-isolated-workspace-v1", "namespace": new_id("kb"),
                       "created_at": utcnow(), "legacy_import": False}
            descriptor, temporary = tempfile.mkstemp(prefix=".workspace-", dir=self.root)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(canonical_json(payload))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, marker)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        value = json.loads(marker.read_text())
        if value.get("format") != "sckg-isolated-workspace-v1" or value.get("legacy_import") is not False:
            raise ValueError("workspace identity is incompatible")
        if not str(value.get("namespace", "")).startswith("kb-"):
            raise ValueError("workspace namespace is invalid")
        self.artifacts_dir.mkdir(exist_ok=True)
        (self.root / "releases").mkdir(exist_ok=True)


class Ledger:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        with workspace.initialization_lock():
            workspace._initialize_locked()
            self._initialize_schema()

    def _initialize_schema(self):
        workspace = self.workspace
        with self.connect() as conn:
            if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(
                    kind TEXT NOT NULL, record_id TEXT NOT NULL, payload TEXT NOT NULL,
                    digest TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(kind,record_id));
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL, subject_id TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT NOT NULL);
            """)
            row = conn.execute("SELECT value FROM metadata WHERE key='namespace'").fetchone()
            if row and row[0] != workspace.namespace:
                raise ValueError("ledger belongs to a different workspace")
            conn.execute("INSERT OR IGNORE INTO metadata VALUES('namespace',?)", (workspace.namespace,))
        workspace.db_path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        for path in (self.workspace.db_path, self.workspace.root / "ledger.sqlite3-wal", self.workspace.root / "ledger.sqlite3-shm"):
            if path.is_symlink():
                raise ValueError("ledger paths must not be symlinks")
        conn = sqlite3.connect(self.workspace.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=20000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def put_record(self, kind: str, record_id: str, payload: dict, *, conn=None) -> dict:
        if not kind or not record_id:
            raise ValueError("kind and record id are required")
        if conn is None:
            with self.transaction() as tx:
                return self.put_record(kind, record_id, payload, conn=tx)
        encoded = canonical_json(payload)
        digest = content_hash(payload)
        old = conn.execute("SELECT digest,payload FROM records WHERE kind=? AND record_id=?", (kind, record_id)).fetchone()
        if old:
            if old["digest"] != digest or old["payload"] != encoded:
                raise ValueError("immutable record conflict; create a new revision")
            return json.loads(old["payload"])
        conn.execute("INSERT INTO records VALUES(?,?,?,?,?)", (kind, record_id, encoded, digest, utcnow()))
        return json.loads(encoded)

    def get_record(self, kind: str, record_id: str, *, conn=None) -> dict | None:
        if conn is None:
            with self.connect() as tx:
                return self.get_record(kind, record_id, conn=tx)
        row = conn.execute("SELECT payload,digest FROM records WHERE kind=? AND record_id=?", (kind, record_id)).fetchone()
        if row is None:
            return None
        value = json.loads(row["payload"])
        if content_hash(value) != row["digest"]:
            raise ValueError("record integrity failure")
        return value

    def list_records(self, kind: str, *, conn=None) -> list[dict]:
        if conn is None:
            with self.connect() as tx:
                return self.list_records(kind, conn=tx)
        rows = conn.execute("SELECT record_id FROM records WHERE kind=? ORDER BY created_at,record_id", (kind,)).fetchall()
        return [self.get_record(kind, row[0], conn=conn) for row in rows]

    def get_state(self, key: str, default=None, *, conn=None):
        if conn is None:
            with self.connect() as tx:
                return self.get_state(key, default, conn=tx)
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def set_state(self, key: str, value: Any, *, conn=None) -> None:
        if conn is None:
            with self.transaction() as tx:
                return self.set_state(key, value, conn=tx)
        conn.execute("INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, canonical_json(value)))

    def append_event(self, event_type: str, subject_id: str, detail: dict, *, conn=None) -> str:
        if conn is None:
            with self.transaction() as tx:
                return self.append_event(event_type, subject_id, detail, conn=tx)
        event_id = new_id("event")
        conn.execute("INSERT INTO events(event_id,event_type,subject_id,detail,created_at) VALUES(?,?,?,?,?)",
                     (event_id, event_type, subject_id, canonical_json(detail), utcnow()))
        return event_id

    def events(self, subject_id: str | None = None, *, after: int = 0) -> list[dict]:
        with self.connect() as conn:
            sql = "SELECT * FROM events WHERE sequence>?"
            values: list[Any] = [after]
            if subject_id is not None:
                sql += " AND subject_id=?"
                values.append(subject_id)
            rows = conn.execute(sql + " ORDER BY sequence", values).fetchall()
            return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]
