"""Synthetic contract/regression tests, NOT scientific scorer calibration."""

from __future__ import annotations

from collections import Counter
import json
import subprocess
import sys

import jsonschema
import pytest

from core.evaluation_models import EvaluationCase, EvaluationRunRecord, EvaluatorResult
from eval.benchmark_v3 import run_lane_alignment_audit as lanes
from eval.benchmark_v3.build_development_review import BASE, fixtures, prompt_inventory
from eval.benchmark_v3.coverage_review import (
    SOURCES,
    aggregate,
    audit_scenario,
    digest,
    make_cell,
    resolve_cell,
)


@pytest.fixture(scope="module")
def frozen():
    source = lanes.load_and_verify_sources()
    manifest = lanes.lane_manifest(source)
    snapshots = lanes.coverage_snapshot(manifest)["sources"]
    inventories, cautions, graphs = lanes.source_records(source)
    return (
        source,
        manifest,
        snapshots,
        {s: {r["id"]: r for r in inventories[s]} for s in SOURCES},
        cautions,
        graphs,
    )


def example():
    fact = {"fact_id": "f", "requirement": "synthetic fact", "critical": True}
    snapshot = {"snapshot_id": "fixture", "digest": "a" * 64}
    registry = {
        "s1": {
            "id": "s1",
            "kind": "approved_statement",
            "consumer_eligible": True,
            "evidence": {"span1": "The synthetic input must be blue."},
        }
    }
    cell = make_cell("case1", fact, SOURCES[0], snapshot, {"sample_match_ids": ["s1"]})
    return fact, snapshot, registry, cell


def decision(identity, status="present", registry=None):
    value = {
        "reviewer_id": identity,
        "reviewed_at": "2026-09-21",
        "status": status,
        "rationale": "synthetic test review; not human scientific adjudication",
    }
    if status == "present":
        value["supports"] = [
            {
                "record_id": "s1",
                "evidence_id": "span1",
                "excerpt": "input must be blue",
                "scope_and_version": "synthetic fixture v1",
                "applicability_reason": "fixture condition blue",
                "entailment_reason": "explicit fixture statement",
            }
        ]
    if status == "absent":
        value["negative_search"] = {
            "search_scope": "all synthetic fixture records, fields and aliases",
            "query_variants": ["fixture blue", "synthetic input"],
            "record_inventory_digest": digest(registry),
            "related_results": [],
            "insufficiency_reason": "test-only negative justification",
        }
    return value


@pytest.mark.parametrize(
    "signature", ["111", "110", "101", "011", "100", "010", "001", "000"]
)
def test_all_eight_signatures_from_reviewed_cells(signature):
    fact = {"fact_id": "f", "critical": True}
    statuses = {
        ("f", source): "present" if bit == "1" else "absent"
        for source, bit in zip(SOURCES, signature)
    }
    result = aggregate([fact], statuses, requirements_reviewed=True)
    assert result["exact_signature"] == signature
    assert result["coarse_label"] == (
        "shared"
        if signature.count("1") >= 2
        else {
            "100": "v2-only",
            "010": "legacy-only",
            "001": "rag-only",
            "000": "out-of-knowledge",
        }[signature]
    )


def test_unknown_not_applicable_and_missing_context_not_absence():
    f = {"fact_id": "f", "critical": True}
    known = {("f", s): "present" for s in SOURCES}
    assert aggregate([f], known, requirements_reviewed=False)["exact_signature"] is None
    assert aggregate([f], {}, requirements_reviewed=True)["exact_signature"] is None
    runtime = aggregate(
        [], {}, requirements_reviewed=True, scientific_applicability="not_applicable"
    )
    assert (
        runtime["audit_status"] == "not_applicable"
        and runtime["exact_signature"] is None
    )
    with pytest.raises(ValueError):
        aggregate([], {}, requirements_reviewed=True)
    with pytest.raises(ValueError):
        aggregate(
            [f],
            {},
            requirements_reviewed=True,
            scientific_applicability="not_applicable",
        )
    # User data/state is deliberately not an argument in science aggregation.
    assert aggregate([f], known, requirements_reviewed=True)["exact_signature"] == "111"


def test_missing_critical_fact_and_mixed_partial_evidence():
    facts = [{"fact_id": "a", "critical": True}, {"fact_id": "b", "critical": True}]
    statuses = {("a", s): "present" for s in SOURCES}
    assert (
        aggregate(facts, statuses, requirements_reviewed=True)["exact_signature"]
        is None
    )
    statuses.update({("b", s): "absent" for s in SOURCES})
    assert (
        aggregate(facts, statuses, requirements_reviewed=True)["exact_signature"]
        == "000"
    )


def test_search_and_stored_status_never_adjudicate():
    fact, snapshot, registry, cell = example()
    cell["status"] = "present"
    assert resolve_cell(cell, fact, snapshot, registry) == "unknown"
    cell["reviews"] = [decision("reviewer-a")]
    assert resolve_cell(cell, fact, snapshot, registry) == "unknown"
    cell["reviews"].append(decision("reviewer-b"))
    assert resolve_cell(cell, fact, snapshot, registry) == "present"


def test_two_reviewers_and_independent_00_disagreement_resolution():
    fact, snapshot, registry, cell = example()
    cell["reviews"] = [decision("r1"), decision("r1")]
    with pytest.raises(ValueError):
        resolve_cell(cell, fact, snapshot, registry)
    cell["reviews"] = [decision("r1"), decision("r2", "absent", registry)]
    assert resolve_cell(cell, fact, snapshot, registry) == "unknown"
    cell["resolution"] = dict(decision("r3"), role="08-engineer")
    with pytest.raises(ValueError):
        resolve_cell(cell, fact, snapshot, registry)
    cell["resolution"]["role"] = "00-adjudicator"
    assert resolve_cell(cell, fact, snapshot, registry) == "present"


@pytest.mark.parametrize(
    "kind,eligible",
    [
        ("held_statement", True),
        ("caution", True),
        ("ToolContract", True),
        ("Planner", True),
        ("execution_guard", True),
        ("validation_contract", True),
        ("approval", True),
        ("approved_statement", False),
        ("catalog_metadata", True),
    ],
)
def test_forbidden_records_cannot_establish_v2_coverage(kind, eligible):
    fact, snapshot, registry, cell = example()
    registry["s1"].update(kind=kind, consumer_eligible=eligible)
    cell["reviews"] = [decision("r1"), decision("r2")]
    with pytest.raises(ValueError, match="permitted"):
        resolve_cell(cell, fact, snapshot, registry)


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_id", "missing"),
        ("evidence_id", "unbound"),
        ("excerpt", "invented scientific text"),
        ("scope_and_version", ""),
        ("applicability_reason", ""),
    ],
)
def test_support_ids_excerpts_and_conditions_are_required(field, value):
    fact, snapshot, registry, cell = example()
    cell["reviews"] = [decision("r1"), decision("r2")]
    cell["reviews"][0]["supports"][0][field] = value
    with pytest.raises(ValueError):
        resolve_cell(cell, fact, snapshot, registry)


@pytest.mark.parametrize(
    "missing",
    [
        "search_scope",
        "query_variants",
        "record_inventory_digest",
        "related_results",
        "insufficiency_reason",
    ],
)
def test_absence_needs_reviewed_negative_evidence(missing):
    fact, snapshot, registry, cell = example()
    cell["reviews"] = [
        decision("r1", "absent", registry),
        decision("r2", "absent", registry),
    ]
    assert resolve_cell(cell, fact, snapshot, registry) == "absent"
    del cell["reviews"][0]["negative_search"][missing]
    with pytest.raises(ValueError):
        resolve_cell(cell, fact, snapshot, registry)


def test_stale_fact_source_and_scenario_reviews_rejected():
    fact, snapshot, registry, cell = example()
    with pytest.raises(ValueError, match="stale fact"):
        resolve_cell(cell, dict(fact, requirement="new"), snapshot, registry)
    with pytest.raises(ValueError, match="stale snapshot"):
        resolve_cell(cell, fact, dict(snapshot, digest="b" * 64), registry)
    scenario = {
        "scenario_id": "case1",
        "input": {"query": "new"},
        "required_scientific_facts": [fact],
        "requirements_review_status": "needs_adjudication",
        "scientific_applicability": "applicable",
    }
    cell["scenario_input_digest"] = digest({"query": "old"})
    with pytest.raises(ValueError, match="stale scenario"):
        audit_scenario(scenario, [cell], {SOURCES[0]: snapshot}, {SOURCES[0]: registry})


def test_frozen_consumer_boundaries_and_dynamic_requests(frozen):
    source, manifest, snapshots, records, cautions, _ = frozen
    assert source["promotion"]["approved_kg_sha256"] == lanes.APPROVED_KG_SHA256
    assert len(records[SOURCES[0]]) == 121 and len(cautions) == 166
    assert lanes.HELD_STATEMENT_ID not in records[SOURCES[0]]
    assert all(r["evidence"] for r in records[SOURCES[0]].values())
    assert len(records[SOURCES[2]]) == 2647
    assert sum(not r["consumer_eligible"] for r in records[SOURCES[2]].values()) == 10
    assert (
        sum(r["kind"] == "catalog_metadata" for r in records[SOURCES[2]].values())
        == 1847
    )
    claims = [
        r for r in records[SOURCES[1]].values() if r["kind"] == "legacy_candidate_claim"
    ]
    assert len(claims) == 25 and all(r["evidence"] for r in claims)
    rag = next(l for l in manifest["lanes"] if l["lane_name"] == "generic_rag")
    assert "search_catalog" in rag["retrieval_budget"]["include_catalog"]
    assert (
        rag["retrieval_budget"]["sparse_candidate_limit"]
        == "max(request.top_k * 12, 120)"
    )
    assert "catalog_chunks_sha256" in rag["corpus_digests"]
    assert snapshots[SOURCES[0]]["digest"] == lanes.APPROVED_KG_SHA256
    assert len(prompt_inventory()) >= 2


def test_fourteen_drafts_schema_origin_and_single_condition_pairs():
    rows = lanes.read_jsonl(BASE / "development_scenarios.jsonl")
    schema = json.loads((BASE / "development_scenario.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    for row in rows:
        jsonschema.validate(row, schema)
        assert not row["human_review"]["reference_claims"]
    assert Counter(r["track"] for r in rows) == {"K": 8, "O": 4, "W": 2}
    assert len({r["family_id"] for r in rows}) == 10
    for family in {r["family_id"] for r in rows if r["track"] == "K"}:
        a, b = [r for r in rows if r["family_id"] == family]
        assert a["draft_query"] == b["draft_query"]
        changed = [
            key
            for key in a["scientific_conditions"]
            if a["scientific_conditions"][key] != b["scientific_conditions"][key]
        ]
        assert changed == [a["contrast"]["changed_field"]]
    for row in rows:
        if row["question_origin"] == "real-user":
            assert row["raw_title_or_question"] in row["draft_query"]
            assert row["added_scientific_context"] == []
        if row["track"] == "W":
            assert row["execution_status"] == "not_run"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(rows[0], gold_status="adjudicated"), schema)


def test_generated_review_cells_are_unknown_and_templates_complete(frozen):
    _, _, snapshots, records, _, _ = frozen
    rows = lanes.read_jsonl(BASE / "development_scenarios.jsonl")
    cells = lanes.read_jsonl(BASE / "development_coverage_review_template.jsonl")
    assert len(cells) == 45
    for row in rows:
        own = [c for c in cells if c["scenario_id"] == row["scenario_id"]]
        assert len(own) == len(row["required_scientific_facts"]) * 3
        assert all(c["reviews"] == [] for c in own)
        assert audit_scenario(row, own, snapshots, records)["exact_signature"] is None


def test_raw_seed_schema_and_source_bytes_unchanged():
    schema = json.loads((BASE / "raw_seed_schema.json").read_text())
    for name in (
        "raw_seeds_pilot.jsonl",
        "paper_notebook_seeds_pilot.jsonl",
        "semantic_cluster_assignments.json",
        "semantic_cluster_report.md",
    ):
        path = BASE / name
        assert path.read_bytes() == lanes.git_blob(
            lanes.HISTORICAL_AUDIT_COMMIT, f"eval/benchmark_v3/{name}"
        )
        if name.endswith("jsonl"):
            for row in lanes.read_jsonl(path):
                jsonschema.validate(row, schema)


def test_old_hardcoded_conclusions_withdrawn():
    audits = lanes.read_jsonl(BASE / "coverage_audit.jsonl")
    assert len(audits) == 20
    for row in audits:
        assert row["exact_signature"] is None and row["withdraws"]["signature"] == "000"
        assert all(v["status"] == "unknown" for v in row["source_results"].values())
        assert all(
            v["negative_search_procedure"] is None
            for v in row["source_results"].values()
        )
    for name in ("candidate_scenarios_pilot.jsonl", "candidate_pool_phase_2_2.jsonl"):
        assert all(
            r["exact_coverage_signature"] is None for r in lanes.read_jsonl(BASE / name)
        )


def test_synthetic_fixture_content_and_zero_exit_empty_output():
    fixture = fixtures()
    hvg = fixture["hvg-layer-choice"]
    assert len(hvg["counts"]) == len(hvg["X"]) == 64
    assert all(len(row) == len(hvg["gene_ids"]) == 32 for row in hvg["counts"])
    assert all(
        value >= 0 and isinstance(value, int) for row in hvg["counts"] for value in row
    )
    assert hvg["counts"] != hvg["X"]
    empty = fixture["empty-artifact"]
    assert empty["exit_code"] == 0
    assert len(empty["artifact_bytes_utf8"].splitlines()) == 1
    assert not empty[
        "repair_approved"
    ]  # Exit status alone cannot satisfy proposed task contract.


def receipt():
    return {
        "schema_version": "sckg-runtime-receipt-v1",
        "run_id": "synthetic",
        "attempt_id": "a1",
        "lane": "llm_only",
        "experiment_manifest_digest": "a" * 64,
        "scenario_digest": "b" * 64,
        "session_id": "isolated",
        "status": "not_run",
        "not_run_reason": "no formal run authorization",
        "seed": {
            "scheduling_seed": 20260921,
            "provider_seed_supported": None,
            "requested": None,
            "actual": None,
        },
        "retrieval_requests": [],
        "provider_calls": [],
        "artifact_checks": [],
        "failure_evidence": [],
        "latency_ms": None,
    }


def test_receipt_schema_distinguishes_not_run_from_zero_and_requires_evidence():
    schema = json.loads((BASE / "runtime_receipt.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    row = receipt()
    jsonschema.validate(row, schema)
    del row["not_run_reason"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)
    row = receipt()
    row["failure_evidence"] = [
        {"classification": "retrieval", "rationale": "guess", "evidence_refs": []}
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(row, schema)


def test_existing_models_not_replaced_or_fed_unreviewed_gold():
    row = lanes.read_jsonl(BASE / "development_scenarios.jsonl")[0]
    with pytest.raises(Exception):
        EvaluationCase.model_validate(row)
    run = EvaluationRunRecord(
        run_id="synthetic",
        experiment_id="synthetic",
        case_id="fixture",
        status="not_run",
    )
    assert run.input_tokens is None
    with pytest.raises(Exception):
        EvaluatorResult(
            evaluator_id="synthetic",
            metric_id="answer.task_pass",
            status="not_run",
            value=0,
        )


def test_no_started_experiment_or_gold_in_run_plan():
    plan = json.loads((BASE / "run_manifest.json").read_text())
    assert plan["status"] == "not_run_awaiting_00_review"
    assert plan["observed_calls"] == plan["observed_runs"] == []
    assert plan["runtime_configuration"]["model"] is None
    assert plan["target_design"]["total_scenarios"] == 50
    assert plan["target_design"]["independent_families"] == 34


def test_rebuild_check_is_deterministic_and_read_only():
    result = subprocess.run(
        [sys.executable, "-m", "eval.benchmark_v3.build_development_review", "--check"],
        cwd=lanes.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
