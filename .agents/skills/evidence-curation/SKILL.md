# Evidence Curation Skill

## Purpose

This skill curates candidate scientific evidence for scKG_Agent.

It handles:
- publication candidate normalization
- benchmark candidate normalization
- duplicate grouping
- canonical record suggestion
- review action generation
- evidence governance preparation

This skill does NOT:
- write to AuraDB
- auto-promote evidence
- modify recommendation logic
- auto-upgrade trust levels
- bypass human review

---

# Primary Inputs

Publication candidates:
- data/evidence_candidates/tool_publication_candidates.tsv
- data/evidence_candidates/core50_tool_publication_candidates.tsv
- data/evidence_candidates/core50_publication_manual_anchors.tsv

Benchmark candidates:
- data/evidence_candidates/tool_benchmark_candidates.tsv
- data/evidence_candidates/core50_tool_benchmark_candidates.tsv

Tool manifests:
- data/evidence_candidates/core_50_tools.tsv

Schemas:
- core/evidence_schemas.py

---

# Expected Outputs

Publication outputs:
- data/evidence_candidates/tool_publication_candidates_dedup.tsv
- data/evidence_candidates/tool_publication_review_actions.tsv
- data/evidence_candidates/publication_work_groups.tsv
- data/evidence_candidates/core50_publication_review_packet.tsv
- data/evidence_candidates/core50_publication_manual_anchor_review_proposals.tsv

Benchmark outputs:
- data/evidence_candidates/tool_benchmark_review_actions.tsv
- data/evidence_candidates/benchmark_work_groups.tsv

Optional logs:
- data/evidence_backfill_logs/*.jsonl

---

# Core Responsibilities

## 1. Publication Deduplication

Group likely duplicate publications using:
- DOI
- PMID
- arXiv ID
- normalized title similarity
- author overlap
- tool_name alignment

The skill should identify:
- preprint
- journal
- protocol
- application paper
- benchmark paper

that belong to the same scientific work.

---

## 2. Canonical Work Grouping

Each scientific work should receive:
- work_group_id

Each record may include:
- canonical_flag
- duplicate_of

Rules:
- canonical selection must remain conservative
- journal publication is generally preferred over preprint
- protocol/application papers are linked evidence, not primary method records
- duplicate records must not inflate recommendation scoring
- duplicate suppression is tool-specific: the same publication may support multiple tools and must not cause another tool's evidence row to be treated as a duplicate

The skill should generate recommendations only.
Final approval remains human-controlled.

Manual anchor seeds are still candidate evidence. They may satisfy a
manual lookup gap, but they do not authorize formal ingestion until a
separate human-review row explicitly marks the seed as reviewed,
verified, or human_reviewed.

---

## 3. Benchmark Validation

Benchmark candidates must be checked for minimum completeness.

Important fields:
- benchmark_name
- task
- modality
- dataset
- metric
- direction
- rank / score / normalized_score
- n_tools_compared
- evaluation_protocol

If benchmark_name appears to be:
- supplementary material
- appendix
- partial extraction
- shell metadata

the record should be marked:
- needs_manual_benchmark_extraction

The skill must NEVER invent:
- scores
- ranks
- benchmark metrics
- evaluation conclusions

---

## 4. Review Action Generation

The skill should generate structured review actions.

Recommended fields:
- publication_id or benchmark_id
- work_group_id
- canonical_flag
- duplicate_of
- recommended_review_status
- recommended_trust_level
- reason
- missing_fields
- validation_notes

---

# Governance Rules

## Candidate Isolation

Anything under:
- data/evidence_candidates/

must remain candidate-only evidence.

Do not:
- auto-promote
- auto-ingest
- auto-write into formal TSVs
- auto-mark verified

---

## Allowed Review Statuses

Approved:
- reviewed
- verified
- human_reviewed

Non-approved:
- pending
- review_needed
- rejected
- deprecated

Only approved records may later enter:
- data/tool_publications.tsv
- data/tool_benchmarks.tsv

through a separate backfill process.

---

# Engineering Preferences

Prefer:
- deterministic logic
- reproducible outputs
- conservative matching
- explicit review queues
- TSV-first workflows

Avoid:
- hidden heuristics
- silent mutations
- destructive overwrites
- opaque scoring logic

---

# Preferred Workflow

1. load candidate TSV
2. normalize fields
3. detect duplicates
4. build work groups
5. generate review actions
6. export review TSVs
7. stop

Human review occurs AFTER this stage.

---

# Validation Expectations

When implementing scripts using this skill:
- preserve all original columns
- preserve row traceability
- avoid lossy transformations
- provide sample outputs
- provide small validation examples
- provide run commands

Preferred validation:
- py_compile
- small TSV smoke test
- row count consistency check
- duplicate grouping sanity check

---

# Recommended Script Names

Suggested scripts:
- publication_canonical_merge.py
- benchmark_candidate_validator.py
- generate_review_actions.py
- publication_workgroup_builder.py

---

# Example Usage

Example task:

"Use the evidence-curation skill.
Implement a publication canonical merge script for tool_publication_candidates.tsv.
Generate deduplicated outputs and review actions.
Do not modify AuraDB or formal TSVs."

---

# Operational Philosophy

This skill exists to improve:
- scientific traceability
- recommendation quality
- evidence governance
- hallucination resistance

Correctness and auditability are more important than automation speed.
