import os
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRequest
from execution.local_controlled_executor import LocalControlledExecutor
from execution.wrapper_registry import WrapperDefinition, WrapperRegistry
from tests.qualification_helpers import build_qualification_case


def test_executor_blocks_unknown_wrapper_invalid_parameter_and_unauthorized(tmp_path):
    case = build_qualification_case(tmp_path)
    executor = _executor(tmp_path, case)

    unknown_contract = case["contract"].model_copy(update={"wrapper_id": "unknown_wrapper"})
    unknown_request = case["request"].model_copy(update={"wrapper_id": "unknown_wrapper"})
    unknown_decision = _route(case, unknown_request, contract=unknown_contract)
    unknown = executor.execute(
        request=unknown_request,
        artifact=case["artifact"],
        contract=unknown_contract,
        router_decision=unknown_decision,
    )
    assert unknown.status == "blocked"
    assert unknown.error_type == "unknown_wrapper"
    assert unknown.command_argv_redacted == []

    invalid_request = case["request"].model_copy(
        update={"run_id": "invalid-parameter", "parameters": {"n_prin_comps": 1000}}
    )
    invalid = executor.execute(
        request=invalid_request,
        artifact=case["artifact"],
        contract=case["contract"],
        router_decision=case["decision"],
    )
    assert invalid.status == "blocked"
    assert invalid.error_type == "invalid_parameter"

    unauthorized_request = case["request"].model_copy(
        update={
            "run_id": "unauthorized",
            "actor": case["request"].actor.model_copy(update={"role": "user"}),
        }
    )
    unauthorized_decision = _route(case, unauthorized_request)
    unauthorized = executor.execute(
        request=unauthorized_request,
        artifact=case["artifact"],
        contract=case["contract"],
        router_decision=unauthorized_decision,
    )
    assert unauthorized.status == "blocked"
    assert unauthorized.command_argv_redacted == []


def test_executor_blocks_traversal_symlink_and_shell_metacharacter(tmp_path):
    case = build_qualification_case(tmp_path)
    executor = _executor(tmp_path, case)
    outside = tmp_path / "outside.h5ad"
    outside.write_bytes(Path(case["artifact"].path).read_bytes())
    escaped_artifact = case["artifact"].model_copy(update={"path": str(outside)})
    escaped = executor.execute(
        request=case["request"],
        artifact=escaped_artifact,
        contract=case["contract"],
        router_decision=case["decision"],
    )
    assert escaped.status == "blocked"
    assert escaped.error_type == "input_path_invalid"

    symlink = tmp_path / "probes" / "probe-link.h5ad"
    symlink.symlink_to(Path(case["artifact"].path))
    symlink_artifact = case["artifact"].model_copy(update={"path": str(symlink)})
    symlink_run = executor.execute(
        request=case["request"].model_copy(update={"run_id": "symlink-input"}),
        artifact=symlink_artifact,
        contract=case["contract"],
        router_decision=case["decision"],
    )
    assert symlink_run.status == "blocked"
    assert symlink_run.error_type == "symlink_input_forbidden"

    with pytest.raises(ValidationError):
        ExecutionRequest.model_validate(
            {**case["request"].model_dump(), "run_id": "run;touch-escaped"}
        )


def test_executor_detects_output_escape(tmp_path):
    case = build_qualification_case(tmp_path)
    registry = _test_wrapper_registry("tests.fixtures.output_escape_wrapper")
    executor = _executor(tmp_path, case, wrapper_registry=registry)
    run = executor.execute(
        request=case["request"].model_copy(update={"run_id": "output-escape"}),
        artifact=case["artifact"],
        contract=case["contract"],
        router_decision=case["decision"],
    )
    assert run.status == "failed"
    assert run.error_type == "output_path_escape"


def test_executor_timeout_cleans_process_group_and_keeps_logs(tmp_path):
    case = build_qualification_case(tmp_path)
    registry = _test_wrapper_registry("tests.fixtures.timeout_wrapper")
    executor = _executor(tmp_path, case, wrapper_registry=registry)
    request = case["request"].model_copy(
        update={"run_id": "timeout-run", "timeout_seconds": 1}
    )
    run = executor.execute(
        request=request,
        artifact=case["artifact"],
        contract=case["contract"],
        router_decision=case["decision"],
    )
    assert run.status == "timeout"
    assert run.process_cleanup.timeout_triggered is True
    assert run.process_cleanup.terminate_sent or run.process_cleanup.kill_sent
    assert Path(run.stdout_path).exists()
    assert Path(run.stderr_path).exists()
    child_file = Path(run.stdout_path).parent / "artifacts" / "child_pid.txt"
    assert child_file.is_file()
    child_pid = int(child_file.read_text(encoding="utf-8"))
    for _ in range(20):
        if not _pid_exists(child_pid):
            break
        time.sleep(0.05)
    assert not _pid_exists(child_pid)


def _executor(tmp_path, case, wrapper_registry=None):
    return LocalControlledExecutor(
        run_root=tmp_path / "runs",
        approved_input_root=tmp_path / "probes",
        wrapper_registry=wrapper_registry,
        environment_registry=case["environment_registry"],
    )


def _route(case, request, contract=None):
    contract = contract or case["contract"]
    return DeterministicRouter().route_qualification(
        request=request,
        artifact=case["artifact"],
        tool_contract=contract,
        environment=case["environment_registry"].get("scRNAseq"),
        planning_gate=case["planning_gate"],
        max_timeout_seconds=120,
    )


def _test_wrapper_registry(module: str) -> WrapperRegistry:
    return WrapperRegistry(
        [
            WrapperDefinition(
                wrapper_id="scrublet_v0_2_3",
                environment_id="scRNAseq",
                tool_name="Scrublet",
                tool_version="0.2.3",
                module=module,
                python_executable=Path(sys.executable),
            )
        ]
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
