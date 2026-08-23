import json

from engine.evidence_discovery_index import EvidenceChunk, chunk_to_dict
from engine.hybrid_retrieval import HybridRetrievalService
from eval.retrieval_evaluation import PROFILES, build_gold_cases, evaluate_profile


def test_gold_builder_creates_fixed_96_case_split():
    chunks = []
    for tool in (
        "Scrublet", "scDblFinder", "Harmony", "Scanorama", "Seurat", "Scanpy",
        "scvi-tools", "CellTypist", "SingleR", "cell2location", "scVelo",
        "CellRank", "MOFA2", "moscot", "tradeSeq", "DoubletFinder",
    ):
        chunks.append(
            EvidenceChunk(
                chunk_id=f"source:{tool}",
                evidence_id=f"source:{tool}",
                source_kind="source_document",
                source_table="sources.jsonl",
                source_record_id=f"source:{tool}",
                source_id=f"source:{tool}",
                source_document_id=f"source:{tool}",
                source_span="README paragraph 1",
                tool_name=tool,
                tool_names=[tool],
                claim_type="general",
                chunk_text=f"{tool} source-bound documentation.",
                source_bound=True,
                retrieval_status="retrieval_only",
            )
        )

    cases = build_gold_cases(chunks)

    assert len(cases) == 96
    assert {case.split for case in cases} == {"development", "evaluation"}
    assert sum(case.must_block for case in cases) == 8
    assert {case.category for case in cases} >= {
        "tool_discovery", "input_requirement", "parameter", "output",
        "failure_mode", "metric", "workflow_relation", "ambiguous", "hard_negative",
    }


def test_dense_profile_is_not_run_when_local_pack_is_missing(tmp_path):
    index_dir = tmp_path / "indexes"
    index_dir.mkdir()
    chunk = EvidenceChunk(
        chunk_id="source:scrublet",
        evidence_id="source:scrublet",
        source_kind="source_document",
        source_table="sources.jsonl",
        source_record_id="source:scrublet",
        source_id="source:scrublet",
        source_document_id="source:scrublet",
        source_span="README paragraph 1",
        tool_name="Scrublet",
        tool_names=["Scrublet"],
        chunk_text="Scrublet requires raw counts and returns doublet scores.",
        source_bound=True,
        retrieval_status="retrieval_only",
    )
    (index_dir / "chunks.jsonl").write_text(json.dumps(chunk_to_dict(chunk)) + "\n")
    (index_dir / "catalog.jsonl").write_text("")
    (index_dir / "manifest.json").write_text(json.dumps({"build_id": "test"}))
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "chunks.jsonl",
        catalog_chunks_path=index_dir / "catalog.jsonl",
        fts_index_path=index_dir / "fts.sqlite",
        index_manifest_path=index_dir / "manifest.json",
        coverage_path=index_dir / "coverage.json",
        dense_matrix_path=index_dir / "missing.npy",
        dense_metadata_path=index_dir / "missing.json",
        graph_dir=tmp_path / "missing",
    )
    cases = build_gold_cases([chunk])
    dense = next(profile for profile in PROFILES if profile.profile_id == "dense")

    summary, _ = evaluate_profile(service, cases, dense)

    assert summary.status == "not_run"
    assert "bge-m3" in summary.failures[0]
