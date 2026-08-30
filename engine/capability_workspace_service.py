from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from core.capability_composition_models import CapabilityCompositionRequest
from core.capability_pack_registry import CapabilityPackRegistry
from core.capability_workspace_models import (
    CapabilityWorkspaceRequest,
    CapabilityWorkspaceResult,
)
from core.execution_models import DataProfile
from core.trace_context import (
    TraceCollector,
    TraceContext,
    TraceCorrelationKind,
    TraceKind,
    TracePrivacyError,
    TraceStage,
    TraceStatus,
    TraceValidationError,
    trace_correlation_id,
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
        trace_collector: TraceCollector | None = None,
    ) -> None:
        self.data_registry = data_registry
        self.pack_registry = pack_registry or CapabilityPackRegistry()
        self.profiler = profiler or AnnDataRepresentationProfiler()
        self.composer = composer or CapabilityWorkflowComposer(
            registry=self.pack_registry
        )
        self.data_profiler = data_profiler or AnnDataProfiler()
        self.notebook_compiler = notebook_compiler
        self._trace_collector = trace_collector or TraceCollector()

    def prepare(
        self,
        request: CapabilityWorkspaceRequest,
        *,
        notebook_path: Path,
    ) -> CapabilityWorkspaceResult:
        trace_request_id = _trace_request_id(request.request_id)
        trace = _new_stepwise_trace(request, trace_request_id=trace_request_id)
        with self._trace_collector.request_scope(trace):
            result = self._prepare(
                request,
                notebook_path=notebook_path,
                trace=trace,
            )
            instrumentation = trace.instrumentation()
            if result.status == "blocked":
                instrumentation.set_request_outcome(
                    TraceStatus.BLOCKED,
                    decision_type="stepwise_request_outcome",
                    outcome="blocked",
                    reason_code=(result.blockers[0] if result.blockers else "workspace_blocked"),
                    rule_version="capability_workspace_v0",
                )
            else:
                instrumentation.set_request_outcome(TraceStatus.SUCCESS)
        return result

    def _prepare(
        self,
        request: CapabilityWorkspaceRequest,
        *,
        notebook_path: Path,
        trace: TraceContext,
    ) -> CapabilityWorkspaceResult:
        manifest = self.pack_registry.load(request.pack_id, request.pack_version)
        gate = self.pack_registry.gate(manifest)
        readiness = [str(item) for item in gate.readiness]
        if request.mode == "ASK":
            return CapabilityWorkspaceResult(
                request_id=request.request_id,
                canonical_trace_id=trace.trace_id,
                pack_id=request.pack_id,
                pack_version=request.pack_version,
                status="discovered",
                readiness=readiness,
                blockers=gate.blockers,
            )

        instrumentation = trace.instrumentation()
        with instrumentation.span(
            stage=TraceStage.STATE_INSPECTION,
            component="capability_workspace_service",
            operation="inspect_dataset_state",
            input_refs=[
                {
                    "record_type": "data_artifact",
                    "record_id": request.artifact_id,
                    "relation": "inspects",
                }
            ],
            exception_error_code="state_inspection_failed",
        ) as state_span:
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
            data_profile_payload = _stable_model_payload(data_profile)
            resolved_data_profile = DataProfile.model_validate(data_profile_payload)
            profile_id = (
                data_profile_payload.get("profile_id")
                if isinstance(data_profile_payload, dict)
                else getattr(data_profile_payload, "profile_id", None)
            )
            if isinstance(profile_id, str) and profile_id:
                state_span.add_output_ref(
                    record_type="data_profile",
                    record_id=profile_id,
                    relation="profiled",
                )
            state_span.add_output_ref(
                record_type="representation_ledger",
                record_id=ledger.ledger_id,
                relation="inspected",
            )
            state_span.set_counter("representation_count", len(ledger.records))
            state_span.succeed()

        with instrumentation.span(
            stage=TraceStage.PLANNING,
            component="capability_workspace_service",
            operation="compose_capability_workflow",
            input_refs=[
                {
                    "record_type": "representation_ledger",
                    "record_id": ledger.ledger_id,
                    "relation": "planning_context",
                }
            ],
            exception_error_code="capability_planning_failed",
        ) as planning_span:
            plan, plan_result, composition = self.composer.compose(
                request=CapabilityCompositionRequest(
                    pack_id=request.pack_id,
                    pack_version=request.pack_version,
                    requirement_id=request.requirement_id,
                    target_representations=request.target_representations,
                    preferred_method_ids=request.preferred_method_ids,
                    parameter_overrides=request.parameter_overrides,
                    enable_doublet_detection=request.enable_doublet_detection,
                    exclude_predicted_doublets=request.exclude_predicted_doublets,
                    doublet_selection_hash=request.doublet_selection_hash,
                    enable_batch_integration=request.enable_batch_integration,
                ),
                ledger=ledger,
                data_profile=resolved_data_profile,
            )
            planning_span.add_output_ref(
                record_type="workflow_plan",
                record_id=plan.plan_id,
                relation="planned",
            )
            planning_span.set_counter("planned_step_count", len(plan.steps))
            if plan_result.blocking_reasons:
                planning_span.blocked(
                    decision_type="capability_plan",
                    outcome="blocked",
                    reason_code=plan_result.blocking_reasons[0],
                    rule_version="capability_composer_v0",
                )
            else:
                planning_span.succeed()
        blockers = sorted(set(gate.blockers + plan_result.blocking_reasons))
        notebook_artifact = {}
        if not blockers:
            with instrumentation.span(
                stage=TraceStage.NOTEBOOK_COMPILE,
                component="capability_workspace_service",
                operation="compile_reviewed_notebook",
                input_refs=[
                    {
                        "record_type": "workflow_plan",
                        "record_id": plan.plan_id,
                        "relation": "compiles",
                    }
                ],
                exception_error_code="notebook_compile_failed",
            ) as notebook_span:
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
                notebook_hash = str(notebook_artifact.get("sha256") or "")
                notebook_span.add_output_ref(
                    record_type="notebook_artifact",
                    record_id=f"notebook:{notebook_hash}",
                    relation="compiled",
                    content_hash=notebook_hash,
                )
                notebook_span.set_counter(
                    "cell_count",
                    int(notebook_artifact.get("cell_count") or 0),
                )
                notebook_span.succeed()
        if blockers:
            status = "blocked"
        elif request.mode == "RUN":
            status = "blocked"
            blockers = ["execution_policy_disabled"]
        else:
            status = "planned"
        return CapabilityWorkspaceResult(
            request_id=request.request_id,
            canonical_trace_id=trace.trace_id,
            pack_id=request.pack_id,
            pack_version=request.pack_version,
            status=status,
            readiness=readiness,
            data_profile=resolved_data_profile,
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


def _trace_request_id(source_id: str) -> str:
    try:
        return trace_correlation_id(source_id, kind=TraceCorrelationKind.REQUEST)
    except (TracePrivacyError, TraceValidationError):
        return f"request-ref:opaque:{uuid.uuid4().hex}"


def _new_stepwise_trace(
    request: CapabilityWorkspaceRequest,
    *,
    trace_request_id: str,
) -> TraceContext:
    try:
        return TraceContext.new_request(
            trace_kind=TraceKind.STEPWISE,
            request_id=trace_request_id,
            parent_trace_id=request.origin_trace_id,
            handoff_id=request.handoff_id,
            parent_request_id=request.parent_request_id,
            original_plan_id=request.original_plan_id,
            principal_ref=request.user_id,
        )
    except (TracePrivacyError, TraceValidationError):
        return TraceContext.new_request(
            trace_kind=TraceKind.STEPWISE,
            request_id=trace_request_id,
        )
