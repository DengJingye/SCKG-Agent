from __future__ import annotations

from pathlib import Path

from execution.runtime_pack_manager import RuntimePackManager


class RuntimePackResolver:
    """Resolve fixed executable entrypoints from qualified runtime packs."""

    def __init__(self, manager: RuntimePackManager | None = None) -> None:
        self.manager = manager or RuntimePackManager()

    def ready(self, pack_id: str) -> bool:
        return self.manager.probe(pack_id).ready

    def python(self, pack_id: str) -> Path:
        return self.manager.resolve_entrypoint(pack_id, "python")

    def rscript(self, pack_id: str) -> Path:
        return self.manager.resolve_entrypoint(pack_id, "rscript")

    def pack_for_environment(self, environment_id: str) -> str:
        return self.manager.registry.for_environment(environment_id).pack_id
