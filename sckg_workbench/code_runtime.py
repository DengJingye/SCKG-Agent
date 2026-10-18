"""Bounded real-Python orchestration guest, with a separate trusted tool server.

This is deliberately not a general notebook/shell runner. Only the server's two
argument-free frozen operations cross the private stdio channel. Scientific
execution remains synchronous on the original server owner thread.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import struct
import subprocess
import sys
import sysconfig
import threading
import time

import psutil

from sckg_workbench.code_worker import (
    CodePolicyError, MAX_FRAME_BYTES, MAX_TOOL_MESSAGES, OPERATIONS,
    decode_payload, encode_frame, validate_source,
)

_BINDING_KEYS = {"namespace", "task_id", "attempt", "payload_digest",
                 "fencing_token_digest", "phase", "source_sha256", "parent_source_sha256"}
SCHEMA = "bounded-code-process-v1"


def _identity(process):
    return {"pid": process.pid, "create_time": process.create_time(),
            "pgid": os.getpgid(process.pid)}


def _runtime_read_resources(runtime_python: str) -> dict:
    """Read scope for this trusted macOS interpreter, not an arbitrary prefix.

    The guest is stdlib-only and starts with -S. Site packages and prefix data
    remain denied. Alternative interpreters need their own qualified discovery.
    """
    if Path(runtime_python).resolve() != Path(sys.executable).resolve():
        raise CodePolicyError("Alternative Python runtime is not qualified")
    prefixes = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    stdlib = {Path(sysconfig.get_path(key)).resolve() for key in ("stdlib", "platstdlib")}
    shared = sysconfig.get_config_var("DESTSHARED")
    if shared:
        stdlib.add(Path(shared).resolve())
    stdlib = {p for p in stdlib if p.is_dir()}
    if (not stdlib or any(p in prefixes or not any(p.is_relative_to(root) for root in prefixes)
                          for p in stdlib)):
        raise CodePolicyError("Trusted stdlib read scope could not be established")
    sites = {Path(sysconfig.get_path(key)).resolve() for key in ("purelib", "platlib")}
    sites.update(p / name for p in stdlib for name in ("site-packages", "dist-packages"))
    library_dir = Path(sysconfig.get_config_var("LIBDIR") or "").resolve()
    if library_dir in prefixes or not any(library_dir.is_relative_to(root) for root in prefixes):
        raise CodePolicyError("Trusted native library scope could not be established")
    literals = {Path(runtime_python).resolve()}
    library_name = sysconfig.get_config_var("LDLIBRARY")
    if library_name and Path(library_name).name == library_name:
        library = (library_dir / library_name).resolve()
        if library.is_file() and library.suffix == ".dylib" and library.is_relative_to(library_dir):
            literals.add(library)
    # Observe exact already-loaded images; never grant the whole LIBDIR. The
    # worker uses hashlib; its observed libcrypto image can back _hashlib.
    try:
        import ctypes
        dyld = ctypes.CDLL(None)
        count = dyld._dyld_image_count
        count.restype = ctypes.c_uint32
        image = dyld._dyld_get_image_name
        image.argtypes = [ctypes.c_uint32]
        image.restype = ctypes.c_char_p
        total = count()
        if not 0 < total < 65536:
            raise ValueError("invalid dyld image count")
        for index in range(total):
            raw = image(index)
            if raw is None:
                raise ValueError("dyld image observation unavailable")
            path = Path(os.fsdecode(raw)).resolve()
            if (path.is_relative_to(library_dir) and path.suffix == ".dylib"
                    and path.name.startswith(("libpython", "libcrypto")) and path.is_file()):
                literals.add(path)
    except Exception as exc:
        raise CodePolicyError("Trusted native image observation unavailable") from exc
    version = str(sys.version_info.major) + str(sys.version_info.minor)
    candidates = {root / "lib" / ("python" + version + ".zip") for root in prefixes}
    executable = Path(runtime_python).resolve()
    candidates.update({executable.parent / "pyvenv.cfg", executable.parent.parent / "pyvenv.cfg"})
    literals.update(p.resolve() for p in candidates if p.is_file())
    return {"stdlib": sorted(stdlib), "sites": sorted(sites),
            "literals": sorted(literals), "prefixes": sorted(prefixes)}


def _sandbox_policy(*, phase: Path, worker: Path, source: Path, runtime_resources=None) -> str:
    """Qualified stdlib/native reads; no home/prefix data, network or source writes."""
    resources = runtime_resources or _runtime_read_resources(sys.executable)
    q = lambda p: json.dumps(str(Path(p).resolve()), ensure_ascii=False)
    protected = sorted({Path.home().resolve(), *resources["prefixes"]})
    read_exceptions = [" (require-not (literal " + q(worker) + "))",
                       " (require-not (subpath " + q(phase) + "))"]
    read_exceptions += [" (require-not (subpath " + q(p) + "))" for p in resources["stdlib"]]
    read_exceptions += [" (require-not (literal " + q(p) + "))" for p in resources["literals"]]
    return "\n".join([
        "(version 1)", "(allow default)",
        '(deny file-read-data (require-all (require-any ' +
        " ".join('(subpath ' + q(p) + ')' for p in protected) + ')',
        *read_exceptions, '))',
        # Explicitly exclude third-party package trees even under allowed stdlib.
        *['(deny file-read-data (require-all (subpath ' + q(p) + ')'
          ' (require-not (literal ' + q(worker) + '))))' for p in resources["sites"]],
        '(deny file-read-data (require-all (regex #"/(site|dist)-packages(/|$)")'
        ' (require-not (literal ' + q(worker) + '))))',
        '(deny file-write* (require-all (require-not (subpath "/dev"))',
        ' (require-not (subpath ' + q(phase) + '))))',
        '(deny file-write* (literal ' + q(source) + ') (literal ' + q(worker) + '))',
        '(deny network*)', '(deny process-fork)',
        # The initial sandbox-exec->Python exec must remain possible. Generated
        # code cannot exec/import and process-fork denies additional children.
        '',
    ])


def _bounded_error(exc):
    return {"type": type(exc).__name__[:80], "message": str(exc)[:2000]}


def _guard_status(exc):
    if type(exc).__name__ in {"ChatRunCancelled", "CancelledError", "CodeProgramCancelled"}:
        return "cancelled"
    return "unknown"


class _Stop(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(reason)


class CodeRuntime:
    def __init__(self, runtime_python=None, *, clock=time.time):
        self.runtime_python = str(Path(runtime_python or sys.executable).resolve())
        self.clock = clock
        self._observation_lock = threading.Lock()
        self._current_rss = 0.0

    def current_rss_mb(self):
        """Observed guest RSS for the trusted scientific supervisor's joint cap."""
        with self._observation_lock:
            return self._current_rss

    def run(self, source, *, directory: Path, binding: dict, deadline_epoch: float,
            max_rss_mb: float, tool_handler, guard, progress) -> dict:
        start = self.clock()
        source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest() if type(source) is str else None
        process = None
        root_identity = None
        observed = {}
        observed_identities = {}
        launch_attempted = False
        observation_error = False
        started = False
        cleaned = False
        cleanup_verified = False
        cleanup_lock = threading.Lock()
        peak_rss = 0.0
        residual = []
        stop = None
        status, output, error = "unknown", None, None
        supervisor = None
        command_digest = None
        monitor_done = threading.Event()
        monitor_stop = []
        selector = None
        monitor = None
        messages = 0
        log = ""
        log_truncated = False
        final = None
        known_run_ids = set()
        binding_copy = dict(binding) if isinstance(binding, dict) else {}
        phase = Path(directory).absolute()

        def record(event, state):
            payload = {"schema_version": SCHEMA, **binding_copy,
                "root": root_identity, "supervisor": supervisor,
                "command_digest": command_digest, "source_sha256": source_sha,
                "deadline_epoch": deadline_epoch, "max_rss_mb": max_rss_mb,
                "known_descendants": list(observed_identities.values()),
                "status": state, "started": started,
                "no_child_dispatched": not launch_attempted,
                "cleanup_verified": cleanup_verified,
                "peak_rss_mb": peak_rss}
            if event == "cleanup":
                payload.update({"residual_processes": list(residual),
                    "returncode": process.returncode if process else None,
                    "resource": resource()})
            progress(event, payload)

        def resource():
            return {"returncode": process.returncode if process else None,
                    "stop": stop, "peak_rss_mb": peak_rss,
                    "seconds": max(0.0, self.clock() - start),
                    "residual_processes": list(residual)}

        def check_guard():
            try:
                if guard() is False:
                    raise PermissionError("Execution guard denied the original owner")
            except Exception as exc:
                raise _Stop(_guard_status(exc), type(exc).__name__ + ": " + str(exc)[:1000]) from exc
            if self.clock() >= deadline_epoch:
                raise _Stop("timeout", "Original program deadline reached")
            if monitor_stop:
                raise _Stop(monitor_stop[0][0], monitor_stop[0][1])

        def sample():
            nonlocal peak_rss, observation_error
            if process is None or root_identity is None:
                return
            try:
                root = psutil.Process(process.pid)
                if root.create_time() != root_identity["create_time"]:
                    if process.poll() is None:
                        observation_error = True
                    return
                children = root.children(recursive=True)
                for item in children:
                    observed[item.pid] = item
                    try:
                        observed_identities[item.pid] = _identity(item)
                    except (psutil.NoSuchProcess, ProcessLookupError):
                        pass
                alive = [root, *list(observed.values())]
                total = 0.0
                for item in alive:
                    try:
                        if item.is_running() and item.status() != psutil.STATUS_ZOMBIE:
                            total += item.memory_info().rss / 2**20
                    except psutil.NoSuchProcess:
                        pass
                    except (psutil.Error, OSError):
                        observation_error = True
                with self._observation_lock:
                    self._current_rss = total
                peak_rss = max(peak_rss, total)
            except psutil.NoSuchProcess:
                if process.poll() is None:
                    observation_error = True
            except (psutil.Error, OSError):
                observation_error = True

        def cleanup():
            nonlocal cleanup_verified, cleaned, residual, observation_error
            with cleanup_lock:
                if cleaned:
                    return
                if process is None:
                    cleanup_verified, cleaned = not launch_attempted, True
                    return
                # Reuse the existing identity-checked cleanup implementation;
                # importing at execution time avoids a service import cycle.
                try:
                    from sckg_workbench.analysis import AnalysisService
                    result, identity_safe = AnalysisService._cleanup_observed_processes(
                        process, root_identity, list(observed.values()))
                    residual = list(result.residual_processes)
                    cleanup_verified = (identity_safe and not observation_error
                                        and process.poll() is not None and not residual)
                except Exception:
                    observation_error = True
                    cleanup_verified = False
                    residual = [process.pid] if process.poll() is None else []
                cleaned = True
                with self._observation_lock:
                    self._current_rss = 0.0

        def monitor_loop():
            while not monitor_done.wait(0.05):
                sample()
                reason = None
                if observation_error:
                    reason = ("unknown", "Guest process observation became unknown")
                elif self.clock() >= deadline_epoch:
                    reason = ("timeout", "Original program deadline reached")
                elif peak_rss > max_rss_mb:
                    reason = ("unknown", "Guest RSS limit exceeded")
                if reason:
                    monitor_stop.append(reason)
                    cleanup()
                    return
                if process.poll() is not None:
                    return

        try:
            if (set(binding_copy) != _BINDING_KEYS or binding_copy.get("phase") not in {"initial", "patch"}
                    or type(binding_copy.get("attempt")) is not int or binding_copy["attempt"] < 1
                    or binding_copy.get("source_sha256") != source_sha):
                raise CodePolicyError("Incomplete or mismatched frozen phase binding")
            if (type(deadline_epoch) not in {int, float} or not math.isfinite(deadline_epoch)
                    or type(max_rss_mb) not in {int, float} or not math.isfinite(max_rss_mb)
                    or not 0 < max_rss_mb <= 2048):
                raise CodePolicyError("Invalid bounded runtime resources")
            validate_source(source)
            if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
                raise CodePolicyError("Supported macOS sandbox boundary unavailable")
            if not Path(self.runtime_python).is_file():
                raise CodePolicyError("Existing Python runtime unavailable")
            runtime_resources = _runtime_read_resources(self.runtime_python)
            check_guard()
            phase.mkdir(mode=0o700, parents=True, exist_ok=True)
            if phase.is_symlink() or any(phase.iterdir()):
                raise CodePolicyError("Phase directory must be a new empty owned directory")
            phase = phase.resolve()
            worker = Path(__file__).with_name("code_worker.py").resolve()
            source_path = phase / "source.py"
            with source_path.open("x", encoding="utf-8") as file:
                file.write(source)
            source_path.chmod(0o400)
            policy_path = phase / "worker.sb"
            with policy_path.open("x", encoding="utf-8") as file:
                file.write(_sandbox_policy(phase=phase, worker=worker, source=source_path,
                                           runtime_resources=runtime_resources))
            policy_path.chmod(0o400)
            command = ["/usr/bin/sandbox-exec", "-f", str(policy_path),
                       self.runtime_python, "-I", "-B", "-S", str(worker)]
            command_digest = hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest()
            supervisor = {**_identity(psutil.Process(os.getpid())),
                          "native_thread_id": threading.get_native_id(),
                          "thread_ident": threading.get_ident()}
            environment = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
                "PYTHONIOENCODING": "utf-8", "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": "",
                "TMPDIR": str(phase)}
            check_guard()
            launch_attempted = True
            process = subprocess.Popen(command, cwd=phase, env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, close_fds=True)
            root_identity = _identity(psutil.Process(process.pid))
            started = True
            # Child cannot execute source until the caller durably records the
            # actual identity and the parent sends the private bootstrap.
            record("started", "running")
            sample()
            check_guard()
            process.stdin.write(encode_frame({"v": 1, "type": "bootstrap", "source": source,
                                               "source_sha256": source_sha}))
            process.stdin.flush()
            selector = selectors.DefaultSelector()
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            monitor = threading.Thread(target=monitor_loop, name="code-guest-resource-monitor", daemon=True)
            monitor.start()
            stdout = bytearray()
            stderr = bytearray()
            last_update = self.clock()
            while True:
                check_guard()
                if self.clock() - last_update >= 1.0:
                    record("updated", "running")
                    last_update = self.clock()
                for key, _ in selector.select(timeout=0.05):
                    data = os.read(key.fileobj.fileno(), MAX_FRAME_BYTES + 4)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stderr":
                        stderr.extend(data)
                        if len(stderr) > 16384:
                            raise _Stop("unknown", "Guest stderr exceeded limit")
                        continue
                    stdout.extend(data)
                    while len(stdout) >= 4:
                        length = struct.unpack("!I", stdout[:4])[0]
                        if not 0 < length <= MAX_FRAME_BYTES:
                            raise _Stop("unknown", "Malformed private frame length")
                        if len(stdout) < length + 4:
                            break
                        value = decode_payload(bytes(stdout[4:length + 4]))
                        del stdout[:length + 4]
                        if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
                            raise _Stop("unknown", "Malformed private frame")
                        if final is not None:
                            raise _Stop("unknown", "Unexpected frame after guest final")
                        if value.get("type") == "tool_request":
                            if (set(value) != {"v", "type", "seq", "operation"}
                                    or type(value.get("seq")) is not int or value["seq"] != messages + 1
                                    or value.get("operation") not in OPERATIONS):
                                raise _Stop("unknown", "Malformed frozen operation request")
                            messages += 1
                            if messages > MAX_TOOL_MESSAGES:
                                raise _Stop("unknown", "Frozen-operation message limit exceeded")
                            check_guard()
                            # Keep this synchronous: scientific worker grants
                            # belong to this exact original owner thread.
                            response = tool_handler(value["operation"])
                            check_guard()
                            response_frame = encode_frame({"v": 1, "type": "tool_response",
                                "seq": messages, "output": response})
                            if value["operation"] == "run_scrublet" and isinstance(response, dict):
                                run_id = response.get("run_id")
                                if type(run_id) is str and 0 < len(run_id) <= 256:
                                    known_run_ids.add(run_id)
                            process.stdin.write(response_frame)
                            process.stdin.flush()
                        elif value.get("type") == "final":
                            if (set(value) != {"v", "type", "status", "output", "error", "log", "log_truncated", "tool_messages"}
                                    or value.get("status") not in {"ok", "python_error", "rejected"}
                                    or type(value.get("log")) is not str
                                    or len(value["log"].encode()) > 16384
                                    or type(value.get("log_truncated")) is not bool
                                    or type(value.get("tool_messages")) is not int
                                    or value["tool_messages"] != messages):
                                raise _Stop("unknown", "Malformed guest final")
                            if value["status"] == "ok":
                                result = value["output"]
                                if (type(result) is not dict or set(result) != {"run_id"}
                                        or type(result.get("run_id")) is not str
                                        or result["run_id"] not in known_run_ids or value["error"] is not None):
                                    raise _Stop("unknown", "Unbound guest scientific result")
                            elif (value["output"] is not None or type(value["error"]) is not dict
                                  or set(value["error"]) != {"type", "message"}
                                  or any(type(x) is not str for x in value["error"].values())
                                  or len(value["error"]["type"]) > 80 or len(value["error"]["message"]) > 2000):
                                raise _Stop("unknown", "Malformed guest error")
                            final = value
                        else:
                            raise _Stop("unknown", "Unexpected guest protocol message")
                    if len(stdout) > MAX_FRAME_BYTES + 4:
                        raise _Stop("unknown", "Private channel buffer exceeded limit")
                if process.poll() is not None and not selector.get_map():
                    if stdout or final is None or process.returncode != 0:
                        raise _Stop("unknown", "Guest exited without a complete valid result")
                    check_guard()
                    status, output, error = final["status"], final["output"], final["error"]
                    log, log_truncated = final["log"], final["log_truncated"]
                    break
        except CodePolicyError as exc:
            status, error, stop = "rejected", _bounded_error(exc), "policy_rejected"
        except _Stop as exc:
            status, error, stop = exc.status, _bounded_error(exc), exc.reason
        except Exception as exc:
            status, error, stop = "unknown", _bounded_error(exc), "runtime_or_tool_exception"
        finally:
            monitor_done.set()
            if monitor is not None:
                monitor.join(timeout=3.0)
            cleanup()
            if monitor_stop:
                status, output, stop = monitor_stop[0][0], None, monitor_stop[0][1]
                error = {"type": "RuntimeLimit", "message": stop}
            if not cleanup_verified:
                status, output = "unknown", None
                error = error or {"type": "CleanupUnknown", "message": "Guest cleanup could not be verified"}
            if selector is not None:
                selector.close()
            for stream in (getattr(process, "stdin", None), getattr(process, "stdout", None), getattr(process, "stderr", None)):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            try:
                record("cleanup", "known_owned_processes_stopped" if process and cleanup_verified else
                       "never_started" if process is None and cleanup_verified else "cleanup_unknown")
            except Exception as exc:
                status, output = "unknown", None
                error = {"type": "ProgressPersistenceError", "message": str(exc)[:2000]}
        return {"status": status, "output": output, "error": error,
            "cleanup_verified": cleanup_verified, "resource": resource(),
            "binding": binding_copy, "source_sha256": source_sha,
            "child_started": process is not None,
            "dispatch_status": "started" if process is not None else "unknown" if launch_attempted else "not_started",
            "log": log, "log_truncated": log_truncated, "tool_messages": messages}


def _still_alive(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return False
