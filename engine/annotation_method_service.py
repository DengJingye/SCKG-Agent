from __future__ import annotations

import hashlib
import json

from core.annotation_method_models import (
    AnnotationCandidate,
    AnnotationCandidateStatus,
    AnnotationMethodFamily,
    AnnotationMethodFamilyResult,
    HumanAnnotationConfirmation,
    MarkerEvidenceCandidate,
)
from core.capability_pack_registry import CapabilityPackRegistry
from core.execution_models import AnnotationDataProfile
from core.representation_models import RepresentationRecord
from core.tool_contract_registry import ToolContractRegistry


class AnnotationMethodFamilyService:
    """Govern annotation candidates without treating a model response as a label."""

    def __init__(
        self,
        *,
        pack_registry: CapabilityPackRegistry | None = None,
        tool_registry: ToolContractRegistry | None = None,
    ) -> None:
        self.pack_registry = pack_registry or CapabilityPackRegistry()
        self.tool_registry = tool_registry or ToolContractRegistry()

    def marker_evidence_candidates(
        self,
        *,
        marker_record: RepresentationRecord | None,
        evidence_candidates: list[MarkerEvidenceCandidate],
    ) -> AnnotationMethodFamilyResult:
        blockers: list[str] = []
        if (
            marker_record is None
            or marker_record.representation_id != "marker_result"
            or not marker_record.validated
            or marker_record.status != "current"
        ):
            blockers.append("validated_marker_result_required")
        if not evidence_candidates:
            blockers.append("marker_evidence_candidates_missing")

        candidates = [
            AnnotationCandidate(
                cluster_id=item.cluster_id,
                candidate_label=item.candidate_label,
                method_family=AnnotationMethodFamily.MARKER_EVIDENCE,
                status=(
                    AnnotationCandidateStatus.CONFLICTING
                    if item.conflicting_labels
                    else item.status
                ),
                evidence_source_ids=item.evidence_source_ids,
                limitations=(
                    ["conflicting_marker_evidence_requires_human_resolution"]
                    if item.conflicting_labels
                    else ["marker_evidence_unresolved_requires_human_review"]
                    if item.status == AnnotationCandidateStatus.UNKNOWN
                    else []
                ),
            )
            for item in evidence_candidates
        ]
        candidate_hash = _candidate_hash(candidates) if candidates else None
        return AnnotationMethodFamilyResult(
            result_id=f"annotation-marker-{(candidate_hash or 'blocked')[:16]}",
            method_family=AnnotationMethodFamily.MARKER_EVIDENCE,
            method_binding_id="scanpy_core.marker_evidence_annotation",
            candidates=candidates,
            candidate_set_hash=candidate_hash,
            eligible_for_confirmation=not blockers and bool(candidates),
            blocking_reasons=sorted(set(blockers)),
            warnings=sorted(
                {
                    limitation
                    for item in candidates
                    for limitation in item.limitations
                }
            ),
        )

    def reference_candidates(
        self,
        *,
        profile: AnnotationDataProfile,
        binding_id: str,
    ) -> AnnotationMethodFamilyResult:
        manifest = self.pack_registry.load("scanpy_core", "1.0.0")
        binding = next(
            (
                item
                for item in manifest.implementation_bindings
                if item.binding_id == binding_id
                and item.method_id == "scanpy_core.reference_annotation"
            ),
            None,
        )
        blockers = list(profile.blocking_errors)
        if binding is None:
            blockers.append("reference_annotation_binding_unknown")
            contract_ref = None
        else:
            contract_ref = binding.tool_contract_ref
            tool_name, version = contract_ref.split(":", 1)
            contract = self.tool_registry.load(tool_name, version)
            planning = self.tool_registry.planning_gate(contract, data_profile=profile)
            if not planning.allowed:
                blockers.extend(planning.reasons)
            execution = self.tool_registry.execution_gate(contract)
            if not execution.allowed or not binding.execution_eligible:
                blockers.append("reference_annotation_binding_not_qualified")

        return AnnotationMethodFamilyResult(
            result_id=f"annotation-reference-{_digest([binding_id, profile.profile_id])[:16]}",
            method_family=AnnotationMethodFamily.REFERENCE_BASED,
            method_binding_id=binding_id,
            candidates=[],
            eligible_for_confirmation=False,
            execution_eligible=False,
            blocking_reasons=sorted(set(blockers)),
            warnings=(
                [f"planning_binding:{contract_ref}"] if contract_ref else []
            ),
        )

    def confirm(
        self,
        *,
        result: AnnotationMethodFamilyResult,
        confirmed_labels: dict[str, str],
        reviewer_id: str,
    ) -> HumanAnnotationConfirmation:
        if not result.eligible_for_confirmation or not result.candidate_set_hash:
            raise ValueError("annotation candidate set is not eligible for confirmation")
        clusters = {item.cluster_id for item in result.candidates}
        if set(confirmed_labels) != clusters:
            raise ValueError("confirmed labels must cover the candidate cluster set exactly")
        if any(not str(value).strip() for value in confirmed_labels.values()):
            raise ValueError("confirmed labels cannot be empty")
        digest = _digest(
            {
                "candidate_set_hash": result.candidate_set_hash,
                "labels": confirmed_labels,
                "reviewer_id": reviewer_id,
            }
        )
        return HumanAnnotationConfirmation(
            confirmation_id=f"annotation-confirmation-{digest[:16]}",
            candidate_set_hash=result.candidate_set_hash,
            confirmed_labels=confirmed_labels,
            reviewer_id=reviewer_id,
        )


def _candidate_hash(candidates: list[AnnotationCandidate]) -> str:
    return _digest([item.model_dump(mode="json") for item in candidates])


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
