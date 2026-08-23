# scKG-Atlas Agent 简历与技术面试事实审计

> 审计日期：2026-07-27
>
> 审计范围：当前工作区代码、数据、配置、测试缓存、运行产物和可读取的 Git 历史
>
> 审计原则：区分已实现、部分实现、仅规划和未实现；不将未来规划包装为当前能力。

## 0. 审计口径与限制

- 当前 Git `HEAD` 为 `34da2f52981ca09b269f35ec776309cd34ae47ba`。
- Git 历史中的 `DengJingye` 和 `17823661217` 两组身份均由项目作者本人确认属于同一人。
- 项目由作者从 0 独立搭建，没有其他人工开发者；开发过程中广泛使用 AI-assisted/vibe coding。由于未做逐行 provenance 记录，无法可靠区分每一行代码由本人还是 AI 辅助生成。
- 更准确的个人贡献口径是：作者独立负责问题定义、系统取舍、数据和证据治理、实现组织、调试、验收与持续迭代，并使用 AI 作为编码和研究辅助工具。
- 当前 `.git/index` 读取出现 `unable to map index file: Operation timed out`。因此，HEAD 之后的工作区内容可以通过文件和运行产物证明存在，但无法从当前 Git 索引精确恢复所有未提交变更的作者和时间。
- 本次为只读事实审计，没有重新执行科学数据集或全量测试。最后保存的完整测试结论为 `349 passed, 6 warnings`；当前 pytest 缓存包含 369 个 node ID，但不能据此声称 369 项当前全部通过。

## 一、项目定位

### 1.1 解决的问题

scKG-Agent 将单细胞分析需求转换为有证据、有输入约束、可审批、可执行、可验证和可复现的分析决策，而不只返回一个工具名称或一段未经验证的代码。

系统当前形成两类主要能力：

1. 知识与规划：工具发现、证据检索、输入输出检查、候选比较、dry-run workflow 和实验性迁移假设。
2. 受控执行：数据画像、合同校验、环境校验、plan-specific approval、固定 wrapper 执行、结果验证、有界修复、Pareto 决策和复现包。

### 1.2 目标用户

- 希望选择和比较单细胞分析方法的研究人员；
- 需要可运行流程、参数解释和结果验证的生信初学者；
- 需要审核数据、环境、证据和运行结果的本地维护者；
- 希望在不上传表达矩阵的前提下使用 Agent 的隐私敏感用户。

### 1.3 输入与输出

输入包括：自然语言问题、可选 `.h5ad` 文件、项目偏好、已登记数据 artifact、数据访问授权和执行审批。

输出包括：

- 工具候选、适用条件、限制和 source span；
- `DataProfile`、`ActionBundle`、`WorkflowPlan`；
- execution blocker、approval fingerprint 和 Router 状态；
- 固定工具运行 artifact、`ValidationResult`、repair lineage；
- `CandidateEvaluation`、Pareto `DecisionResult`；
- Level 2 reproducibility package、trace 和 audit。

### 1.4 与相邻系统的区别

| 对照对象 | scKG-Agent 的真实差异 |
|---|---|
| 普通聊天机器人 | Router、ToolContract、Evidence Gate、Approval 和 Validator 可以否决 LLM；不允许 LLM 直接决定执行权限。 |
| 普通 RAG | 区分 catalog、source-bound、formal、candidate 和 hypothesis；检索命中不能自动成为正式证据。 |
| 传统工具推荐系统 | 不只做排名，还能画像数据、生成计划、受控执行固定工具、验证结果、修复并打包。 |
| 通用代码 Agent | 不接受任意 shell 或任意生成代码，只执行审核过的结构化 wrapper。 |

### 1.5 当前最准确名称

**scKG-Agent 2.x：本地优先、证据治理、合同约束的单细胞分析规划与受控执行 Agent。**

当前仓库仍存在命名漂移：README 和 app 使用 `scKG-Atlas Agent`，规约使用 `scKG-Agent 2.0`，产品方向又称 `scKG Local Research Workbench`。正式求职材料应统一一种名称。

## 二、完整运行链路

当前仓库不是一条完全统一的 Agent 链，而是三条运行链并存。

### 2.1 主 Streamlit 对话链

```text
用户问题
-> app._run_agent
-> 遗留 LangGraph traced workflow（LangGraph 可导入时）
-> intent_parser
-> hard_constraint
-> mcdm_scorer 或 migration_engine
-> report_generator
-> reflection
-> trace collector
```

| 节点 | 输入与输出 | 核心实现 | 外部依赖 | 条件与回退 |
|---|---|---|---|---|
| UI dispatch | query、conversation、memory、uploads -> state | `app.py::_run_agent` | Streamlit | LangGraph traced runner 存在时优先走遗留链；不存在时才调用 Research Chat。 |
| Intent Parser | query -> `ResearchConstraints` | `agent.workflow.parse_intent_node` | 显式授权后可调用 LLM | LLM 不可用时确定性回退。 |
| Hard Constraint | constraints -> candidates/retrieval | `agent.workflow.hard_constraint_node` | 本地 KG 优先，Neo4j 可选 | 有候选进入 MCDM，无候选进入 migration。 |
| MCDM | candidates/evidence -> scored tools | `agent.workflow.mcdm_scoring_node` | Evidence Gate、MCDM | 无 main evidence 时不能形成强推荐。 |
| Migration | no candidates -> migration hypothesis | `agent.workflow.migration_reasoning_node` | KG、相似度、legacy recall signal | 输出必须保持 exploratory，不得成为 formal evidence。 |
| Report | score/migration/context -> final report | `agent.workflow.generate_report_node` | 可选 LLM、deterministic fallback | semantic auditor 检查 unsupported claim。 |
| Reflect | final state -> memory/reflection event | `core.reflection_memory.reflect_agent_run` | SQLite/JSONL | 不允许写 formal evidence 或自动启用 skill。 |

关键缺陷：`app.py:1426-1459` 显示，LangGraph 正常安装时主聊天仍优先走遗留推荐链；更适合当前产品定位的 `ResearchChatService` 反而是 import 失败 fallback。这与“统一 Research Chat”的文档口径不一致，也是此前不同问题输出相似模板的重要原因。

### 2.2 Bounded Parent / Research Chat 链

```text
自然语言问题
-> intent-specific protocol
-> adaptive retrieval decision
-> KG hard filter + BM25 / Hybrid
-> EvidenceGraphQuery
-> ActionBundleRetriever
-> ToolContract / Environment lookup
-> optional DataProfile / WorkflowPlan
-> DeterministicRouter
-> direct answer / dry-run / blocker / next action
```

核心实现：

- `agent/research_chat_service.py::ResearchChatService`
- `agent/bounded_parent_agent.py::BoundedParentAgent`
- `agent/audited_parent_agent.py::AuditedParentAgent`
- `core/deterministic_router.py::DeterministicRouter`

Research Chat 区分 recommendation、workflow、caveat comparison、migration exploration 和 evidence QA。明确 workflow、Top-k caveat 和已知工具输入查询优先 KG+BM25；工具发现、迁移、参数和歧义查询可以使用 governed Hybrid。路由由确定性规则决定，不由 LLM 决定。

### 2.3 受控执行链

```text
RequirementSpec
-> AnnDataProfiler
-> WorkflowPlan Compiler
-> DeterministicRouter
-> data grant / environment approval / execution approval
-> LocalControlledExecutor
-> tool-specific Validator
-> bounded RepairPolicy（必要时）
-> CandidateAggregator
-> ParetoDecision
-> ReproducibilityPackager
```

`ExecutionOrchestrator` 状态机：

```text
CREATED -> PROFILED -> PLANNED -> WAITING_APPROVAL
-> RUNNING -> VALIDATING -> REPAIR_PENDING
-> AGGREGATING -> DECIDING -> PACKAGING
-> COMPLETED / BLOCKED / FAILED
```

主要状态字段包括 request/plan/run/candidate ID、parent run、contract/environment、input/parameter hash、approval、repair count、validation、artifact hash、decision 和 package。

`ExecutionUIService` 只提供薄 UI service；`LocalUserService` 负责 allowlist、approval consumption、用户 workspace、固定 executor、取消和 ownership。Parent Agent 无权覆盖 Router、Approval 或 Validator。

## 三、Agent 与工作流

### 3.1 LangGraph

真实使用 `StateGraph`。`build_sckg_graph()` 包含：

```text
intent_parser
-> hard_constraint
-> has_candidates ? mcdm_scorer : migration_engine
-> report_generator
-> END
```

Graph State 包含：

- `user_query`、`extracted_constraints`；
- `candidate_tools`、`tool_candidates`、`retrieval_results`；
- `scored_tools`、`migration_paths`、`workflow_recommendations`；
- `decision_report`、`context_pack`；
- conversation/project/upload/runtime context；
- KG diagnostics、final report、hallucination audit、step/error。

当前 LangGraph 没有 checkpoint、循环、图内 retry、human interrupt 或 repair edge。复杂执行状态机位于普通 Python Orchestrator 中。因此，LangGraph 是真实能力，但使用深度有限。

### 3.2 为什么适合 LangGraph

该系统存在共享状态、候选/迁移分支、审批中断、可恢复执行、repair lineage 和 audit，长期适合图式编排。但当前 LangGraph 只有单次分支，若只看现有五节点 DAG，普通顺序 Python 也能完成。简历不应写成“复杂 LangGraph 多 Agent 编排”，更准确是“使用 LangGraph 实现中心化决策 DAG，并在独立执行状态机中实现审批与修复闭环”。

### 3.3 Memory

`core/user_store.py` 与 `core/unified_memory.py` 默认使用 `SCKG_HOME/state/workbench.sqlite3`，支持：

- explicit preference；
- pending/confirmed inferred preference；
- episodic run summary；
- reflection event；
- deduplicated skill candidate；
- conflict、export、delete 和 user isolation。

Memory 被明确标记为 `scientific_authority=false`，不能作为科学证据。当前完整 episodic/reflection context 尚未稳定进入主聊天，主链主要使用 project key/value，因此属于部分实现。

### 3.4 多 Agent、Function Calling 与 MCP

- 多 Agent：没有真实自治多 Agent。当前为中心化 Parent Agent 加确定性 specialist-like service。
- Subagent：有只读 contract、深度和预算，但默认 `enabled=false`。
- Function Calling：有 Pydantic 参数校验的内部 `ToolRegistry/ToolExecutor`，但没有模型原生 `bind_tools`/`function_call` 闭环。
- MCP：未实现 server。
- 工具执行：只支持固定 wrapper，不支持任意生成代码执行。

## 四、RAG 与知识图谱

### 4.1 数据和图谱规模

| 资产 | 当前规模 |
|---|---:|
| scRNA-tools catalog | 1,847 行 |
| canonical Tool 节点 | 1,839 |
| canonical Task | 15 |
| SourceDocument v2 | 37 |
| source-bound evidence chunks | 783 |
| dense vectors | 773 x 1,024 |
| catalog-only chunks | 1,847 |
| formal publication rows | 28；推荐允许 0 |
| formal benchmark rows | 14；推荐允许 0 |
| Catalog KG | 7,537 节点 / 17,667 边 |
| Decision Graph | 1,058 节点 / 1,318 边 |
| ToolContract | 6 |
| qualified tools | 4 |

Catalog KG 的 2,896 个 Publication 节点来自目录 publication/preprint metadata，不代表 2,896 篇已人工审核论文。当前 formal publication 只有 28 条且全部冻结。

### 4.2 Chunk 与 embedding

- `data/indexes/evidence_chunks.jsonl`：783 条 source-bound/controlled chunk；
- `data/indexes/scrna_tools_catalog_chunks.jsonl`：1,847 条 catalog-only chunk；
- chunk 策略：目标 500 tokens、最大 700、overlap 80，支持 page/section aware；
- `data/indexes/evidence_vectors.npy`：773 个本地 `BAAI/bge-m3` 归一化向量；
- model revision、source digest、chunk digest 和 build ID 写入 `evidence_index_manifest.json`；
- source、模型 revision 或 chunk 顺序变化会使索引失效；
- dense 不可用时回退 KG+BM25，不调用云 embedding。

### 4.3 Hybrid Retrieval

```text
Query classification
-> task/entity normalization
-> KG hard filter
-> SQLite FTS5 BM25
-> optional local BAAI/bge-m3
-> RRF fusion
-> governance-aware rerank
-> EvidenceContextPack
```

Rerank 会提升明确工具、task、claim type、source-bound chunk 和 source document，降低 catalog-only、title-only 和缺少 source span 的结果。

### 4.4 Neo4j

`Neo4jClient` 真实使用官方 driver，包含 retry、routing/Bolt fallback 和 OfflineGraph fallback。但候选检索刻意优先 canonical local KG，以避免陈旧 Neo4j 绕过 Evidence Gate；Neo4j 当前属于可选投影，不是唯一事实源。

### 4.5 检索结果如何进入回答

Hybrid hit 保存 source ID、tool、task、claim type、title、source span、chunk text 和治理状态，经过 `EvidenceContextPack` 进入回答或可选 LLM context。检索 context 只能支持回答和候选发现，不能直接修改 MCDM、ToolContract、formal TSV 或 trusted graph。

## 五、Evidence Gate 与可信性

### 5.1 main evidence 条件

`trusted_core` 由 formal row、source validation、claim span、review 状态、推荐 scope 和 canonical tool/version 联合生成，不由 LLM 自行声明。

- main publication：source-bound、canonical、核心工具/版本、允许 recommendation 的 `paper_support`。
- main benchmark：只接受 `benchmark_rank` 或 `benchmark_score`。
- `benchmark_result` 永远不能作为主 benchmark evidence。
- citation 数量只能是 popularity/ranking signal，不能独立形成方法有效性证据。

### 5.2 关键违规定义

- `candidate leakage`：candidate、retrieval 或 hypothesis 未晋升却影响可信推荐或执行。
- `unsupported claim`：工具、排名、数值、兼容性或迁移结论没有允许证据支持。
- `trusted non-main violation`：证据虽为 trusted，但 metric/scope 不满足 main 条件却进入 top-k。
- `blocked correctness`：应阻断案例被正确阻断，且 `ExecutionRequest=0`。

### 5.3 阻断和降级

以下情况会阻断或降级：

- 没有 main recommendation evidence；
- unresolved count source；
- planning/execution contract 未通过；
- environment 未登记或未资格化；
- data grant、approval 或 fingerprint 不匹配；
- hash mismatch、path escape、unknown wrapper；
- migration 仅由 legacy embedding 支持；
- source metadata mismatch 或 candidate quarantine。

不确定性记录在 DecisionReport risks、missing evidence、blockers、migration limitations、hypothesis 和 audit warning 中。

### 5.4 人工审核

publication/benchmark promotion flow 已实现，可将完成 source span、reviewer 和 numeric benchmark scope 的结果回写 formal TSV。但当前：

- 28 条 publication 全部存在 `title_only_claim_span` 和 `reviewer_identity_unclear`，推荐允许数为 0；
- 14 条 benchmark 全部是 `qualitative_only`，推荐允许数为 0；
- source chunks 不会自动晋升 formal evidence。

## 六、实际评测体系

| 评测版本 | 数据集规模 | 指标与结果 | 对照/状态 | 证据路径 |
|---|---:|---|---|---|
| DeepSeek ablation v0.2 | 12 query | pure LLM top-k 0.667、hallucination 0.201；Evidence Gate top-k 1.0、hallucination 0 | 已运行，四路对照 | `eval/ablation_deepseek_aura_v0_2_blind_after_mcdm_qual_benchmark_fix_v2/ablation_summary.json` |
| Workflow eval v0.1 | 8 | pass 1.0、candidate recall 1.0、required-step recall 0.982 | 已运行 | `eval/workflow_eval_v0_1_summary.json` |
| KG v2 | 9 | positive retrieval recall 1.0、MRR 0.767、provenance 1.0 | 已运行；旧图且正例偏多 | `eval/kg_v2/kg_v2_summary.json` |
| Context/Migration v0.12 | 35 | leakage/trusted violation/negative false migration 均 0；部分 caveat/compatibility 仅 0.286-0.714 | 已运行 | `eval/context_pack_v0_12_full_offline_migration_eval_summary_v2.json` |
| Phase 6 baseline | 8 | A2 recall 0.991、source coverage 0；B3 completion 0；B4 repair completion 1 | 部分 baseline 未运行 | `eval/phase6/baseline_summary.json` |
| Portfolio A2/A3/A4 | 48 gold / 48 LLM call | A4 raw parameter legality 1.0、source coverage 0.938；治理后 unauthorized/unsupported 0 | 已运行；raw blocker accuracy 约 0.604 | `.sckg_exec/evaluations/portfolio-v2-full-20260717/benchmark_summary.json` |
| Retrieval v2 | 96 | KG+Hybrid+Contract Recall@10 0.972、Precision@10 0.912、MRR 0.991、span hit 1.0、false support 0、p95 37 ms | 已运行，六路线消融 | `data/evaluation/retrieval_eval_v2/summary.json` |
| Agent Quality v2 | 80 x 3 = 240 | correctness/stability/compliance 1.0、unsupported 0、p50 47 ms、p95 160 ms | 确定性冻结集，不代表开放世界 | `data/evaluation/agent_quality_v2/summary.json` |
| Memory Quality | 30 | 30/30、authority/user-isolation violation 0 | 已运行 | `data/evaluation/memory_quality_v2/summary.json` |
| Continuous Eval | 51 metrics | 44 measured，39/42 release gate；3 regression，状态 watch | 已运行 | `data/evaluation/continuous_agent_quality_v1/summary.json` |
| External stability | 16 x 3 planned | completed 0 | 未授权外发，not_run | `data/evaluation/external_agent_stability_v2/summary.json` |
| RAGAS | - | 无 Context Precision/Recall/Faithfulness 实际分数 | 只有入口，not_run | `data/evaluation/ragas_diagnostic_v2.json` |
| GSE108313 pilot | eval 4,060 cells | Scrublet AUPRC 0.491；scDblFinder 0.508-0.510；500 bootstrap | 已运行，dataset-scoped | `.sckg_exec/datasets/GSE108313/phase5c/20260712T024054467635/phase5c_summary.json` |
| scIB pancreas pilot | 16,382 cells；eval 3,000 | Harmony mixing/biology 0.912/0.585；Scanorama 0.805/0.548 | 已运行；两个均 Pareto，Harmony 推荐 | `.sckg_exec/datasets/scIB-pancreas/scientific_pilot_summary_20260716T083044Z.json` |

没有真实 RAGAS 结果、真实组内用户评测、线上生产指标或开放世界 Agent 成功率。

## 七、数据和工程规模

| 项目 | 数量/状态 |
|---|---|
| Python 文件 | 389 |
| 核心技术目录 Python 文件 | 167 |
| 测试模块 | 103 |
| 显式 test 函数 | 337 |
| pytest 缓存 node ID | 369 |
| 最后保存的完整 pytest 结果 | 349 passed，6 warnings |
| Catalog 工具 | 1,847 |
| Qualified 工具 | 4 |
| Planning-only 工具 | 2 |
| Qualified 任务族 | Doublet Detection、Batch Integration |
| ToolContract | 6 |
| LLM provider 实现 | 1 个 OpenAI-compatible adapter，可配置 DeepSeek/OpenAI-compatible endpoint |
| FastAPI | 无 |
| Streamlit | 有 |
| Docker | 无 |
| MCP | 无 |
| pytest | 有 |

工程能力包括 JSONL/SQLite trace、日志脱敏、缓存、Neo4j retry、LLM retry、dense warmup、进程 timeout/cleanup、多配置实验、用户隔离、approval 防重放和错误保留。

项目支持 `python -m cli.sckg launch` 启动本地 UI。真正执行仍依赖对应 Runtime Pack、权限和审批。

## 八、实际完成与规划边界

| 能力 | 已完整实现 | 部分实现 | 仅规划/未实现 | 证据 |
|---|---|---|---|---|
| LangGraph 编排 |  | 是 |  | 真实 5 节点 DAG；无循环/checkpoint/interrupt。 |
| Hybrid KG-RAG | 是 |  |  | FTS5 + bge-m3 + KG + RRF + rerank。 |
| Neo4j |  | 是 |  | 可连接；local canonical graph 仍是事实源。 |
| Evidence Gate | 是 |  |  | 审计、冻结、main evidence gate、promotion flow。 |
| Function Calling |  | 是 |  | 内部 typed tools；无原生模型 tool calling。 |
| MCP |  |  | 是 | 无 server。 |
| 多 Agent |  |  | 是 | Subagent contract 默认关闭。 |
| Memory |  | 是 |  | 存储治理完整；主链完整 recall 不足。 |
| 自动执行生信工具 |  | 是 |  | 四个固定 wrapper；全局 policy 默认 disabled。 |
| sealed migration |  | 是 |  | 可生成 hypothesis；不能作为科学事实或自动执行。 |
| 人工审核 |  | 是 |  | review/promotion/writeback 有；当前无 ready row。 |
| Agent 评测 | 是 |  |  | retrieval、agent、memory、continuous、scientific。 |
| FastAPI |  |  | 是 | 无服务接口。 |
| Docker |  |  | 是 | 当前 executor 不是 OS sandbox。 |
| 线上演示 |  |  | 是 | 只有 localhost Streamlit。 |

## 九、项目演进和失败案例

### 9.1 演进

1. 早期采用中心化 LangGraph：意图解析、硬约束、MCDM/迁移和报告。
2. 引入知识图谱表达工具、任务、输入输出和迁移关系。
3. 发现 catalog metadata 与 AI 审核 TSV 不足以支持可信推荐，引入 Evidence Gate。
4. 将原文 chunk 作为 evidence discovery，将 formal TSV 限定为可复核事实。
5. 引入 ToolContract、DataProfile、WorkflowPlan 和确定性 Router。
6. 加入 Scrublet/scDblFinder，再扩展 Harmony/Scanorama，形成两个任务族。
7. 增加 approval、fixed wrapper、Validator、Repair、Pareto 和 Level 2 package。
8. 重建 canonical graph、FTS5+bge-m3 Hybrid RAG、Research Chat 和 Continuous Evaluation。

### 9.2 真实失败与技术反思

1. **AI 审核 AI 的证据闭环**：28 条 publication 和 14 条 benchmark 最终全部冻结，说明泛化 `human_review` 不能替代 source span 和可追踪 reviewer。
2. **错误 DOI/PDF**：`10.1093/bib/bbad418` 实际指向 PanomiR，证明 DOI/title/PDF 内容必须联合验证并 quarantine。
3. **工具级重复 PDF**：同一论文曾按不同工具重复保存，后来引入 source-level registry 和共享 `source_id`。
4. **整工具 LLM embedding 黑盒**：旧 `scKG_embeddings_backup.jsonl` 无法解释来源和质量，现已降级为 experimental recall signal。
5. **qualitative benchmark 过度支撑**：`benchmark_result` 曾被当作强 benchmark，现只允许 `benchmark_rank/score` 成为 main evidence。
6. **伪 BM25 与查询延迟**：早期 lexical overlap 每次读取 JSONL，后改为 FTS5、本地 dense、RRF 和缓存。
7. **KG junk task 与 projection drift**：旧图出现 hash/文件片段 task，现统一为 15 个 canonical task 并报告 drift。
8. **答案模板化**：Research Chat 已设计多种 intent protocol，但主 UI 仍优先走遗留 LangGraph，导致行为未真正统一。
9. **受控进程不等于沙箱**：LocalControlledExecutor 只能称 application-level control，不能声明 OS-level isolation。
10. **多 Agent 设想未落地**：Hermes/OpenClaw 风格 subagent 和自进化 skill 仍停留在受控候选/关闭状态。

## 十、个人贡献

经作者确认：

- 项目由作者从 0 独立搭建，没有其他人工开发者；
- Git 中 `DengJingye` 和 `17823661217` 两组身份均属于作者本人；
- 开发过程使用了大量 AI-assisted/vibe coding；
- 无法可靠区分每一行代码是否由 AI 辅助生成；
- 作者负责最终的问题定义、架构选择、数据准备、任务拆解、审查、调试、验收和迭代决策。

可合理归入个人负责范围：

- 项目问题定义和产品方向；
- 中心化 Agent、LangGraph 和受控执行架构；
- 工具目录、论文/PDF、formal evidence 与图谱资产建设；
- Hybrid RAG、Evidence Gate 和迁移假设边界；
- ToolContract、审批、执行、验证、修复和复现包；
- Streamlit 本地工作台；
- 测试、评测体系和中文开发规约；
- 使用 AI 辅助进行代码生成、调试、研究和文档迭代。

软著材料当前尚未开始，不能写成“已完成软著”或“已获授权”。可以作为后续工作单独准备。

## 十一、可用于简历的事实

### 11.1 项目定位事实

- 独立构建本地优先、证据治理和合同约束的单细胞分析 Agent。
- 系统同时覆盖知识检索、工作流规划和固定工具受控执行。

### 11.2 技术架构事实

- 使用 LangGraph 实现中心化决策 DAG。
- 使用 KG + SQLite FTS5 + 本地 bge-m3 + RRF + governance rerank。
- 使用 Pydantic ToolContract、Deterministic Router 和 plan-specific approval 建立确定性安全控制面。
- 实现 LocalControlledExecutor、tool-specific Validator、bounded Repair、Pareto Decision 和 Level 2 package。

### 11.3 数据规模事实

- 1,847 条 scRNA-tools catalog；
- 7,537 节点/17,667 边 Catalog KG；
- 1,058 节点/1,318 边 Decision Graph；
- 37 个 SourceDocument、783 个 source-bound chunk、773 个本地向量；
- 6 个 ToolContract，4 个工具完成 integration/scientific-pilot qualification。

### 11.4 评测事实

- 96-case retrieval evaluation 中，KG+Hybrid+Contract 达到 Recall@10 0.972、Precision@10 0.912、MRR 0.991、source-span hit 1.0、false support 0。
- 240-run 确定性 Agent regression 中，冻结集 correctness/stability/compliance 为 1.0；必须注明是确定性回归集。
- GSE108313 和 scIB pancreas 完成 dataset-scoped scientific pilot，并生成 500 次 bootstrap CI 和 Level 2 package。

### 11.5 工程化事实

- 支持数据画像、授权、审批、防重放、用户隔离、取消、trace、failure queue 和路径脱敏。
- 支持 Python/R 多环境下四个固定工具执行。
- 默认 `ExecutionPolicy=disabled`，执行能力不会自动开放。

### 11.6 最有说服力的三个技术难点

1. 将 catalog、source-bound、formal、candidate 和 hypothesis 分层，防止 candidate leakage。
2. 将 LLM 规划与确定性 Router/Contract/Approval/Validator 安全控制面解耦。
3. 在 Python/R 多环境下统一执行、验证、repair lineage、跨工具 Pareto 和复现包。

### 11.7 最有说服力的三个量化结果

1. 1,847 工具目录，7,537 节点/17,667 边 Catalog KG。
2. KG+Hybrid+Contract：Recall@10 0.972、Precision@10 0.912、MRR 0.991。
3. 两个任务族、四个资格化工具、两个公开数据集 scientific pilot。

### 11.8 不能写进简历的内容

- 支持全部 1,847 个工具执行；
- 通用自主生物医学研究 Agent；
- 递归多 Agent 已落地；
- RAGAS 评测通过；
- 生产级 sandbox、Docker、MCP、FastAPI 或云服务已完成；
- 所有回答无幻觉；
- 对所有单细胞数据普遍最优；
- 369 项测试当前全部通过；
- 已完成真实用户试用；
- 已完成或获得软件著作权。

## 十二、证据索引

| 结论 | 代码/数据证据 |
|---|---|
| 主 UI 调度和遗留链优先 | `app.py::_run_agent`，约 1393-1499 行 |
| LangGraph 节点和边 | `agent/workflow.py::build_sckg_graph`，约 1078-1107 行 |
| Graph State | `agent/states.py::ScKGAgentStateModel/ScKGAgentState` |
| Research Chat | `agent/research_chat_service.py::ResearchChatService` |
| Bounded Parent | `agent/bounded_parent_agent.py::BoundedParentAgent` |
| Router 不允许 Parent 覆盖 | `core/deterministic_router.py::DeterministicRouter.route` |
| 执行状态机 | `execution/execution_orchestrator.py::ExecutionOrchestrator` |
| 本地用户执行 | `execution/local_user_service.py::LocalUserService` |
| UI service | `execution/execution_ui_service.py::ExecutionUIService` |
| Hybrid RAG | `engine/hybrid_retrieval.py::HybridRetrievalService` |
| Neo4j 与离线回退 | `connectors/graph_client.py::Neo4jClient`、`connectors/offline_graph.py::OfflineGraph` |
| Evidence Gate | `core/evidence_policy.py`、`engine/evidence_graph_builder.py` |
| formal publication 审计 | `data/evidence_candidates/formal_publication_audit_summary.json` |
| formal benchmark 审计 | `data/evidence_candidates/formal_benchmark_audit_summary.json` |
| source acquisition 问题 | `data/evidence_candidates/source_acquisition_summary.json` |
| canonical 规模 | `data/canonical_knowledge/manifest.json` |
| Catalog KG 质量 | `data/knowledge_graph_v2/quality_report.json` |
| Decision Graph 质量 | `data/decision_graph_v3/quality_report.json` |
| 向量和索引元数据 | `data/indexes/evidence_index_manifest.json` |
| Retrieval 评测 | `data/evaluation/retrieval_eval_v2/summary.json` |
| Agent 评测 | `data/evaluation/agent_quality_v2/summary.json` |
| Continuous Eval | `data/evaluation/continuous_agent_quality_v1/summary.json` |
| Doublet scientific pilot | `.sckg_exec/datasets/GSE108313/phase5c/20260712T024054467635/phase5c_summary.json` |
| Batch scientific pilot | `.sckg_exec/datasets/scIB-pancreas/scientific_pilot_summary_20260716T083044Z.json` |
| 当前项目状态 | `docs/status/PROJECT_STATUS_2.0.md` |

## 最终判断

scKG-Agent 已经超出普通 RAG demo：执行层、安全治理、证据边界和评测体系具有真实工程深度。当前最有价值的求职叙事，是“独立构建证据治理与受控执行驱动的垂直科研 Agent”，而不是“通用自主生物医学 Agent”。

现阶段最主要的技术债是：

1. 遗留 LangGraph、Research Chat 和执行 Orchestrator 尚未真正统一；
2. formal publication/benchmark 当前没有可进入主推荐的记录；
3. Memory 完整召回未进入主链；
4. 真实用户试用、RAGAS、服务化和 OS sandbox 尚未完成；
5. Git 索引和版本基线需要修复，才能形成可信的发布与简历证据链。
