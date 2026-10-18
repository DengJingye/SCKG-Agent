"""Real service journeys over synthetic receipts/files, never a provider or fit.

Only the scientific subprocess boundary is replaced for artifact scenarios. The
actual submit, ownership hook, queue claim, external H5AD/TSV validators, result
store, queue finish, gateway, loop, chat readback and AppTest remain in use.
The legacy preview metadata flags below are deliberately synthetic test input
required by that historical contract; they are not proof Scrublet ran. Every
receipt carries a conspicuous notice, and no scientific performance is tested.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from types import SimpleNamespace

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from core.execution_models import ExecutionRun
from core.research_workspace_models import PreviewLineageSnapshot, PreviewRunResult
from execution.preview_result_store import PreviewResultStore
from execution.validators.doublet import DoubletValidator
from sckg_workbench.analysis import AnalysisService, _attempt_directory, _attempt_key, validate_outputs
from sckg_workbench.chat import ChatService
from sckg_workbench.dataset_origin import origin_from_snapshot
from sckg_workbench.model_service import ModelService
from sckg_workbench.storage import Ledger, Workspace, content_hash


BUDGET = {"max_input_tokens": 64000, "max_output_tokens": 512,
          "timeout_seconds": 5, "max_cost_usd": 1}
PASSPHRASE = "synthetic-bad-artifact-fixture-only"
FALSE_SUCCESS = "SYNTHETIC_MODEL_FALSE_SUCCESS: 分析已成功完成，所有产物均已验收。"
NOTICE = "SYNTHETIC TEST RECEIPT ONLY: no Scrublet execution, fit or scientific approval"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_synthetic_attempt(service, task, fault):
    """Build files for the *already actually claimed* attempt, not another task.

    Faulty bytes are hashed into the synthetic execution receipt before the
    real external validator reads them. Rejection therefore tests semantics of
    required outputs and exact axes rather than only a hash mismatch.
    """
    asset = service.datasets.get_asset(task["input_snapshot"]["asset_id"])
    source = Path(asset["path"])
    data = ad.read_h5ad(source)
    ids = list(map(str, data.obs_names))
    local = service.workspace.artifacts_dir / "analysis" / _attempt_directory(task)
    research, execution = local / "research", local / "users"
    research.mkdir(parents=True)
    preview, notebook_path = research / "preview.h5ad", research / "notebook.ipynb"
    shutil.copyfile(source, preview)
    notebook_path.write_text(json.dumps({"synthetic_fixture_notice": NOTICE}), encoding="utf-8")
    owner = "workbench-local"
    artifact = "asset-" + content_hash(asset["asset_id"])[:24]
    run_id = "synthetic-bad-artifact-preview"
    outputs = execution / owner / "runs" / run_id
    outputs.mkdir(parents=True)
    parameters = {"expected_doublet_rate": task["input_snapshot"]["expected_doublet_rate"]}
    (outputs / "parameters.json").write_text(json.dumps(parameters), encoding="utf-8")
    metadata = {"fixture_id": "synthetic-preview", "input_hash": _sha(preview),
        "n_cells": len(ids), "n_genes": data.n_vars, "scrublet_version": "0.2.3", "execution_seed": 0,
        "execution_purpose": "representative_preview", "scrublet_actually_executed": True,
        "user_data_used": True, "qualification_mode": False, "preview_only": True,
        "scientific_claim_allowed": False, "synthetic_fixture": False, "public_dataset": False,
        "fixture_notice": NOTICE}
    (outputs / "result_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (outputs / "doublet_score_histogram.png").write_bytes(b"synthetic_fixture:not_a_real_plot")
    rows = [[cell, ".8" if i < 2 else ".1", "true" if i < 2 else "false", ""]
            for i, cell in enumerate(ids)]
    if fault == "axis_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif fault == "duplicate_id":
        rows[1][0] = rows[0][0]
    elif fault == "nan_score":
        rows[0][1] = "nan"
    elif fault == "out_of_range_score":
        rows[0][1] = "1.01"
    elif fault not in {"valid", "missing_required"}:
        raise AssertionError("Unknown synthetic fault")
    table_path = outputs / "doublet_results.tsv"
    table_path.write_text("obs_id\tdoublet_score\tpredicted_doublet\tground_truth_doublet\n" +
        "".join("\t".join(row) + "\n" for row in rows), encoding="utf-8")
    if fault == "missing_required":
        (outputs / "parameters.json").unlink()  # Exclusively this disposable test output.
    now = datetime.now(timezone.utc)
    run = ExecutionRun(request_id="synthetic-request", run_id=run_id, trace_id="synthetic-trace",
        plan_id="synthetic-plan", step_id="synthetic-step", wrapper_id="scrublet_v0_2_3",
        tool_name="Scrublet", tool_version="0.2.3", environment_id="scRNAseq",
        command_argv_redacted=["SYNTHETIC_FIXTURE_NO_EXECUTION"], parameters=parameters,
        input_hash=_sha(preview), start_time=now, end_time=now, runtime_seconds=0, peak_memory_mb=1,
        exit_code=0, stdout_path="synthetic-not-a-path", stderr_path="synthetic-not-a-path",
        status="succeeded", fixture_id="synthetic-preview",
        artifact_paths={p.name: str(p) for p in outputs.iterdir()},
        artifact_hashes={p.name: _sha(p) for p in outputs.iterdir()}, qualification_mode=False,
        synthetic_fixture=False, user_data_used=True, execution_purpose="representative_preview",
        owner_user_id=owner, approval_id="synthetic-contract-fixture-not-human-approval")
    parameter_digest = hashlib.sha256(json.dumps(parameters, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    notebook = {"notebook_id": "synthetic-notebook", "parameter_hash": parameter_digest,
        "step_contract_id": "synthetic-step", "step_contract_version": "1",
        "step_template_digest": "c" * 64, "tool_contract_version": "1"}
    frozen = {"source_sha256": _sha(source), "preview_sha256": _sha(preview),
        "preview_id": "synthetic-preview", "profile_id": "synthetic-profile",
        "notebook_id": "synthetic-notebook", "notebook_sha256": _sha(notebook_path),
        "notebook_path": str(notebook_path), "parameters": parameters, "expected_cells": len(ids),
        "contract_digest": "d" * 64, "environment_digest": "e" * 64}
    lineage = PreviewLineageSnapshot(source_hash=_sha(source), profile_id=frozen["profile_id"],
        preview_id=frozen["preview_id"], preview_hash=_sha(preview), notebook_id=frozen["notebook_id"],
        notebook_hash=_sha(notebook_path), parameter_hash=parameter_digest, step_contract_id="synthetic-step",
        step_contract_version="1", step_template_digest="c" * 64, tool_contract_id="scrublet:0.2.3",
        tool_contract_version="1", tool_contract_digest="d" * 64, environment_id="scRNAseq",
        environment_digest="e" * 64, approval_fingerprint="f" * 64)
    validation = validate_outputs(run, preview_path=preview, source_path=source,
        frozen=frozen, output_root=execution)
    legacy = PreviewRunResult(user_id=owner, artifact_id=artifact, preview_id=frozen["preview_id"],
        notebook_id=frozen["notebook_id"], plan_id=run.plan_id,
        status="validated" if validation["passed"] else "failed", execution_run=run,
        validation_result=DoubletValidator().validate(run, expected_cells=len(ids)), lineage=lineage)
    prepared = {"frozen": frozen, "preview_path": str(preview), "source_path": str(source),
        "output_root": str(execution), "notebook": notebook, "profile": {"profile_id": "synthetic-profile"},
        "preview": {"preview_id": "synthetic-preview"}, "synthetic_fixture_notice": NOTICE,
        "approval": {"approval_id": "synthetic-contract-fixture-not-human-approval", "request_fingerprint": "f" * 64}}
    service.ledger.put_record("analysis_preparation", _attempt_key(task), prepared)
    # Exercise the actual v2 admission and readback chain. This is explicitly
    # an in-process fixture for the substituted subprocess boundary, with the
    # *actual current* test PID/thread identities. It proves neither a child
    # launch nor stdin delivery; separate real-worker tests own those claims.
    import psutil
    from sckg_workbench.analysis_repair import OperationalRecovery, enabled, public_summary
    from sckg_workbench.chat_runs import ChatRunService
    recovery = None
    if enabled(task):
        process = service._process_identity(psutil.Process(os.getpid()))
        started = {"namespace": service.workspace.namespace, "task_id": task["task_id"],
            "attempt": task["attempt"], "payload_digest": task["payload_digest"],
            "fencing_token_digest": content_hash(task["fencing_token"]), "root": process,
            "supervisor": {**process, "native_thread_id": threading.get_native_id(),
                           "thread_ident": threading.get_ident()},
            "original_deadline_epoch": time.time() + 180,
            "synthetic_fixture_notice": "In-process synthetic boundary; no child process was spawned"}
        service.ledger.put_record("analysis_process_started", _attempt_key(task), started)
        control = ChatRunService(service.ledger)
        with service.ledger.transaction() as tx:
            grant = control.issue_worker_start_grant(tx, task)
            control.consume_worker_start_grant(tx, task, grant)
        recovery = OperationalRecovery(service, task, prepared)
        recovery.reserve_initial()
    result_path = PreviewResultStore(workspace_root=research, execution_root=execution).save(legacy)
    saved = {"task_id": task["task_id"], "attempt": task["attempt"], "asset_id": asset["asset_id"],
        "run_id": run_id, "status": "validated" if validation["passed"] else "failed", "validation": validation,
        "execution_run": run.model_dump(mode="json"), "legacy_preview_result": legacy.model_dump(mode="json"),
        "synthetic_fixture_notice": NOTICE, **origin_from_snapshot(task["input_snapshot"])}
    if recovery is not None:
        recovery.save_run("initial", legacy, validation)
        recovery.check_after_run()
        saved["operational_recovery"] = public_summary(status="not_used",
            initial_run_id=run_id, final_run_id=run_id)
    return SimpleNamespace(saved=saved, table=table_path, outputs=outputs, source=source,
        result_path=result_path, task=task, validation=validation)


@pytest.fixture
def journey(tmp_path, monkeypatch):
    ledger = Ledger(Workspace(tmp_path / "workspace"))
    calls, actions, artifacts = [], [], []
    state = {"fault": "valid"}
    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        assert actions, "Unexpected extra synthetic gateway call"
        action = actions.pop(0)
        return {"id": "synthetic-artifact-model-response", "model": "synthetic-returned-model",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            "choices": [{"finish_reason": "stop", "message": {"content":
                json.dumps(action, ensure_ascii=False) if isinstance(action, dict) else action}}]}
    models = ModelService(ledger.workspace, ledger, transport=transport)
    connection = models.create_connection("Synthetic transport only", "https://fixture.invalid/v1",
        "synthetic-key-never-networked", PASSPHRASE)
    profile = models.create_profile("Synthetic artifact journey", "chat", connection["id"],
        "synthetic-requested-model", input_usd_per_million=1, output_usd_per_million=2)
    analysis = AnalysisService(ledger.workspace)
    path = tmp_path / "synthetic-source.h5ad"
    ad.AnnData(np.ones((12, 4), dtype=np.int32),
        obs=pd.DataFrame(index=[f"synthetic-private-cell-{i}" for i in range(12)])).write_h5ad(path)
    asset = analysis.datasets.register_local(path)
    options = {"asset_id": asset["asset_id"], "count_source": "X",
        "count_provenance": NOTICE, "expected_doublet_rate": .06,
        "dataset_origin": "synthetic", "dataset_origin_refs": ["work:synthetic-artifact-journey"]}
    def synthetic_execute(service, task):
        artifact = _write_synthetic_attempt(service, task, state["fault"])
        artifacts.append(artifact)
        return artifact.saved
    monkeypatch.setattr(AnalysisService, "_execute_supervised", synthetic_execute)
    monkeypatch.setattr(AnalysisService, "_execute", lambda *a, **k: pytest.fail("No science fit is authorized"))
    chat = ChatService(ledger, models)
    return SimpleNamespace(ledger=ledger, analysis=analysis, models=models, chat=chat,
        conversation=chat.create_conversation("Synthetic artifact acceptance journey"),
        profile=profile, options=options, calls=calls, actions=actions, artifacts=artifacts,
        state=state, path=path)


def _send(a, *, request_id="synthetic-artifact-send", analysis=True, prompt="Synthetic artifact acceptance task"):
    return a.chat.send(a.conversation["id"], prompt, profile_id=a.profile["id"],
        passphrase=PASSPHRASE, budget=deepcopy(BUDGET), use_knowledge=False,
        request_id=request_id, analysis_options=a.options if analysis else None)


def _run_and_finish(a, answer=FALSE_SUCCESS):
    a.actions.extend([{"action": "run_scrublet", "answer": ""}, {"action": "finish", "answer": answer}])
    return _send(a)


def _assert_no_automatic_repeat(a, turn):
    before = {kind: content_hash(a.ledger.list_records(kind)) for kind in (
        "model_request", "model_call", "analysis_preparation", "analysis_result", "task_submission",
        "analysis_execution_budget", "analysis_inner_run", "analysis_repair_admission")}
    count = len(a.artifacts)
    assert _send(a) == turn
    a.chat.view_turn(turn)
    a.chat.view_turn(turn["id"])
    assert before == {kind: content_hash(a.ledger.list_records(kind)) for kind in before}
    assert len(a.artifacts) == count
    tasks = a.ledger.list_records("task_submission")
    assert len(tasks) == 1
    assert a.analysis.get_task_snapshot(tasks[0]["task_id"])["attempt"] <= 1
    assert a.ledger.list_records("analysis_repair_admission") == []


@pytest.mark.parametrize("fault,failure", [
    ("axis_order", "prediction_axis_mismatch"),
    ("duplicate_id", "prediction_ids_empty_or_duplicate"),
    ("missing_required", "required_artifact_missing"),
    ("nan_score", "score_non_finite_or_out_of_range"),
    ("out_of_range_score", "score_non_finite_or_out_of_range"),
])
def test_real_validator_rejection_overrules_model_finish_and_cannot_enter_context(journey, fault, failure):
    a = journey
    a.state["fault"] = fault
    original = a.path.read_bytes()
    turn = _run_and_finish(a)
    assert len(a.artifacts) == 1 and not a.artifacts[0].validation["passed"]
    assert failure in a.artifacts[0].validation["failures"]
    task = a.analysis.get_task_snapshot(turn["analysis_task_ids"][0])
    assert task["status"] == "failed" and task["attempt"] == 1
    assert task["result"]["synthetic_fixture_notice"] == NOTICE
    assert turn["status"] == "failed" and turn["answer"] is None
    assert turn["error"]["type"] == "AnalysisArtifactRejected"
    assert len(a.calls) == 2 and len(turn["receipts"]) == 2
    assert a.ledger.list_records("chat_agent_decision")[-1]["action"]["answer"] == FALSE_SUCCESS
    view = a.chat.view_turn(turn)
    assert not view["usable"] and view["answer"] is None
    assert not view["analysis_outcome"]["validated_preview"]
    assert a.path.read_bytes() == original
    _assert_no_automatic_repeat(a, turn)
    a.actions.append("Synthetic follow-up, independent of rejected model prose.")
    follow = _send(a, request_id="synthetic-follow-up", analysis=False, prompt="Explain current limitations")
    assert follow["status"] == "succeeded"
    assert turn["id"] in follow["context"]["excluded_turn_ids"]
    assert turn["id"] not in follow["context"]["included_turn_ids"]
    assert FALSE_SUCCESS not in json.dumps(a.calls[-1], ensure_ascii=False)
    assert len(a.artifacts) == 1


def test_valid_synthetic_positive_control_remains_usable_but_not_scientific_truth(journey):
    a = journey
    turn = _run_and_finish(a, answer="SYNTHETIC positive control: engineering artifacts only.")
    assert len(a.artifacts) == 1 and a.artifacts[0].validation["passed"]
    assert turn["status"] == "succeeded"
    view = a.chat.view_turn(turn)
    assert view["usable"] and view["analysis_outcome"]["validated_preview"]
    summary = view["analysis_outcome"]["summary"]
    assert summary["status"] == "validated_preview_summary"
    assert summary["metrics"]["n_cells"] == 12
    assert summary["dataset_origin"] == "synthetic"
    assert summary["scientific_truth_verified"] is False and summary["scientific_claim_allowed"] is False
    assert summary["operational_recovery"]["status"] == "not_used"
    assert len(a.ledger.list_records("analysis_execution_budget")) == 1
    assert len(a.ledger.list_records("analysis_inner_run")) == 1
    assert len(a.calls) == 2
    _assert_no_automatic_repeat(a, turn)


def test_later_file_tamper_invalidates_previously_usable_answer_and_history(journey):
    a = journey
    answer = "SYNTHETIC_ORIGINALLY_VALID_ANSWER"
    turn = _run_and_finish(a, answer=answer)
    assert a.chat.view_turn(turn)["usable"]
    table = a.artifacts[0].table
    table.write_bytes(table.read_bytes().replace(b"\t.8\t", b"\t.7\t", 1))
    view = a.chat.view_turn(turn)
    assert not view["usable"] and view["answer"] is None
    assert view["current_status"] in {"result_invalidated", "analysis_failed"}
    assert not view["analysis_outcome"]["validated_preview"]
    a.actions.append("Synthetic follow-up after artifact change.")
    follow = _send(a, request_id="after-tamper", analysis=False)
    assert turn["id"] in follow["context"]["excluded_turn_ids"]
    assert answer not in json.dumps(a.calls[-1], ensure_ascii=False)
    assert len(a.artifacts) == 1 and len(a.calls) == 3


def test_explicit_later_retry_cannot_bless_original_legacy_failed_attempt(journey):
    a = journey
    a.state["fault"] = "axis_order"
    original = _run_and_finish(a)
    task_id = original["analysis_task_ids"][0]
    assert a.analysis.get_task_snapshot(task_id)["status"] == "failed"
    # Model an explicitly synthetic pre-gate historical row. The authoritative
    # original decision/step/attempt is retained, without a newer child binding.
    legacy_id = "synthetic-legacy-before-completion-gate"
    request = deepcopy(a.ledger.get_record("chat_request", original["id"]))
    request.update(id=legacy_id, request_id="synthetic-legacy-event", sequence=2,
        request_hash=content_hash({"synthetic_legacy": legacy_id}))
    result = deepcopy(a.ledger.get_record("chat_result", original["id"]))
    result.update(status="succeeded", answer=FALSE_SUCCESS, error=None,
        synthetic_fixture_notice="Synthetic historical compatibility row, never a new valid result")
    a.ledger.put_record("chat_request", legacy_id, request)
    a.ledger.put_record("chat_result", legacy_id, result)
    assert a.ledger.get_record("chat_child_binding", legacy_id) is None
    assert not a.chat.view_turn(legacy_id)["usable"]
    # This explicit queue operation is test setup, not an autonomous recovery.
    a.analysis.queue.retry(task_id, confirm_no_duplicate=True)
    a.state["fault"] = "valid"
    retried = a.analysis.run_once(task_id=task_id)
    assert retried["status"] == "succeeded" and retried["attempt"] == 2
    assert a.analysis.get_public_result_summary(task_id, attempt=2,
        expected_run_id=retried["result"]["run_id"])["status"] == "validated_preview_summary"
    view = a.chat.view_turn(legacy_id)
    assert not view["usable"] and view["answer"] is None
    assert not view["analysis_outcome"]["validated_preview"]
    assert len(a.artifacts) == 2 and len(a.calls) == 2
    assert len(a.ledger.list_records("task_submission")) == 1


@pytest.mark.parametrize("child_state,parent_state", [
    ("queued", "partial"), ("running", "partial"),
    ("result_unknown", "result_unknown"), ("cancelled", "cancelled"),
])
def test_incomplete_and_unknown_real_queue_states_are_not_coerced_to_failed_or_success(journey, monkeypatch,
        child_state, parent_state):
    a = journey
    def incomplete(service, task_id=None, execution_guard=None, **kwargs):
        if child_state == "queued":
            return service.get_task_snapshot(task_id)
        task = service.queue.claim("synthetic-status-fixture", expected_task_id=task_id,
            execution_guard=execution_guard)
        assert task is not None
        if child_state == "running":
            return task
        if child_state == "cancelled":
            service.queue.request_cancel(task_id, expected_attempt=task["attempt"],
                expected_payload_digest=task["payload_digest"])
        return service.queue.finish(task_id, task["fencing_token"], child_state,
            error={"reason": "synthetic_no_fit_status_fixture"})
    monkeypatch.setattr(AnalysisService, "run_once", incomplete)
    turn = _run_and_finish(a)
    assert turn["status"] == parent_state and turn["answer"] is None
    assert not a.chat.view_turn(turn)["usable"]
    assert a.chat.view_turn(turn)["answer"] is None
    assert a.analysis.get_task_snapshot(turn["analysis_task_ids"][0])["status"] == child_state
    assert len(a.calls) == 2 and a.artifacts == []
    _assert_no_automatic_repeat(a, turn)


@pytest.mark.parametrize("action", ["inspect_dataset", "finish"])
def test_successful_profile_only_or_no_execution_attempt_is_not_rejected(journey, action):
    a = journey
    if action == "inspect_dataset":
        a.actions.append({"action": action, "answer": ""})
    a.actions.append({"action": "finish", "answer": "SYNTHETIC conversation only; no analysis execution."})
    turn = _send(a)
    view = a.chat.view_turn(turn)
    assert turn["status"] == "succeeded" and view["usable"]
    assert not view["analysis_outcome"]["validated_preview"]
    assert turn["analysis_task_ids"] == [] and a.artifacts == []
    assert a.ledger.list_records("task_submission") == []
    assert len(a.calls) == (2 if action == "inspect_dataset" else 1)


def test_real_changed_input_profile_failure_cannot_be_overridden_by_finish_text(journey):
    a = journey
    a.path.write_bytes(b"SYNTHETIC test input changed after asset registration")
    a.actions.extend([{"action": "inspect_dataset", "answer": ""}, {"action": "finish", "answer": FALSE_SUCCESS}])
    turn = _send(a)
    view = a.chat.view_turn(turn)
    assert turn["status"] == "failed" and turn["answer"] is None
    assert not view["usable"] and view["answer"] is None
    assert turn["analysis_task_ids"] == [] and a.artifacts == []
    assert a.ledger.list_records("task_submission") == [] and len(a.calls) == 2


def test_real_app_test_shows_rejected_artifacts_and_hides_false_model_success(journey):
    a = journey
    a.state["fault"] = "axis_order"
    turn = _run_and_finish(a)
    def screen(root, turn_id):
        from pathlib import Path
        from sckg_workbench.chat import ChatService
        from sckg_workbench.model_service import ModelService
        from sckg_workbench.storage import Ledger, Workspace
        from sckg_workbench.ui import _display_chat_turn
        ledger = Ledger(Workspace(Path(root)))
        def forbidden(*args, **kwargs):
            raise AssertionError("Read-only AppTest may not invoke any provider")
        _display_chat_turn(ChatService(ledger, ModelService(ledger.workspace, ledger, transport=forbidden)), turn_id)
    before = content_hash(a.ledger.list_records("model_call"))
    ui = AppTest.from_function(screen, args=(str(a.ledger.workspace.root), turn["id"]), default_timeout=15).run()
    assert not ui.exception and not ui.success
    visible = "\n".join(str(node.value) for nodes in (ui.markdown, ui.info, ui.warning, ui.error, ui.caption, ui.text)
        for node in nodes)
    assert FALSE_SUCCESS not in visible
    assert any(word in visible for word in ("验收", "失败", "未完成"))
    assert len(a.calls) == 2 and before == content_hash(a.ledger.list_records("model_call"))
    assert len(a.artifacts) == 1
