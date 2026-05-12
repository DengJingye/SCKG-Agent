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
| `data/scKG_embeddings_backup.jsonl` | LLM extraction and embedding backup. | 1698 records. |
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
- Algorithm migration uses semantic embedding similarity only; it does not yet check structured compatibility.
- Runtime config now has a single entry point in `core/settings.py`, but the tracked Git history still needs secret hygiene review.
- The app logo path has been moved to `Settings.logo_path`.

## Immediate Migration Checklist

- Add metadata fields during ingestion.
- Keep `.env.example` current and remove tracked real `.env` from future commits.
- Make `language` access consistent: either keep as node and query it through `WRITTEN_IN`, or also mirror it onto `Tool.language`.
- Replace MCDM placeholder fields with explicit missing evidence records until real evidence is available.
- Introduce workflow templates before adding more UI features.
