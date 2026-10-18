"""Process-local background dispatch over the existing authoritative TaskQueue.

This is not a scheduler or a recovery queue. Only an explicit click starts one
thread; page reads never dispatch, resume or retry a task. Process loss retains
the existing lease, unknown-result and process-cleanup semantics.
"""
from __future__ import annotations

import math
import threading

from .analysis import KIND


_LOCK = threading.Lock()
_LAUNCHES = {}


def _key(workspace):
    return (str(workspace.root), workspace.namespace)


def _memory_admission(task):
    import psutil

    limit = task["profile_snapshot"]["max_rss_mb"]
    if type(limit) not in {int, float} or not math.isfinite(limit) or not 0 < limit <= 2048:
        raise ValueError("任务内存预算无效，尚未启动分析。")
    memory = psutil.virtual_memory()
    reserve = max(2 * 1024**3, memory.total // 4)
    required = int(limit * 1024**2) + 256 * 1024**2
    if memory.available - reserve <= required:
        raise ValueError(f"可用内存 {memory.available / 1024**3:.1f} GiB；启动需要超过 "
            f"{(reserve + required) / 1024**3:.2f} GiB（包含系统保留内存）。"
            "请关闭暂不使用的大型应用后重试；任务仍在队列中，尚未开始计算。")


def snapshot(workspace, task_id):
    """Observe the launch thread only; the task/result state stays in TaskQueue."""
    with _LOCK:
        launch = _LAUNCHES.get(_key(workspace))
        if not launch or launch["task_id"] != task_id:
            return None
        return {k: v for k, v in launch.items() if k != "thread"} | {
            "active": launch["thread"].is_alive()}


def start(analysis, task_id):
    """Start at most one local dispatcher per workspace without blocking the UI."""
    key = _key(analysis.workspace)
    with _LOCK:
        previous = _LAUNCHES.get(key)
        if previous and previous["thread"].is_alive():
            return {"status": "already_running" if previous["task_id"] == task_id else "busy"}
        task = analysis.get_task_snapshot(task_id)
        if task["kind"] != KIND:
            raise ValueError("此入口仅执行固定 Scrublet 任务；对话编排任务由原对话管理。")
        if task["status"] != "queued":
            return {"status": "not_queued"}
        if task["input_snapshot"].get("execution_authorized") is not True:
            raise ValueError("此任务没有本地执行授权，尚未启动分析。")
        pending = analysis.queue.peek_next()
        if pending is None or pending["task_id"] != task_id:
            return {"status": "busy"}
        _memory_admission(task)

        def guard(conn, candidate):
            if candidate["task_id"] != task_id or candidate["payload_digest"] != task["payload_digest"]:
                raise ValueError("分析任务已变化，未启动计算。")
            # Recheck under the original claim transaction. Refusal rolls back
            # before a task attempt is consumed, even after a delayed launch.
            if candidate["status"] == "queued":
                _memory_admission(candidate)

        launch = {"task_id": task_id, "status": "starting", "error": None}

        def execute():
            status, error = "finished", None
            try:
                completed = analysis.run_once(task_id=task_id,
                    worker_id="workbench-direct-background", execution_guard=guard)
                if completed is None:
                    status = "busy"
            except Exception as exc:
                # Usually a pre-claim guard error. Never invent a terminal task
                # result here; post-claim errors belong to AnalysisService.
                status, error = "launch_error", f"{type(exc).__name__}: {str(exc)[:1000]}"
            finally:
                with _LOCK:
                    launch.update(status=status, error=error)

        thread = threading.Thread(target=execute, name="workbench-direct-analysis", daemon=True)
        launch["thread"] = thread
        _LAUNCHES[key] = launch
        try:
            thread.start()
        except Exception:
            _LAUNCHES.pop(key, None)
            raise
        return {"status": "started"}
