from __future__ import annotations

import pytest

from core.annotation_method_models import (
    AnnotationCandidateStatus,
    MarkerEvidenceCandidate,
)
from core.execution_models import AnnotationDataProfile
from core.representation_models import RepresentationRecord
from engine.annotation_method_service import AnnotationMethodFamilyService
from engine.method_graph import MethodGraphBuilder, MethodGraphQuery


CELL_HASH = "c" * 64
GENE_HASH = "g" * 64
FILE_HASH = "f" * 64
REFERENCE_HASH = "r" * 64


def _marker_record(*, validated: bool = True) -> RepresentationRecord:
    return RepresentationRecord(
        representation_record_id="rep:markers",
        representation_id="marker_result",
        schema_version="1.0",
        value_state="table",
        slot="uns/rank_genes_groups",
        provenance=["full_gene_log1p_source"],
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH,
        validated=validated,
    )


def _profile(*, blockers: list[str] | None = None) -> AnnotationDataProfile:
    return AnnotationDataProfile(
        profile_id="annotation-profile",
        file_path_redacted="<registered-artifact>",
        file_hash=FILE_HASH,
        n_cells=100,
        n_genes=500,
        expression_source="X",
        expression_state="log1p_normalized",
        normalization_target="ready_log1p_10000",
        gene_identifier_type="gene_symbol",
        species="human",
        reference_id="immune-reference",
        reference_digest=REFERENCE_HASH,
        reference_gene_count=500,
        overlapping_gene_count=450,
        gene_overlap_rate=0.9,
        blocking_errors=blockers or [],
    )


def test_marker_annotation_requires_validated_markers_and_bound_evidence():
    service = AnnotationMethodFamilyService()

    missing_marker = service.marker_evidence_candidates(
        marker_record=None,
        evidence_candidates=[],
    )
    unbound_model_label = service.marker_evidence_candidates(
        marker_record=_marker_record(),
        evidence_candidates=[],
    )

    assert missing_marker.eligible_for_confirmation is False
    assert "validated_marker_result_required" in missing_marker.blocking_reasons
    assert "marker_evidence_candidates_missing" in unbound_model_label.blocking_reasons
    assert unbound_model_label.execution_request_count == 0


def test_marker_evidence_produces_candidates_then_requires_human_confirmation():
    service = AnnotationMethodFamilyService()
    result = service.marker_evidence_candidates(
        marker_record=_marker_record(),
        evidence_candidates=[
            MarkerEvidenceCandidate(
                cluster_id="0",
                candidate_label="CD4 T cell",
                marker_genes=["IL7R", "LTB"],
                evidence_source_ids=["marker-atlas:human-pbmc-v1"],
            ),
            MarkerEvidenceCandidate(
                cluster_id="1",
                candidate_label="Monocyte",
                marker_genes=["LYZ", "S100A8"],
                evidence_source_ids=["marker-atlas:human-pbmc-v1"],
                conflicting_labels=["Dendritic cell"],
            ),
        ],
    )

    assert result.eligible_for_confirmation is True
    assert result.execution_eligible is False
    assert result.execution_request_count == 0
    assert result.candidates[1].status == AnnotationCandidateStatus.CONFLICTING
    assert result.produces_representation_id == "annotation_candidates"

    confirmation = service.confirm(
        result=result,
        confirmed_labels={"0": "CD4 T cell", "1": "Monocyte"},
        reviewer_id="maintainer",
    )
    assert confirmation.produces_representation_id == "confirmed_annotation"
    assert confirmation.source == "explicit_human_review"


def test_human_confirmation_rejects_partial_cluster_coverage():
    service = AnnotationMethodFamilyService()
    result = service.marker_evidence_candidates(
        marker_record=_marker_record(),
        evidence_candidates=[
            MarkerEvidenceCandidate(
                cluster_id="0",
                candidate_label="B cell",
                marker_genes=["MS4A1"],
                evidence_source_ids=["marker-atlas:human-pbmc-v1"],
            )
        ],
    )

    with pytest.raises(ValueError, match="cover the candidate cluster set"):
        service.confirm(
            result=result,
            confirmed_labels={},
            reviewer_id="maintainer",
        )


@pytest.mark.parametrize(
    "blocker",
    [
        "reference_gene_overlap_insufficient",
        "reference_species_mismatch",
        "reference_gene_identifier_mismatch",
    ],
)
def test_reference_annotation_preserves_scientific_blockers(blocker):
    result = AnnotationMethodFamilyService().reference_candidates(
        profile=_profile(blockers=[blocker]),
        binding_id="celltypist.reference_annotation",
    )

    assert blocker in result.blocking_reasons
    assert "reference_annotation_binding_not_qualified" in result.blocking_reasons
    assert result.execution_request_count == 0
    assert result.execution_eligible is False


def test_celltypist_and_singler_are_planning_bindings_not_scanpy_api_bindings(tmp_path):
    graph_dir = tmp_path / "graph"
    manifest = MethodGraphBuilder().build(graph_dir)
    graph = MethodGraphQuery(graph_dir)
    edges = [
        edge
        for edge in graph.edges
        if edge.source_id in {"tool:celltypist", "tool:singler"}
        and edge.target_id == "method:scanpy_core.reference_annotation"
    ]

    assert manifest.quality_path == "quality.json"
    assert len(edges) == 2
    assert all(edge.properties["binding_status"] == "planning_only" for edge in edges)
    assert all(edge.properties["execution_eligible"] is False for edge in edges)
