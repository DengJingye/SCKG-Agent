"""Tiny real subprocess/XML checks; never invoke the workbench suite itself."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import psutil
import pytest


FILE = Path(__file__).resolve().parents[1] / "scripts/run_workbench_acceptance.py"
spec = importlib.util.spec_from_file_location("acceptance_runner_under_test", FILE)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def run(tmp_path, code, *, wall=2, rss=256 * 1024 * 1024):
    return runner.run_process([sys.executable, "-c", code], cwd=tmp_path,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                              log=tmp_path / "child.log", wall_seconds=wall,
                              max_rss_bytes=rss, poll_seconds=0.01)


def test_short_process_succeeds_with_real_receipt(tmp_path):
    result = run(tmp_path, "print('done')")
    assert result["process_ok"] and result["returncode"] == 0
    assert result["peak_rss_bytes"] >= 0 and result["seconds"] > 0
    assert result["cleanup"]["surviving_pids"] == []
    assert (tmp_path / "child.log").read_text().strip() == "done"


@pytest.mark.parametrize("body,ok,counts", [
    ('<testsuite/>', False, (0, 0, 0, 0)),
    ('<testsuite><testcase><skipped/></testcase></testsuite>', False, (1, 0, 0, 1)),
    ('<testsuite><testcase><failure/></testcase></testsuite>', False, (1, 1, 0, 0)),
    ('<testsuite><testcase><error/></testcase></testsuite>', False, (1, 0, 1, 0)),
    ('<testsuites><testsuite><testcase name="actual"/></testsuite></testsuites>', True, (1, 0, 0, 0)),
    ('not xml', False, (0, 0, 0, 0)),
    ('<testsuite tests="1" failures="1"><testcase/></testsuite>', False, (1, 0, 0, 0)),
    ('<testsuite tests="99"><testcase/></testsuite>', False, (1, 0, 0, 0)),
])
def test_junit_actual_case_counts(tmp_path, body, ok, counts):
    xml = tmp_path / "junit.xml"
    xml.write_text(body)
    result = runner.junit_result(xml)
    assert result["ok"] is ok
    assert tuple(result[k] for k in ("tests", "failures", "errors", "skipped")) == counts


def test_exit_zero_without_junit_is_not_acceptance(tmp_path):
    assert run(tmp_path, "pass")["process_ok"]
    assert not runner.junit_result(tmp_path / "absent.xml")["ok"]


@pytest.mark.parametrize("body", [
    '<testcase classname="tests.test_other" name="other"/>',
    '<testcase classname="tests.test_workbench_cli" name="critical"><skipped/></testcase><testcase name="other"/>',
])
def test_critical_cannot_be_missing_or_skipped_among_other_passes(tmp_path, body):
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuite>' + body + '</testsuite>')
    assert not runner.junit_result(xml, ["tests/test_workbench_cli.py"])["ok"]


def test_optional_skip_is_explicit_while_critical_executes(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text('<testsuite><testcase classname="tests.test_workbench_cli" name="critical"/>'
                   '<testcase classname="tests.test_optional" name="optional"><skipped/></testcase></testsuite>')
    result = runner.junit_result(xml, ["tests/test_workbench_cli.py"])
    assert result["ok"] and result["skipped"] == 1


def test_timeout_cleans_process_group_including_child(tmp_path):
    code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True); time.sleep(30)"
    result = run(tmp_path, code, wall=0.35)
    assert result["resource_stop"] == "wall_time_exceeded"
    assert not result["process_ok"] and result["cleanup"]["surviving_pids"] == []
    child_pid = int((tmp_path / "child.log").read_text().strip())
    assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE


def test_successful_parent_with_lingering_child_is_failure_and_cleans(tmp_path):
    code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True); time.sleep(.08)"
    result = run(tmp_path, code)
    assert result["returncode"] == 0 and result["lingering_after_exit"]
    assert not result["process_ok"] and result["cleanup"]["surviving_pids"] == []


def test_rss_limit_is_group_aggregate_and_stops(tmp_path):
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; a=bytearray(60*1024*1024); time.sleep(30)']); time.sleep(30)"
    result = run(tmp_path, code, rss=35 * 1024 * 1024)
    assert result["resource_stop"] == "rss_limit_exceeded" and not result["process_ok"]
    assert result["peak_rss_bytes"] > 35 * 1024 * 1024
    assert not result["cleanup"]["surviving_pids"]


def test_credentials_removed_overlay_first_and_temp_workspaces(tmp_path):
    overlay = tmp_path / "overlay"
    env, removed = runner.child_environment(tmp_path / "isolation", overlay,
        {"OPENAI_API_KEY": "private", "OTHER_TOKEN": "private", "PASSWORD": "private",
         "VAULT_SECRET": "private", "DCS_KEY": "private", "ANTHROPIC_KEY": "private",
         "HTTPS_PROXY": "private", "PATH": "/bin", "PYTHONPATH": "bad",
         "PYTEST_ADDOPTS": "-k nearly_nothing", "PYTEST_PLUGINS": "untrusted_plugin", "PYTHONHOME": "wrong"})
    assert set(removed) == {"OPENAI_API_KEY", "OTHER_TOKEN", "PASSWORD", "VAULT_SECRET", "DCS_KEY", "ANTHROPIC_KEY"}
    assert not any(k in env for k in removed) and "HTTPS_PROXY" not in env
    assert not any(k in env for k in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME"))
    assert env["PYTHONPATH"].split(os.pathsep) == [str(overlay), str(runner.ROOT)]
    assert env["SCKG_ENV_FILE"] == str(tmp_path / "isolation" / "disabled-default-dotenv")
    assert not Path(env["SCKG_ENV_FILE"]).exists()
    assert env["SCKG_HOME"] == str(tmp_path / "isolation/legacy")
    assert env["SCKG_WORKBENCH_HOME"] == str(tmp_path / "isolation/workbench")
    assert env["SCKG_PRIVACY_MODE"] == "strict_offline"


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "0"])
def test_nonpositive_or_nonfinite_limits_rejected(value):
    with pytest.raises(Exception):
        runner.positive_number(value)


def test_existing_output_rejected_before_process(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("must not launch")
    monkeypatch.setattr(runner, "run_process", forbidden)
    assert runner.main(["--python", sys.executable, "--output", str(tmp_path)]) == 2


def test_full_suite_never_recurses_into_runner_tests():
    selected = runner.selected_tests(runner.ROOT, "workbench")
    assert "tests/test_workbench_acceptance_runner.py" not in selected
    assert all(name in selected for name in runner.EXTRA)


def test_runtime_failure_does_not_skip_independent_engineering_lane(tmp_path, monkeypatch):
    calls = []
    def fixture_process(command, *, log, **kwargs):
        calls.append(command)
        log.write_text("runtime import failed" if len(calls) == 1 else "fixtures done")
        if len(calls) == 2:
            (log.parent / "junit.xml").write_text('<testsuite><testcase classname="tests.test_workbench_workflow_chat" name="real-fixture"/></testsuite>')
        return {"process_ok": len(calls) == 2, "returncode": 1 if len(calls) == 1 else 0,
                "resource_stop": None, "peak_rss_bytes": 1, "seconds": 0.01,
                "lingering_after_exit": [], "cleanup": {"found_pids": [], "surviving_pids": []}}
    monkeypatch.setattr(runner, "run_process", fixture_process)
    # The selected path must actually exist for the immutable source receipt;
    # the public snapshot carries workflow tests rather than the legacy CLI suite.
    monkeypatch.setattr(runner, "selected_tests", lambda *a: ["tests/test_workbench_workflow_chat.py"])
    output = tmp_path / "new"
    assert runner.main(["--python", sys.executable, "--output", str(output)]) == 1
    report = json.loads((output / "acceptance.json").read_text())
    assert len(calls) == 2 and not report["passed"]
    assert not report["lanes"]["runtime_probe"]["passed"]
    assert report["lanes"]["engineering"]["passed"]
