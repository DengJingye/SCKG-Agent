"""Persistent, fenced workbench jobs; this module never invokes models or tools.

Usage supplied to checkpoint/finish is a delta. An omitted usage dimension means
no new observation; ``None`` means the amount is unknown, never zero. Consumers
must call check_budget before metered work and serialize calls within a lease.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Callable, Iterator

from sckg_workbench.storage import Ledger


STATUSES = frozenset({"queued", "running", "succeeded", "partial", "failed",
                      "cancel_requested", "cancelled", "result_unknown"})
FINISH_STATUSES = frozenset({"succeeded", "partial", "failed", "cancelled", "result_unknown"})
RETRY_STATUSES = frozenset({"failed", "partial", "result_unknown"})
USAGE_FIELDS = ("calls", "tokens", "cost")


class TaskError(ValueError):
    """Invalid task operation or input."""


class IdempotencyConflict(TaskError):
    pass


class LeaseLost(TaskError):
    pass


class InvalidTransition(TaskError):
    pass


class BudgetExceeded(TaskError):
    pass


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TaskError("Payload must be finite JSON data") from exc


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"{name} must be a non-empty string")
    return value


def _number(value: Any, name: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TaskError(f"{name} must be a non-negative finite number")
    if integer and not isinstance(value, int):
        raise TaskError(f"{name} must be an integer")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise TaskError(f"{name} must be a non-negative finite number")
    return value


def validate_budget(budget: Any) -> dict[str, int | float]:
    required = {"max_calls", "max_tokens", "max_cost"}
    if not isinstance(budget, dict) or set(budget) != required:
        raise TaskError("Budget requires exactly max_calls, max_tokens and max_cost")
    return {name: _number(budget[name], name, integer=name != "max_cost")
            for name in sorted(required)}


def _validate_usage(usage: Any) -> dict[str, int | float | None]:
    if usage is None:
        return {}
    if not isinstance(usage, dict) or set(usage) - set(USAGE_FIELDS):
        raise TaskError("Usage accepts only calls, tokens and cost")
    return {name: None if value is None else _number(value, name, integer=name != "cost")
            for name, value in usage.items()}


def _initial_usage() -> dict[str, dict[str, Any]]:
    return {name: {"known": 0, "unknown": False} for name in USAGE_FIELDS}


def _add_usage(current: dict, delta: dict) -> dict:
    for name, value in delta.items():
        if value is None:
            current[name]["unknown"] = True
        elif name == "cost":
            current[name]["known"] = float(Decimal(str(current[name]["known"])) + Decimal(str(value)))
        else:
            current[name]["known"] += value
    return current


def _budget_status(usage: dict, budget: dict) -> str:
    if any(Decimal(str(usage[k]["known"])) > Decimal(str(budget[f"max_{k}"])) for k in USAGE_FIELDS):
        return "exceeded"
    if any(usage[k]["unknown"] for k in USAGE_FIELDS):
        return "usage_unknown"
    return "within_budget"


class TaskQueue:
    """One active lease per workspace, using SQLite transactions for arbitration.

    ``workspace`` must expose db_path and namespace. All scientific approval is
    outside this queue: succeeded means only that the worker reported completion.
    """

    def __init__(self, workspace: Any, *, clock: Callable[[], float] = time.time):
        self.workspace = workspace
        self.ledger = Ledger(workspace)
        self.db_path = workspace.db_path
        self.namespace = _text(workspace.namespace, "namespace")
        self._clock = clock
        with self._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS workbench_tasks (
                task_id TEXT PRIMARY KEY, namespace TEXT NOT NULL,
                kind TEXT NOT NULL, input_json TEXT NOT NULL, profile_json TEXT NOT NULL,
                budget_json TEXT NOT NULL, payload_digest TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0, fencing_token TEXT,
                worker_id TEXT, lease_expires_at REAL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, checkpoint_json TEXT, result_json TEXT,
                error_json TEXT, usage_json TEXT NOT NULL,
                UNIQUE(namespace, idempotency_key))""")
            conn.execute("""CREATE INDEX IF NOT EXISTS workbench_tasks_status
                ON workbench_tasks(namespace, status, created_at)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workbench_task_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                namespace TEXT NOT NULL, event_type TEXT NOT NULL,
                attempt INTEGER NOT NULL, created_at REAL NOT NULL, detail_json TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES workbench_tasks(task_id))""")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self.ledger.transaction() as conn:
            yield conn

    def _event(self, conn: sqlite3.Connection, row: sqlite3.Row, event_type: str, detail: dict) -> None:
        conn.execute("""INSERT INTO workbench_task_events
            (task_id, namespace, event_type, attempt, created_at, detail_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (row["task_id"], self.namespace, event_type, row["attempt"], self._clock(), _json(detail)))
        self.ledger.append_event(f"task.{event_type}", row["task_id"],
                                 {"attempt": row["attempt"], **detail}, conn=conn)

    def _row(self, conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM workbench_tasks WHERE namespace=? AND task_id=?",
                           (self.namespace, task_id)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return row

    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        result = dict(row)
        for column, name in (("input_json", "input_snapshot"), ("profile_json", "profile_snapshot"),
                             ("budget_json", "budget"), ("usage_json", "usage"),
                             ("checkpoint_json", "checkpoint"), ("result_json", "result"),
                             ("error_json", "error")):
            raw = result.pop(column)
            result[name] = json.loads(raw) if raw is not None else None
        result["budget_status"] = _budget_status(result["usage"], result["budget"])
        return result

    def _expire(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute("""SELECT * FROM workbench_tasks WHERE namespace=?
            AND status IN ('running', 'cancel_requested') AND lease_expires_at<=?""",
            (self.namespace, self._clock())).fetchall()
        for row in rows:
            usage = _add_usage(json.loads(row["usage_json"]), dict.fromkeys(USAGE_FIELDS))
            error = {"reason": "lease_expired", "message": "External effects and unreported usage may be unknown"}
            conn.execute("""UPDATE workbench_tasks SET status='result_unknown',
                fencing_token=NULL, worker_id=NULL, lease_expires_at=NULL,
                updated_at=?, error_json=?, usage_json=? WHERE task_id=?""",
                (self._clock(), _json(error), _json(usage), row["task_id"]))
            self._event(conn, row, "lease_expired", {"previous_status": row["status"], **error})
        return [row["task_id"] for row in rows]

    def recover_expired(self) -> list[str]:
        with self._transaction() as conn:
            return self._expire(conn)

    def submit(self, kind: str, input_snapshot: dict, profile_snapshot: dict,
               budget: dict, idempotency_key: str, *, submission_hook=None) -> dict:
        kind = _text(kind, "kind")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        if not isinstance(input_snapshot, dict) or not isinstance(profile_snapshot, dict):
            raise TaskError("Input and profile snapshots must be JSON objects")
        budget = validate_budget(budget)
        payload = _json({"kind": kind, "input": input_snapshot, "profile": profile_snapshot, "budget": budget})
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._transaction() as conn:
            existing = conn.execute("SELECT * FROM workbench_tasks WHERE namespace=? AND idempotency_key=?",
                                    (self.namespace, idempotency_key)).fetchone()
            if existing is not None:
                if existing["payload_digest"] != digest:
                    raise IdempotencyConflict("Idempotency key already belongs to a different payload")
                public = self._public(existing)
                if submission_hook is not None:
                    submission_hook(conn, public)
                return public
            task_id, now = f"task:{uuid.uuid4().hex}", self._clock()
            conn.execute("""INSERT INTO workbench_tasks (task_id, namespace, kind,
                input_json, profile_json, budget_json, payload_digest, idempotency_key,
                status, created_at, updated_at, usage_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (task_id, self.namespace, kind, _json(input_snapshot), _json(profile_snapshot),
                 _json(budget), digest, idempotency_key, now, now, _json(_initial_usage())))
            row = self._row(conn, task_id)
            self.ledger.put_record("task_submission", task_id,
                {"task_id": task_id, "namespace": self.namespace, "kind": kind,
                 "input_snapshot": input_snapshot, "profile_snapshot": profile_snapshot,
                 "budget": budget, "payload_digest": digest}, conn=conn)
            self._event(conn, row, "submitted", {"payload_digest": digest})
            public = self._public(row)
            if submission_hook is not None:
                submission_hook(conn, public)
            return public

    def get(self, task_id: str) -> dict:
        with self._transaction() as conn:
            self._expire(conn)
            return self._public(self._row(conn, task_id))

    def list(self, status: str | None = None, *, limit: int = 100) -> list[dict]:
        if status is not None and status not in STATUSES:
            raise TaskError("Unknown task status")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise TaskError("limit must be a positive integer")
        with self._transaction() as conn:
            self._expire(conn)
            rows = conn.execute("""SELECT * FROM workbench_tasks WHERE namespace=?
                AND (? IS NULL OR status=?) ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (self.namespace, status, status, limit)).fetchall()
            return [self._public(row) for row in rows]

    def peek_next(self) -> dict | None:
        """Inspect the next claimable task without incrementing its attempt."""
        with self._transaction() as conn:
            self._expire(conn)
            active = conn.execute("""SELECT 1 FROM workbench_tasks WHERE namespace=?
                AND status IN ('running', 'cancel_requested') LIMIT 1""", (self.namespace,)).fetchone()
            if active is not None:
                return None
            row = conn.execute("""SELECT * FROM workbench_tasks WHERE namespace=?
                AND status='queued' ORDER BY created_at, rowid LIMIT 1""", (self.namespace,)).fetchone()
            return self._public(row) if row else None

    @staticmethod
    def _lease_seconds(seconds: Any) -> float:
        value = _number(seconds, "lease_seconds")
        if value <= 0:
            raise TaskError("lease_seconds must be positive")
        return float(value)

    def claim(self, worker_id: str, lease_seconds: float = 60, *, expected_task_id: str | None = None,
              execution_guard=None) -> dict | None:
        worker_id = _text(worker_id, "worker_id")
        lease_seconds = self._lease_seconds(lease_seconds)
        with self._transaction() as conn:
            self._expire(conn)
            active = conn.execute("""SELECT 1 FROM workbench_tasks WHERE namespace=?
                AND status IN ('running', 'cancel_requested') LIMIT 1""", (self.namespace,)).fetchone()
            if active is not None:
                return None
            row = conn.execute("""SELECT * FROM workbench_tasks WHERE namespace=?
                AND status='queued' ORDER BY created_at, rowid LIMIT 1""", (self.namespace,)).fetchone()
            if row is None:
                return None
            if expected_task_id is not None and row["task_id"] != expected_task_id:
                return None
            from .chat_runs import ChatRunService
            ChatRunService(self.ledger).task_execution_guard(conn, self._public(row))
            if execution_guard is not None:
                execution_guard(conn, self._public(row))
            token, now = uuid.uuid4().hex, self._clock()
            conn.execute("""UPDATE workbench_tasks SET status='running', attempt=attempt+1,
                fencing_token=?, worker_id=?, lease_expires_at=?, updated_at=? WHERE task_id=?""",
                (token, worker_id, now + lease_seconds, now, row["task_id"]))
            row = self._row(conn, row["task_id"])
            self._event(conn, row, "claimed", {"worker_id": worker_id, "lease_expires_at": now + lease_seconds})
            return self._public(row)

    def _require_lease(self, conn: sqlite3.Connection, task_id: str, token: str) -> sqlite3.Row:
        row = self._row(conn, task_id)
        if (row["status"] not in {"running", "cancel_requested"} or not token
                or token != row["fencing_token"] or row["lease_expires_at"] <= self._clock()):
            raise LeaseLost("Task lease or fencing token is no longer valid")
        return row

    def heartbeat(self, task_id: str, token: str, lease_seconds: float = 60) -> dict:
        seconds = self._lease_seconds(lease_seconds)
        self.recover_expired()
        with self._transaction() as conn:
            row = self._require_lease(conn, task_id, token)
            conn.execute("UPDATE workbench_tasks SET lease_expires_at=?, updated_at=? WHERE task_id=?",
                         (self._clock() + seconds, self._clock(), task_id))
            self._event(conn, row, "heartbeat", {"lease_expires_at": self._clock() + seconds})
            return self._public(self._row(conn, task_id))

    def checkpoint(self, task_id: str, token: str, stage: str, detail: dict,
                   usage: dict | None = None) -> dict:
        stage = _text(stage, "stage")
        if not isinstance(detail, dict):
            raise TaskError("Checkpoint detail must be a JSON object")
        checkpoint = {"stage": stage, "detail": detail}
        encoded = _json(checkpoint)
        delta = _validate_usage(usage)
        self.recover_expired()
        with self._transaction() as conn:
            row = self._require_lease(conn, task_id, token)
            total = _add_usage(json.loads(row["usage_json"]), delta)
            conn.execute("UPDATE workbench_tasks SET checkpoint_json=?, usage_json=?, updated_at=? WHERE task_id=?",
                         (encoded, _json(total), self._clock(), task_id))
            self._event(conn, row, "checkpoint", {**checkpoint, "usage_delta": delta})
            return self._public(self._row(conn, task_id))

    def check_budget(self, task_id: str, token: str, proposed_usage: dict) -> dict:
        """Check a conservative upper bound before work; this is not a reservation.

        A worker must not dispatch concurrent metered calls under one token. The
        actual delta must be recorded even if a provider exceeded the estimate.
        """
        delta = _validate_usage(proposed_usage)
        if set(delta) != set(USAGE_FIELDS) or any(value is None for value in delta.values()):
            raise TaskError("Proposed usage requires known calls, tokens and cost upper bounds")
        self.recover_expired()
        with self._transaction() as conn:
            row = self._require_lease(conn, task_id, token)
            if row["status"] == "cancel_requested":
                raise InvalidTransition("Cancellation requested; do not dispatch further work")
            total = _add_usage(json.loads(row["usage_json"]), delta)
            if _budget_status(total, json.loads(row["budget_json"])) != "within_budget":
                raise BudgetExceeded("Budget would be exceeded or earlier usage is unknown")
            return {"allowed": True, "projected_usage": total}

    def request_cancel(self, task_id: str, *, expected_attempt: int | None = None,
                       expected_payload_digest: str | None = None, conn=None) -> dict:
        """Cancel one exact generation, optionally in the caller's transaction.

        A queued generation is its next execution attempt, including after an
        explicit retry. This operation never expires unrelated workspace jobs.
        """
        if expected_attempt is not None and (type(expected_attempt) is not int or expected_attempt < 1):
            raise TaskError("expected_attempt must be a positive integer")
        if expected_payload_digest is not None:
            _text(expected_payload_digest, "expected_payload_digest")

        def cancel(tx):
            row = self._row(tx, task_id)
            effective_attempt = row["attempt"] + (row["status"] == "queued")
            if ((expected_attempt is not None and expected_attempt != effective_attempt)
                    or (expected_payload_digest is not None and expected_payload_digest != row["payload_digest"])):
                raise InvalidTransition("Cancellation task generation or payload does not match")
            if row["status"] not in {"queued", "running"}:
                return self._public(row)
            status = "cancelled" if row["status"] == "queued" else "cancel_requested"
            tx.execute("UPDATE workbench_tasks SET status=?, updated_at=? WHERE task_id=?",
                         (status, self._clock(), task_id))
            self._event(tx, row, status, {"previous_status": row["status"]})
            return self._public(self._row(tx, task_id))

        if conn is not None:
            if not conn.in_transaction:
                raise TaskError("Caller cancellation connection must have an active transaction")
            return cancel(conn)
        with self._transaction() as tx:
            return cancel(tx)

    def finish(self, task_id: str, token: str, status: str, result: Any = None,
               error: Any = None, usage: dict | None = None) -> dict:
        if status not in FINISH_STATUSES:
            raise InvalidTransition("finish requires a terminal status")
        encoded_result, encoded_error = _json(result), _json(error)
        delta = _validate_usage(usage)
        if status == "result_unknown":
            delta = {**dict.fromkeys(USAGE_FIELDS), **delta}
        self.recover_expired()
        with self._transaction() as conn:
            row = self._require_lease(conn, task_id, token)
            if row["status"] == "cancel_requested" and status == "succeeded":
                raise InvalidTransition("Cancellation cannot be acknowledged as succeeded")
            total = _add_usage(json.loads(row["usage_json"]), delta)
            conn.execute("""UPDATE workbench_tasks SET status=?, result_json=?, error_json=?, usage_json=?,
                fencing_token=NULL, worker_id=NULL, lease_expires_at=NULL, updated_at=? WHERE task_id=?""",
                (status, encoded_result, encoded_error, _json(total), self._clock(), task_id))
            self._event(conn, row, "finished", {"status": status, "result": result, "error": error,
                                               "usage_delta": delta, "budget_status": _budget_status(total, json.loads(row["budget_json"]))})
            return self._public(self._row(conn, task_id))

    def retry(self, task_id: str, *, confirm_no_duplicate: bool = False) -> dict:
        if confirm_no_duplicate is not True:
            raise InvalidTransition("Explicit confirmation is required before retrying possible external effects")
        with self._transaction() as conn:
            self._expire(conn)
            row = self._row(conn, task_id)
            if row["status"] not in RETRY_STATUSES:
                raise InvalidTransition("Only failed, partial or result_unknown tasks may be retried")
            self._event(conn, row, "retry_requested", {"previous_status": row["status"],
                "previous_result": json.loads(row["result_json"]) if row["result_json"] else None,
                "previous_error": json.loads(row["error_json"]) if row["error_json"] else None,
                "confirmed_no_duplicate": True})
            conn.execute("""UPDATE workbench_tasks SET status='queued', result_json=NULL,
                error_json=NULL, checkpoint_json=NULL, fencing_token=NULL, worker_id=NULL,
                lease_expires_at=NULL, updated_at=? WHERE task_id=?""", (self._clock(), task_id))
            return self._public(self._row(conn, task_id))

    def events(self, task_id: str) -> list[dict]:
        with self._transaction() as conn:
            self._row(conn, task_id)
            rows = conn.execute("""SELECT * FROM workbench_task_events WHERE namespace=?
                AND task_id=? ORDER BY event_id""", (self.namespace, task_id)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["detail"] = json.loads(item.pop("detail_json"))
                result.append(item)
            return result
