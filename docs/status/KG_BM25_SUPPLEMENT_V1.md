# KG＋BM25 补充对照与实际参与度 v1

状态：COMPLETE。开发补充实验，不是 formal holdout。

## 比较表

Hit@5 / Hit@10 均为问题级至少命中一个 gold，不是完整相关文档召回率。历史 recall_at_5 / recall_at_10 字段未改写。

| 来源 | Profile | Track | 问题级 Hit@5 | 问题级 Hit@10 | MRR |
|---|---|---|---:|---:|---:|
| 冻结 v1.1.1 | R0_bm25_only | R1_scientific_evidence | 26/45 | 31/45 | 0.381966 |
| 冻结 v1.1.1 | R0_bm25_only | R2_tool_method_discovery | 3/12 | 3/12 | 0.187500 |
| 冻结 v1.1.1 | R1_dense_only | R1_scientific_evidence | 19/45 | 25/45 | 0.338422 |
| 冻结 v1.1.1 | R1_dense_only | R2_tool_method_discovery | 5/12 | 5/12 | 0.176389 |
| 冻结 v1.1.1 | R2_bm25_dense_rrf | R1_scientific_evidence | 22/45 | 31/45 | 0.340265 |
| 冻结 v1.1.1 | R2_bm25_dense_rrf | R2_tool_method_discovery | 4/12 | 4/12 | 0.250000 |
| 冻结 v1.1.1 | R3_kg_bm25_dense_rrf | R1_scientific_evidence | 22/45 | 31/45 | 0.340265 |
| 冻结 v1.1.1 | R3_kg_bm25_dense_rrf | R2_tool_method_discovery | 5/12 | 5/12 | 0.312500 |
| 冻结 v1.1.1 | R4_kg_bm25_dense_rrf_governance | R1_scientific_evidence | 23/45 | 31/45 | 0.380511 |
| 冻结 v1.1.1 | R4_kg_bm25_dense_rrf_governance | R2_tool_method_discovery | 4/12 | 4/12 | 0.229167 |
| 本次补充 | BM25 | R1_scientific_evidence | 26/45 | 31/45 | 0.381966 |
| 本次补充 | BM25 | R2_tool_method_discovery | 3/12 | 3/12 | 0.187500 |
| 本次补充 | KG_BM25 | R1_scientific_evidence | 26/45 | 31/45 | 0.381966 |
| 本次补充 | KG_BM25 | R2_tool_method_discovery | 3/12 | 4/12 | 0.218750 |

版本/scope/authority 历史指标只是 gold/source 命中代理，不能独立验证所有返回内容的科学正确性。

## 实际参与度与逐问题对照

BM25 冻结排序复现：57/57；观测输出与真实 search 最终排序校验：114/114。

HELPED/HURT 按首个 gold 的 reciprocal rank 提升/降低；未命中记为 0。候选集合变化与最终排名变化分别记录。

### R1_scientific_evidence

```json
{
  "query_count": 45,
  "helped_neutral_hurt": {
    "NEUTRAL": 45
  },
  "participation": {
    "NO_TASK_GRAPH_NOT_QUERIED": 30,
    "GRAPH_MATCH_NO_CANDIDATE_CHANGE": 15
  },
  "candidate_set_changed": 0,
  "final_top_k_changed": 0,
  "first_gold_rank_changed": 0,
  "any_available_gold_removed": {
    "numerator": 0,
    "denominator": 35,
    "rate": 0.0,
    "status": "applicable"
  },
  "all_available_gold_lost": {
    "numerator": 0,
    "denominator": 35,
    "rate": 0.0,
    "status": "applicable"
  },
  "baseline_hit5_lost": {
    "numerator": 0,
    "denominator": 26,
    "rate": 0.0,
    "status": "applicable"
  },
  "baseline_hit10_lost": {
    "numerator": 0,
    "denominator": 31,
    "rate": 0.0,
    "status": "applicable"
  }
}
```

### R2_tool_method_discovery

```json
{
  "query_count": 12,
  "helped_neutral_hurt": {
    "NEUTRAL": 10,
    "HELPED": 2
  },
  "participation": {
    "GRAPH_MATCH_CANDIDATES_CHANGED": 8,
    "NO_TASK_GRAPH_NOT_QUERIED": 4
  },
  "candidate_set_changed": 8,
  "final_top_k_changed": 8,
  "first_gold_rank_changed": 2,
  "any_available_gold_removed": {
    "numerator": 0,
    "denominator": 8,
    "rate": 0.0,
    "status": "applicable"
  },
  "all_available_gold_lost": {
    "numerator": 0,
    "denominator": 8,
    "rate": 0.0,
    "status": "applicable"
  },
  "baseline_hit5_lost": {
    "numerator": 0,
    "denominator": 3,
    "rate": 0.0,
    "status": "applicable"
  },
  "baseline_hit10_lost": {
    "numerator": 0,
    "denominator": 3,
    "rate": 0.0,
    "status": "applicable"
  }
}
```

### ALL

```json
{
  "query_count": 57,
  "helped_neutral_hurt": {
    "NEUTRAL": 55,
    "HELPED": 2
  },
  "participation": {
    "NO_TASK_GRAPH_NOT_QUERIED": 34,
    "GRAPH_MATCH_NO_CANDIDATE_CHANGE": 15,
    "GRAPH_MATCH_CANDIDATES_CHANGED": 8
  },
  "candidate_set_changed": 8,
  "final_top_k_changed": 8,
  "first_gold_rank_changed": 2,
  "any_available_gold_removed": {
    "numerator": 0,
    "denominator": 43,
    "rate": 0.0,
    "status": "applicable"
  },
  "all_available_gold_lost": {
    "numerator": 0,
    "denominator": 43,
    "rate": 0.0,
    "status": "applicable"
  },
  "baseline_hit5_lost": {
    "numerator": 0,
    "denominator": 29,
    "rate": 0.0,
    "status": "applicable"
  },
  "baseline_hit10_lost": {
    "numerator": 0,
    "denominator": 34,
    "rate": 0.0,
    "status": "applicable"
  }
}
```

过滤损失分母：公共过滤后至少存在一个 gold 的 query；top-k 退化分母：BM25 原本命中的 query。HURT 不是 false-filter rate。

| Query | Track | BM25 gold rank | KG＋BM25 gold rank | 结果 | 候选数 before→after | 参与类型 |
|---|---|---:|---:|---|---|---|
| r1-adjudicated-tool-04-discovery | R1_scientific_evidence | 3 | 3 | NEUTRAL | 9→9 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-04-input_requirement | R1_scientific_evidence | 2 | 2 | NEUTRAL | 9→9 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-04-metric | R1_scientific_evidence | None | None | NEUTRAL | 9→9 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-07-parameter | R1_scientific_evidence | 4 | 4 | NEUTRAL | 37→37 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-07-output | R1_scientific_evidence | None | None | NEUTRAL | 47→47 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-08-discovery | R1_scientific_evidence | None | None | NEUTRAL | 53→53 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-adjudicated-tool-08-metric | R1_scientific_evidence | None | None | NEUTRAL | 62→62 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-adjudicated-tool-12-parameter | R1_scientific_evidence | None | None | NEUTRAL | 91→91 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-12-output | R1_scientific_evidence | 1 | 1 | NEUTRAL | 88→88 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-13-discovery | R1_scientific_evidence | 2 | 2 | NEUTRAL | 3→3 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-13-failure_mode | R1_scientific_evidence | 3 | 3 | NEUTRAL | 3→3 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-16-parameter | R1_scientific_evidence | 3 | 3 | NEUTRAL | 11→11 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-tool-16-output | R1_scientific_evidence | 6 | 6 | NEUTRAL | 11→11 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-adjudicated-workflow-04 | R1_scientific_evidence | 4 | 4 | NEUTRAL | 92→92 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-adjudicated-ambiguous-03 | R1_scientific_evidence | 9 | 9 | NEUTRAL | 84→84 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-leiden-input | R1_scientific_evidence | 1 | 1 | NEUTRAL | 20→20 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-harmony-input | R1_scientific_evidence | 1 | 1 | NEUTRAL | 60→60 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-harmony-output | R1_scientific_evidence | 3 | 3 | NEUTRAL | 60→60 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-neighbors-input | R1_scientific_evidence | None | None | NEUTRAL | 4→4 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-raw-input | R1_scientific_evidence | 3 | 3 | NEUTRAL | 54→54 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-dispersion-input | R1_scientific_evidence | 2 | 2 | NEUTRAL | 42→42 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-count-input | R1_scientific_evidence | 1 | 1 | NEUTRAL | 48→48 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-default-flavor | R1_scientific_evidence | 2 | 2 | NEUTRAL | 37→37 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-hvg-output | R1_scientific_evidence | 1 | 1 | NEUTRAL | 31→31 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-query-input | R1_scientific_evidence | 1 | 1 | NEUTRAL | 46→46 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-reference-expression | R1_scientific_evidence | 8 | 8 | NEUTRAL | 48→48 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-reference-labels | R1_scientific_evidence | 4 | 4 | NEUTRAL | 48→48 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-shared-features | R1_scientific_evidence | 7 | 7 | NEUTRAL | 48→48 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-reference-choice | R1_scientific_evidence | 1 | 1 | NEUTRAL | 48→48 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-normalized-input | R1_scientific_evidence | 2 | 2 | NEUTRAL | 59→59 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-feature-overlap-guidance | R1_scientific_evidence | 3 | 3 | NEUTRAL | 49→49 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-default-model | R1_scientific_evidence | 7 | 7 | NEUTRAL | 48→48 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-seed-layer-requirement | R1_scientific_evidence | 4 | 4 | NEUTRAL | 99→99 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-overlapping-samples-supported | R1_scientific_evidence | 1 | 1 | NEUTRAL | 3→3 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-seed-latent-output | R1_scientific_evidence | 1 | 1 | NEUTRAL | 3→3 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-normalization | R1_scientific_evidence | None | None | NEUTRAL | 1→1 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-pca-input | R1_scientific_evidence | None | None | NEUTRAL | 5→5 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-pca-output | R1_scientific_evidence | None | None | NEUTRAL | 3→3 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-neighbors-output | R1_scientific_evidence | None | None | NEUTRAL | 3→3 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-umap-input | R1_scientific_evidence | None | None | NEUTRAL | 6→6 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-umap-output | R1_scientific_evidence | 1 | 1 | NEUTRAL | 2→2 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-soupx-ambient | R1_scientific_evidence | 1 | 1 | NEUTRAL | 1→1 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-extra-edger-count-input | R1_scientific_evidence | None | None | NEUTRAL | 0→0 | NO_TASK_GRAPH_NOT_QUERIED |
| r1-extra-slingshot-output | R1_scientific_evidence | None | None | NEUTRAL | 0→0 | GRAPH_MATCH_NO_CANDIDATE_CHANGE |
| r1-extra-pyscenic-grn | R1_scientific_evidence | None | None | NEUTRAL | 0→0 | NO_TASK_GRAPH_NOT_QUERIED |
| r2-discovery-scrublet | R2_tool_method_discovery | None | None | NEUTRAL | 110→65 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-harmony | R2_tool_method_discovery | None | None | NEUTRAL | 92→39 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-scanorama | R2_tool_method_discovery | 4 | 2 | HELPED | 104→83 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-scvi | R2_tool_method_discovery | None | None | NEUTRAL | 119→119 | NO_TASK_GRAPH_NOT_QUERIED |
| r2-discovery-celltypist | R2_tool_method_discovery | None | None | NEUTRAL | 120→120 | NO_TASK_GRAPH_NOT_QUERIED |
| r2-discovery-singler | R2_tool_method_discovery | 1 | 1 | NEUTRAL | 120→120 | NO_TASK_GRAPH_NOT_QUERIED |
| r2-discovery-cellrank | R2_tool_method_discovery | None | None | NEUTRAL | 114→102 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-mofa2 | R2_tool_method_discovery | None | None | NEUTRAL | 115→3 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-soupx | R2_tool_method_discovery | 1 | 1 | NEUTRAL | 57→2 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-tradeseq | R2_tool_method_discovery | None | 8 | HELPED | 91→41 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-scvelo | R2_tool_method_discovery | None | None | NEUTRAL | 117→71 | GRAPH_MATCH_CANDIDATES_CHANGED |
| r2-discovery-scanpy | R2_tool_method_discovery | None | None | NEUTRAL | 0→0 | NO_TASK_GRAPH_NOT_QUERIED |

## 实际图调用边界

```json
{
  "rank_tools_call_count": 23,
  "graph_read_node_types": {
    "Tool": 1839,
    "Task": 9,
    "Modality": 1
  },
  "unique_nodes_read": 1849,
  "unique_edges_read": 11363,
  "adjacency_read_relation_types": {
    "SUPPORTS_TASK_CLAIM": 23,
    "CONTRACTS_TASK": 6,
    "REQUIRES_OUTPUT_OF": 12,
    "PRECEDES": 11,
    "CATALOG_ADDRESSES_TASK": 1755,
    "ADDRESSES_TASK": 24,
    "EXECUTES_TASK": 6,
    "HAS_MODALITY_SCOPE": 26,
    "CONTRACTS_MODALITY": 6,
    "CATALOG_SUPPORTS_MODALITY": 1839,
    "SUPPORTS_MODALITY": 22,
    "CATALOG_HAS_PUBLICATION": 857,
    "CATALOG_HAS_PREPRINT": 717,
    "CATALOG_HAS_CATEGORY": 3017,
    "HAS_RETRIEVAL_CHUNK": 1818,
    "CATALOG_IMPLEMENTED_IN": 1133,
    "EVALUATED_IN_BENCHMARK": 13,
    "HAS_PUBLICATION": 24,
    "HAS_EVIDENCE_SOURCE": 35,
    "HAS_TOOL_CONTRACT": 6,
    "CATALOG_RUNS_ON": 5,
    "IS_SUBTASK_OF": 1,
    "HAS_SCIENTIFIC_PILOT": 7
  },
  "selected_task_modality_path_relation_types": {
    "CATALOG_ADDRESSES_TASK": 997,
    "CATALOG_SUPPORTS_MODALITY": 751,
    "ADDRESSES_TASK": 5,
    "EXECUTES_TASK": 4,
    "SUPPORTS_MODALITY": 4
  },
  "read_vs_use_boundary": "Adjacency lists can contain unrelated edges; read does not prove semantic evaluation. Selected match paths directly control candidate-tool eligibility. Outgoing contract/pilot/chunk checks only affect tool rank before limit=200.",
  "entrypoints": {
    "search": {
      "path": "engine/hybrid_retrieval.py",
      "line": 138
    },
    "kg_candidates": {
      "path": "engine/hybrid_retrieval.py",
      "line": 902
    },
    "rank_tools": {
      "path": "engine/evidence_graph_query.py",
      "line": 169
    },
    "tool_edges": {
      "path": "engine/evidence_graph_query.py",
      "line": 292
    },
    "filter_ranked": {
      "path": "engine/hybrid_retrieval.py",
      "line": 796
    }
  }
}
```

真实调用：HybridRetrievalService.search → _kg_candidates → EvidenceGraphQuery.rank_tools；图文件为 data/knowledge_graph_v2/{nodes,edges,manifest}.json[l]。
rank_tools 按 Task/Modality 查询工具，可能展开 IS_SUBTASK_OF，并用 contract/pilot/source-chunk 元数据为工具候选评分；分数本身不加入 BM25/RRF 排名。候选集合最多 200 个工具，再以 chunk 原有工具 membership 过滤。

graph_access.jsonl 保存每次真实图查询的节点/边读取、匹配路径、候选工具和 warning。读取某类边不等于执行了该边的科学含义；例如读取 HAS_TOOL_CONTRACT 只检查存在性与治理层，不验证 contract 输入。

production search 内只有一次综合 _filter_ranked。before/after 是两个配对 profile 的实际过滤输出，不伪称 production 先后执行两次 filter，也不是 canonical Trace。

- legacy Tool/Task/Modality：EXERCISED（实际调用证据见 graph_access.jsonl）。
- Scientific KG OperatorRevision：NOT_EXERCISED。
- Scientific requirement / ApplicabilityScope / version 条件：NOT_EXERCISED。
- AtomicClaim → EvidenceSpan 科学决策证据遍历：NOT_EXERCISED。
新 Scientific KG 的适用性语义在 planner applicability 路径，不在此检索候选接口。本次不能证明新图改善科学检索。若后续要测，需要单独定义并实现从 retrieval scientific claim request 到受治理 OperatorRevision/requirement/scope/version/AtomicClaim→EvidenceSpan 的生产查询边界；本轮未接入。

## 冻结与执行记录

输入/SUT/graph/test SHA 见 pre_run_manifest.json；结果摘要见 artifact_manifest.json。测试记录：python -m pytest -q tests/test_kg_bm25_supplement_v1.py: 18 passed in 3.33s; py_compile PASS; git diff --check PASS。
BM25 与 KG＋BM25 各执行 57 次 search，无 dense encode；不修改原有工具识别、归一化、top-k、候选预算或多样化规则。所有 gold 仅在响应产生后评分，未传入 request。
输出中的 candidate_pending_review、catalog metadata 不能因命中升级为 trusted。历史结果与 Seed 保持原字节；未调参、未提交、未 push。
