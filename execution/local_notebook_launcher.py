from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


KERNEL_NAME = "sckg-doublet-python"


@dataclass(frozen=True)
class NotebookLaunchResult:
    editor_name: str
    kernel_name: str
    process_id: int | None
    launched: bool


class LocalNotebookLauncher:
    """Open an owned scKG notebook in a local editor without executing it."""

    def __init__(
        self,
        *,
        allowed_workspace_root: Path,
        kernel_root: Path | None = None,
        editor_executable: Path | None = None,
        process_launcher: Callable[..., object] = subprocess.Popen,
    ) -> None:
        self.allowed_workspace_root = Path(allowed_workspace_root).resolve()
        self.kernel_root = (
            Path(kernel_root).expanduser().resolve()
            if kernel_root is not None
            else (Path.home() / "Library" / "Jupyter" / "kernels").resolve()
        )
        discovered = editor_executable or _discover_editor()
        self.editor_executable = (
            Path(discovered).resolve() if discovered is not None else None
        )
        self.process_launcher = process_launcher

    @property
    def available(self) -> bool:
        return bool(
            self.editor_executable
            and self.editor_executable.is_file()
            and os.access(self.editor_executable, os.X_OK)
        )

    @property
    def editor_name(self) -> str:
        path = str(self.editor_executable or "").casefold()
        if "cursor.app" in path:
            return "Cursor"
        if "visual studio code.app" in path:
            return "Visual Studio Code"
        return "local editor"

    def launch(
        self,
        *,
        notebook_path: Path,
        expected_sha256: str,
        runtime_python: Path,
    ) -> NotebookLaunchResult:
        if not self.available:
            raise FileNotFoundError("no supported local notebook editor was found")
        notebook = Path(notebook_path)
        if notebook.is_symlink():
            raise ValueError("notebook path must not be a symlink")
        notebook = notebook.resolve(strict=True)
        _require_within(notebook, self.allowed_workspace_root)
        if notebook.suffix.casefold() != ".ipynb":
            raise ValueError("only .ipynb notebooks can be opened")
        if _sha256(notebook) != expected_sha256:
            raise ValueError("notebook hash changed")
        payload = json.loads(notebook.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {}).get("sckg", {})
        if metadata.get("trusted_code_source") != "maintainer_step_template":
            raise ValueError("notebook is not a maintainer-generated scKG notebook")

        runtime = Path(runtime_python)
        if runtime.is_symlink():
            runtime = runtime.resolve(strict=True)
        else:
            runtime = runtime.resolve(strict=True)
        if not runtime.is_file() or not os.access(runtime, os.X_OK):
            raise FileNotFoundError("notebook runtime Python is unavailable")
        self._write_kernel_spec(runtime)
        process = self.process_launcher(
            [str(self.editor_executable), "--reuse-window", str(notebook)],
            cwd=str(notebook.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
        return NotebookLaunchResult(
            editor_name=self.editor_name,
            kernel_name=KERNEL_NAME,
            process_id=getattr(process, "pid", None),
            launched=True,
        )

    def _write_kernel_spec(self, runtime_python: Path) -> Path:
        return write_kernel_spec(
            runtime_python=runtime_python,
            kernel_root=self.kernel_root,
            runtime_pack_id="doublet-python",
        )


def write_kernel_spec(
    *, runtime_python: Path, kernel_root: Path, runtime_pack_id: str
) -> Path:
    kernel_dir = Path(kernel_root) / KERNEL_NAME
    kernel_dir.mkdir(parents=True, exist_ok=True)
    target = kernel_dir / "kernel.json"
    payload = {
        "argv": [
            str(Path(runtime_python).resolve(strict=True)),
            "-m",
            "ipykernel_launcher",
            "-f",
            "{connection_file}",
        ],
        "display_name": "scKG Doublet Python",
        "language": "python",
        "metadata": {"debugger": True, "sckg_runtime_pack": runtime_pack_id},
    }
    temporary = target.with_name(".kernel.json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def _discover_editor() -> Path | None:
    executable = shutil.which("code")
    if executable:
        return Path(executable)
    for candidate in (
        Path("/Applications/Cursor.app/Contents/Resources/app/bin/code"),
        Path(
            "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
        ),
    ):
        if candidate.is_file():
            return candidate
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("notebook escapes the owned workspace") from exc
