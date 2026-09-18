# Annotation Delivery & Human-Review Boundary Repair v1

Baseline: `feature/method-kg-expansion-v1@a485c96407d60144795797f0fbbbee05d3577368`.
Status: implementation and focused verification complete; **uncommitted, not pushed**.
No PBMC replay, historical campaign or benchmark was rerun.

## Result and scientific boundary

```text
ANNOTATION_DELIVERY_REPAIR = PASS
REAL_CANDIDATE_GENERATION_VERIFIED = false
SYNTHETIC_CANDIDATE_DELIVERY_VERIFIED = true
MANUAL_BOUNDARY_EXPLICIT = true
FULL_SCIENTIFIC_TASK_COMPLETED = false
```

PASS means the delivery/validation mechanism passed focused tests. It does not mean
PBMC3k now has supported cell-type candidates, human-confirmed labels or a successful
new end-to-end replay. No genuine PBMC marker-to-label evidence bundle or human
confirmation was supplied. The positive review and sources in tests are explicitly
synthetic fixtures, not real scientific adjudication.

| Actual content | Delivery status | Candidate terminal satisfied | Confirmed annotation |
|---|---|---|---|
| Valid marker result only; no qualified candidate evidence | BLOCKED; persisted marker/cluster review packet | No | No |
| Empty candidates, unresolved evidence, stale/misaligned marker record | BLOCKED; explicit missing requirements | No | No |
| Nonempty, reviewed source-bound candidates covering the current cluster set | WAITING_FOR_USER_CONFIRMATION | Yes, for the **candidate** target only | No |
| Partial cluster coverage | BLOCKED; partial candidate artifact retained when otherwise valid | No for complete candidate target | No |
| Metadata service or persisted-artifact validation failure | FAILED | No | No |
| Human-review step without an explicit human decision | WAITING_FOR_USER_CONFIRMATION; terminal raises incomplete | Does not upgrade candidates | No |

The final Notebook cell writes `terminal_validation.json` before raising
`ANNOTATION_TERMINAL_INCOMPLETE` for an unmet annotation target. Successful execution
of an empty/comment cell is no longer an acceptance mechanism. The annotation
validator explicitly does not certify the whole scientific DAG as completed.

## Existing semantics inspected, not redefined

- `scanpy_core.marker_evidence_annotation`: consumes validated `marker_result` and
  `cluster_labels`; produces `annotation_candidates` at `uns/annotation_candidates`;
  StepContract implementation is `method_family`, contract identity is
  `method-family:marker-evidence-annotation`, version 1.0.0.
- `human_confirmation`: consumes candidates and produces `confirmed_annotation` at
  `obs/cell_type`; it remains a separate human-review operation.
- `AnnotationMethodFamilyService.marker_evidence_candidates()` produces the existing
  `AnnotationMethodFamilyResult`/candidate schema and candidate-set hash.
- `AnnotationMethodFamilyService.confirm()` is still the explicit human-confirmation
  boundary. The new production delivery never calls it or assigns `cell_type`.
- Existing service validation does not resolve source IDs. The delivery boundary
  now checks supplied bindings before invoking that service; it does not create a
  second label inference engine or use the old hardcoded PBMC marker panel.
- Existing Notebook compilation had no content-level terminal check for annotation.
  The new finalization hook adds one to the Notebook channel; it does not redesign
  the controlled-execution validator registry or its authorization.
- Observed preexisting metadata discrepancy: Planner node metadata defaults absent
  `method.tool_contract_ref` to `human-review:1.0`, including this method-family node.
  The loaded StepContract above is authoritative for rendering. This fallback was
  **not changed** and must not be read as proof of human approval.

No StepContract, scientific requirement, schema, Planner choice or target was changed.

## Production integration and durable outputs

1. `CapabilityWorkspaceService` passes the already observed Ledger into Notebook
   context. No re-profiling or new representation-selection rule is added.
2. The generic compiler passes plan identity/planned operations and invokes an optional
   renderer finalization hook. Other renderers retain their prior behavior.
3. Scanpy bootstrap opens a unique `annotation-<uuid>` output directory. The marker
   producer records its successful completion; reused markers use the input Ledger.
4. The annotation cell observes the **actual** `rank_genes_groups.params.groupby`.
   It checks marker groups against current clusters, marker genes against the actual
   expression feature universe (including `.raw` where selected), ordered cell/gene
   hashes, cluster assignments, expression fingerprint, marker-output fingerprint,
   recorded staleness and existing cluster lineage.
5. With qualifying explicitly supplied evidence, it calls the existing method-family
   service, persists its result and writes the h5ad-round-trip-safe serialized schema
   to `uns/annotation_candidates`. It never writes the original h5ad.
6. Finalization reopens the persisted request/result/evidence, verifies the candidate
   hash/content and the actual `uns` content, rechecks current marker state and input
   file integrity, then records the target outcome. No key-existence-only success.

Each unique run directory contains:

```text
request.json                   observed marker state + explicit evidence bindings
marker_review_packet.json      cluster/marker packet, NOT annotation candidates
delivery.json                  result, blockers, plan/input/state/request identity
annotation_candidates.json     only when actual nonempty candidates were generated
terminal_validation.json       persisted content-level outcome
```

Unknown/conflicting candidate states remain unknown/conflicting. A later human
confirmation must use the candidate-set hash returned by the existing service;
tests verify that binding. The Notebook does not synthesize a ReviewDecision.

There is no automatic h5ad export: the candidate/result JSON is durable independently
of the kernel, while `uns` is populated in memory. A test saves to a **different**
h5ad and reloads the exact candidate result; original input bytes remain unchanged.

### Explicit evidence input, not automatic label assignment

Notebook context may explicitly supply `annotation_evidence_bundle`; its default is
None. The generated editable Notebook exposes `ANNOTATION_EVIDENCE_BUNDLE`. No RAG
query, dataset-name lookup, model switch, candidate promotion or inference is added.

The transport bundle contains `bindings`. Each binding carries:

- existing `MarkerEvidenceCandidate` payload;
- binding ID, current observed marker-state hash and existing `ApplicabilityScope`;
- source ID/revision/span ID, source-text path, SHA-256, exact UTF-8 decoded character
  offsets, exact quote and span SHA-256;
- an existing-schema `ReviewDecision` accepting that complete binding hash and ID,
  with a qualified-human/designated-owner reviewer type.

Paths resolve relative to the evidence bundle. Source bytes and the exact bounded
span must actually resolve; source ID strings alone are not support. Scientific
label/marker/scope support is supplied by the explicit human-reviewed binding, not
inferred by the validator from substring matches. This is a delivery transport,
not a new KG review/promotion mechanism or an authentication authority. It does not
independently certify the identity of a person who authored a review record.

### Runtime qualification boundary

The actual science kernel lacks `pydantic`; importing the annotation service directly
there fails. The renderer records the application interpreter and repository module
location. The science kernel imports the stdlib-only delivery interface, then uses a
bounded local metadata subprocess in the existing application environment to validate
the existing schemas/service. Only marker/candidate metadata and fingerprints cross
this boundary, not expression matrices. No package install, kernel replacement,
environment-registry mutation, network call or ExecutionRequest is performed.

This remains a local generated-Notebook dependency: moving the Notebook without the
application checkout/interpreter/evidence files requires explicit environment setup.
Unavailable dependencies produce a durable technical failure, not fallback labels.

## Validation

Final focused results: **55 passed**, zero failures/skips in the successful lanes.

| Lane | Result |
|---|---|
| Delivery/terminal tests; existing annotation method service; Scanpy adaptive Notebook; workspace; local Notebook launcher | 53 passed, 60.09 s |
| Generic Notebook compilation + non-Python renderer extensibility regression | 2 passed, 2.79 s |
| Actual temporary science kernel smoke, included above | 2 passed: supported synthetic candidates; missing-evidence incomplete terminal |
| Python compilation of all changed Python files | PASS |
| `git diff --check` | PASS |
| Older `test_notebook_shadow.py` attempted collection | ENVIRONMENT LIMITATION: application interpreter lacks `nbformat`; no dependency change or unrelated repair |

The two kernel tests execute the generated code cells unchanged on a 4-cell synthetic
fixture, with freshly launched kernels that are shut down afterward. This is not a
browser replay, a new PBMC experiment or a controlled-execution Trace. Candidate,
unknown/conflicting, raw-producer/Leiden and reused/Louvain cases are covered, as are
missing/empty/invalid evidence, wrong cluster/gene/source bindings, stale identities,
changed expression, partial coverage, uns tampering, persisted-result tampering,
human-review-only plans, source-input immutability and service failure.

Final focused commands (application Python, with `SCKG_TEST_NOTEBOOK_PYTHON` pointing
to the existing Scanpy kernel interpreter):

```text
python -m pytest -q tests/test_annotation_delivery.py tests/test_annotation_method_families.py tests/test_scanpy_adaptive_notebook.py tests/test_capability_workspace_service.py tests/test_local_notebook_launcher.py --tb=short
python -m pytest -q tests/test_capability_runtime.py::test_generic_notebook_compiles_registry_steps_without_execution tests/test_capability_extensibility_e2e.py --tb=short
```

No Seed autouse generator, full suite, benchmark or historical replay was run.

## EDD / preserved failures

| Observation | Earliest divergence / owner | Repair or disposition | Verification |
|---|---|---|---|
| Original raw plan promises candidates; 17 code cells complete but none are materialized; processed compile has same placeholder | Scanpy annotation Notebook delivery template and missing terminal check | Replace comment with existing-service-backed delivery; persist explicit missing evidence; final content validation | Focused tests and synthetic kernel smoke; old failure remains a failure |
| Direct service import fails in science interpreter (`pydantic` absent) | Application/science dependency boundary | Metadata-only call to existing application interpreter; no installs | Actual temporary kernel smoke passes |
| First new test calls Compiler with `source_artifact_id` | New test harness, before product logic | Use existing `requirement_id` signature | Initial 27 pass/1 fail; corrected related lane 43 pass |
| New smoke uses plain IPython shell; inline backend fails before annotation | New test harness, shell is not a Notebook kernel | Launch a temporary real kernel; no template edits to suppress failure | Initial 32 pass/2 fail; corrected kernel pair 2 pass |
| Broader shadow-test collection lacks `nbformat` | Existing application environment | Record limitation; do not install or claim this lane passed | Directly modified compiler/renderer paths covered separately |

Separate existing UI issue: processed workspace retained a raw Jupyter link. No
session-state/UI repair was made. Before any future browser replay, verify the
input artifact, plan ID, Notebook ID/hash and Jupyter link agree; do not click stale
links. No new browser replay was performed here.

## Preservation and remaining inputs

- Original replay directory remains untouched:
  `data/evaluation/current_version_pbmc3k_replay_v1/pbmc3k-current-20260918T180501Z/`.
- Original report remains unchanged:
  `docs/status/CURRENT_VERSION_PBMC3K_REPLAY_V1.md`.
- All 224 files independently hashed at this repair's start remain unchanged.
- Of the earlier replay's 642 protected files, only the three intentional existing
  production integration files changed. The other 639 are unchanged.
- Both historical Notebook hashes and historical Trace prefix are unchanged.
- Input raw SHA: `89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1`.
- Input processed SHA: `0db367b991dd95809732b218539ede489bea99113807f62ebd7ccc970025fe38`.
- No RAG/KG/candidate review/Planner selection/contract/gold/policy changes.

Still needed: genuine cluster-specific marker-to-label evidence, exact resolvable
source spans and scoped review bindings; subsequently a real human confirmation
bound to the resulting candidate set. This checkpoint supplies neither by invention.
Without those inputs, a future replay should honestly stop as annotation-incomplete.

Changed/new implementation and tests:

```text
engine/capability_workspace_service.py
execution/capability_notebook.py
execution/renderers/scanpy_core.py
execution/annotation_delivery.py
tests/test_annotation_delivery.py
```

New review artifacts:

```text
docs/status/ANNOTATION_DELIVERY_REPAIR_V1.md
data/evaluation/annotation_delivery_repair_v1/validation.json
data/evaluation/annotation_delivery_repair_v1/synthetic_examples.json
```

Synthetic examples retain actual test delivery/terminal payloads and their original
SHA-256 values. They are illustrative test outputs, not a self-contained real evidence
bundle, real review records or revised PBMC results. New files remain for review;
unrelated untracked directories were neither staged nor removed.
