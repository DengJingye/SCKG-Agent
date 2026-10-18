"""Product chat journeys with real restricted-Python guests and fake science only.

The gateway, ledger, original queue/owner binding, CodeProgramService,
CodeRuntime sandbox/subprocess and independent file validators are real. Only
the scientific subprocess boundary writes conspicuously synthetic artifacts;
no provider, Scrublet fit, production data or biological score is used.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from threading import Event
import sys

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from sckg_workbench.analysis import AnalysisService
from sckg_workbench.chat_runs import ChatRunService
from sckg_workbench.code_program import KIND
from sckg_workbench.code_runtime import CodeRuntime
from sckg_workbench.datasets import DatasetService
from sckg_workbench.storage import content_hash
from tests.test_workbench_agent_loop import app, BUDGET, PASSPHRASE, send as legacy_send
from tests.test_workbench_bad_artifact_journey import _write_synthetic_attempt


INITIAL = 'value = undefined_before_science\nrun = tools.run_scrublet()\nresult = {"run_id": run["run_id"]}'
PATCH = 'run = tools.run_scrublet()\nresult = {"run_id": run["run_id"]}'
ANSWER = "SYNTHETIC_PROGRAM_CHAT: actual code repaired; fake science artifacts only."
FALSE_SUCCESS = "SYNTHETIC_FALSE_FINISH: 科学分析已经成功完成。"
requires_sandbox = pytest.mark.skipif(sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="Actual product code execution requires the supported macOS sandbox")


def sha(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def action(name, *, source="", parent=None, answer=""):
    return {"action": name, "source": source, "parent_source_sha256": parent, "answer": answer}


@pytest.fixture
def program_app(app, tmp_path, monkeypatch):
    # Keep the existing real ModelService/gateway fixture. Register a full
    # tiny AnnData fixture for the actual independent artifact validator.
    source = tmp_path / "synthetic-program-counts.h5ad"
    ad.AnnData(np.ones((12, 4), dtype=np.int32), obs=pd.DataFrame(
        {"donor": ["PRIVATE_PROGRAM_DONOR_NOT_OUTBOUND"] * 12},
        index=[f"PRIVATE_PROGRAM_CELL_{i}" for i in range(12)])).write_h5ad(source)
    asset = DatasetService(app.ledger.workspace).register_local(source)
    app.path = source
    app.options.update(asset_id=asset["asset_id"], execution_mode="python_program_v1",
        dataset_origin="synthetic", dataset_origin_refs=["work:synthetic-program-chat-fixture"])
    app.science = []
    def synthetic_science(service, task, **kwargs):
        # The real Python guest has already invoked the actual server RPC.
        # Reuse existing explicit fake receipt files and real output validators.
        fixture = _write_synthetic_attempt(service, task, "valid")
        app.science.append(fixture)
        return fixture.saved
    monkeypatch.setattr(AnalysisService, "_execute_supervised", synthetic_science)
    monkeypatch.setattr(AnalysisService, "_execute", lambda *a, **k: pytest.fail("No scientific fit is permitted"))
    return app


def send(a, *, request_id="program-chat-one", analysis=True, prompt="Synthetic code execution task"):
    return a.chat.send(a.conversation["id"], prompt, profile_id=a.profile["id"],
        passphrase=PASSPHRASE, budget=deepcopy(BUDGET), use_knowledge=False,
        request_id=request_id, analysis_options=a.options if analysis else None)


def repaired(a):
    a.actions.extend([action("execute_program", source=INITIAL),
        action("repair_program", source=PATCH, parent=sha(INITIAL)), action("finish", answer=ANSWER)])
    return send(a)


def records(a, kind):
    return a.ledger.list_records(kind)


def assert_guest_was_real_and_stopped(a, phases):
    starts, cleanups = records(a, "program_process_started"), records(a, "program_process_cleanup")
    assert len(starts) == len(cleanups) == phases
    assert all(row["root"]["pid"] != os.getpid() and row["root"]["create_time"] > 0 for row in starts)
    assert all(row["cleanup_verified"] is True and not row.get("residual_processes") for row in cleanups)
    assert {row["phase"] for row in starts} == ({"initial", "patch"} if phases == 2 else {"initial"})


@requires_sandbox
def test_real_chat_name_error_typed_patch_and_final_share_original_binding_and_budget(program_app):
    a = program_app
    original = a.path.read_bytes()
    turn = repaired(a)
    assert turn["status"] == "succeeded" and turn["answer"] == ANSWER
    assert len(a.calls) == len(turn["receipts"]) == 3
    assert [step["action"] for step in turn["agent_steps"]] == ["execute_program", "repair_program"]
    initial, patch = [step["result"] for step in turn["agent_steps"]]
    assert initial["status"] == "awaiting_patch" and initial["repair_allowed"] is True
    assert initial["error"]["type"] == "NameError"
    assert patch["status"] == "succeeded"
    assert initial["task_id"] == patch["task_id"] and initial["attempt"] == patch["attempt"] == 1
    assert turn["analysis_task_ids"] == [initial["task_id"]]
    task = AnalysisService(a.ledger.workspace).get_task_snapshot(initial["task_id"])
    assert task["kind"] == KIND and task["status"] == "succeeded" and task["attempt"] == 1
    binding = a.ledger.get_record("chat_child_binding", turn["id"])
    assert binding["task_id"] == task["task_id"] and binding["expected_attempt"] == 1
    assert len(records(a, "task_submission")) == 1 and len(records(a, "program_phase_admission")) == 2
    assert len(records(a, "program_science_admission")) == len(a.science) == 1
    assert [row["operation"] for row in records(a, "program_api_call")] == ["run_scrublet"]
    executions = {row["binding"]["phase"]: row for row in records(a, "program_execution")}
    assert executions["initial"]["status"] == "python_error" and executions["patch"]["status"] == "ok"
    assert executions["patch"]["binding"]["parent_source_sha256"] == sha(INITIAL)
    assert_guest_was_real_and_stopped(a, 2)
    assert turn["agent_budget"]["model_calls"] == 3
    assert turn["agent_budget"]["charged_or_reserved_tokens"] == 360
    assert turn["agent_budget"]["cost_usd"] == pytest.approx(.00042)
    assert a.calls[1]["response_format"]["json_schema"]["schema"]["properties"]["action"]["enum"] == ["repair_program", "finish"]
    assert a.calls[2]["response_format"]["json_schema"]["schema"]["properties"]["action"]["enum"] == ["finish"]
    wire = json.dumps(a.calls, ensure_ascii=False)
    assert json.loads(a.calls[1]["messages"][-2]["content"])["source"] == INITIAL
    assert "PRIVATE_PROGRAM_DONOR_NOT_OUTBOUND" not in wire and "PRIVATE_PROGRAM_CELL_" not in wire
    assert str(a.path) not in wire and "fixture-key" not in wire
    assert "work:synthetic-program-chat-fixture" not in wire
    assert task["input_snapshot"]["expected_doublet_rate"] == .06
    assert a.path.read_bytes() == original
    view = a.chat.view_turn(turn)
    assert view["usable"] and view["analysis_outcome"]["validated_preview"]
    assert view["analysis_outcome"]["summary"]["metrics"]["n_cells"] == 12
    assert view["analysis_outcome"]["summary"]["scientific_truth_verified"] is False
    before = {kind: content_hash(records(a, kind)) for kind in (
        "model_call", "program_execution", "program_phase_admission", "program_science_admission", "task_submission")}
    assert send(a) == turn
    a.chat.view_turn(turn["id"])
    assert before == {kind: content_hash(records(a, kind)) for kind in before}
    assert len(a.science) == 1


@requires_sandbox
def test_provider_unknown_after_real_initial_error_closes_task_without_patch_or_finish(program_app):
    a = program_app
    a.actions.extend([action("execute_program", source=INITIAL), TimeoutError("synthetic provider timeout"),
        action("finish", answer="MUST_NOT_BE_REQUESTED")])
    turn = send(a)
    assert turn["status"] == "result_unknown" and turn["answer"] is None
    assert len(a.calls) == len(turn["receipts"]) == 2
    assert turn["receipts"][-1]["outcome"] == "result_unknown"
    assert a.ledger.get_state("chat_active:" + a.conversation["id"]) == turn["id"]
    assert len(records(a, "program_execution")) == len(records(a, "program_phase_admission")) == 1
    assert records(a, "program_phase_admission")[0]["binding"]["phase"] == "initial"
    assert a.science == [] and records(a, "program_science_admission") == []
    task = AnalysisService(a.ledger.workspace).get_task_snapshot(turn["analysis_task_ids"][0])
    assert task["status"] == "failed"  # Known initial failure; model outcome remains unknown separately.
    assert not a.chat.view_turn(turn)["usable"]
    assert send(a) == turn and len(a.calls) == 2
    assert len(a.actions) == 1
    assert_guest_was_real_and_stopped(a, 1)


@requires_sandbox
@pytest.mark.parametrize("guest_first", [False, True], ids=["never-executed", "guest-without-science"])
def test_false_finish_without_scientific_operation_cannot_become_usable(program_app, guest_first):
    a = program_app
    if guest_first:
        a.actions.append(action("execute_program", source='result = {"run_id": "invented"}'))
    a.actions.append(action("finish", answer=FALSE_SUCCESS))
    turn = send(a)
    assert turn["status"] != "succeeded" and turn["answer"] is None
    assert not a.chat.view_turn(turn)["usable"]
    assert a.science == [] and records(a, "program_science_admission") == []
    assert len(a.calls) == (2 if guest_first else 1)
    if guest_first:
        assert_guest_was_real_and_stopped(a, 1)
    else:
        assert records(a, "program_process_started") == []


@requires_sandbox
@pytest.mark.parametrize("target", ["initial_source", "patch_source", "scientific_artifact"])
def test_real_program_source_or_artifact_tamper_hides_answer_and_excludes_history(program_app, target):
    a = program_app
    turn = repaired(a)
    assert a.chat.view_turn(turn)["usable"]
    if target == "scientific_artifact":
        path = a.science[0].table
        path.write_bytes(path.read_bytes() + b"SYNTHETIC test corruption\n")
    else:
        phase = "initial" if target == "initial_source" else "patch"
        revision = next(row for row in records(a, "program_code_revision") if row["phase"] == phase)
        path = a.ledger.workspace.artifacts_dir / revision["relative_path"]
        path.write_bytes(path.read_bytes() + b"\n# SYNTHETIC source changed after completion\n")
    view = a.chat.view_turn(turn)
    assert not view["usable"] and view["answer"] is None
    assert not view["analysis_outcome"]["validated_preview"]
    a.actions.append("Synthetic follow-up after invalidated program evidence.")
    follow = send(a, request_id="after-program-tamper", analysis=False)
    assert follow["status"] == "succeeded"
    assert turn["id"] in follow["context"]["excluded_turn_ids"]
    assert turn["id"] not in follow["context"]["included_turn_ids"]
    assert ANSWER not in json.dumps(a.calls[-1], ensure_ascii=False)
    assert len(a.calls) == 4 and len(a.science) == 1
    assert len(records(a, "program_execution")) == 2


def test_ordinary_chat_and_fixed_profile_modes_keep_existing_protocol(program_app):
    a = program_app
    a.actions.append("Ordinary fixture answer.")
    ordinary = send(a, analysis=False)
    assert ordinary["status"] == "succeeded" and ordinary["answer"] == "Ordinary fixture answer."
    assert "response_format" not in a.calls[0]
    fixed_options = {key: value for key, value in a.options.items() if key != "execution_mode"}
    a.actions.extend([{"action": "inspect_dataset", "answer": ""},
        {"action": "finish", "answer": "Synthetic bounded profile only; no analysis executed."}])
    fixed = legacy_send(a, request_id="legacy-fixed-profile", analysis_options=fixed_options)
    assert fixed["status"] == "succeeded" and len(a.calls) == 3
    assert [step["action"] for step in fixed["agent_steps"]] == ["inspect_dataset"]
    assert "execution_mode" not in fixed["analysis_options"]
    assert set(a.calls[1]["response_format"]["json_schema"]["schema"]["properties"]) == {"action", "answer"}
    assert records(a, "program_budget") == [] and records(a, "program_process_started") == []
    assert a.science == []


def test_program_mode_ui_choice_and_rerender_do_not_dispatch_or_execute(program_app):
    a = program_app
    def screen(root):
        from pathlib import Path
        from sckg_workbench.storage import Ledger, Workspace
        from sckg_workbench.model_service import ModelService
        from sckg_workbench.ui import _research
        ledger = Ledger(Workspace(Path(root)))
        def forbidden(*args, **kwargs):
            raise AssertionError("Browsing program mode cannot dispatch a provider")
        _research(ledger, ModelService(ledger.workspace, ledger, transport=forbidden))
    ui = AppTest.from_function(screen, args=(str(a.ledger.workspace.root),), default_timeout=15).run()
    assert not ui.exception
    ui.checkbox(key="research_analysis_enabled").check().run()
    assert not ui.exception
    choice = ui.selectbox(key="research_execution_mode")
    assert any("Python" in option for option in choice.options)
    choice.set_value("python_program_v1").run()
    assert not ui.exception and ui.selectbox(key="research_execution_mode").value == "python_program_v1"
    ui.run()
    ui.run()
    assert not ui.exception and a.calls == []
    assert records(a, "model_call") == records(a, "chat_request") == records(a, "task_submission") == []


@requires_sandbox
def test_cancel_actual_running_guest_retains_owner_and_never_requests_patch(program_app, monkeypatch):
    a = program_app
    entered, finished = Event(), Event()
    errors = []
    original_run = CodeRuntime.run
    def observe_real_runtime(runtime, *args, **kwargs):
        progress = kwargs["progress"]
        def observed(event, value):
            progress(event, value)
            if event == "started":
                entered.set()
        return original_run(runtime, *args, **{**kwargs, "progress": observed})
    monkeypatch.setattr(CodeRuntime, "run", observe_real_runtime)
    a.actions.append(action("execute_program", source="while True:\n    pass"))
    turn = a.chat.submit_send(a.conversation["id"], "Synthetic bounded cancellation of a real guest",
        profile_id=a.profile["id"], use_knowledge=False, budget=deepcopy(BUDGET),
        request_id="cancel-program-chat", analysis_options=a.options)
    control = ChatRunService(a.ledger)
    def execute(token):
        try:
            a.chat.process_registered_send(turn["id"], token, passphrase=PASSPHRASE)
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()
    control.launch(turn["id"], execute)
    try:
        assert entered.wait(5), "The actual guest must start before cancellation"
        control.request_cancel(a.conversation["id"], turn["id"])
        assert finished.wait(5), "A stopped guest and its chat owner must finish boundedly"
    finally:
        if not finished.is_set():
            control.request_cancel(a.conversation["id"], turn["id"])
            finished.wait(5)
        from sckg_workbench import chat_runs
        with chat_runs._THREAD_LOCK:
            owner = chat_runs._THREADS.get((str(a.ledger.workspace.root), a.ledger.workspace.namespace))
        if owner is not None:
            owner.join(timeout=5)
            assert not owner.is_alive()
    assert errors == []
    stored = a.chat.turns(a.conversation["id"])[0]
    assert stored["status"] == "cancelled" and stored["answer"] is None
    assert not a.chat.view_turn(stored)["usable"]
    assert len(a.calls) == 1 and len(records(a, "program_phase_admission")) == 1
    assert a.science == []
    assert_guest_was_real_and_stopped(a, 1)
