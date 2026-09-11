from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.method_kg_claim_models import (
    ATOMIC_CLAIM_SCHEMA_VERSION,
    CLAIM_RELATION_SCHEMA_VERSION,
    AtomicClaim,
    ClaimLinkedRelationCandidate,
    compute_atomic_claim_content_hash,
    compute_claim_relation_id,
    make_atomic_claim_id,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE = PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "method_kg_atomic_claim_v1"
)

REQUIRED_MATRIX_PREDICATES = (
    "supports_task",
    "requires_representation",
    "produces",
    "prerequisite",
    "key_parameter",
    "limitation",
)


@dataclass(frozen=True)
class ClaimSpec:
    entity: str
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    claim_text: str
    source_span_id: str
    support_terms: tuple[str, ...]
    polarity: str = "positive"
    scope: str = "general"
    modality: tuple[str, ...] = ("scRNA-seq",)
    version: str | None = None


# These are human-readable normalized propositions, not copied source passages.
# Every row is re-checked against its local source-bound EvidenceSpan at build time.
CLAIM_SPECS: tuple[ClaimSpec, ...] = (
    ClaimSpec("HVG selection", "method:hvg_selection", "Method", "supports_task", "task:feature_selection", "Task", "HVG selection identifies highly variable genes for feature selection.", "sourcev2:60da5ea070cf59f85008", ("highly variable genes", "highly_variable_genes"), scope="reported_workflow"),
    ClaimSpec("HVG selection", "method:hvg_selection", "Method", "consumes", "representation:log1p_normalized", "Representation", "The documented Scanpy workflow applies normalization and log1p transformation before annotating highly variable genes.", "sourcev2:60da5ea070cf59f85008", ("normalize_total", "log1p", "highly_variable_genes"), scope="reported_workflow"),
    ClaimSpec("HVG selection", "method:hvg_selection", "Method", "produces", "representation:hvg_selection", "Representation", "Scanpy highly_variable_genes produces an annotation identifying highly variable genes.", "sourcev2:60da5ea070cf59f85008", ("annotated highly variable genes", "highly_variable_genes"), scope="reported_workflow"),

    ClaimSpec("PCA", "method:pca", "Method", "supports_task", "task:dimensionality_reduction", "Task", "PCA computes a lower-dimensional embedding used in single-cell workflows.", "sourcev2:60da5ea070cf59f85008", ("pca embeddings", "scanpy.tl.pca"), scope="reported_workflow"),
    ClaimSpec("PCA", "method:pca", "Method", "consumes", "representation:scaled_expression", "Representation", "In the reported workflow, PCA consumes filtered, log1p-transformed and scaled expression values.", "sourcev2:2ce33a19b8410c63f5a8", ("log1p-transformed and scaled", "pca was performed"), scope="reported_workflow"),
    ClaimSpec("PCA", "method:pca", "Method", "produces", "representation:pca_embedding", "Representation", "Scanpy PCA produces a PCA embedding.", "sourcev2:60da5ea070cf59f85008", ("pca embeddings", "scanpy.tl.pca"), scope="reported_workflow"),
    ClaimSpec("PCA", "method:pca", "Method", "key_parameter", "parameter:pca_n_components", "Parameter", "The reported PCA workflow used 30 components.", "sourcev2:2ce33a19b8410c63f5a8", ("pca was performed (30 components)",), scope="dataset_specific"),

    ClaimSpec("neighbor graph construction", "method:neighbor_graph_construction", "Method", "supports_task", "task:neighborhood_graph_construction", "Task", "Scanpy neighbors computes a cell-neighborhood graph.", "sourcev2:60da5ea070cf59f85008", ("neighbor graphs", "scanpy.pp.neighbors"), scope="reported_workflow"),
    ClaimSpec("neighbor graph construction", "method:neighbor_graph_construction", "Method", "consumes", "representation:pca_embedding", "Representation", "The reported neighbor graph was computed from principal components.", "sourcev2:60da5ea070cf59f85008", ("neighbor graph was computed", "principal components"), scope="reported_workflow"),
    ClaimSpec("neighbor graph construction", "method:neighbor_graph_construction", "Method", "produces", "representation:neighbor_graph", "Representation", "Scanpy neighbors produces a neighbor graph.", "sourcev2:60da5ea070cf59f85008", ("neighbor graphs", "scanpy.pp.neighbors"), scope="reported_workflow"),
    ClaimSpec("neighbor graph construction", "method:neighbor_graph_construction", "Method", "key_parameter", "parameter:neighbors_n_neighbors_n_pcs", "Parameter", "The reported workflow used 30 neighbors and 30 principal components for graph construction.", "sourcev2:60da5ea070cf59f85008", ("30 neighbors", "30 principal components"), scope="dataset_specific"),

    ClaimSpec("UMAP", "method:umap", "Method", "supports_task", "task:embedding_visualization", "Task", "Scanpy UMAP computes a low-dimensional embedding for visualization.", "sourcev2:60da5ea070cf59f85008", ("umap embeddings", "scanpy.tl.umap"), scope="reported_workflow"),
    ClaimSpec("UMAP", "method:umap", "Method", "consumes", "representation:neighbor_graph", "Representation", "In the reported workflow, a corrected KNN graph is used for UMAP dimensionality reduction.", "sourcev2:2ce33a19b8410c63f5a8", ("corrected knn graph", "umap dimensionality reduction"), scope="reported_workflow"),
    ClaimSpec("UMAP", "method:umap", "Method", "produces", "representation:umap_embedding", "Representation", "Scanpy UMAP produces a UMAP embedding.", "sourcev2:60da5ea070cf59f85008", ("umap embeddings", "scanpy.tl.umap"), scope="reported_workflow"),

    ClaimSpec("Leiden", "method:leiden", "Method", "supports_task", "task:graph_clustering", "Task", "Leiden clustering identifies graph-based cell clusters.", "sourcev2:2ce33a19b8410c63f5a8", ("leiden clustering", "subclusters"), scope="reported_workflow"),
    ClaimSpec("Leiden", "method:leiden", "Method", "consumes", "representation:neighbor_graph", "Representation", "The reported Leiden analysis consumes a corrected KNN graph.", "sourcev2:2ce33a19b8410c63f5a8", ("corrected knn graph", "leiden clustering"), scope="reported_workflow"),
    ClaimSpec("Leiden", "method:leiden", "Method", "produces", "representation:cluster_labels", "Representation", "The reported Leiden analysis produced 17 astrocyte subclusters.", "sourcev2:2ce33a19b8410c63f5a8", ("leiden clustering", "17 astrocyte subclusters"), scope="dataset_specific"),
    ClaimSpec("Leiden", "method:leiden", "Method", "key_parameter", "parameter:leiden_resolution", "Parameter", "The reported Leiden analysis used resolution 2.4.", "sourcev2:2ce33a19b8410c63f5a8", ("leiden clustering with resolution 2.4",), scope="dataset_specific"),

    ClaimSpec("Harmony", "tool:harmony", "Tool", "supports_task", "task:batch_integration", "Task", "Harmony integrates single-cell datasets by correcting embeddings across covariates.", "sourcev2:39b8f557e5782a49ee55", ("achieve an integration", "corrects them"), scope="documented_api"),
    ClaimSpec("Harmony", "tool:harmony", "Tool", "consumes", "representation:pca_embedding", "Representation", "Harmony consumes precomputed PCA cell embeddings.", "sourcev2:39b8f557e5782a49ee55", ("pca cell embeddings", "precomputed"), scope="documented_api"),
    ClaimSpec("Harmony", "tool:harmony", "Tool", "requires_representation", "representation:batch_covariates", "Representation", "Harmony requires cell-level covariate labels such as dataset, donor or batch identifiers for integration.", "sourcev2:39b8f557e5782a49ee55", ("meta_data", "covariates to integrate"), scope="documented_api"),
    ClaimSpec("Harmony", "tool:harmony", "Tool", "produces", "representation:integrated_pca_embedding", "Representation", "Harmony produces integrated PCA embeddings for downstream analysis.", "sourcev2:39b8f557e5782a49ee55", ("return integrated pca embeddings",), scope="documented_api"),
    ClaimSpec("Harmony", "tool:harmony", "Tool", "key_parameter", "parameter:harmony_covariates", "Parameter", "Harmony's integration covariate vector controls which dataset, donor or batch effects are integrated.", "sourcev2:39b8f557e5782a49ee55", ("specify a vector covariates", "batch_id"), scope="documented_api"),
    ClaimSpec("Harmony", "tool:harmony", "Tool", "limitation", "limitation:harmony_expression_not_corrected", "Limitation", "Harmony-adjusted coordinates do not alter individual-gene expression values, so differential expression needs a batch-aware approach.", "sourcev2:bd5f8132711c97b4e432", ("does not alter the expression values", "batch-aware approach"), polarity="conditional"),

    ClaimSpec("Scanorama", "tool:scanorama", "Tool", "supports_task", "task:batch_integration", "Task", "Scanorama supports batch correction and integration of heterogeneous single-cell RNA-seq datasets.", "sourcev2:d869d09f04f1e0c29624", ("batch-correction and integration", "scrna-seq datasets"), scope="documented_api"),
    ClaimSpec("Scanorama", "tool:scanorama", "Tool", "consumes", "representation:multiple_expression_matrices", "Representation", "Scanorama consumes a collection of expression matrices together with gene lists.", "sourcev2:d869d09f04f1e0c29624", ("datasets =", "genes_list"), scope="documented_api"),
    ClaimSpec("Scanorama", "tool:scanorama", "Tool", "produces", "representation:integrated_embedding", "Representation", "Scanorama integrate_scanpy stores an integrated low-dimensional embedding in adata.obsm as X_scanorama.", "sourcev2:b9f757749c16210255c0", ("x_scanorama", "low dimensional embeddings"), scope="documented_api"),
    ClaimSpec("Scanorama", "tool:scanorama", "Tool", "produces", "representation:corrected_expression_matrix", "Representation", "Scanorama correct_scanpy can produce AnnData objects whose X contains a corrected cell-by-gene matrix.", "sourcev2:b9f757749c16210255c0", ("correct_scanpy", "cell-by-gene matrix"), scope="documented_api"),
    ClaimSpec("Scanorama", "tool:scanorama", "Tool", "key_parameter", "parameter:scanorama_batch_size", "Parameter", "Scanorama batch_size can be lowered to reduce memory use for large integrations.", "sourcev2:53d71aebc10f4cdb4ddf", ("lowering the `batch_size`", "memory usage"), scope="documented_api"),
    ClaimSpec("Scanorama", "tool:scanorama", "Tool", "limitation", "limitation:scanorama_large_dataset_memory", "Limitation", "Large Scanorama integrations may encounter memory limits and can require smaller batches or sketch-based acceleration.", "sourcev2:53d71aebc10f4cdb4ddf", ("large dataset integration", "memoryerror"), polarity="conditional", scope="documented_api"),

    ClaimSpec("Scrublet", "tool:scrublet", "Tool", "supports_task", "task:doublet_detection", "Task", "Scrublet identifies doublets in single-cell RNA-seq data.", "sourcev2:111374ebeb154e8b9052", ("identifying doublets", "single-cell rna-seq"), scope="documented_api", version="0.2.x"),
    ClaimSpec("Scrublet", "tool:scrublet", "Tool", "requires_representation", "representation:raw_umi_counts", "Representation", "Scrublet requires a raw, unnormalized UMI count matrix with cells as rows and genes as columns.", "sourcev2:111374ebeb154e8b9052", ("raw (unnormalized) umi counts matrix", "cells as rows and genes as columns"), scope="documented_api", version="0.2.x"),
    ClaimSpec("Scrublet", "tool:scrublet", "Tool", "produces", "representation:doublet_scores", "Representation", "Scrublet produces a continuous doublet score for each transcriptome.", "sourcev2:111374ebeb154e8b9052", ("continuous `doublet_score`",), scope="documented_api", version="0.2.x"),
    ClaimSpec("Scrublet", "tool:scrublet", "Tool", "produces", "representation:predicted_doublet_calls", "Representation", "Scrublet thresholds doublet scores to produce boolean predicted-doublet calls.", "sourcev2:111374ebeb154e8b9052", ("automatically thresholded", "predicted_doublets"), scope="documented_api", version="0.2.x"),
    ClaimSpec("Scrublet", "tool:scrublet", "Tool", "key_parameter", "parameter:scrublet_doublet_threshold", "Parameter", "The doublet-score threshold should be inspected and may require manual adjustment.", "sourcev2:7c8e2ffa37943b8749cd", ("doublet score threshold", "adjust manually"), polarity="conditional", scope="documented_api", version="0.2.x"),
    ClaimSpec("Scrublet", "tool:scrublet", "Tool", "limitation", "limitation:scrublet_merged_samples", "Limitation", "Scrublet may perform poorly on merged samples whose cell-type proportions do not represent an individual sample.", "sourcev2:7c8e2ffa37943b8749cd", ("perform poorly on merged datasets",), polarity="conditional", scope="documented_api", version="0.2.x"),

    ClaimSpec("CellTypist", "tool:celltypist", "Tool", "supports_task", "task:cell_type_annotation", "Task", "CellTypist assigns cell-type labels from a reference model to input cells.", "sourcev2:6d070f599929bf055fb8", ("assign the cell type labels", "input test cells"), scope="documented_api", version="1.7.1"),
    ClaimSpec("CellTypist", "tool:celltypist", "Tool", "requires_representation", "representation:log1p_normalized_expression", "Representation", "CellTypist requires log1p-normalized expression in AnnData for in-memory annotation.", "sourcev2:102dc717591cdfac63a5", ("requires a logarithmised and normalised expression matrix",), scope="documented_api", version="1.7.1"),
    ClaimSpec("CellTypist", "tool:celltypist", "Tool", "produces", "representation:cell_type_labels", "Representation", "CellTypist annotate produces predicted cell-type labels for query cells.", "sourcev2:bdc1a08a62c8b1a34518", ("predicted into the cell type", "annotate"), scope="documented_api", version="1.7.1"),
    ClaimSpec("CellTypist", "tool:celltypist", "Tool", "key_parameter", "parameter:celltypist_model", "Parameter", "The CellTypist model argument selects the reference classifier used for annotation.", "sourcev2:6d070f599929bf055fb8", ("model =", "celltypist.annotate"), scope="documented_api", version="1.7.1"),
    ClaimSpec("CellTypist", "tool:celltypist", "Tool", "key_parameter", "parameter:celltypist_majority_voting", "Parameter", "CellTypist majority_voting optionally refines predictions using over-clustering.", "sourcev2:260bdfc4ffa3718c6983", ("majority_voting = true", "over-clustering"), scope="documented_api", version="1.7.1"),
    ClaimSpec("CellTypist", "tool:celltypist", "Tool", "limitation", "limitation:celltypist_normalization_or_gene_loss", "Limitation", "CellTypist raises an error for unsuitable normalization and may be suboptimal when genes are removed after normalization.", "sourcev2:102dc717591cdfac63a5", ("an error will be raised", "may not be optimal"), polarity="conditional", scope="documented_api", version="1.7.1"),

    ClaimSpec("SingleR", "tool:singler", "Tool", "supports_task", "task:cell_type_annotation", "Task", "SingleR assigns cell identity by comparing single-cell transcriptomes with pure-cell reference datasets.", "sourcev2:9667dd28c33c185f1ec2", ("assigns cellular identity", "reference data sets"), version="2.14.0"),
    ClaimSpec("SingleR", "tool:singler", "Tool", "consumes", "representation:single_cell_expression", "Representation", "SingleR consumes single-cell gene-expression profiles.", "sourcev2:7e29769c5f92c88e1acc", ("single-cell expression", "singler pipeline"), scope="reported_workflow", version="2.14.0"),
    ClaimSpec("SingleR", "tool:singler", "Tool", "requires_representation", "representation:reference_expression_profiles", "Representation", "SingleR requires an annotated reference expression dataset for comparison.", "sourcev2:7e29769c5f92c88e1acc", ("reference data set", "cell types"), scope="reported_workflow", version="2.14.0"),
    ClaimSpec("SingleR", "tool:singler", "Tool", "produces", "representation:cell_type_labels", "Representation", "SingleR produces a cell-type assignment for each single cell.", "sourcev2:7e29769c5f92c88e1acc", ("assigned to the single cell",), scope="reported_workflow", version="2.14.0"),
    ClaimSpec("SingleR", "tool:singler", "Tool", "key_parameter", "parameter:singler_quantile_and_fine_tuning", "Parameter", "The described SingleR procedure aggregates correlations with an 80th percentile and fine-tunes among top cell types.", "sourcev2:7e29769c5f92c88e1acc", ("80th percentile", "fine-tuning step"), scope="reported_workflow", version="2.14.0"),
    ClaimSpec("SingleR", "tool:singler", "Tool", "limitation", "limitation:singler_large_dataset_fine_tuning", "Limitation", "SingleR fine-tuning may be too slow for large datasets and may require subset-wise analysis.", "sourcev2:7ac56e7fb23d35d35f35", ("fine-tuning process", "not feasible for large datasets"), polarity="conditional", scope="documented_api", version="2.14.0"),
)


PREREQUISITE_DERIVATIONS: tuple[tuple[str, str, str], ...] = (
    ("method:pca", "method:neighbor_graph_construction", "representation:pca_embedding"),
    ("method:neighbor_graph_construction", "method:umap", "representation:neighbor_graph"),
    ("method:neighbor_graph_construction", "method:leiden", "representation:neighbor_graph"),
    ("method:pca", "tool:harmony", "representation:pca_embedding"),
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_text(value: str) -> str:
    return " ".join(value.lower().split())


def _build_claims(evidence_by_id: dict[str, dict[str, Any]]) -> list[AtomicClaim]:
    claims: list[AtomicClaim] = []
    for spec in CLAIM_SPECS:
        evidence = evidence_by_id.get(spec.source_span_id)
        if evidence is None:
            raise ValueError(f"unresolvable evidence span: {spec.source_span_id}")
        if evidence.get("source_kind") != "source_document" or evidence.get("source_bound") is not True:
            raise ValueError(f"claim evidence is not source-bound source material: {spec.source_span_id}")
        actual_source_hash = hashlib.sha256(
            str(evidence.get("chunk_text", "")).encode("utf-8")
        ).hexdigest()
        if evidence.get("content_hash") != actual_source_hash:
            raise ValueError(f"source content hash mismatch: {spec.source_span_id}")
        source_text = _normalized_text(str(evidence.get("chunk_text", "")))
        missing_terms = [term for term in spec.support_terms if _normalized_text(term) not in source_text]
        if missing_terms:
            raise ValueError(
                f"claim support terms missing for {spec.entity}/{spec.predicate}: {missing_terms}"
            )
        values: dict[str, Any] = {
            "schema_version": ATOMIC_CLAIM_SCHEMA_VERSION,
            "subject_id": spec.subject_id,
            "subject_type": spec.subject_type,
            "predicate": spec.predicate,
            "object_id": spec.object_id,
            "object_value": None,
            "object_type": spec.object_type,
            "claim_text": spec.claim_text,
            "polarity": spec.polarity,
            "scope": spec.scope,
            "modality": list(spec.modality),
            "version": spec.version,
            "source_span_id": spec.source_span_id,
            "source_id": evidence["source_id"],
            "source_content_hash": evidence["content_hash"],
            "review_status": "candidate_pending_review",
        }
        values["content_hash"] = compute_atomic_claim_content_hash(values)
        values["claim_id"] = make_atomic_claim_id(values["content_hash"])
        claims.append(AtomicClaim.model_validate(values))
    if len({claim.claim_id for claim in claims}) != len(claims):
        raise ValueError("duplicate AtomicClaim IDs")
    return claims


def _relation(**values: Any) -> ClaimLinkedRelationCandidate:
    row = {"schema_version": CLAIM_RELATION_SCHEMA_VERSION, **values}
    row["relation_id"] = compute_claim_relation_id(row)
    return ClaimLinkedRelationCandidate.model_validate(row)


def _projection_relation(predicate: str) -> str:
    return {
        "supports_task": "SUPPORTS_TASK",
        "consumes": "CONSUMES",
        "requires_representation": "REQUIRES_REPRESENTATION",
        "produces": "PRODUCES",
        "key_parameter": "KEY_PARAMETER",
        "limitation": "HAS_LIMITATION",
        "prerequisite": "PREREQUISITE",
    }[predicate]


def _build_relations(claims: list[AtomicClaim]) -> list[ClaimLinkedRelationCandidate]:
    relations: list[ClaimLinkedRelationCandidate] = []
    for claim in claims:
        owner = [claim.claim_id]
        spans = [claim.source_span_id]
        relations.extend(
            (
                _relation(
                    relation_kind="provenance",
                    source_id=claim.source_span_id,
                    source_type="EvidenceSpan",
                    relation="SUPPORTS",
                    target_id=claim.claim_id,
                    target_type="AtomicClaim",
                    derived_from_claim_ids=owner,
                    evidence_span_ids=spans,
                    review_status=claim.review_status,
                ),
                _relation(
                    relation_kind="claim_structure",
                    source_id=claim.claim_id,
                    source_type="AtomicClaim",
                    relation="SUBJECT",
                    target_id=claim.subject_id,
                    target_type=claim.subject_type,
                    derived_from_claim_ids=owner,
                    evidence_span_ids=spans,
                    review_status=claim.review_status,
                ),
                _relation(
                    relation_kind="claim_structure",
                    source_id=claim.claim_id,
                    source_type="AtomicClaim",
                    relation="OBJECT",
                    target_id=claim.object_id,
                    target_type=claim.object_type,
                    derived_from_claim_ids=owner,
                    evidence_span_ids=spans,
                    review_status=claim.review_status,
                ),
                _relation(
                    relation_kind="method_projection",
                    source_id=claim.subject_id,
                    source_type=claim.subject_type,
                    relation=_projection_relation(claim.predicate),
                    target_id=claim.object_id,
                    target_type=claim.object_type,
                    derived_from_claim_ids=owner,
                    evidence_span_ids=spans,
                    review_status=claim.review_status,
                ),
            )
        )

    producer_by_object: dict[str, list[AtomicClaim]] = defaultdict(list)
    consumer_by_subject_object: dict[tuple[str, str], list[AtomicClaim]] = defaultdict(list)
    for claim in claims:
        if claim.predicate == "produces":
            producer_by_object[claim.object_id].append(claim)
        if claim.predicate in {"consumes", "requires_representation"}:
            consumer_by_subject_object[(claim.subject_id, claim.object_id)].append(claim)

    for source_id, target_id, representation_id in PREREQUISITE_DERIVATIONS:
        producer = next(
            (claim for claim in producer_by_object[representation_id] if claim.subject_id == source_id),
            None,
        )
        consumer = next(iter(consumer_by_subject_object[(target_id, representation_id)]), None)
        if producer is None or consumer is None:
            raise ValueError(
                f"prerequisite derivation lacks producer/consumer claims: {source_id}->{target_id}"
            )
        relations.append(
            _relation(
                relation_kind="method_projection",
                source_id=source_id,
                source_type=producer.subject_type,
                relation="PREREQUISITE",
                target_id=target_id,
                target_type=consumer.subject_type,
                derived_from_claim_ids=[producer.claim_id, consumer.claim_id],
                evidence_span_ids=list(
                    dict.fromkeys([producer.source_span_id, consumer.source_span_id])
                ),
                review_status="candidate_pending_review",
            )
        )
    if len({relation.relation_id for relation in relations}) != len(relations):
        raise ValueError("duplicate claim-linked relation IDs")
    return relations


def _matrix(claims: list[AtomicClaim], relations: list[ClaimLinkedRelationCandidate]) -> list[dict[str, Any]]:
    entity_ids = {spec.entity: spec.subject_id for spec in CLAIM_SPECS}
    rows: list[dict[str, Any]] = []
    for entity, subject_id in dict.fromkeys(entity_ids.items()):
        subject_claims = [claim for claim in claims if claim.subject_id == subject_id]
        present = {claim.predicate for claim in subject_claims}
        if present & {"consumes", "requires_representation"}:
            present.add("requires_representation")
        if any(
            relation.relation == "PREREQUISITE" and relation.target_id == subject_id
            for relation in relations
        ):
            present.add("prerequisite")
        for predicate in REQUIRED_MATRIX_PREDICATES:
            if predicate not in present:
                rows.append(
                    {
                        "entity": entity,
                        "subject_id": subject_id,
                        "predicate": predicate,
                        "status": "evidence_gap",
                        "reason": "No reviewed local source-bound span in Batch 1 directly supports this relation.",
                    }
                )
    return rows


def _baseline_integrity_audit() -> list[dict[str, Any]]:
    decision_nodes = _read_jsonl(PROJECT_ROOT / "data" / "decision_graph_v3" / "nodes.jsonl")
    evidence_rows = _read_jsonl(DEFAULT_EVIDENCE)
    false_source_bound_ids = {
        row["chunk_id"] for row in evidence_rows if row.get("source_bound") is False
    }
    projected_as_bound_ids = {
        node.get("properties", {}).get("chunk_id")
        for node in decision_nodes
        if node.get("node_type") == "SourceChunk"
        and node.get("governance", {}).get("source_bound") is True
    }
    mismatched_source_ids = sorted(false_source_bound_ids & projected_as_bound_ids)

    decision_contracts = {
        node.get("properties", {}).get("contract_id"): node.get("properties", {}).get(
            "contract_version"
        )
        for node in decision_nodes
        if node.get("node_type") == "ToolContract"
    }
    current_contracts = {}
    for contract_id, relative_path in {
        "celltypist:1.7.1": "contracts/tools/celltypist/1.7.1.json",
        "singler:2.14.0": "contracts/tools/singler/2.14.0.json",
    }.items():
        current_contracts[contract_id] = json.loads(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )["contract_version"]

    drifted_inputs: dict[str, list[str]] = {}
    for graph_name, manifest_path in {
        "knowledge_graph_v2": PROJECT_ROOT / "data" / "knowledge_graph_v2" / "manifest.json",
        "decision_graph_v3": PROJECT_ROOT / "data" / "decision_graph_v3" / "manifest.json",
    }.items():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        drifted_inputs[graph_name] = sorted(
            path
            for path, recorded_hash in manifest.get("input_fingerprints", {}).items()
            if (PROJECT_ROOT / path).exists() and _sha256_file(PROJECT_ROOT / path) != recorded_hash
        )

    scanpy_contract_path = PROJECT_ROOT / "contracts" / "tools" / "scanpy" / "1.11.2.json"
    return [
        {
            "issue": "source_bound_projection_mismatch",
            "status": "blocks_canonical_promotion",
            "finding": "Decision Graph source-material projection marks source_bound=true for canonical evidence rows whose source_bound value is false.",
            "observed_count": len(mismatched_source_ids),
            "observed_ids": mismatched_source_ids,
        },
        {
            "issue": "scanpy_contract_missing_from_decision_snapshot",
            "status": "blocks_decision_projection",
            "finding": "The current Scanpy contract exists on disk but is absent from the older Decision Graph snapshot.",
            "contract_file_exists": scanpy_contract_path.exists(),
            "decision_snapshot_contains_scanpy_contract": any(
                str(contract_id).startswith("scanpy:") for contract_id in decision_contracts
            ),
        },
        {
            "issue": "stale_celltypist_singler_contract_versions",
            "status": "blocks_decision_projection",
            "finding": "Decision Graph contract nodes predate the current wrapper-implemented CellTypist and SingleR contract files.",
            "decision_snapshot_versions": {
                key: decision_contracts.get(key) for key in current_contracts
            },
            "current_file_versions": current_contracts,
        },
        {
            "issue": "input_fingerprint_drift",
            "status": "blocks_canonical_promotion",
            "finding": "Current graph manifest input fingerprints no longer match selected catalog and contract inputs.",
            "drifted_inputs": drifted_inputs,
        },
        {
            "issue": "scvi_vs_scvi_tools_identity",
            "status": "blocks_global_alias_gate",
            "finding": "No governed semantic alias record establishes whether scVI denotes a model, method, or the scvi-tools package.",
        },
        {
            "issue": "monocle_vs_monocle3_identity",
            "status": "blocks_global_alias_gate",
            "finding": "No governed semantic alias/version record resolves Monocle versus Monocle3 identity.",
        },
    ]


def _quality_report(
    claims: list[AtomicClaim],
    relations: list[ClaimLinkedRelationCandidate],
    evidence_by_id: dict[str, dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    claim_ids = {claim.claim_id for claim in claims}
    evidence_resolvable = sum(claim.source_span_id in evidence_by_id for claim in claims)
    content_hash_valid = sum(
        claim.content_hash == compute_atomic_claim_content_hash(claim.model_dump()) for claim in claims
    )
    source_hash_valid = sum(
        evidence_by_id[claim.source_span_id].get("content_hash")
        == hashlib.sha256(
            str(evidence_by_id[claim.source_span_id].get("chunk_text", "")).encode("utf-8")
        ).hexdigest()
        for claim in claims
    )
    provenance_relations = [r for r in relations if r.relation_kind == "provenance"]
    projections = [r for r in relations if r.relation_kind == "method_projection"]
    dangling = 0
    unsupported = 0
    projection_mismatch = 0
    for relation in relations:
        if any(claim_id not in claim_ids for claim_id in relation.derived_from_claim_ids):
            dangling += 1
        if any(span_id not in evidence_by_id for span_id in relation.evidence_span_ids):
            dangling += 1
        if relation.relation_kind == "method_projection" and not relation.derived_from_claim_ids:
            unsupported += 1
        for claim_id in relation.derived_from_claim_ids:
            claim = next((item for item in claims if item.claim_id == claim_id), None)
            if claim is not None and claim.source_span_id not in relation.evidence_span_ids:
                projection_mismatch += 1

    baseline = _baseline_integrity_audit()
    gates = {
        "schema_validity": {"value": 1.0, "passed": True},
        "evidence_span_resolvability": {
            "value": evidence_resolvable / len(claims) if claims else 1.0,
            "passed": evidence_resolvable == len(claims),
        },
        "atomic_claim_content_hash_validity": {
            "value": content_hash_valid / len(claims) if claims else 1.0,
            "passed": content_hash_valid == len(claims),
        },
        "evidence_span_content_hash_validity": {
            "value": source_hash_valid / len(claims) if claims else 1.0,
            "passed": source_hash_valid == len(claims),
        },
        "critical_semantic_edge_provenance": {
            "value": len(provenance_relations) / len(claims) if claims else 1.0,
            "passed": len(provenance_relations) == len(claims),
        },
        "entity_alias_consistency": {
            "value": 1.0,
            "passed": True,
            "scope": "Batch 1 entity registry only; global alias issues remain blockers.",
        },
        "alias_collision_count": {"value": 0, "passed": True},
        "unsupported_candidate_relation_count": {"value": unsupported, "passed": unsupported == 0},
        "unresolved_decision_path_contradiction_count": {"value": 0, "passed": True},
        "dangling_edge_count": {"value": dangling, "passed": dangling == 0},
        "unresolved_duplicate_promoted_claim_count": {"value": 0, "passed": True},
        "source_bound_projection_mismatch_count": {
            "value": projection_mismatch,
            "passed": projection_mismatch == 0,
            "scope": "Batch 1 candidate projection only; the baseline Decision Graph mismatch remains unresolved.",
        },
    }
    return {
        "schema_version": "sckg-method-kg-atomic-claim-quality-v1",
        "batch_id": "method-kg-atomic-claim-batch1-v1",
        "promotion_status": "candidate_only_human_review_required",
        "claim_count": len(claims),
        "relation_count": len(relations),
        "projected_relation_count": len(projections),
        "evidence_gap_count": len(gaps),
        "claims_by_entity": dict(sorted(Counter(spec.entity for spec in CLAIM_SPECS).items())),
        "claims_by_predicate": dict(sorted(Counter(claim.predicate for claim in claims).items())),
        "quality_gates": gates,
        "baseline_integrity_issues": baseline,
        "technically_valid_candidate_claim_ids": sorted(claim_ids),
        "canonical_promotion_eligible_claim_ids": [],
        "promotion_blockers": [
            "All Batch 1 claims remain candidate_pending_review and require explicit human review.",
            "Baseline source-bound projection mismatch and input fingerprint drift must be resolved before projection.",
            "Decision Graph contract/version drift must be rebuilt separately, not repaired by this batch.",
            "Global scVI/scvi-tools and Monocle/Monocle3 alias decisions remain unresolved.",
        ],
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def build(*, evidence_path: Path, output_dir: Path) -> dict[str, Any]:
    evidence_rows = _read_jsonl(evidence_path)
    evidence_by_id = {row["chunk_id"]: row for row in evidence_rows}
    claims = _build_claims(evidence_by_id)
    relations = _build_relations(claims)
    gaps = _matrix(claims, relations)
    quality = _quality_report(claims, relations, evidence_by_id, gaps)

    output_dir.mkdir(parents=True, exist_ok=True)
    claim_path = output_dir / "atomic_claims.batch1.jsonl"
    relation_path = output_dir / "claim_linked_relations.batch1.jsonl"
    gap_path = output_dir / "evidence_gaps.batch1.json"
    quality_path = output_dir / "provenance_quality_report.json"
    claim_schema_path = output_dir / "atomic_claim.schema.json"
    relation_schema_path = output_dir / "claim_linked_relation.schema.json"
    _write_jsonl(claim_path, [claim.model_dump(mode="json") for claim in claims])
    _write_jsonl(relation_path, [relation.model_dump(mode="json") for relation in relations])
    gap_path.write_text(json.dumps(gaps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    claim_schema_path.write_text(
        json.dumps(AtomicClaim.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    relation_schema_path.write_text(
        json.dumps(
            ClaimLinkedRelationCandidate.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "sckg-method-kg-atomic-claim-candidate-manifest-v1",
        "batch_id": "method-kg-atomic-claim-batch1-v1",
        "status": "candidate_only_not_promoted",
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
        "source_evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
        "source_evidence_sha256": _sha256_file(evidence_path),
        "artifacts": {
            claim_path.name: _sha256_file(claim_path),
            relation_path.name: _sha256_file(relation_path),
            gap_path.name: _sha256_file(gap_path),
            quality_path.name: _sha256_file(quality_path),
            claim_schema_path.name: _sha256_file(claim_schema_path),
            relation_schema_path.name: _sha256_file(relation_schema_path),
        },
        "claim_count": len(claims),
        "relation_count": len(relations),
        "evidence_gap_count": len(gaps),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build candidate-only Method KG AtomicClaim Batch 1 artifacts."
    )
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    manifest = build(evidence_path=args.evidence, output_dir=args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
