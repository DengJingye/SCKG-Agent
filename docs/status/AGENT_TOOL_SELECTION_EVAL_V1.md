# Agent Tool / Skill Selection Eval v1

分类：`DEVELOPMENT_RESULT`

portable summary：`data/evaluation/midterm_freeze_v1_1/p0/agent_tool_selection_summary.json`

frozen cases：`data/evaluation/midterm_freeze_v1_1/p0/agent_tool_selection_cases.json`
规模：36 个 hand-authored parent cases，覆盖 ASK、catalog、PLAN、RUN、clarification、block；35 个 case 进入真实 LLM ready 状态。

| 层级 / 指标 | 结果 |
|---|---:|
| LLM proposal intent | 30/30 = 100% |
| deterministic governed intent | 24/30 = 80.0% |
| governed mode | 24/24 = 100% |
| final action selection | 34/36 = 94.4% |
| data/artifact binding | 36/36 = 100% |
| clarification | 6/6 = 100% |
| block | 4/6 = 66.7% |
| unauthorized execution | 0/36 = 0% |
| structured complete while terminal unmet | 0/36 = 0% |

Tool 指标按 proposal、governed plan、actual registry observation 分开：

| 层级 | Precision | Recall | Unnecessary-call rate |
|---|---:|---:|---:|
| LLM proposal | 100% | 50.0% | 0% |
| Governed plan | 100% | 100% | 0% |
| Actual observations | 100% | 100% | 0% |

Proposal required parameters 为 9/13；governed required parameters 为 43/43。两条主要失败来自 forbidden/incompatible 类：模型选择等待或回答，而 rubric 要求明确 block。Proposal tool recall 只有 50%，说明 LLM 常给出正确 intent，但不总是显式提出全部必需工具；deterministic governance 补齐了实际工具链。

这组数字不能当 independent validation：题目由开发者手工编写，每题仅一次生成，没有 seed 保证，也没有独立人工 adjudication。工具 precision 的分母是 permissible calls，recall 的分母是 required calls；actual call 表示 registry observation 已发生，不等于执行了科学代码。首个 `live-20260919-36` 目录因配置未加载而没有真实 LLM 调用，已保留并排除出本报告。
