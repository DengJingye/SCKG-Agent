# Evidence Curation Verification

This document defines the verification protocol for the evidence curation pipeline of scKG_Agent.

The goal of this pipeline is to curate candidate publication evidence, benchmark evidence, and work-group grouping outputs in a conservative, reproducible, and human-review-governed way.

---

## 1. Purpose

This verification protocol exists to ensure that:

1. publication candidates are normalized and deduplicated correctly;
2. benchmark candidates are validated without inventing values;
3. work-group grouping is conservative and traceable;
4. review actions are produced in a structured form;
5. formal evidence tables remain protected from unreviewed or low-trust records.

This protocol applies to the following scripts:

- `publication_canonical_merge.py`
- `benchmark_validate.py`
- `workgroup_grouping.py`

---

## 2. In-Scope Files

### Candidate inputs
- `data/evidence_candidates/tool_publication_candidates.tsv`
- `data/evidence_candidates/tool_benchmark_candidates.tsv`
- `data/evidence_candidates/core50_tool_publication_candidates.tsv`
- `data/evidence_candidates/core50_tool_benchmark_candidates.tsv`
- `data/evidence_candidates/core_50_tools.tsv`

### Candidate outputs
- `data/evidence_candidates/tool_publication_candidates_dedup.tsv`
- `data/evidence_candidates/tool_publication_review_actions.tsv`
- `data/evidence_candidates/tool_benchmark_review_actions.tsv`
- `data/evidence_candidates/publication_work_groups.tsv`
- `data/evidence_candidates/benchmark_work_groups.tsv`
- `data/evidence_candidates/publication_work_groups_summary.tsv`
- `data/evidence_candidates/benchmark_work_groups_summary.tsv`
- `data/evidence_candidates/core50_tool_publication_candidates_dedup.tsv`
- `data/evidence_candidates/core50_tool_publication_review_actions.tsv`
- `data/evidence_candidates/core50_tool_benchmark_review_actions.tsv`
- `data/evidence_candidates/core50_publication_work_groups.tsv`
- `data/evidence_candidates/core50_benchmark_work_groups.tsv`
- `data/evidence_candidates/core50_publication_work_groups_summary.tsv`
- `data/evidence_candidates/core50_benchmark_work_groups_summary.tsv`

### Reference schema
- `core/evidence_schemas.py`

---

## 3. Out-of-Scope Files

The following files must not be modified by the verification step unless explicitly stated:

- `data/tool_publications.tsv`
- `data/tool_benchmarks.tsv`
- AuraDB / Neo4j live writing logic
- recommendation logic
- semantic hallucination auditor logic
- evaluation gold query files

The verification stage must stay in candidate / review space.

---

## 4. Verification Goals

### 4.1 Publication canonical merge verification
The publication merge step must:

- preserve all original rows;
- preserve all original columns;
- add work-group metadata without destroying source fields;
- group exact duplicates and near-duplicate publication versions conservatively;
- identify canonical records conservatively;
- generate review actions for each record.

### 4.2 Benchmark validation verification
The benchmark validation step must:

- detect missing required benchmark fields;
- separate placeholder benchmark shells from usable benchmark records;
- never invent benchmark values;
- generate structured review buckets;
- preserve source traceability.

### 4.3 Work-group grouping verification
The work-group step must:

- group related records by publication or benchmark identity;
- generate work-group IDs;
- mark canonical vs duplicate records conservatively;
- preserve source lineage;
- avoid mixing publication and benchmark records incorrectly.

---

## 5. Acceptance Criteria

A run is considered valid only if all of the following are satisfied.

### 5.1 Structural integrity
- Original input rows are preserved.
- Original source columns are preserved.
- Newly added governance columns are present.
- Output files are written successfully.

### 5.2 Publication curation correctness
- DOI / PMID / arXiv-based duplicates are grouped.
- Title similarity and author overlap are used conservatively.
- Canonical selection is stable and conservative.
- Duplicate records contain a populated `duplicate_of` field.
- Review actions contain a clear reason.
- Duplicate suppression is scoped by `tool_name`; the same publication can support multiple tools and must not erase another tool's evidence row.

### 5.3 Benchmark validation correctness
- Placeholder benchmark names are detected.
- Missing benchmark fields are reported explicitly.
- No metric, rank, score, or normalized score is invented.
- Records are bucketed into a review category deterministically.

### 5.4 Work-group correctness
- `work_group_id` is present.
- `canonical_flag` is present.
- `duplicate_of` is present for non-canonical records.
- Summary outputs correctly reflect group membership.
- Publication and benchmark records are not cross-mixed.

### 5.5 Governance correctness
- Candidate files remain candidate-only.
- No automatic promotion into formal TSVs occurs.
- No AuraDB writes occur.
- No trust level is upgraded automatically.
- No pending / review_needed record is silently treated as trusted.

---

## 6. Verification Commands

Run commands from the repository root:

```bash
cd /Data/Omics/dengjingye/project/04agent/scKG_Agent
```

### 6.1 Publication merge
```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  .agents/skills/evidence-curation/scripts/publication_canonical_merge.py \
  --input data/evidence_candidates/tool_publication_candidates.tsv
```

Expected outputs:

- `data/evidence_candidates/tool_publication_candidates_dedup.tsv`
- `data/evidence_candidates/tool_publication_review_actions.tsv`

Minimum checks:

- input row count equals dedup row count;
- input row count equals review action row count;
- all original `publication_id` values are preserved;
- original source columns are preserved;
- `work_group_id`, `canonical_flag`, and `duplicate_of` are present;
- non-canonical duplicate records have `duplicate_of` populated;
- review actions include `reason`, `missing_fields`, and `validation_notes`.

### 6.2 Benchmark validation
```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  .agents/skills/evidence-curation/scripts/benchmark_validate.py \
  --input data/evidence_candidates/tool_benchmark_candidates.tsv
```

Expected output:

- `data/evidence_candidates/tool_benchmark_review_actions.tsv`

Minimum checks:

- input row count equals review action row count;
- placeholder benchmark names are marked as `needs_manual_benchmark_extraction`;
- missing benchmark fields are explicitly listed in `missing_fields`;
- `rank`, `score`, `normalized_score`, and `n_tools_compared` are copied only if present in the input;
- no benchmark metric, rank, score, or conclusion is synthesized by the script.

### 6.3 Work-group grouping
```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  .agents/skills/evidence-curation/scripts/workgroup_grouping.py \
  --publication-input data/evidence_candidates/tool_publication_candidates.tsv \
  --benchmark-input data/evidence_candidates/tool_benchmark_candidates.tsv
```

Expected outputs:

- `data/evidence_candidates/publication_work_groups.tsv`
- `data/evidence_candidates/benchmark_work_groups.tsv`
- `data/evidence_candidates/publication_work_groups_summary.tsv`
- `data/evidence_candidates/benchmark_work_groups_summary.tsv`

Minimum checks:

- publication input rows equal publication work-group rows;
- benchmark input rows equal benchmark work-group rows;
- publication groups contain only `record_type=publication`;
- benchmark groups contain only `record_type=benchmark`;
- `work_group_id`, `canonical_flag`, and `duplicate_of` are present;
- non-canonical records have `duplicate_of` populated;
- summary files contain group size, canonical ID, member IDs, and group reason.

### 6.4 Core 50 candidate crawl and verification
```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/evidence_candidate_crawler.py \
  --tools-file data/evidence_candidates/core_50_tools.tsv \
  --max-tools 50 \
  --publication-output data/evidence_candidates/core50_tool_publication_candidates.tsv \
  --benchmark-output data/evidence_candidates/core50_tool_benchmark_candidates.tsv
```

Then run publication merge, benchmark validation, and work-group grouping against the `core50_*` inputs, writing only to `data/evidence_candidates/core50_*` outputs.

Minimum checks:

- `core_50_tools.tsv` contains exactly the intended core tools and no duplicates;
- crawler outputs remain candidate-only;
- no formal TSVs are written;
- cross-tool shared publications remain separate tool evidence rows unless a later human review intentionally models a shared-evidence relationship.

---

## 7. Suggested Validation Snippets

### 7.1 Row counts
```bash
wc -l \
  data/evidence_candidates/tool_publication_candidates.tsv \
  data/evidence_candidates/tool_publication_candidates_dedup.tsv \
  data/evidence_candidates/tool_publication_review_actions.tsv \
  data/evidence_candidates/tool_benchmark_candidates.tsv \
  data/evidence_candidates/tool_benchmark_review_actions.tsv \
  data/evidence_candidates/publication_work_groups.tsv \
  data/evidence_candidates/benchmark_work_groups.tsv
```

### 7.2 Publication ID preservation
```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B -c "
import csv
base='data/evidence_candidates/'
src=list(csv.DictReader(open(base+'tool_publication_candidates.tsv', encoding='utf-8'), delimiter='\t'))
out=list(csv.DictReader(open(base+'tool_publication_candidates_dedup.tsv', encoding='utf-8'), delimiter='\t'))
print({r['publication_id'] for r in src} == {r['publication_id'] for r in out})
"
```

### 7.3 Benchmark numeric non-invention
```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B -c "
import csv
base='data/evidence_candidates/'
src=list(csv.DictReader(open(base+'tool_benchmark_candidates.tsv', encoding='utf-8'), delimiter='\t'))
out=list(csv.DictReader(open(base+'tool_benchmark_review_actions.tsv', encoding='utf-8'), delimiter='\t'))
fields=['rank','score','normalized_score','n_tools_compared']
print(all((s.get(f,'') == o.get(f,'')) for s,o in zip(src,out) for f in fields))
"
```

---

## 8. Failure Handling

If a verification failure is found:

1. fix only the script responsible for the failed stage;
2. rerun only that stage first;
3. rerun the downstream work-group stage if its inputs or grouping metadata changed;
4. do not patch formal TSVs to hide candidate-layer problems;
5. do not mark records as `verified`, `reviewed`, or `human_reviewed` inside these scripts.

---

## 9. Promotion Gate

Candidate evidence may move toward formal evidence only after a separate human-review step.

Promotion into `data/tool_publications.tsv` or `data/tool_benchmarks.tsv` requires:

- canonical record selected;
- duplicate records marked and excluded from ranking inflation;
- `review_status` intentionally changed by a human or a separate audited promotion script;
- `trust_level` intentionally assigned;
- source URL / DOI / PMID / arXiv / benchmark provenance preserved;
- candidate-only notes retained or explicitly resolved.

This verification protocol does not perform promotion.

---

## 10. Current Known Limits

- Publication candidate search can retrieve application or protocol papers that are not primary method evidence.
- Benchmark candidates may be only supplement shells until metric/rank/score/protocol are manually extracted.
- Work-group canonical selection is a suggestion, not a final truth assignment.
- Citation counts from external APIs are time-sensitive and should be refreshed before formal evidence promotion.

These limits are acceptable at candidate-curation stage as long as the records remain isolated from formal recommendation-grade evidence.
