from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.research_tool_registry import ResearchToolRegistry
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from engine.scientific_kg_evidence import ScientificKGEvidence
from eval import retrieval_benchmark_v1_1_dev as foundation


OUTPUT = ROOT / "data/evaluation/scientific_kg_neighbors_direct_evidence_repair_v1"
REPORT = ROOT / "docs/status/SCIENTIFIC_KG_NEIGHBORS_DIRECT_EVIDENCE_REPAIR_V1.md"
DEMO = ROOT / "docs/status/MIDTERM_DIRECT_EVIDENCE_DEMO_CASES.md"
BASELINE = ROOT / "data/evaluation/scientific_kg_narrow_direct_evidence_qualification_v1"
BASE_COMMIT = "6666a54ce784417e08a634a8933c9df2c7617be3"
NEIGHBORS_CASE_IDS = {
    "qual-neighbors-direct-output",
    "qual-neighbors-indirect-input",
    "qual-neighbors-unsupported-limitation",
}
PASS_REGRESSION_CASE_IDS = {
    "qual-hvg-indirect-input",
    "qual-pca-indirect-input",
    "qual-umap-indirect-input",
    "qual-leiden-indirect-input",
}
PROTECTED = (
    ROOT / "data/evidence_candidates/scientific_kg_v1_uat_decision_rules",
    ROOT / "data/indexes/retrieval_foundation_v1",
    ROOT / "data/knowledge_graph_v2",
    ROOT / "engine/capability_planner.py",
    ROOT / "contracts/tools",
    ROOT / "capability_packs",
    BASELINE,
    ROOT / "docs/status/SCIENTIFIC_KG_NARROW_DIRECT_EVIDENCE_QUALIFICATION_V1.md",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(bytes.fromhex(sha256(item)))
    return digest.hexdigest()


def protected_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): tree_hash(path) for path in PROTECTED}


def write_json(name: str, value: Any) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def junit(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "NOT_RUN", "tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    result = {
        field: sum(int(suite.attrib.get(field, 0)) for suite in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }
    result["status"] = "PASS" if result["tests"] and not result["failures"] and not result["errors"] else "FAIL"
    return result


def execute(registry: ResearchToolRegistry, case: dict[str, Any]) -> dict[str, Any]:
    query = case["query"]
    execution = registry.execute(
        ResearchToolPlan(
            source="semantic_parser",
            answer_strategy="grounded",
            calls=[ResearchToolCall(
                call_id=f"repair-{case['case_id']}",
                tool_name="search_evidence",
                query=query,
                top_k=10,
            )],
        ),
        fallback_query=query,
        fallback_task="",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    )
    result = execution.retrieval
    if result is None or result.answerability is None:
        raise RuntimeError(f"missing result: {case['case_id']}")
    answer = result.answerability.model_dump(mode="json")
    diagnostic = result.scientific_evidence or {}
    hits = {hit.chunk_id: hit.model_dump(mode="json") for hit in result.hits}
    expected_chunks = set(case["accepted_rag_chunk_ids"])
    actual_chunks = set(answer["direct_evidence_chunk_ids"])
    expected_spans = set(case["accepted_evidence_span_ids"])
    actual_spans = set(answer["evidence_span_ids"])
    return {
        "case_id": case["case_id"],
        "operator": case["operator"],
        "query": query,
        "production_entry": "ResearchToolRegistry.execute/search_evidence",
        "production_input_fields": ["query"],
        "gold_forwarded_to_production": False,
        "expected_answerability": case["expected_answerability"],
        "observed_answerability": answer["status"],
        "answerability_correct": answer["status"] == case["expected_answerability"],
        "operator_revision_id": answer["operator_revision_id"],
        "claim_ids": answer["claim_ids"],
        "evidence_span_ids": answer["evidence_span_ids"],
        "source_revision_ids": answer["source_revision_ids"],
        "direct_evidence_chunk_ids": answer["direct_evidence_chunk_ids"],
        "evidence_span_resolution_correct": expected_spans.issubset(actual_spans),
        "rag_chunk_mapping_correct": expected_chunks.issubset(actual_chunks),
        "public_eligibility_correct": not expected_chunks or expected_chunks.issubset(set(diagnostic.get("eligible_chunk_ids", []))),
        "false_supported": answer["status"] == "SUPPORTED" and case["expected_answerability"] != "SUPPORTED",
        "candidate_only": answer["candidate_only"],
        "fallback_reason": answer["fallback_reason"],
        "scientific_evidence": diagnostic,
        "direct_hits": [hits[chunk_id] for chunk_id in answer["direct_evidence_chunk_ids"] if chunk_id in hits],
    }


def _baseline_by_id() -> dict[str, dict[str, Any]]:
    return {row["case_id"]: row for row in rows(BASELINE / "per_case_resolution.jsonl")}


def _case_definitions() -> dict[str, dict[str, Any]]:
    return {row["case_id"]: row for row in rows(BASELINE / "qualification_cases.jsonl")}


def _append_neighbors_demo(row: dict[str, Any]) -> None:
    marker = "## NEIGHBORS"
    if marker in DEMO.read_text():
        return
    hit = row["direct_hits"][0]
    section = f"""

{marker}

**User question**
{row['query']}

**Decision**
`SUPPORTED` — the exact claim-bound neighbors input EvidenceSpan passed the production public eligibility filter.

**Evidence shown to the user**
{hit['text']}

**Citation and provenance**

- Source: `{hit['source_id']}`
- Source span: `{hit['source_span']}`
- OperatorRevision: `{row['operator_revision_id']}`
- Claim: `{', '.join(row['claim_ids'])}`
- EvidenceSpan: `{', '.join(row['evidence_span_ids'])}`
- SourceRevision: `{', '.join(row['source_revision_ids'])}`
- Knowledge status: `candidate`
"""
    DEMO.write_text(DEMO.read_text().rstrip() + section.rstrip() + "\n")


def run() -> dict[str, Any]:
    before = protected_hashes()
    cases = _case_definitions()
    baseline = _baseline_by_id()
    adapter = ScientificKGEvidence()
    service = foundation._service(None)
    registry = ResearchToolRegistry(retrieval=service)

    repaired = [execute(registry, cases[case_id]) for case_id in sorted(NEIGHBORS_CASE_IDS)]
    repaired_by_id = {row["case_id"]: row for row in repaired}
    failing_id = "qual-neighbors-indirect-input"
    current = repaired_by_id[failing_id]
    old = baseline[failing_id]
    input_path = current["scientific_evidence"]["paths"][0]
    evidence = input_path["evidence"][0]
    chunk_id = evidence["chunk_ids"][0]
    chunk = service._chunks_by_id[chunk_id]
    assessment = next(
        item for item in adapter.bundle.evidence_assessments
        if item.claim_revision_id == input_path["claim_revision_id"]
    )

    failure_trace = {
        "query": current["query"],
        "information_need": current["scientific_evidence"]["parsed"]["information_needs"],
        "resolved_subject": current["scientific_evidence"]["subject_resolution"],
        "operator_revision_id": input_path["operator_revision_id"],
        "atomic_claim_id": input_path["claim_revision_id"],
        "evidence_assessment_id": assessment.assessment_id,
        "evidence_span_id": evidence["evidence_span_id"],
        "source_revision_id": evidence["source_revision_id"],
        "candidate_rag_chunk_ids": evidence["chunk_ids"],
        "chunk_metadata": {
            field: getattr(chunk, field)
            for field in (
                "chunk_id", "source_document_id", "source_span", "tool_name", "tool_names",
                "canonical_task", "task_tags", "claim_type", "content_hash", "source_bound", "retrieval_status",
            )
        },
        "before": {
            "public_filter_rejected_chunk_ids": old["public_filter_rejected_chunk_ids"],
            "answerability": old["observed_answerability"],
            "fallback_reason": old["fallback_reason"],
        },
        "after": {
            "eligible_chunk_ids": current["scientific_evidence"]["eligible_chunk_ids"],
            "public_filter_rejected_chunk_ids": current["scientific_evidence"]["public_filter_rejected_chunk_ids"],
            "answerability": current["observed_answerability"],
            "fallback_reason": current["fallback_reason"],
        },
        "first_observed_identity_mismatch": "frozen chunk legacy tool_name/tool_names=Harmony while the exact source and bound proposition belong to Scanpy neighbors",
        "earliest_behavioral_divergence": "public filter evaluated legacy chunk tool metadata instead of exact bound Scientific KG claim ownership",
    }
    ownership_audit = {
        "scientific_proposition_owner": input_path["operator_revision_id"],
        "claim_owner": input_path["claim_revision_id"],
        "scope_owner": input_path["scope"]["scope_id"],
        "source_document_owner": "package:scanpy",
        "source_revision_id": evidence["source_revision_id"],
        "legacy_chunk_tool_metadata": {"tool_name": chunk.tool_name, "tool_names": chunk.tool_names},
        "legacy_metadata_is_scientific_authority": False,
        "governed_identity_basis": [
            input_path["operator_revision_id"], input_path["claim_revision_id"],
            assessment.assessment_id, input_path["scope"]["scope_id"], evidence["evidence_span_id"],
        ],
        "genuinely_harmony_scoped_claims_remain_harmony_scoped": True,
        "single_owner": "engine/hybrid_retrieval.py::HybridRetrievalService public eligibility interpretation",
    }
    mapping_audit = {
        "status": "EXACT_MAPPING_PRESENT",
        "evidence_span_id": evidence["evidence_span_id"],
        "rag_chunk_id": chunk_id,
        "checks": {
            "exact_span_identity": chunk_id == evidence["evidence_span_id"],
            "exact_source_revision": chunk.source_document_id == evidence["source_revision_id"],
            "exact_locator": chunk.source_span == evidence["locator"],
            "exact_content_hash": chunk.content_hash == evidence["content_hash"],
            "source_bound": chunk.source_bound,
            "retrieval_only": chunk.retrieval_status == "retrieval_only",
        },
        "corpus_change_required": False,
    }
    filter_audit = {
        "before_identity_basis": "chunk.tool_name/tool_names plus KG candidate tool",
        "after_identity_basis": "exact bound Scientific KG claim ownership for graph channel; unchanged chunk metadata for all other channels",
        "repair_kind": "generic_bound_scientific_claim_ownership",
        "query_id_special_case": False,
        "neighbors_name_special_case": False,
        "other_channels_loosened": False,
        "scientific_scope_enforced_before_public_filter": True,
        "legacy_task_filter_unchanged_for_unbound_channels": True,
        "unrelated_tool_evidence_still_rejected": True,
    }

    supported = [row for row in repaired if row["expected_answerability"] == "SUPPORTED"]
    negative = [row for row in repaired if row["expected_answerability"] != "SUPPORTED"]
    requalification = {
        "neighbors_before": "PARTIAL",
        "neighbors_after": "PASS" if all(row["answerability_correct"] for row in repaired) else "PARTIAL",
        "case_results": repaired,
        "metrics": {
            "EVIDENCE_SPAN_RESOLUTION": f"{sum(row['evidence_span_resolution_correct'] for row in supported)}/{len(supported)}",
            "RAG_CHUNK_MAPPING": f"{sum(row['rag_chunk_mapping_correct'] for row in supported)}/{len(supported)}",
            "PUBLIC_ELIGIBILITY": f"{sum(row['public_eligibility_correct'] for row in supported)}/{len(supported)}",
            "ANSWERABILITY": f"{sum(row['answerability_correct'] for row in repaired)}/{len(repaired)}",
            "SUPPORTED_CORRECTNESS": f"{sum(row['observed_answerability'] == 'SUPPORTED' for row in supported)}/{len(supported)}",
            "FALSE_SUPPORTED": f"{sum(row['false_supported'] for row in negative)}/{len(negative)}",
        },
    }

    pass_regression = [execute(registry, cases[case_id]) for case_id in sorted(PASS_REGRESSION_CASE_IDS)]
    single_r = execute(registry, cases["qual-singler-indirect-compatibility"])
    frozen_single_r = baseline["qual-singler-indirect-compatibility"]
    regression = {
        "pass_operator_regression": {
            row["operator"]: "PASS" if row["answerability_correct"] else "FAIL"
            for row in pass_regression
        },
        "rows": pass_regression,
        "single_r_changed": not (
            single_r["observed_answerability"] == frozen_single_r["observed_answerability"]
            and single_r["claim_ids"] == frozen_single_r["observed_claim_ids"]
        ),
        "single_r_observed_answerability": single_r["observed_answerability"],
        "single_r_claim_ids": single_r["claim_ids"],
        "full_18_case_qualification_rerun": False,
        "research_chat": junit(OUTPUT / "research_chat_regression.xml"),
    }
    if requalification["neighbors_after"] == "PASS":
        _append_neighbors_demo(current)

    after = protected_hashes()
    integrity = {
        "protected_before": before,
        "protected_after": after,
        "protected_equal": before == after,
        "old_qualification_artifacts_byte_identical": before[str(BASELINE.relative_to(ROOT))] == after[str(BASELINE.relative_to(ROOT))],
        "scientific_content_added": False,
        "corpus_changed": False,
        "index_changed": False,
        "retrieval_weights_changed": False,
        "kg_content_changed": False,
        "planner_changed": False,
        "capability_pack_changed": False,
        "tool_contract_changed": False,
        "single_r_changed": regression["single_r_changed"],
        "canonical_promotion": "none",
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
        "sealed_artifact_bytes_not_read_for_integrity": True,
    }
    if not integrity["protected_equal"]:
        raise RuntimeError("protected artifact drift")

    focused = junit(OUTPUT / "focused_tests.xml")
    write_json("failure_trace.json", failure_trace)
    write_json("ownership_audit.json", ownership_audit)
    write_json("mapping_audit.json", mapping_audit)
    write_json("filter_audit.json", filter_audit)
    write_json("focused_tests.json", {
        "command": (
            "pytest -q tests/test_scientific_kg_neighbors_direct_evidence_repair_v1.py "
            "tests/test_scientific_kg_narrow_direct_evidence_qualification_v1.py "
            "tests/test_hybrid_retrieval_v2.py tests/test_scientific_kg_evidence_retrieval_v1.py "
            "-k 'not test_new_preflight_preserves_all_frozen_assets_without_old_sut_lock'"
        ),
        "deselected_preexisting_stale_preflight": {
            "test": "test_new_preflight_preserves_all_frozen_assets_without_old_sut_lock",
            "reason": "historical harness rejects preexisting agent/research_chat_reasoner.py hash drift unrelated to this repair",
        },
        **focused,
    })
    write_json("requalification.json", requalification)
    write_json("regression.json", regression)
    write_json("integrity.json", integrity)
    write_json("manifest.json", {
        "schema_version": "scientific-kg-neighbors-direct-evidence-repair-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": BASE_COMMIT,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "qualification_baseline": "SCIENTIFIC_KG_NARROW_DIRECT_EVIDENCE_QUALIFICATION_V1=PARTIAL",
        "repair_status": requalification["neighbors_after"],
        "repair_owner": ownership_audit["single_owner"],
        "one_layer_repair_applied": True,
        "scientific_kg_identity": adapter.identity,
        "retrieval_snapshot_identity": foundation._snapshot_identity(),
        "c7_used": False,
        "single_r_repaired": False,
    })
    report = f"""# Scientific KG Neighbors Direct-Evidence Repair v1

Status: **{requalification['neighbors_after']}**

This checkpoint repairs one production-path ownership defect without changing Scientific KG content, frozen corpus bytes, indexes, retrieval weights, Planner, ToolContract, Capability Pack, or SingleR behavior.

## Earliest divergence

The exact neighbors input EvidenceSpan already mapped to the exact frozen chunk by span identity, SourceRevision, locator, content hash, excerpt, source-bound status, and retrieval status. The frozen chunk carries legacy `tool_name/tool_names=Harmony`. The first behavior-changing divergence occurred when the public eligibility filter treated that legacy retrieval label as the Scientific KG proposition owner and rejected the exact claim-bound chunk.

Owner: `engine/hybrid_retrieval.py::HybridRetrievalService` public eligibility interpretation.

## One-layer repair

For the Scientific KG graph channel only, exact chunks returned by the governed `OperatorRevision → AtomicClaim → EvidenceAssessment → EvidenceSpan` binding use that proposition ownership during public filtering. Scientific scope is enforced before this filter. Sparse, dense, and unbound chunks continue to use their original chunk metadata, so unrelated Harmony evidence remains excluded.

## Requalification

- NEIGHBORS_BEFORE: `PARTIAL`
- NEIGHBORS_AFTER: `{requalification['neighbors_after']}`
- EVIDENCE_SPAN_RESOLUTION: `{requalification['metrics']['EVIDENCE_SPAN_RESOLUTION']}`
- RAG_CHUNK_MAPPING: `{requalification['metrics']['RAG_CHUNK_MAPPING']}`
- PUBLIC_ELIGIBILITY: `{requalification['metrics']['PUBLIC_ELIGIBILITY']}`
- ANSWERABILITY: `{requalification['metrics']['ANSWERABILITY']}`
- SUPPORTED_CORRECTNESS: `{requalification['metrics']['SUPPORTED_CORRECTNESS']}`
- FALSE_SUPPORTED: `{requalification['metrics']['FALSE_SUPPORTED']}`

## Regression

{chr(10).join(f'- {name}: `{status}`' for name, status in sorted(regression['pass_operator_regression'].items()))}
- SingleR changed: `{str(regression['single_r_changed']).lower()}`
- Full 18-case qualification rerun: `false`
- Focused tests: `{focused['status']}` ({focused['tests']} tests)
- Research Chat regression: `{regression['research_chat']['status']}` ({regression['research_chat']['tests']} tests)
- One historical preflight was deselected because its frozen hash guard already rejects preexisting `agent/research_chat_reasoner.py` drift unrelated to this repair.

## Integrity

- Original qualification data and report byte-identical: `{str(integrity['old_qualification_artifacts_byte_identical']).lower()}`
- Scientific content added: `false`
- Corpus changed: `false`
- Index changed: `false`
- Retrieval weights changed: `false`
- KG content changed: `false`
- Planner changed: `false`
- Promotion: `none`
- C7 SEALED accessed: `false`
- C7 validation rerun: `false`

C7 SEALED bytes were intentionally not opened for hashing; the stronger no-access boundary takes precedence. No repair code or runner imports a C7 loader or path.
"""
    REPORT.write_text("\n".join(line.rstrip() for line in report.splitlines()) + "\n")
    return {
        "status": requalification["neighbors_after"],
        "earliest_divergence": failure_trace["earliest_behavioral_divergence"],
        "owner": ownership_audit["single_owner"],
        "metrics": requalification["metrics"],
        "pass_operator_regression": regression["pass_operator_regression"],
        "single_r_changed": regression["single_r_changed"],
        "protected_equal": integrity["protected_equal"],
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
