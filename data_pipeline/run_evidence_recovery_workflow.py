from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_recovery_workflow_summary.json"
)
PUBLICATION_AUDIT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "formal_publication_audit_summary.json"
)
BENCHMARK_AUDIT_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "formal_benchmark_audit_summary.json"
)
SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv"
)


def run_step(name: str, args: List[str]) -> Dict[str, Any]:
    command = [sys.executable, *args]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "name": name,
        "command": " ".join(args),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "ok": result.returncode == 0,
    }


def run_workflow(
    *,
    fetch_mode: str,
    fetch_limit: int | None,
    ai_review_mode: str,
    ai_review_limit: int | None,
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    def step(name: str, args: List[str], *, required: bool = True) -> None:
        item = run_step(name, args)
        steps.append(item)
        if required and not item["ok"]:
            raise WorkflowStepError(name, steps)

    step(
        "audit_publications",
        [
            "eval/audit_formal_publication_evidence.py",
            "--json-summary",
            str(PUBLICATION_AUDIT_SUMMARY.relative_to(PROJECT_ROOT)),
        ],
    )
    step(
        "audit_benchmarks",
        [
            "eval/audit_formal_benchmark_evidence.py",
            "--json-summary",
            str(BENCHMARK_AUDIT_SUMMARY.relative_to(PROJECT_ROOT)),
        ],
    )
    step("build_review_packet", ["data_pipeline/build_evidence_recovery_review_packet.py"])
    step("build_source_manifest", ["data_pipeline/build_evidence_source_manifest.py"])

    if fetch_mode != "none":
        fetch_args = ["data_pipeline/fetch_evidence_sources.py"]
        if fetch_mode == "dry-run":
            fetch_args.append("--dry-run")
        if fetch_limit is not None:
            fetch_args.extend(["--limit", str(fetch_limit)])
        step(f"fetch_sources_{fetch_mode}", fetch_args)

    step(
        "build_evidence_index",
        [
            "data_pipeline/build_evidence_index.py",
            "--source-manifest",
            str(SOURCE_MANIFEST.relative_to(PROJECT_ROOT)),
        ],
    )
    step("prefill_review_packet", ["data_pipeline/prefill_evidence_review_packet.py"])
    if ai_review_mode != "none":
        ai_review_args = [
            "data_pipeline/ai_review_evidence_packet.py",
            "--mode",
            ai_review_mode,
        ]
        if ai_review_limit is not None:
            ai_review_args.extend(["--limit", str(ai_review_limit)])
        step(f"ai_review_{ai_review_mode}", ai_review_args)
    step("promotion_dry_run", ["data_pipeline/promote_recovered_evidence.py"])
    step("conservative_smoke", ["eval/run_evidence_recovery_smoke.py"])

    return {
        "workflow": "Evidence Recovery Sprint v1",
        "fetch_mode": fetch_mode,
        "fetch_limit": fetch_limit,
        "ai_review_mode": ai_review_mode,
        "ai_review_limit": ai_review_limit,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "ok": all(item["ok"] for item in steps),
        "steps": steps,
    }


class WorkflowStepError(RuntimeError):
    def __init__(self, step_name: str, steps: List[Dict[str, Any]]) -> None:
        super().__init__(f"Evidence recovery workflow failed at {step_name}")
        self.step_name = step_name
        self.steps = steps


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the spec-defined Evidence Recovery Sprint v1 workflow.")
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--fetch-mode",
        choices=["none", "dry-run", "live"],
        default="dry-run",
        help="Source fetching mode. live performs network requests; dry-run is the safe default.",
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        default=3,
        help="Limit source fetch attempts for dry-run/live modes. Use -1 for no limit.",
    )
    parser.add_argument(
        "--ai-review-mode",
        choices=["none", "dry-run", "live"],
        default="none",
        help="Optional AI-assisted review. live calls the configured LLM; none is the safe default.",
    )
    parser.add_argument(
        "--ai-review-limit",
        type=int,
        default=3,
        help="Limit AI review attempts for dry-run/live modes. Use -1 for no limit.",
    )
    args = parser.parse_args()

    fetch_limit = None if args.fetch_limit is not None and args.fetch_limit < 0 else args.fetch_limit
    ai_review_limit = (
        None if args.ai_review_limit is not None and args.ai_review_limit < 0 else args.ai_review_limit
    )
    try:
        summary = run_workflow(
            fetch_mode=args.fetch_mode,
            fetch_limit=fetch_limit,
            ai_review_mode=args.ai_review_mode,
            ai_review_limit=ai_review_limit,
        )
    except WorkflowStepError as exc:
        summary = {
            "workflow": "Evidence Recovery Sprint v1",
            "fetch_mode": args.fetch_mode,
            "fetch_limit": fetch_limit,
            "ai_review_mode": args.ai_review_mode,
            "ai_review_limit": ai_review_limit,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "failed_step": exc.step_name,
            "steps": exc.steps,
            "error": str(exc),
        }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
