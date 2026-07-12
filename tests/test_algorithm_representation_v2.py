from engine.algorithm_representation_v2 import (
    build_representations,
    score_representation_for_migration,
)
from engine.evidence_discovery_index import source_manifest_chunks


def test_source_manifest_chunk_preserves_source_metadata(tmp_path):
    text_path = tmp_path / "source.txt"
    text_path.write_text(
        "This method uses a variational autoencoder latent model for batch-aware single-cell integration. "
        "The paragraph is long enough to become a chunk and remains discovery only.",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.tsv"
    manifest.write_text(
        "source_id\tevidence_kind\ttool_name\trecord_id\tsource_title\tsource_url\tdoi_or_pmid\t"
        "preferred_source_type\tlocal_text_path\tfetch_status\tfetch_priority\tnotes\n"
        f"SRC1\tpublication\tscvi-tools\tREC1\tTitle\thttps://example.org\t10.1/x\tpdf_text\t{text_path}\t"
        "pdf_text_extracted\t1\tDiscovery only\n",
        encoding="utf-8",
    )

    chunks = source_manifest_chunks(manifest)

    assert chunks
    assert chunks[0].source_id == "SRC1"
    assert chunks[0].source_type == "pdf_text"
    assert chunks[0].source_span == "paragraph:1"
    assert chunks[0].claim_boundary.startswith("Evidence discovery chunk only")


def test_tool_representation_v2_marks_missing_source_as_low_coverage():
    reps = build_representations(
        catalog_rows=[
            {
                "Tool": "NoSourceTool",
                "Code": "https://example.org/no-source",
                "Platform": "Python",
                "License": "MIT",
            }
        ],
        chunks=[],
        profile_rows=[],
        legacy_audit_rows=[
            {
                "tool_name": "NoSourceTool",
                "has_embedding": "true",
                "embedding_dim": "1024",
                "vector_quality_flag": "llm_profile_embedding_review_required",
            }
        ],
    )

    rep = reps[0]

    assert rep.confidence["review_status"] == "low_source_coverage"
    assert "low_source_coverage" in rep.confidence["quality_flags"]
    assert rep.migration_policy["recommendation_grade"] is False
    assert rep.legacy_embedding["forbidden_use"] == [
        "recommendation",
        "formal_evidence_promotion",
        "migration_validity_claim",
    ]


def test_representation_migration_score_penalizes_low_source_coverage():
    reps = build_representations(
        catalog_rows=[{"Tool": "NoSourceTool", "Code": "", "Platform": "Python", "License": "MIT"}],
        chunks=[],
        profile_rows=[
            {
                "tool_name": "NoSourceTool",
                "algorithm_family": "variational autoencoder",
                "supported_task": "Data Integration",
                "supported_modality": "scRNA-seq",
                "input_object": "AnnData",
                "output_object": "latent embedding",
                "transferable_mechanism": "VAE latent model",
            }
        ],
        legacy_audit_rows=[],
    )

    score = score_representation_for_migration(
        reps[0],
        {
            "task": "Data Integration",
            "modality": "scRNA-seq",
            "output_goal": "VAE latent embedding batch integration",
        },
    )

    assert score["source_coverage_score"] == 0.0
    assert "low_source_coverage" in score["quality_flags"]
    assert score["known_blocker_penalty"] > 0
    assert "Exploratory migration signal only" in score["claim_boundary"]
