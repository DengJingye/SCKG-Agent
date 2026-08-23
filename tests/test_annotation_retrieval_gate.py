from __future__ import annotations

from core.settings import PROJECT_ROOT
from engine.evidence_discovery_index import load_chunks
from eval.retrieval_evaluation import build_annotation_gold_cases


def test_annotation_gate_has_24_source_and_hard_negative_cases() -> None:
    chunks = load_chunks(PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl")
    cases = build_annotation_gold_cases(chunks)

    assert len(cases) == 24
    assert sum(case.must_block for case in cases) == 4
    assert {tool for case in cases for tool in case.expected_tool_names} == {
        "CellTypist",
        "SingleR",
    }
    assert all(case.relevant_chunk_ids for case in cases if not case.must_block)


def test_wrong_bbad418_source_is_not_retrievable() -> None:
    chunks = load_chunks(PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl")

    assert not any(
        "bbad418" in " ".join(
            (
                chunk.doi,
                chunk.source_url,
                chunk.title,
                chunk.chunk_text,
            )
        ).casefold()
        for chunk in chunks
    )
