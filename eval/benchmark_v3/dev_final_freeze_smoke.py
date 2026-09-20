"""Eight-unit final DEV freeze smoke over the accepted hardened runtime.

The runner reuses the targeted-regression capture/receipt implementation. It
does not score the full DEV set and does not change prompts, questions, lanes,
knowledge sources, or corpora.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import subprocess
import sys


EVAL_ROOT = Path(__file__).resolve().parents[2]
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from eval.benchmark_v3 import dev_targeted_regression as common
from eval.benchmark_v3.dev_pilot import BASE, sha, write


RUNTIME_COMMIT = "f3df9056364200fdc114d9cfd8d71fa76b915219"
EXPERIMENT_ID = "dev-final-freeze-smoke-20260921-v1"
SCHEDULE_SEED = 2026092103
RUN_MATRIX = {
    "dev-K04-evidence-version-b": (
        "llm_only",
        "generic_rag",
        "legacy_kg",
        "scientific_kg",
    ),
    "dev-K01-hvg-input-a": ("generic_rag", "scientific_kg"),
    "dev-K03-reference-annotation-b": ("generic_rag", "scientific_kg"),
}

# The shared worker resolves this global dynamically. Patching only the runtime
# identity preserves the already-tested capture and receipt implementation.
common.RUNTIME_COMMIT = RUNTIME_COMMIT


def assert_runtime(root: Path) -> str:
    return common.assert_runtime(root)


def initialize(args):
    preflight = common.preflight(args.runtime, args.env_file)
    if preflight["status"] != "ready":
        raise RuntimeError("configured provider unavailable/disabled; no calls attempted")

    prior_inputs = json.loads((BASE / "dev_pilot_20260921/inputs.json").read_text())
    selected = {case_id: prior_inputs[case_id] for case_id in RUN_MATRIX}
    scheduled = [
        {
            "run_id": f"{case_id}--{lane}--freeze-r0",
            "case_id": case_id,
            "lane": lane,
            "repetition": 0,
            "input_sha256": sha(selected[case_id]["rendered_query"].encode()),
        }
        for case_id, lanes in RUN_MATRIX.items()
        for lane in lanes
    ]
    random.Random(SCHEDULE_SEED).shuffle(scheduled)

    lane_manifest = json.loads((BASE / "evaluation_lane_manifest.json").read_text())
    lane_manifest["baseline_truth"] = {
        "integration_commit": RUNTIME_COMMIT,
        "rule": "07 accepted final hardened runtime; lane knowledge sources remain frozen",
        "prior_lane_manifest_commit": "5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee",
    }
    for lane in lane_manifest["lanes"]:
        lane["implementation_commit"] = RUNTIME_COMMIT

    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "preflight.json", preflight)
    write(args.output / "inputs.json", selected)
    write(
        args.output / "manifest.json",
        {
            "experiment_id": EXPERIMENT_ID,
            "phase": "DEV-FINAL-FREEZE-SMOKE",
            "implementation_commit": RUNTIME_COMMIT,
            "benchmark_commit_before_run": subprocess.check_output(
                ["git", "-C", str(BASE), "rev-parse", "HEAD"], text=True
            ).strip(),
            "runner_sha256_at_freeze": sha(Path(__file__).read_bytes()),
            "shared_worker_sha256_at_freeze": sha(Path(common.__file__).read_bytes()),
            "harness_sha256_at_freeze": sha(Path(common.__file__).read_bytes()),
            "scenario_file_sha256": sha((BASE / "development_scenarios.jsonl").read_bytes()),
            "fixture_file_sha256": sha((BASE / "development_fixtures.json").read_bytes()),
            "lane_manifest_file_sha256": sha((BASE / "evaluation_lane_manifest.json").read_bytes()),
            "approved_kg_sha256": common.APPROVED_SHA,
            "lane_manifest": lane_manifest,
            "selection": {
                "rule": "user-authorized final smoke matrix only",
                "run_matrix": {key: list(value) for key, value in RUN_MATRIX.items()},
                "excluded": ["dev-K01-hvg-input-b", "dev-W01", "dev-W02", "all other DEV cases"],
            },
            "generator": preflight["configuration"],
            "repetitions": 1,
            "schedule_seed": SCHEDULE_SEED,
            "provider_seed": None,
            "deterministic_provider_claimed": False,
            "budgets": {
                "provider_parameters": "unchanged accepted 07 runtime parameters/timeouts",
                "unit_watchdog_seconds": 360,
                "maximum_concurrent_units": 4,
                "no_automatic_reruns": True,
            },
            "schedule": scheduled,
            "formal_scoring_performed": False,
            "formal_gold_created": False,
            "coverage_status": "unchanged; this is a runtime propagation smoke",
            "forbidden_changes": [
                "questions",
                "scoring",
                "KG",
                "RAG corpus",
                "product prompt",
                "seed expansion",
                "K01b/W01/W02 execution",
                "performance-driven tuning",
            ],
        },
    )
    print(json.dumps({"status": "initialized", "expected_runs": len(scheduled)}, sort_keys=True))


def worker(args):
    common.worker(args)


def execute(args):
    manifest = json.loads((args.output / "manifest.json").read_text())
    pending = []
    for unit in manifest["schedule"]:
        directory = args.output / "runs" / unit["run_id"]
        if directory.exists():
            if not (directory / "runtime_receipt.json").exists():
                raise RuntimeError(f"incomplete attempt retained: {directory}")
            continue
        pending.append(unit)

    def launch(unit):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "worker",
            "--runtime",
            str(args.runtime),
            "--env-file",
            str(args.env_file),
            "--output",
            str(args.output),
            "--run-id",
            unit["run_id"],
        ]
        try:
            result = subprocess.run(
                command,
                cwd=args.runtime,
                capture_output=True,
                text=True,
                timeout=360,
            )
            row = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        except subprocess.TimeoutExpired:
            row = {"returncode": None, "timeout": True}
        write(args.output / "process_logs" / f"{unit['run_id']}.json", row)
        return {"run_id": unit["run_id"], "returncode": row["returncode"]}

    failures = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for future in as_completed([pool.submit(launch, unit) for unit in pending]):
            result = future.result()
            print(json.dumps(result, sort_keys=True), flush=True)
            if result["returncode"] != 0:
                failures.append(result)
    if failures:
        raise SystemExit("Incomplete attempts preserved. Inspect logs; do not silently rerun.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("initialize", "run", "worker"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()
    args.runtime = args.runtime.resolve()
    args.env_file = args.env_file.resolve()
    args.output = args.output.resolve()
    {"initialize": initialize, "run": execute, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
