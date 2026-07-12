args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L || args[[1L]] != "r_request.json") {
  stop("scDblFinder wrapper requires fixed r_request.json")
}

required_packages <- c(
  "scDblFinder",
  "SingleCellExperiment",
  "Matrix",
  "jsonlite",
  "BiocParallel",
  "SummarizedExperiment"
)
available <- vapply(required_packages, requireNamespace, logical(1L), quietly = TRUE)
if (!all(available)) {
  stop(paste("required R packages missing:", paste(required_packages[!available], collapse = ",")))
}

request <- jsonlite::read_json(args[[1L]], simplifyVector = TRUE)
expected_fields <- sort(c(
  "artifacts_dir",
  "cell_ids_path",
  "counts_path",
  "expected_cells",
  "fixture_id",
  "input_hash",
  "parameters",
  "purpose",
  "user_data_used"
))
if (!identical(sort(names(request)), expected_fields)) {
  stop("invalid R request fields")
}
if (request$purpose != "synthetic_qualification" || isTRUE(request$user_data_used)) {
  stop("wrapper only permits synthetic qualification")
}
if (request$artifacts_dir != "artifacts" || request$counts_path != "r_input/counts.mtx") {
  stop("wrapper paths are fixed")
}

counts <- Matrix::readMM(request$counts_path)
cell_ids <- readLines(request$cell_ids_path, warn = FALSE)
if (nrow(counts) != request$expected_cells || length(cell_ids) != request$expected_cells) {
  stop("input cell count mismatch")
}
if (any(!is.finite(counts@x)) || any(counts@x < 0) || any(counts@x != round(counts@x))) {
  stop("counts must be finite non-negative integers")
}

params <- request$parameters
if (!identical(params$clusters, FALSE)) {
  stop("clusters must remain false")
}
set.seed(as.integer(params$random_state))
sce <- SingleCellExperiment::SingleCellExperiment(list(counts = Matrix::t(counts)))
colnames(sce) <- cell_ids
parallel_param <- if (as.integer(params$n_cores) == 1L) {
  BiocParallel::SerialParam()
} else {
  BiocParallel::SnowParam(
    workers = as.integer(params$n_cores),
    type = "SOCK",
    progressbar = FALSE
  )
}
sce <- scDblFinder::scDblFinder(
  sce,
  dbr = as.numeric(params$dbr),
  clusters = FALSE,
  BPPARAM = parallel_param
)

scores <- as.numeric(SummarizedExperiment::colData(sce)$scDblFinder.score)
classes <- as.character(SummarizedExperiment::colData(sce)$scDblFinder.class)
if (length(scores) != length(cell_ids) || length(classes) != length(cell_ids)) {
  stop("scDblFinder output length mismatch")
}
predicted <- classes == "doublet"
result <- data.frame(
  cell_id = cell_ids,
  doublet_score = scores,
  predicted_doublet = ifelse(predicted, "true", "false"),
  stringsAsFactors = FALSE
)
dir.create("artifacts", showWarnings = FALSE)
write.table(
  result,
  file = "artifacts/doublet_results.tsv",
  sep = "\t",
  row.names = FALSE,
  quote = FALSE
)
jsonlite::write_json(
  params,
  path = "artifacts/parameters.json",
  auto_unbox = TRUE,
  pretty = TRUE
)
metadata <- list(
  fixture_id = request$fixture_id,
  input_hash = request$input_hash,
  n_cells = length(cell_ids),
  output_fields = c("cell_id", "doublet_score", "predicted_doublet"),
  qualification_mode = TRUE,
  scdblfinder_actually_executed = TRUE,
  scdblfinder_version = as.character(utils::packageVersion("scDblFinder")),
  execution_purpose = request$purpose,
  synthetic_fixture = TRUE,
  user_data_used = FALSE
)
jsonlite::write_json(
  metadata,
  path = "artifacts/result_metadata.json",
  auto_unbox = TRUE,
  pretty = TRUE
)
cat(jsonlite::toJSON(metadata, auto_unbox = TRUE), "\n")
