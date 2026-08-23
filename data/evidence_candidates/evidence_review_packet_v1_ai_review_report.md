# Evidence Review Packet v1 AI Review

- mode: live
- reviewed_rows: 3
- skipped_rows: 20
- output_is_promotion_input: False

## Seurat / HR_BMK_Seurat_scIB_integration_2022

- evidence_kind: benchmark
- ai_review_status: insufficient
- ai_confidence: 1.00
- ai_suggested_decision: reject
- ai_rationale: Source span only contains title and generic benchmarking description; no mention of Seurat, CCA/RPCA, or any specific performance metrics. The claim cannot be supported.
- missing_for_promotion: Specific Seurat performance result; Numeric score or rank; Mention of Seurat in source span
- suggested_claim: 

## Scanpy / CAND_PUB_Scanpy_4671c99f42e8

- evidence_kind: publication
- ai_review_status: support_as_publication_candidate
- ai_confidence: 0.95
- ai_suggested_decision: keep_retrieval_only
- ai_rationale: Source span contains a clear description of Scanpy as a scalable toolkit for single-cell gene expression data analysis, including specific method categories, and cites the journal Genome Biology, sufficient to identify the associated publication as a canonical method paper.
- missing_for_promotion: verified_task; verified_modality; traceable_non_ai_reviewer_confirmation
- suggested_claim: Scanpy is a scalable toolkit for single-cell gene expression data analysis, with a publication in Genome Biology.

## Scanpy / HR_BMK_Scanpy_batch_correction_2020

- evidence_kind: benchmark
- ai_review_status: insufficient
- ai_confidence: 0.95
- ai_suggested_decision: reject
- ai_rationale: Source span contains only title and abstract fragment with no actual benchmark results, metrics, scores, rankings, or even qualitative conclusions. It is too thin to support even a qualitative benchmark claim.
- missing_for_promotion: numeric benchmark results; explicit metric values; ranking or comparison scope; qualitative or quantitative evidence beyond title/abstract
- suggested_claim:
