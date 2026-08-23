from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from execution.local_notebook_launcher import KERNEL_NAME, LocalNotebookLauncher


class _Process:
    pid = 42


def _notebook(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "sckg": {
                        "trusted_code_source": "maintainer_step_template"
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_launcher_opens_owned_notebook_with_fixed_argv_and_kernel(tmp_path):
    workspace = tmp_path / "workspace"
    notebook = workspace / "alice" / "analysis_preview.ipynb"
    digest = _notebook(notebook)
    runtime = tmp_path / "runtime" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime.chmod(0o755)
    editor = tmp_path / "Cursor.app" / "bin" / "code"
    editor.parent.mkdir(parents=True)
    editor.write_text("#!/bin/sh\n", encoding="utf-8")
    editor.chmod(0o755)
    calls = []

    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Process()

    launcher = LocalNotebookLauncher(
        allowed_workspace_root=workspace,
        kernel_root=tmp_path / "kernels",
        editor_executable=editor,
        process_launcher=launch,
    )
    result = launcher.launch(
        notebook_path=notebook,
        expected_sha256=digest,
        runtime_python=runtime,
    )

    assert result.launched is True
    assert result.editor_name == "Cursor"
    assert calls[0][0] == [str(editor.resolve()), "--reuse-window", str(notebook.resolve())]
    assert calls[0][1]["shell"] is False
    kernel = json.loads(
        (tmp_path / "kernels" / KERNEL_NAME / "kernel.json").read_text(
            encoding="utf-8"
        )
    )
    assert kernel["argv"][0] == str(runtime.resolve())


def test_launcher_blocks_escape_hash_change_and_untrusted_notebook(tmp_path):
    workspace = tmp_path / "workspace"
    editor = tmp_path / "code"
    runtime = tmp_path / "python"
    for executable in (editor, runtime):
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
    launcher = LocalNotebookLauncher(
        allowed_workspace_root=workspace,
        kernel_root=tmp_path / "kernels",
        editor_executable=editor,
        process_launcher=lambda *args, **kwargs: _Process(),
    )
    outside = tmp_path / "outside.ipynb"
    digest = _notebook(outside)
    with pytest.raises(ValueError, match="escapes"):
        launcher.launch(
            notebook_path=outside,
            expected_sha256=digest,
            runtime_python=runtime,
        )

    owned = workspace / "analysis_preview.ipynb"
    digest = _notebook(owned)
    with pytest.raises(ValueError, match="hash changed"):
        launcher.launch(
            notebook_path=owned,
            expected_sha256="0" * 64,
            runtime_python=runtime,
        )
    payload = json.loads(owned.read_text(encoding="utf-8"))
    payload["metadata"]["sckg"]["trusted_code_source"] = "user"
    owned.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="maintainer-generated"):
        launcher.launch(
            notebook_path=owned,
            expected_sha256=hashlib.sha256(owned.read_bytes()).hexdigest(),
            runtime_python=runtime,
        )
