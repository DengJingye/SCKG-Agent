# Method KG Batch 1 Promotion Blocker Checklist

Status: candidate-only; no item is resolved by this packet.

- [ ] **source_bound projection mismatch** — 10 canonical evidence rows with `source_bound=false` are projected as bound in the current Decision Graph. IDs remain in `provenance_quality_report.json`.
- [ ] **graph input fingerprint drift** — Knowledge Graph drift: contracts/tools/celltypist/1.7.1.json, contracts/tools/singler/2.14.0.json, data/scrna_tools.tsv; Decision Graph drift: contracts/tools/celltypist/1.7.1.json, contracts/tools/singler/2.14.0.json.
- [ ] **Scanpy contract snapshot missing** — contract file exists, but current Decision Graph contains no Scanpy ToolContract node.
- [ ] **CellTypist / SingleR contract snapshot version drift** — snapshot versions: {"celltypist:1.7.1": "0.1.0-planning-only", "singler:2.14.0": "0.1.0-planning-only"}; current files: {"celltypist:1.7.1": "0.2.0-wrapper-implemented", "singler:2.14.0": "0.2.0-wrapper-implemented"}.
- [ ] **scVI / scvi-tools identity** — no governed alias/version decision distinguishes the scVI model/method from the scvi-tools package identity.
- [ ] **Monocle / Monocle3 identity** — no governed alias/version decision resolves these identities.
- [ ] **full regression artifact dependency** — latest run: `729 passed, 38 failed, 8 warnings`. Failures are concentrated in unavailable runtime packs and absent maintainer pilot/package artifacts, producing `runtime_pack_not_ready`, missing dataset-scoped evaluations, and `contract_verified` rather than `decision_ready`. This packet does not alter execution/runtime state.
- [ ] **human adjudication** — all 48 AtomicClaims remain `candidate_pending_review`; reviewer decisions and reasons are blank.

Canonical promotion remains blocked until every applicable item is independently resolved and audited.
