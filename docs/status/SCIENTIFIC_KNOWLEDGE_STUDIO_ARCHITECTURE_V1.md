# Scientific Knowledge Studio Architecture v1

STATUS=FROZEN_FOR_CHECKPOINT_5A
MODE=preview_only

## Purpose

Scientific Knowledge Studio v1 turns exactly one local, text-extractable PDF into an evidence-bound Candidate Proposal preview. It does not ingest, review, promote, index, or authorize scientific knowledge.

```text
one local PDF
→ preview-scoped source identity
→ page-preserving segments
→ bounded EvidenceSpanProposal
→ semantic Proposal objects
→ identity resolution
→ ontology/evidence/governance validation
→ CandidateDiff + Proposal Graph + Run Manifest
```

## Single orchestration owner

`engine/scientific_knowledge_studio.ScientificKnowledgeStudioService` owns orchestration and run-scoped artifact persistence. It composes existing components and narrow adapters. It has no method for canonical KG mutation, promotion, ReviewDecision persistence, production RAG indexing, or Planner behavior.

The service writes only beneath `data/runtime/scientific_knowledge_studio/<run_id>/` unless a test or explicit freeze output directory is supplied. The midterm evaluation snapshot contains bounded proposal records and hashes; it excludes the PDF binary and full PDF text.

## Reused components

| Capability | Existing owner | Studio use |
|---|---|---|
| Frozen KG counts and identity candidates | `engine/scientific_kg_admin.ScientificKGAdminSnapshotService` | Read current counts and resolve exact IDs/labels without mutation |
| PDF extraction implementation | `data_pipeline.ingest_evidence_pdfs.extract_with_pypdf` | Called through a page-preserving adapter; no OCR or Ghostscript fallback |
| Scientific schema vocabulary | `core.scientific_knowledge_conformance_models` and the frozen Scientific KG snapshot | Load allowed entity types and predicates at runtime |
| Section/paragraph concepts | `engine.source_corpus_v2` | Reuse the page/section/paragraph segmentation policy as an adapter, without rebuilding indexes |
| Candidate identity/deposit boundary | SoupX candidate-deposition pilot | Preserve deterministic IDs, candidate-only status, isolated artifacts, and retrieval exclusion |
| Trace principles | `core.trace_context` | RunManifest stages carry bounded references, status, reasons, and hashes; no new Canonical Trace enum is introduced |
| Graph rendering | `engine.knowledge_graph_view` | Render a bounded run graph in the existing Admin · Scientific KG workspace |

## Generic adapters added in this checkpoint

- `PagePreservingPDFAdapter`: reads pages with the repository parser implementation, records parser package version, emits deterministic bounded segments, and records `PARSE_GAP` rather than hiding failures.
- `EvidenceProposalBuilder`: selects exact bounded source text and validates offsets, page, segment, source revision, and PDF hash.
- `OntologyRegistry`: derives entity types, predicates, and observed endpoint pairs from the current Scientific KG snapshot at runtime.
- `LocalOntologyProposalExtractor`: deterministic, evidence-bound fallback that proposes exact existing identities and conservative document/package candidates. It does not impersonate an LLM.
- `StructuredLLMProposalExtractor`: optional dependency-injected extractor using the existing authorized runtime. It accepts strict JSON only, has bounded retry, records reproducibility metadata, and never writes outside the run.
- `ScientificIdentityResolver`: exact canonical ID, exact API path, exact normalized label, governed alias, and package-constrained lookup only. It never auto-merges by fuzzy or embedding similarity.
- `ProposalValidator`: separate schema, evidence, identity, and governance checks.

## Proposal object ownership

Checkpoint 4 found no safe authoritative persistence owner for SourceWork, SourceRevision, EvidenceSpan, candidate status, or promotion state. Studio therefore owns only preview wrappers in `core.scientific_knowledge_studio_models`:

| Object | Owner in v1 | Relationship to existing model |
|---|---|---|
| `SourceRevisionProposal` | Studio models | Preview wrapper; does not claim to be canonical SourceRevision |
| `EvidenceSpanProposal` | Studio models | Exact-text proposal; does not replace Scientific KG layer JSONL or `EvidenceChunk` |
| `EntityProposal` | Studio models | Constrained by entity types loaded from the current snapshot |
| `RelationProposal` | Studio models | Constrained by predicates and endpoint pairs loaded from the current snapshot |
| `AtomicClaimProposal` | Studio models | Candidate wrapper that may later adapt to `AtomicClaimRevision` after review design |
| `ScopeProposal` | Studio models | Uses explicit/document-context/unspecified/ambiguous dimension states |
| `CandidateDiff` | Studio models | Preview arithmetic only |
| `KnowledgeStudioRunManifest` | Studio models | Run-scoped process record; not a Canonical Trace replacement |

Every scientific proposal has `proposal_status=candidate_proposal`. Pydantic literal validation rejects `reviewed`, `trusted`, and `canonical`.

## Scientific KG mutation boundary

The Studio reads these assets and verifies their before/after hashes:

- Scientific KG physical layers and inventory graph
- Legacy KG
- Decision Graph
- retrieval corpus and indexes
- Planner code
- benchmark gold
- ToolContracts and Capability Packs

It does not call `data_pipeline/neo4j_loader.py`, legacy promotion scripts, index builders, Planner services, or any ReviewDecision backend. Proposal artifacts are excluded from production retrieval. UI copy always says “If accepted, proposed delta would be…” and never claims that KG nodes were added.

## Deliberately absent in v1

- Candidate KG staging or production deposit
- ReviewDecision, keep/reject/merge/supersede actions
- canonical promotion, immutable promotion snapshots, or rollback
- production RAG indexing or Planner consumption
- OCR, tables, figures, multi-PDF, URL crawling, authenticated sources, DOCX, HTML, or supplementary archives
- fuzzy embedding identity merge
- Canonical Trace Explorer or new trace stage enums
- Ingestion-Eval and external benchmark work

## Real-run policy

The first real run uses the already-local authoritative SoupX 1.6.2 manual because it is legally/local available, text-extractable, method-relevant, and already provenance-checked by the SoupX pilot. The PDF remains byte-identical and outside the committed Studio snapshot. If an authorized LLM configuration is unavailable, the run records `REAL_LLM_EXTRACTION=NOT_RUN`; deterministic proposals remain explicitly labeled as local ontology extraction and are not presented as model output.
