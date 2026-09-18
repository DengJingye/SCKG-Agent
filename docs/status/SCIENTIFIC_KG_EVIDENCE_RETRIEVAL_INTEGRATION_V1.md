# Scientific KG Evidence Retrieval Integration v1

开发对照；不是 formal holdout，不是独立泛化验证。问题级 Hit@5/10，不是全相关文档召回率。

Integration: PASS；DEV: COMPLETE；observed benefit: IMPROVED。

## 完整结果

| Panel | Profile | Hit@5 | Hit@10 | MRR |
|---|---|---:|---:|---:|
| scientific_all45 | A_BM25 | 26/45 | 31/45 | 0.381966 |
| scientific_all45 | B_LEGACY_KG_BM25 | 26/45 | 31/45 | 0.381966 |
| scientific_all45 | C_SCIENTIFIC_KG_BM25 | 28/45 | 33/45 | 0.426411 |
| supported_operator_scope | A_BM25 | 4/8 | 4/8 | 0.375 |
| supported_operator_scope | B_LEGACY_KG_BM25 | 4/8 | 4/8 | 0.375 |
| supported_operator_scope | C_SCIENTIFIC_KG_BM25 | 6/8 | 6/8 | 0.625 |
| tool_discovery12 | A_BM25 | 3/12 | 3/12 | 0.1875 |
| tool_discovery12 | B_LEGACY_KG_BM25 | 3/12 | 4/12 | 0.21875 |
| tool_discovery12 | C_SCIENTIFIC_KG_BM25 | 3/12 | 3/12 | 0.1875 |
| unsupported_scientific_scope | A_BM25 | 22/37 | 27/37 | 0.383473 |
| unsupported_scientific_scope | B_LEGACY_KG_BM25 | 22/37 | 27/37 | 0.383473 |
| unsupported_scientific_scope | C_SCIENTIFIC_KG_BM25 | 22/37 | 27/37 | 0.383473 |

## 因果与语义边界

A/B 所有114份 hit 列表（含排名、score和来源字段）与冻结补充实验完全一致；只新增 C。
C 不使用 legacy KG hard filter；科学图通道与 A 的 BM25 候选合并，等权 RRF k=60、图预算12、稳定chunk-ID次序，公共过滤/多样化不变。默认关闭。
实际遍历 OperatorRevision → subject-matched AtomicClaim/Requirement/Constraint → scope/version/flavor → exact binding → EvidenceSpan/SourceRevision → 已有chunk。
candidate 仍是 candidate，supports assessment不等于人工审阅；没有执行授权，没有伪造Ledger。
证据支持检查仅验证已登记的predicate/scope/binding，不是对全部top-k内容的独立科学正确性认证；未命中gold不自动意味着科学错误。
未指定版本仅返回1.11.2范围内证据；未指定HVG flavor保留条件化分支。版本/范围不支持则不向图通道注入。
PCA output在当前图切片无对应claim；pca.mask、neighbors.metadata span未进入冻结corpus。neighbors.input在corpus标记Harmony，显式Scanpy过滤可能拒绝。均保留EvidenceGap/回退，不修图或corpus。

## 图参与度

```json
{
  "query_count": 57,
  "resolved_operator": 7,
  "mapped_graph_evidence": 6,
  "passed_public_filter": 5,
  "graph_evidence_in_final_topk": 5,
  "fallback_reasons": {
    "different_or_multiple_tool_context": 33,
    "unsupported_operator": 2,
    "public_eligibility_filter_rejected_graph_evidence": 1,
    "no_fallback": 5,
    "information_need_unknown": 1,
    "information_need_not_expressed_in_graph": 1,
    "unsupported_or_historical_operator_api": 2,
    "discovery_track_out_of_scope": 12
  },
  "C_vs_A": {
    "NEUTRAL": 54,
    "HELPED": 3
  },
  "C_vs_B": {
    "NEUTRAL": 52,
    "HELPED": 3,
    "HURT": 2
  }
}
```

## 逐题 first-gold rank

| Query | A | B | C | C vs A | C vs B |
|---|---:|---:|---:|---|---|
| r1-adjudicated-tool-04-discovery | 3 | 3 | 3 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-04-input_requirement | 2 | 2 | 2 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-04-metric | None | None | None | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-07-parameter | 4 | 4 | 4 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-07-output | None | None | None | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-08-discovery | None | None | None | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-08-metric | None | None | None | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-12-parameter | None | None | None | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-12-output | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-13-discovery | 2 | 2 | 2 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-13-failure_mode | 3 | 3 | 3 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-16-parameter | 3 | 3 | 3 | NEUTRAL | NEUTRAL |
| r1-adjudicated-tool-16-output | 6 | 6 | 6 | NEUTRAL | NEUTRAL |
| r1-adjudicated-workflow-04 | 4 | 4 | 4 | NEUTRAL | NEUTRAL |
| r1-adjudicated-ambiguous-03 | 9 | 9 | 9 | NEUTRAL | NEUTRAL |
| r1-seed-leiden-input | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-harmony-input | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-harmony-output | 3 | 3 | 3 | NEUTRAL | NEUTRAL |
| r1-seed-neighbors-input | None | None | None | NEUTRAL | NEUTRAL |
| r1-seed-raw-input | 3 | 3 | 3 | NEUTRAL | NEUTRAL |
| r1-seed-dispersion-input | 2 | 2 | 1 | HELPED | HELPED |
| r1-seed-count-input | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-default-flavor | 2 | 2 | 2 | NEUTRAL | NEUTRAL |
| r1-seed-hvg-output | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-query-input | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-reference-expression | 8 | 8 | 8 | NEUTRAL | NEUTRAL |
| r1-seed-reference-labels | 4 | 4 | 4 | NEUTRAL | NEUTRAL |
| r1-seed-shared-features | 7 | 7 | 7 | NEUTRAL | NEUTRAL |
| r1-seed-reference-choice | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-normalized-input | 2 | 2 | 2 | NEUTRAL | NEUTRAL |
| r1-seed-feature-overlap-guidance | 3 | 3 | 3 | NEUTRAL | NEUTRAL |
| r1-seed-default-model | 7 | 7 | 7 | NEUTRAL | NEUTRAL |
| r1-seed-layer-requirement | 4 | 4 | 4 | NEUTRAL | NEUTRAL |
| r1-seed-overlapping-samples-supported | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-seed-latent-output | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-extra-normalization | None | None | None | NEUTRAL | NEUTRAL |
| r1-extra-pca-input | None | None | 2 | HELPED | HELPED |
| r1-extra-pca-output | None | None | None | NEUTRAL | NEUTRAL |
| r1-extra-neighbors-output | None | None | 1 | HELPED | HELPED |
| r1-extra-umap-input | None | None | None | NEUTRAL | NEUTRAL |
| r1-extra-umap-output | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-extra-soupx-ambient | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r1-extra-edger-count-input | None | None | None | NEUTRAL | NEUTRAL |
| r1-extra-slingshot-output | None | None | None | NEUTRAL | NEUTRAL |
| r1-extra-pyscenic-grn | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-scrublet | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-harmony | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-scanorama | 4 | 2 | 4 | NEUTRAL | HURT |
| r2-discovery-scvi | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-celltypist | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-singler | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r2-discovery-cellrank | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-mofa2 | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-soupx | 1 | 1 | 1 | NEUTRAL | NEUTRAL |
| r2-discovery-tradeseq | None | 8 | None | NEUTRAL | HURT |
| r2-discovery-scvelo | None | None | None | NEUTRAL | NEUTRAL |
| r2-discovery-scanpy | None | None | None | NEUTRAL | NEUTRAL |

## 验证与失败归因

Focused validation: {'tests': 46, 'failures': 0, 'errors': 0, 'skipped': 0, 'junit_sha256': 'f54e994aeafd78aef087f79a606c7650123cc03a82bfa4cf819dc77b8eecc0d5'}；未运行full pytest。

预实验EDD：系统python缺pytest（环境）；测试夹具误复制不存在的可选retrieval_coverage.json（测试层，去除复制）；测试给frozen EvidenceChunk赋值（测试层，改用dataclasses.replace临时副本）；HVG flavor被已有工具识别附带识别为Seurat（新adapter上下文层，区分已解析flavor，不改公共工具识别）。均在实验前修复并回归。
额外历史回归检查：62 passed / 1 failed。唯一失败为旧supplement preflight锁定旧hybrid_retrieval.py SHA，当前经授权新增生产入口必然不相等；属于历史SUT身份门槛，不声称旧实验可在新SUT上重跑。未修改旧测试/runner。当前focused门槛使用新adapter/harness+HybridRetrieval+Research入口；新preflight验证旧资产，A/B精确hit等价另行验证行为。
ResearchToolRegistry真实search_evidence入口smoke返回图证据，未调用LLM；不冒充完整问答或canonical执行Trace。新增诊断只包含登记知识标识/约束，无用户数据状态、主机绝对路径、凭证或执行授权。
数据、图、Seed、Planner/Contract/Policy和历史实验摘要前后保持一致，详见pre_run_manifest和integrity_after。测试只写临时目录。
下一步若要覆盖更多谓词、operator或当前数据适用性，需要另行确认知识/映射/产品调用边界；本轮未实施。

## 产物

`eval_v2/scientific_kg_evidence_retrieval_v1_dev/`：pre_run_manifest、raw_search、per_query_results、graph_paths、evidence_checks、product_smoke、report、integrity_after和write-once markers。
新增实现/测试/结果未commit或push；仅上一轮补充实验已独立冻结。
