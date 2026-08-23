from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from core.trial_telemetry import Phase6TrialStore


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = PROJECT_ROOT / ".sckg_exec" / "trials" / f"rehearsal-{timestamp}"
    store = Phase6TrialStore(
        session_path=run_dir / "sessions.jsonl",
        task_result_path=run_dir / "task_results.jsonl",
        feedback_path=run_dir / "feedback.jsonl",
    )
    level_1 = store.start_session(
        level="level_1", actor_type="maintainer_rehearsal"
    )
    for index, task_id in enumerate(level_1.assigned_task_ids):
        store.begin_task(session_id=level_1.session_id, task_id=task_id)
        if index == 0:
            store.record_help(session_id=level_1.session_id, task_id=task_id)
        store.submit_task(
            session_id=level_1.session_id,
            task_id=task_id,
            completion=True,
            observer_notes=(
                "maintainer rehearsal path /Users/example/private.h5ad "
                "barcode AAACCCAAGAAACACT-1"
                if index == 0
                else "maintainer rehearsal passed"
            ),
        )
    completed_level_1 = store.complete_session(level_1.session_id)

    level_2 = store.start_session(
        level="level_2", actor_type="maintainer_rehearsal"
    )
    for task_id in level_2.assigned_task_ids:
        store.submit_task(
            session_id=level_2.session_id,
            task_id=task_id,
            completion=True,
            observer_notes="backend execution is validated by the Phase 6C UI service smoke",
        )
    store.complete_session(level_2.session_id, execution_request_count=0)

    summary = store.summary()
    gate = store.gate_result(summary)
    raw_records = (run_dir / "task_results.jsonl").read_text(encoding="utf-8")
    checks = {
        "level_1_tasks_recorded": len(level_1.assigned_task_ids) == 10,
        "level_2_tasks_recorded": len(level_2.assigned_task_ids) == 7,
        "level_1_execution_request_count_zero": (
            completed_level_1.execution_request_count == 0
        ),
        "sensitive_path_redacted": "/Users/example" not in raw_records,
        "barcode_redacted": "AAACCCAAGAAACACT-1" not in raw_records,
        "real_participant_count_zero": summary.participant_count == 0,
        "rehearsals_excluded_from_gate": summary.maintainer_rehearsal_count == 2,
        "phase6_not_auto_completed": (
            not gate.gate_passed and gate.automatic_status_change is False
        ),
    }
    payload = {
        "status": "passed" if all(checks.values()) else "failed",
        "run_dir": str(run_dir),
        "actor_type": "maintainer_rehearsal",
        "real_participant_count": summary.participant_count,
        "maintainer_rehearsal_count": summary.maintainer_rehearsal_count,
        "gate_passed": gate.gate_passed,
        "recommended_status": gate.recommended_status,
        "blockers": gate.blockers,
        "checks": checks,
    }
    (run_dir / "rehearsal_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
