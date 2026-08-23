from __future__ import annotations

from core.evaluation_models import EvaluationCase, ReferenceClaim
from eval.unified_case_runner import UnifiedConversationCaseRunner


class _Service:
    def run(self, query, *, conversation_context=None):
        return {
            "domain": "SINGLE_CELL",
            "response_intent": "evidence_qa",
            "extracted_constraints": {"canonical_task": "doublet_detection"},
            "deterministic_parent_result": {"execution_request_count": 0},
            "context_pack": {
                "semantic_route": {"domain": "SINGLE_CELL"},
                "grounded_answer_audit": {"invalid_citations": []},
            },
            "references": [
                {"source_span_id": "sourcev2:e28960d0fd977f0c60ce"}
            ],
            "final_report": "Scrublet uses a raw UMI count matrix [1].",
            "runtime_mode": "test",
        }


def test_unified_runner_scores_real_source_span_not_arbitrary_snippet():
    case = EvaluationCase(
        case_id="conversation.scrublet",
        dataset_version="v1",
        source="test",
        split="evaluation",
        input={"query": "Scrublet input?"},
        applicable_metrics=[
            "routing.domain",
            "claim.scientific_precision",
            "citation.precision",
        ],
        routing_gold={
            "domain": "SINGLE_CELL",
            "intent": "evidence_qa",
            "task": "doublet_detection",
        },
        answer_gold=[
            ReferenceClaim(
                claim_id="raw",
                claim_text="raw counts",
                source_span_ids=["sourcev2:e28960d0fd977f0c60ce"],
                scope="Scrublet",
            )
        ],
    )
    records, metrics = UnifiedConversationCaseRunner(service=_Service()).run(
        [case], experiment_id="exp"
    )
    by_id = {metric.metric_id: metric for metric in metrics}
    assert records[0].status == "completed"
    assert by_id["citation.precision"].value == 1.0
    assert by_id["citation.coverage"].value == 1.0
