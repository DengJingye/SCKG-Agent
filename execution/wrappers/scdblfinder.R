args <- commandArgs(trailingOnly = TRUE)
if (length(args) == 1L && args[[1L]] == "--help") {
  cat("Usage: Rscript scdblfinder.R r_request.json\n")
  cat("Runs the fixed maintainer-only synthetic qualification request.\n")
  quit(status = 0L)
}
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
  "accession",
  "artifacts_dir",
  "cell_ids_path",
  "counts_path",
  "expected_cells",
  "fixture_id",
  "ground_truth_path",
  "input_hash",
  "parameters",
  "public_dataset",
  "purpose",
  "synthetic_fixture",
  "user_data_used"
))
if (!identical(sort(names(request)), expected_fields)) {
  stop("invalid R request fields")
}
if (isTRUE(request$user_data_used)) {
  stop("wrapper forbids user data")
}
if (request$purpose == "synthetic_qualification") {
  if (!isTRUE(request$synthetic_fixture) || isTRUE(request$public_dataset)) {
    stop("synthetic qualification requires a synthetic fixture")
  }
} else if (request$purpose == "scientific_pilot") {
  if (request$accession != "GSE108313" || !isTRUE(request$public_dataset) || isTRUE(request$synthetic_fixture)) {
    stop("scientific pilot requires allowlisted public GSE108313")
  }
} else {
  stop("unsupported execution purpose")
}
if (request$artifacts_dir != "artifacts" || request$counts_path != "r_input/counts.mtx") {
  stop("wrapper paths are fixed")
}

counts <- Matrix::readMM(request$counts_path)
cell_ids <- readLines(request$cell_ids_path, warn = FALSE)
ground_truth <- readLines(request$ground_truth_path, warn = FALSE)
if (nrow(counts) != request$expected_cells || length(cell_ids) != request$expected_cells || length(ground_truth) != request$expected_cells) {
  stop("input cell count mismatch")
}
if (any(!ground_truth %in% c("true", "false"))) {
  stop("ground truth labels must be boolean")
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
  obs_id = cell_ids,
  doublet_score = scores,
  predicted_doublet = ifelse(predicted, "true", "false"),
  ground_truth_doublet = ground_truth,
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
  public_dataset = isTRUE(request$public_dataset),
  accession = request$accession,
  synthetic_fixture = isTRUE(request$synthetic_fixture),
  user_data_used = FALSE
)
jsonlite::write_json(
  metadata,
  path = "artifacts/result_metadata.json",
  auto_unbox = TRUE,
  pretty = TRUE
)
cat(jsonlite::toJSON(metadata, auto_unbox = TRUE), "\n")
