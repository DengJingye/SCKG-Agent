# Scientific KG Contribution Evaluation v1

**Evaluation baseline:** `c0ee68c891c7861eb5bbb63347d7a1f06d1e6c2e`

**Pre-KG baseline:** `47b12d9224891a775c366964b6509a6984340a88`

**Status:** `GO` for the bounded evaluation checkpoint

## Scientific conclusion

The causal comparison held the RepresentationLedger, Capability Pack, planner, targets, options and contracts constant:

```text
Baseline
= RepresentationLedger + Capability Pack + CapabilityPlanCompiler
  + explicit no-op applicability

KG-enabled
= RepresentationLedger + Capability Pack + the same CapabilityPlanCompiler
  + Scientific KG applicability
```

Across the four frozen scenarios, Scientific KG produced **0/4 observed incremental Planner behavior changes**, **4/4 explanation or provenance improvements**, and **0/4 regressions of previously correct behavior**.

The correct interpretation is:

> The existing Capability Pack, RepresentationLedger and planner already made the expected decisions in these controlled scenarios. Scientific KG made those decisions scientifically explicit and auditable by adding structured incompatibility reasons, evaluated-representation links, missing-requirement structure, evidence provenance and candidate-status governance.

This evaluation does not support the claim that KG caused the planner to skip PCA or neighbors, reject stale graph reuse, accept a Harmony embedding, or block transformed Scrublet input. The baseline already did those things correctly.

## Evaluation integrity

The expected-decision specification was frozen before the paired run and was not derived from KG-enabled output. Its SHA-256 is:

`6a7027c60b2cf493415f371d7ec0754e56ae480e42db86c97021cfcb8842f290`

Before comparison, evaluation-only Ledger creation metadata was frozen into one canonical serialized request set. The pre-KG and current snapshots then produced the same complete input SHA-256:

`02ce0304effa706788874688728a5a3a896de8195f6a18c1544654c8abe4e09f`

All 24 relevant contract, Capability Pack, StepContract, ToolContract and evidence inputs matched. Pre-KG and current-no-op planner outputs were equivalent in all four scenarios. The comparison retained blocked state, blocking reasons, planned method and step order, dependency edges, parameters, inputs and outputs, reused records and missing requirements. It excluded only the field introduced to carry Scientific KG applicability results.

## Paired results

| Scenario | Baseline behavior | KG-enabled behavior | Observed contribution |
| --- | --- | --- | --- |
| Valid neighbor graph → Leiden | Reused graph; scheduled Leiden; no PCA/neighbors | Same | Source-bound evidence and explicit candidate status |
| Stale or misaligned graph | Blocked; reused no invalid graph | Same | Specific stale and observation-identity reasons, evaluated representations and evidence |
| Harmony embedding → neighbors | Reused embedding; scheduled neighbors; no PCA | Same | Source-bound Harmony/Scanpy evidence and explicit candidate status |
| Transformed expression → Scrublet | Blocked; reported missing raw-count producer | Same | Structured raw-UMI requirement, transformation incompatibilities, assessed representations and evidence |

### Behavioral contribution

| Metric | Baseline | KG-enabled | Applicable denominator |
| --- | ---: | ---: | ---: |
| Correct allow/block | 4 | 4 | 4 |
| Unnecessary step events | 0 | 0 | 2 scenarios |
| Invalid reuse events | 0 | 0 | 2 scenarios |
| Inappropriate scheduling events | 0 | 0 | 4 scenarios |
| Previously correct behavior regressions | 0 | 0 | 4 scenarios |

### Explanation and provenance contribution

| Metric | Baseline | KG-enabled | Applicable denominator |
| --- | ---: | ---: | ---: |
| Evaluated-representation linkage | 2 | 4 | 4 |
| Resolvable supporting evidence | 0 | 4 | 4 |
| Explicit candidate status | 0 | 4 | 4 |
| Specific incompatibility reason | 0 | 2 | 2 |
| Correct missing requirement | 1 | 1 | 1 |

The Scrublet missing-requirement count is unchanged because the baseline already emitted `no_registered_producer:raw_counts`. KG replaced an implementation-centered symptom with a structured scientific requirement for preserved raw UMI counts and recorded why the available normalized and integrated representations were incompatible.

## Evidence boundary

These are four synthetic, bounded mechanism tests. They establish isolation, compatibility and explanation behavior for the tested inputs. They do not establish broad scientific utility, release readiness, or trusted status for the wider candidate KG. Evidence references were checked against previously frozen exact evidence bindings and support assessments; this run did not perform new independent scientific adjudication.

Future KG contribution evaluations should select decisions whose scientific applicability is not already completely encoded by Capability Pack and RepresentationLedger contracts. A reference-dependent method is a suitable direction because representation existence alone cannot establish biological or reference compatibility.

## Reproducibility references

- Harness: `eval/scientific_kg_contribution_v1.py`
- Expected decisions: `eval/specs/scientific_kg_contribution_v1.expected.json`
- Tests: `tests/test_scientific_kg_contribution_v1.py`
- Committed freeze candidate: `data/evaluation/scientific_kg_contribution_v1_freeze/summary.json`
- Preserved original NO-GO evidence: `data/evaluation/scientific_kg_contribution_v1/`
- Preserved complete corrected run: `data/evaluation/scientific_kg_contribution_v1_corrected/`

The original NO-GO and full corrected-run directories remain audit evidence. They contain large input snapshots, raw and normalized planner outputs, test XML and run markers, and are intentionally outside the minimal freeze proposal.
