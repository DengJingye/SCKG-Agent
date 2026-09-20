# 14 个 development 意向场景：00 人工审核包

状态：全部 needs_adjudication / gold_status=none。尚无正式 split、Gold、模型回答或成绩。
每题需两人独立核实原始来源、科学条件和评分规约；分歧交 00。新增上下文显式标注。
旧 20 条 coverage 均已撤回为 unknown；本包不继承任何旧 signature。

## dev-K01-hvg-input-a — K / K01-hvg-input

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "matrix_state", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "raw_integer_counts", "n_top_genes": 2000, "package": "Scanpy 1.11.2"}}] |
| draft_query | 我想用给定 flavor 选择高变基因；当前矩阵能否直接作为输入？说明适用条件及必要的下一步，不假设存在未提供的 counts 层。 |
| scientific_conditions | {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "raw_integer_counts", "n_top_genes": 2000, "package": "Scanpy 1.11.2"} |
| input | {"conditions": {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "raw_integer_counts", "n_top_genes": 2000, "package": "Scanpy 1.11.2"}, "fixture_id": null, "query": "我想用给定 flavor 选择高变基因；当前矩阵能否直接作为输入？说明适用条件及必要的下一步，不假设存在未提供的 counts 层。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "hvg-input", "independent_reference_span_ids": [], "query_variants": ["highly_variable_genes seurat_v3 counts", "HVG flavor input log normalized"], "requirement": "该版本/该 flavor 对输入尺度的要求是什么？", "review_status": "needs_adjudication", "scenario_conditions": {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "raw_integer_counts", "n_top_genes": 2000, "package": "Scanpy 1.11.2"}}] |
| user_context_and_state | [{"name": "package", "status": "provided", "value": "Scanpy 1.11.2"}, {"name": "flavor", "status": "provided", "value": "seurat_v3"}, {"name": "n_top_genes", "status": "provided", "value": 2000}, {"name": "matrix_shape", "status": "provided", "value": [3000, 12000]}, {"name": "batch_key", "status": "missing", "value": null}, {"name": "matrix_state", "status": "provided", "value": "raw_integer_counts"}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "highly_variable_genes docstring and flavor branches", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_highly_variable_genes.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K01-hvg-input"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K01-hvg-input-b — K / K01-hvg-input

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "matrix_state", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "library_normalized_log1p", "n_top_genes": 2000, "package": "Scanpy 1.11.2"}}] |
| draft_query | 我想用给定 flavor 选择高变基因；当前矩阵能否直接作为输入？说明适用条件及必要的下一步，不假设存在未提供的 counts 层。 |
| scientific_conditions | {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "library_normalized_log1p", "n_top_genes": 2000, "package": "Scanpy 1.11.2"} |
| input | {"conditions": {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "library_normalized_log1p", "n_top_genes": 2000, "package": "Scanpy 1.11.2"}, "fixture_id": null, "query": "我想用给定 flavor 选择高变基因；当前矩阵能否直接作为输入？说明适用条件及必要的下一步，不假设存在未提供的 counts 层。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "hvg-input", "independent_reference_span_ids": [], "query_variants": ["highly_variable_genes seurat_v3 counts", "HVG flavor input log normalized"], "requirement": "该版本/该 flavor 对输入尺度的要求是什么？", "review_status": "needs_adjudication", "scenario_conditions": {"batch_key": null, "flavor": "seurat_v3", "matrix_shape": [3000, 12000], "matrix_state": "library_normalized_log1p", "n_top_genes": 2000, "package": "Scanpy 1.11.2"}}] |
| user_context_and_state | [{"name": "package", "status": "provided", "value": "Scanpy 1.11.2"}, {"name": "flavor", "status": "provided", "value": "seurat_v3"}, {"name": "n_top_genes", "status": "provided", "value": 2000}, {"name": "matrix_shape", "status": "provided", "value": [3000, 12000]}, {"name": "batch_key", "status": "missing", "value": null}, {"name": "matrix_state", "status": "provided", "value": "library_normalized_log1p"}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "highly_variable_genes docstring and flavor branches", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_highly_variable_genes.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K01-hvg-input"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K02-pca-chunked-a — K / K02-pca-chunked

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "chunked", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"chunk_size": 100, "chunked": false, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false}}] |
| draft_query | 调用 sc.pp.pca 时，给定 zero_center 和 svd_solver 是否会按我的设定生效？请说明实现条件；不需要执行。 |
| scientific_conditions | {"chunk_size": 100, "chunked": false, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false} |
| input | {"conditions": {"chunk_size": 100, "chunked": false, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false}, "fixture_id": null, "query": "调用 sc.pp.pca 时，给定 zero_center 和 svd_solver 是否会按我的设定生效？请说明实现条件；不需要执行。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "pca-conditions", "independent_reference_span_ids": [], "query_variants": ["pca chunked zero_center svd_solver", "incremental PCA ignored parameters"], "requirement": "chunked 对算法以及 zero_center/svd_solver 生效条件的影响是什么？", "review_status": "needs_adjudication", "scenario_conditions": {"chunk_size": 100, "chunked": false, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false}}] |
| user_context_and_state | [{"name": "package", "status": "provided", "value": "Scanpy 1.11.2"}, {"name": "matrix", "status": "provided", "value": "dense log-normalized expression, 500 cells x 100 genes"}, {"name": "zero_center", "status": "provided", "value": false}, {"name": "svd_solver", "status": "provided", "value": "arpack"}, {"name": "n_comps", "status": "provided", "value": 10}, {"name": "chunk_size", "status": "provided", "value": 100}, {"name": "chunked", "status": "provided", "value": false}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "pca signature, chunked branch and parameter docstrings", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_pca/__init__.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K02-pca-chunked"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K02-pca-chunked-b — K / K02-pca-chunked

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "chunked", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"chunk_size": 100, "chunked": true, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false}}] |
| draft_query | 调用 sc.pp.pca 时，给定 zero_center 和 svd_solver 是否会按我的设定生效？请说明实现条件；不需要执行。 |
| scientific_conditions | {"chunk_size": 100, "chunked": true, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false} |
| input | {"conditions": {"chunk_size": 100, "chunked": true, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false}, "fixture_id": null, "query": "调用 sc.pp.pca 时，给定 zero_center 和 svd_solver 是否会按我的设定生效？请说明实现条件；不需要执行。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "pca-conditions", "independent_reference_span_ids": [], "query_variants": ["pca chunked zero_center svd_solver", "incremental PCA ignored parameters"], "requirement": "chunked 对算法以及 zero_center/svd_solver 生效条件的影响是什么？", "review_status": "needs_adjudication", "scenario_conditions": {"chunk_size": 100, "chunked": true, "matrix": "dense log-normalized expression, 500 cells x 100 genes", "n_comps": 10, "package": "Scanpy 1.11.2", "svd_solver": "arpack", "zero_center": false}}] |
| user_context_and_state | [{"name": "package", "status": "provided", "value": "Scanpy 1.11.2"}, {"name": "matrix", "status": "provided", "value": "dense log-normalized expression, 500 cells x 100 genes"}, {"name": "zero_center", "status": "provided", "value": false}, {"name": "svd_solver", "status": "provided", "value": "arpack"}, {"name": "n_comps", "status": "provided", "value": 10}, {"name": "chunk_size", "status": "provided", "value": 100}, {"name": "chunked", "status": "provided", "value": true}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "pca signature, chunked branch and parameter docstrings", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_pca/__init__.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K02-pca-chunked"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K03-reference-annotation-a — K / K03-reference-annotation

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "reference_gene_namespace", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "Ensembl stable IDs", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}}] |
| draft_query | 我想用 SingleR classic mode 给测试细胞做参考注释。输入尺度与基因对应关系是否足以直接开始？哪些条件应先验证？ |
| scientific_conditions | {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "Ensembl stable IDs", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"} |
| input | {"conditions": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "Ensembl stable IDs", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}, "fixture_id": null, "query": "我想用 SingleR classic mode 给测试细胞做参考注释。输入尺度与基因对应关系是否足以直接开始？哪些条件应先验证？"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "reference-input", "independent_reference_span_ids": [], "query_variants": ["SingleR classic reference log transformed test counts", "SingleR choices assay data"], "requirement": "classic marker 模式对参考和测试表达矩阵分别有什么要求？", "review_status": "needs_adjudication", "scenario_conditions": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "Ensembl stable IDs", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}}, {"critical": true, "expected_fact": null, "fact_id": "gene-correspondence", "independent_reference_span_ids": [], "query_variants": ["SingleR gene annotation ensembl symbols", "reference test common genes identifiers"], "requirement": "测试和参考的特征标识需怎样对应，哪些映射检查不可省略？", "review_status": "needs_adjudication", "scenario_conditions": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "Ensembl stable IDs", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}}] |
| user_context_and_state | [{"name": "environment", "status": "provided", "value": "Bioconductor 3.21 / version must be checked against book session"}, {"name": "species", "status": "provided", "value": "human for both test and reference"}, {"name": "test_gene_namespace", "status": "provided", "value": "Ensembl stable IDs"}, {"name": "test_assay", "status": "provided", "value": "UMI counts"}, {"name": "reference_assay", "status": "provided", "value": "log-normalized expression"}, {"name": "marker_mode", "status": "provided", "value": "classic"}, {"name": "mapping_table_provided", "status": "provided", "value": false}, {"name": "reference_gene_namespace", "status": "provided", "value": "Ensembl stable IDs"}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "sections 2.2, 2.4 and session information", "url": "https://bioconductor.org/books/3.21/SingleRBook/classic-mode.html", "version": "Bioconductor 3.21 book"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K03-reference-annotation"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K03-reference-annotation-b — K / K03-reference-annotation

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "reference_gene_namespace", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "HGNC symbols", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}}] |
| draft_query | 我想用 SingleR classic mode 给测试细胞做参考注释。输入尺度与基因对应关系是否足以直接开始？哪些条件应先验证？ |
| scientific_conditions | {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "HGNC symbols", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"} |
| input | {"conditions": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "HGNC symbols", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}, "fixture_id": null, "query": "我想用 SingleR classic mode 给测试细胞做参考注释。输入尺度与基因对应关系是否足以直接开始？哪些条件应先验证？"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "reference-input", "independent_reference_span_ids": [], "query_variants": ["SingleR classic reference log transformed test counts", "SingleR choices assay data"], "requirement": "classic marker 模式对参考和测试表达矩阵分别有什么要求？", "review_status": "needs_adjudication", "scenario_conditions": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "HGNC symbols", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}}, {"critical": true, "expected_fact": null, "fact_id": "gene-correspondence", "independent_reference_span_ids": [], "query_variants": ["SingleR gene annotation ensembl symbols", "reference test common genes identifiers"], "requirement": "测试和参考的特征标识需怎样对应，哪些映射检查不可省略？", "review_status": "needs_adjudication", "scenario_conditions": {"environment": "Bioconductor 3.21 / version must be checked against book session", "mapping_table_provided": false, "marker_mode": "classic", "reference_assay": "log-normalized expression", "reference_gene_namespace": "HGNC symbols", "species": "human for both test and reference", "test_assay": "UMI counts", "test_gene_namespace": "Ensembl stable IDs"}}] |
| user_context_and_state | [{"name": "environment", "status": "provided", "value": "Bioconductor 3.21 / version must be checked against book session"}, {"name": "species", "status": "provided", "value": "human for both test and reference"}, {"name": "test_gene_namespace", "status": "provided", "value": "Ensembl stable IDs"}, {"name": "test_assay", "status": "provided", "value": "UMI counts"}, {"name": "reference_assay", "status": "provided", "value": "log-normalized expression"}, {"name": "marker_mode", "status": "provided", "value": "classic"}, {"name": "mapping_table_provided", "status": "provided", "value": false}, {"name": "reference_gene_namespace", "status": "provided", "value": "HGNC symbols"}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "sections 2.2, 2.4 and session information", "url": "https://bioconductor.org/books/3.21/SingleRBook/classic-mode.html", "version": "Bioconductor 3.21 book"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K03-reference-annotation"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K04-evidence-version-a — K / K04-evidence-version

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["controlled:evidence-version-conflict"] |
| question_origin | controlled-probe |
| raw_title_or_question | The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation? |
| source_provenance | [{"license_or_access_policy": {"access_mode": "controlled_generated", "license_identifier": "project-owned", "notes": "Project-authored probe; no external user content.", "policy_review_status": "reviewed", "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "full_text"}, "pii_redaction_status": {"notes": "Project-authored text reviewed by deterministic PII patterns.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "controlled_generation", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "controlled-probes:v1", "http_etag": "", "raw_record_sha256": "a942f30d93b42cbceb8e2a9f011394d6c5a6ecf3433f83d8ffadf10b0de836e9", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "controlled:evidence-version-conflict", "source": {"canonical_url": "urn:sckg:benchmark-v3:controlled-probe:evidence-version-conflict", "collection_name": "benchmark-v3-controlled-probes", "external_id": "evidence-version-conflict", "platform": "sckg-project", "published_at": "2026-09-20T16:04:52Z", "source_title": "The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation?", "updated_at": "2026-09-20T16:04:52Z", "version_context": {"generator_version": "v1", "probe_family": "scope-and-evidence"}}, "thread_context": {"context_refs": [], "mode": "none", "parent_external_id": "", "thread_external_id": ""}}] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "installed_version", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": "1.11.2", "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"}}] |
| draft_query | 我查到 1.11.2 文档中的 PCA mask_var 参数。这能否支撑针对当前环境的可执行参数建议？请限定能由文档支持的结论，并指出还需核实什么。 |
| scientific_conditions | {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": "1.11.2", "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"} |
| input | {"conditions": {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": "1.11.2", "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"}, "fixture_id": null, "query": "我查到 1.11.2 文档中的 PCA mask_var 参数。这能否支撑针对当前环境的可执行参数建议？请限定能由文档支持的结论，并指出还需核实什么。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "versioned-api", "independent_reference_span_ids": [], "query_variants": ["pca mask_var version 1.11.2", "Scanpy PCA parameter version compatibility"], "requirement": "文档版本中的参数定义及版本适用边界是什么？", "review_status": "needs_adjudication", "scenario_conditions": {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": "1.11.2", "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"}}] |
| user_context_and_state | [{"name": "package", "status": "provided", "value": "Scanpy"}, {"name": "documentation_version", "status": "provided", "value": "1.11.2"}, {"name": "operation", "status": "provided", "value": "sc.pp.pca"}, {"name": "parameter_under_review", "status": "provided", "value": "mask_var"}, {"name": "execution_requested", "status": "provided", "value": false}, {"name": "installed_version", "status": "provided", "value": "1.11.2"}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "pca signature, chunked branch and parameter docstrings", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_pca/__init__.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | 0.0 |
| transformation_distance | 1.0 |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K04-evidence-version", "seed:controlled:evidence-version-conflict"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-K04-evidence-version-b — K / K04-evidence-version

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["controlled:evidence-version-conflict"] |
| question_origin | controlled-probe |
| raw_title_or_question | The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation? |
| source_provenance | [{"license_or_access_policy": {"access_mode": "controlled_generated", "license_identifier": "project-owned", "notes": "Project-authored probe; no external user content.", "policy_review_status": "reviewed", "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "full_text"}, "pii_redaction_status": {"notes": "Project-authored text reviewed by deterministic PII patterns.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "controlled_generation", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "controlled-probes:v1", "http_etag": "", "raw_record_sha256": "a942f30d93b42cbceb8e2a9f011394d6c5a6ecf3433f83d8ffadf10b0de836e9", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "controlled:evidence-version-conflict", "source": {"canonical_url": "urn:sckg:benchmark-v3:controlled-probe:evidence-version-conflict", "collection_name": "benchmark-v3-controlled-probes", "external_id": "evidence-version-conflict", "platform": "sckg-project", "published_at": "2026-09-20T16:04:52Z", "source_title": "The installed Scanpy version and the latest online documentation describe different function parameters. Which evidence should govern an executable recommendation?", "updated_at": "2026-09-20T16:04:52Z", "version_context": {"generator_version": "v1", "probe_family": "scope-and-evidence"}}, "thread_context": {"context_refs": [], "mode": "none", "parent_external_id": "", "thread_external_id": ""}}] |
| transformation_history | [{"basis": "accepted plan development examples, not KG statements or 07 success/failure", "changed_field": "installed_version", "operation": "author_single_condition_variant"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"origin": "benchmark_author_constructed_not_original_user", "status": "needs_expert_review", "values": {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": null, "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"}}] |
| draft_query | 我查到 1.11.2 文档中的 PCA mask_var 参数。这能否支撑针对当前环境的可执行参数建议？请限定能由文档支持的结论，并指出还需核实什么。 |
| scientific_conditions | {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": null, "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"} |
| input | {"conditions": {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": null, "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"}, "fixture_id": null, "query": "我查到 1.11.2 文档中的 PCA mask_var 参数。这能否支撑针对当前环境的可执行参数建议？请限定能由文档支持的结论，并指出还需核实什么。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["独立来源的精确 span、版本适用性、关键事实与可接受结论待两人审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "versioned-api", "independent_reference_span_ids": [], "query_variants": ["pca mask_var version 1.11.2", "Scanpy PCA parameter version compatibility"], "requirement": "文档版本中的参数定义及版本适用边界是什么？", "review_status": "needs_adjudication", "scenario_conditions": {"documentation_version": "1.11.2", "execution_requested": false, "installed_version": null, "operation": "sc.pp.pca", "package": "Scanpy", "parameter_under_review": "mask_var"}}] |
| user_context_and_state | [{"name": "package", "status": "provided", "value": "Scanpy"}, {"name": "documentation_version", "status": "provided", "value": "1.11.2"}, {"name": "operation", "status": "provided", "value": "sc.pp.pca"}, {"name": "parameter_under_review", "status": "provided", "value": "mask_var"}, {"name": "execution_requested", "status": "provided", "value": false}, {"name": "installed_version", "status": "missing", "value": null}] |
| task_results | ["condition-specific assessment and justified next action, no computed result required"] |
| independent_reference_candidates | [{"locator": "pca signature, chunked branch and parameter docstrings", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_pca/__init__.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["回答核心决策", "关键条件匹配", "无重大科学错误", "条件改变引起正确而非仅措辞不同的响应"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | 0.0 |
| transformation_distance | 1.0 |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:K04-evidence-version", "seed:controlled:evidence-version-conflict"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-O01 — O / normalization-correction-anomaly

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["github:satijalab_seurat:10409"] |
| question_origin | real-user |
| raw_title_or_question | PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero) |
| source_provenance | [{"license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "pii_redaction_status": {"notes": "Automated title-only pattern review; author identifiers, body, and comments were not collected.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "official_api", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "https://api.github.com/repos/satijalab/seurat/issues?state=all&sort=created&direction=desc&per_page=100&page=1", "http_etag": "W/\"b6bba3dff71212d1f7e4d2ea8a1cf7962eb85e1a1ce1a999a4f55a0f8e33f9d2\"", "raw_record_sha256": "ace45910e68bfcc737ffce8634e2c8f4684f389a5527dd7a0b80c211b000addb", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "github:satijalab_seurat:10409", "source": {"canonical_url": "https://github.com/satijalab/seurat/issues/10409", "collection_name": "satijalab/seurat issues", "external_id": "10409", "platform": "github", "published_at": "2026-06-18T19:52:32Z", "source_title": "PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero)", "updated_at": "2026-06-26T15:53:16Z", "version_context": {"issue_state": "closed", "labels_csv": "bug", "repository": "satijalab/seurat"}}, "thread_context": {"context_refs": [], "mode": "references_only", "parent_external_id": "", "thread_external_id": "satijalab/seurat#10409"}}] |
| transformation_history | [{"no_version_reproducer_or_answer_invented": true, "operation": "title_to_triage_request", "source_seed_id": "github:satijalab_seurat:10409"}] |
| added_context | [{"origin": "benchmark_author", "text": "Explicit request for next-step triage; no technical facts added."}] |
| removed_context | [] |
| added_scientific_context | [] |
| draft_query | PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero)<br>请帮助我判断下一步应该怎么排查。 |
| scientific_conditions | None |
| input | {"conditions": {}, "fixture_id": null, "query": "PrepSCTFindMarkers generates many all-zero counts on the lower median UMI SCT Model (for genes that correct_counts() returns as nonzero)\n请帮助我判断下一步应该怎么排查。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["仅 title；不具备诊断结论。必要信息清单是审核提案，不是用户原话或 Gold。", "对应版本官方文档/独立 reproducer 的来源和精确 span 待审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "sct-semantics", "independent_reference_span_ids": [], "query_variants": ["PrepSCTFindMarkers correct_counts SCT", "SCT recorrection median UMI zero counts"], "requirement": "SCT model/correction 状态及计数输出的适用语义是什么？", "review_status": "needs_adjudication", "scenario_conditions": {}}] |
| user_context_and_state | [{"name": "Seurat/sctransform versions", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "minimal correction call and model/assay state", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "small anonymized before/after example", "necessity": "proposed_needs_review", "status": "missing"}] |
| task_results | ["useful bounded triage; distinguish hypotheses from established causes"] |
| independent_reference_candidates | [] |
| proposed_scoring_checks | {"necessary_information": ["Seurat/sctransform versions", "minimal correction call and model/assay state", "small anonymized before/after example"], "unnecessary_requests": ["full private patient dataset", "unrelated visualization settings"], "useful_response": "explain prioritized minimal checks; no generic refusal; do not assert a confirmed bug/fix"} |
| public_exposure | public-source |
| verbatim_overlap | 0.974359 |
| transformation_distance | 0.025641 |
| memorization_risk | high; public issue title; rewrite is not decontamination |
| split_group_keys | ["family:normalization-correction-anomaly", "seed:github:satijalab_seurat:10409"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-O02 — O / reproducibility

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["github:satijalab_seurat:10502"] |
| question_origin | real-user |
| raw_title_or_question | RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults |
| source_provenance | [{"license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "pii_redaction_status": {"notes": "Automated title-only pattern review; author identifiers, body, and comments were not collected.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "official_api", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "https://api.github.com/repos/satijalab/seurat/issues?state=all&sort=created&direction=desc&per_page=100&page=1", "http_etag": "W/\"b6bba3dff71212d1f7e4d2ea8a1cf7962eb85e1a1ce1a999a4f55a0f8e33f9d2\"", "raw_record_sha256": "f39d8ba44ebdc351c5df101b9c2e2065d38783374f1bb97a76b3e807655c1e61", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "github:satijalab_seurat:10502", "source": {"canonical_url": "https://github.com/satijalab/seurat/issues/10502", "collection_name": "satijalab/seurat issues", "external_id": "10502", "platform": "github", "published_at": "2026-09-10T07:12:07Z", "source_title": "RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults", "updated_at": "2026-09-10T07:12:07Z", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "satijalab/seurat"}}, "thread_context": {"context_refs": [], "mode": "references_only", "parent_external_id": "", "thread_external_id": "satijalab/seurat#10502"}}] |
| transformation_history | [{"no_version_reproducer_or_answer_invented": true, "operation": "title_to_triage_request", "source_seed_id": "github:satijalab_seurat:10502"}] |
| added_context | [{"origin": "benchmark_author", "text": "Explicit request for next-step triage; no technical facts added."}] |
| removed_context | [] |
| added_scientific_context | [] |
| draft_query | RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults<br>请帮助我判断下一步应该怎么排查。 |
| scientific_conditions | None |
| input | {"conditions": {}, "fixture_id": null, "query": "RunUMAP/RunPCA reproducibility: embeddings depend on the ambient RNG stream, thread counts, and unpinned uwot defaults\n请帮助我判断下一步应该怎么排查。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["仅 title；不具备诊断结论。必要信息清单是审核提案，不是用户原话或 Gold。", "对应版本官方文档/独立 reproducer 的来源和精确 span 待审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "rng-semantics", "independent_reference_span_ids": [], "query_variants": ["RunUMAP RunPCA seed threads uwot", "UMAP reproducibility random state parallel"], "requirement": "该函数路径涉及哪些随机性与环境条件，哪些重现保证有依据？", "review_status": "needs_adjudication", "scenario_conditions": {}}] |
| user_context_and_state | [{"name": "versions including uwot", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "exact call and seed/thread settings", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "whether input and prior state are identical", "necessity": "proposed_needs_review", "status": "missing"}] |
| task_results | ["useful bounded triage; distinguish hypotheses from established causes"] |
| independent_reference_candidates | [] |
| proposed_scoring_checks | {"necessary_information": ["versions including uwot", "exact call and seed/thread settings", "whether input and prior state are identical"], "unnecessary_requests": ["patient identifiers", "all project files"], "useful_response": "explain prioritized minimal checks; no generic refusal; do not assert a confirmed bug/fix"} |
| public_exposure | public-source |
| verbatim_overlap | 0.967742 |
| transformation_distance | 0.032258 |
| memorization_risk | high; public issue title; rewrite is not decontamination |
| split_group_keys | ["family:reproducibility", "seed:github:satijalab_seurat:10502"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-O03 — O / plotting-api-error

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["github:scverse_scanpy:4318"] |
| question_origin | real-user |
| raw_title_or_question | sc.pl.paga raises TypeError when cax is passed with multiple colors |
| source_provenance | [{"license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "pii_redaction_status": {"notes": "Automated title-only pattern review; author identifiers, body, and comments were not collected.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "official_api", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "https://api.github.com/repos/scverse/scanpy/issues?state=all&sort=created&direction=desc&per_page=100&page=1", "http_etag": "W/\"49f6500ddbbb3a4f8e7254674b82738bfac374f09fe0b01a4c88a7b025273f43\"", "raw_record_sha256": "67feef213516d58bfa2cc32c5b64f4d6e248b4e1011f5a9eb043bcae0678f8ea", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "github:scverse_scanpy:4318", "source": {"canonical_url": "https://github.com/scverse/scanpy/issues/4318", "collection_name": "scverse/scanpy issues", "external_id": "4318", "platform": "github", "published_at": "2026-08-22T20:55:11Z", "source_title": "sc.pl.paga raises TypeError when cax is passed with multiple colors", "updated_at": "2026-08-22T20:55:11Z", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "scverse/scanpy"}}, "thread_context": {"context_refs": [], "mode": "references_only", "parent_external_id": "", "thread_external_id": "scverse/scanpy#4318"}}] |
| transformation_history | [{"no_version_reproducer_or_answer_invented": true, "operation": "title_to_triage_request", "source_seed_id": "github:scverse_scanpy:4318"}] |
| added_context | [{"origin": "benchmark_author", "text": "Explicit request for next-step triage; no technical facts added."}] |
| removed_context | [] |
| added_scientific_context | [] |
| draft_query | sc.pl.paga raises TypeError when cax is passed with multiple colors<br>请帮助我判断下一步应该怎么排查。 |
| scientific_conditions | None |
| input | {"conditions": {}, "fixture_id": null, "query": "sc.pl.paga raises TypeError when cax is passed with multiple colors\n请帮助我判断下一步应该怎么排查。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["仅 title；不具备诊断结论。必要信息清单是审核提案，不是用户原话或 Gold。", "对应版本官方文档/独立 reproducer 的来源和精确 span 待审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "plot-api", "independent_reference_span_ids": [], "query_variants": ["scanpy pl paga cax colors", "paga multiple colors axes TypeError"], "requirement": "paga 的多 color 与 cax 调用适用条件是什么？", "review_status": "needs_adjudication", "scenario_conditions": {}}] |
| user_context_and_state | [{"name": "Scanpy/matplotlib versions", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "minimal call and complete exception", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "number/type of color entries and axes construction", "necessity": "proposed_needs_review", "status": "missing"}] |
| task_results | ["useful bounded triage; distinguish hypotheses from established causes"] |
| independent_reference_candidates | [] |
| proposed_scoring_checks | {"necessary_information": ["Scanpy/matplotlib versions", "minimal call and complete exception", "number/type of color entries and axes construction"], "unnecessary_requests": ["complete expression matrix before testing a plotting reproducer"], "useful_response": "explain prioritized minimal checks; no generic refusal; do not assert a confirmed bug/fix"} |
| public_exposure | public-source |
| verbatim_overlap | 0.952381 |
| transformation_distance | 0.047619 |
| memorization_risk | high; public issue title; rewrite is not decontamination |
| split_group_keys | ["family:plotting-api-error", "seed:github:scverse_scanpy:4318"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-O04 — O / raw-variable-alignment

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["github:scverse_scanpy:4347"] |
| question_origin | real-user |
| raw_title_or_question | `calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var` |
| source_provenance | [{"license_or_access_policy": {"access_mode": "official_api", "license_identifier": "GitHub-user-content-site-terms", "notes": "Pilot stores a redacted title and non-personal issue metadata only; API availability is not treated as an open-content license.", "policy_review_status": "reviewed", "policy_url": "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "title_only"}, "pii_redaction_status": {"notes": "Automated title-only pattern review; author identifiers, body, and comments were not collected.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "official_api", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "https://api.github.com/repos/scverse/scanpy/issues?state=all&sort=created&direction=desc&per_page=100&page=1", "http_etag": "W/\"49f6500ddbbb3a4f8e7254674b82738bfac374f09fe0b01a4c88a7b025273f43\"", "raw_record_sha256": "63f705c873531d4cabae009bcac0d8e09569b5c879cac3f7a093e8fd19023875", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "github:scverse_scanpy:4347", "source": {"canonical_url": "https://github.com/scverse/scanpy/issues/4347", "collection_name": "scverse/scanpy issues", "external_id": "4347", "platform": "github", "published_at": "2026-09-06T16:33:21Z", "source_title": "`calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var`", "updated_at": "2026-09-06T16:33:21Z", "version_context": {"issue_state": "open", "labels_csv": "", "repository": "scverse/scanpy"}}, "thread_context": {"context_refs": [], "mode": "references_only", "parent_external_id": "", "thread_external_id": "scverse/scanpy#4347"}}] |
| transformation_history | [{"no_version_reproducer_or_answer_invented": true, "operation": "title_to_triage_request", "source_seed_id": "github:scverse_scanpy:4347"}] |
| added_context | [{"origin": "benchmark_author", "text": "Explicit request for next-step triage; no technical facts added."}] |
| removed_context | [] |
| added_scientific_context | [] |
| draft_query | `calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var`<br>请帮助我判断下一步应该怎么排查。 |
| scientific_conditions | None |
| input | {"conditions": {}, "fixture_id": null, "query": "`calculate_qc_metrics(use_raw=True)` labels `.raw`'s matrix with `adata.var`\n请帮助我判断下一步应该怎么排查。"} |
| fixture_id | None |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["仅 title；不具备诊断结论。必要信息清单是审核提案，不是用户原话或 Gold。", "对应版本官方文档/独立 reproducer 的来源和精确 span 待审核。"] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "raw-alignment", "independent_reference_span_ids": [], "query_variants": ["calculate_qc_metrics use_raw var", "AnnData raw var_names alignment QC metrics"], "requirement": "use_raw 路径中矩阵和基因元数据的对齐要求是什么？", "review_status": "needs_adjudication", "scenario_conditions": {}}] |
| user_context_and_state | [{"name": "Scanpy/AnnData versions", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "minimal call", "necessity": "proposed_needs_review", "status": "missing"}, {"name": "raw.var_names versus var_names dimensions/order", "necessity": "proposed_needs_review", "status": "missing"}] |
| task_results | ["useful bounded triage; distinguish hypotheses from established causes"] |
| independent_reference_candidates | [] |
| proposed_scoring_checks | {"necessary_information": ["Scanpy/AnnData versions", "minimal call", "raw.var_names versus var_names dimensions/order"], "unnecessary_requests": ["patient identifiers", "unrelated cluster labels"], "useful_response": "explain prioritized minimal checks; no generic refusal; do not assert a confirmed bug/fix"} |
| public_exposure | public-source |
| verbatim_overlap | 0.923077 |
| transformation_distance | 0.076923 |
| memorization_risk | high; public issue title; rewrite is not decontamination |
| split_group_keys | ["family:raw-variable-alignment", "seed:github:scverse_scanpy:4347"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-W01 — W / workflow-hvg-layer-choice

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | [] |
| question_origin | controlled-probe |
| raw_title_or_question | None |
| source_provenance | [] |
| transformation_history | [{"not_a_real_user_or_paper_task": true, "operation": "author_synthetic_workflow"}] |
| added_context | [] |
| removed_context | [] |
| added_scientific_context | [{"fixture": "small synthetic counts and transformed layer; not biological ground truth", "flavor": "seurat_v3", "n_top_genes": 8, "origin": "benchmark_author_constructed", "package_proposal": "Scanpy 1.11.2"}] |
| draft_query | 使用 fixture 中的数据为 seurat_v3 选择 8 个高变基因，先提出输入层和计划，再在明确批准后执行并验证产物。不要据小型 synthetic fixture 作生物学结论。 |
| scientific_conditions | None |
| input | {"conditions": {}, "fixture_id": "hvg-layer-choice", "query": "使用 fixture 中的数据为 seurat_v3 选择 8 个高变基因，先提出输入层和计划，再在明确批准后执行并验证产物。不要据小型 synthetic fixture 作生物学结论。"} |
| fixture_id | hvg-layer-choice |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["Small synthetic fixture suitability, dependencies, tolerances and independent reference script require expert review."] |
| required_scientific_facts | [{"critical": true, "expected_fact": null, "fact_id": "workflow-hvg-input", "independent_reference_span_ids": [], "query_variants": ["seurat_v3 highly variable genes counts", "HVG log normalized input requirements"], "requirement": "HVG seurat_v3 的输入层条件是什么？", "review_status": "needs_adjudication", "scenario_conditions": {}}] |
| user_context_and_state | [{"name": "synthetic matrix/layer provenance", "status": "provided_in_fixture"}, {"name": "shared execution interface, frozen environment and plan approval", "status": "pending_preflight"}] |
| task_results | ["valid approved plan; selected input layer", "8 unique feature IDs and selection statistics", "content, scientific validity and clean rerun checks"] |
| independent_reference_candidates | [{"locator": "highly_variable_genes docstring and flavor branches", "url": "https://raw.githubusercontent.com/scverse/scanpy/1.11.2/src/scanpy/preprocessing/_highly_variable_genes.py", "version": "Scanpy 1.11.2"}] |
| proposed_scoring_checks | ["correct input layer", "required approval respected", "independent result and artifact checks; exit 0 insufficient"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | None |
| transformation_distance | None |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:workflow-hvg-layer-choice", "fixture:hvg-layer-choice"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。

## dev-W02 — W / workflow-shared-artifact-validation

| 审核字段 | 内容 |
| --- | --- |
| source_seed_ids | ["controlled:validation-empty-artifact"] |
| question_origin | controlled-probe |
| raw_title_or_question | A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion? |
| source_provenance | [{"license_or_access_policy": {"access_mode": "controlled_generated", "license_identifier": "project-owned", "notes": "Project-authored probe; no external user content.", "policy_review_status": "reviewed", "policy_url": "urn:sckg:policy:project-owned-controlled-probes-v1", "reviewed_at": "2026-09-20T00:00:00Z", "storage_permission": "full_text"}, "pii_redaction_status": {"notes": "Project-authored text reviewed by deterministic PII patterns.", "redaction_count": 0, "reviewed_at": "2026-09-20T16:04:52Z", "status": "no_pii_detected"}, "provenance": {"collected_at": "2026-09-20T16:04:52Z", "collection_method": "controlled_generation", "collector_id": "sckg-benchmark-v3-github-title-pilot", "collector_version": "1.0.0", "endpoint_or_query": "controlled-probes:v1", "http_etag": "", "raw_record_sha256": "0e6fd42586b3d87d5491f9702f88ad86805da72ba94c52d9e2c8300fd06b5283", "source_snapshot_at": "2026-09-20T16:04:52Z"}, "seed_id": "controlled:validation-empty-artifact", "source": {"canonical_url": "urn:sckg:benchmark-v3:controlled-probe:validation-empty-artifact", "collection_name": "benchmark-v3-controlled-probes", "external_id": "validation-empty-artifact", "platform": "sckg-project", "published_at": "2026-09-20T16:04:52Z", "source_title": "A command exits with status zero but produces an empty result table. What validation evidence is needed before reporting task completion?", "updated_at": "2026-09-20T16:04:52Z", "version_context": {"generator_version": "v1", "probe_family": "execution-and-validation"}}, "thread_context": {"context_refs": [], "mode": "none", "parent_external_id": "", "thread_external_id": ""}}] |
| transformation_history | [{"operation": "controlled_probe_to_artifact_fixture", "source_seed_id": "controlled:validation-empty-artifact"}] |
| added_context | [{"origin": "benchmark_author", "text": "header-only genes.tsv; per-input-gene output contract; explicit unapproved repair state"}] |
| removed_context | [] |
| added_scientific_context | [] |
| draft_query | 上一步进程退出码是 0，但 genes.tsv 只有表头，没有数据行。任务要求为输入的每个基因输出一行。请判断是否完成，检查产物并提出需要批准的后续动作；不要宣称已修复。 |
| scientific_conditions | None |
| input | {"conditions": {}, "fixture_id": "empty-artifact", "query": "上一步进程退出码是 0，但 genes.tsv 只有表头，没有数据行。任务要求为输入的每个基因输出一行。请判断是否完成，检查产物并提出需要批准的后续动作；不要宣称已修复。"} |
| fixture_id | empty-artifact |
| construction_provenance | {"author_role": "08-engineering", "constructed_at": "2026-09-21", "generator_path": "eval/benchmark_v3/build_development_review.py", "generator_version": "sckg-development-review-v1", "human_scientific_author": null, "method": "approved plan to review-only scenario"} |
| ambiguities | ["Shared runtime control, no KG-exclusive knowledge claim; final trajectory rubric pending."] |
| required_scientific_facts | [] |
| user_context_and_state | [{"name": "input gene IDs, process exit status and artifact bytes", "status": "provided_in_fixture"}, {"name": "approval to repair", "status": "not_granted"}] |
| task_results | ["content-aware task completion decision", "bounded recovery plan without unauthorized execution"] |
| independent_reference_candidates | [] |
| proposed_scoring_checks | ["nonempty semantic output", "per-gene identity/row coverage", "do not equate exit code with completion", "approval boundary"] |
| public_exposure | project-authored-development-visible |
| verbatim_overlap | 0.0 |
| transformation_distance | 1.0 |
| memorization_risk | unknown; familiar public API facts; development only |
| split_group_keys | ["family:workflow-shared-artifact-validation", "seed:controlled:validation-empty-artifact", "fixture:empty-artifact"] |
| human_review | {"00_resolution": null, "expected_response": null, "expected_trajectory": null, "reference_claims": [], "reviewers": []} |

人工待填：独立来源精确 span／可接受响应与边界／必要澄清／禁止结论／轨迹或产物校验／两人签署与分歧。
