# Phase 2.1 Candidate Knowledge Coverage Audit

Run: `candidate-audit-20260921-v1`

Candidates audited: 20

Bit order: `Scientific KG v2 / Legacy KG / ordinary RAG`.

Coverage is a frozen-corpus sufficiency judgment, not a retrieval-run outcome. A
`present` value requires supporting IDs; an `absent` value retains the exhaustive
negative-search procedure and partial lexical matches. Public answers and 07 outputs
were not consulted. This audit creates neither Gold nor expected answers.

## Frozen boundaries

- `scientific_kg_v2` — `kg-v2.3.0-canonical:6b20b21847be`; Frozen KG v2 node and edge records; governance fields are respected.
- `legacy_kg` — `legacy-recall-baseline-20260921`; Repository-defined legacy recall baseline: compatibility tool catalog plus legacy LLM-derived embedding/profile records. It is not recommendation-grade evidence.
- `ordinary_rag` — `evidence-v2-bb3aec4cf1266a2e`; Frozen evidence_chunks corpus only; catalog chunks, KG traversal, ToolContracts, and generated model knowledge are excluded.

## Signature summary

| Signature | Count |
| --- | ---: |
| `111` | 0 |
| `110` | 0 |
| `101` | 0 |
| `011` | 0 |
| `100` | 1 |
| `010` | 0 |
| `001` | 0 |
| `000` | 19 |

## Candidate audit index

| Candidate | Origin | Required facts/conditions (summary) | V2 | Legacy | RAG | Signature |
| --- | --- | --- | --- | --- | --- | --- |
| `candidate-pilot-01` | `real-user` | The exact version-bound behavior for the reported software api organization condition. | absent | absent | absent | `000` |
| `candidate-pilot-02` | `real-user` | The exact version-bound behavior for the reported differential expression statistics condition. | absent | absent | absent | `000` |
| `candidate-pilot-03` | `real-user` | The exact version-bound behavior for the reported normalization parameter semantics condition. | absent | absent | absent | `000` |
| `candidate-pilot-04` | `controlled-probe` | Artifact lineage showing which UMAP and clustering outputs depend on the recomputed neighbor graph. | absent | absent | absent | `000` |
| `candidate-pilot-05` | `controlled-probe` | The installed Scanpy version and the API signature valid for that exact version. | absent | absent | absent | `000` |
| `candidate-pilot-06` | `controlled-probe` | A successful process exit is insufficient when a required artifact fails its declared validator. | present | absent | absent | `100` |
| `candidate-pilot-07` | `real-user` | The exact version-bound behavior for the reported resource and parallelism condition. | absent | absent | absent | `000` |
| `candidate-pilot-08` | `real-user` | The exact version-bound behavior for the reported normalization and count correction condition. | absent | absent | absent | `000` |
| `candidate-pilot-09` | `real-user` | The exact version-bound behavior for the reported object state and layers condition. | absent | absent | absent | `000` |
| `candidate-pilot-10` | `real-user` | The exact version-bound behavior for the reported clustering label semantics condition. | absent | absent | absent | `000` |
| `candidate-pilot-11` | `real-user` | The exact version-bound behavior for the reported clustering backend selection condition. | absent | absent | absent | `000` |
| `candidate-pilot-12` | `real-user` | The exact version-bound behavior for the reported reference mapping and subsetting condition. | absent | absent | absent | `000` |
| `candidate-pilot-13` | `real-user` | The exact version-bound behavior for the reported reproducibility and rng condition. | absent | absent | absent | `000` |
| `candidate-pilot-14` | `real-user` | The exact version-bound behavior for the reported visualization api error condition. | absent | absent | absent | `000` |
| `candidate-pilot-15` | `real-user` | The exact version-bound behavior for the reported quality control and raw state condition. | absent | absent | absent | `000` |
| `candidate-pilot-16` | `real-user` | The exact version-bound behavior for the reported feature selection and batch state condition. | absent | absent | absent | `000` |
| `candidate-pilot-17` | `paper-notebook` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |
| `candidate-pilot-18` | `paper-notebook` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |
| `candidate-pilot-19` | `paper-notebook` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |
| `candidate-pilot-20` | `paper-notebook` | The exact frozen input dataset/capsule and its schema. | absent | absent | absent | `000` |

Full required-condition lists, supporting IDs, scan variants, counts, and sample
partial-match IDs are in `coverage_audit.jsonl`.

## Interpretation

The high `000` count is not a failure of the audit. Title-only software issues lack
versioned reproduction context, and paper/notebook questions request dataset-specific
computed outputs whose input artifacts were intentionally not imported. The single
`100` probe is supported by multiple governed V2 ToolContract records that bind
required artifacts to named validators; neither the legacy recall baseline nor the
ordinary scientific-document corpus carries that execution-validation contract.
