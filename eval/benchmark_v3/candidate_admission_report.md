# Phase 2.2 Candidate Admission Audit

Admission is independent of 07 performance. `suitable_for_candidate=false` leaves the
source in the raw-seed inventory and removes its identity draft from the active candidate pool.
No item gains Gold or a split assignment.

| candidate | source title/query | standalone | needs version | needs reproducer | needs data state | suitable | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `candidate-pilot-01` | Reorg io functions | `false` | `true` | `false` | `false` | `false` | `demoted_to_raw_only` |
| `candidate-pilot-02` | `rank_genes_groups(method="t-test", mean_in_log_space=False)` runs the t-test on exponentiated values | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-03` | Feature Request: Change the default value of `margin` parameter to 2 in `NormalizeData()` for CLR normalization | `false` | `true` | `false` | `false` | `true` | `retained` |
| `candidate-pilot-04` | A notebook stopped after neighbors were recomputed but before UMAP and clustering were rerun. How should an agent determine which artifacts are stale before resuming? | `true` | `false` | `false` | `true` | `true` | `retained` |
| `candidate-pilot-05` | The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation? | `true` | `true` | `false` | `false` | `true` | `retained` |
| `candidate-pilot-06` | A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion? | `true` | `false` | `false` | `false` | `true` | `retained` |
| `candidate-pilot-07` | BUG: Potential issue in parallel memory usage | `false` | `true` | `true` | `true` | `false` | `demoted_to_raw_only` |
| `candidate-pilot-08` | PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero) | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-09` | RNA assay has no layers after running harmony integration followed by rejoining layers | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-10` | Does FindClusters order/renumber clusters by size (largest cluster first) | `false` | `true` | `false` | `false` | `true` | `retained` |
| `candidate-pilot-11` | BUG: FindClusters function always fall back to Louvain clustering even if I tried both leidenbase and igraph methods | `false` | `true` | `true` | `false` | `true` | `retained` |
| `candidate-pilot-12` | BUG: MapQuery gives aberrant results if reference is subset after RunUMAP | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-13` | RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-14` | sc.pl.paga raises TypeError when cax is passed with multiple colors | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-15` | `calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var` | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-16` | `highly_variable_genes` with `batch_key` and `subset=True` keeps the wrong genes when `n_top_genes` is not set | `false` | `true` | `true` | `true` | `true` | `retained` |
| `candidate-pilot-17` | Which immune cell type has the highest number of significantly differentially expressed genes after AAV9 mini-dystrophin treatment? | `false` | `true` | `false` | `true` | `true` | `retained` |
| `candidate-pilot-18` | Using the provided RNA-seq count data and metadata files, perform DESeq2 differential expression analysis to identify significant DEGs (padj < 0.05), then run enrichGO analysis with clusterProfiler::simplify() (similarity > 0.7). What is the approximate adjusted p-value (rounded to 4 decimal points) for "regulation of T cell activation" in the resulting simplified GO enrichment results? | `false` | `true` | `false` | `true` | `true` | `retained` |
| `candidate-pilot-19` | Train a cell counting model on the BBBC002 datasets containing Drosophila KC167 cells. Save the test set predictions as a single column "count" to "pred_results/cell-count_pred.csv". | `false` | `true` | `false` | `true` | `true` | `retained` |
| `candidate-pilot-20` | Train a drug-target interaction model using the DAVIS dataset to determine the binding affinity between several drugs and targets. Then use the trained model to predict the binding affinities between antiviral drugs and COVID-19 target. Rank the antiviral drugs based on their predicted affinities and save the ordered list of drugs to "pred_results/davis_dti_repurposing.txt", with one drug name per line. | `false` | `true` | `false` | `true` | `true` | `retained` |

Demoted raw-only titles:

- `candidate-pilot-01` — “Reorg io functions”.
- `candidate-pilot-07` — “BUG: Potential issue in parallel memory usage”.

Both source seeds remain unchanged in `raw_seeds_pilot.jsonl`.
