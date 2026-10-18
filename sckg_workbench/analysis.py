"""One bounded, explicitly authorized Scrublet preview on existing control planes.

No model, installation, second queue, or scientific-performance claim is made.
Count provenance is the caller's declaration, never inferred from integer values.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time

from .datasets import DatasetService, _fingerprint, _local_path, _open_local
from .dataset_origin import ORIGIN_FIELDS, origin_context, origin_from_snapshot
from .storage import Ledger, Workspace, content_hash, canonical_json
from .tasks import IdempotencyConflict, LeaseLost, TaskQueue, InvalidTransition


KIND = "analysis.scrublet"
PROGRAM_KIND = "analysis.scrublet.program.v1"
ANALYSIS_KINDS = frozenset({KIND, PROGRAM_KIND})
MAX_BYTES = 25 * 1024 * 1024
MAX_CELLS, MAX_GENES = 1000, 10000
PUBLIC_SUMMARY_SCHEMA = "sckg-public-preview-summary-v1"
WORKER_GRANT_BYTES = 8192
WORKER_GRANT_READ_SECONDS = 30
RUNTIME_HOME_ENV = "SCKG_WORKBENCH_RUNTIME_PACK_HOME"


def _analysis_worker_environment(guard: Path, workspace: Workspace) -> dict:
    """Keep task state private while handing down server-selected runtime home.

    The parent reads default_sckg_home before replacing SCKG_HOME for its worker.
    No asset/profile/model field selects the installed runtime location.
    """
    from execution.runtime_pack_manager import default_sckg_home
    runtime_home = default_sckg_home().expanduser().resolve()
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "CONDA_EXE") if k in os.environ}
    env.update({"PYTHONPATH": os.pathsep.join(dict.fromkeys([os.environ.get("PYTHONPATH", ""), str(Path(__file__).resolve().parents[1])])),
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "SCKG_HOME": str(guard / "legacy-home"), "SCKG_WORKBENCH_HOME": str(workspace.root),
                RUNTIME_HOME_ENV: str(runtime_home),
                "SCKG_ENV_FILE": str(guard / "disabled-default-dotenv"),
                "SCKG_PRIVACY_MODE": "strict_offline", "SCKG_EXTERNAL_NETWORK_ALLOWED": "false",
                "SCKG_OFFLINE_LLM": "true"})
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    return env


def _strict_summary_rows(payload: bytes, *, expected_cells: int, axis_digest: str):
    """Parse precisely the hashed snapshot; never skip or coerce an invalid row."""
    if type(expected_cells) is not int or not 1 <= expected_cells <= MAX_CELLS:
        raise ValueError("invalid preview size")
    reader = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), delimiter="\t", strict=True)
    if next(reader, None) != ["obs_id", "doublet_score", "predicted_doublet", "ground_truth_doublet"]:
        raise ValueError("invalid result header")
    ids, scores, calls = [], [], []
    for row in reader:
        if len(row) != 4 or not row[0] or row[2] not in {"true", "false"} or row[3] != "":
            raise ValueError("invalid preview result row")
        score = float(row[1])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid preview score")
        ids.append(row[0]); scores.append(score); calls.append(row[2] == "true")
        if len(ids) > expected_cells:
            raise ValueError("too many result rows")
    if len(ids) != expected_cells or len(set(ids)) != len(ids) or content_hash(ids) != axis_digest:
        raise ValueError("preview axis differs from validated axis")
    return ids, scores, calls


class AnalysisProcessError(RuntimeError):
    def __init__(self, message, resource):
        super().__init__(message)
        self.resource = resource


def _attempt_key(task: dict) -> str:
    return f"{task['task_id']}:attempt:{task['attempt']}"


def _attempt_directory(task: dict) -> str:
    return content_hash([task["task_id"], task["attempt"]])[:24]


def _read_worker_start_grant(stream, *, timeout_seconds=WORKER_GRANT_READ_SECONDS) -> dict:
    """Read one bounded private stdin capability, not model instructions."""
    deadline, payload = time.monotonic() + timeout_seconds, bytearray()
    fd = stream.fileno()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], max(0, remaining))[0]:
            raise PermissionError("worker start grant timed out")
        chunk = os.read(fd, WORKER_GRANT_BYTES + 1 - len(payload))
        if not chunk:
            raise PermissionError("worker start grant missing or incomplete")
        payload.extend(chunk)
        if len(payload) > WORKER_GRANT_BYTES:
            raise PermissionError("worker start grant exceeds input bound")
        if b"\n" in payload:
            line, extra = payload.split(b"\n", 1)
            if extra.strip():
                raise PermissionError("worker accepts exactly one grant")
            try:
                grant = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError) as exc:
                raise PermissionError("worker start grant is invalid") from exc
            if not isinstance(grant, dict):
                raise PermissionError("worker start grant must be an object")
            return grant


def _authorize_worker_start(service, task: dict, *, stream=None):
    """Only this already spawned worker may consume the owner's dispatch grant.

    Ordinary queued claims still require a positively observed live owner. A
    grant authorizes this exact dispatch point, not future thread liveness.
    """
    from .chat_runs import ChatRunService
    reverse_key = f"chat_child_owner:{task['task_id']}:attempt:{task['attempt']}"
    bound = service.ledger.get_state(reverse_key) is not None
    grant = _read_worker_start_grant(stream or sys.stdin.buffer) if bound else None
    with service.ledger.transaction() as tx:
        row = service.queue._require_lease(tx, task["task_id"], task["fencing_token"])
        if row["status"] != "running" or row["attempt"] != task["attempt"]:
            raise PermissionError("worker generation was cancelled or changed before execution")
        return ChatRunService(service.ledger).consume_worker_start_grant(tx, service.queue._public(row), grant)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_inside(path: Path, root: Path) -> Path:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("analysis paths may not traverse symlinks")
    path = path.resolve()
    path.relative_to(root.resolve())
    return path


def _local_hdf5_only(path: Path) -> None:
    """Admit one self-contained HDF5 file; do not follow external/virtual data."""
    import h5py
    with h5py.File(path, "r") as file:
        pending, seen, count = [file], set(), 0
        while pending:
            group = pending.pop()
            address = h5py.h5o.get_info(group.id).addr
            if address in seen:
                continue
            seen.add(address)
            for name in group:
                count += 1
                if count > 20000:
                    raise ValueError("analysis HDF5 metadata exceeds admission bound")
                if not isinstance(group.get(name, getlink=True), h5py.HardLink):
                    raise ValueError("analysis does not support HDF5 soft/external links")
                child = group[name]
                if isinstance(child, h5py.Group):
                    pending.append(child)
                elif isinstance(child, h5py.Dataset) and (child.is_virtual or child.external):
                    raise ValueError("analysis does not support virtual/external HDF5 datasets")


def validate_outputs(run, *, preview_path: Path, source_path: Path, frozen: dict,
                     output_root: Path) -> dict:
    """Independent external checks against the pre-execution frozen binding."""
    from execution.validators.doublet import DoubletValidator
    import anndata as ad

    failures = []
    details = {}
    try:
        for path in (source_path, preview_path, Path(frozen["notebook_path"])):
            _path_inside(path, path.parent)
        if _sha(source_path) != frozen["source_sha256"]:
            failures.append("original_input_changed")
        if _sha(preview_path) != frozen["preview_sha256"] or run.input_hash != frozen["preview_sha256"]:
            failures.append("preview_input_binding_mismatch")
        if _sha(Path(frozen["notebook_path"])) != frozen["notebook_sha256"]:
            failures.append("notebook_binding_mismatch")
        if run.parameters != frozen["parameters"]:
            failures.append("run_parameters_differ_from_frozen")
        if run.tool_name != "Scrublet" or run.tool_version != "0.2.3":
            failures.append("tool_version_mismatch")
        if run.process_cleanup.residual_processes:
            failures.append("residual_processes")
        # The immutable execution receipt supplies expected output digests.
        for name, text in run.artifact_paths.items():
            path = _path_inside(Path(text), output_root)
            if not path.is_file() or _sha(path) != run.artifact_hashes.get(name):
                failures.append("artifact_hash_mismatch:" + name)
        if failures:
            return {"validator": "workbench-scrublet-preview-v1", "passed": False,
                    "failures": sorted(set(failures)), "details": details,
                    "scientific_claim_allowed": False, "authority": "preview_engineering_only"}
        base = DoubletValidator().validate(run, expected_cells=frozen["expected_cells"])
        failures.extend(base.failures)
        details["doublet_validator"] = base.model_dump(mode="json")
        data = ad.read_h5ad(preview_path, backed="r")
        try:
            expected_ids = list(map(str, data.obs_names))
        finally:
            if getattr(data, "file", None) is not None:
                data.file.close()
        tsv = _path_inside(Path(run.artifact_paths["doublet_results.tsv"]), output_root)
        with tsv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        actual_ids = [r.get("obs_id", "") for r in rows]
        details["axis_policy"] = "exact_preview_obs_order"
        details["axis_ids_sha256"] = content_hash(expected_ids)
        if any(not x for x in actual_ids) or len(set(actual_ids)) != len(actual_ids):
            failures.append("prediction_ids_empty_or_duplicate")
        if actual_ids != expected_ids:
            failures.append("prediction_axis_mismatch")
        parameters = json.loads(Path(run.artifact_paths["parameters.json"]).read_text())
        if parameters != frozen["parameters"]:
            failures.append("parameter_artifact_mismatch")
        metadata = json.loads(Path(run.artifact_paths["result_metadata.json"]).read_text())
        for key, expected in {"input_hash": frozen["preview_sha256"],
                              "fixture_id": frozen["preview_id"],
                              "n_cells": len(expected_ids), "scrublet_version": "0.2.3",
                              "execution_seed": 0}.items():
            if metadata.get(key) != expected:
                failures.append("metadata_binding_mismatch:" + key)
        if run.status != "succeeded" or run.exit_code != 0:
            failures.append("execution_not_successful")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failures.append(f"external_validation_error:{type(exc).__name__}:{exc}")
    return {"validator": "workbench-scrublet-preview-v1", "passed": not failures,
            "failures": sorted(set(failures)), "details": details,
            "scientific_claim_allowed": False, "authority": "preview_engineering_only"}


class AnalysisService:
    def __init__(self, workspace: Workspace, *, max_rss_mb: float = 2048):
        if isinstance(max_rss_mb, bool) or not math.isfinite(max_rss_mb) or not 0 < max_rss_mb <= 2048:
            raise ValueError("analysis max_rss_mb must be finite and in (0, 2048]")
        self.workspace = workspace
        self.datasets = DatasetService(workspace)
        self.ledger = Ledger(workspace)
        self.queue = TaskQueue(workspace)
        self.max_rss_mb = max_rss_mb

    def submit_scrublet(self, asset_id: str, count_source: str, count_provenance: str,
                        expected_doublet_rate: float, idempotency_key: str, *,
                        execution_authorized: bool = False, dataset_origin: str = "unknown",
                        dataset_origin_refs: list[str] | None = None, submission_hook=None) -> dict:
        declared_origin = origin_context(dataset_origin, dataset_origin_refs)
        if count_source != "X":
            raise ValueError("this skill supports only explicitly declared X raw counts")
        if not isinstance(count_provenance, str) or not count_provenance.strip():
            raise ValueError("a caller-declared raw-count provenance is required")
        if len(count_provenance) > 4000:
            raise ValueError("count provenance exceeds 4000 characters")
        if type(execution_authorized) is not bool:
            raise ValueError("execution_authorized must be an explicit boolean")
        if isinstance(expected_doublet_rate, bool) or not isinstance(expected_doublet_rate, (int, float)) or not math.isfinite(expected_doublet_rate) or not .001 <= expected_doublet_rate <= .25:
            raise ValueError("expected_doublet_rate must be explicitly supplied within the contract range")
        asset = self.datasets.get_asset(asset_id)
        if asset is None or asset["namespace"] != self.workspace.namespace:
            raise ValueError("dataset asset not found in this workspace")
        source, digest = self._source(asset)
        snapshot = {"asset_id": asset_id, "source_sha256": digest, "count_source": count_source,
                    "count_provenance": count_provenance, "count_provenance_status": "caller_declared_not_independently_verified",
                    "expected_doublet_rate": expected_doublet_rate, "execution_authorized": execution_authorized,
                    **declared_origin}
        from .analysis_repair import PROFILE, POLICY, LIMITS
        legacy_profile = {"skill": "scrublet-preview-v1", "max_cells": MAX_CELLS, "max_genes": MAX_GENES,
             "max_bytes": MAX_BYTES, "max_rss_mb": self.max_rss_mb, "execution_seed": 0,
             "scientific_claim_allowed": False}
        profile = {**legacy_profile, "skill": PROFILE, "execution_budget": dict(LIMITS),
                   "operational_recovery_policy": POLICY}
        budget = {"max_calls": 0, "max_tokens": 0, "max_cost": 0}
        try:
            return self.queue.submit(KIND, snapshot, profile, budget, idempotency_key,
                                     submission_hook=submission_hook)
        except IdempotencyConflict:
            # Preserve only an exactly equivalent pre-origin request. Do not
            # mutate its immutable snapshot, change source claims, or re-run it.
            with self.ledger.transaction() as tx:
                row = tx.execute("SELECT * FROM workbench_tasks WHERE namespace=? AND idempotency_key=?",
                                 (self.workspace.namespace, idempotency_key)).fetchone()
                old = self.queue._public(row) if row else None
                same_snapshot = old is not None and old["input_snapshot"] == snapshot
                legacy_origin = (old is not None and not (ORIGIN_FIELDS & old["input_snapshot"].keys())
                    and declared_origin == origin_context()
                    and old["input_snapshot"] == {k: v for k, v in snapshot.items() if k not in ORIGIN_FIELDS})
                if (old is not None and old["kind"] == KIND
                        and old["profile_snapshot"] in (profile, legacy_profile) and old["budget"] == budget
                        and (same_snapshot or legacy_origin)):
                    if submission_hook is not None:
                        submission_hook(tx, old)
                    return old
            raise

    def _source(self, asset: dict) -> tuple[Path, str]:
        _path_inside(Path(asset["path"]), Path(asset["path"]).parent)
        path = _local_path(asset["path"])
        with _open_local(path) as (handle, signature):
            if signature != asset["stat_signature"] or _fingerprint(handle, signature["size"]) != asset["bounded_fingerprint"]:
                raise ValueError("dataset changed since registration")
            if signature["size"] > MAX_BYTES:
                raise ValueError("analysis currently supports input files of at most 25 MiB")
            digest = hashlib.sha256(handle.read(MAX_BYTES + 1)).hexdigest()
        return path, digest

    def run_once(self, task_id: str | None = None, *, worker_id: str = "workbench-analysis",
                 execution_guard=None) -> dict | None:
        if task_id is not None:
            existing = self.get_task_snapshot(task_id)
            if existing["kind"] != KIND:
                raise ValueError("task is not a workbench Scrublet analysis")
            if existing["status"] != "queued":
                return existing  # Never automatically repeat a possible analysis effect.
        peek = self.queue.peek_next()
        if peek is None or peek["kind"] != KIND or (task_id and peek["task_id"] != task_id):
            return None
        task = self.queue.claim(worker_id, lease_seconds=600, expected_task_id=peek["task_id"],
                                execution_guard=execution_guard)
        if task is None:
            return None
        token, task_id = task["fencing_token"], task["task_id"]
        record_id = _attempt_key(task)
        try:
            if task["input_snapshot"]["execution_authorized"] is not True:
                raise PermissionError("explicit_local_analysis_authorization_missing")
            self.queue.check_budget(task_id, token, {"calls": 0, "tokens": 0, "cost": 0})
            with self.ledger.transaction() as tx:
                current = self.queue._require_lease(tx, task_id, token)
                if current["status"] == "cancel_requested":
                    raise InvalidTransition("Cancellation requested before analysis execution")
                from .chat_runs import ChatRunService
                ChatRunService(self.ledger).task_execution_guard(tx, self.queue._public(current))
                if execution_guard is not None:
                    execution_guard(tx, self.queue._public(current))
            result = self._execute_supervised(task)
            result = {**result, "task_id": task_id, "attempt": task["attempt"],
                      **origin_from_snapshot(task["input_snapshot"])}
            status = "succeeded" if result["validation"]["passed"] else "failed"
            self.queue.recover_expired()
            lease_lost = False
            with self.ledger.transaction() as tx:
                try:
                    row = self.queue._require_lease(tx, task_id, token)
                except LeaseLost:
                    self.ledger.put_record("analysis_unconfirmed_effect", record_id, result, conn=tx)
                    lease_lost = True
                else:
                    if row["status"] == "cancel_requested":
                        status = "cancelled"
                    self.ledger.put_record("analysis_result", record_id, result, conn=tx)
            if lease_lost:
                return self.queue.get(task_id)
            return self.queue.finish(task_id, token, status, result=result,
                error=None if status == "succeeded" else {"reason": status, "failures": result["validation"]["failures"]})
        except LeaseLost:
            return self.queue.get(task_id)
        except Exception as exc:
            result = {"task_id": task_id, "attempt": task["attempt"], "run_id": None, "summary": str(exc), "status": "blocked" if isinstance(exc, PermissionError) else "failed",
                      "validation": {"passed": False, "failures": [f"{type(exc).__name__}:{exc}"]},
                      "scientific_claim_allowed": False, "preview_only": True,
                      **origin_from_snapshot(task["input_snapshot"]),
                      "resource_control": getattr(exc, "resource", None)}
            from .analysis_repair import unfinished_summary
            recovery_summary = unfinished_summary(self, task)
            if recovery_summary is not None:
                result["operational_recovery"] = recovery_summary
            self.queue.recover_expired()
            lease_lost = False
            with self.ledger.transaction() as tx:
                try:
                    row = self.queue._require_lease(tx, task_id, token)
                except LeaseLost:
                    self.ledger.put_record("analysis_unconfirmed_effect", record_id, result, conn=tx)
                    lease_lost = True
                else:
                    # A finish race must not overwrite an already frozen effect.
                    saved = self.ledger.get_record("analysis_result", record_id, conn=tx)
                    if saved is not None:
                        result = saved
                    else:
                        self.ledger.put_record("analysis_result", record_id, result, conn=tx)
                    cancelled = row["status"] == "cancel_requested"
            if lease_lost:
                return self.queue.get(task_id)
            return self.queue.finish(task_id, token, "cancelled" if cancelled else "failed",
                                     result=result, error={"reason": type(exc).__name__, "message": str(exc)})

    def get_process_control(self, task_id: str, *, attempt: int) -> dict:
        """Read one recorded process generation without expiring any task."""
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        self.get_task_snapshot(task_id)
        value = self.ledger.get_state(f"analysis_process:{task_id}:attempt:{attempt}")
        return value or {"task_id": task_id, "attempt": attempt, "status": "cleanup_unknown",
                         "reason": "process_identity_not_recorded", "cleanup_verified": False}

    @staticmethod
    def _process_identity(process) -> dict:
        return {"pid": process.pid, "create_time": process.create_time(),
                "pgid": os.getpgid(process.pid)}

    def _save_process_control(self, task: dict, value: dict, *, record_kind=None):
        # Process observations are audit facts about this exact attempt, not
        # permission to finish/retry a task whose execution lease was lost.
        with self.ledger.transaction() as tx:
            self.ledger.set_state("analysis_process:" + _attempt_key(task), value, conn=tx)
            if record_kind:
                self.ledger.put_record(record_kind, _attempt_key(task), value, conn=tx)
            else:
                self.ledger.put_record("analysis_process_observation",
                    _attempt_key(task) + ":" + content_hash(value), value, conn=tx)

    @staticmethod
    def _cleanup_observed_processes(process, root_identity, known_children):
        """Use psutil identity-checked signals, never a recycled bare PGID."""
        import psutil
        from core.execution_models import ProcessCleanup
        observed = {p.pid: p for p in known_children}
        identity_safe = root_identity is not None
        try:
            root = psutil.Process(process.pid)
            if root_identity is None or root.create_time() != root_identity["create_time"]:
                identity_safe = False
            else:
                observed.update({p.pid: p for p in root.children(recursive=True)})
                observed[root.pid] = root
        except psutil.NoSuchProcess:
            pass
        except psutil.Error:
            identity_safe = False
        terminated, killed = False, False
        for item in observed.values():
            try:
                item.terminate()
                terminated = True
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                identity_safe = False
        _, alive = psutil.wait_procs(list(observed.values()), timeout=1)
        for item in alive:
            try:
                item.kill()
                killed = True
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                identity_safe = False
        _, alive = psutil.wait_procs(alive, timeout=1)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            identity_safe = False
        residual = []
        for item in alive:
            try:
                if item.is_running() and item.status() != psutil.STATUS_ZOMBIE:
                    residual.append(item.pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                identity_safe = False
        return ProcessCleanup(terminate_sent=terminated, kill_sent=killed,
                              child_processes_seen=max(0, len(observed) - int(process.pid in observed)),
                              residual_processes=residual), identity_safe

    def cleanup_owned_processes(self, task_id: str, *, attempt: int,
                                expected_payload_digest: str, _program_phase: str | None = None) -> dict:
        """Explicit recovery cleanup only; never claim, retry, fit or invoke models.

        Only recorded PID/create_time identities may be signalled. A missing or
        reused identity stays unknown; an empty sampled tree is not universal
        proof that no unobserved descendant escaped before owner death.
        """
        import psutil
        task = self.get_task_snapshot(task_id)
        if task["payload_digest"] != expected_payload_digest:
            raise InvalidTransition("Process cleanup payload does not match")
        if _program_phase not in {None, "initial", "patch"}:
            raise ValueError("invalid program process phase")
        if _program_phase and task["kind"] != PROGRAM_KIND:
            raise ValueError("program process cleanup requires a program task")
        prefix = "program_process" if _program_phase else "analysis_process"
        record_id = f"{task_id}:attempt:{attempt}" + (":" + _program_phase if _program_phase else "")
        record = (self.ledger.get_state(prefix + ":" + record_id, {}) if _program_phase else
                  self.get_process_control(task_id, attempt=attempt))
        unknown = {"task_id": task_id, "attempt": attempt, "status": "cleanup_unknown",
                   "cleanup_verified": False, "new_execution": False}
        if (record.get("namespace") != self.workspace.namespace
                or record.get("task_id") != task_id or record.get("attempt") != attempt
                or record.get("payload_digest") != expected_payload_digest
                or not record.get("root") or not record.get("supervisor")):
            return {**unknown, "reason": "process_identity_not_recorded"}
        started = self.ledger.get_record(prefix + "_started", record_id)
        binding_fields = ("namespace", "task_id", "attempt", "payload_digest", "fencing_token_digest",
                          "command_digest", "root", "supervisor")
        if _program_phase:
            binding_fields += ("phase", "source_sha256")
        if (not started or any(record.get(k) != started.get(k) for k in binding_fields)
                or not all(isinstance(started.get(k), str) and len(started[k]) == 64
                           for k in ("fencing_token_digest", "command_digest"))):
            return {**unknown, "reason": "immutable_process_start_binding_mismatch"}
        # Mutable state alone cannot introduce a PID to be killed. A changing
        # descendant set must have been observed by this exact supervisor and
        # preserved as an immutable observation before recovery may signal it.
        candidates = [started]
        for kind in (prefix + "_observation", prefix + "_cleanup", prefix + "_recovery"):
            candidates.extend(self.ledger.list_records(kind))
        if not any(all(p.get(k) == started.get(k) for k in binding_fields)
                   and p.get("known_descendants", []) == record.get("known_descendants", []) for p in candidates):
            return {**unknown, "reason": "immutable_descendant_observation_missing"}

        def resolve(identity):
            if (not isinstance(identity, dict) or type(identity.get("pid")) is not int or identity["pid"] <= 0
                    or type(identity.get("create_time")) not in {int, float}
                    or not math.isfinite(identity["create_time"]) or identity["create_time"] <= 0):
                return None, "invalid_identity"
            try:
                process = psutil.Process(identity["pid"])
                if process.create_time() != identity["create_time"]:
                    return None, "identity_mismatch"
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                    return None, "gone"
                return process, "live"
            except psutil.NoSuchProcess:
                return None, "gone"
            except (psutil.Error, OSError):
                return None, "identity_unknown"

        owner, owner_status = resolve(record["supervisor"])
        if owner is not None:
            native_thread = record["supervisor"].get("native_thread_id")
            if type(native_thread) is not int or native_thread <= 0:
                return {**unknown, "status": "owner_still_running", "reason": "supervisor_thread_identity_missing"}
            try:
                if any(t.id == native_thread for t in owner.threads()):
                    return {**unknown, "status": "owner_still_running", "reason": "live_original_supervisor_thread"}
                owner_status = "gone"
            except psutil.Error:
                return {**unknown, "reason": "supervisor_thread_identity_unknown"}
        if owner_status not in {"gone", "identity_mismatch"}:
            return {**unknown, "reason": "supervisor_identity_unknown"}
        identities = list(record.get("known_descendants", [])) + [record["root"]]
        processes, uncertain = {}, []
        root_process, _ = resolve(record["root"])
        if root_process is not None:
            try:
                identities.extend(self._process_identity(p) for p in root_process.children(recursive=True))
            except (psutil.Error, OSError):
                uncertain.append("descendant_discovery_incomplete")
        for identity in identities:
            process, status = resolve(identity)
            if process is not None:
                processes[(process.pid, identity["create_time"])] = process
            elif status != "gone":
                uncertain.append(status)
        for process in processes.values():
            try:
                process.terminate()  # psutil checks PID/create_time before signalling.
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                uncertain.append("termination_unconfirmed")
        _, alive = psutil.wait_procs(list(processes.values()), timeout=1)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                uncertain.append("kill_unconfirmed")
        _, alive = psutil.wait_procs(alive, timeout=1)
        residual = []
        for process in alive:
            try:
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    residual.append(process.pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                uncertain.append("final_observation_unknown")
        result = {**record, "status": "cleanup_unknown" if uncertain or residual else "known_owned_processes_stopped",
                  "cleanup_verified": not uncertain and not residual, "residual_processes": residual,
                  "identity_problems": sorted(set(uncertain)), "scope": "recorded_and_currently_observed_owned_identities_only",
                  "unobserved_descendants_excluded_from_guarantee": True, "new_execution": False}
        # Recovery receipts have a fresh ID; the original execution receipt is immutable.
        with self.ledger.transaction() as tx:
            self.ledger.set_state(prefix + ":" + record_id, result, conn=tx)
            self.ledger.put_record(prefix + "_recovery", record_id + ":" + str(time.time_ns()), result, conn=tx)
        return result

    def _send_worker_start_grant(self, task: dict, process):
        """Original owner writes once to this child's private stdin, then closes."""
        from .chat_runs import ChatRunService
        try:
            with self.ledger.transaction() as tx:
                row = self.queue._require_lease(tx, task["task_id"], task["fencing_token"])
                if row["status"] != "running" or row["attempt"] != task["attempt"]:
                    raise PermissionError("worker was cancelled before start authorization")
                grant = ChatRunService(self.ledger).issue_worker_start_grant(tx, self.queue._public(row))
            if grant is None:
                return None  # Original non-chat analysis never requires stdin.
            payload = (canonical_json(grant) + "\n").encode("utf-8")
            if len(payload) > WORKER_GRANT_BYTES or process.stdin is None:
                raise PermissionError("worker grant cannot be delivered within its input bound")
            fd = process.stdin.fileno()
            os.set_blocking(fd, False)
            deadline, position = time.monotonic() + 5, 0
            while position < len(payload):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [fd], [], max(0, remaining))[1]:
                    raise PermissionError("worker grant delivery timed out")
                try:
                    position += os.write(fd, payload[position:])
                except BlockingIOError:
                    continue
            return grant
        finally:
            if process.stdin is not None:
                process.stdin.close()

    def _execute_supervised(self, task: dict, *, deadline_epoch: float | None = None,
                            extra_rss_mb=None) -> dict:
        """Bound preparation and the existing executor together; no second queue."""
        import psutil
        from execution.process_control import _process_tree_rss_mb
        root = _path_inside(self.workspace.artifacts_dir / "analysis-processes", self.workspace.artifacts_dir)
        root.mkdir(exist_ok=True)
        guard = _path_inside(root / _attempt_directory(task), root)
        guard.mkdir(exist_ok=False)
        receipt = guard / "worker_result.json"
        env = _analysis_worker_environment(guard, self.workspace)
        command = [sys.executable, "-m", "sckg_workbench.analysis", "--execute-task", task["task_id"],
                   "--workspace", str(self.workspace.root), "--receipt", str(receipt),
                   "--fencing-token", task["fencing_token"], "--attempt", str(task["attempt"])]
        known, peak, stop, lingering = {}, 0.0, None, []
        start = time.monotonic()
        original_deadline_epoch = time.time() + 180
        if deadline_epoch is not None:
            if type(deadline_epoch) not in {int, float} or not math.isfinite(deadline_epoch):
                raise ValueError("execution deadline must be finite")
            original_deadline_epoch = min(original_deadline_epoch, deadline_epoch)
            if time.time() >= original_deadline_epoch:
                raise PermissionError("original execution deadline exhausted before launch")
        with (guard / "worker.log").open("x") as log:
            process = subprocess.Popen(command, env=env, cwd=guard, stdin=subprocess.PIPE,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            control = {"namespace": self.workspace.namespace, "task_id": task["task_id"], "attempt": task["attempt"],
                "payload_digest": task["payload_digest"], "fencing_token_digest": content_hash(task["fencing_token"]),
                "command_digest": content_hash(command), "root": None, "supervisor": None,
                "known_descendants": [], "status": "cleanup_unknown", "cleanup_verified": False,
                "original_deadline_epoch": original_deadline_epoch}
            try:
                control["supervisor"] = {**self._process_identity(psutil.Process(os.getpid())),
                                         "native_thread_id": threading.get_native_id(),
                                         "thread_ident": threading.get_ident()}
                control["root"] = self._process_identity(psutil.Process(process.pid))
                control["status"] = "running"
                self._save_process_control(task, control, record_kind="analysis_process_started")
                self._send_worker_start_grant(task, process)
                while True:
                    try:
                        for child in psutil.Process(process.pid).children(recursive=True):
                            known[child.pid] = child
                    except psutil.Error:
                        pass
                    identities = []
                    for child in known.values():
                        try:
                            identities.append(self._process_identity(child))
                        except (psutil.Error, OSError):
                            pass
                    if identities != control["known_descendants"]:
                        control["known_descendants"] = identities
                        self._save_process_control(task, control)
                    reserve = extra_rss_mb() if extra_rss_mb is not None else 0
                    if type(reserve) not in {int, float} or not math.isfinite(reserve) or reserve < 0:
                        raise PermissionError("orchestration process RSS could not be verified")
                    peak = max(peak, _process_tree_rss_mb(process.pid) + reserve)
                    current = self.queue.get(task["task_id"])
                    if peak > task["profile_snapshot"]["max_rss_mb"]:
                        stop = "rss_limit_exceeded"
                    elif (time.monotonic() - start > 180
                          or (deadline_epoch is not None and time.time() >= original_deadline_epoch)):
                        stop = "wall_time_exceeded"
                    elif current["status"] == "cancel_requested":
                        stop = "cancel_requested"
                    elif current["fencing_token"] != task["fencing_token"]:
                        stop = "lease_lost"
                    if stop:
                        break
                    if process.poll() is not None:
                        for child in known.values():
                            try:
                                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                                    lingering.append(child.pid)
                            except psutil.Error:
                                pass
                        break
                    time.sleep(.05)
            finally:
                cleanup, identity_safe = self._cleanup_observed_processes(process, control["root"], list(known.values()))
                cleanup = cleanup.model_copy(update={"timeout_triggered": stop == "wall_time_exceeded",
                    "cancellation_triggered": stop == "cancel_requested",
                    "cancellation_reason": "cancel_requested" if stop == "cancel_requested" else None})
                control.update({"status": "known_owned_processes_stopped" if identity_safe and not cleanup.residual_processes else "cleanup_unknown",
                                "cleanup_verified": identity_safe and not cleanup.residual_processes,
                                "scope": "observed_process_tree_only", "cleanup": cleanup.model_dump(mode="json"),
                                "unobserved_descendants_excluded_from_guarantee": True})
                self._save_process_control(task, control, record_kind="analysis_process_cleanup")
        resources = {"method": "sampled_process_tree_rss_termination", "max_rss_mb": task["profile_snapshot"]["max_rss_mb"],
                     "peak_rss_mb": peak, "wall_limit_seconds": 180, "seconds": time.monotonic() - start,
                     "returncode": process.returncode, "stop": stop, "lingering_after_exit": lingering,
                     "cleanup": cleanup.model_dump(mode="json"), "worker_log": str(guard / "worker.log"),
                     "scope": "preparation plus executor descendants; excludes caller; not OS sandbox"}
        if stop or process.returncode != 0 or lingering or cleanup.residual_processes or not control["cleanup_verified"] or not receipt.is_file():
            raise AnalysisProcessError(stop or "analysis_worker_failed_or_incomplete", resources)
        payload = json.loads(receipt.read_text())
        if payload.get("ok") is not True:
            raise AnalysisProcessError(payload.get("error", "analysis_worker_error"), resources)
        if payload["result"].get("task_id") != task["task_id"] or payload["result"].get("attempt") != task["attempt"]:
            raise AnalysisProcessError("analysis_worker_receipt_binding_mismatch", resources)
        return {**payload["result"], "resource_control": resources}

    def _execute(self, task: dict) -> dict:
        from .code_provenance import capture_code_provenance
        code_provenance = capture_code_provenance()
        # Heavy/legacy imports occur only for a claimed, explicitly authorized task.
        import anndata as ad
        import numpy as np
        from scipy import sparse
        from core.research_workspace_models import DataAssetProfile
        from core.tool_contract_registry import ToolContractRegistry
        from engine.data_intelligence import AnnDataBackedAdapter
        from execution.approval_service import ApprovalService
        from execution.data_registry import DataRegistry
        from execution.environment_registry import EnvironmentRegistry
        from execution.execution_policy import ExecutionPair, ExecutionPolicy, ExecutionPolicyMode
        from execution.local_user_service import LocalUserAllowlist
        from execution.preview_execution_service import PreviewExecutionService
        from execution.research_workspace_service import ResearchWorkspaceService
        from execution.runtime_pack_resolver import RuntimePackResolver
        from execution.user_workspace import UserWorkspaceService
        from execution.workspace_checkpoint import _model_digest
        from execution.wrapper_registry import WrapperRegistry
        from .analysis_repair import enabled, OperationalRecovery, public_summary

        recovery_enabled = enabled(task)
        max_inner_runs = 2 if recovery_enabled else 1

        task_id, token = task["task_id"], task["fencing_token"]
        request = task["input_snapshot"]
        asset = self.datasets.get_asset(request["asset_id"])
        source, digest = self._source(asset)
        if digest != request["source_sha256"]:
            raise ValueError("source hash differs from frozen task input")
        _local_hdf5_only(source)
        bounded = self.datasets.profile(request["asset_id"], max_matrices=1)
        dimensions = bounded["profile"]["dimensions"]
        if not 1 <= dimensions["n_obs"] <= MAX_CELLS or not 1 <= dimensions["n_vars"] <= MAX_GENES:
            raise ValueError("analysis input exceeds 1000 cells/10000 genes or is empty")
        data = ad.read_h5ad(source, backed="r")
        try:
            if not data.obs_names.is_unique or not data.var_names.is_unique:
                raise ValueError("analysis requires unique cell and gene IDs")
            # Validate all values of the bounded selected X, not only a prefix.
            matrix = data.X[:]
            values = matrix.data if sparse.issparse(matrix) else np.asarray(matrix)
            if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
                raise ValueError("declared X raw counts contain nonfinite/negative/noninteger values")
        finally:
            if getattr(data, "file", None) is not None:
                data.file.close()

        root = _path_inside(self.workspace.artifacts_dir / "analysis", self.workspace.artifacts_dir)
        root.mkdir(exist_ok=True)
        # Per-task legacy state cannot reset another task's allowance or permissions.
        local = _path_inside(root / _attempt_directory(task), root)
        local.mkdir(exist_ok=False)
        user = "workbench-local"
        artifact_id = "asset-" + content_hash(request["asset_id"])[:24]
        registry = DataRegistry(approved_input_roots=[source.parent], registry_root=local / "data-registry")
        registry.register(user_id=user, path=source, artifact_id=artifact_id)
        approvals = ApprovalService(root=local / "authorizations")
        grant = approvals.grant_data_access(user_id=user, artifact_id=artifact_id)
        self.ledger.put_record("analysis_authorization", _attempt_key(task),
            {"origin": "explicit_local_request", "human_scientific_review": False,
             "task_id": task_id, "attempt": task["attempt"], "asset_id": request["asset_id"], "source_sha256": digest,
             "authorization_input_digest": content_hash(request), "data_grant_id": grant.grant_id})

        class ExplicitXAdapter(AnnDataBackedAdapter):
            def profile(self, **kwargs):
                value = super().profile(**kwargs).model_dump(mode="json")
                value["selected_count_source"] = "X"
                return DataAssetProfile.model_validate(value)

        research = ResearchWorkspaceService(data_registry=registry, approval_service=approvals,
            workspace_root=local / "research", adapter=ExplicitXAdapter())
        profile = research.profile(user_id=user, artifact_id=artifact_id, data_grant_id=grant.grant_id)
        preview = research.build_preview(user_id=user, artifact_id=artifact_id, profile=profile,
            data_grant_id=grant.grant_id, max_cells=MAX_CELLS, random_seed=0)
        notebook = research.compile_notebook(user_id=user, artifact_id=artifact_id, profile=profile,
            preview=preview, data_grant_id=grant.grant_id,
            parameters={"expected_doublet_rate": request["expected_doublet_rate"]})
        environments = EnvironmentRegistry()
        contracts = ToolContractRegistry(environment_registry=environments)
        contract = contracts.load("Scrublet", "0.2.3")
        gate = contracts.execution_gate(contract)
        if not gate.allowed:
            raise PermissionError(";".join(gate.reasons))
        allowlist = LocalUserAllowlist(root=local / "allowlist")
        allowlist.allow_user(user_id=user, allowed_pairs=[ExecutionPair(tool_name=contract.tool_name,
            tool_version=contract.tool_version, wrapper_id=contract.wrapper_id, environment_id=contract.environment_id)],
            allowed_artifact_ids=[artifact_id], allowed_data_scopes=["representative_preview"], max_runs=max_inner_runs)
        # Stable installed runtimes are read-only shared state. Authorization,
        # allowance, data registry, budget and outputs remain per attempt above.
        configured_runtime_home = os.environ.get(RUNTIME_HOME_ENV)
        resolver = RuntimePackResolver.for_read_only_discovery(
            home=Path(configured_runtime_home) if configured_runtime_home else None,
            allow_legacy_environments=True)
        runtime_probe = resolver.manager.probe("doublet-python")
        runtime_discovery = {
            "schema_version": "analysis-runtime-discovery-v1",
            "task_id": task_id, "attempt": task["attempt"],
            "home_source": "parent_server_default_sckg_home" if configured_runtime_home else "server_default_sckg_home",
            "runtime_home_hash": content_hash(str(resolver.manager.home)),
            "read_only": True, "probe": runtime_probe.model_dump(mode="json"),
            "imports_verified_in_this_attempt": False, "scientific_execution_attempted": False,
            "authorization_scope": "per_attempt_not_runtime_installation_state",
        }
        self.ledger.put_record("analysis_runtime_discovery", _attempt_key(task), runtime_discovery)
        def cancellation():
            current = self.queue.get(task_id)
            return "workbench_task_cancel_requested" if current["status"] == "cancel_requested" else (
                "workbench_task_lease_lost" if current["fencing_token"] != token else None)
        service = PreviewExecutionService(research_workspace=research, data_registry=registry,
            approval_service=approvals, allowlist=allowlist, workspace=UserWorkspaceService(root=local / "users"),
            execution_policy=ExecutionPolicy(mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS),
            contract_registry=contracts, environment_registry=environments,
            wrapper_registry=WrapperRegistry(resolver=resolver),
            max_rss_mb=task["profile_snapshot"]["max_rss_mb"], cancellation_checker=cancellation)
        kwargs = dict(user_id=user, artifact_id=artifact_id, data_grant_id=grant.grant_id,
                      profile=profile, preview=preview, notebook=notebook)
        preparation = service.prepare(**kwargs, execution_approval_id=None)
        blockers = [b for b in preparation.blockers if b != "execution_approval_missing"]
        if blockers:
            raise PermissionError(";".join(blockers))
        approval = approvals.create_execution_approval(scope=preparation.approval_scope, data_grant_id=grant.grant_id, max_uses=max_inner_runs)
        preview_path = research.preview_path(user_id=user, artifact_id=artifact_id, preview=preview)
        notebook_path = research.notebook_path(user_id=user, artifact_id=artifact_id, bundle=notebook)
        parameters = research.notebook_parameters(user_id=user, artifact_id=artifact_id, bundle=notebook)
        frozen = {"source_sha256": digest, "preview_sha256": preview.preview_hash, "preview_id": preview.preview_id,
                  "profile_id": profile.profile_id, "notebook_sha256": notebook.notebook_hash,
                  "notebook_id": notebook.notebook_id, "notebook_path": str(notebook_path),
                  "parameters": parameters, "expected_cells": preview.n_preview_cells,
                  "contract_digest": _model_digest(contract),
                  "environment_digest": _model_digest(environments.get(contract.environment_id))}
        prepared = {"frozen": frozen,
            "code_provenance": code_provenance,
            **origin_from_snapshot(request),
            "runtime_discovery": runtime_discovery,
            "preview_path": str(preview_path), "source_path": str(source), "output_root": str(local / "users"),
            "profile": profile.model_dump(mode="json"), "preview": preview.model_dump(mode="json"),
            "notebook": notebook.model_dump(mode="json"), "approval": approval.model_dump(mode="json")}
        self.ledger.put_record("analysis_preparation", _attempt_key(task), prepared)
        self.queue.checkpoint(task_id, token, "prepared", {"preview_id": preview.preview_id,
            "source_sha256": digest, "execution_effect_may_follow": True})
        if cancellation():
            raise PermissionError(cancellation())
        def validate(result):
            validation = validate_outputs(result.execution_run, preview_path=preview_path, source_path=source,
                                           frozen=frozen, output_root=local / "users")
            lineage = result.lineage
            if lineage is None or (lineage.source_hash, lineage.preview_hash, lineage.notebook_hash,
                lineage.tool_contract_digest, lineage.environment_digest) != (digest, preview.preview_hash,
                notebook.notebook_hash, frozen["contract_digest"], frozen["environment_digest"]):
                validation["passed"] = False
                validation["failures"].append("execution_lineage_mismatch")
            integrity = service.result_store.inspect_integrity(result)
            if not integrity.passed:
                validation["passed"] = False
                validation["failures"].extend(integrity.issues)
            return validation

        recovery = OperationalRecovery(self, task, prepared) if recovery_enabled else None
        execution_budget, initial_timeout = recovery.reserve_initial() if recovery else (None, None)
        initial_options = {"timeout_seconds": initial_timeout} if recovery else {}
        result = service.execute(**kwargs, execution_approval_id=approval.approval_id,
                                 request_id="wb-analysis-" + content_hash(task_id)[:24], **initial_options)
        validation = validate(result)
        initial_run_id = result.execution_run.run_id
        recovery_summary = None
        if recovery:
            recovery.save_run("initial", result, validation)
            recovery.check_after_run()
            recovery_summary = public_summary(status="not_used", initial_run_id=initial_run_id,
                                               final_run_id=initial_run_id)
            admission = recovery.admit_repair(initial=result, service=service, contract=contract, budget=execution_budget)
            if admission is not None:
                proposal, reservation = admission
                from .analysis_repair import verify_inputs
                verify_inputs(prepared, result, approval_id=approval.approval_id)
                timeout = recovery.before_repair_dispatch(reservation)
                initial = result
                result = service.execute(**kwargs, execution_approval_id=approval.approval_id,
                    request_id="wb-analysis-recovery-" + content_hash([task_id, task["attempt"]])[:24],
                    timeout_seconds=timeout)
                validation = validate(result)
                recovery.save_run("repair", result, validation)
                recovery.finish_repair(proposal, initial, result)
                recovery_summary = public_summary(status="repaired_validated" if validation["passed"] else "repair_failed",
                    admissions=1, initial_run_id=initial_run_id, final_run_id=result.execution_run.run_id)
        response = {"task_id": task_id, "attempt": task["attempt"], "asset_id": request["asset_id"], "run_id": result.execution_run.run_id,
                "code_provenance_digest": content_hash(code_provenance),
                "status": "validated" if validation["passed"] else "failed", "validation": validation,
                "summary": ("Scrublet preview completed and independent artifact/ID checks passed." if validation["passed"] else
                            "Scrublet preview did not pass external validation: " + "; ".join(validation["failures"])),
                "execution_run": result.execution_run.model_dump(mode="json"),
                "legacy_preview_result": result.model_dump(mode="json"),
                "artifact_paths": result.execution_run.artifact_paths, "preview_only": True,
                "scientific_claim_allowed": False, "count_provenance": request["count_provenance"],
                "count_provenance_status": request["count_provenance_status"],
                **origin_from_snapshot(request),
                "resource_control": "fixed wrapper; BLAS/OpenMP environment set to1; neighbor backend threading depends on installed binary; sampled child RSS termination; 120s contract timeout; not OS sandbox"}
        if recovery_summary is not None:
            response["operational_recovery"] = recovery_summary
        return response

    def get_task_snapshot(self, task_id: str) -> dict:
        # TaskQueue.get also expires other leases. Result views must not do so.
        with self.ledger.connect() as tx:
            row = tx.execute("SELECT * FROM workbench_tasks WHERE namespace=? AND task_id=?",
                             (self.workspace.namespace, task_id)).fetchone()
        if row is None:
            raise ValueError("analysis task not found in this workspace")
        return self.queue._public(row)

    def get_result(self, task_id: str, *, attempt: int | None = None) -> dict | None:
        task = self.get_task_snapshot(task_id)
        if task["kind"] not in ANALYSIS_KINDS:
            raise ValueError("not a workbench analysis task")
        if attempt is None and task["status"] == "queued":
            return None  # A requested retry has not yet acquired its new attempt.
        selected = task["attempt"] if attempt is None else attempt
        if type(selected) is not int or not 0 <= selected <= task["attempt"]:
            raise ValueError("invalid analysis attempt")
        record_id = _attempt_key({"task_id": task_id, "attempt": selected})
        result = self.ledger.get_record("analysis_result", record_id)
        if result is None:
            result = self.ledger.get_record("analysis_unconfirmed_effect", record_id)
        if result and result.get("execution_run"):
            prepared = self.ledger.get_record("analysis_preparation", record_id)
            current = self.revalidate_execution(task, result)
            if task["kind"] == PROGRAM_KIND:
                try:
                    from .code_program import verify_program_chain
                    verify_program_chain(self, task, result)
                except Exception:
                    current = {**current, "passed": False,
                        "failures": sorted(set(current.get("failures", []) + ["program_chain_invalid"]))}
            result = {**result, "current_integrity": current}
            if not current["passed"]:
                result.update(status="invalidated", validation=current,
                              summary="Saved analysis artifacts or input no longer pass integrity checks.")
        if result:
            result = {**result, **origin_from_snapshot(task["input_snapshot"])}
            status = task["status"] if selected == task["attempt"] else "previous_attempt"
            result = {**result, "task_status": status,
                      "product_completed": status == "succeeded" and result["validation"]["passed"]}
            if status != "succeeded" and result["validation"]["passed"]:
                result = {**result, "status": status, "artifact_validation": result["validation"],
                          "validation": {"passed": False, "failures": ["task_completion_not_confirmed"]},
                          "summary": "Artifacts exist, but the task did not complete under its valid lease."}
        return result

    def revalidate_execution(self, task: dict, saved: dict) -> dict:
        """Read-only scientific artifact checks, also before a program finishes.

        A passed return does not finish a task or establish its program chain.
        """
        from core.execution_models import ExecutionRun
        prepared = self.ledger.get_record("analysis_preparation", _attempt_key({**task, "attempt": saved["attempt"]}))
        if not prepared:
            return {"passed": False, "failures": ["analysis_preparation_missing"]}
        current = validate_outputs(ExecutionRun.model_validate(saved["execution_run"]),
            preview_path=Path(prepared["preview_path"]), source_path=Path(prepared["source_path"]),
            frozen=prepared["frozen"], output_root=Path(prepared["output_root"]))
        try:
            from .analysis_repair import verify_chain
            verify_chain(self, task, saved, prepared)
        except Exception:
            current = {**current, "passed": False,
                "failures": sorted(set(current.get("failures", []) + ["operational_recovery_chain_invalid"]))}
        return current

    def list_runs(self) -> list[dict]:
        return [self.queue.get(r["task_id"]) for r in self.ledger.list_records("task_submission") if r["kind"] in ANALYSIS_KINDS]

    def get_public_result_summary(self, task_id: str, *, attempt: int, expected_run_id: str) -> dict:
        return self._read_validated_result(task_id, attempt=attempt, expected_run_id=expected_run_id)

    def get_result_export(self, task_id: str, *, attempt: int, expected_run_id: str) -> dict:
        """Return a deterministic summary/manifest ZIP from current validated evidence.

        No raw cell identifiers, local paths, credentials or execution commands
        are exported. Missing historical provenance is not reconstructed.
        """
        return self._read_validated_result(task_id, attempt=attempt,
                                           expected_run_id=expected_run_id, export=True)

    def _read_validated_result(self, task_id: str, *, attempt: int,
                               expected_run_id: str, export: bool = False) -> dict:
        """Revalidate one server-selected current result and disclose aggregates only.

        Caller access/conversation selection belongs to the chat service. This
        boundary binds that selection to this workspace, attempt and saved run;
        it never submits or executes work, nor falls back to cached metrics.
        """
        unavailable = {"schema_version": PUBLIC_SUMMARY_SCHEMA, "status": "unavailable",
                       "computation_performed_by_read": False}
        if (type(attempt) is not int or attempt < 1 or not isinstance(task_id, str)
                or not task_id or len(task_id) > 200 or not isinstance(expected_run_id, str)
                or not expected_run_id or len(expected_run_id) > 200):
            return {**unavailable, "reason_code": "invalid_result_selection"}
        reason = "integrity_failed"
        try:
            from execution.preview_result_store import PreviewResultStore
            from execution.preview_result_interpreter import _observed_metrics

            task = self.get_task_snapshot(task_id)
            if task["kind"] not in ANALYSIS_KINDS or task["status"] != "succeeded" or task["attempt"] != attempt:
                return {**unavailable, "reason_code": "task_not_current_completed"}
            key = _attempt_key(task)
            saved = self.ledger.get_record("analysis_result", key)
            prepared = self.ledger.get_record("analysis_preparation", key)
            if not saved or not prepared:
                return {**unavailable, "reason_code": "result_not_available"}
            if (saved.get("task_id") != task_id or saved.get("attempt") != attempt
                    or saved.get("run_id") != expected_run_id or task["result"] != saved):
                return {**unavailable, "reason_code": "result_binding_mismatch"}
            from .code_provenance import recorded_code_provenance
            code_provenance = recorded_code_provenance(prepared, saved)

            # Establish owned paths before get_result or the legacy store reads.
            local = _path_inside(self.workspace.artifacts_dir / "analysis" / _attempt_directory(task),
                                 self.workspace.artifacts_dir)
            research_root = _path_inside(local / "research", local)
            execution_root = _path_inside(local / "users", local)
            if _path_inside(Path(prepared["output_root"]), local) != execution_root:
                raise ValueError("output root differs from attempt root")
            frozen, request = prepared["frozen"], task["input_snapshot"]
            _path_inside(Path(prepared["preview_path"]), research_root)
            _path_inside(Path(frozen["notebook_path"]), research_root)
            asset = self.datasets.get_asset(request["asset_id"])
            if (not asset or asset["namespace"] != self.workspace.namespace
                    or _path_inside(Path(prepared["source_path"]), Path(asset["path"]).parent)
                    != _path_inside(Path(asset["path"]), Path(asset["path"]).parent)):
                raise ValueError("source asset binding differs")
            current = self.get_result(task_id, attempt=attempt)
            if (not current or current.get("product_completed") is not True
                    or current.get("validation", {}).get("passed") is not True
                    or current.get("current_integrity", {}).get("passed") is not True):
                raise ValueError("current result failed revalidation")
            owner = "workbench-local"
            artifact = "asset-" + content_hash(request["asset_id"])[:24]
            store = PreviewResultStore(workspace_root=research_root, execution_root=execution_root)
            result_dir = research_root / owner / "artifacts" / artifact / "preview-runs" / expected_run_id
            result_path = _path_inside(result_dir / "preview_run_result.json", research_root)
            sidecar = _path_inside(result_dir / "preview_run_result.sha256", research_root)
            result_bytes, sidecar_bytes = result_path.read_bytes(), sidecar.read_bytes()
            result_digest = hashlib.sha256(result_bytes).hexdigest()
            if result_digest != sidecar_bytes.decode("ascii").strip():
                raise ValueError("result sidecar differs from snapshot")
            loaded = store.load_result(user_id=owner, artifact_id=artifact, run_id=expected_run_id)
            integrity = store.inspect_integrity(loaded)
            run, lineage, notebook = loaded.execution_run, loaded.lineage, prepared["notebook"]
            if (not integrity.passed or loaded.model_dump(mode="json") != saved["legacy_preview_result"]
                    or run.model_dump(mode="json") != saved["execution_run"]
                    or loaded.status != "validated" or not loaded.validation_result.passed
                    or loaded.validation_result.run_id != expected_run_id
                    or loaded.validation_result.metric_authority != "preview_engineering_metric"
                    or saved["asset_id"] != request["asset_id"] or lineage is None):
                raise ValueError("store result differs from immutable receipt")
            expected_lineage = {"source_hash": frozen["source_sha256"], "profile_id": frozen["profile_id"],
                "preview_id": frozen["preview_id"], "preview_hash": frozen["preview_sha256"],
                "notebook_id": frozen["notebook_id"], "notebook_hash": frozen["notebook_sha256"],
                "parameter_hash": notebook["parameter_hash"], "step_contract_id": notebook["step_contract_id"],
                "step_contract_version": notebook["step_contract_version"],
                "step_template_digest": notebook["step_template_digest"],
                "tool_contract_version": notebook["tool_contract_version"],
                "tool_contract_digest": frozen["contract_digest"], "environment_digest": frozen["environment_digest"],
                "environment_id": run.environment_id,
                "approval_fingerprint": prepared["approval"]["request_fingerprint"]}
            # Reuse the recorded approval binding without authorizing any work.
            if any(getattr(lineage, k) != v for k, v in expected_lineage.items()):
                raise ValueError("frozen lineage mismatch")
            if (loaded.preview_id != frozen["preview_id"] or loaded.notebook_id != frozen["notebook_id"]
                    or loaded.plan_id != run.plan_id or request["source_sha256"] != frozen["source_sha256"]
                    or run.parameters != frozen["parameters"] or run.input_hash != frozen["preview_sha256"]
                    or run.fixture_id != frozen["preview_id"] or run.owner_user_id != owner
                    or run.execution_purpose != "representative_preview" or run.status != "succeeded"
                    or run.exit_code != 0 or run.approval_id != prepared["approval"]["approval_id"]
                    or notebook["parameter_hash"] != hashlib.sha256(json.dumps(
                        frozen["parameters"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    or json.loads(result_bytes) != loaded.model_dump(mode="json")):
                raise ValueError("execution binding mismatch")
            # Read and hash exactly the bytes that are strictly parsed below.
            tsv = _path_inside(Path(run.artifact_paths["doublet_results.tsv"]),
                               execution_root / owner / "runs" / expected_run_id)
            with tsv.open("rb") as handle:
                table = handle.read(MAX_BYTES + 1)
            table_digest = hashlib.sha256(table).hexdigest()
            if len(table) > MAX_BYTES or table_digest != run.artifact_hashes["doublet_results.tsv"]:
                raise ValueError("result table snapshot hash mismatch")
            axis_digest = current["current_integrity"]["details"]["axis_ids_sha256"]
            ids, scores, calls = _strict_summary_rows(table, expected_cells=frozen["expected_cells"],
                                                      axis_digest=axis_digest)
            rate = sum(calls) / len(calls)
            recorded_rate = loaded.validation_result.task_metrics["preview_predicted_doublet_call_rate"]
            checked_rate = current["current_integrity"]["details"]["doublet_validator"]["task_metrics"]["preview_predicted_doublet_call_rate"]
            if (isinstance(recorded_rate, bool) or not isinstance(recorded_rate, (int, float))
                    or not math.isfinite(recorded_rate) or recorded_rate != rate or checked_rate != rate):
                raise ValueError("recorded metric differs from table")
            prior = run.parameters["expected_doublet_rate"]
            if (isinstance(prior, bool) or not isinstance(prior, (int, float))
                    or not math.isfinite(prior) or not .001 <= prior <= .25):
                raise ValueError("invalid recorded prior")
            # Reuse the existing interpreter's in-memory numeric projection.
            # Its permissive file reader and free-text interpretation stay out.
            observed = {m.metric_id: m.raw_value for m in _observed_metrics(
                result=loaded, scores=scores, expected_cells=len(ids), call_rate=rate)}
            origin = origin_from_snapshot(request)
            public = {"schema_version": PUBLIC_SUMMARY_SCHEMA, "status": "validated_preview_summary",
                "method": {"name": "Scrublet", "version": "0.2.3"}, "authority": "preview_engineering_only",
                "metrics": {"n_cells": observed["preview_cells"], "predicted_doublet_count": sum(calls),
                    "predicted_non_doublet_count": len(calls) - sum(calls),
                    "predicted_doublet_call_rate": observed["predicted_call_rate"]},
                "configuration": {"expected_doublet_rate": prior},
                "threshold": {"value": None, "status": "not_recorded"},
                "validation": {"artifact_integrity_passed": True, "axis_check_passed": True},
                "dataset_origin": origin["dataset_origin"],
                "dataset_origin_verification": origin["dataset_origin_verification"],
                "scientific_truth_verified": False, "scientific_claim_allowed": False,
                "computation_performed_by_read": False}
            if "operational_recovery" in current:
                public["operational_recovery"] = current["operational_recovery"]
            public["summary_sha256"] = content_hash(public)
            binding = {"schema": PUBLIC_SUMMARY_SCHEMA, "workspace_namespace": self.workspace.namespace,
                "task_id": task_id, "attempt": attempt, "asset_id": request["asset_id"], "run_id": expected_run_id,
                "analysis_result_digest": content_hash(saved), "preparation_digest": content_hash(prepared),
                "execution_run_digest": content_hash(saved["execution_run"]), "lineage": lineage.model_dump(mode="json"),
                "store_result_sha256": result_digest,
                "store_sidecar_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
                "table_sha256": table_digest, "axis_ids_sha256": axis_digest,
                "metadata_sha256": run.artifact_hashes["result_metadata.json"],
                "validator": current["current_integrity"]["validator"]}
            if code_provenance is not None:
                binding["code_provenance"] = code_provenance
            # Ensure the selection still denotes the completed current attempt.
            content_hash(binding)  # Validate the private binding's finite canonical form; do not persist it here.
            latest = self.get_task_snapshot(task_id)
            if latest["status"] != "succeeded" or latest["attempt"] != attempt or latest["result"] != saved:
                return {**unavailable, "reason_code": "task_not_current_completed"}
            if export:
                from .result_export import build_result_export
                return build_result_export(summary=public, task=latest, run=run, binding=binding)
            return public
        except Exception:
            # Never disclose exception text, paths, arbitrary metadata or stale
            # saved values on an unavailable read.
            return {**unavailable, "reason_code": reason}


def _worker_main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Internal bounded workbench analysis worker")
    parser.add_argument("--execute-task", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--fencing-token", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args(argv)
    workspace = Workspace(args.workspace)
    receipt = _path_inside(args.receipt, workspace.artifacts_dir / "analysis-processes")
    service = AnalysisService(workspace)
    task = service.queue.get(args.execute_task)
    if (task["kind"] not in ANALYSIS_KINDS or task["status"] != "running" or task["input_snapshot"]["execution_authorized"] is not True
            or task["fencing_token"] != args.fencing_token or task["attempt"] != args.attempt):
        raise PermissionError("worker requires a claimed, explicitly authorized analysis task")
    _authorize_worker_start(service, task)
    try:
        payload = {"ok": True, "result": service._execute(task)}
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
    with receipt.open("x") as handle:
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_worker_main())
