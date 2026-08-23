# Phase 6 Closure Review

日期：2026-07-21  
状态：`PHASE6_TRIAL_READY`

## 工程验收

- 双轨 baseline 已生成结构化 per-case、summary、failure queue 和 trace audit。
- A2 使用 8 个冻结 workflow cases；A1/A3/A4 因无冻结公平入口保持 `not_run`。
- B3/B4 共享相同 synthetic fixture、参数与初始失败 runs；B3 停止，B4 只使用 bounded deterministic repair。
- B1 缺少独立冻结 artifact；B2 为 `not_run_safety_boundary`，没有执行新生成或不可信代码。
- success、repair、approval/hash mismatch blocked 三个答辩场景均已形成 demo bundle。
- 适用 trace stage completeness = 1.0；unauthorized execution、path escape、repair budget violation、evidence boundary violation 均为 0。
- 默认 `ExecutionPolicy=disabled`；仅两个固定 tool/environment pair 可在本地 allowlist、授权与精确审批全部满足时运行。
- System Quality Gate v1 已复用现有 8 个评测入口完成统一验收：6/6 operational scenarios 正确，功能/安全/知识/复现/性能/审计通过；真实可用性和 change risk 为 partial。
- 当前资格范围已扩展为四个固定工具组合；本轮 fresh restricted-user smoke 只运行 Scrublet/scDblFinder，Harmony/Scanorama 继续引用已冻结 Batch Integration qualification/scientific-pilot artifact。

## UI 与隐私

- UI 可读取 DataProfile、WorkflowPlan、approval/blockers、run status、logs、Validation、CandidateEvaluation、Pareto、repair history、failure queue、trace audit 与 package manifest。
- 页面渲染不触发执行；取消仍调用既有后端。
- 路径继续脱敏，并明确显示 `network_not_os_isolated`。
- Trial telemetry 使用随机 participant ID，不记录 query、原始路径、矩阵或 barcode；主观反馈可留空，且永远不是科学证据。
- Defense Demo 内的 Trial Runner 已支持 10 项 Level 1 与 7 项 Level 2 固定任务、自动计时、help count、断点恢复和脱敏 observer notes。
- 维护者 Level 1/2 rehearsal 已通过；rehearsal 使用独立 actor type，真实 participant count 保持 0。
- Level 2 participant 只有检测到既有 Restricted Execution 结果后才能完成；UI 不能修改 policy、allowlist、contract、environment 或 execution gate。
- 本轮 Phase 6C synthetic backend 复测通过：Scrublet 与 scDblFinder 各 2 次运行成功，package 完整，输入未复制。

## 未关闭项

- 真实组内试用人数：0；尚未满足 3 至 5 人条件，禁止标记 `PHASE6_COMPLETE`。
- A1/A3/A4/B1 没有可公平运行的冻结 baseline；B2 受安全边界阻断。
- 安全控制仍是应用层，不是 OS/container sandbox，也没有系统级禁网或不可信多租户隔离。
- GSE108313 仍是单数据集 scientific pilot，不支持普遍最优声明。
- 原 Phase 5 Batch Integration 已完成；Phase 7 服务化/MCP 尚未开始。
- 系统级版本 baseline 尚未冻结，因此当前只能报告 `baseline_not_provided`，不能声称本版本统计上优于上一版本。

## 试用放行条件

仅限本机、维护者配置的 `allowlisted_local_users`，使用已登记 synthetic 或授权 artifact，并保持完整 data grant、plan-specific approval、contract、environment、ownership 与 execution gate。试用中出现 unauthorized execution、路径逃逸、跨用户访问或不受控 repair 时立即回退为 `PHASE6_BLOCKED`。
