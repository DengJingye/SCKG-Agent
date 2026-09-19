# Current-version PBMC3k replay v2

测量日期：2026-09-19

代码基线：`02d4c131c8180ed163105b1388ea9d3318c85d21`，dirty worktree

portable 事实源：`data/evaluation/midterm_freeze_v1_1/p0/current_pbmc_replay.json`

本轮从真实产品页面完成 `Research -> Stepwise -> WorkflowPlan -> Notebook -> JupyterLab` 回放。Research 使用本地 deterministic 路径；用户已授权 replay，但浏览器链路没有实际调用 LLM。Notebook 由用户授权后在 JupyterLab 手动 Restart and Run All；这不是 Controlled Execution，`ExecutionRequest = 0`。

| 数据 | 输入与 DataProfile | WorkflowPlan | Notebook | annotation 终态 |
|---|---|---|---|---|
| Raw PBMC3k | SHA-256 `89a96f...653a1`；2700 × 32738；`X=raw_counts` | `cap-plan-060f3fdd8e1664bf`；11 steps | 18/18 code cells；5 PNG；最后 1 个预期 terminal error | `BLOCKED`：cluster coverage 不完整、candidate 缺失 |
| Processed PBMC3k | SHA-256 `0db367...5fe38`；2638 × 1838；已有 PCA/neighbors/clusters/marker/UMAP | `cap-plan-39567af880c3cd1f`；只补 `marker_evidence_annotation` | 4/4 code cells；复用 UMAP；最后 1 个预期 terminal error | `BLOCKED`：marker group mismatch、candidate 和 validated marker result 缺失 |

| 必报字段 | Raw | Processed |
|---|---:|---:|
| `PLAN_COMPILED` | true | true |
| `NOTEBOOK_COMPILED` | true | true |
| `NOTEBOOK_EXECUTED` | true | true |
| `CANDIDATE_TERMINAL_SATISFIED` | false | false |
| `HUMAN_CONFIRMATION_COMPLETED` | false | false |
| `FULL_SCIENTIFIC_TASK_COMPLETED` | false | false |

两份原始输入与 content-addressed 上传副本哈希一致。Notebook 的所有 cell source digest 与 compile manifest 一致，说明 Run All 没有改写代码单元。Raw 的 5 个数值结果图和两份 annotation delivery 目录均已记录 SHA-256。

本轮可以声明真实输入绑定、状态感知规划、Raw 数值流程执行、Processed 表示复用和守门终态。不能声明 LLM planning 质量、annotation candidate 已满足、人工确认已完成或完整科学任务已完成。Processed 对“最新 marker revision”的自然语言要求没有转成结构化、人工审阅过的 evidence bundle，因此保持阻断。

首次生成的本地 `summary.json` 被保留为审计证据；它把 nbformat 的 list-form `source` 用 `str(list)` 计算哈希，造成两个 false negative。修复审计脚本后生成 portable freeze，没有重跑或改写科学结果。
