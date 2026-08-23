from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.runtime_pack_resolver import RuntimePackResolver


RECIPE = ROOT / "examples/workflows/harmony_batch_integration_workflow.py"
SUMMARY_PATH = ROOT / "data/evaluation/workflow_code_smoke_v1/harmony_summary.json"
RUNTIME_PACK_ID = "batch-cpu"


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / ".sckg_exec/workflow-code-smoke" / f"harmony-{timestamp}"
    try:
        runtime_python = RuntimePackResolver().python(RUNTIME_PACK_ID)
        runtime_error = None
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        runtime_python = None
        runtime_error = f"{type(exc).__name__}:{exc}"

    if runtime_python is None:
        summary = {
            "smoke_id": f"harmony-workflow-code-smoke-{timestamp}",
            "smoke_passed": False,
            "recipe_id": "batch-integration-harmony-python",
            "recipe_version": "1.0.0",
            "recipe_sha256": hashlib.sha256(RECIPE.read_bytes()).hexdigest(),
            "runtime_pack_id": RUNTIME_PACK_ID,
            "environment": None,
            "python_executable": None,
            "runtime_blocker": runtime_error,
            "harmony_actually_executed": False,
            "synthetic_demo": False,
            "user_data_used": False,
            "artifacts_complete": False,
            "exit_code": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_PATH.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1

    command = [
        str(runtime_python),
        str(RECIPE),
        "--demo",
        "--output",
        str(output_dir),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )
    required = [
        "integrated_embedding.tsv",
        "harmony_integrated.h5ad",
        "batch_mixing_before_after.png",
        "workflow_summary.json",
    ]
    artifacts_complete = all(
        (output_dir / name).is_file() and (output_dir / name).stat().st_size > 0
        for name in required
    )
    workflow_summary = {}
    if (output_dir / "workflow_summary.json").is_file():
        workflow_summary = json.loads(
            (output_dir / "workflow_summary.json").read_text(encoding="utf-8")
        )
    recipe_digest = hashlib.sha256(RECIPE.read_bytes()).hexdigest()
    smoke_passed = bool(
        completed.returncode == 0
        and artifacts_complete
        and workflow_summary.get("harmony_actually_executed") is True
        and workflow_summary.get("synthetic_demo") is True
        and workflow_summary.get("user_data_used") is False
    )
    summary = {
        "smoke_id": f"harmony-workflow-code-smoke-{timestamp}",
        "smoke_passed": smoke_passed,
        "recipe_id": "batch-integration-harmony-python",
        "recipe_version": "1.0.0",
        "recipe_sha256": recipe_digest,
        "runtime_pack_id": RUNTIME_PACK_ID,
        "environment": runtime_python.parent.parent.name,
        "python_executable": str(runtime_python),
        "runtime_blocker": None,
        "harmony_actually_executed": bool(
            workflow_summary.get("harmony_actually_executed")
        ),
        "synthetic_demo": bool(workflow_summary.get("synthetic_demo")),
        "user_data_used": False,
        "artifacts_complete": artifacts_complete,
        "input_shape": workflow_summary.get("input_shape"),
        "batch_count": workflow_summary.get("batch_count"),
        "output_directory": output_dir.relative_to(ROOT).as_posix(),
        "required_artifacts": required,
        "exit_code": completed.returncode,
        "stderr_tail": completed.stderr[-1000:],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
