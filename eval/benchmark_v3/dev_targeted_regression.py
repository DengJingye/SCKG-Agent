"""Targeted regression runner for the accepted 07 DEV runtime hardening.

Selection is derived mechanically from the prior canonical failure attribution.
The frozen questions, corpora, product prompts and provider arguments are not edited.
Each unit is a fresh process/session and every artifact is write-once.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time

import jsonschema

# Workers execute with the detached runtime as cwd. Add the evaluation worktree
# explicitly so the harness imports itself, while product modules are still
# inserted from the immutable runtime inside preflight/worker.
EVAL_ROOT = Path(__file__).resolve().parents[2]
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from eval.benchmark_v3.dev_pilot import (
    Capture,
    canonical,
    isolation,
    read_rows,
    render_input,
    sha,
    write,
)


BASE = Path(__file__).resolve().parent
RUNTIME_COMMIT = "0cfc390ab398ff5d48e5e68440d8dee36227b4b0"
APPROVED_SHA = "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
LANES = ("llm_only", "generic_rag", "legacy_kg", "scientific_kg")
CONTROLS = ("dev-K01-hvg-input-b", "dev-O02")
FIX_MAPPING = {
    "dev-K01-hvg-input-a": "user_fact_preservation",
    "dev-K02-pca-chunked-a": "user_fact_preservation",
    "dev-K03-reference-annotation-b": "user_fact_preservation",
    "dev-K04-evidence-version-b": "targeted_clarification",
    "dev-W02": "artifact_validation_routing",
}


def assert_runtime(root: Path) -> str:
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != RUNTIME_COMMIT:
        raise ValueError("targeted regression runtime commit mismatch")
    subprocess.run(["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--"],
                   check=True, stdout=subprocess.DEVNULL)
    return head


def select_cases():
    previous = BASE / "dev_pilot_20260921"
    result_index = json.loads((previous / "result_index.json").read_text())
    attribution_path = previous / result_index["canonical_attribution"]
    failures = json.loads(attribution_path.read_text())
    selected_rows = [row for row in failures
                     if row["attribution"]["stage"] in {"validation-governance", "routing"}]
    affected = sorted({row["run_id"].rsplit("--", 2)[0] for row in selected_rows})
    if affected != sorted(FIX_MAPPING):
        raise ValueError(f"mechanical affected set changed: {affected}")
    if "dev-W01" in affected or set(affected) & set(CONTROLS):
        raise ValueError("W01/control leaked into affected set")
    return affected, selected_rows, {
        "result_index_sha256": sha((previous / "result_index.json").read_bytes()),
        "attribution_sha256": sha(attribution_path.read_bytes()),
        "amendments_sha256": sha((previous / "attribution_amendments.json").read_bytes()),
        "canonical_attribution": str(attribution_path.relative_to(BASE)),
    }


def preflight(root: Path, env_file: Path):
    assert_runtime(root)
    os.environ["SCKG_ENV_FILE"] = str(env_file)
    sys.path.insert(0, str(root))
    from agent.research_chat_service import ResearchChatService
    from agent.research_runtime import build_chat_retrieval, runtime_configuration_status

    status = runtime_configuration_status()
    lanes = []
    for lane in LANES:
        retrieval = build_chat_retrieval(Path(tempfile.mkdtemp(prefix="sckg-targeted-preflight-")))
        service = ResearchChatService(retrieval=retrieval, dense_default_enabled=False,
                                      evaluation_retrieval_profile=lane)
        lanes.append({"lane": lane, "profile": retrieval.profile,
                      "backend_class": type(service.retrieval).__module__ + "." + type(service.retrieval).__name__,
                      "approved_hash": retrieval.approved.manifest["approved_kg_sha256"],
                      "approved_statements": len(retrieval.approved.allowlist)})
    if any(row["approved_hash"] != APPROVED_SHA for row in lanes):
        raise ValueError("approved consumer hash mismatch")
    return {"status": "ready" if status["credentials_present"] and not status["disabled"] else "blocked",
            "runtime_commit": RUNTIME_COMMIT, "configuration": status, "lane_initialization": lanes,
            "W01": {"status": "excluded", "reason": "targeted regression instructions: W01 not rerun"},
            "provider_calls": 0}


def initialize(args):
    pre = preflight(args.runtime, args.env_file)
    if pre["status"] != "ready":
        raise RuntimeError("configured provider unavailable/disabled; no calls attempted")
    affected, selection_rows, provenance = select_cases()
    cases = {c["scenario_id"]: c for c in read_rows(BASE / "development_scenarios.jsonl")}
    fixtures = json.loads((BASE / "development_fixtures.json").read_text())
    selected_ids = affected + list(CONTROLS)
    previous_inputs = json.loads((BASE / "dev_pilot_20260921/inputs.json").read_text())
    for case_id in selected_ids:
        if render_input(cases[case_id], fixtures) != previous_inputs[case_id]["rendered_query"]:
            raise ValueError(f"frozen rendered question changed: {case_id}")
    rng = random.Random(2026092102)
    case_order = list(selected_ids)
    rng.shuffle(case_order)
    schedule = []
    for case_id in case_order:
        lane_order = list(LANES)
        rng.shuffle(lane_order)
        for lane in lane_order:
            query = previous_inputs[case_id]["rendered_query"]
            schedule.append({"run_id": f"{case_id}--{lane}--targeted-r0", "case_id": case_id,
                             "lane": lane, "repetition": 0, "input_sha256": sha(query.encode())})
    lane_manifest = json.loads((BASE / "evaluation_lane_manifest.json").read_text())
    lane_manifest["baseline_truth"] = {
        "integration_commit": RUNTIME_COMMIT,
        "rule": "07 accepted hardened runtime; lane knowledge sources remain those in the frozen manifest",
        "prior_lane_manifest_commit": "5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee",
    }
    for lane in lane_manifest["lanes"]:
        lane["implementation_commit"] = RUNTIME_COMMIT
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "preflight.json", pre)
    inputs = {case_id: previous_inputs[case_id] for case_id in selected_ids}
    write(args.output / "inputs.json", inputs)
    manifest = {
        "experiment_id": "dev-targeted-regression-20260921-v3",
        "phase": "DEV-TARGETED-REGRESSION", "implementation_commit": RUNTIME_COMMIT,
        "benchmark_commit_before_run": subprocess.check_output(
            ["git", "-C", str(BASE), "rev-parse", "HEAD"], text=True).strip(),
        "harness_sha256_at_freeze": sha(Path(__file__).read_bytes()),
        "scenario_file_sha256": sha((BASE / "development_scenarios.jsonl").read_bytes()),
        "fixture_file_sha256": sha((BASE / "development_fixtures.json").read_bytes()),
        "lane_manifest_file_sha256": sha((BASE / "evaluation_lane_manifest.json").read_bytes()),
        "approved_kg_sha256": APPROVED_SHA, "lane_manifest": lane_manifest,
        "selection": {"rule": "unique scenario IDs with canonical final stage validation-governance or routing, then direct fix mapping",
                      "affected_scenarios": affected, "fix_mapping": FIX_MAPPING,
                      "source_rows": selection_rows, "provenance": provenance,
                      "control_scenarios": list(CONTROLS), "W01_excluded": True},
        "generator": pre["configuration"], "repetitions": 1, "schedule_seed": 2026092102,
        "provider_seed": None, "deterministic_provider_claimed": False,
        "budgets": {"provider_parameters": "unchanged accepted 07 runtime parameters/timeouts",
                    "unit_watchdog_seconds": 360, "maximum_concurrent_units": 4,
                    "no_automatic_reruns": True},
        "schedule": schedule, "formal_gold_created": False,
        "coverage_status": "unchanged/unknown; targeted runtime regression is not a coverage audit",
        "forbidden_changes": ["questions", "scoring criteria", "KG", "RAG corpus", "product prompt",
                              "taxonomy", "seed expansion", "W01 execution", "performance-driven tuning"],
    }
    write(args.output / "manifest.json", manifest)
    print(canonical({"status": "initialized", "affected": affected, "controls": CONTROLS,
                     "expected_runs": len(schedule)}))


def worker(args):
    assert_runtime(args.runtime)
    os.environ["SCKG_ENV_FILE"] = str(args.env_file)
    sys.path.insert(0, str(args.runtime))
    from agent.research_chat_service import ResearchChatService
    from agent.research_runtime import build_chat_retrieval
    from core.evaluation_models import EvaluationRunRecord
    from core.privacy_policy import OutboundDisclosureService, PrivacyMode
    from core.trace_context import TraceCollector

    manifest = json.loads((args.output / "manifest.json").read_text())
    unit = next(row for row in manifest["schedule"] if row["run_id"] == args.run_id)
    source = json.loads((args.output / "inputs.json").read_text())[unit["case_id"]]
    case, query = source["scenario"], source["rendered_query"]
    directory = args.output / "runs" / args.run_id
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "execution_metadata.json", {"harness_sha256": sha(Path(__file__).read_bytes()),
        "runtime_commit": RUNTIME_COMMIT, "python": sys.version, "isolated_process": True,
        "request_id": args.run_id})
    capture = Capture(directory)
    capture.install_provider()
    retrieval = build_chat_retrieval(Path(tempfile.mkdtemp(prefix="sckg-targeted-unit-cache-")))
    capture.install_retrieval(retrieval)
    service = ResearchChatService(retrieval=retrieval, dense_default_enabled=False,
        evaluation_retrieval_profile=unit["lane"], trace_collector=TraceCollector(directory / "trace.jsonl"))
    disclosure = OutboundDisclosureService(audit_path=directory / "disclosure.jsonl")
    prepared = disclosure.prepare({"query": query, "conversation_context": []},
                                  purpose="research_chat_reasoning", provider=manifest["generator"]["provider"])
    consent = disclosure.grant(disclosure_hash=prepared.disclosure.disclosure_hash,
                               session_id=args.run_id, scope="session")
    allowed = disclosure.authorize(mode=PrivacyMode.LOCAL_HYBRID,
        disclosure_hash=prepared.disclosure.disclosure_hash, session_id=args.run_id, consent_id=consent.consent_id)
    runtime = {"privacy_authorized": allowed.allowed, "outbound_authorized": allowed.allowed,
               "privacy_mode": "local_hybrid", "disclosure_hash": prepared.disclosure.disclosure_hash}
    write(directory / "input.json", {"frozen_query": query, "disclosed_query": prepared.payload["query"],
                                     "disclosure_allowed": allowed.allowed, "query_sha256": sha(query.encode())})
    started = time.perf_counter()
    result, error = {}, ""
    try:
        result = service.run(prepared.payload["query"], request_id=args.run_id,
            conversation_id=args.run_id, conversation_context=[], user_runtime_config=runtime)
        write(directory / "output.json", result)
        status = "completed"
    except Exception as exc:
        error, status = type(exc).__name__, "failed"
        write(directory / "error.json", {"error_type": error})
    latency_ms = (time.perf_counter() - started) * 1000
    traces = read_rows(directory / "trace.jsonl") if (directory / "trace.jsonl").exists() else []
    retrieval_spans = [span["span_id"] for trace in traces for span in trace.get("spans", [])
                       if span["stage"] == "RETRIEVAL"]
    context = {"synthesis_calls": [{"call_id": call["call_id"], "request_ref": call["messages_ref"],
        "actual_messages": json.loads((directory / call["messages_ref"]).read_text())["messages"]}
        for call in capture.calls if call["purpose"] in {"synthesis", "support_check"}],
        "product_context_pack": result.get("context_pack", {}), "product_references": result.get("references", [])}
    write(directory / "final_context.json", context)
    snapshots = json.loads((BASE / "coverage_snapshot_manifest.json").read_text())["sources"]
    source_key = {"scientific_kg": "scientific_kg_v2", "legacy_kg": "legacy_kg",
                  "generic_rag": "ordinary_rag"}.get(unit["lane"], "ordinary_rag")
    receipt_requests = []
    if len(capture.retrieval) != len(capture.backend_events):
        raise ValueError("retrieval and actual backend captures are not one-to-one")
    for index, (observed, backend) in enumerate(zip(capture.retrieval, capture.backend_events)):
        receipt_requests.append({"request_id": observed["request_id"], "path": observed["path"],
            "effective_request": backend["request"], "returned_ids": observed["returned_ids"],
            "excluded_ids": observed["excluded_ids"],
            "trace_span_id": retrieval_spans[min(index, len(retrieval_spans) - 1)] if retrieval_spans else "missing-canonical-span",
            "backend": "engine.approved_scientific_kg.ApprovedScientificKG" if backend["backend"] == "approved"
                       else "engine.hybrid_retrieval.HybridRetrievalService",
            "snapshot_digest": snapshots[source_key]["digest"], "final_context_ref": "final_context.json",
            "final_context_sha256": sha(context), "final_context_tokens": None})
    lane_check = isolation(unit["lane"], capture.backend_events, result)
    write(directory / "lane_isolation.json", lane_check)
    receipt = {"schema_version": "sckg-runtime-receipt-v1", "run_id": args.run_id,
        "attempt_id": args.run_id + "--attempt-1", "lane": unit["lane"],
        "experiment_manifest_digest": sha(manifest), "scenario_digest": sha(case),
        "session_id": args.run_id, "status": status,
        "seed": {"scheduling_seed": 2026092102, "provider_seed_supported": None,
                 "requested": None, "actual": None},
        "retrieval_requests": receipt_requests, "provider_calls": capture.calls,
        "artifact_checks": [], "failure_evidence": [], "latency_ms": latency_ms}
    def usage(key):
        values = [call[key] for call in capture.calls]
        return sum(values) if values and all(value is not None for value in values) else None
    record = EvaluationRunRecord(run_id=args.run_id, experiment_id=manifest["experiment_id"],
        case_id=unit["case_id"], repetition=0, status=status,
        observed={"lane": unit["lane"], "answer": result.get("final_report", ""),
                  "product_status": result.get("status"), "runtime_mode": result.get("runtime_mode"),
                  "provider_calls": len(capture.calls)},
        canonical_trace_id=result.get("canonical_trace_id", ""), trace=traces, latency_ms=latency_ms,
        input_tokens=usage("input_tokens"), output_tokens=usage("output_tokens"),
        answer_hash=sha(result.get("final_report", "").encode()), error=error,
        artifact_refs=["runtime_receipt.json", "final_context.json", "output.json" if result else "error.json"])
    schema = json.loads((BASE / "runtime_receipt.schema.json").read_text())
    jsonschema.validate(receipt, schema)
    write(directory / "run_record.json", record.model_dump(mode="json"))
    write(directory / "runtime_receipt.json", receipt)


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
        command = [sys.executable, str(Path(__file__).resolve()), "worker", "--runtime", str(args.runtime),
                   "--env-file", str(args.env_file), "--output", str(args.output), "--run-id", unit["run_id"]]
        try:
            result = subprocess.run(command, cwd=args.runtime, capture_output=True, text=True, timeout=360)
            code, timeout = result.returncode, False
            write(args.output / "process_logs" / f"{unit['run_id']}.json",
                  {"returncode": code, "stdout": result.stdout, "stderr": result.stderr})
        except subprocess.TimeoutExpired:
            code, timeout = None, True
            write(args.output / "process_logs" / f"{unit['run_id']}.json",
                  {"returncode": None, "timeout": True})
        return {"run_id": unit["run_id"], "returncode": code, "timeout": timeout}

    failures = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for future in as_completed([pool.submit(launch, unit) for unit in pending]):
            row = future.result()
            print(canonical(row), flush=True)
            if row["returncode"] != 0:
                failures.append(row)
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
