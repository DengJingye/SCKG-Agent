"""G0 must reject incomplete evidence without changing historical acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

FILE = Path(__file__).resolve().parents[1] / "scripts/verify_g0.py"
SPEC = importlib.util.spec_from_file_location("g0_under_test", FILE)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize("body, expected", [
    ('<testsuite><testcase classname="tests.test_required" name="ok"/></testsuite>', True),
    ('<testsuite><testcase classname="tests.test_required" name="ok"/>'
     '<testcase classname="tests.test_optional" name="optional"><skipped/></testcase></testsuite>', False),
    ('<testsuite><testcase classname="tests.test_other" name="wrong"/></testsuite>', False),
    ('<testsuite tests="3"><testcase classname="tests.test_required" name="ok"/></testsuite>', False),
    ('<testsuite/>', False),
    ('not XML', False),
])
def test_real_junit_required_identity_and_no_skips(tmp_path, body, expected):
    (tmp_path / "smoke.xml").write_text(body)
    result = {"process_ok": True}
    assert gate.evidence_passed("smoke", result, tmp_path, ("tests/test_required.py",)) is expected


def test_successful_process_without_report_cannot_pass(tmp_path):
    result = gate.run_process([sys.executable, "-I", "-B", "-c", "print('done')"],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, log=tmp_path / "output.log",
        wall_seconds=5, max_rss_bytes=64 * 1024**2)
    assert result["process_ok"] and (tmp_path / "output.log").read_text().strip() == "done"
    for lane in ("dependencies", "smoke", "regression", "ui"):
        assert not gate.evidence_passed(lane, result, tmp_path, ("tests/test_required.py",))


@pytest.mark.parametrize("report", [None, [], {"status": "passed"},
    {"status": "passed", "preflight": {"failures": []}, "probe": {"status": "passed"},
     "probe_process": {"returncode": 0}, "pip_check": {"returncode": 1}}])
def test_dependency_success_label_is_insufficient(tmp_path, report):
    (tmp_path / "dependencies.json").write_text(json.dumps(report))
    assert not gate.evidence_passed("dependencies", {"process_ok": True}, tmp_path)


def test_dependency_requires_probe_and_pip_check_and_supervisor(tmp_path):
    report = {"status": "passed", "preflight": {"failures": []}, "probe": {"status": "passed"},
              "probe_process": {"returncode": 0}, "pip_check": {"returncode": 0}}
    (tmp_path / "dependencies.json").write_text(json.dumps(report))
    assert gate.evidence_passed("dependencies", {"process_ok": True}, tmp_path)
    assert not gate.evidence_passed("dependencies", {"process_ok": False}, tmp_path)


def test_ui_rejects_rendered_errors_even_when_report_says_passed(tmp_path):
    report = {"status": "passed", "stage": "complete", "ui_observations": [{"errors": ["broken"], "exceptions": []}],
              "input_form": {"persistent_snapshot_unchanged": True},
              "activity": {"model_calls": 0, "network_attempts": 0, "scientific_fits": 0,
                           "human_reviews": 0, "releases": 0}}
    (tmp_path / "ui.json").write_text(json.dumps(report))
    assert not gate.evidence_passed("ui", {"process_ok": True}, tmp_path)
    report["ui_observations"][0]["errors"] = []
    (tmp_path / "ui.json").write_text(json.dumps(report))
    assert gate.evidence_passed("ui", {"process_ok": True}, tmp_path)


@pytest.mark.parametrize("extra, allowed", [(0, False), (1, True), (-1, False)])
def test_memory_reserve_boundary(monkeypatch, extra, allowed):
    total = 16 * 1024**3
    available = total // 4 + gate.LIMITS["max_rss_bytes"] + 256 * gate.MIB + extra
    monkeypatch.setattr(gate.psutil, "virtual_memory", lambda: SimpleNamespace(total=total, available=available))
    assert gate.resource_admission()["allowed"] is allowed


def test_resource_refusal_is_recorded_without_launch_and_cannot_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(gate.psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * 1024**3, available=3 * 1024**3))
    monkeypatch.setattr(gate, "run_process", lambda *a, **k: pytest.fail("resource refusal launched a child"))
    output = tmp_path.resolve() / "new-output"
    assert gate.main(["--output", str(output)]) == 3
    raw = (output / "receipt.json").read_bytes()
    result = json.loads(raw)
    assert result["status"] == "deferred_resource" and result["passed"] is False
    assert list(result["lanes"]) == ["dependencies"]
    assert result["source_hashes_unchanged"] is True
    with pytest.raises(SystemExit) as error:
        gate.main(["--output", str(output)])
    assert error.value.code == 2 and (output / "receipt.json").read_bytes() == raw


@pytest.mark.parametrize("failure", ["missing_evidence", "supervisor_error", None])
def test_serial_gate_terminates_on_failure_and_keeps_receipt(tmp_path, monkeypatch, failure):
    """Synthetic lane receipts exercise orchestration, not product qualification."""
    monkeypatch.setattr(gate, "resource_admission", lambda: {"allowed": True})
    calls = []

    def synthetic_process(command, *, log, **kwargs):
        lane = log.stem
        calls.append(lane)
        log.write_text("Synthetic orchestration fixture only.\n")
        if failure == "supervisor_error":
            raise OSError("synthetic supervisor error")
        if failure == "missing_evidence":
            return {"process_ok": True, "returncode": 0}
        if lane == "dependencies":
            value = {"status": "passed", "preflight": {"failures": []}, "probe": {"status": "passed"},
                     "probe_process": {"returncode": 0}, "pip_check": {"returncode": 0}}
        elif lane == "ui":
            value = {"status": "passed", "stage": "complete", "ui_observations": [{"errors": [], "exceptions": []}],
                     "input_form": {"persistent_snapshot_unchanged": True},
                     "activity": {"model_calls": 0, "network_attempts": 0, "scientific_fits": 0,
                                  "human_reviews": 0, "releases": 0}}
        else:
            names = [Path(item).stem for item in command if item.startswith("tests/")]
            xml = '<testsuite>' + ''.join(f'<testcase classname="tests.{name}" name="synthetic"/>' for name in names) + '</testsuite>'
            (log.parent / f"{lane}.xml").write_text(xml)
            return {"process_ok": True, "returncode": 0}
        (log.parent / f"{lane}.json").write_text(json.dumps(value))
        return {"process_ok": True, "returncode": 0}

    monkeypatch.setattr(gate, "run_process", synthetic_process)
    output = tmp_path.resolve() / "serial"
    code = gate.main(["--output", str(output)])
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["clean_install_claim"] is False
    assert receipt["source_hashes_unchanged"] is True
    if failure:
        assert code == 1 and receipt["passed"] is False and calls == ["dependencies"]
    else:
        assert code == 0 and receipt["passed"] is True
        assert calls == ["dependencies", "smoke", "regression", "ui"]
