from __future__ import annotations

import hashlib
import json
from typing import Any

from core.research_workspace_models import (
    DataAssetProfile,
    ManagedStepNode,
    ManagedStepRuntimeSnapshot,
    NotebookShadowBundle,
    PreviewRunPreparation,
    PreviewRunResult,
    RepresentativePreviewManifest,
    StepParameterChange,
    StepParameterPatch,
)
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import parameter_hash
from execution.notebook_shadow import scrublet_step_contract


_STEP_META = (
    ("register_data", "Register data", []),
    ("profile_data", "Inspect matrix state", ["register_data"]),
    ("build_preview", "Build representative Preview", ["profile_data"]),
    ("compile_notebook", "Review parameters and code", ["build_preview"]),
    ("approve_execution", "Approve this exact step", ["compile_notebook"]),
    ("run_tool", "Run fixed Scrublet wrapper", ["approve_execution"]),
    ("validate_outputs", "Validate artifacts", ["run_tool"]),
    ("review_result", "Review result and next action", ["validate_outputs"]),
)


class InteractiveStepRuntime:
    """Derive a user-facing step graph without duplicating execution logic."""

    def __init__(self, registry: ToolContractRegistry | None = None) -> None:
        self.registry = registry or ToolContractRegistry()

    def default_parameters(self) -> dict[str, Any]:
        return dict(self.registry.load("Scrublet", "0.2.3").default_parameters)

    def propose_parameter_patch(
        self,
        *,
        notebook: NotebookShadowBundle | None,
        proposed_parameters: dict[str, Any],
    ) -> StepParameterPatch:
        contract = self.registry.load("Scrublet", "0.2.3")
        step = scrublet_step_contract(self.registry)
        base = (
            dict(notebook.parameter_snapshot)
            if notebook is not None and notebook.parameter_snapshot
            else dict(contract.default_parameters)
        )
        proposed = self.registry.validate_parameters(contract, proposed_parameters)
        changes = [
            StepParameterChange(
                parameter_name=name,
                old_value=base.get(name),
                new_value=proposed[name],
            )
            for name in sorted(proposed)
            if base.get(name) != proposed[name]
        ]
        base_hash = parameter_hash(base)
        proposed_hash = parameter_hash(proposed)
        requires_rebuild = base_hash != proposed_hash
        patch_payload = {
            "step_id": step.step_id,
            "base": base_hash,
            "proposed": proposed_hash,
            "changes": [item.model_dump(mode="json") for item in changes],
        }
        patch_id = "step-patch-" + hashlib.sha256(
            json.dumps(
                patch_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:16]
        return StepParameterPatch(
            patch_id=patch_id,
            step_id=step.step_id,
            step_version=step.step_version,
            base_parameter_hash=base_hash,
            proposed_parameter_hash=proposed_hash,
            parameters=proposed,
            changes=changes,
            requires_rebuild=requires_rebuild,
            invalidates=(
                ["notebook", "approval", "result"] if requires_rebuild else []
            ),
        )

    def inspect(
        self,
        *,
        artifact_id: str,
        profile: DataAssetProfile | None,
        preview: RepresentativePreviewManifest | None,
        notebook: NotebookShadowBundle | None,
        approval_id: str | None,
        result: PreviewRunResult | None,
        preparation: PreviewRunPreparation | None = None,
        parameter_patch: StepParameterPatch | None = None,
    ) -> ManagedStepRuntimeSnapshot:
        patch_required = bool(parameter_patch and parameter_patch.requires_rebuild)
        statuses: dict[str, tuple[str, list[str], str]] = {}
        statuses["register_data"] = (
            "CURRENT",
            [],
            "The registered artifact remains in its original local location.",
        )
        statuses["profile_data"] = self._profile_status(profile)
        statuses["build_preview"] = self._preview_status(profile, preview)
        statuses["compile_notebook"] = self._notebook_status(
            preview, notebook, patch_required
        )
        statuses["approve_execution"] = self._approval_status(
            notebook, approval_id, preparation, patch_required
        )
        statuses["run_tool"] = self._run_status(
            notebook, approval_id, result, preparation, patch_required
        )
        statuses["validate_outputs"] = self._validation_status(result)
        statuses["review_result"] = self._review_status(result)

        steps = [
            ManagedStepNode(
                step_id=step_id,
                label=label,
                depends_on=depends_on,
                status=statuses[step_id][0],
                blockers=statuses[step_id][1],
                user_action=statuses[step_id][2],
            )
            for step_id, label, depends_on in _STEP_META
        ]
        current = next(
            (
                item
                for item in steps
                if item.status not in {"CURRENT", "COMPLETED"}
            ),
            None,
        )
        next_action = (
            current.user_action
            if current is not None
            else "Preview validation is complete; review limitations before a full-data RUN."
        )
        return ManagedStepRuntimeSnapshot(
            artifact_id=artifact_id,
            committed_parameter_hash=(notebook.parameter_hash if notebook else None),
            proposed_parameter_hash=(
                parameter_patch.proposed_parameter_hash if parameter_patch else None
            ),
            parameter_patch_required=patch_required,
            steps=steps,
            current_step_id=(current.step_id if current else None),
            next_action=next_action,
        )

    @staticmethod
    def _profile_status(profile):
        if profile is None:
            return "READY", [], "Authorize a read-only profile and inspect the count source."
        if profile.blocking_errors:
            return "BLOCKED", list(profile.blocking_errors), "Resolve the DataProfile blockers."
        return "CURRENT", [], "The backed DataProfile is current."

    @staticmethod
    def _preview_status(profile, preview):
        if profile is None:
            return "WAITING", ["profile_required"], "Build the DataProfile first."
        if profile.preview_capability != "supported":
            return "BLOCKED", list(profile.blocking_errors), "Resolve the count-source blockers."
        if preview is None:
            return "READY", [], "Choose the cell budget and build a representative Preview."
        return "CURRENT", [], "The representative Preview is ready."

    @staticmethod
    def _notebook_status(preview, notebook, patch_required):
        if preview is None:
            return "WAITING", ["preview_required"], "Build the representative Preview first."
        if notebook is None:
            return "READY", [], "Review the contract parameters and compile the Notebook Shadow."
        if patch_required:
            return (
                "STALE",
                ["parameter_patch_not_committed"],
                "Confirm the parameter change and rebuild the governed Notebook.",
            )
        return "CURRENT", [], "The governed Notebook and parameter snapshot are current."

    @staticmethod
    def _approval_status(notebook, approval_id, preparation, patch_required):
        if notebook is None or patch_required:
            return "WAITING", ["current_notebook_required"], "Compile the current Notebook first."
        non_approval = [
            item
            for item in (preparation.blockers if preparation else [])
            if item != "execution_approval_missing"
        ]
        if non_approval:
            return "BLOCKED", non_approval, "Resolve policy and runtime blockers before approval."
        if not approval_id:
            return "READY", [], "Approve this exact artifact, parameter and environment fingerprint."
        return "CURRENT", [], "The plan-specific approval is ready for one request."

    @staticmethod
    def _run_status(notebook, approval_id, result, preparation, patch_required):
        if result is not None:
            if result.status == "validated":
                return "COMPLETED", [], "The fixed wrapper completed."
            if result.status == "blocked":
                return "BLOCKED", list(result.validation_result.failures), "Review the execution blocker."
            return "FAILED", list(result.validation_result.failures), "Review the execution error context."
        if notebook is None or patch_required or not approval_id:
            return "WAITING", ["approval_required"], "Complete the exact approval first."
        if preparation is not None and not preparation.ready:
            return "BLOCKED", list(preparation.blockers), "Resolve the remaining execution blockers."
        return "READY", [], "Run the fixed Scrublet wrapper on this Preview."

    @staticmethod
    def _validation_status(result):
        if result is None:
            return "WAITING", ["execution_result_required"], "Run the tool before validating outputs."
        if result.validation_result.passed:
            return "COMPLETED", [], "Artifact schema, hashes and score constraints passed."
        return "FAILED", list(result.validation_result.failures), "Inspect ValidationResult and error context."

    @staticmethod
    def _review_status(result):
        if result is None or not result.validation_result.passed:
            return "WAITING", ["validated_result_required"], "A validated result is required for interpretation."
        return "COMPLETED", [], "Review metrics, plot, limitations and the next governed action."
