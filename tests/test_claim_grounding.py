from __future__ import annotations

from agent.claim_grounding import (
    bind_claim_evidence,
    claim_requests_for_query,
    external_answer_preserves_bindings,
    reasoner_binding_projection,
    references_from_bindings,
    render_grounded_answer,
)
from agent.research_chat_reasoner import ExternalReasoningResult
from agent.research_chat_service import ResearchChatService
from core.trace_context import TraceCollector


def _snippet(
    subject: str,
    evidence_id: str,
    claim_type: str,
    text: str,
    *,
    source_bound: bool = True,
    score: float = 1.0,
) -> dict:
    return {
        "chunk_id": evidence_id,
        "source_id": f"source:{subject.casefold()}",
        "source_span": f"methods:{evidence_id}",
        "tool_name": subject,
        "title": f"{subject} governed documentation",
        "claim_type": claim_type,
        "claim_span": text,
        "relevance_score": score,
        "source_bound": source_bound,
    }


def _ground(query: str, subjects: list[str], snippets: list[dict]):
    requests = claim_requests_for_query(query, subjects=subjects, snippets=snippets)
    bindings = bind_claim_evidence(requests, snippets, query=query)
    references = references_from_bindings(bindings)
    report = render_grounded_answer(bindings, references, task_label="Test task")
    return requests, bindings, references, report


def _assert_local_bindings(bindings, references, report):
    by_id = {row["source_span_id"]: row for row in references}
    for binding in bindings:
        if binding.support_status == "abstained":
            assert binding.evidence_refs == ()
            continue
        citations = "".join(
            f"[{by_id[evidence.evidence_span_id]['index']}]"
            for evidence in binding.evidence_refs
        )
        assert f"{binding.claim_text}{citations}" in report


def test_one_entity_one_claim_is_atomic_and_source_bound():
    snippets = [
        _snippet(
            "CellTypist",
            "source:celltypist-input",
            "input_requirement",
            "CellTypist accepts a log-normalized expression matrix as input.",
        )
    ]

    requests, bindings, references, report = _ground(
        "What input does CellTypist require?", ["CellTypist"], snippets
    )

    assert [(row.subject, row.predicate) for row in requests] == [
        ("CellTypist", "input_requirement")
    ]
    assert bindings[0].support_status == "supported"
    assert bindings[0].evidence_refs[0].evidence_span_id == "source:celltypist-input"
    assert references[0]["source_bound"] is True
    _assert_local_bindings(bindings, references, report)


def test_definitional_method_type_proposition_passes():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:definition",
            "general",
            "ExampleTool is a method for batch integration of single-cell data.",
        )
    ]

    _, bindings, references, report = _ground(
        "What method type is ExampleTool?", ["ExampleTool"], snippets
    )

    assert bindings[0].support_status == "supported"
    assert bindings[0].request.predicate == "method_type"
    _assert_local_bindings(bindings, references, report)


def test_scientific_purpose_method_type_proposition_passes():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:purpose",
            "general",
            "ExampleTool was designed for detecting doublets in single-cell transcriptomes.",
        )
    ]

    _, bindings, references, report = _ground(
        "Find source-bound information about ExampleTool and its supported task.",
        ["ExampleTool"],
        snippets,
    )

    assert bindings[0].support_status == "supported"
    _assert_local_bindings(bindings, references, report)


def test_runtime_troubleshooting_statement_fails_method_type():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:runtime",
            "workflow",
            "ExampleTool runs with Python and troubleshooting uses pytest for installation checks.",
        )
    ]

    _, bindings, references, report = _ground(
        "What method type is ExampleTool?", ["ExampleTool"], snippets
    )

    assert bindings[0].support_status == "abstained"
    assert bindings[0].abstain_reason == "no_direct_support"
    assert references == []
    assert "[1]" not in report


def test_input_or_output_statement_alone_fails_method_type():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:io",
            "output",
            "ExampleTool accepts count matrices and returns integrated embeddings.",
        )
    ]

    _, bindings, references, _ = _ground(
        "What method type is ExampleTool?", ["ExampleTool"], snippets
    )

    assert bindings[0].support_status == "abstained"
    assert references == []


def test_parameter_install_or_environment_statement_fails_method_type():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:environment",
            "parameter",
            "ExampleTool installs with pip, depends on Python 3.12, and has parameter k=10.",
        )
    ]

    _, bindings, references, _ = _ground(
        "What method type is ExampleTool?", ["ExampleTool"], snippets
    )

    assert bindings[0].support_status == "abstained"
    assert references == []


def test_direct_method_definition_wins_over_weak_runtime_span():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:runtime",
            "workflow",
            "Methods for installation use Python; ExampleTool runs with pytest.",
            score=100.0,
        ),
        _snippet(
            "ExampleTool",
            "source:definition",
            "general",
            "ExampleTool is a framework for cell type annotation in single-cell data.",
            score=0.01,
        ),
    ]

    _, bindings, references, report = _ground(
        "What method type is ExampleTool?", ["ExampleTool"], snippets
    )

    assert bindings[0].evidence_refs[0].evidence_span_id == "source:definition"
    assert references[0]["source_span_id"] == "source:definition"
    _assert_local_bindings(bindings, references, report)


def test_one_entity_multiple_claims_keep_independent_bindings():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:example-input",
            "input_requirement",
            "ExampleTool accepts a raw count matrix as input.",
        ),
        _snippet(
            "ExampleTool",
            "source:example-output",
            "output",
            "ExampleTool returns an embedding matrix as its output.",
        ),
        _snippet(
            "ExampleTool",
            "source:example-limit",
            "failure_mode",
            "A limitation is that ExampleTool may perform poorly on rare populations.",
        ),
    ]

    _, bindings, references, report = _ground(
        "Describe ExampleTool input, output, and limitations.",
        ["ExampleTool"],
        snippets,
    )

    assert [row.request.predicate for row in bindings] == [
        "input_requirement",
        "output",
        "limitation",
    ]
    assert [row.evidence_refs[0].evidence_span_id for row in bindings] == [
        "source:example-input",
        "source:example-output",
        "source:example-limit",
    ]
    assert len(references) == 3
    _assert_local_bindings(bindings, references, report)


def test_multiple_entities_shared_predicate_never_borrow_citations():
    snippets = [
        _snippet(
            "CellTypist",
            "source:celltypist-method",
            "general",
            "CellTypist is a tool for automated cell type annotation using reference-trained models.",
        ),
        _snippet(
            "SingleR",
            "source:singler-method",
            "general",
            "SingleR is a method for reference-based cell type annotation.",
        ),
    ]

    requests, bindings, references, report = _ground(
        "Describe both CellTypist and SingleR method types.",
        ["CellTypist", "SingleR"],
        snippets,
    )

    assert [(row.subject, row.predicate) for row in requests] == [
        ("CellTypist", "method_type"),
        ("SingleR", "method_type"),
    ]
    assert [row.evidence_refs[0].evidence_span_id for row in bindings] == [
        "source:celltypist-method",
        "source:singler-method",
    ]
    _assert_local_bindings(bindings, references, report)


def test_entityless_discovery_requires_local_subject_predicate_and_object():
    snippets = [
        _snippet(
            "RelevantMethod",
            "source:local-relation",
            "general",
            "RelevantMethod is a reference-based method for cell type annotation.",
        ),
        _snippet(
            "UnrelatedMethod",
            "source:split-relation",
            "general",
            "UnrelatedMethod was included in a benchmark. Reference-based cell type annotation methods were discussed elsewhere.",
        ),
    ]

    requests, bindings, references, report = _ground(
        "reference-based cell type annotation", [], snippets
    )

    assert [row.subject for row in requests] == ["RelevantMethod"]
    assert [row.request.subject for row in bindings] == ["RelevantMethod"]
    assert [row["tool_name"] for row in references] == ["RelevantMethod"]
    assert "UnrelatedMethod" not in report


def test_entityless_benchmark_list_does_not_create_method_bindings():
    snippets = [
        _snippet(
            "FirstTool",
            "source:benchmark-list",
            "benchmark",
            "FirstTool, SecondTool, and ThirdTool were compared in a reference-based annotation benchmark.",
        )
    ]

    requests, bindings, references, report = _ground(
        "reference-based cell type annotation", [], snippets
    )

    assert requests == []
    assert bindings == []
    assert references == []
    assert "[1]" not in report


def test_comparison_cannot_attach_object_constraint_to_listed_subject():
    snippets = [
        _snippet(
            "IntegrationTool",
            "source:comparison",
            "benchmark",
            "IntegrationTool integration was evaluated together with reference-based annotation methods.",
        )
    ]

    requests, bindings, references, _ = _ground(
        "reference-based cell type annotation", [], snippets
    )

    assert requests == []
    assert bindings == []
    assert references == []


def test_clause_local_multiple_entities_keep_independent_predicates():
    snippets = [
        _snippet(
            "CellTypist",
            "source:celltypist-input",
            "input_requirement",
            "CellTypist accepts normalized expression data as input.",
        ),
        _snippet(
            "SingleR",
            "source:singler-limit",
            "failure_mode",
            "A limitation is that SingleR may perform poorly without a suitable reference.",
        ),
    ]

    requests, bindings, references, report = _ground(
        "CellTypist input requirements; SingleR limitations.",
        ["CellTypist", "SingleR"],
        snippets,
    )

    assert [(row.subject, row.predicate) for row in requests] == [
        ("CellTypist", "input_requirement"),
        ("SingleR", "limitation"),
    ]
    assert all(row.support_status == "supported" for row in bindings)
    _assert_local_bindings(bindings, references, report)


def test_ambiguous_scope_abstains_without_cross_product():
    requests, bindings, references, report = _ground(
        "CellTypist input requirements SingleR limitations",
        ["CellTypist", "SingleR"],
        [],
    )

    assert len(requests) == 2
    assert all(row.ambiguous for row in requests)
    assert {row.abstain_reason for row in bindings} == {"ambiguous_target"}
    assert references == []
    assert "[1]" not in report


def test_entityless_discovery_uses_each_supporting_primary_entity():
    snippets = [
        _snippet(
            "CellTypist",
            "source:celltypist-method",
            "general",
            "CellTypist is a tool for automated cell type annotation using reference-trained models.",
        ),
        _snippet(
            "SingleR",
            "source:singler-method",
            "general",
            "We developed a computational method called SingleR, which correlates single-cell transcriptomes with reference data for annotation.",
        ),
        _snippet(
            "CatalogOnly",
            "catalog:method",
            "general",
            "CatalogOnly is a method for cell type annotation.",
            source_bound=False,
        ),
    ]

    requests, bindings, references, report = _ground(
        "reference-based cell type annotation", [], snippets
    )

    assert [(row.subject, row.mode) for row in requests] == [
        ("CellTypist", "entityless_discovery"),
        ("SingleR", "entityless_discovery"),
    ]
    assert all(row.support_status == "supported" for row in bindings)
    assert "CatalogOnly" not in report
    _assert_local_bindings(bindings, references, report)


def test_secondary_entity_mention_is_binding_local_and_does_not_mutate_hit():
    benchmark = _snippet(
        "Harmony",
        "source:multi-tool",
        "input_requirement",
        "Scanorama accepts a list of cell-by-gene matrices as input. Harmony was also evaluated.",
    )

    _, bindings, references, report = _ground(
        "What input does Scanorama require?", ["Scanorama"], [benchmark]
    )

    assert bindings[0].support_status == "supported"
    assert references[0]["tool_name"] == "Scanorama"
    assert benchmark["tool_name"] == "Harmony"
    _assert_local_bindings(bindings, references, report)


def test_object_constraint_and_direct_support_fail_closed():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:normalized",
            "input_requirement",
            "ExampleTool accepts normalized expression data as input.",
        )
    ]

    _, bindings, references, report = _ground(
        "Does ExampleTool require raw counts as input?", ["ExampleTool"], snippets
    )

    assert bindings[0].support_status == "abstained"
    assert bindings[0].abstain_reason == "no_direct_support"
    assert references == []
    assert "[1]" not in report


def test_unsupported_sibling_claim_cannot_borrow_a_supported_citation():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:example-input",
            "input_requirement",
            "ExampleTool accepts a raw count matrix as input.",
        )
    ]

    _, bindings, references, report = _ground(
        "Describe ExampleTool input and limitations.", ["ExampleTool"], snippets
    )

    assert [row.support_status for row in bindings] == ["supported", "abstained"]
    limitation_line = next(line for line in report.splitlines() if "主要限制" in line)
    assert "[1]" not in limitation_line
    _assert_local_bindings(bindings, references, report)


def test_external_reasoner_projection_cannot_rebind_citations():
    snippets = [
        _snippet(
            "ExampleTool",
            "source:example-input",
            "input_requirement",
            "ExampleTool accepts a raw count matrix as input.",
        )
    ]
    _, bindings, references, report = _ground(
        "What input does ExampleTool require?", ["ExampleTool"], snippets
    )

    projection = reasoner_binding_projection(bindings, references)
    assert projection[0]["claim_text"] == bindings[0].claim_text
    assert projection[0]["citation_indexes"] == [1]
    assert external_answer_preserves_bindings(report, bindings, references) is True
    assert (
        external_answer_preserves_bindings(
            "ExampleTool accepts arbitrary normalized values.[1]",
            bindings,
            references,
        )
        is False
    )


class _CaptureReasoner:
    def __init__(self) -> None:
        self.kwargs = None

    def synthesize(self, **kwargs):
        self.kwargs = kwargs
        return ExternalReasoningResult(status="not_available")


def test_evidence_qa_reasoner_receives_bindings_without_static_knowledge(tmp_path):
    reasoner = _CaptureReasoner()
    service = ResearchChatService(
        dense_default_enabled=False,
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )
    service._reasoner = reasoner

    state = service.run(
        "What input matrix and data state does CellTypist require?",
        user_runtime_config={"privacy_authorized": True},
    )

    assert reasoner.kwargs is not None
    assert reasoner.kwargs["algorithm_cards"] == []
    assert reasoner.kwargs["tool_observations"] == []
    assert reasoner.kwargs["contract_context"] == []
    assert reasoner.kwargs["allow_unverified_model_knowledge"] is False
    assert reasoner.kwargs["retrieval_snippets"][0]["evidence_span_ids"]
    assert state["context_pack"]["external_reasoning"]["status"] == "not_available"


def test_retrieval_request_and_ranked_hits_are_not_changed_by_grounding(tmp_path):
    service = ResearchChatService(
        dense_default_enabled=False,
        evaluation_retrieval_profile="bm25",
        trace_collector=TraceCollector(tmp_path / "traces.jsonl"),
    )
    original_search = service.retrieval.search
    calls = []

    def capture(request):
        result = original_search(request)
        calls.append(
            (
                request.model_dump(mode="json"),
                [
                    (hit.chunk_id, hit.tool_name, hit.score, hit.source_id)
                    for hit in result.hits
                ],
            )
        )
        return result

    service.retrieval.search = capture
    state = service.run("What outputs and artifacts does Harmony produce?")

    assert len(calls) == 1
    request_row, ranked_hits = calls[0]
    assert request_row["top_k"] == 12
    assert request_row["tool_names"] == ["Harmony"]
    assert request_row["claim_types"] == ["output"]
    assert [
        (
            row["chunk_id"],
            row["tool_name"],
            row["relevance_score"],
            row["source_id"],
        )
        for row in state["retrieval_results"]
    ] == ranked_hits
