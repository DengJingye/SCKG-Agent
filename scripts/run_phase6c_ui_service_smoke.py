#!/usr/bin/env python
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from execution.execution_policy import ExecutionPolicy, ExecutionPolicyMode
from tests.execution_ui_helpers import approval_confirmations, build_ui_harness


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    root = PROJECT_ROOT / ".sckg_exec" / "phase6c" / token
    harness = build_ui_harness(root)
    outputs = []
    for tool_name, tool_version, parameters in (
        ("Scrublet", "0.2.3", {"n_prin_comps": 2}),
        ("scDblFinder", "1.24.0", {}),
    ):
        request_id = f"phase6c-{tool_name.casefold()}-{token}"
        query = f"run approved local {tool_name} doublet detection"
        grant = harness.service.grant_profile_access(
            user_id="user-a", artifact_id=harness.artifact.artifact_id
        )
        planned = harness.service.prepare(
            user_id="user-a",
            artifact_id=harness.artifact.artifact_id,
            data_grant_id=grant.grant_id,
            execution_approval_id=None,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=tool_name,
            tool_version=tool_version,
        )
        approval = harness.service.create_plan_approval(
            context=planned,
            data_grant_id=grant.grant_id,
            confirmations=approval_confirmations(),
            confirmation_text=harness.service.confirmation_text(planned),
            max_uses=2,
        )
        approved = harness.service.prepare(
            user_id="user-a",
            artifact_id=harness.artifact.artifact_id,
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            tool_name=tool_name,
            tool_version=tool_version,
        )
        job = harness.service.start_execution(
            context=approved,
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            package_id=f"phase6c-{tool_name.casefold()}-{token}",
            requested_runs=2,
        )
        status = _wait(harness.service, job.job_id)
        if status.result is None:
            raise RuntimeError(status.error_summary or f"{tool_name} UI job failed")
        view = harness.service.result_view(user_id="user-a", result=status.result)
        outputs.append(
            {
                "tool_name": tool_name,
                "profile_ready": planned.profile is not None
                and not planned.profile.is_blocked,
                "plan_ready": planned.plan is not None
                and planned.plan.plan_status == "dry_run",
                "approval_fingerprint": planned.approval_fingerprint,
                "button_enabled_after_approval": approved.button_enabled,
                "actual_runs": len(status.result.execution_runs),
                "successful_runs": sum(
                    item.status == "succeeded"
                    for item in status.result.execution_runs
                ),
                "validation_passed": all(
                    item.passed for item in status.result.validation_results
                ),
                "recommended_candidate_id": status.result.decision_result.recommended_candidate_id,
                "package_path": view.package_path_redacted,
                "package_complete": view.package_complete,
                "manifest_hashes_valid": view.manifest_hashes_valid,
                "logs_redacted": all(
                    str(root) not in item["stdout_summary"]
                    and str(root) not in item["stderr_summary"]
                    for item in view.run_statuses
                ),
            }
        )

    cancellation = _cancel_ui_job(harness, token)
    cross_user_blocked = False
    try:
        harness.service.result_view(
            user_id="user-b",
            result=_wait_result_from_output(harness, outputs),
        )
    except PermissionError:
        cross_user_blocked = True
    checks = {
        "profile": all(item["profile_ready"] for item in outputs),
        "plan": all(item["plan_ready"] for item in outputs),
        "approval": all(item["approval_fingerprint"] for item in outputs),
        "execute": all(item["successful_runs"] == 2 for item in outputs),
        "cancel": cancellation,
        "result": all(item["validation_passed"] for item in outputs),
        "package": all(
            item["package_complete"] and item["manifest_hashes_valid"]
            for item in outputs
        ),
        "ownership": cross_user_blocked,
        "redaction": all(item["logs_redacted"] for item in outputs),
        "default_policy_disabled": ExecutionPolicy().mode
        == ExecutionPolicyMode.DISABLED,
    }
    summary = {
        "ok": all(checks.values()),
        "checks": checks,
        "ui_policy": harness.service.execution_policy.mode,
        "global_default_policy": ExecutionPolicy().mode,
        "artifact": harness.artifact.model_dump(mode="json"),
        "tools": outputs,
        "cancellation": {"requested": cancellation, "backend": "UserWorkspaceService"},
        "cross_user_blocked": cross_user_blocked,
        "input_data_copied": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _wait(service, job_id, timeout=180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.poll_job(user_id="user-a", job_id=job_id)
        if status.state in {"completed", "failed"}:
            return status
        time.sleep(0.1)
    raise TimeoutError("UI service job did not complete")


def _cancel_ui_job(harness, token: str) -> bool:
    request_id = f"phase6c-cancel-{token}"
    query = "run approved local Scrublet doublet detection"
    parameters = {"n_prin_comps": 2}
    grant = harness.service.grant_profile_access(
        user_id="user-a", artifact_id=harness.artifact.artifact_id
    )
    planned = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=None,
        request_id=request_id,
        query=query,
        parameters=parameters,
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    approval = harness.service.create_plan_approval(
        context=planned,
        data_grant_id=grant.grant_id,
        confirmations=approval_confirmations(),
        confirmation_text=harness.service.confirmation_text(planned),
        max_uses=2,
    )
    approved = harness.service.prepare(
        user_id="user-a",
        artifact_id=harness.artifact.artifact_id,
        data_grant_id=grant.grant_id,
        execution_approval_id=approval.approval_id,
        request_id=request_id,
        query=query,
        parameters=parameters,
        tool_name="Scrublet",
        tool_version="0.2.3",
    )
    original = harness.service.local_user_service
    harness.service.local_user_service = _BlockingLocalService(harness.workspace)
    try:
        job = harness.service.start_execution(
            context=approved,
            data_grant_id=grant.grant_id,
            execution_approval_id=approval.approval_id,
            request_id=request_id,
            query=query,
            parameters=parameters,
            package_id=f"phase6c-cancel-{token}",
            requested_runs=2,
        )
        requested = harness.service.cancel_job(
            user_id="user-a", job_id=job.job_id, wait_seconds=2.0
        )
        status = _wait(harness.service, job.job_id, timeout=5.0)
        record = harness.workspace.get_record(
            resource_type="run", user_id="user-a", resource_id=f"{request_id}-run-1"
        )
        return requested and status.state == "failed" and record.status == "cancelled"
    finally:
        harness.service.local_user_service = original


def _wait_result_from_output(harness, outputs):
    package_id = Path(outputs[0]["package_path"]).name
    for job in harness.service._jobs.values():
        if not job.future.done():
            continue
        try:
            result = job.future.result()
        except Exception:
            continue
        if result.package_result.package_id == package_id:
            return result
    raise RuntimeError("completed UI result not found")


class _BlockingLocalService:
    def __init__(self, workspace):
        self.workspace = workspace

    def execute_approved_plan(self, **kwargs):
        run_id = f"{kwargs['request_id']}-run-1"
        self.workspace.reserve_run(user_id=kwargs["user_id"], run_id=run_id)
        self.workspace.mark_run_running(user_id=kwargs["user_id"], run_id=run_id)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.workspace.cancellation_reason(
                user_id=kwargs["user_id"], run_id=run_id
            ):
                self.workspace.mark_run_terminal(
                    user_id=kwargs["user_id"], run_id=run_id, status="cancelled"
                )
                raise RuntimeError("cancelled_by_local_user")
            time.sleep(0.02)
        raise RuntimeError("cancel smoke timed out")


if __name__ == "__main__":
    raise SystemExit(main())
