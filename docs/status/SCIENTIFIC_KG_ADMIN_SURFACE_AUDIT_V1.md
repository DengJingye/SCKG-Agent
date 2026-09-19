# Scientific KG Admin Surface Audit V1

## Scope

This audit was completed before adding the read-only Scientific KG page. It maps the existing Streamlit admin surfaces to their real data owners so the new page does not rename, duplicate, or merge unrelated graph layers.

## Existing surfaces

| Surface | Current data owner | Current meaning | Reuse decision | Conflict avoided |
|---|---|---|---|---|
| Graph Explorer | `data/decision_graph_v3` plus the Legacy Tool KG catalog view | Decision-time action network, tool neighborhoods, and catalog discovery | Reuse the existing interactive graph renderer only | Keep the page titled Graph Explorer; do not present its Decision Graph/catalog counts as Scientific KG counts |
| Knowledge Review | Decision Graph v3 query, ActionBundles, Tool Dossiers, and governance quality | Review of governed action-space records and tool decision readiness | Preserve unchanged | Do not relabel this as scientific claim review |
| Evidence & RAG | Evidence dashboard, source registry, extraction status, and retrieval indexes | Retrieval/source operations and failures | Preserve unchanged; link concepts through source IDs only | Do not infer scientific claim trust from retrieval availability |
| Evaluation | Phase 6/system-quality evaluation artifacts | Release gates, test failures, and operational evaluation | Preserve unchanged; show only a small scKG-Eval context caption on the new page | Do not mix evaluation-suite counts with KG inventory totals |
| Architecture | Static implementation-status inventory | Product architecture and roadmap | Preserve unchanged | Do not use it as a live KG inventory |
| Scientific KG | Checkpoint-1 Scientific KG inventory snapshot and its four frozen candidate layers | Candidate scientific semantics, evidence bindings, readiness, and integrity | New read-only page with Overview, Scientific Graph, and Readiness & Integrity tabs | No mutation, promotion, ingestion, or execution controls |

## Required layer boundary

| Layer ID | Frozen size | Meaning | Counting rule |
|---|---:|---|---|
| `LEGACY_TOOL_KG` | 7,537 nodes / 17,667 edges | Tool catalog, publications, tasks, and retrieval source records | Report independently |
| `DECISION_GRAPH` | 1,058 nodes / 1,318 edges | Decision-time action, dossier, contract, and governance projection | Report independently |
| `SCIENTIFIC_KG` | 1,651 nodes / 2,429 edges | Candidate claims, scopes, representations, evidence, and scientific relations | Report independently |

The UI binding is `DO_NOT_SUM_ACROSS_LAYERS`. Cross-layer totals would combine different semantics and double-count overlapping identities.

## Reused implementation

- `engine.knowledge_graph_view.KnowledgeGraphView`, `GraphNode`, `GraphEdge`, and `build_knowledge_graph_html` render bounded Scientific KG subgraphs.
- Existing `_render_admin_header`, sidebar navigation, metric, table, and tab patterns keep the page inside the current app.
- Checkpoint-1 JSON artifacts remain the only source for counts, readiness, governance, and integrity.

## New boundary

`engine.scientific_kg_admin.ScientificKGAdminSnapshotService` exposes inspection only. It has no upload, extraction, review, promotion, merge, rejection, deletion, or update API. Source authority remains separate from claim governance: 380 candidate claims, 0 reviewed claims, and 0 trusted/canonical claims.
