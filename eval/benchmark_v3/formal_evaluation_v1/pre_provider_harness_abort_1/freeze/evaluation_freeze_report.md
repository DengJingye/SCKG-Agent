# Formal evaluation freeze report

- Freeze timestamp: `2026-09-20T21:38:43.236655+00:00`
- Freeze manifest SHA256: `03872a629e04c7abd7838ee0eb572da82b8e352419d3d5f18d6d484bfc1d1fd9`
- Runtime: `f3df9056364200fdc114d9cfd8d71fa76b915219`
- Approved KG: `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`
- Dataset: 36 scenarios (K=24, O=8, W=4), 24 independent families.
- Reviews: two isolated AI-assisted passes plus separate AI-assisted adjudication; these are not human reviews.
- Leakage gate: PASS (DEV IDs, families, and source threads have no exact overlap).
- Provider calls before freeze: 0.
- Schedule: 432 immutable units, 3 repetitions, seed `20260921`.

All scenario, fixture, primary-source span, scoring protocol, runtime code, prompt/code, corpus, and schedule hashes are recorded in `evaluation_manifest.json`.  Public issue titles remain marked as publicly exposed; transformation is not treated as decontamination.
