# Phase 2 Pilot Source Policy Decisions

Decision date: 2026-09-20
Scope: `pilot-20260920-v1` only
Status: operational research-data decisions, not legal advice

These decisions authorize or block only the bounded mining pilot. They do not
authorize bulk collection, redistribution of thread bodies, collection of user
profiles, or use of public replies as scientific Gold.

## Decision summary

| Source | Decision | Permitted access | Durable fields | Explicit exclusions |
| --- | --- | --- | --- | --- |
| Scanpy GitHub issues (`scverse/scanpy`) | `reviewed` / allow | One unauthenticated call to the official GitHub REST `List repository issues` endpoint, page 1, at most 100 results; respect returned rate-limit headers. | Issue number, title after redaction, canonical URL, state, created/updated timestamps, non-user labels, API version, ETag, and hashes. | Pull requests, author/login/avatar/profile data, body, comments, reactions, assignees, maintainer replies, accepted answers, and deleted/private records. |
| Seurat GitHub issues (`satijalab/seurat`) | `reviewed` / allow | Same bounded official REST profile as Scanpy. | Same title-level profile as Scanpy. | Same exclusions as Scanpy. |
| Project-owned controlled probes | `reviewed` / allow | Deterministic local generation by the versioned pilot collector. | Full project-authored prompt and generation metadata. | Expected answer, split, Gold, or downstream-system result. |
| scverse Discourse | `prohibited` for automation | None. Do not call the category JSON/RSS endpoint in this pilot. | Registry decision only; zero topic records. | The forum [Terms of Service](https://discourse.scverse.org/tos) prohibit automated access except crawling by a public search engine for indexing. An official-looking JSON endpoint does not override that term. |
| Biostars | `pending` / blocked | None. | Registry decision only. | No page, API, RSS, or search collection until terms, robots, storage, PII, and removal handling are reviewed. |
| Bioconductor Support | `pending` / blocked | None. | Registry decision only. | No page, API, or RSS collection until its user agreement and reuse/storage terms are reviewed. |

## GitHub basis and safeguards

The pilot uses GitHub's documented [List repository issues REST
endpoint](https://docs.github.com/en/rest/issues/issues#list-repository-issues),
which may be used without authentication for public resources. GitHub's [API
Terms](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms)
prohibit abusive/excessive use and token sharing to evade limits, and the
[Acceptable Use
Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)
permit research use of public, non-personal information subject to their stated
conditions. The pilot therefore performs two serial GET requests, records the
returned [rate-limit
headers](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api),
and stores no author identifiers.

Issue text remains user-generated content with site-specific rights; public API
availability is not treated as an open-content license. The storage decision is
therefore `title_only`, with canonical-link provenance, PII pattern redaction,
and no redistribution claim. A removal request or inaccessible canonical record
must produce a tombstone in a future refresh rather than silently reusing a
cached title.

## PII and minimization procedure

Only the issue title enters durable raw-seed text. Before writing, the collector
checks and replaces email addresses, IPv4 addresses, phone-like digit runs,
common home-directory paths, and token-like secrets. Every replacement is
counted and recorded in `pii_redaction_status` and `transformation_history`.
The source API response body is held only in memory; the repository stores the
selected minimal projections and hashes, not the unredacted issue body or user
object.

The automated patterns are a conservative first pass, not human PII clearance.
All records remain raw seeds with `gold_eligible=false`. Candidate scenarios
remain `review_status=needs_adjudication` and `gold_status=none`.

## Answers, replies, and scientific authority

This pilot never requests issue comments or forum replies. An accepted answer,
maintainer reply, issue closure, or high-vote response would still be context
rather than Gold. Any future scientific answer must be independently authored
and adjudicated using the existing `ReferenceClaim`/source-span and evaluation
protocol contracts.

## Re-review triggers

Stop collection and re-review this file if a source changes its terms, API
version, authentication requirement, robots policy, public/private status,
rate-limit response, or removal mechanism. Expansion beyond the two allowlisted
repositories, page 1, title-only storage, or the 40--60 seed pilot requires a
new decision.
