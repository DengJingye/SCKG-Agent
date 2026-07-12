from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable


@dataclass(frozen=True)
class WrapperDefinition:
    wrapper_id: str
    environment_id: str
    tool_name: str
    tool_version: str
    module: str
    python_executable: Path

    def command(self, request_filename: str = "worker_request.json") -> list[str]:
        return [
            str(self.python_executable),
            "-m",
            self.module,
            "--request-json",
            request_filename,
        ]


class WrapperRegistry:
    def __init__(self, definitions: Iterable[WrapperDefinition] | None = None) -> None:
        definitions = (
            list(definitions)
            if definitions is not None
            else [_scrublet_definition(), _scdblfinder_definition()]
        )
        self._definitions: Dict[str, WrapperDefinition] = {}
        for definition in definitions:
            if definition.wrapper_id in self._definitions:
                raise ValueError(f"duplicate wrapper id: {definition.wrapper_id}")
            self._definitions[definition.wrapper_id] = definition

    def get(self, wrapper_id: str) -> WrapperDefinition:
        try:
            return self._definitions[wrapper_id]
        except KeyError as exc:
            raise KeyError(f"wrapper is not allowlisted: {wrapper_id}") from exc

    def contains(self, wrapper_id: str) -> bool:
        return wrapper_id in self._definitions


def _scrublet_definition() -> WrapperDefinition:
    conda_exe = Path(os.environ.get("CONDA_EXE", "/opt/anaconda3/bin/conda"))
    conda_root = conda_exe.parent.parent
    python_executable = conda_root / "envs" / "scRNAseq" / "bin" / "python"
    return WrapperDefinition(
        wrapper_id="scrublet_v0_2_3",
        environment_id="scRNAseq",
        tool_name="Scrublet",
        tool_version="0.2.3",
        module="execution.wrappers.scrublet",
        python_executable=python_executable,
    )


def _scdblfinder_definition() -> WrapperDefinition:
    conda_exe = Path(os.environ.get("CONDA_EXE", "/opt/anaconda3/bin/conda"))
    conda_root = conda_exe.parent.parent
    python_executable = conda_root / "envs" / "scRNAseq" / "bin" / "python"
    return WrapperDefinition(
        wrapper_id="scdblfinder_not_installed",
        environment_id="scDblFinder-R",
        tool_name="scDblFinder",
        tool_version="not_installed",
        module="execution.wrappers.scdblfinder",
        python_executable=python_executable,
    )
