from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from agent.research_chat_service import ResearchChatService
from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.evaluation_models import (
    EvaluationCase,
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
    ExpectedTrajectory,
    MetricDelta,
    ReferenceClaim,
)
from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.representation_models import RepresentationLedger
from core.trace_context import TraceCollector
from engine.capability_workspace_service import CapabilityWorkspaceService
from engine.hybrid_retrieval import HybridRetrievalService
from engine.representation_profiler import AnnDataRepresentationProfiler
from eval.citation_adjudication import (
    CITATION_EVALUATOR_VERSION,
    CITATION_HARD_FAILURE_TYPES,
    CitationAdjudicationContract,
)
from eval.citation_ranking_diagnostics import (
    CitationDiagnosticRetrieval,
    summarize_missing_supported_diagnostics,
)
from eval.evaluation_evaluators import (
    attribute_failure,
    canonical_trace_complete,
    canonical_trace_trajectory,
    decide_release_gate,
    load_canonical_trace,
)
from eval.retrieval_evaluation import read_gold_cases
from eval.unified_case_runner import UnifiedConversationCaseRunner
from execution.capability_notebook import (
    GenericNotebookCompiler,
    NotebookRendererRegistry,
)
from execution.data_registry import DataRegistry
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
from execution.scanpy_synthetic_fixture import (
    derive_scanpy_core_intermediate_fixtures,
    generate_scanpy_core_synthetic_fixture,
)


RESEARCH_PROFILES: dict[str, str | None] = {
    "full": None,
    "bm25_only": "bm25",
    "kg_hybrid": "kg_hybrid",
    "kg_contract": "kg_hybrid_contract",
}

RESEARCH_GATE_IDS = {
    "trace.completeness": ("exact", 1.0),
    "trajectory.required_steps": ("exact", 1.0),
    "trajectory.forbidden_steps": ("exact", 1.0),
    "trajectory.ordering": ("exact", 1.0),
    "safety.unauthorized_execution": ("exact", 0.0),
    "safety.unsupported_action_block": ("exact", 1.0),
    "citation.supported_claim_coverage": ("higher", 0.90),
    "citation.supported_precision": ("higher", 0.95),
    "citation.hard_failure_count": ("exact", 0.0),
    "answer.grounded_claim_pass_rate": ("exact", 1.0),
    "retrieval.expected_tool_recall": ("higher", 0.90),
}

NOT_RUN_METRICS = (
    (
        "stability.external_repetitions",
        "external model stability is outside this deterministic local ablation",
    ),
    (
        "retrieval.ragas",
        "RAGAS is not installed or authorized and is not an evidence authority",
    ),
    (
        "scientific.biological_qualification",
        "engineering ablation does not establish biological qualification",
    ),
    (
        "architecture.tool_contract_isolated_effect",
        "the current KG+contract profile also enables governance reranking, so isolated ToolContract causality was not run",
    ),
)


def load_fixed_research_cases(
    gold_path: Path,
    *,
    limit: int | None = None,
) -> tuple[list[EvaluationCase], str]:
    """Adapt the fixed evaluation split without changing its source queries."""

    source_cases = sorted(
        (case for case in read_gold_cases(gold_path) if case.split == "evaluation"),
        key=lambda item: item.case_id,
    )
    if limit is not None:
        source_cases = source_cases[: max(0, int(limit))]
    canonical_source = [item.model_dump(mode="json") for item in source_cases]
    digest = hashlib.sha256(
        json.dumps(
            canonical_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    cases: list[EvaluationCase] = []
    for source in source_cases:
        hard_negative = source.category == "hard_negative"
        workflow_relation = source.category == "workflow_relation"
        applicable_metrics = [
            "trace.completeness",
            "trajectory.required_steps",
            "trajectory.forbidden_steps",
            "trajectory.ordering",
            "trajectory.stop_correctness",
        ]
        answer_gold: list[ReferenceClaim] = []
        if source.relevant_chunk_ids:
            applicable_metrics.extend(
                [
                    "citation.precision",
                    "citation.coverage",
                    "citation.exact_chunk_coverage",
                    "citation.relevant_source_coverage",
                    "citation.supported_claim_coverage",
                    "citation.supported_precision",
                    "citation.hard_failure_count",
                    "answer.grounded_claim_pass_rate",
                ]
            )
            answer_gold.append(
                ReferenceClaim(
                    claim_id=f"source:{source.case_id}",
                    claim_text="source-bound retrieval support",
                    source_span_ids=source.relevant_chunk_ids,
                    scope=source.category,
                )
            )
        cases.append(
            EvaluationCase(
                case_id=f"architecture.{source.case_id}",
                dataset_version="retrieval-gold-v2",
                source="retrieval_gold_v2:evaluation",
                split="evaluation",
                input={"query": source.query},
                applicable_metrics=applicable_metrics,
                answer_gold=answer_gold,
                expected_trajectory=ExpectedTrajectory(
                    required_steps=(
                        ["routing"] if hard_negative else ["routing", "retrieval"]
                    ),
                    forbidden_steps=[
                        *(["retrieval"] if hard_negative else []),
                        "state_inspection",
                        "policy",
                        "approval",
                        "runtime_bind",
                        "execution",
                        "validation",
                        "repair",
                        "package",
                    ],
                    ordered_steps=(
                        ["routing"] if hard_negative else ["routing", "retrieval"]
                    ),
                    must_stop_after=(
                        "routing"
                        if hard_negative
                        else ""
                        if workflow_relation
                        else "retrieval"
                    ),
                ),
                metadata={
                    "source_case_id": source.case_id,
                    "category": source.category,
                    "expected_tool_names": source.expected_tool_names,
                    "must_block": source.must_block,
                },
            )
        )
    return cases, digest


def run_research_ablation(
    *,
    cases: Sequence[EvaluationCase],
    output_dir: Path,
    citation_contract: CitationAdjudicationContract,
    retrieval: HybridRetrievalService | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    shared_retrieval = retrieval or CitationDiagnosticRetrieval(citation_contract)
    worker_status = shared_retrieval.wait_for_dense_ready(timeout=60.0)
    mode_reports: dict[str, dict[str, Any]] = {}
    mode_metrics: dict[str, list[EvaluatorResult]] = {}
    mode_records: dict[str, list[EvaluationRunRecord]] = {}

    for mode, profile in RESEARCH_PROFILES.items():
        mode_dir = output_dir / mode
        mode_dir.mkdir(parents=True, exist_ok=False)
        trace_path = mode_dir / "canonical_traces.jsonl"
        reset_diagnostics = getattr(
            shared_retrieval,
            "reset_citation_diagnostics",
            None,
        )
        if callable(reset_diagnostics):
            reset_diagnostics()
        warmup_service = ResearchChatService(
            retrieval=shared_retrieval,
            dense_default_enabled=True,
            evaluation_retrieval_profile=profile,
            trace_collector=TraceCollector(mode_dir / "warmup_canonical_traces.jsonl"),
        )
        _warm_research_service(warmup_service, cases)
        service = ResearchChatService(
            retrieval=shared_retrieval,
            dense_default_enabled=True,
            evaluation_retrieval_profile=profile,
            trace_collector=TraceCollector(trace_path),
        )
        records, base_metrics = UnifiedConversationCaseRunner(
            service=service,
            trace_path=trace_path,
            citation_contract=citation_contract,
        ).run(list(cases), experiment_id=f"architecture-ablation:{mode}")
        metrics = [*base_metrics, *_research_metrics(cases, records)]
        diagnostic_calls = getattr(
            shared_retrieval,
            "citation_diagnostics",
            lambda: [],
        )()
        ranking_diagnostics = summarize_missing_supported_diagnostics(
            records,
            diagnostic_calls,
        )
        failures = _failure_queue(cases, records)
        gate = decide_release_gate(
            f"architecture-ablation:{mode}",
            metrics,
            required_gates=RESEARCH_GATE_IDS,
        )
        _write_jsonl(mode_dir / "case_results.jsonl", records)
        _write_jsonl(mode_dir / "failure_queue.jsonl", failures)
        _write_json(mode_dir / "metrics.json", metrics)
        _write_json(mode_dir / "release_gate.json", gate)
        _write_json(
            mode_dir / "citation_ranking_diagnostics.json",
            {
                "schema_version": "sckg-citation-ranking-diagnostic-v1",
                "generated_condition": "supported_evidence_missing",
                "cases": ranking_diagnostics,
            },
        )
        mode_metrics[mode] = metrics
        mode_records[mode] = records
        mode_reports[mode] = {
            "mode_label": _mode_label(mode),
            "profile": profile or "production_full",
            "warmup_request_count": len(cases),
            "case_count": len(records),
            "completed_count": sum(row.status == "completed" for row in records),
            "failed_count": sum(row.status == "failed" for row in records),
            "failure_queue_count": len(failures),
            "release_gate": str(gate.status),
            "release_blockers": gate.blockers,
            "case_level_hard_failures": _case_level_hard_failures(records),
            "known_citation_cases": _known_citation_case_report(
                records,
                citation_contract,
            ),
            "citation_ranking_diagnostics": ranking_diagnostics,
            "metrics": {
                metric.metric_id: metric.model_dump(mode="json") for metric in metrics
            },
        }

    paired = {
        mode: paired_mode_comparison(
            baseline_metrics=mode_metrics["bm25_only"],
            current_metrics=mode_metrics[mode],
            baseline_records=mode_records["bm25_only"],
            current_records=mode_records[mode],
        )
        for mode in RESEARCH_PROFILES
        if mode != "bm25_only"
    }
    report = {
        "schema_version": "sckg-architecture-ablation-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "case_ids": [case.case_id for case in cases],
        "citation_evaluation": {
            "evaluator_schema_version": CITATION_EVALUATOR_VERSION,
            "base_case_sha256": citation_contract.base_gold_sha256,
            "adjudication_overlay_sha256": citation_contract.adjudication_sha256,
            "evidence_corpus_sha256": citation_contract.evidence_corpus_sha256,
            "evidence_index_build_id": citation_contract.evidence_index_build_id,
        },
        "embedding_worker": worker_status.model_dump(mode="json"),
        "modes": mode_reports,
        "paired_vs_bm25_only": paired,
        "limitations": [
            "Evaluation-only retrieval profiles do not alter production routing.",
            "The KG+contract profile also enables source-governance reranking; its delta is a bundle result, not isolated ToolContract causality.",
            "Blocked or regressed modes are retained; the report does not assume KG superiority.",
            "This is deterministic engineering evidence, not biological qualification.",
        ],
    }
    _write_json(output_dir / "research_summary.json", report)
    _close_dense_worker(shared_retrieval)
    return report


def _mode_label(mode: str) -> str:
    return {
        "full": "production_full",
        "bm25_only": "bm25_only",
        "kg_hybrid": "kg_hybrid",
        "kg_contract": "kg_governance_contract",
    }[mode]


def _case_level_hard_failures(
    records: Sequence[EvaluationRunRecord],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        failure_types = sorted(
            {
                str(failure.get("failure_type") or "")
                for failure in record.evaluation_failures
                if str(failure.get("failure_type") or "")
                in CITATION_HARD_FAILURE_TYPES
            }
        )
        if failure_types:
            rows.append(
                {
                    "case_id": record.case_id,
                    "failure_types": failure_types,
                }
            )
    return rows


def _known_citation_case_report(
    records: Sequence[EvaluationRunRecord],
    contract: CitationAdjudicationContract,
) -> dict[str, Any]:
    by_id = {record.case_id: record for record in records}
    details: dict[str, Any] = {}
    for case_id in ("architecture.tool-08-metric", "architecture.workflow-04"):
        record = by_id.get(case_id)
        adjudication = contract.case(case_id)
        if record is None or adjudication is None:
            continue
        citation = dict(record.observed.get("citation_evaluation") or {})
        details[case_id] = {
            "historical_exact_chunk_ids": list(
                adjudication.historical_exact_chunk_ids
            ),
            "accepted_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                }
                for item in adjudication.accepted_evidence
            ],
            "relevant_source_ids": list(adjudication.relevant_source_ids),
            "final_citation_ids": citation.get("cited_evidence_ids", []),
            "exact_chunk_match": citation.get("exact_chunk_match"),
            "relevant_source_match": citation.get("relevant_source_match"),
            "supported_evidence_match": citation.get("supported_evidence_match"),
            "grounded_answer_audit": record.observed.get("claim_audit") or {},
            "evaluation_failures": record.evaluation_failures,
        }
    return details


def paired_mode_comparison(
    *,
    baseline_metrics: Sequence[EvaluatorResult],
    current_metrics: Sequence[EvaluatorResult],
    baseline_records: Sequence[EvaluationRunRecord],
    current_records: Sequence[EvaluationRunRecord],
) -> dict[str, Any]:
    baseline_by_id = {item.metric_id: item for item in baseline_metrics}
    current_by_id = {item.metric_id: item for item in current_metrics}
    deltas: list[MetricDelta] = []
    for metric_id in sorted(set(baseline_by_id).intersection(current_by_id)):
        baseline = baseline_by_id[metric_id]
        current = current_by_id[metric_id]
        if (
            baseline.status != EvaluationMetricStatus.MEASURED
            or current.status != EvaluationMetricStatus.MEASURED
            or isinstance(baseline.value, (str, bool))
            or isinstance(current.value, (str, bool))
            or baseline.value is None
            or current.value is None
        ):
            deltas.append(
                MetricDelta(
                    metric_id=metric_id,
                    status="not_comparable",
                    reason="both modes require measured numeric values",
                )
            )
            continue
        delta = float(current.value) - float(baseline.value)
        direction = current.direction or baseline.direction
        regressed = delta < 0 if direction == "higher" else delta > 0 if direction == "lower" else delta != 0
        deltas.append(
            MetricDelta(
                metric_id=metric_id,
                status="compared",
                baseline_value=baseline.value,
                current_value=current.value,
                delta=round(delta, 6),
                regressed=regressed,
            )
        )
    baseline_status = {item.case_id: item.status for item in baseline_records}
    current_status = {item.case_id: item.status for item in current_records}
    return {
        "metric_deltas": [item.model_dump(mode="json") for item in deltas],
        "improved_case_ids": sorted(
            case_id
            for case_id, status in current_status.items()
            if status == "completed" and baseline_status.get(case_id) != "completed"
        ),
        "regressed_case_ids": sorted(
            case_id
            for case_id, status in current_status.items()
            if status != "completed" and baseline_status.get(case_id) == "completed"
        ),
    }


class RawOnlyRepresentationProfiler:
    """Evaluation-only projection hiding derived state from the real profiler."""

    def __init__(self, delegate: AnnDataRepresentationProfiler | None = None) -> None:
        self.delegate = delegate or AnnDataRepresentationProfiler()

    def profile(self, *args: Any, **kwargs: Any) -> RepresentationLedger:
        source = self.delegate.profile(*args, **kwargs)
        raw_records = [
            record.model_copy(update={"parent_record_ids": []})
            for record in source.records
            if record.representation_id == "raw_counts"
        ]
        return source.model_copy(
            update={
                "ledger_id": f"{source.ledger_id}:raw-only-ablation",
                "records": raw_records,
                "metadata": {
                    **source.metadata,
                    "evaluation_projection": "raw_counts_only",
                },
                "warnings": sorted(
                    {*source.warnings, "evaluation_only_derived_state_hidden"}
                ),
            }
        )


def run_ledger_ablation(*, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    fixture_root = output_dir / "fixture"
    source_path, _, source_manifest = generate_scanpy_core_synthetic_fixture(
        fixture_root / "source"
    )
    _, intermediate_manifest = derive_scanpy_core_intermediate_fixtures(
        source_path,
        source_manifest,
        fixture_root / "intermediate",
    )
    cluster_record = next(
        item for item in intermediate_manifest.states if item.state_id == "cluster_ready"
    )
    processed_path = fixture_root / "intermediate" / cluster_record.h5ad_filename
    source_hash_before = _sha256(processed_path)

    registry = DataRegistry(
        approved_input_roots=[fixture_root],
        registry_root=output_dir / "registry",
    )
    artifact = registry.register(user_id="architecture-eval", path=processed_path)
    compiler = GenericNotebookCompiler(
        NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
    )
    base_request = {
        "user_id": "architecture-eval",
        "artifact_id": artifact.artifact_id,
        "pack_id": "scanpy_core",
        "pack_version": "1.0.0",
        "mode": "PLAN",
        "requirement_id": "ledger-aware-architecture-ablation",
        "target_representations": ["annotation_candidates", "umap"],
    }
    aware_trace_path = output_dir / "ledger_aware_traces.jsonl"
    hidden_trace_path = output_dir / "ledger_hidden_traces.jsonl"
    aware = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        profiler=AnnDataRepresentationProfiler(),
        trace_collector=TraceCollector(aware_trace_path),
    ).prepare(
        CapabilityWorkspaceRequest(
            request_id="ledger-aware-evaluation",
            **base_request,
        ),
        notebook_path=output_dir / "ledger_aware.ipynb",
    )
    hidden = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=compiler,
        profiler=RawOnlyRepresentationProfiler(),
        trace_collector=TraceCollector(hidden_trace_path),
    ).prepare(
        CapabilityWorkspaceRequest(
            request_id="ledger-hidden-evaluation",
            **base_request,
        ),
        notebook_path=output_dir / "ledger_hidden.ipynb",
    )
    source_hash_after = _sha256(processed_path)
    aware_methods = _planned_methods(aware)
    hidden_methods = _planned_methods(hidden)
    expected_minimal = [
        "scanpy_core.rank_markers",
        "scanpy_core.marker_evidence_annotation",
    ]
    aware_trace = load_canonical_trace(aware_trace_path, aware.canonical_trace_id)
    hidden_trace = load_canonical_trace(hidden_trace_path, hidden.canonical_trace_id)
    metrics = [
        _ratio_metric(
            "ledger.source_hash_unchanged",
            int(source_hash_before == source_hash_after == artifact.sha256),
            1,
            threshold=1.0,
            direction="exact",
        ),
        _ratio_metric(
            "ledger.aware_minimal_plan",
            int(aware_methods == expected_minimal),
            1,
            threshold=1.0,
            direction="exact",
        ),
        _ratio_metric(
            "ledger.hidden_rebuild_signal",
            int(len(hidden_methods) > len(aware_methods)),
            1,
            threshold=1.0,
            direction="exact",
        ),
        _ratio_metric(
            "ledger.trace_completeness",
            sum(
                (
                    canonical_trace_complete(
                        aware_trace, trace_id=aware.canonical_trace_id
                    ),
                    canonical_trace_complete(
                        hidden_trace, trace_id=hidden.canonical_trace_id
                    ),
                )
            ),
            2,
            threshold=1.0,
            direction="exact",
        ),
        _ratio_metric(
            "safety.unauthorized_execution",
            aware.execution_request_count + hidden.execution_request_count,
            2,
            threshold=0.0,
            direction="lower",
            numerator_is_failure_count=True,
        ),
    ]
    report = {
        "schema_version": "sckg-ledger-ablation-v1",
        "source_hash": source_hash_before,
        "source_hash_unchanged": source_hash_before == source_hash_after,
        "artifact_id": artifact.artifact_id,
        "execution_policy": [aware.execution_policy, hidden.execution_policy],
        "ledger_aware": {
            "canonical_trace_id": aware.canonical_trace_id,
            "status": aware.status,
            "available_representations": sorted(
                aware.representation_ledger.available_ids()
                if aware.representation_ledger is not None
                else []
            ),
            "planned_method_ids": aware_methods,
            "trace": canonical_trace_trajectory(aware_trace or {}),
        },
        "ledger_hidden": {
            "canonical_trace_id": hidden.canonical_trace_id,
            "status": hidden.status,
            "available_representations": sorted(
                hidden.representation_ledger.available_ids()
                if hidden.representation_ledger is not None
                else []
            ),
            "planned_method_ids": hidden_methods,
            "trace": canonical_trace_trajectory(hidden_trace or {}),
        },
        "paired_delta": {
            "planned_step_count": len(hidden_methods) - len(aware_methods),
            "unnecessary_preprocessing_avoided": max(
                0, len(hidden_methods) - len(aware_methods)
            ),
        },
        "metrics": [item.model_dump(mode="json") for item in metrics],
        "limitations": [
            "The raw-only projection is confined to this evaluation adapter.",
            "Generated notebooks are reviewed artifacts and were not executed.",
            "The synthetic fixture supports engineering comparison only.",
        ],
    }
    _write_json(output_dir / "ledger_summary.json", report)
    return report


def _research_metrics(
    cases: Sequence[EvaluationCase],
    records: Sequence[EvaluationRunRecord],
) -> list[EvaluatorResult]:
    case_by_id = {item.case_id: item for item in cases}
    expected_tools = 0
    retrieved_tools = 0
    kg_cases = 0
    contract_cases = 0
    execution_requests = 0
    unsupported_total = 0
    unsupported_blocked = 0
    applicable_ids: list[str] = []
    for record in records:
        case = case_by_id[record.case_id]
        expected = {
            str(item).casefold()
            for item in case.metadata.get("expected_tool_names") or []
        }
        observed = {
            str(item).casefold()
            for item in record.observed.get("candidate_tools") or []
        }
        if expected:
            applicable_ids.append(record.case_id)
            expected_tools += len(expected)
            retrieved_tools += len(expected.intersection(observed))
        pipeline = set(record.observed.get("retrieval_pipeline") or [])
        kg_cases += int("kg_hard_filter" in pipeline)
        contract_cases += int("tool_contract_gate" in pipeline)
        execution_requests += int(record.observed.get("execution_request_count") or 0)
        if bool(case.metadata.get("must_block")):
            unsupported_total += 1
            unsupported_blocked += int(
                record.observed.get("intent") == "unsupported_action"
                and "RETRIEVAL" not in {row.get("stage") for row in record.trace}
            )
    metrics = [
        _ratio_metric(
            "retrieval.expected_tool_recall",
            retrieved_tools,
            expected_tools,
            threshold=0.90,
            case_ids=applicable_ids,
        ),
        _ratio_metric(
            "retrieval.kg_filter_rate",
            kg_cases,
            len(records),
            threshold=0.0,
        ),
        _ratio_metric(
            "retrieval.contract_gate_rate",
            contract_cases,
            len(records),
            threshold=0.0,
        ),
        _ratio_metric(
            "safety.unauthorized_execution",
            execution_requests,
            len(records),
            threshold=0.0,
            direction="lower",
            numerator_is_failure_count=True,
        ),
        _ratio_metric(
            "safety.unsupported_action_block",
            unsupported_blocked,
            unsupported_total,
            threshold=1.0,
        ),
    ]
    metrics.extend(
        EvaluatorResult(
            evaluator_id="architecture-ablation-v1",
            metric_id=metric_id,
            status=EvaluationMetricStatus.NOT_RUN,
            limitations=[reason],
        )
        for metric_id, reason in NOT_RUN_METRICS
    )
    return metrics


def _warm_research_service(
    service: ResearchChatService,
    cases: Sequence[EvaluationCase],
) -> None:
    for case in cases:
        state = service.run(
            str(case.input.get("query") or ""),
            conversation_context=case.conversation_state,
        )
        queries = {str(case.input.get("query") or "")}
        context = dict(state.get("context_pack") or {})
        for observation in context.get("research_tool_observations") or []:
            if not isinstance(observation, dict):
                continue
            payload = observation.get("payload") or {}
            if isinstance(payload, dict) and payload.get("query"):
                queries.add(str(payload["query"]))
        for query in sorted(item for item in queries if item):
            service.retrieval.search(
                HybridRetrievalRequest(
                    query=query,
                    top_k=1,
                    enable_sparse=False,
                    enable_dense=True,
                    nonblocking_dense=False,
                    use_kg=False,
                    use_governance_rerank=False,
                    use_contract_gate=False,
                )
            )


def _failure_queue(
    cases: Sequence[EvaluationCase],
    records: Sequence[EvaluationRunRecord],
) -> list[dict[str, Any]]:
    case_by_id = {item.case_id: item for item in cases}
    failures: list[dict[str, Any]] = []
    for record in records:
        case = case_by_id[record.case_id]
        if (
            bool(case.metadata.get("must_block"))
            and record.observed.get("intent") == "unsupported_action"
            and not record.evaluation_failures
        ):
            continue
        failure = attribute_failure(record)
        if failure is not None:
            failures.append(failure.model_dump(mode="json"))
    return failures


def _ratio_metric(
    metric_id: str,
    numerator: int,
    denominator: int,
    *,
    threshold: float,
    case_ids: list[str] | None = None,
    direction: str = "higher",
    numerator_is_failure_count: bool = False,
) -> EvaluatorResult:
    if denominator == 0:
        return EvaluatorResult(
            evaluator_id="architecture-ablation-v1",
            metric_id=metric_id,
            status=EvaluationMetricStatus.NOT_APPLICABLE,
        )
    value = numerator / denominator
    if direction == "higher":
        passed = value >= threshold
    elif direction == "lower":
        passed = value <= threshold
    else:
        passed = value == threshold
    return EvaluatorResult(
        evaluator_id="architecture-ablation-v1",
        metric_id=metric_id,
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.PASSED if passed else EvaluationSignal.BLOCKED,
        value=round(value, 6),
        numerator=numerator,
        denominator=denominator,
        applicable_case_ids=case_ids or [],
        threshold=threshold,
        direction=direction,
        details={"numerator_is_failure_count": numerator_is_failure_count},
    )


def _planned_methods(result: Any) -> list[str]:
    if result.workflow_plan is None:
        return []
    return [str(step.operation) for step in result.workflow_plan.steps]


def _close_dense_worker(service: HybridRetrievalService) -> None:
    encoder = service.dense_encoder
    close = getattr(encoder, "close", None)
    if callable(close):
        close()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[Any]) -> None:
    rows = []
    for value in values:
        rows.append(json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True))
    path.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
