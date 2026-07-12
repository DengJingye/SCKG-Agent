# scKG-Atlas Agent 中文开发规约

版本：0.1
状态：1.x 历史维护版，2.0 生效后冻结
首次创建：2026-06-22

> 说明：本文件保留 scKG-Agent 1.x 的证据治理、KG-RAG、推荐、迁移与可观测性演进记录。自 2026-07-10 起，新的执行型 Agent 主路线以 `docs/DEV_SPEC_2.0.md` 为唯一中文主开发基准。英文版 `docs/DEV_SPEC_scKG.md` 继续作为冻结参考版保留。

---

## 0. 一句话结论

scKG-Atlas Agent 不是普通聊天机器人，也不应该继续以“玩具 agent”的方式零散加功能。它应该被规划成：

```text
面向单细胞、空间组学、多组学工具推荐的
证据治理型 Hybrid KG-RAG / GraphRAG 科研 Agent
```

它的核心创新不是“会聊天”，而是把下面几个环节串成一个可审计闭环：

```text
formal evidence
  -> knowledge graph
  -> governed retrieval
  -> evidence gate
  -> MCDM / migration routing
  -> EvidenceContextPack
  -> safe report
  -> semantic hallucination audit
  -> evaluation and review loop
```

我们后续所有开发都应该围绕这个闭环展开。

---

## 1. 项目定位

### 1.1 项目是什么

scKG-Atlas Agent 是一个证据治理型科研推荐系统，目标是帮助用户在 single-cell、spatial omics、multi-omics 场景下选择合适的分析工具、工作流或方法迁移方向。

系统要做的不是开放式闲聊，而是：

- 理解用户科研问题；
- 抽取结构化约束；
- 在知识图谱和 formal evidence 中检索候选工具；
- 用可信证据约束推荐；
- 对缺证据的地方明确降级或阻断；
- 生成可审计报告；
- 用 semantic auditor 阻止 unsupported scientific claims；
- 用 eval 结果推动证据与系统迭代。

### 1.2 项目不是什么

scKG 不应该被做成：

- 普通 ChatGPT wrapper；
- 只会查向量库的 RAG demo；
- 只凭 GitHub stars 排名的工具推荐器；
- 无证据自动推理的 AutoGPT；
- 自动把候选证据写进正式知识库的爬虫；
- 先堆功能、后补治理的玩具系统。

系统必须永远区分：

```text
可信推荐证据
检索解释上下文
候选待审证据
实验性迁移假设
用户记忆与偏好
```

这五类东西绝对不能混在一起。

---

## 2. 核心产品闭环

### 2.1 主推荐闭环

```text
用户问题
  -> 约束解析
  -> task ontology 归一化
  -> KG 硬约束召回
  -> formal evidence 获取
  -> evidence gate
  -> trusted_core 过滤
  -> task-specific guardrail
  -> MCDM 打分
  -> top-k 推荐
  -> EvidenceContextPack
  -> 报告生成
  -> semantic hallucination audit
  -> 安全输出或 blocked report
```

### 2.2 迁移假设闭环

当没有足够强的直接工具推荐，或用户明确问“能不能借鉴、迁移、没有现成工具怎么办”时，进入 migration route：

```text
migration intent gate
  -> source/target task 检查
  -> algorithm representation v2
     - source-bound evidence text embedding
     - structured task / modality / method ontology
     - typed graph neighborhood overlap
     - code / package / benchmark metadata
  -> typed graph neighborhood overlap
  -> compatibility gap analysis
  -> accept_exploratory / reject / needs_more_evidence
  -> migration_context
  -> audit
```

迁移输出永远是：

```text
MigrationHypothesis
```

不是：

```text
ScoredTool
正式推荐
benchmark-backed claim
production-ready replacement
```

### 2.2.1 Algorithm Vector Space v2

当前旧实现：

```text
scrna_tools.tsv
  -> LLM 提取 tool profile
  -> 对 LLM profile 做 embedding
  -> 每个工具一个向量
  -> 通过向量相似度探索算法迁移
```

这个设计可以作为早期探索，但不能作为可靠迁移依据。原因：

- embedding 的直接输入是 LLM 生成的二手摘要，不是原文 source span；
- LLM 可能把工具能力、算法机制、适用任务说宽；
- 单一向量会把 task、modality、algorithm mechanism、input/output、benchmark 表现混在一起；
- 向量相似不等于算法可迁移，更不等于生物学适用；
- 对大而全的 toolkit，例如 Seurat / Scanpy / scvi-tools，单向量会掩盖模块级差异。

因此 v2 不再把“工具=一个向量”当作最终形态，而是改成多视角表示：

```text
ToolRepresentationV2
  identity:
    tool_name, aliases, repository, package, version, license
  evidence_text_view:
    paper chunks, docs chunks, README chunks, benchmark chunks
    embedding_model, chunk_ids, source_span_ids
  structured_profile_view:
    tasks, modalities, inputs, outputs, assumptions
    algorithm_family, model_class, learning_paradigm
  graph_view:
    typed KG neighborhood, metapaths, task/method/data links
  empirical_view:
    benchmark metrics, datasets, rank_scope, caveats
  operational_view:
    language, installability, maintenance, runtime, hardware
  confidence:
    source_coverage, extraction_confidence, review_status
```

迁移相似度也必须拆开计算：

```text
migration_similarity =
  task_overlap
  + modality_compatibility
  + algorithm_mechanism_similarity
  + input_output_compatibility
  + graph_neighborhood_overlap
  + evidence_text_similarity
  + empirical_support
  - known_blockers
```

硬规则：

- 旧 `data/scKG_embeddings_backup.jsonl` 标记为 `legacy_algorithm_embedding`；
- legacy embedding 只能做 candidate recall / exploration；
- 不能凭 embedding similarity 直接产生 recommendation；
- 不能凭 embedding similarity 晋升 formal evidence；
- migration 输出必须带 `exploratory` 标签和 blocker/caveat；
- 对 toolkit 级工具，后续应支持 `ToolModule` / `MethodComponent` 粒度，而不是只建一个 tool vector。

当前审计入口：

```bash
python data_pipeline/audit_algorithm_vector_space.py
```

输出：

```text
data/evidence_candidates/algorithm_vector_audit.tsv
data/evidence_candidates/algorithm_vector_audit_summary.json
```

当前审计快照：

```text
scrna_tools.tsv rows: 1842
scKG_embeddings_backup.jsonl rows: 1698
catalog embedding coverage: 0.9224
embedding dim: 1024
catalog tools missing embedding: 143
embedding source status: LLM-extracted profiles only
primary quality flag: llm_profile_embedding_review_required
```

结论：

```text
旧向量空间不是废物，但只能当召回信号。
真正的算法迁移需要 source-bound representation + structured ontology + graph reasoning + empirical evidence。
```

v2 构建入口：

```bash
# 先从 PDF / source text 构建 retrieval-only evidence chunk index
python data_pipeline/build_evidence_index.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv

# 再构建 ToolRepresentationV2
python data_pipeline/build_algorithm_representations_v2.py
```

v2 输出：

```text
data/indexes/tool_representations_v2.jsonl
data/evidence_candidates/algorithm_representation_v2_audit.tsv
data/evidence_candidates/algorithm_representation_v2_summary.json
```

v2 运行时约束：

- `tool_representations_v2.jsonl` 是 migration / retrieval index，不是 formal evidence；
- `engine/isomorphism_analyzer.py` 的旧输出必须带 `legacy_embedding_only=true`、`recommendation_grade=false`、`can_rank_mcdm=false`；
- `engine/migration_hypothesis_engine.py` 可以读取 v2 representation 作为组合评分组件，但输出仍只能进入 `migration_context`；
- 如果 `dense_vector_chunk_count=0`，必须显示 `dense_embedding_missing`，不能假装 dense retrieval 已完成；
- 如果 `source_chunk_count=0`，必须显示 `low_source_coverage`，该工具只能作为低证据覆盖候选。

### 2.3 Workflow 规划闭环

workflow 目前只能算 prototype。目标路线是：

```text
tool recommendation
  -> workflow skeleton
  -> step-level evidence
  -> tool transition compatibility
  -> workflow audit
  -> plan-only workflow
  -> future sandbox execution
```

在 step-level evidence 不足前，不能声称“完整自动执行 agent”。

---

## 3. RAG / GraphRAG / KG-RAG 术语定稿

### 3.1 我们现在做的是什么 RAG

当前系统已有的是：

```text
Controlled formal evidence RAG baseline
```

具体是：

```text
formal TSV rows
  -> evidence chunks
  -> offline lexical retrieval
  -> deterministic rerank
  -> formal RAG snippets
  -> EvidenceContextPack.retrieval_context
```

代码入口：

- `engine/evidence_rag_pipeline.py`
- `engine/formal_evidence_rag.py`
- `engine/context_pack_builder.py`

当前版本已经做对了一件非常重要的事：

```text
RAG snippets 只能用于解释和溯源，不能改变 MCDM score，不能晋升证据等级。
```

### 3.2 未来应该叫什么

最准确的内部术语：

```text
Evidence-governed Hybrid KG-RAG
```

对外可以说：

```text
证据治理版 GraphRAG
或
KG-RAG for scientific tool recommendation
```

不建议只叫 `GRAG`，因为这个词不够清楚。不同人可能理解成 GraphRAG、Graph-guided RAG、Generalized RAG。我们文档里统一使用：

```text
Hybrid KG-RAG
Evidence-governed GraphRAG
```

### 3.3 和普通 RAG 的区别

普通 RAG：

```text
文档 -> chunk -> embedding/BM25 -> retrieve -> answer
```

scKG 的 KG-RAG：

```text
formal evidence / reviewed source / protocol / benchmark
  -> EvidenceChunk
  -> BM25 + dense retrieval
  -> RRF fusion
  -> governance-aware rerank
  -> evidence policy filter
  -> EvidenceContextPack
  -> audited report
```

区别在于 scKG 的 chunk 不是普通文本片段，而是带治理边界的 evidence chunk。

### 3.4 和典型 GraphRAG 的区别

很多 GraphRAG 方案强调：

- 从文档中抽实体关系；
- 构建实体图；
- 做社区发现；
- 生成 community summary；
- 查询时按图结构召回摘要。

scKG 不应该照搬这条路。我们的图谱不是自动从文档里抽出来的通用实体图，而是人工治理和 formal evidence 支撑的科研决策图谱。

scKG 的图谱更应该承担：

- Tool / Task / Modality 结构约束；
- Evidence governance；
- canonical / work_group 去重；
- benchmark / publication 关系；
- migration compatibility；
- workflow step compatibility；
- recommendation boundary。

所以 scKG 的 GraphRAG 更准确是：

```text
KG 负责结构、边界、证据等级、可推荐性；
RAG 负责原文片段、claim span、protocol、benchmark 解释；
LLM 负责组织表达；
Auditor 负责阻断 unsupported claims。
```

---

## 4. Agent 架构定稿

### 4.1 当前架构口径

当前系统不是去中心化多 Agent，也不是多个自治 agent 自由协商。

当前最准确的表述是：

```text
中心化 LangGraph 工作流
```

目标演进表述是：

```text
中心化递归 Agent（Recursive Centralized Agent）
```

含义：

```text
Trigger
  -> Gateway
  -> Parent Agent Loop
       Think -> Act -> Remember -> Reflect
       optional spawn_subagent(read-only candidate context)
  -> Parent Agent final answer / evidence gate / audit
```

Parent Agent 对最终回复、推荐排序、证据边界和 audit 负责。
Subagent 只能由 Parent 通过 tool-call spawn，且必须受深度、预算、只读权限和 evidence gate 约束。

### 4.2 为什么不再把当前系统叫“中心化多 Agent”

旧表述“中心化多 Agent / 混合型 Agent”容易造成误解，好像当前已经有多个独立 LLM agent 在协作。
实际代码形态是：

- `agent/workflow.py` 使用 LangGraph / StateGraph 编排固定节点；
- 所有节点共享 `ScKGAgentState`；
- 当前没有第二个有自主目标和长期记忆的独立 LLM agent；
- evidence policy 和 semantic auditor 是全局硬边界；
- v1 subagent contract 默认关闭，只允许 read-only candidate context。

因此当前/近期应该写成：

```text
centralized workflow now;
recursive centralized agent target;
decentralized multi-agent explicitly out of scope.
```

### 4.3 Hermes/OpenClaw-style loop engineering

scKG 借鉴 Hermes / OpenClaw 的不是“让很多 agent 热闹协商”，而是它们的递归 centralized loop：

```text
Trigger 层：接收用户问题、上传上下文、CLI/MCP 调用
Gateway 层：注入 project memory、设置预算、选择 route、建立 trace
Agent Loop：Think -> Act -> Remember -> Reflect
Learning Loop：Reflect -> private memory / skill candidate -> 下一次 Gateway 可检索
```

v1 已采用的边界：

- `TraceContext`：记录 agent run / evidence recovery / RAG / reflection；
- `ReflectionEvent`：记录一次 run 后的反思；
- `MemoryEvent`：写入私有 operational memory；
- `SkillCandidate`：只进入 review queue，不自动加载执行；
- `SubagentRequest` / `SubagentResult`：定义递归 subagent contract，但默认 disabled。

### 4.4 Remember / Reflect 权限

允许自动写入：

- 用户偏好：常用物种、平台、输出格式、strictness；
- 项目状态：最近任务、未解决 evidence gap；
- 运行教训：失败阶段、audit warning、frozen evidence warning；
- skill candidate 文件，状态必须是 `review_needed`。

不允许自动写入：

- `data/tool_publications.tsv`；
- `data/tool_benchmarks.tsv`；
- Neo4j trusted evidence；
- 正式 `skills/xxx/SKILL.md`；
- MCDM rank / main recommendation evidence。

任何 memory-derived scientific claim 必须继续走：

```text
candidate -> source span -> review -> formal TSV -> backfill -> evidence gate
```

### 4.5 Recursive subagent v1 contract

v1 默认不启用真正 subagent 执行，只定义 contract。

允许的 subagent task：

- evidence search；
- benchmark span check；
- workflow compatibility check；
- report critique。

强制约束：

- `max_depth=2`；
- `max_subagents_per_run=3`；
- `max_tool_calls_per_subagent=8`；
- subagent result 只能进入 `candidate_context`；
- subagent 不能改推荐排名、formal TSV、trusted evidence。

### 4.6 最小实现

当前最小闭环：

```text
User Query
  -> Trigger / Gateway
  -> Intent / Constraint Parser
  -> KG Retrieval
  -> Evidence Retrieval Context
  -> Evidence Gate
  -> MCDM Ranking or Migration
  -> Report Generator
  -> Auditor
  -> Reflect / Remember
  -> Trace Dashboard
```

中心治理不能丢：

- formal evidence source of truth；
- evidence gate；
- context pack layer separation；
- semantic auditor；
- eval gate；
- trace dashboard；
- private memory cannot become evidence。

---

## 5. 从 MODULAR-RAG-MCP-SERVER 拿来主义

### 5.1 它最值得学的地方

`MODULAR-RAG-MCP-SERVER` 的强项不是领域知识，而是工程闭环。

值得拿来的结构：

- DEV_SPEC 驱动开发；
- reference files 拆分；
- schedule + status tracking；
- 可插拔组件；
- Loader / Splitter / Transform / Embedding / Upsert ingestion pipeline；
- Dense + Sparse hybrid search；
- RRF fusion；
- Cross-Encoder / LLM rerank；
- TraceContext / TraceCollector；
- Streamlit dashboard；
- MCP stdio server；
- unit / integration / e2e 测试分层；
- golden set regression。

### 5.2 它的 RAG 设计怎么迁移到 scKG

通用 RAG 设计：

```text
Document
  -> Chunk
  -> ChunkRecord
  -> Dense vector
  -> Sparse vector
  -> Hybrid Search
  -> Rerank
  -> Response
```

scKG 应该改造为：

```text
ReviewedEvidenceDocument
  -> EvidenceChunk
  -> EvidenceChunkRecord
  -> Dense evidence vector
  -> Sparse evidence index
  -> Hybrid Evidence Search
  -> Governance-aware Rerank
  -> EvidenceContextPack
  -> Audited Report
```

### 5.3 可以直接借鉴的模块形态

| RAG 项目模块 | scKG 对应模块 | 是否照搬 |
| --- | --- | --- |
| `core/types.py::Document` | `EvidenceDocument` | 借鉴，不直接照搬 |
| `core/types.py::Chunk` | `EvidenceChunk` | 借鉴，不直接照搬 |
| `ChunkRecord` | `EvidenceChunkRecord` | 借鉴 |
| `BaseLoader` | `EvidenceSourceLoader` | 借鉴 |
| `PdfLoader` | `PaperPdfLoader` / `ProtocolLoader` | 直接借鉴工程模式 |
| `RecursiveSplitter` | `EvidenceAwareSplitter` | 借鉴 |
| `ChunkRefiner` | `EvidenceClaimRefiner` | 谨慎使用 |
| `MetadataEnricher` | `EvidenceMetadataNormalizer` | 借鉴，但不能升证据等级 |
| `DenseRetriever` | `DenseEvidenceRetriever` | 借鉴 |
| `SparseRetriever` | `BM25EvidenceRetriever` | 借鉴 |
| `RRFFusion` | `EvidenceRRFFusion` | 基本可借鉴 |
| `Reranker` | `GovernedEvidenceReranker` | 借鉴，需加治理权重 |
| `TraceContext` | `ScKGTraceContext` | 借鉴 |
| `MCP Server` | `scKG MCP Server` | 借鉴 |
| `Dashboard` | evidence/audit/trace dashboard | 借鉴 |

### 5.4 不能照搬的地方

不能照搬：

- 普通文档 chunk metadata；
- LLM 自动增强后直接进入推荐；
- RAG 结果直接影响最终排名；
- Ragas faithfulness 作为唯一质量指标；
- 通用 MCP `query_knowledge_hub` 直接当科研推荐工具；
- 文档删除/重摄取逻辑直接套到 formal evidence；
- 图像 caption 直接当科学证据。

scKG 的最低要求：

```text
任何 RAG 内容都必须带 claim_boundary。
任何 RAG 内容都不能绕过 evidence_policy。
任何 LLM 提取都必须默认 review_needed 或 experimental。
```

### 5.5 可插拔组件要怎么拿来

可插拔组件不是为了“显得高级”，而是为了让核心能力能替换、能测试、能降级。

通用结构：

```text
业务流程
  -> 抽象接口
  -> Factory / Registry
  -> 具体实现 A/B/C
  -> 统一返回对象
```

scKG 应该优先做这些可插拔组件：

| 组件 | 抽象接口 | 默认实现 | 可替换实现 | 为什么要可插拔 |
| --- | --- | --- | --- | --- |
| LLM | `BaseLLM` | DeepSeek/OpenAI-compatible | Azure/OpenAI/Ollama/vLLM | 降成本、换模型、离线运行 |
| Embedding | `BaseEmbedding` | BGE/SiliconFlow | OpenAI/Azure/Ollama/local sentence-transformer | 检索质量和成本可调 |
| Evidence source loader | `BaseEvidenceLoader` | formal TSV loader | Paper PDF loader, protocol loader, docs loader | 后续接论文、协议、官方文档 |
| Splitter | `BaseSplitter` | evidence-aware splitter | recursive/semantic/fixed | 不同文档结构需要不同切分 |
| Vector store | `BaseVectorStore` | Chroma/local store | Qdrant/Milvus/Neo4j vector | 本地和部署环境可切换 |
| Sparse index | `BaseSparseIndex` | BM25 | Elasticsearch/OpenSearch/SPLADE | 专有名词召回可增强 |
| Reranker | `BaseReranker` | deterministic rerank | cross-encoder/LLM rerank | 精排可逐步增强 |
| Evaluator | `BaseEvaluator` | custom governance eval | Ragas/DeepEval/expert eval | 通用 RAG 指标和科学治理指标分开 |
| KG client | `BaseGraphClient` | Neo4j + offline fallback | AuraDB/local Neo4j/read-only snapshot | 本地、服务器和云端切换 |

可插拔组件的验收标准：

- 上层 workflow 不依赖具体 provider；
- 配置集中在 `core/settings.py`；
- 单元测试使用 fake/mock provider；
- 外部服务失败时有可解释降级；
- 每个 provider 的输入输出 contract 一致；
- 不同 provider 不改变 evidence governance 规则。

对 scKG 来说，最先应该做的不是把所有 provider 都写完，而是先把接口边界定好：

```text
EvidenceLoader
EvidenceRetriever
EvidenceReranker
GraphClient
MCPTool
Evaluator
```

然后每次新增能力都挂到这些接口上，而不是在 workflow 里硬编码。

### 5.6 从 smart-appointment-ai-agent 借什么

`smart-appointment-ai-agent` 和 scKG 领域完全不同，但它有一个很值得学习的应用型 agent 架构：

```text
FastAPI / Web
  -> API Layer
  -> Agents Layer
  -> Services Layer
  -> DB / Repository Layer
```

它的 agent 组织方式是：

```text
TaskClassificationAgent
  -> AgentRouter
  -> AppointmentAgent / ConsultantAgent
  -> StateManager
  -> Services
```

值得借鉴：

- 中心任务分类器先判断 intent，再路由到专职 agent；
- `AgentRouter` 负责 handoff，不让各 agent 随意互相调用；
- `StateManager` 显式维护对话状态；
- Agent 只做流程控制，业务逻辑下沉到 service；
- model provider factory 统一管理不同模型供应商；
- API / agent / service / repository 分层清楚，利于部署和测试。

不适合照搬：

- 它是面向预约业务的会话系统，核心是流程填槽和客服；
- 它的 RAG 是普通知识库问答，不含 formal evidence governance；
- 它的 agent 之间没有科研证据审计；
- 它没有复杂工具链规划和 KG-driven tool composition。

scKG 可以吸收它的结构，但要改成：

```text
IntentRouter
  -> RecommendationAgent
  -> EvidenceAgent
  -> MigrationAgent
  -> WorkflowPlanningAgent
  -> AuditAgent
```

所有 agent 都必须通过 `ScKGAgentState` 和 `EvidenceContextPack` 交换结构化信息。

### 5.7 从 SciToolAgent 借什么

`SciToolAgent` 是 scKG 最应该重点对标的项目。它的核心不是普通聊天 agent，而是：

```text
KG-driven scientific tool planning and execution
```

它的主流程可以概括为：

```text
Question
  -> Tool KG retrieval
  -> retrieve relevant tool subgraph
  -> LLM Planner generates Plan Chain
  -> Executor calls tools in sequence
  -> Safety Checker
  -> Summarizer judges completion and produces final answer
```

关键设计：

- 用工具 KG 描述工具的 `category / functionality / input / output / source / safety`；
- 只对 `functionality` 关系建立 embedding，用于从自然语言问题召回工具；
- 通过 input / output 边扩展工具子图，寻找可衔接的工具链；
- Planner 输出显式 `Plan Chain: ['tool_A', 'tool_B']`；
- Executor 根据工具 input/output 类型生成参数并顺序调用；
- Safety checker 在工具执行前后检查风险；
- Summarizer 判断任务是否 completed；
- SciToolEval 同时评估 final answer 和 tool path。

scKG 应该直接借鉴的思想：

| SciToolAgent 设计 | scKG 对应设计 |
| --- | --- |
| Tool KG | scKG Tool / Task / Modality / Evidence KG |
| functionality embedding | tool capability / task description embedding |
| input / output edge expansion | workflow step compatibility / migration compatibility |
| Plan Chain | plan-only workflow skeleton |
| tool runner | future sandboxed execution / read-only MCP tools |
| safety checker | semantic auditor + evidence policy |
| tool path eval | recommendation path / workflow path eval |

但 scKG 不能简单照搬 SciToolAgent：

- SciToolAgent 的目标是调用科学工具完成任务，scKG 当前目标是证据治理型工具推荐；
- SciToolAgent 的 KG 主要服务工具组合，scKG 的 KG 还要服务证据等级、canonical 去重、benchmark 支撑和推荐边界；
- SciToolAgent 的 tool execution 可以直接产生结果，scKG 在 formal evidence 不足时必须输出 gap / exploratory；
- SciToolAgent 的安全检查偏化学/生物安全，scKG 的核心安全是 unsupported scientific claim 和 ranking hallucination。

scKG 的对标路线应该是：

```text
短期：KG-driven recommendation path
中期：KG-driven workflow plan path
长期：KG-driven tool execution path
```

也就是先做到“推荐什么工具、为什么推荐、证据在哪里”，再做到“这些工具如何组成 workflow”，最后才考虑“自动调用工具执行”。

#### 5.7.1 scKG-Agent 与 SciToolAgent 的核心区别

一句话判断：

```text
SciToolAgent = KG-driven scientific tool execution agent
scKG-Agent = evidence-governed single-cell tool recommendation and workflow-planning agent
```

两者都使用知识图谱，也都可以走向多工具编排，但产品目标不同。

| 维度 | SciToolAgent | scKG-Agent |
| --- | --- | --- |
| 核心目标 | 自动选择并调用科学工具，完成多步科学任务 | 在单细胞/空间组学场景下，给出证据可追踪、可审计的工具推荐、迁移建议和 workflow plan |
| 主要输出 | tool path、工具执行结果、最终答案 | ranked recommendation、evidence trace、gap report、migration rationale、workflow skeleton |
| KG 角色 | 记录工具的功能、输入、输出、安全要求，用于拼接工具链 | 记录 Tool / Task / Modality / Evidence / Benchmark / Dataset / Metric / WorkGroup，用于证据治理、硬约束过滤和推荐边界控制 |
| Agent 形态 | Planner + Executor + Summarizer，偏执行型 agent | Central StateGraph orchestrator + specialist roles，偏治理型 hybrid agent |
| 安全重点 | 工具执行安全，尤其是化学/生物安全检查 | unsupported scientific claim、ranking hallucination、formal evidence 不足时的错误推荐 |
| 评估重点 | final answer accuracy、tool path accuracy | evidence coverage、candidate leakage、recommendation correctness、audit hit rate、workflow path quality |
| 服务入口 | agent HTTP `/chat` + tool service HTTP `/run-func` | Streamlit / CLI / future MCP stdio / future FastAPI |

这意味着：SciToolAgent 是长期对标对象，但不是当前 scKG 的替代实现。我们要借它的“KG 驱动工具链规划”思想，而不是立刻把 scKG 改成全自动执行工具的系统。

#### 5.7.2 编排方式对齐

SciToolAgent 的编排更像：

```text
User question
  -> retrieve relevant tools from SciToolKG
  -> LLM Planner generates Plan Chain
  -> Executor calls tool service
  -> Safety Checker
  -> Summarizer produces answer
```

scKG 当前和目标编排应该是：

```text
User scientific intent
  -> central orchestrator
  -> constraint parser
  -> KG hard filter
  -> governed hybrid KG-RAG
  -> evidence gate
  -> MCDM scorer
  -> migration / workflow planner
  -> semantic auditor
  -> governed recommendation report
```

关键差别：

- SciToolAgent 的 Planner 可以把工具放进 Plan Chain，只要 KG 和工具服务说明它们能衔接；
- scKG 的 Planner 不能只看“能不能接上”，还必须看 formal evidence 是否足够、是否 canonical、是否符合用户任务和 modality；
- SciToolAgent 的 Executor 是主线能力，scKG 的 Executor 只能作为长期阶段，短中期必须默认 plan-only / dry-run；
- SciToolAgent 的 Summarizer 判断任务是否完成，scKG 的 Auditor 要判断回答是否被证据支持。

#### 5.7.3 Schema 不能直接照搬

SciToolAgent 的工具 KG 可以抽象成：

```text
Tool
  -> category
  -> functionality
  -> input
  -> output
  -> source
  -> safety
```

scKG 至少需要：

```text
Tool
  -> Task
  -> Modality
  -> Evidence
  -> Publication
  -> Benchmark
  -> Dataset
  -> Metric
  -> WorkGroup
  -> CanonicalTool
  -> Alias
  -> Implementation
  -> WorkflowStep
```

原因是 scKG 的核心价值不只是“工具能做什么”，而是：

- 这个工具是否真的适合用户任务；
- 证据是否来自 formal publication / benchmark；
- 是否属于 canonical tool，还是衍生实现、wrapper、过时版本；
- 推荐理由是否能落到具体 evidence record；
- 与另一个工具之间的迁移建议是否有证据，还是只能作为探索假设；
- workflow 中前后步骤是否有输入输出兼容性和领域合理性。

所以可以借 SciToolAgent 的 `functionality / input / output / safety` 四类边，但 scKG 必须保留 evidence governance schema。

#### 5.7.4 可以直接借鉴的工程模式

可以直接借鉴：

- `Plan Chain` 输出格式：用于 scKG 的 workflow skeleton，不直接等价于自动执行；
- input / output 边扩展：用于发现 workflow step compatibility 和 tool migration path；
- tool path evaluation：改造成 recommendation path / workflow path evaluation；
- separate tool service：未来把耗时工具、外部 API、sandbox execution 拆出主 agent；
- case dataset：建设 scKG 自己的 task-level evaluation set；
- retry / summarizer 思路：未来执行阶段可用于结果失败恢复和完成度判断。

暂时不能直接借鉴：

- 默认自动执行工具；
- 让 LLM 自由生成工具参数并运行；
- 只基于功能相似性做推荐；
- 把 GitHub/README/source 当成 scientific evidence；
- 在没有 evidence gate 的情况下输出“最佳工具”。

#### 5.7.5 我们自己的定位

scKG-Agent 的正确产品定位应该写死：

```text
第一阶段：evidence-governed recommender
第二阶段：KG-RAG workflow planner
第三阶段：MCP evidence and recommendation service
第四阶段：sandboxed scientific tool executor
```

与 SciToolAgent 对齐时，要遵守三条原则：

1. 先推荐，后规划，再执行。
2. 先 evidence gate，后 LLM reasoning。
3. 先本地可解释闭环，后组内服务化和云端部署。

最终可以形成互补关系：

```text
SciToolAgent-like executor
  asks scKG-Agent for evidence-grounded tool candidates
  receives ranked candidates / constraints / risks
  builds executable tool chain only after evidence approval
```

也就是说，scKG 不只是一个“小 SciToolAgent”，而是可以成为 SciToolAgent 类系统的 upstream evidence and recommendation layer。

### 5.8 MCP 对 scKG 是否必要

MCP 对 scKG 不是第一天必须，但它是从原型走向可复用科研服务的关键能力。

判断：

```text
本地 demo 阶段：MCP 非必须
组内试用阶段：MCP 很有价值
对外/长期生态阶段：MCP 应该成为标准入口之一
```

为什么需要 MCP：

- 让其他 agent 或 IDE 直接调用 scKG，不必打开 Streamlit；
- 把 scKG 推荐能力包装成标准 tool，而不是一个只能人工点网页的应用；
- 方便做只读 evidence query、tool profile、recommendation trace；
- 方便未来让 SciToolAgent 类系统把 scKG 当作 upstream evidence / recommendation service；
- 方便组内同学在自己的工作流里调用，而不是每个人重写脚本。

MCP 不应该替代所有入口。推荐入口分工：

| 入口 | 用途 |
| --- | --- |
| Streamlit | 演示、调试、非工程用户试用 |
| CLI | 批量评估、回归测试、脚本化调用 |
| MCP stdio | Claude Code / Cursor / agent 工具调用 |
| FastAPI | 组内网页、服务化、云端部署 |

所以 scKG 需要 MCP，但实现顺序应该是：

```text
先稳定核心 recommendation API
再做本地 MCP stdio read-only tools
再做组内 HTTP / Streamlit 试用
最后考虑云端和 remote MCP
```

---

## 6. scKG RAG 详细设计

### 6.1 RAG 总体目标

把当前的 lexical formal evidence RAG 升级成可扩展、可观测、可评估的 governed evidence RAG。

目标不是让 LLM “知道更多”，而是让系统：

- 找得到证据；
- 找得准证据；
- 说得清证据；
- 区分证据等级；
- 暴露缺证据；
- 阻断不被证据支持的结论。

### 6.2 RAG 数据源分层

| 数据源 | 是否可进 RAG | 是否可进推荐 | 说明 |
| --- | --- | --- | --- |
| `data/tool_publications.tsv` | 是 | 通过 gate 后可以 | formal publication evidence |
| `data/tool_benchmarks.tsv` | 是 | 通过 gate 后可以 | formal benchmark evidence |
| reviewed paper PDF | 是 | 不直接 | 用于 claim span / provenance |
| official docs / protocol | 是 | 通常不直接 | 解释和 workflow 支持 |
| `data/evidence_candidates/` | 可选 review-only | 否 | 只能进入 review / gap analysis |
| GitHub README | 可选 | 否 | 工程信息，不是科学证据 |
| user upload | 是，session-only | 否 | 只能作为用户上下文 |
| memory | 是，context-only | 否 | 不能成为科学证据 |

### 6.3 EvidenceChunk schema

已在 `engine/evidence_discovery_index.py` 固化一个证据 chunk 契约：

```text
EvidenceChunk
  chunk_id
  evidence_id
  source_kind
  source_table
  source_record_id
  tool_name
  tool_alias
  task
  modality
  species
  work_group_id
  canonical_flag
  duplicate_of
  review_status
  trust_level
  graph_layer
  recommendation_eligible
  authority_tier
  canonical_scope
  evidence_category
  audit_support_level
  doi
  pmid
  source_url
  title
  claim_text
  claim_span
  chunk_text
  claim_boundary
  use_for
  kg_version
  embedding_version
  created_at
```

### 6.4 EvidenceChunkRecord schema

```text
EvidenceChunkRecord
  chunk: EvidenceChunk
  dense_vector
  sparse_terms
  content_hash
  index_version
  embedding_provider
  embedding_model
  indexed_at
```

### 6.5 Ingestion pipeline

借鉴 RAG 项目的 ingestion pipeline，但换成 evidence ingestion：

```text
Source Loader
  -> Evidence Normalizer
  -> Evidence-aware Splitter
  -> Claim Boundary Annotator
  -> Metadata Validator
  -> Dense Encoder
  -> Sparse Encoder
  -> Upsert to vector/BM25 store
  -> Trace
```

当前已落地的最小实现：

```text
data_pipeline/build_evidence_index.py
  -> formal TSV loader
  -> EvidenceChunk builder
  -> sparse lexical index
  -> local JSONL storage
```

本地索引路径：

```text
data/indexes/evidence_chunks.jsonl
data/indexes/evidence_vectors.jsonl
```

默认只生成 chunk JSONL，不主动请求 embedding API。需要 dense index 时显式运行：

```bash
python data_pipeline/build_evidence_index.py --with-embeddings
```

阶段职责：

1. `Source Loader`
   - 读取 formal TSV；
   - 后续读取 PDF / protocol / docs；
   - 不做证据晋升。

2. `Evidence Normalizer`
   - 对齐字段；
   - 标准化 `tool_name/task/modality`；
   - 补充 `source_kind/source_record_id`。

3. `Evidence-aware Splitter`
   - formal TSV 行通常是一条 evidence chunk；
   - PDF / docs 可以按 section / paragraph 切分；
   - 不切断 claim span。

4. `Claim Boundary Annotator`
   - 明确该 chunk 能支持什么；
   - 明确不能支持什么；
   - 写入 `claim_boundary`。

5. `Metadata Validator`
   - 检查 review_status；
   - 检查 trust_level；
   - 检查 recommendation_eligible；
   - 缺字段写入 missing evidence。

6. `Dense Encoder`
   - 对 chunk text 做 embedding；
   - embedding 是 retrieval signal，不是 evidence。

7. `Sparse Encoder`
   - BM25 关键词索引；
   - 强化 DOI、工具名、任务名、benchmark 名称召回。

8. `Upsert`
   - 幂等写入；
   - `chunk_id/content_hash` 稳定；
   - 不重复索引。

重要边界：

- 原文 chunk 向量库用于 evidence discovery，不等于 formal evidence；
- dense / BM25 / RRF 召回出来的内容默认进入 `retrieval_context`；
- 只有经过人工逐条复核、带 source span / figure / table / metric 定位的事实，才能进入 formal TSV；
- AI 辅助审核只能产生 review suggestion，不能直接产生 `human_reviewed/trusted_core`；
- 对应文档切 chunk 入库是必要升级，但它解决的是“找证据”，不是自动完成“证据晋升”。

### 6.6 Retrieval pipeline

```text
Query Processor
  -> constraint-aware query expansion
  -> Dense Evidence Retrieval
  -> BM25 Evidence Retrieval
  -> RRF Fusion
  -> Metadata / Governance Filter
  -> Governance-aware Rerank
  -> retrieval_context
```

Query Processor 应使用：

- user query；
- parsed constraints；
- task aliases；
- tool aliases；
- modality aliases；
- known benchmark names；
- DOI / PMID / title hints。

Dense route 解决：

- 同义表达；
- 模糊科研意图；
- 机制相似；
- protocol 解释。

Sparse route 解决：

- 工具名；
- DOI；
- benchmark 名；
- metric 名；
- exact task；
- paper title。

RRF fusion 解决：

- dense 漏掉专有名词；
- sparse 漏掉语义同义；
- 两路分数不可比。

Governance-aware rerank 要考虑：

```text
query relevance
+ tool/task/modality match
+ source_kind priority
+ review_status priority
+ canonical priority
+ authority_tier priority
- candidate/review_needed penalty
- task mismatch penalty
```

注意：这里 rerank 的是 evidence snippets，不是 tool recommendation rank。

### 6.7 ContextPack 接入

检索结果必须进入：

```text
EvidenceContextPack.retrieval_context
```

不能直接进入：

```text
trusted_recommendation_context
```

除非该 evidence item 本身通过 `is_main_recommendation_evidence`。

ContextPack 最少应分层：

- `trusted_recommendation_context`
- `retrieval_context`
- `migration_context`
- `blocked_context`
- `missing_evidence`
- `prompt_policy`

### 6.8 RAG 测试指标

普通 RAG 指标不够，需要加 governance 指标。

检索质量：

- Hit@K；
- MRR；
- NDCG；
- source recall；
- tool recall；
- task recall。

治理质量：

- candidate leakage rate；
- retrieval item rankable violation；
- trusted non-main violation；
- missing evidence exposure rate；
- unsupported claim rate；
- context pack present rate。

报告质量：

- semantic audit pass rate；
- high/critical hallucination rate；
- unsupported tool claim rate；
- blocked report rate；
- citation coverage；
- evidence-grounded claim rate。

### 6.9 RAGAS 如何接入

RAGAS 可以用，但只能作为 scKG 的“通用 RAG 评估层”，不能替代 evidence governance。

外部参考：RAGAS 官方文档的 available metrics、Context Precision、Context Recall、Faithfulness 页面。

定位：

```text
RAGAS = generic RAG / response grounding evaluator
scKG custom eval = scientific evidence governance evaluator
```

官方 RAGAS 适合我们先用的指标：

| RAGAS 指标 | scKG 用法 | 输入字段 | 注意事项 |
| --- | --- | --- | --- |
| Context Precision | 评估 `retrieval_context` 是否把相关 evidence chunk 排在前面 | `user_input`, `reference`, `retrieved_contexts` | 适合衡量 BM25/dense/RRF/rerank 排序 |
| Context Recall | 评估重要 reference claims 是否被检索上下文覆盖 | `user_input`, `reference`, `retrieved_contexts` | 需要 gold answer 或 gold evidence claims |
| Faithfulness | 评估最终回答中的 claims 是否被 retrieved context 支持 | `response`, `retrieved_contexts` | 只能评估“是否被上下文支持”，不能判断 evidence 是否有资格推荐 |
| Response Relevancy | 评估回答是否回应用户问题 | `user_input`, `response` | 适合作为 report quality 辅助指标 |
| Context Utilization | 无 reference 时评估 response 是否真正使用了 retrieved context | `response`, `retrieved_contexts` | 可用于早期 smoke，但不如有 gold 的评估硬 |
| Tool Call Accuracy / Tool Call F1 | 长期执行阶段评估工具调用 | agent trajectory / tool call labels | 当前 plan-only 阶段暂不作为主指标 |

RAGAS 最适合先回答这三个问题：

```text
检索到的 evidence chunk 是否相关？
该检索是否漏掉 gold evidence？
生成报告是否忠实于 retrieval_context？
```

但它不能回答这些 scKG 关键问题：

```text
这个 evidence 是否 formal reviewed？
这个 evidence 是否 recommendation_eligible？
这个工具是否 canonical？
这个 benchmark 是否适配当前 task/modality？
RAG snippet 有没有越权进入 ranking？
LLM 有没有把 exploratory signal 说成 formal conclusion？
```

因此 scKG 的评估应该是双层：

```text
Layer 1: RAGAS generic RAG metrics
  -> context precision / context recall / faithfulness / relevancy

Layer 2: scKG governance metrics
  -> candidate leakage / trusted non-main violation / unsupported scientific claim
  -> recommendation evidence coverage / citation coverage / blocked report correctness
```

建议新增适配脚本：

```text
eval/run_ragas_eval.py
```

它不直接调用生产 workflow，而是读取现有 prediction / trace artifact：

```text
prediction JSONL
  -> user_input = query
  -> response = final_report
  -> retrieved_contexts = EvidenceContextPack.retrieval_context[*].text
  -> reference = gold answer / gold evidence rationale
  -> reference_context_ids = gold evidence ids
  -> retrieved_context_ids = retrieved evidence ids
```

优先实现顺序：

1. 先做 ID-based context precision / recall：基于 `evidence_id`，不依赖 evaluator LLM，便宜且稳定；
2. 再做 LLM-based Context Precision / Recall：用于判断语义相关性；
3. 再做 Faithfulness：检查 final report 是否忠实于 retrieved context；
4. 最后再考虑 RAGAS agent/tool-use 指标，用于 future executor。

验收标准：

- RAGAS 结果必须和 scKG custom eval 分开输出；
- RAGAS 低分可以阻断发布；
- RAGAS 高分不能绕过 evidence gate；
- RAGAS evaluator LLM 的模型、温度、版本必须记录进 eval artifact；
- RAGAS API 版本变化较快，脚本要集中封装，不能散落在业务代码里；
- 没有 reference 的样本只能用于 smoke，不能作为正式回归结论。

短期推荐阈值：

| 指标 | 目标 |
| --- | --- |
| ID-based context recall | >= 0.85 |
| ID-based context precision | >= 0.75 |
| LLM context precision | >= 0.75 |
| LLM context recall | >= 0.80 |
| Faithfulness | >= 0.90 |
| candidate leakage rate | 0 |
| trusted non-main violation | 0 |

如果 RAGAS 指标与 scKG 指标冲突，以 scKG governance 为准。

---

## 7. Knowledge Graph 设计

### 7.1 KG 的职责

KG 负责结构化、边界化、可治理的知识。

KG 应回答：

- 哪个工具做什么任务；
- 支持什么模态；
- 哪些 evidence 支持它；
- publication 是否 canonical；
- benchmark 对应什么 task/dataset/metric；
- 哪些证据可推荐，哪些只能检索；
- migration 是否结构上可行；
- workflow step 是否兼容。

KG 不负责：

- 生成自然语言答案；
- 把候选证据自动变成事实；
- 替代 formal TSV；
- 让弱证据进入强推荐。

### 7.2 核心节点

优先建设：

```text
Tool
Task
Modality
Evidence
PublicationWork
BenchmarkEvidence
Dataset
Metric
Protocol
Workflow
WorkflowStep
MigrationHypothesis
RecommendationRun
GovernanceEvent
```

### 7.3 核心关系

```text
(Tool)-[:PERFORMS_TASK]->(Task)
(Tool)-[:SUPPORTS_MODALITY]->(Modality)
(Tool)-[:SUPPORTED_BY]->(Evidence)
(Tool)-[:EVALUATED_IN]->(BenchmarkEvidence)
(Evidence)-[:BELONGS_TO_WORK]->(PublicationWork)
(BenchmarkEvidence)-[:EVALUATES_TASK]->(Task)
(BenchmarkEvidence)-[:USES_DATASET]->(Dataset)
(BenchmarkEvidence)-[:USES_METRIC]->(Metric)
(BenchmarkEvidence)-[:DERIVED_FROM]->(PublicationWork)
(Workflow)-[:HAS_STEP]->(WorkflowStep)
(WorkflowStep)-[:USES_TOOL]->(Tool)
(MigrationHypothesis)-[:SOURCE_TOOL]->(Tool)
(MigrationHypothesis)-[:TARGET_TASK]->(Task)
(RecommendationRun)-[:USED_EVIDENCE]->(Evidence)
(RecommendationRun)-[:RECOMMENDED]->(Tool)
```

### 7.4 Neo4j 的地位

Neo4j 是：

```text
runtime serving graph
```

不是：

```text
formal evidence source of truth
```

source of truth 仍然是：

```text
data/tool_publications.tsv
data/tool_benchmarks.tsv
core/evidence_schemas.py
human review decisions
```

所有 Neo4j 写入脚本必须：

- 可 dry-run；
- 可重复运行；
- 不产生重复节点；
- 不写 candidate evidence；
- 输出 inventory diff；
- 能从 formal TSV 复现。

### 7.5 图结构如何用于推荐

我们使用 GraphRAG / KG-RAG 的根本原因，不只是为了“把图谱展示出来”，而是利用图结构发现工具、任务、证据、算法、数据集之间的关系，从而让推荐更有结构性。

可以分三层实现。

第一层：硬约束过滤。

```text
Tool --PERFORMS_TASK--> Task
Tool --SUPPORTS_MODALITY--> Modality
Tool --OPERATES_ON--> DataObject
Tool --REQUIRES_HARDWARE--> Hardware
```

用途：

- 排除不支持目标 task/modality 的工具；
- 找到同一 task family 下候选工具；
- 在用户约束不足时提出 clarification question。

第二层：证据加权推荐。

```text
Tool --SUPPORTED_BY--> Evidence
Evidence --BELONGS_TO_WORK--> PublicationWork
Tool --EVALUATED_IN--> BenchmarkEvidence
BenchmarkEvidence --USES_DATASET--> Dataset
BenchmarkEvidence --USES_METRIC--> Metric
```

用途：

- 计算某工具是否有主推荐证据；
- 去掉重复 publication work 带来的虚高；
- 按 task-local benchmark 支持度加权；
- 暴露缺 publication、benchmark、protocol 的位置。

第三层：关系发现和迁移假设。

```text
Tool --IMPLEMENTS_ALGORITHM--> Algorithm
Algorithm --HAS_OBJECTIVE--> Objective
Algorithm --USES_REPRESENTATION--> Representation
Algorithm --HAS_INPUT_SIGNATURE--> InputSignature
Algorithm --HAS_OUTPUT_SIGNATURE--> OutputSignature
Tool --SIMILAR_TO / SHARES_MECHANISM_WITH--> Tool
```

用途：

- 找“同任务不同机制”的备选工具；
- 找“不同任务同机制”的可迁移方法；
- 用 typed neighborhood Jaccard 衡量结构相似；
- 用路径解释推荐原因，例如：

```text
用户要 Data Integration
  -> Harmony / scVI / Seurat 都 PERFORMS_TASK Data Integration
  -> scVI 有 VAE latent model 机制
  -> Harmony 有 embedding-level batch correction 机制
  -> Seurat 有 anchor/RPCA/WNN 机制
  -> benchmark evidence 和 publication evidence 决定主推荐强度
```

图推荐不能只依赖 shortest path 或 embedding similarity。推荐排序应该是：

```text
graph candidate recall
  + formal evidence gate
  + MCDM score
  + governed RAG provenance
  + semantic audit
```

可探索的图算法：

- typed path expansion；
- metapath-based candidate recall；
- neighborhood overlap / Jaccard；
- Personalized PageRank 作为召回信号；
- graph embedding 作为召回信号；
- GNN 作为未来关系预测。

但这些都只能是 retrieval / recall / exploratory signal，不能绕过 formal evidence gate。

---

## 8. Evidence Governance 规约

### 8.1 三层证据

| 层级 | 含义 | 可用于推荐 |
| --- | --- | --- |
| `trusted_core` | 人工审核或正式证据 | 可以，但仍需过 gate |
| `review_needed` | 候选、半结构化、待审 | 不可以 |
| `experimental` | LLM 抽取、embedding、迁移假设 | 不可以 |

### 8.2 formal evidence

正式证据表：

- `data/tool_publications.tsv`
- `data/tool_benchmarks.tsv`

字段顺序必须跟：

- `core/evidence_schemas.py`

保持一致。

### 8.3 approved review status

可进入 formal 层的状态：

```text
reviewed
verified
human_reviewed
```

不可进入推荐路径：

```text
pending
review_needed
rejected
deprecated
unreviewed
auto_checked
```

### 8.4 Publication 证据 gate

主推荐 publication evidence 必须满足：

```text
recommendation_eligible = true
graph_layer = trusted_core
source_type = paper
canonical_scope in {core_tool, major_version}
evidence_category = architectural_core
authority_tier in {canonical_primary, canonical_secondary}
review_status approved
source identifier and URL available
claim_text or source span beyond title
reviewer identity clear
```

当前 runtime gate 已固化：

```text
paper_support   -> can be main publication evidence only if audit gate passes
paper_citations -> retrieval / ranking signal only; cannot admit a tool into main recommendation
citations       -> cannot be main publication evidence
```

也就是说，publication evidence 可以证明“某工具可能有主论文/核心论文”，但不能因为 Crossref 命中、引用量高、或 `human_reviewed` 字段存在，就自动变成主推荐硬证据。当前 `tool_publications.tsv` 中 `claim_span` 基本等于论文标题，`reviewed_by=human_review` 也过于泛化，所以运行时先降为 retrieval-only。

formal publication 审计入口：

```bash
python eval/audit_formal_publication_evidence.py \
  --json-summary data/evidence_candidates/formal_publication_audit_summary.json
```

输出：

```text
data/evidence_candidates/formal_publication_audit.tsv
data/evidence_candidates/formal_publication_audit_summary.json
```

### 8.5 Benchmark 证据 gate

主推荐 benchmark evidence 必须满足：

```text
graph_layer = trusted_core
source_type = benchmark
review_status approved
metric / rank / score / normalized_score source-bound
numeric result available
task scope clear
tool scope clear
```

定性 benchmark 结论的规则：

```text
result_text-only benchmark = retrieval / caveat / explanation only
result_text-only benchmark != main recommendation evidence
```

也就是说，可以保留 qualitative result，但不能让它支撑主推荐或 top-k admit。只有一句 “top-tier / strong / competitive / high performance” 但没有表格、排名、分数、metric 定义和可定位 source span 的记录，必须降级为 retrieval-only 或 review-needed。

当前 runtime gate 已固化：

```text
benchmark_result -> retrieval / caveat / explanation only
benchmark_rank   -> can be main benchmark evidence if gate passes
benchmark_score  -> can be main benchmark evidence if gate passes
```

MCDM 不读取 `benchmark_result` 作为 benchmark component；semantic auditor 也不会把 `benchmark_result` 视为 benchmark claim 的充分证据。

formal benchmark 审计入口：

```bash
python eval/audit_formal_benchmark_evidence.py \
  --json-summary data/evidence_candidates/formal_benchmark_audit_summary.json
```

输出：

```text
data/evidence_candidates/formal_benchmark_audit.tsv
data/evidence_candidates/formal_benchmark_audit_summary.json
```

后续 formal benchmark 晋升必须记录：

- 原文文档来源；
- figure/table/section 定位；
- metric 名称；
- rank/score/normalized_score 至少一个；
- n_tools_compared 或清晰 rank_scope；
- task/modality/dataset scope；
- reviewer_notes 中说明是否为 third-party benchmark、self-reported benchmark、negative-control/caveat evidence。

### 8.6 Candidate evidence

`data/evidence_candidates/` 只能用于：

- candidate crawl；
- dedup；
- work group proposal；
- review packet；
- gap analysis；
- audit report。

不能直接用于：

- final recommendation；
- MCDM score；
- formal TSV；
- Neo4j trusted node；
- report strong claim。

---

## 8A. Evidence Recovery Sprint v1

目标：从“冻结不可靠 formal TSV”进入“可复核证据恢复”，建立：

```text
audit TSV
  -> evidence_review_packet_v1
  -> source manifest / original text chunks
  -> auto prefill
  -> AI-assisted evidence review
  -> optional human confirmation
  -> recovered formal TSV promotion
  -> gate / smoke validation
```

第一批默认只处理 10 个核心工具：

```text
Seurat
Scanpy
Harmony
scvi-tools
CellTypist
SingleR
cell2location
scVelo
CellRank
Scrublet
```

### 8A.0 Spec-driven execution

本阶段必须按 spec 主入口执行，不再手动散跑脚本作为常规流程。

安全默认入口：

```bash
python data_pipeline/run_evidence_recovery_workflow.py
```

该命令按顺序执行：

```text
publication audit
  -> benchmark audit
  -> review packet
  -> source manifest
  -> source fetch dry-run
  -> evidence chunk index
  -> review packet prefill
  -> optional AI-assisted evidence review
  -> promotion dry-run
  -> conservative smoke
```

输出：

```text
data/evidence_candidates/evidence_recovery_workflow_summary.json
```

如果需要真实抓取 open HTML / text 来源，必须显式：

```bash
python data_pipeline/run_evidence_recovery_workflow.py \
  --fetch-mode live \
  --fetch-limit 3
```

如果需要让 AI 帮忙审查已经抓到的 source span，必须显式：

```bash
python data_pipeline/run_evidence_recovery_workflow.py \
  --fetch-mode none \
  --ai-review-mode live \
  --ai-review-limit 3
```

AI review 只生成审查建议，不是 formal promotion 输入，不会自动把 `promotion_ready` 改成 `true`。

执行后必须反向维护本 spec：

- 如果新增脚本入口，写入本节；
- 如果修改 gate 条件，更新 8.4 / 8.5；
- 如果 smoke 验收变化，更新 8A.5；
- 英文 spec 暂不跟随修改。

### 8A.1 Review packet

生成入口：

```bash
python data_pipeline/build_evidence_recovery_review_packet.py
```

常规流程中不直接运行该命令，而由 `run_evidence_recovery_workflow.py` 调用。

输出：

```text
data/evidence_candidates/evidence_review_packet_v1.tsv
data/evidence_candidates/evidence_review_packet_v1_summary.json
```

review packet 不是要求研究者直接读懂全部论文，而是记录 evidence recovery 需要补齐的字段。

publication 行最终晋升前必须补齐：

- `decision`
- `reviewed_by`
- `source_span`
- `claim_text`
- `verified_task`
- `verified_modality`
- `canonical_scope`
- `authority_tier`
- `recommendation_eligible`

benchmark 行最终晋升前必须补齐：

- `decision`
- `reviewed_by`
- `source_span`
- `metric`
- `rank` / `score` / `normalized_score` 至少一个
- `rank_scope` / `n_tools_compared` 至少一个
- `verified_task`
- `verified_modality`
- `caveat_type`

默认 reviewer 不能再写泛化 `human_review`，必须写可追踪值，例如：

```text
lris_manual_2026_06
```

AI 可以辅助完成第一轮证据审查，但 AI reviewer 不能写入 `reviewed_by` 并作为 formal promotion 的依据。
例如 `ai_assisted_deepseek_2026_06`、`openai_review`、`llm_review` 都只能保存在 AI suggestion 字段中，不能冒充 human review。

### 8A.2 Source manifest and chunks

生成 source manifest：

```bash
python data_pipeline/build_evidence_source_manifest.py
```

常规流程中不直接运行该命令，而由 `run_evidence_recovery_workflow.py` 调用。

输出：

```text
data/evidence_candidates/evidence_source_manifest_v1.tsv
data/evidence_candidates/evidence_source_manifest_v1_summary.json
```

该 manifest 只记录 DOI/source URL、建议本地文本路径和 fetch 状态，不自动晋升 evidence。

自动抓取 open HTML / text 来源：

```bash
python data_pipeline/fetch_evidence_sources.py --dry-run
python data_pipeline/fetch_evidence_sources.py --limit 3
```

常规流程中优先通过：

```bash
python data_pipeline/run_evidence_recovery_workflow.py --fetch-mode dry-run
python data_pipeline/run_evidence_recovery_workflow.py --fetch-mode live --fetch-limit 3
```

约束：

- 默认优先 DOI landing / open HTML / text；
- PDF 解析不是默认路径；
- 抓取结果只保存到 `data/evidence_sources/text/*.txt`；
- 抓取成功也不代表 evidence 可晋升。

如果已经把原文文本放到 `local_text_path`，可重新构建 evidence chunk index：

```bash
python data_pipeline/build_evidence_index.py \
  --source-manifest data/evidence_candidates/evidence_source_manifest_v1.tsv
```

source chunk 仍然只能用于 evidence discovery，不得直接改 MCDM rank。

基于 source chunks 预填 review packet：

```bash
python data_pipeline/prefill_evidence_review_packet.py
```

常规流程中不直接运行该命令，而由 `run_evidence_recovery_workflow.py` 调用。

输出：

```text
data/evidence_candidates/evidence_review_packet_v1_prefilled.tsv
data/evidence_candidates/evidence_review_packet_v1_prefill_summary.json
```

预填规则：

- 自动填 `source_span` / `claim_text` 候选；
- benchmark 只做保守 rank/score 正则提示；
- 不设置 `promotion_ready=true`；
- 不覆盖原始 `evidence_review_packet_v1.tsv`。

### 8A.2.1 可见样例：Doublet Detection Evidence Recovery Demo

为了让 Evidence Recovery 不停留在抽象流程，当前保留一个可见样例任务：

```text
task = Doublet Detection
modality = scRNA-seq
target_tools = Scrublet, DoubletFinder
```

入口：

```bash
# 只读本地已有 source text / metadata，生成 demo artifact
python data_pipeline/build_doublet_recovery_demo.py

# 尝试抓取 DOI landing / Crossref metadata fallback
python data_pipeline/build_doublet_recovery_demo.py --fetch-live
```

输出：

```text
data/evidence_candidates/doublet_detection_recovery_demo.json
data/evidence_candidates/doublet_detection_recovery_demo.tsv
data/evidence_candidates/doublet_detection_source_manifest.tsv
data/evidence_sources/text/*DoubletFinder*.txt
data/evidence_sources/text/*Scrublet*.txt
```

PDF 全文恢复入口：

```bash
# 1. 建立 PDF 存放目录
mkdir -p data/evidence_sources/pdfs

# 2A. 如果已经有 PDF，推荐文件名
data/evidence_sources/pdfs/Scrublet_CAND_PUB_Scrublet_137a56b00546.pdf
data/evidence_sources/pdfs/DoubletFinder_CAND_PUB_DoubletFinder_03be3bc27cea.pdf
data/evidence_sources/pdfs/Scrublet_HR_BMK_Scrublet_doublet_detection_2020.pdf
data/evidence_sources/pdfs/DoubletFinder_HR_BMK_DoubletFinder_doublet_detection_2020.pdf

# 2B. 如果还没有 PDF，先做开放 PDF discovery dry-run
python data_pipeline/download_evidence_pdfs.py --limit 4

# 2C. 确认候选 URL 合理后，再下载开放 PDF
python data_pipeline/download_evidence_pdfs.py --live --limit 4

# 可选：用 Unpaywall 增强开放获取检索，需要自己的邮箱
UNPAYWALL_EMAIL=your_email@example.com python data_pipeline/download_evidence_pdfs.py --live --limit 4

# 2D. 全量 source manifest 的开放 PDF discovery / download
python data_pipeline/download_evidence_pdfs.py \
  --source-manifest data/evidence_candidates/evidence_source_manifest_v1.tsv \
  --summary-output data/evidence_candidates/evidence_pdf_download_full_summary.json

python data_pipeline/download_evidence_pdfs.py \
  --source-manifest data/evidence_candidates/evidence_source_manifest_v1.tsv \
  --summary-output data/evidence_candidates/evidence_pdf_download_full_summary.json \
  --live

# 2E. 根据自动下载结果生成手动下载清单
# 注意：这是原始下载建议清单，不是当前最终 unresolved queue。
# 当前最终状态以 build_literature_source_coverage.py 生成的
# core_literature_manual_download_queue.md 为准；该文件现在是 resolution queue，
# 不是“还需要下载所有条目”的意思。
python data_pipeline/build_pdf_download_checklist.py

# 3. 抽取 PDF 文本到 retrieval-only source text
python data_pipeline/ingest_evidence_pdfs.py --overwrite

# 全量 manifest 抽取入口
python data_pipeline/ingest_evidence_pdfs.py \
  --source-manifest data/evidence_candidates/evidence_source_manifest_v1.tsv \
  --output-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --summary-output data/evidence_candidates/evidence_pdf_ingest_full_summary.json \
  --overwrite

# 4. 刷新 demo artifact
python data_pipeline/build_doublet_recovery_demo.py
```

说明：

- 第 3 和第 4 个 benchmark PDF 可以是同一篇 benchmark 论文的两个副本，也可以只放一个包含 DOI/title/record_id 的 PDF 文件；脚本会按 record_id、DOI、title、tool name 做保守匹配。
- `download_evidence_pdfs.py` 只下载开放 PDF / 直接 PDF URL / Crossref 或 Unpaywall 返回的 OA PDF；不绕过付费墙，不使用 Sci-Hub，不自动登录学校代理。
- 默认运行是 dry-run，只写 `data/evidence_candidates/evidence_pdf_download_summary.json`，用于审查候选 URL；加 `--live` 才真正写入 `data/evidence_sources/pdfs/`。
- 全量下载结果写到 `data/evidence_candidates/evidence_pdf_download_full_summary.json`；人工补充清单写到 `data/evidence_candidates/pdf_manual_download_checklist.md` 和 `data/evidence_candidates/pdf_manual_download_checklist.tsv`。
- 当前保守策略：主文 evidence 只接受 primary article PDF；`MOESM` / `MediaObjects` / `supplement` / `supplementary` 等 supplement PDF 不能写到主文 PDF 文件名下。
- 如果脚本曾误下 supplement，必须移入 `data/evidence_sources/pdfs/quarantine_supplement_misdownloads/`，不得进入 PDF ingest。
- 当前本地环境需要 `pypdf` 或系统 `pdftotext` 才能解析 PDF；`requirements.txt` 已加入 `pypdf>=5.0.0`。
- PDF 抽取文本会写到 `data/evidence_sources/text/*.txt`，仍然只是 evidence discovery，不会自动写 formal TSV。
- Dashboard `Evidence & RAG -> PDF Download Status` 会显示 attempted、candidate、downloaded、errors、selected PDF URL。
- Dashboard `Evidence & RAG -> PDF Ingestion Status` 会显示 PDF files、matched rows、extracted rows、extractor、suggested filenames。

当前全量 PDF 下载状态快照：

```text
source rows: 23
source_text_available: 19
pdf_extraction_failed_use_alternate_text_or_repair: 2
resolve_wrong_doi_or_replace_source: 2
quarantined supplement misdownloads: 4
full PDF ingest extracted rows: 19
full PDF ingest unresolved rows: 4
```

解释：

- `already_downloaded`：本地已经有主文 PDF，可以进入 PDF text ingestion；
- `manual_download_or_browser_login`：脚本发现了主文 PDF URL，但 publisher 拒绝脚本下载或需要浏览器会话；可手动打开 DOI / selected PDF URL 下载；
- `manual_search_required`：Crossref / DOI landing page 没暴露主文 PDF URL，需要按标题/DOI 人工搜索，或使用合法机构权限；
- `pdf_extraction_failed_use_alternate_text_or_repair`：PDF 文件已经存在，但当前 extractor 没抽出文本；不要重复下载同一个 PDF，优先换 extractor、找 HTML/full text 或换一份可抽取 PDF；
- `resolve_wrong_doi_or_replace_source`：脚本发现的 DOI/PDF 与当前 evidence title 不匹配，不能下载使用，必须先修正 DOI/source 或替换 benchmark source；
- 即使 PDF 成功入库，也只是 source chunk / evidence discovery，不能自动晋升 formal TSV。
- PDF ingest 匹配必须保守：文件名必须命中 `record_id`、建议文件名或 DOI；不能只因为 tool name 相同就匹配，否则会把 benchmark PDF 误当 publication PDF。

Dashboard `Evidence & RAG` 页面会展示该样例：

- latest Neo4j KG gate snapshot；
- Scrublet / DoubletFinder 的 formal evidence blocker；
- publication / benchmark 当前为何 `runtime_recommendation_allowed=false`；
- DOI/Crossref metadata/source chunk 检索结果；
- 下一步是找全文 section / figure / table / source span，还是补 numeric rank/score。

当前样例的边界：

- Crossref metadata fallback 只能作为 evidence discovery text；
- metadata-only source 不能视为全文 source span；
- source chunk 不能改变 MCDM rank；
- demo 不写 formal TSV、不写 Neo4j、不修改推荐排序。

### 8A.3 AI-assisted evidence review

现实约束：项目负责人不一定有能力逐篇 paper 判断 evidence 是否成立，因此本阶段允许 AI 做第一轮 evidence review。

入口：

```bash
python data_pipeline/ai_review_evidence_packet.py --mode dry-run
python data_pipeline/ai_review_evidence_packet.py --mode live --limit 3
```

常规 workflow 入口：

```bash
python data_pipeline/run_evidence_recovery_workflow.py \
  --fetch-mode none \
  --ai-review-mode dry-run

python data_pipeline/run_evidence_recovery_workflow.py \
  --fetch-mode none \
  --ai-review-mode live \
  --ai-review-limit 3
```

输入：

```text
data/evidence_candidates/evidence_review_packet_v1_prefilled.tsv
```

输出：

```text
data/evidence_candidates/evidence_review_packet_v1_ai_reviewed.tsv
data/evidence_candidates/evidence_review_packet_v1_ai_review_summary.json
data/evidence_candidates/evidence_review_packet_v1_ai_review_report.md
```

AI review 负责：

- 判断 source span 是否真的支撑 publication / benchmark claim；
- 生成可读的 `ai_rationale`；
- 对 benchmark 提示可能的 metric / rank / score / rank scope；
- 列出 `ai_missing_for_promotion`；
- 给出 `keep_retrieval_only` / `needs_human_confirmation` / `reject` 建议。

AI review 不允许：

- 写入 formal TSV；
- 自动设置 `promotion_ready=true`；
- 把 `benchmark_result` 变成 main benchmark evidence；
- 把 AI reviewer 冒充为 `human_reviewed/trusted_core`。

如果没有 human confirmation，则 AI review 后的证据状态是：

```text
model-reviewed / retrieval-only / review-needed
```

这并不浪费，因为它已经能服务于：

- 论文/手册中的可解释 evidence report；
- 推荐结果旁边的 warning / missing evidence；
- 下一轮人工或组内复核的低门槛任务包。

### 8A.4 Recovered promotion

promotion 默认 dry-run：

```bash
python data_pipeline/promote_recovered_evidence.py
```

常规流程中不直接运行该命令，而由 `run_evidence_recovery_workflow.py` 调用。

真正写入 formal TSV 必须显式：

```bash
python data_pipeline/promote_recovered_evidence.py --apply
```

publication 晋升条件：

- `promotion_ready=true`
- `decision=promote`
- reviewer 可追踪；
- `source_span` 不能只是 title；
- `claim_text` 非空；
- `verified_task` / `verified_modality` 非空；
- recommendation metadata 与 canonical scope 一致。

benchmark 晋升条件：

- `promotion_ready=true`
- `decision=promote`
- reviewer 可追踪；
- `source_span` 和 `metric` 非空；
- `rank` / `score` / `normalized_score` 至少一个；
- `rank_scope` / `n_tools_compared` 至少一个；
- `caveat_type` 不是 caveat / negative-control。
- reviewer 不能是 AI-assisted / OpenAI / DeepSeek / LLM / model review 标记。

### 8A.5 Conservative smoke

验证入口：

```bash
python eval/run_evidence_recovery_smoke.py
```

常规流程中不直接运行该命令，而由 `run_evidence_recovery_workflow.py` 调用。

验收：

- 当前冻结态下 publication / benchmark 的 `runtime_recommendation_allowed = 0`；
- frozen publication/benchmark 不能进入 main evidence gate；
- RAG snippets 必须带 retrieval-only / manual-review boundary；
- 5 条 gold query 能输出可检查 retrieval summary。

---

## 8B. Algorithm Representation v2 与 Source Coverage Sprint v2.1

### 8B.1 为什么要做 v2

旧版本的“每个工具一个 LLM-profile embedding”只能作为探索性 recall signal，不能作为算法迁移、推荐排序或证据晋升的核心依据。

原因：

- 向量来自模型总结，source span 不稳定；
- 一个大 toolkit 被压成一个向量，无法表达模块差异；
- 不能解释相似度到底来自任务、输入输出、算法机制、图邻域还是 benchmark；
- 无法审计“这个相似是从哪段原文来的”。

v2 的目标是把工具表示拆成可解释视图：

```text
ToolRepresentationV2
  -> source-bound text view
  -> structured task / modality / input / output / method profile
  -> typed KG neighborhood view
  -> empirical benchmark / publication view
  -> operational GitHub / package metadata view
  -> confidence / quality flags
  -> legacy embedding status
```

迁移相似度只能进入：

```text
migration_context
```

不能进入：

```text
main recommendation evidence
formal evidence promotion
MCDM rank
```

### 8B.2 Source Coverage Sprint v2.1 已落地流程

第一阶段不追求 1800+ 工具全量覆盖，先覆盖核心工具：

```text
Seurat
Scanpy
Harmony
scvi-tools
CellTypist
SingleR
cell2location
scVelo
CellRank
Scrublet
DoubletFinder
MIMOSCA
tradeSeq
MOFA2
moscot
wot
```

生成核心工具 source manifest：

```bash
python data_pipeline/build_core_tool_source_manifest.py
```

输出：

```text
data/evidence_candidates/core_tool_source_manifest_v2.tsv
data/evidence_candidates/core_tool_source_manifest_v2_summary.json
```

当前 manifest 同时包含：

```text
16 个 GitHub README source row
2 个 official docs fallback row: MOFA2, wot
```

抓取 GitHub README 正文：

```bash
python data_pipeline/fetch_evidence_sources.py \
  --manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv \
  --summary-output data/evidence_candidates/core_tool_source_fetch_summary.json \
  --timeout 20 \
  --refresh
```

说明：

- 该步骤需要访问 GitHub；
- GitHub README 只是 source-bound retrieval chunk；
- README chunk 不能自动晋升 formal TSV；
- README chunk 不能直接改变推荐排序。

重建 evidence chunk index：

```bash
python data_pipeline/build_evidence_index.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv
```

重建 Algorithm Representation v2：

```bash
python data_pipeline/build_algorithm_representations_v2.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv
```

验证：

```bash
python -m pytest
python eval/run_evidence_recovery_smoke.py
python eval/run_observability_acceptance.py
```

### 8B.3 2026-07-04 本地快照

当前已生成：

```text
core source manifest rows: 18
GitHub README fetched: 14
official docs fallback fetched: 2
GitHub README empty/too short: 2
blocked/low coverage core tools: 0

evidence_chunks.jsonl total chunks: 565
source manifest chunks: 523
PDF/HTML source chunks: 197
core README/docs source chunks: 326
dense vectors: 0

ToolRepresentationV2 records: 1834
tools_with_source_chunks: 16
tools_without_source_chunks: 1818
tools_with_dense_vectors: 0
```

核心工具覆盖情况：

```text
source_bound_profile:
  Seurat, Scanpy, Harmony, scvi-tools, CellTypist, SingleR,
  cell2location, scVelo, CellRank, Scrublet, DoubletFinder,
  MIMOSCA, tradeSeq, MOFA2, moscot, wot
```

当前测试结果：

```text
pytest: 16 passed
evidence recovery smoke: passed
observability acceptance: ok=true
```

重要边界：

- `dense_embedding_missing` 仍然是预期状态，因为还没有主动调用 embedding API；
- 旧 `scKG_embeddings_backup.jsonl` 仍保留，但只允许 candidate recall、可视化和聚类探索；
- source chunk 可以改善 migration retrieval 和 evidence discovery；
- source chunk 不能绕过 formal evidence gate。

### 8B.4 下一步

下一步不是立刻做 GNN 或云部署，而是继续提高 source-bound coverage：

1. 给 16 个已覆盖核心工具继续补 paper/protocol/benchmark PDF；
2. 为 `MOFA2` 和 `wot` 后续补更细粒度 tutorial / method page，当前 official docs homepage 只解决第一层 source coverage；
3. 为核心工具补结构化 `tool_algorithm_profiles.tsv`，减少 `structured_profile_missing`；
4. 在确认 embedding API、成本和缓存策略后，再运行 `build_evidence_index.py --with-embeddings`；
5. 继续扩展 Dashboard 的 Evidence & RAG coverage view，加入 paper/protocol/benchmark source coverage。

验收标准：

- 核心 16 工具 source-bound coverage 达到 16/16；
- source chunk 仍然只进入 retrieval / migration context；
- frozen publication / benchmark 仍然不能进入 main recommendation；
- migration 输出必须带 exploratory 和 caveat；
- dense embedding 重建后必须输出模型名、chunk count、vector count 和失败行。

---

## 8C. Paper / Benchmark Source Coverage Sprint v2.2

### 8C.1 为什么 v2.1 之后还要做 v2.2

README / docs homepage 只能证明工具存在、基本用途和工程入口，不足以恢复 publication / benchmark formal evidence。

真正能恢复强证据的来源仍然是：

```text
method paper
benchmark paper
protocol / tutorial
figure / table / section / paragraph span
```

因此 v2.2 的目标是：

```text
paper / benchmark DOI rows
  -> PDF / HTML source text acquisition
  -> source text quality check
  -> retrieval-only chunk
  -> review packet prefill
  -> human/model-assisted review
  -> formal TSV promotion only after gate
```

### 8C.2 已落地 artifacts

生成 literature source coverage：

```bash
python data_pipeline/build_literature_source_coverage.py
```

输出：

```text
data/evidence_candidates/core_literature_source_coverage.tsv
data/evidence_candidates/core_literature_source_coverage_summary.json
data/evidence_candidates/core_literature_manual_download_queue.md
```

Dashboard 页面：

```text
Evidence & RAG -> Paper / Benchmark Source Coverage
```

### 8C.3 2026-07-04 本地快照

当前 paper / benchmark source rows：

```text
rows: 23
source_text_available: 19
source_text_too_short: 0
missing_source_text: 4
manual_queue_rows: 4
min_source_text_chars: 1000
```

动作分布：

```text
already_ingested: 19
pdf_extraction_failed_use_alternate_text_or_repair: 2
resolve_wrong_doi_or_replace_source: 2
```

`data/evidence_sources/pdfs/` 现在会递归扫描子目录，因此用户把 PDF 放在 `data/evidence_sources/pdfs/news/` 也能被 ingest。

### 8C.4 PDF / Literature Source Pipeline v2.3

v2.3 的目标不是继续下载 PDF，而是把小样本流程固化成可扩展的 source-level pipeline。

当前状态必须按两层理解：

```text
tool-level source rows: 23
tool-level source_text_available: 19
tool-level unresolved rows: 4

source-level records: 20
source-level source_text_available: 17
source_metadata_mismatch: 1
pdf_extraction_failed: 2
```

这不是矛盾：同一篇 benchmark paper 可以被多个 tool evidence row 引用，因此 source-level 记录少于 tool-level 行数。例如 `10.1038/s41592-021-01336-8` 同时服务 Seurat / Harmony / scvi-tools benchmark；`10.1093/bib/bbad418` 的 CellTypist / SingleR benchmark 错源也合并为同一个 quarantined source record。

固定 6 阶段 pipeline：

```text
1. build_source_registry
2. discover_pdf_candidates
3. validate_pdf_candidates
4. acquire_pdf_or_html
5. extract_source_text
6. build_coverage_and_indexes
```

当前本地命令：

```bash
# 一键离线刷新：默认不联网、不下载
python data_pipeline/run_literature_source_pipeline.py

# 1 + 3：构建 source-level registry、candidate quarantine、validation report
python data_pipeline/build_source_registry.py

# 6A：刷新 tool-level literature source coverage / resolution queue
python data_pipeline/build_literature_source_coverage.py

# 6B：刷新 retrieval-only chunk index
python data_pipeline/build_evidence_index.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv

# 6C：刷新 Algorithm Representation v2
python data_pipeline/build_algorithm_representations_v2.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv
```

如果后续要重新做开放 PDF candidate discovery，必须显式执行：

```bash
# 只发现候选，不下载
python data_pipeline/run_literature_source_pipeline.py --discover

# 只在人工看过候选后才允许 live download
python data_pipeline/run_literature_source_pipeline.py --live-download
```

核心产物：

```text
data/evidence_candidates/source_registry.tsv
data/evidence_candidates/pdf_candidate_registry.tsv
data/evidence_candidates/source_validation_report.tsv
data/evidence_candidates/source_acquisition_summary.json
data/evidence_candidates/source_extraction_summary.json
data/evidence_candidates/literature_source_coverage.tsv
```

source-level `SourceRecord` 字段：

```text
source_id
canonical_title
doi
source_url
source_type
source_status
local_pdf_path
local_text_path
validation_status
validation_issue
```

扩展字段包括 `referring_record_ids`、`referring_tool_names`、`source_row_count`、`recommended_pdf_path`。正式逻辑是：一篇 paper/source 只产生一个 source record；多个 tool evidence row 通过 `referring_record_ids` 引用同一个 `source_id`。

当前 4 条 unresolved 的正确处理：

```text
CellTypist / SingleR benchmark:
  validation_status = source_metadata_mismatch
  action = resolve_wrong_doi_or_replace_source
  原 DOI 10.1093/bib/bbad418 指向 PanomiR，不能保存、不能 ingest、不能作为 CellTypist/SingleR benchmark source。

Seurat v3 / Seurat v4 publication:
  validation_status = pdf_exists_but_extract_failed
  action = pdf_extraction_failed_use_alternate_text_or_repair
  PDF 已存在，不是重新下载任务；下一步是换 extractor、找 publisher HTML/full text，或替换为可抽取 PDF。
```

Dashboard `Evidence & RAG` 已分层展示：

```text
Core README/docs coverage
Paper/benchmark source coverage
Source-level registry
Source validation failures
PDF extraction failures
Quarantined PDF candidates
Manual acquisition / resolution queue
```

Dashboard 状态枚举：

```text
source_text_available
source_metadata_mismatch
pdf_exists_but_extract_failed
download_needed
not_download_task
```

验收标准：

- 当前 23 条 tool-level source row 仍保持 19 条 source text available；
- 4 条 unresolved 分类正确：2 条 wrong DOI/source，2 条 Seurat extraction failure；
- bad DOI/PDF candidate 不产生 `Save as` / `target_pdf`；
- PDF 已存在但抽取失败时，不进入 download queue；
- candidate title / DOI mismatch 进入 quarantine，不能进入 ingest；
- source chunk 仍只能用于 evidence discovery，不自动晋升 formal TSV。

## 8D. Decision Workflow Demo v1

为了避免 scKG-Agent 退化成“普通工具推荐助手”，当前阶段增加一个明确的价值展示入口：

```text
single-cell user scenario
  -> workflow decision graph
  -> step-level candidate tools
  -> source-bound RAG snippets
  -> evidence gaps / caveats
  -> executable skeleton
  -> auditable decision report
```

这一定义比“推荐报告”更准确：

```text
scKG-Agent = evidence-governed single-cell analysis decision and migration agent
```

当前 demo 场景：

```text
multi-sample 10x PBMC scRNA-seq
QC
doublet detection
batch integration
cell type annotation
optional trajectory / fate analysis
evidence audit
```

生成命令：

```bash
python data_pipeline/build_decision_workflow_demo.py
```

输出：

```text
data/evidence_candidates/decision_workflow_demo_v1.json
data/evidence_candidates/decision_workflow_demo_v1.tsv
data/evidence_candidates/decision_workflow_demo_v1.md
```

Dashboard 展示位置：

```text
Evidence & RAG -> Decision Workflow Demo
```

当前 demo 的边界：

- `status = evidence_limited_plan_only`；
- workflow candidate 不等于强推荐；
- RAG snippets 只进入 retrieval context；
- source-bound chunks 可以解释上下文，但不能自动晋升 formal TSV；
- `formal_main_recommendation_evidence_count = 0` 是预期，因为 publication / benchmark formal evidence 仍处于冻结或待修复状态；
- 代码 skeleton 是执行模板，不是自动运行结果。

当前 demo 应至少展示：

- workflow steps；
- candidate tool cards；
- source-bound snippet count；
- formal evidence blocker；
- graph-style step handoff；
- Scanpy / Seurat skeleton；
- next actions。

验收口径：

```text
workflow_steps >= 6
total_retrieval_snippets > 0
source_bound_retrieval_snippets > 0
formal_main_recommendation_evidence_count == 0
status == evidence_limited_plan_only
```

这个 demo 是下一步产品方向的基准：用户最终不应该只拿到“推荐某工具”，而应该拿到“为什么这样规划、每一步怎么做、证据在哪里、哪些地方不能强说”的可审计分析决策过程。

## 8E. Workflow Eval Set v0.1

为了评估当前阶段是否真的从“推荐报告”升级成“可审计 workflow decision agent”，新增一个最小 gold eval set：

```text
eval/gold_workflow_scenarios_v0_1.jsonl
```

覆盖 8 类典型单细胞工作流：

- PBMC multi-sample workflow planning；
- doublet detection；
- spatial deconvolution；
- RNA velocity / fate-state review；
- multiome integration；
- AnnData / Seurat object conversion；
- ambient RNA removal；
- trajectory differential expression。

运行命令：

```bash
python eval/run_workflow_eval.py
```

输出：

```text
eval/workflow_eval_v0_1_summary.json
eval/workflow_eval_v0_1_per_scenario.tsv
eval/workflow_eval_v0_1_failure_queue.tsv
```

Dashboard 展示位置：

```text
Evaluation -> Workflow Eval v0.1
```

当前验收指标：

```text
scenario_count = 8
pass_rate = 1.0
required_step_recall >= 0.75
candidate_tool_recall >= 0.60
unsupported_step_rate <= 0.25
evidence_boundary_violation_count = 0
```

当前一次运行结果：

```text
pass_rate = 1.0
required_step_recall = 0.982143
candidate_tool_recall = 1.0
unsupported_step_rate = 0.0
evidence_boundary_violation_count = 0
failure_count = 0
```

注意边界：

- Workflow Eval v0.1 只验证 workflow 形状、候选工具覆盖和 evidence boundary；
- 它不验证生物学结论是否正确；
- 它不允许 RAG chunk、reflection memory、internal workflow template 直接晋升 formal evidence；
- failure queue 是后续修模板、补证据和扩 gold set 的主要入口。

下一步扩展方向：

- 把 gold set 从 8 条扩到 20-30 条；
- 每条 scenario 增加 negative constraint，例如物种、平台、GPU/CPU、数据规模；
- 对每一步增加 expected blocker / caveat；
- 加入 ID-based context precision / recall；
- 后续再接 RAGAS，但 RAGAS 分数不能绕过 evidence gate。

## 8F. Home / Chat Workflow Decision Sandbox v0.1

为了让当前阶段的效果不只停留在 demo artifact 和 eval JSON，dashboard 的 `Home / Chat` 增加一个本地可交互入口：

```text
Home / Chat -> Workflow Decision Sandbox
```

用户可以输入：

- query；
- task；
- modality；
- species / platform / noise；
- data object；
- output goal；
- candidate tools。

系统输出：

```text
query + structured constraints
  -> deterministic workflow planner
  -> step-level candidate tools
  -> governed RAG retrieval context
  -> source-bound snippet preview
  -> evidence boundary metrics
  -> markdown decision report
```

当前实现位置：

```text
engine/workflow_decision.py
observability/dashboard/app.py
tests/test_workflow_decision.py
```

当前样例输出：

```text
workflow_steps = 7
retrieval_snippets = 28
source_bound_retrieval_snippets = 18
evidence_boundary_violation_count = 0
formal_main_recommendation_evidence_count = 0
```

边界声明：

- 这是 sandbox，不是正式用户聊天入口；
- 不调用 LLM；
- 不写 Neo4j；
- 不写 memory / skill / formal TSV；
- 不改变 MCDM rank；
- RAG snippets 只用于 evidence discovery / explanation；
- internal workflow template 不允许成为 main recommendation evidence。

这一步的意义是把 scKG-Agent 的产品形态从“后台评测 + 静态 demo”推进到“用户可输入场景并即时看到决策过程”。后续正式 Chat 页面应复用 `engine.workflow_decision.build_workflow_decision_response`，不要把同样逻辑重新散写在 UI 里。

## 8G. Unified App v0.2：用户界面 + 管理员界面

当前 `app.py` 已经从原始聊天窗口升级为统一应用：

```text
app.py
  User workspace
    Chat
    Knowledge Graph
  Admin workspace
    Evidence & RAG
    Evaluation
    Memory
    Architecture
```

用户侧：

- `Chat` 保留原始对话窗口、会话存储、上传文件摘要、follow-up suggestions；
- 每次正式 agent run 后，默认附加 `Workflow Decision` card；
- 该 card 展示 workflow steps、candidate tools、retrieval snippets、source chunks、boundary status；
- `Knowledge Graph` 保留正式图谱探索器，展示 Tool / Task / Publication / Benchmark 主干和候选证据隔离状态。

管理员侧：

- `Evidence & RAG`：查看 evidence chunks、dense vector 数量、core source coverage、literature source coverage、source registry、PDF/HTML acquisition policy；
- `Evaluation`：查看 Workflow Eval v0.1 summary、per-scenario rows、failure queue；
- `Memory`：查看 reflection events、private operational memory、review-only skill candidates；
- `Architecture`：查看当前中心化递归 Agent 路线、Hybrid RAG、PDF pipeline、memory、subagent、MCP 状态。

当前融合边界：

- Chat 的主回答仍由原始 `run_sckg_workflow_traced` 生成；
- workflow decision card 由 `engine.workflow_decision.build_workflow_decision_response` 生成；
- workflow decision 不调用 LLM、不写 Neo4j、不写 formal TSV、不改变 MCDM rank；
- RAG snippets/source chunks 只进入 evidence discovery / explanation；
- memory 只写 private operational memory，不能成为 scientific authority。

PDF/source 后续路线：

```text
automatic candidate discovery
  -> title/DOI validation
  -> open PDF/HTML acquisition
  -> extraction
  -> evidence_chunks.jsonl
  -> manual/source-level validation
  -> review packet
  -> formal TSV promotion only if source-bound and reviewed
```

需要人工或半人工处理的情况：

- paywall / browser login；
- DOI 指向错误文章；
- PDF title 与 expected title 不匹配；
- PDF 已存在但 extractor 失败；
- 需要判定 source span 是否真正支持 claim；
- 需要决定是否能晋升 formal evidence。

多智能体后续路线：

- 当前主系统仍是中心化 Parent Agent / centralized workflow；
- subagent contract 和测试已存在，但默认不参与主推荐；
- 下一阶段只允许 read-only subagents：
  - evidence search；
  - benchmark span check；
  - workflow compatibility check；
  - report critique；
- subagent 输出只能进入 candidate_context / review notes；
- Parent Agent 仍负责最终回答、证据边界、推荐排序和 audit。

当前有 3 个特殊处理：

- `scvi-tools_CAND_PUB_scvi-tools_0214cd4cc2d8.pdf`：`pypdf` 首次失败，但 Ghostscript repair 后成功抽取；
- `Seurat_CAND_PUB_Seurat_v3_2019_Stuart.pdf`：PDF 文件存在，但当前 extractor 抽取失败；
- `Seurat_CAND_PUB_Seurat_v4_2021_Hao.pdf`：PDF 文件存在，但当前 extractor 抽取失败。

已知 bad candidate：

```text
10.1093/bib/bbad418 / bbad418.pdf
  -> PDF title: PanomiR: a systems biology framework for analysis of multi-pathway targeting by miRNAs
  -> 不可用于 CellTypist / SingleR 的 cell type annotation benchmark
  -> 当前进入 resolve_wrong_doi_or_replace_source 队列
```

当前可用 source text 的工具：

```text
CellRank: 2/2
CellTypist: 1/2
Harmony: 2/2
Scanpy: 3/3
Scrublet: 2/2
Seurat: 1/3
SingleR: 1/2
cell2location: 2/2
scVelo: 2/2
scvi-tools: 3/3
```

当前仍缺 paper / benchmark source text 的工具：

```text
CellTypist: 1
Seurat: 2
SingleR: 1
```

剩余处理队列：

```text
data/evidence_candidates/core_literature_manual_download_queue.md
```

注意：当前队列里的 4 条不再是普通下载任务。`resolve_wrong_doi_or_replace_source` 不允许保存错误 PDF；`pdf_extraction_failed_use_alternate_text_or_repair` 表示 PDF 已经存在，需要修复抽取或换成 HTML/full text。

### 8C.4 PDF 放好后继续跑什么

当手动下载 PDF 放入 `data/evidence_sources/pdfs/` 后，依次运行：

```bash
python data_pipeline/ingest_evidence_pdfs.py \
  --source-manifest data/evidence_candidates/evidence_source_manifest_v1.tsv \
  --output-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --summary-output data/evidence_candidates/evidence_pdf_ingest_full_summary.json \
  --overwrite

python data_pipeline/build_literature_source_coverage.py

python data_pipeline/build_evidence_index.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv

python data_pipeline/build_algorithm_representations_v2.py \
  --source-manifest data/evidence_candidates/evidence_pdf_source_manifest_full.tsv \
  --source-manifest data/evidence_candidates/core_tool_source_manifest_v2.tsv
```

验证：

```bash
python -m pytest
python eval/run_evidence_recovery_smoke.py
python eval/run_observability_acceptance.py
```

### 8C.5 边界

- PDF / HTML source text 只进入 retrieval / evidence discovery；
- source text 不自动晋升 formal TSV；
- `source_text_too_short` 不能算完整原文证据；
- RAGAS 或模型判断不能绕过 promotion gate；
- 下载器不绕过 paywall，不使用灰色来源。

---

## 9. MCDM 推荐设计

### 9.1 MCDM 不是 popularity rank

MCDM 必须区分：

```text
scientific performance
literature support
engineering reliability
evidence completeness
task alignment
canonical authority
```

建议公式方向：

```text
base_score =
  0.45 * benchmark_component
+ 0.30 * literature_component
+ 0.25 * engineering_component

final_score =
  base_score
* evidence_completeness
* task_alignment
* canonical_priority
* governance_gate
```

### 9.2 GitHub 的地位

GitHub 只能说明：

- 维护情况；
- 工程活跃度；
- 可用性风险；
- 社区采用度的一部分。

GitHub 不能单独支持：

- 强科学推荐；
- benchmark superiority；
- method correctness；
- ranking claim。

### 9.3 输出必须解释

每个推荐工具都应输出：

- MCDM score；
- evidence completeness；
- benchmark support；
- publication support；
- engineering support；
- missing evidence；
- confidence；
- caveats。

---

## 10. Semantic Auditor 设计

### 10.1 Auditor 的地位

Auditor 是最终安全门。

它应阻断：

- unsupported tool claims；
- unsupported benchmark claims；
- unsupported ranking claims；
- unsupported literature claims；
- unsupported workflow transitions；
- unsupported migration guarantees；
- invented thresholds；
- invented numeric metrics。

### 10.2 高危输出处理

如果发现 high / critical issue：

```text
unsafe report
  -> replaced by safe blocked report
```

不能只在日志里记录。

### 10.3 Auditor 输入

Auditor 必须能看到：

- final report；
- scored tools；
- evidence bundle；
- context pack；
- migration paths；
- workflow recommendation；
- missing evidence。

### 10.4 Auditor 输出

```text
passed
hallucination_rate
issues
unsupported_tools
unsupported_claims
severity_counts
blocked_by_guardrail
```

---

## 11. Memory 设计

### 11.1 Memory 能做什么

Memory 可以影响：

- 用户偏好；
- 输出格式；
- 历史会话上下文；
- 项目目标；
- 未解决约束；
- 推荐运行历史；
- audit 历史。

### 11.2 Memory 不能做什么

Memory 不能变成：

- publication evidence；
- benchmark evidence；
- ranking evidence；
- scientific proof。

任何 memory-derived scientific claim 必须走：

```text
candidate
  -> human review
  -> formal TSV
  -> graph backfill
  -> evidence gate
```

---

## 12. MCP 规划

### 12.1 为什么要做 MCP

Streamlit 是演示界面。MCP 才能让 scKG 变成可被其他 agent 调用的科研证据服务。

MCP 的直接收益：

- 让 Claude Code、Cursor、VS Code Copilot 等工具直接调用 scKG；
- 不需要每个入口都重写一套 UI；
- 工具调用结果天然结构化，便于 trace 和 eval；
- 可以把 scKG 包装成团队共享的 evidence service；
- 后续其他 agent 可以把 scKG 当作可信 evidence tool，而不是重新实现推荐逻辑。

### 12.2 scKG MCP tools

| Tool | 作用 |
| --- | --- |
| `recommend_omics_tools` | 证据治理型工具推荐 |
| `query_sckg_evidence` | 查询 formal evidence / KG evidence |
| `explain_recommendation_trace` | 解释约束、召回、gate、MCDM、audit |
| `list_evidence_gaps` | 列出缺 publication / benchmark / protocol 的地方 |
| `get_tool_profile` | 返回工具画像、正式证据、风险 |
| `audit_scientific_claim` | 检查用户给出的科学 claim 是否被证据支持 |

### 12.3 MCP 约束

- stdout 只能输出 MCP JSON-RPC；
- logs 写 stderr 或文件；
- tool output 必须结构化；
- 输出必须包含 governance status；
- read-only tools 先行；
- 写 formal TSV / Neo4j 的 admin tools 暂时不做。

### 12.4 MCP stdio server 是什么

`MODULAR-RAG-MCP-SERVER` 采用的是 MCP stdio server。

工作方式：

```text
MCP Client
  -> 启动本地 Python 子进程
  -> stdin 发送 JSON-RPC 请求
  -> stdout 接收 JSON-RPC 响应
  -> stderr / logs 记录日志
```

核心文件：

- `src/mcp_server/server.py`
- `src/mcp_server/protocol_handler.py`
- `src/mcp_server/tools/query_knowledge_hub.py`
- `src/mcp_server/tools/list_collections.py`
- `src/mcp_server/tools/get_document_summary.py`

它的关键工程约束：

- `stdout` 只能输出 MCP 协议消息；
- 所有日志必须到 `stderr` 或文件；
- tool 要有 JSON Schema 输入；
- tool handler 捕获异常，不能把堆栈直接暴露给用户；
- 重 I/O 要放到线程，避免阻塞 stdio event loop；
- tools/list 暴露工具定义；
- tools/call 路由到具体 tool。

### 12.5 本地部署路径

第一阶段推荐做本地 MCP：

```text
本地 .env
  -> 本地 Python 环境
  -> scKG MCP stdio server
  -> Claude Code / Cursor / VS Code 调用
  -> Neo4j Aura 或 offline fallback
```

适合：

- 自己开发；
- 给少数同学安装配置；
- 验证 tool schema；
- 跑 offline smoke；
- 快速迭代。

本地 MCP 的优点：

- 配置简单；
- 不暴露网络端口；
- 数据留在本机；
- 很适合开发者工具链；
- 不需要先做鉴权和多租户。

缺点：

- 每个试用者都要配置环境；
- 不适合网页访问；
- 不适合多人共享同一服务；
- 更新版本需要重新拉代码或安装。

### 12.6 组内小规模试用路径

组内试用建议分三步，不要一上来就做复杂云部署。

Step 1：本地 MCP 试用。

```text
每个同学本地配置 MCP
  -> 连接同一个 Neo4j Aura
  -> 使用 read-only tools
```

要求：

- 不开放写 formal TSV；
- 不开放写 Neo4j；
- 每人使用自己的 LLM key，或使用统一受控 key；
- 输出带 governance status。

Step 2：局域网 / 实验室服务器 HTTP 服务。

```text
FastAPI / Streamlit service
  -> 内部端口
  -> read-only recommendation API
  -> simple auth
  -> shared logs and traces
```

适合：

- 组内同学不用配置 MCP；
- 通过网页或 HTTP API 试用；
- 收集 bad case；
- 收集反馈。

Step 3：云端小规模部署。

```text
Docker container
  -> cloud VM / Azure Container Apps / internal server
  -> Neo4j Aura
  -> managed secrets
  -> auth
  -> monitoring
```

上线前必须补：

- 鉴权；
- rate limit；
- secret management；
- log redaction；
- trace storage；
- error reporting；
- read-only 默认策略；
- 成本监控。

### 12.7 云端部署是否麻烦

不算特别麻烦，但要分清两种部署。

本地 MCP stdio：

```text
最简单
适合开发工具调用
不需要开放端口
不适合多人共享同一个进程
```

云端服务：

```text
需要 HTTP/SSE 或 MCP remote transport
需要鉴权
需要容器化
需要 secrets 管理
需要日志和成本控制
```

建议路线：

```text
本地 MCP stdio
  -> 本地 Streamlit + Neo4j Aura
  -> 内部 FastAPI/Streamlit 服务
  -> Docker 化
  -> 组内小规模试用
  -> 云端部署
```

---

## 13. Dashboard 规划

目标不是做花哨 UI，而是把坏 case 变得可诊断。

需要的页面：

- 系统总览；
- formal evidence inventory；
- KG explorer；
- RAG trace；
- recommendation trace；
- MCDM breakdown；
- context pack viewer；
- hallucination audit viewer；
- evidence gap board；
- eval history。

RAG trace 页面至少展示：

```text
query
parsed constraints
dense results
sparse results
RRF fused results
reranked evidence snippets
governance filter result
context pack layer placement
```

### 13.1 Observability v1 已落地接口

默认 trace log：

```text
logs/traces.jsonl
```

默认 reflection log：

```text
data/memory/reflection_events.jsonl
```

默认 private memory：

```text
data/memory/project_memory.sqlite
```

默认 skill candidate：

```text
data/skill_candidates/*.md
```

Dashboard 启动：

```bash
python scripts/start_dashboard.py
```

生成一条本地离线 agent trace：

```bash
python scripts/run_agent_trace_smoke.py
```

自动验收 Observability v1：

```bash
python eval/run_observability_acceptance.py

# 如果当前还没有 trace，可让验收脚本先生成一条：
python eval/run_observability_acceptance.py --run-smoke
```

当前统一应用与 dashboard 页面已经与目标信息架构对齐：

- Home / Chat；
- Run Trace；
- Evidence & RAG；
- Neo4j / KG；
- Reflection Memory；
- Evaluation；
- Settings。

统一多页面 App 目标信息架构：

```text
Home / Chat
Knowledge Graph
Run Trace
Evidence & RAG
Neo4j / KG
Reflection Memory
Evaluation
Settings
```

实现顺序：

1. `app.py` 已完成第一轮融合：Chat / Knowledge Graph / Evidence & RAG / Evaluation / Memory / Architecture；
2. `observability/dashboard/app.py` 继续作为管理员调试备用面板；
3. 后续把 Run Trace 也接入 `app.py`，形成完全统一的单应用；
4. Settings 继续只读或低风险配置，不提供 formal evidence 编辑。

页面职责：

- `Home / Chat`：正式使用入口；保留原始对话窗口，并在正式回答下附加 Workflow Decision card；
- `Knowledge Graph`：用户/管理员都可查看的图谱探索器；
- `Run Trace`：查看单次 agent run 的 route、stage latency、warnings、audit；
- `Evidence & RAG`：查看 KG filter、dense/sparse/fusion/rerank、evidence boundary、missing evidence；
- `Evidence & RAG -> Core Tool Source Coverage`：查看核心工具 source chunk、fetch status、dense vector 状态和缺口；
- `Evidence & RAG -> Paper / Benchmark Source Coverage`：查看 tool-level source row 覆盖、source-level registry、metadata mismatch quarantine、PDF extraction failure 和 manual resolution queue；
- `Neo4j / KG`：查看 Tool / Task / Modality inventory、query 命中的 graph path、formal TSV vs Neo4j 对比；
- `Reflection Memory`：查看 private memory、reflection events、review-only skill candidates；
- `Evaluation`：查看 smoke/eval 历史、acceptance summary、failure queue；
- `Settings`：只读展示模型、Neo4j、embedding、trace 路径；v1 不提供 formal evidence 编辑。

近期不要把所有内容塞进 Chat 页面。Chat 页面只展示用户需要的摘要和引用；调试细节放到 Dashboard / Run Trace。

当前 KG gate diagnostics 已经写入 `kg_hard_filter` trace stage：

- `provider`：`neo4j` 或 `offline_graph`；
- `raw_candidate_count` / `raw_candidate_tools`；
- `candidate_tool_count` / `admitted_candidate_tools`；
- `blocked_reason_counts`；
- `candidate_diagnostics`：每个候选工具的 gate status、gate reasons、task alignment、evidence metric/source/layer 摘要。

这些字段用于解释“为什么 Neo4j 命中了工具，但主推荐还是 0”。它们只用于观察和调试，不改变推荐排序，不绕过 evidence gate。

Agent run 固定 stage：

```text
trigger
gateway
intent_parse
kg_hard_filter
evidence_retrieval
mcdm_rank
migration_or_workflow_plan
report_generate
audit
reflect
```

每个 stage 至少记录：

```text
elapsed_ms
status
method/provider
input_summary
output_summary
warnings
```

---

## 14. 测试与评估

### 14.1 测试分层

借鉴 RAG 项目的测试金字塔：

```text
Unit Tests
  -> 单函数/类逻辑

Integration Tests
  -> KG/RAG/MCDM/Auditor 协作

E2E Tests
  -> 预测生成、评估、UI/MCP smoke
```

### 14.2 scKG 必须保留的 smoke

```bash
/opt/anaconda3/envs/sckg_env/bin/python -B -m py_compile \
  app.py \
  agent/traced_runner.py \
  agent/workflow.py \
  core/models.py \
  core/agent_runtime.py \
  core/trace_context.py \
  core/reflection_memory.py \
  core/subagent_runtime.py \
  core/evidence_policy.py \
  observability/dashboard/app.py \
  observability/dashboard/services.py \
  scripts/start_dashboard.py \
  engine/context_pack_builder.py \
  engine/evidence_rag_pipeline.py \
  engine/knowledge_graph_view.py \
  data_pipeline/kg_quality_audit.py \
  eval/generate_predictions.py \
  eval/run_eval.py \
  eval/run_agent_eval.py

/opt/anaconda3/envs/sckg_env/bin/python -B \
  eval/generate_predictions.py \
  --limit 3 \
  --offline-llm \
  --output /tmp/sckg_smoke_predictions.jsonl

/opt/anaconda3/envs/sckg_env/bin/python -B \
  eval/run_eval.py \
  --predictions /tmp/sckg_smoke_predictions.jsonl

/opt/anaconda3/envs/sckg_env/bin/python -B \
  eval/run_agent_eval.py \
  --predictions /tmp/sckg_smoke_predictions.jsonl \
  --json-output /tmp/sckg_agent_run_eval_summary.json \
  --output /tmp/sckg_agent_run_eval_summary.tsv \
  --per-query-output /tmp/sckg_agent_run_eval_per_query.tsv
```

### 14.3 核心评估脚本

| 脚本 | 评估内容 |
| --- | --- |
| `eval/run_eval.py` | 推荐、约束、证据、报告 |
| `eval/run_migration_eval.py` | migration decision |
| `eval/audit_context_pack_v0_12.py` | context pack governance |
| `eval/audit_formal_benchmark_evidence.py` | formal benchmark numeric/source-bound 审计 |
| `eval/audit_formal_publication_evidence.py` | formal publication source-span / reviewer / canonical 审计 |
| `eval/run_agent_eval.py` | AgentRun process quality |
| `eval/run_ragas_eval.py` | future RAGAS-based generic RAG quality |
| `eval/validate_*.py` | sealed protocol |

### 14.4 指标

RAGAS / 通用 RAG 指标：

- ID-based context precision；
- ID-based context recall；
- RAGAS context precision；
- RAGAS context recall；
- RAGAS faithfulness；
- RAGAS response relevancy；
- evaluator model/version trace completeness。

推荐指标：

- recommendation type accuracy；
- top-k hit；
- evidence coverage；
- main recommendation evidence coverage；
- empty candidate rate；
- empty scored tools rate。

治理指标：

- candidate leakage rate；
- retrieval rankable violation；
- trusted non-main violation；
- semantic audit pass rate；
- high/critical hallucination rate；
- unsupported tool claim rate；
- blocked report rate。

Agent 指标：

- task success；
- progress rate；
- trajectory match；
- tool call accuracy；
- invalid action rate；
- mean tool latency；
- recovery success。

---

## 15. 中文主排期

### 阶段 A：规约与环境基线

目标：停止零散改动，固定项目方向。

任务：

- A1：维护中文 DEV_SPEC；
- A2：冻结英文 DEV_SPEC；
- A3：补齐 `.env.example`；
- A4：确认本地 `sckg_env`；
- A5：确认 Neo4j connectivity；
- A6：确认 offline smoke。
- A7：冻结 Agent 架构选择为“中心化递归 Agent（Recursive Centralized Agent）”。

验收：

- 中文 spec 存在并成为 README 入口；
- `.env` 不进 git；
- Neo4j 可连接；
- offline smoke 可运行。
- 不再按去中心化多 Agent 方向随意扩展。

### 阶段 B：formal evidence 清理

目标：把 formal evidence 做扎实。

任务：

- B1：跑 `kg_quality_audit.py`；
- B2：处理 `candidate_marker_in_formal_table`；
- B3：补 publication task mapping；
- B4：补 benchmark `work_group_id`；
- B5：补 DOI/PMID 或记录 no-PMID；
- B6：确认 schema order；
- B7：生成新的 quality report。

验收：

- formal TSV 不含未解释 candidate-only 标记；
- missing 字段有 review action；
- candidate evidence 没有被自动晋升。

### 阶段 C：KG sync 稳定化

目标：Neo4j 成为可靠 runtime graph。

任务：

- C1：审查 `sync_reviewed_tool_nodes.py`；
- C2：审查 `evidence_backfill.py`；
- C3：加 dry-run / summary；
- C4：验证 idempotent upsert；
- C5：导出 graph snapshot；
- C6：对比 TSV inventory 和 Neo4j inventory。

验收：

- 重跑不会重复节点；
- graph explorer 显示可信 trunk；
- candidate evidence 不进入 trusted graph。

### 阶段 D：Governed Evidence RAG v1

目标：把 RAG 从 lexical baseline 升级成真正工程化。

任务：

- D1：定义 `EvidenceChunk`；
- D2：定义 `EvidenceChunkRecord`；
- D3：formal TSV chunk builder；已落地：`engine/evidence_discovery_index.py`；
- D4：BM25-like sparse evidence index；已落地本地 lexical 版本；
- D5：dense evidence embedding；已接入 SiliconFlow `BAAI/bge-m3` 配置，默认不自动请求；
- D6：RRF fusion；已落地；
- D7：governance-aware rerank；已落地；
- D8：trace dense/sparse/fusion/rerank；已在 RAG context 输出 pipeline / mode / latency；
- D9：接入 EvidenceContextPack；
- D10：context-pack audit。
- D11：新增 `eval/run_ragas_eval.py` 适配层；
- D12：新增 RAGAS 与 scKG governance 双层 eval artifact。

验收：

- RAG snippets 仍然 `can_rank=false`；
- context pack present rate = 1.0；
- candidate leakage = 0；
- trusted non-main violation = 0；
- ID-based context recall >= 0.85；
- RAGAS faithfulness >= 0.90；
- RAGAS 高分不能绕过 evidence gate；
- offline fallback 仍可用。

### 阶段 E：MCDM 与推荐 hardening

目标：推荐结果更稳、更可解释。

任务：

- E1：梳理 MCDM 输入；
- E2：拆分 benchmark/literature/engineering components；
- E3：加入 evidence completeness penalty；
- E4：加入 task alignment penalty；
- E5：加入 canonical priority；
- E6：输出 per-tool evidence breakdown；
- E7：扩充 gold queries；
- E8：建立 failure queue。

验收：

- GitHub-only 不会强推荐；
- missing evidence 会降低 confidence；
- final report 能解释为什么推荐和为什么不推荐。

### 阶段 F：Migration hardening

目标：迁移假设有用但不过度承诺。

任务：

- F1：冻结 MigrationHypothesis schema；
- F2：补 compatibility gaps；
- F3：补 validation plan；
- F4：扩充 positive / negative / trap eval；
- F5：auditor 阻断 migration overclaim；
- F6：migration panel 与 recommendation panel 分离。

验收：

- migration 不进入 MCDM；
- false migration rate 受控；
- accepted migration 全部标记 exploratory。

### 阶段 G：Trace、Dashboard 与 Reflect

目标：坏 case 可诊断，agent run 可复盘，Hermes-like 反思只能沉淀到私有 operational memory。

任务：

- G1：统一 trace schema；已落地：`core/trace_context.py`；
- G2：记录 trigger / gateway；
- G3：记录 constraint parse；
- G4：记录 KG hard filter；
- G5：记录 evidence retrieval boundary；
- G6：记录 MCDM ranking / migration route；
- G7：记录 report generation；
- G8：记录 auditor issue；
- G9：记录 reflect stage；
- G10：做 dashboard viewer；已落地独立入口：`scripts/start_dashboard.py`；
- G11：写 private reflection memory；已落地：`core/reflection_memory.py`；
- G12：定义 recursive subagent contract；已落地：`core/subagent_runtime.py`，默认 disabled。

验收：

- 任意 bad case 可从 trace 解释；
- dashboard 不展示误导性指标；
- trace 不泄露 secret。
- memory/reflection/subagent output 不能绕过 evidence gate；
- skill candidate 不自动加载执行。

### 阶段 H：MCP Server

目标：让 scKG 可被其他 agent 调用。

任务：

- H1：设计 scKG MCP package；
- H2：实现 `recommend_omics_tools`；
- H3：实现 `query_sckg_evidence`；
- H4：实现 `explain_recommendation_trace`；
- H5：实现 `list_evidence_gaps`；
- H6：实现 `get_tool_profile`；
- H7：MCP client integration test；
- H8：MCP setup docs；
- H9：本地 MCP stdio 配置示例；
- H10：组内 read-only 试用部署方案；
- H11：HTTP/FastAPI service wrapper 预研；
- H12：Dockerfile 和 secrets 管理方案；
- H13：确保 MCP tools 复用核心 Python API，而不是复制 Streamlit 逻辑。

验收：

- stdio 不被日志污染；
- tools 返回结构化 JSON；
- tools 暴露 governance status；
- offline smoke 可通过 MCP 跑；
- 本地 Claude Code / Cursor / VS Code 至少一个客户端能成功调用；
- 组内试用版本默认 read-only；
- 部署版本不暴露 `.env` 和 API key。

### 阶段 I：Workflow evidence

目标：从工具推荐走向 workflow 推荐。

任务：

- I1：定义 workflow graph schema；
- I2：收集 protocol evidence；
- I3：定义 step compatibility；
- I4：workflow template 标记 template-only；
- I5：workflow audit；
- I6：workflow eval set。
- I7：借鉴 SciToolAgent，定义 `PlanChain` schema；
- I8：KG 子图召回 workflow 候选路径；
- I9：评估 recommendation path / workflow path 是否能解决问题；
- I10：把 input/output compatibility 加入 workflow trace。

验收：

- 每个 step 有证据或明确 template-only；
- unsupported transition 被 auditor 阻断。
- plan chain 不允许使用不存在或未治理的工具节点。

### 阶段 J：Execution Agent 预研

目标：只做 plan-only，不急着执行。

任务：

- J1：plan-only executor；
- J2：script generator design；
- J3：sandbox design；
- J4：command allowlist；
- J5：resource limit；
- J6：repair loop design。
- J7：对标 SciToolAgent 的 executor，但默认只做 dry-run / plan-only；
- J8：执行前后都必须进入 audit / safety gate。

验收：

- 没有 sandbox 前不执行真实命令；
- destructive/expensive operation 必须人工确认。
- 执行 agent 不能绕过 central orchestrator。

### 阶段 K：Production packaging

目标：从项目变成可交付系统。

任务：

- K1：config validation；
- K2：service entry；
- K3：health check；
- K4：Docker / env lock；
- K5：CI smoke；
- K6：release checklist。

验收：

- fresh clone 可跑 smoke；
- 缺配置 fail fast；
- logs/traces/secrets 分离。

### 阶段 L：GNN / RL / Learning-to-rank

目标：等证据和 trace 足够之后再做高级学习。

前置条件：

- KG schema 稳定；
- formal evidence 足够大；
- eval set 足够强；
- 有用户反馈 trace；
- reward 定义清楚；
- 有 rollback plan。

可以做：

- graph embedding recall；
- GNN relationship prediction；
- learning-to-rank；
- feedback-based interaction policy。

不能做：

- 让 GNN 分数变成科学证据；
- 让 RL 优化流畅度而牺牲可信度；
- 让模型绕过 human review。

---

## 16. 开发工作流

借鉴 `auto-coder` 的方式，后续每个开发循环都按这个走：

```text
读中文 spec
  -> 找当前阶段任务
  -> 明确输入输出和验收标准
  -> 小步实现
  -> 写测试
  -> 跑 smoke/eval
  -> 更新任务状态
  -> 更新中文 spec
```

每次改动前必须回答：

1. 属于哪个阶段？
2. 改哪个 contract？
3. 读哪些 evidence layer？
4. 写不写 formal TSV / Neo4j？
5. 需要跑哪个 eval？
6. 是否要更新中文 spec？

---

## 17. 当前优先级

短期不要做：

- RL；
- GNN；
- 去中心化多 Agent；
- 自动执行脚本；
- 大 UI 重构；
- 自动晋升证据。

近期最该做：

1. 中文 DEV_SPEC 固化；
2. formal evidence quality audit 清理；
3. Neo4j sync 稳定；
4. Governed Evidence RAG v1；
5. MCDM evidence breakdown；
6. trace/dashboard；
7. MCP server。

最关键的一条：

```text
先把 scKG 做成一个可检索、可追踪、可调用、可评估的证据治理系统，
再去谈更高级的 agent 自主性。
```

---

## 18. 里程碑定义

### Milestone 1：可信证据底座

完成：

- formal TSV 清理；
- KG quality audit 降低；
- Neo4j sync 稳定；
- offline fallback 保留。

### Milestone 2：工程化 KG-RAG

完成：

- EvidenceChunk；
- BM25 + dense；
- RRF；
- rerank；
- trace；
- ContextPack audit。

### Milestone 3：可信推荐 Agent

完成：

- MCDM breakdown；
- recommendation eval；
- semantic audit；
- safe blocked report；
- failure queue。

### Milestone 4：MCP Evidence Service

完成：

- read-only MCP tools；
- client integration；
- structured governance output。

### Milestone 5：Workflow and Execution Roadmap

完成：

- workflow evidence schema；
- plan-only executor；
- sandbox design。

---

## 19. 最终北极星

项目最终应该长成：

```text
reviewed scientific evidence
  -> governed KG
  -> governed RAG indexes
  -> centered multi-role Agent workflow
  -> MCP evidence service
  -> traceable recommendation / migration / workflow output
  -> semantic audit
  -> eval feedback
  -> human evidence improvement loop
```

这才是 scKG-Atlas Agent 的产品级闭环。

---

## 20. 科研绘图与手册规范

scKG 后续不只是开发项目，也要能被组内同学、论文读者和评审看懂。因此从设计阶段开始，架构图、流程图和手册图都作为正式工程资产维护。

### 20.1 harness-anything / nature-skills 对我们的启发

`/Users/lris/Desktop/scKG_agent/harness-anything` 主要提供 WPS / Illustrator / Photoshop / Zotero 等自动化 harness。

当前判断：

- WPS / Illustrator / Photoshop harness 多依赖 Windows COM，当前 macOS 本地不适合直接作为主绘图工具；
- 它的价值在于“图、PPT、手册可以工程化生成”这一思想；
- 后续如果在 Windows 机器上做 PPT 或 Illustrator 精修，可以把 `docs/figures/*.svg` 作为输入；
- 现阶段 scKG 应优先维护可版本化的图源文件，而不是只保存手工截图。

`/Users/lris/Desktop/scKG_agent/harness-anything-mac` 的定位略不同：

- 它包含 macOS / Linux 下通过 LibreOffice headless 做 Office 转换的路径；
- 如果本机安装 `LibreOffice.app` 或命令行 `soffice`，后续可用于把 `.pptx` 导出 `.pdf`，或做手册/PPT 的批量渲染；
- 它不适合作为当前 scKG 科研架构图的主生产工具，因为论文级架构图更需要稳定图源、可 diff、可重复导出；
- 它适合放到后续组会汇报、项目手册、PPT 自动化阶段。

`/Users/lris/Desktop/scKG_agent/nature-skills` 对 scKG 更有直接价值，尤其是 `nature-figure`：

- 它强调 figure contract：先确定每张图要证明什么，再决定布局和图形编码；
- 它强调 publication-ready 输出：SVG / PDF / PNG 都要可复现；
- 它强调多 panel、克制配色、清晰层级和图例规范；
- 它更适合指导 scKG 的论文图、手册图、架构图，而不是直接操控 Office。

所以 scKG 当前采用：

```text
Graphviz DOT source for engineering diagrams
  -> quick SVG / PDF / PNG drafts
Python matplotlib publication renderer
  -> publication-style SVG / PDF / PNG figures
Manual refinement if needed
  -> Illustrator / PowerPoint / paper layout
```

### 20.2 当前 Figure Set

图源和导出文件统一放在：

```text
docs/figures/
```

当前三张核心图：

| Figure | 文件 | 用途 |
| --- | --- | --- |
| Figure 1 | `scKG_current_agent_orchestration.*` | 当前 agent 编排架构图，偏工程草图 |
| Figure 1P | `scKG_current_agent_orchestration_publication.*` | 当前 agent 编排架构图，论文/手册优先版本 |
| Figure 2 | `scKG_target_hybrid_agent_architecture.*` | 目标中心化治理混合型 Agent 架构图，偏工程草图 |
| Figure 2P | `scKG_target_hybrid_agent_architecture_publication.*` | 目标 agent 架构图，论文/手册优先版本 |
| Figure 3 | `scKG_hybrid_kg_rag_flow.*` | Evidence-governed Hybrid KG-RAG 流程图，偏工程草图 |
| Figure 3P | `scKG_hybrid_kg_rag_flow_publication.*` | Hybrid KG-RAG 流程图，论文/手册优先版本 |

每张图至少保留：

- `.dot`：可编辑源文件；
- `.svg`：手册、网页、Illustrator 精修；
- `.pdf`：论文或 LaTeX；
- `.png`：快速预览、PPT 草稿。

Graphviz 草图渲染命令：

```bash
bash docs/figures/render_figures.sh
```

Publication 风格渲染命令：

```bash
bash docs/figures/render_publication_figures.sh
```

维护原则：

- `*_publication.*` 是手册和论文优先引用版本；
- `.dot` 版本用于快速改逻辑和给工程同学看流程；
- 所有图都必须能从 repo 中重新生成；
- 不能只保留截图或手工编辑后的孤立图片；
- 如果 Illustrator / PowerPoint 精修，必须保留精修源文件并记录来自哪个 SVG/PDF。

### 20.3 图 1：当前 Agent 编排

图 1 必须表达当前系统不是去中心化多 Agent，而是：

```text
中心化 StateGraph workflow
```

必须包含：

- user query；
- project memory / upload context；
- intent parser；
- normalized constraints；
- KG hard-constraint retrieval；
- evidence gate；
- MCDM scorer；
- migration engine；
- report generator；
- EvidenceContextPack；
- semantic auditor；
- ranked / migration / blocked outputs；
- Neo4j、offline graph、formal TSV、task ontology 等证据来源。

### 20.4 图 2：目标混合型 Agent 架构

图 2 必须表达长期目标：

```text
Central Orchestrator
  + specialist agents / typed tools
  + MCP evidence service
  + governed KG-RAG
  + audit gate
```

必须保留的层：

- entry surfaces：Streamlit、CLI、MCP clients、FastAPI；
- central governance layer：orchestrator、tool registry、evidence policy、context pack、audit gate；
- specialist agents：intent、KG reasoning、evidence retrieval、ranking、migration、workflow planning、future execution；
- knowledge plane：formal evidence store、scKG Neo4j、hybrid evidence index、trace/eval store、pluggable providers；
- governed outputs：recommendation report、workflow plan、gap board、safe blocked report。

### 20.5 图 3：Hybrid KG-RAG 流程

图 3 必须表达 scKG 的 RAG 不是普通 RAG，而是：

```text
Evidence-governed Hybrid KG-RAG
```

核心流程：

```text
Reviewed evidence / protocols / tool metadata
  -> pluggable loaders
  -> EvidenceChunk
  -> review gate
  -> KG + BM25 + dense index
  -> query constraint parser
  -> KG hard filter
  -> sparse search + dense search
  -> RRF fusion
  -> governance-aware rerank
  -> EvidenceContextPack
  -> evidence gate + MCDM
  -> report generation
  -> semantic auditor
```

必须在图中明确：

```text
RAG snippets explain evidence; they cannot directly upgrade rank or trust.
```

### 20.6 后续 Figure Roadmap

后续建议继续补：

1. `Figure 4`：scKG schema / ontology 图；
2. `Figure 5`：recommendation scoring / MCDM breakdown 图；
3. `Figure 6`：evidence curation and promotion workflow；
4. `Figure 7`：MCP stdio local deployment and group trial deployment；
5. `Figure 8`：evaluation and bad-case feedback loop。

论文或手册优先图序：

```text
Figure 1: Overall architecture
Figure 2: Hybrid KG-RAG method
Figure 3: Evidence governance and audit
Figure 4: Evaluation protocol
```
