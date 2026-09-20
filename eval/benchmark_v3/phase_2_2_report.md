# Phase 2.2 Evaluation Lane Alignment + Coverage Re-audit

Status: complete bounded metadata audit; no DEV/Gold, lane execution, Agent Gain, seed expansion, or 05/06/07 changes.

## Outcome

- Lane manifest freezes `llm_only`, `generic_rag`, `legacy_kg`, and `scientific_kg` at `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`.
- Approved Scientific KG identity verified as `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4` with 121 visible statements, 166 separate caution contexts, and the held scVelo statement absent.
- All 20 existing candidate drafts were re-audited against the actual consumers: `{"000": 20}`.
- Track proposals across the audited 20: K=4, O=10, W=6. They are sampling/review metadata, not Gold.
- Candidate admission: 18 retained; 2 demoted to raw-only (`candidate-pilot-01`, `candidate-pilot-07`).

## Alignment correction

The Phase 2.1 `kg-v2.3.0-canonical:6b20b218...` source is the legacy 7,537-node tool/catalog graph, not the approved Scientific KG v2 consumer. Its former `100` result for `candidate-pilot-06` came from a ToolContract. The re-audit excludes that shared runtime component, so the candidate is `000`. The legacy lane remains bound to its candidate evidence adapter, frozen RAG corpus, and graph filtering channel; the RAG lane remains bound to the same frozen BM25 corpus with graph channels off.

## Review blockers

1. The retained title-only issues still need the version/reproducer/data-state fields recorded in the admission audit before scientific adjudication.
2. Paper/notebook candidates still need frozen input/capsule and execution-environment digests.
3. All coverage decisions remain `needs_adjudication`; no answer source or expected result has been promoted to Gold.

## Explicit non-actions

No LLM answer, Research Chat lane, A/B/C/D run, Agent Gain calculation, DEV/Gold split, seed expansion, or 05/06/07 modification occurred.
