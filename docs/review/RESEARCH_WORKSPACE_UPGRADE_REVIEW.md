# Research Workspace 升级手册审查与落地裁决

日期：2026-08-12  
输入：`scKG-Agent_后续更新规划计划手册_v1.0.docx`  
结论：方向合理，按现有主链增量采纳；P1 不推倒重构，也不扩大执行权限。

## 采纳

- `AnnData path -> backed profile -> Representative Preview -> Notebook Shadow` 作为下一产品纵切面。
- metadata/lazy first、Preview before full、StepContract 单一事实源、shadow before default。
- Preview 只证明数据结构、代码、环境和 artifact contract 兼容，不证明全量科学结论。
- Notebook 从受测模板编译，并保存参数来源、输入输出、验证规则和 provenance。
- EDD 先定义路径、画像、Preview、Notebook、安全和回归 gate，再继续扩展。

## 适配后采纳

- 手册中的 Path Registry 由现有 `DataRegistry + approved roots + DataAccessGrant` 承担，避免第二套登记与权限系统。
- P1 使用轻量 profile/preview/notebook artifact 引用，不立即实现覆盖全系统的 `ResearchState + Patch/Reducer`，避免与 `ResearchAgentState` 和 `ExecutionOrchestrator` 形成第三套状态机。
- Notebook Shadow 编译与 Preview runtime 分开。编译永不执行；synthetic clean-kernel 只作为工程 qualification。用户数据运行仍需新增明确审批并接入既有 controlled runtime。
- 第一模板仅为 Scrublet。scDblFinder 的 R kernel、跨 kernel lineage 与共享 Validator 在独立 gate 后再做。

## 暂缓

- 只读 subagent 消融、scDblFinder 跨语言 Notebook 和任意自由代码执行。
- MuData、SpatialData、HPC、MCP、云执行、多用户 SaaS 与任意 LLM 代码执行。
- 把自由编辑后的 Notebook 重新当作 trusted artifact。

## 当前验收

```text
backed profile                   passed
full matrix materialized        false
deterministic stratified preview passed
source file unchanged           true
notebook schema/provenance       passed
synthetic clean-kernel run       passed
generated result table/plot      passed
compile-time ExecutionRequest    0
scientific claim authority       false
full UI state progression       passed
full pytest                      464 passed
ExecutionPolicy                  disabled
```

## Controlled Preview Runtime 完成情况

- 已实现 `PreviewRunPreparation/PreviewRunRequest/PreviewRunResult` 与统一 `ValidationResult/ErrorContext`。
- 只对受控 Preview 副本调用固定 Scrublet wrapper；Notebook 仍是 shadow artifact，不是执行源。
- 审批绑定 Preview/Notebook/参数/合同/环境/用户，单次消费；hash 漂移在进程前阻断。
- Preview 指标固定为 `preview_engineering_metric`，没有 ground truth 时不计算科学准确率。
- 真实 smoke 生成结果表和诊断图，原始文件 hash 不变，fresh full pytest=`468 passed`，Mainline=`6/6`。

## 下一合法增量

completed/blocked Preview 页面状态与持久化结果导航已完成：结果在刷新后可恢复，图片展示前重验 owner/path/hash，异常记录降为 FAILED；跨用户读取和页面执行副作用均为 0。下一合法增量是评估 checkpoint/stale propagation。跨语言 Notebook、任意生成代码和全量用户数据执行继续 deferred。

最终验收：Preview store/runtime/UI 定向测试=`15 passed`；fresh full pytest=`474 passed, 6 warnings`；Mainline=`6/6`；Preview smoke 的恢复状态为 `COMPLETED` 且 result/artifact integrity valid。

### Checkpoint correction

checkpoint/stale propagation 已完成：source/profile/preview/notebook/approval/result 六段状态由现有 hash、contract/environment digest 与 approval fingerprint 派生；最早失效节点决定重建起点，后续节点传播 STALE。页面只允许显式清理下游引用，检查过程 `ExecutionRequest=0`。下一合法增量改为 Error Intelligence 与用户可读结果解释；cell-level Notebook trust downgrade 和 scDblFinder 跨语言 Notebook继续 deferred。

最终验收：fresh full pytest=`480 passed, 6 warnings`；Mainline=`6/6`；真实 Preview smoke checkpoint=`CURRENT`、ExecutionRequest=0；`git diff --check` 通过。

### UI 验收 correction

初始测试只覆盖空状态，未覆盖 Profile 后的条件组件；完整状态推进首次暴露 nested expander 异常。修复为 popover 后，登记、授权、Profile、Preview、Notebook 编译与下载控件全链已通过，并固化为回归测试。该 correction 是 P1 Shadow Foundation 验收的一部分。

### Chat-Governed Stepwise correction - 2026-08-13

- Data & Preview 不再是脱离任务上下文的一级入口。用户先在 Research Chat 请求 workflow，系统确认资格化 task/tool 后，再通过 handoff 进入 Stepwise Analysis。
- Preview 后必须先检查参数并显式生成 Notebook；参数变化使 Notebook、approval 和 current result stale，不能复用旧审批。
- 页面与 Notebook 共用 Scrublet StepContract；Notebook 记录对话任务、参数 provenance 和每个维护者 cell 的 source digest。修改或新增 cell 会降为 untrusted，scKG 在线执行继续只调用固定 wrapper。
- `InteractiveStepRuntime` 提供八个用户可见状态和 next action，但不复制 Executor/Validator。真实 Preview smoke 已验证 `run_tool -> validate_outputs`、一次性审批、结果恢复、源文件不变和 scientific authority=false。
- 最新用户操作流程见 `docs/demo/STEPWISE_ANALYSIS_GUIDE.md`。scDblFinder 跨语言 Notebook 与任意代码执行继续 deferred。
