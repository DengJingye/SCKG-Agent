from __future__ import annotations

import hashlib

from core.capability_composition_models import (
    CapabilityCompositionRequest,
    CapabilityCompositionResult,
)
from core.capability_pack_registry import CapabilityPackRegistry
from core.representation_models import RepresentationLedger
from engine.capability_planner import CapabilityPlanCompiler


class CapabilityWorkflowComposer:
    def __init__(
        self,
        *,
        registry: CapabilityPackRegistry | None = None,
        planner: CapabilityPlanCompiler | None = None,
    ) -> None:
        self.registry = registry or CapabilityPackRegistry()
        self.planner = planner or CapabilityPlanCompiler(self.registry)

    def compose(
        self,
        *,
        request: CapabilityCompositionRequest,
        ledger: RepresentationLedger,
    ) -> tuple:
        manifest = self.registry.load(request.pack_id, request.pack_version)
        bindings = {item.binding_id: item for item in manifest.composed_actions}
        preferred: list[str] = list(request.preferred_method_ids)
        targets = list(request.target_representations)
        selected_actions: list[str] = []
        blockers: list[str] = []
        confirmation_required = False
        original_hash = ledger.cell_index_hash
        resulting_hash = original_hash
        stale: list[str] = []
        changed = bool(request.exclude_predicted_doublets and request.doublet_selection_hash)
        effective_ledger = ledger

        if changed:
            resulting_hash = hashlib.sha256(
                f"{original_hash}:{request.doublet_selection_hash}".encode("utf-8")
            ).hexdigest()
            stale_scope = {
                "library_size_normalized",
                "log1p_normalized",
                "hvg_selection",
                "scaled_hvg",
                "pca",
                "integrated_representation",
                "neighbor_graph",
                "umap",
                "cluster_labels",
                "marker_result",
                "annotation_candidates",
                "confirmed_annotation",
            }
            stale = sorted(
                item.representation_id
                for item in ledger.records
                if item.representation_id in stale_scope and item.status == "current"
            )
            effective_ledger = ledger.model_copy(
                update={
                    "records": [
                        item.model_copy(
                            update={
                                "status": "stale",
                                "stale_reasons": ["doublet_exclusion_cell_hash_changed"],
                            }
                        )
                        if item.representation_id in stale_scope
                        and item.status == "current"
                        else item
                        for item in ledger.records
                    ]
                }
            )

        if request.enable_doublet_detection:
            binding = bindings.get("scanpy_core.doublet_detection")
            if binding is None:
                blockers.append("doublet_composition_not_registered")
            else:
                selected_actions.append(binding.action_bundle_ref)
                targets.append("doublet_scores_and_calls")
                if request.exclude_predicted_doublets:
                    confirmation_required = binding.explicit_confirmation_required
                    targets.append("library_size_normalized")
                    if not request.doublet_selection_hash:
                        blockers.append("doublet_exclusion_requires_confirmed_selection_hash")
                    preferred.extend(
                        ["scanpy_core.normalize_after_doublet_exclusion", *binding.method_ids]
                    )
        if request.enable_batch_integration:
            binding = bindings.get("scanpy_core.batch_integration")
            if binding is None:
                blockers.append("batch_integration_composition_not_registered")
            else:
                selected_actions.append(binding.action_bundle_ref)
                preferred.extend(["scanpy_core.neighbors_integrated", *binding.method_ids])
                if not ledger.metadata.get("batch_key"):
                    blockers.append("batch_integration_requires_batch_key")
                if int(ledger.metadata.get("batch_count") or 0) < 2:
                    blockers.append("batch_integration_requires_at_least_two_batches")

        plan, result = self.planner.compile(
            pack_id=request.pack_id,
            pack_version=request.pack_version,
            ledger=effective_ledger,
            target_representations=sorted(set(targets)),
            requirement_id=request.requirement_id,
            options={"preferred_method_ids": preferred},
        )
        blockers.extend(result.blocking_reasons)
        if request.enable_doublet_detection and "scanpy_core.doublet_detection_action" not in result.planned_method_ids:
            blockers.append("doublet_action_not_composed_into_plan")
        if request.exclude_predicted_doublets and "scanpy_core.confirm_doublet_exclusion" not in result.planned_method_ids:
            blockers.append("doublet_exclusion_not_composed_into_plan")
        if request.enable_batch_integration and "scanpy_core.batch_integration_action" not in result.planned_method_ids:
            blockers.append("batch_integration_not_composed_into_plan")
        if blockers and not result.blocked:
            plan = plan.model_copy(
                update={
                    "blocking_conditions": sorted(set(blockers)),
                    "plan_status": "blocked",
                }
            )
            result = result.model_copy(
                update={"blocked": True, "blocking_reasons": sorted(set(blockers))}
            )
        return plan, result, CapabilityCompositionResult(
            selected_action_bundle_refs=sorted(set(selected_actions)),
            selected_method_ids=result.planned_method_ids,
            original_cell_index_hash=original_hash,
            resulting_cell_index_hash=resulting_hash,
            cell_set_changed=changed,
            stale_representation_ids=stale,
            invalidated_approval=changed,
            confirmation_required=confirmation_required,
            blocking_reasons=sorted(set(blockers)),
        )
