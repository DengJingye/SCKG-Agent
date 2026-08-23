# Phase 6 Group Trial Task Bank

状态：`not_started`。本文件只定义固定试用任务，不包含任何伪造的用户结果。

## Trial Levels

**Level 1：只读 Demo**

- 所有 3 至 5 位参与者都完成。
- 只查看预生成 Defense Demo，不运行工具。
- 不提供真实数据。

**Level 2：监督下 synthetic 执行**

- 仅 1 至 2 位技术参与者完成。
- 由维护者配置 allowlist、授权和 policy。
- 只使用维护者提供的 synthetic fixture，完成一次受限本地执行。
- 不使用参与者私人或真实科研数据。

## Fixed Tasks

| ID | Instruction | Expected answer |
| --- | --- | --- |
| P6-T01 | 找到 Restricted Execution。 | 侧边栏和 Home 都有一级入口，不经过 Legacy Chat。 |
| P6-T02 | 判断 execution policy。 | 默认 disabled；UI 无权修改。 |
| P6-T03 | 读取细胞数、基因数和 count source。 | 从 DataProfile 准确读取；count source 不明确应 blocking。 |
| P6-T04 | 识别 warning/blocker。 | 指出真实 blocker，并判断 Execute 是否禁用。 |
| P6-T05 | 识别工具、环境、参数和输出。 | 固定 Scrublet/scDblFinder 组合、contract 参数和 score/label artifacts。 |
| P6-T06 | 解释 approval。 | 绑定 user、artifact、plan、contract、environment 和 parameter hash；变化即失效。 |
| P6-T07 | 解释 repair。 | n_prin_comps 过大；只降低该字段；parent/new run lineage 可追踪。 |
| P6-T08 | 解释 blocked。 | fingerprint mismatch；在执行前阻断；ExecutionRequest=0。 |
| P6-T09 | 解释 DecisionResult 和 limitation。 | 基于 CandidateEvaluation/Pareto；synthetic 结果不能外推普遍最优。 |
| P6-T10 | 解释 reproducibility package。 | 保存关键 snapshot/hash/rerun 信息，不复制用户原始输入。 |

每项正式记录字段固定为：`task_id`、`instruction`、`expected_answer`、`completion`、`time_seconds`、`help_count`、`critical_error`、`observer_notes`。机器可读版本位于 `eval/phase6/group_trial_task_bank.json`。
