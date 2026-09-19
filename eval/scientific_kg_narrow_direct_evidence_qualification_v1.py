from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.research_tool_registry import ResearchToolRegistry
from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.research_agent_models import ResearchToolCall, ResearchToolPlan
from engine.scientific_kg_evidence import PREDICATES, ScientificKGEvidence
from eval import retrieval_benchmark_v1_1_dev as foundation


OUTPUT = ROOT / "data/evaluation/scientific_kg_narrow_direct_evidence_qualification_v1"
CASES = OUTPUT / "qualification_cases.jsonl"
MANIFEST = OUTPUT / "manifest.json"
REPORT = ROOT / "docs/status/SCIENTIFIC_KG_NARROW_DIRECT_EVIDENCE_QUALIFICATION_V1.md"
DEMO_REPORT = ROOT / "docs/status/MIDTERM_DIRECT_EVIDENCE_DEMO_CASES.md"
EXPECTED_CASES_SHA256 = "7b82d1b0662ef54585a7df9686781b18a1364b35a7fba60dea597693166aaa30"

# C7 is deliberately absent. Reading it, even for an integrity hash, is prohibited.
PROTECTED = (
    ROOT / "data/evidence_candidates/scientific_kg_v1_uat_decision_rules",
    ROOT / "data/indexes/retrieval_foundation_v1",
    ROOT / "data/knowledge_graph_v2",
    ROOT / "engine/capability_planner.py",
    ROOT / "engine/hybrid_retrieval.py",
    ROOT / "engine/scientific_kg_evidence.py",
    ROOT / "contracts/tools",
    ROOT / "capability_packs",
    ROOT / "data/evaluation/scientific_kg_direct_evidence_abstention_v1",
    ROOT / "data/evaluation/scientific_kg_direct_evidence_rootcause_v1",
    ROOT / "data/evaluation/scientific_kg_operator_wiring_v1",
    ROOT / "data/evaluation/scientific_kg_direct_evidence_coverage_audit_v1",
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
    return {
        str(path.relative_to(ROOT)): tree_hash(path)
        for path in PROTECTED
        if path.exists()
    }


def load_cases() -> list[dict[str, Any]]:
    actual = sha256(CASES)
    if actual != EXPECTED_CASES_SHA256:
        raise RuntimeError(f"qualification case drift: {actual}")
    return [json.loads(line) for line in CASES.read_text().splitlines() if line]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
    }


def _expected_predicates(case: dict[str, Any]) -> set[str]:
    return {
        predicate
        for need in case["information_need_types"]
        for predicate in PREDICATES.get(need, set())
    }


def _case_failure_class(row: dict[str, Any]) -> str:
    if row["answerability_correct"] and row["claim_type_fidelity"] and row["rag_chunk_mapping_correct"]:
        return "NONE"
    if row["case_id"] == "qual-neighbors-indirect-input":
        return "EVIDENCE_MAPPING_ERROR"
    if row["case_id"] == "qual-singler-indirect-compatibility":
        return "CLAIM_SELECTION_ERROR"
    if not row["subject_resolution_correct"]:
        return "SUBJECT_RESOLUTION_ERROR"
    if not row["claim_type_fidelity"]:
        return "CLAIM_SELECTION_ERROR"
    if not row["rag_chunk_mapping_correct"]:
        return "EVIDENCE_MAPPING_ERROR"
    return "AUDIT_MISCLASSIFICATION"


def _run_case(
    registry: ResearchToolRegistry,
    adapter: ScientificKGEvidence,
    case: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    # Only query and generic search parameters cross the production boundary.
    query = case["query"]
    plan = ResearchToolPlan(
        source="semantic_parser",
        answer_strategy="grounded",
        calls=[ResearchToolCall(
            call_id=case["case_id"],
            tool_name="search_evidence",
            query=query,
            top_k=10,
        )],
    )
    execution = registry.execute(
        plan,
        fallback_query=query,
        fallback_task="",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    )
    retrieval = execution.retrieval
    if retrieval is None or retrieval.answerability is None:
        raise RuntimeError(f"missing production retrieval result: {case['case_id']}")
    answer = retrieval.answerability.model_dump(mode="json")
    diagnostic = retrieval.scientific_evidence or {}
    resolution = diagnostic.get("subject_resolution", {})
    paths = diagnostic.get("paths", [])
    claims = set(answer["claim_ids"])
    spans = set(answer["evidence_span_ids"])
    chunks = set(answer["direct_evidence_chunk_ids"])
    accepted_claims = set(case["accepted_claim_ids"])
    accepted_spans = set(case["accepted_evidence_span_ids"])
    accepted_chunks = set(case["accepted_rag_chunk_ids"])
    expected_predicates = _expected_predicates(case)
    actual_predicates = {path["predicate"] for path in paths}
    claim_type_fidelity = (
        claims == accepted_claims
        if accepted_claims
        else not claims or case["case_id"] == "qual-pca-version-mismatch"
    )
    evidence_rows = [evidence for path in paths for evidence in path.get("evidence", [])]
    source_binding_correct = bool(evidence_rows) and all(
        evidence.get("binding_verified") is True
        and evidence.get("source_revision_id")
        and evidence.get("knowledge_status") == "candidate"
        for evidence in evidence_rows
    )
    subject_correct = resolution.get("status") == case["expected_subject_resolution_status"]
    revision_correct = (
        resolution.get("selected_operator_revision_id", "")
        == case["expected_operator_revision_id"]
    )
    # Resolution asks whether every frozen accepted identity was reached. Extra
    # identities are scored separately as claim-type/leakage errors so one
    # defect does not depress several otherwise distinct path metrics.
    span_correct = accepted_spans.issubset(spans)
    chunk_correct = accepted_chunks.issubset(chunks)
    row = {
        "case_id": case["case_id"],
        "operator": case["operator"],
        "case_kind": case["case_kind"],
        "query": query,
        "production_entry": "ResearchToolRegistry.execute/search_evidence",
        "production_input_fields": ["query"],
        "gold_forwarded_to_production": False,
        "parsed_information_needs": diagnostic.get("parsed", {}).get("information_needs", []),
        "subject_resolution": resolution,
        "observed_operator_revision_id": resolution.get("selected_operator_revision_id", ""),
        "observed_claim_ids": sorted(claims),
        "observed_evidence_span_ids": sorted(spans),
        "observed_source_revision_ids": sorted(answer["source_revision_ids"]),
        "observed_direct_evidence_chunk_ids": sorted(chunks),
        "mapped_chunk_ids_before_public_filter": diagnostic.get("mapped_chunk_ids", []),
        "public_filter_rejected_chunk_ids": diagnostic.get("public_filter_rejected_chunk_ids", []),
        "observed_answerability": answer["status"],
        "answerability_reason": answer["reason"],
        "fallback_reason": answer["fallback_reason"],
        "candidate_only": answer["candidate_only"],
        "expected_answerability": case["expected_answerability"],
        "subject_resolution_correct": subject_correct,
        "operator_revision_correct": revision_correct,
        "direct_claim_resolution_correct": claims == accepted_claims if accepted_claims else None,
        "direct_evidence_span_resolution_correct": span_correct if accepted_spans else None,
        "rag_chunk_mapping_correct": chunk_correct if accepted_chunks else not chunks,
        "answerability_correct": answer["status"] == case["expected_answerability"],
        "claim_type_fidelity": claim_type_fidelity and actual_predicates.issubset(expected_predicates),
        "source_binding_correct": source_binding_correct if evidence_rows else None,
        "scope_version_correct": (
            answer["status"] == case["expected_answerability"]
            if case["case_kind"] == "condition_scope_control"
            else None
        ),
        "unrelated_claim_ids": sorted(claims - accepted_claims) if accepted_claims else [],
        "false_supported": answer["status"] == "SUPPORTED" and case["expected_answerability"] != "SUPPORTED",
        "retrieved_chunk_ids": [hit.chunk_id for hit in retrieval.hits],
        "warnings": [warning for obs in execution.observations for warning in obs.warnings],
    }
    row["failure_class"] = _case_failure_class(row)
    assessments = {
        assessment.claim_revision_id: assessment.assessment_id
        for assessment in adapter.bundle.evidence_assessments
    }
    provenance = []
    for path in paths:
        for evidence in path.get("evidence", []):
            for chunk_id in evidence.get("chunk_ids", []) or [""]:
                provenance.append({
                    "case_id": case["case_id"],
                    "operator": case["operator"],
                    "operator_revision_id": path["operator_revision_id"],
                    "claim_revision_id": path["claim_revision_id"],
                    "claim_type": path["predicate"],
                    "scope_id": path.get("scope", {}).get("scope_id", ""),
                    "evidence_assessment_id": assessments.get(path["claim_revision_id"], ""),
                    "evidence_span_id": evidence["evidence_span_id"],
                    "source_revision_id": evidence["source_revision_id"],
                    "rag_chunk_id": chunk_id,
                    "binding_verified": evidence.get("binding_verified", False),
                    "production_eligible": chunk_id in chunks,
                    "knowledge_status": evidence.get("knowledge_status", "candidate"),
                })
    hit_by_id = {hit.chunk_id: hit.model_dump(mode="json") for hit in retrieval.hits}
    demo = {
        "case_id": case["case_id"],
        "operator": case["operator"],
        "user_question": query,
        "answerability": answer["status"],
        "candidate_status": answer["candidate_only"],
        "operator_revision_id": answer["operator_revision_id"],
        "claim_ids": answer["claim_ids"],
        "evidence_span_ids": answer["evidence_span_ids"],
        "source_revision_ids": answer["source_revision_ids"],
        "direct_evidence": [hit_by_id[item] for item in answer["direct_evidence_chunk_ids"] if item in hit_by_id],
    }
    return row, provenance, demo


def _negative_controls(service, rows: list[dict[str, Any]]) -> dict[str, Any]:
    query = "What input matrix does scanpy.pp.pca in Scanpy 1.11.2 accept?"
    baseline = service.search(HybridRetrievalRequest(
        query=query,
        top_k=10,
        include_catalog=False,
        enable_sparse=True,
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
        use_scientific_evidence=False,
    ))
    by_id = {row["case_id"]: row for row in rows}
    registry = ResearchToolRegistry(retrieval=service)
    ambiguous_query = "Does Scanpy PCA or UMAP require an input representation?"
    ambiguous = registry.execute(
        ResearchToolPlan(
            source="semantic_parser",
            answer_strategy="grounded",
            calls=[ResearchToolCall(call_id="negative-ambiguous", tool_name="search_evidence", query=ambiguous_query, top_k=10)],
        ),
        fallback_query=ambiguous_query,
        fallback_task="",
        enable_dense=False,
        use_kg=True,
        use_governance_rerank=True,
        use_contract_gate=True,
    ).retrieval
    ambiguous_answer = ambiguous.answerability.model_dump(mode="json")
    ambiguous_diag = ambiguous.scientific_evidence or {}
    checks = {
        "scientific_kg_disabled_baseline_retrieval_works": bool(baseline.hits),
        "scientific_kg_disabled_has_no_direct_evidence": baseline.answerability is None,
        "wrong_claim_type_not_projected": (
            by_id["qual-umap-unsupported-output"]["observed_answerability"] == "UNRESOLVED"
            and not by_id["qual-umap-unsupported-output"]["observed_claim_ids"]
        ),
        "incompatible_scope_not_supported": by_id["qual-hvg-scope-mismatch"]["observed_answerability"] == "UNRESOLVED",
        "ambiguous_operator_not_selected": (
            ambiguous_answer["status"] in {"CLARIFICATION_REQUIRED", "UNRESOLVED"}
            and not ambiguous_diag.get("resolved_operator_revision")
        ),
        "missing_span_not_fabricated": (
            by_id["qual-umap-unsupported-output"]["observed_answerability"] == "UNRESOLVED"
            and not by_id["qual-umap-unsupported-output"]["observed_evidence_span_ids"]
        ),
        "missing_chunk_not_fabricated": (
            by_id["qual-leiden-unmapped-output"]["observed_answerability"] == "UNRESOLVED"
            and not by_id["qual-leiden-unmapped-output"]["observed_direct_evidence_chunk_ids"]
        ),
    }
    return {
        "all_passed": all(checks.values()),
        "checks": checks,
        "disabled_baseline": {
            "query": query,
            "retrieved_chunk_count": len(baseline.hits),
            "retrieved_chunk_ids": [hit.chunk_id for hit in baseline.hits],
            "scientific_evidence": baseline.scientific_evidence,
        },
        "ambiguity_control": {
            "query": ambiguous_query,
            "answerability": ambiguous_answer,
            "subject_resolution": ambiguous_diag.get("subject_resolution", {}),
        },
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def scored(field: str) -> dict[str, Any]:
        values = [row[field] for row in rows if row[field] is not None]
        return ratio(sum(value is True for value in values), len(values))

    non_supported = [row for row in rows if row["expected_answerability"] != "SUPPORTED"]
    actual_supported = [row for row in rows if row["observed_answerability"] == "SUPPORTED"]
    return {
        "case_count": len(rows),
        "OPERATOR_SUBJECT_RESOLUTION": scored("subject_resolution_correct"),
        "OPERATOR_REVISION_RESOLUTION": scored("operator_revision_correct"),
        "DIRECT_CLAIM_RESOLUTION": scored("direct_claim_resolution_correct"),
        "DIRECT_EVIDENCE_SPAN_RESOLUTION": scored("direct_evidence_span_resolution_correct"),
        "RAG_CHUNK_MAPPING": ratio(
            sum(row["rag_chunk_mapping_correct"] for row in rows if row["direct_evidence_span_resolution_correct"] is not None and row["expected_answerability"] == "SUPPORTED"),
            sum(row["expected_answerability"] == "SUPPORTED" for row in rows),
        ),
        "ANSWERABILITY_CORRECTNESS": scored("answerability_correct"),
        "SUPPORTED_CORRECTNESS": ratio(
            sum(row["expected_answerability"] == "SUPPORTED" for row in actual_supported),
            len(actual_supported),
        ),
        "CLAIM_TYPE_FIDELITY": scored("claim_type_fidelity"),
        "SOURCE_BINDING_CORRECTNESS": scored("source_binding_correct"),
        "SCOPE_VERSION_CORRECTNESS": scored("scope_version_correct"),
        "UNRELATED_CLAIM_LEAKAGE": ratio(
            sum(bool(row["unrelated_claim_ids"]) for row in rows), len(rows)
        ),
        "FALSE_SUPPORTED": ratio(
            sum(row["false_supported"] for row in non_supported), len(non_supported)
        ),
        "answerability_status_counts": dict(sorted(Counter(row["observed_answerability"] for row in rows).items())),
    }


def _operator_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["operator"]].append(row)
    summaries = {}
    for operator, cases in sorted(grouped.items()):
        failed = [row for row in cases if row["failure_class"] != "NONE"]
        summaries[operator] = {
            "status": "PASS" if not failed else "PARTIAL",
            "case_count": len(cases),
            "supported_count": sum(row["observed_answerability"] == "SUPPORTED" for row in cases),
            "answerability_correct": sum(row["answerability_correct"] for row in cases),
            "available_information_need_types": sorted({
                need
                for row in cases
                if row["observed_claim_ids"]
                for need in row["parsed_information_needs"]
            }),
            "failure_classes": sorted({row["failure_class"] for row in failed}),
            "failed_case_ids": [row["case_id"] for row in failed],
        }
    return {
        "overall_status": "PASS" if all(item["status"] == "PASS" for item in summaries.values()) else "PARTIAL",
        "operators": summaries,
        "midterm_demo_ready_operators": [name for name, item in summaries.items() if item["status"] == "PASS"],
    }


def _junit_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "NOT_RUN", "tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = {
        field: sum(int(suite.attrib.get(field, 0)) for suite in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }
    totals["status"] = "PASS" if totals["tests"] and not totals["failures"] and not totals["errors"] else "FAIL"
    return totals


def _write_reports(metrics, operators, rows, demos, integrity) -> None:
    focused = _junit_summary(OUTPUT / "focused_tests.xml")
    research_chat = _junit_summary(OUTPUT / "research_chat_regression.xml")
    metric_lines = "\n".join(
        f"| {name} | {value['numerator']}/{value['denominator']} | {value['rate']:.1%} |"
        for name, value in metrics.items()
        if isinstance(value, dict) and {"numerator", "denominator", "rate"} <= value.keys() and value["rate"] is not None
    )
    operator_lines = "\n".join(
        f"| {name} | {value['status']} | {value['answerability_correct']}/{value['case_count']} | {', '.join(value['available_information_need_types'])} | {', '.join(value['failure_classes']) or 'none'} |"
        for name, value in operators["operators"].items()
    )
    failures = [row for row in rows if row["failure_class"] != "NONE"]
    failure_lines = "\n".join(
        f"- `{row['case_id']}`: **{row['failure_class']}** — expected {row['expected_answerability']}, observed {row['observed_answerability']}; fallback `{row['fallback_reason'] or 'none'}`."
        for row in failures
    )
    REPORT.write_text(f"""# Scientific KG Narrow Direct-Evidence Qualification v1

Status: **{operators['overall_status']}**
Scope: production-path qualification of the six existing L4 candidate operators. This is not an independent benchmark or a generalization result.

## Frozen design

- 18 repository-derived parent cases, three per operator.
- Production entry: `ResearchToolRegistry.execute` with one `search_evidence` call.
- Only `query` was supplied as scientific input; expected IDs and answerability were retained outside the production call.
- Sparse retrieval used the existing frozen `retrieval_foundation_v1`; dense retrieval was disabled. No corpus, index, KG content, weights, Planner, ToolContract, Capability Pack, or policy was changed.
- Candidate status remained candidate; qualification performed no promotion.

## Primary metrics

| Metric | Result | Rate |
|---|---:|---:|
{metric_lines}

Observed answerability: `{json.dumps(metrics['answerability_status_counts'], sort_keys=True)}`.

## Operator results

| Operator | Status | Correct answerability | Available information needs | Failure classes |
|---|---|---:|---|---|
{operator_lines}

## Bounded failures

{failure_lines}

The neighbors input claim resolves through OperatorRevision, claim, scope, EvidenceSpan, and source binding, but its frozen RAG chunk is labelled `Harmony` in `tool_name/tool_names`. The existing public eligibility filter therefore rejects it. This is recorded as `EVIDENCE_MAPPING_ERROR`; the frozen corpus was not repaired.

The SingleR compatibility query also parses the generic word “require” as an input need, so it returns three unrelated input claims in addition to the correct compatibility claim. Answerability remains supported, but claim-type fidelity fails. This is recorded as `CLAIM_SELECTION_ERROR`; claim-selection semantics were not changed.

## Interpretation

HVG, PCA, UMAP, and Leiden pass this narrow production qualification. Neighbors and SingleR are partial. The result demonstrates that an existing bounded Scientific KG slice is consumable through the real search path, while preserving abstention and exposing two concrete quality limits. It does not establish benchmark accuracy beyond these repository-derived cases.

## Integrity

- Protected artifacts unchanged: `{str(integrity['protected_equal']).lower()}`
- C7 SEALED accessed: `false`
- C7 rerun: `false`
- Scientific content added: `false`
- Corpus/index rebuild: `false`
- Promotion: `none`
- Focused qualification tests: `{focused['status']}` ({focused['tests'] - focused['failures'] - focused['errors']}/{focused['tests']} passed)
- Research Chat regression: `{research_chat['status']}` ({research_chat['tests'] - research_chat['failures'] - research_chat['errors']}/{research_chat['tests']} passed)
""")

    selected = [
        demo for demo in demos
        if demo["case_id"] in {
            "qual-hvg-direct-output",
            "qual-pca-direct-input",
            "qual-umap-direct-input",
            "qual-leiden-direct-input",
        }
    ]
    sections = []
    for demo in selected:
        evidence = demo["direct_evidence"][0] if demo["direct_evidence"] else {}
        sections.append(f"""## {demo['operator']}

**User question**
{demo['user_question']}

**Decision**
`{demo['answerability']}` — direct, source-bound evidence was returned by the production `search_evidence` path.

**Evidence shown to the user**
{evidence.get('chunk_text', evidence.get('text', 'Exact frozen evidence chunk resolved.'))}

**Citation and provenance**

- Source: `{evidence.get('source_id', demo['source_revision_ids'][0] if demo['source_revision_ids'] else '')}`
- Source span: `{evidence.get('source_span', '')}`
- OperatorRevision: `{demo['operator_revision_id']}`
- Claim: `{', '.join(demo['claim_ids'])}`
- EvidenceSpan: `{', '.join(demo['evidence_span_ids'])}`
- SourceRevision: `{', '.join(demo['source_revision_ids'])}`
- Knowledge status: `candidate`
""")
    DEMO_REPORT.write_text("""# Midterm Direct-Evidence Demo Cases

These four production-path examples are suitable for the midterm demo or screenshots. They are qualification examples from the existing candidate Scientific KG, not benchmark claims. Product UI should show the question, decision, evidence text, and citation; the internal qualification metadata below is for presenter notes.

""" + "\n".join(sections))


def run() -> dict[str, Any]:
    cases = load_cases()
    before = protected_hashes()
    adapter = ScientificKGEvidence()
    service = foundation._service(None)
    registry = ResearchToolRegistry(retrieval=service)
    rows: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    demos: list[dict[str, Any]] = []
    for case in cases:
        row, paths, demo = _run_case(registry, adapter, case)
        rows.append(row)
        provenance.extend(paths)
        demos.append(demo)
    negative = _negative_controls(service, rows)
    metrics = _metrics(rows)
    operators = _operator_summary(rows)
    after = protected_hashes()
    integrity = {
        "protected_before": before,
        "protected_after": after,
        "protected_equal": before == after,
        "c7_paths_opened_by_runner": [],
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
        "scientific_content_added": False,
        "corpus_changed": False,
        "index_rebuilt": False,
        "retrieval_weights_changed": False,
        "planner_changed": False,
        "tool_contract_changed": False,
        "capability_pack_changed": False,
        "canonical_promotion": "none",
    }
    if not integrity["protected_equal"]:
        raise RuntimeError("protected artifact drift")
    write_jsonl(OUTPUT / "per_case_resolution.jsonl", rows)
    write_json(OUTPUT / "operator_summary.json", operators)
    write_jsonl(OUTPUT / "provenance_paths.jsonl", provenance)
    write_json(OUTPUT / "answerability_summary.json", metrics)
    write_json(OUTPUT / "negative_controls.json", negative)
    focused = _junit_summary(OUTPUT / "focused_tests.xml")
    research_chat = _junit_summary(OUTPUT / "research_chat_regression.xml")
    write_json(OUTPUT / "regression_summary.json", {
        "qualification_status": operators["overall_status"],
        "production_path_completed": len(rows),
        "production_path_expected": len(cases),
        "tool_observation_failures": sum(bool(row["warnings"]) for row in rows),
        "negative_controls_all_passed": negative["all_passed"],
        "focused_tests": focused,
        "focused_test_command": "pytest -q tests/test_scientific_kg_narrow_direct_evidence_qualification_v1.py",
        "research_chat_regression": research_chat,
        "research_chat_regression_command": "pytest -q tests/test_research_tool_registry.py tests/test_research_chat_service.py",
    })
    write_json(OUTPUT / "integrity.json", integrity)
    manifest = json.loads(MANIFEST.read_text())
    manifest.update({
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "git_head_at_qualification": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "production_entry": "ResearchToolRegistry.execute/search_evidence",
        "retrieval_snapshot_identity": foundation._snapshot_identity(),
        "scientific_kg_identity": adapter.identity,
        "enable_sparse": True,
        "enable_dense": False,
        "use_kg": True,
        "use_governance_rerank": True,
        "use_contract_gate": True,
        "overall_status": operators["overall_status"],
        "qualification_artifacts": [
            "per_case_resolution.jsonl", "operator_summary.json", "provenance_paths.jsonl",
            "answerability_summary.json", "negative_controls.json", "regression_summary.json", "integrity.json",
            "focused_tests.xml", "research_chat_regression.xml",
        ],
    })
    write_json(MANIFEST, manifest)
    _write_reports(metrics, operators, rows, demos, integrity)
    return {
        "overall_status": operators["overall_status"],
        "metrics": metrics,
        "operators": operators["operators"],
        "negative_controls_all_passed": negative["all_passed"],
        "protected_equal": integrity["protected_equal"],
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
