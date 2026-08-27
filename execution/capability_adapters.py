from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.capability_pack_models import ExecutionAdapterBinding


class ExecutionAdapter(Protocol):
    adapter_id: str
    runtime_kind: str

    def command(self, request_filename: str) -> list[str]: ...


@dataclass(frozen=True)
class PythonModuleExecutionAdapter:
    adapter_id: str
    python_executable: Path
    module: str
    runtime_kind: str = "python_module"

    def command(self, request_filename: str) -> list[str]:
        executable = self.python_executable.resolve(strict=True)
        return [str(executable), "-m", self.module, "--request-json", request_filename]


@dataclass(frozen=True)
class RScriptExecutionAdapter:
    adapter_id: str
    rscript_executable: Path
    script_path: Path
    runtime_kind: str = "rscript"

    def command(self, request_filename: str) -> list[str]:
        executable = self.rscript_executable.resolve(strict=True)
        script = self.script_path.resolve(strict=True)
        return [str(executable), str(script), "--request-json", request_filename]


class ExecutionAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}

    def register(self, adapter: ExecutionAdapter) -> None:
        if adapter.adapter_id in self._adapters:
            raise ValueError(f"duplicate execution adapter: {adapter.adapter_id}")
        self._adapters[adapter.adapter_id] = adapter

    def get(self, adapter_id: str) -> ExecutionAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise KeyError(f"execution adapter is not registered: {adapter_id}") from exc

    def validate_binding(self, binding: ExecutionAdapterBinding) -> bool:
        adapter = self.get(binding.adapter_id)
        return adapter.runtime_kind == binding.runtime_kind
