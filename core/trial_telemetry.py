from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Literal

from pydantic import ConfigDict, Field, model_validator

from core.execution_models import StrictModel
from core.settings import PROJECT_ROOT


DEFAULT_TRIAL_TELEMETRY = PROJECT_ROOT / "data" / "telemetry" / "phase6_trial_events.jsonl"
DEFAULT_TRIAL_SESSIONS = PROJECT_ROOT / "data" / "telemetry" / "phase6_trial_sessions.jsonl"
DEFAULT_TRIAL_TASK_RESULTS = (
    PROJECT_ROOT / "data" / "telemetry" / "phase6_trial_task_results.jsonl"
)
DEFAULT_TRIAL_TASK_BANK = PROJECT_ROOT / "eval" / "phase6" / "group_trial_task_bank.json"
CRITICAL_TASK_IDS = frozenset({"P6-T02", "P6-T04", "P6-T06", "P6-T08", "P6-T10"})
SAFETY_VIOLATION_CODES = frozenset(
    {
        "unauthorized_execution",
        "path_leak_or_escape",
        "cross_user_access",
        "uncontrolled_repair",
    }
)

_ABSOLUTE_PATH = re.compile(
    r"(?:(?:/Users|/home|/private|/var|/tmp)/[^\s,;]+|[A-Za-z]:\\[^\s,;]+)"
)
_BARCODE = re.compile(r"\b[ACGTN]{12,32}(?:-\d+)?\b", re.IGNORECASE)
_QUERY_ASSIGNMENT = re.compile(r"(?i)\b(?:query|prompt)\s*[:=]\s*[^\n]+")


class TrialTelemetryEvent(StrictModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"trial-event-{uuid.uuid4().hex}")
    participant_id: str = Field(pattern=r"^trial-[a-f0-9]{32}$")
    task_completion: bool | None = None
    user_intervention_count: int = Field(default=0, ge=0)
    blocking_reason: str | None = None
    execution_success: bool | None = None
    repair_result: Literal["not_applicable", "not_attempted", "succeeded", "failed"] = (
        "not_applicable"
    )
    reproducibility_package_opened: bool | None = None
    user_rated_usefulness: int | None = Field(default=None, ge=1, le=5)
    user_reported_incorrect_claim: bool | None = None
    scientific_authority: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def new_trial_participant_id() -> str:
    return f"trial-{uuid.uuid4().hex}"


class TrialTelemetryStore:
    def __init__(self, path: Path = DEFAULT_TRIAL_TELEMETRY) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event: TrialTelemetryEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def list_events(self, *, limit: int = 500) -> list[dict]:
        if not self.path.is_file():
            return []
        rows: list[dict] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows[-limit:][::-1]


class TrialSession(StrictModel):
    session_id: str = Field(
        default_factory=lambda: f"trial-session-{uuid.uuid4().hex}",
        pattern=r"^trial-session-[a-f0-9]{32}$",
    )
    participant_id: str = Field(pattern=r"^trial-[a-f0-9]{32}$")
    level: Literal["level_1", "level_2"]
    actor_type: Literal["participant", "maintainer_rehearsal"] = "participant"
    status: Literal["in_progress", "completed", "abandoned"] = "in_progress"
    assigned_task_ids: list[str] = Field(min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    execution_request_count: int = Field(default=0, ge=0)
    user_data_used: Literal[False] = False
    scientific_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_trial_boundaries(self) -> "TrialSession":
        if self.level == "level_1" and self.execution_request_count != 0:
            raise ValueError("Level 1 trial cannot create an ExecutionRequest")
        if self.status == "completed" and self.completed_at is None:
            raise ValueError("completed trial session requires completed_at")
        if self.status != "completed" and self.completed_at is not None:
            raise ValueError("only completed trial sessions may set completed_at")
        if (
            self.status == "completed"
            and self.level == "level_2"
            and self.actor_type == "participant"
            and self.execution_request_count < 1
        ):
            raise ValueError("completed Level 2 participant trial requires a controlled execution")
        return self


class TrialTaskResult(StrictModel):
    result_id: str = Field(
        default_factory=lambda: f"trial-result-{uuid.uuid4().hex}",
        pattern=r"^trial-result-[a-f0-9]{32}$",
    )
    session_id: str = Field(pattern=r"^trial-session-[a-f0-9]{32}$")
    participant_id: str = Field(pattern=r"^trial-[a-f0-9]{32}$")
    level: Literal["level_1", "level_2"]
    actor_type: Literal["participant", "maintainer_rehearsal"] = "participant"
    task_id: str = Field(pattern=r"^P6-T\d{2}$")
    completion: bool | None = None
    time_seconds: float = Field(default=0.0, ge=0)
    help_count: int = Field(default=0, ge=0)
    critical_error: bool = False
    safety_violation_codes: list[
        Literal[
            "unauthorized_execution",
            "path_leak_or_escape",
            "cross_user_access",
            "uncontrolled_repair",
        ]
    ] = Field(default_factory=list)
    observer_notes: str = Field(default="", max_length=500)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scientific_authority: Literal[False] = False


class TrialSummary(StrictModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    participant_count: int = Field(ge=0)
    level_1_participant_count: int = Field(ge=0)
    level_2_participant_count: int = Field(ge=0)
    maintainer_rehearsal_count: int = Field(ge=0)
    completed_session_count: int = Field(ge=0)
    task_result_count: int = Field(ge=0)
    level_1_completion_rate: float = Field(ge=0, le=1)
    critical_task_completion_rate: float = Field(ge=0, le=1)
    median_time_seconds: float | None = Field(default=None, ge=0)
    help_rate: float = Field(ge=0, le=1)
    critical_error_count: int = Field(ge=0)
    safety_violation_counts: dict[str, int] = Field(default_factory=dict)
    usefulness_median: float | None = Field(default=None, ge=1, le=5)
    incorrect_claim_count: int = Field(ge=0)


class Phase6TrialGateResult(StrictModel):
    gate_passed: bool
    eligible_for_maintainer_completion_review: bool
    recommended_status: Literal["PHASE6_TRIAL_READY", "PHASE6_BLOCKED"]
    automatic_status_change: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def sanitize_trial_note(value: str) -> str:
    """Remove path/query/barcode-like payloads before telemetry persistence."""

    text = str(value or "")
    if "query=[redacted]" not in text:
        text = _QUERY_ASSIGNMENT.sub("query=[redacted]", text)
    text = " ".join(text.split())
    text = _ABSOLUTE_PATH.sub("[redacted-path]", text)
    text = _BARCODE.sub("[redacted-barcode]", text)
    return text[:500]


class Phase6TrialStore:
    """Append-only local store and deterministic Phase 6 trial aggregator."""

    def __init__(
        self,
        *,
        session_path: Path | None = None,
        task_result_path: Path | None = None,
        task_bank_path: Path | None = None,
        feedback_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_path = Path(
            session_path
            or os.environ.get("SCKG_PHASE6_TRIAL_SESSIONS", DEFAULT_TRIAL_SESSIONS)
        )
        self.task_result_path = Path(
            task_result_path
            or os.environ.get(
                "SCKG_PHASE6_TRIAL_TASK_RESULTS", DEFAULT_TRIAL_TASK_RESULTS
            )
        )
        self.task_bank_path = Path(
            task_bank_path
            or os.environ.get("SCKG_PHASE6_TRIAL_TASK_BANK", DEFAULT_TRIAL_TASK_BANK)
        )
        self.feedback = TrialTelemetryStore(
            Path(
                feedback_path
                or os.environ.get(
                    "SCKG_PHASE6_TRIAL_FEEDBACK", DEFAULT_TRIAL_TELEMETRY
                )
            )
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    def task_bank(self, level: Literal["level_1", "level_2"]) -> list[dict[str, Any]]:
        payload = json.loads(self.task_bank_path.read_text(encoding="utf-8"))
        task_ids = set(payload["levels"][level]["task_ids"])
        return [row for row in payload["tasks"] if row["task_id"] in task_ids]

    def start_session(
        self,
        *,
        level: Literal["level_1", "level_2"],
        actor_type: Literal["participant", "maintainer_rehearsal"] = "participant",
        participant_id: str | None = None,
    ) -> TrialSession:
        session = TrialSession(
            participant_id=participant_id or new_trial_participant_id(),
            level=level,
            actor_type=actor_type,
            assigned_task_ids=[row["task_id"] for row in self.task_bank(level)],
            started_at=self.clock(),
        )
        self._append_model(self.session_path, session)
        return session

    def get_session(self, session_id: str) -> TrialSession:
        sessions = {row.session_id: row for row in self.list_sessions()}
        if session_id not in sessions:
            raise KeyError(f"trial session not found: {session_id}")
        return sessions[session_id]

    def list_sessions(self) -> list[TrialSession]:
        latest: dict[str, TrialSession] = {}
        for payload in self._read_jsonl(self.session_path):
            session = TrialSession.model_validate(payload)
            latest[session.session_id] = session
        return sorted(latest.values(), key=lambda row: row.started_at, reverse=True)

    def begin_task(self, *, session_id: str, task_id: str) -> TrialTaskResult:
        session = self.get_session(session_id)
        self._validate_task(session, task_id)
        current = self.latest_task_results().get((session_id, task_id))
        if current is not None:
            return current
        result = TrialTaskResult(
            session_id=session.session_id,
            participant_id=session.participant_id,
            level=session.level,
            actor_type=session.actor_type,
            task_id=task_id,
            started_at=self.clock(),
            updated_at=self.clock(),
        )
        self._append_model(self.task_result_path, result)
        return result

    def record_help(self, *, session_id: str, task_id: str) -> TrialTaskResult:
        current = self.begin_task(session_id=session_id, task_id=task_id)
        updated = current.model_copy(
            update={
                "help_count": current.help_count + 1,
                "time_seconds": self._elapsed(current.started_at),
                "updated_at": self.clock(),
            }
        )
        self._append_model(self.task_result_path, updated)
        return updated

    def submit_task(
        self,
        *,
        session_id: str,
        task_id: str,
        completion: bool,
        critical_error: bool = False,
        safety_violation_codes: list[str] | None = None,
        observer_notes: str = "",
    ) -> TrialTaskResult:
        current = self.begin_task(session_id=session_id, task_id=task_id)
        codes = list(dict.fromkeys(safety_violation_codes or []))
        unknown = sorted(set(codes) - SAFETY_VIOLATION_CODES)
        if unknown:
            raise ValueError("unknown safety violation code: " + ", ".join(unknown))
        updated = current.model_copy(
            update={
                "completion": bool(completion),
                "critical_error": bool(critical_error),
                "safety_violation_codes": codes,
                "observer_notes": sanitize_trial_note(observer_notes),
                "time_seconds": self._elapsed(current.started_at),
                "updated_at": self.clock(),
            }
        )
        self._append_model(self.task_result_path, updated)
        return updated

    def complete_session(
        self, session_id: str, *, execution_request_count: int | None = None
    ) -> TrialSession:
        session = self.get_session(session_id)
        current = self.latest_task_results()
        missing = [
            task_id
            for task_id in session.assigned_task_ids
            if (session_id, task_id) not in current
            or current[(session_id, task_id)].completion is None
        ]
        if missing:
            raise ValueError("trial tasks are incomplete: " + ", ".join(missing))
        completed = session.model_copy(
            update={
                "status": "completed",
                "completed_at": self.clock(),
                "execution_request_count": (
                    session.execution_request_count
                    if execution_request_count is None
                    else execution_request_count
                ),
            }
        )
        completed = TrialSession.model_validate(completed.model_dump(mode="python"))
        self._append_model(self.session_path, completed)
        return completed

    def latest_task_results(self) -> dict[tuple[str, str], TrialTaskResult]:
        latest: dict[tuple[str, str], TrialTaskResult] = {}
        for payload in self._read_jsonl(self.task_result_path):
            result = TrialTaskResult.model_validate(payload)
            latest[(result.session_id, result.task_id)] = result
        return latest

    def summary(self) -> TrialSummary:
        completed = [row for row in self.list_sessions() if row.status == "completed"]
        participants = {
            row.participant_id for row in completed if row.actor_type == "participant"
        }
        level_1 = self._latest_participant_sessions(completed, "level_1")
        level_2 = self._latest_participant_sessions(completed, "level_2")
        rehearsals = [row for row in completed if row.actor_type == "maintainer_rehearsal"]
        selected = [*level_1, *level_2]
        latest_results = self.latest_task_results()
        results = [
            latest_results[(session.session_id, task_id)]
            for session in selected
            for task_id in session.assigned_task_ids
            if (session.session_id, task_id) in latest_results
        ]
        all_human_results = [
            latest_results[(session.session_id, task_id)]
            for session in completed
            if session.actor_type == "participant"
            for task_id in session.assigned_task_ids
            if (session.session_id, task_id) in latest_results
        ]
        level_1_results = [row for row in results if row.level == "level_1"]
        critical_results = [
            row for row in level_1_results if row.task_id in CRITICAL_TASK_IDS
        ]
        feedback = [
            row
            for row in self.feedback.list_events(limit=5000)
            if row.get("participant_id") in participants
        ]
        usefulness = [
            int(row["user_rated_usefulness"])
            for row in feedback
            if row.get("user_rated_usefulness") is not None
        ]
        safety_counts = Counter(
            code for row in all_human_results for code in row.safety_violation_codes
        )
        return TrialSummary(
            participant_count=len(participants),
            level_1_participant_count=len(
                {row.participant_id for row in level_1}
            ),
            level_2_participant_count=len(
                {row.participant_id for row in level_2}
            ),
            maintainer_rehearsal_count=len(rehearsals),
            completed_session_count=len(selected),
            task_result_count=len(results),
            level_1_completion_rate=self._completion_rate(level_1_results),
            critical_task_completion_rate=self._completion_rate(critical_results),
            median_time_seconds=(
                float(median(row.time_seconds for row in results)) if results else None
            ),
            help_rate=(
                sum(row.help_count > 0 for row in results) / len(results)
                if results
                else 0.0
            ),
            critical_error_count=sum(row.critical_error for row in results),
            safety_violation_counts=dict(sorted(safety_counts.items())),
            usefulness_median=float(median(usefulness)) if usefulness else None,
            incorrect_claim_count=sum(
                row.get("user_reported_incorrect_claim") is True for row in feedback
            ),
        )

    def gate_result(self, summary: TrialSummary | None = None) -> Phase6TrialGateResult:
        summary = summary or self.summary()
        blockers: list[str] = []
        if summary.level_1_participant_count < 3:
            blockers.append("at_least_3_level_1_participants_required")
        if summary.level_2_participant_count < 1:
            blockers.append("at_least_1_level_2_participant_required")
        if summary.level_1_completion_rate < 0.9:
            blockers.append("level_1_completion_rate_below_90_percent")
        if summary.critical_task_completion_rate < 1.0:
            blockers.append("critical_task_completion_rate_below_100_percent")
        if summary.critical_error_count:
            blockers.append("unresolved_critical_errors_present")
        safety_violation_count = sum(summary.safety_violation_counts.values())
        if safety_violation_count:
            blockers.append("safety_violation_present")
        warnings = []
        if summary.usefulness_median is None:
            warnings.append("subjective_usefulness_not_recorded")
        return Phase6TrialGateResult(
            gate_passed=not blockers,
            eligible_for_maintainer_completion_review=not blockers,
            recommended_status=(
                "PHASE6_BLOCKED"
                if safety_violation_count
                else "PHASE6_TRIAL_READY"
            ),
            blockers=blockers,
            warnings=warnings,
        )

    def _latest_participant_sessions(
        self,
        sessions: list[TrialSession],
        level: Literal["level_1", "level_2"],
    ) -> list[TrialSession]:
        latest: dict[str, TrialSession] = {}
        for session in sorted(sessions, key=lambda row: row.completed_at or row.started_at):
            if session.level == level and session.actor_type == "participant":
                latest[session.participant_id] = session
        return list(latest.values())

    @staticmethod
    def _completion_rate(results: list[TrialTaskResult]) -> float:
        return sum(row.completion is True for row in results) / len(results) if results else 0.0

    def _elapsed(self, started_at: datetime) -> float:
        return max(0.0, (self.clock() - started_at).total_seconds())

    @staticmethod
    def _validate_task(session: TrialSession, task_id: str) -> None:
        if session.status != "in_progress":
            raise ValueError("trial session is not in progress")
        if task_id not in session.assigned_task_ids:
            raise ValueError(f"task is not assigned to this trial session: {task_id}")

    def _append_model(self, path: Path, model: StrictModel) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(model.model_dump_json() + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows
