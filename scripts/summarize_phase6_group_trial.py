from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from core.trial_telemetry import Phase6TrialStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize local anonymous Phase 6 trial records without changing project status."
    )
    parser.add_argument("--sessions", type=Path)
    parser.add_argument("--task-results", type=Path)
    parser.add_argument("--feedback", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (
        PROJECT_ROOT / ".sckg_exec" / "trials" / f"summary-{timestamp}"
    )
    store = Phase6TrialStore(
        session_path=args.sessions,
        task_result_path=args.task_results,
        feedback_path=args.feedback,
    )
    summary = store.summary()
    gate = store.gate_result(summary)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "trial_summary.json"
    gate_path = output_dir / "phase6_trial_gate.json"
    summary_path.write_text(
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    gate_path.write_text(
        json.dumps(gate.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload = {
        "output_dir": str(output_dir),
        "participant_count": summary.participant_count,
        "level_1_participant_count": summary.level_1_participant_count,
        "level_2_participant_count": summary.level_2_participant_count,
        "maintainer_rehearsal_count": summary.maintainer_rehearsal_count,
        "gate_passed": gate.gate_passed,
        "eligible_for_maintainer_completion_review": (
            gate.eligible_for_maintainer_completion_review
        ),
        "recommended_status": gate.recommended_status,
        "automatic_status_change": gate.automatic_status_change,
        "blockers": gate.blockers,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
