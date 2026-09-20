"""Execute the frozen 432-unit formal evaluation without retries."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import jsonschema

from eval.benchmark_v3.dev_pilot import Capture, isolation, read_rows, sha, write


BASE = Path(__file__).resolve().parent
OUT = BASE / "formal_evaluation_v1"
FREEZE = OUT / "freeze"
RUNTIME_COMMIT = "f3df9056364200fdc114d9cfd8d71fa76b915219"
APPROVED_SHA = "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
SCHEDULE_SEED = 20260921


def assert_runtime(root: Path) -> None:
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != RUNTIME_COMMIT:
        raise ValueError(f"runtime commit mismatch: {head}")
    subprocess.run(["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--"], check=True, stdout=subprocess.DEVNULL)


def file_sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze() -> dict:
    manifest_path = FREEZE / "evaluation_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["frozen_file_hashes"].items():
        actual = file_sha(FREEZE / name)
        if actual != expected:
            raise ValueError(f"frozen artifact changed: {name}")
    if manifest["runner_sha256"] != file_sha(Path(__file__)):
        raise ValueError("formal runner changed after freeze")
    if manifest["approved_kg_sha256"] != APPROVED_SHA or manifest["runtime_commit"] != RUNTIME_COMMIT:
        raise ValueError("frozen runtime or approved KG identity mismatch")
    if len(manifest["schedule"]) != 432 or manifest["schedule_seed"] != SCHEDULE_SEED:
        raise ValueError("frozen schedule mismatch")
    return manifest


def preflight(runtime: Path, env_file: Path) -> dict:
    assert_runtime(runtime)
    os.environ["SCKG_ENV_FILE"] = str(env_file)
    sys.path.insert(0, str(runtime))
    from agent.research_runtime import build_chat_retrieval, runtime_configuration_status
    from agent.research_chat_service import ResearchChatService
    status = runtime_configuration_status()
    if not status["credentials_present"] or status["disabled"]:
        raise RuntimeError("provider credentials completely unavailable")
    rows = []
    for lane in ("llm_only", "generic_rag", "legacy_kg", "scientific_kg"):
        retrieval = build_chat_retrieval(Path(tempfile.mkdtemp(prefix="sckg-formal-preflight-")))
        service = ResearchChatService(retrieval=retrieval, dense_default_enabled=False, evaluation_retrieval_profile=lane)
        rows.append({"lane": lane, "profile": retrieval.profile,
                     "approved_hash": retrieval.approved.manifest["approved_kg_sha256"],
                     "approved_statements": len(retrieval.approved.allowlist),
                     "backend_class": type(service.retrieval).__module__ + "." + type(service.retrieval).__name__})
    if any(row["approved_hash"] != APPROVED_SHA or row["approved_statements"] != 121 for row in rows):
        raise ValueError("approved consumer invariant failed")
    return {"status": "ready", "runtime_commit": RUNTIME_COMMIT, "configuration": status,
            "lane_initialization": rows, "provider_calls": 0}


def initialize(args) -> None:
    manifest = verify_freeze()
    if (OUT / "run_preflight.json").exists():
        raise FileExistsError("formal run already initialized")
    before = len(list((OUT / "runs").glob("*/runtime_receipt.json"))) if (OUT / "runs").exists() else 0
    if before:
        raise ValueError("provider artifacts exist before formal initialization")
    check = preflight(args.runtime, args.env_file)
    frozen_provider = manifest["provider_config"]
    actual = check["configuration"]
    if frozen_provider.get("provider") not in {actual["provider"], "resolved_at_preflight_and_recorded"}:
        raise ValueError("provider differs from freeze")
    if frozen_provider.get("model") not in {actual["model"], "resolved_at_preflight_and_recorded"}:
        raise ValueError("model differs from freeze")
    write(OUT / "run_preflight.json", check)
    print(json.dumps({"status": "ready", "runs": len(manifest["schedule"]), "provider": actual["provider"], "model": actual["model"]}, sort_keys=True))


def worker(args) -> None:
    assert_runtime(args.runtime)
    manifest = verify_freeze()
    os.environ["SCKG_ENV_FILE"] = str(args.env_file)
    sys.path.insert(0, str(args.runtime))
    from agent.research_chat_service import ResearchChatService
    from agent.research_runtime import build_chat_retrieval
    from core.evaluation_models import EvaluationRunRecord
    from core.privacy_policy import OutboundDisclosureService, PrivacyMode
    from core.trace_context import TraceCollector

    unit = next(row for row in manifest["schedule"] if row["run_id"] == args.run_id)
    source = json.loads((FREEZE / "rendered_inputs.json").read_text())[unit["case_id"]]
    case, query = source["scenario"], source["rendered_query"]
    directory = OUT / "runs" / args.run_id
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "execution_metadata.json", {"harness_sha256": file_sha(Path(__file__)), "runtime_commit": RUNTIME_COMMIT,
          "python": sys.version, "isolated_process": True, "request_id": args.run_id, "freeze_manifest_sha256": file_sha(FREEZE / "evaluation_manifest.json")})
    capture = Capture(directory)
    capture.install_provider()
    retrieval = build_chat_retrieval(Path(tempfile.mkdtemp(prefix="sckg-formal-unit-cache-")))
    capture.install_retrieval(retrieval)
    service = ResearchChatService(retrieval=retrieval, dense_default_enabled=False, evaluation_retrieval_profile=unit["lane"], trace_collector=TraceCollector(directory / "trace.jsonl"))
    disclosure = OutboundDisclosureService(audit_path=directory / "disclosure.jsonl")
    provider = json.loads((OUT / "run_preflight.json").read_text())["configuration"]["provider"]
    prepared = disclosure.prepare({"query": query, "conversation_context": []}, purpose="research_chat_reasoning", provider=provider)
    consent = disclosure.grant(disclosure_hash=prepared.disclosure.disclosure_hash, session_id=args.run_id, scope="session")
    allowed = disclosure.authorize(mode=PrivacyMode.LOCAL_HYBRID, disclosure_hash=prepared.disclosure.disclosure_hash,
                                   session_id=args.run_id, consent_id=consent.consent_id)
    runtime_config = {"privacy_authorized": allowed.allowed, "outbound_authorized": allowed.allowed,
                      "privacy_mode": "local_hybrid", "disclosure_hash": prepared.disclosure.disclosure_hash}
    write(directory / "input.json", {"frozen_query": query, "disclosed_query": prepared.payload["query"],
          "disclosure_allowed": allowed.allowed, "query_sha256": sha(query.encode())})
    started = time.perf_counter()
    result: dict = {}
    error = ""
    try:
        result = service.run(prepared.payload["query"], request_id=args.run_id, conversation_id=args.run_id,
                             conversation_context=[], user_runtime_config=runtime_config)
        write(directory / "output.json", result)
        status = "completed"
    except Exception as exc:  # Provider/runtime failures are formal outcomes.
        error, status = type(exc).__name__, "failed"
        write(directory / "error.json", {"error_type": error, "message_redacted": True})
    latency_ms = (time.perf_counter() - started) * 1000
    traces = read_rows(directory / "trace.jsonl") if (directory / "trace.jsonl").exists() else []
    retrieval_spans = [span["span_id"] for trace in traces for span in trace.get("spans", []) if span["stage"] == "RETRIEVAL"]
    context = {"synthesis_calls": [{"call_id": call["call_id"], "request_ref": call["messages_ref"],
               "actual_messages": json.loads((directory / call["messages_ref"]).read_text())["messages"]}
              for call in capture.calls if call["purpose"] in {"synthesis", "support_check"}],
              "product_context_pack": result.get("context_pack", {}), "product_references": result.get("references", [])}
    write(directory / "final_context.json", context)
    snapshots = json.loads((BASE / "coverage_snapshot_manifest.json").read_text())["sources"]
    source_key = {"scientific_kg": "scientific_kg_v2", "legacy_kg": "legacy_kg", "generic_rag": "ordinary_rag"}.get(unit["lane"], "ordinary_rag")
    if len(capture.retrieval) != len(capture.backend_events):
        # Preserve the run as failed rather than fabricating an effective request.
        status = "failed"; error = error or "RetrievalReceiptCardinalityError"
        if not (directory / "error.json").exists():
            write(directory / "error.json", {"error_type": error, "message_redacted": True})
    receipt_requests = []
    for index, (observed, backend) in enumerate(zip(capture.retrieval, capture.backend_events)):
        receipt_requests.append({"request_id": observed["request_id"], "path": observed["path"], "effective_request": backend["request"],
            "returned_ids": observed["returned_ids"], "excluded_ids": observed["excluded_ids"],
            "trace_span_id": retrieval_spans[min(index, len(retrieval_spans)-1)] if retrieval_spans else "missing-canonical-span",
            "backend": "engine.approved_scientific_kg.ApprovedScientificKG" if backend["backend"] == "approved" else "engine.hybrid_retrieval.HybridRetrievalService",
            "snapshot_digest": snapshots[source_key]["digest"], "final_context_ref": "final_context.json", "final_context_sha256": sha(context), "final_context_tokens": None})
    lane_check = isolation(unit["lane"], capture.backend_events, result)
    write(directory / "lane_isolation.json", lane_check)
    receipt = {"schema_version": "sckg-runtime-receipt-v1", "run_id": args.run_id, "attempt_id": args.run_id + "--attempt-1",
        "lane": unit["lane"], "experiment_manifest_digest": sha(manifest), "scenario_digest": sha(case), "session_id": args.run_id,
        "status": status, "seed": {"scheduling_seed": SCHEDULE_SEED, "provider_seed_supported": None, "requested": None, "actual": None},
        "retrieval_requests": receipt_requests, "provider_calls": capture.calls, "artifact_checks": [],
        "failure_evidence": ([{"classification": "unresolved", "evidence_refs": ["error.json"],
                              "rationale": f"Formal runtime failure retained without post-hoc retry: {error}."}] if error else []),
        "latency_ms": latency_ms}
    def usage(key: str):
        values = [call[key] for call in capture.calls]
        return sum(values) if values and all(value is not None for value in values) else None
    record = EvaluationRunRecord(run_id=args.run_id, experiment_id=manifest["experiment_id"], case_id=unit["case_id"],
        repetition=unit["repetition"], status=status,
        observed={"lane": unit["lane"], "answer": result.get("final_report", ""), "product_status": result.get("status"),
                  "runtime_mode": result.get("runtime_mode"), "provider_calls": len(capture.calls)},
        canonical_trace_id=result.get("canonical_trace_id", ""), trace=traces, latency_ms=latency_ms,
        input_tokens=usage("input_tokens"), output_tokens=usage("output_tokens"), answer_hash=sha(result.get("final_report", "").encode()),
        error=error, artifact_refs=["runtime_receipt.json", "final_context.json", "output.json" if result else "error.json"])
    jsonschema.validate(receipt, json.loads((BASE / "runtime_receipt.schema.json").read_text()))
    write(directory / "run_record.json", record.model_dump(mode="json"))
    write(directory / "runtime_receipt.json", receipt)
    (OUT / "receipts").mkdir(exist_ok=True)
    # A small immutable index copy; the canonical receipt stays with the run.
    write(OUT / "receipts" / f"{args.run_id}.json", {"run_id": args.run_id, "receipt_path": f"runs/{args.run_id}/runtime_receipt.json",
          "receipt_sha256": file_sha(directory / "runtime_receipt.json"), "status": status})


def execute(args) -> None:
    manifest = verify_freeze()
    if not (OUT / "run_preflight.json").exists():
        raise RuntimeError("run preflight has not been recorded")
    pending = []
    for unit in manifest["schedule"]:
        directory = OUT / "runs" / unit["run_id"]
        if directory.exists():
            if not (directory / "runtime_receipt.json").exists():
                raise RuntimeError(f"incomplete formal attempt retained; no automatic retry: {directory}")
            continue
        pending.append(unit)

    def launch(unit: dict) -> dict:
        command = [sys.executable, str(Path(__file__).resolve()), "worker", "--runtime", str(args.runtime),
                   "--env-file", str(args.env_file), "--run-id", unit["run_id"]]
        environment = os.environ.copy()
        evaluation_root = str(BASE.parents[1])
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = evaluation_root + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )
        try:
            result = subprocess.run(command, cwd=args.runtime, env=environment, capture_output=True, text=True, timeout=360)
            row = {"returncode": result.returncode, "timeout": False, "stdout": result.stdout, "stderr": result.stderr}
        except subprocess.TimeoutExpired:
            row = {"returncode": None, "timeout": True, "stdout": "", "stderr": "watchdog timeout; attempt directory retained"}
        write(OUT / "process_logs" / f"{unit['run_id']}.json", row)
        return {"run_id": unit["run_id"], "returncode": row["returncode"], "timeout": row["timeout"]}

    failures = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(launch, unit) for unit in pending]
        for number, future in enumerate(as_completed(futures), 1):
            row = future.result()
            if row["returncode"] != 0:
                failures.append(row)
            print(json.dumps({"progress": number, "pending_at_start": len(pending), **row}, sort_keys=True), flush=True)
    # Provider/runtime failures captured by the worker remain valid formal results.
    # A subprocess that could not write a receipt is a harness failure and is fatal.
    missing = [unit["run_id"] for unit in manifest["schedule"] if not (OUT / "runs" / unit["run_id"] / "runtime_receipt.json").exists()]
    if missing:
        raise SystemExit(f"fatal incomplete attempts retained; no rerun performed: {len(missing)}")
    print(json.dumps({"status": "complete", "receipts": 432, "subprocess_nonzero": len(failures)}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("initialize", "run", "worker"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()
    args.runtime = args.runtime.resolve(); args.env_file = args.env_file.resolve()
    {"initialize": initialize, "run": execute, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
