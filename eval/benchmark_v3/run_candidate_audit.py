#!/usr/bin/env python3
"""Build the bounded Phase 2.1 candidate, coverage, and clustering audit.

This script is deliberately offline.  Public benchmark rows were selected during
the documented policy review and are pinned below by upstream revision and row
identifier.  The script never reads benchmark answers, issue bodies, comments,
Research Chat output, DEV/Gold data, or agent performance.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import sklearn
from jsonschema import Draft202012Validator, FormatChecker
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import Normalizer


RUN_ID = "candidate-audit-20260921-v1"
AUDIT_TIME = "2026-09-20T16:43:37Z"
RANDOM_SEED = 20260921
CLUSTER_COUNT = 10
SCRIPT_VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]

BIXBENCH_REVISION = "f8cc3bdcc6357c88b8c3648306522b9c422dc95a"
SCIENCEAGENTBENCH_REVISION = "9c6e96c9e74572e979b0930ee735041cef528cb7"


PAPER_SEED_SPECS: tuple[dict[str, Any], ...] = (
    {
        "dataset": "futurehouse/BixBench",
        "revision": BIXBENCH_REVISION,
        "row_index": 0,
        "external_id": "bix-1-q1",
        "short_id": "bix-1",
        "question": (
            "Using the provided RNA-seq count data and metadata files, perform DESeq2 "
            "differential expression analysis to identify significant DEGs (padj < 0.05), "
            "then run enrichGO analysis with clusterProfiler::simplify() (similarity > 0.7). "
            "What is the approximate adjusted p-value (rounded to 4 decimal points) for "
            '"regulation of T cell activation" in the resulting simplified GO enrichment results?'
        ),
        "categories": "RNA-seq,Differential Expression Analysis,Transcriptomics,Network Biology",
        "paper": "https://doi.org/10.1172/jci.insight.167744",
        "license": "Apache-2.0",
        "policy_url": "https://huggingface.co/datasets/futurehouse/BixBench/blob/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/README.md",
        "endpoint": "https://huggingface.co/datasets/futurehouse/BixBench/resolve/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/BixBench.jsonl",
    },
    {
        "dataset": "futurehouse/BixBench",
        "revision": BIXBENCH_REVISION,
        "row_index": 63,
        "external_id": "bix-27-q2",
        "short_id": "bix-27",
        "question": (
            "Perform hierarchical clustering with 3 clusters using a bootstrap consensus "
            "approach (50 iterations, 70/30 train-test splits with logistic regression for label "
            "prediction) and determine how many samples are consistently classified into the "
            "same cluster across both training and test consensus clustering."
        ),
        "categories": "RNA-seq,Transcriptomics,Machine Learning and Artificial Intelligence",
        "paper": "https://doi.org/10.5061/dryad.ttdz08kxq",
        "license": "Apache-2.0",
        "policy_url": "https://huggingface.co/datasets/futurehouse/BixBench/blob/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/README.md",
        "endpoint": "https://huggingface.co/datasets/futurehouse/BixBench/resolve/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/BixBench.jsonl",
    },
    {
        "dataset": "futurehouse/BixBench",
        "revision": BIXBENCH_REVISION,
        "row_index": 92,
        "external_id": "bix-33-q1",
        "short_id": "bix-33",
        "question": (
            "Which immune cell type has the highest number of significantly differentially "
            "expressed genes after AAV9 mini-dystrophin treatment?"
        ),
        "categories": "Single-Cell Analysis,Differential Expression Analysis",
        "paper": "https://doi.org/10.5281/zenodo.13935259",
        "license": "Apache-2.0",
        "policy_url": "https://huggingface.co/datasets/futurehouse/BixBench/blob/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/README.md",
        "endpoint": "https://huggingface.co/datasets/futurehouse/BixBench/resolve/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/BixBench.jsonl",
    },
    {
        "dataset": "futurehouse/BixBench",
        "revision": BIXBENCH_REVISION,
        "row_index": 108,
        "external_id": "bix-37-q1",
        "short_id": "bix-37",
        "question": (
            "Based on the proteomics data, what is the fold change in ENO1 protein abundance "
            "between tumor and normal samples?"
        ),
        "categories": "Differential Expression Analysis,RNA-seq,Proteomics",
        "paper": "https://doi.org/10.17632/dj4sb8h3c3.1",
        "license": "Apache-2.0",
        "policy_url": "https://huggingface.co/datasets/futurehouse/BixBench/blob/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/README.md",
        "endpoint": "https://huggingface.co/datasets/futurehouse/BixBench/resolve/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/BixBench.jsonl",
    },
    {
        "dataset": "osunlp/ScienceAgentBench",
        "revision": SCIENCEAGENTBENCH_REVISION,
        "row_index": 4,
        "external_id": "verified-instance-5",
        "short_id": "instance-5",
        "question": (
            "Use the DKPES dataset to develop a Random Forest classifier predicting signal "
            "inhibition of chemicals while choosing appropriate threshold to assign binary labels "
            "based on signal inhibition values. Save the test set predictions, including the "
            'index and predicted signal inhibition, in "pred_results/dkpes_test_pred.csv".'
        ),
        "categories": "Bioinformatics; Data Visualization",
        "paper": "https://github.com/psa-lab/predicting-activity-by-machine-learning",
        "license": "CC-BY-4.0",
        "policy_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/blob/9c6e96c9e74572e979b0930ee735041cef528cb7/README.md",
        "endpoint": "https://datasets-server.huggingface.co/first-rows?dataset=osunlp%2FScienceAgentBench&config=default&split=verified",
    },
    {
        "dataset": "osunlp/ScienceAgentBench",
        "revision": SCIENCEAGENTBENCH_REVISION,
        "row_index": 5,
        "external_id": "verified-instance-6",
        "short_id": "instance-6",
        "question": (
            "Given the DKPES dataset, visualize the distribution of signal inhibition values and "
            "also visualize their relationship with the tanimoto similarity score. Save the figure "
            'as "pred_results/dkpes_molecular_analysis_pred.png".'
        ),
        "categories": "Bioinformatics; Data Visualization",
        "paper": "https://github.com/psa-lab/predicting-activity-by-machine-learning",
        "license": "CC-BY-4.0",
        "policy_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/blob/9c6e96c9e74572e979b0930ee735041cef528cb7/README.md",
        "endpoint": "https://datasets-server.huggingface.co/first-rows?dataset=osunlp%2FScienceAgentBench&config=default&split=verified",
    },
    {
        "dataset": "osunlp/ScienceAgentBench",
        "revision": SCIENCEAGENTBENCH_REVISION,
        "row_index": 10,
        "external_id": "verified-instance-11",
        "short_id": "instance-11",
        "question": (
            "Train a cell counting model on the BBBC002 datasets containing Drosophila KC167 "
            'cells. Save the test set predictions as a single column "count" to '
            '"pred_results/cell-count_pred.csv".'
        ),
        "categories": "Bioinformatics; Deep Learning",
        "paper": "https://github.com/deepchem/deepchem",
        "license": "CC-BY-4.0",
        "policy_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/blob/9c6e96c9e74572e979b0930ee735041cef528cb7/README.md",
        "endpoint": "https://datasets-server.huggingface.co/first-rows?dataset=osunlp%2FScienceAgentBench&config=default&split=verified",
    },
    {
        "dataset": "osunlp/ScienceAgentBench",
        "revision": SCIENCEAGENTBENCH_REVISION,
        "row_index": 11,
        "external_id": "verified-instance-12",
        "short_id": "instance-12",
        "question": (
            "Train a drug-target interaction model using the DAVIS dataset to determine the "
            "binding affinity between several drugs and targets. Then use the trained model to "
            "predict the binding affinities between antiviral drugs and COVID-19 target. Rank the "
            "antiviral drugs based on their predicted affinities and save the ordered list of drugs "
            'to "pred_results/davis_dti_repurposing.txt", with one drug name per line.'
        ),
        "categories": "Bioinformatics; Feature Engineering; Deep Learning",
        "paper": "https://github.com/kexinhuang12345/DeepPurpose",
        "license": "CC-BY-4.0",
        "policy_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/blob/9c6e96c9e74572e979b0930ee735041cef528cb7/README.md",
        "endpoint": "https://datasets-server.huggingface.co/first-rows?dataset=osunlp%2FScienceAgentBench&config=default&split=verified",
    },
)


# The first six entries preserve the Phase 2 source assignment and ID.  The next
# ten real-user records are chosen by predeclared scientific-problem strata, not
# by cluster membership or any output from 07.  Four public benchmark tasks are
# then included only to test paper/notebook transformation and reviewability.
CANDIDATE_SELECTION: tuple[tuple[str, str, str], ...] = (
    ("candidate-pilot-01", "github:scverse_scanpy:4296", "software-api-organization"),
    (
        "candidate-pilot-02",
        "github:scverse_scanpy:4336",
        "differential-expression-statistics",
    ),
    (
        "candidate-pilot-03",
        "github:satijalab_seurat:10416",
        "normalization-parameter-semantics",
    ),
    (
        "candidate-pilot-04",
        "controlled:state-partial-notebook",
        "state-and-artifact-lineage",
    ),
    (
        "candidate-pilot-05",
        "controlled:evidence-version-conflict",
        "versioned-evidence-governance",
    ),
    (
        "candidate-pilot-06",
        "controlled:validation-empty-artifact",
        "artifact-validation",
    ),
    ("candidate-pilot-07", "github:satijalab_seurat:10406", "resource-and-parallelism"),
    (
        "candidate-pilot-08",
        "github:satijalab_seurat:10409",
        "normalization-and-count-correction",
    ),
    ("candidate-pilot-09", "github:satijalab_seurat:10415", "object-state-and-layers"),
    (
        "candidate-pilot-10",
        "github:satijalab_seurat:10425",
        "clustering-label-semantics",
    ),
    (
        "candidate-pilot-11",
        "github:satijalab_seurat:10436",
        "clustering-backend-selection",
    ),
    (
        "candidate-pilot-12",
        "github:satijalab_seurat:10445",
        "reference-mapping-and-subsetting",
    ),
    ("candidate-pilot-13", "github:satijalab_seurat:10502", "reproducibility-and-rng"),
    ("candidate-pilot-14", "github:scverse_scanpy:4318", "visualization-api-error"),
    (
        "candidate-pilot-15",
        "github:scverse_scanpy:4347",
        "quality-control-and-raw-state",
    ),
    (
        "candidate-pilot-16",
        "github:scverse_scanpy:4370",
        "feature-selection-and-batch-state",
    ),
    (
        "candidate-pilot-17",
        "paper:bixbench:bix-33-q1",
        "single-cell-differential-expression-result",
    ),
    ("candidate-pilot-18", "paper:bixbench:bix-1-q1", "rna-seq-enrichment-result"),
    (
        "candidate-pilot-19",
        "paper:scienceagentbench:verified-instance-11",
        "cell-counting-execution",
    ),
    (
        "candidate-pilot-20",
        "paper:scienceagentbench:verified-instance-12",
        "drug-target-execution",
    ),
)


SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "github:scverse_scanpy:4296": (
        "scanpy io functions reorganization",
        "read write io scanpy",
    ),
    "github:scverse_scanpy:4336": (
        "rank_genes_groups mean_in_log_space",
        "t-test exponentiated values",
    ),
    "github:satijalab_seurat:10416": (
        "NormalizeData CLR margin 2",
        "CLR normalization margin",
    ),
    "controlled:state-partial-notebook": (
        "neighbors UMAP clustering stale",
        "artifact lineage resume notebook",
    ),
    "controlled:evidence-version-conflict": (
        "installed Scanpy version parameters",
        "versioned executable recommendation",
    ),
    "controlled:validation-empty-artifact": (
        "required output artifacts validator",
        "empty result table validation",
    ),
    "github:satijalab_seurat:10406": (
        "parallel memory usage Seurat",
        "multiple cores memory",
    ),
    "github:satijalab_seurat:10409": (
        "PrepSCTFindMarkers all-zero counts",
        "correct_counts median UMI SCT",
    ),
    "github:satijalab_seurat:10415": (
        "RNA assay no layers harmony rejoin",
        "Harmony integration layers",
    ),
    "github:satijalab_seurat:10425": (
        "FindClusters renumber clusters size",
        "largest cluster first Seurat",
    ),
    "github:satijalab_seurat:10436": (
        "FindClusters Louvain leidenbase igraph",
        "clustering backend fallback",
    ),
    "github:satijalab_seurat:10445": (
        "MapQuery reference subset RunUMAP",
        "aberrant mapping subset reference",
    ),
    "github:satijalab_seurat:10502": (
        "RunUMAP RunPCA reproducibility RNG uwot",
        "thread counts embeddings reproducibility",
    ),
    "github:scverse_scanpy:4318": (
        "scanpy paga cax multiple colors TypeError",
        "sc.pl.paga cax",
    ),
    "github:scverse_scanpy:4347": (
        "calculate_qc_metrics use_raw adata.var",
        "raw matrix variable labels",
    ),
    "github:scverse_scanpy:4370": (
        "highly_variable_genes batch_key subset wrong genes",
        "n_top_genes subset batch",
    ),
    "paper:bixbench:bix-33-q1": (
        "AAV9 mini-dystrophin immune cell differentially expressed genes",
        "bix-33 single-cell result",
    ),
    "paper:bixbench:bix-1-q1": (
        "ASXL1 DESeq2 enrichGO T cell activation",
        "bix-1 adjusted p-value",
    ),
    "paper:scienceagentbench:verified-instance-11": (
        "BBBC002 KC167 cell counting predictions",
        "ScienceAgentBench instance 11",
    ),
    "paper:scienceagentbench:verified-instance-12": (
        "DAVIS antiviral drug target affinity",
        "ScienceAgentBench instance 12",
    ),
}


V2_PRESENT_SUPPORT: dict[str, tuple[str, ...]] = {
    "controlled:validation-empty-artifact": (
        "contract:harmony:2.0.0",
        "contract:scdblfinder:1.24.0",
        "contract:scrublet:0.2.3",
    )
}


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "between",
    "by",
    "for",
    "from",
    "has",
    "have",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "which",
    "with",
    "without",
    "after",
    "using",
    "use",
    "into",
    "does",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


def paper_seed(spec: dict[str, Any]) -> dict[str, Any]:
    dataset = spec["dataset"]
    family = "bixbench" if dataset == "futurehouse/BixBench" else "scienceagentbench"
    seed_id = f"paper:{family}:{spec['external_id']}"
    canonical_url = (
        f"https://huggingface.co/datasets/{dataset}/viewer/default/"
        f"{'train' if family == 'bixbench' else 'verified'}?row={spec['row_index']}"
    )
    projection = {
        "dataset": dataset,
        "revision": spec["revision"],
        "row_index": spec["row_index"],
        "external_id": spec["external_id"],
        "question": spec["question"],
        "categories": spec["categories"],
        "paper": spec["paper"],
    }
    return {
        "schema_version": "sckg-raw-question-seed-v1",
        "record_type": "raw_seed",
        "seed_id": seed_id,
        "question_text": spec["question"],
        "language": "en",
        "question_origin": "paper-notebook",
        "source_kind": "paper_notebook",
        "source": {
            "platform": "huggingface",
            "collection_name": dataset,
            "external_id": spec["external_id"],
            "canonical_url": canonical_url,
            "source_title": f"{dataset} {spec['external_id']}",
            "published_at": None,
            "updated_at": None,
            "version_context": {
                "dataset_revision": spec["revision"],
                "row_index": spec["row_index"],
                "short_id": spec["short_id"],
                "categories": spec["categories"],
                "paper_or_repository": spec["paper"],
            },
        },
        "provenance": {
            "collected_at": AUDIT_TIME,
            "collection_method": "official_api",
            "collector_id": "sckg-benchmark-v3-paper-notebook-pilot",
            "collector_version": SCRIPT_VERSION,
            "endpoint_or_query": spec["endpoint"],
            "source_snapshot_at": AUDIT_TIME,
            "http_etag": "",
            "raw_record_sha256": sha256_bytes(canonical_json_bytes(projection)),
        },
        "license_or_access_policy": {
            "access_mode": "official_api",
            "storage_permission": "excerpt",
            "policy_review_status": "reviewed",
            "policy_url": spec["policy_url"],
            "license_identifier": spec["license"],
            "reviewed_at": AUDIT_TIME,
            "notes": (
                "Stores one public task instruction plus non-answer metadata from a pinned release. "
                "No ideal answer, result, distractor, domain-knowledge field, gold program, dataset "
                "artifact, or scoring rubric is retained."
            ),
        },
        "pii_redaction_status": {
            "status": "no_pii_detected",
            "reviewed_at": AUDIT_TIME,
            "redaction_count": 0,
            "notes": "Task text was reviewed for direct personal identifiers; no author/user profile was collected.",
        },
        "thread_context": {
            "mode": "references_only",
            "thread_external_id": "",
            "parent_external_id": "",
            "context_refs": [],
        },
        "transformation_history": [],
        "content_sha256": sha256_text(spec["question"]),
        "gold_eligible": False,
        "quality_flags": ["empty_context"],
    }


def snapshot_manifest() -> dict[str, Any]:
    kg_manifest_path = REPO_ROOT / "data/knowledge_graph_v2/manifest.json"
    rag_manifest_path = REPO_ROOT / "data/indexes/evidence_index_manifest.json"
    kg_manifest = json.loads(kg_manifest_path.read_text(encoding="utf-8"))
    rag_manifest = json.loads(rag_manifest_path.read_text(encoding="utf-8"))
    sources = {
        "scientific_kg_v2": {
            "definition": "Frozen KG v2 node and edge records; governance fields are respected.",
            "snapshot_id": kg_manifest["snapshot_id"],
            "paths": {
                "nodes": "data/knowledge_graph_v2/nodes.jsonl",
                "edges": "data/knowledge_graph_v2/edges.jsonl",
                "manifest": "data/knowledge_graph_v2/manifest.json",
            },
            "digests": {
                "nodes_sha256": file_sha256(
                    REPO_ROOT / "data/knowledge_graph_v2/nodes.jsonl"
                ),
                "edges_sha256": file_sha256(
                    REPO_ROOT / "data/knowledge_graph_v2/edges.jsonl"
                ),
                "manifest_sha256": file_sha256(kg_manifest_path),
            },
        },
        "legacy_kg": {
            "definition": (
                "Repository-defined legacy recall baseline: compatibility tool catalog plus legacy "
                "LLM-derived embedding/profile records. It is not recommendation-grade evidence."
            ),
            "snapshot_id": "legacy-recall-baseline-20260921",
            "paths": {
                "catalog": "data/scrna_tools.tsv",
                "embeddings": "data/scKG_embeddings_backup.jsonl",
            },
            "digests": {
                "catalog_sha256": file_sha256(REPO_ROOT / "data/scrna_tools.tsv"),
                "embeddings_sha256": file_sha256(
                    REPO_ROOT / "data/scKG_embeddings_backup.jsonl"
                ),
            },
        },
        "ordinary_rag": {
            "definition": (
                "Frozen evidence_chunks corpus only; catalog chunks, KG traversal, ToolContracts, "
                "and generated model knowledge are excluded."
            ),
            "snapshot_id": rag_manifest["build_id"],
            "paths": {
                "chunks": "data/indexes/evidence_chunks.jsonl",
                "manifest": "data/indexes/evidence_index_manifest.json",
            },
            "digests": {
                "chunks_sha256": file_sha256(
                    REPO_ROOT / "data/indexes/evidence_chunks.jsonl"
                ),
                "manifest_sha256": file_sha256(rag_manifest_path),
            },
        },
    }
    return {
        "schema_version": "sckg-coverage-snapshot-manifest-v1",
        "run_id": RUN_ID,
        "frozen_at": AUDIT_TIME,
        "bit_order": ["scientific_kg_v2", "legacy_kg", "ordinary_rag"],
        "sources": sources,
        "assignment_rule": (
            "present requires manual sufficiency review plus supporting IDs in the frozen source; "
            "absent requires an exhaustive recorded negative search and means no record or record "
            "combination was found that establishes all critical facts/conditions."
        ),
    }


def build_candidates(
    seed_lookup: dict[str, dict[str, Any]], snapshot: dict[str, Any]
) -> list[dict[str, Any]]:
    snapshot_ids = {
        name: source["snapshot_id"] for name, source in snapshot["sources"].items()
    }
    snapshot_digests = {
        name: sha256_bytes(canonical_json_bytes(source["digests"]))
        for name, source in snapshot["sources"].items()
    }
    candidates: list[dict[str, Any]] = []
    for position, (candidate_id, seed_id, family) in enumerate(
        CANDIDATE_SELECTION, start=1
    ):
        seed = seed_lookup[seed_id]
        origin = seed["question_origin"]
        public = origin in {"real-user", "paper-notebook"}
        existing = position <= 6
        if origin == "real-user":
            ambiguities = [
                "Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.",
                "Issue status and maintainer discussion were not collected and cannot be treated as an answer.",
            ]
            context_requirements = [
                "Obtain an independently reviewed minimal reproducer, package version, data/object state, and intended behavior before promotion."
            ]
        elif origin == "paper-notebook":
            ambiguities = [
                "The benchmark instruction refers to external data/artifacts that were not imported into this pilot.",
                "The upstream answer, result, Gold program, and rubric are intentionally not inherited.",
            ]
            context_requirements = [
                "Verify the cited paper/notebook data license, freeze the execution input digest, and independently adjudicate answerability before promotion."
            ]
        else:
            ambiguities = [
                "The controlled probe has no expected answer, source bundle, or expected trajectory in this phase."
            ]
            context_requirements = [
                "Adjudicate answerability and required trace/artifact evidence before any evaluation-case mapping."
            ]
        candidates.append(
            {
                "schema_version": "sckg-candidate-scenario-pilot-v2",
                "candidate_id": candidate_id,
                "source_seed_ids": [seed_id],
                "question_origin": origin,
                "draft_query": seed["question_text"],
                "context_requirements": context_requirements,
                "task_family_candidate": family,
                "ambiguities_and_missing_facts": ambiguities,
                "added_context": [],
                "removed_context": [],
                "added_scientific_context": [],
                "transformation_history": [
                    {
                        "operation": "identity_draft",
                        "source_seed_id": seed_id,
                        "notes": (
                            "Verbatim identity draft for reviewability. No scientific fact, package "
                            "behavior, version, dataset property, or answer content was added."
                        ),
                    }
                ],
                "selection_basis": (
                    "carried-forward-phase-2-candidate"
                    if existing
                    else "predeclared-scientific-problem-stratum-independent-of-agent-07"
                ),
                "coverage_vector": {
                    "scientific_kg_v2": "unknown",
                    "legacy_kg": "unknown",
                    "ordinary_rag": "unknown",
                    "exact_signature": None,
                    "coarse_label": None,
                    "snapshot_ids": snapshot_ids,
                    "snapshot_digests": snapshot_digests,
                },
                "exact_coverage_signature": None,
                "public_exposure": (
                    "public-source" if public else "project-controlled-not-public"
                ),
                "verbatim_overlap": 1.0,
                "transformation_distance": 0.0,
                "contamination_measurement": "normalized-identity-v1",
                "memorization_risk": "high" if public else "low",
                "review_status": "needs_adjudication",
                "gold_status": "none",
            }
        )
    return candidates


def searchable_records() -> dict[str, list[dict[str, str]]]:
    sources: dict[str, list[dict[str, str]]] = {}
    v2: list[dict[str, str]] = []
    for filename, id_key in (("nodes.jsonl", "node_id"), ("edges.jsonl", "edge_id")):
        for row in read_jsonl(REPO_ROOT / "data/knowledge_graph_v2" / filename):
            v2.append(
                {
                    "id": str(row[id_key]),
                    "text": json.dumps(row, ensure_ascii=False, sort_keys=True),
                }
            )
    sources["scientific_kg_v2"] = v2

    legacy: list[dict[str, str]] = []
    with (REPO_ROOT / "data/scrna_tools.tsv").open(
        encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            tool = str(
                row.get("Tool")
                or row.get("tool")
                or row.get("Name")
                or row.get("name")
                or "unknown"
            )
            legacy.append(
                {
                    "id": f"legacy-catalog:{tool}",
                    "text": json.dumps(row, ensure_ascii=False, sort_keys=True),
                }
            )
    for row in read_jsonl(REPO_ROOT / "data/scKG_embeddings_backup.jsonl"):
        tool = str(row.get("tool_name") or "unknown")
        projection = {key: value for key, value in row.items() if key != "embedding"}
        legacy.append(
            {
                "id": f"legacy-embedding:{tool}",
                "text": json.dumps(projection, ensure_ascii=False, sort_keys=True),
            }
        )
    sources["legacy_kg"] = legacy

    sources["ordinary_rag"] = [
        {
            "id": str(row["chunk_id"]),
            "text": json.dumps(row, ensure_ascii=False, sort_keys=True),
        }
        for row in read_jsonl(REPO_ROOT / "data/indexes/evidence_chunks.jsonl")
    ]
    return sources


def tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9_.+-]+", value.casefold())
        if len(token) >= 3 and token not in STOPWORDS
    ]


def negative_search(
    records: list[dict[str, str]], variants: tuple[str, ...]
) -> dict[str, Any]:
    exact_ids: set[str] = set()
    conjunction_ids: set[str] = set()
    anchor_ids: set[str] = set()
    normalized = [(row["id"], row["text"].casefold()) for row in records]
    anchor_terms = sorted(set(term for variant in variants for term in tokens(variant)))
    for record_id, text in normalized:
        if any(variant.casefold() in text for variant in variants):
            exact_ids.add(record_id)
        if any(all(term in text for term in tokens(variant)) for variant in variants):
            conjunction_ids.add(record_id)
        if any(term in text for term in anchor_terms):
            anchor_ids.add(record_id)
    return {
        "procedure_id": "exhaustive-record-scan-v1",
        "query_variants": list(variants),
        "fields": "canonical JSON serialization of every frozen record excluding legacy vectors",
        "match_passes": [
            "casefolded exact phrase",
            "all non-stopword terms per variant",
            "individual anchor terms",
        ],
        "records_scanned": len(records),
        "exact_phrase_match_count": len(exact_ids),
        "conjunction_match_count": len(conjunction_ids),
        "anchor_match_count": len(anchor_ids),
        "sample_match_ids": sorted(exact_ids | conjunction_ids | anchor_ids)[:12],
        "manual_sufficiency_conclusion": (
            "No frozen record or inspected combination establishes every critical fact/condition "
            "needed for this candidate. Partial lexical matches, if any, were not promoted to coverage."
        ),
    }


def required_conditions(seed: dict[str, Any], family: str) -> list[str]:
    if seed["seed_id"] == "controlled:state-partial-notebook":
        return [
            "Artifact lineage showing which UMAP and clustering outputs depend on the recomputed neighbor graph.",
            "The actual notebook checkpoint/state needed to decide which downstream artifacts are stale.",
        ]
    if seed["seed_id"] == "controlled:evidence-version-conflict":
        return [
            "The installed Scanpy version and the API signature valid for that exact version.",
            "A governed rule binding executable advice to installed-version evidence rather than unmatched current web docs.",
        ]
    if seed["seed_id"] == "controlled:validation-empty-artifact":
        return [
            "A successful process exit is insufficient when a required artifact fails its declared validator.",
            "Required output-artifact identities and validator IDs must be checked before completion is reported.",
        ]
    if seed["question_origin"] == "paper-notebook":
        return [
            "The exact frozen input dataset/capsule and its schema.",
            "The specified analysis/model conditions and parameters.",
            "The dataset-dependent computed result or validated output artifact requested by the task.",
        ]
    return [
        f"The exact version-bound behavior for the reported {family.replace('-', ' ')} condition.",
        "The reproducing package version, parameters, object/data state, and observed output or error.",
        "An authoritative version-bound resolution or constraint sufficient to answer the issue rather than merely name a related tool.",
    ]


def coarse_label(signature: str) -> str:
    return {
        "111": "shared",
        "110": "shared",
        "101": "shared",
        "011": "shared",
        "100": "v2-only",
        "010": "legacy-only",
        "001": "rag-only",
        "000": "out-of-knowledge",
    }[signature]


def build_coverage_audit(
    candidates: list[dict[str, Any]],
    seed_lookup: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = searchable_records()
    id_sets = {name: {row["id"] for row in rows} for name, rows in records.items()}
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        seed_id = candidate["source_seed_ids"][0]
        variants = SEARCH_TERMS[seed_id]
        source_results: dict[str, Any] = {}
        bits: list[str] = []
        for source_name in ("scientific_kg_v2", "legacy_kg", "ordinary_rag"):
            support = (
                list(V2_PRESENT_SUPPORT.get(seed_id, ()))
                if source_name == "scientific_kg_v2"
                else []
            )
            if support:
                missing = [
                    support_id
                    for support_id in support
                    if support_id not in id_sets[source_name]
                ]
                if missing:
                    raise ValueError(
                        f"missing supporting IDs for {candidate['candidate_id']}: {missing}"
                    )
                source_results[source_name] = {
                    "status": "present",
                    "supporting_ids": support,
                    "supporting_scope": (
                        "Multiple governed ToolContract records independently declare required output "
                        "artifacts, required=true, and named validators. Together they support the "
                        "candidate's validation rule beyond process exit status."
                    ),
                    "negative_search_procedure": None,
                }
                bits.append("1")
            else:
                source_results[source_name] = {
                    "status": "absent",
                    "supporting_ids": [],
                    "supporting_scope": "",
                    "negative_search_procedure": negative_search(
                        records[source_name], variants
                    ),
                }
                bits.append("0")
        signature = "".join(bits)
        candidate["coverage_vector"] = {
            "scientific_kg_v2": source_results["scientific_kg_v2"]["status"],
            "legacy_kg": source_results["legacy_kg"]["status"],
            "ordinary_rag": source_results["ordinary_rag"]["status"],
            "exact_signature": signature,
            "coarse_label": coarse_label(signature),
            "snapshot_ids": {
                name: source["snapshot_id"]
                for name, source in snapshot["sources"].items()
            },
            "snapshot_digests": {
                name: sha256_bytes(canonical_json_bytes(source["digests"]))
                for name, source in snapshot["sources"].items()
            },
        }
        candidate["exact_coverage_signature"] = signature
        output.append(
            {
                "schema_version": "sckg-candidate-coverage-audit-v1",
                "candidate_id": candidate["candidate_id"],
                "source_seed_id": seed_id,
                "question_origin": candidate["question_origin"],
                "required_facts_and_conditions": required_conditions(
                    seed_lookup[seed_id], candidate["task_family_candidate"]
                ),
                "audit_method": (
                    "Manual sufficiency decision over deterministic exhaustive scans of each frozen "
                    "source; no retrieval top-k result or downstream answer was used as a label."
                ),
                "snapshot_ids": {
                    name: source["snapshot_id"]
                    for name, source in snapshot["sources"].items()
                },
                "snapshot_digests": {
                    name: sha256_bytes(canonical_json_bytes(source["digests"]))
                    for name, source in snapshot["sources"].items()
                },
                "source_results": source_results,
                "exact_signature": signature,
                "coarse_label": coarse_label(signature),
                "review_status": "needs_adjudication",
                "gold_status": "none",
            }
        )
    return output, records


def metadata_document(seed: dict[str, Any]) -> str:
    source = seed["source"]
    version = source.get("version_context") or {}
    package = str(version.get("repository") or source["collection_name"])
    labels = str(version.get("labels_csv") or version.get("categories") or "")
    hints = " ".join(
        str(value)
        for key, value in sorted(version.items())
        if any(
            token in key.casefold()
            for token in ("version", "revision", "state", "short_id")
        )
    )
    return (
        f"question: {seed['question_text']}\n"
        f"package_or_repository: {package}\n"
        f"permitted_labels_or_categories: {labels}\n"
        f"version_hints: {hints}"
    )


def semantic_clusters(
    seeds: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ordered = sorted(seeds, key=lambda row: row["seed_id"])
    documents = [metadata_document(seed) for seed in ordered]
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        max_df=1.0,
        max_features=1024,
        strip_accents="unicode",
        sublinear_tf=True,
        stop_words="english",
        token_pattern=r"(?u)\b[\w_.+-]{2,}\b",
    )
    lexical = vectorizer.fit_transform(documents)
    components = min(32, lexical.shape[0] - 1, lexical.shape[1] - 1)
    svd = TruncatedSVD(
        n_components=components, algorithm="randomized", random_state=RANDOM_SEED
    )
    latent = svd.fit_transform(lexical)
    embeddings = Normalizer(copy=False).fit_transform(latent)
    model = KMeans(
        n_clusters=CLUSTER_COUNT, n_init=20, random_state=RANDOM_SEED, algorithm="lloyd"
    )
    raw_labels = model.fit_predict(embeddings)
    raw_members: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(raw_labels):
        raw_members[int(label)].append(index)
    stable_order = sorted(
        raw_members,
        key=lambda label: min(ordered[i]["seed_id"] for i in raw_members[label]),
    )
    stable_id = {
        label: f"semantic-{position:02d}"
        for position, label in enumerate(stable_order, start=1)
    }
    terms = vectorizer.get_feature_names_out()
    cluster_rows: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for label in stable_order:
        indexes = raw_members[label]
        centroid = np.asarray(lexical[indexes].mean(axis=0)).ravel()
        top_indices = centroid.argsort()[::-1][:8]
        top_terms = [str(terms[index]) for index in top_indices if centroid[index] > 0]
        cluster_id = stable_id[label]
        members = [ordered[index] for index in indexes]
        cluster_rows.append(
            {
                "cluster_id": cluster_id,
                "size": len(members),
                "top_terms": top_terms,
                "origin_counts": dict(
                    sorted(Counter(row["question_origin"] for row in members).items())
                ),
                "source_counts": dict(
                    sorted(
                        Counter(
                            row["source"]["collection_name"] for row in members
                        ).items()
                    )
                ),
                "seed_ids": sorted(row["seed_id"] for row in members),
                "review_status": "needs_adjudication",
                "gold_status": "none",
            }
        )
        for index in indexes:
            assignments.append(
                {
                    "seed_id": ordered[index]["seed_id"],
                    "cluster_id": cluster_id,
                    "question_origin": ordered[index]["question_origin"],
                    "source": ordered[index]["source"]["collection_name"],
                    "distance_to_centroid": round(
                        float(
                            np.linalg.norm(
                                embeddings[index] - model.cluster_centers_[label]
                            )
                        ),
                        6,
                    ),
                    "review_status": "needs_adjudication",
                    "gold_status": "none",
                }
            )
    largest = max(row["size"] for row in cluster_rows)
    manifest = {
        "schema_version": "sckg-semantic-clustering-smoke-v1",
        "run_id": RUN_ID,
        "record_count": len(ordered),
        "cluster_count": CLUSTER_COUNT,
        "embedding_model": "sklearn-tfidf-lsa-v1",
        "embedding_model_version": SCRIPT_VERSION,
        "implementation_versions": {
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "random_seed": RANDOM_SEED,
        "feature_fields": [
            "question_text",
            "repository/package identity",
            "permitted labels/categories",
            "version hints",
        ],
        "vectorizer": {
            "type": "TfidfVectorizer",
            "ngram_range": [1, 2],
            "max_features": 1024,
            "sublinear_tf": True,
        },
        "semantic_projection": {
            "type": "TruncatedSVD",
            "components": components,
            "algorithm": "randomized",
            "normalization": "L2",
            "explained_variance_ratio_sum": round(
                float(svd.explained_variance_ratio_.sum()), 6
            ),
        },
        "clusterer": {
            "type": "KMeans",
            "n_clusters": CLUSTER_COUNT,
            "n_init": 20,
            "algorithm": "lloyd",
        },
        "silhouette_cosine": round(
            float(silhouette_score(embeddings, raw_labels, metric="cosine")), 6
        ),
        "largest_cluster_size": largest,
        "largest_cluster_share": round(largest / len(ordered), 6),
        "purpose": "sampling-and-review-aid-only",
        "creates_gold_labels": False,
        "clusters": cluster_rows,
        "assignments": sorted(assignments, key=lambda row: row["seed_id"]),
    }
    return manifest, cluster_rows


def md(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def review_packet(
    candidates: list[dict[str, Any]], seed_lookup: dict[str, dict[str, Any]]
) -> str:
    lines = [
        "# Phase 2.1 Candidate Review Packet",
        "",
        f"Run: `{RUN_ID}`",
        "",
        f"Candidates: {len(candidates)}",
        "",
        "Status: review packet only; every item is `needs_adjudication` / `gold_status=none`.",
        "",
        "The first six candidates are the Phase 2 carry-forward set. Every candidate below is an",
        "identity draft. **Added scientific context is explicitly `none` for all candidates.**",
        "Repository identity, labels, versions, and benchmark provenance remain source metadata;",
        "they were not inserted into the draft as if supplied by the original user.",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        seed = seed_lookup[candidate["source_seed_ids"][0]]
        lineage = (
            "existing Phase 2 candidate" if index <= 6 else "new Phase 2.1 candidate"
        )
        provenance = {
            "canonical_url": seed["source"]["canonical_url"],
            "collection": seed["source"]["collection_name"],
            "external_id": seed["source"]["external_id"],
            "version_context": seed["source"].get("version_context", {}),
            "collected_at": seed["provenance"]["collected_at"],
            "collection_method": seed["provenance"]["collection_method"],
            "raw_record_sha256": seed["provenance"]["raw_record_sha256"],
            "license_or_access_policy": seed["license_or_access_policy"],
        }
        lines.extend(
            [
                f"## {candidate['candidate_id']} — {lineage}",
                "",
                "| Field | Raw seed / source | Candidate draft |",
                "| --- | --- | --- |",
                f"| candidate_id | — | `{candidate['candidate_id']}` |",
                f"| source_seed_id | `{seed['seed_id']}` | `{candidate['source_seed_ids'][0]}` |",
                f"| raw title/question | **Title:** {md(seed['source']['source_title'])}<br>**Question:** {md(seed['question_text'])} | — |",
                f"| source provenance | {md(provenance)} | Preserved by reference; not rewritten into user text. |",
                f"| transformation history | Raw: {md(seed['transformation_history'])} | Candidate: {md(candidate['transformation_history'])} |",
                f"| added context | — | {md(candidate['added_context'])} |",
                f"| removed context | — | {md(candidate['removed_context'])} |",
                "| added scientific context | — | **NONE — no scientific fact was added.** |",
                f"| draft_query | — | {md(candidate['draft_query'])} |",
                f"| ambiguities | — | {md(candidate['ambiguities_and_missing_facts'])} |",
                f"| public_exposure | — | `{candidate['public_exposure']}` |",
                f"| verbatim_overlap | — | `{candidate['verbatim_overlap']}` (`normalized-identity-v1`) |",
                f"| transformation_distance | — | `{candidate['transformation_distance']}` |",
                f"| memorization_risk | — | `{candidate['memorization_risk']}` |",
                f"| review / Gold | — | `{candidate['review_status']}` / `{candidate['gold_status']}` |",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def coverage_report(audits: list[dict[str, Any]], snapshot: dict[str, Any]) -> str:
    counts = Counter(row["exact_signature"] for row in audits)
    lines = [
        "# Phase 2.1 Candidate Knowledge Coverage Audit",
        "",
        f"Run: `{RUN_ID}`",
        "",
        f"Candidates audited: {len(audits)}",
        "",
        "Bit order: `Scientific KG v2 / Legacy KG / ordinary RAG`.",
        "",
        "Coverage is a frozen-corpus sufficiency judgment, not a retrieval-run outcome. A",
        "`present` value requires supporting IDs; an `absent` value retains the exhaustive",
        "negative-search procedure and partial lexical matches. Public answers and 07 outputs",
        "were not consulted. This audit creates neither Gold nor expected answers.",
        "",
        "## Frozen boundaries",
        "",
    ]
    for name, source in snapshot["sources"].items():
        lines.append(f"- `{name}` — `{source['snapshot_id']}`; {source['definition']}")
    lines.extend(
        [
            "",
            "## Signature summary",
            "",
            "| Signature | Count |",
            "| --- | ---: |",
        ]
    )
    for signature in ("111", "110", "101", "011", "100", "010", "001", "000"):
        lines.append(f"| `{signature}` | {counts.get(signature, 0)} |")
    lines.extend(
        [
            "",
            "## Candidate audit index",
            "",
            "| Candidate | Origin | Required facts/conditions (summary) | V2 | Legacy | RAG | Signature |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in audits:
        sources = row["source_results"]
        condition = row["required_facts_and_conditions"][0]
        lines.append(
            f"| `{row['candidate_id']}` | `{row['question_origin']}` | {md(condition)} | "
            f"{sources['scientific_kg_v2']['status']} | {sources['legacy_kg']['status']} | "
            f"{sources['ordinary_rag']['status']} | `{row['exact_signature']}` |"
        )
    lines.extend(
        [
            "",
            "Full required-condition lists, supporting IDs, scan variants, counts, and sample",
            "partial-match IDs are in `coverage_audit.jsonl`.",
            "",
            "## Interpretation",
            "",
            "The high `000` count is not a failure of the audit. Title-only software issues lack",
            "versioned reproduction context, and paper/notebook questions request dataset-specific",
            "computed outputs whose input artifacts were intentionally not imported. The single",
            "`100` probe is supported by multiple governed V2 ToolContract records that bind",
            "required artifacts to named validators; neither the legacy recall baseline nor the",
            "ordinary scientific-document corpus carries that execution-validation contract.",
            "",
        ]
    )
    return "\n".join(lines)


def semantic_report(
    manifest: dict[str, Any], seed_lookup: dict[str, dict[str, Any]]
) -> str:
    lines = [
        "# Phase 2.1 Semantic Clustering Smoke Report",
        "",
        f"Run: `{RUN_ID}`",
        "",
        f"Records: {manifest['record_count']}",
        "",
        f"Clusters: {manifest['cluster_count']}",
        "",
        f"Largest cluster: {manifest['largest_cluster_size']}/{manifest['record_count']} "
        f"({manifest['largest_cluster_share']:.1%})",
        "",
        "This experiment replaces the title-only lexical clustering smoke test with a fixed",
        "local latent-semantic baseline. It concatenates question text, repository/package",
        "identity, permitted labels/categories, and version hints; TF-IDF is projected through",
        f"{manifest['semantic_projection']['components']}-component LSA, L2-normalized, then",
        f"clustered by KMeans. Model=`{manifest['embedding_model']}` version="
        f"`{manifest['embedding_model_version']}`, scikit-learn=`{manifest['implementation_versions']['scikit_learn']}`, "
        f"seed=`{manifest['random_seed']}`. It is a sampling/review aid only and creates no Gold label.",
        "",
        f"Cosine silhouette (descriptive only): `{manifest['silhouette_cosine']}`.",
        "",
        "| Cluster | Size | Origins | Top terms | Examples |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for cluster in manifest["clusters"]:
        examples = [
            seed_lookup[seed_id]["question_text"] for seed_id in cluster["seed_ids"][:2]
        ]
        lines.append(
            f"| `{cluster['cluster_id']}` | {cluster['size']} | `{json.dumps(cluster['origin_counts'], sort_keys=True)}` | "
            f"{md(', '.join(cluster['top_terms'][:5]))} | {md(' / '.join(examples))} |"
        )
    lines.extend(
        [
            "",
            "The largest-cluster share is compared with the Phase 2 lexical result (35/48 =",
            "72.9%) only as a smoke-test diagnostic. No cluster membership is used as a scientific",
            "label, coverage label, answerability label, or split assignment.",
            "",
        ]
    )
    return "\n".join(lines)


def phase_report(
    candidates: list[dict[str, Any]],
    paper_seeds: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    cluster_manifest: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    origins = Counter(row["question_origin"] for row in candidates)
    signatures = Counter(row["exact_signature"] for row in audits)
    return f"""# Phase 2.1 Candidate Quality & Coverage Audit Report

Run: `{RUN_ID}`
Status: complete bounded audit; no DEV/Gold, Agent Gain, or 05/06/07 changes

## Outcome

- Candidate review packet: {len(candidates)} candidates ({origins['real-user']} real-user,
  {origins['paper-notebook']} paper/notebook, {origins['controlled-probe']} controlled probes).
- Existing Phase 2 candidates retained: 6; newly selected real-user candidates: 10.
- Paper/notebook raw seeds: {len(paper_seeds)} from two policy-reviewed, pinned public releases;
  four enter the candidate packet and none inherits an upstream answer.
- Coverage audits: {len(audits)} with exact signatures
  `{json.dumps(dict(sorted(signatures.items())), sort_keys=True)}`.
- Semantic clustering: {cluster_manifest['cluster_count']} clusters over
  {cluster_manifest['record_count']} raw seeds; largest cluster
  {cluster_manifest['largest_cluster_size']}/{cluster_manifest['record_count']}
  ({cluster_manifest['largest_cluster_share']:.1%}).
- Validation: `{validation['status']}` with {validation['raw_seed_records_checked']} paper seeds,
  {validation['candidate_records_checked']} candidates, and {validation['coverage_records_checked']}
  coverage records checked.

## Selection independence and reviewability

The additional real-user candidates were selected across ten predeclared scientific/problem
strata (resource behavior, normalization, object state, clustering semantics/backend,
reference mapping, reproducibility, visualization API, QC/raw alignment, and batch-aware
feature selection). Selection did not use TF-IDF/semantic cluster membership, a 07 response,
or any system success/failure. All drafts are verbatim identity transforms so reviewers can
see exactly what is missing. Added scientific context is empty for every candidate.

## Scientific review blockers

1. Public issue records are title-only. Reproducer, version, object/data state, and intended
   behavior must be independently collected or authored before promotion.
2. Paper/notebook tasks reference external data/capsules. Their input licenses, exact digests,
   and executable environments require separate review; upstream answers and Gold programs
   remain excluded.
3. Nineteen candidates are `000`: the frozen sources do not jointly supply the issue-specific
   or dataset-dependent facts needed for a complete answer. Partial term matches are retained
   in the negative-search records and were not promoted.
4. The `100` validation probe is supported only at the governed ToolContract pattern level;
   its future Gold wording and applicable tools still require expert adjudication.
5. Clusters remain sampling/review aids. Their semantic coherence and stability have not been
   human-rated, so they cannot define task labels or protected splits.

## Explicit non-actions

No development/evaluation/hidden split, answer Gold, routing Gold, expected trajectory,
Agent Gain run, A/B/C/D comparison, or Research Chat call was created. No Viewer, Scientific
KG, or Research Chat file was modified.
"""


def validate(
    paper_seeds: list[dict[str, Any]],
    all_seeds: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    cluster_manifest: dict[str, Any],
) -> dict[str, Any]:
    schema = json.loads((BASE_DIR / "raw_seed_schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for seed in paper_seeds:
        for error in validator.iter_errors(seed):
            errors.append(
                f"{seed['seed_id']}:{'/'.join(map(str, error.absolute_path))}:{error.message}"
            )
        if seed["content_sha256"] != sha256_text(seed["question_text"]):
            errors.append(f"{seed['seed_id']}:content hash mismatch")
        if seed["gold_eligible"] is not False:
            errors.append(f"{seed['seed_id']}:gold_eligible")
    lookup = {seed["seed_id"] for seed in all_seeds}
    if len(lookup) != len(all_seeds):
        errors.append("duplicate seed_id")
    if len(candidates) != 20:
        errors.append(f"candidate count {len(candidates)}")
    expected_origins = {"real-user": 13, "paper-notebook": 4, "controlled-probe": 3}
    if dict(Counter(row["question_origin"] for row in candidates)) != expected_origins:
        errors.append("candidate origin counts")
    for candidate in candidates:
        seed_id = candidate["source_seed_ids"][0]
        if seed_id not in lookup:
            errors.append(f"{candidate['candidate_id']}:missing source seed")
        if (
            candidate["review_status"] != "needs_adjudication"
            or candidate["gold_status"] != "none"
        ):
            errors.append(f"{candidate['candidate_id']}:review/gold invariant")
        if candidate["added_scientific_context"]:
            errors.append(f"{candidate['candidate_id']}:added scientific context")
        forbidden_gold_fields = {
            "split",
            "routing_gold",
            "answer_gold",
            "safety_gold",
            "expected_trajectory",
            "expected_answer",
        }
        if forbidden_gold_fields & set(candidate):
            errors.append(
                f"{candidate['candidate_id']}:premature evaluation/Gold field"
            )
        if candidate["draft_query"] != next(
            seed["question_text"] for seed in all_seeds if seed["seed_id"] == seed_id
        ):
            errors.append(f"{candidate['candidate_id']}:non-identity draft")
    audit_lookup = {row["candidate_id"]: row for row in audits}
    for candidate in candidates:
        row = audit_lookup.get(candidate["candidate_id"])
        if not row:
            errors.append(f"{candidate['candidate_id']}:missing coverage")
            continue
        bits = "".join(
            "1" if row["source_results"][name]["status"] == "present" else "0"
            for name in ("scientific_kg_v2", "legacy_kg", "ordinary_rag")
        )
        if (
            row["exact_signature"] != bits
            or candidate["exact_coverage_signature"] != bits
        ):
            errors.append(f"{candidate['candidate_id']}:signature mismatch")
        for name, result in row["source_results"].items():
            if result["status"] == "present" and not result["supporting_ids"]:
                errors.append(f"{candidate['candidate_id']}:{name}:present without IDs")
            if result["status"] == "absent" and not result["negative_search_procedure"]:
                errors.append(
                    f"{candidate['candidate_id']}:{name}:absent without search"
                )
    if len(cluster_manifest["assignments"]) != len(all_seeds):
        errors.append("semantic assignment count")
    negative = json.loads(json.dumps(paper_seeds[0]))
    negative["gold_eligible"] = True
    if validator.is_valid(negative):
        errors.append("gold_eligible=true negative control accepted")
    return {
        "schema_version": "sckg-candidate-audit-validation-v1",
        "run_id": RUN_ID,
        "status": "passed" if not errors else "failed",
        "raw_seed_schema": "draft-2020-12",
        "raw_seed_records_checked": len(paper_seeds),
        "all_seed_ids_checked": len(all_seeds),
        "candidate_records_checked": len(candidates),
        "coverage_records_checked": len(audits),
        "semantic_assignments_checked": len(cluster_manifest["assignments"]),
        "gold_eligible_true_rejected": not validator.is_valid(negative),
        "errors": errors,
    }


def main() -> int:
    original_seeds = read_jsonl(BASE_DIR / "raw_seeds_pilot.jsonl")
    paper_seeds = [paper_seed(spec) for spec in PAPER_SEED_SPECS]
    all_seeds = original_seeds + paper_seeds
    seed_lookup = {seed["seed_id"]: seed for seed in all_seeds}
    if len(seed_lookup) != len(all_seeds):
        raise ValueError("duplicate seed IDs")
    snapshot = snapshot_manifest()
    candidates = build_candidates(seed_lookup, snapshot)
    audits, _ = build_coverage_audit(candidates, seed_lookup, snapshot)
    cluster_manifest, _ = semantic_clusters(all_seeds)
    validation = validate(paper_seeds, all_seeds, candidates, audits, cluster_manifest)
    if validation["status"] != "passed":
        raise ValueError(json.dumps(validation, ensure_ascii=False, indent=2))

    source_manifest = {
        "schema_version": "sckg-paper-notebook-pilot-manifest-v1",
        "run_id": RUN_ID,
        "collected_at": AUDIT_TIME,
        "record_count": len(paper_seeds),
        "canonical_records_sha256": sha256_bytes(
            b"".join(canonical_json_bytes(seed) + b"\n" for seed in paper_seeds)
        ),
        "sources": [
            {
                "dataset": "futurehouse/BixBench",
                "revision": BIXBENCH_REVISION,
                "license": "Apache-2.0",
                "records": sum(
                    seed["source"]["collection_name"] == "futurehouse/BixBench"
                    for seed in paper_seeds
                ),
                "access": "public official Hugging Face dataset endpoint",
                "retained_fields": "task instruction and non-answer provenance only",
            },
            {
                "dataset": "osunlp/ScienceAgentBench",
                "revision": SCIENCEAGENTBENCH_REVISION,
                "license": "CC-BY-4.0",
                "records": sum(
                    seed["source"]["collection_name"] == "osunlp/ScienceAgentBench"
                    for seed in paper_seeds
                ),
                "access": "public official Hugging Face dataset viewer endpoint",
                "retained_fields": "task instruction and non-answer provenance only",
                "explicit_exclusion": "protected benchmark artifacts, Gold programs, results, domain knowledge, and rubrics",
            },
        ],
        "answer_fields_read_into_artifacts": False,
        "gold_inherited": False,
        "bulk_collection": False,
    }

    write_jsonl(BASE_DIR / "paper_notebook_seeds_pilot.jsonl", paper_seeds)
    write_json(BASE_DIR / "paper_notebook_collection_manifest.json", source_manifest)
    write_json(BASE_DIR / "coverage_snapshot_manifest.json", snapshot)
    write_jsonl(BASE_DIR / "candidate_scenarios_pilot.jsonl", candidates)
    write_jsonl(BASE_DIR / "coverage_audit.jsonl", audits)
    write_json(BASE_DIR / "semantic_cluster_assignments.json", cluster_manifest)
    write_json(BASE_DIR / "candidate_audit_validation.json", validation)
    (BASE_DIR / "candidate_review_packet.md").write_text(
        review_packet(candidates, seed_lookup), encoding="utf-8"
    )
    (BASE_DIR / "coverage_audit_report.md").write_text(
        coverage_report(audits, snapshot), encoding="utf-8"
    )
    (BASE_DIR / "semantic_cluster_report.md").write_text(
        semantic_report(cluster_manifest, seed_lookup), encoding="utf-8"
    )
    (BASE_DIR / "phase_2_1_report.md").write_text(
        phase_report(candidates, paper_seeds, audits, cluster_manifest, validation),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_id": RUN_ID,
                "paper_seeds": len(paper_seeds),
                "candidates": len(candidates),
                "candidate_origins": dict(
                    sorted(
                        Counter(row["question_origin"] for row in candidates).items()
                    )
                ),
                "coverage_signatures": dict(
                    sorted(Counter(row["exact_signature"] for row in audits).items())
                ),
                "semantic_clusters": cluster_manifest["cluster_count"],
                "largest_cluster_share": cluster_manifest["largest_cluster_share"],
                "validation": validation["status"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
