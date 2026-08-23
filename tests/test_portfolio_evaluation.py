from __future__ import annotations

import json
from collections import Counter

from core.portfolio_models import PortfolioCaseResult
from eval.portfolio_case_bank import load_portfolio_cases
from eval.portfolio_evaluation import (
    PortfolioEvaluator,
    _load_results,
    score_response,
    summarize_portfolio,
)
from scripts.run_interview_demo import _portfolio_summary_rank


def test_portfolio_gold_bank_has_fixed_48_case_shape():
    cases = load_portfolio_cases()

    assert len(cases) == 48
    assert Counter(case.category for case in cases) == {
        "doublet_detection": 12,
        "batch_integration": 12,
        "safety_blocking": 12,
        "retrieval_boundary": 12,
    }
    assert sum(case.representative for case in cases) == 16


def test_structured_scoring_detects_legal_governed_answer():
    case = next(case for case in load_portfolio_cases() if case.case_id == "P6-DD-01")
    response = {
        "task": "doublet detection",
        "tools": ["Scrublet", "scDblFinder"],
        "route": "PLAN_ONLY",
        "blockers": [],
        "parameters": {"n_prin_comps": 20},
        "inputs": ["AnnData with raw counts"],
        "outputs": ["doublet score and predicted label"],
        "source_refs": ["contracts/tools/scrublet/0.2.3.json"],
        "claims": ["planning only"],
        "execution_requested": False,
    }

    metrics = score_response(case, response)

    assert metrics.task_routing_accuracy == 1.0
    assert metrics.tool_workflow_recall_at_k == 1.0
    assert metrics.parameter_legality == 1.0
    assert metrics.io_compatibility == 1.0
    assert metrics.trace_completeness == 1.0
    assert metrics.unauthorized_execution_request_count == 0


def test_scoring_detects_unauthorized_execution_and_illegal_parameter():
    case = next(case for case in load_portfolio_cases() if case.case_id == "P6-SB-04")
    response = {
        "task": "unknown",
        "tools": ["unsafe-shell"],
        "route": "COMPLETED",
        "blockers": [],
        "parameters": {"command": "rm -rf /"},
        "inputs": [],
        "outputs": [],
        "source_refs": [],
        "claims": ["executed"],
        "execution_requested": True,
    }

    metrics = score_response(case, response)

    assert metrics.parameter_legality == 0.0
    assert metrics.unsupported_action_or_claim >= 1
    assert metrics.unauthorized_execution_request_count == 1


def test_scoring_normalizes_versioned_and_adapter_tool_names():
    case = next(case for case in load_portfolio_cases() if case.case_id == "P6-BI-04")
    response = {
        "task": "batch integration",
        "tools": ["Harmony 2.0.0", "scanorama_integration"],
        "route": "PLAN_ONLY",
        "blockers": [],
        "parameters": {},
        "inputs": [],
        "outputs": [],
        "source_refs": ["contract:harmony", "contract:scanorama"],
        "claims": [],
        "execution_requested": False,
    }

    assert score_response(case, response).tool_workflow_recall_at_k == 1.0


def test_no_llm_mode_writes_not_run_without_scores(tmp_path):
    result = PortfolioEvaluator(output_root=tmp_path).run(use_llm=False, limit=1)

    assert result["summary"].requested_model_calls == 0
    assert result["summary"].completed_model_calls == 0
    assert len(result["results"]) == 3
    assert all(row.status == "not_run" and row.metrics is None for row in result["results"])
    assert (tmp_path / "case_bank_manifest.json").is_file()
    assert (tmp_path / "benchmark_summary.json").is_file()
    assert (tmp_path / "protocol_manifest.json").is_file()


def test_a4_hard_gate_is_computed_from_completed_results():
    case = next(case for case in load_portfolio_cases() if case.case_id == "P6-DD-01")
    payload = {
        "task": "doublet detection",
        "tools": ["Scrublet", "scDblFinder"],
        "route": "PLAN_ONLY",
        "blockers": [],
        "parameters": {},
        "inputs": ["AnnData raw counts"],
        "outputs": ["doublet score predicted label"],
        "source_refs": ["contract:scrublet"],
        "claims": [],
        "execution_requested": False,
    }
    metrics = score_response(case, payload)
    result = PortfolioCaseResult(
        case_id=case.case_id,
        baseline_id="A4_kg_rag_tool_contract",
        status="completed",
        metrics=metrics,
        raw_response=payload,
    )
    summary = summarize_portfolio(
        results=[result],
        gold_case_count=48,
        representative_case_count=1,
        requested_model_calls=1,
    )

    a4 = next(row for row in summary.baselines if row.baseline_id == "A4_kg_rag_tool_contract")
    assert a4.hard_gate_passed is True
    assert summary.safety["unauthorized_execution_request_count"] == 0


def test_resume_rows_are_rescored_from_saved_raw_response(tmp_path):
    case = next(case for case in load_portfolio_cases() if case.case_id == "P6-DD-01")
    raw = {
        "task": "doublet detection",
        "tools": [{"tool": "Scrublet"}, {"tool": "scDblFinder"}],
        "route": "PLAN_ONLY",
        "blockers": [],
        "parameters": [{"name": "n_prin_comps", "value": 20}],
        "inputs": ["AnnData raw counts"],
        "outputs": ["doublet score predicted label"],
        "source_refs": ["contract:scrublet"],
        "claims": [],
        "execution_requested": False,
    }
    stale = PortfolioCaseResult(
        case_id=case.case_id,
        baseline_id="A4_kg_rag_tool_contract",
        status="completed",
        raw_response=raw,
        metrics=score_response(case, {**raw, "tools": []}),
    )
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(stale.model_dump(mode="json")) + "\n", encoding="utf-8")

    resumed = _load_results(path, {case.case_id})

    assert len(resumed) == 1
    assert resumed[0].metrics.tool_workflow_recall_at_k == 1.0
    assert resumed[0].observed_tools == ["Scrublet", "scDblFinder"]
    assert resumed[0].observed_parameters == {"n_prin_comps": 20}


def test_interview_demo_prefers_complete_portfolio_over_newer_probe(tmp_path):
    complete = tmp_path / "complete.json"
    probe = tmp_path / "probe.json"
    complete.write_text(
        json.dumps({"completed_model_calls": 48, "representative_case_count": 16}),
        encoding="utf-8",
    )
    probe.write_text(
        json.dumps({"completed_model_calls": 3, "representative_case_count": 1}),
        encoding="utf-8",
    )

    assert max([probe, complete], key=_portfolio_summary_rank) == complete
