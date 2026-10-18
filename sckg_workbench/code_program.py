"""One task/attempt for candidate Python orchestration and one bounded patch.

Generated code has no data paths or credentials. It calls frozen server-side
operations; the existing scientific executor and validators retain authority.
This module never calls a model and never resumes an abandoned controller.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from .storage import Ledger, content_hash, utcnow
from .tasks import TaskQueue, LeaseLost

MODE = "python_program_v1"
KIND = "analysis.scrublet.program.v1"
POLICY = "bounded-python-tool-orchestration-v1"
MAX_SOURCE_BYTES = 16384
LIMITS = {"initial_executions": 1, "patch_executions": 1, "scientific_operations": 1,
          "api_messages": 8, "whole_seconds": 180, "max_rss_mb": 2048}


class CodeProgramError(ValueError):
    pass


def _base(task):
    return f"{task['task_id']}:attempt:{task['attempt']}"


def _scope(task):
    return content_hash({"task_id": task["task_id"], "attempt": task["attempt"],
        "payload_digest": task["payload_digest"], "input": task["input_snapshot"],
        "profile": task["profile_snapshot"]})


def _sha(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _source(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise CodeProgramError("A nonempty program of at most16384 UTF-8 bytes is required")
    from .code_worker import validate_source
    validate_source(source)
    return source


def verify_policy_rejection(ledger, reference, *, options=None):
    """Re-read a first-draft AST rejection; never create or execute a task.

    The parent here is a rejected model proposal, not an executed program.
    Its immutable model decision, request and explicit options must still agree.
    """
    from .agent_loop import validate_options
    from .code_worker import CodePolicyError
    if (not isinstance(reference, dict)
            or set(reference) != {"record_id", "record_sha256", "parent_source_sha256"}):
        raise CodeProgramError("Invalid policy correction reference")
    rejected = ledger.get_record("chat_program_policy_rejection", reference["record_id"])
    if (not rejected or content_hash(rejected) != reference["record_sha256"]
            or rejected.get("schema") != "program-source-policy-rejection-v1"
            or rejected.get("namespace") != ledger.workspace.namespace
            or reference["record_id"] != f"{rejected['turn_id']}:policy:0"
            or rejected.get("index") != 0 or rejected.get("parent_source_sha256") is not None
            or rejected.get("execution_attempted") is not False
            or rejected.get("repair_allowed") is not True
            or rejected.get("source_sha256") != reference["parent_source_sha256"]
            or _sha(rejected["source"]) != rejected["source_sha256"]):
        raise CodeProgramError("Original rejected proposal binding differs")
    request = ledger.get_record("chat_request", rejected["turn_id"])
    decision = ledger.get_record("chat_agent_decision", f"{rejected['turn_id']}:0")
    receipt = (decision or {}).get("receipt") or {}
    model_call = ledger.get_record("model_call", receipt.get("call_id")) if receipt.get("call_id") else None
    raw_output = ledger.get_record("model_output", receipt.get("call_id")) if receipt.get("call_id") else None
    usage = receipt.get("usage") or {}
    if (not request or request.get("request_hash") != rejected["request_hash"]
            or not decision or decision.get("turn_id") != rejected["turn_id"]
            or decision.get("index") != 0
            or decision.get("action") != {"action": "execute_program", "source": rejected["source"],
                "parent_source_sha256": None, "answer": rejected["proposal_answer"]}
            or content_hash(receipt) != rejected["model_receipt_sha256"]
            or receipt.get("status") != "succeeded" or receipt.get("outcome") == "result_unknown"
            or receipt.get("budget_exceeded") is True or receipt.get("profile_id") != request["profile_id"]
            or model_call != receipt or not raw_output
            or content_hash(raw_output) != receipt.get("raw_output_record_hash")
            or json.loads(raw_output["text"]) != decision["action"]
            or any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens"))
            or validate_options(request["analysis_options"], ledger) != rejected["options"]
            or content_hash(rejected["options"]) != rejected["options_digest"]
            or (options is not None and options != rejected["options"])):
        raise CodeProgramError("Rejected proposal request, receipt or options differ")
    try:
        _source(rejected["source"])
    except CodePolicyError as error:
        if error.diagnostic() != rejected["error"]:
            raise CodeProgramError("Original static policy diagnostic differs") from None
    else:
        raise CodeProgramError("Policy correction parent was not a rejected source")
    return rejected


def _verify_policy_correction(ledger, reference, source, *, options=None, task=None):
    rejected = verify_policy_rejection(ledger, reference, options=options)
    if _sha(source) == rejected["source_sha256"]:
        raise CodeProgramError("Policy correction must replace the rejected draft")
    _source(source)
    if task is not None:
        snapshot = task["input_snapshot"]
        if {key: snapshot.get(key) for key in rejected["options"]} != rejected["options"]:
            raise CodeProgramError("Policy correction changed the frozen analysis options")
        owner = ledger.get_record("chat_child_binding", rejected["turn_id"])
        if (not owner or owner.get("task_id") != task["task_id"]
                or owner.get("expected_attempt") != task["attempt"]
                or owner.get("payload_digest") != task["payload_digest"]):
            raise CodeProgramError("Policy correction belongs to a different original chat owner")
    return rejected


def _read(conn, kind, record_id):
    row = conn.execute("SELECT payload,digest FROM records WHERE kind=? AND record_id=?", (kind, record_id)).fetchone()
    if not row:
        return None
    value = json.loads(row["payload"])
    if content_hash(value) != row["digest"]:
        raise CodeProgramError("Program record integrity failed")
    return value


def _phase_proof(conn, task, phase):
    key = _base(task) + ":" + phase
    admission = _read(conn, "program_phase_admission", key)
    execution = _read(conn, "program_execution", key)
    if not admission or not execution or execution.get("binding") != admission["binding"]:
        return False
    if any(admission["binding"].get(k) != task[k] for k in ("task_id", "attempt")):
        return False
    started = _read(conn, "program_process_started", key)
    cleanup = _read(conn, "program_process_cleanup", key)
    if (execution.get("process_start_sha256") != (content_hash(started) if started else None)
            or execution.get("process_cleanup_sha256") != (content_hash(cleanup) if cleanup else None)):
        return False
    if not started:
        return bool(execution.get("child_started") is False and execution.get("dispatch_status") == "not_started"
                    and execution.get("cleanup_verified") is True)
    if not cleanup:
        # A later explicit cleanup can prove stopped identities without
        # rewriting the original execution result or silently resuming it.
        rows = conn.execute("SELECT record_id FROM records WHERE kind='program_process_recovery'").fetchall()
        candidates = [_read(conn, "program_process_recovery", row[0]) for row in rows]
        cleanup = next((c for c in candidates if c and c.get("task_id") == task["task_id"]
            and c.get("attempt") == task["attempt"] and c.get("phase") == phase
            and c.get("cleanup_verified") is True), None)
    fields = ("namespace", "task_id", "attempt", "payload_digest", "fencing_token_digest",
              "source_sha256", "phase", "root", "supervisor", "command_digest")
    return bool(cleanup and started.get("root")
        and all(started.get(k) == v for k, v in admission["binding"].items())
        and all(started.get(k) == cleanup.get(k) for k in fields)
        and cleanup.get("cleanup_verified") is True and not cleanup.get("residual_processes")
        and not (cleanup.get("cleanup") or {}).get("residual_processes"))


def verify_program_chain(analysis, task, saved):
    """Verify all candidate revisions, actual executions and committed science.

    Read-only: no claims, dispatches, repair admissions or artifact edits.
    """
    if task["kind"] != KIND:
        return
    from .analysis import _path_inside
    ledger, base = analysis.ledger, _base({**task, "attempt": saved["attempt"]})
    scope = _scope({**task, "attempt": saved["attempt"]})
    budget = ledger.get_record("program_budget", base)
    completion = ledger.get_record("program_completion", base)
    science = ledger.get_record("program_science_result", base)
    effect = ledger.get_record("program_science_admission", base)
    if not all((budget, completion, science, effect)):
        raise CodeProgramError("Program completion chain is incomplete")
    submission = ledger.get_record("task_submission", task["task_id"])
    expected_submission = {"task_id": task["task_id"], "namespace": analysis.workspace.namespace,
        "kind": KIND, "input_snapshot": task["input_snapshot"], "profile_snapshot": task["profile_snapshot"],
        "budget": task["budget"], "payload_digest": task["payload_digest"]}
    if submission != expected_submission:
        raise CodeProgramError("Program original submission differs from its authoritative task")
    correction = task["input_snapshot"].get("program_policy_correction")
    if correction is not None:
        _verify_policy_correction(ledger, correction, task["input_snapshot"]["program_source"], task=task)
    if budget["limits"] != LIMITS or any(r.get("scope_digest") != scope for r in (budget, completion, science, effect)):
        raise CodeProgramError("Program scientific scope or budget changed")
    phases = ["initial", "patch"] if ledger.get_record("program_phase_admission", base + ":patch") else ["initial"]
    if correction is not None and phases != ["initial"]:
        raise CodeProgramError("Policy correction already consumed the single repair allowance")
    code_hashes, execution_hashes = [], []
    with ledger.connect() as conn:
        for phase in phases:
            rid = base + ":" + phase
            revision = ledger.get_record("program_code_revision", rid, conn=conn)
            admission = ledger.get_record("program_phase_admission", rid, conn=conn)
            execution = ledger.get_record("program_execution", rid, conn=conn)
            if not revision or not admission or not execution or not _phase_proof(conn, task, phase):
                raise CodeProgramError("Program execution or cleanup proof is missing")
            path = _path_inside(analysis.workspace.artifacts_dir / revision["relative_path"], analysis.workspace.artifacts_dir)
            if (revision["trust"] != "candidate_generated_code" or revision["source_sha256"] != _sha(revision["source"])
                    or path.read_bytes() != revision["source"].encode("utf-8")
                    or admission["scope_digest"] != scope or execution["binding"]["source_sha256"] != revision["source_sha256"]
                    or admission["deadline_epoch"] != budget["deadline_epoch"]):
                raise CodeProgramError("Candidate source, execution or original deadline differs")
            if phase == "initial":
                if revision["source_sha256"] != task["input_snapshot"]["program_source_sha256"] or revision["parent_source_sha256"] is not None:
                    raise CodeProgramError("Original generated code binding differs")
                initial = execution
            elif (revision["parent_source_sha256"] != code_hashes[0] or initial["status"] != "python_error"
                    or initial.get("cleanup_verified") is not True):
                raise CodeProgramError("Patch is not bound to a confirmed original Python failure")
            code_hashes.append(revision["source_sha256"])
            execution_hashes.append(content_hash(execution))
    last = ledger.get_record("program_execution", base + ":" + phases[-1])
    if (last["status"] != "ok" or last["output"] != {"run_id": science["result"]["run_id"]}
            or completion["code_hashes"] != code_hashes or completion["execution_hashes"] != execution_hashes
            or completion["scientific_result_sha256"] != content_hash(science["result"])
            or completion["final_phase"] != phases[-1]
            or saved.get("program_validation", {}).get("completion_sha256") != content_hash(completion)
            or {k: v for k, v in saved.items() if k != "program_validation"} != science["result"]):
        raise CodeProgramError("Program output or final scientific result binding differs")


class CodeProgramService:
    # Lazy construction is essential: cleanup_confirmed can run inside the
    # existing chat controller's SQLite write transaction.
    def __init__(self, workspace, *, analysis=None, runtime=None, clock=time.time):
        self.workspace, self._analysis, self.runtime, self.clock = workspace, analysis, runtime, clock
        self._ledger = self._queue = None
        self._claims = {}

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = Ledger(self.workspace)
        return self._ledger

    @property
    def queue(self):
        if self._queue is None:
            self._queue = TaskQueue(self.workspace)
        return self._queue

    @property
    def analysis(self):
        if self._analysis is None:
            from .analysis import AnalysisService
            self._analysis = AnalysisService(self.workspace)
        return self._analysis

    def submit(self, initial_source, options, *, idempotency_key, submission_hook=None, policy_correction=None):
        from .agent_loop import validate_options
        from .analysis import MAX_BYTES, MAX_CELLS, MAX_GENES
        from .dataset_origin import origin_context
        initial_source = _source(initial_source)
        options = validate_options(options, self.ledger)
        if options.get("execution_mode") != MODE:
            raise CodeProgramError("An explicit versioned Python program mode is required")
        if policy_correction is not None:
            rejected = _verify_policy_correction(self.ledger, policy_correction, initial_source, options=options)
            if idempotency_key != f"{rejected['turn_id']}:execute_program" or submission_hook is None:
                raise CodeProgramError("Policy correction requires its original chat submission binding")
        asset = self.analysis.datasets.get_asset(options["asset_id"])
        _, digest = self.analysis._source(asset)
        snapshot = {k: options[k] for k in ("asset_id", "count_source", "count_provenance", "expected_doublet_rate")}
        snapshot.update(source_sha256=digest, program_source_sha256=_sha(initial_source), program_source=initial_source,
            execution_authorized=True, execution_mode=MODE, count_provenance_status="caller_declared_not_independently_verified",
            **origin_context(options.get("dataset_origin", "unknown"), options.get("dataset_origin_refs")))
        if policy_correction is not None:
            snapshot["program_policy_correction"] = deepcopy(policy_correction)
        profile = {"skill": POLICY, "max_cells": MAX_CELLS, "max_genes": MAX_GENES, "max_bytes": MAX_BYTES,
            "max_rss_mb": LIMITS["max_rss_mb"], "execution_seed": 0, "scientific_claim_allowed": False,
            "program_limits": dict(LIMITS), "generated_code_trust": "candidate_only"}
        hook = submission_hook
        if policy_correction is not None:
            def hook(conn, child):
                submission_hook(conn, child)
                # The queue insertion, immutable submission and both ownership
                # directions must commit together. A merely non-null/no-op
                # callback cannot leave an unowned policy-corrected task.
                self._require_policy_owner(conn, child)
        return self.queue.submit(KIND, snapshot, profile, {"max_calls": 0, "max_tokens": 0, "max_cost": 0},
                                 idempotency_key, submission_hook=hook)

    def get_task_snapshot(self, task_id):
        return self.analysis.get_task_snapshot(task_id)

    def get_public_result_summary(self, *args, **kwargs):
        return self.analysis.get_public_result_summary(*args, **kwargs)

    def _claim(self, task_id):
        task = self._claims.get(task_id)
        if not task:
            raise PermissionError("Only the original live program controller may continue this attempt")
        return task

    def _require_policy_owner(self, conn, task):
        reference = task["input_snapshot"].get("program_policy_correction")
        if reference is None:
            return
        from .chat_runs import ChatRunService
        rejected = self.ledger.get_record("chat_program_policy_rejection", reference["record_id"], conn=conn)
        if not rejected or content_hash(rejected) != reference["record_sha256"]:
            raise PermissionError("Policy correction has no matching original rejected proposal")
        control = ChatRunService(self.ledger)
        bound = control._bound_owner(conn, task)
        if bound is None or bound[0]["turn_id"] != rejected["turn_id"]:
            raise PermissionError("Policy correction requires its original live chat child binding")
        control.task_execution_guard(conn, task)

    def _check(self, task, execution_guard=None, *, allow_cancel=False, check_deadline=True):
        from .chat_runs import ChatRunService
        with self.ledger.transaction() as tx:
            row = self.queue._require_lease(tx, task["task_id"], task["fencing_token"])
            if row["attempt"] != task["attempt"] or row["payload_digest"] != task["payload_digest"]:
                raise PermissionError("Program task generation changed")
            if (json.loads(row["input_json"]) != task["input_snapshot"]
                    or json.loads(row["profile_json"]) != task["profile_snapshot"]
                    or json.loads(row["budget_json"]) != task["budget"]):
                raise PermissionError("Program frozen task input or profile changed")
            if row["status"] != "running" and not allow_cancel:
                raise PermissionError("Program cancelled before further execution")
            if not allow_cancel:
                self._require_policy_owner(tx, self.queue._public(row))
                ChatRunService(self.ledger).task_execution_guard(tx, self.queue._public(row))
                if execution_guard:
                    execution_guard(tx, self.queue._public(row))
            budget = self.ledger.get_record("program_budget", _base(task), conn=tx)
            if check_deadline and budget and self.clock() >= budget["deadline_epoch"]:
                raise TimeoutError("Original program deadline exhausted")
        asset = self.analysis.datasets.get_asset(task["input_snapshot"]["asset_id"])
        if self.analysis._source(asset)[1] != task["input_snapshot"]["source_sha256"]:
            raise PermissionError("Frozen program data changed")

    def _record_source(self, task, phase, source, parent):
        from .analysis import _path_inside, _attempt_directory
        root = _path_inside(self.workspace.artifacts_dir / "programs" / _attempt_directory(task), self.workspace.artifacts_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / (phase + ".py")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(source)
        revision = {"task_id": task["task_id"], "attempt": task["attempt"], "phase": phase,
            "source": source, "source_sha256": _sha(source), "parent_source_sha256": parent,
            "relative_path": str(path.relative_to(self.workspace.artifacts_dir)),
            "trust": "candidate_generated_code", "created_at": utcnow()}
        self.ledger.put_record("program_code_revision", _base(task) + ":" + phase, revision)
        return root, revision

    def _progress(self, task, phase, binding, event, payload):
        if event not in {"started", "updated", "cleanup"}:
            raise CodeProgramError("Unsupported runtime observation event")
        # Runtime-generated process facts must not replace the immutable scope.
        value = {**deepcopy(payload), **binding}
        key = _base(task) + ":" + phase
        kind = {"started": "program_process_started", "updated": "program_process_observation", "cleanup": "program_process_cleanup"}[event]
        rid = key + (":" + content_hash(value) if event == "updated" else "")
        with self.ledger.transaction() as tx:
            self.ledger.put_record(kind, rid, value, conn=tx)
            self.ledger.set_state("program_process:" + key, value, conn=tx)

    def _science(self, task, operation, guard, runtime):
        self._check(task, guard)
        if operation not in {"inspect_dataset", "run_scrublet"}:
            raise CodeProgramError("Unregistered scientific operation")
        base = _base(task)
        with self.ledger.transaction() as tx:
            row = self.queue._require_lease(tx, task["task_id"], task["fencing_token"])
            if row["status"] != "running":
                raise PermissionError("Program cancelled before tool admission")
            state = self.ledger.get_state("program:" + base, conn=tx)
            if state["api_messages"] >= LIMITS["api_messages"]:
                raise CodeProgramError("Program API message ceiling exhausted")
            state["api_messages"] += 1
            self.ledger.set_state("program:" + base, state, conn=tx)
            self.ledger.put_record("program_api_call", base + ":" + str(state["api_messages"]),
                {"operation": operation, "scope_digest": _scope(task), "sequence": state["api_messages"]}, conn=tx)
        if operation == "inspect_dataset":
            cached = self.ledger.get_record("program_profile", base)
            if cached is None:
                from .agent_loop import AnalysisAgentLoop
                cached = AnalysisAgentLoop(self.ledger, None)._tool("inspect_dataset", task["input_snapshot"],
                    turn_id=task["task_id"], index=0, execution_guard=guard)
                self.ledger.put_record("program_profile", base, cached)
            return cached
        completed = self.ledger.get_record("program_science_result", base)
        if completed:
            result = completed["result"]
            if completed["scope_digest"] != _scope(task) or not self.analysis.revalidate_execution(task, result)["passed"]:
                raise CodeProgramError("Committed scientific artifacts can no longer be verified")
        else:
            with self.ledger.transaction() as tx:
                row = self.queue._require_lease(tx, task["task_id"], task["fencing_token"])
                if row["status"] != "running" or self.ledger.get_record("program_science_admission", base, conn=tx):
                    raise CodeProgramError("Scientific effect already started; no automatic repetition")
                self.ledger.put_record("program_science_admission", base,
                    {"scope_digest": _scope(task), "effect": "started_once", "scientific_fit_limit": 1,
                     "task_id": task["task_id"], "attempt": task["attempt"]}, conn=tx)
            deadline = self.ledger.get_record("program_budget", base)["deadline_epoch"]
            try:
                result = self.analysis._execute_supervised(task, deadline_epoch=deadline,
                    extra_rss_mb=getattr(runtime, "current_rss_mb", lambda: 0))
            except Exception as exc:
                # Scientific diagnostics can include local paths or data.
                # Keep them local; only a generic failure returns to the guest
                # and hence to the following model/patch request.
                self.ledger.put_record("program_science_failure", base,
                    {"scope_digest": _scope(task), "type": type(exc).__name__, "message": str(exc)[:2000]})
                raise CodeProgramError("Frozen scientific operation did not complete; local records retain details") from None
            self._check(task, guard)
            if not result.get("validation", {}).get("passed") or not self.analysis.revalidate_execution(task, result)["passed"]:
                raise CodeProgramError("Scientific operation did not pass independent validation")
            self.ledger.put_record("program_science_result", base, {"scope_digest": _scope(task), "result": result})
        return {"status": "scientific_artifacts_validated", "run_id": result["run_id"],
                "scientific_truth_verified": False, "configuration_change_allowed": False}

    def execute_initial(self, task_id, *, execution_guard=None):
        existing = self.get_task_snapshot(task_id)
        if existing["kind"] != KIND:
            raise CodeProgramError("Not a registered program task")
        if existing["status"] != "queued":
            return self._public(existing)
        if existing["attempt"] != 0:
            raise PermissionError("Program attempts are not automatically restarted after retry")
        if existing["input_snapshot"].get("program_policy_correction") is not None:
            original_guard = execution_guard
            def execution_guard(conn, child):
                self._require_policy_owner(conn, child)
                if original_guard is not None:
                    original_guard(conn, child)
        task = self.queue.claim("workbench-program", lease_seconds=600, expected_task_id=task_id, execution_guard=execution_guard)
        if task is None:
            return self._public(existing)
        self._claims[task_id] = task
        base = _base(task)
        with self.ledger.transaction() as tx:
            self.ledger.put_record("program_budget", base,
                {"scope_digest": _scope(task), "limits": dict(LIMITS), "deadline_epoch": self.clock() + LIMITS["whole_seconds"],
                 "fencing_token_digest": content_hash(task["fencing_token"]), "automatic_resume": False}, conn=tx)
            self.ledger.set_state("program:" + base, {"phase": "initial", "state": "executing", "api_messages": 0}, conn=tx)
        return self._run_phase(task, "initial", task["input_snapshot"]["program_source"], None, execution_guard)

    def apply_patch(self, task_id, *, parent_source_sha256, source, execution_guard=None):
        task = self._claim(task_id)
        self._check(task, execution_guard)
        if task["input_snapshot"].get("program_policy_correction") is not None:
            raise PermissionError("The original policy correction consumed this turn's single repair allowance")
        source = _source(source)
        base = _base(task)
        initial = self.ledger.get_record("program_code_revision", base + ":initial")
        if (not initial or parent_source_sha256 != initial["source_sha256"] or _sha(source) == parent_source_sha256):
            raise CodeProgramError("Patch must replace exactly the recorded failed original source")
        with self.ledger.transaction() as tx:
            row = self.queue._require_lease(tx, task_id, task["fencing_token"])
            state = self.ledger.get_state("program:" + base, conn=tx)
            if row["status"] != "running" or state["state"] != "awaiting_patch" or self.ledger.get_record("program_phase_admission", base + ":patch", conn=tx):
                raise PermissionError("No unused patch admission on this original running attempt")
            state.update(state="patch_reserved", phase="patch")
            self.ledger.set_state("program:" + base, state, conn=tx)
        return self._run_phase(task, "patch", source, parent_source_sha256, execution_guard)

    def _run_phase(self, task, phase, source, parent, guard):
        base = _base(task)
        try:
            self._check(task, guard)
            root, revision = self._record_source(task, phase, source, parent)
            budget = self.ledger.get_record("program_budget", base)
            binding = {"namespace": self.workspace.namespace, "task_id": task["task_id"], "attempt": task["attempt"],
                "payload_digest": task["payload_digest"], "fencing_token_digest": content_hash(task["fencing_token"]),
                "phase": phase, "source_sha256": revision["source_sha256"], "parent_source_sha256": parent}
            self.ledger.put_record("program_phase_admission", base + ":" + phase,
                {"binding": binding, "scope_digest": _scope(task), "deadline_epoch": budget["deadline_epoch"]})
            if self.runtime is None:
                from .code_runtime import CodeRuntime
                self.runtime = CodeRuntime()
            runtime = self.runtime
            receipt = runtime.run(source, directory=root / phase, binding=binding,
                deadline_epoch=budget["deadline_epoch"], max_rss_mb=LIMITS["max_rss_mb"],
                tool_handler=lambda op: self._science(task, op, guard, runtime),
                guard=lambda: self._check(task, guard),
                progress=lambda event, payload: self._progress(task, phase, binding, event, payload))
            if receipt.get("binding") != binding or receipt.get("source_sha256") != revision["source_sha256"]:
                raise CodeProgramError("Runtime returned a different code binding")
            started = self.ledger.get_record("program_process_started", base + ":" + phase)
            cleaned = self.ledger.get_record("program_process_cleanup", base + ":" + phase)
            receipt = {**receipt, "process_start_sha256": content_hash(started) if started else None,
                       "process_cleanup_sha256": content_hash(cleaned) if cleaned else None}
            self.ledger.put_record("program_execution", base + ":" + phase, receipt)
            self._check(task, guard)
            science = self.ledger.get_record("program_science_result", base)
            science_started = self.ledger.get_record("program_science_admission", base)
            clean = receipt.get("cleanup_verified") is True
            repairable = (phase == "initial" and not task["input_snapshot"].get("program_policy_correction")
                and receipt["status"] == "python_error" and clean
                and (not science_started or (science and self.analysis.revalidate_execution(task, science["result"])["passed"])))
            if repairable:
                with self.ledger.transaction() as tx:
                    self.queue._require_lease(tx, task["task_id"], task["fencing_token"])
                    state = self.ledger.get_state("program:" + base, conn=tx)
                    state.update(state="awaiting_patch", phase="initial")
                    self.ledger.set_state("program:" + base, state, conn=tx)
                self.queue.checkpoint(task["task_id"], task["fencing_token"], "awaiting_code_patch",
                    {"source_sha256": revision["source_sha256"], "original_deadline_epoch": budget["deadline_epoch"], "patches_remaining": 1})
                return self._public(self.get_task_snapshot(task["task_id"]), receipt, status="awaiting_patch", repair_allowed=True)
            if (receipt["status"] != "ok" or not clean or not science or
                    receipt.get("output") != {"run_id": science["result"]["run_id"]}):
                state = "result_unknown" if (not clean or (science_started and not science) or receipt["status"] == "unknown") else "failed"
                return self.abort(task["task_id"], reason="Program or scientific output did not pass completion checks", status=state)
            phases = ["initial", "patch"] if phase == "patch" else ["initial"]
            completion = {"scope_digest": _scope(task), "final_phase": phase,
                "code_hashes": [self.ledger.get_record("program_code_revision", base + ":" + p)["source_sha256"] for p in phases],
                "execution_hashes": [content_hash(self.ledger.get_record("program_execution", base + ":" + p)) for p in phases],
                "scientific_result_sha256": content_hash(science["result"])}
            self.ledger.put_record("program_completion", base, completion)
            result = {**science["result"], "program_validation": {"schema": POLICY,
                "completion_sha256": content_hash(completion), "code_executions": len(phases),
                "patches_used": int(phase == "patch" or bool(task["input_snapshot"].get("program_policy_correction"))),
                "scientific_operations": 1}}
            verify_program_chain(self.analysis, task, result)
            self.ledger.put_record("analysis_result", base, result)
            self._check(task, guard)
            finished = self.queue.finish(task["task_id"], task["fencing_token"], "succeeded", result=result)
            return self._public(finished, receipt)
        except Exception as exc:
            return self.abort(task["task_id"], reason=f"{type(exc).__name__}:{exc}", status="failed")

    def abort(self, task_id, *, reason, status="failed"):
        task = self._claim(task_id)
        if status not in {"failed", "cancelled", "result_unknown"}:
            raise CodeProgramError("Invalid terminal program state")
        current = self.get_task_snapshot(task_id)
        if current["status"] not in {"running", "cancel_requested"}:
            return self._public(current)
        if current["attempt"] != task["attempt"] or current.get("fencing_token") != task["fencing_token"]:
            return self._public(current, status="result_unknown")
        if current["status"] == "cancel_requested":
            status = "cancelled"
        base = _base(task)
        if self.ledger.get_record("program_science_admission", base) and not self.ledger.get_record("program_science_result", base):
            status = "result_unknown"
        error = {"type": "ProgramNotCompleted", "message": "程序或科学产物未完成验收；详情保存在本地记录。", "outcome": status}
        self.ledger.put_record("program_local_diagnostic", base,
            {"reason": str(reason)[:2000], "public_error": error})
        self.ledger.put_record("program_terminal", base, {"status": status, "error": error, "automatic_resume": False})
        try:
            finished = self.queue.finish(task_id, task["fencing_token"], status, error=error)
        except LeaseLost:
            finished = self.get_task_snapshot(task_id)
        return self._public(finished)

    def _public(self, task, receipt=None, *, status=None, repair_allowed=False):
        base = _base(task)
        latest = receipt
        if latest is None:
            latest = self.ledger.get_record("program_execution", base + ":patch") or self.ledger.get_record("program_execution", base + ":initial")
        code = self.ledger.get_record("program_code_revision", base + ":patch") or self.ledger.get_record("program_code_revision", base + ":initial")
        result = task.get("result") or {}
        summary = None
        if task["status"] == "succeeded" and result.get("run_id"):
            summary = self.analysis.get_public_result_summary(task["task_id"], attempt=task["attempt"], expected_run_id=result["run_id"])
        return {"tool": "repair_program" if code and code["phase"] == "patch" else "execute_program",
            "task_id": task["task_id"], "attempt": task["attempt"], "run_id": result.get("run_id"),
            "status": status or task["status"], "source_sha256": code["source_sha256"] if code else task["input_snapshot"].get("program_source_sha256"),
            "repair_allowed": repair_allowed, "error": (latest or {}).get("error") or task.get("error"),
            "summary": summary, "program_execution_id": base + ":" + code["phase"] if code else None}

    def cleanup_confirmed(self, task_id, attempt, *, conn=None):
        if conn is None:
            with self.ledger.connect() as tx:
                return self.cleanup_confirmed(task_id, attempt, conn=tx)
        row = conn.execute("SELECT * FROM workbench_tasks WHERE namespace=? AND task_id=?", (self.workspace.namespace, task_id)).fetchone()
        if (not row or row["kind"] != KIND or row["attempt"] != attempt
                or row["status"] in {"running", "queued", "cancel_requested"}):
            return False
        task = {"task_id": task_id, "attempt": attempt}
        base = _base(task)
        phases = [p for p in ("initial", "patch") if _read(conn, "program_phase_admission", base + ":" + p)]
        if not phases or not all(_phase_proof(conn, task, p) for p in phases):
            return False
        science_started = _read(conn, "analysis_process_started", base)
        effect = _read(conn, "program_science_admission", base)
        committed = _read(conn, "program_science_result", base)
        if effect and not committed and not science_started:
            return False  # Missing start receipt does not prove no spawn.
        if science_started:
            science_cleanup = _read(conn, "analysis_process_cleanup", base)
            if (not science_cleanup or science_cleanup.get("cleanup_verified") is not True
                    or any(science_cleanup.get(k) != science_started.get(k) for k in
                        ("namespace", "task_id", "attempt", "payload_digest", "root", "supervisor", "fencing_token_digest"))
                    or (science_cleanup.get("cleanup") or {}).get("residual_processes")):
                return False
        return True

    def cleanup_owned_processes(self, task_id, *, attempt, expected_payload_digest):
        task = self.get_task_snapshot(task_id)
        if task["kind"] != KIND or task["payload_digest"] != expected_payload_digest:
            raise PermissionError("Program cleanup binding differs")
        base = _base({**task, "attempt": attempt})
        results = []
        for phase in ("initial", "patch"):
            if self.ledger.get_record("program_process_started", base + ":" + phase):
                with self.ledger.connect() as conn:
                    done = _phase_proof(conn, {**task, "attempt": attempt}, phase)
                if not done:
                    results.append(self.analysis.cleanup_owned_processes(task_id, attempt=attempt,
                        expected_payload_digest=expected_payload_digest, _program_phase=phase))
        if self.ledger.get_record("analysis_process_started", base):
            proof = self.analysis.get_process_control(task_id, attempt=attempt)
            if not proof.get("cleanup_verified"):
                results.append(self.analysis.cleanup_owned_processes(task_id, attempt=attempt, expected_payload_digest=expected_payload_digest))
        # A dead coordinator remains unknown even after its owned children are
        # stopped. Cleanup does not finalize, resume or fit anything.
        with self.ledger.connect() as conn:
            phases = [p for p in ("initial", "patch") if _read(conn, "program_phase_admission", base + ":" + p)]
            phase_clean = bool(phases) and all(_phase_proof(conn, {**task, "attempt": attempt}, p) for p in phases)
            if (_read(conn, "program_science_admission", base) and not _read(conn, "program_science_result", base)
                    and not _read(conn, "analysis_process_started", base)):
                phase_clean = False
        known = phase_clean and all(r.get("cleanup_verified") is True for r in results)
        return {"status": "known_owned_processes_stopped" if known else "cleanup_unknown",
            "cleanup_verified": known, "new_execution": False, "phase_results": results}
