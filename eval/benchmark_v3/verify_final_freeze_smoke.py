"""Offline integrity verification for the DEV final freeze smoke."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from eval.benchmark_v3 import run_lane_alignment_audit as frozen
from eval.benchmark_v3.dev_final_freeze_smoke import (
    RUN_MATRIX,
    RUNTIME_COMMIT,
    assert_runtime,
)
from eval.benchmark_v3.dev_pilot import BASE, sha, write
from eval.benchmark_v3.dev_scoring import receipt_for, validate_receipts
from eval.benchmark_v3.verify_targeted_regression import _normalized_lane_manifest


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
    from eval.benchmark_v3 import dev_final_freeze_smoke, dev_targeted_regression

    assert sha(Path(dev_final_freeze_smoke.__file__).read_bytes()) == manifest["runner_sha256_at_freeze"]
    assert sha(Path(dev_targeted_regression.__file__).read_bytes()) == manifest["shared_worker_sha256_at_freeze"]
    current_lane_manifest = json.loads((BASE / "evaluation_lane_manifest.json").read_text())
    assert _normalized_lane_manifest(manifest["lane_manifest"]) == _normalized_lane_manifest(current_lane_manifest)

    prior_inputs = json.loads((BASE / "dev_pilot_20260921/inputs.json").read_text())
    current_inputs = json.loads((output / "inputs.json").read_text())
    assert set(current_inputs) == set(RUN_MATRIX)
    for case_id in RUN_MATRIX:
        assert current_inputs[case_id] == prior_inputs[case_id]

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

    validation = validate_receipts(output, 8)
    assert validation["pass"], validation["errors"]
    statuses, models, purposes = Counter(), Counter(), Counter()
    total_calls = 0
    for path in sorted((output / "runs").glob("*/runtime_receipt.json")):
        directory = path.parent
        receipt = receipt_for(directory)
        assert receipt["status"] == "completed"
        statuses[(receipt["lane"], receipt["status"])] += 1
        record = json.loads((directory / "run_record.json").read_text())
        assert record["input_tokens"] == sum(call["input_tokens"] for call in receipt["provider_calls"])
        assert record["output_tokens"] == sum(call["output_tokens"] for call in receipt["provider_calls"])
        total_calls += len(receipt["provider_calls"])
        for call in receipt["provider_calls"]:
            assert call["status"] == "completed"
            models[(call["provider"], call["model"], call["model_revision"])] += 1
            purposes[call["purpose"]] += 1
    assert statuses == Counter(
        {
            ("llm_only", "completed"): 1,
            ("generic_rag", "completed"): 3,
            ("legacy_kg", "completed"): 1,
            ("scientific_kg", "completed"): 3,
        }
    )
    assert total_calls == 21
    logs = sorted((output / "process_logs").glob("*.json"))
    assert len(logs) == 8
    assert all(json.loads(path.read_text())["returncode"] == 0 for path in logs)

    audit = json.loads((output / "freeze_audit.json").read_text())
    gate_names = (
        "k04_null_missingness_pass",
        "targeted_clarification_pass",
        "user_fact_authority_pass",
        "mixed_segment_gate_pass",
        "scientific_evidence_gate_pass",
        "lane_isolation_pass",
        "receipt_pass",
        "dev_frozen",
        "ready_for_evaluation_freeze",
    )
    assert audit["status"] == "PASS" and all(audit[name] for name in gate_names)
    assert audit["blockers"] == []

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
        "runs_completed": 8,
        "provider_calls": total_calls,
        "provider_models": [
            {
                "provider": key[0],
                "requested": key[1],
                "returned": key[2],
                "calls": count,
            }
            for key, count in models.items()
        ],
        "provider_call_purposes": dict(purposes),
        "lane_status_counts": [
            {"lane": key[0], "status": key[1], "runs": count}
            for key, count in statuses.items()
        ],
        "lane_isolation_pass": True,
        "runtime_receipt_pass": True,
        "freeze_gate_pass": True,
        "credential_scan": secret_scan,
        "provider_reruns": 0,
        "full_dev_rescored": False,
        "evaluation_or_gold_created": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    output, runtime = args.output.resolve(), args.runtime.resolve()
    result = verify(output, runtime, args.env_file)
    if args.save:
        write(output / "postrun_verification.json", result)
        write(
            output / "runtime_artifact_inventory.json",
            [
                {
                    "path": str(path.relative_to(output)),
                    "sha256": sha(path.read_bytes()),
                    "bytes": path.stat().st_size,
                }
                for path in sorted((output / "runs").rglob("*"))
                if path.is_file()
            ],
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
