# Biomni 架构对照：Adopt / Adapt / Reject

更新时间：2026-07-17
审计方式：只读官方仓库，不安装环境、不复制源码、不修改 scKG allowlist
官方仓库：<https://github.com/snap-stanford/Biomni>
审计 commit：`400c1f366b96a35ca253e13c9b06c5076af41d65`

## 1. 客观边界

Biomni 是面向通用生物医学任务的 generalist Agent。官方仓库将 ToolRegistry、ToolRetriever、data lake、library inventory、know-how 与 ReAct/LangGraph loop 组合起来，并允许模型在 `<execute>` 中生成 Python、R 或 Bash 后执行。README 同时明确其软件环境很大，默认 data lake 约 11 GB。

scKG-Agent 不是 Biomni 的缩小复刻。当前定位是单细胞领域内更窄、但拥有 DataProfile、ToolContract、逐请求审批、固定 wrapper、独立 Validator、有限 Repair 和复现包的执行 Agent。

## 2. 对照矩阵

| 裁决 | Biomni 机制 | scKG-Agent 处理 | 原因 |
| --- | --- | --- | --- |
| Adopt | 查询时检索相关 tool/data/library/know-how | 保留离线 Action Discovery 与在线 ActionBundle retrieval | 避免把全部 1,847 个目录工具塞入一次上下文 |
| Adopt | 集中的 tool registry 与环境资源描述 | ToolContractRegistry + EnvironmentRegistry + Decision Graph inventory | 让版本、I/O、参数、环境和失败模式可查询 |
| Adopt | ReAct 的 plan -> execute -> observe -> revise | Parent Agent -> Executor -> Validator -> bounded Repair | Agent 必须根据真实观察继续行动，而非只生成报告 |
| Adapt | 动态选择和组合工具 | 只在 qualified ActionBundle 内组合，Router/Approval 拥有否决权 | 动态规划不能等于动态授权 |
| Adapt | generalist LLM loop | LLM semantic proposal plane + deterministic safety plane | 保留模型灵活性，同时阻断非法参数、路径、权限和证据越界 |
| Adapt | 统一大环境 | 按任务懒加载的独立 CPU/R 环境 | 降低依赖冲突和本地磁盘压力，允许未来 worker 化 |
| Reject | 任意 Python/R/Bash `<execute>` 直接运行 | 只接受结构化 ExecutionRequest 与固定 wrapper allowlist | scKG 当前面向本地用户数据，不接受宿主机全权限代码生成 |
| Reject | Bash 通过通用 shell runner 执行 | `shell=False`、固定 argv、固定输入输出根 | 防止 shell 注入和路径逃逸 |
| Reject | 未经独立资格化的新 action 直接进入执行空间 | catalog/source chunk 只能召回；contract + environment + validator + pilot 后才能准入 | 检索相关不等于可执行或科学有效 |
| Reject | 单一 massive environment + 默认大 data lake | 不安装 Biomni；四个工具使用三个登记环境 | 当前 Mac 不应为目录广度承担全部依赖成本 |

## 3. 官方代码审计依据

- `biomni/agent/a1.py`：`ToolRegistry`、`ToolRetriever`、know-how 与 data lake 进入 Agent prompt；模型输出 `<execute>` 后分派到 Python REPL、R 或 Bash。
- `biomni/model/retriever.py`：LLM 从 tools、data lake、libraries、know-how 中选择相关资源。
- `biomni/utils.py`：包含 R/Bash/subprocess 执行；通用 Bash 路径使用 `shell=True`。
- `biomni/env_desc.py` 与 `biomni_env/`：集中登记 Python/R/CLI 软件与大环境。
- 官方 README：默认 data lake 约 11 GB，并明确环境为 massive。

这些是架构事实，不代表对 Biomni 的否定。Biomni 优先解决通用性和科研任务广度；scKG-Agent 优先解决用户数据边界内的可审计执行深度。

## 4. 当前差距

| 维度 | Biomni | scKG-Agent 当前 |
| --- | --- | --- |
| 领域 | 通用生物医学 | 单细胞 scRNA-seq 两个任务族 |
| 动作规模 | 大量工具、数据库、data lake、know-how | 2 个 qualified Action、4 个 qualified tool implementation |
| 代码组合 | 开放 Python/R/Bash | 固定 wrapper + contract-constrained parameters |
| 安全边界 | timeout 与执行观察为主 | approval、ownership、hash、path、wrapper、validator、repair budget |
| 科学评测 | Biomni-Eval1 等广域 benchmark | GSE108313 与 scIB pancreas dataset-scoped pilot |
| 服务化 | Web UI、MCP 示例 | 本地 Streamlit；Phase 7 尚未开始 |

结论：应该学习 Biomni 的 action discovery、资源检索与 generalist loop，但不能为了“像 Biomni”而丢掉 scKG 最有价值的 deterministic safety plane。
