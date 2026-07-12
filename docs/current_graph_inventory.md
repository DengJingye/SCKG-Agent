# Current Graph Inventory

This file records what the current codebase actually creates or queries. It is intentionally separate from the target schema so that schema evolution remains explicit.

## Code Paths Inspected

- `data_pipeline/neo4j_loader.py`
- `data_pipeline/hybrid_loader.py`
- `script/init_mock_data.py`
- `connectors/graph_client.py`
- `engine/isomorphism_analyzer.py`
- `agent/workflow.py`

## Current Node Labels

| Label | Created By | Queried By | Current Purpose |
| --- | --- | --- | --- |
| `Tool` | `neo4j_loader.py`, `hybrid_loader.py`, `init_mock_data.py` | `graph_client.py`, `workflow.py`, `isomorphism_analyzer.py` | Software tools. |
| `Task` | `neo4j_loader.py`, `init_mock_data.py` | `graph_client.py` | Analysis task vocabulary. |
| `Modality` | `neo4j_loader.py`, `init_mock_data.py` | `graph_client.py` | Data modality vocabulary. |
| `Language` | `neo4j_loader.py` | not directly queried | Implementation language. |
| `Hardware` | `neo4j_loader.py` | not directly queried | Hardware requirements. |
| `Resolution` | `neo4j_loader.py` | not directly queried | Biological resolution. |
| `Algorithm` | `neo4j_loader.py`, `hybrid_loader.py` | `isomorphism_analyzer.py` | Algorithm feature text and embedding. |

## Current Relationship Types

| Relationship | From | To | Created By | Queried By | Purpose |
| --- | --- | --- | --- | --- | --- |
| `PERFORMS_TASK` | `Tool` | `Task` | `neo4j_loader.py`, `init_mock_data.py` | `graph_client.py` | Hard task matching. |
| `SUPPORTS_MODALITY` | `Tool` | `Modality` | `neo4j_loader.py`, `init_mock_data.py` | `graph_client.py` | Hard modality matching. |
| `WRITTEN_IN` | `Tool` | `Language` | `neo4j_loader.py` | not directly queried | Engineering metadata. |
| `REQUIRES_HARDWARE` | `Tool` | `Hardware` | `neo4j_loader.py` | not directly queried | Feasibility metadata. |
| `OPERATES_ON` | `Tool` | `Resolution` | `neo4j_loader.py` | not directly queried | Biological granularity. |
| `IMPLEMENTS_ALGORITHM` | `Tool` | `Algorithm` | `neo4j_loader.py`, `hybrid_loader.py` | `isomorphism_analyzer.py` | Algorithm migration retrieval. |
| `SUPPORTED_BY` | `Tool` | `Evidence` | `neo4j_loader.py`, `hybrid_loader.py`, `graph_client.py` | `graph_client.py`, `agent/workflow.py` | Auditable evidence binding. |

## Current Tool Properties

Observed in loaders and queries:

- `name`
- `description`
- `github_url`
- `github_stars`
- `license`
- `publish_year`
- `language` is queried in `agent/workflow.py`, but currently created as a `Language` node rather than a `Tool` property in the main loader.

## Current Algorithm Properties

- `name`
- `features`
- `embedding`

## Current Data Assets

| File | Role | Current Size |
| --- | --- | --- |
| `data/scrna_tools.tsv` | Raw single-cell tools catalog. | 1843 lines. |
| `data/scKG_embeddings_backup.jsonl` | Legacy LLM extraction and embedding backup. | 1698 records; use for exploratory recall only. |
| `data/evidence_candidates/algorithm_vector_audit.tsv` | Algorithm vector audit. | Catalog/vector coverage and profile quality flags. |
| `data/evidence_candidates/algorithm_vector_audit_summary.json` | Algorithm vector audit summary. | Current coverage: 1842 catalog rows, 1698 embedding rows, 0.9224 catalog coverage. |
| `data/evidence_candidates/core_tool_source_manifest_v2.tsv` | Core tool README/docs source manifest. | 18 rows: 16 core GitHub README rows plus 2 official docs fallback rows for MOFA2 and wot. |
| `data/evidence_candidates/core_tool_source_fetch_summary.json` | Core tool README/docs fetch summary. | 16 source texts fetched: 14 GitHub README texts and 2 official docs pages; 2 short README rows remain retrieval-skipped but covered by docs fallback. |
| `data/evidence_sources/text/core_docs/*.txt` | Local source text for core tool README/docs chunks. | 16 source text files. |
| `data/evidence_candidates/core_literature_source_coverage.tsv` | Paper/benchmark source coverage board. | 23 source rows; 19 source texts available, 4 missing. |
| `data/evidence_candidates/literature_source_coverage.tsv` | Alias for paper/benchmark source coverage board. | Same 23 tool-level source rows; includes dashboard status labels. |
| `data/evidence_candidates/core_literature_source_coverage_summary.json` | Paper/benchmark source coverage summary. | Manual queue has 4 rows: 2 Seurat extractor failures and 2 DOI/PDF mismatch rows; min source text length is 1000 chars. |
| `data/evidence_candidates/core_literature_manual_download_queue.md` | Literature source resolution queue. | Current unresolved rows are not download tasks: 2 wrong DOI/source rows and 2 Seurat PDF extraction failures. |
| `data/evidence_candidates/pdf_bad_candidate_overrides.tsv` | Known bad PDF candidate overrides. | Marks `10.1093/bib/bbad418` / `bbad418.pdf` as PanomiR mismatch for CellTypist and SingleR benchmark rows. |
| `data/evidence_candidates/source_registry.tsv` | Source-level literature registry. | 20 source records; 17 source texts available, 1 source metadata mismatch, 2 PDF extraction failures. |
| `data/evidence_candidates/pdf_candidate_registry.tsv` | PDF candidate validation/quarantine registry. | 35 candidate rows; 2 quarantined bbad418/PanomiR mismatch rows; quarantined rows have no target PDF path. |
| `data/evidence_candidates/source_validation_report.tsv` | Source-level validation report. | 1 `correct_doi_or_replace_source`, 2 `repair_extractor_or_use_html`, 17 `none`. |
| `data/evidence_candidates/source_acquisition_summary.json` | Source acquisition/validation summary. | Source-level counts, candidate quarantine counts, and download summary snapshot. |
| `data/evidence_candidates/source_extraction_summary.json` | Source extraction summary. | Source text availability, metadata mismatch, extraction failure, and ingest summary snapshot. |
| `data/evidence_candidates/source_pipeline_run_summary.json` | Literature source pipeline run log. | Offline v2.3 pipeline summary; records stage status and elapsed time without downloading PDFs by default. |
| `data/evidence_candidates/decision_workflow_demo_v1.json` | Decision workflow demo artifact. | PBMC multi-batch workflow demo; 7 plan-only steps, 35 snippets, 15 source-bound snippets, 0 formal main recommendation evidence. |
| `data/evidence_candidates/decision_workflow_demo_v1.tsv` | Step-level workflow demo table. | One row per workflow step with candidate tools, snippets, coverage, warnings, and plan-only status. |
| `data/evidence_candidates/decision_workflow_demo_v1.md` | Human-readable workflow demo note. | Markdown summary for the current decision-workflow product direction. |
| `eval/gold_workflow_scenarios_v0_1.jsonl` | Workflow planning gold eval set. | 8 scenarios covering workflow planning, doublet detection, spatial deconvolution, RNA velocity, multiome integration, object conversion, ambient RNA, and trajectory DE. |
| `eval/workflow_eval_v0_1_summary.json` | Workflow eval summary. | Current pass rate 1.0, step recall 0.982143, tool recall 1.0, unsupported step rate 0.0, evidence boundary violations 0. |
| `eval/workflow_eval_v0_1_per_scenario.tsv` | Per-scenario workflow eval results. | One row per scenario with generated steps, candidate tools, recall metrics, boundary checks, and missing terms. |
| `eval/workflow_eval_v0_1_failure_queue.tsv` | Workflow eval failure queue. | Empty except header when all scenarios pass; this is the repair queue when workflow behavior regresses. |
| `engine/workflow_decision.py` | Interactive workflow decision service. | Powers Dashboard Home / Chat sandbox; sample PBMC query produces 7 steps, 28 snippets, 18 source-bound snippets, 0 evidence boundary violations. |
| `app.py` | Unified Streamlit user/admin app. | User Chat + Knowledge Graph plus admin Evidence & RAG, Evaluation, Memory, and Architecture panels; chat can attach plan-only workflow decision cards. |
| `data/indexes/evidence_chunks.jsonl` | Local evidence discovery chunk index. | 819 chunks total: 28 formal publication, 14 formal benchmark, 451 PDF/HTML source, 326 core README/docs source. |
| `data/indexes/evidence_vectors.jsonl` | Local dense vector index. | 0 vectors; dense embedding has not been intentionally built yet. |
| `data/indexes/tool_representations_v2.jsonl` | Source-bound Algorithm Representation v2 index. | 1834 unique tool representations; migration/retrieval only. |
| `data/evidence_candidates/algorithm_representation_v2_audit.tsv` | Algorithm Representation v2 audit. | Source coverage, vector coverage, legacy flags, toolkit split flags. |
| `data/evidence_candidates/algorithm_representation_v2_summary.json` | Algorithm Representation v2 summary. | 16 tools with source chunks, 1818 low-source-coverage tools, 0 dense vectors. |
| `loader_log.out` | Historical loader execution log. | Local log file. |

## Current Inference Fields

The production workflow currently expects:

- `task`
- `modality`

These are extracted by `core/prompts.py` and consumed by `hard_constraint_node`.

The target intent schema should expand to:

- `task`
- `modality`
- `platform`
- `data_object`
- `scale`
- `noise`
- `hardware`
- `species`
- `output_goal`
- `strictness`

## Current Risks

- Evidence fields `citations` and `benchmark_rank` are placeholders in `mcdm_scoring_node`.
- `language` is queried as `t.language` but loaded as a `Language` node.
- No source, confidence, review status, or graph version metadata is attached to most graph facts.
- No `Evidence`, `Workflow`, `WorkflowStep`, or `DataScenario` labels exist yet.
- Legacy LLM-profile embeddings are retained only as recall/visualization/cluster exploration signals; they must not validate migration claims by themselves.
- Algorithm Representation v2 exists locally, but dense chunk vectors are not built yet; v2 output must keep `dense_embedding_missing` until `build_evidence_index.py --with-embeddings` is intentionally run.
- Core-16 source coverage is complete at the README/docs homepage level, but paper/protocol/benchmark source coverage is still incomplete.
- Paper/benchmark source coverage is 19/23 by strict text length; remaining gaps are 2 Seurat PDF extraction failures plus 2 known DOI/PDF mismatch benchmark rows.
- The `bbad418.pdf` candidate is a confirmed metadata mismatch and must not be saved under CellTypist/SingleR benchmark filenames.
- Source-level registry is now the authority for literature acquisition status; tool-level evidence rows may share a single source record.
- Decision workflow demo now demonstrates the target value proposition beyond a ranked recommendation report: step-level workflow planning, candidate tools, evidence snippets, code skeleton, and explicit evidence gaps.
- Workflow Eval v0.1 now guards the decision workflow direction with 8 gold scenarios. It validates workflow shape and evidence boundaries only; it does not certify biological correctness.
- Home / Chat now has a Workflow Decision Sandbox powered by `engine/workflow_decision.py`; it is plan-only and does not write Neo4j, formal TSV, memory, or MCDM rank.
- `app.py` now combines the original chat UI with admin views for Evidence/RAG, Evaluation, Memory, and Architecture. `observability/dashboard/app.py` remains useful as a separate debugging dashboard.
- Runtime config now has a single entry point in `core/settings.py`, but the tracked Git history still needs secret hygiene review.
- The app logo path has been moved to `Settings.logo_path`.

## Immediate Migration Checklist

- Add metadata fields during ingestion.
- Keep `.env.example` current and remove tracked real `.env` from future commits.
- Make `language` access consistent: either keep as node and query it through `WRITTEN_IN`, or also mirror it onto `Tool.language`.
- Replace MCDM placeholder fields with explicit missing evidence records until real evidence is available.
- Introduce workflow templates before adding more UI features.
- Add paper/protocol/benchmark source coverage for the core-16 set; README/docs homepage coverage is only the first layer.
- Resolve the 4-row literature queue: replace/fix Seurat PDFs or extractor path, and replace the CellTypist/SingleR benchmark DOI/source rows.
- Keep Algorithm Representation v2 exploratory until formal evidence and source-bound profiles are stronger.
- Expand Workflow Eval from 8 smoke scenarios to 20-30 richer scenarios with negative constraints, expected caveats, and ID-based retrieval precision/recall.
- Attach trace logging to the integrated workflow decision card and add a Run Trace panel inside `app.py`.
