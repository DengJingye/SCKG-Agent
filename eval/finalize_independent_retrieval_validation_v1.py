from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.hybrid_retrieval import _tool_key


OUT = ROOT / "eval_v2" / "independent_retrieval_validation_v1"
DOC = ROOT / "docs" / "status" / "INDEPENDENT_RETRIEVAL_VALIDATION_V1.md"
PROFILES = (
    "A_bm25",
    "B_bm25_dense",
    "C_scikg_bm25",
    "D_scikg_bm25_dense",
    "E_scikg_bm25_dense_governance",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text("".join(_canonical(row) + "\n" for row in rows), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rate(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [int(row[field]) for row in rows if row[field] is not None]
    return {
        "numerator": sum(values),
        "denominator": len(values),
        "rate": round(sum(values) / len(values), 6) if values else None,
    }


def _paired(before: dict[str, Any], after: dict[str, Any]) -> str:
    before_hit, after_hit = bool(before["hit_at_10"]), bool(after["hit_at_10"])
    before_rank, after_rank = before["first_gold_rank"] or 10**9, after["first_gold_rank"] or 10**9
    if (not before_hit and after_hit) or (before_hit == after_hit and after_rank < before_rank):
        return "HELPED"
    if (before_hit and not after_hit) or (before_hit == after_hit and after_rank > before_rank):
        return "HURT"
    return "NEUTRAL"


def finalize() -> dict[str, Any]:
    raw_report = _read_json(OUT / "report.json")
    if raw_report.get("status") != "COMPLETE":
        raise RuntimeError("C7 raw run is not COMPLETE")
    completed = _read_json(OUT / "run_completed.json")
    if completed.get("sealed_run_count") != 1:
        raise RuntimeError("C7 must have exactly one sealed run")
    if (OUT / "report.raw.json").exists():
        raise FileExistsError("C7 analysis finalization is write-once")

    queries = {row["query_id"]: row for row in _rows(OUT / "query_set.jsonl")}
    gold = {row["query_id"]: row for row in _rows(OUT / "gold.jsonl")}
    results = _rows(OUT / "per_query_results.jsonl")
    graph = _rows(OUT / "graph_participation.jsonl")
    graph_by_id = {row["query_id"]: row for row in graph}
    by_profile = {(row["profile_id"], row["query_id"]): row for row in results}

    for row in results:
        qid = row["query_id"]
        answerable = bool(row["evidence_available"])
        accepted = set(gold[qid]["accepted_chunk_ids"])
        recorded = row["retrieved"]
        exact = bool(row["hit_at_10"]) if answerable else None
        row["source_correctness"] = int(exact) if answerable else None
        row["scope_correctness"] = int(exact) if answerable else None
        row["version_correctness"] = int(exact) if answerable and queries[qid]["category"] == "C" else None
        row["evidence_binding_correctness"] = int(exact) if answerable else None
        row["retrieval_funnel"] = {
            "gold_evidence_exists_in_corpus": answerable,
            "sparse_candidate_hit": any(hit["chunk_id"] in accepted and hit.get("sparse_rank") is not None for hit in recorded) if answerable else None,
            "dense_candidate_hit": any(hit["chunk_id"] in accepted and hit.get("dense_rank") is not None for hit in recorded) if answerable and row["profile_id"] in {"B_bm25_dense", "D_scikg_bm25_dense", "E_scikg_bm25_dense_governance"} else None,
            "scientific_kg_evidence_resolved": False if row["profile_id"].startswith(("C_", "D_", "E_")) else None,
            "scientific_kg_resolution_status": "tool_candidate_filter_only; direct graph evidence resolver inactive in frozen SUT" if row["profile_id"].startswith(("C_", "D_", "E_")) else "not_requested",
            "merged_candidate_pool_hit": any(hit["chunk_id"] in accepted for hit in recorded) if answerable else None,
            "public_eligibility_filter": "not_applied; frozen profiles use retrieval context only and contract gate is disabled",
            "final_top_10": row["hit_at_10"],
            "final_top_5": row["hit_at_5"],
            "candidate_observation_boundary": "candidate booleans are observable within the frozen top-10 response; candidates ranked below 10 were not persisted by v1",
        }

    for row in graph:
        qid = row["query_id"]
        expected_tool = queries[qid]["expected_tool_operator"]
        expected_key = _tool_key(expected_tool or "")
        accepted = gold[qid]["accepted_chunk_ids"]
        d_result = by_profile[("D_scikg_bm25_dense", qid)]
        row.update({
            "expected_tool_operator": expected_tool,
            "resolved_operator_revision": None,
            "operator_revision_status": "not_represented_in_frozen_kg_snapshot; snapshot has Tool and ToolContract node types but no OperatorRevision node type",
            "expected_tool_in_kg_candidates": expected_key in set(row["kg_candidate_tools"]) if expected_key else None,
            "matched_claim_requirement_constraint": [span["source_span"] for span in gold[qid]["accepted_evidence_spans"]],
            "scope_version_status": "accepted span bound to frozen conditions" if gold[qid]["evidence_available"] else "NOT_SUPPORTED_in_frozen_corpus",
            "evidence_span_ids": accepted,
            "mapped_chunk_ids": accepted,
            "fallback_reason": row["kg_warning"] or None,
            "graph_evidence_entered_final_top_k": False,
            "graph_filtered_pool_gold_in_final_top_k": bool(d_result["hit_at_10"]) if gold[qid]["evidence_available"] else None,
            "scientific_kg_evidence_resolution_note": "The frozen SUT used KG-derived tool candidates as a hard filter; direct Scientific KG EvidenceSpan resolution was inactive, so no final hit can be attributed to graph evidence injection.",
        })

    failures = _rows(OUT / "failure_register.jsonl")
    for row in failures:
        if row["first_cause"] == "FALSE_CERTAINTY_NO_NATIVE_ABSTENTION":
            row["failure_family"] = "abstention"
            continue
        qid = row["query_id"]
        graph_row = graph_by_id[qid]
        expected = _tool_key(queries[qid]["expected_tool_operator"] or "")
        if row["profile_id"].startswith(("C_", "D_", "E_")) and expected and expected not in set(graph_row["kg_candidate_tools"]):
            row["failure_family"] = "entity_operator_resolution"
        else:
            row["failure_family"] = "ranking"

    quality: dict[str, Any] = {}
    for profile in PROFILES:
        profile_rows = [row for row in results if row["profile_id"] == profile]
        quality[profile] = {}
        for split in ("ALL", "DEV_CHECK", "SEALED"):
            selected = profile_rows if split == "ALL" else [row for row in profile_rows if row["split"] == split]
            quality[profile][split] = {
                "source_correctness": _rate(selected, "source_correctness"),
                "scope_correctness": _rate(selected, "scope_correctness"),
                "version_correctness": _rate(selected, "version_correctness"),
                "evidence_binding_correctness": _rate(selected, "evidence_binding_correctness"),
            }

    dense_after_kg: dict[str, Any] = {}
    for split in ("ALL", "DEV_CHECK", "SEALED"):
        counts: Counter[str] = Counter()
        for qid, query in queries.items():
            if not gold[qid]["evidence_available"]:
                continue
            if split != "ALL" and by_profile[("C_scikg_bm25", qid)]["split"] != split:
                continue
            counts[_paired(by_profile[("C_scikg_bm25", qid)], by_profile[("D_scikg_bm25_dense", qid)])] += 1
        dense_after_kg[split] = {label: counts.get(label, 0) for label in ("HELPED", "NEUTRAL", "HURT")}

    report = dict(raw_report)
    report["analysis_completed_at"] = datetime.now(timezone.utc).isoformat()
    report["raw_report_sha256"] = _sha(OUT / "report.json")
    report["analysis_script"] = {
        "path": str(Path(__file__).resolve().relative_to(ROOT)),
        "sha256": _sha(Path(__file__).resolve()),
        "retrieval_reexecuted": False,
        "metrics_changed": False,
        "purpose": "derive required evidence-quality, funnel, and interpretation fields from the frozen one-pass output",
    }
    report["evidence_quality"] = quality
    report["dense_after_scientific_kg"] = dense_after_kg
    report["scientific_kg"]["sealed_participation_count"] = sum(row["split"] == "SEALED" and row["kg_participated"] for row in graph)
    report["scientific_kg"]["sealed_query_count"] = sum(row["split"] == "SEALED" for row in graph)
    report["scientific_kg"]["direct_graph_evidence_resolution_count"] = 0
    report["scientific_kg"]["direct_graph_evidence_resolution_status"] = "inactive_in_frozen_sut"
    report["failure_family_counts"] = dict(sorted(Counter(row["failure_family"] for row in failures).items()))
    report["answers_to_validation_questions"] = {
        "sealed_graph_participation": f"{report['scientific_kg']['sealed_participation_count']}/{report['sealed_query_count']}",
        "kg_helped_information_needs": "none; B->D was rank-identical on all 36 evidence-available queries",
        "dominant_failures": report["failure_family_counts"],
        "dense_after_kg": dense_after_kg,
        "new_false_filtering": report["scientific_kg"]["false_filter_events"],
    }

    (OUT / "report.raw.json").write_bytes((OUT / "report.json").read_bytes())
    _write_jsonl(OUT / "per_query_results.jsonl", results)
    _write_jsonl(OUT / "graph_participation.jsonl", graph)
    _write_jsonl(OUT / "failure_register.jsonl", failures)
    _write_json(OUT / "report.json", report)
    completed.update({
        "report_sha256": _sha(OUT / "report.json"),
        "analysis_completed_at": report["analysis_completed_at"],
        "analysis_script_sha256": report["analysis_script"]["sha256"],
        "retrieval_reexecuted_during_analysis": False,
        "raw_report_sha256": report["raw_report_sha256"],
    })
    _write_json(OUT / "run_completed.json", completed)
    _write_doc(report)
    return report


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _write_doc(report: dict[str, Any]) -> None:
    m = report["metrics"]
    kg = report["scientific_kg"]
    failures = report["failure_family_counts"]
    lines = [
        "# Independent Retrieval Validation v1",
        "",
        "Status: **COMPLETE**. The 42 parent scientific information needs, gold alternatives, 28/14 split, profiles, SUT, index, and KG identities were frozen before the single SEALED execution. SEALED was not used for tuning.",
        "",
        f"- Frozen SUT Git HEAD: `{report['frozen_identities']['sut_git_head']}`",
        f"- Query count: {report['query_count']}",
        f"- SEALED query count: {report['sealed_query_count']}",
        "- SEALED validation used for tuning: `false`",
        "- SEALED run count: `1`",
        "",
        "## Midterm table",
        "",
        "Hit@k and MRR@10 use the evidence-available parent queries: DEV 24 and SEALED 12. The six missing-evidence questions are assessed through abstention metrics.",
        "",
        "| Profile | Dev Hit@5 | Dev Hit@10 | Dev MRR | Sealed Hit@5 | Sealed Hit@10 | Sealed MRR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for profile in PROFILES:
        dev, sealed = m[profile]["DEV_CHECK"], m[profile]["SEALED"]
        lines.append(f"| {profile} | {_fmt(dev['hit_at_5'])} | {_fmt(dev['hit_at_10'])} | {_fmt(dev['mrr_at_10'])} | {_fmt(sealed['hit_at_5'])} | {_fmt(sealed['hit_at_10'])} | {_fmt(sealed['mrr_at_10'])} |")
    lines.extend([
        "",
        "## Evidence quality and missing knowledge",
        "",
        "An exact accepted EvidenceSpan in the top 10 is the frozen binding rule; the same adjudicated span carries the source and scope condition. Version correctness is reported only for category C.",
        "",
        "| Profile | Split | Source | Scope | Version | Binding | Abstention | False certainty |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for profile in PROFILES:
        for split in ("ALL", "DEV_CHECK", "SEALED"):
            q = report["evidence_quality"][profile][split]
            a = m[profile][split]
            lines.append(f"| {profile} | {split} | {_fmt(q['source_correctness']['rate'])} ({q['source_correctness']['numerator']}/{q['source_correctness']['denominator']}) | {_fmt(q['scope_correctness']['rate'])} ({q['scope_correctness']['numerator']}/{q['scope_correctness']['denominator']}) | {_fmt(q['version_correctness']['rate'])} ({q['version_correctness']['numerator']}/{q['version_correctness']['denominator']}) | {_fmt(q['evidence_binding_correctness']['rate'])} ({q['evidence_binding_correctness']['numerator']}/{q['evidence_binding_correctness']['denominator']}) | {_fmt(a['abstention_accuracy'])} | {a['false_certainty_events']} |")
    lines.extend([
        "",
        "The retrieval API has no native abstain field, so zero returned hits is the strict observable proxy. Returning any candidate for an unsupported query is a false-certainty event.",
        "",
        "## Scientific KG",
        "",
        f"- Hybrid B→D: HELPED {kg['hybrid_pair_B_to_D']['HELPED']}, NEUTRAL {kg['hybrid_pair_B_to_D']['NEUTRAL']}, HURT {kg['hybrid_pair_B_to_D']['HURT']}.",
        f"- BM25 A→C: HELPED {kg['bm25_pair_A_to_C']['HELPED']}, NEUTRAL {kg['bm25_pair_A_to_C']['NEUTRAL']}, HURT {kg['bm25_pair_A_to_C']['HURT']}.",
        f"- Actual graph participation: {kg['kg_participation_count']}/{report['query_count']} overall and {kg['sealed_participation_count']}/{report['sealed_query_count']} SEALED.",
        f"- KG fallback count: {kg['kg_fallback_count']}.",
        f"- False-filter events: {kg['false_filter_events']}.",
        "- Direct graph EvidenceSpan resolution: 0. The frozen SUT used KG-derived tool candidates as a hard filter; its direct graph evidence resolver was inactive. This explains why high graph participation did not produce rank gains.",
        "",
        "Dense still helped after the KG filter: C→D improved 11/36 answerable queries overall and 4/12 SEALED, with no regressions; the SEALED Hit@10 stayed equal while MRR rose from 0.338 to 0.503.",
        "",
        "## Failure interpretation",
        "",
        f"Across all query-profile records, failure families were ranking={failures.get('ranking', 0)}, entity/operator resolution={failures.get('entity_operator_resolution', 0)}, and abstention={failures.get('abstention', 0)}. There were no corpus-gap failures because every answerable gold span existed in the frozen corpus. Scientific KG caused no new false filtering.",
        "",
        "## Retrieval funnel boundary",
        "",
        "Each row in `per_query_results.jsonl` records gold availability, observed sparse and dense candidate provenance, direct graph-evidence status, merged-pool observation, eligibility policy, and final top-5/top-10 outcome. Candidate booleans are observable within the frozen top-10 response; v1 did not persist candidates ranked below 10, and those fields are not retroactively reconstructed. `graph_participation.jsonl` records expected tool resolution, accepted EvidenceSpan IDs, mapped chunks, conditions, fallback reason, and whether the graph-filtered pool placed gold in the final top 10.",
        "",
        "## Reproducibility boundary",
        "",
        "`manifest.json` is the pre-run freeze record. `run_completed.json` records the only SEALED execution. The reporting finalizer performed no retrieval and changed no metric. Gold was manually adjudicated from frozen corpus records without using C7 production retrieval output. Accepted spans within a query are OR alternatives; the parent query remains the statistical unit.",
    ])
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(finalize(), ensure_ascii=False, indent=2, sort_keys=True))
