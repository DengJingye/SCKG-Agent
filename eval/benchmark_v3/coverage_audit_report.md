# Phase 2.2 Lane-aligned Coverage Re-audit

Run: `lane-alignment-20260921-v1`

Status: candidate coverage proposal only; `needs_adjudication`, `gold_status=none`.

The Phase 2.1 coverage conclusion is superseded. The V2 bit now uses only the actual
approved-v2 consumer at the 07 integration commit. ToolContracts and all other shared
runtime components are excluded. Legacy and RAG use the exact paired backends from 07.

Signature counts: `{"000": 20}`.

| candidate | admission | track | required fact/condition (first) | V2 | Legacy | RAG | signature |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `candidate-pilot-01` | `demoted_to_raw_only` | `O` | The exact version-bound behavior for the reported software api organization condition. | absent | absent | absent | `000` |
| `candidate-pilot-02` | `retained` | `K` | The exact version-bound behavior for the reported differential expression statistics condition. | absent | absent | absent | `000` |
| `candidate-pilot-03` | `retained` | `K` | The exact version-bound behavior for the reported normalization parameter semantics condition. | absent | absent | absent | `000` |
| `candidate-pilot-04` | `retained` | `W` | Artifact lineage showing which UMAP and clustering outputs depend on the recomputed neighbor graph. | absent | absent | absent | `000` |
| `candidate-pilot-05` | `retained` | `K` | The installed Scanpy version and the API signature valid for that exact version. | absent | absent | absent | `000` |
| `candidate-pilot-06` | `retained` | `W` | A successful process exit is insufficient when a required artifact fails its declared validator. | absent | absent | absent | `000` |
| `candidate-pilot-07` | `demoted_to_raw_only` | `O` | The exact version-bound behavior for the reported resource and parallelism condition. | absent | absent | absent | `000` |
| `candidate-pilot-08` | `retained` | `O` | The exact version-bound behavior for the reported normalization and count correction condition. | absent | absent | absent | `000` |
| `candidate-pilot-09` | `retained` | `O` | The exact version-bound behavior for the reported object state and layers condition. | absent | absent | absent | `000` |
| `candidate-pilot-10` | `retained` | `K` | The exact version-bound behavior for the reported clustering label semantics condition. | absent | absent | absent | `000` |
| `candidate-pilot-11` | `retained` | `O` | The exact version-bound behavior for the reported clustering backend selection condition. | absent | absent | absent | `000` |
| `candidate-pilot-12` | `retained` | `O` | The exact version-bound behavior for the reported reference mapping and subsetting condition. | absent | absent | absent | `000` |
| `candidate-pilot-13` | `retained` | `O` | The exact version-bound behavior for the reported reproducibility and rng condition. | absent | absent | absent | `000` |
| `candidate-pilot-14` | `retained` | `O` | The exact version-bound behavior for the reported visualization api error condition. | absent | absent | absent | `000` |
| `candidate-pilot-15` | `retained` | `O` | The exact version-bound behavior for the reported quality control and raw state condition. | absent | absent | absent | `000` |
| `candidate-pilot-16` | `retained` | `O` | The exact version-bound behavior for the reported feature selection and batch state condition. | absent | absent | absent | `000` |
| `candidate-pilot-17` | `retained` | `W` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |
| `candidate-pilot-18` | `retained` | `W` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |
| `candidate-pilot-19` | `retained` | `W` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |
| `candidate-pilot-20` | `retained` | `W` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |

## Negative-search interpretation

Every `absent` cell in `coverage_audit.jsonl` records the exact lane snapshot, query
variants, record count, match counts, partial-match IDs, and manual all-critical-facts
sufficiency conclusion. Scientific KG searches all 121 approved statements with their
evidence and scope joins and separately reports caution matches. Legacy searches the
same 800 frozen evidence chunks plus the 25 direct-evidence candidate claims used by
its consumer, and records the tool-graph filter
scan separately. RAG searches all 800 frozen evidence chunks. A partial match never becomes
`present`, and no single retrieval result was used as a label.

The held scVelo statement `statement-revision:d0d887b96b7a1cf45e2c47bf:1` was verified absent and never searched as
support. Cautions are non-assertive and never establish a present bit.
