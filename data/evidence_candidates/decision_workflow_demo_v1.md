# scKG Decision Workflow Demo v1

Evidence-governed single-cell analysis decision workflow. This is broader than a ranked tool report: it returns an auditable workflow plan, candidate tools, evidence snippets, code skeletons, and gaps.

## Scenario

- Query: I have multi-sample 10x PBMC scRNA-seq data and want QC, doublet detection, batch integration, cell type annotation, and optional trajectory analysis.
- Modality: scRNA-seq
- Output goal: integrated, doublet-filtered, annotated PBMC object with an auditable report

## Workflow

### 1. Input and QC precheck

- Task: QC
- Default candidate: Scanpy
- Candidate tools: Scanpy, Seurat
- Evidence snippets: 5 (Scanpy, Seurat)
- Status: plan_only_evidence_limited
- Policy: Use the ecosystem that matches downstream execution; do not mix object schemas without validation.
- Warnings: Scanpy is a broad toolkit; module-level representation is required before precise migration claims. | Seurat is a broad toolkit; module-level representation is required before precise migration claims.

### 2. Doublet detection

- Task: Doublet Detection
- Default candidate: Scrublet
- Candidate tools: Scrublet, DoubletFinder
- Evidence snippets: 5 (DoubletFinder, Scrublet)
- Status: plan_only_evidence_limited
- Policy: Prefer tools with source text and benchmark evidence discovery; thresholds require sample-aware review.

### 3. Normalization and HVG selection

- Task: Normalization
- Default candidate: Scanpy
- Candidate tools: Scanpy, Seurat, scvi-tools
- Evidence snippets: 5 (Scanpy, Seurat, scvi-tools)
- Status: plan_only_evidence_limited
- Policy: Keep normalization assumptions consistent with the chosen integration method.
- Warnings: Scanpy is a broad toolkit; module-level representation is required before precise migration claims. | Seurat is a broad toolkit; module-level representation is required before precise migration claims. | scvi-tools is a broad toolkit; module-level representation is required before precise migration claims.

### 4. Batch-aware integration

- Task: Data Integration
- Default candidate: Harmony
- Candidate tools: Harmony, scvi-tools, Seurat
- Evidence snippets: 5 (Harmony, Seurat, scvi-tools)
- Status: plan_only_evidence_limited
- Policy: Use graph/task compatibility plus benchmark source context; do not treat integration score as universal across datasets.
- Warnings: scvi-tools is a broad toolkit; module-level representation is required before precise migration claims. | Seurat is a broad toolkit; module-level representation is required before precise migration claims.

### 5. Cell type annotation

- Task: Cell Type Annotation
- Default candidate: CellTypist
- Candidate tools: CellTypist, SingleR, Seurat
- Evidence snippets: 5 (CellTypist, Seurat, SingleR)
- Status: plan_only_evidence_limited
- Policy: Use annotation tools as candidates only until benchmark DOI/source mismatch is fixed for the frozen benchmark rows.
- Warnings: CellTypist/SingleR benchmark source currently has a wrong DOI/source mismatch; keep benchmark claims blocked. | Seurat is a broad toolkit; module-level representation is required before precise migration claims.

### 6. Optional trajectory and fate analysis

- Task: Trajectory Inference
- Default candidate: scVelo
- Candidate tools: scVelo, CellRank
- Evidence snippets: 5 (CellRank, scVelo)
- Status: plan_only_evidence_limited
- Policy: Treat as optional because PBMC steady-state analysis often does not require trajectory inference.

### 7. Evidence audit and report

- Task: Evidence Governance
- Default candidate: scKG-Agent
- Candidate tools: scKG-Agent
- Evidence snippets: 5 (none)
- Status: plan_only_evidence_limited
- Policy: RAG snippets explain context; only reviewed formal evidence can support strong recommendation wording.
- Warnings: Some candidate tools have no retrieved source snippet for this step.

## Guardrail

This demo does not promote formal TSV evidence, does not write Neo4j, and does not change MCDM ranks.

## Next Actions

- Fix source_metadata_mismatch for CellTypist/SingleR annotation benchmark before using it as strong benchmark support.
- Repair Seurat v3/v4 publication extraction or use publisher HTML/full text.
- Add workflow path eval set for 5-10 single-cell scenarios.
- Add module-level representations for Seurat, Scanpy, and scvi-tools.
