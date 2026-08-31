from __future__ import annotations

from typing import Any, Sequence

from core.evaluation_models import EvaluationRunRecord
from core.knowledge_intelligence_models import (
    HybridRetrievalRequest,
    HybridRetrievalResult,
)
from engine.hybrid_retrieval import (
    HybridRetrievalService,
    _rrf,
    _tool_key,
)
from eval.citation_adjudication import CitationAdjudicationContract


class CitationDiagnosticRetrieval(HybridRetrievalService):
    """Evaluation-only observer for accepted-evidence ranks at real boundaries."""

    def __init__(
        self,
        citation_contract: CitationAdjudicationContract,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.citation_contract = citation_contract
        self._diagnostic_case_id = ""
        self._accepted_ids: set[str] = set()
        self._active_diagnostic: dict[str, Any] | None = None
        self._next_filter_stage = ""
        self._filtered_sparse: list[tuple[str, float]] = []
        self._filtered_dense: list[tuple[str, float]] = []
        self._diagnostic_calls: list[dict[str, Any]] = []

    def begin_citation_diagnostic_case(self, case_id: str) -> None:
        adjudication = self.citation_contract.case(case_id)
        self._diagnostic_case_id = case_id
        self._accepted_ids = (
            set(adjudication.accepted_evidence_ids) if adjudication is not None else set()
        )

    def end_citation_diagnostic_case(self) -> None:
        self._diagnostic_case_id = ""
        self._accepted_ids = set()

    def reset_citation_diagnostics(self) -> None:
        self._diagnostic_calls = []

    def citation_diagnostics(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._diagnostic_calls]

    def search(self, request: HybridRetrievalRequest) -> HybridRetrievalResult:
        if not self._diagnostic_case_id or not self._accepted_ids:
            return super().search(request)
        active: dict[str, Any] = {
            "case_id": self._diagnostic_case_id,
            "query": request.query,
            "request": {
                "tool_names": list(request.tool_names),
                "canonical_tasks": list(request.canonical_tasks),
                "claim_types": list(request.claim_types),
                "top_k": request.top_k,
                "enable_sparse": request.enable_sparse,
                "enable_dense": request.enable_dense,
                "use_kg": request.use_kg,
                "use_governance_rerank": request.use_governance_rerank,
                "use_contract_gate": request.use_contract_gate,
            },
            "accepted_evidence_ids": sorted(self._accepted_ids),
            "stages": {},
        }
        self._active_diagnostic = active
        self._next_filter_stage = ""
        self._filtered_sparse = []
        self._filtered_dense = []
        result: HybridRetrievalResult | None = None
        try:
            result = super().search(request)
            return result
        finally:
            fused = _rrf(self._filtered_sparse, self._filtered_dense)
            active["stages"].setdefault(
                "fusion",
                _accepted_rank_snapshot(fused, self._accepted_ids),
            )
            active["stages"].setdefault("governance_rerank", None)
            active["stages"]["contract_filter"] = {
                "requested": request.use_contract_gate,
                "implementation": (
                    "no_independent_chunk_filter_in_hybrid_retrieval"
                    if request.use_contract_gate
                    else "not_requested"
                ),
            }
            active["stages"]["final_top_k"] = (
                _accepted_rank_snapshot(
                    [(hit.chunk_id, hit.score) for hit in result.hits],
                    self._accepted_ids,
                )
                if result is not None
                else {}
            )
            active["first_divergence_by_evidence"] = {
                evidence_id: _first_divergence(active["stages"], evidence_id)
                for evidence_id in sorted(self._accepted_ids)
            }
            self._diagnostic_calls.append(active)
            self._active_diagnostic = None
            self._next_filter_stage = ""

    def _kg_candidates(
        self,
        *,
        task_ids: Sequence[str],
        explicit_tools: Sequence[str],
    ) -> tuple[set[str], str]:
        candidates, warning = super()._kg_candidates(
            task_ids=task_ids,
            explicit_tools=explicit_tools,
        )
        active = self._active_diagnostic
        if active is not None:
            matches: dict[str, bool | None] = {}
            for evidence_id in self._accepted_ids:
                chunk = self._chunks_by_id.get(evidence_id)
                chunk_tools = {
                    _tool_key(value)
                    for value in (chunk.tool_names or [chunk.tool_name])
                    if value
                } if chunk is not None else set()
                matches[evidence_id] = (
                    bool(candidates.intersection(chunk_tools))
                    if candidates and chunk_tools
                    else None
                )
            active["stages"]["kg_candidate_filter"] = {
                "candidate_tool_count": len(candidates),
                "accepted_tool_match": matches,
                "warning_present": bool(warning),
            }
        return candidates, warning

    def _bm25_search(self, query: str, *, limit: int) -> list[tuple[str, float]]:
        ranked = super()._bm25_search(query, limit=limit)
        if self._active_diagnostic is not None:
            self._active_diagnostic["stages"]["initial_bm25"] = (
                _accepted_rank_snapshot(ranked, self._accepted_ids)
            )
            self._next_filter_stage = "filtered_bm25"
        return ranked

    def _dense_search(
        self,
        query: str,
        *,
        limit: int,
        nonblocking: bool = False,
    ) -> tuple[list[tuple[str, float]], str]:
        ranked, status = super()._dense_search(
            query,
            limit=limit,
            nonblocking=nonblocking,
        )
        if self._active_diagnostic is not None:
            self._active_diagnostic["stages"]["initial_dense"] = {
                "status": status,
                "accepted_ranks": _accepted_rank_snapshot(
                    ranked,
                    self._accepted_ids,
                ),
            }
            self._next_filter_stage = "filtered_dense"
        return ranked, status

    def _filter_ranked(
        self,
        ranked: Sequence[tuple[str, float]],
        *,
        request: HybridRetrievalRequest,
        task_ids: set[str],
        candidate_tools: set[str],
    ) -> list[tuple[str, float]]:
        filtered = super()._filter_ranked(
            ranked,
            request=request,
            task_ids=task_ids,
            candidate_tools=candidate_tools,
        )
        if self._active_diagnostic is not None and self._next_filter_stage:
            self._active_diagnostic["stages"][self._next_filter_stage] = (
                _accepted_rank_snapshot(filtered, self._accepted_ids)
            )
            if self._next_filter_stage == "filtered_bm25":
                self._filtered_sparse = list(filtered)
            else:
                self._filtered_dense = list(filtered)
            self._next_filter_stage = ""
        return filtered

    def _governance_rerank(
        self,
        fused: Sequence[tuple[str, float, int | None, int | None]],
        *,
        request: HybridRetrievalRequest,
        task_ids: set[str],
        claim_types: set[str],
        candidate_tools: set[str],
    ) -> list[tuple[str, float, int | None, int | None]]:
        reranked = super()._governance_rerank(
            fused,
            request=request,
            task_ids=task_ids,
            claim_types=claim_types,
            candidate_tools=candidate_tools,
        )
        if self._active_diagnostic is not None:
            self._active_diagnostic["stages"]["fusion"] = (
                _accepted_rank_snapshot(fused, self._accepted_ids)
            )
            self._active_diagnostic["stages"]["governance_rerank"] = (
                _accepted_rank_snapshot(reranked, self._accepted_ids)
            )
        return reranked


def summarize_missing_supported_diagnostics(
    records: Sequence[EvaluationRunRecord],
    calls: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    calls_by_case: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        calls_by_case.setdefault(str(call.get("case_id") or ""), []).append(call)
    summaries: list[dict[str, Any]] = []
    for record in records:
        citation = dict(record.observed.get("citation_evaluation") or {})
        if citation.get("status") == "not_applicable" or citation.get(
            "supported_evidence_match"
        ):
            continue
        case_calls = calls_by_case.get(record.case_id, [])
        accepted_ids = {
            evidence_id
            for call in case_calls
            for evidence_id in call.get("accepted_evidence_ids") or []
        }
        cited_ids = set(citation.get("cited_evidence_ids") or [])
        present = {
            stage: {
                evidence_id
                for call in case_calls
                for evidence_id in _stage_rank_ids(call, stage)
            }
            for stage in (
                "initial_bm25",
                "initial_dense",
                "filtered_bm25",
                "filtered_dense",
                "fusion",
                "governance_rerank",
                "final_top_k",
            )
        }
        initial = present["initial_bm25"] | present["initial_dense"]
        filtered = present["filtered_bm25"] | present["filtered_dense"]
        if accepted_ids.intersection(cited_ids):
            disposition = "cited_but_mapping_or_evaluator_rejected"
        elif accepted_ids.intersection(present["final_top_k"]):
            disposition = "selected_but_not_cited"
        elif accepted_ids.intersection(filtered):
            disposition = "retrieved_then_ranked_out"
        elif accepted_ids.intersection(initial):
            disposition = "filtered_out"
        else:
            disposition = "never_retrieved"
        summaries.append(
            {
                "case_id": record.case_id,
                "accepted_evidence_ids": sorted(accepted_ids),
                "final_citation_ids": sorted(cited_ids),
                "disposition": disposition,
                "calls": case_calls,
            }
        )
    return summaries


def _accepted_rank_snapshot(
    ranked: Sequence[tuple[Any, ...]],
    accepted_ids: set[str],
) -> dict[str, int]:
    return {
        str(row[0]): rank
        for rank, row in enumerate(ranked, start=1)
        if str(row[0]) in accepted_ids
    }


def _stage_rank_ids(call: dict[str, Any], stage: str) -> set[str]:
    value = dict(call.get("stages") or {}).get(stage) or {}
    if stage == "initial_dense" and isinstance(value, dict):
        value = value.get("accepted_ranks") or {}
    return set(value) if isinstance(value, dict) else set()


def _first_divergence(stages: dict[str, Any], evidence_id: str) -> str:
    initial_dense = dict(stages.get("initial_dense") or {}).get(
        "accepted_ranks", {}
    )
    if evidence_id not in (stages.get("initial_bm25") or {}) and evidence_id not in initial_dense:
        return "initial_bm25_dense_candidates"
    if evidence_id not in (stages.get("filtered_bm25") or {}) and evidence_id not in (
        stages.get("filtered_dense") or {}
    ):
        return "request_or_kg_filter"
    if evidence_id not in (stages.get("fusion") or {}):
        return "fusion"
    governance = stages.get("governance_rerank")
    if isinstance(governance, dict) and evidence_id not in governance:
        return "governance_rerank"
    if evidence_id not in (stages.get("final_top_k") or {}):
        return "top_k_or_diversification"
    return "retained_by_retrieval_call"
