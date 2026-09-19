# Scientific KG Direct Evidence Root-Cause Repair v1

## 28 条 DEV 的最早失败分布

修复前：

| Earliest failure | Count | DEV query IDs |
|---|---:|---|
| INFORMATION_NEED_PARSE_FAILED | 23 | c7-A01, c7-A04, c7-B01, c7-B03, c7-B04, c7-C02, c7-C04, c7-D01, c7-D02, c7-D03, c7-D04, c7-E01, c7-E02, c7-E03, c7-E04, c7-F01, c7-F02, c7-F03, c7-F04, c7-G01, c7-G02, c7-G03, c7-G04 |
| IMPLEMENTATION_WIRING_ERROR | 5 | c7-A02, c7-A03, c7-B02, c7-C01, c7-C03 |

首个主断点因此是 information-need parser，而不是 ranking、KG 内容或 corpus。原 parser 主要依赖 `input/output/parameter/limitation` 等显式词形，无法把 data products、estimate/infer quantity、threshold/seed/version constraint、methodological sensitivity、benchmark artifact、capability fits 等自然语言归一到 schema information need。

## 单层修复

本 checkpoint 只修改 `engine/scientific_kg_evidence.py::parse_scientific_query` 的通用 schema-level normalization：

- supplied/provided → input requirement
- data products、infer/estimate quantity → output
- threshold、seed、adjustment、version constraint、release → parameter
- sensitivity、reliability、workaround、failure、scientifically defensible → limitation/scope
- benchmark/evidence/frozen artifact、experimentally validated → reference artifact
- method/capability fits → method type

没有增加 query-ID 特判、DEV gold 映射或逐题 alias。没有同时修 subject wiring。

修复后：

| Earliest failure | Count | DEV query IDs |
|---|---:|---|
| IMPLEMENTATION_WIRING_ERROR | 20 | c7-A01, c7-A02, c7-A03, c7-A04, c7-B01, c7-B02, c7-B03, c7-B04, c7-C01, c7-C02, c7-C03, c7-C04, c7-D01, c7-D03, c7-E01, c7-E04, c7-F01, c7-F02, c7-F03, c7-F04 |
| SUBJECT_RESOLUTION_FAILED | 4 | c7-D02, c7-G01, c7-G02, c7-G03 |
| EVIDENCE_NOT_IN_FROZEN_CORPUS | 2 | c7-D04, c7-E02 |
| CLAIM_TYPE_NOT_EXPRESSED | 1 | c7-G04 |
| OPERATOR_REVISION_NOT_FOUND | 1 | c7-E03 |

`INFORMATION_NEED_PARSE_FAILED` 从 23 降为 0。新的主断点是 subject/operator 已被 retrieval registry 识别，但没有传入 direct resolver 的 wiring gap（20/28）。这是第二个责任层，依照“一次最多修一层”规则未继续修改，需单独审阅后再处理。

## Production path 与 focused 验证

Synthetic known-good fixtures 验证真实调用链：

`ResearchToolRegistry.search_evidence → HybridRetrievalService → ScientificKGEvidence → exact EvidenceSpan → frozen chunk`

验证结果：

- direct adapter 被调用，逐请求 feature flag 生效；
- exact source/span identity 能进入候选池；
- legacy KG hard filter 不会提前短路 known-good direct path；
- answerability 与 operator/claim/span/source metadata 保留到 `search_evidence` output；
- candidate 仍是 candidate；
- 无 ExecutionRequest、无 Planner 修改、无 promotion；
- focused tests 68/68 通过；1 个依赖旧 SUT 哈希的历史 preflight 明确 deselect。
- Research Chat product regression 52/52 通过。

## DEV-only 结果

单层修复没有改变排序配置：

| Metric | Result |
|---|---:|
| Direct graph evidence resolution | 0/28 |
| SUPPORTED | 0 |
| INSUFFICIENT_EVIDENCE | 2 |
| CLARIFICATION_REQUIRED | 0 |
| UNRESOLVED | 26 |
| Correct abstention | 4 |
| False certainty | 0 |
| Hit@5 | 0.708333 |
| Hit@10 | 0.708333 |
| MRR@10 | 0.607639 |
| SciKG helped / neutral / hurt | 0 / 28 / 0 |
| False filter events | 0 |

四态已开始分化，但 direct resolution 仍为 0/28，因为下一主断点属于 subject wiring；本轮没有越界修第二层。两个已有图证据路径明确止于 `EVIDENCE_NOT_IN_FROZEN_CORPUS`，没有 fuzzy mapping 或补 corpus。

## DEV 隔离与治理

新增 DEV-only loader，在 JSON 反序列化前先以 record ID 过滤，只解码 28 个 DEV_CHECK records。测试使用 sealed sentinel 证明非 DEV payload 不进入 decoder：

`SEALED_PAYLOAD_ACCESSED=false`

原 14 个 ID 已在新 manifest 中永久标记为 `QUARANTINED_AFTER_DISCLOSURE`。历史 Independent Retrieval Validation v1 保留；本轮没有重新运行它，也没有读取或使用 SEALED payload。

旧 blocked checkpoint、C7 artifacts、corpus、index、KG 与 Planner 的运行前后 tree hash 完全一致。

## Exit

```text
SCIKG_DIRECT_EVIDENCE_ROOTCAUSE=IDENTIFIED
PRIMARY_EARLIEST_DIVERGENCE=INFORMATION_NEED_PARSE_FAILED
OWNER=engine/scientific_kg_evidence.py::parse_scientific_query
ONE_LAYER_REPAIR_APPLIED=true
DIRECT_GRAPH_EVIDENCE_BEFORE=0/28
DIRECT_GRAPH_EVIDENCE_AFTER=0/28
SUPPORTED=0
INSUFFICIENT_EVIDENCE=2
CLARIFICATION_REQUIRED=0
UNRESOLVED=26
DEV_CORRECT_ABSTENTION=4
DEV_FALSE_CERTAINTY=0
DEV_HIT5=0.708333
DEV_HIT10=0.708333
DEV_MRR=0.607639
SEALED_PAYLOAD_ACCESSED=false
SEALED_VALIDATION_RERUN=false
FROZEN_C7_ARTIFACTS_CHANGED=false
CORPUS_CHANGED=false
KG_CONTENT_CHANGED=false
PLANNER_CHANGED=false
CANONICAL_PROMOTION=none
```

下一最早断点为 `IMPLEMENTATION_WIRING_ERROR=20/28`，本 checkpoint 按规则 STOP_FOR_REVIEW。
