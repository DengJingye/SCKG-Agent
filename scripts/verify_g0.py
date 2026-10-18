"""Strict, serial plan_v1/G0 engineering checks using the existing supervisor.

No install, provider request or scientific fitting. A passing receipt covers
this engineering selection, not clean-install provenance, browser journeys or
the complete development gate. Historical acceptance scripts are unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_workbench_acceptance import child_environment, junit_result, run_process
from verify_workflow_stage import hashes

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ("tests/test_workbench_tasks.py", "tests/test_workbench_acceptance_runner.py",
         "tests/test_workbench_g0.py")
MIB = 1024**2
LIMITS = {"wall_seconds": 120, "max_rss_bytes": 512 * MIB}


def resource_admission():
    memory = psutil.virtual_memory()
    reserve = max(2 * 1024**3, memory.total // 4)
    required = LIMITS["max_rss_bytes"] + 256 * MIB
    return {"total_bytes": memory.total, "available_bytes": memory.available,
            "reserve_bytes": reserve, "required_bytes": required,
            "allowed": memory.available - reserve > required}


def source_hashes():
    result = hashes()
    paths = [ROOT / "scripts/verify_g0.py", ROOT / "workbench-dependencies.json"]
    paths += list(ROOT.glob("requirements-workbench*.txt"))
    paths += list((ROOT / "release/locks").glob("*workbench*"))
    paths += list((ROOT / ".github/workflows").glob("*"))
    for directory in ("contracts", "runtime_packs", "execution/environments", "tests/fixtures"):
        paths += [p for p in (ROOT / directory).rglob("*") if p.suffix in {".json", ".txt", ".sig", ".pem"}]
    for path in paths:
        if path.is_file():
            result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def read_report(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def evidence_passed(lane, result, output, selectors=()):
    """Exit 0 alone, missing reports, skipped tests or incomplete UI cannot pass."""
    if not result.get("process_ok"):
        return False
    if lane in {"smoke", "regression"}:
        result["junit"] = junit_result(output / f"{lane}.xml", selectors)
        return bool(result["junit"]["ok"] and result["junit"]["skipped"] == 0)
    report = read_report(output / f"{lane}.json")
    if lane == "dependencies":
        return bool(report.get("status") == "passed"
                    and report.get("preflight", {}).get("failures") == []
                    and report.get("probe", {}).get("status") == "passed"
                    and report.get("probe_process", {}).get("returncode") == 0
                    and report.get("pip_check", {}).get("returncode") == 0)
    if lane == "ui":
        observations = report.get("ui_observations", [])
        return bool(report.get("status") == "passed" and report.get("stage") == "complete"
                    and observations and all(not row.get("errors") and not row.get("exceptions")
                                             for row in observations)
                    and report.get("input_form", {}).get("persistent_snapshot_unchanged") is True
                    and report.get("activity") == {"model_calls": 0, "network_attempts": 0,
                                                   "scientific_fits": 0, "human_reviews": 0, "releases": 0})
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    python, output = args.python.expanduser().absolute(), args.output.expanduser().absolute()
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        parser.error("output must be new and must not traverse symlinks")
    if not python.is_file() or not os.access(python, os.X_OK):
        parser.error("python must be an existing executable")
    regression = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_workbench_*.py"))
    if not set(SMOKE).issubset(regression):
        parser.error("required smoke files missing")
    before = source_hashes()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "plan_v1-g0-engineering-v1", "started_at": datetime.now(timezone.utc).isoformat(),
               "python": str(python), "source_hashes": before, "lanes": {}, "passed": False,
               "status": "running", "limits_per_lane": LIMITS,
               "scope": "offline engineering plus full-app AppTest; not browser or scientific qualification",
               "clean_install_claim": False, "configured_provider_calls": 0, "configured_scientific_fits": 0}
    try:
        receipt["code_sha"] = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        receipt["git_status"] = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain=v1"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        receipt["code_sha"] = None
        receipt["git_status"] = "unavailable_source_archive"

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")

    save()
    try:
        with tempfile.TemporaryDirectory(prefix="isolated-", dir=output) as temporary:
            env, removed = child_environment(Path(temporary), None)
            receipt["credential_variable_names_removed"] = removed
            for lane in ("dependencies", "smoke", "regression", "ui"):
                admission = resource_admission()
                if not admission["allowed"]:
                    receipt["lanes"][lane] = {"status": "deferred_resource", "admission": admission}
                    receipt["status"] = "deferred_resource"
                    break
                selectors = SMOKE if lane == "smoke" else regression if lane == "regression" else ()
                if lane == "dependencies":
                    command = [str(python), "-I", "-B", str(ROOT / "scripts/check_workbench_dependencies.py"),
                               "--prefix", str(python.parent.parent), "--profile", "analysis",
                               "--report", str(output / "dependencies.json")]
                elif selectors:
                    command = [str(python), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               *selectors, "--junitxml=" + str(output / f"{lane}.xml")]
                else:
                    command = [str(python), "-I", "-B", str(ROOT / "scripts/smoke_workbench_ui.py"),
                               "--workspace", str(Path(temporary) / "ui"), "--output", str(output / "ui.json")]
                result = run_process(command, cwd=ROOT, env=env, log=output / f"{lane}.log", **LIMITS)
                result["admission"] = admission
                result["passed"] = evidence_passed(lane, result, output, selectors)
                receipt["lanes"][lane] = result
                save()
                if not result["passed"]:
                    receipt["status"] = "failed"
                    break
            else:
                receipt["status"] = "passed"
    except Exception as exc:
        receipt.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)[:1000]})
    finally:
        receipt["source_hashes_unchanged"] = source_hashes() == before
        if not receipt["source_hashes_unchanged"]:
            receipt["status"] = "failed"
        receipt["passed"] = receipt["status"] == "passed"
        save()
    print(json.dumps({"status": receipt["status"], "passed": receipt["passed"],
                      "receipt": str(output / "receipt.json")}))
    return 0 if receipt["passed"] else 3 if receipt["status"] == "deferred_resource" else 1


if __name__ == "__main__":
    raise SystemExit(main())
