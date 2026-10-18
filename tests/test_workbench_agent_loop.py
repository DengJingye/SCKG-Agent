"""Actual ledger/gateway and HDF5 reads; in-process model transport only."""
from copy import deepcopy
import json
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from sckg_workbench.agent_loop import AnalysisAgentLoop, AgentLoopError, validate_options
from sckg_workbench.chat import ChatError, ChatService
from sckg_workbench.datasets import DatasetService
from sckg_workbench.model_service import ModelService
from sckg_workbench.storage import Ledger, Workspace
from sckg_workbench.tasks import TaskQueue
from sckg_workbench.worker import Worker


BUDGET = {"max_input_tokens": 64000, "max_output_tokens": 512,
          "timeout_seconds": 5, "max_cost_usd": 1}
PASSPHRASE = "local-fixture-passphrase"


@pytest.fixture
def app(tmp_path):
    ledger = Ledger(Workspace(tmp_path / "workspace"))
    calls, actions = [], []
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    def transport(url, headers, payload, timeout):
        calls.append(deepcopy(payload))
        action = actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return {"model": "fixture-returned", "usage": usage,
                "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(action, ensure_ascii=False) if isinstance(action, dict) else action}}]}
    models = ModelService(ledger.workspace, ledger, transport=transport)
    conn = models.create_connection("fixture", "https://provider.example/v1", "fixture-key", PASSPHRASE)
    profile = models.create_profile("fixture", "chat", conn["id"], "fixture",
                                   input_usd_per_million=1, output_usd_per_million=2)
    path = tmp_path / "input.h5ad"
    with h5py.File(path, "w") as handle:
        handle.attrs["encoding-type"] = "anndata"
        handle.create_dataset("X", data=np.ones((12, 10), dtype=np.int32))
        for name in ("obs", "var", "layers", "obsm", "obsp", "uns"):
            handle.create_group(name)
        handle["obs"].create_dataset("donor", data=[b"PRIVATE_VALUE_NOT_OUTBOUND"] * 12)
    asset = DatasetService(ledger.workspace).register_local(path)
    options = {"asset_id": asset["asset_id"], "count_source": "X",
               "count_provenance": "Synthetic fixture integer counts, not biological data",
               "expected_doublet_rate": 0.06}
    chat = ChatService(ledger, models)
    return SimpleNamespace(ledger=ledger, models=models, chat=chat, conversation=chat.create_conversation(),
        profile=profile, path=path, options=options, calls=calls, actions=actions, usage=usage)


def send(app, **kwargs):
    params = {"profile_id": app.profile["id"], "passphrase": PASSPHRASE, "budget": BUDGET,
              "request_id": "one-send", "analysis_options": app.options}
    params.update(kwargs)
    return app.chat.send(app.conversation["id"], "请检查所选数据，再说明能否分析", **params)


def test_real_profile_and_three_call_loop_have_persistent_steps_without_raw_matrix(app):
    original = app.path.read_bytes()
    app.actions.extend([{"action": "inspect_dataset", "answer": ""},
                        {"action": "inspect_dataset", "answer": ""},
                        {"action": "finish", "answer": "仅完成有界画像，尚未执行分析。"}])
    turn = send(app)
    assert turn["status"] == "succeeded"
    assert len(app.calls) == 3 and len(turn["agent_steps"]) == 2
    assert len(app.ledger.list_records("chat_agent_decision")) == 3
    assert len(app.ledger.list_records("chat_agent_step")) == 2
    assert len(app.ledger.list_records("dataset_profile")) == 2
    assert turn["analysis_task_ids"] == []
    assert turn["agent_budget"]["model_calls"] == 3
    assert turn["agent_budget"]["charged_or_reserved_tokens"] == 360
    assert turn["agent_budget"]["cost_usd"] == pytest.approx(0.00042)
    assert turn["agent_budget"]["max_cost_usd"] == 1
    assert app.calls[-1]["response_format"]["json_schema"]["schema"]["properties"]["action"]["enum"] == ["finish"]
    serialized = json.dumps(app.calls)
    assert "PRIVATE_VALUE_NOT_OUTBOUND" not in serialized and str(app.path) not in serialized
    assert app.path.read_bytes() == original
    assert send(app) == turn and len(app.calls) == 3


def test_ordinary_chat_retains_exactly_one_attempt_without_tools(app):
    app.actions.append("普通回答")
    turn = send(app, analysis_options=None)
    assert turn["answer"] == "普通回答" and len(app.calls) == 1
    assert "response_format" not in app.calls[0] and "agent_steps" not in turn


@pytest.mark.parametrize("change", [{"count_source": "raw.X"}, {"count_provenance": ""},
    {"asset_id": "unknown"}, {"expected_doublet_rate": True}, {"expected_doublet_rate": float("nan")},
    {"expected_doublet_rate": 0.5}, {"shell": "touch /tmp/must-not-run"}])
def test_unbound_or_unsupported_options_do_not_send_or_create_turn(app, change):
    with pytest.raises(AgentLoopError):
        send(app, analysis_options={**app.options, **change})
    assert not app.calls and not app.ledger.list_records("chat_request")


def test_model_cannot_supply_shell_paths_or_execution_parameters(app):
    app.actions.append({"action": "run_scrublet", "answer": "", "shell": "rm -rf /"})
    turn = send(app)
    assert turn["status"] == "failed" and len(app.calls) == 1
    assert len(app.ledger.list_records("model_call")) == 1
    assert not app.ledger.list_records("chat_agent_step")
    assert turn["receipts"][0]["status"] == "invalid_response"
    assert turn["error"]["outcome"] == "invalid_response"


def test_tool_failure_is_observed_not_converted_into_successful_analysis(app):
    app.path.write_bytes(b"changed input")
    app.actions.extend([{"action": "inspect_dataset", "answer": ""},
                        {"action": "finish", "answer": "输入已变化，未执行分析。"}])
    turn = send(app)
    assert turn["status"] == "failed" and turn["answer"] is None
    assert turn["error"]["type"] == "AnalysisArtifactRejected"
    assert turn["agent_steps"][0]["result"]["status"] == "failed"
    assert turn["analysis_task_ids"] == []
    assert "DatasetChangedError" in app.calls[1]["messages"][-1]["content"] or "ValueError" in app.calls[1]["messages"][-1]["content"]


def test_unknown_usage_with_monetary_cap_stops_before_second_attempt(app):
    app.usage.clear()
    app.actions.append({"action": "inspect_dataset", "answer": ""})
    turn = send(app)
    assert turn["status"] == "partial" and len(app.calls) == 1
    assert turn["agent_budget"]["cost_known"] is False
    assert turn["agent_budget"]["cost_usd"] is None
    assert turn["agent_budget"]["charged_or_reserved_tokens"] == 64512
    assert turn["error"]["type"] == "AgentBudgetStopped"


def test_model_failure_retains_prior_tool_and_all_receipts_without_retry(app):
    app.actions.extend([{"action": "inspect_dataset", "answer": ""}, TimeoutError("fixture timeout")])
    turn = send(app)
    assert turn["status"] == "result_unknown" and len(app.calls) == 2
    assert len(turn["agent_steps"]) == 1 and len(turn["receipts"]) == 2
    assert turn["receipts"][-1]["outcome"] == "result_unknown"
    assert app.ledger.get_state("chat_active:" + app.conversation["id"]) == turn["id"]
    assert not app.chat.view_turn(turn)["usable"] and turn["answer"] is None
    assert send(app) == turn and len(app.calls) == 2
    with pytest.raises(ChatError, match="different send"):
        send(app, analysis_options={**app.options, "expected_doublet_rate": 0.07})


def test_revoked_evidence_stops_before_tool_execution(app):
    app.actions.append({"action": "inspect_dataset", "answer": ""})
    request = {"id": "fixture-turn", "profile_id": app.profile["id"],
               "analysis_options": app.options, "budget": BUDGET}
    prepared = {"messages": [{"role": "system", "content": "fixture"}]}
    checks = iter([None, "source withdrawn"])
    result = AnalysisAgentLoop(app.ledger, app.models).run(request, prepared,
        passphrase=PASSPHRASE, evidence_check=lambda: next(checks))
    assert result["status"] == "blocked" and len(app.calls) == 1
    assert not app.ledger.list_records("dataset_profile")


def test_unsupported_worker_kind_is_not_claimed_or_interpreted_as_model_profile(app):
    queue = TaskQueue(app.ledger.workspace)
    task = queue.submit("unsupported.kind", {}, {"not_a_model": {}},
                        {"max_calls": 0, "max_tokens": 0, "max_cost": 0}, "unsupported")
    worker = Worker(app.ledger, app.models)
    assert worker.requires_passphrase() is False
    with pytest.raises(ValueError, match="not claimed"):
        worker.run_once(outbound_authorized=True)
    assert queue.get(task["task_id"])["status"] == "queued" and not app.calls


def test_default_analysis_bridge_binds_real_asset_and_reuses_repeated_action(app, monkeypatch):
    from sckg_workbench.analysis import AnalysisService
    runs = []
    def queued_only(self, task_id=None, **kwargs):
        runs.append(task_id)
        return self.queue.get(task_id)
    monkeypatch.setattr(AnalysisService, "run_once", queued_only)
    app.actions.extend([{"action": "run_scrublet", "answer": ""},
                        {"action": "run_scrublet", "answer": ""},
                        {"action": "finish", "answer": "Fixture prose is not proof of execution."}])
    turn = send(app)
    assert turn["status"] == "partial" and turn["answer"] is None and len(app.calls) == 3
    assert len(runs) == 1  # Two model decisions cannot trigger two analyses.
    assert len(set(turn["analysis_task_ids"])) == 1
    task = TaskQueue(app.ledger.workspace).get(runs[0])
    assert task["status"] == "queued" and task["input_snapshot"]["execution_authorized"] is True
    assert len(task["input_snapshot"]["source_sha256"]) == 64
    view = app.chat.view_turn(turn)
    assert view["analysis_outcome"]["validated_preview"] is False
    assert view["analysis_outcome"]["state"] == "not_validated"
    assert len(view["analysis_outcome"]["tasks"]) == 1
    assert view["analysis_outcome"]["tasks"][0]["status"] == "queued"
    assert view["analysis_outcome"]["tasks"][0]["result_status"] is None
    assert send(app) == turn and len(runs) == 1


def test_origin_options_preserve_old_four_field_shape_and_declared_context(app):
    assert validate_options(app.options, app.ledger) == app.options
    options = {**app.options, "dataset_origin": "published_derived", "dataset_origin_refs": ["doi:10.1038/s41592-019-0405-6"]}
    assert validate_options(options, app.ledger) == options
    with pytest.raises(AgentLoopError):
        validate_options({**options, "dataset_origin_verification": "verified"}, app.ledger)
    with pytest.raises(AgentLoopError):
        validate_options({**options, "dataset_origin_refs": ["/private/local/input.h5ad"]}, app.ledger)


def test_origin_passes_to_real_task_but_references_stay_out_of_model_receipt(app, monkeypatch):
    from sckg_workbench.analysis import AnalysisService
    monkeypatch.setattr(AnalysisService, "run_once", lambda self, task_id=None, **kwargs: self.queue.get(task_id))
    app.options.update(dataset_origin="synthetic", dataset_origin_refs=["work:local-engineering-fixture"])
    app.actions.extend([{"action": "run_scrublet", "answer": ""}, {"action": "finish", "answer": "Queued fixture, not completed analysis."}])
    turn = send(app)
    task = TaskQueue(app.ledger.workspace).get(turn["analysis_task_ids"][0])
    assert task["input_snapshot"]["dataset_origin"] == "synthetic"
    assert task["input_snapshot"]["dataset_origin_refs"] == ["work:local-engineering-fixture"]
    assert "work:local-engineering-fixture" not in json.dumps(app.calls)
    step = turn["agent_steps"][0]["result"]
    assert step["dataset_origin"] == "synthetic" and "dataset_origin_refs" not in step


def test_evidence_io_error_after_tool_preserves_trace_and_receipts(app):
    app.actions.append({"action": "inspect_dataset", "answer": ""})
    checks = []
    def check():
        checks.append(1)
        if len(checks) == 3:
            raise OSError("source blob vanished")
    result = AnalysisAgentLoop(app.ledger, app.models).run(
        {"id": "fixture-turn", "profile_id": app.profile["id"], "analysis_options": app.options, "budget": BUDGET},
        {"messages": [{"role": "system", "content": "fixture"}]}, passphrase=PASSPHRASE, evidence_check=check)
    assert result["status"] == "blocked" and len(result["receipts"]) == 1
    assert len(result["agent_steps"]) == 1 and len(app.calls) == 1


def test_tool_exception_path_is_local_only(app, monkeypatch):
    secret_path = "/private/user/patient-identifiers/forbidden.h5ad"
    def error(*args, **kwargs):
        raise FileNotFoundError(secret_path)
    monkeypatch.setattr(AnalysisAgentLoop, "_tool", error)
    app.actions.extend([{"action": "inspect_dataset", "answer": ""}, {"action": "finish", "answer": "本地工具失败"}])
    turn = send(app)
    assert turn["status"] == "failed" and turn["answer"] is None and len(app.calls) == 2
    assert secret_path not in json.dumps(app.calls)
    assert secret_path in app.ledger.list_records("chat_tool_error")[0]["message"]
    assert app.chat.view_turn(turn)["analysis_outcome"]["validated_preview"] is False


def test_shared_worker_dispatches_local_analysis_without_model_credentials(app, monkeypatch):
    from sckg_workbench.analysis import AnalysisService
    analysis = AnalysisService(app.ledger.workspace)
    task = analysis.submit_scrublet(**app.options, idempotency_key="analysis-dispatch", execution_authorized=True)
    monkeypatch.setattr(AnalysisService, "run_once", lambda self, task_id=None, **kwargs: self.queue.get(task_id))
    worker = Worker(app.ledger, app.models)
    assert worker.requires_passphrase() is False
    assert worker.run_once(outbound_authorized=False)["task_id"] == task["task_id"]
    assert not app.calls


@pytest.mark.parametrize("kind", ["chat_agent_decision", "chat_agent_step"])
def test_trace_write_failure_retains_consumed_call_and_stops_without_retry(app, monkeypatch, kind):
    original = app.ledger.put_record
    def fail_kind(record_kind, *args, **kwargs):
        if record_kind == kind:
            raise OSError("fixture disk error")
        return original(record_kind, *args, **kwargs)
    monkeypatch.setattr(app.ledger, "put_record", fail_kind)
    app.actions.append({"action": "inspect_dataset", "answer": ""})
    turn = send(app)
    assert turn["status"] == "failed" and len(app.calls) == 1
    assert turn["error"]["type"] == "TraceWriteFailed"
    assert len(turn["receipts"]) == 1 and turn["agent_budget"]["model_calls"] == 1
    assert len(turn["agent_steps"]) == (1 if kind == "chat_agent_step" else 0)
    assert send(app) == turn and len(app.calls) == 1


def test_analysis_scaffold_is_part_of_pre_dispatch_input_budget(app):
    app.actions.append({"action": "finish", "answer": "unused"})
    turn = send(app, budget={**BUDGET, "max_input_tokens": 2000})
    assert turn["status"] == "failed" and not app.calls
    assert turn["error"]["type"] == "ChatError"
