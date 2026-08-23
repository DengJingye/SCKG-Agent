from __future__ import annotations

from agent.research_chat_reasoner import OpenWorldReasoningResult
from eval.open_world_evaluation import (
    REQUIRED_CONFIRMATION,
    load_natural_query_cases,
    run_open_world_ablation,
    select_evaluation_panel,
)


class _FakeReasoner:
    def __init__(self, cases_by_query):
        self.cases_by_query = cases_by_query
        self.call_count = 0

    def answer_open_world(
        self,
        *,
        query,
        conversation_context,
        canonical_tasks,
        runtime_config,
    ):
        self.call_count += 1
        case = self.cases_by_query[query]
        expected_action = str(case.expected_action)
        return OpenWorldReasoningResult(
            status="ready",
            domain=case.expected_domain,
            intent=case.expected_intent,
            canonical_task=case.expected_task or "",
            needs_clarification=expected_action == "CLARIFY",
            confidence=1.0,
            answer=_answer_for(query),
            provider="fake",
            model_name="fake",
            input_tokens=10,
            output_tokens=5,
            provider_call_attempted=True,
        )


class _FakeService:
    def __init__(self, cases_by_query, profile):
        self.cases_by_query = cases_by_query
        self.profile = profile

    def run(self, query, *, conversation_context=None, user_runtime_config=None):
        case = self.cases_by_query[query]
        provider_calls = 2 * int(bool((user_runtime_config or {}).get("api_key")))
        expected_action = str(case.expected_action)
        terminal_status = {
            "ALLOW": "ANSWERED",
            "CLARIFY": "WAITING",
            "BLOCK": "BLOCKED",
        }[expected_action]
        return {
            "domain": case.expected_domain,
            "response_intent": case.expected_intent,
            "extracted_constraints": {
                "canonical_task": case.expected_task or "Unknown"
            },
            "candidate_tools": [],
            "workflow_code_bundle": (
                {"smoke_tested": True}
                if case.expected_intent == "workflow"
                and case.expected_task in {"doublet_detection", "batch_integration"}
                else None
            ),
            "deterministic_parent_result": {
                "status": terminal_status,
                "execution_request_count": 0,
            },
            "context_pack": {
                "retrieval_context": {
                    "snippets": [],
                    "governance_leakage_count": 0,
                    "adaptive_decision": {"route": self.profile or "default"},
                },
                "external_provider_call_count": provider_calls,
                "semantic_parse": {
                    "input_tokens": 4 if provider_calls else None,
                    "output_tokens": 2 if provider_calls else None,
                },
                "external_reasoning": {
                    "input_tokens": 6 if provider_calls else None,
                    "output_tokens": 3 if provider_calls else None,
                },
            },
            "claim_audit": {
                "schema_version": "grounded-answer-audit-v2",
                "passed": True,
                "scientific_answer": True,
                "claims": [],
                "cited_references": [],
                "invalid_citations": [],
                "citation_precision": 1.0,
                "citation_coverage": 1.0,
                "supported_claim_rate": 1.0,
                "unsupported_claim_count": 0,
                "execution_claim_violation": False,
                "governance_violation_count": 0,
                "reasons": [],
                "verifier": "deterministic_v2",
            },
            "final_report": _answer_for(query),
        }


def _answer_for(query: str) -> str:
    lowered = query.casefold()
    if "top-3" in lowered or "top 3" in lowered or "前三" in lowered:
        return "Scrublet\nscDblFinder\nDoubletFinder"
    if "top-2" in lowered or "top 2" in lowered or "前二" in lowered:
        return "Harmony\nScanorama"
    return "bounded answer"


def _fixture_components():
    cases = select_evaluation_panel(load_natural_query_cases())
    by_query = {case.query: case for case in cases}
    reasoner = _FakeReasoner(by_query)

    def service_factory(profile, _reasoner):
        return _FakeService(by_query, profile)

    return cases, reasoner, service_factory


def test_open_world_panel_is_24_evaluation_plus_4_adjudicated_answer_cases():
    panel = select_evaluation_panel(load_natural_query_cases())

    assert len(panel) == 28
    assert sum(case.split == "evaluation" for case in panel) == 24
    assert sum(case.split == "development" for case in panel) == 4
    assert all(
        case.split == "evaluation" or case.gold_status == "adjudicated"
        for case in panel
    )
    assert sum("answer_gold" in case.gold_tiers for case in panel) == 4
    assert sum("safety_gold" in case.gold_tiers for case in panel) == 2


def test_open_world_ablation_runs_local_lane_and_marks_external_not_run(tmp_path):
    _, reasoner, service_factory = _fixture_components()

    summary = run_open_world_ablation(
        output_dir=tmp_path,
        provider_call_budget=200,
        reasoner_factory=lambda: reasoner,
        service_factory=service_factory,
    )

    assert summary.case_count == 28
    assert summary.completed_provider_calls == 0
    assert summary.baseline_metrics["kg_rag_only"]["completed_case_count"] == 28
    assert summary.baseline_metrics["deepseek_only"]["not_run_count"] == 28
    assert summary.hard_gate_passed is False
    assert (tmp_path / "case_results.jsonl").exists()
    assert (tmp_path / "summary.json").exists()


def test_open_world_ablation_respects_budget_and_completes_all_lanes(tmp_path):
    _, reasoner, service_factory = _fixture_components()

    summary = run_open_world_ablation(
        output_dir=tmp_path,
        runtime_config={"api_key": "test-only"},
        safe_runtime_metadata={"api_host": "fake.local"},
        authorize_outbound=True,
        confirmation_text=REQUIRED_CONFIRMATION,
        provider_call_budget=200,
        reasoner_factory=lambda: reasoner,
        service_factory=service_factory,
    )

    assert summary.completed_provider_calls == 196
    assert summary.completed_provider_calls <= summary.provider_call_budget
    assert all(
        summary.baseline_metrics[baseline]["completed_case_count"] == 28
        for baseline in (
            "deepseek_only",
            "kg_rag_only",
            "deepseek_bm25",
            "deepseek_kg_hybrid",
            "deepseek_kg_hybrid_contract",
        )
    )
    assert summary.hard_gate_passed is True
    assert (
        summary.baseline_metrics["deepseek_kg_hybrid_contract"][
            "unauthorized_execution_request_count"
        ]
        == 0
    )


def test_open_world_ablation_resumes_from_case_checkpoint(tmp_path):
    _, reasoner, service_factory = _fixture_components()
    kwargs = {
        "output_dir": tmp_path,
        "runtime_config": {"api_key": "test-only"},
        "safe_runtime_metadata": {"api_host": "fake.local"},
        "authorize_outbound": True,
        "confirmation_text": REQUIRED_CONFIRMATION,
        "provider_call_budget": 200,
        "reasoner_factory": lambda: reasoner,
        "service_factory": service_factory,
    }

    first = run_open_world_ablation(**kwargs)
    first_reasoner_calls = reasoner.call_count
    second = run_open_world_ablation(**kwargs)

    assert first.completed_provider_calls == 196
    assert second.completed_provider_calls == 196
    assert reasoner.call_count == first_reasoner_calls
    assert (
        len(
            (
                tmp_path / "case_results.checkpoint.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        )
        == 140
    )
