# Scientific KG Direct-Evidence Coverage Audit v1

## Executive finding

当前 production resolver 使用的 Scientific KG v1.1 candidate asset 一共有 **8 个 OperatorRevision**。Bundle 全局有 25 个 AtomicClaim，其中 24 个以这 8 个 OperatorRevision 为 subject。全部 8 个都有 planning-relevant AtomicClaim、EvidenceAssessment、exact EvidenceSpan、可解析 SourceRevision 以及显式 scope/version metadata；其中：

- **6 个已经天然达到 L3，并且当前 resolver 已允许，因此最高级别为 L4**；
- **Harmony 与 Scrublet 停在 L2**，唯一最早缺口是 frozen RAG chunk mapping；
- 没有 OperatorRevision 停在 L0 或 L1；
- 6 个 L3/L4 operator 全部仍是 `candidate_only_not_promoted`，L4 不代表 trusted knowledge 或 execution authorization。

因此仓库中天然存在 narrow direct-evidence slice，不需要增加科学内容。推荐先审阅 5 个 operator：HVG、PCA、neighbors、Leiden、SingleR。它们共同覆盖 input requirement、output semantics 和 compatibility；当前没有 frozen-mapped limitation claim，所以不应把 limitation QA 纳入这轮 narrow slice。

## Audited assets

```text
LEGACY_DISCOVERY_ASSET=data/knowledge_graph_v2
SCIENTIFIC_EVIDENCE_ASSET=data/evidence_candidates/scientific_kg_v1_uat_decision_rules
DIRECT_EVIDENCE_BINDING_ASSET=evidence_assessments.jsonl + exact_evidence_bindings.jsonl + authoritative_evidence_spans.jsonl + authoritative_source_manifest.json
FROZEN_RAG_CHUNK_ASSET=data/indexes/retrieval_foundation_v1/evidence_chunks.jsonl
```

`data/knowledge_graph_v2` 只作为 legacy Tool–Task–Modality discovery asset；本审计没有把它计作 Scientific KG evidence coverage。

本审计按生产 `ScientificKGEvidence._span_binding` 的完整性规则验证 claim、assessment、binding、span 和 source，并使用生产 exact chunk mapping 条件核对 frozen retrieval index。没有执行 C7 DEV_CHECK、SEALED、Hit@K、MRR 或 helped/hurt 评测。

## Coverage levels

Coverage level 是层级关系。最高级别的互斥分布为：

| Highest level | Operators |
|---|---:|
| L0 `IDENTITY_ONLY` | 0 |
| L1 `CLAIM_PRESENT` | 0 |
| L2 `EVIDENCE_BOUND` | 2 |
| L3 `RETRIEVAL_READY` but not enabled | 0 |
| L4 `PRODUCTION_ENABLED` | 6 |

按“达到该层或更高”统计：8/8 达到 L1，8/8 达到 L2，6/8 达到 L3，6/8 达到 L4。下面 exit 中的 `L3_RETRIEVAL_READY=6` 包含这 6 个 L4 operator。

## Operator-level matrix

| OperatorRevision | Claims | Assessments | Exact spans | Frozen chunks | Highest level | Earliest gap |
|---|---:|---:|---:|---:|---|---|
| `scanpy.pp.highly_variable_genes:1.11.2` | 3 | 3 | 2 | 2 | L4 | — |
| `scanpy.pp.pca:1.11.2` | 2 | 2 | 2 | 1 | L4 | — |
| `scanpy.pp.neighbors:1.11.2` | 2 | 2 | 3 | 2 | L4 | — |
| `scanpy.tl.umap:1.11.2` | 1 | 1 | 1 | 1 | L4 | — |
| `scanpy.tl.leiden:1.11.2` | 2 | 2 | 2 | 1 | L4 | — |
| `SingleR::SingleR:2.14.1` | 5 | 5 | 6 | 5 | L4 | — |
| `harmony.RunHarmony:2.0.5` | 4 | 4 | 3 | 0 | L2 | `RAG_CHUNK_MAPPING_MISSING` |
| `scrublet.Scrublet.scrub_doublets:0.2.3` | 5 | 5 | 3 | 0 | L2 | `RAG_CHUNK_MAPPING_MISSING` |

逐 claim 的 predicate、scope、assessment、EvidenceSpan、SourceRevision 和 RAG chunk IDs 记录在 `operator_coverage_matrix.jsonl`。6 个 ready operator 的完整可用链记录在 `retrieval_ready_operators.json`。

Scrublet 的 `project_guardrail` claim 是 `partial_support`，因此不计入 supported direct chain；其余 supported claims 已具备 exact evidence binding，仍足以把该 OperatorRevision 定为 L2。所有引用的 EvidenceSpan 都保持 source-bound。

## Natural L3 candidates

当前天然满足 L3 的 OperatorRevision 共 6 个：

1. `operator-revision:scanpy.pp.highly_variable_genes:1.11.2:uat-corrected` — input、output；2 spans，2 chunks。
2. `operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected` — input、output；2 mapped spans，2 chunks。
3. `operator-revision:scanpy.pp.pca:1.11.2:uat-corrected` — input；1 mapped span，1 chunk。
4. `operator-revision:scanpy.tl.leiden:1.11.2:uat-corrected` — input；1 mapped span，1 chunk。
5. `operator-revision:scanpy.tl.umap:1.11.2:uat-corrected` — input；1 mapped span，1 chunk。
6. `operator-revision:SingleR::SingleR:2.14.1:uat-corrected` — input、compatibility；5 mapped spans，5 chunks。

这些链在本轮开始前已经存在。本轮没有新增 OperatorRevision、claim、assessment、EvidenceSpan、SourceRevision 或 corpus chunk，也没有重建 index。所有 ready operator 仍是 candidate status。

推荐的最多 5 个 narrow slice 是：HVG、PCA、neighbors、Leiden、SingleR。UMAP 同样达到 L4，但其当前 mapped information need 只有 input，与推荐 slice 中已有能力重复。

## Midterm core audit

| Operator | Identity | Claim | Scope/version | EvidenceSpan | RAG mapping | Level |
|---|---:|---:|---:|---:|---:|---|
| HVG | yes | yes | yes | yes | yes | L4 |
| PCA | yes | yes | yes | yes | yes | L4 |
| neighbors | yes | yes | yes | yes | yes | L4 |
| UMAP | yes | yes | yes | yes | yes | L4 |
| Leiden | yes | yes | yes | yes | yes | L4 |
| Harmony | yes | yes | yes | yes | no | L2 |
| Scrublet | yes | yes | yes | yes | no | L2 |
| SingleR | yes | yes | yes | yes | yes | L4 |
| marker ranking / DE | no | no | no | no | no | not in current asset |
| CellTypist | no | no | no | no | no | not in current asset |
| SoupX | no | no | no | no | no | not in current asset |

中期核心 L3 operator 是 HVG、PCA、neighbors 和 Leiden。Harmony 与 Scrublet 不需要新科学内容才能从 L2 前进；它们需要的是现有 exact spans 到 frozen RAG chunks 的治理后映射。marker ranking / DE、CellTypist、SoupX 若要进入这个 Scientific KG asset，则需要新的受治理科学内容，不能只靠 production enablement。

## Gap taxonomy

对 8 个现有 OperatorRevision 中未达到 L3 的 earliest gap 统计：

| Gap | Count |
|---|---:|
| `IDENTITY_ONLY` | 0 |
| `CLAIM_MISSING` | 0 |
| `SCOPE_MISSING` | 0 |
| `EVIDENCE_ASSESSMENT_MISSING` | 0 |
| `EVIDENCE_SPAN_MISSING` | 0 |
| `SOURCE_REVISION_UNRESOLVED` | 0 |
| `RAG_CHUNK_MAPPING_MISSING` | 2 |
| `OTHER` | 0 |

当前 Scientific KG 内部的主要 coverage gap 因此是 `RAG_CHUNK_MAPPING_MISSING`，不是 claim 或 source coverage。扩大到当前 8 个之外的 ecosystem 则仍需要新科学内容。

## Integrity and Phase A freeze

Phase A 已按责任层完成并推送：

- `a967183` — `feat: add governed scientific subject resolution`
- `4afd46e` — `eval: freeze direct-evidence root-cause and wiring audits`
- `edfbc6b` — `test: add scientific evidence resolution regressions`

Focused tests 为 80 passed、1 deselected；Research Chat regression 为 52 passed。`LOCAL_HEAD` 与 `REMOTE_HEAD` 均为 `edfbc6b2916ba3ad416d8d71b66e482a1f5fef71`。

Phase B 的 Scientific KG、legacy KG、frozen retrieval index、Planner、retrieval engine 运行前后 hashes 完全一致。未读取 SEALED payload，未运行 C7 DEV/SEALED，未修改 retrieval weights，未 promotion。

## Exit

```text
SCIENTIFIC_KG_DIRECT_EVIDENCE_COVERAGE_AUDIT_V1=COMPLETE
TOTAL_OPERATOR_REVISIONS=8
L0_IDENTITY_ONLY=0
L1_CLAIM_PRESENT=0 (highest level; 8/8 reach L1 or higher)
L2_EVIDENCE_BOUND=2 (highest level; 8/8 reach L2 or higher)
L3_RETRIEVAL_READY=6 (includes the 6 L4 operators)
L4_PRODUCTION_ENABLED=6
PRIMARY_COVERAGE_GAP=RAG_CHUNK_MAPPING_MISSING (2/8: Harmony, Scrublet)
MIDTERM_CORE_L3_OPERATORS=[operator-revision:scanpy.pp.highly_variable_genes:1.11.2:uat-corrected, operator-revision:scanpy.pp.pca:1.11.2:uat-corrected, operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected, operator-revision:scanpy.tl.leiden:1.11.2:uat-corrected]
NARROW_DIRECT_EVIDENCE_SLICE_FEASIBLE=true
REQUIRES_NEW_SCIENTIFIC_CONTENT=false
SEALED_PAYLOAD_ACCESSED=false
SEALED_VALIDATION_RERUN=false
CORPUS_CHANGED=false
KG_CONTENT_CHANGED=false
PLANNER_CHANGED=false
RETRIEVAL_WEIGHTS_CHANGED=false
CANONICAL_PROMOTION=none
LOCAL_HEAD=edfbc6b2916ba3ad416d8d71b66e482a1f5fef71
REMOTE_HEAD=edfbc6b2916ba3ad416d8d71b66e482a1f5fef71
```

本 checkpoint 到此停止；没有自动开启 narrow production slice。
