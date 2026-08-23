# scKG-Agent 简历撰写项目事实手册

> 用途：将本文完整提供给负责撰写简历或准备面试材料的 GPT。
>
> 本文只解释项目在做什么、为什么这样设计、当前实现到哪里，不直接代写简历。
>
> 事实基准：当前 `SCKG-Agent` 仓库、`docs/DEV_SPEC_2.0.md`、测试与运行产物。

当前产品主线已在 v2.7.2 收束：`ResearchChatService.run_request` 是唯一任务入口，ASK/PLAN/RUN 复用同一个 Bounded Parent Agent 与确定性安全后端；旧 `agent/workflow.py` 只保留为历史 baseline，不再由主 UI 调用。

求职作品集 RC 使用 `python scripts/run_portfolio_acceptance.py` 统一复跑 pytest、Mainline、96-case retrieval、240-run Agent Quality、30-case Memory、四案例 Interview Demo、复现包 hash、Git 完整性和 release privacy gate。RC 保存当前 Git HEAD、dirty/untracked 计数及 release-file worktree digest；这使当前未提交的 2.7.x 工作树可追溯，但在用户确认并正式提交/tag 前不得称为已发布版本。

## 1. 请先理解项目的唯一主线

scKG-Agent 的主线不是“做一个工具知识图谱”，也不是“做一个生信工具推荐网站”。

项目真正要解决的问题是：

```text
如何把用户的单细胞分析目标和真实数据状态，
转化为可以运行、可以验证、失败时可以有限修复、
最终可以交付给别人复现的分析工作流？
```

当前最准确的项目定位是：

> **scKG-Agent 是一个面向单细胞数据分析的可执行科研 Agent。它理解用户的分析目标和真实数据状态，从受治理的单细胞 Action Space 中选择方法、生成工作流，在本地受控执行候选工具，根据运行结果完成验证、有限修复和多目标决策，最终交付可复现的分析代码、结果与报告。**

推荐英文定位：

> **An executable research agent for planning, running, validating, and repairing single-cell analysis workflows.**

更面向用户的一句话是：

> **从“我有一份单细胞数据，应该怎么分析”，走到“流程已经运行、结果经过验证、代码可以复现”。**

## 2. 为什么要做这个项目

单细胞分析的困难不只是“不知道工具名称”。用户通常还需要回答：

- 我的矩阵是 raw counts、log-normalized 还是 scaled？
- 当前工具是否接受这种数据状态？
- 应该使用哪些参数，参数来源是什么？
- 工具能否在当前环境中实际运行？
- 运行失败是数据问题、环境问题还是参数问题？
- 多个候选工具实际表现如何，而不只是论文中如何描述？
- 最终代码、参数、环境和结果能否被另一位研究者复现？

普通聊天机器人或普通 RAG 可以生成一份“看起来合理”的建议，但不能稳定完成文件检查、参数合法性校验、真实工具执行、结果验证、错误修复、资源监控和复现打包。

因此，scKG-Agent 的核心价值不是生成更长的报告，而是完成一个受约束的科研执行闭环。

## 3. 一次任务的完整主流程

```text
用户的科研问题 + 可选单细胞数据
        ↓
理解任务、输出目标和资源限制
        ↓
确定 AnnData / matrix 的真实状态
        ↓
从单细胞 Action Space 检索适用方法
        ↓
检查证据、输入输出、参数、环境和失败条件
        ↓
生成可执行 WorkflowPlan / DAG
        ↓
用户完成数据授权和 plan-specific approval
        ↓
在受控本地环境运行固定工具 wrapper
        ↓
观察 stdout、stderr、artifact、运行时间和内存
        ↓
Validator 判断结果是否完整、合法和可解释
        ↓
允许时进行有预算、可追踪的确定性修复
        ↓
聚合多配置或多工具运行结果
        ↓
通过 Pareto Decision 选择方案或拒绝推荐
        ↓
交付代码、参数、图表、结果、trace 和复现包
```

这条链路中，Agent 不是“想一次就输出答案”，而是：

```text
Observe -> Plan -> Act -> Observe -> Validate
-> Repair or Stop -> Decide -> Package
```

## 4. 为什么它是 Agent，而不只是固定工作流

Workflow 是被规划和执行的对象；Agent 是控制整个闭环的决策主体。

Parent Agent 会根据运行时状态动态决定：

- 当前是普通知识问答、工作流请求还是执行任务；
- 是否需要用户补充数据或授权；
- 是否需要 DataProfile；
- 应检索哪些 ActionBundle；
- 当前计划应继续、等待、阻断还是请求执行；
- 某次失败是否允许修复；
- 是否继续测试其他 candidate；
- 何时停止并输出负结果；
- 在 Pareto frontier 中如何结合用户偏好选择方案。

但 LLM 不拥有无限权限。以下内容由确定性模块控制：

- 文件路径和 hash；
- matrix 状态；
- ToolContract schema；
- 参数类型和范围；
- 数据授权与执行审批；
- wrapper allowlist；
- artifact validation；
- repair 白名单和预算；
- Pareto 计算；
- 停止和安全阻断。

因此当前架构应称为：

> **Bounded Centralized Agent：有边界的中心化 Parent Agent。**

当前不是运行中的多 Agent 系统。DataProfiler、Retriever、Executor、Validator 和 Pareto Engine 都是工具或确定性服务，不应包装成独立 Agent。Subagent contract 已存在但默认关闭。

## 5. 系统的四个支撑平面

### 5.1 Agent 决策平面

职责：理解任务、形成候选计划、选择 route、决定继续/等待/修复/停止。

主要组件：

- Parent Agent；
- ASK/PLAN/RUN 高层决策 DAG；安装 LangGraph 时由 StateGraph 调度，未安装时同节点确定性调度；
- Research Chat intent routing；
- Deterministic Router；
- ActionBundle Retriever。

### 5.2 知识平面

职责：为方法发现、输入要求、参数、失败模式和 source span 提供依据。

主要组件：

- 1,847 条工具目录；
- Catalog Knowledge Graph；
- 严格 Decision Graph / Action Space；
- SQLite FTS5 BM25；
- 本地 BAAI/bge-m3 dense retrieval；
- RRF fusion；
- governance-aware rerank；
- ToolContract 和 source-bound EvidenceChunk。

知识图谱和 RAG 是 Agent 的知识基础，不是产品最终输出。

### 5.3 执行与安全平面

职责：确保数据、参数、工具、环境和权限满足执行条件。

主要组件：

- AnnDataProfiler；
- ToolContractRegistry；
- EnvironmentRegistry / Runtime Pack；
- DataRegistry；
- DataAccessGrant；
- plan-specific ExecutionApproval；
- LocalControlledExecutor；
- wrapper allowlist；
- 用户 workspace 和 ownership gate。

当前 executor 是应用层受控进程执行，不是 OS-level sandbox。

### 5.4 验证与交付平面

职责：判断运行是否成功、结果是否完整、失败能否修复、结论能否复现。

主要组件：

- tool-specific Validator；
- RepairPolicy；
- CandidateAggregator；
- ParetoDecision；
- ReproducibilityPackager；
- trace、audit 和 failure queue。

## 6. KG、RAG 和 Evidence Gate 在主线中的位置

### 6.1 两层知识图谱

系统没有把全部工具都当成可执行能力，而是拆成：

```text
Catalog Graph
  负责大范围工具发现和召回

Decision Graph / Action Space
  只容纳有合同、输入输出、环境、验证规则和 scoped evaluation 的动作
```

“目录中存在某个工具”不等于“Agent 可以推荐或执行该工具”。

### 6.2 Hybrid Retrieval

```text
任务与实体规范化
-> KG hard filter
-> SQLite FTS5 BM25
-> 可选本地 BAAI/bge-m3
-> RRF fusion
-> governance-aware rerank
-> EvidenceContextPack
```

Dense 模型不可用时可以回退 KG+BM25，不默认调用云 embedding API。

### 6.3 Evidence Gate

系统区分：

| 信息层 | 能否直接支持主推荐或执行 |
|---|---|
| Catalog metadata | 不能，只负责发现 |
| Source chunk / RAG snippet | 不能自动晋升，只负责解释和 evidence discovery |
| AI-reviewed candidate | 不能，只进入 review queue |
| Formal source-bound evidence | 满足 gate 后可以支持推荐 |
| ToolContract | 可以约束规划和参数，但本身不能代替科学效果证据 |
| Scientific pilot | 只能支持 dataset-scoped 结论，不能外推普遍最优 |
| Memory | 不能成为科学证据 |
| Migration hypothesis | 不能成为已验证方法 |

Evidence Gate 主要防止：

- candidate leakage；
- unsupported claim；
- qualitative benchmark 被当成数字 benchmark；
- citation 数量被当成方法有效性；
- title-only 论文记录被当成 source-bound claim；
- RAG 命中自动进入可信图谱或执行空间。

## 7. 当前真正完成的任务族

### 7.1 Doublet Detection

工具：

- Scrublet 0.2.3；
- scDblFinder 1.24.0。

已完成：

- Python/R 独立环境；
- ToolContract；
- 固定 wrapper；
- Validator；
- synthetic engineering qualification；
- 多配置、多 seed 评估；
- GSE108313 Cell Hashing PBMC scientific pilot；
- 跨工具 Pareto；
- Level 2 reproducibility package。

### 7.2 Batch Integration

工具：

- Harmony 2.0.0；
- Scanorama 1.7.4。

已完成：

- 独立 CPU 环境；
- ToolContract；
- 固定 wrapper；
- IntegrationValidator；
- development/evaluation probe；
- 多配置、多 seed engineering qualification；
- scIB pancreas scientific pilot；
- 跨工具 Pareto；
- Level 2 reproducibility package。

### 7.3 Cell Type Annotation

工具：

- CellTypist 1.7.1；
- SingleR 2.14.0。

当前只完成 source、planning contract、ActionBundle 和 retrieval admission 准备。环境、真实 qualification 和 scientific pilot 尚未完成，不能写成已经支持执行。

### 7.4 当前能力边界

项目已经用两个独立任务族证明闭环可以迁移，但不能声称支持完整单细胞分析流程，更不能声称支持目录中的 1,847 个工具执行。

## 8. 当前数据与工程规模

| 资产 | 当前事实 |
|---|---:|
| scRNA-tools catalog | 1,847 条 |
| canonical Tool node | 1,839 |
| canonical Task | 15 |
| Catalog KG | 7,537 节点 / 17,667 边 |
| Decision Graph | 1,058 节点 / 1,318 边 |
| SourceDocument v2 | 37 |
| source-bound evidence chunks | 783 |
| local bge-m3 vectors | 773 x 1,024 |
| ToolContract | 6 |
| execution-qualified tools | 4 |
| completed task families | 2 |
| Python files | 396 |
| test modules | 107 |
| explicit test functions | 351 |
| fresh full pytest | 363 passed，18 warnings |

目录中的 publication/preprint metadata 不等于人工审核论文数量。当前 formal publication 为 28 条、formal benchmark 为 14 条，而且都因审核或 source-bound 条件不足而被冻结，不能写成“42 条可信正式证据”。

## 9. 当前主要评测结果

### 9.1 Retrieval Evaluation

96-case 六路线消融中，`KG + Hybrid + ToolContract`：

- Recall@10：0.972；
- Precision@10：0.912；
- MRR：0.991；
- source-span hit：1.0；
- false support：0；
- warm p95：24.406 ms。

这些是冻结 retrieval gold set 上的结果，不代表所有开放问题。

### 9.2 Agent Quality Evaluation

80 个场景、每个 3 次，共 240 次确定性运行：

- correctness/stability/compliance 在该冻结集上为 1.0；
- unsupported claim 为 0；
- p50 约 36 ms；
- p95 约 144 ms。

这属于 deterministic regression，不得表述为开放世界任务成功率 100%。

### 9.3 Doublet Scientific Pilot

GSE108313 evaluation split：4,060 cells。

- Scrublet AUPRC：约 0.491；
- scDblFinder 两个配置 AUPRC：约 0.508-0.510；
- 使用 500 次 bootstrap CI；
- 结论只适用于该数据集和当前预处理；
- HTO 主要覆盖跨样本 multiplet，不能证明普遍性能。

### 9.4 Batch Integration Scientific Pilot

scIB pancreas：16,382 cells，evaluation subset 3,000 cells。

- Harmony：batch mixing ASW 约 0.912，biology conservation ASW 约 0.585；
- Scanorama：约 0.805 / 0.548；
- 两者都在 Pareto frontier；
- 当前数据集 scoped 推荐 Harmony；
- 不能声称 Harmony 在所有数据上普遍最优。

### 9.5 尚未运行的评测

- RAGAS：只有诊断入口，没有正式结果；
- 外部随机模型稳定性：未授权外发，记录为 `not_run`；
- 真实组内用户试用：参与人数为 0；
- 线上生产指标：不存在。

## 10. 本地执行和隐私边界

项目采用本地优先方向：

- 表达矩阵、barcode 和本地完整路径默认不发送给外部 LLM；
- DataProfiler、Router、Contract、Approval 和 Validator 在本地确定性运行；
- 外部 LLM 需要显式 disclosure approval；
- 全局 `ExecutionPolicy` 默认 `disabled`；
- 只有 allowlisted local user、登记数据、有效授权和完全匹配的 approval 才可能执行；
- contract/environment qualified 不等于全局执行已开放；
- 当前没有 Docker/OCI sandbox，不能声称 OS-level isolation；
- 当前没有公共 API、远程多用户服务或云部署。

## 11. 项目演进中的关键技术反思

1. 早期系统更像“工具推荐和报告 Agent”，后来转向真实执行、验证和复现。
2. 曾经存在 AI 生成候选、再由 AI 审核的证据闭环，因此 formal evidence 被保守冻结。
3. 错误 DOI 曾把 PanomiR 论文关联到 cell annotation benchmark，促使项目增加 source metadata validation 和 quarantine。
4. 旧方案将每个工具压缩为一个 LLM profile embedding，缺少来源和解释性，现已降级为 experimental recall signal。
5. qualitative `benchmark_result` 曾被过度使用，现只允许 source-bound rank/score 支持主 benchmark。
6. 早期 lexical retrieval 不是真 BM25且每次解析 JSONL，后来迁移到 FTS5、本地 dense、RRF 和缓存。
7. 旧 KG 出现 junk task 和 projection drift，后来建立 canonical task ontology 和唯一 snapshot。
8. LocalControlledExecutor 只能称受控进程执行，不能包装成安全沙箱。
9. Memory 已统一存储，但完整 episodic/reflection recall 尚未稳定进入主 Agent。

## 12. 作者个人贡献口径

经作者本人确认：

- 项目从 0 独立搭建，没有其他人工开发者；
- Git 中 `DengJingye` 与 `17823661217` 两组身份均属于作者；
- 开发过程中广泛使用 AI-assisted/vibe coding；
- 无法可靠区分每一行代码是否由 AI 辅助生成；
- 作者负责最终的问题定义、架构取舍、数据准备、任务拆解、实现组织、调试、验收和持续迭代。

撰写材料时可以表述为：

```text
独立负责项目从 0 到 1 的问题定义、系统架构、数据与证据治理、
执行闭环、评测和产品原型，并使用 AI-assisted development 提升开发效率。
```

不要写成“所有代码均纯手工编写”，也无需把项目贬低为“只是 AI 生成”。项目价值在于作者完成了持续的问题判断、架构治理、验证和迭代闭环。

软件著作权材料尚未开始准备，不能写成已完成或已授权。

## 13. 撰写简历时应突出什么

请按照以下优先级理解项目：

1. 从自然语言任务和真实数据到可执行、可验证、可复现工作流；
2. Bounded Parent Agent 与确定性安全控制面；
3. 两个任务族、四个工具的真实执行闭环；
4. KG/RAG/ToolContract 共同构成受治理 Action Space；
5. Evidence Gate 防止候选知识越权；
6. Validator、bounded repair、Pareto 和 Level 2 package；
7. retrieval、Agent、scientific pilot 和持续评测结果；
8. 本地优先和审批隔离作为工程边界。

不要把以下内容放在项目主线前面：

- 知识图谱可视化；
- PDF 下载和 chunk 数量；
- Streamlit 页面数量；
- 多 Agent、MCP、Docker；
- 算法迁移和新算法发现；
- Runtime Pack 产品化。

它们分别属于支撑能力、未来路线或工程细节。

## 14. 禁止夸大的内容

不得声称：

- 已支持全部 1,847 个工具执行；
- 已支持完整单细胞或多组学分析全流程；
- 已实现递归多 Agent；
- 已实现任意代码生成和安全沙箱执行；
- 已完成 MCP、FastAPI、Docker 或云部署；
- 已完成 RAGAS 评测；
- Agent 开放世界成功率为 100%；
- 已完成真实用户试用；
- 已完成或获得软件著作权；
- 在所有数据集上某个工具普遍最优；
- 所有 formal evidence 均已人工审核通过。

## 15. 给简历撰写模型的最后要求

使用本文时，请遵守：

1. 先写“用户问题到可复现分析交付”的主线，再写 KG/RAG 和安全工程。
2. 将项目描述为单细胞垂直科研 Agent，不描述为通用生物医学 Agent。
3. 将 LangGraph 表述为可选的中心化 DAG 调度器；主线即使无该依赖也执行同一组节点，不描述为成熟多 Agent 编排。
4. 将四个工具描述为受控执行和 dataset-scoped qualification，不外推全领域性能。
5. 所有量化结果注明对应冻结评测集或公开数据集。
6. 明确区分确定性模块、LLM 能力和用户审批权限。
7. 可以突出作者独立负责从 0 到 1，并使用 AI-assisted development，但不要虚构逐行代码归属。
8. 不得把规划中的 MCP、Docker、annotation execution、算法迁移研究或软著写成已完成能力。

项目最核心的面试结论应是：

> **scKG-Agent 不是把 RAG 包装成聊天界面，而是尝试把单细胞分析中最容易出错的“数据状态、工具约束、参数、真实运行、失败修复和结果复现”组织成一个由 Agent 控制、由确定性安全模块约束的执行闭环。**
