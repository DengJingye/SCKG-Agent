# Midterm Project Evidence Snapshot v1

Measurement HEAD: `66430343e3e2b96a9dc6884137523923c8667e74`. Branch: `feature/method-kg-expansion-v1`. Snapshot date: 2026-09-19.

Repository freeze completed with recorded regression debt. This is an evidence aggregation, not a release-readiness claim.

## Classification contract

Every metric belongs to `CURRENT_MEASURED`, `FROZEN_HISTORICAL`, `DEVELOPMENT_RESULT`, or `NOT_RUN`. Recounting an old artifact verifies its present bytes, not the result of a fresh experiment. Machine-readable values, denominators, source identities and limitations are in `data/evaluation/midterm_project_snapshot_v1/metrics.json`; source hashes are in `artifact_index.json`.

## Repository identity [CURRENT_MEASURED]

Remote baseline before push: `4d2e44e70b99f1f2c595875929f088376eaf7020`. The commit containing this document is the independent snapshot commit. No production files changed during this freeze.

| Checkpoint | Verified ancestor |
|---|---|
| retrieval_foundation | `3c120e1a262559d1e858273a6fbd8feea10f29dd` |
| retrieval_strengthening | `67c04268f2865a1a2728756a4b86800c271ee758` |
| retrieval_benchmark_v1_1_1 | `52d1d1d8ee54dc035e88c3f855cee59a35023607` |
| core_planner_integration | `22a1dc9515ca18676e34a51017926a84d346a6fb` |
| capability_readiness_gate | `387625250cf791bb946746020593eb009d64eee3` |
| capability_readiness_resolution | `8416a8f3299135d1079dd4e7a23cf8d6f50088f3` |
| celltypist_runtime_qualification | `66430343e3e2b96a9dc6884137523923c8667e74` |

## Scientific KG inventory [CURRENT_MEASURED]

Legacy catalog graph: 7537 nodes / 17667 edges. Decision Graph: 1058 nodes / 1318 edges.

The consolidated view contains 1651 nodes and 2429 edges across 4 preserved layers and 22 listed ecosystems. It is a multi-layer inventory, not a deduplicated trusted KG.

Frozen Core candidate: 236 AtomicClaims, 171 derived relations, 87 evidence spans. Corrected UAT overlay: 25 claims and 29 derived relations. Candidate records have not been globally promoted.

## RAG/index inventory [CURRENT_MEASURED]

| Surface | Evidence chunks | Source-bound | Catalog chunks | Dense shape |
|---|---:|---:|---:|---|
| production_default | 783 | 773 | 1847 | 773 × 1024 |
| strengthened_benchmark_snapshot | 800 | 790 | 1847 | 790 × 1024 |

The production default remains `data/indexes`. The strengthened development snapshot remains `data/indexes/retrieval_foundation_v1`; its benchmark gains cannot be attributed automatically to the default product path. Both dense corpus digests were recomputed and match their metadata. Model: BAAI/bge-m3, revision `cb1779f90b988b8deb01f9155c790ef9417d7648`. The legacy source-document registry has 37 rows; this is not the number of distinct sources represented by every candidate overlay.

## Retrieval benchmark [DEVELOPMENT_RESULT]

Frozen v1.1.1 DEV is COMPLETE. Scientific evidence uses 45 query units; catalog discovery uses 12 separate units. No campaign was rerun.

| Profile | Evidence Recall@10 | Evidence MRR | Discovery Recall@10 |
|---|---:|---:|---:|
| R0_bm25_only | 31/45 | 0.381966 | 3/12 |
| R1_dense_only | 25/45 | 0.338422 | 5/12 |
| R2_bm25_dense_rrf | 31/45 | 0.340265 | 4/12 |
| R3_kg_bm25_dense_rrf | 31/45 | 0.340265 | 5/12 |
| R4_kg_bm25_dense_rrf_governance | 31/45 | 0.380511 | 4/12 |

All frozen primary metrics, scope/version denominators and task-independent profile definitions remain in metrics.json. BM25 and hybrid evidence Recall@10 reached 31/45 in the strengthened snapshot; their v1 values were 19/45 and 18/45. KG: HELPED 2, NEUTRAL 55, HURT 0; false-filter rate 0. Governance: HELPED 8, NEUTRAL 43, HURT 6. These counts cover the combined 57-query development panel; they are not independent chunk samples. The preserved INVALID v1.1 result remains diagnostic-only.

## Planner/readiness [DEVELOPMENT_RESULT]

Frozen eight-case production-path result: requirement/action correctness 8/8, evidence fidelity 8/8, unsafe allow 0/8, false block 0/8, behavior changes versus no-op 0/8. This supports explanation quality, not demonstrated behavioral superiority.

Inherited readiness remains planning-ready 3/14 (Scanpy, Harmony, Scrublet), authoritative-evidence-ready 13/14, execution-ready contracts/environments 2/14, retrieval-only 6/14. Execution readiness does not override disabled policy. This checkpoint did not re-adjudicate the matrix.

CellTypist now has a verified artifact and bounded runtime smoke, but no production Capability Pack/Planner binding was added. SoupX and scVelo still require actual human ReviewDecisions. SingleR/reference and scVelo→CellRank gaps are not silently resolved.

## Evidence fidelity [FROZEN_HISTORICAL]

CP4.7 v1.2 formal PASS remains preserved: recall 5/5, decision precision 5/5, extras 0, runtime citation abstention 7/7, ownership 12/12, scope 5/5, epistemic 5/5, concrete representation links 6/6 plus explicit absence 1/1, negative controls 8/8, behavior invariance 4/4. Formal ordinal remains 1.

This result belongs to the historical SUT SHA `9d40f3ef06c3eff8653ebf8afc6d7a2995cd25aae76fa1d44bd6e6de45307722`. Current accepted applicability code has a different SHA after Core integration. No claim of a new current-SUT formal PASS is made. Earlier contribution evaluation separately found behavior gain 0/4, explanation gain 4/4, regressions 0/4.

## Candidate self-evolution [DEVELOPMENT_RESULT]

The bounded SoupX CP5→CP6→CP7 pilot records one acquired source/span, one candidate claim, one pending review item and reuse with zero external reacquisition. Claim `claim-revision:cp6:7005e7aaf1f910d6:1` remains `candidate_pending_review`. ReviewDecision count and canonical promotions remain zero in the recorded pilot. Downstream scientific utility was not established. Full local audits remain intentionally untracked; this snapshot preserves their compact values and hashes.

## Governance/safety [CURRENT_MEASURED / DEVELOPMENT_RESULT]

Code default ExecutionPolicy remains disabled. No promotion, capability integration, authority grant or runtime policy change was performed here. Live application policy was not re-probed. Candidate knowledge is not trusted by this freeze.

## CellTypist runtime qualification [DEVELOPMENT_RESULT]

Frozen qualification PASS at `66430343e3e2b96a9dc6884137523923c8667e74`: official Immune_All_Low v2 digest, human pan-immune scope, 6,639 features, 98 labels; Python 3.9.23 / CellTypist 1.7.1 / scikit-learn 0.24.1. Two deterministic synthetic inference runs and one process-level socket-guard run were recorded. No biological accuracy claim follows. The local pack, pickle, runtime environment and absolute paths are excluded from Git. Default production registry/runtime-pack installation remains separate.

## Real-data evidence [CURRENT_MEASURED artifact inspection; FROZEN_HISTORICAL execution]

| Path | Existing code cells/executed | Error outputs | PNG outputs | Input matches frozen SHA now |
|---|---:|---:|---:|---|
| processed | 2/2 | 0 | 0 | True |
| raw | 17/17 | 0 | 5 | True |

Actual PBMC3k executions and reuse/11-step-DAG observations are historical, documented in PROJECT_RETROSPECTIVE_V1.md. Notebook files and inputs were read/hash-checked only. No new Jupyter execution or cross-dataset validation was run.

## Regression snapshot [CURRENT_MEASURED]

Full suite at measurement HEAD: **1020 passed, 10 failed, 3 setup errors, 0 skipped, 8 warnings**, 1407.26 seconds. This is not a green suite.

| Classification | Outcomes | Evidence |
|---|---:|---|
| PREEXISTING | 9 | Same failures reproduced on isolated parent 8416a8f |
| EXPECTED_ARTIFACT_STATE | 4 | One failure + three setup errors: frozen v1.2 runner rejects later SUT hash; exact failure reproduced after providing preserved historical request input |
| NEW | 0 | No new failing test outcome attributable to qualification/freeze |
| ENVIRONMENTAL | 0 | No remaining outcome assigned this class |

Complete node IDs and causes are in metrics.json. Parent reproduction was diagnostic and did not rerun canonical formal evaluation.

A separate test-isolation defect was observed: the Seed module autouse fixture runs its generator against repository paths. Its unbounded file enumeration included later retrieval campaigns and .DS_Store, changing two frozen Seed manifests. The side-effect diff was preserved; only these test-owned writes were restored byte-for-byte to pre-run HEAD. No gold semantics or test implementation was repaired. This remains regression-suite debt even though it did not fail an assertion.

Raw regression logs and recovery patch are preserved locally under `.sckg_exec/reports/midterm-project-snapshot-v1/`; hashes and compact failure results are committed. Historical formal and retrieval artifact groups match measurement HEAD. No preserved formal artifacts were deleted to make tests pass.

## Not run [NOT_RUN]

Formal Midterm holdout, Seed v1, current-HEAD real-data/Jupyter replay, retrieval benchmark rerun, CP4.7 formal rerun, new capability integration and CellTypist biological accuracy evaluation.

## Freeze scope

Only this document and the three requested snapshot artifacts are in the snapshot commit. Existing development/audit directories remain excluded. Push verification is performed after this immutable snapshot commit and reported by the task; main is not merged and no release/tag is created.
