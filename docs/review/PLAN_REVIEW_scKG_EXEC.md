# scKG-Agent 2.0 Phase 0-2 实施审查

版本：1.0  
日期：2026-07-10  
主规约：`docs/DEV_SPEC_2.0.md` 2.0.3  

## 1. 结论

Phase 0 可以基于当前仓库完成。Phase 1 可以启动，但必须带着明确 blocker 开始：仓库还没有 AnnData fixture，Scrublet execution-critical source 尚未完成 contract review，`scRNAseq` 只是 import-qualified candidate。Phase 2 不应提前启动，因为 Phase 1 canonical schemas 和 planning gate 尚不存在。

## 2. 前置条件检查

### 已具备

- 中文主规约 2.0.3 已冻结 Agent/Workflow、Evidence Governance 和权限边界；
- 当前测试基线 38/38 通过；
- `scRNAseq` 环境存在，并可重复导入 AnnData、Scanpy、Scrublet；
- `sckg_env` 可运行 Streamlit、LangGraph、Neo4j、Pydantic 控制平面；
- Neo4j Aura 只读连通性已验证，同时存在 offline fallback；
- Scrublet 方法论文/README/source chunks 已有一部分 retrieval source；
- 现有 plan-only workflow 与 evidence boundary 可作为 Phase 2 baseline；
- `.env`、logs、memory、skill candidates 已在 `.gitignore` 中隔离。

### 缺失

- canonical `RequirementSpec/DataProfile/MatrixProfile/ToolContract/WorkflowPlan` 实现；
- synthetic `.h5ad` fixture；
- Scrublet ToolContract 及 execution-critical field review；
- environment registry 与 qualification 状态机；
- count source 判定规则的测试 fixture；
- `execution/` 和 `contracts/` 目录；
- Phase 2 可编译 dry-run plan 的 schema 与 compiler；
- 对 live Neo4j、Parent workflow、ToolExecutor 和 MCDM 的直接回归测试。

## 3. 建议实施顺序

```text
Phase 1A canonical schemas
-> Phase 1B synthetic AnnData fixtures
-> Phase 1C deterministic AnnDataProfiler
-> Phase 1D Scrublet planning contract
-> Phase 1E environment registry + planning/execution gate tests
-> Phase 1 full regression
-> Phase 2 dry-run PlanCompiler
```

Phase 1 不依赖 dense embedding、全量 PDF、MCP、subagent 或 live execution。

## 4. Phase 1 允许修改的文件

建议新增：

```text
core/execution_models.py
engine/data_profiler.py
execution/__init__.py
execution/environment_registry.py
contracts/tools/scrublet/0.2.3.json
tests/fixtures/execution/*
tests/test_execution_models.py
tests/test_data_profiler.py
tests/test_tool_contracts.py
tests/test_environment_registry.py
```

可能小幅修改：

```text
core/settings.py
.gitignore
requirements.txt 或单独的 execution environment lock
docs/status/PROJECT_STATUS_2.0.md
docs/DEV_SPEC_2.0.md（仅 schema/gate 真正改变时）
```

## 5. Phase 1 不应修改的文件

```text
data/tool_publications.tsv
data/tool_benchmarks.tsv
data/scKG_embeddings_backup.jsonl
Neo4j trusted graph
engine/mcdm_calculator.py
engine/isomorphism_analyzer.py
core/subagent_runtime.py
agent/workflow.py 的真实执行 route
app.py 的执行按钮
任何 MCP/FastAPI server
```

这些文件如果必须改，必须先证明它们是 Phase 1 gate 的直接依赖并更新规约；默认不改。

## 6. 可独立验证的最小任务

| 任务 | 输入 | 输出 | 独立验收 |
| --- | --- | --- | --- |
| Schema v1 | 手工合法/非法 dict | Pydantic models | 类型、枚举、不变量测试 |
| Raw counts fixture | 固定 seed 小矩阵 | `.h5ad` | hash、shape、整数非负 |
| Log1p/scaled fixture | 固定变换 | `.h5ad` | profiler 正确阻断/降级 |
| Layer fixture | counts in `layers['counts']` | DataProfile | count source 与依据正确 |
| Invalid files | missing/corrupt/non-h5ad | blocked profile | 无 LLM、无输入修改 |
| Scrublet contract | JSON contract | planning gate result | planning 可过、execution 必须失败 |
| Environment registry | `scRNAseq` metadata | candidate qualification | import smoke != integration pass |

## 7. Phase 2 readiness gate

进入 Phase 2 前必须同时满足：

- Phase 1 新旧测试全部通过；
- DataProfile 不修改输入文件；
- unresolved count source 会阻断；
- Scrublet contract 能通过 planning gate；
- `enabled_for_execution=false`；
- `execution_critical_fields_reviewed=false` 或其他 execution gate 条件未满足时，plan 只能是 `dry_run`；
- fixture 来源、seed、hash 和适用范围已记录。

## 8. 风险与回滚点

| 风险 | 控制 | 回滚点 |
| --- | --- | --- |
| `core/models.py` 继续膨胀 | execution schema 放独立模块 | 删除新模块引用，不影响 1.x models |
| AnnData 依赖污染控制平面 | profiler 通过受控环境/可选导入边界 | 保留 `sckg_env` 控制平面启动方式 |
| DataProfiler 误判 counts | 多矩阵 fixture + reason codes | contract gate 保持 blocking |
| Scrublet contract 与 0.2.3 不符 | source-bound review + runtime version check | execution 保持 disabled |
| 新 planner 破坏旧 UI | 独立 application API，旧 demo 保留 | UI 继续调用旧 plan-only route |
| 工作树覆盖用户改动 | 每次只改 Phase 文件并看 diff | 回滚单个新文件/小 patch |

## 9. Phase 0 对 Phase 1 的裁决

```text
READY_WITH_BLOCKERS
```

可以开始 Phase 1 的 schema 与 fixture 工作；在 fixture、contract review 和 environment registry 完成前，不得进入真实执行或把 Scrublet 标记为 execution-enabled。

