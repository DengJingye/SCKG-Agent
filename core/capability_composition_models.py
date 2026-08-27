from __future__ import annotations

from pydantic import Field

from core.execution_models import StrictModel


class CapabilityCompositionRequest(StrictModel):
    pack_id: str
    pack_version: str
    requirement_id: str
    target_representations: list[str] = Field(min_length=1)
    preferred_method_ids: list[str] = Field(default_factory=list)
    enable_doublet_detection: bool = False
    exclude_predicted_doublets: bool = False
    doublet_selection_hash: str | None = Field(default=None, min_length=64, max_length=64)
    enable_batch_integration: bool = False


class CapabilityCompositionResult(StrictModel):
    selected_action_bundle_refs: list[str] = Field(default_factory=list)
    selected_method_ids: list[str] = Field(default_factory=list)
    original_cell_index_hash: str | None = None
    resulting_cell_index_hash: str | None = None
    cell_set_changed: bool = False
    stale_representation_ids: list[str] = Field(default_factory=list)
    invalidated_approval: bool = False
    confirmation_required: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)
