# Knowledge Foundation P0C — Dense Retrieval Qualification

## Decision

`KNOWLEDGE_FOUNDATION_P0C = PASS`

`dense_available = true`

This checkpoint qualifies the already implemented local BGE-M3 retrieval path
against the frozen evidence corpus. It does not assert that dense retrieval is
better than BM25, does not run a retrieval benchmark, and does not change KG,
ranking, governance, Planner, Seed v0, or scientific knowledge status.

## Frozen identity

| Item | Qualified value |
| --- | --- |
| Model | `BAAI/bge-m3` |
| Revision | `cb1779f90b988b8deb01f9155c790ef9417d7648` |
| Snapshot digest | `5cac1098681d451c3acb281c9581e1c424616749456713fba3b924b4c7966cf6` |
| Model-pack manifest SHA-256 | `72a2d2f9bc2bf7e5f261b8b73dc573d83de2d7bd32e9f9ee6d20f801a38477fb` |
| Evidence build ID | `evidence-v2-bb3aec4cf1266a2e` |
| Dense corpus digest | `7c8545721cd73a47fc0849ccc240ba2e150a064e07005de5f11ac26ab1213fd0` |
| Eligible/indexed chunks | `773 / 773` |
| Vector shape | `773 × 1024` |
| Vector dtype | `float32` |
| Normalized | yes; norm range `0.9999999404–1.0000001192` |

The 10 quarantined, non-source-bound formal rows remain outside the dense
index. All 773 indexed chunk IDs resolve to the current source-bound corpus;
there are no duplicate or dangling IDs.

## Physical artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| `data/indexes/evidence_vectors.npy` | `73b0abb9c952d925b277018f469fc72031cf627face6fda6ba544ef67df1bcbf` |
| `data/indexes/evidence_vector_metadata.json` | `61df992256af9438cecdc8d97d95ad93166ba59413589e4e63d7864884b7a89a` |
| `data/indexes/evidence_index_manifest.json` | `c1520ac9eabf5b30dbe313c54e482c89c2d386000d79310678c43a48ecab8364` |

The matrix and vector metadata remain local runtime artifacts under the
repository's existing ignore policy. Their digests and complete qualification
metadata are preserved in the P0C machine-readable report.

## Cold-start and query qualification

- A fresh Python process loaded the persisted `773 × 1024` matrix and all 773
  ordered chunk identities without rebuilding the index.
- The representative dense-only query was:
  `What raw count input does Scrublet require for doublet detection?`
- Runtime result: `dense_status=ready`, `mode=dense`, five source-bound hits,
  no warnings.
- Rank 1 was `sourcev2:111374ebeb154e8b9052`, the official Scrublet README
  span `section:Scrublet;paragraph:1-5`, which directly states the raw,
  unnormalized UMI-count input requirement.
- Repeating the same query in the qualified process produced the identical
  chunk ranking.

This is a deterministic availability and resolution smoke, not an accuracy
benchmark and not evidence that dense retrieval should become the default
route.

## Failure fallback

With the dense matrix and metadata deliberately absent from an isolated
service instance, the existing local path returned:

- `dense_status=vector_index_missing`;
- `mode=kg_bm25`;
- five source-bound BM25 hits;
- the existing explicit fallback warning.

Therefore qualification of the dense artifacts does not remove or weaken the
governed KG + SQLite FTS5 BM25 fallback.

## Gates

All P0C gates passed:

- model pack ready and version-pinned;
- snapshot identity matched;
- frozen corpus digest matched independently;
- build ID, chunk order, membership, vector count, dimension and normalization
  matched;
- every chunk resolved and no duplicate IDs existed;
- fresh-process reload passed;
- real representative dense query passed with stable ranking;
- BM25 fallback passed.

No Scientific KG content was changed or promoted. No Seed v1 or retrieval
benchmark was started.
