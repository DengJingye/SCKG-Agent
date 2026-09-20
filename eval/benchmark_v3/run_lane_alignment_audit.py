#!/usr/bin/env python3
"""Freeze the 07 evaluation lanes and withdraw invalid Phase 2.2 labels.

This is an offline metadata audit.  It reads immutable Git blobs, never calls an
LLM or a Research Chat lane, and never treats retrieval success as coverage.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
INTEGRATION_COMMIT = "5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee"
APPROVED_PACKAGE_COMMIT = "6018699092d979a2da0dda45a19c920018ed9eda"
APPROVED_PACKAGE_PATH = "reconstruction/promotion_v2/snapshots/approved-v2-01"
APPROVED_KG_SHA256 = "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
HELD_STATEMENT_ID = "statement-revision:d0d887b96b7a1cf45e2c47bf:1"
RUN_ID = "lane-alignment-20260921-v2-withdrawal"
HISTORICAL_AUDIT_COMMIT = "810ed0853c763c0a497f74100f7bb8d47ed2e4e8"
FROZEN_AT = "2026-09-21"

RETRIEVAL_ROOT = "data/indexes/retrieval_foundation_v1"
LEGACY_CANDIDATE_ROOT = "data/evidence_candidates/scientific_kg_v1_uat_decision_rules"
LEGACY_INVENTORY_PATH = (
    "data/evidence_candidates/scientific_kg_v1_inventory/"
    "scientific_kg_v1_consolidated_graph.json"
)
LEGACY_GRAPH_ROOT = "data/knowledge_graph_v2"

SHARED_RUNTIME = [
    {
        "component": "Planner",
        "implementation": "agent.research_chat_service.ResearchChatService tool-plan path",
        "coverage_rule": "shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage",
    },
    {
        "component": "ToolContracts",
        "implementation": "contracts/tools plus shared research/execution services",
        "coverage_rule": "shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage",
    },
    {
        "component": "execution guards",
        "implementation": "shared execution policy, authorization, and runtime guards",
        "coverage_rule": "shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage",
    },
    {
        "component": "validation contracts",
        "implementation": "shared artifact and result validation contracts",
        "coverage_rule": "shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage",
    },
    {
        "component": "approval system",
        "implementation": "shared plan-specific approval and approval-consumption path",
        "coverage_rule": "shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage",
    },
]

TRACKS = {
    "candidate-pilot-01": ("O", "API organization issue with insufficient standalone context"),
    "candidate-pilot-02": ("K", "method and condition semantics"),
    "candidate-pilot-03": ("K", "normalization parameter semantics"),
    "candidate-pilot-04": ("W", "notebook state and artifact lineage"),
    "candidate-pilot-05": ("K", "version, scope, and evidence authority"),
    "candidate-pilot-06": ("W", "execution result and artifact validation"),
    "candidate-pilot-07": ("O", "open-world performance and memory issue"),
    "candidate-pilot-08": ("O", "bug report requiring reproducer and data state"),
    "candidate-pilot-09": ("O", "object-state regression issue"),
    "candidate-pilot-10": ("K", "clustering output semantics"),
    "candidate-pilot-11": ("O", "backend-selection bug report"),
    "candidate-pilot-12": ("O", "reference-subsetting regression report"),
    "candidate-pilot-13": ("O", "reproducibility and version-default issue"),
    "candidate-pilot-14": ("O", "plotting API error report"),
    "candidate-pilot-15": ("O", "raw-state alignment bug report"),
    "candidate-pilot-16": ("O", "batch-aware feature-selection bug report"),
    "candidate-pilot-17": ("W", "dataset-dependent scientific analysis"),
    "candidate-pilot-18": ("W", "dataset-dependent multi-step analysis"),
    "candidate-pilot-19": ("W", "model training and output artifact task"),
    "candidate-pilot-20": ("W", "model training, ranking, and artifact task"),
}

# ``standalone_answerable`` evaluates the current identity draft, not whether a
# richer future scenario could become answerable.  The two vague titles are
# deliberately demoted; the other title-only issues remain candidate material
# but still need the listed context before adjudication.
TITLE_ISSUE_ADMISSION = {
    "candidate-pilot-01": (False, True, False, False, False, "Internal reorganization title does not state a user question, version, behavior, or scientific decision."),
    "candidate-pilot-02": (False, True, True, True, True, "Specific statistical behavior can seed a scenario after version, reproducer, and input-state review."),
    "candidate-pilot-03": (False, True, False, False, True, "Specific parameter proposal can seed a method-semantics review, but the applicable release is missing."),
    "candidate-pilot-07": (False, True, True, True, False, "Potential memory issue is too broad without scale, code path, measurement, or reproducer."),
    "candidate-pilot-08": (False, True, True, True, True, "Specific correction anomaly can be reviewed after reproducer and object-state collection."),
    "candidate-pilot-09": (False, True, True, True, True, "Specific layer-state regression can be reviewed after workflow and object-state collection."),
    "candidate-pilot-10": (False, True, False, False, True, "Direct behavior question is candidate-suitable but needs release scoping."),
    "candidate-pilot-11": (False, True, True, False, True, "Specific backend-selection failure can seed a scenario after reproducer and release review."),
    "candidate-pilot-12": (False, True, True, True, True, "Specific mapping regression can seed a scenario after reference-state and reproducer review."),
    "candidate-pilot-13": (False, True, True, True, True, "Specific reproducibility issue can seed a scenario after environment and state capture."),
    "candidate-pilot-14": (False, True, True, True, True, "Specific API error can seed a scenario after call and plotting-state capture."),
    "candidate-pilot-15": (False, True, True, True, True, "Specific raw/var alignment issue can seed a scenario after object-state capture."),
    "candidate-pilot-16": (False, True, True, True, True, "Specific batch/subset issue can seed a scenario after version, parameters, and data-state capture."),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(commit: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "show", f"{commit}:{path}"],
        stderr=subprocess.PIPE,
    )


def json_blob(commit: str, path: str) -> Any:
    return json.loads(git_blob(commit, path))


def jsonl_blob(commit: str, path: str) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in git_blob(commit, path).decode("utf-8").splitlines()
        if line
    ]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def artifact(commit: str, path: str) -> dict[str, str]:
    raw = git_blob(commit, path)
    return {"path": path, "sha256": sha256(raw)}


def load_and_verify_sources() -> dict[str, Any]:
    promotion_path = f"{APPROVED_PACKAGE_PATH}/promotion_manifest.json"
    promotion = json_blob(APPROVED_PACKAGE_COMMIT, promotion_path)
    approved_raw = git_blob(
        APPROVED_PACKAGE_COMMIT, f"{APPROVED_PACKAGE_PATH}/approved_kg.json"
    )
    caution_raw = git_blob(
        APPROVED_PACKAGE_COMMIT, f"{APPROVED_PACKAGE_PATH}/caution_context_index.json"
    )
    if promotion["approved_kg_sha256"] != APPROVED_KG_SHA256:
        raise ValueError("promotion manifest approved hash mismatch")
    if sha256(approved_raw) != APPROVED_KG_SHA256:
        raise ValueError("approved_kg.json hash mismatch")
    if sha256(caution_raw) != promotion["output_sha256"]["caution_context_index.json"]:
        raise ValueError("caution context hash mismatch")
    approved = json.loads(approved_raw)
    cautions = json.loads(caution_raw)
    allowlist = set(promotion["production_retrieval_statement_revision_ids"])
    statements = {row["statement_revision_id"] for row in approved["statements"]}
    if len(allowlist) != 121 or allowlist != statements:
        raise ValueError("approved statement allowlist mismatch")
    if HELD_STATEMENT_ID in allowlist or HELD_STATEMENT_ID in statements:
        raise ValueError("held statement leaked into approved consumer")
    if len(cautions) != 166:
        raise ValueError("caution context count mismatch")
    direct_assessments = [
        row
        for row in approved["evidence_assessments"]
        if row.get("support_type") == "DIRECT_SUPPORT"
        and all(
            row.get(key) is True
            for key in ("subject_aligned", "predicate_aligned", "object_aligned")
        )
    ]
    source_artifact_count = len(
        {row["source_artifact_id"] for row in approved["evidence_spans"]}
    )
    source_revision_count = len(
        {row["source_revision_id"] for row in approved["evidence_spans"]}
    )
    if (len(direct_assessments), source_artifact_count, source_revision_count) != (
        134,
        61,
        48,
    ):
        raise ValueError("approved evidence-chain count mismatch")

    # Mirror the immutable consumer's source-chain checks without importing or
    # executing Research Chat. Counts alone do not establish chain integrity.
    entities = {row["id"]: row for row in approved["entities"]}
    provenance = {p["source_artifact_id"]: p for p in approved["provenance"]
                  if "source" in p and "source_revision_id" in p}
    artifact_links = {(l["subject_id"], l["object_id"]) for l in approved["links"]
                      if l["predicate"] == "artifact_of"}
    for span in approved["evidence_spans"]:
        if sha256(span["exact_text"].encode()) != span["content_hash"]:
            raise ValueError("approved excerpt hash mismatch")
        origin = provenance.get(span["source_artifact_id"])
        if not origin or span["source_artifact_id"] not in entities:
            raise ValueError("approved source provenance missing")
        if origin["source_revision_id"] != span["source_revision_id"]:
            raise ValueError("approved source revision mismatch")
        if origin["source"].get("text_sha256") not in span["locator"]["value"]:
            raise ValueError("approved source locator mismatch")
        if (span["source_artifact_id"], span["source_revision_id"]) not in artifact_links:
            raise ValueError("approved artifact revision link missing")

    retrieval_manifest = json_blob(
        INTEGRATION_COMMIT, f"{RETRIEVAL_ROOT}/evidence_index_manifest.json"
    )
    for name, expected in retrieval_manifest["artifacts"].items():
        if sha256(git_blob(INTEGRATION_COMMIT, f"{RETRIEVAL_ROOT}/{name}")) != expected:
            raise ValueError(f"retrieval foundation hash mismatch: {name}")

    candidate_manifest = json_blob(
        INTEGRATION_COMMIT, f"{LEGACY_CANDIDATE_ROOT}/manifest.json"
    )
    for name, expected in candidate_manifest["artifacts"].items():
        if sha256(git_blob(INTEGRATION_COMMIT, f"{LEGACY_CANDIDATE_ROOT}/{name}")) != expected:
            raise ValueError(f"legacy candidate hash mismatch: {name}")

    graph_manifest = json_blob(
        INTEGRATION_COMMIT, f"{LEGACY_GRAPH_ROOT}/manifest.json"
    )
    for name in ("nodes.jsonl", "edges.jsonl"):
        expected = graph_manifest[f"{name.split('.')[0]}_sha256"]
        if sha256(git_blob(INTEGRATION_COMMIT, f"{LEGACY_GRAPH_ROOT}/{name}")) != expected:
            raise ValueError(f"legacy graph hash mismatch: {name}")

    inventory_raw = git_blob(INTEGRATION_COMMIT, LEGACY_INVENTORY_PATH)
    inventory = json.loads(inventory_raw)
    if len(inventory["nodes"]) != 1651:
        raise ValueError("legacy inventory node count mismatch")

    return {
        "promotion": promotion,
        "approved": approved,
        "cautions": cautions,
        "retrieval_manifest": retrieval_manifest,
        "candidate_manifest": candidate_manifest,
        "graph_manifest": graph_manifest,
        "inventory": inventory,
        "inventory_sha256": sha256(inventory_raw),
        "direct_assessment_binding_count": len(direct_assessments),
        "source_artifact_count": source_artifact_count,
        "source_revision_count": source_revision_count,
    }


def lane_manifest(source: dict[str, Any]) -> dict[str, Any]:
    retrieval = source["retrieval_manifest"]
    candidate = source["candidate_manifest"]
    graph = source["graph_manifest"]
    common = {
        "implementation_commit": INTEGRATION_COMMIT,
        "entry_point": "agent.research_runtime.build_chat_retrieval -> engine.approved_scientific_kg.GovernedChatRetrieval.search",
        "retrieval_budget": {
            "top_k": "per request (tool call.top_k); fallback 12; supplemental 4",
            "include_catalog": "call.tool_name == search_catalog; fallback/supplemental false",
            "enable_dense": False,
            "enable_sparse": True,
            "sparse_candidate_limit": "max(request.top_k * 12, 120)",
            "use_governance_rerank": False,
            "use_contract_gate": False,
        },
        "shared_runtime_components": [row["component"] for row in SHARED_RUNTIME],
    }
    lanes = [
        dict(
            common,
            lane_name="llm_only",
            backend_class="engine.approved_scientific_kg.GovernedChatRetrieval (no-retrieval branch)",
            corpus_snapshot_id="none",
            corpus_digests={},
            graph_channels="disabled",
            caution_policy="no local caution channel",
            retrieval_budget=dict(
                common["retrieval_budget"],
                top_k="incoming request may vary; no-retrieval backend returns zero hits",
                maximum_returned_hits=0,
                enable_sparse=False,
                sparse_candidate_limit=0,
                use_kg=False,
                use_scientific_evidence=False,
            ),
        ),
        dict(
            common,
            lane_name="generic_rag",
            backend_class="engine.hybrid_retrieval.HybridRetrievalService",
            corpus_snapshot_id=retrieval["build_id"],
            corpus_digests={
                "corpus_digest": retrieval["corpus_digest_after"],
                "catalog_chunks_sha256": sha256(git_blob(INTEGRATION_COMMIT, f"{RETRIEVAL_ROOT}/scrna_tools_catalog_chunks.jsonl")),
                "evidence_chunks_sha256": retrieval["artifacts"]["evidence_chunks.jsonl"],
                "fts_sha256": retrieval["artifacts"]["evidence_fts5.sqlite"],
                "manifest_sha256": sha256(
                    git_blob(INTEGRATION_COMMIT, f"{RETRIEVAL_ROOT}/evidence_index_manifest.json")
                ),
            },
            graph_channels="disabled (use_kg=false; scientific evidence adapter disabled)",
            caution_policy="no Scientific KG caution context",
            retrieval_budget=dict(
                common["retrieval_budget"],
                use_kg=False,
                use_scientific_evidence=False,
            ),
        ),
        dict(
            common,
            lane_name="legacy_kg",
            backend_class=(
                "engine.hybrid_retrieval.HybridRetrievalService + "
                "engine.scientific_kg_evidence.ScientificKGEvidence + "
                "engine.evidence_graph_query.EvidenceGraphQuery"
            ),
            corpus_snapshot_id=(
                f"{retrieval['build_id']} + scientific_kg_v1_uat_decision_rules + "
                f"{graph['snapshot_id']}"
            ),
            corpus_digests={
                "retrieval_corpus_digest": retrieval["corpus_digest_after"],
                "catalog_chunks_sha256": sha256(git_blob(INTEGRATION_COMMIT, f"{RETRIEVAL_ROOT}/scrna_tools_catalog_chunks.jsonl")),
                "candidate_manifest_sha256": sha256(
                    git_blob(INTEGRATION_COMMIT, f"{LEGACY_CANDIDATE_ROOT}/manifest.json")
                ),
                "candidate_bundle_sha256": candidate["artifacts"]["conformance_bundle.json"],
                "candidate_bindings_sha256": candidate["artifacts"]["exact_evidence_bindings.jsonl"],
                "legacy_inventory_sha256": source["inventory_sha256"],
                "legacy_tool_graph_nodes_sha256": graph["nodes_sha256"],
                "legacy_tool_graph_edges_sha256": graph["edges_sha256"],
            },
            graph_channels=(
                "candidate ScientificKGEvidence direct-evidence channel enabled; "
                "7,537-node legacy tool/catalog graph enabled only for candidate-tool filtering"
            ),
            caution_policy=(
                "candidate-only evidence-gap diagnostics may abstain; no approved-v2 caution context"
            ),
            retrieval_budget=dict(
                common["retrieval_budget"],
                use_kg=True,
                use_scientific_evidence=True,
            ),
        ),
        dict(
            common,
            lane_name="scientific_kg",
            backend_class="engine.approved_scientific_kg.ApprovedScientificKG",
            corpus_snapshot_id="approved-scientific-kg-v2-01",
            corpus_digests={
                "approved_kg_sha256": APPROVED_KG_SHA256,
                "caution_context_index_sha256": source["promotion"]["output_sha256"]["caution_context_index.json"],
                "package_commit": APPROVED_PACKAGE_COMMIT,
            },
            graph_channels=(
                "approved allowlist, evidence-chain joins, exact scope policy, and separate caution context; "
                "generic RAG and both legacy graphs are not consulted"
            ),
            caution_policy={
                "count": 166,
                "scientific_assertion": False,
                "trusted": False,
                "production_retrieval_eligible": False,
                "execution_gate": False,
                "execution_authorized": False,
            },
            retrieval_budget={
                "top_k": "per request; approved facts capped at min(request.top_k, 12)",
                "maximum_approved_facts": 12,
                "maximum_caution_contexts": 4,
                "algorithm": "approved exact-evidence in-memory ranking",
                "generic_sparse_consumer_used": False,
                "generic_dense_consumer_used": False,
                "legacy_kg_used": False,
            },
        ),
    ]
    return {
        "schema_version": "sckg-evaluation-lane-manifest-v2",
        "configuration_observation": "static immutable-code inspection; no runtime observations",
        "comparison_estimand": "product bundle, not graph structure alone",
        "actual_request_receipts_required": True,
        "run_id": RUN_ID,
        "frozen_at": FROZEN_AT,
        "baseline_truth": {
            "integration_commit": INTEGRATION_COMMIT,
            "rule": "07 runtime implementation at this commit is the only lane definition",
        },
        "lane_order": ["llm_only", "generic_rag", "legacy_kg", "scientific_kg"],
        "lanes": lanes,
        "shared_runtime": SHARED_RUNTIME,
        "coverage_exclusion_rule": (
            "Planner, ToolContracts, execution guards, validation contracts, and approval system "
            "are common infrastructure. Their records and behavior cannot establish any V2, Legacy, "
            "or RAG coverage bit and cannot be reported as Scientific KG gain."
        ),
        "approved_consumer_invariants": {
            "approved_statement_count": 121,
            "direct_assessment_binding_count": source["direct_assessment_binding_count"],
            "source_artifact_count": source["source_artifact_count"],
            "source_revision_count": source["source_revision_count"],
            "caution_context_count": 166,
            "approved_kg_sha256": APPROVED_KG_SHA256,
            "held_statement_id": HELD_STATEMENT_ID,
            "held_statement_visible": False,
        },
        "formal_agent_gain_run": False,
    }


def coverage_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    by_name = {row["lane_name"]: row for row in manifest["lanes"]}
    return {
        "schema_version": "sckg-coverage-snapshot-manifest-v2",
        "run_id": RUN_ID,
        "frozen_at": FROZEN_AT,
        "integration_commit": INTEGRATION_COMMIT,
        "bit_order": ["scientific_kg_v2", "legacy_kg", "ordinary_rag"],
        "assignment_rule": (
            "present requires sufficient consumer-visible facts/conditions plus supporting IDs; "
            "absent requires reviewer-checked negative evidence; search alone leaves unknown. "
            "Shared runtime components never count."
        ),
        "supersedes": {
            "run_id": "candidate-audit-20260921-v1",
            "reason": (
                "Phase 2.1 used the canonical tool graph as V2 and counted a ToolContract. "
                "Neither is the approved-v2 consumer used by the 07 scientific_kg lane."
            ),
        },
        "withdraws_invalid_audit": {
            "run_id": "lane-alignment-20260921-v1",
            "commit": HISTORICAL_AUDIT_COMMIT,
            "reason": "Unconditional absent/000 generation; no reviewed coverage conclusion.",
        },
        "sources": {
            "scientific_kg_v2": {
                "lane_name": "scientific_kg",
                "snapshot_id": by_name["scientific_kg"]["corpus_snapshot_id"],
                "digest": APPROVED_KG_SHA256,
                "coverage_records": "121 approved statements with approved evidence-chain and scope records",
                "cautions": "166 separate non-assertion contexts; searchable for negative evidence but never support",
                "held_statement_excluded": HELD_STATEMENT_ID,
            },
            "legacy_kg": {
                "lane_name": "legacy_kg",
                "snapshot_id": by_name["legacy_kg"]["corpus_snapshot_id"],
                "digest": sha256(
                    json.dumps(by_name["legacy_kg"]["corpus_digests"], sort_keys=True).encode()
                ),
                "coverage_records": (
                    "800 evidence chunks (10 quarantined), 1847 conditional catalog metadata records, plus consumer-visible candidate "
                    "ScientificKGEvidence claims/bindings; the legacy tool graph is recorded as a "
                    "filtering channel, not promoted to answer evidence"
                ),
            },
            "ordinary_rag": {
                "lane_name": "generic_rag",
                "snapshot_id": by_name["generic_rag"]["corpus_snapshot_id"],
                "digest": sha256(json.dumps(by_name["generic_rag"]["corpus_digests"], sort_keys=True).encode()),
                "evidence_corpus_digest": by_name["generic_rag"]["corpus_digests"]["corpus_digest"],
                "coverage_records": "800 evidence chunks (790 eligible) plus 1847 catalog metadata records when include_catalog=true; authority boundaries retained",
            },
        },
        "shared_runtime_excluded": [row["component"] for row in SHARED_RUNTIME],
    }


def record_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def source_records(source: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]], list[dict[str, str]]]:
    approved = source["approved"]
    utility = defaultdict(list)
    for row in approved["utility"]:
        utility[row.get("statement_revision_id")].append(row.get("interpretation", ""))
    assessments = defaultdict(list)
    for row in approved["evidence_assessments"]:
        assessments[row["statement_revision_id"]].append(row)
    spans = {row["evidence_span_id"]: row for row in approved["evidence_spans"]}
    entities = {row["id"]: row for row in approved["entities"]}
    v2_records = []
    for statement in approved["statements"]:
        sid = statement["statement_revision_id"]
        statement_assessments = [a for a in assessments[sid]
            if a.get("support_type") == "DIRECT_SUPPORT" and all(
                a.get(k) is True for k in ("subject_aligned", "predicate_aligned", "object_aligned"))]
        span_rows = [
            spans[row["evidence_span_id"]]
            for row in statement_assessments
            if row.get("evidence_span_id") in spans
        ]
        payload = {
            "statement": statement,
            "utility": utility[sid],
            "assessments": statement_assessments,
            "evidence_spans": span_rows,
            "subject": entities.get(statement["subject_id"]),
            "object": entities.get(statement["object_id"]),
            "descriptor_links": [link for link in approved["links"]
                if link["subject_id"] in {statement["subject_id"], statement["object_id"]}],
            "descriptor_entities": [entities[link["object_id"]] for link in approved["links"]
                if link["subject_id"] in {statement["subject_id"], statement["object_id"]}
                and link["predicate"] in {"requires_constraint", "has_output_port"}
                and link["object_id"] in entities],
            "source_provenance": [p for p in approved["provenance"]
                if p.get("source_artifact_id") in {s["source_artifact_id"] for s in span_rows}],
        }
        v2_records.append({"id": sid, "text": record_text(payload),
            "kind": "approved_statement", "consumer_eligible": True,
            "evidence": {s["evidence_span_id"]: s["exact_text"] for s in span_rows}})

    caution_records = [
        {"id": row["caution_id"], "text": record_text(row)} for row in source["cautions"]
    ]

    candidate_bundle = json_blob(
        INTEGRATION_COMMIT, f"{LEGACY_CANDIDATE_ROOT}/conformance_bundle.json"
    )
    candidate_bindings = {
        row["claim_revision_id"]: row
        for row in jsonl_blob(
            INTEGRATION_COMMIT, f"{LEGACY_CANDIDATE_ROOT}/exact_evidence_bindings.jsonl"
        )
    }
    candidate_spans = {
        row["evidence_span_id"]: row
        for row in jsonl_blob(
            INTEGRATION_COMMIT, f"{LEGACY_CANDIDATE_ROOT}/authoritative_evidence_spans.jsonl"
        )
    }
    candidate_assessments = defaultdict(list)
    for row in candidate_bundle["evidence_assessments"]:
        candidate_assessments[row["claim_revision_id"]].append(row)
    legacy_claim_records = []
    for claim in candidate_bundle["atomic_claims"]:
        cid = claim["claim_revision_id"]
        binding = candidate_bindings.get(cid, {})
        evidence_ids = binding.get("evidence_span_ids") or binding.get("evidence_span_id") or []
        if isinstance(evidence_ids, str):
            evidence_ids = [evidence_ids]
        payload = {
            "claim": claim,
            "binding": binding,
            "assessments": candidate_assessments[cid],
            "evidence_spans": [candidate_spans[x] for x in evidence_ids if x in candidate_spans],
            "scopes": candidate_bundle["scopes"],
        }
        legacy_claim_records.append({"id": cid, "text": record_text(payload),
            "kind": "legacy_candidate_claim", "consumer_eligible": bool(binding),
            "evidence": {s: candidate_spans[s]["source_excerpt"] for s in evidence_ids if s in candidate_spans}})

    rag_records = []
    for name in ("evidence_chunks.jsonl", "scrna_tools_catalog_chunks.jsonl"):
        for row in jsonl_blob(INTEGRATION_COMMIT, f"{RETRIEVAL_ROOT}/{name}"):
            # Same generic rule as the pinned formal_evidence_is_quarantined;
            # inventory includes quarantined rows but they can never support present.
            formal = row.get("source_kind", "").casefold() in {"publication", "benchmark"} or row.get("source_type", "").casefold() in {"formal_publication_tsv", "formal_benchmark_tsv"}
            rag_records.append({"id": row["chunk_id"], "text": record_text(row),
                "kind": "catalog_metadata" if row["retrieval_status"] == "catalog_only" else "rag_chunk",
                "consumer_eligible": not (formal and not row.get("source_bound")),
                "evidence": {row["chunk_id"]: row["chunk_text"]},
                "claim_boundary": row.get("claim_boundary", ""),
                "request_condition": "include_catalog=true" if row["retrieval_status"] == "catalog_only" else None})
    # The actual 07 legacy lane retains the same BM25 corpus and adds the
    # candidate ScientificKGEvidence channel.  Its coverage audit must therefore
    # inspect both; auditing only the 25 candidate claims would make a narrower
    # synthetic baseline than the runtime.
    legacy_records = [*legacy_claim_records, *rag_records]
    graph_records = [
        {"id": row["node_id"], "text": record_text(row)}
        for row in jsonl_blob(INTEGRATION_COMMIT, f"{LEGACY_GRAPH_ROOT}/nodes.jsonl")
        if row.get("node_type") != "ToolContract"
    ]
    return (
        {
            "scientific_kg_v2": v2_records,
            "legacy_kg": legacy_records,
            "ordinary_rag": rag_records,
        },
        caution_records,
        graph_records,
    )


STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "after", "when", "into",
    "what", "which", "does", "using", "issue", "function", "data", "result", "results",
}


def terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9_.+-]+", text.casefold())
        if len(token) >= 3 and token not in STOPWORDS
    ]


def scan(records: list[dict[str, str]], variants: list[str]) -> dict[str, Any]:
    exact, conjunction, anchors = set(), set(), set()
    anchor_terms = sorted({token for variant in variants for token in terms(variant)})
    for record in records:
        text = record["text"].casefold()
        if any(variant.casefold() in text for variant in variants):
            exact.add(record["id"])
        if any(terms(variant) and all(token in text for token in terms(variant)) for variant in variants):
            conjunction.add(record["id"])
        if any(token in text for token in anchor_terms):
            anchors.add(record["id"])
    return {
        "records_scanned": len(records),
        "exact_phrase_match_count": len(exact),
        "conjunction_match_count": len(conjunction),
        "anchor_match_count": len(anchors),
        "sample_match_ids": sorted(exact | conjunction | anchors)[:12],
    }


def admission(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_id = candidate["candidate_id"]
    if candidate_id in TITLE_ISSUE_ADMISSION:
        standalone, version, reproducer, data_state, suitable, rationale = TITLE_ISSUE_ADMISSION[candidate_id]
        basis = "title-only-official-issue"
    elif candidate["question_origin"] == "paper-notebook":
        standalone, version, reproducer, data_state, suitable = False, True, False, True, True
        rationale = "Instruction is reviewable, but frozen input data/capsule and environment are required for an answer."
        basis = "paper-notebook-identity-draft"
    elif candidate_id == "candidate-pilot-04":
        standalone, version, reproducer, data_state, suitable = True, False, False, True, True
        rationale = "Controlled state probe is coherent; the evaluated run would need notebook state."
        basis = "project-controlled-probe"
    elif candidate_id == "candidate-pilot-05":
        standalone, version, reproducer, data_state, suitable = True, True, False, False, True
        rationale = "Controlled evidence-governance probe is coherent and explicitly version-sensitive."
        basis = "project-controlled-probe"
    else:
        standalone, version, reproducer, data_state, suitable = True, False, False, False, True
        rationale = "Controlled artifact-validation probe is coherent without adding source facts."
        basis = "project-controlled-probe"
    return {
        "schema_version": "sckg-candidate-admission-audit-v1",
        "candidate_id": candidate_id,
        "source_seed_id": candidate["source_seed_ids"][0],
        "audit_basis": basis,
        "standalone_answerable": standalone,
        "needs_version": version,
        "needs_reproducer": reproducer,
        "needs_data_state": data_state,
        "suitable_for_candidate": suitable,
        "admission_status": "retained" if suitable else "demoted_to_raw_only",
        "rationale": rationale,
        "review_status": "needs_adjudication",
        "gold_status": "none",
    }


def re_audit(
    candidates: list[dict[str, Any]],
    prior_audits: dict[str, dict[str, Any]],
    snapshot: dict[str, Any],
    records: dict[str, list[dict[str, str]]],
    cautions: list[dict[str, str]],
    graph_records: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audits, admissions = [], []
    snapshot_ids = {key: value["snapshot_id"] for key, value in snapshot["sources"].items()}
    snapshot_digests = {key: value["digest"] for key, value in snapshot["sources"].items()}
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        prior = prior_audits[candidate_id]
        variants = prior["source_results"]["ordinary_rag"]["negative_search_procedure"]["query_variants"]
        source_results = {}
        for source_name in ("scientific_kg_v2", "legacy_kg", "ordinary_rag"):
            result = scan(records[source_name], variants)
            procedure = {
                "procedure_id": "lane-bound-exhaustive-consumer-record-scan-v2",
                "query_variants": variants,
                "consumer_lane": snapshot["sources"][source_name]["lane_name"],
                "fields": "canonical JSON serialization of consumer-visible knowledge records",
                "match_passes": [
                    "casefolded exact phrase",
                    "all non-stopword terms per query variant",
                    "individual anchor terms",
                ],
                **result,
                "reviewer_sufficiency_conclusion": None,
                "search_is_not_a_coverage_decision": True,
                "shared_runtime_excluded": [row["component"] for row in SHARED_RUNTIME],
            }
            if source_name == "scientific_kg_v2":
                caution_result = scan(cautions, variants)
                procedure.update(
                    {
                        "approved_statement_allowlist_count": 121,
                        "evidence_chain_inventory_verified": True,
                        "fact_specific_scope_review": "pending",
                        "caution_records_scanned": caution_result["records_scanned"],
                        "caution_sample_match_ids": caution_result["sample_match_ids"],
                        "cautions_can_support_present": False,
                        "held_statement_checked_absent": HELD_STATEMENT_ID,
                    }
                )
            elif source_name == "legacy_kg":
                graph_result = scan(graph_records, variants)
                procedure.update(
                    {
                        "candidate_claim_records_scanned": 25,
                        "retrieval_foundation_records_scanned": 800,
                        "legacy_tool_graph_filter_records_scanned": graph_result["records_scanned"],
                        "legacy_tool_graph_sample_match_ids": graph_result["sample_match_ids"],
                        "legacy_tool_graph_role": "candidate-tool filtering only; not answer support",
                        "tool_contract_nodes_excluded": 6,
                    }
                )
            source_results[source_name] = {
                "status": "unknown",
                "supporting_ids": [],
                "supporting_scope": "",
                "search_evidence": procedure,
                "negative_search_procedure": None,
            }

        signature = None
        track, track_basis = TRACKS[candidate_id]
        admission_row = admission(candidate)
        admissions.append(admission_row)
        candidate["schema_version"] = "sckg-candidate-scenario-pilot-v3"
        candidate["benchmark_track_proposal"] = {
            "track": track,
            "track_name": {
                "K": "Scientific Knowledge Utility",
                "O": "Open-world Real-user Robustness",
                "W": "Workflow / Execution",
            }[track],
            "basis": track_basis,
            "status": "proposal_not_gold",
        }
        candidate["admission_audit"] = {
            key: admission_row[key]
            for key in (
                "standalone_answerable", "needs_version", "needs_reproducer",
                "needs_data_state", "suitable_for_candidate", "admission_status", "rationale"
            )
        }
        candidate["coverage_vector"] = {
            "scientific_kg_v2": "unknown",
            "legacy_kg": "unknown",
            "ordinary_rag": "unknown",
            "exact_signature": signature,
            "coarse_label": None,
            "snapshot_ids": snapshot_ids,
            "snapshot_digests": snapshot_digests,
            "shared_runtime_excluded": [row["component"] for row in SHARED_RUNTIME],
        }
        candidate["exact_coverage_signature"] = signature
        audits.append(
            {
                "schema_version": "sckg-candidate-coverage-audit-v3-withdrawn",
                "run_id": RUN_ID,
                "candidate_id": candidate_id,
                "source_seed_id": candidate["source_seed_ids"][0],
                "question_origin": candidate["question_origin"],
                "candidate_admission_status": admission_row["admission_status"],
                "benchmark_track_proposal": track,
                "legacy_requirements_unreviewed": prior["required_facts_and_conditions"],
                "required_scientific_facts": [],
                "requirements_review_status": "needs_decomposition",
                "user_context_and_state": candidate["context_requirements"],
                "task_results": [],
                "withdraws": {"commit": HISTORICAL_AUDIT_COMMIT, "signature": "000",
                    "reason": "Program assigned absent unconditionally; no human coverage decision existed."},
                "audit_method": (
                    "Deterministic lexical search inventory only. All labels withdrawn to unknown. "
                    "Separate scientific facts from user state and task outputs before human review."
                ),
                "snapshot_ids": snapshot_ids,
                "snapshot_digests": snapshot_digests,
                "source_results": source_results,
                "exact_signature": signature,
                "coarse_label": None,
                "review_status": "needs_adjudication",
                "gold_status": "none",
            }
        )
    return audits, admissions


def md(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def lane_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# Phase 2.2 Evaluation Lane Manifest",
        "",
        f"Baseline truth: 07 integration commit `{INTEGRATION_COMMIT}`.",
        "",
        "This is a configuration freeze, not a four-lane run. No LLM, Research Chat lane, DEV/Gold,",
        "or Agent Gain evaluation was invoked.",
        "",
        "| lane | backend / entry point | corpus or snapshot | retrieval | graph channels | caution policy |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for lane in manifest["lanes"]:
        lines.append(
            f"| `{lane['lane_name']}` | {md(lane['backend_class'])}<br>{md(lane['entry_point'])} | "
            f"{md(lane['corpus_snapshot_id'])}<br>{md(lane['corpus_digests'])} | "
            f"{md(lane['retrieval_budget'])} | {md(lane['graph_channels'])} | {md(lane['caution_policy'])} |"
        )
    lines.extend(
        [
            "",
            "## Shared runtime exclusion",
            "",
            manifest["coverage_exclusion_rule"],
            "",
            "| component | implementation binding | coverage treatment |",
            "| --- | --- | --- |",
        ]
    )
    for row in manifest["shared_runtime"]:
        lines.append(
            f"| `{row['component']}` | {row['implementation']} | {row['coverage_rule']} |"
        )
    lines.extend(
        [
            "",
            "## Approved-v2 consumer invariants",
            "",
            f"- Approved snapshot SHA256: `{APPROVED_KG_SHA256}`.",
            "- Visible approved statements: 121; direct assessment bindings: 134.",
            "- Evidence chain: Statement → Assessment → EvidenceSpan → SourceRevision.",
            "- Scope qualifiers remain explicit; mismatches exclude and missing conditions remain unknown.",
            "- Caution contexts: 166, separate and non-assertive.",
            f"- Held statement `{HELD_STATEMENT_ID}` is not visible.",
            "",
        ]
    )
    return "\n".join(lines)


def coverage_report(audits: list[dict[str, Any]], snapshot: dict[str, Any]) -> str:
    counts = Counter(row["exact_signature"] or "unknown" for row in audits)
    lines = [
        "# Phase 2.2 Lane-aligned Coverage Re-audit",
        "",
        f"Run: `{RUN_ID}`",
        "",
        "Status: previous all-000 conclusion WITHDRAWN; all 20 unknown pending fact decomposition and human review.",
        "",
        "The Phase 2.1 coverage conclusion is superseded. The V2 bit now uses only the actual",
        "approved-v2 consumer at the 07 integration commit. ToolContracts and all other shared",
        "runtime components are excluded. Legacy and RAG use the exact paired backends from 07.",
        "",
        f"Signature counts: `{json.dumps(dict(sorted(counts.items())), sort_keys=True)}`.",
        "",
        "| candidate | admission | track | required fact/condition (first) | V2 | Legacy | RAG | signature |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in audits:
        lines.append(
            f"| `{row['candidate_id']}` | `{row['candidate_admission_status']}` | "
            f"`{row['benchmark_track_proposal']}` | decomposition pending | "
            "unknown | unknown | unknown | unassigned |"
        )
    lines.extend(
        [
            "",
            "## Negative-search interpretation",
            "",
            "No cell currently establishes absence or presence. Search evidence records snapshot, query",
            "variants, counts and partial-match IDs, NOT manual sufficiency decisions.",
            "Scientific KG searches all 121 approved statements with their",
            "evidence and scope joins and separately reports caution matches. Legacy searches the",
            "same 800 frozen evidence chunks plus the 25 direct-evidence candidate claims used by",
            "its consumer, and records the tool-graph filter",
            "scan separately. Both RAG-backed inventories include the 1847 conditional catalog records;",
            "10 quarantined formal chunks cannot support present. Catalog metadata cannot support recommendations/execution.",
            "A partial match never becomes",
            "`present`, and no single retrieval result was used as a label.",
            "",
            f"The held scVelo statement `{HELD_STATEMENT_ID}` was verified absent and never searched as",
            "support. Cautions are non-assertive and never establish a present bit.",
            "",
        ]
    )
    return "\n".join(lines)


def admission_report(
    candidates: list[dict[str, Any]], admissions: list[dict[str, Any]]
) -> str:
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    lines = [
        "# Phase 2.2 Candidate Admission Audit",
        "",
        "Admission is independent of 07 performance. `suitable_for_candidate=false` leaves the",
        "source in the raw-seed inventory and removes its identity draft from the active candidate pool.",
        "No item gains Gold or a split assignment.",
        "",
        "| candidate | source title/query | standalone | needs version | needs reproducer | needs data state | suitable | status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in admissions:
        query = candidate_by_id[row["candidate_id"]]["draft_query"]
        lines.append(
            f"| `{row['candidate_id']}` | {md(query)} | `{str(row['standalone_answerable']).lower()}` | "
            f"`{str(row['needs_version']).lower()}` | `{str(row['needs_reproducer']).lower()}` | "
            f"`{str(row['needs_data_state']).lower()}` | `{str(row['suitable_for_candidate']).lower()}` | "
            f"`{row['admission_status']}` |"
        )
    lines.extend(
        [
            "",
            "Demoted raw-only titles:",
            "",
            "- `candidate-pilot-01` — “Reorg io functions”.",
            "- `candidate-pilot-07` — “BUG: Potential issue in parallel memory usage”.",
            "",
            "Both source seeds remain unchanged in `raw_seeds_pilot.jsonl`.",
            "",
        ]
    )
    return "\n".join(lines)


def phase_report(
    candidates: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    admissions: list[dict[str, Any]],
) -> str:
    tracks = Counter(row["benchmark_track_proposal"]["track"] for row in candidates)
    retained = [row for row in admissions if row["suitable_for_candidate"]]
    demoted = [row for row in admissions if not row["suitable_for_candidate"]]
    return f"""# Phase 2.2 Evaluation Lane Alignment + Coverage Re-audit

Status: COVERAGE CONCLUSION WITHDRAWN. Lane identities remain verified; coverage is unknown, not 000.

## Outcome

- Lane manifest freezes `llm_only`, `generic_rag`, `legacy_kg`, and `scientific_kg` at `{INTEGRATION_COMMIT}`.
- Approved Scientific KG identity verified as `{APPROVED_KG_SHA256}` with 121 visible statements, 166 separate caution contexts, and the held scVelo statement absent.
- All {len(audits)} former coverage labels are withdrawn pending fact-level human review. Search inventory is not adjudication.
- Track proposals across the audited 20: K={tracks['K']}, O={tracks['O']}, W={tracks['W']}. They are sampling/review metadata, not Gold.
- Candidate admission: {len(retained)} retained; {len(demoted)} demoted to raw-only (`candidate-pilot-01`, `candidate-pilot-07`).

## Alignment correction

The Phase 2.1 canonical graph is not the approved Scientific KG consumer. The former `100` for candidate-pilot-06 incorrectly counted a shared ToolContract. The subsequent all-000 result was also invalid: the program hardcoded absent. Neither result is a scientific coverage conclusion. Historical bytes remain at commit {HISTORICAL_AUDIT_COMMIT}; current labels are unknown. Runtime-only tasks may become not_applicable after requirement decomposition, never automatically 000.

## Review blockers

1. The retained title-only issues still need the version/reproducer/data-state fields recorded in the admission audit before scientific adjudication.
2. Paper/notebook candidates still need frozen input/capsule and execution-environment digests.
3. All coverage decisions remain `needs_adjudication`; no answer source or expected result has been promoted to Gold.

## Explicit non-actions

No LLM answer, Research Chat lane, A/B/C/D run, Agent Gain calculation, DEV/Gold split, seed expansion, or 05/06/07 modification occurred.
"""


def validate(
    source: dict[str, Any],
    manifest: dict[str, Any],
    candidates: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    admissions: list[dict[str, Any]],
    records: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    errors = []
    if [row["lane_name"] for row in manifest["lanes"]] != manifest["lane_order"]:
        errors.append("lane order mismatch")
    if source["promotion"]["approved_kg_sha256"] != APPROVED_KG_SHA256:
        errors.append("approved hash mismatch")
    if len(records["scientific_kg_v2"]) != 121:
        errors.append("approved statement count")
    if len(source["cautions"]) != 166:
        errors.append("caution count")
    if len(records["legacy_kg"]) != 2672:
        errors.append("legacy consumer knowledge-record count")
    if len(records["ordinary_rag"]) != 2647:
        errors.append("RAG chunk count")
    if len(candidates) != 20 or len(audits) != 20 or len(admissions) != 20:
        errors.append("candidate/audit count")
    if any(row["review_status"] != "needs_adjudication" or row["gold_status"] != "none" for row in candidates):
        errors.append("candidate review/Gold invariant")
    if any(row["exact_signature"] is not None for row in audits):
        errors.append("unreviewed coverage must remain unassigned")
    for row in audits:
        for result in row["source_results"].values():
            if result["status"] == "present" and not result["supporting_ids"]:
                errors.append(f"{row['candidate_id']}:present without supporting IDs")
            if result["status"] == "absent" and not result["negative_search_procedure"]:
                errors.append(f"{row['candidate_id']}:absent without negative search")
    demoted = [row["candidate_id"] for row in admissions if not row["suitable_for_candidate"]]
    if demoted != ["candidate-pilot-01", "candidate-pilot-07"]:
        errors.append("admission demotion mismatch")
    if HELD_STATEMENT_ID in {row["id"] for row in records["scientific_kg_v2"]}:
        errors.append("held statement leak")
    if set(TRACKS) != {row["candidate_id"] for row in candidates}:
        errors.append("track coverage mismatch")
    return {
        "schema_version": "sckg-lane-alignment-validation-v1",
        "run_id": RUN_ID,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "checks": {
            "integration_commit_exists": True,
            "approved_hash_verified": True,
            "approved_statements": len(records["scientific_kg_v2"]),
            "held_statements_visible": 0,
            "caution_contexts": len(source["cautions"]),
            "legacy_candidate_claims": 25,
            "legacy_retrieval_foundation_chunks": 800,
            "legacy_consumer_knowledge_records": len(records["legacy_kg"]),
            "ordinary_rag_chunks": len(records["ordinary_rag"]),
            "catalog_inventory_per_rag_backed_lane": 1847,
            "quarantined_evidence_per_rag_backed_lane": sum(not r["consumer_eligible"] for r in records["ordinary_rag"]),
            "candidate_labels_withdrawn": len(audits),
            "candidates_human_coverage_audited": 0,
            "candidates_retained": sum(row["suitable_for_candidate"] for row in admissions),
            "candidates_demoted": sum(not row["suitable_for_candidate"] for row in admissions),
            "shared_runtime_excluded": [row["component"] for row in SHARED_RUNTIME],
            "llm_calls": 0,
            "lane_runs": 0,
            "agent_gain_runs": 0,
            "dev_or_gold_created": False,
        },
    }


def main() -> None:
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{INTEGRATION_COMMIT}^{{commit}}"],
        check=True,
    )
    source = load_and_verify_sources()
    manifest = lane_manifest(source)
    snapshot = coverage_snapshot(manifest)
    candidates = read_jsonl(BASE_DIR / "candidate_scenarios_pilot.jsonl")
    prior_audits = {
        row["candidate_id"]: row for row in jsonl_blob(
            HISTORICAL_AUDIT_COMMIT, "eval/benchmark_v3/coverage_audit.jsonl")
    }
    records, cautions, graph_records = source_records(source)
    audits, admissions = re_audit(
        candidates, prior_audits, snapshot, records, cautions, graph_records
    )
    retained = [
        row
        for row in candidates
        if row["admission_audit"]["suitable_for_candidate"]
    ]
    validation = validate(source, manifest, candidates, audits, admissions, records)
    if validation["status"] != "passed":
        raise ValueError(validation["errors"])

    write_json(BASE_DIR / "evaluation_lane_manifest.json", manifest)
    (BASE_DIR / "evaluation_lane_manifest.md").write_text(
        lane_report(manifest), encoding="utf-8"
    )
    write_json(BASE_DIR / "coverage_snapshot_manifest.json", snapshot)
    write_jsonl(BASE_DIR / "candidate_scenarios_pilot.jsonl", candidates)
    write_jsonl(BASE_DIR / "candidate_pool_phase_2_2.jsonl", retained)
    write_jsonl(BASE_DIR / "candidate_admission_audit.jsonl", admissions)
    (BASE_DIR / "candidate_admission_report.md").write_text(
        admission_report(candidates, admissions), encoding="utf-8"
    )
    write_jsonl(BASE_DIR / "coverage_audit.jsonl", audits)
    (BASE_DIR / "coverage_audit_report.md").write_text(
        coverage_report(audits, snapshot), encoding="utf-8"
    )
    write_json(BASE_DIR / "lane_alignment_validation.json", validation)
    (BASE_DIR / "phase_2_2_report.md").write_text(
        phase_report(candidates, audits, admissions), encoding="utf-8"
    )
    print(json.dumps(validation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
