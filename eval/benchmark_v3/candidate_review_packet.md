# Phase 2.1 Candidate Review Packet

Run: `candidate-audit-20260921-v1`

Candidates: 20

Status: review packet only; every item is `needs_adjudication` / `gold_status=none`.

The first six candidates are the Phase 2 carry-forward set. Every candidate below is an
identity draft. **Added scientific context is explicitly `none` for all candidates.**
Repository identity, labels, versions, and benchmark provenance remain source metadata;
they were not inserted into the draft as if supplied by the original user.

## candidate-pilot-01 — existing Phase 2 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-01` |
| source_seed_id | `github:scverse_scanpy:4296` | `github:scverse_scanpy:4296` |
| raw title/question | **Title:** Reorg io functions<br>**Question:** Reorg io functions | — |
| source provenance | {"canonical_url": "https://github.com/scverse/scanpy/issues/4296", "collected_at": "2026-09-20T16:04:52Z", "collection": "scverse/scanpy issues", "collection_method": "official_api", "external_id": "4296", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "dd08ad11d1bb477b8bfb6e58f5c9e32f7219dd83444ac3302576d801b9c95578", "version_context": {"issue_state": "closed", "labels_csv": "", "repository": "scverse/scanpy"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "dd08ad11d1bb477b8bfb6e58f5c9e32f7219dd83444ac3302576d801b9c95578", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "c32f4b71d3b8a87ef3656235c0c35d7160425e41fdb1c705916c9a7ac8f99fdd", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "c32f4b71d3b8a87ef3656235c0c35d7160425e41fdb1c705916c9a7ac8f99fdd", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "c32f4b71d3b8a87ef3656235c0c35d7160425e41fdb1c705916c9a7ac8f99fdd", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:scverse_scanpy:4296"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Reorg io functions |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-02 — existing Phase 2 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-02` |
| source_seed_id | `github:scverse_scanpy:4336` | `github:scverse_scanpy:4336` |
| raw title/question | **Title:** `rank_genes_groups(method="t-test", mean_in_log_space=False)` runs the t-test on exponentiated values<br>**Question:** `rank_genes_groups(method="t-test", mean_in_log_space=False)` runs the t-test on exponentiated values | — |
| source provenance | {"canonical_url": "https://github.com/scverse/scanpy/issues/4336", "collected_at": "2026-09-20T16:04:52Z", "collection": "scverse/scanpy issues", "collection_method": "official_api", "external_id": "4336", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "07ae559fd7c69d472ec3e473482acd7e9a074545004f832da95587444bc2d2aa", "version_context": {"issue_state": "open", "labels_csv": "Triage 🩺", "repository": "scverse/scanpy"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "07ae559fd7c69d472ec3e473482acd7e9a074545004f832da95587444bc2d2aa", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "6143902a8df74221773369916041197d08a7338f87fc8682d0ba2c8682e10638", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "6143902a8df74221773369916041197d08a7338f87fc8682d0ba2c8682e10638", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "6143902a8df74221773369916041197d08a7338f87fc8682d0ba2c8682e10638", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:scverse_scanpy:4336"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | `rank_genes_groups(method="t-test", mean_in_log_space=False)` runs the t-test on exponentiated values |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-03 — existing Phase 2 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-03` |
| source_seed_id | `github:satijalab_seurat:10416` | `github:satijalab_seurat:10416` |
| raw title/question | **Title:** Feature Request: Change the default value of `margin` parameter to 2 in `NormalizeData()` for CLR normalization<br>**Question:** Feature Request: Change the default value of `margin` parameter to 2 in `NormalizeData()` for CLR normalization | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10416", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10416", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "146d86cd4038ad8a468316d792b2eba390dfed7515bd3214d46e0b710c9bcd4c", "version_context": {"issue_state": "open", "labels_csv": "enhancement", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "146d86cd4038ad8a468316d792b2eba390dfed7515bd3214d46e0b710c9bcd4c", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "816c3b40e0a1e3d093cdd40ec637465a2fd295e129ecd4b1aa9200430b606011", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "816c3b40e0a1e3d093cdd40ec637465a2fd295e129ecd4b1aa9200430b606011", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "816c3b40e0a1e3d093cdd40ec637465a2fd295e129ecd4b1aa9200430b606011", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10416"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Feature Request: Change the default value of `margin` parameter to 2 in `NormalizeData()` for CLR normalization |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-04 — existing Phase 2 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-04` |
| source_seed_id | `controlled:state-partial-notebook` | `controlled:state-partial-notebook` |
| raw title/question | **Title:** A notebook stopped after neighbors were recomputed but before UMAP and clustering were rerun. How should an agent determine which artifacts are stale before resuming?<br>**Question:** A notebook stopped after neighbors were recomputed but before UMAP and clustering were rerun. How should an agent determine which artifacts are stale before resuming? | — |
| source provenance | {"canonical_url": "urn:sckg:benchmark-v3:controlled-probe:state-partial-notebook", "collected_at": "2026-09-20T16:04:52Z", "collection": "benchmark-v3-controlled-probes", "collection_method": "controlled_generation", "external_id": "state-partial-notebook", "license_or_access_policy": {"access_mode": "controlled_generated", "license_identifier": "project-owned", "notes": "Project-authored probe; no external user content.", "policy_review_status": "reviewed", "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "full_text"}, "raw_record_sha256": "46b56189ca414bda98b27f1b67e2cf765cc81bce58595bf803f182879bfd7fa4", "version_context": {"generator_version": "v1", "probe_family": "state-and-representation"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "controlled:state-partial-notebook"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | A notebook stopped after neighbors were recomputed but before UMAP and clustering were rerun. How should an agent determine which artifacts are stale before resuming? |
| ambiguities | — | ["The controlled probe has no expected answer, source bundle, or expected trajectory in this phase."] |
| public_exposure | — | `project-controlled-not-public` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `low` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-05 — existing Phase 2 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-05` |
| source_seed_id | `controlled:evidence-version-conflict` | `controlled:evidence-version-conflict` |
| raw title/question | **Title:** The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation?<br>**Question:** The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation? | — |
| source provenance | {"canonical_url": "urn:sckg:benchmark-v3:controlled-probe:evidence-version-conflict", "collected_at": "2026-09-20T16:04:52Z", "collection": "benchmark-v3-controlled-probes", "collection_method": "controlled_generation", "external_id": "evidence-version-conflict", "license_or_access_policy": {"access_mode": "controlled_generated", "license_identifier": "project-owned", "notes": "Project-authored probe; no external user content.", "policy_review_status": "reviewed", "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "full_text"}, "raw_record_sha256": "a942f30d93b42cbceb8e2a9f011394d6c5a6ecf3433f83d8ffadf10b0de836e9", "version_context": {"generator_version": "v1", "probe_family": "scope-and-evidence"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "controlled:evidence-version-conflict"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation? |
| ambiguities | — | ["The controlled probe has no expected answer, source bundle, or expected trajectory in this phase."] |
| public_exposure | — | `project-controlled-not-public` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `low` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-06 — existing Phase 2 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-06` |
| source_seed_id | `controlled:validation-empty-artifact` | `controlled:validation-empty-artifact` |
| raw title/question | **Title:** A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion?<br>**Question:** A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion? | — |
| source provenance | {"canonical_url": "urn:sckg:benchmark-v3:controlled-probe:validation-empty-artifact", "collected_at": "2026-09-20T16:04:52Z", "collection": "benchmark-v3-controlled-probes", "collection_method": "controlled_generation", "external_id": "validation-empty-artifact", "license_or_access_policy": {"access_mode": "controlled_generated", "license_identifier": "project-owned", "notes": "Project-authored probe; no external user content.", "policy_review_status": "reviewed", "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "full_text"}, "raw_record_sha256": "0e6fd42586b3d87d5491f9702f88ad86805da72ba94c52d9e2c8300fd06b5283", "version_context": {"generator_version": "v1", "probe_family": "execution-and-validation"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "controlled:validation-empty-artifact"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion? |
| ambiguities | — | ["The controlled probe has no expected answer, source bundle, or expected trajectory in this phase."] |
| public_exposure | — | `project-controlled-not-public` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `low` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-07 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-07` |
| source_seed_id | `github:satijalab_seurat:10406` | `github:satijalab_seurat:10406` |
| raw title/question | **Title:** BUG: Potential issue in parallel memory usage<br>**Question:** BUG: Potential issue in parallel memory usage | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10406", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10406", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "48f18837552cc43834a2ae44fbefd32344b3648f00263ec7d62bff2b2835e77d", "version_context": {"issue_state": "open", "labels_csv": "bug", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "48f18837552cc43834a2ae44fbefd32344b3648f00263ec7d62bff2b2835e77d", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "3af6bc83b09030b8c102bfd3b55d542cad194f708d15da95ba0d6982ff9297a2", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "3af6bc83b09030b8c102bfd3b55d542cad194f708d15da95ba0d6982ff9297a2", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "3af6bc83b09030b8c102bfd3b55d542cad194f708d15da95ba0d6982ff9297a2", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10406"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | BUG: Potential issue in parallel memory usage |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-08 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-08` |
| source_seed_id | `github:satijalab_seurat:10409` | `github:satijalab_seurat:10409` |
| raw title/question | **Title:** PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero)<br>**Question:** PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero) | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10409", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10409", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "ace45910e68bfcc737ffce8634e2c8f4684f389a5527dd7a0b80c211b000addb", "version_context": {"issue_state": "closed", "labels_csv": "bug", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "ace45910e68bfcc737ffce8634e2c8f4684f389a5527dd7a0b80c211b000addb", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "40680ac98f4423560fbd64d114532947f6c1fd2334a1e4e56c370a2bc22fa5b4", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "40680ac98f4423560fbd64d114532947f6c1fd2334a1e4e56c370a2bc22fa5b4", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "40680ac98f4423560fbd64d114532947f6c1fd2334a1e4e56c370a2bc22fa5b4", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10409"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero) |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-09 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-09` |
| source_seed_id | `github:satijalab_seurat:10415` | `github:satijalab_seurat:10415` |
| raw title/question | **Title:** RNA assay has no layers after running harmony integration followed by rejoining layers<br>**Question:** RNA assay has no layers after running harmony integration followed by rejoining layers | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10415", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10415", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "0056e905f1005ad260fd89b6c5804a9d846ee88f237e4df00c45ce3f38d91290", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "0056e905f1005ad260fd89b6c5804a9d846ee88f237e4df00c45ce3f38d91290", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "5717d0bea895c6945b3ad63169a4b1d974469830f9c8851fcb2e33dddc418b25", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "5717d0bea895c6945b3ad63169a4b1d974469830f9c8851fcb2e33dddc418b25", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "5717d0bea895c6945b3ad63169a4b1d974469830f9c8851fcb2e33dddc418b25", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10415"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | RNA assay has no layers after running harmony integration followed by rejoining layers |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-10 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-10` |
| source_seed_id | `github:satijalab_seurat:10425` | `github:satijalab_seurat:10425` |
| raw title/question | **Title:** Does FindClusters order/renumber clusters by size (largest cluster first)<br>**Question:** Does FindClusters order/renumber clusters by size (largest cluster first) | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10425", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10425", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "d9bcf55f270886d95698e94e97b9c2bfdf73051bb8316066a139b7514e37ef27", "version_context": {"issue_state": "open", "labels_csv": "bug", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "d9bcf55f270886d95698e94e97b9c2bfdf73051bb8316066a139b7514e37ef27", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "99d30e12928d61a566d6ea210627fb3abf7324be86c9e0e78f62aa6c64d74208", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "99d30e12928d61a566d6ea210627fb3abf7324be86c9e0e78f62aa6c64d74208", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "99d30e12928d61a566d6ea210627fb3abf7324be86c9e0e78f62aa6c64d74208", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10425"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Does FindClusters order/renumber clusters by size (largest cluster first) |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-11 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-11` |
| source_seed_id | `github:satijalab_seurat:10436` | `github:satijalab_seurat:10436` |
| raw title/question | **Title:** BUG: FindClusters function always fall back to Louvain clustering even if I tried both leidenbase and igraph methods<br>**Question:** BUG: FindClusters function always fall back to Louvain clustering even if I tried both leidenbase and igraph methods | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10436", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10436", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "bf118b39c15fc0b2e9f8dc350dc1e0a2d757a1820a42365d936d4d29842f03f0", "version_context": {"issue_state": "open", "labels_csv": "bug", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "bf118b39c15fc0b2e9f8dc350dc1e0a2d757a1820a42365d936d4d29842f03f0", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "fabd602e2370274cde2e1ed6a74d1703a0650a5465cb2456a160ef8fc94fd706", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "fabd602e2370274cde2e1ed6a74d1703a0650a5465cb2456a160ef8fc94fd706", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "fabd602e2370274cde2e1ed6a74d1703a0650a5465cb2456a160ef8fc94fd706", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10436"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | BUG: FindClusters function always fall back to Louvain clustering even if I tried both leidenbase and igraph methods |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-12 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-12` |
| source_seed_id | `github:satijalab_seurat:10445` | `github:satijalab_seurat:10445` |
| raw title/question | **Title:** BUG: MapQuery gives aberrant results if reference is subset after RunUMAP<br>**Question:** BUG: MapQuery gives aberrant results if reference is subset after RunUMAP | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10445", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10445", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "95aa70dc42d3d797fdee998d6ef0b1ce250e7bcbd1bd395470a820b9ed494225", "version_context": {"issue_state": "open", "labels_csv": "bug", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "95aa70dc42d3d797fdee998d6ef0b1ce250e7bcbd1bd395470a820b9ed494225", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "275008220bfbaa6988ff0f51bf435be24355c9d3a5562aca3bbb8b90554304a7", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "275008220bfbaa6988ff0f51bf435be24355c9d3a5562aca3bbb8b90554304a7", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "275008220bfbaa6988ff0f51bf435be24355c9d3a5562aca3bbb8b90554304a7", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10445"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | BUG: MapQuery gives aberrant results if reference is subset after RunUMAP |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-13 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-13` |
| source_seed_id | `github:satijalab_seurat:10502` | `github:satijalab_seurat:10502` |
| raw title/question | **Title:** RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults<br>**Question:** RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults | — |
| source provenance | {"canonical_url": "https://github.com/satijalab/seurat/issues/10502", "collected_at": "2026-09-20T16:04:52Z", "collection": "satijalab/seurat issues", "collection_method": "official_api", "external_id": "10502", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "f39d8ba44ebdc351c5df101b9c2e2065d38783374f1bb97a76b3e807655c1e61", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "satijalab/seurat"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "f39d8ba44ebdc351c5df101b9c2e2065d38783374f1bb97a76b3e807655c1e61", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "f06f226a19b93ef8dc71e64a155ca5ca42441cbfa779dbb4d3f48d7623ecae03", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "f06f226a19b93ef8dc71e64a155ca5ca42441cbfa779dbb4d3f48d7623ecae03", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "f06f226a19b93ef8dc71e64a155ca5ca42441cbfa779dbb4d3f48d7623ecae03", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:satijalab_seurat:10502"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-14 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-14` |
| source_seed_id | `github:scverse_scanpy:4318` | `github:scverse_scanpy:4318` |
| raw title/question | **Title:** sc.pl.paga raises TypeError when cax is passed with multiple colors<br>**Question:** sc.pl.paga raises TypeError when cax is passed with multiple colors | — |
| source provenance | {"canonical_url": "https://github.com/scverse/scanpy/issues/4318", "collected_at": "2026-09-20T16:04:52Z", "collection": "scverse/scanpy issues", "collection_method": "official_api", "external_id": "4318", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "67feef213516d58bfa2cc32c5b64f4d6e248b4e1011f5a9eb043bcae0678f8ea", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "scverse/scanpy"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "67feef213516d58bfa2cc32c5b64f4d6e248b4e1011f5a9eb043bcae0678f8ea", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "52eb24996f8a01147e69dc567edeed253d060aeba30a0f3c681fecba8205cb5d", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "52eb24996f8a01147e69dc567edeed253d060aeba30a0f3c681fecba8205cb5d", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "52eb24996f8a01147e69dc567edeed253d060aeba30a0f3c681fecba8205cb5d", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:scverse_scanpy:4318"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | sc.pl.paga raises TypeError when cax is passed with multiple colors |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-15 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-15` |
| source_seed_id | `github:scverse_scanpy:4347` | `github:scverse_scanpy:4347` |
| raw title/question | **Title:** `calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var`<br>**Question:** `calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var` | — |
| source provenance | {"canonical_url": "https://github.com/scverse/scanpy/issues/4347", "collected_at": "2026-09-20T16:04:52Z", "collection": "scverse/scanpy issues", "collection_method": "official_api", "external_id": "4347", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "63f705c873531d4cabae009bcac0d8e09569b5c879cac3f7a093e8fd19023875", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "scverse/scanpy"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "63f705c873531d4cabae009bcac0d8e09569b5c879cac3f7a093e8fd19023875", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "521f4fb238f1caa464cf6ad190a370c7e6e755afeaff95e8ae46bdbc95ecb575", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "521f4fb238f1caa464cf6ad190a370c7e6e755afeaff95e8ae46bdbc95ecb575", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "521f4fb238f1caa464cf6ad190a370c7e6e755afeaff95e8ae46bdbc95ecb575", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:scverse_scanpy:4347"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | `calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var` |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-16 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-16` |
| source_seed_id | `github:scverse_scanpy:4370` | `github:scverse_scanpy:4370` |
| raw title/question | **Title:** `highly_variable_genes` with `batch_key` and `subset=True` keeps the wrong genes when `n_top_genes` is not set<br>**Question:** `highly_variable_genes` with `batch_key` and `subset=True` keeps the wrong genes when `n_top_genes` is not set | — |
| source provenance | {"canonical_url": "https://github.com/scverse/scanpy/issues/4370", "collected_at": "2026-09-20T16:04:52Z", "collection": "scverse/scanpy issues", "collection_method": "official_api", "external_id": "4370", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "raw_record_sha256": "2d94b27384de969618db3db70778d6e0f5d63c0cb8048668039f42f7b47b34bb", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "scverse/scanpy"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [{"input_sha256": "2d94b27384de969618db3db70778d6e0f5d63c0cb8048668039f42f7b47b34bb", "notes": "Extracted the issue title from a minimal in-memory API projection; body and comments were not stored.", "operation": "title_extraction", "output_sha256": "4c9c952d5ab03f46f20f0b5dd75eb314d7e4e3169dab900a13e908dc48081be1", "performed_at": "2026-09-20T16:04:52Z", "sequence": 1, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}, {"input_sha256": "4c9c952d5ab03f46f20f0b5dd75eb314d7e4e3169dab900a13e908dc48081be1", "notes": "Applied NFC normalization and folded whitespace without changing case or wording.", "operation": "whitespace_normalization", "output_sha256": "4c9c952d5ab03f46f20f0b5dd75eb314d7e4e3169dab900a13e908dc48081be1", "performed_at": "2026-09-20T16:04:52Z", "sequence": 2, "tool_id": "sckg-benchmark-v3-github-title-pilot", "tool_version": "1.0.0"}] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "github:scverse_scanpy:4370"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | `highly_variable_genes` with `batch_key` and `subset=True` keeps the wrong genes when `n_top_genes` is not set |
| ambiguities | — | ["Only the public issue title was collected; body, reproducer, versions, object state, and intended outcome are missing.", "Issue status and maintainer discussion were not collected and cannot be treated as an answer."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-17 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-17` |
| source_seed_id | `paper:bixbench:bix-33-q1` | `paper:bixbench:bix-33-q1` |
| raw title/question | **Title:** futurehouse/BixBench bix-33-q1<br>**Question:** Which immune cell type has the highest number of significantly differentially expressed genes after AAV9 mini-dystrophin treatment? | — |
| source provenance | {"canonical_url": "https://huggingface.co/datasets/futurehouse/BixBench/viewer/default/train?row=92", "collected_at": "2026-09-20T16:43:37Z", "collection": "futurehouse/BixBench", "collection_method": "official_api", "external_id": "bix-33-q1", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "Apache-2.0", "notes": "Stores one public task instruction plus non-answer metadata from a pinned release. No ideal answer, result, distractor, domain-knowledge field, gold program, dataset artifact, or scoring rubric is retained.", "policy_review_status": "reviewed", "policy_url": "https://huggingface.co/datasets/futurehouse/BixBench/blob/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/README.md", "reviewed_at": "2026-09-20T16:43:37Z", "storage_permission": "excerpt"}, "raw_record_sha256": "4aa1624d1561c4cac06a392b193c15df5e606067aefd69eff015a5a8c7db9d15", "version_context": {"categories": "Single-Cell Analysis,Differential Expression Analysis", "dataset_revision": "f8cc3bdcc6357c88b8c3648306522b9c422dc95a", "paper_or_repository": "https://doi.org/10.5281/zenodo.13935259", "row_index": 92, "short_id": "bix-33"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "paper:bixbench:bix-33-q1"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Which immune cell type has the highest number of significantly differentially expressed genes after AAV9 mini-dystrophin treatment? |
| ambiguities | — | ["The benchmark instruction refers to external data/artifacts that were not imported into this pilot.", "The upstream answer, result, Gold program, and rubric are intentionally not inherited."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-18 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-18` |
| source_seed_id | `paper:bixbench:bix-1-q1` | `paper:bixbench:bix-1-q1` |
| raw title/question | **Title:** futurehouse/BixBench bix-1-q1<br>**Question:** Using the provided RNA-seq count data and metadata files, perform DESeq2 differential expression analysis to identify significant DEGs (padj < 0.05), then run enrichGO analysis with clusterProfiler::simplify() (similarity > 0.7). What is the approximate adjusted p-value (rounded to 4 decimal points) for "regulation of T cell activation" in the resulting simplified GO enrichment results? | — |
| source provenance | {"canonical_url": "https://huggingface.co/datasets/futurehouse/BixBench/viewer/default/train?row=0", "collected_at": "2026-09-20T16:43:37Z", "collection": "futurehouse/BixBench", "collection_method": "official_api", "external_id": "bix-1-q1", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "Apache-2.0", "notes": "Stores one public task instruction plus non-answer metadata from a pinned release. No ideal answer, result, distractor, domain-knowledge field, gold program, dataset artifact, or scoring rubric is retained.", "policy_review_status": "reviewed", "policy_url": "https://huggingface.co/datasets/futurehouse/BixBench/blob/f8cc3bdcc6357c88b8c3648306522b9c422dc95a/README.md", "reviewed_at": "2026-09-20T16:43:37Z", "storage_permission": "excerpt"}, "raw_record_sha256": "5ce8fb7ce374d459bdd5beac867b5febb35dddfbfc4b755a47c9bad3b3b7a591", "version_context": {"categories": "RNA-seq,Differential Expression Analysis,Transcriptomics,Network Biology", "dataset_revision": "f8cc3bdcc6357c88b8c3648306522b9c422dc95a", "paper_or_repository": "https://doi.org/10.1172/jci.insight.167744", "row_index": 0, "short_id": "bix-1"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "paper:bixbench:bix-1-q1"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Using the provided RNA-seq count data and metadata files, perform DESeq2 differential expression analysis to identify significant DEGs (padj < 0.05), then run enrichGO analysis with clusterProfiler::simplify() (similarity > 0.7). What is the approximate adjusted p-value (rounded to 4 decimal points) for "regulation of T cell activation" in the resulting simplified GO enrichment results? |
| ambiguities | — | ["The benchmark instruction refers to external data/artifacts that were not imported into this pilot.", "The upstream answer, result, Gold program, and rubric are intentionally not inherited."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-19 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-19` |
| source_seed_id | `paper:scienceagentbench:verified-instance-11` | `paper:scienceagentbench:verified-instance-11` |
| raw title/question | **Title:** osunlp/ScienceAgentBench verified-instance-11<br>**Question:** Train a cell counting model on the BBBC002 datasets containing Drosophila KC167 cells. Save the test set predictions as a single column "count" to "pred_results/cell-count_pred.csv". | — |
| source provenance | {"canonical_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/viewer/default/verified?row=10", "collected_at": "2026-09-20T16:43:37Z", "collection": "osunlp/ScienceAgentBench", "collection_method": "official_api", "external_id": "verified-instance-11", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "CC-BY-4.0", "notes": "Stores one public task instruction plus non-answer metadata from a pinned release. No ideal answer, result, distractor, domain-knowledge field, gold program, dataset artifact, or scoring rubric is retained.", "policy_review_status": "reviewed", "policy_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/blob/9c6e96c9e74572e979b0930ee735041cef528cb7/README.md", "reviewed_at": "2026-09-20T16:43:37Z", "storage_permission": "excerpt"}, "raw_record_sha256": "647d11895b1329758a9daa251f6433c272206111db595e0eb1f4635262e6e91e", "version_context": {"categories": "Bioinformatics; Deep Learning", "dataset_revision": "9c6e96c9e74572e979b0930ee735041cef528cb7", "paper_or_repository": "https://github.com/deepchem/deepchem", "row_index": 10, "short_id": "instance-11"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "paper:scienceagentbench:verified-instance-11"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Train a cell counting model on the BBBC002 datasets containing Drosophila KC167 cells. Save the test set predictions as a single column "count" to "pred_results/cell-count_pred.csv". |
| ambiguities | — | ["The benchmark instruction refers to external data/artifacts that were not imported into this pilot.", "The upstream answer, result, Gold program, and rubric are intentionally not inherited."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |

## candidate-pilot-20 — new Phase 2.1 candidate

| Field | Raw seed / source | Candidate draft |
| --- | --- | --- |
| candidate_id | — | `candidate-pilot-20` |
| source_seed_id | `paper:scienceagentbench:verified-instance-12` | `paper:scienceagentbench:verified-instance-12` |
| raw title/question | **Title:** osunlp/ScienceAgentBench verified-instance-12<br>**Question:** Train a drug-target interaction model using the DAVIS dataset to determine the binding affinity between several drugs and targets. Then use the trained model to predict the binding affinities between antiviral drugs and COVID-19 target. Rank the antiviral drugs based on their predicted affinities and save the ordered list of drugs to "pred_results/davis_dti_repurposing.txt", with one drug name per line. | — |
| source provenance | {"canonical_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/viewer/default/verified?row=11", "collected_at": "2026-09-20T16:43:37Z", "collection": "osunlp/ScienceAgentBench", "collection_method": "official_api", "external_id": "verified-instance-12", "license_or_access_policy": {"access_mode": "official_api", "license_identifier": "CC-BY-4.0", "notes": "Stores one public task instruction plus non-answer metadata from a pinned release. No ideal answer, result, distractor, domain-knowledge field, gold program, dataset artifact, or scoring rubric is retained.", "policy_review_status": "reviewed", "policy_url": "https://huggingface.co/datasets/osunlp/ScienceAgentBench/blob/9c6e96c9e74572e979b0930ee735041cef528cb7/README.md", "reviewed_at": "2026-09-20T16:43:37Z", "storage_permission": "excerpt"}, "raw_record_sha256": "9c1d8b02a6a018f9fae282725765c7405f94121c57ceefea72f1c3f24fd2812c", "version_context": {"categories": "Bioinformatics; Feature Engineering; Deep Learning", "dataset_revision": "9c6e96c9e74572e979b0930ee735041cef528cb7", "paper_or_repository": "https://github.com/kexinhuang12345/DeepPurpose", "row_index": 11, "short_id": "instance-12"}} | Preserved by reference; not rewritten into user text. |
| transformation history | Raw: [] | Candidate: [{"notes": "Verbatim identity draft for reviewability. No scientific fact, package behavior, version, dataset property, or answer content was added.", "operation": "identity_draft", "source_seed_id": "paper:scienceagentbench:verified-instance-12"}] |
| added context | — | [] |
| removed context | — | [] |
| added scientific context | — | **NONE — no scientific fact was added.** |
| draft_query | — | Train a drug-target interaction model using the DAVIS dataset to determine the binding affinity between several drugs and targets. Then use the trained model to predict the binding affinities between antiviral drugs and COVID-19 target. Rank the antiviral drugs based on their predicted affinities and save the ordered list of drugs to "pred_results/davis_dti_repurposing.txt", with one drug name per line. |
| ambiguities | — | ["The benchmark instruction refers to external data/artifacts that were not imported into this pilot.", "The upstream answer, result, Gold program, and rubric are intentionally not inherited."] |
| public_exposure | — | `public-source` |
| verbatim_overlap | — | `1.0` (`normalized-identity-v1`) |
| transformation_distance | — | `0.0` |
| memorization_risk | — | `high` |
| review / Gold | — | `needs_adjudication` / `none` |
