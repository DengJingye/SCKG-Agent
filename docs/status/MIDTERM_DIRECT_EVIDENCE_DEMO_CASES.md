# Midterm Direct-Evidence Demo Cases

These four production-path examples are suitable for the midterm demo or screenshots. They are qualification examples from the existing candidate Scientific KG, not benchmark claims. Product UI should show the question, decision, evidence text, and citation; the internal qualification metadata below is for presenter notes.

## HVG

**User question**
In Scanpy 1.11.2, what output does scanpy.pp.highly_variable_genes store?

**Decision**
`SUPPORTED` — direct, source-bound evidence was returned by the production `search_evidence` path.

**Evidence shown to the user**
boolean indicator of highly-variable genes

**Citation and provenance**

- Source: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Source span: `src/scanpy/preprocessing/_highly_variable_genes.py#L622-L627`
- OperatorRevision: `operator-revision:scanpy.pp.highly_variable_genes:1.11.2:uat-corrected`
- Claim: `claim-revision:uat:hvg-output:v1`
- EvidenceSpan: `scanpy-authoritative-span:hvg.output:1.11.2`
- SourceRevision: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Knowledge status: `candidate`

## PCA

**User question**
What input matrix does scanpy.pp.pca in Scanpy 1.11.2 accept?

**Decision**
`SUPPORTED` — direct, source-bound evidence was returned by the production `search_evidence` path.

**Evidence shown to the user**
Rows correspond to cells and columns to genes.

**Citation and provenance**

- Source: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Source span: `src/scanpy/preprocessing/_pca/__init__.py#L108-L115`
- OperatorRevision: `operator-revision:scanpy.pp.pca:1.11.2:uat-corrected`
- Claim: `claim-revision:uat:pca-expression:v1, claim-revision:uat:pca-mask-optional:v1`
- EvidenceSpan: `scanpy-authoritative-span:pca.input:1.11.2, scanpy-authoritative-span:pca.mask:1.11.2`
- SourceRevision: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Knowledge status: `candidate`

## UMAP

**User question**
What input does scanpy.tl.umap in Scanpy 1.11.2 require?

**Decision**
`SUPPORTED` — direct, source-bound evidence was returned by the production `search_evidence` path.

**Evidence shown to the user**
for neighbors settings

**Citation and provenance**

- Source: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Source span: `src/scanpy/tools/_umap.py#L142-L145`
- OperatorRevision: `operator-revision:scanpy.tl.umap:1.11.2:uat-corrected`
- Claim: `claim-revision:uat:umap-input:v1`
- EvidenceSpan: `scanpy-authoritative-span:umap.input:1.11.2`
- SourceRevision: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Knowledge status: `candidate`

## LEIDEN

**User question**
What input does scanpy.tl.leiden in Scanpy 1.11.2 accept?

**Decision**
`SUPPORTED` — direct, source-bound evidence was returned by the production `search_evidence` path.

**Evidence shown to the user**
Sparse adjacency matrix of the graph, defaults to neighbors connectivities.

**Citation and provenance**

- Source: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Source span: `src/scanpy/tools/_leiden.py#L72-L99`
- OperatorRevision: `operator-revision:scanpy.tl.leiden:1.11.2:uat-corrected`
- Claim: `claim-revision:uat:leiden-input:v1`
- EvidenceSpan: `scanpy-authoritative-span:leiden.input:1.11.2`
- SourceRevision: `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`
- Knowledge status: `candidate`
