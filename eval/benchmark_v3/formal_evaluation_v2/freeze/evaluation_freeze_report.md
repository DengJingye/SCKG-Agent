# Formal evaluation v2 freeze report

- Freeze timestamp: `2026-09-20T23:38:41.366938+00:00`
- Freeze manifest SHA256: `7e6f4593b5218c5b5cb0d4770277277cc3b6af48cee487c8959097f47654ff6e`
- Source v1 manifest SHA256: `156a41b777a4d75991d3cfb455d80fb2569ac3e8b9a17d05587253278b658cd7`
- Runtime: `f3df9056364200fdc114d9cfd8d71fa76b915219`
- Approved KG: `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`
- Dataset: the same 36 byte-preserved v1 scenarios (K=24, O=8, W=4); no result-based selection or replacement.
- Scenario review: two isolated AI-assisted passes plus separate AI-assisted adjudication; no human review claimed.
- Leakage: PASS for DEV scenario, family, and source-thread overlap.
- Provider readiness: PASS across all four lanes before freeze.
- Semantic scoring calibration: pass A 6/6; pass B 6/6; no formal output used.
- Provider calls before v2 formal runs: readiness/calibration only; zero v2 formal lane calls.
- Schedule: 432 immutable units, 3 repetitions, seed `20260921`.

The invalid v1 run remains immutable and is not pooled with v2.
