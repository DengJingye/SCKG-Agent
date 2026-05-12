# scKG-Atlas Graph Schema

This document defines the target schema for scKG-Atlas as a graph-driven decision system for single-cell and multi-omics analysis. The schema is designed for correctness, maintainability, evidence traceability, and future workflow reasoning.

## Scope

The system accepts research constraints and returns one of four output types:

- Directly usable tools.
- Executable workflows.
- Algorithm migration suggestions.
- Evidence chains supporting or limiting the recommendation.

The system does not replace human experimental judgement, does not invent unsupported conclusions, and must distinguish direct evidence from weak or exploratory evidence.

## Standard Metadata

Every durable node should carry these fields where possible:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Canonical display name. |
| `source_url` | string | recommended | URL of the primary source. |
| `source_type` | enum | recommended | `manual`, `scrna-tools`, `github`, `paper`, `benchmark`, `llm_extracted`, `derived`. |
| `extraction_method` | string | recommended | Manual curation, crawler name, model name, or script name. |
| `extraction_time` | datetime | recommended | When the fact was created or refreshed. |
| `confidence` | float | recommended | 0.0 to 1.0 confidence score. |
| `trust_level` | enum | recommended | `verified`, `source_based`, `model_extracted`, `inferred`, `missing`. |
| `graph_layer` | enum | recommended | `trusted_core`, `review_needed`, `experimental`. |
| `use_for` | list[string] | recommended | Allowed uses such as `retrieval`, `ranking`, `recommendation`, `report`. |
| `review_status` | enum | recommended | `unreviewed`, `auto_checked`, `human_reviewed`, `rejected`. |
| `kg_version` | string | recommended | Knowledge graph release or batch version. |

## Trust Layers

The graph is not a single truth store. It is split into trust layers so weak signals cannot become final conclusions.

| Layer | Allowed content | Allowed use |
| --- | --- | --- |
| `trusted_core` | Human-reviewed facts, GitHub metadata, benchmark/paper evidence, official documentation claims. | Retrieval, ranking, recommendation, report. |
| `review_needed` | Source-based but not yet manually reviewed facts. | Retrieval and provisional ranking with explicit uncertainty. |
| `experimental` | LLM-extracted claims, embeddings, algorithm similarity, migration suggestions, synthetic workflow templates. | Candidate recall and exploratory analysis only. |

Evidence must also carry `trust_level`. `model_extracted` and `inferred` evidence must not be treated as recommendation-grade evidence unless promoted by review.

## Publication Evidence Governance V2

Publication curation separates formal ingestion from recommendation authority.

`decision=formalize` means a human-reviewed record may enter `data/tool_publications.tsv`. It does not mean the record may enter the main recommendation context. Recommendation eligibility is controlled separately by `recommendation_eligible`, `canonical_scope`, `evidence_category`, and `authority_tier`.

Strategy A is the default policy:

| `canonical_scope` | `authority_tier` | Formal evidence | Main recommendation |
| --- | --- | --- | --- |
| `core_tool` | `canonical_primary` | yes | yes |
| `major_version` | `canonical_secondary` | yes | yes, lower priority than `canonical_primary` |
| `ecosystem_component` | `ecosystem_support` | yes | no |
| `workflow_protocol` | `contextual_support` | supporting only | no |
| `non_canonical` | `contextual_support` | supporting only | no |
| `provenance_only` | `provenance_only` | provenance only | no |
| `manual_anchor_required` | `manual_required` | no formal paper row until anchored | no |

The primary recommendation gate must require all of the following for paper evidence:

- `recommendation_eligible=true`
- `canonical_scope in {"core_tool", "major_version"}`
- `evidence_category="architectural_core"`
- `authority_tier in {"canonical_primary", "canonical_secondary"}`
- `review_status in {"reviewed", "verified", "human_reviewed"}` at the formal TSV layer, mapped to `review_status="human_reviewed"` in Evidence nodes.

Trusted support is still useful for retrieval, provenance, reports, and audit context. However, `trusted_core` does not imply equal recommendation priority. `ecosystem_component` records such as official extensions, hubs, wrappers, and spatial variants remain formal evidence but must be retrieval-only unless a later human governance change explicitly reclassifies them.

Embedding policy:

- Embeddings are retrieval signals, not facts.
- Embeddings derived from LLM summaries must use `trust_level=model_extracted`, `graph_layer=experimental`, and `use_for=["retrieval"]`.
- Migration suggestions from embedding similarity must be labelled `exploratory` and cannot support a high-confidence recommendation by themselves.

## Benchmark Evidence Governance V1

Benchmark curation starts from candidate review packets, not from direct formal ingestion.

`data/tool_benchmarks.tsv` must keep the field order defined by `core/evidence_schemas.py::BENCHMARK_FIELDS`. Benchmark Governance V1 does not add formal-table columns. Candidate benchmark material stays under `data/evidence_candidates/`, and the primary human-review queue is:

- `data/evidence_candidates/core50_benchmark_review_packet.tsv`

Candidate benchmark shells, supplement landing records, abstracts, editor evaluations, and records missing metric context must not enter `data/tool_benchmarks.tsv`.

Minimum structure for a formal benchmark fact:

- source identity: `benchmark_id`, `benchmark_name`, `source_url` or DOI/PMID-backed paper fields
- scope: `tool_name`, `task`, `dataset`, and where possible `modality`
- metric semantics: `metric`, `direction`, and `evaluation_protocol`
- result value: at least one of `rank`, `score`, `normalized_score`, or a human-reviewed source-bound `result_text`
- comparison context: `n_tools_compared` or an equivalent explicit rank scope
- governance: `review_status in {"reviewed", "verified", "human_reviewed"}` and `trust_level`

Benchmark recommendation authority is derived conservatively:

| Formal benchmark state | Allowed use |
| --- | --- |
| Approved review status + complete metric context + `trust_level=trusted_core` | retrieval, ranking, recommendation |
| Approved review status + complete metric context + `trust_level=review_needed` | retrieval only until governance reclassifies it |
| Approved review status + `trust_level=retrieval_only` | retrieval/provenance only |
| Candidate, pending, review_needed, shell, or incomplete metric context | no recommendation use |

Benchmark review packets may propose `ready_for_review`, `needs_manual_extraction`, `needs_field_completion`, `likely_shell`, `hold_candidate`, or `no_candidate_found`. These are review-queue decisions only. They do not authorize formal ingestion and must not create benchmark scores, ranks, metrics, datasets, or protocols that are not present in a trusted source.

When exact numeric ranks or scores are not curated, a formal benchmark row may use `result_text` for a qualitative comparative conclusion. Backfill must expose that record as `metric_name="benchmark_result"`, not as `benchmark_rank` or `benchmark_score`. This preserves recommendation-grade benchmark support without inventing numeric values.

## Node Types

### Tool

Represents a concrete software package, library, pipeline, web service, or command-line tool.

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Canonical tool name. |
| `description` | string | Short functional description. |
| `github_url` | string | Source repository when available. |
| `homepage_url` | string | Project homepage when available. |
| `documentation_url` | string | Documentation URL when available. |
| `license` | string | Software license. |
| `language` | string | Main implementation language. |
| `publish_year` | int/string | First release or catalog year. |
| `github_stars` | int | GitHub stars. |
| `forks` | int | GitHub forks. |
| `open_issues` | int | Open GitHub issues. |
| `last_updated` | datetime/string | Last observed repository update. |
| `maintenance_status` | enum | `active`, `low_activity`, `archived`, `unknown`. |

Required metadata:

- `source_url`
- `source_type`
- `extraction_method`
- `extraction_time`
- `confidence`
- `review_status`
- `kg_version`

### Task

Represents a scientific analysis task.

Controlled vocabulary starter set:

- `QC`
- `Normalization`
- `Batch Correction`
- `Data Integration`
- `Clustering`
- `Cell Type Annotation`
- `Trajectory Inference`
- `Differential Expression`
- `DTU Analysis`
- `Multiome Integration`

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Canonical task name. |
| `definition` | string | What the task means. |
| `aliases` | list[string] | Common synonyms. |
| `task_family` | string | Broad task group. |

### Algorithm

Represents the computational method behind a tool.

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Algorithm node name. |
| `features` | string | Human-readable algorithm summary. |
| `embedding` | list[float] | Algorithm feature embedding. |
| `model_family` | string | e.g. VAE, graph neural network, MNN, CCA, HMM. |
| `objective` | string | Optimization or statistical objective. |
| `distance_metric` | string | Main metric, similarity, or divergence. |
| `optimization` | string | Training/inference method. |
| `input_signature` | list[string] | Expected input representation. |
| `output_signature` | list[string] | Expected output representation. |

### DataScenario

Represents the user's analysis context and constraints.

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Scenario name. |
| `modality` | string | e.g. scRNA-seq, scATAC-seq, spatial transcriptomics, long-read scRNA-seq. |
| `platform` | string | e.g. 10x Genomics, Smart-seq2, Nanopore, PacBio. |
| `data_object` | string | e.g. AnnData, SeuratObject, SingleCellExperiment, FASTQ, BAM, h5ad. |
| `sample_size` | string/int | Number of cells/spots/samples. |
| `noise_level` | enum | `low`, `medium`, `high`, `unknown`. |
| `species` | string | Human, mouse, mixed, unknown. |
| `hardware` | list[string] | CPU, GPU, high memory, cluster. |
| `analysis_goal` | string | User's desired output. |
| `strictness` | enum | `strict`, `balanced`, `exploratory`. |

### Task Ontology V0.2

Recommendation retrieval uses a constrained task vocabulary. Fine tasks should be preserved during parsing and may map to a broader `task_family` for graph fallback.

Fine tasks added in V0.2:

| Fine task | Task family | Typical primary tools |
| --- | --- | --- |
| `Doublet Detection` | `QC` | Scrublet, DoubletFinder |
| `Ambient RNA Removal` | `QC` | SoupX |
| `RNA Velocity` | `Trajectory Inference` | scVelo |
| `Spatial Deconvolution` | `Cell Type Annotation` | cell2location |
| `Trajectory Differential Expression` | `Differential Expression` | tradeSeq |
| `Foundation Model Representation` | `Data Integration` | scGPT, CellPLM |
| `Optimal Transport Trajectory` | `Trajectory Inference` | wot, moscot |

Policy:

- Fine task matches should be ranked above coarse task-family matches.
- `scIB` is a benchmark protocol/source, not a primary data integration tool.
- `ecosystem_component` evidence remains retrieval-only under Strategy A.
- Main recommendation top-k requires `recommendation_eligible=true` and `authority_tier` in `canonical_primary` or `canonical_secondary`, or a trusted benchmark record.

### Evidence

Represents a fact used for ranking, filtering, or explanation.

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Evidence identifier. |
| `evidence_type` | enum | `benchmark`, `literature`, `github_activity`, `runtime`, `memory`, `compatibility`, `manual_note`. |
| `metric_name` | string | e.g. citations, benchmark_rank, runtime_minutes. |
| `metric_value` | string/number | Raw value. |
| `metric_unit` | string | Unit if applicable. |
| `dataset_scope` | string | Dataset/task where the evidence applies. |
| `source_url` | string | Primary source URL. |
| `source_title` | string | Paper, benchmark, repository, or dataset title. |
| `evidence_strength` | enum | `strong`, `medium`, `weak`, `exploratory`. |
| `trust_level` | enum | `verified`, `source_based`, `model_extracted`, `inferred`, `missing`. |
| `graph_layer` | enum | `trusted_core`, `review_needed`, `experimental`. |
| `use_for` | list[string] | Which stages may use the evidence. |
| `human_review_decision` | enum/string | Formal review action such as `formalize`, `supporting`, or `quarantine`. |
| `canonical_scope` | enum/string | Scope of the work, such as `core_tool`, `major_version`, `ecosystem_component`, or `non_canonical`. |
| `evidence_category` | enum/string | Evidence role, such as `architectural_core`, `method_extension`, `application_case`, or `benchmark_evaluation`. |
| `recommendation_eligible` | boolean/null | Whether this evidence may support the main recommendation path. |
| `authority_tier` | enum/string | Recommendation authority tier, such as `canonical_primary`, `canonical_secondary`, `ecosystem_support`, `contextual_support`, or `provenance_only`. |
| `audit_support_level` | enum/string | Auditor support level, such as `absolute_authority`, `empirical_proof`, `contextual_use_case`, or `provenance_only`. |

### Workflow

Represents an analysis pipeline or reusable workflow template.

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Workflow name. |
| `description` | string | Workflow purpose. |
| `workflow_type` | string | e.g. scRNA-seq standard, multiome integration, long-read DTU. |
| `input_signature` | list[string] | Accepted inputs. |
| `output_signature` | list[string] | Produced outputs. |
| `compatibility_rules` | list[string] | Human-readable compatibility constraints. |

### WorkflowStep

Represents one ordered step in a workflow.

Minimum properties:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Step name. |
| `order` | int | Position in workflow. |
| `task` | string | Task performed by this step. |
| `required_input` | list[string] | Input objects required. |
| `produced_output` | list[string] | Output objects produced. |
| `is_optional` | bool | Whether the step can be skipped. |

## Relationship Types

| Relationship | From | To | Description |
| --- | --- | --- | --- |
| `PERFORMS_TASK` | Tool | Task | Tool supports a task. |
| `SUPPORTS_MODALITY` | Tool | DataScenario/Modality | Tool supports a modality or scenario. |
| `IMPLEMENTS_ALGORITHM` | Tool | Algorithm | Tool implements an algorithm. |
| `SUPPORTED_BY` | Tool/Algorithm/Workflow | Evidence | Concrete evidence binding used by current code. |
| `HAS_EVIDENCE` | Tool/Algorithm/Workflow | Evidence | Alias for evidence binding in later schema migrations. |
| `PART_OF_WORKFLOW` | WorkflowStep | Workflow | Step belongs to a workflow. |
| `NEXT_STEP` | WorkflowStep | WorkflowStep | Step ordering. |
| `USES_TOOL` | WorkflowStep | Tool | Step can be implemented with a tool. |
| `REQUIRES_INPUT` | Tool/WorkflowStep | DataScenario | Required input scenario or object. |
| `PRODUCES_OUTPUT` | Tool/WorkflowStep | DataScenario | Output scenario or object. |
| `COMPATIBLE_WITH` | Tool | Tool/DataScenario | Positive compatibility relation. |
| `INCOMPATIBLE_WITH` | Tool | Tool/DataScenario | Negative compatibility relation. |
| `MIGRATES_TO` | Algorithm/Tool | DataScenario/Task | Exploratory migration suggestion. |

## Current-to-Target Migration

Current labels `Modality`, `Hardware`, `Resolution`, and `Language` can remain as auxiliary vocabulary nodes, but the target schema should introduce `DataScenario`, `Evidence`, `Workflow`, and `WorkflowStep`.

Migration order:

1. Add metadata fields to existing `Tool`, `Task`, and `Algorithm`.
2. Add `Evidence` nodes and connect them with `SUPPORTED_BY`.
3. Add `DataScenario` nodes for modality/platform/data object/hardware constraints.
4. Add `Workflow` and `WorkflowStep` templates for common single-cell pipelines.
5. Move recommendation output from single-tool records to evidence-backed decision objects.

## Acceptance Criteria

The schema is usable when:

- Every recommendation can point to at least one `Tool` or `Workflow`.
- Every ranked item has at least three evidence fields or explicit missing-evidence flags.
- Every LLM-extracted fact has source, extraction method, confidence, and review status.
- Every LLM-extracted or inferred fact is isolated as `experimental` until reviewed.
- Recommendation ranking uses recommendation-grade evidence first; retrieval-only evidence can recall candidates but cannot support high-confidence final claims.
- Migration recommendations include algorithm similarity, structural compatibility, and risk level.
