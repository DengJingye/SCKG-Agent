# Scientific KG Subject / Operator Wiring Repair v1

## 20/28 个 `IMPLEMENTATION_WIRING_ERROR` 的真实构成

先归因、后修复的结论如下：旧 checkpoint 中的 20 个 `IMPLEMENTATION_WIRING_ERROR` 只有 1 个是真实 identity wiring bug；17 个查询对应的 subject 不在当前 Scientific KG direct-evidence supported slice；2 个只能得到多个合理的 OperatorRevision，必须保留歧义。

| Classification | Count | Interpretation |
|---|---:|---|
| `H_TRUE_IMPLEMENTATION_WIRING_ERROR` | 1 | 当前 slice 有唯一 OperatorRevision，但 legacy discovery identity 没有接到 Scientific KG identity |
| `F_OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE` | 17 | legacy catalog / gap inventory 能识别 subject，但当前 8 个 OperatorRevision 的 direct-evidence slice 不覆盖 |
| `G_AMBIGUOUS_SUBJECT` | 2 | 当前上下文只能约束到多个 Scanpy OperatorRevision，不能任意选一个 |
| Other | 0 | 没有剩余的 revision addressability 或 method-only 分类 |

真实 wiring bug 已由 generic identity bridge 修复；两个歧义 case 现在返回 `CLARIFICATION_REQUIRED`。17 个范围外 case 明确返回 `OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE`，没有通过新增 alias、claim 或 evidence 临时接入。

## Architecture audit

当前 production path 使用两层资产，因此结论是 `MIXED`：

```text
ResearchToolRegistry
  -> HybridRetrievalService
     -> data/knowledge_graph_v2                  (tool/task discovery and hard filter)
     -> ScientificSubjectResolver                (identity-only bridge)
        -> Scientific KG v1.1 OperatorRevision  (canonical scientific identity)
           -> Claim -> EvidenceSpan              (direct evidence)
```

- `LEGACY_KG_USED_FOR_DISCOVERY=true`
- `SCIENTIFIC_KG_USED_FOR_EVIDENCE=true`
- 修复前没有显式 legacy Tool identity → Scientific KG OperatorRevision identity bridge。
- 修复后 bridge owner 是 `engine/scientific_subject_resolution.py::ScientificSubjectResolver`。
- bridge 只返回 project、package、method、operator/revision candidates、status、ambiguity 和 provenance；不选择 claim，不判断科学 scope，不映射 evidence，不产生 Planner action。
- 新 bridge 只在显式 `use_scientific_evidence=true` 的 direct-evidence 请求中启用。旧全局开关路径和 tool discovery 行为保持不变。

## Current direct-evidence supported slice

| Scientific subject | OperatorRevision exists | Direct-evidence claims / bound | Production resolver supported |
|---|---:|---:|---:|
| `SingleR::SingleR` 2.14.1 | yes | 5 / 5 | yes |
| `harmony.RunHarmony` 2.0.5 | yes | 4 / 4 | yes |
| `scanpy.pp.highly_variable_genes` 1.11.2 | yes | 3 / 3 | yes |
| `scanpy.pp.neighbors` 1.11.2 | yes | 2 / 2 | yes |
| `scanpy.pp.pca` 1.11.2 | yes | 2 / 2 | yes |
| `scanpy.tl.leiden` 1.11.2 | yes | 2 / 2 | yes |
| `scanpy.tl.umap` 1.11.2 | yes | 1 / 1 | yes |
| `scrublet.Scrublet.scrub_doublets` 0.2.3 | yes | 5 / 5 | yes |

这张表描述的是 candidate Scientific KG 中当前 direct integration 的 identity/claim/binding 覆盖；它不表示 frozen corpus 一定含有对应 exact chunk，也不表示 candidate knowledge 已 canonical promotion。

## Identity bridge and synthetic proof

新增的确定性 resolver 消费当前 conformance bundle 中已有的 Operator、OperatorRevision、PackageRelease、Method 关系，以及已有 evidence-gap inventory。它支持 exact revision/operator ID、registered API、governed parser alias、package/operator、legacy registry hint、Method → implementing OperatorRevision 和显式 version 过滤；多个 operator 或多个 revision 时保留 ambiguity。

8/8 synthetic cases 通过，覆盖：exact OperatorRevision、exact API、package-qualified operator、governed alias、method name、legacy registry bridge、version-qualified revision 和 ambiguous method。测试 fixture 只使用当前 Scientific KG 已存在的 identity，并以 synthetic duplicate 检查 ambiguity/version 行为；未使用 DEV gold 或 query ID。

## DEV-only before / after

| Metric | Before | After |
|---|---:|---:|
| Subject resolved | 20/28 | 23/28 |
| Operator candidate resolved | 3/28 | 6/28 |
| Unique OperatorRevision resolved | 3/28 | 4/28 |
| Direct graph evidence resolved | 0/28 | 0/28 |

修复后的 identity 状态为：`RESOLVED=4`、`AMBIGUOUS=2`、`OUTSIDE_SCOPE=17`、`UNRESOLVED=5`。最早失败分布为：

| Earliest failure after wiring | Count |
|---|---:|
| `OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE` | 17 |
| `SUBJECT_RESOLUTION_FAILED` | 5 |
| `MULTIPLE_OPERATOR_AMBIGUITY` | 2 |
| `EVIDENCE_NOT_IN_FROZEN_CORPUS` | 2 |
| `CLAIM_TYPE_NOT_EXPRESSED` | 1 |
| `OTHER_EXPLICIT` | 1 |

整体主边界已变成 `OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE=17/28`，它是覆盖边界，不是 wiring bug。当前 slice 内已经显露出的下一层断点包括 exact evidence 不在 frozen corpus、claim type 未表达，以及 public eligibility filter 拒绝 graph evidence。本 checkpoint 按 one-layer rule 停止，没有继续修改这些 owner。

Answerability 从 `0 / 2 / 0 / 26` 变为：

| Status | Count |
|---|---:|
| `SUPPORTED` | 0 |
| `INSUFFICIENT_EVIDENCE` | 2 |
| `CLARIFICATION_REQUIRED` | 2 |
| `UNRESOLVED` | 24 |

`DEV_CORRECT_ABSTENTION=4`、`DEV_FALSE_CERTAINTY=0`。Hit@5、Hit@10、MRR@10 仍分别为 `0.708333`、`0.708333`、`0.607639`；SciKG helped / neutral / hurt 为 `0 / 28 / 0`，false-filter events 为 0。本轮没有调整 BM25、Dense、RRF 或 governance。

## Verification and integrity

- Focused tests: 80 passed，1 个历史 `new_preflight` 按既定条件 deselect。
- Research Chat regression: 52 passed。
- Python compile check: PASS。
- DEV-only loader 在 JSON 反序列化前按 record ID 过滤；14 个旧 ID 继续永久标记 `QUARANTINED_AFTER_DISCLOSURE`。
- 运行前、运行后及测试后的 protected tree hashes 一致：旧 C7、旧 rootcause/blocked checkpoints、frozen corpus/index、legacy KG 与 Planner 均未变化。
- 未读取 SEALED payload，未重跑 SEALED validation，未 canonical promotion。

## Exit

```text
SCIENTIFIC_KG_OPERATOR_WIRING_V1=PASS
SCIENTIFIC_KG_ASSET_USED=MIXED
LEGACY_KG_USED_FOR_DISCOVERY=true
SCIENTIFIC_KG_USED_FOR_EVIDENCE=true
IDENTITY_BRIDGE_EXISTS=true
INITIAL_IMPLEMENTATION_WIRING_ERROR=20/28
TRUE_WIRING_BUG=1/20
OUTSIDE_CURRENT_SCOPE=17/20
AMBIGUOUS_SUBJECT=2/20
OTHER=0/20
SUBJECT_RESOLVED_BEFORE=20/28
SUBJECT_RESOLVED_AFTER=23/28
OPERATOR_REVISION_RESOLVED_BEFORE=3/28
OPERATOR_REVISION_RESOLVED_AFTER=4/28
DIRECT_GRAPH_EVIDENCE_BEFORE=0/28
DIRECT_GRAPH_EVIDENCE_AFTER=0/28
SUPPORTED=0
INSUFFICIENT_EVIDENCE=2
CLARIFICATION_REQUIRED=2
UNRESOLVED=24
NEXT_EARLIEST_DIVERGENCE=OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE (17/28; coverage boundary, not wiring bug)
FOCUSED_TESTS=80 passed, 1 deselected
REGRESSION_TESTS=52 passed
SEALED_PAYLOAD_ACCESSED=false
SEALED_VALIDATION_RERUN=false
FROZEN_C7_ARTIFACTS_CHANGED=false
CORPUS_CHANGED=false
KG_CONTENT_CHANGED=false
PLANNER_CHANGED=false
CANONICAL_PROMOTION=none
```

Subject/operator wiring checkpoint 到此停止；未提交、未推送。
