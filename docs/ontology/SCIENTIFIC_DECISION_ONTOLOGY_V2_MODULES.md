# Ontology v2 Core modules

Design proposal `2.0.0-core-review.1`, targeted correction `5C.1-N01-N05`; QA recheck pending.

| Module | Core object types | Owner |
|---|---|---|
| scKG-core | ScientificTask, Method, MethodVariant, SoftwareProject, Package, PackageRelease, Operator, OperatorRevision, ParameterDefinition, ReferenceArtifact, ReferenceArtifactRevision | Scientific knowledge |
| scKG-representation | RepresentationType, RepresentationConstraint, InputPort, OutputPort, Requirement | Scientific knowledge |
| scKG-statement | ScientificStatement, StatementRevision, ApplicabilityScope | Scientific knowledge |
| scKG-evidence | SourceWork, SourceRevision, SourceArtifact, EvidenceSpan, EvidenceAssessment, EvidenceGap | Scientific knowledge |
| runtime-bridge | RepresentationRecord | Existing RepresentationLedger; reference only |

Core count: 25 scientific objects + 1 runtime reference type. No implicit
inheritance/interfaces. Identity/revision membership is limited to:

| Revision | Stable identity |
|---|---|
| PackageRelease | Package |
| OperatorRevision | Operator |
| SourceRevision | SourceWork |
| StatementRevision | ScientificStatement |
| ReferenceArtifactRevision | ReferenceArtifact |

`SourceRevision → PackageRelease` is invalid. OperatorRevision release binding
must use a PackageRelease whose Package also owns the corresponding Operator.
Each InputPort/OutputPort has one owning OperatorRevision. Output lineage may
reference only its owner's InputPorts. ParameterDefinition belongs to an Operator;
release-specific has_parameter links must agree with that owner.

## Minimal reference-resource core (N02)

ReferenceArtifact and ReferenceArtifactRevision now belong to scKG-core, matching
existing v1 scientific model/atlas/mapping needs. The revision requires a version
and immutable byte digest. `requires_reference` is restored from the historical
link proposal with Requirement → ReferenceArtifactRevision endpoints; it and
`requires_constraint` jointly satisfy the minimum-one-target requirement. This
adds one Core link, without a reference predicate family or resource-management
implementation.

## Extension objects (7)

- IdentityAssertion: independently reviewable assertion **about two resources**.
- MetricDefinition, EvaluationDataset, BenchmarkStudy, EmpiricalResult: bounded
  comparison extension, including splits, leakage controls and protocols.
- ReviewDecision, SupersessionRecord: external governance records; none created.

Extensions are named design dependencies, not fully specified executable modules.
Their endpoint names are not admitted to core links merely by being listed here.

## Deferred objects (8)

ExtractionRun, ReviewActivity, EvidenceDriftAssessment, OntologyConceptRevision,
OntologyMigrationPlan, GovernedAction, ActionPolicy, TraceSpan. Their provenance,
drift, ontology change, authorization and trace contracts await separate review.

## Merged compatibility surfaces (4)

| design.1 type | 5C disposition |
|---|---|
| AtomicClaimRevision | Conceptual StatementRevision-compatible view; no adapter |
| Limitation | Statement assertion_kind; reusable limitation taxonomy deferred |
| DerivedRelation | Derived link provenance metadata; no core fact object |
| RepresentationInstanceBinding | Existing runtime binding; never scientific ownership |

All 45 historical class candidates are accounted for by these sets. The extension
and deferred registries preserve the reasons and CQ references; no historical
artifact is deleted or overwritten.

## Actual repository owners

| Surface | Existing authority |
|---|---|
| Scientific v1.1 schema | `core/scientific_knowledge_conformance_models.py` |
| Exported candidate JSON schemas | `data_pipeline/build_scientific_knowledge_conformance_v1_1.py` generates from those models |
| Candidate inventory projections | `data_pipeline/build_scientific_kg_v1_inventory.py` |
| Catalog KG record types | `core/knowledge_graph_models.py` |
| Canonical task vocabulary | `core/canonical_task_ontology.py`, consumed by `core/kg_ontology.py` |
| Runtime representation state | `core/representation_models.py` |
| Pilot source identity dictionaries | `data_pipeline/run_evidence_gap_acquisition_pilot_v1.py` |
| Historical design generator | `eval/scientific_decision_ontology_v2_design_audit.py` |

The historical 21 “physical classes” were observed in the **candidate consolidated
inventory**, not verified as production Neo4j classes. The old generator projected
claim predicates from claim nodes, so observed graph edge domains are not semantic
predicate domains. This review does not change any of these owners.
