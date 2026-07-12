# scKG-Agent 2.0 Phase 0 项目审查

审查日期：2026-07-10  
审查范围：Phase 0，规约冻结与执行环境资格审查  
主规约：`docs/DEV_SPEC_2.0.md` 2.0.3  
当前分支：`main`  
当前提交：`91b3f58`  

> 本审查以当前代码、测试、运行产物和实际环境命令为事实来源。`implemented` 只表示对应的 1.x 能力已经存在，不表示 scKG-Agent 2.0 的执行闭环已经完成。

## 1. 审查结论

当前仓库是一个已经可运行的 evidence-governed recommendation/workflow prototype，具有约束解析、KG 候选检索、受治理的文献检索、plan-only workflow、报告审计、trace、dashboard 和 operational memory。它当前不是可执行生信 Agent：没有 DataProfiler、ToolContract registry、受控生信执行器、Validator、Repair Loop 或复现包。

仓库可以渐进迁移，不需要推倒重写。当前最重要的边界是：

```text
现有 Parent workflow + KG/RAG/evidence governance
  = 2.0 控制平面和知识平面的可复用基础

现有 workflow report / MCDM / algorithm embedding
  = plan-only、baseline 或 exploratory signal

LocalControlledExecutor / DataProfiler / ToolContract / Validator
  = 尚未实现的 2.0 执行平面
```

## 2. 仓库事实基线

- Git 分支为 `main`，远端状态显示与 `origin/main` 一致。
- 仓库只有两个可见提交：`91b3f58`、`1887e34`。
- 审查开始时工作树有 131 个 modified/untracked 条目；这些改动均被保留。
- `python -m pytest` 收集 38 个测试，38 个通过，0 失败，0 跳过。
- 仓库不存在 `execution/` 和 `contracts/` 目录。
- 仓库不存在 `.h5ad`、`.h5`、`.loom` 或 `.rds`。
- `scRNAseq` 可重复导入 NumPy、Pandas、SciPy、AnnData、Scanpy 和 Scrublet。
- Neo4j Aura 只读 smoke 在允许网络访问后返回 `RETURN 1 AS ok -> [{'ok': 1}]`；受限沙箱内会降级为 offline graph。

## 3. 重要能力审计

| 路径/模块 | 当前职责 | 状态 | 可否复用 | 2.0 目标位置 | 主要缺口 | 迁移风险 | plan-only |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `core/constraints.py` | LLM 结果归一化、规则回退、约束澄清 | partially_implemented | 是 | Requirement Parser / Gateway | 不是 2.0 `RequirementSpec`；没有数据访问和执行授权字段 | 中 | 是 |
| `agent/workflow.py` | LangGraph 固定图：意图、KG、MCDM/迁移、报告 | partially_implemented | 是 | Parent Agent + deterministic Router | 不是 Observe-Act-Validate-Adapt 执行闭环；无执行状态机 | 高 | 是 |
| `core/agent_runtime.py` | Python 函数注册、Pydantic 参数校验、重复/预算阻断、tool-call trace | implemented | 是，保留原名 | Agent tool-call runtime | 不管理外部进程、环境、路径、timeout、hash 或 artifact | 高，易被误称为生信执行器 | 否，但不是 execution plane |
| `connectors/graph_client.py` | Neo4j 连接、hard constraint 查询、evidence 读取与 offline fallback | implemented prototype | 是 | Graph service | 查询 schema 仍偏 1.x；live Neo4j 未纳入自动化回归；含写接口需保持治理 | 中 | 否 |
| `engine/evidence_discovery_index.py` | source/formal chunk、sparse/dense 检索、RRF、治理 rerank | partially_implemented | 是 | Execution-oriented retrieval | dense index 为 0；source coverage 仅 16 个工具；schema 尚未统一 | 中 | 检索结果是 retrieval-only |
| `engine/evidence_rag_pipeline.py`、`formal_evidence_rag.py` | Hybrid retrieval 与 formal TSV lexical fallback | partially_implemented | 是 | RAG service | execution claim types、ToolContract 联动和参数 provenance 未实现 | 中 | 是 |
| `data_pipeline/build_source_registry.py` 等 | source 去重、候选校验、隔离错误 PDF、抽取与 coverage | implemented prototype | 是 | Source ingestion service | 大规模下载成功率、HTML/PDF extractor 和 source review 仍有限 | 中 | 不产生正式证据 |
| `core/evidence_policy.py` | recommendation evidence gate、publication/benchmark 边界 | implemented | 是 | Evidence governance | 需要持续扩展 execution claim audit，但不能放宽现有 gate | 低 | 否 |
| `engine/workflow_recommender.py` | 确定性 workflow 模板与候选工具映射 | partially_implemented | 是，作为 baseline/fallback | PlanCompiler 的输入或对照 | 没有 ToolContract、真实 I/O、参数、授权、execution status | 高 | 是 |
| `engine/workflow_decision.py` | workflow plan + step RAG context 的本地交互 demo | implemented prototype | 是，作为 planning baseline | Phase 2 dry-run plan 的对照 | 输出明确是 `plan_only_evidence_limited`，不可执行 | 低 | 是 |
| `engine/mcdm_calculator.py` | 1.x 文献/元数据推荐打分 | partially_implemented | 仅 baseline | Decision Engine | 没有 CandidateEvaluation、Pareto frontier、实测 metrics | 高 | 是 |
| `engine/isomorphism_analyzer.py` | 旧 LLM-profile embedding 的 cosine recall | deprecated | 仅回归/探索 | legacy recall baseline | 依赖远程 embedding；不是 source-bound；不可支持迁移有效性 | 高 | 是 |
| `engine/algorithm_representation_v2.py` | source/profile/KG/empirical 多视图表示与探索性迁移评分 | partially_implemented | 是，非 MVP | migration_context | 1818/1834 工具低 source coverage，dense vectors 为 0，tool module 未拆 | 中 | 是 |
| `engine/semantic_hallucination_auditor.py` | 工具、benchmark、文献、workflow、阈值和迁移声明审计 | implemented prototype | 是 | Report/Audit + execution claim audit | 当前没有执行 artifact 可审计；Agent 主链缺少直接单测 | 中 | 否 |
| `core/trace_context.py`、`agent/traced_runner.py` | JSONL stage trace | implemented v1 | 是 | Execution trace | 无 run/request/artifact/repair stages；部分 stage 仅记录 0 ms 占位 | 低 | 否 |
| `observability/dashboard/`、`app.py` | Chat、trace、RAG、KG、memory、evaluation 展示 | implemented prototype | 是 | 用户端与管理端 | 没有真实 Execution Runs；当前只可展示 1.x artifacts | 中 | 否 |
| `core/reflection_memory.py` | JSONL/SQLite operational memory 与 skill candidate | partially_implemented | 有条件复用 | Episodic/User Preference Memory | 当前从约束推断的 species/platform/strictness 会直接写 `user_preference`，缺少 2.0 所要求的用户确认 | 高，权限语义未完全对齐 | 否 |
| `core/subagent_runtime.py` | 默认关闭的只读 specialist contract | design_only | 后续可参考 | Optional Specialist | 无真实 specialist 执行；预算仍是旧的 depth=2/count=3，与 2.0.3 不一致 | 中，默认关闭 | 是 |
| `data/scKG_embeddings_backup.jsonl` | 旧算法 embedding artifact | deprecated | 仅 baseline | legacy recall signal | 24 MB，来源与质量不足以支持推荐或迁移 claim | 高 | 是 |
| `execution/`、`contracts/` | 2.0 执行平面与契约 | not_implemented | 不适用 | Phase 1/3 新模块 | 目录和代码均不存在 | 高 | 否 |
| DataProfiler / Validator / Repair / Packager | 2.0 核心闭环 | not_implemented | 不适用 | Phase 1/3/4 | 无代码、无 fixture、无测试 | 高 | 否 |

## 4. 状态分类汇总

### implemented

- 1.x evidence gate；
- Python 函数级 `ToolExecutor`；
- JSONL trace 与本地 dashboard 基础；
- source registry 的去重、错误候选 quarantine 和抽取状态分类；
- Neo4j/offline graph connector 的基础查询能力；
- plan-only workflow demo 的 evidence boundary 测试。

### partially_implemented

- Requirement Parser；
- LangGraph Parent workflow；
- Hybrid KG-RAG；
- algorithm representation v2；
- report/audit；
- operational memory；
- MCDM 与 UI。

### design_only

- Optional Specialist/Subagent；
- MCP 服务；
- 2.0 supporting schemas；
- Pareto-based empirical Decision Engine；
- execution-oriented skill contracts。

### not_implemented

- Matrix-level AnnData DataProfiler；
- ToolContract registry；
- Probe Builder；
- LocalControlledExecutor；
- Validator；
- bounded Repair Loop；
- Reproducibility Packager；
- execution worker/job manager。

### deprecated

- 旧 LLM-profile embedding 作为迁移依据；
- 把旧 MCDM 分数解释为 2.0 empirical decision；
- 把 1.x recommendation/report artifact 解释为执行成功；
- “recursive centralized” 旧架构命名。

## 5. 当前测试所证明与未证明的内容

38 个测试主要覆盖：source registry/PDF 防错、workflow plan-only boundary、trace 序列化、dashboard service、reflection authority flag、subagent 默认阻断和 representation v2 降权。

当前测试没有直接覆盖：

- `agent/workflow.py` 完整 LangGraph 运行；
- live Neo4j schema/查询回归；
- `ToolExecutor` 的预算和重复调用；
- MCDM 与 semantic auditor 主路径；
- LLM 在线行为；
- 任何 AnnData、Scrublet、外部进程、Validator 或 Repair 行为。

因此“38 passed”不能解释为 2.0 workflow 已经可执行。

## 6. 数据与 artifact 审查

- 工具目录：`scrna_tools.tsv` 1842 条数据行，是 long-tail seed catalog，不代表完整或审核完成。
- formal publication：28 条数据行；formal benchmark：14 条数据行，当前均受保守 evidence gate 约束。
- source chunks：819 条；dense vectors：0；ToolRepresentationV2：1834 条。
- source-bound 工具：16；低 source coverage 工具：1818。
- core literature rows：23，其中 19 有 source text，4 个 unresolved。
- 旧 embedding：`data/scKG_embeddings_backup.jsonl`，约 24 MB，只能做 legacy baseline。
- `eval/` 约 43 MB，包含 1.x 多轮评测 artifact；可用于回归，但不能代表 2.0 execution evaluation。
- 未发现 `.h5ad/.h5/.loom/.rds`；未发现可用于 Phase 3 的 AnnData fixture。
- `data/evidence_sources/` 中有未跟踪 PDF，包括 quarantine/supplement 候选；它们不是用户原始单细胞矩阵，但提交前仍需单独决定 license、体积和保留策略。
- `.env` 已被 `.gitignore` 忽略，审查没有输出其秘密内容。

## 7. 容易误解的旧命名

- `ToolExecutor`：函数调用包装器，不是 `LocalControlledExecutor`。
- `workflow_recommendation` / `workflow_decision`：plan-only，不是 executable plan。
- `algorithm embedding`：legacy recall，不是迁移有效性证据。
- `execution_status` 等旧模型字段：预测/评测元数据，不能证明外部生信进程运行。
- `SubagentController`：默认关闭的 contract，当前不是多 Agent runtime。
- `sandbox`：当前不存在 OS/container sandbox。

## 8. 技术债与 blocker

1. 工作树有 131 个未提交条目，且包括 tracked `__pycache__/*.pyc`，后续迁移必须小步提交并避免覆盖现有工作。
2. 没有 AnnData fixture，Phase 1 profiler 无法做真实文件 integration test。
3. `scRNAseq` 只通过 import qualification，没有 environment registry 和 Scrublet integration test。
4. `sckg_env` 可运行控制平面核心包，但缺 SciPy/AnnData/Scanpy/Scrublet；这一点符合平面分离，但必须在文档和启动命令中明确。
5. Reflection 的用户偏好写入缺少显式确认，当前只能视为部分实现。
6. Subagent schema 与 2.0.3 预算不一致，但默认关闭；不得启用。
7. live Neo4j 依赖外部网络，自动测试仅覆盖本地逻辑，不覆盖 Aura schema。
8. formal evidence coverage 低，旧 evidence 冻结；这不阻断 Phase 1 planning contract，但阻断 execution-critical source review 完成。
9. `EvidenceChunk` 有重复概念/定义，Phase 2 前需要统一，不能在 Phase 0 大改。

## 9. 不得夸大的能力

- 不得称当前系统已执行 Scrublet 或任意生信工具；
- 不得称已有 sandbox、memory hard limit 或 network isolation；
- 不得称当前是运行中的多 Agent；
- 不得称 source chunk 自动成为 formal evidence；
- 不得称旧 workflow/MCDM 输出经过真实数据验证；
- 不得称 1800+ 工具已有高质量 source-bound representation；
- 不得称 synthetic/scenario eval 证明生物学正确性。

