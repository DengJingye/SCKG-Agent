"""Process observation/cleanup shared by existing execution and analysis supervision.

No settings, runtime provisioning, credential loading, or scientific dispatch.
"""
from __future__ import annotations

import os
import signal
import subprocess

import psutil

from core.execution_models import ProcessCleanup


def _process_tree_rss_mb(pid: int) -> float:
    try:
        parent = psutil.Process(pid)
        try:
            processes = [parent, *parent.children(recursive=True)]
        except (psutil.Error, PermissionError):
            processes = [parent]
        return sum(process.memory_info().rss for process in processes if process.is_running()) / 2**20
    except (psutil.Error, ProcessLookupError, PermissionError):
        return 0.0

def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    timeout_triggered: bool = False,
    cancellation_triggered: bool = False,
    cancellation_reason: str | None = None,
    known_children: list[psutil.Process] | None = None,
) -> ProcessCleanup:
    children: list[psutil.Process] = []
    for child in known_children or []:
        try:
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                children.append(child)
        except psutil.Error:
            pass
    try:
        children.extend(psutil.Process(process.pid).children(recursive=True))
    except (psutil.Error, PermissionError):
        pass
    known_pids = {item.pid for item in children}
    try:
        candidates = psutil.process_iter(["pid"])
        for candidate in candidates:
            if candidate.pid == process.pid:
                continue
            try:
                if os.getpgid(candidate.pid) == process.pid and candidate.pid not in known_pids:
                    children.append(candidate)
                    known_pids.add(candidate.pid)
            except (OSError, psutil.Error, PermissionError):
                continue
    except (psutil.Error, PermissionError):
        pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
        terminate_sent = True
    except (ProcessLookupError, PermissionError):
        terminate_sent = False
    # Descendants may have created another session/process group. Process
    # objects retain identity checks, so terminate those observed descendants too.
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(children, timeout=1.0)
    kill_sent = False
    if process.poll() is None or alive:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            kill_sent = True
        except (ProcessLookupError, PermissionError):
            pass
        for child in alive:
            try:
                child.kill()
                kill_sent = True
            except psutil.Error:
                pass
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass
    residual = []
    for child in children:
        try:
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                residual.append(child.pid)
        except (psutil.Error, PermissionError):
            continue
    return ProcessCleanup(
        timeout_triggered=timeout_triggered,
        terminate_sent=terminate_sent,
        kill_sent=kill_sent,
        child_processes_seen=len(children),
        residual_processes=residual,
        cancellation_triggered=cancellation_triggered,
        cancellation_reason=cancellation_reason,
    )
