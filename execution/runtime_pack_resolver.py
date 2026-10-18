from __future__ import annotations

from pathlib import Path

from execution.runtime_pack_manager import RuntimePackManager
from execution.runtime_pack_registry import RuntimePackRegistry


class RuntimePackResolver:
    """Resolve fixed executable entrypoints from qualified runtime packs."""

    def __init__(self, manager: RuntimePackManager | None = None) -> None:
        self.manager = manager or RuntimePackManager()

    @classmethod
    def for_read_only_discovery(
        cls, *, home: Path | None = None, registry: RuntimePackRegistry | None = None,
        allow_legacy_environments: bool = True,
    ) -> "RuntimePackResolver":
        """Read stable installed state without creating state or installation grants.

        Only server configuration chooses home; task/model input must never be
        passed here as a runtime path. Discovery is not a fresh import/fit check.
        """
        return cls(RuntimePackManager(home=home, registry=registry,
            allow_legacy_environments=allow_legacy_environments, read_only=True))

    def ready(self, pack_id: str) -> bool:
        return self.manager.probe(pack_id).ready

    def python(self, pack_id: str) -> Path:
        return self.manager.resolve_entrypoint(pack_id, "python")

    def rscript(self, pack_id: str) -> Path:
        return self.manager.resolve_entrypoint(pack_id, "rscript")

    def pack_for_environment(self, environment_id: str) -> str:
        return self.manager.registry.for_environment(environment_id).pack_id
