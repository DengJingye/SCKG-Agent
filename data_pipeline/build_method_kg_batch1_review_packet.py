from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.method_kg_claim_models import AtomicClaim, ClaimLinkedRelationCandidate
from data_pipeline.build_method_kg_atomic_claim_batch1 import (
    CLAIM_SPECS,
    DEFAULT_EVIDENCE,
    DEFAULT_OUTPUT_DIR,
    PROJECT_ROOT,
    _build_claims,
    _read_jsonl,
)


REVIEW_TABLE_FIELDS = (
    "claim_id",
    "subject_id",
    "subject",
    "predicate",
    "object_id",
    "object",
    "claim_text",
    "source_document_id",
    "source_document",
    "source_type",
    "source_authority",
    "authority_tier",
    "source_span_id",
    "exact_evidence_locator",
    "source_local_wording",
    "scope",
    "modality",
    "version",
    "projected_kg_relation",
    "derived_relation_ids",
    "alias_version_ambiguity",
    "alias_version_note",
    "multi_entity_evidence",
    "evidence_entities",
    "possible_contradiction",
    "contradiction_note",
    "review_risk",
    "review_risk_reasons",
    "review_decision",
    "reviewer_reason",
)

CHAIN_FIELDS = (
    "prerequisite_relation_id",
    "producer_claim_id",
    "producer_subject",
    "produced_representation",
    "producer_evidence_span",
    "consumer_claim_id",
    "consumer_subject",
    "consumer_predicate",
    "consumer_evidence_span",
    "prerequisite_source",
    "prerequisite_target",
    "review_decision",
    "reviewer_reason",
)

SUMMARY_FIELDS = (
    "entity",
    "subject_id",
    "predicate",
    "claim_count",
    "evidence_sources",
    "review_risk",
    "risk_reasons",
)

_ENTITY_LABELS = {
    "method:hvg_selection": "HVG selection",
    "method:pca": "PCA",
    "method:neighbor_graph_construction": "neighbor graph construction",
    "method:umap": "UMAP",
    "method:leiden": "Leiden",
    "tool:harmony": "Harmony",
    "tool:scanorama": "Scanorama",
    "tool:scrublet": "Scrublet",
    "tool:celltypist": "CellTypist",
    "tool:singler": "SingleR",
}

_OBJECT_LABELS = {
    "task:feature_selection": "feature selection",
    "task:dimensionality_reduction": "dimensionality reduction",
    "task:neighborhood_graph_construction": "neighborhood graph construction",
    "task:embedding_visualization": "embedding visualization",
    "task:graph_clustering": "graph clustering",
    "task:batch_integration": "batch integration",
    "task:doublet_detection": "doublet detection",
    "task:cell_type_annotation": "cell type annotation",
}

_EVIDENCE_ENTITY_TERMS = {
    "HVG selection": ("highly variable gene", "highly_variable_genes", "hvg"),
    "PCA": ("pca", "principal component"),
    "neighbor graph": ("neighbor graph", "nearest-neighbor graph", "knn graph"),
    "UMAP": ("umap",),
    "Leiden": ("leiden",),
    "Harmony": ("harmony",),
    "Scanorama": ("scanorama",),
    "Scrublet": ("scrublet",),
    "CellTypist": ("celltypist",),
    "SingleR": ("singler",),
    "Scanpy": ("scanpy",),
    "Seurat": ("seurat",),
    "BBKNN": ("bbknn",),
    "CellRank": ("cellrank",),
    "scVelo": ("scvelo", "scvelo"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_tsv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _source_authority(source_type: str) -> str:
    if source_type == "github_readme":
        return "official_project_documentation"
    if source_type == "doi_landing_or_open_html":
        return "primary_or_peer_reviewed_source_document"
    return "source_bound_local_document"


def _bounded_source_wording(text: str, support_terms: tuple[str, ...]) -> str:
    normalized = " ".join(text.split())
    folded = normalized.casefold()
    matches = []
    for term in support_terms:
        index = folded.find(" ".join(term.casefold().split()))
        if index >= 0:
            matches.append((index, index + len(" ".join(term.split()))))
    if not matches:
        raise ValueError("review excerpt cannot locate the claim support terms")
    first = min(start for start, _ in matches)
    last = max(end for _, end in matches)
    start = max(0, first - 220)
    end = min(len(normalized), max(last + 360, start + 500))
    if end - start > 1200:
        end = start + 1200
    excerpt = normalized[start:end].strip()
    if start:
        excerpt = "…" + excerpt
    if end < len(normalized):
        excerpt += "…"
    return excerpt


def _evidence_entities(text: str) -> list[str]:
    folded = text.casefold()
    return [
        label
        for label, terms in _EVIDENCE_ENTITY_TERMS.items()
        if any(term.casefold() in folded for term in terms)
    ]


def _alias_version_note(claim: AtomicClaim) -> tuple[bool, str]:
    if claim.subject_id.startswith("method:"):
        return (
            True,
            "Generic method identity is supported here by a Scanpy workflow/API use and needs scope review before canonical projection.",
        )
    if claim.subject_id in {"tool:celltypist", "tool:singler"}:
        return (
            True,
            "Current contract file version differs from the older Decision Graph contract snapshot.",
        )
    return False, ""


def _contradiction_note(claim: AtomicClaim) -> tuple[bool, str]:
    if claim.scope == "dataset_specific":
        return (
            True,
            "Dataset-specific parameter must not be promoted as a universal default.",
        )
    if claim.subject_id == "tool:celltypist" and claim.predicate == "requires_representation":
        return (
            True,
            "CellTypist documents different normalization expectations for file inputs and in-memory AnnData; input mode must remain explicit.",
        )
    if claim.subject_id == "tool:scanorama" and claim.predicate == "produces":
        return (
            True,
            "Scanorama output differs by API function and return flags; embedding and corrected-matrix claims must remain separate.",
        )
    if claim.subject_id == "tool:harmony" and claim.predicate == "limitation":
        return (
            True,
            "Adjusted-coordinate output must not be interpreted as corrected gene-expression values.",
        )
    return False, ""


def _risk(
    claim: AtomicClaim,
    *,
    multi_entity: bool,
    alias_ambiguity: bool,
    possible_contradiction: bool,
) -> tuple[str, list[str]]:
    reasons = []
    if claim.scope == "dataset_specific":
        reasons.append("dataset_specific_scope")
    elif claim.scope == "reported_workflow":
        reasons.append("reported_workflow_not_universal")
    if multi_entity:
        reasons.append("multi_entity_source_span")
    if alias_ambiguity:
        reasons.append("alias_or_version_scope")
    if possible_contradiction:
        reasons.append("possible_scope_or_output_conflict")
    if claim.predicate == "limitation":
        reasons.append("conditional_limitation_boundary")
    if "dataset_specific_scope" in reasons or "possible_scope_or_output_conflict" in reasons:
        return "high", reasons
    if reasons:
        return "medium", reasons
    return "low", ["direct_source_bound_documented_api_claim"]


def _review_rows(
    claims: list[AtomicClaim],
    relations: list[ClaimLinkedRelationCandidate],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    generated = _build_claims(evidence_by_id)
    spec_by_claim_id = {
        claim.claim_id: spec for claim, spec in zip(generated, CLAIM_SPECS, strict=True)
    }
    projected_by_claim: dict[str, list[ClaimLinkedRelationCandidate]] = defaultdict(list)
    derived_by_claim: dict[str, list[ClaimLinkedRelationCandidate]] = defaultdict(list)
    for relation in relations:
        if relation.relation_kind != "method_projection":
            continue
        if relation.relation == "PREREQUISITE":
            for claim_id in relation.derived_from_claim_ids:
                derived_by_claim[claim_id].append(relation)
        else:
            for claim_id in relation.derived_from_claim_ids:
                projected_by_claim[claim_id].append(relation)

    rows = []
    for claim in claims:
        evidence = evidence_by_id[claim.source_span_id]
        spec = spec_by_claim_id[claim.claim_id]
        entities = _evidence_entities(str(evidence["chunk_text"]))
        multi_entity = len(entities) > 1
        alias_ambiguity, alias_note = _alias_version_note(claim)
        possible_contradiction, contradiction_note = _contradiction_note(claim)
        review_risk, risk_reasons = _risk(
            claim,
            multi_entity=multi_entity,
            alias_ambiguity=alias_ambiguity,
            possible_contradiction=possible_contradiction,
        )
        projection = projected_by_claim[claim.claim_id]
        if len(projection) != 1:
            raise ValueError(f"claim must have exactly one direct projection: {claim.claim_id}")
        rows.append(
            {
                "claim_id": claim.claim_id,
                "subject_id": claim.subject_id,
                "subject": _ENTITY_LABELS[claim.subject_id],
                "predicate": claim.predicate,
                "object_id": claim.object_id or "",
                "object": _OBJECT_LABELS.get(claim.object_id or "", (claim.object_id or "").split(":", 1)[-1]),
                "claim_text": claim.claim_text,
                "source_document_id": claim.source_id,
                "source_document": evidence["title"],
                "source_type": evidence["source_type"],
                "source_authority": _source_authority(str(evidence["source_type"])),
                "authority_tier": evidence["authority_tier"],
                "source_span_id": claim.source_span_id,
                "exact_evidence_locator": evidence["source_span"],
                "source_local_wording": _bounded_source_wording(
                    str(evidence["chunk_text"]), spec.support_terms
                ),
                "scope": claim.scope,
                "modality": ";".join(claim.modality),
                "version": claim.version or "",
                "projected_kg_relation": projection[0].relation,
                "derived_relation_ids": ";".join(
                    relation.relation_id for relation in derived_by_claim[claim.claim_id]
                ),
                "alias_version_ambiguity": str(alias_ambiguity).lower(),
                "alias_version_note": alias_note,
                "multi_entity_evidence": str(multi_entity).lower(),
                "evidence_entities": ";".join(entities),
                "possible_contradiction": str(possible_contradiction).lower(),
                "contradiction_note": contradiction_note,
                "review_risk": review_risk,
                "review_risk_reasons": ";".join(risk_reasons),
                "review_decision": "",
                "reviewer_reason": "",
            }
        )
    return rows


def _derived_chains(
    claims: list[AtomicClaim], relations: list[ClaimLinkedRelationCandidate]
) -> list[dict[str, Any]]:
    claim_by_id = {claim.claim_id: claim for claim in claims}
    rows = []
    for relation in relations:
        if relation.relation != "PREREQUISITE":
            continue
        producer, consumer = [claim_by_id[claim_id] for claim_id in relation.derived_from_claim_ids]
        if producer.predicate != "produces" or consumer.predicate not in {
            "consumes",
            "requires_representation",
        }:
            raise ValueError(f"invalid prerequisite derivation: {relation.relation_id}")
        if producer.object_id != consumer.object_id:
            raise ValueError(f"prerequisite representation mismatch: {relation.relation_id}")
        rows.append(
            {
                "prerequisite_relation_id": relation.relation_id,
                "producer_claim_id": producer.claim_id,
                "producer_subject": producer.subject_id,
                "produced_representation": producer.object_id,
                "producer_evidence_span": producer.source_span_id,
                "consumer_claim_id": consumer.claim_id,
                "consumer_subject": consumer.subject_id,
                "consumer_predicate": consumer.predicate,
                "consumer_evidence_span": consumer.source_span_id,
                "prerequisite_source": relation.source_id,
                "prerequisite_target": relation.target_id,
                "review_decision": "",
                "reviewer_reason": "",
            }
        )
    if len(rows) != 4:
        raise ValueError("Batch 1 must expose exactly four derived prerequisite chains")
    return rows


def _summary_rows(review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in review_rows:
        grouped[(str(row["subject"]), str(row["subject_id"]), str(row["predicate"]))].append(row)
    result = []
    risk_order = {"low": 0, "medium": 1, "high": 2}
    for (entity, subject_id, predicate), rows in sorted(grouped.items()):
        risk = max((str(row["review_risk"]) for row in rows), key=risk_order.__getitem__)
        result.append(
            {
                "entity": entity,
                "subject_id": subject_id,
                "predicate": predicate,
                "claim_count": len(rows),
                "evidence_sources": ";".join(
                    sorted({f"{row['source_document_id']}|{row['source_document']}" for row in rows})
                ),
                "review_risk": risk,
                "risk_reasons": ";".join(
                    sorted(
                        {
                            reason
                            for row in rows
                            for reason in str(row["review_risk_reasons"]).split(";")
                            if reason
                        }
                    )
                ),
            }
        )
    return result


def _blocker_markdown(quality: dict[str, Any]) -> str:
    issues = {row["issue"]: row for row in quality["baseline_integrity_issues"]}
    drift = issues["input_fingerprint_drift"]["drifted_inputs"]
    mismatch = issues["source_bound_projection_mismatch"]
    versions = issues["stale_celltypist_singler_contract_versions"]
    return f"""# Method KG Batch 1 Promotion Blocker Checklist

Status: candidate-only; no item is resolved by this packet.

- [ ] **source_bound projection mismatch** — {mismatch['observed_count']} canonical evidence rows with `source_bound=false` are projected as bound in the current Decision Graph. IDs remain in `provenance_quality_report.json`.
- [ ] **graph input fingerprint drift** — Knowledge Graph drift: {', '.join(drift['knowledge_graph_v2'])}; Decision Graph drift: {', '.join(drift['decision_graph_v3'])}.
- [ ] **Scanpy contract snapshot missing** — contract file exists, but current Decision Graph contains no Scanpy ToolContract node.
- [ ] **CellTypist / SingleR contract snapshot version drift** — snapshot versions: {json.dumps(versions['decision_snapshot_versions'], sort_keys=True)}; current files: {json.dumps(versions['current_file_versions'], sort_keys=True)}.
- [ ] **scVI / scvi-tools identity** — no governed alias/version decision distinguishes the scVI model/method from the scvi-tools package identity.
- [ ] **Monocle / Monocle3 identity** — no governed alias/version decision resolves these identities.
- [ ] **full regression artifact dependency** — latest run: `729 passed, 38 failed, 8 warnings`. Failures are concentrated in unavailable runtime packs and absent maintainer pilot/package artifacts, producing `runtime_pack_not_ready`, missing dataset-scoped evaluations, and `contract_verified` rather than `decision_ready`. This packet does not alter execution/runtime state.
- [ ] **human adjudication** — all 48 AtomicClaims remain `candidate_pending_review`; reviewer decisions and reasons are blank.

Canonical promotion remains blocked until every applicable item is independently resolved and audited.
"""


def build_review_packet(*, candidate_dir: Path, evidence_path: Path) -> dict[str, Any]:
    claim_path = candidate_dir / "atomic_claims.batch1.jsonl"
    relation_path = candidate_dir / "claim_linked_relations.batch1.jsonl"
    quality_path = candidate_dir / "provenance_quality_report.json"
    claims = [AtomicClaim.model_validate(row) for row in _read_jsonl(claim_path)]
    relations = [
        ClaimLinkedRelationCandidate.model_validate(row) for row in _read_jsonl(relation_path)
    ]
    evidence_by_id = {row["chunk_id"]: row for row in _read_jsonl(evidence_path)}
    review_rows = _review_rows(claims, relations, evidence_by_id)
    chains = _derived_chains(claims, relations)
    summaries = _summary_rows(review_rows)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))

    review_path = candidate_dir / "human_review_batch1.tsv"
    chain_path = candidate_dir / "derived_prerequisite_review.tsv"
    summary_path = candidate_dir / "entity_predicate_review_summary.tsv"
    blocker_path = candidate_dir / "promotion_blocker_checklist.md"
    _write_tsv(review_path, review_rows, REVIEW_TABLE_FIELDS)
    _write_tsv(chain_path, chains, CHAIN_FIELDS)
    _write_tsv(summary_path, summaries, SUMMARY_FIELDS)
    blocker_path.write_text(_blocker_markdown(quality), encoding="utf-8")

    manifest = {
        "schema_version": "sckg-method-kg-batch1-review-packet-v1",
        "status": "human_review_pending",
        "source_claims_sha256": _sha256(claim_path),
        "source_relations_sha256": _sha256(relation_path),
        "claim_count": len(claims),
        "derived_prerequisite_count": len(chains),
        "review_decision_count": sum(bool(row["review_decision"]) for row in review_rows),
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
        "artifacts": {
            review_path.name: _sha256(review_path),
            chain_path.name: _sha256(chain_path),
            summary_path.name: _sha256(summary_path),
            blocker_path.name: _sha256(blocker_path),
        },
    }
    manifest_path = candidate_dir / "review_packet_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Batch 1 human adjudication packet.")
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    manifest = build_review_packet(candidate_dir=args.candidate_dir, evidence_path=args.evidence)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
