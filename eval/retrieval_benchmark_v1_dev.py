from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.canonical_task_ontology import canonical_task_for_text
from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.evidence_discovery_index import EvidenceChunk, load_chunks
from engine.hybrid_retrieval import (
    HybridRetrievalService,
    LocalBgeM3Encoder,
    _infer_claim_types,
    _rrf,
    _tool_key,
)


OUTPUT_DIR = PROJECT_ROOT / "eval_v2" / "retrieval_benchmark_v1_dev"
REPORT_PATH = PROJECT_ROOT / "docs" / "status" / "RETRIEVAL_BENCHMARK_V1_DEV_REPORT.md"
CHUNKS_PATH = PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl"
VECTOR_METADATA_PATH = PROJECT_ROOT / "data" / "indexes" / "evidence_vector_metadata.json"
INDEX_MANIFEST_PATH = PROJECT_ROOT / "data" / "indexes" / "evidence_index_manifest.json"
ADJUDICATION_PATH = PROJECT_ROOT / "eval" / "fixtures" / "architecture_citation_adjudication_v1.json"
LEGACY_GOLD_PATH = PROJECT_ROOT / "eval" / "fixtures" / "retrieval_gold_v2.json"
SEED_EVIDENCE_GOLD_PATH = PROJECT_ROOT / "eval_v2" / "gold" / "midterm_core_seed_v0" / "evidence_gold.jsonl"
SEED_PROVENANCE_PATH = PROJECT_ROOT / "eval_v2" / "gold" / "midterm_core_seed_v0" / "scientific_source_provenance.jsonl"
UAT_SPANS_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_uat_decision_rules" / "authoritative_evidence_spans.jsonl"
CORE_SPANS_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_core" / "evidence_spans.jsonl"
KG_MANIFEST_PATH = PROJECT_ROOT / "data" / "knowledge_graph_v2" / "manifest.json"

EXPECTED_MODEL = "BAAI/bge-m3"
EXPECTED_MODEL_REVISION = "cb1779f90b988b8deb01f9155c790ef9417d7648"
EXPECTED_CORPUS_DIGEST = "7c8545721cd73a47fc0849ccc240ba2e150a064e07005de5f11ac26ab1213fd0"
EXPECTED_VECTOR_COUNT = 773
EXPECTED_DIMENSION = 1024
TOP_K = 10


@dataclass(frozen=True)
class Profile:
    profile_id: str
    sparse: bool
    dense: bool
    kg: bool
    governance: bool


PROFILES = (
    Profile("R0_bm25_only", True, False, False, False),
    Profile("R1_dense_only", False, True, False, False),
    Profile("R2_bm25_dense_rrf", True, True, False, False),
    Profile("R3_kg_bm25_dense_rrf", True, True, True, False),
    Profile("R4_kg_bm25_dense_rrf_governance", True, True, True, True),
)


SEED_QUERY_METADATA = {
    "evidence-gold:v2.1:neighbor-graph-reuse-leiden:leiden-input": ("Can Scanpy Leiden consume an existing neighbor graph or an explicit adjacency matrix?", "clustering", "input_requirement"),
    "evidence-gold:v2.1:harmony-embedding-neighbors:harmony-input": ("What cell embedding and batch covariates can Harmony consume?", "batch_integration", "input_requirement"),
    "evidence-gold:v2.1:harmony-embedding-neighbors:harmony-output": ("What representation does Harmony return after integration?", "batch_integration", "output"),
    "evidence-gold:v2.1:harmony-embedding-neighbors:neighbors-input": ("Can scanpy.pp.neighbors use a selected representation from obsm without forcing PCA?", "neighbor_graph_construction", "input_requirement"),
    "evidence-gold:v2.1:scrublet-transformed-input:raw-input": ("What expression state and matrix orientation does Scrublet require?", "doublet_detection", "input_requirement"),
    "evidence-gold:v2.1:hvg-flavor-conditional-input:dispersion-input": ("What expression state do dispersion-based Scanpy HVG flavors require?", "feature_selection", "input_requirement"),
    "evidence-gold:v2.1:hvg-flavor-conditional-input:count-input": ("What input state do the Scanpy seurat_v3 HVG flavors require?", "feature_selection", "input_requirement"),
    "evidence-gold:v2.1:hvg-flavor-conditional-input:default-flavor": ("What flavor does Scanpy highly_variable_genes use when flavor is omitted in version 1.11.2?", "feature_selection", "version"),
    "evidence-gold:v2.1:hvg-flavor-conditional-input:hvg-output": ("What feature mask and statistics does Scanpy HVG selection record?", "feature_selection", "output"),
    "evidence-gold:v2.1:singler-reference-compatibility:query-input": ("Can SingleR accept raw-count expression as the query input?", "cell_type_annotation", "input_requirement"),
    "evidence-gold:v2.1:singler-reference-compatibility:reference-expression": ("What expression information must a SingleR reference provide?", "cell_type_annotation", "reference_dependency"),
    "evidence-gold:v2.1:singler-reference-compatibility:reference-labels": ("What label metadata must a SingleR reference provide?", "cell_type_annotation", "reference_dependency"),
    "evidence-gold:v2.1:singler-reference-compatibility:shared-features": ("What feature compatibility is required between a SingleR query and reference?", "cell_type_annotation", "compatibility"),
    "evidence-gold:v2.1:singler-reference-compatibility:reference-choice": ("How should a SingleR reference be chosen for the intended annotation task?", "cell_type_annotation", "applicability"),
    "evidence-gold:v2.1:celltypist-model-feature-alignment:normalized-input": ("What expression state does CellTypist 1.7.1 require for AnnData input?", "cell_type_annotation", "input_requirement"),
    "evidence-gold:v2.1:celltypist-model-feature-alignment:feature-overlap-guidance": ("Why should all genes be retained when preparing CellTypist input?", "cell_type_annotation", "compatibility"),
    "evidence-gold:v2.1:celltypist-model-feature-alignment:default-model": ("What model does CellTypist 1.7.1 use when annotate receives no model argument?", "cell_type_annotation", "version"),
    "evidence-gold:v2.1:scvelo-layer-availability:layer-requirement": ("Which AnnData layers are required by the canonical scVelo velocity workflow?", "rna_velocity", "input_requirement"),
    "evidence-gold:v2.1:mofa2-sample-alignment:overlapping-samples-supported": ("Can MOFA2 integrate omics matrices measured on overlapping sample sets?", "multimodal_integration", "compatibility"),
    "evidence-gold:v2.1:mofa2-sample-alignment:latent-output": ("What low-dimensional result does MOFA2 infer?", "multimodal_integration", "output"),
}


SPAN_TO_INDEXED_CHUNKS = {
    "uat-authoritative-span:harmony.generic_input": ["sourcev2:39b8f557e5782a49ee55"],
    "uat-authoritative-span:harmony.output": ["sourcev2:bd5f8132711c97b4e432"],
    "uat-authoritative-span:scrublet.input_output": ["sourcev2:111374ebeb154e8b9052"],
    "gold-span:celltypist:normalized-input:1.7.1": ["sourcev2:102dc717591cdfac63a5"],
    "gold-span:scvelo:spliced-unspliced-input:0.3.3": ["sourcev2:ec521bf9803b9467b940", "sourcev2:cfcfa7fce0aeabf69594"],
    "gold-span:mofa2:input-output:ec2ee6d": ["sourcev2:7c73d5e998696443ddbb"],
}


EXTRA_R1_CASES = (
    ("r1-extra-normalization", "How does scanpy.pp.normalize_total normalize per-cell library size?", "normalization", "method_identity", "Scanpy", "evidence-span:v1-core:scanpy:scanpy_pp_normalize_total:capability"),
    ("r1-extra-pca-input", "What matrix orientation and layer selection can scanpy.pp.pca consume?", "dimensionality_reduction", "input_requirement", "Scanpy", "scanpy-authoritative-span:pca.input:1.11.2"),
    ("r1-extra-pca-output", "Where does scanpy.pp.pca store coordinates loadings and explained variance?", "dimensionality_reduction", "output", "Scanpy", "scanpy-authoritative-span:pca.output:1.11.2"),
    ("r1-extra-neighbors-output", "What matrices and metadata does scanpy.pp.neighbors write?", "neighbor_graph_construction", "output", "Scanpy", "scanpy-authoritative-span:neighbors.output:1.11.2"),
    ("r1-extra-umap-input", "How does scanpy.tl.umap select neighbor graph connectivities?", "dimensionality_reduction", "input_requirement", "Scanpy", "scanpy-authoritative-span:umap.input:1.11.2"),
    ("r1-extra-umap-output", "Where does scanpy.tl.umap store coordinates and parameters?", "dimensionality_reduction", "output", "Scanpy", "scanpy-authoritative-span:umap.output:1.11.2"),
    ("r1-extra-soupx-ambient", "What contamination problem is SoupX designed to address in droplet single-cell RNA sequencing?", "ambient_rna", "method_identity", "SoupX", "publication:CAND_PUB_SoupX_5218c8e163d7"),
    ("r1-extra-edger-count-input", "What count data and sample metadata are required to construct an edgeR DGEList?", "differential_expression", "input_requirement", "edgeR", "evidence-span:v1-core:edger:edger__dgelist:capability"),
    ("r1-extra-slingshot-output", "What lineage and pseudotime result does Slingshot infer?", "trajectory_inference", "output", "Slingshot", "evidence-span:v1-core:slingshot:slingshot__slingshot:primary_method_evidence"),
    ("r1-extra-pyscenic-grn", "What gene-regulatory-network task does the pySCENIC workflow perform?", "gene_regulatory_network", "method_identity", "pySCENIC", "evidence-span:v1-core:pyscenic:pyscenic_grn:primary_method_evidence"),
)


R2_DISCOVERY_CASES = (
    ("scrublet", "Find the source-bound method for detecting doublets from single-cell RNA count data.", "Scrublet", "doublet_detection", "publication:CAND_PUB_Scrublet_137a56b00546"),
    ("harmony", "Find a source-bound method for integrating batches in low-dimensional single-cell embeddings.", "Harmony", "batch_integration", "publication:CAND_PUB_Harmony_072fd76703cc"),
    ("scanorama", "Find a source-bound method for heterogeneous single-cell RNA-seq batch integration.", "Scanorama", "batch_integration", "sourcev2:d869d09f04f1e0c29624"),
    ("scvi", "Find a source-bound probabilistic framework for single-cell integration and representation learning.", "scvi-tools", "batch_integration", "publication:CAND_PUB_scvi-tools_0214cd4cc2d8"),
    ("celltypist", "Find a source-bound automated cell-type annotation method based on pretrained models.", "CellTypist", "cell_type_annotation", "publication:CAND_PUB_CellTypist_0ab6945053d3"),
    ("singler", "Find a source-bound reference-based cell-type annotation method.", "SingleR", "cell_type_annotation", "publication:CAND_PUB_SingleR_2019_Aran"),
    ("cellrank", "Find a source-bound method for cell fate mapping from single-cell dynamics.", "CellRank", "fate_mapping", "publication:CAND_PUB_CellRank_37ae953d1d1a"),
    ("mofa2", "Find a source-bound factor-analysis method for multimodal integration.", "MOFA2", "multimodal_integration", "publication:CAND_PUB_MOFA2_aa1b75ff2c06"),
    ("soupx", "Find a source-bound method for ambient RNA contamination correction.", "SoupX", "ambient_rna", "publication:CAND_PUB_SoupX_5218c8e163d7"),
    ("tradeseq", "Find a source-bound method for differential expression along single-cell trajectories.", "tradeSeq", "differential_expression", "publication:CAND_PUB_tradeSeq_f20b8273a8d0"),
    ("scvelo", "Find a source-bound method for RNA velocity using spliced and unspliced expression.", "scVelo", "rna_velocity", "publication:CAND_PUB_scVelo_524cf1f1f80e"),
    ("scanpy", "Find a source-bound software ecosystem for single-cell preprocessing and analysis.", "Scanpy", "single_cell_analysis", "publication:CAND_PUB_Scanpy_4671c99f42e8"),
)


def _json_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _source_authority(chunk: EvidenceChunk | None) -> str:
    if chunk is None:
        return "independent_candidate_source"
    if chunk.source_kind == "publication" or chunk.source_type in {"peer_reviewed_publication", "primary_peer_reviewed_literature"}:
        return "primary_publication"
    if "official" in chunk.source_type or chunk.source_type in {"github_readme", "official_docs_html"}:
        return "official_project_source"
    return chunk.authority_tier or "source_bound"


def _span_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for path in (UAT_SPANS_PATH, CORE_SPANS_PATH, SEED_PROVENANCE_PATH):
        for row in _json_rows(path):
            span_id = row.get("evidence_span_id")
            if span_id:
                catalog[str(span_id)] = row
    return catalog


def _gold_record(
    *,
    query_id: str,
    track: str,
    query: str,
    task_family: str,
    query_type: str,
    expected_tools: Sequence[str],
    evidence_span_ids: Sequence[str],
    indexed_chunk_ids: Sequence[str],
    source_revision_ids: Sequence[str],
    source_ids: Sequence[str],
    authority: str,
    version: str = "",
    scope: str = "",
    gold_origin: str,
) -> dict[str, Any]:
    return {
        "schema_version": "sckg-retrieval-benchmark-v1-dev-gold-v1",
        "query_id": query_id,
        "track": track,
        "query": query,
        "task_family": task_family,
        "query_type": query_type,
        "expected_tools": list(expected_tools),
        "gold_evidence_span_ids": sorted(set(evidence_span_ids)),
        "indexed_chunk_aliases": sorted(set(indexed_chunk_ids)),
        "source_revision_ids": sorted(set(source_revision_ids)),
        "source_ids": sorted(set(source_ids)),
        "source_authority": authority,
        "expected_version": version,
        "expected_scope": scope,
        "gold_origin": gold_origin,
        "generated_from_retrieval_output": False,
    }


def build_frozen_specs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    chunks = load_chunks(CHUNKS_PATH)
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    spans = _span_catalog()
    legacy_queries = {row["case_id"]: row for row in json.loads(LEGACY_GOLD_PATH.read_text(encoding="utf-8"))}
    adjudication = json.loads(ADJUDICATION_PATH.read_text(encoding="utf-8"))
    excluded_duplicates = {"tool-03-parameter", "tool-03-output", "tool-08-input_requirement", "tool-13-input_requirement"}
    queries: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []

    for case in adjudication["cases"]:
        if case["case_id"] in excluded_duplicates:
            continue
        base = legacy_queries[case["case_id"]]
        accepted = case["accepted_evidence"]
        ids = [row["evidence_id"] for row in accepted]
        source_ids = [row["source_id"] for row in accepted]
        tools = base.get("expected_tool_names", [])
        query_id = f"r1-adjudicated-{case['case_id']}"
        row = _gold_record(
            query_id=query_id,
            track="R1_scientific_evidence",
            query=base["query"],
            task_family=(base.get("expected_canonical_tasks") or [chunks_by_id.get(ids[0]).canonical_task if chunks_by_id.get(ids[0]) else "unknown"])[0],
            query_type=case["category"],
            expected_tools=tools,
            evidence_span_ids=ids,
            indexed_chunk_ids=ids,
            source_revision_ids=[],
            source_ids=source_ids,
            authority=_source_authority(chunks_by_id.get(ids[0])),
            gold_origin="claim_first_corpus_adjudication_v1",
        )
        gold.append(row)
        queries.append({key: row[key] for key in ("query_id", "track", "query", "task_family", "query_type", "expected_tools")})

    for item in _json_rows(SEED_EVIDENCE_GOLD_PATH):
        if not item["evidence_required"]:
            continue
        query, task_family, query_type = SEED_QUERY_METADATA[item["evidence_gold_id"]]
        evidence_ids = item["allowed_evidence_spans"]
        aliases = [alias for span_id in evidence_ids for alias in SPAN_TO_INDEXED_CHUNKS.get(span_id, [])]
        provenance = [spans.get(span_id, {}) for span_id in evidence_ids]
        source_revisions = [row.get("source_revision_id", "") for row in provenance if row.get("source_revision_id")]
        source_ids = [row.get("source_id", row.get("source_work_id", "")) for row in provenance if row.get("source_id") or row.get("source_work_id")]
        expected_tools = _tools_for_seed_case(item["evidence_gold_id"])
        row = _gold_record(
            query_id=f"r1-seed-{item['evidence_gold_id'].split(':')[-1]}",
            track="R1_scientific_evidence",
            query=query,
            task_family=task_family,
            query_type=query_type,
            expected_tools=expected_tools,
            evidence_span_ids=evidence_ids,
            indexed_chunk_ids=aliases,
            source_revision_ids=source_revisions,
            source_ids=source_ids,
            authority=(provenance[0].get("authority", "independent_reviewed_source") if provenance else "independent_reviewed_source"),
            version=item.get("version", ""),
            scope=item.get("scope", ""),
            gold_origin="midterm_core_seed_v0_project_owner_reviewed",
        )
        gold.append(row)
        queries.append({key: row[key] for key in ("query_id", "track", "query", "task_family", "query_type", "expected_tools")})

    for case_id, query, task, query_type, tool, evidence_id in EXTRA_R1_CASES:
        evidence = spans.get(evidence_id, {})
        indexed = [evidence_id] if evidence_id in chunks_by_id else []
        source_id = evidence.get("source_id", "")
        source_revision = evidence.get("source_revision_id", "")
        if evidence_id.startswith(("publication:", "sourcev2:")):
            chunk = chunks_by_id.get(evidence_id)
            indexed = [evidence_id] if chunk else []
            source_id = (chunk.source_document_id or chunk.source_id) if chunk else ""
        row = _gold_record(
            query_id=case_id,
            track="R1_scientific_evidence",
            query=query,
            task_family=task,
            query_type=query_type,
            expected_tools=[tool],
            evidence_span_ids=[evidence_id],
            indexed_chunk_ids=indexed,
            source_revision_ids=[source_revision] if source_revision else [],
            source_ids=[source_id] if source_id else [],
            authority=evidence.get("authority", _source_authority(chunks_by_id.get(evidence_id))),
            version=str((evidence.get("version_pin") or {}).get("release", "")),
            gold_origin="pinned_authoritative_or_candidate_source_fixture",
        )
        gold.append(row)
        queries.append({key: row[key] for key in ("query_id", "track", "query", "task_family", "query_type", "expected_tools")})

    for suffix, query, tool, task, evidence_id in R2_DISCOVERY_CASES:
        chunk = chunks_by_id.get(evidence_id)
        row = _gold_record(
            query_id=f"r2-discovery-{suffix}",
            track="R2_tool_method_discovery",
            query=query,
            task_family=task,
            query_type="method_discovery",
            expected_tools=[tool],
            evidence_span_ids=[evidence_id],
            indexed_chunk_ids=[evidence_id] if chunk else [],
            source_revision_ids=[],
            source_ids=[chunk.source_document_id or chunk.source_id] if chunk else [],
            authority=_source_authority(chunk),
            gold_origin="source_bound_method_identity_fixture",
        )
        gold.append(row)
        queries.append({key: row[key] for key in ("query_id", "track", "query", "task_family", "query_type", "expected_tools")})

    r1_count = sum(row["track"] == "R1_scientific_evidence" for row in gold)
    if r1_count != 45:
        raise AssertionError(f"expected 45 R1 information needs, got {r1_count}")
    if len({row["query_id"] for row in gold}) != len(gold):
        raise AssertionError("query IDs must be unique")
    config = {
        "schema_version": "sckg-retrieval-benchmark-v1-dev-config-v1",
        "campaign": "development_not_formal_midterm",
        "top_k": TOP_K,
        "profiles": [asdict(profile) for profile in PROFILES],
        "primary_sampling_unit": "retrieval_query_scientific_information_need",
        "nested_unit_policy": "multiple gold spans are OR-equivalent within one query and are not independent samples",
        "r1_catalog_policy": "excluded",
        "r2_catalog_policy": "included_for_discovery_but_never_mixed_into_R1_metrics",
        "metric_policy": {
            "recall_at_k": "fraction of queries with at least one exact accepted indexed evidence span at k",
            "mrr": "mean reciprocal rank of first exact accepted evidence span",
            "ndcg_at_10": "binary relevance over exact accepted evidence spans, query averaged",
            "irrelevant_context_rate": "non-gold hits divided by returned hits per query, then query averaged",
            "not_applicable": "version metrics omit queries without an expected version",
        },
        "kg_pair_policy": "R2_to_R3: HELPED if top10 hit appears or first-gold rank improves; HURT if top10 hit disappears or first-gold rank worsens; otherwise NEUTRAL",
        "frozen_foundation": {
            "embedding_model": EXPECTED_MODEL,
            "model_revision": EXPECTED_MODEL_REVISION,
            "corpus_digest": EXPECTED_CORPUS_DIGEST,
            "vector_count": EXPECTED_VECTOR_COUNT,
            "dimension": EXPECTED_DIMENSION,
            "dense_available": True,
        },
    }
    return queries, gold, config


def _tools_for_seed_case(case_id: str) -> list[str]:
    lowered = case_id.casefold()
    for marker, tool in (("singler", "SingleR"), ("celltypist", "CellTypist"), ("scvelo", "scVelo"), ("mofa2", "MOFA2"), ("scrublet", "Scrublet"), ("harmony", "Harmony"), ("neighbor", "Scanpy"), ("hvg", "Scanpy")):
        if marker in lowered:
            return [tool]
    return []


def prepare(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite existing development benchmark directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    queries, gold, config = build_frozen_specs()
    _write_jsonl(output_dir / "queries.jsonl", queries)
    _write_jsonl(output_dir / "gold.jsonl", gold)
    _write_json(output_dir / "retrieval_config.json", config)
    source_paths = [ADJUDICATION_PATH, LEGACY_GOLD_PATH, SEED_EVIDENCE_GOLD_PATH, SEED_PROVENANCE_PATH, UAT_SPANS_PATH, CORE_SPANS_PATH, CHUNKS_PATH, VECTOR_METADATA_PATH, INDEX_MANIFEST_PATH]
    manifest = {
        "schema_version": "sckg-retrieval-benchmark-v1-dev-prerun-v1",
        "state": "prepared_not_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query_set_sha256": _sha_file(output_dir / "queries.jsonl"),
        "gold_sha256": _sha_file(output_dir / "gold.jsonl"),
        "retrieval_config_sha256": _sha_file(output_dir / "retrieval_config.json"),
        "source_artifact_sha256": {str(path.relative_to(PROJECT_ROOT)): _sha_file(path) for path in source_paths},
        "kg_snapshot_identity": _kg_identity(),
        "dense_index_identity": _dense_identity(),
    }
    _write_json(output_dir / "pre_run_manifest.json", manifest)
    return manifest


def _dense_identity() -> dict[str, Any]:
    metadata = json.loads(VECTOR_METADATA_PATH.read_text(encoding="utf-8"))
    matrix_path = PROJECT_ROOT / "data" / "indexes" / "evidence_vectors.npy"
    identity = {
        "model": metadata.get("model"),
        "model_revision": metadata.get("model_revision"),
        "source_digest": metadata.get("source_digest"),
        "vector_count": len(metadata.get("chunk_ids", [])),
        "dimension": EXPECTED_DIMENSION,
        "build_id": metadata.get("build_id"),
        "metadata_sha256": _sha_file(VECTOR_METADATA_PATH),
        "matrix_sha256": _sha_file(matrix_path),
    }
    expected = (EXPECTED_MODEL, EXPECTED_MODEL_REVISION, EXPECTED_CORPUS_DIGEST, EXPECTED_VECTOR_COUNT, EXPECTED_DIMENSION)
    actual = (identity["model"], identity["model_revision"], identity["source_digest"], identity["vector_count"], identity["dimension"])
    if actual != expected:
        raise RuntimeError(f"frozen dense foundation drift: expected={expected!r}; actual={actual!r}")
    return identity


def _kg_identity() -> dict[str, Any]:
    if KG_MANIFEST_PATH.is_file():
        manifest = json.loads(KG_MANIFEST_PATH.read_text(encoding="utf-8"))
        return {"path": str(KG_MANIFEST_PATH.relative_to(PROJECT_ROOT)), "sha256": _sha_file(KG_MANIFEST_PATH), "build_id": manifest.get("build_id", manifest.get("graph_version", ""))}
    graph_files = sorted((PROJECT_ROOT / "data" / "knowledge_graph_v2").glob("*.jsonl"))
    return {"path": "data/knowledge_graph_v2", "sha256": _sha_bytes("".join(_sha_file(path) for path in graph_files).encode()), "build_id": "directory_digest"}


def _validate_prepared(output_dir: Path) -> dict[str, Any]:
    manifest = json.loads((output_dir / "pre_run_manifest.json").read_text(encoding="utf-8"))
    checks = {
        "query_set_sha256": _sha_file(output_dir / "queries.jsonl"),
        "gold_sha256": _sha_file(output_dir / "gold.jsonl"),
        "retrieval_config_sha256": _sha_file(output_dir / "retrieval_config.json"),
    }
    for key, value in checks.items():
        if manifest[key] != value:
            raise RuntimeError(f"prepared benchmark drift: {key}")
    for rel, digest in manifest["source_artifact_sha256"].items():
        if _sha_file(PROJECT_ROOT / rel) != digest:
            raise RuntimeError(f"frozen source artifact drift: {rel}")
    if manifest["dense_index_identity"] != _dense_identity():
        raise RuntimeError("dense index identity drift")
    if manifest["kg_snapshot_identity"] != _kg_identity():
        raise RuntimeError("KG snapshot identity drift")
    return manifest


def _request(query: dict[str, Any], profile: Profile) -> HybridRetrievalRequest:
    return HybridRetrievalRequest(
        query=query["query"],
        top_k=TOP_K,
        include_catalog=query["track"] == "R2_tool_method_discovery",
        enable_sparse=profile.sparse,
        enable_dense=profile.dense,
        nonblocking_dense=False,
        use_kg=profile.kg,
        use_governance_rerank=profile.governance,
        use_contract_gate=False,
    )


def _evaluate_hit_list(query: dict[str, Any], gold: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = set(gold["indexed_chunk_aliases"])
    ranks = [index for index, hit in enumerate(hits, 1) if hit["chunk_id"] in accepted]
    first = min(ranks) if ranks else None
    hit5 = bool(first and first <= 5)
    hit10 = bool(first and first <= 10)
    ideal = min(len(accepted), 10)
    dcg = sum((1.0 / math.log2(rank + 1)) for rank in ranks if rank <= 10)
    idcg = sum((1.0 / math.log2(rank + 1)) for rank in range(1, ideal + 1)) if ideal else 0.0
    source_ids = set(gold["source_ids"])
    authoritative_hit = any(hit["chunk_id"] in accepted or hit.get("source_id") in source_ids for hit in hits[:10])
    returned = hits[:10]
    return {
        "query_id": query["query_id"],
        "track": query["track"],
        "task_family": query["task_family"],
        "query_type": query["query_type"],
        "recall_at_5": int(hit5),
        "recall_at_10": int(hit10),
        "reciprocal_rank": (1.0 / first if first else 0.0),
        "ndcg_at_10": (dcg / idcg if idcg else 0.0),
        "first_gold_rank": first,
        "authoritative_source_hit": int(authoritative_hit),
        "correct_version_hit": (int(hit10) if gold["expected_version"] else None),
        "correct_scope_hit": (int(hit10) if gold["expected_scope"] else None),
        "irrelevant_context_rate": (sum(hit["chunk_id"] not in accepted for hit in returned) / len(returned) if returned else 0.0),
        "retrieved": hits,
    }


def _mean(values: Iterable[float | int | None]) -> float | None:
    kept = [float(value) for value in values if value is not None]
    return round(sum(kept) / len(kept), 6) if kept else None


def _aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "query_count": len(rows),
        "recall_at_5": _mean(row["recall_at_5"] for row in rows),
        "recall_at_10": _mean(row["recall_at_10"] for row in rows),
        "mrr": _mean(row["reciprocal_rank"] for row in rows),
        "ndcg_at_10": _mean(row["ndcg_at_10"] for row in rows),
        "authoritative_source_hit_rate": _mean(row["authoritative_source_hit"] for row in rows),
        "correct_version_hit_rate": _mean(row["correct_version_hit"] for row in rows),
        "correct_version_denominator": sum(row["correct_version_hit"] is not None for row in rows),
        "correct_scope_hit_rate": _mean(row["correct_scope_hit"] for row in rows),
        "correct_scope_denominator": sum(row["correct_scope_hit"] is not None for row in rows),
        "irrelevant_context_rate": _mean(row["irrelevant_context_rate"] for row in rows),
    }


def _stage_diagnostics(service: HybridRetrievalService, query: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    base_request = HybridRetrievalRequest(query=query["query"], top_k=TOP_K, include_catalog=query["track"] == "R2_tool_method_discovery")
    inferred_tools = service._named_tools_in_query(query["query"])
    effective = base_request.model_copy(update={"tool_names": inferred_tools}) if inferred_tools else base_request
    inferred_task = canonical_task_for_text(query["query"])
    task_ids = {inferred_task.task_id} if inferred_task else set()
    claim_types = _infer_claim_types(query["query"])
    bm25_raw = service._bm25_search(query["query"], limit=120)
    dense_raw, dense_status = service._dense_search(query["query"], limit=120, nonblocking=False)
    common_tools = {_tool_key(value) for value in effective.tool_names}
    bm25_common = service._filter_ranked(bm25_raw, request=effective, task_ids=task_ids, candidate_tools=common_tools)
    dense_common = service._filter_ranked(dense_raw, request=effective, task_ids=task_ids, candidate_tools=common_tools)
    fused_before = _rrf(bm25_common, dense_common)
    kg_tools, warning = service._kg_candidates(task_ids=sorted(task_ids), explicit_tools=effective.tool_names)
    bm25_kg = service._filter_ranked(bm25_raw, request=effective, task_ids=task_ids, candidate_tools=kg_tools)
    dense_kg = service._filter_ranked(dense_raw, request=effective, task_ids=task_ids, candidate_tools=kg_tools)
    fused_after = _rrf(bm25_kg, dense_kg)
    governed = service._governance_rerank(fused_after, request=effective, task_ids=task_ids, claim_types=claim_types, candidate_tools=kg_tools)
    accepted = set(gold["indexed_chunk_aliases"])
    def rank(rows: Sequence[Sequence[Any]]) -> int | None:
        return next((idx for idx, row in enumerate(rows, 1) if row[0] in accepted), None)
    stages = {
        "corpus": [chunk_id for chunk_id in accepted if chunk_id in service._chunks_by_id],
        "bm25_raw_rank": rank(bm25_raw),
        "dense_raw_rank": rank(dense_raw),
        "common_filter_rank": min([value for value in (rank(bm25_common), rank(dense_common)) if value is not None], default=None),
        "fusion_before_kg_rank": rank(fused_before),
        "kg_filter_rank": min([value for value in (rank(bm25_kg), rank(dense_kg)) if value is not None], default=None),
        "fusion_after_kg_rank": rank(fused_after),
        "governance_rank": rank(governed),
    }
    first_disappearance = "none"
    ordered = [("corpus", bool(stages["corpus"])), ("initial_retrieval", stages["bm25_raw_rank"] is not None or stages["dense_raw_rank"] is not None), ("common_filter", stages["common_filter_rank"] is not None), ("fusion_before_kg", stages["fusion_before_kg_rank"] is not None), ("kg_filter", stages["kg_filter_rank"] is not None), ("fusion_after_kg", stages["fusion_after_kg_rank"] is not None), ("governance", stages["governance_rank"] is not None)]
    for name, present in ordered:
        if not present:
            first_disappearance = name
            break
    return {
        "query_id": query["query_id"],
        "dense_status": dense_status,
        "inferred_tools": inferred_tools,
        "inferred_task": inferred_task.task_id if inferred_task else None,
        "inferred_claim_types": sorted(claim_types),
        "kg_candidate_tools": sorted(kg_tools),
        "kg_warning": warning,
        "gold_present_before_kg_filtering": stages["fusion_before_kg_rank"] is not None,
        "gold_survives_kg_filtering": stages["fusion_after_kg_rank"] is not None,
        "gold_rank_before_kg": stages["fusion_before_kg_rank"],
        "gold_rank_after_kg": stages["fusion_after_kg_rank"],
        "first_stage_gold_disappears": first_disappearance,
        "stages": stages,
    }


def _paired_classification(before: dict[str, Any], after: dict[str, Any]) -> str:
    b_hit, a_hit = bool(before["recall_at_10"]), bool(after["recall_at_10"])
    b_rank = before["first_gold_rank"] or 10**9
    a_rank = after["first_gold_rank"] or 10**9
    if (not b_hit and a_hit) or (a_hit == b_hit and a_rank < b_rank):
        return "HELPED"
    if (b_hit and not a_hit) or (a_hit == b_hit and a_rank > b_rank):
        return "HURT"
    return "NEUTRAL"


def _failure_cause(gold: dict[str, Any], profile_id: str, result: dict[str, Any], diagnostic: dict[str, Any], paired_r2: dict[str, Any] | None = None, paired_r3: dict[str, Any] | None = None) -> str | None:
    if result["recall_at_10"]:
        return None
    if not gold["gold_evidence_span_ids"]:
        return "CORPUS_MISSING"
    if not gold["indexed_chunk_aliases"] or not diagnostic["stages"]["corpus"]:
        return "GOLD_SOURCE_NOT_INDEXED"
    if diagnostic["inferred_tools"] and not {_tool_key(x) for x in gold["expected_tools"]}.intersection({_tool_key(x) for x in diagnostic["inferred_tools"]}):
        return "TOOL_NORMALIZATION"
    if diagnostic["inferred_task"] and diagnostic["inferred_task"] != gold["task_family"] and diagnostic["first_stage_gold_disappears"] == "common_filter":
        return "TASK_NORMALIZATION"
    if profile_id == "R0_bm25_only":
        return "BM25_RANKING"
    if profile_id == "R1_dense_only":
        return "DENSE_RANKING"
    if profile_id == "R3_kg_bm25_dense_rrf" and paired_r2 and paired_r2["recall_at_10"]:
        return "KG_FALSE_FILTER"
    if profile_id == "R4_kg_bm25_dense_rrf_governance" and paired_r3 and paired_r3["recall_at_10"]:
        return "GOVERNANCE_RERANK"
    if gold["expected_version"] or gold["expected_scope"]:
        return "VERSION_SCOPE"
    return "OTHER"


def run(output_dir: Path = OUTPUT_DIR, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    if (output_dir / "report.json").exists() or (output_dir / "run_completed.json").exists():
        raise FileExistsError("development benchmark is write-once and has already completed")
    pre = _validate_prepared(output_dir)
    queries = _json_rows(output_dir / "queries.jsonl")
    gold_rows = _json_rows(output_dir / "gold.jsonl")
    gold_by_id = {row["query_id"]: row for row in gold_rows}
    started = {"schema_version": "sckg-retrieval-benchmark-v1-dev-run-marker-v1", "started_at": datetime.now(timezone.utc).isoformat(), "pre_run_manifest_sha256": _sha_file(output_dir / "pre_run_manifest.json")}
    _write_json(output_dir / "run_started.json", started)

    encoder = LocalBgeM3Encoder()
    if encoder.model_revision != EXPECTED_MODEL_REVISION:
        raise RuntimeError("loaded dense encoder revision differs from frozen revision")
    service = HybridRetrievalService(dense_encoder=encoder)
    diagnostics = {query["query_id"]: _stage_diagnostics(service, query, gold_by_id[query["query_id"]]) for query in queries}
    all_results: list[dict[str, Any]] = []
    by_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for profile in PROFILES:
        by_profile[profile.profile_id] = {}
        for query in queries:
            response = service.search(_request(query, profile))
            hits = [hit.model_dump(mode="json") for hit in response.hits]
            evaluated = _evaluate_hit_list(query, gold_by_id[query["query_id"]], hits)
            evaluated.update({"profile_id": profile.profile_id, "dense_status": response.dense_status, "latency_ms": response.latency_ms, "pipeline": response.pipeline, "warnings": response.warnings})
            all_results.append(evaluated)
            by_profile[profile.profile_id][query["query_id"]] = evaluated

    kg_rows = []
    governance_rows = []
    failures = []
    for query in queries:
        qid = query["query_id"]
        r2 = by_profile["R2_bm25_dense_rrf"][qid]
        r3 = by_profile["R3_kg_bm25_dense_rrf"][qid]
        r4 = by_profile["R4_kg_bm25_dense_rrf_governance"][qid]
        kg_class = _paired_classification(r2, r3)
        kg_rows.append({**diagnostics[qid], "paired_classification": kg_class})
        governance_rows.append({
            "query_id": qid,
            "authoritative_source_preference_delta": r4["authoritative_source_hit"] - r3["authoritative_source_hit"],
            "source_binding_correctness_delta": r4["recall_at_10"] - r3["recall_at_10"],
            "version_correctness_delta": None if r3["correct_version_hit"] is None else r4["correct_version_hit"] - r3["correct_version_hit"],
            "scope_correctness_delta": None if r3["correct_scope_hit"] is None else r4["correct_scope_hit"] - r3["correct_scope_hit"],
            "recommendation_eligibility_leakage_r3": sum(hit["recommendation_eligible"] and hit["governance_status"] == "catalog_only" for hit in r3["retrieved"]),
            "recommendation_eligibility_leakage_r4": sum(hit["recommendation_eligible"] and hit["governance_status"] == "catalog_only" for hit in r4["retrieved"]),
            "classification": _paired_classification(r3, r4),
        })
        for profile in PROFILES:
            result = by_profile[profile.profile_id][qid]
            cause = _failure_cause(gold_by_id[qid], profile.profile_id, result, diagnostics[qid], r2, r3)
            if cause:
                failures.append({"query_id": qid, "track": query["track"], "profile_id": profile.profile_id, "first_cause": cause, "first_stage_gold_disappears": diagnostics[qid]["first_stage_gold_disappears"]})

    aggregates: dict[str, Any] = {}
    stratified: dict[str, Any] = {}
    for profile in PROFILES:
        rows = [row for row in all_results if row["profile_id"] == profile.profile_id]
        aggregates[profile.profile_id] = {track: _aggregate([row for row in rows if row["track"] == track]) for track in ("R1_scientific_evidence", "R2_tool_method_discovery")}
        stratified[profile.profile_id] = {}
        for dimension in ("task_family", "query_type"):
            values = sorted({row[dimension] for row in rows})
            stratified[profile.profile_id][dimension] = {value: _aggregate([row for row in rows if row[dimension] == value]) for value in values}
        stratified[profile.profile_id]["source_authority"] = {value: _aggregate([row for row in rows if gold_by_id[row["query_id"]]["source_authority"] == value]) for value in sorted({gold["source_authority"] for gold in gold_rows})}

    counts = {label: sum(row["paired_classification"] == label for row in kg_rows) for label in ("HELPED", "NEUTRAL", "HURT")}
    kg_summary = {
        "query_count": len(kg_rows),
        "helped": counts["HELPED"],
        "neutral": counts["NEUTRAL"],
        "hurt": counts["HURT"],
        "kg_positive_utility_rate": round(counts["HELPED"] / len(kg_rows), 6),
        "kg_neutral_rate": round(counts["NEUTRAL"] / len(kg_rows), 6),
        "kg_false_filter_rate": round(sum(row["paired_classification"] == "HURT" and row["first_stage_gold_disappears"] == "kg_filter" for row in kg_rows) / len(kg_rows), 6),
    }
    _write_jsonl(output_dir / "per_query_results.jsonl", all_results)
    _write_json(output_dir / "aggregate_metrics.json", aggregates)
    _write_json(output_dir / "stratified_metrics.json", stratified)
    _write_jsonl(output_dir / "kg_diagnostics.jsonl", kg_rows)
    _write_json(output_dir / "kg_summary.json", kg_summary)
    _write_jsonl(output_dir / "governance_diagnostics.jsonl", governance_rows)
    _write_jsonl(output_dir / "failure_register.jsonl", failures)
    report = {
        "schema_version": "sckg-retrieval-benchmark-v1-dev-report-v1",
        "status": "COMPLETE",
        "interpretation_boundary": "COMPLETE means faithful execution, not superiority of KG or hybrid retrieval",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "query_set_sha256": pre["query_set_sha256"],
        "gold_sha256": pre["gold_sha256"],
        "retrieval_config_sha256": pre["retrieval_config_sha256"],
        "corpus_digest": EXPECTED_CORPUS_DIGEST,
        "kg_snapshot_identity": pre["kg_snapshot_identity"],
        "dense_index_identity": pre["dense_index_identity"],
        "query_counts": {"R1_scientific_evidence": sum(q["track"] == "R1_scientific_evidence" for q in queries), "R2_tool_method_discovery": sum(q["track"] == "R2_tool_method_discovery" for q in queries)},
        "aggregate_metrics": aggregates,
        "kg_analysis": kg_summary,
        "failure_count": len(failures),
    }
    _write_json(output_dir / "report.json", report)
    completed = {"schema_version": "sckg-retrieval-benchmark-v1-dev-run-marker-v1", "completed_at": report["completed_at"], "report_sha256": _sha_file(output_dir / "report.json"), "run_count": 1}
    _write_json(output_dir / "run_completed.json", completed)
    _write_report(report_path, report, failures, governance_rows)
    manifest = {"schema_version": "sckg-retrieval-benchmark-v1-dev-artifact-manifest-v1", "artifacts": {path.name: _sha_file(path) for path in sorted(output_dir.iterdir()) if path.is_file()}}
    _write_json(output_dir / "manifest.json", manifest)
    return report


def _write_report(path: Path, report: dict[str, Any], failures: Sequence[dict[str, Any]], governance: Sequence[dict[str, Any]]) -> None:
    lines = [
        "# Retrieval Benchmark v1 — Development Campaign",
        "",
        "Status: **COMPLETE**. This is a development experiment, not the formal Midterm holdout. COMPLETE records faithful execution and does not assert that KG or hybrid retrieval outperformed BM25.",
        "",
        f"- Query-set SHA-256: `{report['query_set_sha256']}`",
        f"- Gold SHA-256: `{report['gold_sha256']}`",
        f"- Retrieval-config SHA-256: `{report['retrieval_config_sha256']}`",
        f"- Corpus digest: `{report['corpus_digest']}`",
        f"- R1 scientific evidence queries: {report['query_counts']['R1_scientific_evidence']}",
        f"- R2 tool/method discovery queries: {report['query_counts']['R2_tool_method_discovery']}",
        "",
        "## Aggregate metrics",
        "",
        "R1 and R2 are reported separately; catalog discovery rows never enter R1 scientific-evidence metrics.",
        "",
        "| Profile | Track | Recall@5 | Recall@10 | MRR | nDCG@10 | Authoritative hit | Version hit | Scope hit | Irrelevant context |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile, tracks in report["aggregate_metrics"].items():
        for track, metrics in tracks.items():
            lines.append(f"| {profile} | {track} | {_fmt(metrics['recall_at_5'])} | {_fmt(metrics['recall_at_10'])} | {_fmt(metrics['mrr'])} | {_fmt(metrics['ndcg_at_10'])} | {_fmt(metrics['authoritative_source_hit_rate'])} | {_fmt(metrics['correct_version_hit_rate'])} | {_fmt(metrics['correct_scope_hit_rate'])} | {_fmt(metrics['irrelevant_context_rate'])} |")
    kg = report["kg_analysis"]
    lines.extend([
        "",
        "## KG paired diagnostic (R2 → R3)",
        "",
        f"- HELPED: {kg['helped']}",
        f"- NEUTRAL: {kg['neutral']}",
        f"- HURT: {kg['hurt']}",
        f"- KG positive-utility rate: {kg['kg_positive_utility_rate']}",
        f"- KG neutral rate: {kg['kg_neutral_rate']}",
        f"- KG false-filter rate: {kg['kg_false_filter_rate']}",
        "",
        "## Governance diagnostic (R3 → R4)",
        "",
        f"- HELPED: {sum(row['classification'] == 'HELPED' for row in governance)}",
        f"- NEUTRAL: {sum(row['classification'] == 'NEUTRAL' for row in governance)}",
        f"- HURT: {sum(row['classification'] == 'HURT' for row in governance)}",
        "",
        "## Failure register",
        "",
        f"There are {len(failures)} failed query-profile records. Earliest attributable causes are preserved in `failure_register.jsonl`; no corpus, KG, gold, or retrieval configuration was changed after observing them.",
        "",
        "## Boundaries",
        "",
        "The primary statistical unit is the retrieval query/scientific information need. Multiple chunks and accepted spans under a query are nested OR-equivalent evidence alternatives, not independent observations. No aggregate RAG score is produced.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    return "not_applicable" if value is None else f"{float(value):.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen Scientific KG retrieval benchmark v1 development campaign")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.prepare:
        print(json.dumps(prepare(args.output), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(run(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
