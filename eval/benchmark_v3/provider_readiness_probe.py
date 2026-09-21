"""Run a non-formal four-lane provider readiness gate on a DEV-only prompt."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


RUNTIME_COMMIT = "f3df9056364200fdc114d9cfd8d71fa76b915219"
LANES = ("llm_only", "generic_rag", "legacy_kg", "scientific_kg")
QUERY = (
    "Provider readiness smoke（DEV-only，不计分）：我有用于单细胞分析的 raw counts，"
    "请说明 scVI 是否能以此作为输入。不要执行。"
)


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_runtime(runtime: Path) -> None:
    head = subprocess.check_output(
        ["git", "-C", str(runtime), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != RUNTIME_COMMIT:
        raise ValueError(f"runtime commit mismatch: {head}")
    subprocess.run(
        ["git", "-C", str(runtime), "diff", "--exit-code", "HEAD", "--"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def worker(args: argparse.Namespace) -> None:
    assert_runtime(args.runtime)
    os.environ["SCKG_ENV_FILE"] = str(args.env_file)
    sys.path.insert(0, str(args.runtime))

    from agent.research_chat_service import ResearchChatService
    from agent.research_runtime import build_chat_retrieval, runtime_configuration_status
    from core.privacy_policy import OutboundDisclosureService, PrivacyMode
    from eval.benchmark_v3.dev_pilot import Capture, isolation

    directory = args.output / args.lane
    directory.mkdir(parents=True, exist_ok=False)
    configuration = runtime_configuration_status()
    capture = Capture(directory)
    capture.install_provider()
    retrieval = build_chat_retrieval(
        Path(tempfile.mkdtemp(prefix="sckg-readiness-cache-"))
    )
    capture.install_retrieval(retrieval)
    service = ResearchChatService(
        retrieval=retrieval,
        dense_default_enabled=False,
        evaluation_retrieval_profile=args.lane,
    )
    disclosure = OutboundDisclosureService(
        audit_path=directory / "disclosure.jsonl"
    )
    prepared = disclosure.prepare(
        {"query": QUERY, "conversation_context": []},
        purpose="research_chat_reasoning",
        provider=configuration["provider"],
    )
    session_id = f"provider-readiness-{args.lane}"
    consent = disclosure.grant(
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id=session_id,
        scope="session",
    )
    allowed = disclosure.authorize(
        mode=PrivacyMode.LOCAL_HYBRID,
        disclosure_hash=prepared.disclosure.disclosure_hash,
        session_id=session_id,
        consent_id=consent.consent_id,
    )
    result = service.run(
        prepared.payload["query"],
        request_id=session_id,
        conversation_id=session_id,
        conversation_context=[],
        user_runtime_config={
            "privacy_authorized": allowed.allowed,
            "outbound_authorized": allowed.allowed,
            "privacy_mode": "local_hybrid",
            "disclosure_hash": prepared.disclosure.disclosure_hash,
        },
    )
    write(directory / "output.json", result)
    lane_check = isolation(args.lane, capture.backend_events, result)
    write(directory / "lane_isolation.json", lane_check)
    write(
        directory / "receipt.json",
        {
            "lane": args.lane,
            "runtime_commit": RUNTIME_COMMIT,
            "provider": configuration["provider"],
            "model": configuration["model"],
            "query_sha256": hashlib.sha256(QUERY.encode()).hexdigest(),
            "provider_calls": capture.calls,
            "lane_isolation": lane_check,
            "product_status": result.get("status"),
        },
    )


def run(args: argparse.Namespace) -> None:
    assert_runtime(args.runtime)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    def launch(lane: str) -> dict[str, object]:
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
            "--lane",
            lane,
        ]
        environment = os.environ.copy()
        evaluation_root = str(Path(__file__).resolve().parents[2])
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = evaluation_root + (
            os.pathsep + existing if existing else ""
        )
        completed = subprocess.run(
            command,
            cwd=args.runtime,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "lane": lane,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    process_rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(launch, lane) for lane in LANES]
        for future in as_completed(futures):
            process_rows.append(future.result())
    write(args.output / "process_results.json", process_rows)

    rows = []
    errors = []
    for lane in LANES:
        receipt_path = args.output / lane / "receipt.json"
        if not receipt_path.exists():
            errors.append(f"{lane}: worker did not produce a receipt")
            continue
        receipt = json.loads(receipt_path.read_text())
        calls = receipt["provider_calls"]
        failed = [call for call in calls if call["status"] != "completed"]
        missing_usage = [
            call["call_id"]
            for call in calls
            if call["status"] == "completed"
            and (call["input_tokens"] is None or call["output_tokens"] is None)
        ]
        if not calls:
            errors.append(f"{lane}: no provider call captured")
        if failed:
            errors.append(f"{lane}: {len(failed)} provider calls failed")
        if missing_usage:
            errors.append(f"{lane}: provider usage missing for {missing_usage}")
        if not receipt["lane_isolation"]["pass"]:
            errors.append(f"{lane}: lane isolation failed")
        rows.append(
            {
                "lane": lane,
                "provider_calls": len(calls),
                "completed_calls": len(calls) - len(failed),
                "failed_calls": len(failed),
                "input_tokens": sum(call["input_tokens"] or 0 for call in calls),
                "output_tokens": sum(call["output_tokens"] or 0 for call in calls),
                "receipt_sha256": digest(receipt_path),
                "lane_isolation_pass": receipt["lane_isolation"]["pass"],
            }
        )
    providers = {
        (json.loads((args.output / lane / "receipt.json").read_text())["provider"],
         json.loads((args.output / lane / "receipt.json").read_text())["model"])
        for lane in LANES
        if (args.output / lane / "receipt.json").exists()
    }
    if len(providers) != 1:
        errors.append("provider/model differed across lanes")
    summary = {
        "status": "ready" if not errors else "blocked",
        "pass": not errors,
        "formal_run": False,
        "dev_only_prompt": True,
        "runtime_commit": RUNTIME_COMMIT,
        "concurrency": 4,
        "lanes": rows,
        "provider_model": [list(item) for item in sorted(providers)],
        "errors": errors,
    }
    write(args.output / "readiness_summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    if errors:
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "worker"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lane", choices=LANES)
    args = parser.parse_args()
    args.runtime = args.runtime.resolve()
    args.env_file = args.env_file.resolve()
    args.output = args.output.resolve()
    if args.action == "worker" and not args.lane:
        parser.error("worker requires --lane")
    {"run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
