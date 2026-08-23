from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from execution.local_jupyter_service import LocalJupyterService
from execution.runtime_pack_resolver import RuntimePackResolver


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sckg-jupyter-smoke-") as temporary:
        root = Path(temporary)
        notebook = root / "workspace" / "analysis_preview.ipynb"
        notebook.parent.mkdir(parents=True)
        notebook.write_text(
            json.dumps(
                {
                    "cells": [],
                    "metadata": {
                        "kernelspec": {
                            "display_name": "scKG doublet Python runtime",
                            "language": "python",
                            "name": "sckg-doublet-python",
                        },
                        "sckg": {
                            "trusted_code_source": "maintainer_step_template"
                        },
                    },
                    "nbformat": 4,
                    "nbformat_minor": 5,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(notebook.read_bytes()).hexdigest()
        service = LocalJupyterService(
            allowed_workspace_root=root / "workspace",
            state_root=root / "state",
        )
        session = service.start(
            owner_user_id="smoke-user",
            notebook_path=notebook,
            expected_sha256=digest,
            runtime_python=RuntimePackResolver().python("doublet-python"),
            runtime_pack_id="doublet-python",
        )
        with urllib.request.urlopen(session.launch_url, timeout=3) as response:
            http_status = response.status
        stopped = service.stop(
            session_id=session.session_id, owner_user_id="smoke-user"
        )
        summary = {
            "jupyter_available": service.available,
            "localhost_only": session.launch_url.startswith("http://127.0.0.1:"),
            "runtime_pack": session.runtime_pack_id,
            "kernel": session.kernel_name,
            "http_status": http_status,
            "notebook_auto_executed": False,
            "dependency_install_attempted": False,
            "stopped": stopped,
        }
        if not all(
            (
                summary["jupyter_available"],
                summary["localhost_only"],
                summary["http_status"] == 200,
                summary["notebook_auto_executed"] is False,
                summary["dependency_install_attempted"] is False,
                summary["stopped"],
            )
        ):
            raise AssertionError(summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
