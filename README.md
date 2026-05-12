# scKG-Atlas Agent

scKG-Atlas Agent 不是一个普通聊天机器人，而是一个面向单细胞与多组学分析场景的智能决策基础设施原型。它的目标是把单细胞工具、任务、模态、算法原理、工程活跃度和可迁移性证据组织成知识图谱，并在用户提出科研分析需求时，给出可解释、可追溯、可扩展的工具推荐或算法迁移建议。

当前项目已经具备一个最小可运行闭环：自然语言需求解析、Neo4j 知识图谱硬约束检索、MCDM 多准则排序、算法同构性向量检索、最终报告生成，以及 Streamlit 前端展示。

## 项目定位

这个项目后续应该被当作“单细胞领域智能决策基础设施”来建设，而不是只当成问答界面。

核心能力包括：

- 将单细胞工具生态沉淀为可查询、可更新、可审计的知识图谱。
- 根据任务、模态、硬件、数据对象和生物学分辨率筛选可行工具。
- 用 GitHub 活跃度、引用量、Benchmark 排名等证据做多准则决策排序。
- 当没有直接工具匹配时，基于算法特征 embedding 做同构性迁移推理。
- 输出带证据链的科研分析建议，而不是只生成自然语言答案。

## 当前架构

```text
用户问题
  |
  v
Streamlit 前端 app.py
  |
  v
LangGraph 工作流 agent/workflow.py
  |
  +-- 意图解析：core/prompts.py + core/llm_client.py
  |
  +-- 硬约束检索：connectors/graph_client.py -> Neo4j
  |
  +-- 有候选工具：engine/mcdm_calculator.py 做 MCDM 排序
  |
  +-- 无候选工具：engine/isomorphism_analyzer.py 做算法同构性迁移检索
  |
  v
报告生成
```

## 目录说明

```text
docs/
  schema.md              目标知识图谱 schema 与系统边界
  current_graph_inventory.md 当前图谱节点、关系和风险盘点
  mcdm_evidence_plan.md  MCDM 真实证据采集与替换占位字段方案

eval/
  gold_queries.jsonl     20 条核心评测 query，用于后续 P@K、召回率和幻觉率评估
  run_eval.py            离线约束解析回归评测入口

agent/
  states.py              LangGraph 全局状态定义
  workflow.py            Agent 决策工作流：解析、检索、排序、迁移、报告生成

core/
  models.py              Pydantic 科学对象系统：Evidence、ToolCandidate、Workflow、Report 等
  constraints.py         Pydantic 科研约束解析与 fallback 归一化
  llm_client.py          LLM 客户端封装，读取 .env 中的模型配置
  prompts.py             意图解析与报告生成 prompt

connectors/
  graph_client.py        Neo4j 连接器和硬约束查询接口

engine/
  mcdm_calculator.py     多准则决策排序引擎
  isomorphism_analyzer.py 算法同构性向量检索引擎

data_pipeline/
  github_crawler.py      GitHub 工程证据抓取
  llm_extractor.py       从摘要/说明文本抽取结构化图谱信息
  neo4j_loader.py        从 TSV 批量抽取、向量化并写入 Neo4j
  hybrid_loader.py       从本地 JSONL 备份恢复图谱算法特征

script/
  init_mock_data.py      写入少量测试图谱数据
  test_neo4j.py          Neo4j 连通性测试
  test_llm.py            LLM 连通性测试

data/
  scrna_tools.tsv        单细胞工具原始清单
  scKG_embeddings_backup.jsonl 图谱抽取与 embedding 本地备份

app.py                   Streamlit 可视化交互入口
main.py                  命令行 MVP 测试入口
```

## 知识图谱模型

当前 Neo4j 中主要使用以下节点和关系：

```text
(:Tool)-[:PERFORMS_TASK]->(:Task)
(:Tool)-[:SUPPORTS_MODALITY]->(:Modality)
(:Tool)-[:WRITTEN_IN]->(:Language)
(:Tool)-[:REQUIRES_HARDWARE]->(:Hardware)
(:Tool)-[:OPERATES_ON]->(:Resolution)
(:Tool)-[:IMPLEMENTS_ALGORITHM]->(:Algorithm)
(:Tool)-[:SUPPORTED_BY]->(:Evidence)
```

`Algorithm` 节点保存算法特征文本和 embedding，用于后续的同构性迁移检索。`Tool` 节点保存 description、github_stars、license、publish_year 等基础属性。

`Evidence` 是一级实体，用来记录 GitHub、文献、Benchmark、文档、LLM 抽取和人工审核等证据。后续推荐结果必须绑定 Evidence 或显式声明 missing evidence。

## 数据来源与规模

当前仓库包含两类核心数据：

- `data/scrna_tools.tsv`：单细胞工具清单，共 1843 行，字段包括工具名、平台、代码地址、描述、许可证、加入时间和更新时间。
- `data/scKG_embeddings_backup.jsonl`：图谱抽取与向量备份，共 1698 条记录，包含工具名、GitHub URL、LLM 抽取结果、算法特征 embedding 和额外元数据。

`loader_log.out` 记录了历史批量入库过程，可用于排查数据构建是否完整。

## 运行方式

建议使用 Python 3.10+。

如果使用现有 conda 环境：

```bash
conda activate /Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env
```

安装固定依赖：

```bash
pip install -r requirements.txt
```

准备 `.env`。先复制模板，再填真实值：

```bash
cp .env.example .env
```

核心配置统一从 `core/settings.py` 读取，不要在业务代码里直接写 `os.getenv`、默认密钥、默认密码或绝对路径。

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
OPENAI_API_BASE=https://api.deepseek.com
OPENAI_API_KEY=your_deepseek_key
DEEPSEEK_API_KEY=your_deepseek_key
MODEL_NAME=deepseek-v4-pro
EXTRACT_MODEL=deepseek-v4-pro
CHAT_API_BASE=https://api.deepseek.com
```

DeepSeek V4 当前官方 OpenAI-compatible 模型名包括 `deepseek-v4-pro` 和 `deepseek-v4-flash`。本项目默认使用 `deepseek-v4-pro`，更适合知识抽取、报告生成和复杂科研约束解析。

也可以用脚本更新本地 `.env`：

```bash
python script/configure_deepseek.py --api-key <your_deepseek_key> --model deepseek-v4-pro
```

测试 LLM：

```bash
python script/test_llm.py
```

测试 Neo4j：

```bash
python script/test_neo4j.py
```

写入少量 mock 数据：

```bash
python script/init_mock_data.py
```

从 JSONL 备份恢复算法特征：

```bash
python data_pipeline/hybrid_loader.py
```

运行命令行 MVP：

```bash
python main.py
```

运行 Streamlit 前端：

```bash
streamlit run app.py
```

运行离线评测：

```bash
python eval/run_eval.py
```

先生成标准化系统预测，再计算检索、证据和 workflow 指标：

```bash
python eval/generate_predictions.py --output eval/predictions.jsonl
python eval/run_eval.py --predictions eval/predictions.jsonl
```

预测 JSONL 使用固定机器契约：`query_id`、`user_query`、`parsed_constraints`、`candidate_tools`、`scored_tools`、`migration_paths`、`recommendation_type`、`evidence_bundle`、`workflow_recommendation`、`final_report`、`missing_components`、`clarification_needed` 和 `execution_status`。兼容评测字段包括 `id`、`recommendation_kind`、`recommended_tools`、`evidence_coverage`、`workflow_steps`、`claim_count` 和 `unsupported_claims`。

## 当前工作流

1. `parse_intent_node` 使用 LLM 将用户问题转为结构化约束，例如 `task` 和 `modality`。
2. `hard_constraint_node` 基于 Neo4j 查询直接满足任务和模态的工具候选集。
3. 如果存在候选工具，`mcdm_scoring_node` 读取图谱中的工程指标，并用 MCDM 做综合排序。
4. 如果没有候选工具，`migration_reasoning_node` 将需求转为 BGE-M3 embedding，并与图谱中算法特征做余弦相似度检索。
5. `generate_report_node` 基于结构化中间结果生成最终科研决策报告。

## 当前不足

这个原型已经有正确方向，但还没有达到稳定基础设施标准。最需要优先处理的问题是：

- 密钥管理：当前仓库中存在 `.env`，部分代码也有硬编码默认密钥或密码，应尽快迁移到安全配置方案，并清理 Git 历史中的敏感信息。
- 依赖管理：当前缺少 `requirements.txt` 或 `pyproject.toml`，环境不可复现。
- Prompt 约束过窄：意图解析只支持少量 task 和 modality，无法覆盖真实单细胞分析场景。
- 状态模型偏松：`ScKGAgentState` 只是 TypedDict，缺少字段校验、错误类型、证据对象和版本信息。
- 数据可信度不足：LLM 抽取结果缺少来源引用、置信度、人工审核状态和数据版本。
- MCDM 证据不完整：citations 和 benchmark_rank 目前仍是占位值，排序结果不能直接当作科研结论。
- 向量检索可扩展性有限：当前从 Neo4j 拉取所有 embedding 后在本地做 NumPy 相似度，数据量增大后应迁移到向量索引。
- 前后端耦合：Streamlit 中有较多状态解析和兜底逻辑，后续应拆出 API 层和标准响应 schema。
- 测试体系不足：目前只有连通性脚本，没有单元测试、集成测试和固定样例回归集。
- 可观测性不足：工作流依赖 `print`，缺少结构化日志、trace id、节点耗时和失败重试策略。

## 下一阶段路线图

### 第一阶段：把原型变成可复现实验系统

- 新增 `requirements.txt` 或 `pyproject.toml`，固定依赖版本。
- 新增 `.env.example`，并停止追踪真实 `.env`。
- 去除代码中的硬编码密钥、密码和绝对路径。
- 为 Neo4j schema、数据字段和关系类型建立文档。
- 为 MCDM、意图解析 JSON 清洗、GitHub URL 解析写单元测试。

### 第二阶段：把图谱变成可信科研数据资产

- 为每个 Tool、Task、Modality、Algorithm 增加 `source_url`、`source_type`、`extraction_model`、`extraction_time`、`confidence`、`review_status`。
- 建立数据版本号，例如 `kg_version` 和 `embedding_version`。
- 加入文献数据源，例如 PubMed、bioRxiv、OpenAlex 或 Semantic Scholar。
- 把 citations、benchmark_rank、last_updated、license、maintenance_status 做成真实证据字段。
- 设计人工审核闭环：自动抽取 -> 低置信度标记 -> 人工校验 -> 入库。

### 第三阶段：增强推理稳定性

- 将意图解析 schema 扩展为任务、模态、平台、输入数据对象、样本规模、噪声类型、硬件约束、物种、分析目标。
- 使用 Pydantic 或类似机制校验 LLM 输出，失败时走可解释的 fallback。
- 将每个推荐结论绑定证据对象，报告生成只能引用证据对象，减少幻觉。
- 为常见任务构建 golden set，做推荐结果回归测试。
- 在报告中区分“直接证据”“间接证据”“算法迁移假设”。

### 第四阶段：提升检索与决策能力

- 将 embedding 检索迁移到 Neo4j Vector Index、FAISS、Milvus 或 Qdrant。
- MCDM 权重从前端滑块传入后端，并写入最终报告。
- 引入任务特异性 Benchmark 数据，而不是统一占位 rank。
- 增加工具兼容性推理，例如 AnnData、SeuratObject、SingleCellExperiment、h5ad、loom。
- 支持 workflow 推荐，不只推荐单个工具，例如 QC -> normalization -> integration -> clustering -> annotation。

### 第五阶段：产品化与自动化

- 将 LangGraph 后端拆成 API 服务，Streamlit 只负责展示。
- 增加任务队列，用于批量爬取、抽取、embedding、入库和质量检查。
- 增加结构化日志、审计日志、失败重试和运行监控。
- 建立每日/每周自动更新流程，持续刷新 GitHub 和文献证据。
- 增加导出功能：推荐报告、证据表、Cypher 查询结果、可复现实验脚本。

## 建议的近期优先级

近期不要急着继续堆 UI 或扩大 Prompt。最值得先做的是：

1. 先补工程地基：依赖文件、配置模板、密钥清理、路径清理、基础测试。
2. 再补数据可信度：来源、版本、置信度、人工审核状态。
3. 再补推理 schema：把用户需求从两个字段扩展到真实科研决策所需字段。
4. 再补证据排序：把 citations、benchmark、维护状态、许可证、硬件成本纳入真实 MCDM。
5. 最后再扩前端：前端应该展示证据链和决策过程，而不是只包装聊天体验。

只有先把这五件事做好，scKG-Atlas 才能从一个 MVP 逐步长成真正可维护、可扩展、可验证的单细胞智能决策基础设施。
