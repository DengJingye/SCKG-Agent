"""Bounded DEV runner over immutable 07 code, with evaluation-only instrumentation.

The source questions, corpus, product prompts and provider arguments are not edited.
One subprocess/session per unit. All artifacts are write-once; resume skips completed
units, never replaces an attempt. No automatic provider retry beyond the frozen code.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent
PIN = "5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee"
APPROVED_SHA = "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
LANES = ("llm_only", "generic_rag", "legacy_kg", "scientific_kg")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def render_input(case, fixtures):
    """Lossless transport of the frozen input; no answer/rubric/source injection."""
    text = case["input"]["query"]
    conditions = case["input"]["conditions"]
    if conditions:
        text += "\n\n已提供的条件（未提供的值不作推断）：\n" + "\n".join(
            f"{k}={v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"
            for k, v in sorted(conditions.items()))
    if case.get("fixture_id") == "empty-artifact":
        text += "\n\n任务中给定的产物与状态：\n" + canonical(fixtures["empty-artifact"])
    return text


def assert_runtime(root):
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        raise ValueError("runtime integration commit mismatch")
    subprocess.run(["git", "-C", str(root), "diff", "--exit-code", "HEAD", "--"], check=True, stdout=subprocess.DEVNULL)
    return head


def preflight(root, env_file):
    assert_runtime(root)
    os.environ["SCKG_ENV_FILE"] = str(env_file)
    sys.path.insert(0, str(root))
    from agent.research_runtime import runtime_configuration_status, build_chat_retrieval
    from agent.research_chat_service import ResearchChatService
    status = runtime_configuration_status()
    checks = []
    for lane in LANES:
        retrieval = build_chat_retrieval(Path(tempfile.mkdtemp(prefix="sckg-dev-cache-")))
        service = ResearchChatService(retrieval=retrieval, dense_default_enabled=False,
                                      evaluation_retrieval_profile=lane)
        checks.append({"lane": lane, "profile": retrieval.profile,
                       "approved_hash": retrieval.approved.manifest["approved_kg_sha256"],
                       "approved_statements": len(retrieval.approved.allowlist),
                       "backend_class": type(service.retrieval).__module__ + "." + type(service.retrieval).__name__})
    # The committed allowlisted wrapper fixes flavor=seurat; the notebook renderer
    # also exposes only n_top_genes, not seurat_v3. Do not widen either interface.
    wrapper_path = root / "execution/wrappers/scanpy_core.py"
    renderer_path = root / "execution/renderers/scanpy_core.py"
    wrapper_text, renderer_text = wrapper_path.read_text(), renderer_path.read_text()
    if 'sc.pp.highly_variable_genes(adata, n_top_genes=n_top, flavor="seurat")' not in wrapper_text:
        raise ValueError("W01 interface preflight must be reviewed for this runtime")
    renderer_hvg = next(line for line in renderer_text.splitlines() if '"highly_variable_genes":' in line)
    if "flavor" in renderer_hvg:
        raise ValueError("W01 renderer capability differs from reviewed preflight")
    return {"status": "ready" if status["credentials_present"] and not status["disabled"] else "blocked",
        "runtime_commit": PIN, "configuration": status, "lane_initialization": checks,
        "W01": {"status": "not_run", "reason": "shared_execution_interface_unavailable",
            "scope": "frozen seurat_v3 task; not a claim that all Scanpy execution is absent",
            "evidence": [{"path": str(p.relative_to(root)), "sha256": sha(p.read_bytes()),
                          "relevant_lines": [line for line in p.read_text().splitlines() if "sc.pp.highly_variable_genes(" in line]}
                         for p in (wrapper_path, renderer_path)]},
        "python": sys.version, "executable": sys.executable,
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("openai", "pydantic", "numpy", "scipy", "jsonschema")},
        "optional_scheduler": "langgraph" if importlib.util.find_spec("langgraph") else "deterministic_graph",
        "provider_calls": 0}


def initialize(args):
    pre = preflight(args.runtime, args.env_file)
    if pre["status"] != "ready":
        raise RuntimeError("configured provider unavailable/disabled; no calls attempted")
    cases = read_rows(BASE / "development_scenarios.jsonl")
    fixtures = json.loads((BASE / "development_fixtures.json").read_text())
    ids = [c["scenario_id"] for c in cases]
    if len(ids) != 14 or len(set(ids)) != 14:
        raise ValueError("expected 14 frozen scenarios")
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / "preflight.json", pre)
    rng = random.Random(20260921)
    others = [c for c in cases if c["scenario_id"] != "dev-K01-hvg-input-a"]
    rng.shuffle(others)
    case_order = [next(c for c in cases if c["scenario_id"] == "dev-K01-hvg-input-a"), *others]
    schedule = []
    for case in case_order:
        lanes = list(LANES)
        rng.shuffle(lanes)
        for lane in lanes:
            schedule.append({"run_id": f"{case['scenario_id']}--{lane}--r0", "case_id": case["scenario_id"],
                             "lane": lane, "repetition": 0, "input_sha256": sha(render_input(case, fixtures).encode())})
    lane_manifest = json.loads((BASE / "evaluation_lane_manifest.json").read_text())
    manifest = {"experiment_id": "dev-pilot-20260921-v1", "phase": "DEV-PILOT-RUN",
        "harness_sha256_at_freeze": sha(Path(__file__).read_bytes()),
        "digest_convention": "SHA256 of canonical JSON; explicit file_sha256 and rendered text use bytes",
        "authority": "00 approval in user message; single-review exception DEV only; formal Gold still requires dual independent review",
        "implementation_commit": PIN, "benchmark_base_commit": "bf73ba04c6d827770c56a07029379040bf82335b",
        "scenario_file_sha256": sha((BASE / "development_scenarios.jsonl").read_bytes()),
        "fixture_file_sha256": sha((BASE / "development_fixtures.json").read_bytes()),
        "lane_manifest_file_sha256": sha((BASE / "evaluation_lane_manifest.json").read_bytes()),
        "approved_kg_sha256": APPROVED_SHA, "lane_manifest": lane_manifest,
        "generator": pre["configuration"], "repetitions": 1, "schedule_seed": 20260921,
        "provider_seed": None, "deterministic_provider_claimed": False,
        "smoke_policy": "first K01a block is part of the 56 scheduled units; no extra scientific repetitions",
        "budgets": {"provider_parameters": "unchanged frozen 07 parameters and timeouts", "unit_watchdog_seconds": 360,
                    "maximum_concurrent_units": 4, "no_automatic_reruns": True},
        "shared_execution_preflight": pre["W01"], "schedule": schedule,
        "data_disclosure": "frozen public/redacted issue titles, authored conditions, tiny project-owned W02 text fixture; no private dataset",
        "formal_gold_created": False, "coverage_status": "unknown; not relabeled from these runs",
        "rubric_authority": "00 scientific boundaries, O triage-only, W02 content validation and approval boundary"}
    write(args.output / "manifest.json", manifest)
    write(args.output / "inputs.json", {c["scenario_id"]: {"scenario": c, "rendered_query": render_input(c, fixtures)} for c in cases})
    print(canonical({"status": "initialized", "expected_runs": len(schedule), "provider": pre["configuration"], "W01": pre["W01"]["reason"]}))


class Capture:
    """Observe actual API boundary without changing provider arguments or responses."""
    def __init__(self, directory):
        self.directory = directory
        self.calls = []
        self.retrieval = []
        self.backend_events = []

    def install_provider(self):
        from openai.resources.chat.completions import Completions
        original = Completions.create
        capture = self

        def observed(client, *args, **kwargs):
            # Only messages/parameters are serialized; never client secrets/headers.
            if args:
                raise ValueError("unexpected positional provider arguments")
            index = len(capture.calls) + 1
            call_id = f"call-{index:02d}"
            stack = {frame.function for frame in inspect.stack()}
            purpose = "routing" if "parse" in stack else "synthesis"
            if "supported_indexes" in str(kwargs.get("messages", [{}])[0]):
                purpose = "support_check"
            row = {"call_id": call_id, "purpose": purpose,
                "provider": urlsplit(str(client._client.base_url)).hostname,
                "model": kwargs["model"], "model_revision": None,
                "messages_ref": f"calls/{call_id}.request.json", "messages_sha256": sha(kwargs["messages"]),
                "parameters": {"temperature": kwargs.get("temperature"), "max_tokens": kwargs.get("max_tokens"),
                               "timeout_seconds": kwargs.get("timeout"), "seed": kwargs.get("seed")},
                "status": "failed", "input_tokens": None, "output_tokens": None,
                "usage_source": "unavailable", "latency_ms": 0.0}
            write(capture.directory / row["messages_ref"], kwargs)
            capture.calls.append(row)
            started = time.perf_counter()
            try:
                response = original(client, **kwargs)
                data = response.model_dump(mode="json")
                write(capture.directory / f"calls/{call_id}.response.json", data)
                row["status"] = "completed"
                row["model_revision"] = data.get("model")
                usage = data.get("usage") or {}
                row["input_tokens"] = usage.get("prompt_tokens")
                row["output_tokens"] = usage.get("completion_tokens")
                row["usage_source"] = "provider_reported" if usage else "unavailable"
                return response
            except Exception as exc:
                write(capture.directory / f"calls/{call_id}.error.json", {"error_type": type(exc).__name__,
                      "http_status": getattr(exc, "status_code", None)})
                raise
            finally:
                row["latency_ms"] = (time.perf_counter() - started) * 1000
                write(capture.directory / f"calls/{call_id}.receipt.json", row)
        Completions.create = observed

    def install_retrieval(self, retrieval):
        for label, backend in (("legacy", retrieval.legacy), ("approved", retrieval.approved)):
            original = backend.search
            def wrapped(*args, _original=original, _label=label, **kwargs):
                self.backend_events.append({"backend": _label, "request": args[0].model_dump(mode="json") if args else None})
                return _original(*args, **kwargs)
            backend.search = wrapped
        original = retrieval.search
        def observed(request):
            index = len(self.retrieval) + 1
            stack = {frame.function for frame in inspect.stack()}
            path = "supplemental" if "_complete_top_tool_evidence" in stack else (
                "search_catalog" if request.include_catalog else "search_evidence" if "_search" in stack else "fallback")
            row = {"request_id": f"retrieval-{index:02d}", "path": path,
                   "effective_request": request.model_dump(mode="json"), "returned_ids": [], "excluded_ids": []}
            self.retrieval.append(row)
            write(self.directory / f"retrieval/{index:02d}.request.json", row)
            result = original(request)
            row["result_ref"] = f"retrieval/{index:02d}.response.json"
            write(self.directory / row["result_ref"], result.model_dump(mode="json"))
            row["returned_ids"] = [hit.chunk_id for hit in result.hits]
            row["excluded_ids"] = (result.scientific_evidence or {}).get("excluded_statement_ids", [])
            return result
        retrieval.search = observed


def isolation(lane, events, result):
    observed = {e["backend"] for e in events}
    allowed = {"llm_only": set(), "generic_rag": {"legacy"}, "legacy_kg": {"legacy"}, "scientific_kg": {"approved"}}[lane]
    errors = []
    if not observed <= allowed:
        errors.append("cross_lane_backend_call")
    for event in events:
        req = event["request"] or {}
        if lane == "generic_rag" and (req.get("use_kg") or req.get("use_scientific_evidence")):
            errors.append("generic_rag_graph_or_scientific_channel_enabled")
        if req.get("enable_dense"):
            errors.append("unexpected_dense_request")
    if lane == "llm_only" and result.get("references"):
        errors.append("llm_only_references_not_empty")
    return {"pass": not errors, "errors": errors, "actual_backend_calls": events,
            "note": "Backend invocation isolation; correctness of generated citations is scored separately."}


def worker(args):
    assert_runtime(args.runtime)
    os.environ["SCKG_ENV_FILE"] = str(args.env_file)
    sys.path.insert(0, str(args.runtime))
    from agent.research_chat_service import ResearchChatService
    from agent.research_runtime import build_chat_retrieval
    from core.privacy_policy import OutboundDisclosureService, PrivacyMode
    from core.trace_context import TraceCollector
    from core.evaluation_models import EvaluationRunRecord
    import jsonschema
    manifest = json.loads((args.output / "manifest.json").read_text())
    unit = next(r for r in manifest["schedule"] if r["run_id"] == args.run_id)
    source = json.loads((args.output / "inputs.json").read_text())[unit["case_id"]]
    case, query = source["scenario"], source["rendered_query"]
    directory = args.output / "runs" / args.run_id
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "execution_metadata.json", {"harness_sha256": sha(Path(__file__).read_bytes()),
        "runtime_commit": PIN, "python": sys.version, "isolated_process": True, "request_id": args.run_id})
    receipt = {"schema_version": "sckg-runtime-receipt-v1", "run_id": args.run_id, "attempt_id": args.run_id + "--attempt-1",
        "lane": unit["lane"], "experiment_manifest_digest": sha(manifest), "scenario_digest": sha(case),
        "session_id": args.run_id, "status": "not_run",
        "seed": {"scheduling_seed": 20260921, "provider_seed_supported": None, "requested": None, "actual": None},
        "retrieval_requests": [], "provider_calls": [], "artifact_checks": [], "failure_evidence": [], "latency_ms": None}
    if unit["case_id"] == "dev-W01":
        receipt["not_run_reason"] = "shared_execution_interface_unavailable"
        jsonschema.validate(receipt, json.loads((BASE / "runtime_receipt.schema.json").read_text()))
        write(directory / "runtime_receipt.json", receipt)
        write(directory / "run_record.json", EvaluationRunRecord(run_id=args.run_id, experiment_id=manifest["experiment_id"],
            case_id=unit["case_id"], status="not_run", error=receipt["not_run_reason"]).model_dump(mode="json"))
        return
    capture = Capture(directory)
    capture.install_provider()
    retrieval = build_chat_retrieval(Path(tempfile.mkdtemp(prefix="sckg-dev-unit-cache-")))
    capture.install_retrieval(retrieval)
    service = ResearchChatService(retrieval=retrieval, dense_default_enabled=False, evaluation_retrieval_profile=unit["lane"],
                                 trace_collector=TraceCollector(directory / "trace.jsonl"))
    disclosure = OutboundDisclosureService(audit_path=directory / "disclosure.jsonl")
    prepared = disclosure.prepare({"query": query, "conversation_context": []}, purpose="research_chat_reasoning",
                                  provider=manifest["generator"]["provider"])
    consent = disclosure.grant(disclosure_hash=prepared.disclosure.disclosure_hash, session_id=args.run_id, scope="session")
    allowed = disclosure.authorize(mode=PrivacyMode.LOCAL_HYBRID, disclosure_hash=prepared.disclosure.disclosure_hash,
                                   session_id=args.run_id, consent_id=consent.consent_id)
    runtime = {"privacy_authorized": allowed.allowed, "outbound_authorized": allowed.allowed,
               "privacy_mode": "local_hybrid", "disclosure_hash": prepared.disclosure.disclosure_hash}
    write(directory / "input.json", {"frozen_query": query, "disclosed_query": prepared.payload["query"],
                                     "disclosure_allowed": allowed.allowed, "query_sha256": sha(query.encode())})
    started = time.perf_counter()
    result, error = {}, ""
    try:
        result = service.run(prepared.payload["query"], request_id=args.run_id, conversation_id=args.run_id,
                             conversation_context=[], user_runtime_config=runtime)
        write(directory / "output.json", result)
        receipt["status"] = "completed"
    except Exception as exc:
        error = type(exc).__name__
        write(directory / "error.json", {"error_type": error})
        receipt["status"] = "failed"
    receipt["latency_ms"] = (time.perf_counter() - started) * 1000
    receipt["provider_calls"] = capture.calls
    traces = read_rows(directory / "trace.jsonl") if (directory / "trace.jsonl").exists() else []
    retrieval_spans = [s["span_id"] for t in traces for s in t.get("spans", []) if s["stage"] == "RETRIEVAL"]
    context = {"synthesis_calls": [{"call_id": c["call_id"], "request_ref": c["messages_ref"],
        "actual_messages": json.loads((directory / c["messages_ref"]).read_text())["messages"]}
        for c in capture.calls if c["purpose"] in {"synthesis", "support_check"}],
        "product_context_pack": result.get("context_pack", {}), "product_references": result.get("references", [])}
    write(directory / "final_context.json", context)
    snapshots = json.loads((BASE / "coverage_snapshot_manifest.json").read_text())["sources"]
    snapshot = snapshots[{"scientific_kg": "scientific_kg_v2", "legacy_kg": "legacy_kg", "generic_rag": "ordinary_rag"}.get(unit["lane"], "ordinary_rag")]
    for r in capture.retrieval:
        receipt["retrieval_requests"].append({k: r[k] for k in ("request_id", "path", "effective_request", "returned_ids", "excluded_ids")})
        receipt["retrieval_requests"][-1].update(trace_span_id=retrieval_spans[0] if retrieval_spans else "missing-canonical-span",
            backend="engine.approved_scientific_kg.ApprovedScientificKG" if unit["lane"] == "scientific_kg" else "engine.hybrid_retrieval.HybridRetrievalService",
            snapshot_digest=snapshot["digest"], final_context_ref="final_context.json", final_context_sha256=sha(context), final_context_tokens=None)
    write(directory / "lane_isolation.json", isolation(unit["lane"], capture.backend_events, result))
    def usage(key):
        values = [c[key] for c in capture.calls]
        return sum(values) if values and all(v is not None for v in values) else None
    record = EvaluationRunRecord(run_id=args.run_id, experiment_id=manifest["experiment_id"], case_id=unit["case_id"],
        repetition=0, status=receipt["status"], observed={"lane": unit["lane"], "answer": result.get("final_report", ""),
        "product_status": result.get("status"), "runtime_mode": result.get("runtime_mode"), "provider_calls": len(capture.calls)},
        canonical_trace_id=result.get("canonical_trace_id", ""), trace=traces, latency_ms=receipt["latency_ms"],
        input_tokens=usage("input_tokens"), output_tokens=usage("output_tokens"),
        answer_hash=sha(result.get("final_report", "").encode()), error=error,
        artifact_refs=["runtime_receipt.json", "final_context.json", "output.json" if result else "error.json"])
    jsonschema.validate(receipt, json.loads((BASE / "runtime_receipt.schema.json").read_text()))
    write(directory / "run_record.json", record.model_dump(mode="json"))
    write(directory / "runtime_receipt.json", receipt)


def execute(args):
    manifest = json.loads((args.output / "manifest.json").read_text())
    pending = []
    for unit in manifest["schedule"]:
        if args.case and unit["case_id"] != args.case:
            continue
        directory = args.output / "runs" / unit["run_id"]
        if directory.exists():
            if not (directory / "runtime_receipt.json").exists():
                raise RuntimeError(f"incomplete attempt retained; inspect before proceeding: {directory}")
            continue
        pending.append(unit)
    def launch(unit):
        command = [sys.executable, str(Path(__file__).resolve()), "worker", "--runtime", str(args.runtime),
                   "--env-file", str(args.env_file), "--output", str(args.output), "--run-id", unit["run_id"]]
        try:
            result = subprocess.run(command, cwd=args.runtime, capture_output=True, text=True, timeout=360)
            code, timeout = result.returncode, False
            # Logs contain no credentials; provider exceptions deliberately record only type/status.
            write(args.output / "process_logs" / f"{unit['run_id']}.json", {"returncode": code, "stdout": result.stdout, "stderr": result.stderr})
        except subprocess.TimeoutExpired:
            code, timeout = None, True
            write(args.output / "process_logs" / f"{unit['run_id']}.json", {"returncode": None, "timeout": True})
        return {"run_id": unit["run_id"], "returncode": code, "timeout": timeout}
    failures = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for future in as_completed([pool.submit(launch, unit) for unit in pending]):
            row = future.result()
            print(canonical(row), flush=True)
            if row["returncode"] != 0:
                failures.append(row)
    if failures:
        raise SystemExit("Incomplete attempts preserved. Inspect harness logs; do not silently rerun.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("initialize", "run", "worker"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--case")
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()
    {"initialize": initialize, "run": execute, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
