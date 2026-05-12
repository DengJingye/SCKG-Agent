# AGENTS.md

# scKG_Agent — Agent Operating Rules

This repository builds a scientific evidence-governed recommendation and workflow system for single-cell and spatial omics tools.

The system prioritizes:
- structured evidence
- reproducibility
- recommendation traceability
- hallucination reduction
- conservative recommendation behavior

Agents working in this repository must follow the rules below.

---

# Core Principles

## 1. Evidence First

Do not generate recommendation-grade conclusions without structured evidence.

Recommendation-grade evidence should preferably include:
- DOI / PMID / publication metadata
- benchmark evidence
- protocol or workflow evidence
- trusted human-reviewed evidence
- reproducible evaluation evidence

GitHub activity alone is not sufficient for strong scientific recommendation claims.

---

## 2. Conservative Behavior

When evidence is weak:
- downgrade confidence
- mark exploratory status
- preserve uncertainty
- avoid strong recommendation wording

Do not fabricate:
- benchmark rankings
- metric values
- migration compatibility
- QC thresholds
- literature conclusions
- workflow transitions

---

## 3. Human Review Required

Candidate evidence is NOT trusted evidence.

Anything with:
- pending
- review_needed
- experimental

must remain outside recommendation-grade pathways unless explicitly approved by human review.

Only the following review statuses are considered approved for formal ingestion:
- reviewed
- verified
- human_reviewed

Rejected statuses:
- rejected
- deprecated

---

# Repository Governance Rules

## 4. Candidate Evidence Must Stay Isolated

Files under:
- data/evidence_candidates/

are candidate-only evidence.

Agents must NOT:
- auto-promote candidates
- auto-write candidates into production evidence
- auto-ingest candidates into AuraDB
- auto-upgrade trust levels

Candidate evidence requires explicit human review before promotion.

---

## 5. Formal Evidence Tables

Formal evidence tables:
- data/tool_publications.tsv
- data/tool_benchmarks.tsv

must only contain reviewed or verified evidence.

Field order must remain synchronized with:
- core/evidence_schemas.py

Agents must preserve:
- schema consistency
- column order
- backward compatibility

---

## 6. Canonical Record Policy

A single scientific work may appear as:
- preprint
- journal paper
- protocol paper
- application paper
- benchmark paper

These should be grouped into a shared:
- work_group_id

Rules:
- canonical records should be conservative
- duplicate records must not inflate scoring
- only canonical records should enter recommendation-grade scoring
- non-canonical records remain linked evidence

---

## 7. Recommendation Pipeline Rules

Main recommendation flow should remain narrow and evidence-governed.

Allowed pathway:

raw retrieval
→ evidence gate
→ trusted_core filtering
→ top-k selection
→ report generation
→ semantic hallucination audit

Rules:
- raw graph recall may be large
- recommendation context must remain small
- only trusted_core recommendation-grade evidence enters final recommendation context
- top-k limits must remain enforced
- report generation must not access unrestricted candidate pools

---

## 8. Semantic Hallucination Prevention

Reports must not introduce unsupported:
- tools
- benchmark claims
- literature claims
- ranking claims
- migration guarantees
- workflow transitions
- numeric thresholds

All generated reports should be auditable against:
- structured evidence
- scored_tools
- workflow state
- migration paths

Critical or high-severity hallucination findings should block unsafe reports.

---

# Agent Development Rules

## 9. Prefer Small Deterministic Scripts

Prefer:
- deterministic scripts
- explicit validation
- TSV-based workflows
- review queues
- reproducible outputs

Avoid:
- hidden heuristics
- implicit evidence mutation
- opaque ranking logic
- uncontrolled LLM rewriting

---

## 10. Do Not Expand Scope Unnecessarily

Current priority is:
- evidence quality
- publication evidence
- benchmark evidence
- canonical deduplication
- review workflow governance
- hallucination reduction

Current priority is NOT:
- UI expansion
- feature proliferation
- autonomous reasoning loops
- agent complexity growth

---

# Preferred Engineering Workflow

Preferred workflow:

1. generate candidates
2. normalize records
3. group duplicates
4. generate review actions
5. human review
6. promote reviewed evidence
7. backfill structured graph
8. run evaluation
9. run semantic hallucination audit

---

# Validation Expectations

Before completing major changes, agents should preferably run:
- py_compile
- smoke eval
- semantic hallucination audit
- small sample validation

Do not claim completion without validation output.

---

# Output Expectations

When modifying repository logic:
- explain modified files
- explain validation steps
- explain governance impact
- preserve backward compatibility where possible

When uncertain:
- preserve conservative behavior
- avoid silent automation
- prefer review queues over automatic decisions

---

# Current Project Priorities

Highest priority:
1. publication evidence quality
2. benchmark evidence quality
3. canonical deduplication
4. trusted_core governance
5. hallucination reduction
6. recommendation traceability

Lower priority:
- UI polishing
- autonomous agent expansion
- generalized tool discovery
- large-scale feature additions

---

# Operational Philosophy

The goal of this repository is not maximal automation.

The goal is:
- trustworthy scientific recommendation
- evidence traceability
- controllable governance
- conservative scientific reasoning
- reproducible recommendation behavior

When tradeoffs appear:
prefer correctness and traceability over automation speed.