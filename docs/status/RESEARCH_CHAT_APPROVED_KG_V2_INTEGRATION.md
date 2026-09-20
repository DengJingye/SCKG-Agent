# 07 — Approved Scientific KG v2 read-only integration

Status: PASS for integration qualification. Formal Agent Gain was not run.

The initial worktree was `SCKG-Agent-candidate-demo`, branch
`feature/candidate-kg-demo-v1`, HEAD `3bdf8a1448c2847a000ff1a575a96d2847229609`.
Existing uncommitted 07 conversation/runtime work was preserved and extended.
The approved package commit `6018699092d979a2da0dda45a19c920018ed9eda` was directly
accessible in this repository. No other worktree path is used to load knowledge.

## Production path

`build_chat_retrieval` and the default `ResearchChatService` construct
`GovernedChatRetrieval`. Production and `scientific_kg` searches call
`ApprovedScientificKG` directly; they never call the Legacy retriever. The
loader reads immutable Git blobs at the pinned upstream commit, verifies every
manifest output hash, and checks the exact 121-revision retrieval allowlist.
Missing Git objects, hash mismatches or incomplete source bindings fail closed.
Deployment therefore requires that upstream commit in the local repository's
object database; an export of Python files alone is insufficient.

Snapshot: `approved-scientific-kg-v2-01`.
Approved KG SHA256:
`06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`.
The held revision `statement-revision:d0d887b96b7a1cf45e2c47bf:1` is absent
from all production statement indexes. Its archival sidecar is hash-verified,
but never offered as retrieval evidence.

An in-memory evidence index joins 134 direct assessment bindings to the
package's verbatim excerpts, 61 source artifacts and 48 source revisions.
Artifacts sharing a revision retain their individual title, hash and locator.
Source expansion shows Statement → Assessment → EvidenceSpan → SourceRevision,
the registered source link and exact excerpt. No source corpus was fabricated.
Binding verification covers the immutable package and excerpt hashes; it does
not claim to have independently downloaded/reverified the original full sources.

## Consumer policies

- Scope stays verbatim. Known qualifier mismatches exclude statements; missing
  context, `unknown` and `partially_known` remain unknown. Conditional knowledge
  can be explained without declaring it applicable to the user's data. User
  context is separate from model-generated retrieval queries; assistant history
  cannot supply a version or parameter. Follow-ups update the user conditions.
- 166 caution/EvidenceGap records remain available as separate reminder context.
  They are not scientific assertions: `trusted=false`,
  `production_retrieval_eligible=false`, `execution_gate=false`,
  `execution_authorized=false`. Their citations use `CAUTION_CONTEXT`; attempts
  to cite them as approved KG or ordinary scientific assertions are rejected.
- Scrublet's absent parent singlet state remains a detectability caution.
  CellRank's putative lineage-correlated drivers remain non-causal candidates.
- HVG preserves logarithmized input for `seurat`/`cell_ranger` and counts for
  `seurat_v3`/`seurat_v3_paper`, at the approved Scanpy release.
- PCA projects both OutputPort branches with conjunctive conditions:
  `chunked=true` for incremental PCA; `chunked=false AND zero_center=true`
  for centered PCA. A consumer guard rejects an unqualified truncated-SVD
  statement inferred from `zero_center=false` alone. Live qualification caught
  this omission in an intermediate answer; the final answer retains the two
  supported branches and asks for the missing chunked condition.
- `REQUIRED` is a scientific/API requirement. It never creates execution
  authority or a new planner blocking gate.

## Preserved baselines

`llm_only` performs no retrieval. `generic_rag` uses the existing source retriever
with graph channels disabled. `legacy_kg` explicitly uses the previous candidate
Scientific KG evidence adapter and legacy tool graph; it returns candidate
bindings, never approved-v2 facts. `scientific_kg` uses only the new approved
adapter and its separate caution context. An actual baseline smoke test checks
that the approved adapter's call counter does not change during a legacy query.

The frozen 1,651-node Scientific KG inventory and its four layers are retained.
The separate 7,537-node legacy tool/catalog graph is also retained. These are
different inventories, and neither is relabeled as the approved snapshot.

No frozen ontology, Scientific KG content, 05 viewer, planner safety contract,
execution authorization semantics, raw data or weights were changed.

## Qualification evidence

Artifacts are write-once under `.sckg_exec/research-chat-approved-v2/`:

- `qualification-final/`: six actual ASK turns, 17 provider calls to the existing
  configured DeepSeek `deepseek-v4-pro`, zero execution requests and zero errors.
  Cases cover HVG, its seurat follow-up, Scrublet parent singlets, CellRank causal
  boundaries, an out-of-KG causal-forest question, and PCA branches. All returned
  statement IDs were checked against the approved allowlist. The out-of-KG case
  actually called the adapter, obtained no matching statement, and labeled the
  response as unverified model knowledge with no borrowed local citations.
- `ui-final.json`: actual Streamlit AppTest, with an isolated chat store, calls
  the approved runtime and renders four KG facts, exact excerpts, assessment
  records, per-artifact metadata and the Why/Evidence expanders.
- `acceptance.json`, `protected-final.json`: retrieval invariants, source-chain
  checks, legacy preservation and protected-file byte comparisons.
- Intermediate `smoke-01`, `qualification-02`, `qualification-03` remain intact
  to show the discovered failures and corrections. They are not final results.

Regression suite: **212 passed, 2 deselected**. The two pre-existing PLAN trace
tests expect a smoke-qualified workspace handoff that the existing recipe does
not provide; its safety status was not changed to satisfy those expectations.
After the final explicit Legacy-lane adjustment, **42 focused tests passed**,
including the added real Legacy-versus-approved separation test. Historical
tests pinning old source IDs now explicitly construct the Legacy backend.

These are integration/development checks. They do not establish an Agent Gain
score or independent scientific correctness of every model-knowledge paragraph.
Model support checking remains fallible and is not independent evidence review.

## Runtime and reproduction

Research Chat is served at `http://127.0.0.1:8501/`. This host's
`/opt/anaconda3/envs/sckg_env/bin/python` currently has a broken psutil binary
import (`getpagesize` absent). Qualification and the restarted Chat use the
existing working `/opt/anaconda3/bin/python`; no Python environment was modified.
Only the Chat process was restarted. Existing credentials were reused without
printing their values.

From this worktree, rerun small adapter checks with:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/anaconda3/bin/python -m pytest -q tests/test_approved_scientific_chat_v2.py
```

For a new, explicitly authorized six-turn live qualification, use an unused
output directory and the path to the existing authorized environment file:

```sh
SCKG_ENV_FILE=/path/to/authorized.env /opt/anaconda3/bin/python -m eval.approved_scientific_chat_qualification --live --output .sckg_exec/research-chat-approved-v2/qualification-new
```

No formal Agent Gain or four-lane performance comparison was run. This work is
packaged as a local integration commit with the required earlier 07 changes;
it is not pushed. The exit response and runtime receipt identify that commit.

```text
SCIENTIFIC_KG_V2_LOADED=true
APPROVED_KG_HASH_VERIFIED=true
APPROVED_STATEMENTS_VISIBLE=121
HELD_STATEMENTS_VISIBLE=0
CAUTION_CONTEXT_ACTIVE=true
SCOPE_POLICY_ACTIVE=true
LEGACY_KG_PRESERVED=true
SOURCE_EXPANSION_PASS=true
RESEARCH_CHAT_INTEGRATION_READY=true
TESTS=212 regression PASS; 42 final focused PASS; 6 live ASK PASS; UI PASS
```
