# Midterm Metrics Snapshot v2

portable 机器事实源：`data/evaluation/midterm_freeze_v1_1/p0/midterm_metrics_snapshot_v2.json`

平铺表：`data/evaluation/midterm_freeze_v1_1/p0/midterm_metrics_tables.csv`

来源哈希：`data/evaluation/midterm_freeze_v1_1/manifest.json`

代码基线：`02d4c131c8180ed163105b1388ea9d3318c85d21`，dirty worktree

## 答辩主数字

| 主题 | 数字 | 分类 | 边界 |
|---|---:|---|---|
| 真实输入绑定 | PASS；leakage 0；未授权 synthetic fallback 0 | CURRENT_MEASURED | real PBMC3k offline service integration + browser replay；multi-file 显式选择由 focused test 验证 |
| Raw replay | 18/18 code cells；5 PNG；terminal BLOCKED | CURRENT_MEASURED | 数值链完成，annotation candidate/人工确认未完成 |
| Processed replay | 4/4 code cells；1-step minimal plan；terminal BLOCKED | CURRENT_MEASURED | 复用已有表示；validated marker revision 未满足 |
| Agent final action selection | 34/36 = 94.4% | DEVELOPMENT_RESULT | 36 个 hand-authored cases，单次生成 |
| Agent data binding | 36/36 = 100% | DEVELOPMENT_RESULT | 非独立验证 |
| Agent block | 4/6 = 66.7% | DEVELOPMENT_RESULT | 暴露真实弱点，不隐藏 |
| Unauthorized execution | 0/36 | DEVELOPMENT_RESULT | eval 本身不执行科学代码 |
| Retrieval BM25 Recall@10 | 31/45 = 68.9% | DEVELOPMENT_RESULT | 已知 45 题 |
| Retrieval Dense Recall@10 | 25/45 = 55.6% | DEVELOPMENT_RESULT | 已知 45 题 |
| Retrieval Hybrid Recall@10 | 31/45 = 68.9% | DEVELOPMENT_RESULT | 已知 45 题 |
| Scientific KG + Hybrid Recall@10 | 31/45 = 68.9% | DEVELOPMENT_RESULT | KG 对科学集行为增益为中性；catalog 有局部帮助 |
| Evidence fidelity formal | 12 atoms，0 failed | FROZEN_HISTORICAL | 当前 SUT digest 已变化，不是 current score |
| SoupX candidate reuse | 1 claim reused；0 external reacquisition；0 ReviewDecision | DEVELOPMENT_RESULT | pending human review，无 canonical promotion |
| CellTypist runtime smoke | 2/2 executions；offline output match | DEVELOPMENT_RESULT | synthetic runtime qualification，不是生物学准确率 |
| Focused regression | 189 passed，0 failed，2 warnings | CURRENT_MEASURED | 当前 P0/P1 focused set；完整 pytest 未重跑 |

## KG 与 Dashboard

当前 artifact inventory 仍保留 legacy catalog、decision graph、consolidated view 与 candidate layers 的分层计数，不能把跨层重复身份加总成“唯一方法数”。默认 RAG snapshot 为 783 evidence chunks / 773 vectors；strengthened benchmark snapshot 为 800 / 790，两者在 Dashboard 中按 snapshot 独立展示。Core source association 为 16/16，表示有来源关联，不表示来源已完成人工科学验证。Source audit 明确展示 20 = 17 available + 2 extraction failures + 1 metadata mismatch。

## 尚未运行

以下项目统一标记 `NOT_RUN`：30–50 题独立检索验证与 sealed subset、外部 benchmark smoke、DCS deployment readiness、PBMC 人工 ReviewDecision、current-head 完整 pytest suite。它们不得进入已完成或已验证的答辩数字。
