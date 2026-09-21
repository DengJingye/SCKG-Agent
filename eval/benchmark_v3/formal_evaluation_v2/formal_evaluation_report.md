# scKG-Agent V3 formal evaluation v2 report

## Status

**BLOCKED during semantic-review adjudication. No K/O/W score or Scientific KG gain claim is emitted.**

This is not another poor benchmark result. The product experiment itself ran
cleanly; the remaining blocker is the configured judge account balance.

## Completed and verified

- Dataset: 36 frozen scenarios (K=24, O=8, W=4), unchanged from the original freeze.
- Leakage: no exact DEV scenario, family, or source-thread overlap.
- Runtime: `f3df9056364200fdc114d9cfd8d71fa76b915219`.
- Approved KG: `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`.
- Freeze manifest: `7e6f4593b5218c5b5cb0d4770277277cc3b6af48cee487c8959097f47654ff6e`.
- Formal runs: 432/432 completed, 108 per lane, with zero failed runs.
- Product provider calls: 578/578 completed with zero failures.
- Lane isolation and runtime-receipt inventory: PASS.
- Two lane-blind semantic review passes: 72/72 provider calls completed.

## Observed product runtime usage

| Lane | Runs | Provider calls | Input tokens | Output tokens | Mean run latency ms |
|---|---:|---:|---:|---:|---:|
| llm_only | 108 | 145 | 295,979 | 54,595 | 4,411.1 |
| generic_rag | 108 | 129 | 257,456 | 46,495 | 3,900.4 |
| legacy_kg | 108 | 132 | 264,336 | 48,281 | 5,018.7 |
| scientific_kg | 108 | 172 | 716,538 | 61,465 | 5,025.9 |

These are observed provider usage values. They are not normalized for answer
length or call count, and no cost is calculated without a frozen price table.

## Why scores are withheld

The answer judge produced 864 raw review rows. Eight hundred rows satisfied the
frozen schema. Sixty-four rows contained output-format defects, chiefly null
in-track booleans, non-exact quote anchors, or an invalid required-fact map.
Those rows and ordinary A/B disagreements yield 167 run judgments requiring the
separate adjudication pass. Raw judge responses are preserved; invalid values
were not silently coerced.

The first adjudication call returned HTTP 402 `Insufficient Balance`. Therefore
the frozen scoring procedure is incomplete. Treating disagreements as failures,
selecting one reviewer, or reporting only agreement cases could materially alter
the lane comparison, so none of those shortcuts was used.

## Limitations

Even after adjudication, this remains a 36-scenario pilot. Scenario review and
answer scoring are AI-assisted, not two-human Gold review. The judge uses the
same configured provider family as the runtime, although lane identities are
hidden. Public O sources retain contamination risk. Product-lane contrasts do
not isolate graph structure alone.

## Resume point

After replenishing the configured DeepSeek balance, run the two commands in
[`BLOCKED.md`](BLOCKED.md). The 432 product answers must not be rerun.
