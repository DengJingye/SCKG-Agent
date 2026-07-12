# scKG-Agent 2.0 项目状态

更新时间：2026-07-11  
当前 Phase：Phase 4 execution orchestration + bounded repair completed  
主规约：`docs/DEV_SPEC_2.0.md`  
主规约版本：2.4.0  
用户执行：`DISABLED`  
科学验证：`SCIENTIFIC_PILOT`  

## 1. Phase 4 结论

已完成维护者限定的统一执行与有界修复闭环：

```text
RequirementSpec -> DataProfile -> WorkflowPlan -> qualification authorization
-> ExecutionRun -> ValidationResult -> bounded RepairPolicy
-> CandidateAggregator -> Pareto Decision -> Level 2 Reproducibility Package
```

该闭环能够保留失败、提出可审计修复并重新执行，但不开放普通用户执行，不自动修改代码、wrapper、工具、环境或数据范围。

## 2. 新增能力

| 能力 | 状态 | 边界 |
| --- | --- | --- |
| ExecutionOrchestrator | implemented | 固定 13 状态；禁止 `PLANNED -> COMPLETED` |
| RepairPolicy | implemented | 仅确定性白名单动作；安全/证据违规不可修复 |
| layered run budget | enforced | initial 12、repair 4、validation rerun 2、total 18 |
| repair Router | implemented | pending/approved/rejected/budget/critical safety 分流 |
| run lineage | traceable | parent/new run id、参数前后值、policy provenance |
| repair package | Level 2 | runs、validation、repair history、trace、decision、artifact hash |

## 3. Gate 状态

```text
source_review_status=reviewed
execution_critical_fields_reviewed=true
wrapper_status=smoke_passed
environment_status=smoke_passed
execution_status=integration_passed
scientific_validation_status=scientific_pilot
contract.enabled_for_execution=false
environment.enabled_for_execution=false
```

Planning gate：`allowed=true`。

Execution gate：

```text
allowed=false
contract_execution_disabled
environment_execution_disabled
```

Qualification route 仅允许 `maintainer + qualification approval + allowlisted fixture`，不受普通用户入口调用。

## 4. Phase 4 Smoke

场景 A：两个真实 Scrublet initial runs 使用 `n_prin_comps=100` 失败；RepairPolicy 识别 `invalid_n_prin_comps`，生成两条 lineage，将参数降至 10。两个 rerun 均通过 Validator，CandidateEvaluation eligible，Pareto 产生推荐，package 完整。

场景 B：两个真实 Scrublet runs 在 smoke-only validator 中构造 artifact hash mismatch。Router 判定不可修复，repair runs 为 0，候选失败，最终状态 `BLOCKED`，失败证据仍完整打包。

```text
initial runs used: 2
repair runs used: 2 (A) / 0 (B)
validation reruns used: 0
unauthorized user execution: 0
hash mismatch illegal rerun: 0
contract/environment enabled: false
```

## 5. 测试与复现

全量测试：121 passed。Phase 1、Phase 2、Phase 3A、Phase 3A-E、Phase 4 smoke 全部通过。

最新 Phase 4 package：

```text
.sckg_exec/packages/phase4-repairable-20260711T142902055733
.sckg_exec/packages/phase4-nonrepairable-20260711T142902055733
```

两个 package 均完整且 manifest hashes valid；repair package 保存完整 proposal/action/lineage 和结构化 orchestrator trace。

## 6. 保持不变

```text
app.py
agent/workflow.py
engine/workflow_recommender.py
formal evidence TSV
trusted Neo4j
普通用户执行
Streamlit 执行入口
第二工具
MCP/FastAPI
云部署
```

## 7. Blockers

1. contract/environment execution enable 仍关闭；
2. qualification approval 仍是维护者级授权，不是用户执行授权；
3. repair 目前只在 Scrublet synthetic engineering fixture 上真实验收；
4. scientific evaluation split 禁止参数型 repair，避免 evaluation leakage；
5. 第二工具、跨工具 decision 和用户数据安全审批尚未开始。

## 8. 下一阶段 Readiness

Phase 4 的单工具执行与 repair 基础已具备。下一阶段可以选择第二独立工具的 contract/wrapper/environment qualification，或先做用户执行前的授权、安全与数据隔离设计；在另行批准前，不接 UI、不打开 execution enable、不处理用户数据。
