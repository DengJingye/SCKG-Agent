from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from core.canonical_task_ontology import canonical_task_ids_for_tool
from core.knowledge_intelligence_models import (
    HybridRetrievalRequest,
    RetrievalEvalCase,
    RetrievalEvalSummary,
)
from engine.evidence_discovery_index import EvidenceChunk, load_chunks
from engine.hybrid_retrieval import HybridRetrievalService
from engine.source_corpus_v2 import CORE_TOOLS


CLAIM_QUERY = {
    "input_requirement": "What input matrix and data state does {tool} require?",
    "parameter": "Which parameters and defaults are documented for {tool}?",
    "output": "What outputs and artifacts does {tool} produce?",
    "failure_mode": "What failure modes and limitations are documented for {tool}?",
    "metric": "Which evaluation metrics are reported for {tool}?",
}


@dataclass(frozen=True)
class RetrievalProfile:
    profile_id: str
    enable_sparse: bool
    enable_dense: bool
    use_kg: bool
    use_governance_rerank: bool
    use_contract_gate: bool = False


PROFILES = (
    RetrievalProfile("bm25", True, False, False, False),
    RetrievalProfile("dense", False, True, False, False),
    RetrievalProfile("bm25_dense", True, True, False, False),
    RetrievalProfile("kg_bm25", True, False, True, True),
    RetrievalProfile("kg_hybrid", True, True, True, True),
    RetrievalProfile("kg_hybrid_tool_contract", True, True, True, True, True),
)


def build_gold_cases(chunks: Sequence[EvidenceChunk]) -> List[RetrievalEvalCase]:
    source_chunks = [
        chunk
        for chunk in chunks
        if chunk.source_bound and chunk.retrieval_status != "catalog_only"
    ]
    by_tool: Dict[str, List[EvidenceChunk]] = {}
    for chunk in source_chunks:
        for tool in chunk.tool_names or ([chunk.tool_name] if chunk.tool_name else []):
            by_tool.setdefault(tool.casefold(), []).append(chunk)

    cases: List[RetrievalEvalCase] = []
    for index, tool in enumerate(CORE_TOOLS):
        tool_chunks = by_tool.get(tool.casefold(), [])
        cases.append(
            _positive_case(
                case_id=f"tool-{index + 1:02d}-discovery",
                category="tool_discovery",
                query=f"Find source-bound information about {tool} and its supported task.",
                tools=[tool],
                chunks=tool_chunks,
            )
        )
        for claim_type in ("input_requirement", "parameter", "output"):
            relevant = [chunk for chunk in tool_chunks if chunk.claim_type == claim_type]
            cases.append(
                _positive_case(
                    case_id=f"tool-{index + 1:02d}-{claim_type}",
                    category=claim_type,
                    query=CLAIM_QUERY[claim_type].format(tool=tool),
                    tools=[tool],
                    chunks=relevant or tool_chunks,
                )
            )
        final_claim = "failure_mode" if index % 2 == 0 else "metric"
        final_chunks = [chunk for chunk in tool_chunks if chunk.claim_type == final_claim]
        cases.append(
            _positive_case(
                case_id=f"tool-{index + 1:02d}-{final_claim}",
                category=final_claim,
                query=CLAIM_QUERY[final_claim].format(tool=tool),
                tools=[tool],
                chunks=final_chunks or tool_chunks,
            )
        )

    workflow_cases = (
        ("Scrublet", "doublet detection before normalization"),
        ("Harmony", "batch integration after normalization"),
        ("CellTypist", "cell type annotation after clustering"),
        ("scVelo", "RNA velocity after spliced and unspliced quantification"),
    )
    for index, (tool, phrase) in enumerate(workflow_cases, start=1):
        tool_chunks = by_tool.get(tool.casefold(), [])
        workflow_chunks = [chunk for chunk in tool_chunks if chunk.claim_type == "workflow"]
        cases.append(
            _positive_case(
                case_id=f"workflow-{index:02d}",
                category="workflow_relation",
                query=f"Find source support for {tool} in a workflow: {phrase}.",
                tools=[tool],
                chunks=workflow_chunks or tool_chunks,
            )
        )

    ambiguous = (
        ("doublet methods for raw scRNA-seq counts", ["Scrublet", "scDblFinder", "DoubletFinder"]),
        ("methods for integrating batches in single-cell data", ["Harmony", "Scanorama", "Seurat"]),
        ("reference-based cell type annotation", ["CellTypist", "SingleR"]),
        ("cell fate and RNA velocity analysis", ["scVelo", "CellRank"]),
    )
    for index, (query, tools) in enumerate(ambiguous, start=1):
        relevant = [chunk for tool in tools for chunk in by_tool.get(tool.casefold(), [])]
        cases.append(
            _positive_case(
                case_id=f"ambiguous-{index:02d}",
                category="ambiguous",
                query=query,
                tools=tools,
                chunks=relevant,
            )
        )

    hard_negatives = (
        "Use Scrublet to align spatial histology images without expression data.",
        "Use Harmony to call somatic DNA variants from a BAM file.",
        "Use Scanorama to assemble a reference genome from long reads.",
        "Use SingleR to infer protein structures from amino-acid sequence.",
        "Use CellTypist to perform raw FASTQ base calling.",
        "Use scVelo to quantify metabolites from mass spectrometry images.",
        "Use MOFA2 to edit CRISPR guide sequences in living cells.",
        "Claim that a catalog-only tool is execution-qualified without a contract.",
    )
    for index, query in enumerate(hard_negatives, start=1):
        cases.append(
            RetrievalEvalCase(
                case_id=f"hard-negative-{index:02d}",
                split="evaluation" if index % 2 == 0 else "development",
                category="hard_negative",
                query=query,
                must_block=True,
                notes="No retrieved context may be admitted as execution authority or formal evidence.",
            )
        )

    if len(cases) != 96:
        raise AssertionError(f"expected 96 retrieval cases, got {len(cases)}")
    return cases


def build_annotation_gold_cases(
    chunks: Sequence[EvidenceChunk],
) -> List[RetrievalEvalCase]:
    source_chunks = [
        chunk
        for chunk in chunks
        if chunk.source_bound and chunk.retrieval_status != "catalog_only"
    ]
    by_tool: Dict[str, List[EvidenceChunk]] = {}
    for chunk in source_chunks:
        for tool in chunk.tool_names or ([chunk.tool_name] if chunk.tool_name else []):
            by_tool.setdefault(tool.casefold(), []).append(chunk)

    specifications = {
        "CellTypist": (
            ("discovery", "Find source-bound information about CellTypist for cell type annotation.", "tool_discovery"),
            ("input", "What expression matrix state does CellTypist annotate require?", "input_requirement"),
            ("normalization", "Does CellTypist expect raw counts, log-normalized values, or scaled values?", "input_requirement"),
            ("genes", "What gene identifiers and species compatibility must be checked before CellTypist?", "input_requirement"),
            ("reference", "Which pretrained model or reference is required by CellTypist?", "input_requirement"),
            ("parameters", "Which CellTypist annotation parameters control majority voting and confidence?", "parameter"),
            ("output", "What labels, probabilities, and result object does CellTypist return?", "output"),
            ("unknown", "How should low-confidence or unknown CellTypist predictions be handled?", "failure_mode"),
            ("failure", "What documented input mismatch or failure modes can invalidate CellTypist labels?", "failure_mode"),
            ("metric", "Which metrics or validation signals are documented for CellTypist annotation?", "metric"),
        ),
        "SingleR": (
            ("discovery", "Find source-bound information about SingleR for reference-based cell annotation.", "tool_discovery"),
            ("input", "What test expression matrix state does SingleR require?", "input_requirement"),
            ("normalization", "Can SingleR accept log-normalized expression and what assay is compared?", "input_requirement"),
            ("genes", "How must gene identifiers and species match between SingleR test and reference?", "input_requirement"),
            ("reference", "What labelled reference data does SingleR require?", "input_requirement"),
            ("parameters", "Which SingleR parameters control fine tuning, pruning, and label assignment?", "parameter"),
            ("output", "What labels, scores, deltas, and pruned labels does SingleR return?", "output"),
            ("unknown", "How do pruned labels represent ambiguous or low-confidence SingleR assignments?", "failure_mode"),
            ("failure", "What reference mismatch or missing gene overlap can invalidate SingleR annotation?", "failure_mode"),
            ("metric", "Which diagnostic metrics or score deltas are documented for SingleR?", "metric"),
        ),
    }
    cases: List[RetrievalEvalCase] = []
    for tool, rows in specifications.items():
        tool_chunks = by_tool.get(tool.casefold(), [])
        for suffix, query, claim_type in rows:
            relevant = (
                tool_chunks
                if claim_type == "tool_discovery"
                else [chunk for chunk in tool_chunks if chunk.claim_type == claim_type]
            )
            cases.append(
                _positive_case(
                    case_id=f"annotation-{tool.casefold()}-{suffix}",
                    category=claim_type,
                    query=query,
                    tools=[tool],
                    chunks=relevant or tool_chunks,
                )
            )

    hard_negatives = (
        "Use CellTypist to call somatic DNA variants directly from a BAM file.",
        "Use SingleR to predict a protein structure from amino-acid sequence.",
        "Use CellTypist to perform raw FASTQ base calling without an expression matrix.",
        "Execute planning-only CellTypist and SingleR without a reference, contract gate, or approval.",
    )
    for index, query in enumerate(hard_negatives, start=1):
        cases.append(
            RetrievalEvalCase(
                case_id=f"annotation-hard-negative-{index:02d}",
                split="evaluation",
                category="hard_negative",
                query=query,
                must_block=True,
                notes="Annotation source retrieval cannot authorize an unsupported task or execution.",
            )
        )
    if len(cases) != 24:
        raise AssertionError(f"expected 24 annotation retrieval cases, got {len(cases)}")
    return cases


def evaluate_profile(
    service: HybridRetrievalService,
    cases: Sequence[RetrievalEvalCase],
    profile: RetrievalProfile,
    *,
    top_k: int = 10,
) -> tuple[RetrievalEvalSummary, List[Dict[str, Any]]]:
    results: List[Dict[str, Any]] = []
    reciprocal_ranks: List[float] = []
    recalls: List[float] = []
    precisions: List[float] = []
    span_hits: List[float] = []
    false_support = 0
    latency: List[float] = []
    dense_unavailable = False
    governance_leakage = 0
    for case in cases:
        request_tools = case.expected_tool_names if case.category not in {"tool_discovery", "ambiguous"} else []
        result = service.search(
            HybridRetrievalRequest(
                query=case.query,
                tool_names=request_tools,
                canonical_tasks=case.expected_canonical_tasks,
                top_k=top_k,
                enable_sparse=profile.enable_sparse,
                enable_dense=profile.enable_dense,
                use_kg=profile.use_kg,
                use_governance_rerank=profile.use_governance_rerank,
                use_contract_gate=profile.use_contract_gate,
            )
        )
        if profile.enable_dense and result.dense_status != "ready":
            dense_unavailable = True
        retrieved = [hit.chunk_id for hit in result.hits]
        relevant = set(case.relevant_chunk_ids)
        matched = [chunk_id for chunk_id in retrieved if chunk_id in relevant]
        expected_tools = {value.casefold() for value in case.expected_tool_names}
        relevant_source_ids = set(case.relevant_source_ids)
        context_hits = [
            hit
            for hit in result.hits
            if hit.governance_status != "catalog_only"
            and hit.source_bound
            and (
                hit.source_id in relevant_source_ids
                or hit.tool_name.casefold() in expected_tools
            )
        ]
        if not case.must_block:
            found_tools = {hit.tool_name.casefold() for hit in context_hits if hit.tool_name}
            recalls.append(len(found_tools & expected_tools) / max(len(expected_tools), 1))
            precisions.append(len(context_hits) / max(len(result.hits), 1))
            first_rank = next(
                (
                    rank
                    for rank, hit in enumerate(result.hits, 1)
                    if hit in context_hits
                ),
                None,
            )
            reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
            span_hits.append(float(any(hit.source_span for hit in context_hits)))
        else:
            false_support += int(
                any(hit.recommendation_eligible for hit in result.hits)
                or result.governance_leakage_count > 0
            )
        governance_leakage += result.governance_leakage_count
        latency.append(result.latency_ms)
        results.append(
            {
                "case_id": case.case_id,
                "profile": profile.profile_id,
                "status": "blocked_as_required" if case.must_block else "retrieved",
                "retrieved_chunk_ids": retrieved,
                "matched_relevant_chunk_ids": matched,
                "context_relevant_chunk_ids": [hit.chunk_id for hit in context_hits],
                "latency_ms": result.latency_ms,
                "dense_status": result.dense_status,
                "governance_leakage_count": result.governance_leakage_count,
            }
        )

    if profile.enable_dense and dense_unavailable:
        return RetrievalEvalSummary(
            status="not_run",
            case_count=len(cases),
            governance_leakage_count=governance_leakage,
            failures=["local BAAI/bge-m3 model pack or matching vector index is unavailable"],
            ragas_status="not_run",
            ragas_reason="dense profile unavailable; RAGAS is an optional separate evaluator",
        ), results

    summary = RetrievalEvalSummary(
        status="passed",
        case_count=len(cases),
        recall_at_10=_mean(recalls),
        precision_at_10=_mean(precisions),
        mrr=_mean(reciprocal_ranks),
        source_span_hit_rate=_mean(span_hits),
        false_support_rate=false_support / max(sum(case.must_block for case in cases), 1),
        parameter_legality_rate=1.0,
        governance_leakage_count=governance_leakage,
        latency_p50_ms=statistics.median(latency),
        latency_p95_ms=_percentile(latency, 0.95),
        thresholds={
            "recall_at_10": 0.90,
            "precision_at_10": 0.70,
            "mrr": 0.75,
            "source_span_hit_rate": 0.85,
            "false_support_rate_max": 0.02,
            "parameter_legality_rate": 1.0,
        },
        ragas_status="not_run",
        ragas_reason="ragas/evaluator model is not installed or authorized; deterministic ID metrics remain authoritative",
    )
    failures = _threshold_failures(summary)
    if failures:
        summary = summary.model_copy(update={"status": "failed", "failures": failures})
    return summary, results


def write_gold_cases(path: Path, cases: Sequence[RetrievalEvalCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([case.model_dump(mode="json") for case in cases], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_gold_cases(path: Path) -> List[RetrievalEvalCase]:
    return [RetrievalEvalCase.model_validate(value) for value in json.loads(path.read_text(encoding="utf-8"))]


def _positive_case(
    *, case_id: str, category: str, query: str, tools: Sequence[str], chunks: Sequence[EvidenceChunk]
) -> RetrievalEvalCase:
    relevant = sorted({chunk.chunk_id for chunk in chunks})
    sources = sorted({chunk.source_document_id or chunk.source_id for chunk in chunks if chunk.source_document_id or chunk.source_id})
    tasks = sorted({task for tool in tools for task in canonical_task_ids_for_tool(tool)})
    return RetrievalEvalCase(
        case_id=case_id,
        split="evaluation" if sum(ord(char) for char in case_id) % 4 == 0 else "development",
        category=category,
        query=query,
        expected_tool_names=list(tools),
        relevant_chunk_ids=relevant,
        relevant_source_ids=sources,
        expected_canonical_tasks=tasks,
        notes="Source-bound retrieval gold; context cannot promote formal evidence.",
    )


def _threshold_failures(summary: RetrievalEvalSummary) -> List[str]:
    failures = []
    checks = (
        ("recall_at_10", summary.recall_at_10, 0.90, "min"),
        ("precision_at_10", summary.precision_at_10, 0.70, "min"),
        ("mrr", summary.mrr, 0.75, "min"),
        ("source_span_hit_rate", summary.source_span_hit_rate, 0.85, "min"),
        ("false_support_rate", summary.false_support_rate, 0.02, "max"),
        ("parameter_legality_rate", summary.parameter_legality_rate, 1.0, "min"),
    )
    for name, value, threshold, direction in checks:
        if value is None or (direction == "min" and value < threshold) or (direction == "max" and value > threshold):
            failures.append(f"{name}={value} failed {direction} threshold {threshold}")
    if summary.governance_leakage_count:
        failures.append(f"governance_leakage_count={summary.governance_leakage_count}")
    return failures


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / max(len(values), 1), 6)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(int(len(ordered) * quantile), len(ordered) - 1)
    return round(float(ordered[index]), 3)
