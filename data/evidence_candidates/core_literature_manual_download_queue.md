# scKG Core Literature Resolution Queue

This queue lists unresolved paper/protocol/benchmark source rows.

Current unresolved rows are not automatically PDF download tasks. Check the action field:

- `resolve_wrong_doi_or_replace_source`: do not download; fix the wrong DOI/source or replace the benchmark source.
- `pdf_extraction_failed_use_alternate_text_or_repair`: PDF already exists; repair extraction, use HTML/full text, or replace with an extractable PDF.
- `manual_search_required` / `manual_download_or_browser_login`: only these actions are download/search tasks.

- source rows: 23
- source text available: 19
- source text too short: 0
- missing source text: 4
- min source text chars: 1000

Guardrail: source text is evidence discovery input only. It does not promote formal TSV evidence.

## resolve_wrong_doi_or_replace_source (2)

- CellTypist / benchmark: A comprehensive benchmarking of cell type annotation methods for single-cell RNA sequencing
  - DOI/source: https://doi.org/10.1093/bib/bbad418
  - Do not save/download the listed bad candidate PDF.
  - Next step: correct the DOI/source record or replace this benchmark source.
  - Current text chars: 0
  - Candidate issue: metadata_mismatch_pdf_title_or_doi
  - Selected PDF URL: (none)
  - Candidate URLs: (none)
  - Notes: Candidate PDF title is PanomiR: a systems biology framework for analysis of multi-pathway targeting by miRNAs; do not use for cell type annotation benchmark.

- SingleR / benchmark: A comprehensive benchmarking of cell type annotation methods for single-cell RNA sequencing
  - DOI/source: https://doi.org/10.1093/bib/bbad418
  - Do not save/download the listed bad candidate PDF.
  - Next step: correct the DOI/source record or replace this benchmark source.
  - Current text chars: 0
  - Candidate issue: metadata_mismatch_pdf_title_or_doi
  - Selected PDF URL: (none)
  - Candidate URLs: (none)
  - Notes: Candidate PDF title is PanomiR: a systems biology framework for analysis of multi-pathway targeting by miRNAs; do not use for cell type annotation benchmark.

## pdf_extraction_failed_use_alternate_text_or_repair (2)

- Seurat / publication: Comprehensive Integration of Single-Cell Data
  - DOI/source: https://doi.org/10.1016/j.cell.2019.05.031
  - Existing PDF: `data/evidence_sources/pdfs/news/Seurat_CAND_PUB_Seurat_v3_2019_Stuart.pdf`
  - Next step: repair/extract with another parser, use publisher HTML/full text, or replace with an extractable PDF.
  - Current text chars: 0
  - Candidate issue: (none)
  - Selected PDF URL: (none)
  - Candidate URLs: (none)
  - Notes: Manual/open-source text capture target. Do not promote without review packet validation.; pypdf failed: PdfReadError: Invalid object in /Pages; PDF text extraction produced empty text

- Seurat / publication: Integrated analysis of multimodal single-cell data
  - DOI/source: https://doi.org/10.1016/j.cell.2021.04.048
  - Existing PDF: `data/evidence_sources/pdfs/news/Seurat_CAND_PUB_Seurat_v4_2021_Hao.pdf`
  - Next step: repair/extract with another parser, use publisher HTML/full text, or replace with an extractable PDF.
  - Current text chars: 0
  - Candidate issue: (none)
  - Selected PDF URL: (none)
  - Candidate URLs: (none)
  - Notes: Manual/open-source text capture target. Do not promote without review packet validation.; pypdf failed: PdfReadError: Invalid object in /Pages; PDF text extraction produced empty text
