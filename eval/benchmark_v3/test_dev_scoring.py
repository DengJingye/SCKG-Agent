"""Offline regression tests for receipt repair, score aggregation and attribution.

These validate engineering contracts, not independent human scientific agreement.
"""
from copy import deepcopy
import json

import pytest

from eval.benchmark_v3.dev_pilot import BASE, sha, write
from eval.benchmark_v3.dev_scoring import (
    correct_receipts, criteria, read_rows, receipt_for, validate_receipts, validate_review,
)


def fixture_review(tmp_path, case_id="dev-K01-hvg-input-a"):
    write(tmp_path / "output.json", {"answer": "synthetic answer"})
    run = {"case_id": case_id, "answer_hash": sha(b"synthetic answer"),
           "observed": {"answer": "synthetic answer"}}
    review = {"output_sha256": run["answer_hash"], "checks": dict.fromkeys(criteria(case_id), True),
        "major_scientific_error": False, "rationale": "Synthetic aggregation fixture, not a scientific reference",
        "answer_excerpts": ["synthetic answer"], "failure": None}
    return run, review


@pytest.mark.parametrize("case_id", ["dev-K01-hvg-input-a", "dev-K02-pca-chunked-a",
    "dev-K03-reference-annotation-a", "dev-K04-evidence-version-a", "dev-O01", "dev-W02"])
def test_all_required_checks_and_no_major_error_pass(tmp_path, case_id):
    run, review = fixture_review(tmp_path, case_id)
    assert validate_review(review, run, tmp_path)


@pytest.mark.parametrize("kind", ["missing_condition", "major_error", "empty_artifact"])
def test_failures_not_compensated_by_other_correct_checks(tmp_path, kind):
    run, review = fixture_review(tmp_path, "dev-W02" if kind == "empty_artifact" else "dev-K01-hvg-input-a")
    if kind == "major_error":
        review["major_scientific_error"] = True
    else:
        review["checks"][next(iter(review["checks"]))] = False
    review["failure"] = {"stage": "unresolved", "rationale": "Root cause not proven by final output alone",
                         "evidence_refs": ["output.json"]}
    assert not validate_review(review, run, tmp_path)


@pytest.mark.parametrize("mutation", ["stale", "invented_quote", "nonboolean", "missing_check", "unbound_failure"])
def test_invalid_review_is_rejected(tmp_path, mutation):
    run, review = fixture_review(tmp_path)
    if mutation == "stale": review["output_sha256"] = "a" * 64
    if mutation == "invented_quote": review["answer_excerpts"] = ["not in actual output"]
    if mutation == "nonboolean": review["major_scientific_error"] = "false"
    if mutation == "missing_check": review["checks"].pop(next(iter(review["checks"])))
    if mutation == "unbound_failure": review["checks"][next(iter(review["checks"]))] = False
    with pytest.raises(ValueError):
        validate_review(review, run, tmp_path)


def test_passing_clarification_is_not_a_failure(tmp_path):
    run, review = fixture_review(tmp_path, "dev-O01")
    review["failure"] = {"stage": "synthesis", "rationale": "Incorrectly marking a correct clarification"}
    with pytest.raises(ValueError, match="passing task"):
        validate_review(review, run, tmp_path)


def test_receipt_correction_uses_captured_effective_request_and_retains_original(tmp_path):
    directory = tmp_path / "runs" / "synthetic"
    incoming = {"query": "synthetic", "use_scientific_evidence": False}
    original = {"status": "completed", "run_id": "synthetic", "retrieval_requests": [
        {"request_id": "r1", "effective_request": incoming}]}
    actual = dict(incoming, use_scientific_evidence=True)
    write(directory / "runtime_receipt.json", original)
    write(directory / "lane_isolation.json", {"actual_backend_calls": [{"backend": "legacy", "request": actual}]})
    before = (directory / "runtime_receipt.json").read_bytes()
    correct_receipts(tmp_path)
    assert receipt_for(directory)["retrieval_requests"][0]["effective_request"] == actual
    assert (directory / "runtime_receipt.json").read_bytes() == before
    assert json.loads((tmp_path / "receipt_corrections.json").read_text())[0]["provider_rerun"] is False


def test_live_56_receipts_and_52_reviews_are_consistent():
    output = BASE / "dev_pilot_20260921"
    result = validate_receipts(output, 56)
    assert result["pass"], result["errors"]
    reviews = {r["blind_id"]: r for r in read_rows(output / "reviews.jsonl")}
    assert len(reviews) == 52
    scores = json.loads((output / "scoring_results.json").read_text())
    assert len(scores) == 56
    for row in scores:
        directory = output / "runs" / row["run_id"]
        run = json.loads((directory / "run_record.json").read_text())
        if run["status"] == "not_run":
            assert row["result"]["status"] == "not_run" and row["result"]["value"] is None
            assert receipt_for(directory)["not_run_reason"] == "shared_execution_interface_unavailable"
        else:
            review = reviews["review-" + sha(run["run_id"])[:12]]
            assert validate_review(review, run, directory) == bool(row["result"]["value"])


def test_corrections_do_not_modify_outputs_or_claim_additional_calls():
    output = BASE / "dev_pilot_20260921"
    corrections = json.loads((output / "receipt_corrections.json").read_text())
    assert corrections
    for row in corrections:
        directory = output / "runs" / row["run_id"]
        original = json.loads((directory / "runtime_receipt.json").read_text())
        corrected = receipt_for(directory)
        assert original["provider_calls"] == corrected["provider_calls"]
        assert original["status"] == corrected["status"]
        assert not row["outputs_changed"] and not row["provider_rerun"]


def test_actual_synthesis_messages_equal_captured_context_no_held_assertions():
    output = BASE / "dev_pilot_20260921"
    held = "statement-revision:d0d887b96b7a1cf45e2c47bf:1"
    for path in (output / "runs").glob("*/final_context.json"):
        context = json.loads(path.read_text())
        for call in context["synthesis_calls"]:
            assert call["actual_messages"] == json.loads((path.parent / call["request_ref"]).read_text())["messages"]
        scientific = context["product_context_pack"].get("response_context", {}).get("scientific_kg", {})
        if scientific.get("adapter_called"):
            assert scientific["approved_kg_sha256"] == "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"
            assert held not in json.dumps(scientific.get("facts", []))


def test_final_attribution_revision_preserves_all_scientific_scores():
    output = BASE / "dev_pilot_20260921"
    initial = json.loads((output / "scoring_results.json").read_text())
    final = json.loads((output / "scoring_results.final.json").read_text())
    assert {r["run_id"]: r["result"] for r in initial} == {r["run_id"]: r["result"] for r in final}
    summary = json.loads((output / "summary.final.json").read_text())
    assert summary["failure_stage_counts"] == {"routing": 4, "evidence": 1, "validation-governance": 6, "unresolved": 18}
    for row in final:
        if row["review"]:
            directory = output / "runs" / row["run_id"]
            run = json.loads((directory / "run_record.json").read_text())
            assert validate_review(row["review"], run, directory) == bool(row["result"]["value"])
