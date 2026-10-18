"""Execution completion gates over server records, independent of model prose.

These gates establish engineering completion, never scientific correctness.
They neither run work nor retry it, and cannot approve a cached tool receipt.
"""
from __future__ import annotations


def completion_gate(outcome):
    """Return a stop decision, or None for an allowed conversational finish."""
    state = outcome.get("state")
    if state in {"not_run", "profile_only"}:
        return None
    if state in {"validated_preview", "result_read"} and outcome.get("validated_preview") is True:
        return None
    statuses = {item.get("status") for item in outcome.get("tasks", [])}
    if state == "unverifiable" or "result_unknown" in statuses:
        status, kind, message = ("result_unknown", "AnalysisCompletionUnknown",
            "当前无法核验分析是否完整结束；已保留记录，不会自动重试。")
    elif "cancelled" in statuses:
        status, kind, message = "cancelled", "AnalysisCancelled", "分析已停止，未将模型回答作为完成结果。"
    elif statuses & {"queued", "running", "cancel_requested"}:
        status, kind, message = ("partial", "AnalysisNotCompleted",
            "分析仍在排队、运行或停止核对中，尚未交付已验收结果。")
    else:
        status, kind, message = ("failed", "AnalysisArtifactRejected",
            "本轮工具或分析产物未通过服务端验收，模型回答不能将其标记为成功。")
    return {"status": status, "error": {"type": kind, "message": message}}


def inspect_completion(steps, analysis, *, require_result_read=False):
    """Re-read every attempted analysis at finish, retaining original bindings."""
    outcome = {"state": "not_run", "validated_preview": False, "tasks": []}
    attempted = [step for step in steps if step.get("action") in {"run_scrublet", "read_analysis_result"}]
    # Initial program failure can have no scientific run yet. The final patch
    # is the authoritative selection for this same task/attempt; its service
    # revalidates the complete immutable initial+patch chain independently.
    programs = {}
    for step in steps:
        if step.get("action") in {"execute_program", "repair_program"}:
            result = step.get("result", {})
            programs[(result.get("task_id"), result.get("attempt"))] = step
    attempted.extend(programs.values())
    if not attempted:
        if require_result_read:
            outcome["state"] = "result_unavailable"
            return outcome
        if steps:
            outcome["state"] = ("profile_only" if all(
                step.get("action") == "inspect_dataset" and
                step.get("result", {}).get("status") == "bounded_profile" for step in steps)
                else "profile_failed")
        return outcome
    if any(not step.get("result", {}).get("task_id") for step in attempted):
        outcome["state"] = "failed_before_task"
        return outcome
    seen = set()
    try:
        for step in attempted:
            saved = step["result"]
            binding = (saved["task_id"], saved.get("attempt"), saved.get("run_id"))
            if binding in seen:
                continue
            seen.add(binding)
            task = analysis.get_task_snapshot(saved["task_id"])
            item = {"task_id": saved["task_id"], "status": task["status"], "validation_passed": False}
            outcome["tasks"].append(item)
            if task["attempt"] != saved.get("attempt"):
                raise ValueError("Analysis attempt changed after the tool receipt")
            if task["status"] != "succeeded":
                continue
            if not saved.get("run_id"):
                raise ValueError("Completed tool receipt is missing its original run")
            current = analysis.get_public_result_summary(saved["task_id"],
                attempt=saved["attempt"], expected_run_id=saved["run_id"])
            prior = saved.get("summary") or {}
            if prior and current.get("summary_sha256") != prior.get("summary_sha256"):
                raise ValueError("Analysis summary changed after the tool receipt")
            item["validation_passed"] = current.get("status") == "validated_preview_summary"
            item["result_status"] = current.get("status")
        outcome["validated_preview"] = bool(outcome["tasks"]) and all(
            task["validation_passed"] for task in outcome["tasks"])
        outcome["state"] = "validated_preview" if outcome["validated_preview"] else "not_validated"
    except Exception:
        outcome["state"] = "unverifiable"
    return outcome
