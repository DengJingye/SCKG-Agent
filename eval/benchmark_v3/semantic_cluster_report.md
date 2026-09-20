# Phase 2.1 Semantic Clustering Smoke Report

Run: `candidate-audit-20260921-v1`

Records: 56

Clusters: 10

Largest cluster: 10/56 (17.9%)

This experiment replaces the title-only lexical clustering smoke test with a fixed
local latent-semantic baseline. It concatenates question text, repository/package
identity, permitted labels/categories, and version hints; TF-IDF is projected through
32-component LSA, L2-normalized, then
clustered by KMeans. Model=`sklearn-tfidf-lsa-v1` version=`1.0.0`, scikit-learn=`1.5.2`, seed=`20260921`. It is a sampling/review aid only and creates no Gold label.

Cosine silhouette (descriptive only): `0.269349`.

| Cluster | Size | Origins | Top terms | Examples |
| --- | ---: | --- | --- | --- |
| `semantic-01` | 7 | `{"controlled-probe": 7}` | package_or_repository benchmark-v3-controlled-probes, benchmark-v3-controlled-probes permitted_labels_or_categories, version_hints v1, v1, benchmark-v3-controlled-probes | The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation? / A saved workflow requires a package version incompatible with the current environment. How should the agent separate plan validity from execution failure? |
| `semantic-02` | 2 | `{"controlled-probe": 1, "real-user": 1}` | counts, runpca reproducibility, uwot, counts unpinned, unpinned | A Scanpy object has counts in layers['counts'], normalized values in X, and an old raw snapshot. What state must be inspected before choosing the matrix for differential expression? / RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults |
| `semantic-03` | 9 | `{"real-user": 9}` | bug, permitted_labels_or_categories bug, bug version_hints, question bug, satijalab | BUG: Potential issue in parallel memory usage / PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero) |
| `semantic-04` | 10 | `{"real-user": 10}` | package_or_repository satijalab, seurat, satijalab, satijalab seurat, seurat permitted_labels_or_categories | RNA assay has no layers after running harmony integration followed by rejoining layers / Feature Request: Change the default value of `margin` parameter to 2 in `NormalizeData()` for CLR normalization |
| `semantic-05` | 8 | `{"real-user": 8}` | scverse scanpy, scanpy permitted_labels_or_categories, scverse, package_or_repository scverse, scanpy | Move tutorials into repo / log1p warning when modifying several layers |
| `semantic-06` | 4 | `{"real-user": 4}` | area, permitted_labels_or_categories area, area preprocessing, preprocessing, preprocessing version_hints | Pre 2.0 janitor work / deprecate `sc.external` |
| `semantic-07` | 4 | `{"real-user": 4}` | api, area api, anndata.acc, api version_hints, area | Have `use_rep` accept `anndata.acc` acessors / `anndata.acc` based API for `mask`/`mask_{obs,var}` |
| `semantic-08` | 4 | `{"real-user": 4}` | triage, triage version_hints, permitted_labels_or_categories triage, scanpy permitted_labels_or_categories, package_or_repository scverse | list read_zarr in docs / sc.external.exporting.cellbrowser: cellbrowser_raw_data\sample_colors.tsv does not exist, skipping it An exception has occurred, use %tb to see the full traceback. |
| `semantic-09` | 4 | `{"paper-notebook": 4}` | analysis, version_hints f8cc3bdcc6357c88b8c3648306522b9c422dc95a, bixbench permitted_labels_or_categories, f8cc3bdcc6357c88b8c3648306522b9c422dc95a, futurehouse bixbench | Using the provided RNA-seq count data and metadata files, perform DESeq2 differential expression analysis to identify significant DEGs (padj < 0.05), then run enrichGO analysis with clusterProfiler::simplify() (similarity > 0.7). What is the approximate adjusted p-value (rounded to 4 decimal points) for "regulation of T cell activation" in the resulting simplified GO enrichment results? / Perform hierarchical clustering with 3 clusters using a bootstrap consensus approach (50 iterations, 70/30 train-test splits with logistic regression for label prediction) and determine how many samples are consistently classified into the same cluster across both training and test consensus clustering. |
| `semantic-10` | 4 | `{"paper-notebook": 4}` | version_hints 9c6e96c9e74572e979b0930ee735041cef528cb7, scienceagentbench permitted_labels_or_categories, 9c6e96c9e74572e979b0930ee735041cef528cb7, save, package_or_repository osunlp | Train a cell counting model on the BBBC002 datasets containing Drosophila KC167 cells. Save the test set predictions as a single column "count" to "pred_results/cell-count_pred.csv". / Train a drug-target interaction model using the DAVIS dataset to determine the binding affinity between several drugs and targets. Then use the trained model to predict the binding affinities between antiviral drugs and COVID-19 target. Rank the antiviral drugs based on their predicted affinities and save the ordered list of drugs to "pred_results/davis_dti_repurposing.txt", with one drug name per line. |

The largest-cluster share is compared with the Phase 2 lexical result (35/48 =
72.9%) only as a smoke-test diagnostic. No cluster membership is used as a scientific
label, coverage label, answerability label, or split assignment.
