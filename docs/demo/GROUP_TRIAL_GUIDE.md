# Phase 6 组内试用指南

范围：3 至 5 位组内同学；不开放远程服务，不要求普通参与者提供真实数据。

## Level 1：只读 Demo

所有参与者先从 Home 进入 Defense Demo，在 `Trial Task Runner` 中启动 Level 1，完成 `GROUP_TRIAL_TASK_BANK.md` 的 10 项固定任务。此级别不运行工具，`ExecutionRequest` 必须保持 0。

每项任务先点击 `Start task timer`。需要查看参考答案时点击 help，系统会自动累计求助次数。完成后只记录 outcome、critical error 和可选脱敏 notes；不要填写 query、路径、矩阵内容或 barcode。浏览器中断后可从本地 in-progress session 恢复。

## Level 2：监督下 synthetic 执行

仅 1 至 2 位技术参与者在维护者监督下执行。维护者提供 synthetic fixture、配置 allowlist，并明确启用受限 policy；参与者不得提供私人或真实科研数据。

1. Level 2 由维护者登记 synthetic artifact、配置 approved input root 和 local user allowlist。
2. 参与者先查看 DataProfile 与 dry-run WorkflowPlan，不理解时停止并记录 blocker。
3. 核对数据、工具、参数、环境和 approval fingerprint，再输入确认文本。
4. 执行后查看 run status、Validation、Decision、repair history 与 package integrity。
5. 尝试取消一个测试任务；不得修改全局 policy、contract 或 environment。
6. 提交可选匿名反馈。系统不记录 query、路径、矩阵或 barcode。
7. 发现错误声明、跨用户可见、路径泄露、不受控执行或 repair 越界时立即通知维护者。

每位参与者完成至少一个成功或正确阻断案例。达到 3 至 5 人且无关键 blocker 前，项目状态保持 `PHASE6_TRIAL_READY`。

## 维护者自测

没有真实参与者时可使用 `Start maintainer rehearsal` 或运行：

```bash
python scripts/run_phase6_trial_runner_smoke.py
python scripts/run_phase6c_ui_service_smoke.py
```

维护者演练用于验证界面、telemetry 和 synthetic backend，不计入真实参与人数、完成率或 Phase 6 完成 gate。
