"""One durable same-configuration operational recovery, never generated-code repair.

Only the executor's typed, positively observed pre-Popen EAGAIN is eligible.
The original task/attempt, grant, scientific inputs and 180s deadline stay fixed.
An admission is consumed before a second dispatch and is never resumed.
"""
from __future__ import annotations

import errno
import math
import os
from pathlib import Path
import time

from .storage import content_hash


PROFILE = "scrublet-preview-v2-operational-recovery"
POLICY = "workbench-same-request-eagain-v1"
LIMITS = {"max_initial_runs": 1, "reserved_repair_runs": 1,
          "reserved_validation_reruns": 0, "max_total_runs": 2,
          "max_concurrent_runs": 1, "timeout_seconds": 180}


def enabled(task):
    profile = task["profile_snapshot"]
    if profile.get("skill") != PROFILE:
        return False
    if profile.get("execution_budget") != LIMITS or profile.get("operational_recovery_policy") != POLICY:
        raise ValueError("invalid frozen operational recovery profile")
    return True


def key(task):
    return f"{task['task_id']}:attempt:{task['attempt']}"


def public_summary(*, status, admissions=0, initial_run_id=None, final_run_id=None):
    return {"schema_version": "workbench-operational-recovery-summary-v1", "status": status,
            "admissions": admissions, "initial_run_id": initial_run_id,
            "final_run_id": final_run_id, "scientific_configuration_changed": False,
            "generated_code_repair": False}


def unfinished_summary(analysis, task):
    """Expose consumed recovery allowance after an interrupted run, not success."""
    if not enabled(task):
        return None
    base = key(task)
    initial = analysis.ledger.get_record("analysis_inner_run", base + ":initial")
    repair = analysis.ledger.get_record("analysis_inner_run", base + ":repair")
    admission = analysis.ledger.get_record("analysis_repair_admission", base)
    return public_summary(status="unknown" if admission else "not_used", admissions=int(admission is not None),
        initial_run_id=initial.get("run_id") if initial else None,
        final_run_id=repair.get("run_id") if repair else initial.get("run_id") if initial else None)


def eligible_launch(run):
    """No stderr/error-message inference, broad exit classification or unknown retry."""
    proof = getattr(run, "launch_evidence", None)
    expected = {"schema_version": "popen-launch-observation-v1",
                "observation_source": "server_popen_boundary", "phase": "popen_call",
                "os_errno": errno.EAGAIN, "process_handle_returned": False,
                "program_start": "not_started", "cleanup_status": "not_required_no_process",
                "residual_processes": []}
    cleanup = run.process_cleanup
    return (proof is not None and proof.model_dump(mode="json") == expected
            and run.status == "failed" and run.exit_code is None
            and run.error_type in {"BlockingIOError", "OSError"}
            and not run.artifact_paths and not run.artifact_hashes
            and not cleanup.timeout_triggered and not cleanup.cancellation_triggered
            and not cleanup.terminate_sent and not cleanup.kill_sent
            and cleanup.child_processes_seen == 0 and not cleanup.residual_processes)


def check_worker_generation(analysis, task, conn):
    """Retain the already-consumed dispatch grant; never loosen queued guards.

    Foreign-thread visibility can remain unknown on Darwin. It is not restored
    here: this is the actual original worker, under its consumed launch grant.
    """
    from .chat_runs import ChatRunService, ChatRunFenceError
    service = ChatRunService(analysis.ledger)
    row = analysis.queue._require_lease(conn, task["task_id"], task["fencing_token"])
    if row["status"] != "running" or row["attempt"] != task["attempt"]:
        raise PermissionError("original analysis generation is cancelled or changed")
    bound = service._worker_start_binding(conn, analysis.queue._public(row))
    if bound is None:
        return
    grant_key, fields, control, _ = bound
    issued = analysis.ledger.get_record("chat_worker_start_grant", grant_key, conn=conn)
    consumed = analysis.ledger.get_record("chat_worker_start_consumed", grant_key, conn=conn)
    if (not issued or any(issued.get(k) != v for k, v in fields.items()) or not consumed
            or consumed.get("grant_hash") != content_hash(issued)
            or consumed.get("grant_id") != issued.get("grant_id")
            or consumed.get("task_id") != task["task_id"] or consumed.get("attempt") != task["attempt"]
            or consumed.get("worker_process") != issued.get("worker_process")):
        raise ChatRunFenceError("operational recovery requires original consumed worker authorization")
    import psutil
    try:
        current = psutil.Process(os.getpid())
        worker = issued["worker_process"]
        owner = psutil.Process(control["owner_process"]["pid"])
        live = (current.pid == worker["pid"] and current.create_time() == worker["create_time"]
                and owner.create_time() == control["owner_process"]["create_time"]
                and owner.is_running() and owner.status() != psutil.STATUS_ZOMBIE)
    except (psutil.Error, OSError, KeyError, TypeError):
        live = False
    if live is not True or service.owner_probe(control["owner_process"]) is False:
        raise ChatRunFenceError("original worker or owner is dead or different")


def _scope(task, prepared):
    return content_hash({"task_id": task["task_id"], "attempt": task["attempt"],
        "payload_digest": task["payload_digest"], "profile": task["profile_snapshot"],
        "preparation": prepared})


def verify_inputs(prepared, result, *, approval_id):
    """Re-read frozen input bytes and stored lineage without fitting anything."""
    from .analysis import _sha, _path_inside
    frozen = prepared["frozen"]
    paths = [(Path(prepared["source_path"]), frozen["source_sha256"]),
             (Path(prepared["preview_path"]), frozen["preview_sha256"]),
             (Path(frozen["notebook_path"]), frozen["notebook_sha256"])]
    if any(_sha(_path_inside(p, p.parent)) != digest for p, digest in paths):
        raise ValueError("operational recovery frozen input changed")
    run, lineage = result.execution_run, result.lineage
    notebook = prepared["notebook"]
    expected = {"source_hash": frozen["source_sha256"], "profile_id": frozen["profile_id"],
        "preview_id": frozen["preview_id"], "preview_hash": frozen["preview_sha256"],
        "notebook_id": frozen["notebook_id"], "notebook_hash": frozen["notebook_sha256"],
        "parameter_hash": notebook["parameter_hash"], "step_contract_id": notebook["step_contract_id"],
        "step_contract_version": notebook["step_contract_version"],
        "step_template_digest": notebook["step_template_digest"],
        "tool_contract_version": notebook["tool_contract_version"],
        "tool_contract_digest": frozen["contract_digest"], "environment_digest": frozen["environment_digest"],
        "environment_id": run.environment_id,
        "approval_fingerprint": prepared["approval"]["request_fingerprint"]}
    if (lineage is None or any(getattr(lineage, field) != value for field, value in expected.items())
            or run.parameters != frozen["parameters"] or run.input_hash != frozen["preview_sha256"]
            or run.fixture_id != frozen["preview_id"] or run.tool_name != "Scrublet" or run.tool_version != "0.2.3"
            or run.execution_seed != 0 or run.approval_id != approval_id
            or run.owner_user_id != "workbench-local" or run.execution_purpose != "representative_preview"
            or result.preview_id != frozen["preview_id"] or result.notebook_id != frozen["notebook_id"]):
        raise ValueError("operational recovery frozen lineage differs")


class OperationalRecovery:
    def __init__(self, analysis, task, prepared, *, clock=time.time):
        self.analysis, self.task, self.prepared, self.clock = analysis, task, prepared, clock
        self.ledger, self.key = analysis.ledger, key(task)
        self.scope = _scope(task, prepared)

    def _remaining(self, deadline, *, now=None):
        remaining = math.floor(deadline - (self.clock() if now is None else now))
        if remaining < 1:
            raise TimeoutError("original analysis deadline exhausted; no further execution")
        return min(120, remaining)

    def reserve_initial(self):
        from core.execution_models import ExecutionBudget
        from execution.repair_policy import RunBudgetLedger
        with self.ledger.transaction() as tx:
            check_worker_generation(self.analysis, self.task, tx)
            if self.ledger.get_record("analysis_execution_budget", self.key, conn=tx) is not None:
                raise PermissionError("initial execution admission already consumed; no resume")
            started = self.ledger.get_record("analysis_process_started", self.key, conn=tx)
            deadline = started.get("original_deadline_epoch") if started else None
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                raise PermissionError("original supervised analysis deadline is missing")
            timeout = self._remaining(deadline)
            budget = RunBudgetLedger(limits=ExecutionBudget(**LIMITS)).reserve_initial(1)
            receipt = {"schema_version": "workbench-analysis-execution-budget-v1",
                "task_id": self.task["task_id"], "attempt": self.task["attempt"],
                "payload_digest": self.task["payload_digest"], "fencing_token_digest": content_hash(self.task["fencing_token"]),
                "preparation_digest": content_hash(self.prepared), "scope_digest": self.scope,
                "deadline_epoch": deadline, "budget": budget.model_dump(mode="json"),
                "original_process_started_hash": content_hash(started), "policy_version": POLICY}
            self.ledger.put_record("analysis_execution_budget", self.key, receipt, conn=tx)
        return receipt, timeout

    def save_run(self, phase, result, validation):
        value = {"schema_version": "workbench-analysis-inner-run-v1", "phase": phase,
            "task_id": self.task["task_id"], "attempt": self.task["attempt"],
            "scope_digest": self.scope, "run_id": result.execution_run.run_id,
            "result": result.model_dump(mode="json"), "validation": validation}
        self.ledger.put_record("analysis_inner_run", self.key + ":" + phase, value)
        return value

    def check_after_run(self):
        with self.ledger.transaction() as tx:
            check_worker_generation(self.analysis, self.task, tx)

    def admit_repair(self, *, initial, service, contract, budget):
        from execution.repair_policy import (RepairPolicy, RepairProposal, RepairReason,
            RepairType, RunBudgetLedger, apply_repair_parameters)
        run = initial.execution_run
        if not eligible_launch(run):
            return None
        # A valid sidecar alone cannot replace the immutable original receipt.
        loaded = service.result_store.load_result(user_id=initial.user_id,
            artifact_id=initial.artifact_id, run_id=run.run_id)
        if loaded.model_dump(mode="json") != initial.model_dump(mode="json") or not service.result_store.inspect_integrity(loaded).passed:
            raise ValueError("initial result store integrity differs")
        verify_inputs(self.prepared, initial, approval_id=self.prepared["approval"]["approval_id"])
        proposal = RepairProposal(proposal_id="repair-proposal-" + content_hash([self.scope, run.run_id])[:24],
            parent_run_id=run.run_id, reason_code=RepairReason.TRANSIENT_PROCESS_FAILURE,
            repair_type=RepairType.RETRY_SAME_REQUEST_ONCE, changed_fields=[], old_values={}, new_values={},
            provenance={"origin": "typed_launch_receipt", "policy_version": POLICY,
                "contract_id": contract.contract_id, "contract_version": contract.contract_version,
                "launch_evidence_digest": content_hash(run.launch_evidence.model_dump(mode="json"))},
            approval_required=False, changes_execution_scope=False)
        if apply_repair_parameters(run.parameters, proposal) != self.prepared["frozen"]["parameters"]:
            raise ValueError("operational recovery cannot change scientific parameters")
        with self.ledger.transaction() as tx:
            check_worker_generation(self.analysis, self.task, tx)
            if self.ledger.get_record("analysis_repair_admission", self.key, conn=tx) is not None:
                raise PermissionError("one operational recovery admission already consumed; no resume")
            saved_budget = self.ledger.get_record("analysis_execution_budget", self.key, conn=tx)
            saved_initial = self.ledger.get_record("analysis_inner_run", self.key + ":initial", conn=tx)
            if saved_budget != budget or not saved_initial or saved_initial["result"] != initial.model_dump(mode="json"):
                raise ValueError("initial run or execution budget differs")
            admitted_at = self.clock()
            timeout = self._remaining(budget["deadline_epoch"], now=admitted_at)
            after = RunBudgetLedger.model_validate(budget["budget"]).reserve_repair()
            admission = {"schema_version": "workbench-analysis-repair-admission-v1", "policy_version": POLICY,
                "task_id": self.task["task_id"], "attempt": self.task["attempt"], "scope_digest": self.scope,
                "parent_run_id": run.run_id, "parent_result_digest": content_hash(saved_initial),
                "proposal_digest": content_hash(proposal.model_dump(mode="json")),
                "budget_digest": content_hash(budget), "budget_after": after.model_dump(mode="json"),
                "deadline_epoch": budget["deadline_epoch"], "admitted_at_epoch": admitted_at,
                "server_timeout_seconds": timeout, "automatic_resume": False}
            self.ledger.put_record("analysis_repair_proposal", self.key, proposal.model_dump(mode="json"), conn=tx)
            self.ledger.put_record("analysis_repair_admission", self.key, admission, conn=tx)
        return proposal, admission

    def before_repair_dispatch(self, admission):
        with self.ledger.transaction() as tx:
            check_worker_generation(self.analysis, self.task, tx)
            if self.ledger.get_record("analysis_repair_admission", self.key, conn=tx) != admission:
                raise ValueError("operational recovery admission differs")
            # A separate durable marker consumes dispatch once even if launch
            # raises or the worker dies before recording the resulting run.
            if self.ledger.get_record("analysis_repair_dispatch", self.key, conn=tx) is not None:
                raise PermissionError("operational recovery dispatch already consumed")
            dispatched_at = self.clock()
            timeout = min(admission["server_timeout_seconds"], self._remaining(admission["deadline_epoch"], now=dispatched_at))
            self.ledger.put_record("analysis_repair_dispatch", self.key,
                {"admission_digest": content_hash(admission), "timeout_seconds": timeout,
                 "dispatched_at_epoch": dispatched_at, "automatic_resume": False}, conn=tx)
        return timeout

    def finish_repair(self, proposal, initial, final):
        from execution.repair_policy import RepairPolicy
        if initial.execution_run.run_id == final.execution_run.run_id:
            raise ValueError("operational recovery requires a distinct run id")
        verify_inputs(self.prepared, final, approval_id=self.prepared["approval"]["approval_id"])
        with self.ledger.transaction() as tx:
            check_worker_generation(self.analysis, self.task, tx)
            action = RepairPolicy().apply(proposal=proposal, new_run_id=final.execution_run.run_id, approved=True)
            self.ledger.put_record("analysis_repair_action", self.key, action.model_dump(mode="json"), conn=tx)


def verify_chain(analysis, task, saved, prepared):
    """Re-read every immutable link and both owned stored results; no executions."""
    if not enabled(task):
        return saved.get("operational_recovery")  # Historical schemas remain readable.
    from execution.preview_result_store import PreviewResultStore
    from execution.repair_policy import RepairAction, RepairProposal, RepairPolicy, RunBudgetLedger
    from core.research_workspace_models import PreviewRunResult
    base = key({**task, "attempt": saved["attempt"]})
    budget = analysis.ledger.get_record("analysis_execution_budget", base)
    initial = analysis.ledger.get_record("analysis_inner_run", base + ":initial")
    started = analysis.ledger.get_record("analysis_process_started", base)
    if (not budget or not initial or not started
            or budget.get("original_process_started_hash") != content_hash(started)
            or budget.get("deadline_epoch") != started.get("original_deadline_epoch")
            or budget.get("fencing_token_digest") != started.get("fencing_token_digest")
            or budget.get("scope_digest") != _scope({**task, "attempt": saved["attempt"]}, prepared)
            or budget.get("preparation_digest") != content_hash(prepared)
            or budget.get("payload_digest") != task["payload_digest"] or budget.get("policy_version") != POLICY):
        raise ValueError("operational recovery initial chain missing or different")
    limits = RunBudgetLedger.model_validate(budget["budget"])
    if limits.model_dump(mode="json") != {"limits": LIMITS, "initial_runs_used": 1, "repair_runs_used": 0, "validation_reruns_used": 0}:
        raise ValueError("operational recovery initial budget differs")
    output = Path(prepared["output_root"])
    store = PreviewResultStore(workspace_root=output.parent / "research", execution_root=output)
    def check(receipt, phase):
        value = PreviewRunResult.model_validate(receipt["result"])
        if (receipt.get("phase") != phase or receipt.get("scope_digest") != budget["scope_digest"]
                or receipt.get("task_id") != task["task_id"] or receipt.get("attempt") != saved["attempt"]
                or receipt.get("run_id") != value.execution_run.run_id):
            raise ValueError("inner run receipt binding differs")
        loaded = store.load_result(user_id=value.user_id, artifact_id=value.artifact_id, run_id=value.execution_run.run_id)
        if loaded.model_dump(mode="json") != receipt["result"] or not store.inspect_integrity(loaded).passed:
            raise ValueError("inner run store differs from immutable receipt")
        verify_inputs(prepared, value, approval_id=prepared["approval"]["approval_id"])
        return value
    first = check(initial, "initial")
    admission = analysis.ledger.get_record("analysis_repair_admission", base)
    if admission is None:
        final, status, count = first, "not_used", 0
        if analysis.ledger.get_record("analysis_repair_action", base) or analysis.ledger.get_record("analysis_inner_run", base + ":repair"):
            raise ValueError("unadmitted operational recovery result")
    else:
        proposal_raw = analysis.ledger.get_record("analysis_repair_proposal", base)
        dispatch = analysis.ledger.get_record("analysis_repair_dispatch", base)
        action_raw = analysis.ledger.get_record("analysis_repair_action", base)
        repair = analysis.ledger.get_record("analysis_inner_run", base + ":repair")
        if not proposal_raw or not dispatch or not action_raw or not repair or not eligible_launch(first.execution_run):
            raise ValueError("operational recovery chain incomplete or initial failure ineligible")
        proposal, action = RepairProposal.model_validate(proposal_raw), RepairAction.model_validate(action_raw)
        after = RunBudgetLedger.model_validate(admission["budget_after"])
        if (admission.get("scope_digest") != budget["scope_digest"] or admission.get("parent_run_id") != first.execution_run.run_id
                or admission.get("parent_result_digest") != content_hash(initial)
                or admission.get("proposal_digest") != content_hash(proposal_raw)
                or admission.get("budget_digest") != content_hash(budget)
                or admission.get("deadline_epoch") != budget["deadline_epoch"]
                or after != limits.reserve_repair() or proposal.parent_run_id != first.execution_run.run_id
                or proposal.changed_fields or proposal.changes_execution_scope or proposal.approval_required
                or proposal.repair_type != "retry_same_request_once" or proposal.provenance.get("policy_version") != POLICY
                or dispatch.get("admission_digest") != content_hash(admission)
                or not 0 < dispatch.get("timeout_seconds", 0) <= admission["server_timeout_seconds"] <= 120
                or dispatch.get("dispatched_at_epoch", math.inf) + dispatch["timeout_seconds"] > budget["deadline_epoch"]
                or not admission.get("admitted_at_epoch", math.inf) <= dispatch.get("dispatched_at_epoch", -math.inf)
                or action.proposal_id != proposal.proposal_id or action.parent_run_id != first.execution_run.run_id
                or not action.approved or action.changed_fields or action.repair_type != proposal.repair_type):
            raise ValueError("operational recovery admission/action/budget differs")
        final = check(repair, "repair")
        if (action.new_run_id != final.execution_run.run_id or action.new_run_id == first.execution_run.run_id
                or action != RepairPolicy().apply(proposal=proposal, new_run_id=final.execution_run.run_id, approved=True)):
            raise ValueError("operational recovery final run differs")
        status, count = ("repaired_validated" if repair["validation"]["passed"] else "repair_failed"), 1
    if (saved.get("execution_run") != final.execution_run.model_dump(mode="json")
            or saved.get("legacy_preview_result") != final.model_dump(mode="json")
            or saved.get("run_id") != final.execution_run.run_id):
        raise ValueError("selected final operational recovery run differs")
    summary = public_summary(status=status, admissions=count, initial_run_id=first.execution_run.run_id,
                             final_run_id=final.execution_run.run_id)
    if saved.get("operational_recovery") != summary:
        raise ValueError("operational recovery public summary differs")
    return summary
