# scKG Decision Graph v3.1 / Action Space v1

日期：2026-07-16
状态：implemented

## 1. 为什么拆成两张图

scRNA-tools 的 1847 个工具需要完整保留，但“目录里存在”不等于“可以推荐或执行”。因此知识层明确拆分为：

```text
Catalog Graph v2
  全量工具、category、publication/preprint metadata、legacy hypothesis
  用途：搜索、召回、发现证据、审计 catalog 覆盖

Decision Graph v3
  核心工具、Action、原文 chunk、ToolContract、输入输出、数据假设、
  FailureMode、ValidationRule、KnowHow、环境、科学 pilot
  用途：ActionBundle、任务规划、工具档案、执行前约束、局部决策路径
```

两张图不互相冒充。Catalog Graph 的 category、旧 LLM profile 和向量相似度不能直接生成 Decision Graph 能力边。

## 2. 严格关系

Decision Graph 当前只允许：

```text
Tool -[:HAS_SOURCE_MATERIAL]-> SourceChunk
Tool -[:HAS_VERIFIED_CONTRACT]-> ToolContract
ToolContract -[:CONTRACTS_TASK]-> Task
ToolContract -[:IMPLEMENTS_ACTION]-> Action
Action -[:REALIZES_TASK]-> Task
Action -[:CONSUMES_INPUT]-> InputArtifact
Action -[:MAY_PRODUCE_OUTPUT]-> OutputArtifact
Action -[:REQUIRES_ASSUMPTION]-> DataAssumption
Action -[:GUARDED_AGAINST]-> FailureMode
Action -[:VALIDATED_BY]-> ValidationRule
Action -[:INFORMED_BY_KNOW_HOW]-> KnowHow
ToolContract -[:ACCEPTS_INPUT]-> InputArtifact
ToolContract -[:REQUIRES_ASSUMPTION]-> DataAssumption
ToolContract -[:DECLARES_PARAMETER]-> Parameter
ToolContract -[:PRODUCES_OUTPUT]-> OutputArtifact
ToolContract -[:RUNS_IN]-> Environment
ToolContract -[:DECLARES_FAILURE_MODE]-> FailureMode
ToolContract -[:USES_VALIDATION_RULE]-> ValidationRule
ToolContract -[:HAS_REVIEWED_KNOW_HOW]-> KnowHow
Tool -[:HAS_DATASET_SCOPED_EVALUATION]-> Evaluation
Evaluation -[:EVALUATED_ON]-> Dataset
```

每条边必须有 `provenance_refs`。`HYPOTHESIZED_*` 在 schema 层被拒绝。旧 chunk 中 AI 辅助生成、尚未复核的 task 字段不会转成能力边。

Action 是跨工具共享的分析动作，不是工具别名。当前 Scrublet 和 scDblFinder 通过两个独立 ToolContract 实现同一个 `Doublet Detection` Action，因此工具能力在动作层汇合，同时保留各自参数、环境、输出和失败边界。

`ActionBundleRetriever` 将上述路径编译成 Parent Agent 可消费的结构化 planning context。ActionBundle 的 `execution_allowed` 固定为 false；它不能替代 policy、data grant、exact approval、ownership、Router 或 safety gate。

## 3. Readiness

```text
source_material
  有原文或正式表条目 chunk；只支持发现

contract_verified
  有通过 execution-critical review 的版本化 contract 和登记环境

decision_ready
  contract_verified + dataset-scoped evaluation
```

`decision_ready` 仍不等于“自动执行”。真实运行继续要求 `ExecutionPolicy`、owner、data grant、未变化 plan 和 plan-specific approval。

## 4. 当前快照

```text
snapshot: decision-kg-v3.1.0-action-space
nodes: 1007
edges: 1113
catalog tools: 1847
scoped tools: 25
governed actions: 2
qualified actions: 1
planning-only actions: 1
action implementations: 2
generic action bundles: 2
tools with source material: 23
source-rich tools: 16
contract-verified tools: 2
dataset-scoped evaluated tools: 2
decision-ready tools: 2
hypothesis edges: 0
edge provenance coverage: 100%
decision source-bound rate: 100%
contract I/O coverage: 100%
connected components: 22
isolated nodes: 0
```

22 个 component 是诚实的覆盖结果，不是错误。它说明多数工具之间尚无经过审核的决策关系；系统不会再用共同的 `scRNA-seq` 标签或宽泛 category 强行连通。

当前 decision-ready 工具只有 Scrublet 0.2.3 与 scDblFinder 1.24.0，科学评估范围仅为 GSE108313 PBMC HTO pilot。

## 5. 前端

Knowledge Graph 使用宽屏工作台，默认打开 Graph Explorer：

- Catalog landscape：按官网 33 个 category 保留全部 1847 条目录记录，支持 `Catalog -> Category -> Tool -> Metadata/Publication/Preprint` 逐层展开；
- Decision neighborhood：默认只显示 Tool、Action、Task、Contract、Environment、Dataset、Evaluation 与关键 I/O，参数、失败模式、验证规则、KnowHow 和证据节点通过点击逐邻居展开；
- Search projection：按节点类型和关键词加载有界子图，并复用相同交互画布；
- Action Space：展示共享 Action、contract implementations 和 read-only ActionBundle；
- Tool Dossier：展示输入、输出、假设、环境、参数、FailureMode、ValidationRule、KnowHow、source coverage 和 scoped evaluation；
- Governance：展示严格图谱质量、provenance coverage 与真实 component。

Catalog hierarchy 提供搜索、面包屑、Back、Overview 和分页。Decision/Search network 提供滚轮缩放、画布平移、节点拖拽、类型/治理层过滤、搜索、适配画布、详情检查器和逐邻居展开。完整 JSONL/Neo4j projection 不会一次性画成 8631 节点画布，因为那只能产生不可读的 hairball；Catalog landscape 保证全量记录可达，Search projection 和 Decision neighborhood 保证关系可读。

节点坐标只是一种可修改的视觉布局，不代表 `1 -> 2 -> 3` 顺序、证据等级或统计相关性。流程顺序由 WorkflowPlan DAG 和 Orchestrator 状态机表达；节点关系只由带 provenance 的 typed edge 表达。未来 KEGG/GO 只能作为独立、版本化的生物解释层连接 Gene、GOTerm、Pathway 与 AnalysisArtifact，不能反向授予工具执行能力。

Bounded Parent Agent 同时使用两层图：Catalog Graph 负责 recall context，Decision Graph/ActionBundle 负责 strict admission 和 DataProfile compatibility。候选必须具备 contract-implemented Action，Parent 才会加载 contract 并编译 dry-run plan；catalog-only 候选路由到 Evidence Recovery。

## 6. 构建与验证

```bash
python scripts/build_decision_graph_v3.py
python scripts/run_decision_graph_v3_smoke.py
python scripts/run_action_space_v1_smoke.py
python -m pytest tests/test_decision_graph_v3.py tests/test_action_bundle_retriever.py
```

JSONL 是当前 canonical artifact：

```text
data/decision_graph_v3/nodes.jsonl
data/decision_graph_v3/edges.jsonl
data/decision_graph_v3/quality_report.json
data/decision_graph_v3/manifest.json
data/decision_graph_v3/action_bundles.jsonl
```

Decision Graph v3 暂不写入 Neo4j。schema 和质量 gate 稳定后再做隔离 namespace 导入，不能覆盖 Catalog Graph 或 trusted graph。
