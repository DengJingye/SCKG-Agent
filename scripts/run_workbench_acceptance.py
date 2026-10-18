"""Bounded, serial engineering acceptance for existing offline fixture tests.

Run this supervisor with a healthy Python/psutil installation. The child may use
an isolated PYTHONPATH overlay; no environment repair or scientific run occurs.
Offline application settings and credential removal are not an OS network sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import psutil

ROOT = Path(__file__).resolve().parents[1]
# This public source snapshot carries the workflow milestone tests. The process,
# cleanup and JUnit machinery below is reused from the existing acceptance runner.
# Private development/release suites are not silently required by a fresh clone.
SMOKE = (
    "tests/test_workbench_workflow_chat.py",
    "tests/test_workbench_workflow_chat_ui.py",
    "tests/test_workbench_workflow_inputs.py",
    "tests/test_workbench_workflow_inputs_ui.py",
    "tests/test_workbench_agent_loop.py",
)
EXTRA = ()
PROBE = """import json, psutil, pydantic, streamlit
p = psutil.Process()
print(json.dumps({'probe': 'workbench-runtime-v1',
 'versions': {m.__name__: m.__version__ for m in (psutil, pydantic, streamlit)},
 'psutil_file': psutil.__file__, 'rss': p.memory_info().rss,
 'children_count': len(p.children(recursive=True))}))
"""
CREDENTIAL = re.compile(r"API.?KEY|TOKEN|PASSWORD|PASSPHRASE|SECRET|CREDENTIAL|AUTHORIZATION|PRIVATE.?KEY|ACCESS.?KEY|(?:^|_)KEY$", re.I)


def positive_number(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def selected_tests(repo: Path, suite: str) -> list[str]:
    if suite == "smoke":
        selected = list(SMOKE)
    else:
        selected = sorted(str(p.relative_to(repo)) for p in (repo / "tests").glob("test_workbench_*.py")
                          if p.name != "test_workbench_acceptance_runner.py") + list(EXTRA)
    if not selected or any(not (repo / s.split("::", 1)[0]).is_file() for s in selected):
        raise ValueError("selected test file missing; acceptance cannot silently shrink")
    return selected


def child_environment(isolation: Path, overlay: Path | None, inherited=None) -> tuple[dict, list[str]]:
    inherited = os.environ if inherited is None else inherited
    removed = sorted(k for k in inherited if CREDENTIAL.search(k))
    env = {k: v for k, v in inherited.items() if k not in removed}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME"):
        env.pop(key, None)
    env.update({
        "SCKG_HOME": str(isolation / "legacy"), "SCKG_WORKBENCH_HOME": str(isolation / "workbench"),
        "SCKG_ENV_FILE": str(isolation / "disabled-default-dotenv"),
        "SCKG_PRIVACY_MODE": "strict_offline", "SCKG_EXTERNAL_NETWORK_ALLOWED": "false",
        "SCKG_OFFLINE_LLM": "true", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
        "PYTHONPATH": os.pathsep.join(str(p) for p in ([overlay] if overlay else []) + [ROOT]),
    })
    return env, removed


def _owned_processes(pgid: int, known: dict[int, float]) -> list:
    """Only our fresh process group and previously identified descendants."""
    found = {}
    for process in psutil.process_iter(["pid"]):
        try:
            if os.getpgid(process.pid) == pgid:
                found[process.pid] = process
        except (OSError, psutil.Error):
            continue
    for pid, created in list(known.items()):
        try:
            process = psutil.Process(pid)
            if process.create_time() == created:
                found[pid] = process
        except psutil.Error:
            continue
    for process in list(found.values()):
        try:
            for child in process.children(recursive=True):
                found[child.pid] = child
        except psutil.Error:
            continue
    live = []
    for process in found.values():
        try:
            created = process.create_time()
            if process.status() != psutil.STATUS_ZOMBIE:
                known[process.pid] = created
                live.append(process)
        except psutil.Error:
            continue
    return live


def _cleanup(pgid: int, known: dict[int, float]) -> dict:
    processes = _owned_processes(pgid, known)
    initial = sorted(p.pid for p in processes)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        processes = _owned_processes(pgid, known)
        if not processes:
            break
        # Do not signal a process group unless an identified owned member exists.
        if any(_same_group(p.pid, pgid) for p in processes):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                pass
        for process in processes:
            try:
                if not _same_group(process.pid, pgid):
                    process.send_signal(sig)
            except psutil.Error:
                pass
        # Popen must remain the only reaper of its direct child so the actual
        # signal/return code is preserved. psutil.wait_procs could consume it.
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline and _owned_processes(pgid, known):
            time.sleep(0.01)
    return {"found_pids": initial, "surviving_pids": sorted(p.pid for p in _owned_processes(pgid, known))}


def _same_group(pid: int, pgid: int) -> bool:
    try:
        return os.getpgid(pid) == pgid
    except OSError:
        return False


def run_process(command, *, cwd: Path, env: dict, log: Path,
                wall_seconds: float, max_rss_bytes: int, poll_seconds=0.025) -> dict:
    """Run one fresh POSIX process group; preserve logs and actual termination."""
    if not math.isfinite(wall_seconds) or wall_seconds <= 0 or not math.isfinite(max_rss_bytes) or max_rss_bytes <= 0:
        raise ValueError("resource limits must be positive and finite")
    if os.name != "posix":
        raise ValueError("this process-group supervisor requires POSIX")
    start = time.monotonic()
    known, peak, stop, lingering = {}, 0, None, []
    with log.open("x", encoding="utf-8") as stream:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            stream.write(f"launch failed: {type(exc).__name__}: {exc}\n")
            return {"command": command, "returncode": None, "resource_stop": "launch_failed",
                    "peak_rss_bytes": 0, "seconds": time.monotonic() - start,
                    "lingering_after_exit": [], "cleanup": {"found_pids": [], "surviving_pids": []},
                    "process_ok": False, "log": str(log)}
        pgid = process.pid
        try:
            while True:
                owned = _owned_processes(pgid, known)
                rss = 0
                for child in owned:
                    try:
                        rss += child.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, rss)
                if rss > max_rss_bytes:
                    stop = "rss_limit_exceeded"
                    break
                if time.monotonic() - start > wall_seconds:
                    stop = "wall_time_exceeded"
                    break
                if process.poll() is not None:
                    lingering = sorted(p.pid for p in owned if p.pid != process.pid)
                    break
                time.sleep(poll_seconds)
        finally:
            cleanup = _cleanup(pgid, known)
            process.wait(timeout=3)
    return {"command": command, "pid": process.pid, "returncode": process.returncode,
            "resource_stop": stop, "peak_rss_bytes": peak, "seconds": time.monotonic() - start,
            "lingering_after_exit": lingering, "cleanup": cleanup,
            "process_ok": process.returncode == 0 and not stop and not lingering and not cleanup["surviving_pids"],
            "log": str(log)}


def _matches_selector(case, selector: str) -> bool:
    filename, _, node = selector.partition("::")
    module = Path(filename).stem
    file_match = module in case.get("classname", "").split(".") or case.get("file", "").endswith(filename)
    return file_match and (not node or case.get("name", "").split("[", 1)[0] == node)


def junit_result(path: Path, required_selectors=()) -> dict:
    result = {"file": str(path), "valid": False, "tests": 0, "failures": 0,
              "errors": 0, "skipped": 0, "passed": 0, "ok": False}
    try:
        root = ET.parse(path).getroot()
        if root.tag not in ("testsuites", "testsuite"):
            raise ValueError("unrecognized JUnit root")
        cases = list(root.iter("testcase"))
        result.update(tests=len(cases), failures=sum(c.find("failure") is not None for c in cases),
                      errors=sum(c.find("error") is not None for c in cases),
                      skipped=sum(c.find("skipped") is not None for c in cases))
        result["passed"] = sum(not any(c.find(tag) is not None for tag in ("failure", "error", "skipped")) for c in cases)
        for suite in root.iter():
            if suite.tag not in ("testsuites", "testsuite"):
                continue
            subtree = list(suite.iter("testcase"))
            actual = {"tests": len(subtree), **{key: sum(c.find(tag) is not None for c in subtree)
                      for key, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}
            for key, count in actual.items():
                if key in suite.attrib and int(suite.attrib[key]) != count:
                    raise ValueError(f"inconsistent JUnit {key} count")
        critical = []
        for selector in required_selectors:
            matched = [c for c in cases if _matches_selector(c, selector)]
            critical.append({"selector": selector, "cases": len(matched),
                             "ok": bool(matched) and not any(c.find("skipped") is not None for c in matched)})
        result["required_critical"] = critical
        result["valid"] = True
        result["ok"] = (bool(cases) and result["failures"] == 0 and result["errors"] == 0
                        and result["passed"] > 0 and all(c["ok"] for c in critical))
    except (OSError, ET.ParseError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _probe_result(log: Path) -> dict:
    for line in reversed(log.read_text(encoding="utf-8").splitlines()):
        try:
            data = json.loads(line)
            if data.get("probe") == "workbench-runtime-v1":
                return {"ok": set(data.get("versions", {})) == {"psutil", "pydantic", "streamlit"}, "receipt": data}
        except (ValueError, AttributeError):
            continue
    return {"ok": False, "error": "runtime probe receipt absent"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path, dest="child_python")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--suite", choices=("smoke", "workbench"), default="smoke")
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--wall-seconds", type=positive_number, default=180.0, help="wall limit for each serial lane")
    parser.add_argument("--max-rss-mib", type=positive_number, default=2048.0, help="aggregate descendant RSS per lane")
    args = parser.parse_args(argv)
    try:
        # Preserve a venv's executable symlink: resolving it can select the wrong environment.
        python = args.child_python.expanduser().absolute()
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ValueError("child Python must be an existing executable")
        output = args.output.expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise ValueError("output already exists; no overwrite or resume")
        if any(p.is_symlink() for p in (output, *output.parents)):
            raise ValueError("output may not traverse a symlink")
        overlay = args.overlay.expanduser().resolve() if args.overlay else None
        if overlay is not None and not overlay.is_dir():
            raise ValueError("overlay must be an existing directory")
        rss_bytes = args.max_rss_mib * 1024 * 1024
        if not math.isfinite(rss_bytes) or rss_bytes > sys.maxsize:
            raise ValueError("RSS limit exceeds supported byte range")
        tests = selected_tests(ROOT, args.suite)
        # Fail before creating output if the supervising psutil is broken.
        psutil.Process().memory_info()
        output.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError, AttributeError) as exc:
        print(f"acceptance not started: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    limits = {"wall_seconds": args.wall_seconds, "max_rss_bytes": int(rss_bytes)}
    with tempfile.TemporaryDirectory(prefix="isolated-workspaces-", dir=output) as directory:
        env, removed = child_environment(Path(directory), overlay)
        runtime = run_process([str(python), "-c", PROBE], cwd=ROOT, env=env,
                              log=output / "runtime.log", **limits)
        runtime["probe"] = _probe_result(output / "runtime.log")
        runtime["passed"] = runtime["process_ok"] and runtime["probe"]["ok"]
        # Engineering fixtures are independent of the runtime probe; collect both.
        junit = output / "junit.xml"
        engineering = run_process([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                   "--junitxml=" + str(junit), *tests], cwd=ROOT, env=env,
                                  log=output / "pytest.log", **limits)
        selected_files = {s.split("::", 1)[0] for s in tests}
        critical = [s for s in SMOKE if s in tests or s.split("::", 1)[0] in selected_files]
        engineering["junit"] = junit_result(junit, critical)
        engineering["passed"] = engineering["process_ok"] and engineering["junit"]["ok"]
        report = {"schema_version": "workbench-engineering-acceptance-v1", "suite": args.suite,
                  "scope": "selected offline engineering fixtures; not scientific acceptance or an OS network sandbox",
                  "repository": str(ROOT), "child_python": str(python), "supervisor_python": sys.executable,
                  "overlay": str(overlay) if overlay else None, "limits_per_lane": limits,
                  "rss_scope": "sampled aggregate child process group and identified descendants; excludes supervisor",
                  "supervisor_rss_bytes_at_report": psutil.Process().memory_info().rss,
                  "removed_override_variable_names": ["PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME"],
                  "removed_credential_variable_names": removed, "selected_tests": tests,
                  "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                    for p in sorted({s.split("::", 1)[0] for s in tests} | {str(Path(__file__).relative_to(ROOT))})},
                  "lanes": {"runtime_probe": runtime, "engineering": engineering},
                  "passed": runtime["passed"] and engineering["passed"]}
        report["result_kind"] = ("subset_with_skips" if engineering["junit"]["skipped"] else
                                 "workbench_suite_pass" if args.suite == "workbench" else "smoke_subset_pass") if report["passed"] else "failed"
    (output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output / "acceptance.json"), "passed": report["passed"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
