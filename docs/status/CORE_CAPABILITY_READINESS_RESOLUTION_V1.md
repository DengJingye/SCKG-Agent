# Core Capability Readiness Resolution v1

Status: `COMPLETE_WITH_GOVERNANCE_GATES_PRESERVED`

Baseline: `387625250cf791bb946746020593eb009d64eee3`

This checkpoint resolves review and artifact prerequisites only. It does not
change production planning, ToolContracts, Capability Packs, RAG, benchmark
gold or canonical knowledge.

## Outcome

| Target | Result | What is now available | What remains prohibited |
| --- | --- | --- | --- |
| SoupX | `READY_FOR_HUMAN_REVIEW` | Complete packet for the existing SoupChannel `tod`/`toc` candidate, including exact PDF span and verified hashes | No ReviewDecision, promotion, contract or pack |
| CellTypist | `ARTIFACT_RESOLVED` | Candidate `Immune_All_Low.pkl` v2 ReferenceArtifactRevision and compatibility manifest bound to SHA-256 | No contract alias rewrite, pack, planner binding or execution enablement |
| scVelo | `READY_FOR_HUMAN_REVIEW` | Five R3 input-requirement packets with claims, constraints, evidence, scope and risk flags | No self-approval, `CAN_FEED`, CellRank compatibility, contract or pack |

## SoupX

The existing review item remains `pending_human_review`. The review packet
preserves the exact candidate proposition:

> In SoupX 1.6.2, SoupChannel defines `tod` as a genes-by-droplets droplet
> table and `toc` as the count table containing only `tod` columns
> corresponding to droplets with cells.

The source is the official SoupX 1.6.2 manual. The PDF SHA-256
`dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19`
and exact evidence content hash
`d56762056291c5c96519ff9eec38ca5345e1ad88e5ed4bf823f79181b0a558df`
were reverified against the preserved local acquisition artifact.

The packet explicitly prevents widening this evidence into a universal raw
count rule, an execution rule, a workflow-order rule or a resolution of the
broader droplet-profile EvidenceGap. `review_decision` remains null and
`promotion_allowed_now` remains false.

## CellTypist

The official CellTypist model index currently identifies
`Immune_All_Low.pkl` as the default Pan Immune model, version `v2`, at a
version-qualified official URL. A temporary read-only acquisition was used to
calculate the artifact identity; the binary was not copied into the repository
or production reference-pack directory.

Verified identity:

- content length: `2,824,990` bytes;
- HTTP ETag/MD5: `f0ecbcf5687f2dff6dc5a46cecc9dab5`;
- SHA-256: `290874d35dac039d4c9218c343fde4aac1077709b72a331ce7266f6828c36502`;
- model version: `v2`;
- species: human (`NCBITaxon:9606`);
- feature namespace: human gene symbols, without asserting universal HGNC
  normalization;
- features: `6,639` with ordered-list digest
  `d476727a7bd03362720f8db23ee5b22b53dcd658fc04389ffbc9ecbb5f5ad0be`;
- labels: `98` with ordered-list digest
  `b087fd6c2b00547ac0f6e9f9ecb72af286a967c7ec5a10cc6ee1cfe889e123d7`.

The candidate preserves important unknowns: no universal minimum feature
overlap threshold, no verified immutable label-ontology mapping, no non-human
compatibility claim, and no guarantee that the model is biologically suitable
for every tissue or disease context.

The existing ToolContract alias `celltypist-immune-all-low-v1` was not changed.
The candidate manifest is a proposed crosswalk only. CellTypist is therefore
artifact-resolved but not planning-ready.

## scVelo

Five decision-critical R3 requirement claims were packaged:

1. `scvelo.pp.moments` consumes spliced/unspliced layers;
2. `scvelo.pp.moments` consumes a neighbor graph;
3. `scvelo.tl.velocity` consumes first/second-order moments;
4. `scvelo.tl.velocity_graph` consumes velocity vectors;
5. `scvelo.tl.velocity_graph` consumes a neighbor graph.

All remain `candidate_pending_review` with `qualified_human` review required.
The packet exposes a material review issue rather than hiding it: several
stored evidence excerpts establish the operator capability but do not directly
state every detailed port/component requirement. The registered source is
versioned as scVelo 0.3.4, while its URI is the mutable `stable` documentation
alias and its locator is not an immutable source offset. These are review risks,
not facts that this checkpoint may silently repair.

No scVelo-to-CellRank compatibility was asserted or activated.

## Frozen boundaries

- RAG corpus/index modified: no;
- frozen retrieval benchmark modified: no;
- Planner or `CapabilityPlanCompiler` modified: no;
- ToolContract modified: no;
- Capability Pack created or modified: no;
- benchmark gold or formal holdout modified: no;
- candidate promoted: no;
- ReviewDecision created: no;
- unreviewed `CAN_FEED` activated: no.

## Next authorized owners

1. A qualified reviewer may adjudicate the bounded SoupX claim.
2. A qualified reviewer may adjudicate or request stronger evidence for the
   five scVelo requirements.
3. A later engineering checkpoint may register the verified CellTypist binary
   in an approved reference pack, reconcile the contract alias, and validate
   compatibility before creating a Capability Pack.

This checkpoint does not rerun Core Capability Expansion automatically.
