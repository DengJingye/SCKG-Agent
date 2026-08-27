from __future__ import annotations

from pathlib import Path
from typing import Any

from core.capability_composition_models import CapabilityCompositionRequest
from core.capability_pack_registry import CapabilityPackRegistry
from core.capability_workspace_models import (
    CapabilityWorkspaceRequest,
    CapabilityWorkspaceResult,
)
from engine.capability_composer import CapabilityWorkflowComposer
from engine.data_profiler import AnnDataProfiler
from engine.representation_profiler import AnnDataRepresentationProfiler
from execution.capability_notebook import GenericNotebookCompiler
from execution.data_registry import DataRegistry


class CapabilityWorkspaceService:
    """Thin application service over registries and existing deterministic controls."""

    def __init__(
        self,
        *,
        data_registry: DataRegistry,
        notebook_compiler: GenericNotebookCompiler,
        pack_registry: CapabilityPackRegistry | None = None,
        profiler: AnnDataRepresentationProfiler | None = None,
        composer: CapabilityWorkflowComposer | None = None,
        data_profiler: AnnDataProfiler | None = None,
    ) -> None:
        self.data_registry = data_registry
        self.pack_registry = pack_registry or CapabilityPackRegistry()
        self.profiler = profiler or AnnDataRepresentationProfiler()
        self.composer = composer or CapabilityWorkflowComposer(
            registry=self.pack_registry
        )
        self.data_profiler = data_profiler or AnnDataProfiler()
        self.notebook_compiler = notebook_compiler

    def prepare(
        self,
        request: CapabilityWorkspaceRequest,
        *,
        notebook_path: Path,
    ) -> CapabilityWorkspaceResult:
        manifest = self.pack_registry.load(request.pack_id, request.pack_version)
        gate = self.pack_registry.gate(manifest)
        readiness = [str(item) for item in gate.readiness]
        if request.mode == "ASK":
            return CapabilityWorkspaceResult(
                request_id=request.request_id,
                pack_id=request.pack_id,
                pack_version=request.pack_version,
                status="discovered",
                readiness=readiness,
                blockers=gate.blockers,
            )

        path = self.data_registry.resolve_path(
            request.artifact_id,
            user_id=request.user_id,
        )
        data_profile = self.data_profiler.profile(path, batch_key=request.batch_key)
        ledger = self.profiler.profile(
            path,
            artifact_id=request.artifact_id,
            batch_key=request.batch_key,
        )
        plan, plan_result, composition = self.composer.compose(
            request=CapabilityCompositionRequest(
                pack_id=request.pack_id,
                pack_version=request.pack_version,
                requirement_id=request.requirement_id,
                target_representations=request.target_representations,
                preferred_method_ids=request.preferred_method_ids,
                enable_doublet_detection=request.enable_doublet_detection,
                exclude_predicted_doublets=request.exclude_predicted_doublets,
                doublet_selection_hash=request.doublet_selection_hash,
                enable_batch_integration=request.enable_batch_integration,
            ),
            ledger=ledger,
        )
        blockers = sorted(set(gate.blockers + plan_result.blocking_reasons))
        notebook_artifact = {}
        if not blockers:
            notebook_artifact = self.notebook_compiler.compile(
                plan=plan,
                step_contracts=self.pack_registry.load_step_contracts(manifest),
                output_path=notebook_path,
                title=f"{manifest.pack_id} governed workflow",
                notebook_context={
                    "input_path": str(path),
                    "artifact_id": request.artifact_id,
                    "batch_key": request.batch_key,
                },
            )
        if blockers:
            status = "blocked"
        elif request.mode == "RUN":
            status = "blocked"
            blockers = ["execution_policy_disabled"]
        else:
            status = "planned"
        return CapabilityWorkspaceResult(
            request_id=request.request_id,
            pack_id=request.pack_id,
            pack_version=request.pack_version,
            status=status,
            readiness=readiness,
            data_profile=_stable_model_payload(data_profile),
            representation_ledger=_stable_model_payload(ledger),
            workflow_plan=_stable_model_payload(plan),
            composition=_stable_model_payload(composition),
            notebook_artifact=notebook_artifact,
            blockers=blockers,
        )


def _stable_model_payload(value: Any) -> Any:
    """Cross Streamlit reload boundaries without relying on model class identity."""

    if value is None or isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value
