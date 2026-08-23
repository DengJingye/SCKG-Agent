# Evidence-governed Knowledge Graph v2

日期：2026-07-15
状态：KG v2.2 implemented，官方 catalog 已全量同步

## 1. 目标

KG v2 解决的不是“把图画大”，而是让 Agent 能明确区分：

```text
这是目录实体
这是可检索原文
这是被冻结或隔离的证据
这是完成工程 qualification 的执行能力
这是可支持主推荐的 formal evidence
```

旧 Neo4j 图保留，不删除。旧 LLM profile/embedding 经过确定性 ontology normalization 后，只能生成带 provenance 的 `HYPOTHESIZED_*` 检索边，不能自动生成可信关系。

## 2. 产物

```text
data/knowledge_graph_v2/nodes.jsonl
data/knowledge_graph_v2/edges.jsonl
data/knowledge_graph_v2/quality_report.json
data/knowledge_graph_v2/manifest.json
data/catalog/scrna_tools_snapshot.json
data/indexes/scrna_tools_catalog_chunks.jsonl
data/evidence_candidates/scrna_tools_catalog_audit.json
eval/kg_v2/kg_v2_per_case.jsonl
eval/kg_v2/kg_v2_summary.json
eval/kg_v2/graph_retrieval_gold.json
```

Neo4j 使用隔离命名空间：

```text
(:KGv2Node)
(:KGv2Tool)
(:KGv2Task)
(:KGv2Category)
(:KGv2ToolContract)
(:KGv2Environment)
(:KGv2SourceChunk)
(:KGv2AlgorithmFamily)
(:KGv2Language)
(:KGv2RuntimePlatform)
(:KGv2Hardware)
(:KGv2Resolution)
-[:KG_V2_REL]->
```

旧 `Tool/Algorithm/Task/Evidence` 节点不会被删除或覆盖。

## 3. 治理层

| Layer | 含义 | 能否支持主推荐 |
| --- | --- | --- |
| `trusted_core` | source-bound 且通过 formal promotion | 可以 |
| `execution_verified` | contract/environment/qualification 或 dataset-scoped pilot | 不直接可以 |
| `retrieval_only` | 目录、原文 chunk、待晋升材料 | 不可以 |
| `frozen` | audit 不通过、缺 source span 或 numeric scope | 不可以 |
| `quarantined` | DOI、标题、来源元数据不一致 | 不可以 |

`recommendation_eligible=true` 只能出现在 `trusted_core + source_bound` 记录上，Pydantic schema 会拒绝其他组合。

## 4. 当前快照

```text
snapshot: kg-v2.2.0
nodes: 8631
edges: 31410
catalog tools: 1847 / 1847 upstream snapshot
connected tools: 1847
isolated tools: 0
connected components: 1
largest component: 100%
catalog category coverage: 100%
tool semantic coverage: 100%
hypothesis edges: 12389
catalog publications: 1607
catalog preprints: 1327
source chunks: 819 evidence + 1847 catalog metadata
execution-verified tools: 2
formal publication allowed: 0 / 28
formal benchmark allowed: 0 / 14
frozen recommendation leakage: 0
hypothesis recommendation leakage: 0
dangling edges: 0
Neo4j shadow import: 8631 / 31410 count verified
```

“连通”不等于“可信”。当前 1847 个工具全部具备官网 category、scRNA-seq scope 和目录 chunk；官网 publication/preprint 只作为文献发现元数据，不代表已读取全文。12389 条旧 LLM profile 关系仍是低置信检索假设；只有 Scrublet 与 scDblFinder 具备 execution-verified capability path，formal publication/benchmark 仍未晋升。

## 5. Agent 使用方式

KG v2 存在时，`Neo4jClient.find_candidates_by_hard_constraints` 优先读取 governed local snapshot。候选带有：

```text
candidate_basis=execution_verified
candidate_basis=catalog_metadata
candidate_basis=graph_hypothesis
```

`execution_verified` 仍需 DataProfile、WorkflowPlan、ExecutionPolicy、data grant、plan-specific approval 与 ownership gate；`catalog_metadata` 是官网来源绑定的候选召回；`graph_hypothesis` 是旧 profile 的未核验关系。后两者都只能触发证据检索，不能直接推荐或执行。

Agent 对 KG 的实际调用能力包括：任务/模态候选召回、ToolContract 与输入输出约束过滤、路径解释、证据缺口识别和 `EVIDENCE_RECOVERY` 路由。它不是网站表格的图形复制。

前端 Knowledge Graph 页面包含：

- Graph Explorer：关系与治理层可视化；
- Tool Evidence：可解释 GraphRAG planner、ontology path、contract、environment、pilot、冻结证据与 limitations；
- Quality Audit：连通性、语义覆盖、两类泄漏、fixed retrieval regression、formal promotion 与 Neo4j shadow 状态。

固定 positive-only retrieval regression 覆盖 doublet detection、cell type annotation、data integration、RNA velocity 和 spatial mapping，共 5 个 case。当前 Macro Recall@10=1.0、path provenance coverage=1.0、execution admission violation=0；该集合不能估计全目录 precision，也不能充当 formal evidence。

## 6. 固定命令

构建主快照：

```bash
python scripts/build_knowledge_graph_v2.py
```

同步并审计官网目录：

```bash
python scripts/sync_scrna_tools_catalog.py
python scripts/sync_scrna_tools_catalog.py --apply
python data_pipeline/build_evidence_index.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv
```

默认第一次命令只报告 drift；只有显式 `--apply` 才更新本地全量快照与 7 列兼容 TSV。

运行质量 smoke：

```bash
python scripts/run_kg_v2_smoke.py
```

运行固定治理评测：

```bash
python eval/run_kg_v2_evaluation.py
```

生成 Agent demo：

```bash
python scripts/run_kg_v2_agent_demo.py
```

显式更新 Neo4j shadow projection：

```bash
python scripts/import_knowledge_graph_v2.py --confirm-shadow-import
```

重建后若 nodes/edges hash 未变化，已验证的 shadow import 状态会保留；hash 变化时必须重新导入并核对计数。

## 7. 下一步边界

允许：

- 通过 Evidence Recovery promotion 增加 source-bound relations；
- 为核心工具补 reviewed ToolContract；
- 扩充独立标注的 retrieval gold，并增加 hard negative/precision 评测；
- 为高频工具补官方 README、primary paper full text、benchmark 和 reviewed ToolContract；
- 将 JSONL 中稳定 schema 显式映射为 typed Neo4j relation。

不允许：

- 用 LLM profile 或 cosine similarity 自动生成 trusted edge；
- 把全量 catalog publication 标题当成 full-text evidence；
- 把 scientific pilot 当成普遍最优证据；
- 将 `HYPOTHESIZED_*` 边重标为 trusted 或据此直接执行；
- 让 memory、reflection、subagent output 或 RAG chunk 绕过 formal promotion。
