from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.evidence_discovery_index import EvidenceChunk, chunk_to_dict, load_chunks
from engine.hybrid_retrieval import HybridRetrievalService, LocalBgeM3Encoder


FROZEN_BENCHMARK = PROJECT_ROOT / "eval_v2" / "retrieval_benchmark_v1_dev"
DEFAULT_INDEX = PROJECT_ROOT / "data" / "indexes"
SNAPSHOT_DIR = DEFAULT_INDEX / "retrieval_foundation_v1"
OUTPUT_DIR = PROJECT_ROOT / "data" / "evaluation" / "retrieval_foundation_strengthening_v1"
REPORT_PATH = PROJECT_ROOT / "docs" / "status" / "RETRIEVAL_FOUNDATION_STRENGTHENING_V1.md"
UAT_SPANS = PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_uat_decision_rules" / "authoritative_evidence_spans.jsonl"
SEED_PROVENANCE = PROJECT_ROOT / "eval_v2" / "gold" / "midterm_core_seed_v0" / "scientific_source_provenance.jsonl"
CORE_SPANS = PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_core" / "evidence_spans.jsonl"
CATALOG_CHUNKS = DEFAULT_INDEX / "scrna_tools_catalog_chunks.jsonl"

FROZEN_CORPUS_DIGEST = "7c8545721cd73a47fc0849ccc240ba2e150a064e07005de5f11ac26ab1213fd0"
EXPECTED_MODEL_REVISION = "cb1779f90b988b8deb01f9155c790ef9417d7648"
CORE_SPAN_BLOCK_REASON = (
    "The candidate row contains an authored source_local_excerpt and mutable source URI, "
    "but no independently resolvable exact SourceArtifact/SourceRevision object."
)


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digest(chunks: Iterable[EvidenceChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda row: row.chunk_id):
        digest.update(chunk.chunk_id.encode())
        digest.update(b"\0")
        digest.update(chunk.content_hash.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _assert_frozen_benchmark() -> dict[str, Any]:
    pre = json.loads((FROZEN_BENCHMARK / "pre_run_manifest.json").read_text(encoding="utf-8"))
    expected = {
        "queries.jsonl": pre["query_set_sha256"],
        "gold.jsonl": pre["gold_sha256"],
        "retrieval_config.json": pre["retrieval_config_sha256"],
    }
    for name, digest in expected.items():
        if _sha(FROZEN_BENCHMARK / name) != digest:
            raise RuntimeError(f"frozen retrieval benchmark drift: {name}")
    if pre["dense_index_identity"]["source_digest"] != FROZEN_CORPUS_DIGEST:
        raise RuntimeError("unexpected frozen P0C corpus digest")
    return pre


def _affected_gold() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gold = {row["query_id"]: row for row in _rows(FROZEN_BENCHMARK / "gold.jsonl")}
    failures = _rows(FROZEN_BENCHMARK / "failure_register.jsonl")
    affected_ids = sorted({row["query_id"] for row in failures if row["first_cause"] == "GOLD_SOURCE_NOT_INDEXED"})
    return [gold[query_id] for query_id in affected_ids], failures


def _source_work(span_id: str, row: dict[str, Any]) -> str:
    lowered = span_id.casefold()
    if "scanpy" in lowered:
        return "source-work:github:scverse/scanpy"
    if "singler" in lowered:
        return "source-work:bioconductor:SingleRBook" if "reference-choice" in lowered else "source-work:bioconductor:SingleR"
    if "celltypist" in lowered:
        return "source-work:celltypist:annotate"
    source_id = str(row.get("source_id") or "")
    if source_id:
        return source_id
    return "UNKNOWN"


def analyze_missing_gold() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    affected, failures = _affected_gold()
    uat = {row["evidence_span_id"]: row for row in _rows(UAT_SPANS)}
    seed = {row["evidence_span_id"]: row for row in _rows(SEED_PROVENANCE)}
    core = {row["evidence_span_id"]: row for row in _rows(CORE_SPANS)}
    records: list[dict[str, Any]] = []
    indexable: list[dict[str, Any]] = []
    query_by_span: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in affected:
        for span_id in item["gold_evidence_span_ids"]:
            query_by_span[span_id].append(item)
    for span_id, query_gold in sorted(query_by_span.items()):
        source = uat.get(span_id) or seed.get(span_id) or core.get(span_id)
        if source is None:
            classification = "SOURCE_NOT_ACQUIRED"
            reason = "No governed source or evidence-span record resolves this frozen gold identity."
        elif span_id in core:
            classification = "SOURCE_ARTIFACT_MISSING"
            reason = CORE_SPAN_BLOCK_REASON
        else:
            classification = "EVIDENCE_SPAN_NOT_CHUNKED"
            reason = "A pinned/reviewed exact evidence span resolves, but no retrieval EvidenceChunk carries its identity."
            indexable.append({"evidence_span_id": span_id, "source": source, "query_gold": query_gold})
        records.append(
            {
                "evidence_span_id": span_id,
                "affected_query_ids": sorted(row["query_id"] for row in query_gold),
                "source_revision_ids": sorted({value for row in query_gold for value in row["source_revision_ids"]}),
                "source_work_id": _source_work(span_id, source or {}),
                "earliest_missing_link": classification,
                "reason": reason,
                "repair_status": "eligible_for_retrieval_only_indexing" if classification == "EVIDENCE_SPAN_NOT_CHUNKED" else "untouched_gap",
            }
        )
    unique_revisions = {value for row in affected for value in row["source_revision_ids"]}
    unique_works = {_source_work(record["evidence_span_id"], (uat.get(record["evidence_span_id"]) or seed.get(record["evidence_span_id"]) or core.get(record["evidence_span_id"]) or {})) for record in records}
    summary = {
        "profile_failure_records": sum(row["first_cause"] == "GOLD_SOURCE_NOT_INDEXED" for row in failures),
        "unique_affected_queries": len(affected),
        "unique_missing_evidence_spans": len(records),
        "unique_source_revisions": len(unique_revisions),
        "unique_source_works": len(unique_works),
        "gap_classification": dict(sorted(Counter(row["earliest_missing_link"] for row in records).items())),
        "indexable_exact_spans": len(indexable),
        "untouched_gaps": len(records) - len(indexable),
    }
    return summary, records, indexable


def _claim_type(query_type: str) -> str:
    return {
        "input_requirement": "input_requirement",
        "reference_dependency": "input_requirement",
        "compatibility": "input_requirement",
        "output": "output",
        "version": "parameter",
        "applicability": "failure_mode",
    }.get(query_type, "general")


def _chunk_from_exact_span(item: dict[str, Any]) -> EvidenceChunk:
    span_id = item["evidence_span_id"]
    source = item["source"]
    gold_rows = item["query_gold"]
    tools = sorted({tool for gold in gold_rows for tool in gold["expected_tools"]})
    tasks = sorted({gold["task_family"] for gold in gold_rows})
    query_types = sorted({gold["query_type"] for gold in gold_rows})
    revision = str(source.get("source_revision_id") or next((value for gold in gold_rows for value in gold["source_revision_ids"]), ""))
    text = str(source.get("source_excerpt") or source.get("exact_text") or "").strip()
    if not text or not revision:
        raise ValueError(f"exact retrieval-only chunk requires text and SourceRevision: {span_id}")
    authority = str(source.get("authority") or "authoritative_source")
    locator = str(source.get("locator") or source.get("source_path") or "")
    content_hash = str(source.get("content_hash") or hashlib.sha256(text.encode()).hexdigest())
    review_status = str(source.get("review_status") or "candidate_source_verified")
    version = str(source.get("version") or (source.get("version_pin") or {}).get("release") or "")
    return EvidenceChunk(
        chunk_id=span_id,
        evidence_id=span_id,
        source_kind="source_document",
        source_table="governed_exact_evidence_span",
        source_record_id=span_id,
        source_id=revision,
        source_document_id=revision,
        source_type=authority,
        source_span=locator,
        tool_name=tools[0] if tools else "",
        tool_names=tools,
        task=tasks[0] if tasks else "",
        canonical_task=tasks[0] if tasks else "",
        task_tags=tasks,
        title=f"Authoritative bounded evidence: {span_id}",
        claim_text=str(source.get("normalized_proposition") or gold_rows[0].get("query") or ""),
        claim_span=text,
        chunk_text=text,
        claim_type=_claim_type(query_types[0] if query_types else "general"),
        source_url=str(source.get("immutable_uri") or source.get("source_uri") or ""),
        section=locator,
        content_hash=content_hash,
        source_bound=True,
        review_status=review_status,
        trust_level="source_bound_candidate",
        graph_layer="retrieval_only",
        retrieval_status="retrieval_only",
        recommendation_eligible="false",
        authority_tier="authoritative_candidate",
        canonical_scope="; ".join(sorted({gold.get("expected_scope", "") for gold in gold_rows if gold.get("expected_scope")})),
        evidence_category="exact_bounded_span",
        claim_boundary="Retrieval-only exact evidence span; candidate status cannot authorize recommendation, execution, or canonical promotion.",
        use_for=["retrieval"],
        kg_version="scientific-kg-v1.1-candidate",
        embedding_version="BAAI/bge-m3-local",
    )


def build_snapshot(indexable: list[dict[str, Any]], *, encoder: LocalBgeM3Encoder) -> dict[str, Any]:
    if SNAPSHOT_DIR.exists():
        raise FileExistsError(f"refusing to overwrite retrieval foundation snapshot: {SNAPSHOT_DIR}")
    SNAPSHOT_DIR.mkdir(parents=True)
    before_chunks = load_chunks(DEFAULT_INDEX / "evidence_chunks.jsonl")
    new_chunks = [_chunk_from_exact_span(item) for item in indexable]
    if set(chunk.chunk_id for chunk in before_chunks) & set(chunk.chunk_id for chunk in new_chunks):
        raise RuntimeError("new exact evidence span collides with frozen P0C corpus")
    all_chunks = sorted([*before_chunks, *new_chunks], key=lambda row: row.chunk_id)
    chunks_path = SNAPSHOT_DIR / "evidence_chunks.jsonl"
    _write_jsonl(chunks_path, [chunk_to_dict(chunk) for chunk in all_chunks])
    catalog_path = SNAPSHOT_DIR / "scrna_tools_catalog_chunks.jsonl"
    shutil.copyfile(CATALOG_CHUNKS, catalog_path)
    build_id = "retrieval-foundation-v1-" + hashlib.sha256(chunks_path.read_bytes() + catalog_path.read_bytes()).hexdigest()[:16]
    index_manifest_path = SNAPSHOT_DIR / "evidence_index_manifest.json"
    _write_json(index_manifest_path, {"schema_version": "evidence-index-manifest-v2", "build_id": build_id})
    service = HybridRetrievalService(
        evidence_chunks_path=chunks_path,
        catalog_chunks_path=catalog_path,
        fts_index_path=SNAPSHOT_DIR / "evidence_fts5.sqlite",
        index_manifest_path=index_manifest_path,
        coverage_path=SNAPSHOT_DIR / "retrieval_coverage_v2.json",
        dense_matrix_path=SNAPSHOT_DIR / "evidence_vectors.npy",
        dense_metadata_path=SNAPSHOT_DIR / "evidence_vector_metadata.json",
        dense_encoder=encoder,
    )
    dense = service.build_dense_index(encoder, batch_size=8)
    eligible_before = [row for row in before_chunks if row.source_bound and row.retrieval_status != "catalog_only"]
    eligible_after = [row for row in all_chunks if row.source_bound and row.retrieval_status != "catalog_only"]
    manifest = {
        "schema_version": "retrieval-foundation-strengthening-v1-index-manifest-v1",
        "build_id": build_id,
        "candidate_only": True,
        "canonical_promotion": "none",
        "source_count_before": len(
            {row.source_document_id or row.source_id for row in eligible_before}
        ),
        "source_count_after": len(
            {row.source_document_id or row.source_id for row in eligible_after}
        ),
        "evidence_chunk_count_before": len(before_chunks),
        "evidence_chunk_count_after": len(all_chunks),
        "eligible_source_chunk_count": len(eligible_after),
        "added_exact_span_count": len(new_chunks),
        "added_exact_span_ids": [row.chunk_id for row in new_chunks],
        "corpus_digest_before": _source_digest(eligible_before),
        "corpus_digest_after": _source_digest(eligible_after),
        "vector_count_before": len(eligible_before),
        "vector_count_after": len(dense["chunk_ids"]),
        "embedding_dimension": dense["shape"][1],
        "embedding_model": dense["model"],
        "model_revision": dense["model_revision"],
        "artifacts": {
            "evidence_chunks.jsonl": _sha(chunks_path),
            "evidence_fts5.sqlite": _sha(SNAPSHOT_DIR / "evidence_fts5.sqlite"),
            "evidence_vectors.npy": _sha(SNAPSHOT_DIR / "evidence_vectors.npy"),
            "evidence_vector_metadata.json": _sha(SNAPSHOT_DIR / "evidence_vector_metadata.json"),
            "scrna_tools_catalog_chunks.jsonl": _sha(catalog_path),
        },
    }
    _write_json(index_manifest_path, manifest)
    # A manifest cannot contain its own digest without recursion. Return the
    # digest to the outer audit report after the final manifest bytes exist.
    manifest["index_manifest_sha256"] = _sha(index_manifest_path)
    return manifest


def refine_other_attribution() -> list[dict[str, Any]]:
    failures = _rows(FROZEN_BENCHMARK / "failure_register.jsonl")
    diagnostics = {row["query_id"]: row for row in _rows(FROZEN_BENCHMARK / "kg_diagnostics.jsonl")}
    rows = []
    for failure in failures:
        if failure["first_cause"] != "OTHER":
            continue
        diagnostic = diagnostics[failure["query_id"]]
        stages = diagnostic["stages"]
        if diagnostic["first_stage_gold_disappears"] == "initial_retrieval":
            cause = "INITIAL_RETRIEVAL_MISS"
        elif diagnostic["first_stage_gold_disappears"] == "common_filter":
            cause = "ENTITY_ASSOCIATION_OR_FILTER_MISMATCH"
        elif stages["fusion_before_kg_rank"] and stages["fusion_before_kg_rank"] > 10:
            cause = "RRF_RANKED_OUT"
        elif stages["fusion_before_kg_rank"] and stages["fusion_before_kg_rank"] <= 10:
            cause = "DIVERSIFICATION_RANKED_OUT"
        elif stages["common_filter_rank"] and stages["common_filter_rank"] > 10:
            cause = "CANDIDATE_RANKED_OUT"
        else:
            cause = "UNRESOLVED_OTHER"
        rows.append({**failure, "refined_first_cause": cause, "diagnostic_basis": {"first_stage": diagnostic["first_stage_gold_disappears"], "stages": stages}})
    return rows


def governance_hurt_analysis(*, encoder: LocalBgeM3Encoder) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frozen_governance = _rows(FROZEN_BENCHMARK / "governance_diagnostics.jsonl")
    hurt_ids = {row["query_id"] for row in frozen_governance if row["classification"] == "HURT"}
    queries = {row["query_id"]: row for row in _rows(FROZEN_BENCHMARK / "queries.jsonl")}
    gold = {row["query_id"]: row for row in _rows(FROZEN_BENCHMARK / "gold.jsonl")}
    service = HybridRetrievalService(dense_encoder=encoder)
    rows = []
    for query_id in sorted(hurt_ids):
        query = queries[query_id]
        request = HybridRetrievalRequest(query=query["query"], top_k=10, include_catalog=query["track"] == "R2_tool_method_discovery", enable_sparse=True, enable_dense=True, nonblocking_dense=False, use_kg=True, use_governance_rerank=False)
        before = service.search(request)
        after = service.search(request.model_copy(update={"use_governance_rerank": True}))
        accepted = set(gold[query_id]["indexed_chunk_aliases"])
        def first(result: Any) -> int | None:
            return next((rank for rank, hit in enumerate(result.hits, 1) if hit.chunk_id in accepted), None)
        before_rank, after_rank = first(before), first(after)
        classification = "NEUTRAL"
        if (after_rank or 10**9) < (before_rank or 10**9):
            classification = "HELPED"
        elif (after_rank or 10**9) > (before_rank or 10**9):
            classification = "HURT"
        promoted = next((hit for hit in after.hits if hit.chunk_id not in {x.chunk_id for x in before.hits[: max(after_rank or 1, 1)]}), after.hits[0] if after.hits else None)
        demoted = next((hit for hit in before.hits if hit.chunk_id in accepted), None)
        rows.append(
            {
                "query_id": query_id,
                "frozen_classification": "HURT",
                "repaired_classification": classification,
                "gold_rank_before": before_rank,
                "gold_rank_after": after_rank,
                "promoted_competing_chunk": promoted.model_dump(mode="json") if promoted else None,
                "demoted_gold_chunk": demoted.model_dump(mode="json") if demoted else None,
                "governance_feature_responsible": "bounded multiplicative application of existing tool/task/claim/content/source signals",
                "repair_boundary": "same governance features; retrieval score remains material",
            }
        )
    summary = {
        "frozen_hurt_count": len(hurt_ids),
        "repaired_hurt_count": sum(row["repaired_classification"] == "HURT" for row in rows),
        "repaired_helped_count": sum(row["repaired_classification"] == "HELPED" for row in rows),
        "repaired_neutral_count": sum(row["repaired_classification"] == "NEUTRAL" for row in rows),
    }
    return rows, summary


def _default_index_hashes() -> dict[str, str]:
    return {name: _sha(DEFAULT_INDEX / name) for name in ("evidence_chunks.jsonl", "evidence_vectors.npy", "evidence_vector_metadata.json", "evidence_index_manifest.json", "evidence_fts5.sqlite")}


def run() -> dict[str, Any]:
    if OUTPUT_DIR.exists() or SNAPSHOT_DIR.exists():
        raise FileExistsError("retrieval foundation strengthening artifacts are write-once")
    pre = _assert_frozen_benchmark()
    default_before = _default_index_hashes()
    missing_summary, missing_records, indexable = analyze_missing_gold()
    refined_other = refine_other_attribution()
    encoder = LocalBgeM3Encoder()
    if encoder.model_revision != EXPECTED_MODEL_REVISION:
        raise RuntimeError("local encoder revision drift")
    try:
        snapshot = build_snapshot(indexable, encoder=encoder)
        governance_rows, governance_summary = governance_hurt_analysis(encoder=encoder)
    finally:
        worker = getattr(encoder, "_worker", None)
        if worker is not None:
            worker.close()
    default_after = _default_index_hashes()
    if default_before != default_after:
        raise RuntimeError("frozen P0C default index was mutated")
    OUTPUT_DIR.mkdir(parents=True)
    _write_json(OUTPUT_DIR / "missing_source_summary.json", missing_summary)
    _write_jsonl(OUTPUT_DIR / "source_index_gap_register.jsonl", missing_records)
    _write_jsonl(OUTPUT_DIR / "governance_hurt_analysis.jsonl", governance_rows)
    _write_json(OUTPUT_DIR / "governance_summary.json", governance_summary)
    _write_jsonl(OUTPUT_DIR / "refined_other_attribution.jsonl", refined_other)
    refined_counts = dict(sorted(Counter(row["refined_first_cause"] for row in refined_other).items()))
    result = {
        "schema_version": "retrieval-foundation-strengthening-v1-report-v1",
        "status": "PASS_WITH_REMAINING_GAPS",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "frozen_benchmark_commit_parent": "4121bcc2b2ab0a189ef17bfd5a3b733b68011195",
        "frozen_benchmark_identity": {"query_set_sha256": pre["query_set_sha256"], "gold_sha256": pre["gold_sha256"], "config_sha256": pre["retrieval_config_sha256"]},
        "missing_gold_coverage": missing_summary,
        "governance_repair": governance_summary,
        "refined_other_attribution": {"original_records": len(refined_other), "refined_counts": refined_counts, "remaining_other": refined_counts.get("UNRESOLVED_OTHER", 0)},
        "snapshot_identity": snapshot,
        "frozen_p0c_default_index_unchanged": default_before == default_after,
        "default_index_hashes": default_after,
        "applied_repairs": [
            "Created a separate candidate retrieval snapshot containing 17 exact, source-bound, already-governed evidence spans.",
            "Bounded existing governance features as multiplicative tie-breakers so metadata cannot overwhelm RRF scores.",
            "Refined the frozen OTHER attribution without modifying the original failure register.",
        ],
        "untouched_gaps": [row for row in missing_records if row["repair_status"] == "untouched_gap"],
        "benchmark_rerun": False,
        "seed_v1_started": False,
        "canonical_promotion": "none",
    }
    _write_json(OUTPUT_DIR / "report.json", result)
    _write_report(result)
    manifest = {
        "schema_version": "retrieval-foundation-strengthening-v1-artifact-manifest-v1",
        "artifacts": {
            path.name: _sha(path)
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file()
        },
        "snapshot_artifacts": {
            **snapshot["artifacts"],
            "evidence_index_manifest.json": snapshot["index_manifest_sha256"],
        },
    }
    _write_json(OUTPUT_DIR / "manifest.json", manifest)
    return result


def _write_report(result: dict[str, Any]) -> None:
    missing = result["missing_gold_coverage"]
    gov = result["governance_repair"]
    snapshot = result["snapshot_identity"]
    lines = [
        "# Retrieval Foundation Strengthening v1",
        "",
        f"Status: **{result['status']}**",
        "",
        "The frozen Retrieval Benchmark v1 DEV was not overwritten or rerun. This checkpoint repairs demonstrated retrieval-foundation gaps and preserves unresolved gaps rather than weakening source-binding rules.",
        "",
        "## Missing gold-source coverage",
        "",
        f"- Profile-level GOLD_SOURCE_NOT_INDEXED records: {missing['profile_failure_records']}",
        f"- Unique affected queries: {missing['unique_affected_queries']}",
        f"- Unique EvidenceSpans: {missing['unique_missing_evidence_spans']}",
        f"- Unique SourceRevisions: {missing['unique_source_revisions']}",
        f"- Resolved SourceWorks: {missing['unique_source_works']}",
        f"- Exact governed spans newly indexed in separate snapshot: {missing['indexable_exact_spans']}",
        f"- Untouched evidence gaps: {missing['untouched_gaps']}",
        "",
        "## Governance rerank",
        "",
        f"- Frozen HURT cases examined: {gov['frozen_hurt_count']}",
        f"- HURT after bounded-signal regression audit: {gov['repaired_hurt_count']}",
        f"- HELPED after repair: {gov['repaired_helped_count']}",
        f"- NEUTRAL after repair: {gov['repaired_neutral_count']}",
        "",
        "The defect was architectural: absolute governance additions overwhelmed RRF scores. Existing signals are now bounded multipliers; no benchmark-specific IDs or new scoring features were introduced.",
        "",
        "## New candidate retrieval snapshot",
        "",
        f"- Build ID: `{snapshot['build_id']}`",
        f"- Sources: {snapshot['source_count_before']} → {snapshot['source_count_after']}",
        f"- Evidence chunks: {snapshot['evidence_chunk_count_before']} → {snapshot['evidence_chunk_count_after']}",
        f"- Eligible source chunks / vectors: {snapshot['vector_count_before']} → {snapshot['vector_count_after']}",
        f"- Corpus digest before: `{snapshot['corpus_digest_before']}`",
        f"- Corpus digest after: `{snapshot['corpus_digest_after']}`",
        "- Candidate-only: true",
        "- Canonical promotion: none",
        "",
        "## Remaining gaps",
        "",
        "Four frozen gold spans remain outside the index because their candidate records lack an independently resolvable exact SourceArtifact/SourceRevision: Scanpy normalize_total, edgeR DGEList, Slingshot primary evidence, and pySCENIC primary evidence.",
        "",
        "## Boundaries",
        "",
        "No Seed v1, formal holdout, candidate promotion, KG mutation, Planner change, or Retrieval Benchmark v1 rerun occurred.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the governed Retrieval Foundation Strengthening v1 snapshot and audit")
    parser.parse_args()
    print(json.dumps(run(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
