# scKG-Agent 1.x 到 2.0 执行 Agent 迁移图

版本：1.0  
日期：2026-07-10  
主规约：`docs/DEV_SPEC_2.0.md` 2.0.3  

## 1. 迁移原则

迁移采用渐进替换：保留已通过测试的 KG、RAG、evidence governance、trace、dashboard 和 operational memory；在它们旁边增加 2.0 schema、DataProfiler、ToolContract 和执行平面。旧推荐与报告链继续作为 baseline，直到新的执行闭环具有独立测试和替代入口。

```text
保留 1.x 可复用能力
-> 适配 2.0 schema
-> 新建受控执行平面
-> 双轨回归
-> 新入口稳定后再冻结旧入口
```

## 2. 迁移映射

| 旧模块/路径 | 当前职责 | 2.0 目标职责 | 处理方式 | 目标 Phase | 依赖条件 | 风险 |
| --- | --- | --- | --- | --- | --- | --- |
| `core/constraints.py` | 解析并归一化研究约束 | RequirementSpec 的 deterministic parser | 适配 | Phase 1 | execution models schema | 避免破坏 1.x state dict |
| `agent/states.py` | LangGraph state | Thread State + execution state 引用 | 适配 | Phase 2 | RequirementSpec/DataProfile/WorkflowPlan | state 膨胀与兼容性 |
| `agent/workflow.py` | 固定推荐/迁移/报告图 | Parent Agent + deterministic Router | 包装后渐进适配 | Phase 2-4 | Router states、approval、planner、executor | 不能一次性重写主链 |
| `core/agent_runtime.ToolExecutor` | Python tool-call budget/trace | 保留为 Parent tool runtime | 保留 | Phase 0+ | 明确命名边界 | 易与生信 executor 混淆 |
| `connectors/graph_client.py` | Neo4j/offline KG 查询 | Graph service / Contract query input | 适配 | Phase 2 | 稳定 schema 与只读 service API | live/offline 结果漂移 |
| `core/evidence_policy.py` | formal evidence gate | 文献、retrieval、execution authority 分层 | 保留并扩展 | Phase 2-4 | execution claim types | 不得放宽现有 gate |
| `engine/evidence_discovery_index.py` | chunk index、sparse/dense/RRF | execution knowledge retrieval | 适配 | Phase 2 | 统一 EvidenceChunk、claim types | dense 为空、coverage 低 |
| `engine/evidence_rag_pipeline.py` | governed hybrid/fallback RAG | 参数、输入、失败模式、metric 检索 | 适配 | Phase 2 | ToolContract/source spans | snippet 直接变参数风险 |
| `data_pipeline/*source*` | 文献发现、去重、验证、抽取 | source ingestion 子系统 | 保留 | Phase 0+ | source registry governance | publisher/PDF 差异 |
| `engine/workflow_recommender.py` | deterministic plan template | baseline/template provider | 冻结为 baseline，必要时包装 | Phase 2 | executable PlanCompiler | 不能冒充 executable plan |
| `engine/workflow_decision.py` | step-level plan-only demo | Phase 2 对照与 UI fallback | 保留 | Phase 2/6 | 新 planner 输出 adapter | 双套 schema 漂移 |
| `engine/mcdm_calculator.py` | 文献/元数据推荐评分 | 旧 baseline；新 Decision Engine 读取 CandidateEvaluation | 拆分 | Phase 4 | real run aggregation、Pareto | 伪精确分数延续 |
| `engine/semantic_hallucination_auditor.py` | report claim audit | 加 execution/artifact claim audit | 适配 | Phase 4/6 | ValidationResult/RunContextPack | 规则覆盖不足 |
| `core/trace_context.py` | stage JSONL trace | agent + execution + repair trace | 扩展 | Phase 3 | execution schemas | 旧 trace consumer 兼容 |
| `observability/` | 1.x trace/RAG/memory dashboard | 管理端真实 run/validation/repair 展示 | 适配 | Phase 6 | real execution artifacts | UI 先于 backend |
| `app.py` | Chat + KG + admin views | 用户授权、执行状态、结果/复现包入口 | 适配 | Phase 6 | application service 稳定 | callback 复制业务逻辑 |
| `core/reflection_memory.py` | operational memory | 四层 memory 中的偏好候选和 episodic lesson | 适配 | Phase 4/6 | confirmation gate、ReflectionEvent v2 | 推断偏好误写长期记忆 |
| `core/subagent_runtime.py` | disabled read-only contract | 可选 Evidence/Repair Critic Specialist | 冻结 | Phase 6 以后 | 主链闭环和评测证明收益 | 协调税、权限扩张 |
| `engine/algorithm_representation_v2.py` | 多视图探索性迁移表示 | 非 MVP migration research branch | 冻结/保留 | 可选 Phase 5+ | source coverage 与 gold eval | 分散主线资源 |
| `engine/isomorphism_analyzer.py` | legacy embedding cosine recall | legacy baseline only | 废弃为主路径 | Phase 0 | 替代说明已存在 | 黑盒向量被误用 |
| `data/scKG_embeddings_backup.jsonl` | legacy vectors | regression artifact | 保留但不加载到主推荐 | Phase 0+ | audit label | 体积、来源与质量 |
| `eval/` 1.x artifacts | recommendation/migration/workflow 评测 | Track A regression | 保留 | Phase 0+ | protocol versioning | 与 execution 指标混淆 |
| 不存在：`core/execution_models.py` | 无 | 2.0 canonical schemas | 新增 | Phase 1 | 规约冻结 | schema 过度设计 |
| 不存在：`engine/data_profiler.py` | 无 | matrix-level AnnData profile | 新增 | Phase 1 | AnnData fixture | 数据状态误判 |
| 不存在：`contracts/` | 无 | versioned ToolContract registry | 新增 | Phase 1 | source review、runtime version | contract 与实际工具漂移 |
| 不存在：`execution/environment_registry.py` | 无 | candidate environment metadata/gate | 新增 | Phase 1 | scRNAseq smoke | import 成功被误当 integration |
| 不存在：`engine/execution_planner.py` | 无 | dry-run executable DAG compiler | 新增 | Phase 2 | Phase 1 schemas/contracts | 未授权计划被误标 ready |
| 不存在：`execution/local_controlled_executor.py` | 无 | 单用户受控 worker | 新增 | Phase 3A-E | execution-gated contract、security tests | 无 OS 隔离 |
| 不存在：wrapper/validator/probe | 无 | Scrublet run、artifact validation、probe | 新增 | Phase 3A-E | fixture、environment qualification | synthetic/scientific claim 混淆 |
| 不存在：RepairPolicy | 无 | bounded deterministic repair | 新增 | Phase 4 | failed run taxonomy | 自动修复越权 |
| 不存在：Packager | 无 | reproducibility package | 新增 | Phase 3A-E | complete run manifest | 不完整复现声明 |

## 3. 迁移顺序与回滚点

1. Phase 1 只新增 schema、profiler、planning-gated Scrublet contract 和 environment registry；不接入现有主图执行。
2. Phase 2 新 planner 先以独立 API 生成 `dry_run`，旧 workflow demo 保持可用。
3. Phase 3 通过独立 controlled worker qualification 后，才允许在 Parent route 中提出执行授权。
4. 每个阶段保留旧 Track A 回归；新功能失败时回滚入口，不删除旧模块或 artifact。
5. 只有新入口覆盖测试、迁移文档和 UI adapter 后，旧入口才能标记 deprecated。

## 4. 明确不做的大爆炸迁移

- 不机械搬迁 `core/engine/observability` 到新目录；
- 不重写完整 `agent/workflow.py` 后再补测试；
- 不把 `ToolExecutor` 改名后冒充 `LocalControlledExecutor`；
- 不把旧 WorkflowRecommendation 直接扩字段后称为 executable plan；
- 不删除旧 eval artifacts；
- 不在 Phase 1 引入 MCP、subagent、Docker 或云部署。

