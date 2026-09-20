# Phase 2 Real-world Question Mining Pilot Report

Run: `pilot-20260920-v1`
Date: 2026-09-20
Status: complete bounded pilot; no DEV/Gold or Agent Gain

## Outcome

- Raw seeds: 48 (40 real-user, 8 controlled probes).
- Source counts: `{"benchmark-v3-controlled-probes": 8, "satijalab/seurat issues": 20, "scverse/scanpy issues": 20}`.
- Official API calls: 2 serial GitHub REST GETs; bodies/comments/replies were never requested.
- Automated PII replacements in stored titles: 0.
- Exact duplicate groups: 0; near-duplicate candidates: 0.
- Provisional clusters: 8; candidate-scenario plumbing records: 6.
- Raw schema: 48 checked, 0 errors; negative `gold_eligible=true` test rejected: true.
- Candidate invariants: `review_status=needs_adjudication`, `gold_status=none`, and contamination fields valid for all 6 records.

## Selection and leakage controls

Each GitHub source was limited to page 1 (100 API items maximum). Pull requests,
bot-authored items, and empty titles were excluded. Twenty issues per repository
were selected by a fixed SHA-256 rank over repository plus issue number, without
looking at issue text, replies, or any 07 Research Chat result. Eight project-owned
controlled probes were appended and are reported separately.

The dedup thresholds are provisional and not yet calibrated by human pair
review. Zero near-duplicate candidates therefore means “none crossed the pilot
threshold,” not that the sample contains no semantic duplicates. The lexical
clustering smoke test placed 35/48 records in its largest cluster;
that imbalance is evidence that title-only TF-IDF clusters are not yet suitable
for balanced scenario sampling. Cluster labels and memberships remain review
queues only.

No public answer, accepted answer, maintainer reply, issue state, or label became
Gold. Candidate drafts are identity transformations used to exercise the
transformation and contamination fields; public candidates are deliberately
flagged `memorization_risk=high`. No coverage signature was assigned because no
frozen V2/Legacy/RAG coverage audit was run.

## Policy outcomes

Scanpy and Seurat were collected only through the official GitHub REST API under
the title-only profile in `policy_decisions.md`. scverse Discourse was not
contacted because its Terms of Service prohibit this automation. Biostars and
Bioconductor Support remained policy-pending and were not contacted.

## Interpretation limits

This pilot validates engineering flow and provenance retention, not population
representativeness. The one-page GitHub frame, title-only questions, fixed eight
clusters, automated PII patterns, and unadjudicated duplicate candidates are
deliberate pilot constraints. It generated no development/evaluation/hidden
split, no expected answer, no scientific Gold, and no Agent Gain result. It did
not modify Viewer, Scientific KG, or Research Chat.
