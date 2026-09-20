# Phase 2 Pilot Cluster Report

Run: `pilot-20260920-v1`
Records: 48
Provisional clusters: 8

This is a deterministic lexical inventory smoke test, not a task taxonomy or Gold label.
TF-IDF unigrams/bigrams (512-feature cap) feed average-linkage agglomerative
clustering with cosine distance and `n_clusters=8`. Cluster names are
top-term summaries and every cluster remains `needs_adjudication`.

## cluster-01: number / bug / layers

- Size: 35
- Origins: `{"controlled-probe": 7, "real-user": 28}`
- Sources: `{"benchmark-v3-controlled-probes": 7, "satijalab/seurat issues": 19, "scverse/scanpy issues": 9}`
- Top terms: `number`, `bug`, `layers`, `function`, `documentation`, `loadxenium`
- Example seeds:

  - `controlled:evidence-version-conflict` — The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation?
  - `controlled:execution-package-drift` — A saved workflow requires a package version incompatible with the current environment. How should the agent separate plan validity from execution failure?
  - `controlled:planning-authorization` — An analysis plan would overwrite an existing h5ad file. What approval and artifact-preservation steps are required before execution?

Review status: `needs_adjudication`.

## cluster-02: list / documented / list read_zarr

- Size: 3
- Origins: `{"controlled-probe": 1, "real-user": 2}`
- Sources: `{"benchmark-v3-controlled-probes": 1, "scverse/scanpy issues": 2}`
- Top terms: `list`, `documented`, `list read_zarr`, `read_zarr`, `docs`, `read_zarr docs`
- Example seeds:

  - `controlled:scope-species-mismatch` — A marker list is documented for mouse, while the loaded AnnData uses human gene symbols. What scope checks are required before cell-type annotation?
  - `github:scverse_scanpy:4332` — list read_zarr in docs
  - `github:scverse_scanpy:4341` — The `.uns` output for `scanpy.pp.highly_variable_genes` is not documented

Review status: `needs_adjudication`.

## cluster-03: sketchdata / sketchdata combat-seq / compatibility

- Size: 1
- Origins: `{"real-user": 1}`
- Sources: `{"satijalab/seurat issues": 1}`
- Top terms: `sketchdata`, `sketchdata combat-seq`, `compatibility`, `combat-seq compatibility`, `combat-seq`
- Example seeds:

  - `github:satijalab_seurat:10446` — SketchData and ComBat-seq compatibility

Review status: `needs_adjudication`.

## cluster-04: tutorials repo / tutorials / repo

- Size: 1
- Origins: `{"real-user": 1}`
- Sources: `{"scverse/scanpy issues": 1}`
- Top terms: `tutorials repo`, `tutorials`, `repo`
- Example seeds:

  - `github:scverse_scanpy:4281` — Move tutorials into repo

Review status: `needs_adjudication`.

## cluster-05: deprecate sc.external / deprecate / sc.external

- Size: 1
- Origins: `{"real-user": 1}`
- Sources: `{"scverse/scanpy issues": 1}`
- Top terms: `deprecate sc.external`, `deprecate`, `sc.external`
- Example seeds:

  - `github:scverse_scanpy:4295` — deprecate `sc.external`

Review status: `needs_adjudication`.

## cluster-06: anndata.acc / functions / based api

- Size: 5
- Origins: `{"real-user": 5}`
- Sources: `{"scverse/scanpy issues": 5}`
- Top terms: `anndata.acc`, `functions`, `based api`, `based`, `anndata.acc based`, `api`
- Example seeds:

  - `github:scverse_scanpy:4296` — Reorg io functions
  - `github:scverse_scanpy:4314` — Have `use_rep` accept `anndata.acc` acessors
  - `github:scverse_scanpy:4331` — `anndata.acc` based API for `mask`/`mask_{obs,var}`

Review status: `needs_adjudication`.

## cluster-07: scanpy.pp.bbknn / adopt scanpy.pp.bbknn / adopt

- Size: 1
- Origins: `{"real-user": 1}`
- Sources: `{"scverse/scanpy issues": 1}`
- Top terms: `scanpy.pp.bbknn`, `adopt scanpy.pp.bbknn`, `adopt`
- Example seeds:

  - `github:scverse_scanpy:4302` — Adopt `scanpy.pp.bbknn`

Review status: `needs_adjudication`.

## cluster-08: sc.pp / sc.external.pp.hashsolo sc.pp / sc.external.pp.hashsolo

- Size: 1
- Origins: `{"real-user": 1}`
- Sources: `{"scverse/scanpy issues": 1}`
- Top terms: `sc.pp`, `sc.external.pp.hashsolo sc.pp`, `sc.external.pp.hashsolo`
- Example seeds:

  - `github:scverse_scanpy:4304` — move `sc.external.pp.hashsolo` into `sc.pp`

Review status: `needs_adjudication`.
