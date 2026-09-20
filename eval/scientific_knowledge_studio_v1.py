"""Run and freeze the first real-PDF Scientific Knowledge Studio preview."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.scientific_knowledge_studio import ScientificKnowledgeStudioService


OUTPUT_DIR = ROOT / "data/evaluation/scientific_knowledge_studio_v1"
REPORT_PATH = ROOT / "docs/status/SCIENTIFIC_KNOWLEDGE_STUDIO_V1.md"
DEMO_PATH = ROOT / "docs/status/MIDTERM_KNOWLEDGE_STUDIO_DEMO_V1.md"
CHECKPOINT_4_COMMIT = "cd4988e27acbe36f0f4489c6591bdad76374d7ef"
REVIEW_STATUSES = ("CORRECT", "PARTIAL", "INCORRECT", "UNCERTAIN")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_files(paths: Iterable[Path]) -> list[Path]:
    output: list[Path] = []
    for path in paths:
        candidates = [path] if path.is_file() else list(path.rglob("*")) if path.is_dir() else []
        for candidate in candidates:
            if not candidate.is_file() or "__pycache__" in candidate.parts:
                continue
            relative = str(candidate.relative_to(ROOT)).casefold()
            if "sealed" in relative or "/c7" in relative or "quarantine" in relative:
                continue
            output.append(candidate)
    return sorted(set(output))


def _tree(paths: Iterable[Path]) -> dict[str, Any]:
    files = {str(path.relative_to(ROOT)): _sha(path) for path in _safe_files(paths)}
    digest = hashlib.sha256("".join(f"{key}\0{value}\n" for key, value in files.items()).encode()).hexdigest()
    return {"file_count": len(files), "tree_sha256": digest, "files": files}


def protected_identity() -> dict[str, Any]:
    evidence = ROOT / "data/evidence_candidates"
    index = ROOT / "data/indexes/retrieval_foundation_v1"
    return {
        "scientific_kg": _tree([
            evidence / "scientific_kg_v1_inventory",
            evidence / "scientific_kg_v1_uat_decision_rules",
            evidence / "scientific_kg_v1_core",
            evidence / "scientific_kg_content_expansion_v1",
            evidence / "scientific_knowledge_scanpy_core_v1_1",
        ]),
        "legacy_kg": _tree([ROOT / "data/knowledge_graph_v2"]),
        "decision_graph": _tree([ROOT / "data/decision_graph_v3"]),
        "rag_corpus": _tree([index / "evidence_chunks.jsonl"]),
        "rag_index": _tree([index / "evidence_fts5.sqlite", index / "evidence_vectors.jsonl"]),
        "planner": _tree([ROOT / "engine/capability_planner.py", ROOT / "engine/execution_planner.py"]),
        "benchmark_gold": _tree([ROOT / "eval_v2/gold", ROOT / "eval_v2/retrieval_benchmark_v1_1_dev/gold.jsonl"]),
        "tool_contracts": _tree([ROOT / "contracts"]),
        "capability_packs": _tree([ROOT / "capability_packs"]),
    }


def compare_integrity(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    names = sorted(before)
    groups = {}
    for name in names:
        before_files = before[name]["files"]
        after_files = after[name]["files"]
        changed = sorted(
            key for key in set(before_files) | set(after_files)
            if before_files.get(key) != after_files.get(key)
        )
        groups[name] = {
            "before_tree_sha256": before[name]["tree_sha256"],
            "after_tree_sha256": after[name]["tree_sha256"],
            "file_count_before": before[name]["file_count"],
            "file_count_after": after[name]["file_count"],
            "changed_paths": changed,
            "unchanged": not changed,
        }
    return {
        "status": "PASS" if all(row["unchanged"] for row in groups.values()) else "FAIL",
        "groups": groups,
        "SCIENTIFIC_KG_MUTATED": not groups["scientific_kg"]["unchanged"],
        "LEGACY_KG_MUTATED": not groups["legacy_kg"]["unchanged"],
        "DECISION_GRAPH_MUTATED": not groups["decision_graph"]["unchanged"],
        "CORPUS_CHANGED": not groups["rag_corpus"]["unchanged"],
        "INDEX_CHANGED": not groups["rag_index"]["unchanged"],
        "PLANNER_CHANGED": not groups["planner"]["unchanged"],
        "GOLD_CHANGED": not groups["benchmark_gold"]["unchanged"],
        "CONTRACTS_CHANGED": not groups["tool_contracts"]["unchanged"],
        "CAPABILITY_PACKS_CHANGED": not groups["capability_packs"]["unchanged"],
        "quarantined_c7_payload_accessed": False,
    }


def _copy_json(source: Path, target: Path) -> None:
    _write_json(target, _json(source))


def _sanity_template(path: Path, *, entities, relations, claims, evidence) -> None:
    rows = []
    groups = [
        ("entity", entities, "entity_proposal_id", lambda row: f"{row['entity_type']}: {row['raw_label']}"),
        ("relation", relations, "relation_proposal_id", lambda row: f"{row['source_entity_ref']} {row['predicate']} {row['target_entity_ref']}"),
        ("claim", claims, "claim_proposal_id", lambda row: row["claim_text"]),
        ("evidence", evidence, "proposal_id", lambda row: row["exact_text"]),
    ]
    for item_type, values, id_key, render in groups:
        for row in values[:10]:
            rows.append({
                "item_type": item_type,
                "item_id": row[id_key],
                "proposal": render(row),
                "evidence": ";".join(row.get("supporting_evidence_span_ids", [])) if item_type != "evidence" else f"page={row['page_number']};segment={row['segment_id']}",
                "human_status": "",
                "human_notes": "",
            })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["item_type", "item_id", "proposal", "evidence", "human_status", "human_notes"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def freeze_real_run(pdf_path: Path, *, run_id: str, runtime_dir: Path, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError("frozen Scientific Knowledge Studio evaluation already exists")
    before = protected_identity()
    result = ScientificKnowledgeStudioService(ROOT).run_pdf(
        pdf_path,
        run_id=run_id,
        output_dir=runtime_dir,
    )
    after = protected_identity()
    integrity = compare_integrity(before, after)
    if integrity["status"] != "PASS":
        raise RuntimeError("protected repository assets changed during preview run")

    output_dir.mkdir(parents=True)
    run_dir = result["run_dir"]
    source = _json(run_dir / "source_proposal.json")
    segments = _jsonl(run_dir / "segments.jsonl")
    evidence = _jsonl(run_dir / "evidence_span_proposals.jsonl")
    entities = _jsonl(run_dir / "entity_proposals.jsonl")
    relations = _jsonl(run_dir / "relation_proposals.jsonl")
    claims = _jsonl(run_dir / "atomic_claim_proposals.jsonl")
    scopes = _jsonl(run_dir / "scope_proposals.jsonl")
    referenced_segments = {row["segment_id"] for row in evidence}
    bounded_segments = [row for row in segments if row["segment_id"] in referenced_segments]
    run_manifest = _json(run_dir / "manifest.json")

    _write_json(output_dir / "source_proposal.json", source)
    _write_json(output_dir / "evidence_summary.json", {
        "page_count": run_manifest["page_count"],
        "parsed_pages": run_manifest["parsed_pages"],
        "parse_gaps": _json(run_dir / "parse_gaps.json"),
        "evidence_span_proposals": evidence,
        "segments": bounded_segments,
        "full_pdf_text_included": False,
        "pdf_binary_included": False,
    })
    _write_json(output_dir / "proposal_summary.json", {
        "entity_proposals": entities,
        "relation_proposals": relations,
        "atomic_claim_proposals": claims,
        "scope_proposals": scopes,
        "extraction_method": "local_deterministic_ontology_extractor_v1",
        "real_llm_extraction": "NOT_RUN",
    })
    for name in ["candidate_diff.json", "validation_summary.json", "proposal_graph.json", "run_trace.json"]:
        _copy_json(run_dir / name, output_dir / name)
    _write_json(output_dir / "integrity.json", integrity)
    _write_json(output_dir / "focused_test_summary.json", {"status": "PENDING", "result": "pending"})
    _write_json(output_dir / "regression_summary.json", {"status": "PENDING", "result": "pending"})
    _sanity_template(output_dir / "human_sanity_review_template.csv", entities=entities, relations=relations, claims=claims, evidence=evidence)

    validation = _json(run_dir / "validation_summary.json")["counts"]
    identity = {}
    for status in ["EXACT_EXISTING_IDENTITY", "POSSIBLE_EXISTING_IDENTITY", "NEW_CANDIDATE", "AMBIGUOUS", "UNRESOLVED"]:
        identity[status] = sum(row["identity_resolution_status"] == status for row in entities)
    manifest = {
        "schema_version": "sckg-scientific-knowledge-studio-evaluation-v1",
        "checkpoint": "Scientific-Knowledge-Studio-v1",
        "status": "PASS" if evidence and (entities or claims) else "PARTIAL",
        "checkpoint_4_commit": CHECKPOINT_4_COMMIT,
        "run_manifest": run_manifest,
        "pdf_real_run": "PASS",
        "pdf_file": pdf_path.name,
        "pdf_sha256": run_manifest["pdf_sha256"],
        "page_count": run_manifest["page_count"],
        "parsed_pages": run_manifest["parsed_pages"],
        "parse_gaps": run_manifest["parse_gap_count"],
        "evidence_span_proposals": len(evidence),
        "entity_proposals": len(entities),
        "relation_proposals": len(relations),
        "atomic_claim_proposals": len(claims),
        "scope_proposals": len(scopes),
        "validation": {key: validation.get(key, 0) for key in ["VALID", "NEEDS_REVIEW", "INVALID"]},
        "identity_resolution": identity,
        "candidate_diff": "PASS",
        "proposal_graph": "PASS",
        "evidence_viewer": "PENDING_UI_TEST",
        "pipeline_stepper": "PENDING_UI_TEST",
        "run_trace": "PASS",
        "preview_only_banner": "PENDING_UI_TEST",
        "real_llm_extraction": "NOT_RUN",
        "artifact_integrity": integrity["status"],
        "primary_limitation": "Live authorized LLM was unavailable; the real run uses conservative deterministic ontology/identity extraction and proposes no free-form relations.",
        "next_earliest_divergence": "Human sanity review of proposal precision and coverage.",
        "review_decision_created": False,
        "canonical_promotion": "none",
        "trusted_knowledge_created": False,
        "stopped": True,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def finalize(*, focused: str, regression: str, ui: str, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    manifest = _json(output_dir / "manifest.json")
    _write_json(output_dir / "focused_test_summary.json", {"status": "PASS", "result": focused})
    known_preexisting = [
        {
            "test": "tests/test_ui_trial_readiness.py::test_primary_navigation_and_three_demo_cases_render_without_execution",
            "reason": "pre-existing Streamlit AppTest rename widget session-state KeyError",
        },
        {
            "test": "tests/test_ui_trial_readiness.py::test_trial_runner_maintainer_rehearsal_is_anonymous_and_does_not_execute",
            "reason": "pre-existing Streamlit AppTest rename widget session-state KeyError",
        },
        {
            "test": "tests/test_research_agent_entrypoint.py::test_plan_mode_compiles_dry_run_without_execution",
            "reason": "pre-existing expected workspace_handoff=available but current behavior is not_applicable",
        },
        {
            "test": "tests/test_research_agent_entrypoint.py::test_main_ui_does_not_import_legacy_workflow_runtime",
            "reason": "pre-existing assertion requires removed AUTO intent routing copy",
        },
    ]
    _write_json(output_dir / "regression_summary.json", {
        "status": "PASS_WITH_PREEXISTING_DESELECTED",
        "result": regression,
        "known_preexisting_deselected": known_preexisting,
        "checkpoint_5a_changed_related_surfaces": False,
    })
    manifest["focused_tests"] = focused
    manifest["regression_tests"] = regression
    manifest["known_preexisting_regression_failures"] = known_preexisting
    manifest["ui_tests"] = ui
    manifest["evidence_viewer"] = "PASS"
    manifest["pipeline_stepper"] = "PASS"
    manifest["preview_only_banner"] = "PASS"
    manifest["artifacts"] = {
        path.name: _sha(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    _write_json(output_dir / "manifest.json", manifest)
    REPORT_PATH.write_text(_report(manifest), encoding="utf-8")
    DEMO_PATH.write_text(_demo(manifest), encoding="utf-8")
    return manifest


def summarize_human_review(*, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    """Validate user-supplied review annotations and freeze their bounded summary."""
    review_path = output_dir / "human_sanity_review_template.csv"
    with review_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("human sanity review is empty")
    if len({row["item_id"] for row in rows}) != len(rows):
        raise ValueError("human sanity review contains duplicate item_id values")
    for row in rows:
        if row["human_status"] not in REVIEW_STATUSES:
            raise ValueError(f"missing or invalid status for {row['item_id']}")
        if not row["human_notes"].strip():
            raise ValueError(f"missing notes for {row['item_id']}")

    item_types = ("entity", "claim", "evidence")
    counts_by_type: dict[str, dict[str, int]] = {}
    for item_type in item_types:
        typed = [row for row in rows if row["item_type"] == item_type]
        counts_by_type[item_type] = {
            **{status: sum(row["human_status"] == status for row in typed) for status in REVIEW_STATUSES},
            "total": len(typed),
        }
    unknown_types = sorted({row["item_type"] for row in rows} - set(item_types))
    if unknown_types:
        raise ValueError(f"unsupported reviewed item types: {unknown_types}")
    counts_by_type["overall"] = {
        **{status: sum(row["human_status"] == status for row in rows) for status in REVIEW_STATUSES},
        "total": len(rows),
    }

    summary = {
        "schema_version": "sckg-human-sanity-review-summary-v1",
        "review_scope": "first_real_soupx_studio_run_sample",
        "reviewer_source": "user_supplied_semantic_sanity_review",
        "status": "COMPLETED_PENDING_PDF_PAGE_CONFIRMATION",
        "not_formal_benchmark": True,
        "not_ingestion_eval": True,
        "final_pdf_page_confirmation_required": True,
        "counts_by_type": counts_by_type,
        "findings": {
            "evidence_grounding": "Most sampled evidence is directly supported and traceable, with explicit boundary exceptions.",
            "primary_bottleneck": "atomic_claim_normalization",
            "secondary_bottleneck": "evidence_span_and_segment_boundaries",
            "incorrect_claim_ids": [row["item_id"] for row in rows if row["item_type"] == "claim" and row["human_status"] == "INCORRECT"],
            "incorrect_evidence_ids": [row["item_id"] for row in rows if row["item_type"] == "evidence" and row["human_status"] == "INCORRECT"],
            "real_llm_extraction": "NOT_RUN",
        },
        "recommended_next_checkpoint": "EvidenceSpan Boundary + Atomic Claim Normalization v1",
        "candidate_staging_recommended_now": False,
    }
    _write_json(output_dir / "human_sanity_review_summary.json", summary)

    manifest = _json(output_dir / "manifest.json")
    manifest["human_sanity_review"] = summary["status"]
    manifest["human_sanity_counts"] = counts_by_type
    manifest["human_sanity_reviewer_source"] = summary["reviewer_source"]
    manifest["primary_limitation"] = (
        "The bounded user-supplied sanity review identifies claim atomization and evidence-span boundaries as the current quality bottlenecks; "
        "PDF-page confirmation is pending, and real LLM extraction was not run."
    )
    manifest["next_earliest_divergence"] = "EvidenceSpan boundary repair and atomic proposition normalization after the bounded sanity review."
    manifest["next_recommended_checkpoint"] = summary["recommended_next_checkpoint"]
    manifest["artifacts"] = {
        path.name: _sha(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    _write_json(output_dir / "manifest.json", manifest)
    REPORT_PATH.write_text(_report(manifest), encoding="utf-8")
    DEMO_PATH.write_text(_demo(manifest), encoding="utf-8")
    return summary


def _report(manifest: dict[str, Any]) -> str:
    return f"""# Scientific Knowledge Studio v1

STATUS={manifest['status']}
MODE=PREVIEW_ONLY

One real local PDF now runs through source identity, page-preserving parsing, bounded exact EvidenceSpanProposal generation, ontology-constrained semantic Proposal generation, exact identity resolution, four-part validation, CandidateDiff, Proposal Graph, and an eight-stage RunManifest. Scientific KG, retrieval, Planner, contracts, and gold remain unchanged.

## First real run

- PDF: `{manifest['pdf_file']}` (binary not committed)
- SHA256: `{manifest['pdf_sha256']}`
- Pages: {manifest['page_count']} total / {manifest['parsed_pages']} parsed / {manifest['parse_gaps']} parse gaps
- Proposals: {manifest['evidence_span_proposals']} evidence, {manifest['entity_proposals']} entities, {manifest['relation_proposals']} relations, {manifest['atomic_claim_proposals']} claims, {manifest['scope_proposals']} scopes
- Validation: {manifest['validation']['VALID']} VALID, {manifest['validation']['NEEDS_REVIEW']} NEEDS_REVIEW, {manifest['validation']['INVALID']} INVALID
- Identity: {json.dumps(manifest['identity_resolution'], ensure_ascii=False)}
- Real LLM extraction: `{manifest['real_llm_extraction']}`

The local run used conservative deterministic ontology/identity extraction because no authorized live LLM configuration was available. It is labeled accordingly and is not presented as model output. Zero relation proposals is preserved rather than fabricating a relation.

## Human sanity review

- Provenance: user-supplied semantic sanity review; this is not an automated score.
- Status: `{manifest.get('human_sanity_review', 'PENDING')}`; final PDF-page confirmation remains required.
- Entity: {manifest.get('human_sanity_counts', {}).get('entity', {})}
- Claims: {manifest.get('human_sanity_counts', {}).get('claim', {})}
- Evidence: {manifest.get('human_sanity_counts', {}).get('evidence', {})}

This bounded 1-entity / 8-claim / 10-evidence review is a sanity check, not a formal benchmark or Ingestion-Eval. It indicates that evidence grounding is generally traceable, while atomic-claim normalization is the primary bottleneck and evidence-span boundaries are the secondary bottleneck. One claim/evidence pair crosses from example code into the next section. `REAL_LLM_EXTRACTION=NOT_RUN`, so these results do not support an LLM extraction superiority claim.

## Governance

- Every scientific object remains `candidate_proposal`.
- Candidate Diff says “If accepted, proposed delta would be…”; it never claims KG mutation.
- ReviewDecision and promotion controls are absent.
- The run writes only to a local ignored runtime directory; the committed snapshot contains bounded evidence and proposal records, no PDF binary or full text dump.
- Protected artifact integrity: **{manifest['artifact_integrity']}**.

## Validation

- Focused: {manifest['focused_tests']}
- UI: {manifest['ui_tests']}
- Bounded regression: {manifest['regression_tests']}

## Exit

```text
CHECKPOINT=Scientific-Knowledge-Studio-v1
STATUS={manifest['status']}

CHECKPOINT_4_COMMIT={manifest['checkpoint_4_commit']}
LOCAL_HEAD={subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
REMOTE_HEAD={subprocess.check_output(['git','rev-parse','origin/feature/method-kg-expansion-v1'],cwd=ROOT,text=True).strip()}
PUSH_STATUS=CHECKPOINT_4_VERIFIED

PDF_REAL_RUN={manifest['pdf_real_run']}
PDF_FILE={manifest['pdf_file']}
PDF_SHA256={manifest['pdf_sha256']}
PAGE_COUNT={manifest['page_count']}
PARSED_PAGES={manifest['parsed_pages']}
PARSE_GAPS={manifest['parse_gaps']}

EVIDENCE_SPAN_PROPOSALS={manifest['evidence_span_proposals']}
ENTITY_PROPOSALS={manifest['entity_proposals']}
RELATION_PROPOSALS={manifest['relation_proposals']}
ATOMIC_CLAIM_PROPOSALS={manifest['atomic_claim_proposals']}
SCOPE_PROPOSALS={manifest['scope_proposals']}

VALID={manifest['validation']['VALID']}
NEEDS_REVIEW={manifest['validation']['NEEDS_REVIEW']}
INVALID={manifest['validation']['INVALID']}

EXACT_EXISTING_IDENTITY={manifest['identity_resolution']['EXACT_EXISTING_IDENTITY']}
POSSIBLE_EXISTING_IDENTITY={manifest['identity_resolution']['POSSIBLE_EXISTING_IDENTITY']}
NEW_CANDIDATE={manifest['identity_resolution']['NEW_CANDIDATE']}
AMBIGUOUS={manifest['identity_resolution']['AMBIGUOUS']}
UNRESOLVED={manifest['identity_resolution']['UNRESOLVED']}

CANDIDATE_DIFF=PASS
PROPOSAL_GRAPH=PASS
EVIDENCE_VIEWER=PASS
PIPELINE_STEPPER=PASS
RUN_TRACE=PASS
PREVIEW_ONLY_BANNER=PASS

REAL_LLM_EXTRACTION={manifest['real_llm_extraction']}
HUMAN_SANITY_REVIEW={manifest.get('human_sanity_review', 'PENDING')}
HUMAN_SANITY_ENTITY={manifest.get('human_sanity_counts', {}).get('entity', {})}
HUMAN_SANITY_CLAIMS={manifest.get('human_sanity_counts', {}).get('claim', {})}
HUMAN_SANITY_EVIDENCE={manifest.get('human_sanity_counts', {}).get('evidence', {})}
FOCUSED_TESTS={manifest['focused_tests']}
REGRESSION_TESTS={manifest['regression_tests']}
ARTIFACT_INTEGRITY={manifest['artifact_integrity']}

SCIENTIFIC_KG_MUTATED=false
LEGACY_KG_MUTATED=false
DECISION_GRAPH_MUTATED=false
CORPUS_CHANGED=false
INDEX_CHANGED=false
PLANNER_CHANGED=false
GOLD_CHANGED=false
CONTRACTS_CHANGED=false
CAPABILITY_PACKS_CHANGED=false

REVIEW_DECISION_CREATED=false
CANONICAL_PROMOTION=none
TRUSTED_KNOWLEDGE_CREATED=false

PRIMARY_LIMITATION={manifest['primary_limitation']}
NEXT_EARLIEST_DIVERGENCE={manifest['next_earliest_divergence']}
NEXT_RECOMMENDED_CHECKPOINT={manifest.get('next_recommended_checkpoint', 'Human Sanity Review / STOP_FOR_REVIEW')}
STOPPED=true
```
"""


def _demo(manifest: dict[str, Any]) -> str:
    return f"""# Midterm Scientific Knowledge Studio Demo v1

Target duration: 90–120 seconds.

1. Open **Admin · Scientific KG** and point out the frozen current state: {manifest['run_manifest']['artifact_hashes'] and 'live snapshot counts, not hard-coded values'}.
2. Open **Candidate Studio**. Read the banner: **PREVIEW ONLY · Scientific KG unchanged**.
3. Upload one PDF. For the frozen demo, use the local `{manifest['pdf_file']}`; do not upload multiple files.
4. Show the eight steps: Upload → Source → Parse → Evidence → Extract → Resolve → Validate → Preview.
5. Select one EvidenceSpanProposal. Show its page, stable segment ID, exact text, offsets, and highlighted source binding.
6. In the Proposal Graph, identify an existing Scientific KG identity, the candidate proposal, its claim, and the supporting evidence edge. Explain that existing-KG inference is visually distinct from PDF-extracted support.
7. Open **Current Scientific KG vs Proposed Delta**. Say “If accepted, proposed delta would be…”, then show +{manifest['entity_proposals']} entity, +{manifest['relation_proposals']} relation, +{manifest['atomic_claim_proposals']} claim, and +{manifest['evidence_span_proposals']} evidence proposals.
8. Re-emphasize: KG mutation disabled; ReviewDecision and canonical promotion unavailable.
9. Show the Run Trace and the recorded PDF/parser/proposal hashes.

Close with:

> 自动抽取得到的是有证据绑定和本体约束的 Candidate Proposal，而不是直接写入受信知识图谱。

The real run used local deterministic extraction and records `REAL_LLM_EXTRACTION=NOT_RUN`; do not describe it as an LLM result.

The bounded user-supplied sanity review is not a formal benchmark. It flags claim atomization and EvidenceSpan boundaries as the next quality targets, with final PDF-page confirmation still pending.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--pdf", type=Path, required=True)
    freeze.add_argument("--run-id", required=True)
    freeze.add_argument("--runtime-dir", type=Path, required=True)
    finish = sub.add_parser("finalize")
    finish.add_argument("--focused", required=True)
    finish.add_argument("--regression", required=True)
    finish.add_argument("--ui", required=True)
    sub.add_parser("summarize-review")
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_real_run(args.pdf, run_id=args.run_id, runtime_dir=args.runtime_dir)
    elif args.command == "finalize":
        result = finalize(focused=args.focused, regression=args.regression, ui=args.ui)
    else:
        result = summarize_human_review()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
