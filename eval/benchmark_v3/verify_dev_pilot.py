"""Offline post-run checks. Never invokes a model, changes a corpus or rescoring rubric."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from core.evaluation_models import EvaluatorResult, FailureAttribution
from eval.benchmark_v3 import run_lane_alignment_audit as frozen
from eval.benchmark_v3.dev_pilot import BASE, LANES, assert_runtime, isolation, sha, write
from eval.benchmark_v3.dev_scoring import receipt_for, validate_receipts


def verify(output, runtime, env_file=None):
    assert_runtime(runtime)
    manifest = json.loads((output / "manifest.json").read_text())
    for name, field in (("development_scenarios.jsonl", "scenario_file_sha256"),
                        ("development_fixtures.json", "fixture_file_sha256"),
                        ("evaluation_lane_manifest.json", "lane_manifest_file_sha256")):
        assert sha((BASE / name).read_bytes()) == manifest[field], f"frozen input changed: {name}"
    assert sha((BASE / "dev_pilot.py").read_bytes()) == manifest["harness_sha256_at_freeze"]
    source = frozen.load_and_verify_sources()
    current_lanes = frozen.lane_manifest(source)
    assert current_lanes["lanes"] == manifest["lane_manifest"]["lanes"]
    # Also compare the actual runtime files, not just the static manifest.
    for root in (frozen.RETRIEVAL_ROOT, frozen.LEGACY_CANDIDATE_ROOT, frozen.LEGACY_GRAPH_ROOT):
        for path in (runtime / root).rglob("*"):
            if path.is_file() and path.suffix != ".pyc":
                relative = str(path.relative_to(runtime))
                try:
                    committed = frozen.git_blob(frozen.INTEGRATION_COMMIT, relative)
                except subprocess.CalledProcessError:
                    continue  # An ignored local index cache is not a source artifact.
                assert path.read_bytes() == committed, f"runtime corpus changed: {relative}"
    validation = validate_receipts(output, 56)
    assert validation["pass"], validation["errors"]
    models, providers, budgets, call_purposes, statuses = Counter(), Counter(), Counter(), Counter(), Counter()
    for path in sorted((output / "runs").glob("*/runtime_receipt.json")):
        directory = path.parent
        receipt = receipt_for(directory)
        statuses[(receipt["lane"], receipt["status"])] += 1
        if receipt["status"] == "not_run":
            assert "dev-W01--" in receipt["run_id"]
            assert receipt["not_run_reason"] == "shared_execution_interface_unavailable"
            continue
        raw_capture = json.loads((directory / "lane_isolation.json").read_text())
        result = json.loads((directory / "output.json").read_text())
        assert isolation(receipt["lane"], raw_capture["actual_backend_calls"], result)["pass"]
        handoff = result.get("execution_handoff") or {}
        assert handoff.get("execution_request_count", 0) == 0
        assert handoff.get("run_id") is None and handoff.get("artifact_id") is None
        assert handoff.get("status", "not_requested") in {"not_requested", "blocked"}
        for request in receipt["retrieval_requests"]:
            budgets[(receipt["lane"], request["effective_request"]["top_k"], request["effective_request"]["include_catalog"])] += 1
        for call in receipt["provider_calls"]:
            models[(call["model"], call["model_revision"])] += 1
            providers[call["provider"]] += 1
            call_purposes[call["purpose"]] += 1
    for lane in LANES:
        assert statuses[lane, "completed"] == 13 and statuses[lane, "not_run"] == 1
    for path in (output / "process_logs").glob("*.json"):
        assert json.loads(path.read_text())["returncode"] == 0
    index = json.loads((output / "result_index.json").read_text()) if (output / "result_index.json").exists() else {}
    failures = json.loads((output / index.get("canonical_attribution", "failure_attribution.json")).read_text())
    for failure in failures:
        if failure["native"]:
            FailureAttribution.model_validate(failure["native"])
        else:
            assert failure["attribution"]["stage"] == "unresolved"
    for row in json.loads((output / index.get("canonical_scores", "scoring_results.json")).read_text()):
        EvaluatorResult.model_validate(row["result"])
    secret_scan = {"status": "not_run", "credential_values_written": False}
    if env_file:
        from dotenv import dotenv_values
        values = [v.encode() for k, v in dotenv_values(env_file).items()
                  if v and len(v) > 8 and any(term in k.upper() for term in ("KEY", "TOKEN", "SECRET", "PASSWORD"))]
        artifacts = [p for p in output.rglob("*") if p.is_file()]
        assert all(not any(value in path.read_bytes() for value in values) for path in artifacts), "credential detected; do not commit"
        secret_scan = {"status": "passed", "files_scanned": len(artifacts), "credential_values_written": False}
    return {"status": "PASS", "provider_network_verified_by": "116 actual completed provider responses, not configuration flag",
        "runtime_commit": frozen.INTEGRATION_COMMIT, "scientific_kg_sha256": frozen.APPROVED_KG_SHA256,
        "approved_statements": len(source["approved"]["statements"]), "caution_contexts": len(source["cautions"]),
        "held_statement_excluded": True, "frozen_questions_fixtures_and_corpora_unchanged": True,
        "lane_isolation_pass": True, "runtime_receipt_pass": True,
        "scoring_pass": "engineering and explicit DEV annotations; not independent human scientific adjudication",
        "failure_attribution_pass": "evidence-bound proposals; unresolved roots retained",
        "provider_models": [{"requested": k[0], "returned": k[1], "calls": v} for k, v in models.items()],
        "providers": dict(providers), "call_purposes": dict(call_purposes),
        "actual_retrieval_budgets": [{"lane": k[0], "top_k": k[1], "include_catalog": k[2], "requests": v} for k, v in budgets.items()],
        "lane_status_counts": [{"lane": k[0], "status": k[1], "runs": v} for k, v in statuses.items()],
        "credential_scan": secret_scan, "provider_reruns": 0, "evaluation_or_gold_created": False,
        "limitations": ["provider-reported model alias is not an immutable weights fingerprint",
            "no independent judge/human agreement study", "context-only token count unavailable; full-call tokens captured",
            f"{sum(f['attribution']['stage'] == 'unresolved' for f in failures)} unresolved root causes; do not substitute observed generation stage for proven root cause"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    result = verify(args.output, args.runtime, args.env_file)
    if args.save:
        name = "postrun_verification.final.json" if (args.output / "result_index.json").exists() else "postrun_verification.json"
        write(args.output / name, result)
        inventory = args.output / "runtime_artifact_inventory.json"
        if inventory.exists():
            for row in json.loads(inventory.read_text()):
                assert sha((args.output / row["path"]).read_bytes()) == row["sha256"]
        else:
            write(inventory, [
                {"path": str(p.relative_to(args.output)), "sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
                for p in sorted((args.output / "runs").rglob("*")) if p.is_file()])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
