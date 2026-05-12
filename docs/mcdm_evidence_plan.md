# MCDM Evidence Collection Plan

The current MCDM implementation uses real `github_stars`, but `citations` and `benchmark_rank` are placeholders. This document defines how to replace placeholders with real, auditable evidence.

## Goal

Every ranked recommendation should answer three questions:

1. Why can this tool be used?
2. Why is it ranked above other candidates?
3. Why are alternatives weaker or riskier?

## Minimum Evidence Dimensions

Start with three dimensions before adding more:

| Dimension | Field | Source | Update Frequency | MCDM Role |
| --- | --- | --- | --- | --- |
| Benchmark support | `benchmark_rank`, `benchmark_score`, `benchmark_dataset` | curated benchmark papers/tables | manual per benchmark release | Scientific performance. |
| GitHub activity | `github_stars`, `forks`, `open_issues`, `last_updated`, `maintenance_status` | GitHub API | weekly/monthly | Engineering reliability. |
| Literature support | `citations`, `paper_url`, `publication_year`, `venue` | OpenAlex/Semantic Scholar/PubMed/manual DOI mapping | monthly/quarterly | Academic adoption. |

## Evidence Node Schema

Represent each evidence item as an `Evidence` node and connect it to `Tool` with `SUPPORTED_BY`.

```cypher
(:Tool)-[:SUPPORTED_BY]->(:Evidence {
  name: "Harmony github activity 2026-05",
  evidence_type: "github_activity",
  metric_name: "last_updated",
  metric_value: "2026-04-20",
  metric_unit: "date",
  dataset_scope: "global_repository",
  source_url: "https://github.com/...",
  source_title: "GitHub repository metadata",
  evidence_strength: "medium",
  extraction_method: "github_crawler.py",
  extraction_time: "2026-05-12T00:00:00",
  confidence: 0.95,
  review_status: "auto_checked",
  kg_version: "v0.1"
})
```

## Data Collection Tasks

### 1. GitHub Activity

Existing code: `data_pipeline/github_crawler.py`.

Add fields:

- `forks`
- `open_issues`
- `last_updated`
- `archived`
- `default_branch`
- `license`

Derived field:

```text
maintenance_status =
  archived == true -> archived
  last_updated within 18 months -> active
  last_updated within 36 months -> low_activity
  otherwise -> stale
```

Acceptance:

- Every GitHub-backed `Tool` has `github_stars`, `forks`, `open_issues`, `last_updated`, and `maintenance_status`.
- Missing GitHub data is represented as missing evidence, not silently replaced with fake values.

### 2. Literature Support

Minimum strategy:

- Add a curated mapping file: `data/tool_publications.tsv`.
- Columns: `tool_name`, `title`, `doi`, `pmid`, `paper_url`, `publication_year`, `venue`, `citation_source`, `citations`, `last_checked`.
- Later automate citation refresh with OpenAlex or Semantic Scholar.

Acceptance:

- Ranking code reads `citations` only from a sourced field.
- If citations are missing, the evidence breakdown says `literature_support: missing`.

### 3. Benchmark Support

Minimum strategy:

- Add a curated mapping file: `data/tool_benchmarks.tsv`.
- Columns: `benchmark_name`, `task`, `modality`, `dataset`, `tool_name`, `rank`, `score`, `metric`, `source_url`, `notes`, `last_checked`.

Rules:

- Benchmark evidence is task-specific.
- Do not compare benchmark ranks across unrelated tasks.
- If multiple benchmark datasets exist, compute a task-local aggregate only after documenting the rule.

Acceptance:

- `benchmark_rank` is never a global default.
- If no benchmark exists for the user's task/modality, MCDM should mark it missing and lower evidence confidence.

## Initial MCDM Formula

Use a weighted score only after normalizing each available metric:

```text
score = 0.45 * benchmark_component
      + 0.30 * literature_component
      + 0.25 * engineering_component
```

If a component is missing:

- Do not fabricate the value.
- Add `missing_evidence` to `evidence_breakdown`.
- Compute score with available components and add `evidence_completeness`.

Example output object:

```json
{
  "tool_name": "Harmony",
  "mcdm_score": 0.82,
  "evidence_completeness": 0.67,
  "evidence_breakdown": {
    "benchmark": {"status": "available", "rank": 1, "source_url": "..."},
    "literature": {"status": "missing"},
    "engineering": {"status": "available", "github_stars": 1300, "last_updated": "..."}
  },
  "recommendation_confidence": "medium"
}
```

## Implementation Order

1. Extend `GitHubCrawler` to collect richer repository evidence.
2. Add `data/tool_publications.tsv` and `data/tool_benchmarks.tsv` with a small manually curated seed set.
3. Extend Neo4j loader to create `Evidence` nodes instead of writing only scalar properties onto `Tool`.
4. Change `mcdm_scoring_node` to read evidence records and explicitly handle missing evidence.
5. Update report generation to quote evidence source URLs and evidence strength.

## First Seed Tasks

Keep benchmark curation narrow at first:

- `Data Integration`
- `Clustering`
- `Cell Type Annotation`
- `Trajectory Inference`
- `DTU Analysis`

## Acceptance Criteria

MCDM is production-like when:

- No placeholder `citations` or `benchmark_rank` remains in scoring code.
- Every score has `evidence_breakdown`.
- Every evidence item has a source and timestamp.
- The final report can explain why a tool is recommended and why alternatives are weaker.
- Missing evidence decreases confidence instead of being hidden.
