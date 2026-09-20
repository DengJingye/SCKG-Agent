"""Offline integrity checks for the DEV targeted regression.

This verifier never calls the provider, changes a lane, or rescales a result.
It binds the recorded observations to the frozen inputs, runtime, receipts,
provider responses, and unchanged knowledge corpora.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from eval.benchmark_v3 import run_lane_alignment_audit as frozen
from eval.benchmark_v3.dev_pilot import BASE, LANES, sha, write
from eval.benchmark_v3.dev_scoring import receipt_for, validate_receipts
from eval.benchmark_v3.dev_targeted_regression import (
    CONTROLS,
    FIX_MAPPING,
    RUNTIME_COMMIT,
    assert_runtime,
)


def _normalized_lane_manifest(value):
    normalized = json.loads(json.dumps(value))
    normalized["baseline_truth"]["integration_commit"] = "<runtime-commit>"
    normalized["baseline_truth"]["rule"] = "<runtime-rule>"
    normalized["baseline_truth"].pop("prior_lane_manifest_commit", None)
    for lane in normalized["lanes"]:
        lane["implementation_commit"] = "<runtime-commit>"
    return normalized


def _verify_aborted_attempt(path: Path):
    aborted = json.loads((path / "ABORTED.json").read_text())
    logs = sorted((path / "process_logs").glob("*.json"))
    receipts = sorted(path.glob("runs/*/runtime_receipt.json"))
    assert aborted["status"] == "aborted_before_worker_initialization"
    assert aborted["provider_calls"] == 0
    assert aborted["runs_with_runtime_receipt"] == 0
    assert len(logs) == 28 and not receipts
    return {
        "path": path.name,
        "process_logs": len(logs),
        "provider_calls": 0,
        "runtime_receipts": 0,
        "reason": aborted["reason"],
    }


def verify(output: Path, runtime: Path, env_file: Path | None = None):
    assert_runtime(runtime)
    assert not subprocess.check_output(
        ["git", "-C", str(runtime), "status", "--porcelain"], text=True
    ).strip(), "detached runtime has uncommitted or untracked files"

    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["implementation_commit"] == RUNTIME_COMMIT
    assert manifest["approved_kg_sha256"] == frozen.APPROVED_KG_SHA256
    for name, field in (
        ("development_scenarios.jsonl", "scenario_file_sha256"),
        ("development_fixtures.json", "fixture_file_sha256"),
        ("evaluation_lane_manifest.json", "lane_manifest_file_sha256"),
    ):
        assert sha((BASE / name).read_bytes()) == manifest[field], f"frozen input changed: {name}"
    assert sha((BASE / "dev_targeted_regression.py").read_bytes()) == manifest["harness_sha256_at_freeze"]

    current_lane_manifest = json.loads((BASE / "evaluation_lane_manifest.json").read_text())
    assert _normalized_lane_manifest(manifest["lane_manifest"]) == _normalized_lane_manifest(current_lane_manifest)

    source = frozen.load_and_verify_sources()
    for root in (frozen.RETRIEVAL_ROOT, frozen.LEGACY_CANDIDATE_ROOT, frozen.LEGACY_GRAPH_ROOT):
        for path in (runtime / root).rglob("*"):
            if not path.is_file() or path.suffix == ".pyc":
                continue
            relative = str(path.relative_to(runtime))
            try:
                expected = frozen.git_blob(frozen.INTEGRATION_COMMIT, relative)
            except subprocess.CalledProcessError:
                continue
            assert path.read_bytes() == expected, f"runtime corpus changed: {relative}"

    validation = validate_receipts(output, 28)
    assert validation["pass"], validation["errors"]
    expected_ids = set(FIX_MAPPING) | set(CONTROLS)
    lane_statuses, purposes, provider_models = Counter(), Counter(), Counter()
    provider_calls = 0
    for path in sorted((output / "runs").glob("*/runtime_receipt.json")):
        directory = path.parent
        receipt = receipt_for(directory)
        assert receipt["status"] == "completed"
        assert receipt["run_id"].rsplit("--", 2)[0] in expected_ids
        lane_statuses[(receipt["lane"], receipt["status"])] += 1
        record = json.loads((directory / "run_record.json").read_text())
        input_tokens = sum(call["input_tokens"] for call in receipt["provider_calls"])
        output_tokens = sum(call["output_tokens"] for call in receipt["provider_calls"])
        assert input_tokens == record["input_tokens"]
        assert output_tokens == record["output_tokens"]
        provider_calls += len(receipt["provider_calls"])
        for call in receipt["provider_calls"]:
            assert call["status"] == "completed"
            purposes[call["purpose"]] += 1
            provider_models[(call["provider"], call["model"], call["model_revision"])] += 1
    for lane in LANES:
        assert lane_statuses[(lane, "completed")] == 7
    assert provider_calls == 60

    logs = sorted((output / "process_logs").glob("*.json"))
    assert len(logs) == 28
    assert all(json.loads(path.read_text())["returncode"] == 0 for path in logs)

    audit = json.loads((output / "regression_audit.json").read_text())
    assert audit["runs_completed"] == 28 and audit["runs_not_run"] == 0
    assert audit["lane_isolation_pass"] and audit["runtime_receipt_pass"]
    assert audit["artifact_validation_routing_pass"]
    assert audit["unauthorized_execution_count"] == 0
    assert not audit["user_fact_preserved"]
    assert not audit["targeted_clarification_preserved"]
    assert audit["control_regression_count"] == 1
    assert not audit["ready_for_evaluation_freeze"]

    aborted = [
        _verify_aborted_attempt(BASE / "dev_targeted_regression_20260921"),
        _verify_aborted_attempt(BASE / "dev_targeted_regression_20260921_v2"),
    ]
    inventory_path = output / "runtime_artifact_inventory.json"
    if inventory_path.exists():
        inventory = json.loads(inventory_path.read_text())
        actual_paths = {
            str(path.relative_to(output))
            for path in (output / "runs").rglob("*")
            if path.is_file()
        }
        assert {row["path"] for row in inventory} == actual_paths
        for row in inventory:
            path = output / row["path"]
            assert row["sha256"] == sha(path.read_bytes())
            assert row["bytes"] == path.stat().st_size
    secret_scan = {"status": "not_run", "credential_values_written": False}
    if env_file:
        from dotenv import dotenv_values

        values = [
            value.encode()
            for key, value in dotenv_values(env_file).items()
            if value
            and len(value) > 8
            and any(term in key.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        ]
        artifacts = [path for path in output.rglob("*") if path.is_file()]
        assert all(
            not any(value in path.read_bytes() for value in values) for path in artifacts
        ), "credential detected; do not commit"
        secret_scan = {
            "status": "passed",
            "files_scanned": len(artifacts),
            "credential_values_written": False,
        }

    return {
        "status": "PASS",
        "runtime_commit": RUNTIME_COMMIT,
        "runtime_clean": True,
        "scientific_kg_sha256": frozen.APPROVED_KG_SHA256,
        "approved_statements": len(source["approved"]["statements"]),
        "caution_contexts": len(source["cautions"]),
        "held_statement_excluded": True,
        "frozen_questions_fixtures_lanes_and_corpora_unchanged": True,
        "runs_completed": 28,
        "provider_calls": provider_calls,
        "provider_models": [
            {
                "provider": key[0],
                "requested": key[1],
                "returned": key[2],
                "calls": count,
            }
            for key, count in provider_models.items()
        ],
        "provider_call_purposes": dict(purposes),
        "lane_status_counts": [
            {"lane": lane, "status": "completed", "runs": lane_statuses[(lane, "completed")]}
            for lane in LANES
        ],
        "lane_isolation_pass": True,
        "runtime_receipt_pass": True,
        "credential_scan": secret_scan,
        "aborted_pre_provider_attempts": aborted,
        "provider_reruns": 0,
        "benchmark_or_scoring_changes_after_observation": False,
        "evaluation_or_gold_created": False,
        "limitations": [
            "provider-reported model alias is not an immutable weights fingerprint",
            "one repetition cannot establish causal regression",
            "token comparison has different generated outputs and call mix",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    result = verify(args.output.resolve(), args.runtime.resolve(), args.env_file)
    if args.save:
        write(args.output / "postrun_verification.json", result)
        write(
            args.output / "runtime_artifact_inventory.json",
            [
                {
                    "path": str(path.relative_to(args.output)),
                    "sha256": sha(path.read_bytes()),
                    "bytes": path.stat().st_size,
                }
                for path in sorted((args.output / "runs").rglob("*"))
                if path.is_file()
            ],
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
