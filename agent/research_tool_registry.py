from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.knowledge_intelligence_models import (
    HybridRetrievalRequest,
    HybridRetrievalResult,
)
from core.research_agent_models import (
    ResearchToolCall,
    ResearchToolObservation,
    ResearchToolPlan,
)
from core.tool_contract_registry import ToolContractRegistry
from core.capability_pack_registry import CapabilityPackRegistry
from engine.hybrid_retrieval import HybridRetrievalService
from engine.workflow_code_service import WorkflowCodeService


@dataclass
class ResearchToolExecution:
    observations: list[ResearchToolObservation] = field(default_factory=list)
    retrieval_results: list[HybridRetrievalResult] = field(default_factory=list)
    contract_context: list[dict[str, Any]] = field(default_factory=list)
    workflow_bundles: list[dict[str, Any]] = field(default_factory=list)
    capability_context: list[dict[str, Any]] = field(default_factory=list)

    @property
    def retrieval(self) -> HybridRetrievalResult | None:
        return _merge_retrieval_results(self.retrieval_results)


class ResearchToolRegistry:
    """Execute only maintained, read-only Research Chat tools.

    This registry deliberately has no shell, installer, executor, or evidence-write
    capability. Tool proposals come from the LLM; authority remains in local code.
    """

    def __init__(
        self,
        *,
        retrieval: HybridRetrievalService,
        contracts: ToolContractRegistry | None = None,
        workflow_code: WorkflowCodeService | None = None,
        capability_packs: CapabilityPackRegistry | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.contracts = contracts or ToolContractRegistry()
        self.workflow_code = workflow_code or WorkflowCodeService()
        self.capability_packs = capability_packs or CapabilityPackRegistry()

    def execute(
        self,
        plan: ResearchToolPlan,
        *,
        fallback_query: str,
        fallback_task: str,
        enable_dense: bool,
        use_kg: bool,
        use_governance_rerank: bool,
        use_contract_gate: bool,
    ) -> ResearchToolExecution:
        result = ResearchToolExecution()
        for call in plan.calls:
            started = time.perf_counter()
            try:
                if call.tool_name in {"search_catalog", "search_evidence"}:
                    retrieval = self._search(
                        call,
                        fallback_query=fallback_query,
                        fallback_task=fallback_task,
                        enable_dense=enable_dense,
                        use_kg=use_kg,
                        use_governance_rerank=use_governance_rerank,
                        use_contract_gate=use_contract_gate,
                    )
                    result.retrieval_results.append(retrieval)
                    result.observations.append(
                        ResearchToolObservation(
                            call_id=call.call_id,
                            tool_name=call.tool_name,
                            status="completed",
                            result_count=len(retrieval.hits),
                            source_bound_count=sum(
                                hit.source_bound for hit in retrieval.hits
                            ),
                            latency_ms=_elapsed_ms(started),
                            payload={
                                "mode": retrieval.mode,
                                "query": retrieval.query,
                                "chunk_ids": [hit.chunk_id for hit in retrieval.hits],
                            },
                            warnings=retrieval.warnings,
                        )
                    )
                elif call.tool_name == "get_tool_contract":
                    contracts = self._contract_context(
                        call.tool_names,
                        task=call.canonical_task or fallback_task,
                    )
                    result.contract_context.extend(contracts)
                    result.observations.append(
                        ResearchToolObservation(
                            call_id=call.call_id,
                            tool_name=call.tool_name,
                            status="completed" if contracts else "blocked",
                            result_count=len(contracts),
                            source_bound_count=len(contracts),
                            latency_ms=_elapsed_ms(started),
                            payload={"contracts": contracts},
                            warnings=([] if contracts else ["matching_tool_contract_missing"]),
                        )
                    )
                elif call.tool_name == "compile_workflow":
                    task = call.canonical_task or fallback_task
                    bundle = self.workflow_code.get_bundle(
                        task_id=task,
                        preferred_tool=(call.tool_names[0] if call.tool_names else None),
                    )
                    payload = bundle.model_dump(mode="json")
                    result.workflow_bundles.append(payload)
                    result.observations.append(
                        ResearchToolObservation(
                            call_id=call.call_id,
                            tool_name=call.tool_name,
                            status="completed",
                            result_count=1,
                            latency_ms=_elapsed_ms(started),
                            payload={
                                "task_id": task,
                                "bundle_id": payload.get("bundle_id"),
                                "smoke_status": payload.get("smoke_status"),
                            },
                        )
                    )
                elif call.tool_name == "discover_capabilities":
                    capabilities = self._capability_context(
                        task=call.canonical_task or fallback_task,
                        query=call.query or fallback_query,
                    )
                    result.capability_context.extend(capabilities)
                    result.observations.append(
                        ResearchToolObservation(
                            call_id=call.call_id,
                            tool_name=call.tool_name,
                            status="completed" if capabilities else "blocked",
                            result_count=len(capabilities),
                            latency_ms=_elapsed_ms(started),
                            payload={"capabilities": capabilities},
                            warnings=(
                                []
                                if capabilities
                                else ["matching_capability_pack_missing"]
                            ),
                        )
                    )
            except Exception as exc:
                result.observations.append(
                    ResearchToolObservation(
                        call_id=call.call_id,
                        tool_name=call.tool_name,
                        status="blocked",
                        latency_ms=_elapsed_ms(started),
                        warnings=[f"{type(exc).__name__}:{str(exc)[:240]}"],
                    )
                )
        return result

    def _search(
        self,
        call: ResearchToolCall,
        *,
        fallback_query: str,
        fallback_task: str,
        enable_dense: bool,
        use_kg: bool,
        use_governance_rerank: bool,
        use_contract_gate: bool,
    ) -> HybridRetrievalResult:
        return self.retrieval.search(
            HybridRetrievalRequest(
                query=call.query or fallback_query,
                tool_names=call.tool_names,
                canonical_tasks=[call.canonical_task or fallback_task]
                if call.canonical_task or fallback_task
                else [],
                claim_types=call.claim_types,
                top_k=call.top_k,
                include_catalog=call.tool_name == "search_catalog",
                enable_dense=enable_dense,
                nonblocking_dense=True,
                use_kg=use_kg,
                use_governance_rerank=use_governance_rerank,
                use_contract_gate=(
                    use_contract_gate and call.tool_name == "search_evidence"
                ),
            )
        )

    def _contract_context(
        self,
        tool_names: Iterable[str],
        *,
        task: str,
    ) -> list[dict[str, Any]]:
        requested = {name.casefold() for name in tool_names if name}
        rows: list[dict[str, Any]] = []
        for contract in self.contracts.load_all():
            if requested and contract.tool_name.casefold() not in requested:
                continue
            if task and contract.task != task:
                continue
            planning = self.contracts.planning_gate(contract)
            execution = self.contracts.execution_gate(contract)
            rows.append(
                {
                    "contract_id": contract.contract_id,
                    "tool_name": contract.tool_name,
                    "tool_version": contract.tool_version,
                    "task": contract.task,
                    "input_object": contract.input_object,
                    "default_parameters": contract.default_parameters,
                    "searchable_parameters": contract.searchable_parameters,
                    "output_artifacts": [
                        artifact.model_dump(mode="json")
                        for artifact in contract.output_artifacts
                    ],
                    "planning_allowed": planning.allowed,
                    "planning_blockers": planning.reasons,
                    "contract_execution_gate_allowed": execution.allowed,
                    "execution_blockers": execution.reasons,
                    "does_not_authorize_execution": True,
                    "requires_plan_specific_approval": True,
                    "source_refs": contract.source_refs,
                    "scientific_validation_status": contract.scientific_validation_status,
                }
            )
        return rows[:5]

    def _capability_context(
        self,
        *,
        task: str,
        query: str,
    ) -> list[dict[str, Any]]:
        terms = {term.casefold() for term in [task, *query.replace("/", " ").split()] if term}
        rows: list[dict[str, Any]] = []
        for manifest in self.capability_packs.load_all():
            gate = self.capability_packs.gate(manifest)
            non_human_consumed = {
                requirement.representation_id
                for method in manifest.methods
                if method.implementation_kind != "human_review"
                for requirement in method.consumes
            }
            suggested_targets = list(manifest.workspace_targets) or sorted(
                {
                    production.representation_id
                    for method in manifest.methods
                    if method.implementation_kind != "human_review"
                    for production in method.produces
                    if production.representation_id not in non_human_consumed
                }
            )
            for capability in manifest.capabilities:
                searchable = {
                    manifest.pack_id.casefold(),
                    *[item.casefold() for item in manifest.task_families],
                    capability.capability_id.casefold(),
                    capability.task_family.casefold(),
                    *capability.title.casefold().split(),
                }
                if terms and not any(
                    term == value
                    or (len(term) >= 4 and term in value)
                    or (len(value) >= 4 and value in term)
                    for term in terms
                    for value in searchable
                ):
                    continue
                rows.append(
                    {
                        "pack_id": manifest.pack_id,
                        "pack_version": manifest.pack_version,
                        "capability_id": capability.capability_id,
                        "capability_title": capability.title,
                        "task_family": capability.task_family,
                        "method_ids": [
                            item.method_id
                            for item in manifest.methods
                            if item.capability_id == capability.capability_id
                        ],
                        "suggested_workspace_targets": suggested_targets,
                        "readiness": [str(item) for item in gate.readiness],
                        "execution_eligible": gate.execution_eligible,
                        "blockers": gate.blockers,
                    }
                )
        return rows[:12]


def _merge_retrieval_results(
    results: list[HybridRetrievalResult],
) -> HybridRetrievalResult | None:
    if not results:
        return None
    if len(results) == 1:
        return results[0]
    by_chunk: dict[str, Any] = {}
    for result in results:
        for hit in result.hits:
            previous = by_chunk.get(hit.chunk_id)
            if previous is None or hit.score > previous.score:
                by_chunk[hit.chunk_id] = hit
    hits = sorted(by_chunk.values(), key=lambda hit: (-hit.score, hit.chunk_id))[:12]
    first = results[0]
    return HybridRetrievalResult(
        query=" | ".join(dict.fromkeys(result.query for result in results)),
        mode=first.mode,
        hits=hits,
        latency_ms=round(sum(result.latency_ms for result in results), 3),
        index_build_id=first.index_build_id,
        embedding_model=next(
            (result.embedding_model for result in results if result.embedding_model),
            "",
        ),
        dense_status=(
            "ready" if any(result.dense_status == "ready" for result in results)
            else first.dense_status
        ),
        pipeline=list(
            dict.fromkeys(
                step for result in results for step in [*result.pipeline, "tool_plan_fusion"]
            )
        ),
        warnings=list(dict.fromkeys(w for result in results for w in result.warnings)),
        governance_leakage_count=sum(
            result.governance_leakage_count for result in results
        ),
        stage_timings=[timing for result in results for timing in result.stage_timings],
        scientific_evidence=(
            {"queries": [result.scientific_evidence for result in results if result.scientific_evidence is not None],
             "final_graph_chunk_ids": sorted({hit.chunk_id for hit in hits} & {
                 cid for result in results if result.scientific_evidence is not None
                 for cid in result.scientific_evidence.get("final_graph_chunk_ids", [])})}
            if any(result.scientific_evidence is not None for result in results) else None
        ),
    )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)
