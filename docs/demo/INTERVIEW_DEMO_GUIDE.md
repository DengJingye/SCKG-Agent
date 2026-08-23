# scKG-Agent 三分钟面试 Demo

## 运行

```bash
python scripts/run_portfolio_acceptance.py
streamlit run app.py
```

进入 `Defense Demo -> Interview Demo`。页面优先读取最新 Portfolio RC bundle；渲染只读产物，不创建 `ExecutionRequest`。外部模型稳定性和 RAGAS 本轮固定为 `not_run`，不会为填满表格而调用 API。

当前本机已验收 bundle 位于 `.sckg_exec/portfolio/rc-2.7.2-<timestamp>`，页面自动读取最新一份。验收状态为 `RC_READY_FOR_USER_REVIEW`；全量测试 `363 passed`、Mainline `6/6`、Interview `4/4`、trace completeness=1.0、correctly blocked `ExecutionRequest=0`、privacy issue=0。该路径是本机忽略目录中的审计产物，不是仓库内伪造的固定结果；具体 digest 以包内 `portfolio_acceptance.json` 为准。

## 三分钟节奏

### 0:00–0:35 为什么这是 Agent

自然语言任务不是直接变成报告，而是进入统一 Parent loop：Gateway 解析需求，KG-RAG 找 ActionBundle，DataProfiler 检查真实数据，WorkflowPlan 编译计划，Router 和 Approval 决定是否能执行，随后才进入 Executor、Validator、Repair、Pareto 与 Package。

主架构图只使用 `docs/figures/scKG_product_mainline_v2_7_2.png`。旧编排图只解释历史演进，不用于描述当前产品。

### 0:35–1:15 为什么不是普通 RAG 推荐器

展示 Doublet Detection 与 Batch Integration 两个成功案例。RAG 只找证据和候选；ToolContract 决定参数/I-O/环境是否合法；LocalControlledExecutor 实际运行 Python/R 工具；Validator 读取真实 artifact。最终交付是 Level 2 复现包，不只是自然语言推荐。

### 1:15–1:50 KG 多解决了什么

Catalog Graph 保存 1,847 个工具用于召回；Decision Graph 只保留 2 个 qualified Action 和 4 个 ActionBundle 用于动作准入。Tool、Task、Action、Contract、I/O、Environment、FailureMode、ValidationRule、Dataset 和 Evaluation 是显式 typed path。目录相关性不会自动变成执行能力。

### 1:50–2:20 安全和可复现

展示 Bounded Repair：失败 run、RepairProposal、允许修改的参数、父子 run lineage。再展示 Correctly Blocked：parameter hash 或 evidence/contract 不匹配时，`ExecutionRequest=0`。强调全局 `ExecutionPolicy=disabled`。

### 2:20–2:45 A2/A3/A4 评测

48 条固定 gold case 覆盖 Doublet、Batch、安全阻断与 evidence hard negative；其中 16 条进行 A2 ordinary RAG、A3 KG-RAG、A4 KG-RAG+ToolContract 的 48 次同模型对照。API 失败不补分，成本没有冻结单价时保持 null。

当前冻结 v2 结果必须分两层讲。A4 raw proposal 的 tool recall 为 0.78125，但 blocker correctness 只有 0.604167、I/O compatibility 只有 0.416667；LLM 本身并不可靠。经过 ActionBundle、ToolContract 与 deterministic policy admission 后，A4 的关键指标均为 1.0，hard gate 通过，且 unauthorized execution=0。这个结果证明的是“LLM proposal + 确定性 safety plane”的系统价值，不是模型裸能力满分；48-case 仍是自建作品集，不是外部统计 benchmark。

### 2:45–3:00 与 Biomni 的关系

借鉴 Biomni 的 action discovery、resource retrieval 和 generalist loop；不照搬任意 Python/R/Bash 全权限执行与 massive 单环境。scKG 的差异化是单细胞领域内的 contract、数据画像、逐请求审批、独立验证和复现深度。

## 六个高频问题

1. **为什么这是 Agent？** 它根据数据画像、执行观察和验证结果改变下一步，并能有限修复或停止。
2. **为什么不是普通 RAG？** RAG 无权执行；动作必须通过 contract、data、policy、approval 和 validator。
3. **KG 的价值？** 把检索候选与可执行 Action 分层，并返回可解释 typed path，而不是只做关键词搜索。
4. **为什么执行安全？** 结构化 request、wrapper allowlist、`shell=False`、固定路径、hash、ownership、一次性 approval 和 repair budget。
5. **与 Biomni 的差异？** Biomni 强在通用 action-space 广度；scKG 强在窄领域受治理执行深度。
6. **失败边界？** 只有 2 个任务族、4 个工具、2 个 dataset-scoped pilot；无 OS sandbox、远程服务和真实组内试用。
