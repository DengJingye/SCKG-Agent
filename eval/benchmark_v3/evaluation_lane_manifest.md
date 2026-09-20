# Phase 2.2 Evaluation Lane Manifest

Baseline truth: 07 integration commit `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`.

This is a configuration freeze, not a four-lane run. No LLM, Research Chat lane, DEV/Gold,
or Agent Gain evaluation was invoked.

| lane | backend / entry point | corpus or snapshot | retrieval | graph channels | caution policy |
| --- | --- | --- | --- | --- | --- |
| `llm_only` | engine.approved_scientific_kg.GovernedChatRetrieval (no-retrieval branch)<br>agent.research_runtime.build_chat_retrieval -> engine.approved_scientific_kg.GovernedChatRetrieval.search | none<br>{} | {"enable_dense": false, "enable_sparse": false, "include_catalog": "call.tool_name == search_catalog; fallback/supplemental false", "maximum_returned_hits": 0, "sparse_candidate_limit": 0, "top_k": "incoming request may vary; no-retrieval backend returns zero hits", "use_contract_gate": false, "use_governance_rerank": false, "use_kg": false, "use_scientific_evidence": false} | disabled | no local caution channel |
| `generic_rag` | engine.hybrid_retrieval.HybridRetrievalService<br>agent.research_runtime.build_chat_retrieval -> engine.approved_scientific_kg.GovernedChatRetrieval.search | retrieval-foundation-v1-ff5b4829bc5943f4<br>{"catalog_chunks_sha256": "d6d9f077d5fe8d0cace35ecc91c709038b7944a42e36122a4d32d795b6b080bc", "corpus_digest": "8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436", "evidence_chunks_sha256": "552df8b572e5db342a27fc7de5c69adce6806ca22a2194333b0e92c01a1c3ece", "fts_sha256": "288241ab4072b5aaca31dab68cd8ffbb00c161a4d946ab5b341f0582e09c6808", "manifest_sha256": "0afc019e7c4cb5b52ea89dbccdb70b2d1e40cf3100efbd4562e0966d2a78d92a"} | {"enable_dense": false, "enable_sparse": true, "include_catalog": "call.tool_name == search_catalog; fallback/supplemental false", "sparse_candidate_limit": "max(request.top_k * 12, 120)", "top_k": "per request (tool call.top_k); fallback 12; supplemental 4", "use_contract_gate": false, "use_governance_rerank": false, "use_kg": false, "use_scientific_evidence": false} | disabled (use_kg=false; scientific evidence adapter disabled) | no Scientific KG caution context |
| `legacy_kg` | engine.hybrid_retrieval.HybridRetrievalService + engine.scientific_kg_evidence.ScientificKGEvidence + engine.evidence_graph_query.EvidenceGraphQuery<br>agent.research_runtime.build_chat_retrieval -> engine.approved_scientific_kg.GovernedChatRetrieval.search | retrieval-foundation-v1-ff5b4829bc5943f4 + scientific_kg_v1_uat_decision_rules + kg-v2.3.0-canonical:6b20b21847be<br>{"candidate_bindings_sha256": "b9b77442968a705787b77c2b1a74c094d9a7223bd7d3eeebc7e028954c66c76f", "candidate_bundle_sha256": "5e6b41d61cdd4204f4ebea6125be302fb981dd6e104cc883f21dbc3e6eec41c2", "candidate_manifest_sha256": "f5272f1e69c5766a069ca3dd6565d90b323ccdf7a3944a987bd0cba5409ef638", "catalog_chunks_sha256": "d6d9f077d5fe8d0cace35ecc91c709038b7944a42e36122a4d32d795b6b080bc", "legacy_inventory_sha256": "9a6da2e3981bbeddd5654d3f59b766bdc55d805ba52dec9beaead90294cdb138", "legacy_tool_graph_edges_sha256": "20298de3f0754723650045f2cc6697e24f9b956dc134bf178d267e424bf51213", "legacy_tool_graph_nodes_sha256": "6b20b21847be6f472a537d7e79ac30d3df18a07f42616bfd7655603b31ee10c3", "retrieval_corpus_digest": "8d8990ec75f25c598f467b0da0ca2ad81ce9f0931efadff7f70acec4b7a47436"} | {"enable_dense": false, "enable_sparse": true, "include_catalog": "call.tool_name == search_catalog; fallback/supplemental false", "sparse_candidate_limit": "max(request.top_k * 12, 120)", "top_k": "per request (tool call.top_k); fallback 12; supplemental 4", "use_contract_gate": false, "use_governance_rerank": false, "use_kg": true, "use_scientific_evidence": true} | candidate ScientificKGEvidence direct-evidence channel enabled; 7,537-node legacy tool/catalog graph enabled only for candidate-tool filtering | candidate-only evidence-gap diagnostics may abstain; no approved-v2 caution context |
| `scientific_kg` | engine.approved_scientific_kg.ApprovedScientificKG<br>agent.research_runtime.build_chat_retrieval -> engine.approved_scientific_kg.GovernedChatRetrieval.search | approved-scientific-kg-v2-01<br>{"approved_kg_sha256": "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4", "caution_context_index_sha256": "5e782d1a21ceb0789afc2392c901556f24ba763ca6a39a55052c0e3be5805062", "package_commit": "6018699092d979a2da0dda45a19c920018ed9eda"} | {"algorithm": "approved exact-evidence in-memory ranking", "generic_dense_consumer_used": false, "generic_sparse_consumer_used": false, "legacy_kg_used": false, "maximum_approved_facts": 12, "maximum_caution_contexts": 4, "top_k": "per request; approved facts capped at min(request.top_k, 12)"} | approved allowlist, evidence-chain joins, exact scope policy, and separate caution context; generic RAG and both legacy graphs are not consulted | {"count": 166, "execution_authorized": false, "execution_gate": false, "production_retrieval_eligible": false, "scientific_assertion": false, "trusted": false} |

## Shared runtime exclusion

Planner, ToolContracts, execution guards, validation contracts, and approval system are common infrastructure. Their records and behavior cannot establish any V2, Legacy, or RAG coverage bit and cannot be reported as Scientific KG gain.

| component | implementation binding | coverage treatment |
| --- | --- | --- |
| `Planner` | agent.research_chat_service.ResearchChatService tool-plan path | shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage |
| `ToolContracts` | contracts/tools plus shared research/execution services | shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage |
| `execution guards` | shared execution policy, authorization, and runtime guards | shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage |
| `validation contracts` | shared artifact and result validation contracts | shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage |
| `approval system` | shared plan-specific approval and approval-consumption path | shared infrastructure; excluded from V2/Legacy/RAG knowledge coverage |

## Approved-v2 consumer invariants

- Approved snapshot SHA256: `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`.
- Visible approved statements: 121; direct assessment bindings: 134.
- Evidence chain: Statement → Assessment → EvidenceSpan → SourceRevision.
- Scope qualifiers remain explicit; mismatches exclude and missing conditions remain unknown.
- Caution contexts: 166, separate and non-assertive.
- Held statement `statement-revision:d0d887b96b7a1cf45e2c47bf:1` is not visible.
