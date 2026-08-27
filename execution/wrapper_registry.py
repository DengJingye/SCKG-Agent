from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

from execution.runtime_pack_resolver import RuntimePackResolver
from core.settings import PROJECT_ROOT


@dataclass(frozen=True)
class WrapperDefinition:
    wrapper_id: str
    environment_id: str
    tool_name: str
    tool_version: str
    module: str
    python_executable: Path | None = None
    runtime_pack_id: str | None = None
    additional_runtime_pack_ids: tuple[str, ...] = ()
    resolver: RuntimePackResolver | None = None
    runtime_environment: tuple[tuple[str, str], ...] = ()

    def command(self, request_filename: str = "worker_request.json") -> list[str]:
        executable = self.python_executable
        if executable is None:
            if not self.runtime_pack_id or self.resolver is None:
                raise FileNotFoundError("wrapper runtime pack is not configured")
            executable = self.resolver.python(self.runtime_pack_id)
        return [
            str(executable),
            "-m",
            self.module,
            "--request-json",
            request_filename,
        ]

    def is_runtime_ready(self) -> bool:
        if self.python_executable is not None:
            return self.python_executable.is_file()
        if not self.runtime_pack_id or self.resolver is None:
            return False
        required = (self.runtime_pack_id, *self.additional_runtime_pack_ids)
        return all(self.resolver.ready(pack_id) for pack_id in required)

    def worker_environment(self) -> dict[str, str]:
        values = dict(self.runtime_environment)
        if self.wrapper_id == "scdblfinder_v1_24_0" and self.resolver is not None:
            values["SCKG_SCDBLFINDER_RSCRIPT"] = str(
                self.resolver.rscript("doublet-r")
            )
        if self.wrapper_id == "celltypist_v1_7_1":
            values["SCKG_CELLTYPIST_REFERENCE_MANIFEST"] = str(
                PROJECT_ROOT
                / "reference_packs/manifests/celltypist-immune-all-low-v1.json"
            )
        if self.wrapper_id == "singler_v2_14_0" and self.resolver is not None:
            values["SCKG_SINGLER_RSCRIPT"] = str(
                self.resolver.rscript("annotation-r")
            )
            values["SCKG_SINGLER_REFERENCE_MANIFEST"] = str(
                PROJECT_ROOT
                / "reference_packs/manifests/singler-immune-reference-v1.json"
            )
        return values


class WrapperRegistry:
    def __init__(
        self,
        definitions: Iterable[WrapperDefinition] | None = None,
        *,
        resolver: RuntimePackResolver | None = None,
    ) -> None:
        resolver = resolver or RuntimePackResolver()
        definitions = (
            list(definitions)
            if definitions is not None
            else [
                _scrublet_definition(resolver),
                _scdblfinder_definition(resolver),
                _harmony_definition(resolver),
                _scanorama_definition(resolver),
                _scanpy_core_definition(resolver),
                _celltypist_definition(resolver),
                _singler_definition(resolver),
            ]
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


def _scrublet_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return WrapperDefinition(
        wrapper_id="scrublet_v0_2_3",
        environment_id="scRNAseq",
        tool_name="Scrublet",
        tool_version="0.2.3",
        module="execution.wrappers.scrublet",
        runtime_pack_id="doublet-python",
        resolver=resolver,
    )


def _scdblfinder_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return WrapperDefinition(
        wrapper_id="scdblfinder_v1_24_0",
        environment_id="scDblFinder-R",
        tool_name="scDblFinder",
        tool_version="1.24.0",
        module="execution.wrappers.scdblfinder",
        runtime_pack_id="doublet-python",
        resolver=resolver,
    )


def _batch_definition(
    *,
    wrapper_id: str,
    tool_name: str,
    tool_version: str,
    module: str,
    resolver: RuntimePackResolver,
) -> WrapperDefinition:
    return WrapperDefinition(
        wrapper_id=wrapper_id,
        environment_id="sckg-batch-cpu",
        tool_name=tool_name,
        tool_version=tool_version,
        module=module,
        runtime_pack_id="batch-cpu",
        resolver=resolver,
    )


def _harmony_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return _batch_definition(
        wrapper_id="harmony_v2_0_0",
        tool_name="Harmony",
        tool_version="2.0.0",
        module="execution.wrappers.harmony",
        resolver=resolver,
    )


def _scanorama_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return _batch_definition(
        wrapper_id="scanorama_v1_7_4",
        tool_name="Scanorama",
        tool_version="1.7.4",
        module="execution.wrappers.scanorama",
        resolver=resolver,
    )


def _scanpy_core_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return WrapperDefinition(
        wrapper_id="scanpy_core_v1_11_2",
        environment_id="scRNAseq",
        tool_name="Scanpy",
        tool_version="1.11.2",
        module="execution.wrappers.scanpy_core",
        runtime_pack_id="doublet-python",
        resolver=resolver,
    )


def _celltypist_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return WrapperDefinition(
        wrapper_id="celltypist_v1_7_1",
        environment_id="annotation-python",
        tool_name="CellTypist",
        tool_version="1.7.1",
        module="execution.wrappers.celltypist",
        runtime_pack_id="annotation-python",
        resolver=resolver,
    )


def _singler_definition(resolver: RuntimePackResolver) -> WrapperDefinition:
    return WrapperDefinition(
        wrapper_id="singler_v2_14_0",
        environment_id="annotation-r",
        tool_name="SingleR",
        tool_version="2.14.0",
        module="execution.wrappers.singler",
        runtime_pack_id="annotation-python",
        additional_runtime_pack_ids=("annotation-r",),
        resolver=resolver,
    )
