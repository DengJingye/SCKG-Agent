from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.evaluation_models import (
    EvaluationCase,
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
    ReferenceClaim,
)
from core.knowledge_intelligence_models import HybridRetrievalRequest
from eval.architecture_ablation import (
    RESEARCH_GATE_IDS,
    _failure_queue,
    load_fixed_research_cases,
)
from eval.citation_adjudication import (
    CitationAdjudicationContract,
    CitationAdjudicationError,
    CitationReference,
    evidence_source_id,
    file_sha256,
    load_citation_adjudication,
)
from eval.evaluation_evaluators import decide_release_gate
from eval.citation_ranking_diagnostics import (
    CitationDiagnosticRetrieval,
    summarize_missing_supported_diagnostics,
)
from eval.unified_case_runner import UnifiedConversationCaseRunner


GOLD_PATH = Path("eval/fixtures/retrieval_gold_v2.json")
ADJUDICATION_PATH = Path(
    "eval/fixtures/architecture_citation_adjudication_v1.json"
)
CHUNKS_PATH = Path("data/indexes/evidence_chunks.jsonl")
MANIFEST_PATH = Path("data/indexes/evidence_index_manifest.json")
TOOL_08_ACCEPTED = "sourcev2:874963573d3988efdd71"
TOOL_08_NONACCEPTED = "sourcev2:756c0b3d078804b8a533"
TOOL_08_SOURCE = "SRCV2_d4d32e641274a88b"
WRONG_SOURCE_EVIDENCE = "benchmark:HR_BMK_MOFA2_jDR_cancer_2021"


@pytest.fixture(scope="module")
def citation_contract() -> CitationAdjudicationContract:
    return load_citation_adjudication(
        base_gold_path=GOLD_PATH,
        adjudication_path=ADJUDICATION_PATH,
        evidence_chunks_path=CHUNKS_PATH,
        evidence_manifest_path=MANIFEST_PATH,
    )


def test_overlay_is_complete_and_base_fixture_is_unchanged(citation_contract):
    cases, _ = load_fixed_research_cases(GOLD_PATH)

    assert len(cases) == 23
    assert len(citation_contract.cases) == 19
    assert sum(not case.answer_gold for case in cases) == 4
    assert citation_contract.base_gold_sha256 == file_sha256(GOLD_PATH)
    assert citation_contract.evaluator_version == "architecture-citation-v2"


def test_accepted_nonhistorical_evidence_is_supported(citation_contract):
    result = citation_contract.evaluate(
        "architecture.tool-08-metric",
        [CitationReference(TOOL_08_ACCEPTED, TOOL_08_SOURCE)],
    )

    assert result.exact_chunk_match is False
    assert result.relevant_source_match is True
    assert result.supported_evidence_match is True
    assert result.supported_precision == 1.0


def test_cited_same_source_nonaccepted_evidence_is_not_promoted(citation_contract):
    result = citation_contract.evaluate(
        "architecture.tool-08-metric",
        [CitationReference(TOOL_08_NONACCEPTED, TOOL_08_SOURCE)],
    )

    assert result.exact_chunk_match is True
    assert result.relevant_source_match is True
    assert result.supported_evidence_match is False
    assert result.supported_precision == 0.0


def test_duplicate_ids_count_once_but_distinct_same_source_ids_count(citation_contract):
    result = citation_contract.evaluate(
        "architecture.tool-08-metric",
        [
            CitationReference(TOOL_08_ACCEPTED, TOOL_08_SOURCE),
            CitationReference(TOOL_08_ACCEPTED, TOOL_08_SOURCE),
            CitationReference(TOOL_08_NONACCEPTED, TOOL_08_SOURCE),
        ],
    )

    assert result.cited_evidence_ids == (
        TOOL_08_ACCEPTED,
        TOOL_08_NONACCEPTED,
    )
    assert result.adjudicable_evidence_ids == (
        TOOL_08_ACCEPTED,
        TOOL_08_NONACCEPTED,
    )
    assert result.supported_evidence_match is True
    assert result.supported_precision == 0.5


def test_unknown_is_excluded_from_precision_but_remains_visible(citation_contract):
    fabricated = "sourcev2:fabricated0000000000"
    result = citation_contract.evaluate(
        "architecture.tool-08-metric",
        [
            CitationReference(fabricated, TOOL_08_SOURCE),
            CitationReference(TOOL_08_ACCEPTED, TOOL_08_SOURCE),
        ],
    )

    assert result.unknown_evidence_ids == (fabricated,)
    assert result.adjudicable_evidence_ids == (TOOL_08_ACCEPTED,)
    assert result.supported_precision == 1.0


def test_wrong_source_and_declared_source_conflict_are_distinct(citation_contract):
    authoritative_wrong_source = evidence_source_id(
        citation_contract.evidence_by_id[WRONG_SOURCE_EVIDENCE]
    )
    wrong_source = citation_contract.evaluate(
        "architecture.tool-08-metric",
        [CitationReference(WRONG_SOURCE_EVIDENCE, authoritative_wrong_source)],
    )
    conflict = citation_contract.evaluate(
        "architecture.tool-08-metric",
        [CitationReference(TOOL_08_ACCEPTED, "SRCV2_wrong")],
    )

    assert wrong_source.wrong_source_evidence_ids == (WRONG_SOURCE_EVIDENCE,)
    assert wrong_source.supported_evidence_match is False
    assert conflict.source_metadata_conflicts == (TOOL_08_ACCEPTED,)
    assert conflict.relevant_source_match is True
    assert conflict.supported_evidence_match is False


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda row: row["cases"][0]["relevant_source_ids"].append(
                "SRCV2_unadjudicated"
            ),
            "expanded source lacks accepted claim evidence",
        ),
        (
            lambda row: row["cases"][0]["accepted_evidence"][0].__setitem__(
                "rationale", "too short"
            ),
            "claim-level rationale is too short",
        ),
    ],
)
def test_overlay_rejects_unproven_source_expansion_and_weak_rationale(
    tmp_path,
    mutator,
    message,
):
    row = json.loads(ADJUDICATION_PATH.read_text(encoding="utf-8"))
    mutator(row)
    candidate = tmp_path / "adjudication.json"
    candidate.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(CitationAdjudicationError, match=message):
        load_citation_adjudication(
            base_gold_path=GOLD_PATH,
            adjudication_path=candidate,
            evidence_chunks_path=CHUNKS_PATH,
            evidence_manifest_path=MANIFEST_PATH,
        )


@pytest.mark.parametrize(
    ("references", "audit_passed", "expected_failure"),
    [
        (
            [{"source_span_id": "sourcev2:fabricated0000000000"}],
            True,
            "fabricated_or_unknown_citation",
        ),
        (
            [
                {
                    "source_span_id": WRONG_SOURCE_EVIDENCE,
                    "source_id": "HR_BMK_MOFA2_jDR_cancer_2021",
                }
            ],
            True,
            "unsupported_wrong_source_evidence",
        ),
        (
            [
                {
                    "source_span_id": TOOL_08_ACCEPTED,
                    "source_id": TOOL_08_SOURCE,
                }
            ],
            False,
            "unsupported_or_conflicting_scientific_claim",
        ),
    ],
)
def test_case_hard_failures_remain_on_evaluation_record(
    citation_contract,
    references,
    audit_passed,
    expected_failure,
):
    records, metrics = UnifiedConversationCaseRunner(
        service=_CitationService(references, audit_passed=audit_passed),
        citation_contract=citation_contract,
    ).run([_tool_08_case()], experiment_id="citation-v2")
    metric_by_id = {item.metric_id: item for item in metrics}

    assert records[0].status == "failed"
    assert expected_failure in {
        item["failure_type"] for item in records[0].evaluation_failures
    }
    assert metric_by_id["citation.hard_failure_count"].value == 1
    assert metric_by_id["citation.hard_failure_count"].details[
        "counted_case_ids"
    ] == ["architecture.tool-08-metric"]


def test_supported_coverage_can_pass_while_precision_falls(citation_contract):
    records, metrics = UnifiedConversationCaseRunner(
        service=_CitationService(
            [
                {
                    "source_span_id": TOOL_08_ACCEPTED,
                    "source_id": TOOL_08_SOURCE,
                },
                {
                    "source_span_id": TOOL_08_NONACCEPTED,
                    "source_id": TOOL_08_SOURCE,
                },
            ],
            audit_passed=True,
        ),
        citation_contract=citation_contract,
    ).run([_tool_08_case()], experiment_id="citation-v2")
    metric_by_id = {item.metric_id: item for item in metrics}

    assert records[0].status == "completed"
    assert metric_by_id["citation.supported_claim_coverage"].value == 1.0
    assert metric_by_id["citation.supported_precision"].value == 0.5
    assert metric_by_id["citation.hard_failure_count"].value == 0


def test_available_but_uncited_reference_is_not_scored(citation_contract):
    records, metrics = UnifiedConversationCaseRunner(
        service=_CitationService(
            [
                {
                    "source_span_id": TOOL_08_ACCEPTED,
                    "source_id": TOOL_08_SOURCE,
                }
            ],
            audit_passed=True,
            cited_references=[],
        ),
        citation_contract=citation_contract,
    ).run([_tool_08_case()], experiment_id="citation-v2")
    citation = records[0].observed["citation_evaluation"]

    assert citation["cited_evidence_ids"] == []
    assert citation["adjudicable_evidence_ids"] == []
    assert citation["supported_evidence_match"] is False
    assert next(
        item for item in metrics if item.metric_id == "citation.supported_precision"
    ).status == EvaluationMetricStatus.NOT_APPLICABLE


def test_invalid_citation_mapping_is_a_case_hard_failure(citation_contract):
    records, metrics = UnifiedConversationCaseRunner(
        service=_CitationService(
            [
                {
                    "source_span_id": TOOL_08_ACCEPTED,
                    "source_id": TOOL_08_SOURCE,
                }
            ],
            audit_passed=False,
            invalid_citations=[99],
        ),
        citation_contract=citation_contract,
    ).run([_tool_08_case()], experiment_id="citation-v2")

    assert "invalid_citation_mapping" in {
        item["failure_type"] for item in records[0].evaluation_failures
    }
    assert next(
        item for item in metrics if item.metric_id == "citation.hard_failure_count"
    ).value == 1
    queue = _failure_queue([_tool_08_case()], records)
    assert queue
    assert queue[0]["root_error_type"] == "invalid_citation_mapping"


def test_supported_coverage_cannot_hide_hard_failure_gate():
    metrics = [
        _gate_metric(metric_id, threshold, direction)
        for metric_id, (direction, threshold) in RESEARCH_GATE_IDS.items()
    ]
    hard_failure = next(
        item for item in metrics if item.metric_id == "citation.hard_failure_count"
    )
    hard_failure.value = 1
    hard_failure.numerator = 1

    gate = decide_release_gate(
        "citation-hard-failure",
        metrics,
        required_gates=RESEARCH_GATE_IDS,
    )

    assert gate.status == EvaluationSignal.BLOCKED
    assert "citation.hard_failure_count" in gate.blockers
    assert "citation.supported_claim_coverage" not in gate.blockers
    assert "citation.exact_chunk_coverage" not in RESEARCH_GATE_IDS
    assert "citation.relevant_source_coverage" not in RESEARCH_GATE_IDS


def test_evaluation_only_ranking_diagnostic_captures_real_stage_ranks(
    citation_contract,
):
    retrieval = CitationDiagnosticRetrieval(citation_contract)
    retrieval.begin_citation_diagnostic_case("architecture.tool-08-metric")
    result = retrieval.search(
        HybridRetrievalRequest(
            query="CellTypist precision recall global F1",
            tool_names=["CellTypist"],
            claim_types=["metric"],
            top_k=12,
            include_catalog=False,
            enable_dense=False,
            use_kg=False,
            use_governance_rerank=False,
        )
    )
    retrieval.end_citation_diagnostic_case()
    call = retrieval.citation_diagnostics()[0]

    assert result.hits[0].chunk_id == TOOL_08_ACCEPTED
    assert call["stages"]["initial_bm25"] == {TOOL_08_ACCEPTED: 1}
    assert call["stages"]["filtered_bm25"] == {TOOL_08_ACCEPTED: 1}
    assert call["stages"]["fusion"] == {TOOL_08_ACCEPTED: 1}
    assert call["stages"]["final_top_k"] == {TOOL_08_ACCEPTED: 1}
    assert call["first_divergence_by_evidence"][TOOL_08_ACCEPTED] == (
        "retained_by_retrieval_call"
    )


def test_ranking_diagnostic_classifies_wrong_selected_evidence():
    record = EvaluationRunRecord(
        run_id="diagnostic-run",
        experiment_id="diagnostic",
        case_id="architecture.tool-08-metric",
        status="failed",
        observed={
            "citation_evaluation": {
                "supported_evidence_match": False,
                "cited_evidence_ids": [TOOL_08_NONACCEPTED],
            }
        },
    )
    call = {
        "case_id": record.case_id,
        "accepted_evidence_ids": [TOOL_08_ACCEPTED],
        "stages": {
            "initial_bm25": {TOOL_08_ACCEPTED: 1},
            "filtered_bm25": {TOOL_08_ACCEPTED: 1},
            "fusion": {TOOL_08_ACCEPTED: 1},
            "governance_rerank": None,
            "final_top_k": {TOOL_08_ACCEPTED: 1},
        },
    }

    summary = summarize_missing_supported_diagnostics([record], [call])

    assert summary[0]["disposition"] == "wrong_evidence_selected"


def test_ranking_diagnostic_requires_selected_reference_for_assembly_failure():
    record = EvaluationRunRecord(
        run_id="diagnostic-run",
        experiment_id="diagnostic",
        case_id="architecture.tool-08-metric",
        status="failed",
        observed={
            "citation_evaluation": {
                "supported_evidence_match": False,
                "cited_evidence_ids": [],
            },
            "reference_span_ids": [TOOL_08_ACCEPTED],
        },
    )
    call = {
        "case_id": record.case_id,
        "accepted_evidence_ids": [TOOL_08_ACCEPTED],
        "stages": {
            "initial_bm25": {TOOL_08_ACCEPTED: 1},
            "filtered_bm25": {TOOL_08_ACCEPTED: 1},
            "fusion": {TOOL_08_ACCEPTED: 1},
            "governance_rerank": None,
            "final_top_k": {TOOL_08_ACCEPTED: 1},
        },
    }

    summary = summarize_missing_supported_diagnostics([record], [call])

    assert summary[0]["disposition"] == "selected_but_not_cited"


def test_ranking_diagnostic_does_not_call_deliberate_abstention_assembly_bug():
    record = EvaluationRunRecord(
        run_id="diagnostic-run",
        experiment_id="diagnostic",
        case_id="architecture.tool-08-metric",
        status="failed",
        observed={
            "citation_evaluation": {
                "supported_evidence_match": False,
                "cited_evidence_ids": [],
            },
            "reference_span_ids": [],
        },
    )
    call = {
        "case_id": record.case_id,
        "accepted_evidence_ids": [TOOL_08_ACCEPTED],
        "stages": {
            "initial_bm25": {TOOL_08_ACCEPTED: 1},
            "filtered_bm25": {TOOL_08_ACCEPTED: 1},
            "fusion": {TOOL_08_ACCEPTED: 1},
            "governance_rerank": None,
            "final_top_k": {TOOL_08_ACCEPTED: 1},
        },
    }

    summary = summarize_missing_supported_diagnostics([record], [call])

    assert summary[0]["disposition"] == "evidence_available_but_unbound"


class _CitationService:
    def __init__(
        self,
        references,
        *,
        audit_passed: bool,
        invalid_citations: list[int] | None = None,
        cited_references: list[int] | None = None,
    ):
        self.references = [
            {"index": index, **reference}
            for index, reference in enumerate(references, start=1)
        ]
        self.audit_passed = audit_passed
        self.invalid_citations = invalid_citations or []
        self.cited_references = (
            list(cited_references)
            if cited_references is not None
            else list(range(1, len(self.references) + 1))
        )

    def run(self, query, *, conversation_context=None):
        return {
            "domain": "SINGLE_CELL",
            "response_intent": "evidence_qa",
            "extracted_constraints": {"canonical_task": "cell_type_annotation"},
            "deterministic_parent_result": {"execution_request_count": 0},
            "context_pack": {
                "semantic_route": {"domain": "SINGLE_CELL"},
                "grounded_answer_audit": {
                    "passed": self.audit_passed,
                    "invalid_citations": self.invalid_citations,
                    "cited_references": self.cited_references,
                },
            },
            "candidate_tools": [{"tool_name": "CellTypist"}],
            "references": self.references,
            "final_report": "bounded answer",
            "runtime_mode": "test",
        }


def _tool_08_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="architecture.tool-08-metric",
        dataset_version="retrieval-gold-v2",
        source="test",
        split="evaluation",
        input={"query": "How is CellTypist performance evaluated?"},
        applicable_metrics=["citation.supported_claim_coverage"],
        routing_gold={
            "domain": "SINGLE_CELL",
            "intent": "evidence_qa",
            "task": "cell_type_annotation",
        },
        answer_gold=[
            ReferenceClaim(
                claim_id="tool-08-metric",
                claim_text="CellTypist precision recall and F1",
                source_span_ids=[TOOL_08_NONACCEPTED],
                scope="metric",
            )
        ],
    )


def _gate_metric(metric_id: str, threshold: float, direction: str) -> EvaluatorResult:
    return EvaluatorResult(
        evaluator_id="test",
        metric_id=metric_id,
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.PASSED,
        value=threshold,
        numerator=threshold,
        denominator=1,
        threshold=threshold,
        direction=direction,
    )
