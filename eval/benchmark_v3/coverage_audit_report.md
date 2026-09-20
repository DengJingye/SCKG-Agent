# Phase 2.2 Lane-aligned Coverage Re-audit

Run: `lane-alignment-20260921-v2-withdrawal`

Status: previous all-000 conclusion WITHDRAWN; all 20 unknown pending fact decomposition and human review.

The Phase 2.1 coverage conclusion is superseded. The V2 bit now uses only the actual
approved-v2 consumer at the 07 integration commit. ToolContracts and all other shared
runtime components are excluded. Legacy and RAG use the exact paired backends from 07.

Signature counts: `{"unknown": 20}`.

| candidate | admission | track | required fact/condition (first) | V2 | Legacy | RAG | signature |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `candidate-pilot-01` | `demoted_to_raw_only` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-02` | `retained` | `K` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-03` | `retained` | `K` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-04` | `retained` | `W` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-05` | `retained` | `K` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-06` | `retained` | `W` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-07` | `demoted_to_raw_only` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-08` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-09` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-10` | `retained` | `K` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-11` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-12` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-13` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-14` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-15` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-16` | `retained` | `O` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-17` | `retained` | `W` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-18` | `retained` | `W` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-19` | `retained` | `W` | decomposition pending | unknown | unknown | unknown | unassigned |
| `candidate-pilot-20` | `retained` | `W` | decomposition pending | unknown | unknown | unknown | unassigned |

## Negative-search interpretation

No cell currently establishes absence or presence. Search evidence records snapshot, query
variants, counts and partial-match IDs, NOT manual sufficiency decisions.
Scientific KG searches all 121 approved statements with their
evidence and scope joins and separately reports caution matches. Legacy searches the
same 800 frozen evidence chunks plus the 25 direct-evidence candidate claims used by
its consumer, and records the tool-graph filter
scan separately. Both RAG-backed inventories include the 1847 conditional catalog records;
10 quarantined formal chunks cannot support present. Catalog metadata cannot support recommendations/execution.
A partial match never becomes
`present`, and no single retrieval result was used as a label.

The held scVelo statement `statement-revision:d0d887b96b7a1cf45e2c47bf:1` was verified absent and never searched as
support. Cautions are non-assertive and never establish a present bit.
