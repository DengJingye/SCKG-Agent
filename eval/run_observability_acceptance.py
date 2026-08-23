from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.reflection_memory import DEFAULT_MEMORY_DB, DEFAULT_REFLECTION_LOG, DEFAULT_SKILL_CANDIDATES_DIR
from core.trace_context import DEFAULT_TRACE_PATH, load_traces


REQUIRED_AGENT_STAGES = [
    "trigger",
    "gateway",
    "intent_parse",
    "kg_hard_filter",
    "evidence_retrieval",
    "mcdm_rank",
    "migration_or_workflow_plan",
    "report_generate",
    "audit",
    "reflect",
]


def run_acceptance(*, run_smoke: bool) -> Dict[str, Any]:
    if run_smoke:
        subprocess.run(
            [sys.executable, "scripts/run_agent_trace_smoke.py"],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    traces = load_traces(DEFAULT_TRACE_PATH)
    agent_runs = [trace for trace in traces if trace.get("trace_type") == "agent_run"]
    latest = agent_runs[-1] if agent_runs else {}
    stage_names = [stage.get("stage") for stage in latest.get("stages", [])]
    stage_errors = _stage_errors(latest)
    missing_stages = [stage for stage in REQUIRED_AGENT_STAGES if stage not in stage_names]
    missing_elapsed = [
        stage.get("stage", "")
        for stage in latest.get("stages", [])
        if not isinstance(stage.get("elapsed_ms"), (int, float))
    ]
    reflection_events = _load_jsonl(DEFAULT_REFLECTION_LOG)
    memory_event_count = _memory_event_count(DEFAULT_MEMORY_DB)
    skill_candidates = list(DEFAULT_SKILL_CANDIDATES_DIR.glob("*.md")) if DEFAULT_SKILL_CANDIDATES_DIR.exists() else []
    skill_candidate_violations = [
        str(path)
        for path in skill_candidates
        if "review-only" not in path.read_text(encoding="utf-8", errors="ignore")
    ]
    evidence_smoke = _run_evidence_smoke()
    checks = {
        "has_agent_trace": bool(agent_runs),
        "has_required_stages": not missing_stages,
        "stage_elapsed_present": not missing_elapsed,
        "stage_errors_absent": not stage_errors,
        "has_reflection_event": bool(reflection_events),
        "has_private_memory_events": memory_event_count > 0,
        "skill_candidates_review_only": not skill_candidate_violations,
        "evidence_smoke_passed": evidence_smoke.get("passed") is True,
        "frozen_publications_still_blocked": (
            (evidence_smoke.get("audit_freeze") or {}).get("publication_runtime_allowed") == 0
        ),
        "frozen_benchmarks_still_blocked": (
            (evidence_smoke.get("audit_freeze") or {}).get("benchmark_runtime_allowed") == 0
        ),
        "trusted_non_main_violation_zero": (
            (evidence_smoke.get("gate") or {}).get("trusted_non_main_violation_count") == 0
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "trace_path": str(DEFAULT_TRACE_PATH),
        "latest_trace_id": latest.get("trace_id", ""),
        "stage_names": stage_names,
        "missing_stages": missing_stages,
        "missing_elapsed": missing_elapsed,
        "stage_errors": stage_errors,
        "reflection_log": str(DEFAULT_REFLECTION_LOG),
        "reflection_event_count": len(reflection_events),
        "memory_db": str(DEFAULT_MEMORY_DB),
        "memory_event_count": memory_event_count,
        "skill_candidates_dir": str(DEFAULT_SKILL_CANDIDATES_DIR),
        "skill_candidate_count": len(skill_candidates),
        "skill_candidate_violations": skill_candidate_violations,
        "evidence_smoke_summary": {
            "passed": evidence_smoke.get("passed"),
            "audit_freeze": evidence_smoke.get("audit_freeze"),
            "trusted_non_main_violation_count": (evidence_smoke.get("gate") or {}).get("trusted_non_main_violation_count"),
        },
    }


def _run_evidence_smoke() -> Dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "eval/run_evidence_recovery_smoke.py"],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return {"passed": False, "error": result.stderr or result.stdout}
    return json.loads(result.stdout)


def _stage_errors(trace: Dict[str, Any]) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    for stage in trace.get("stages", []):
        data = stage.get("data") if isinstance(stage.get("data"), dict) else {}
        if stage.get("status") == "error" or data.get("error"):
            errors.append({"stage": stage.get("stage", ""), "error": data.get("error", "")})
    return errors


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _memory_event_count(path: Path) -> int:
    if not path.exists():
        return 0
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()
    return int(row[0] if row else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate scKG observability/reflection acceptance criteria.")
    parser.add_argument("--run-smoke", action="store_true", help="Generate one trace before validation.")
    parser.add_argument("--json-output", type=Path, default=PROJECT_ROOT / "eval" / "observability_acceptance_summary.json")
    args = parser.parse_args()
    summary = run_acceptance(run_smoke=args.run_smoke)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
