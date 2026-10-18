"""Real loopback HTTP startup; separate from browser and AppTest qualification.

Reuses the existing process ownership and cleanup helpers. Call through verify_g0
for resource admission and supervision. No browser, model or science is started.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_workbench_acceptance import _cleanup, _owned_processes, child_environment

ROOT = Path(__file__).resolve().parents[1]


def listener_owner(processes, port, entry):
    for process in processes:
        try:
            if str(entry) not in process.cmdline():
                continue
            # connections() is the API in the locked psutil 5.9.8 environment.
            if any(c.status == psutil.CONN_LISTEN and c.laddr.ip == "127.0.0.1"
                   and c.laddr.port == port for c in process.connections(kind="inet")):
                return {"pid": process.pid, "create_time": process.create_time(),
                        "argv": process.cmdline(), "listener_port": port, "address": "127.0.0.1"}
        except psutil.Error:
            continue
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    log_path = output.with_suffix(".server.log")
    if any(p.exists() for p in (output, log_path)) or any(
            p.is_symlink() for p in (output, log_path, *output.parents)):
        parser.error("report and log must be new and must not traverse symlinks")
    output.parent.mkdir(parents=True, exist_ok=True)
    entry = ROOT / "workbench_app.py"
    before = hashlib.sha256(entry.read_bytes()).hexdigest()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    command = [sys.executable, "-I", "-B", "-m", "streamlit", "run", str(entry),
               "--server.address", "127.0.0.1", "--server.port", str(port),
               "--server.headless", "true", "--server.fileWatcherType", "none",
               "--browser.gatherUsageStats", "false"]
    receipt = {"schema": "workbench-real-server-startup-v1", "status": "failed",
               "command": command, "entry_sha256": before, "health": None,
               "listener_owner": None, "cleanup": None, "error": None,
               "scope": "real installed Streamlit loopback health; no browser session or page execution",
               "configured_provider_calls": 0, "configured_scientific_fits": 0}
    process, known = None, {}
    started = time.monotonic()
    # Disable ambient proxies for the local-only request and isolate application
    # state from the user's existing workspace.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with tempfile.TemporaryDirectory(prefix="server-isolated-", dir=output.parent) as temporary:
            env, removed = child_environment(Path(temporary), None)
            env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
            receipt["credential_variable_names_removed"] = removed
            with log_path.open("x") as log:
                try:
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    known[process.pid] = psutil.Process(process.pid).create_time()
                    while time.monotonic() - started < 30:
                        owned = _owned_processes(process.pid, known)
                        if process.poll() is not None:
                            raise RuntimeError("server_exited_before_owned_health")
                        try:
                            with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=0.5) as response:
                                body = response.read(128).decode("utf-8")
                                owner = listener_owner(owned, port, entry)
                                if response.status == 200 and body.strip() == "ok" and owner:
                                    receipt.update(health={"status": response.status, "body": body},
                                                   listener_owner=owner)
                                    break
                        except (OSError, psutil.Error):
                            pass
                        time.sleep(0.05)
                    if not receipt["health"] or not receipt["listener_owner"]:
                        raise RuntimeError("owned_health_not_verified_within_30_seconds")
                finally:
                    if process is not None:
                        receipt["cleanup"] = _cleanup(process.pid, known)
                        process.wait(timeout=5)
                        receipt["server_returncode_after_cleanup"] = process.returncode
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    receipt["entry_unchanged"] = hashlib.sha256(entry.read_bytes()).hexdigest() == before
    receipt["seconds"] = time.monotonic() - started
    if (receipt["error"] is None and receipt["entry_unchanged"] and receipt["health"]
            and receipt["listener_owner"] and receipt["cleanup"]
            and not receipt["cleanup"]["surviving_pids"]):
        receipt["status"] = "passed"
    with output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": receipt["status"], "report": str(output)}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
