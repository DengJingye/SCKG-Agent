# Human-approved Scientific KG v2 package

This directory contains an immutable snapshot derived from the exact 06b
candidate hash authorized by the human user. It approves 121 exact revisions
for scientific retrieval and archives scVelo #21 as HOLD. It grants no execution
authority. No production runtime or ontology changes are part of this package.

The four requested outputs are in `snapshots/approved-v2-01/`:
`approved_kg.json`, `promotion_manifest.json`, `held_out_statements.json`, and
`promotion_report.md`. The snapshot also includes the unchanged caution context
index, explicit human decision with revision IDs, validation results, and input
hashes. The manifest is protected by the package's Git commit; it hashes all
other snapshot files. New content or decisions require a new snapshot ID.

`knowledge_status=approved` is external governance, as allowed by the frozen
property registry's externalization of lifecycle/trust. The scientific schema
remains unchanged. The existing candidate-only validator cannot validate human
approval: packaging validates real governance separately and uses a documented,
temporary candidate-governance projection only for frozen structure/provenance.

`production_retrieval_eligible=true` concerns only the 121 approved assertions.
Cautions have a separate context policy: available to future context retrieval,
untrusted and non-assertive, never execution gates. The HOLD sidecar is archival
and must never enter the production retrieval set. Unknown/partially_known scopes
remain unknown, never wildcard; consumers must enforce known qualifiers and must
not equate human approval with applicability. Existing utility records remain
historical metadata, not authorization. Research Chat integration remains pending.

Run from the repository root, using the existing local source archive and 06b
deliverables. These inputs and their earlier implementation are intentionally
not added to this independent promotion commit. Python and pytest are sufficient;
no network, GPU, database, or formal evaluation is used.

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/sckg_env/bin/python -m reconstruction.promotion_v2.promotion
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/sckg_env/bin/python -m pytest -q -p no:cacheprovider reconstruction/promotion_v2/test_promotion.py reconstruction/hardening_06b/test_hardening.py reconstruction/tests
```

Re-running the first command verifies the existing manifest, payloads, decision,
implementation and protected input hashes without rewriting files. The second
runs the short packaging and existing engineering regressions, not Agent Gain.
Plugin autoload is disabled because the installed, unrelated LangSmith pytest
plugin imports an incompatible psutil binary before tests can be collected.
These tests use pytest's built-in fixtures and require no external plugins.
`test_results.json` records the pre-commit test run outside the immutable snapshot.
The graph and sidecars include exact evidence quotations and provenance; complete
source bytes remain in the existing source archive for full offset/hash replay.
