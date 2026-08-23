from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from core.settings import PROJECT_ROOT
from core.trial_telemetry import (
    Phase6TrialStore,
    TrialSession,
    TrialTelemetryEvent,
    TrialTelemetryStore,
    new_trial_participant_id,
    sanitize_trial_note,
)


def test_trial_telemetry_allows_optional_feedback_and_is_not_scientific_evidence(tmp_path):
    event = TrialTelemetryEvent(participant_id=new_trial_participant_id())
    store = TrialTelemetryStore(tmp_path / "events.jsonl")
    store.append(event)
    rows = store.list_events()
    assert rows[0]["scientific_authority"] is False
    assert rows[0]["user_rated_usefulness"] is None


@pytest.mark.parametrize("field", ["query", "raw_path", "matrix", "barcodes"])
def test_trial_telemetry_rejects_sensitive_payload_fields(field):
    with pytest.raises(ValidationError):
        TrialTelemetryEvent(
            participant_id=new_trial_participant_id(),
            **{field: "sensitive"},
        )


def test_trial_telemetry_file_has_no_query_or_path_fields(tmp_path):
    path = tmp_path / "events.jsonl"
    store = TrialTelemetryStore(path)
    store.append(
        TrialTelemetryEvent(
            participant_id=new_trial_participant_id(),
            task_completion=True,
            user_rated_usefulness=4,
        )
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert not {"query", "raw_path", "matrix", "barcodes"} & set(payload)


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 15, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def _trial_store(tmp_path, clock=None):
    return Phase6TrialStore(
        session_path=tmp_path / "sessions.jsonl",
        task_result_path=tmp_path / "task_results.jsonl",
        task_bank_path=PROJECT_ROOT / "eval" / "phase6" / "group_trial_task_bank.json",
        feedback_path=tmp_path / "feedback.jsonl",
        clock=clock,
    )


def _complete_all(store, session, *, completion=True):
    for task_id in session.assigned_task_ids:
        store.begin_task(session_id=session.session_id, task_id=task_id)
        store.submit_task(
            session_id=session.session_id,
            task_id=task_id,
            completion=completion,
        )
    return store.complete_session(
        session.session_id,
        execution_request_count=(
            1
            if session.level == "level_2" and session.actor_type == "participant"
            else 0
        ),
    )


def test_level_1_session_cannot_claim_an_execution_request():
    with pytest.raises(ValidationError):
        TrialSession(
            participant_id=new_trial_participant_id(),
            level="level_1",
            assigned_task_ids=["P6-T01"],
            execution_request_count=1,
        )


def test_level_2_participant_session_requires_controlled_execution(tmp_path):
    store = _trial_store(tmp_path)
    session = store.start_session(level="level_2")
    for task_id in session.assigned_task_ids:
        store.submit_task(
            session_id=session.session_id,
            task_id=task_id,
            completion=True,
        )
    with pytest.raises(ValidationError):
        store.complete_session(session.session_id, execution_request_count=0)


def test_trial_task_timing_help_and_interruption_recovery(tmp_path):
    clock = _Clock()
    store = _trial_store(tmp_path, clock)
    session = store.start_session(level="level_1")
    task_id = session.assigned_task_ids[0]
    store.begin_task(session_id=session.session_id, task_id=task_id)
    clock.advance(5)
    store.record_help(session_id=session.session_id, task_id=task_id)
    clock.advance(7)

    resumed = _trial_store(tmp_path, clock)
    result = resumed.submit_task(
        session_id=session.session_id,
        task_id=task_id,
        completion=True,
    )
    assert result.help_count == 1
    assert result.time_seconds == 12
    assert resumed.latest_task_results()[(session.session_id, task_id)].completion is True


def test_trial_notes_are_redacted_before_persistence(tmp_path):
    store = _trial_store(tmp_path)
    session = store.start_session(level="level_1")
    task_id = session.assigned_task_ids[0]
    result = store.submit_task(
        session_id=session.session_id,
        task_id=task_id,
        completion=False,
        observer_notes=(
            "query: analyze private sample\npath /Users/lris/private/input.h5ad "
            "barcode AAACCCAAGAAACACT-1"
        ),
    )
    assert "/Users/" not in result.observer_notes
    assert "AAACCCAAGAAACACT-1" not in result.observer_notes
    assert "analyze private sample" not in result.observer_notes
    assert "[redacted-path]" in result.observer_notes
    assert "[redacted-barcode]" in result.observer_notes
    assert sanitize_trial_note(result.observer_notes) == result.observer_notes


def test_maintainer_rehearsal_never_counts_as_real_participant(tmp_path):
    store = _trial_store(tmp_path)
    task_bank_before = (PROJECT_ROOT / "eval" / "phase6" / "group_trial_task_bank.json").read_bytes()
    rehearsal = store.start_session(
        level="level_1", actor_type="maintainer_rehearsal"
    )
    _complete_all(store, rehearsal)
    summary = store.summary()
    gate = store.gate_result(summary)
    assert summary.maintainer_rehearsal_count == 1
    assert summary.participant_count == 0
    assert summary.level_1_participant_count == 0
    assert not gate.gate_passed
    assert gate.recommended_status == "PHASE6_TRIAL_READY"
    assert (
        PROJECT_ROOT / "eval" / "phase6" / "group_trial_task_bank.json"
    ).read_bytes() == task_bank_before


def test_trial_gate_requires_three_level_1_and_one_level_2_participant(tmp_path):
    store = _trial_store(tmp_path)
    participant_ids = [new_trial_participant_id() for _ in range(3)]
    for participant_id in participant_ids:
        session = store.start_session(
            level="level_1", participant_id=participant_id
        )
        _complete_all(store, session)
    technical = store.start_session(
        level="level_2", participant_id=participant_ids[0]
    )
    _complete_all(store, technical)

    summary = store.summary()
    gate = store.gate_result(summary)
    assert summary.participant_count == 3
    assert summary.level_1_completion_rate == 1.0
    assert summary.critical_task_completion_rate == 1.0
    assert summary.level_2_participant_count == 1
    assert gate.gate_passed
    assert gate.eligible_for_maintainer_completion_review
    assert gate.automatic_status_change is False
    assert gate.recommended_status == "PHASE6_TRIAL_READY"


def test_safety_violation_forces_blocked_recommendation(tmp_path):
    store = _trial_store(tmp_path)
    participant_ids = [new_trial_participant_id() for _ in range(3)]
    for index, participant_id in enumerate(participant_ids):
        session = store.start_session(
            level="level_1", participant_id=participant_id
        )
        for task_id in session.assigned_task_ids:
            store.submit_task(
                session_id=session.session_id,
                task_id=task_id,
                completion=True,
                safety_violation_codes=(
                    ["path_leak_or_escape"] if index == 0 and task_id == "P6-T04" else []
                ),
            )
        store.complete_session(session.session_id)
    technical = store.start_session(
        level="level_2", participant_id=participant_ids[0]
    )
    _complete_all(store, technical)
    clean_retest = store.start_session(
        level="level_1", participant_id=participant_ids[0]
    )
    _complete_all(store, clean_retest)

    gate = store.gate_result()
    assert not gate.gate_passed
    assert gate.recommended_status == "PHASE6_BLOCKED"
    assert "safety_violation_present" in gate.blockers
