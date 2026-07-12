from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DOWNLOAD_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv"
)
DEFAULT_PDF_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_source_manifest_full.tsv"
)
DEFAULT_CORE_SOURCE_MANIFEST = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_tool_source_manifest_v2.tsv"
)
DEFAULT_RUN_SUMMARY = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_pipeline_run_summary.json"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local literature source pipeline. Default mode is offline/stabilization only; "
            "use --discover to refresh PDF candidate discovery."
        )
    )
    parser.add_argument("--discover", action="store_true", help="Run open PDF candidate discovery dry-run.")
    parser.add_argument(
        "--live-download",
        action="store_true",
        help="Download validated open PDFs during discovery. Use only after reviewing candidates.",
    )
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--download-source-manifest", type=Path, default=DEFAULT_DOWNLOAD_SOURCE_MANIFEST)
    parser.add_argument("--pdf-source-manifest", type=Path, default=DEFAULT_PDF_SOURCE_MANIFEST)
    parser.add_argument("--core-source-manifest", type=Path, default=DEFAULT_CORE_SOURCE_MANIFEST)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_RUN_SUMMARY)
    args = parser.parse_args()

    steps = build_steps(args)
    rows: List[Dict[str, Any]] = []
    started = time.time()
    for name, command in steps:
        step_started = time.time()
        result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True)
        row = {
            "step": name,
            "status": "ok" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "elapsed_ms": round((time.time() - step_started) * 1000, 3),
            "command": " ".join(str(part) for part in command),
            "stdout_tail": tail(result.stdout),
            "stderr_tail": tail(result.stderr),
        }
        rows.append(row)
        if result.returncode != 0 and not args.continue_on_error:
            break

    summary = {
        "pipeline": "scKG PDF / Literature Source Pipeline v2.3",
        "mode": "live_download" if args.live_download else ("discover_dry_run" if args.discover else "offline_refresh"),
        "ok": all(row["status"] == "ok" for row in rows),
        "elapsed_ms": round((time.time() - started) * 1000, 3),
        "steps": rows,
        "guardrail": (
            "Default mode does not download PDFs. Source text remains retrieval-only and cannot promote formal TSV evidence."
        ),
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    if not summary["ok"]:
        raise SystemExit(1)


def build_steps(args: argparse.Namespace) -> List[tuple[str, List[str]]]:
    steps: List[tuple[str, List[str]]] = []
    if args.discover or args.live_download:
        command = [
            sys.executable,
            "data_pipeline/download_evidence_pdfs.py",
            "--source-manifest",
            str(args.download_source_manifest),
            "--summary-output",
            "data/evidence_candidates/evidence_pdf_download_full_summary.json",
        ]
        if args.live_download:
            command.append("--live")
        steps.append(("discover_pdf_candidates" if not args.live_download else "acquire_pdf_or_html", command))
    steps.extend(
        [
            (
                "build_source_registry",
                [sys.executable, "data_pipeline/build_source_registry.py"],
            ),
            (
                "build_literature_source_coverage",
                [sys.executable, "data_pipeline/build_literature_source_coverage.py"],
            ),
            (
                "build_coverage_and_indexes",
                [
                    sys.executable,
                    "data_pipeline/build_evidence_index.py",
                    "--source-manifest",
                    str(args.pdf_source_manifest),
                    "--source-manifest",
                    str(args.core_source_manifest),
                ],
            ),
            (
                "build_algorithm_representations_v2",
                [
                    sys.executable,
                    "data_pipeline/build_algorithm_representations_v2.py",
                    "--source-manifest",
                    str(args.pdf_source_manifest),
                    "--source-manifest",
                    str(args.core_source_manifest),
                ],
            ),
        ]
    )
    return steps


def tail(value: str, limit: int = 2000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


if __name__ == "__main__":
    main()
