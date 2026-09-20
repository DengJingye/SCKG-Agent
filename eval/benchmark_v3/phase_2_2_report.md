# Phase 2.2 Evaluation Lane Alignment + Coverage Re-audit

Status: COVERAGE CONCLUSION WITHDRAWN. Lane identities remain verified; coverage is unknown, not 000.

## Outcome

- Lane manifest freezes `llm_only`, `generic_rag`, `legacy_kg`, and `scientific_kg` at `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`.
- Approved Scientific KG identity verified as `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4` with 121 visible statements, 166 separate caution contexts, and the held scVelo statement absent.
- All 20 former coverage labels are withdrawn pending fact-level human review. Search inventory is not adjudication.
- Track proposals across the audited 20: K=4, O=10, W=6. They are sampling/review metadata, not Gold.
- Candidate admission: 18 retained; 2 demoted to raw-only (`candidate-pilot-01`, `candidate-pilot-07`).

## Alignment correction

The Phase 2.1 canonical graph is not the approved Scientific KG consumer. The former `100` for candidate-pilot-06 incorrectly counted a shared ToolContract. The subsequent all-000 result was also invalid: the program hardcoded absent. Neither result is a scientific coverage conclusion. Historical bytes remain at commit 810ed0853c763c0a497f74100f7bb8d47ed2e4e8; current labels are unknown. Runtime-only tasks may become not_applicable after requirement decomposition, never automatically 000.

## Review blockers

1. The retained title-only issues still need the version/reproducer/data-state fields recorded in the admission audit before scientific adjudication.
2. Paper/notebook candidates still need frozen input/capsule and execution-environment digests.
3. All coverage decisions remain `needs_adjudication`; no answer source or expected result has been promoted to Gold.

## Explicit non-actions

No LLM answer, Research Chat lane, A/B/C/D run, Agent Gain calculation, DEV/Gold split, seed expansion, or 05/06/07 modification occurred.
