suppressPackageStartupMessages({
  library(jsonlite)
  library(Matrix)
  library(SingleCellExperiment)
  library(SingleR)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L || args[[1L]] != "r_request.json") {
  stop("SingleR wrapper accepts only ./r_request.json")
}
request <- fromJSON(args[[1L]], simplifyVector = FALSE)
expression <- readMM(request$expression_path)
cell_ids <- readLines(request$cell_ids_path, warn = FALSE)
gene_ids <- readLines(request$gene_ids_path, warn = FALSE)
if (ncol(expression) != length(gene_ids) || nrow(expression) != length(cell_ids)) {
  stop("SingleR input dimensions do not match identifiers")
}
rownames(expression) <- cell_ids
colnames(expression) <- gene_ids
reference <- readRDS(request$reference_path)
test <- SingleCellExperiment(list(logcounts = t(expression)))
prediction <- SingleR(
  test = test,
  ref = reference,
  labels = colData(reference)[[request$parameters$label_field]],
  assay.type.test = request$parameters$assay_type_test,
  assay.type.ref = request$parameters$assay_type_reference,
  de.method = request$parameters$de_method,
  fine.tune = request$parameters$fine_tune,
  prune = request$parameters$prune
)
labels <- if (isTRUE(request$parameters$prune)) prediction$pruned.labels else prediction$labels
unknown <- is.na(labels) | labels == ""
labels[unknown] <- "unknown"
label_table <- data.frame(
  cell_id = cell_ids,
  predicted_label = labels,
  unknown = unknown,
  stringsAsFactors = FALSE
)
score_table <- as.data.frame(prediction$scores)
score_table <- cbind(cell_id = cell_ids, score_table)
write.table(
  label_table,
  file.path(request$artifacts_dir, "predicted_labels.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)
write.table(
  score_table,
  file.path(request$artifacts_dir, "annotation_scores.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)
write_json(
  list(
    parameters = request$parameters,
    reference_id = request$reference_id,
    reference_digest = request$reference_digest
  ),
  file.path(request$artifacts_dir, "parameters.json"),
  auto_unbox = TRUE,
  pretty = TRUE
)
write_json(
  list(
    tool_name = "SingleR",
    tool_version = as.character(packageVersion("SingleR")),
    input_hash = request$input_hash,
    cell_count = length(cell_ids),
    reference_id = request$reference_id,
    reference_digest = request$reference_digest,
    runtime_network_used = FALSE
  ),
  file.path(request$artifacts_dir, "result_metadata.json"),
  auto_unbox = TRUE,
  pretty = TRUE
)
