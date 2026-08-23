from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.knowledge_intelligence_models import MemoryRetrievalContext
from core.settings import PROJECT_ROOT


DEFAULT_SCKG_HOME = Path(
    os.environ.get("SCKG_HOME", str(PROJECT_ROOT / ".sckg_user"))
).expanduser()
DEFAULT_WORKBENCH_DB = DEFAULT_SCKG_HOME / "state" / "workbench.sqlite3"


class UnifiedMemoryStore:
    """Private operational memory with no scientific evidence authority."""

    def __init__(self, path: Path = DEFAULT_WORKBENCH_DB) -> None:
        self.path = Path(path)
        self._init()

    def set_explicit_preference(self, user_id: str, key: str, value: Any) -> None:
        self._upsert_preference(
            user_id=user_id,
            key=key,
            value=value,
            status="explicit",
            confidence=1.0,
            source="user",
        )

    def propose_inferred_preference(
        self, user_id: str, key: str, value: Any, *, confidence: float, source: str
    ) -> None:
        self._upsert_preference(
            user_id=user_id,
            key=key,
            value=value,
            status="pending_inferred",
            confidence=confidence,
            source=source,
        )

    def confirm_inferred_preference(self, user_id: str, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_preferences
                SET status = 'confirmed_inferred', updated_at = ?
                WHERE user_id = ? AND key = ? AND status = 'pending_inferred'
                """,
                (time.time(), user_id, key),
            )
        return bool(cursor.rowcount)

    def record_episodic_run(
        self,
        user_id: str,
        run_id: str,
        summary: Dict[str, Any],
        *,
        trace_id: str = "",
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodic_run_memory(
                    user_id, run_id, trace_id, summary_json,
                    can_affect_scientific_authority, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(user_id, run_id) DO UPDATE SET
                    trace_id = excluded.trace_id,
                    summary_json = excluded.summary_json
                """,
                (user_id, run_id, trace_id, _json(summary), now),
            )

    def record_reflection(
        self,
        user_id: str,
        reflection: Dict[str, Any],
    ) -> None:
        reflection_id = str(reflection.get("reflection_id") or _fingerprint(reflection))
        trace_id = str(reflection.get("trace_id") or "")
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reflection_event_memory(
                    reflection_id, user_id, trace_id, payload_json,
                    can_affect_scientific_authority, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (reflection_id, user_id, trace_id, _json(reflection), now),
            )
            for event in reflection.get("memory_events") or []:
                event_id = str(event.get("event_id") or _fingerprint(event))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_events(
                        event_id, user_id, event_type, key, value_json, source,
                        trace_id, confidence, can_affect_scientific_authority, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        event_id,
                        user_id,
                        str(event.get("event_type") or "reflection"),
                        str(event.get("key") or "lesson"),
                        _json(event.get("value")),
                        str(event.get("source") or "reflection"),
                        trace_id,
                        float(event.get("confidence") or 0.0),
                        str(event.get("created_at") or now),
                    ),
                )
            for candidate in reflection.get("skill_candidates") or []:
                self._record_skill_candidate(conn, user_id, candidate, trace_id, now)

    def context(self, user_id: str, *, limit: int = 12) -> MemoryRetrievalContext:
        with self._connect() as conn:
            preferences = conn.execute(
                """
                SELECT key, value_json, status FROM memory_preferences
                WHERE user_id = ? AND status IN ('explicit', 'confirmed_inferred')
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
            episodes = conn.execute(
                """
                SELECT run_id, trace_id, summary_json, created_at
                FROM episodic_run_memory WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            reflections = conn.execute(
                """
                SELECT reflection_id, trace_id, payload_json, created_at
                FROM reflection_event_memory WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            skills = conn.execute(
                """
                SELECT candidate_id, title, trigger_text, payload_json, status
                FROM skill_candidate_memory WHERE user_id = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        explicit: Dict[str, Any] = {}
        inferred: Dict[str, Any] = {}
        for row in preferences:
            target = explicit if row["status"] == "explicit" else inferred
            target[row["key"]] = _load_json(row["value_json"])
        return MemoryRetrievalContext(
            user_id=user_id,
            explicit_preferences=explicit,
            confirmed_inferences=inferred,
            episodic_runs=[
                {
                    "run_id": row["run_id"],
                    "trace_id": row["trace_id"],
                    "summary": _load_json(row["summary_json"]),
                    "created_at": row["created_at"],
                }
                for row in episodes
            ],
            reflection_lessons=[
                {
                    "reflection_id": row["reflection_id"],
                    "trace_id": row["trace_id"],
                    "payload": _load_json(row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in reflections
            ],
            skill_candidates=[
                {
                    "candidate_id": row["candidate_id"],
                    "title": row["title"],
                    "trigger": row["trigger_text"],
                    "payload": _load_json(row["payload_json"]),
                    "status": row["status"],
                }
                for row in skills
            ],
            can_affect_scientific_authority=False,
        )

    def export_user_memory(self, user_id: str) -> Dict[str, Any]:
        context = self.context(user_id, limit=10_000)
        with self._connect() as conn:
            pending = conn.execute(
                """
                SELECT key, value_json, confidence, source FROM memory_preferences
                WHERE user_id = ? AND status = 'pending_inferred'
                ORDER BY key
                """,
                (user_id,),
            ).fetchall()
        return {
            "schema_version": "unified-memory-export-v1",
            "user_id": user_id,
            "context": context.model_dump(mode="json"),
            "pending_inferences": [
                {
                    "key": row["key"],
                    "value": _load_json(row["value_json"]),
                    "confidence": row["confidence"],
                    "source": row["source"],
                }
                for row in pending
            ],
            "evidence_authority": False,
        }

    def list_conflicts(self, user_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT conflict_id, key, existing_json, proposed_json,
                       proposed_source, status, created_at
                FROM memory_conflicts WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "conflict_id": row["conflict_id"],
                "key": row["key"],
                "existing": _load_json(row["existing_json"]),
                "proposed": _load_json(row["proposed_json"]),
                "proposed_source": row["proposed_source"],
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def resolve_conflict(self, user_id: str, conflict_id: str, *, accept: bool) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT key, proposed_json, proposed_source FROM memory_conflicts
                WHERE user_id = ? AND conflict_id = ? AND status = 'pending'
                """,
                (user_id, conflict_id),
            ).fetchone()
            if row is None:
                return False
            if accept:
                now = time.time()
                conn.execute(
                    """
                    UPDATE memory_preferences
                    SET value_json = ?, status = 'confirmed_inferred',
                        source = ?, updated_at = ?
                    WHERE user_id = ? AND key = ?
                    """,
                    (
                        row["proposed_json"],
                        row["proposed_source"],
                        now,
                        user_id,
                        row["key"],
                    ),
                )
            conn.execute(
                "UPDATE memory_conflicts SET status = ? WHERE conflict_id = ?",
                ("accepted" if accept else "rejected", conflict_id),
            )
        return True

    def delete_user_memory(self, user_id: str) -> None:
        with self._connect() as conn:
            for table in (
                "memory_preferences",
                "episodic_run_memory",
                "reflection_event_memory",
                "skill_candidate_memory",
                "memory_conflicts",
                "memory_events",
            ):
                conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))

    def _upsert_preference(
        self,
        *,
        user_id: str,
        key: str,
        value: Any,
        status: str,
        confidence: float,
        source: str,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT value_json, status FROM memory_preferences WHERE user_id = ? AND key = ?",
                (user_id, key),
            ).fetchone()
            if existing and existing["status"] in {"explicit", "confirmed_inferred"} and existing["value_json"] != _json(value):
                conn.execute(
                    """
                    INSERT INTO memory_conflicts(
                        conflict_id, user_id, key, existing_json, proposed_json,
                        proposed_source, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        _fingerprint({"user": user_id, "key": key, "time": now}),
                        user_id,
                        key,
                        existing["value_json"],
                        _json(value),
                        source,
                        now,
                    ),
                )
                if status == "pending_inferred":
                    return
            conn.execute(
                """
                INSERT INTO memory_preferences(
                    user_id, key, value_json, status, confidence, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    status = excluded.status,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (user_id, key, _json(value), status, confidence, source, now, now),
            )

    @staticmethod
    def _record_skill_candidate(
        conn: sqlite3.Connection,
        user_id: str,
        candidate: Dict[str, Any],
        trace_id: str,
        now: float,
    ) -> None:
        payload = {
            "title": candidate.get("title"),
            "trigger": candidate.get("trigger"),
            "proposed_steps": candidate.get("proposed_steps") or [],
        }
        fingerprint = _fingerprint(payload)
        conn.execute(
            """
            INSERT INTO skill_candidate_memory(
                candidate_id, user_id, fingerprint, title, trigger_text,
                payload_json, source_trace_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'review_needed', ?, ?)
            ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                source_trace_id = excluded.source_trace_id,
                updated_at = excluded.updated_at
            """,
            (
                str(candidate.get("candidate_id") or f"skill_{fingerprint[:16]}"),
                user_id,
                fingerprint,
                str(candidate.get("title") or "Untitled skill candidate"),
                str(candidate.get("trigger") or ""),
                _json(payload),
                trace_id,
                now,
                now,
            ),
        )

    def _init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_preferences (
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, key)
                );
                CREATE TABLE IF NOT EXISTS episodic_run_memory (
                    user_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    can_affect_scientific_authority INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(user_id, run_id)
                );
                CREATE TABLE IF NOT EXISTS reflection_event_memory (
                    reflection_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    can_affect_scientific_authority INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_candidate_memory (
                    candidate_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    title TEXT NOT NULL,
                    trigger_text TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(user_id, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS memory_conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    existing_json TEXT NOT NULL,
                    proposed_json TEXT NOT NULL,
                    proposed_source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    event_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    can_affect_scientific_authority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_events)")}
            if "user_id" not in columns:
                conn.execute(
                    "ALTER TABLE memory_events ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
