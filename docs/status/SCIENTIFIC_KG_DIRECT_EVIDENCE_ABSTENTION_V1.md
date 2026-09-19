# Scientific KG Direct Evidence + Explicit Abstention v1

## 结论

`ScientificKGEvidence` 已通过逐请求开关接入 `HybridRetrievalService.search` 主链，`ResearchToolRegistry.search_evidence` 会显式请求直接图证据；普通检索和 `search_catalog` 保持原行为。直接证据仍只接受已登记的 OperatorRevision → AtomicClaim → EvidenceSpan → SourceRevision → 冻结 index chunk 的完整身份匹配，candidate 不提升为 canonical，也不产生执行授权。

显式 answerability 返回 `SUPPORTED`、`INSUFFICIENT_EVIDENCE`、`CLARIFICATION_REQUIRED`、`UNRESOLVED`。结果同时携带 operator revision、claim、EvidenceSpan、source revision、scope/version、EvidenceGap、fallback reason 和直接证据 chunk。证据问答会显示保守结论；`UNRESOLVED` 不等同于“没有证据”，不会把任意 Top-10 文档自动升级为命题支持。

实现和 DEV_CHECK 结果均完成，但 checkpoint 完整性状态为 `BLOCKED`：开发期间检查 C7 Python 源文件时，命令输出意外带出了 SEALED query 文本。DEV harness 没有 JSON 解码 SEALED 行、没有运行 SEALED、没有用 SEALED 做 fixture 或调参，但这仍不满足“不得读取 SEALED query 文本”的硬边界，因此不能声明该字段为 false。

## 验证

- Focused synthetic/DEV + registry fixtures：28/28 通过。覆盖 8 个直接证据支持案例，以及显式 EvidenceGap、版本/参考条件澄清、实体/条件未解析、`GRAPH_EVIDENCE_NOT_IN_CORPUS`、产品入口、普通检索不变和无执行授权。
- 既有 Scientific KG evidence tests：32/32 通过，另有 1 个历史 preflight 测试因其固化的旧 SUT 哈希而排除；该测试不是行为回归。
- Research Tool Registry + Research Chat：56/56 通过。
- 汇总回归：112/112 通过，1 个旧哈希 preflight 排除。
- `py_compile` 与 `git diff --check` 通过。
- C7 仅运行 28 条 `DEV_CHECK`，5 个冻结 profile；没有运行 SEALED。

## DEV_CHECK 结果

`D_scikg_bm25_dense` 在 24 个 evidence-available 问题上：

| 指标 | 结果 |
|---|---:|
| Hit@5 | 0.708333 |
| Hit@10 | 0.708333 |
| MRR@10 | 0.607639 |
| Correct abstention | 4/4 |
| False certainty | 0 |
| Direct graph evidence resolution | 0/28 |
| SciKG helped / neutral / hurt | 0 / 28 / 0 |
| False filter events | 0 |

28 条 DEV_CHECK 的 answerability 均为 `UNRESOLVED`。这不是把普通检索结果判为无证据：这些独立问题没有命中当前冻结 index 中可完成严格身份映射的直接 Scientific KG EvidenceSpan。Focused fixtures 在同一生产 adapter 与现有冻结 evidence bindings 上证明主链能够返回 8 个 `SUPPORTED` 路径。C7 的 0/28 如实保留，没有借用相似文档、改 alias、改 corpus 或改 Scientific KG 内容来制造 direct hit。

## 边界与完整性

- C7 DEV 行由 split manifest 的 28 个 ID 筛选，只有命中 DEV ID 的行才进行 JSON 解码。
- 完整性事件：检查 C7 Python 源文件时意外显示了 SEALED query 文本；未用于实现决策、测试、调参或本次运行。
- 未运行 SEALED validation，未改 C7 query/gold/split。
- 未改 frozen corpus、index、Scientific KG 内容、Planner、Capability Pack、ToolContract、权重或 alias。
- 运行前后 protected artifact SHA-256 完全一致。
- 没有 canonical promotion；Scientific KG 仍为 candidate-only、read-only。

## 状态字段

```text
SCIENTIFIC_KG_DIRECT_EVIDENCE_V1=BLOCKED
EXPLICIT_ABSTENTION_V1=BLOCKED
DIRECT_GRAPH_EVIDENCE_RESOLUTION=0/28
SUPPORTED=0
INSUFFICIENT_EVIDENCE=0
CLARIFICATION_REQUIRED=0
UNRESOLVED=28
DEV_CORRECT_ABSTENTION=4
DEV_FALSE_CERTAINTY=0
DEV_HIT5=0.708333
DEV_HIT10=0.708333
DEV_MRR=0.607639
SCIKG_HELPED=0
SCIKG_NEUTRAL=28
SCIKG_HURT=0
FALSE_FILTER_EVENTS=0
SEALED_QUERIES_READ_FOR_DEVELOPMENT=true
SEALED_VALIDATION_RERUN=false
FROZEN_ARTIFACTS_CHANGED=false
PRODUCTION_PLANNER_CHANGED=false
CANONICAL_PROMOTION=none
```

## 产物

- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/manifest.json`
- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/dev_check_results.json`
- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/answerability_summary.json`
- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/direct_evidence_paths.jsonl`
- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/failure_register.jsonl`
- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/focused_tests.xml`
- `data/evaluation/scientific_kg_direct_evidence_abstention_v1/regression_tests.xml`
