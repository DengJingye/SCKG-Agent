from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.canonical_task_ontology import canonical_task_for_text
from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.hybrid_retrieval import HybridRetrievalService, LocalBgeM3Encoder, _tool_key
from eval import retrieval_benchmark_v1_1_dev as c6


OUTPUT_DIR = PROJECT_ROOT / "eval_v2" / "independent_retrieval_validation_v1"
REPORT_PATH = PROJECT_ROOT / "docs" / "status" / "INDEPENDENT_RETRIEVAL_VALIDATION_V1.md"
RUNNER_PATH = Path(__file__).resolve()
OLD_QUERY_PATH = PROJECT_ROOT / "eval_v2" / "retrieval_benchmark_v1_dev" / "queries.jsonl"
CHUNKS_PATH = c6.INDEX_DIR / "evidence_chunks.jsonl"
SUT_PATH = PROJECT_ROOT / "engine" / "hybrid_retrieval.py"
EXPECTED_SUT_HEAD = "af8fa06ed3bd779662ee4b98ab30cf4dd708d42b"
TOP_K = 10


@dataclass(frozen=True)
class Profile:
    profile_id: str
    sparse: bool
    dense: bool
    kg: bool
    governance: bool = False


PROFILES = (
    Profile("A_bm25", True, False, False),
    Profile("B_bm25_dense", True, True, False),
    Profile("C_scikg_bm25", True, False, True),
    Profile("D_scikg_bm25_dense", True, True, True),
    Profile("E_scikg_bm25_dense_governance", True, True, True, True),
)


CATEGORY_NAMES = {
    "A": "input_requirement",
    "B": "output_semantics",
    "C": "version_flavor_parameter",
    "D": "scope_limitation",
    "E": "reference_artifact",
    "F": "missing_evidence_abstention",
    "G": "indirect_natural_language",
}


def _case(
    query_id: str,
    query: str,
    tool: str | None,
    task: str,
    chunk_ids: Sequence[str],
    conditions: str,
    rationale: str,
) -> dict[str, Any]:
    category = query_id[3]
    return {
        "query_id": query_id,
        "query": query,
        "query_type": CATEGORY_NAMES[category],
        "category": category,
        "expected_tool_operator": tool,
        "task_family": task,
        "accepted_chunk_ids": list(chunk_ids),
        "conditions": conditions,
        "evidence_available": bool(chunk_ids),
        "expected_abstention": not bool(chunk_ids),
        "novelty_rationale": rationale,
    }


def _frozen_cases() -> list[dict[str, Any]]:
    """Hand-authored before any C7 production retrieval result was observed."""
    return [
        _case("c7-A01", "For separate cell captures, how should sample identity be supplied to scDblFinder so capture-specific doublet rates are respected?", "scDblFinder", "doublet_detection", ["sourcev2:b2ac239784dafb96cb8a"], "Multiple captures rather than cell-hashed multiplexing within one capture.", "New operational condition: capture-aware execution."),
        _case("c7-A02", "Which Scanorama Scanpy interface leaves expression values in place and where does it put the integrated representation?", "Scanorama", "batch_integration", ["sourcev2:b9f757749c16210255c0"], "Distinguish integrate_scanpy from correct_scanpy.", "New API-behavior distinction, not the prior generic matrix-input question."),
        _case("c7-A03", "What two matrices does cell2location require to estimate cell-type abundance in spatial locations?", "cell2location", "spatial_mapping", ["sourcev2:ad69544cf458dd11e6fb"], "Require both untransformed spatial counts and reference cell-type signatures.", "New paired-input requirement for spatial deconvolution."),
        _case("c7-A04", "When is it scientifically defensible to run DoubletFinder on data merged from multiple 10x lanes?", "DoubletFinder", "doublet_detection", ["sourcev2:a5d5ae025bf3f95f22bc"], "Same biological sample split across lanes is the supported exception.", "New merged-lane applicability condition."),
        _case("c7-A05", "What supervision and expression inputs are needed to train a new CellTypist classifier?", "CellTypist", "cell_type_annotation", ["sourcev2:a890f23bcb6584bec1c4", "sourcev2:6d070f599929bf055fb8"], "Training, not applying a pretrained model.", "New model-training input need."),
        _case("c7-A06", "How should Scrublet be applied when a study contains several independently captured samples?", "Scrublet", "doublet_detection", ["sourcev2:7c8e2ffa37943b8749cd"], "Independent technical captures with different cell-type proportions.", "New multi-sample execution boundary."),

        _case("c7-B01", "Contrast the data products written by Scanorama integrate_scanpy and correct_scanpy.", "Scanorama", "batch_integration", ["sourcev2:b9f757749c16210255c0"], "Report X_scanorama embedding versus transformed AnnData.X copies.", "New comparative output-semantics question."),
        _case("c7-B02", "Which score matrices and label results are exposed by a CellTypist AnnotationResult?", "CellTypist", "cell_type_annotation", ["sourcev2:bdc1a08a62c8b1a34518"], "AnnotationResult after inference.", "New result-object semantics."),
        _case("c7-B03", "After CellRank builds its Markov chain, which fate-level quantities can its estimators infer?", "CellRank", "fate_mapping", ["sourcev2:2ad3f06022e2efaf7e89", "sourcev2:bb52eb5b6d94943d512c"], "Outputs must include states or probabilities derived from the chain.", "New estimator-output need."),
        _case("c7-B04", "What biological quantity does the cell2location model estimate for each spatial location?", "cell2location", "spatial_mapping", ["sourcev2:ad69544cf458dd11e6fb"], "Absolute cell-type abundance, not only a low-dimensional embedding.", "New output interpretation for spatial mapping."),
        _case("c7-B05", "What intermediate score does DoubletFinder compute before making final singlet or doublet calls?", "DoubletFinder", "doublet_detection", ["sourcev2:10a0ac3da870a89348a1"], "Identify pANN from artificial-neighbor proportions.", "New intermediate-output semantics."),
        _case("c7-B06", "What two arrays are returned by Scrublet's main doublet-calling operation, and what does the continuous one mean?", "Scrublet", "doublet_detection", ["sourcev2:111374ebeb154e8b9052"], "scrub_doublets on a raw UMI matrix.", "New explicit return-value interpretation."),

        _case("c7-C01", "In scDblFinder, which parameter controls the expected doublet proportion and why does it matter more for the call threshold than the score?", "scDblFinder", "doublet_detection", ["sourcev2:3cd1bb37cc31da83a1e4"], "Use dbr and distinguish score from threshold behavior.", "New parameter-effect question."),
        _case("c7-C02", "What version constraints does scDblFinder document for old Bioconductor releases and for scATAC analysis?", "scDblFinder", "doublet_detection", ["sourcev2:95dc4c497cd678fed6ca"], "Version-specific support statement.", "New release-compatibility need."),
        _case("c7-C03", "Which Scanorama parameters are suggested when integration hits a MemoryError, and what tradeoff are they intended to address?", "Scanorama", "batch_integration", ["sourcev2:53d71aebc10f4cdb4ddf"], "Large datasets under memory pressure.", "New resource-tuning question."),
        _case("c7-C04", "How should DoubletFinder's nExp be estimated and adjusted before thresholding pANN?", "DoubletFinder", "doublet_detection", ["sourcev2:3b8ea22562b9c4f32234"], "Use loading density and homotypic-doublet adjustment.", "New parameter-estimation question."),
        _case("c7-C05", "How can a user override CellTypist's heuristic over-clustering during majority voting?", "CellTypist", "cell_type_annotation", ["sourcev2:260bdfc4ffa3718c6983"], "majority_voting enabled; user has external clusters or an AnnData column.", "New parameter override question."),
        _case("c7-C06", "During CellTypist cross-species model conversion, what does unique_only change?", "CellTypist", "cell_type_annotation", ["sourcev2:2a267b639b234f663e5a"], "Ortholog mapping during model conversion.", "New flavor-specific conversion behavior."),

        _case("c7-D01", "Which methodological sensitivities prevent scVelo velocity arrows from being treated as unconditional trajectory evidence?", "scVelo", "rna_velocity", ["benchmark:HR_BMK_scVelo_velocity_unraveled_2022"], "Require the bounded critique rather than a global rejection of RNA velocity.", "New evidence-boundary question."),
        _case("c7-D02", "What does the cancer multi-omics benchmark support for MOFA, and which stronger overall-clustering claim must be avoided?", "MOFA2", "multimodal_integration", ["benchmark:HR_BMK_MOFA2_jDR_cancer_2021"], "Separate interpretable sparse factors from global best-clustering claims.", "New bounded-comparison question."),
        _case("c7-D03", "What workaround does Scanorama document for annoy-related illegal-instruction or segmentation-fault failures?", "Scanorama", "batch_integration", ["sourcev2:53d71aebc10f4cdb4ddf"], "Failure is associated with recent annoy versions.", "New implementation-failure boundary."),
        _case("c7-D04", "Why can pooling independently captured samples reduce Scrublet's reliability?", "Scrublet", "doublet_detection", ["sourcev2:7c8e2ffa37943b8749cd"], "Technical doublets arise within captures whose cell-type proportions differ.", "New causal limitation question."),
        _case("c7-D05", "Why should a homotypic-doublet adjustment in DoubletFinder be treated as an estimate rather than exact ground truth?", "DoubletFinder", "doublet_detection", ["sourcev2:bbe8cec45b9ec190bac2"], "Cell-type labels may not reflect the transcriptional divergence relevant to detection.", "New uncertainty boundary."),
        _case("c7-D06", "What probability-calibration caveat accompanies CellTypist training with stochastic gradient descent?", "CellTypist", "cell_type_annotation", ["sourcev2:190136329cebfaa977a1"], "SGD training rather than the default traditional logistic-regression path.", "New training-mode limitation."),

        _case("c7-E01", "Which frozen benchmark artifact supports the claim that DoubletFinder had the highest overall accuracy among the tested doublet detectors?", "DoubletFinder", "doublet_detection", ["benchmark:HR_BMK_DoubletFinder_doublet_detection_2020"], "Artifact must bind the comparative claim to its benchmark source.", "New provenance lookup for a comparative claim."),
        _case("c7-E02", "Which benchmark artifact documents Harmony's strong integration score and computational efficiency?", "Harmony", "batch_integration", ["benchmark:HR_BMK_Harmony_scIB_integration_2022"], "Use the frozen scIB benchmark record.", "New claim-to-artifact lookup."),
        _case("c7-E03", "Which evidence artifact supports scVI and scANVI as strong at balancing batch correction with biological conservation?", "scvi-tools", "batch_integration", ["benchmark:HR_BMK_scvi_tools_scIB_integration_2022"], "Use benchmark evidence, not a generic library description.", "New benchmark provenance need."),
        _case("c7-E04", "Which frozen artifact bounds cell2location's deconvolution performance relative to SpatialDWLS and RCTD?", "cell2location", "spatial_mapping", ["benchmark:HR_BMK_cell2location_spatial_deconvolution_2022"], "The artifact must avoid a unique-best claim.", "New comparative-source binding need."),
        _case("c7-E05", "Which source artifact records tradeSeq as a strong GAM baseline for trajectory differential expression?", "tradeSeq", "differential_expression", ["benchmark:HR_BMK_tradeSeq_trajectory_de_2024"], "Retrieve the benchmark record rather than method identity alone.", "New evidence-artifact lookup."),
        _case("c7-E06", "Which artifact supports SoupX as consistently strong alongside CellBender and DecontX for ambient decontamination?", "SoupX", "ambient_rna", ["benchmark:HR_BMK_SoupX_ambient_decontamination_2026"], "The comparison is non-exclusive and benchmark-bounded.", "New benchmark provenance question."),

        _case("c7-F01", "What experimentally validated false-discovery rate does CellTypist majority voting achieve on pediatric kidney scRNA-seq?", "CellTypist", "cell_type_annotation", [], "No accepted frozen span reports this dataset-specific rate.", "Purpose-built unsupported quantitative claim."),
        _case("c7-F02", "Which Scanorama release guarantees bitwise-deterministic integration across different GPU models, and which seed enforces it?", "Scanorama", "batch_integration", [], "No accepted frozen span makes a cross-GPU determinism guarantee.", "Purpose-built unsupported reproducibility guarantee."),
        _case("c7-F03", "What validated scDblFinder threshold should be used universally for joint RNA-plus-ATAC doublets in 10x Multiome?", "scDblFinder", "doublet_detection", [], "No accepted frozen span establishes a universal multimodal threshold.", "Purpose-built unsupported universal parameter."),
        _case("c7-F04", "What benchmarked correction guarantee does SoupX provide for cell mixtures within Visium spatial spots?", "SoupX", "ambient_rna", [], "No accepted frozen span establishes this spatial-spot guarantee.", "Purpose-built out-of-scope guarantee."),
        _case("c7-F05", "What is the formally supported maximum cell count for CellRank 2 under a fixed 16 GB memory limit?", "CellRank", "fate_mapping", [], "The frozen sources contain scale examples but no formal maximum under this hardware bound.", "Purpose-built unsupported capacity bound."),
        _case("c7-F06", "Which scVI latent dimension is proven universally optimal across every tissue and sequencing protocol?", "scvi-tools", "batch_integration", [], "No accepted frozen span supports a universal optimum.", "Purpose-built unsupported universal optimum."),

        _case("c7-G01", "I have several independent 10x captures and need doublet calls that respect a different loading rate in each capture. What capability fits?", "scDblFinder", "doublet_detection", ["sourcev2:b2ac239784dafb96cb8a"], "No tool name appears in the request; sample-aware doublet detection is required.", "Indirect capability-selection need."),
        _case("c7-G02", "A large heterogeneous atlas runs out of memory during batch integration. What documented adjustments can reduce memory and runtime?", "Scanorama", "batch_integration", ["sourcev2:53d71aebc10f4cdb4ddf"], "No tool name appears; require a documented memory remedy.", "Indirect operational-selection need."),
        _case("c7-G03", "I have Visium counts plus single-cell-derived signatures and need the number of each cell type per spot. Which evidence-backed method fits?", "cell2location", "spatial_mapping", ["sourcev2:ad69544cf458dd11e6fb", "publication:CAND_PUB_cell2location_34b39045863f"], "Infer absolute abundance from spatial counts and signatures.", "Indirect method-selection need."),
        _case("c7-G04", "I need terminal states and lineage fate probabilities from a cell-state transition model, not just arrows on a UMAP. Which capability fits?", "CellRank", "fate_mapping", ["sourcev2:2ad3f06022e2efaf7e89", "publication:CAND_PUB_CellRank_363ead324201"], "No tool name appears; require global fate inference.", "Indirect output-driven method selection."),
        _case("c7-G05", "Which method is supported as a generalized-additive-model baseline for expression changes along branching trajectories?", "tradeSeq", "differential_expression", ["benchmark:HR_BMK_tradeSeq_trajectory_de_2024", "publication:CAND_PUB_tradeSeq_f20b8273a8d0"], "No tool name appears; require trajectory differential expression.", "Indirect scientific-task selection."),
        _case("c7-G06", "Droplet profiles contain soup-like ambient transcripts; which source-bound method directly targets that contamination?", "SoupX", "ambient_rna", ["publication:CAND_PUB_SoupX_5218c8e163d7", "benchmark:HR_BMK_SoupX_ambient_decontamination_2026"], "No tool name appears; require ambient RNA correction.", "Indirect problem-to-method selection."),
    ]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _json_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _novelty(query: str, old_queries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    normalized = _normal(query)
    scored = [
        (SequenceMatcher(None, normalized, _normal(row["query"])).ratio(), row["query_id"])
        for row in old_queries
    ]
    score, query_id = max(scored, default=(0.0, ""))
    return {"max_character_sequence_similarity": round(score, 6), "nearest_prior_query_id": query_id}


def _span(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "source_id": chunk.get("source_id") or chunk.get("source_document_id") or "",
        "source_kind": chunk.get("source_kind", ""),
        "source_type": chunk.get("source_type", ""),
        "source_url": chunk.get("source_url", ""),
        "source_span": chunk.get("claim_span") or chunk.get("source_span") or chunk.get("title") or "",
    }


def build_specs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    chunks = {row["chunk_id"]: row for row in _json_rows(CHUNKS_PATH)}
    old_queries = _json_rows(OLD_QUERY_PATH)
    cases = _frozen_cases()
    if len(cases) != 42 or len({row["query_id"] for row in cases}) != 42:
        raise AssertionError("C7 must contain 42 unique parent information needs")
    if Counter(row["category"] for row in cases) != Counter({key: 6 for key in CATEGORY_NAMES}):
        raise AssertionError("C7 must contain six queries in each A-G category")

    query_rows: list[dict[str, Any]] = []
    gold_rows: list[dict[str, Any]] = []
    for row in cases:
        missing = [chunk_id for chunk_id in row["accepted_chunk_ids"] if chunk_id not in chunks]
        if missing:
            raise AssertionError(f"accepted evidence missing from frozen corpus: {row['query_id']} {missing}")
        novelty = _novelty(row["query"], old_queries)
        if novelty["max_character_sequence_similarity"] >= 0.88:
            raise AssertionError(f"query too close to prior C6 wording: {row['query_id']} {novelty}")
        query_rows.append({
            "schema_version": "sckg-independent-retrieval-query-v1",
            "query_id": row["query_id"],
            "natural_language_query": row["query"],
            "query": row["query"],
            "query_type": row["query_type"],
            "category": row["category"],
            "task_family": row["task_family"],
            "expected_tool_operator": row["expected_tool_operator"],
            "novelty_against_c6": novelty,
            "novelty_rationale": row["novelty_rationale"],
        })
        gold_rows.append({
            "schema_version": "sckg-independent-retrieval-gold-v1",
            "query_id": row["query_id"],
            "natural_language_query": row["query"],
            "query_type": row["query_type"],
            "expected_tool_operator": row["expected_tool_operator"],
            "accepted_evidence_spans": [_span(chunks[value]) for value in row["accepted_chunk_ids"]],
            "accepted_chunk_ids": row["accepted_chunk_ids"],
            "conditions": row["conditions"],
            "evidence_available": row["evidence_available"],
            "expected_abstention": row["expected_abstention"],
            "provenance": {
                "adjudication_method": "manual claim-first inspection of the frozen local evidence corpus before any C7 production retrieval run",
                "generated_from_production_retrieval_output": False,
                "corpus_path": str(CHUNKS_PATH.relative_to(PROJECT_ROOT)),
                "absence_basis": row["conditions"] if row["expected_abstention"] else None,
            },
        })

    dev = [row["query_id"] for row in cases if row["query_id"].endswith(("01", "02", "03", "04"))]
    sealed = [row["query_id"] for row in cases if row["query_id"].endswith(("05", "06"))]
    split = {
        "schema_version": "sckg-independent-retrieval-split-v1",
        "split_frozen_before_any_run": True,
        "sealed_validation_used_for_tuning": False,
        "allocation_rule": "Within each A-G category, cases 01-04 are DEV_CHECK and 05-06 are SEALED.",
        "DEV_CHECK": dev,
        "SEALED": sealed,
        "counts": {"DEV_CHECK": len(dev), "SEALED": len(sealed), "ALL": len(cases)},
    }
    config = {
        "schema_version": "sckg-independent-retrieval-config-v1",
        "campaign": "Independent Retrieval Validation v1",
        "top_k": TOP_K,
        "profiles": [asdict(profile) for profile in PROFILES],
        "primary_profiles": [profile.profile_id for profile in PROFILES[:4]],
        "optional_governance_profile": PROFILES[4].profile_id,
        "metric_policy": {
            "hit_at_k": "fraction of evidence-available parent queries with at least one exact accepted chunk at k",
            "mrr_at_10": "mean reciprocal rank of first exact accepted chunk within top 10 over evidence-available parent queries",
            "evidence_correctness": "exact accepted chunk in top 10 for evidence-available queries; zero returned hits for expected-abstention queries",
            "abstention_proxy": "the retrieval API has no native abstain field; zero returned hits is the strict observable abstention proxy",
            "false_certainty_event": "expected_abstention is true and the retriever returns one or more candidate evidence hits",
            "kg_pair": "A->C for BM25 and B->D for BM25+Dense; HELPED/HURT includes top-10 transition or first-gold-rank movement",
            "sampling_unit": "parent scientific information need; accepted spans are OR alternatives and never independent samples",
        },
        "execution_policy": {
            "dev_check_used_for_tuning": False,
            "sealed_validation_used_for_tuning": False,
            "sealed_run_limit": 1,
            "no_sut_index_kg_or_gold_changes_after_prepare": True,
        },
    }
    return query_rows, gold_rows, split, config


def prepare(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite C7 campaign: {output_dir}")
    if _git_head() != EXPECTED_SUT_HEAD:
        raise RuntimeError(f"C7 must be prepared at frozen Phase A HEAD {EXPECTED_SUT_HEAD}")
    queries, gold, split, config = build_specs()
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_jsonl(output_dir / "query_set.jsonl", queries)
    _write_jsonl(output_dir / "gold.jsonl", gold)
    _write_json(output_dir / "split_manifest.json", split)
    _write_json(output_dir / "retrieval_config.json", config)
    source_paths = [
        CHUNKS_PATH,
        c6.INDEX_DIR / "scrna_tools_catalog_chunks.jsonl",
        c6.INDEX_DIR / "evidence_fts5.sqlite",
        c6.INDEX_DIR / "evidence_index_manifest.json",
        c6.INDEX_DIR / "evidence_vector_metadata.json",
        c6.INDEX_DIR / "evidence_vectors.npy",
        c6.KG_MANIFEST_PATH,
        SUT_PATH,
        OLD_QUERY_PATH,
        RUNNER_PATH,
    ]
    manifest = {
        "schema_version": "sckg-independent-retrieval-prerun-manifest-v1",
        "state": "PREPARED_NOT_RUN",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "sut_git_head": EXPECTED_SUT_HEAD,
        "query_set_sha256": _sha_file(output_dir / "query_set.jsonl"),
        "gold_sha256": _sha_file(output_dir / "gold.jsonl"),
        "split_manifest_sha256": _sha_file(output_dir / "split_manifest.json"),
        "retrieval_config_sha256": _sha_file(output_dir / "retrieval_config.json"),
        "runner_sha256": _sha_file(RUNNER_PATH),
        "source_artifact_sha256": {str(path.relative_to(PROJECT_ROOT)): _sha_file(path) for path in source_paths},
        "retrieval_snapshot_identity": c6._snapshot_identity(),
        "kg_snapshot_identity": c6._kg_identity(),
        "query_count": 42,
        "sealed_query_count": 14,
        "sealed_run_count": 0,
        "sealed_validation_used_for_tuning": False,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _validate_prepared(output_dir: Path) -> dict[str, Any]:
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    checks = {
        "query_set_sha256": output_dir / "query_set.jsonl",
        "gold_sha256": output_dir / "gold.jsonl",
        "split_manifest_sha256": output_dir / "split_manifest.json",
        "retrieval_config_sha256": output_dir / "retrieval_config.json",
        "runner_sha256": RUNNER_PATH,
    }
    for field, path in checks.items():
        if manifest[field] != _sha_file(path):
            raise RuntimeError(f"prepared C7 artifact drift: {field}")
    for rel, digest in manifest["source_artifact_sha256"].items():
        if _sha_file(PROJECT_ROOT / rel) != digest:
            raise RuntimeError(f"frozen C7 source drift: {rel}")
    if manifest["retrieval_snapshot_identity"] != c6._snapshot_identity():
        raise RuntimeError("retrieval snapshot identity drift")
    if manifest["kg_snapshot_identity"] != c6._kg_identity():
        raise RuntimeError("Scientific KG snapshot identity drift")
    if (output_dir / "run_completed.json").exists() or (output_dir / "per_query_results.jsonl").exists():
        raise FileExistsError("C7 is write-once and has already run")
    return manifest


def _request(query: dict[str, Any], profile: Profile) -> HybridRetrievalRequest:
    return HybridRetrievalRequest(
        query=query["query"],
        top_k=TOP_K,
        include_catalog=False,
        enable_sparse=profile.sparse,
        enable_dense=profile.dense,
        nonblocking_dense=False,
        use_kg=profile.kg,
        use_governance_rerank=profile.governance,
        use_contract_gate=False,
    )


def _evaluate(query: dict[str, Any], gold: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = set(gold["accepted_chunk_ids"])
    ranks = [index for index, hit in enumerate(hits[:TOP_K], 1) if hit["chunk_id"] in accepted]
    first = min(ranks) if ranks else None
    abstained = len(hits) == 0
    answerable = bool(gold["evidence_available"])
    return {
        "query_id": query["query_id"],
        "split": query["split"],
        "category": query["category"],
        "query_type": query["query_type"],
        "evidence_available": answerable,
        "expected_abstention": gold["expected_abstention"],
        "hit_at_5": int(bool(first and first <= 5)) if answerable else None,
        "hit_at_10": int(bool(first and first <= 10)) if answerable else None,
        "reciprocal_rank_at_10": (round(1.0 / first, 8) if answerable and first and first <= 10 else (0.0 if answerable else None)),
        "first_gold_rank": first,
        "system_abstained": abstained,
        "evidence_correctness": int(bool(first and first <= 10)) if answerable else int(abstained),
        "false_certainty_event": bool(gold["expected_abstention"] and not abstained),
        "retrieved": hits[:TOP_K],
    }


def _mean(values: Iterable[float | int | None]) -> float | None:
    kept = [float(value) for value in values if value is not None]
    return round(sum(kept) / len(kept), 6) if kept else None


def aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row["evidence_available"]]
    abstention = [row for row in rows if row["expected_abstention"]]
    return {
        "query_count": len(rows),
        "evidence_available_count": len(answerable),
        "expected_abstention_count": len(abstention),
        "hit_at_5": _mean(row["hit_at_5"] for row in answerable),
        "hit_at_10": _mean(row["hit_at_10"] for row in answerable),
        "mrr_at_10": _mean(row["reciprocal_rank_at_10"] for row in answerable),
        "evidence_correctness": _mean(row["evidence_correctness"] for row in rows),
        "abstention_accuracy": _mean(row["system_abstained"] for row in abstention),
        "false_certainty_events": sum(row["false_certainty_event"] for row in abstention),
        "false_certainty_rate": _mean(row["false_certainty_event"] for row in abstention),
    }


def paired_classification(before: dict[str, Any], after: dict[str, Any]) -> str:
    before_hit = bool(before["hit_at_10"])
    after_hit = bool(after["hit_at_10"])
    before_rank = before["first_gold_rank"] or 10**9
    after_rank = after["first_gold_rank"] or 10**9
    if (not before_hit and after_hit) or (before_hit == after_hit and after_rank < before_rank):
        return "HELPED"
    if (before_hit and not after_hit) or (before_hit == after_hit and after_rank > before_rank):
        return "HURT"
    return "NEUTRAL"


def _kg_diagnostic(service: HybridRetrievalService, query: dict[str, Any]) -> dict[str, Any]:
    inferred_tools = service._named_tools_in_query(query["query"])
    inferred_task = canonical_task_for_text(query["query"])
    task_ids = [inferred_task.task_id] if inferred_task else []
    tools, warning = service._kg_candidates(task_ids=task_ids, explicit_tools=inferred_tools)
    return {
        "query_id": query["query_id"],
        "split": query["split"],
        "inferred_tools": inferred_tools,
        "inferred_task": inferred_task.task_id if inferred_task else None,
        "kg_candidate_tools": sorted(tools),
        "kg_participated": bool(tools),
        "kg_fallback": bool(warning),
        "kg_warning": warning,
    }


def _first_failure(result: dict[str, Any], gold: dict[str, Any]) -> str | None:
    if gold["expected_abstention"]:
        return "FALSE_CERTAINTY_NO_NATIVE_ABSTENTION" if result["false_certainty_event"] else None
    if result["hit_at_10"]:
        return None
    retrieved_ids = {row["chunk_id"] for row in result["retrieved"]}
    if retrieved_ids.intersection(gold["accepted_chunk_ids"]):
        return "EVALUATION_INVARIANT_ERROR"
    return "ACCEPTED_EVIDENCE_RANKED_OUT"


def run(output_dir: Path = OUTPUT_DIR, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    manifest = _validate_prepared(output_dir)
    queries = _json_rows(output_dir / "query_set.jsonl")
    gold_rows = _json_rows(output_dir / "gold.jsonl")
    split = json.loads((output_dir / "split_manifest.json").read_text(encoding="utf-8"))
    split_by_id = {query_id: label for label in ("DEV_CHECK", "SEALED") for query_id in split[label]}
    for query in queries:
        query["split"] = split_by_id[query["query_id"]]
    gold_by_id = {row["query_id"]: row for row in gold_rows}

    _write_json(output_dir / "run_started.json", {
        "schema_version": "sckg-independent-retrieval-run-marker-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "run_count": 1,
        "sealed_run_count": 1,
        "manifest_sha256": _sha_file(output_dir / "manifest.json"),
    })
    encoder = LocalBgeM3Encoder()
    if encoder.model_revision != c6.EXPECTED_MODEL_REVISION:
        raise RuntimeError("dense encoder revision drift")
    service = c6._service(encoder)
    kg_rows = [_kg_diagnostic(service, query) for query in queries]
    all_results: list[dict[str, Any]] = []
    by_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for profile in PROFILES:
        by_profile[profile.profile_id] = {}
        for query in queries:
            response = service.search(_request(query, profile))
            result = _evaluate(query, gold_by_id[query["query_id"]], [hit.model_dump(mode="json") for hit in response.hits])
            result.update({
                "profile_id": profile.profile_id,
                "dense_status": response.dense_status,
                "pipeline": response.pipeline,
                "warnings": response.warnings,
                "latency_ms": response.latency_ms,
            })
            all_results.append(result)
            by_profile[profile.profile_id][query["query_id"]] = result

    failures: list[dict[str, Any]] = []
    for result in all_results:
        cause = _first_failure(result, gold_by_id[result["query_id"]])
        if cause:
            failures.append({
                "query_id": result["query_id"],
                "split": result["split"],
                "profile_id": result["profile_id"],
                "first_cause": cause,
                "first_gold_rank": result["first_gold_rank"],
            })

    graph_rows: list[dict[str, Any]] = []
    diag_by_id = {row["query_id"]: row for row in kg_rows}
    for query in queries:
        qid = query["query_id"]
        if not gold_by_id[qid]["evidence_available"]:
            hybrid_class = "NOT_APPLICABLE"
            bm25_class = "NOT_APPLICABLE"
        else:
            hybrid_class = paired_classification(by_profile["B_bm25_dense"][qid], by_profile["D_scikg_bm25_dense"][qid])
            bm25_class = paired_classification(by_profile["A_bm25"][qid], by_profile["C_scikg_bm25"][qid])
        false_filter_hybrid = bool(by_profile["B_bm25_dense"][qid]["hit_at_10"] and not by_profile["D_scikg_bm25_dense"][qid]["hit_at_10"])
        false_filter_bm25 = bool(by_profile["A_bm25"][qid]["hit_at_10"] and not by_profile["C_scikg_bm25"][qid]["hit_at_10"])
        graph_rows.append({
            **diag_by_id[qid],
            "bm25_pair_classification": bm25_class,
            "hybrid_pair_classification": hybrid_class,
            "false_filter_bm25": false_filter_bm25,
            "false_filter_hybrid": false_filter_hybrid,
            "false_filter_event": false_filter_bm25 or false_filter_hybrid,
            "A_first_gold_rank": by_profile["A_bm25"][qid]["first_gold_rank"],
            "B_first_gold_rank": by_profile["B_bm25_dense"][qid]["first_gold_rank"],
            "C_first_gold_rank": by_profile["C_scikg_bm25"][qid]["first_gold_rank"],
            "D_first_gold_rank": by_profile["D_scikg_bm25_dense"][qid]["first_gold_rank"],
        })

    metrics: dict[str, Any] = {}
    for profile in PROFILES:
        rows = [row for row in all_results if row["profile_id"] == profile.profile_id]
        metrics[profile.profile_id] = {
            label: aggregate(rows if label == "ALL" else [row for row in rows if row["split"] == label])
            for label in ("ALL", "DEV_CHECK", "SEALED")
        }
    hybrid_counts = Counter(row["hybrid_pair_classification"] for row in graph_rows if row["hybrid_pair_classification"] != "NOT_APPLICABLE")
    bm25_counts = Counter(row["bm25_pair_classification"] for row in graph_rows if row["bm25_pair_classification"] != "NOT_APPLICABLE")
    graph_summary = {
        "hybrid_pair_B_to_D": {key: hybrid_counts.get(key, 0) for key in ("HELPED", "NEUTRAL", "HURT")},
        "bm25_pair_A_to_C": {key: bm25_counts.get(key, 0) for key in ("HELPED", "NEUTRAL", "HURT")},
        "kg_participation_count": sum(row["kg_participated"] for row in graph_rows),
        "kg_participation_rate": round(sum(row["kg_participated"] for row in graph_rows) / len(graph_rows), 6),
        "kg_fallback_count": sum(row["kg_fallback"] for row in graph_rows),
        "false_filter_events": sum(row["false_filter_event"] for row in graph_rows),
        "false_filter_query_ids": [row["query_id"] for row in graph_rows if row["false_filter_event"]],
    }
    report = {
        "schema_version": "sckg-independent-retrieval-report-v1",
        "status": "COMPLETE",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "interpretation_boundary": "A faithful one-pass independent validation; poor metrics are findings and were not tuned away. The retrieval API has no native abstention signal, so zero returned hits is the declared strict proxy.",
        "query_count": len(queries),
        "sealed_query_count": len(split["SEALED"]),
        "sealed_validation_used_for_tuning": False,
        "sealed_run_count": 1,
        "frozen_identities": {
            "sut_git_head": manifest["sut_git_head"],
            "query_set_sha256": manifest["query_set_sha256"],
            "gold_sha256": manifest["gold_sha256"],
            "split_manifest_sha256": manifest["split_manifest_sha256"],
            "retrieval_config_sha256": manifest["retrieval_config_sha256"],
            "retrieval_snapshot_identity": manifest["retrieval_snapshot_identity"],
            "kg_snapshot_identity": manifest["kg_snapshot_identity"],
        },
        "metrics": metrics,
        "scientific_kg": graph_summary,
        "failure_count": len(failures),
        "failure_counts": dict(sorted(Counter(row["first_cause"] for row in failures).items())),
    }
    _write_jsonl(output_dir / "per_query_results.jsonl", all_results)
    _write_jsonl(output_dir / "graph_participation.jsonl", graph_rows)
    _write_jsonl(output_dir / "failure_register.jsonl", failures)
    _write_json(output_dir / "report.json", report)
    _write_json(output_dir / "run_completed.json", {
        "schema_version": "sckg-independent-retrieval-run-marker-v1",
        "status": "COMPLETE",
        "completed_at": report["completed_at"],
        "run_count": 1,
        "sealed_run_count": 1,
        "sealed_validation_used_for_tuning": False,
        "report_sha256": _sha_file(output_dir / "report.json"),
    })
    _write_report(report_path, report)
    return report


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _write_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Independent Retrieval Validation v1",
        "",
        "Status: **COMPLETE**. The 42 parent scientific information needs, gold alternatives, 28/14 split, profiles, SUT, index, and KG identities were frozen before the single sealed execution. SEALED was not used for tuning.",
        "",
        f"- Frozen SUT Git HEAD: `{report['frozen_identities']['sut_git_head']}`",
        f"- Query count: {report['query_count']}",
        f"- SEALED query count: {report['sealed_query_count']}",
        "- SEALED validation used for tuning: `false`",
        "- SEALED run count: `1`",
        "",
        "## Metrics",
        "",
        "Hit@k and MRR@10 use only evidence-available parent queries. Evidence correctness also includes expected-abstention cases. Since the retrieval API has no native abstain field, zero returned hits is the strict observable proxy; returning any candidate for an unsupported query is counted as a false-certainty event.",
        "",
        "| Profile | Split | n | answerable | Hit@5 | Hit@10 | MRR@10 | Evidence correctness | False certainty |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile, splits in report["metrics"].items():
        for label, metric in splits.items():
            lines.append(f"| {profile} | {label} | {metric['query_count']} | {metric['evidence_available_count']} | {_fmt(metric['hit_at_5'])} | {_fmt(metric['hit_at_10'])} | {_fmt(metric['mrr_at_10'])} | {_fmt(metric['evidence_correctness'])} | {metric['false_certainty_events']} |")
    kg = report["scientific_kg"]
    lines.extend([
        "",
        "## Scientific KG paired analysis",
        "",
        f"- Hybrid B→D: HELPED {kg['hybrid_pair_B_to_D']['HELPED']}, NEUTRAL {kg['hybrid_pair_B_to_D']['NEUTRAL']}, HURT {kg['hybrid_pair_B_to_D']['HURT']}",
        f"- BM25 A→C: HELPED {kg['bm25_pair_A_to_C']['HELPED']}, NEUTRAL {kg['bm25_pair_A_to_C']['NEUTRAL']}, HURT {kg['bm25_pair_A_to_C']['HURT']}",
        f"- KG participation: {kg['kg_participation_count']}/{report['query_count']}",
        f"- KG fallback count: {kg['kg_fallback_count']}",
        f"- False-filter events: {kg['false_filter_events']}",
        "",
        "## Reproducibility boundary",
        "",
        "`manifest.json` is the pre-run freeze record. `run_completed.json` records the only SEALED execution. Gold was manually adjudicated from frozen corpus records without using C7 production retrieval output. Accepted spans within a query are OR alternatives; the parent query remains the statistical unit.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent Retrieval Validation v1")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    value = prepare(args.output) if args.prepare else run(args.output)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
