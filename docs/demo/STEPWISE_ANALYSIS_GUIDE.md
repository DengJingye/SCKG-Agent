# Stepwise Analysis 操作手册

更新时间：2026-08-14

## 它解决什么问题

Stepwise Analysis 不是一个独立的机械 Notebook 生成器。它承接 Research Chat 中已经确认的 Doublet Detection + Scrublet 任务，把同一个任务逐步推进到数据画像、代表性 Preview、参数审阅、固定 Notebook、精确审批、受控运行、Validation 和结果解释。

当前只支持本地 `.h5ad` 的 Scrublet 代表性 Preview。它不会执行任意 Notebook cell，也不会把 Preview 结果当作全量数据科学结论。

## 不安装任何新环境的首次体验

当前机器已经存在并通过能力检查的 `doublet-python` Runtime Pack 时，可以直接使用固定合成数据体验完整 Preview：

1. 打开侧边栏 `More -> Runtime Packs`。
2. 找到页面顶部“无需安装：Scrublet 合成数据 Preview”。
3. 确认状态为 `READY`、下载为 `0 B`，点击“直接体验 Scrublet Preview”。
4. 系统会生成或复用 `scrublet_preview_demo.h5ad`，登记到当前本地用户，并带着 `doublet_detection + Scrublet` 任务跳转到 Stepwise Analysis。
5. 依次完成只读画像授权、DataProfile、Preview、参数确认和 Notebook。
6. 若页面提示旧模板，先点击“更新 Notebook（包含新版诊断图）”；否则点击“生成可交互分析 Notebook”。再点击“启动本地 JupyterLab”和“打开 JupyterLab 工作区”。已预选 `scKG Doublet Python` kernel，按章节从上到下逐格运行即可。
7. Notebook 会依次显示 DataProfile、输入 UMI/基因数 QC、参数 provenance、Scrublet 评分、结果表、score/rank/call 三联图和 score manifold。每一段代码前都有用途与解释边界。
8. 只有需要固定 wrapper、Validation、lineage 和审计记录时，才展开“需要审计记录时，使用受控验证运行”，再完成“确认批准 -> 运行验证”。

这个入口不访问网络、不安装 Runtime Pack、不使用私人数据，也不会因为点击而自动执行工具。若本机没有通过能力检查的 Scrublet 环境，入口会明确显示 `BLOCKED`，不会伪造零安装运行。

## 两种运行方式

| 模式 | 适合场景 | 用户体验 | 权威边界 |
| --- | --- | --- | --- |
| 浏览器 Jupyter Notebook（默认） | 学习、探索、调参、逐步看图和定位错误 | 在 localhost JupyterLab 中逐 cell 运行，可修改参数 | 用户自控探索；修改后不自动取得 scKG Validation 或科学权威 |
| 受控验证运行（可选） | 需要固定 wrapper、hash、审批、Validation、lineage 和复现记录 | 两步确认后整体运行 | `preview_engineering_metric`，仍不是全量科学结论 |

“启动本地 JupyterLab”只为 owner workspace 内 hash 完整的维护者 Notebook 启动浏览器编辑器，不自动执行任何 cell。服务器只监听 `127.0.0.1`，使用随机 token，并以 Jupyter core mode 禁用无关第三方扩展。系统会注册一个指向现有 `doublet-python` Runtime Pack 的 `sckg-doublet-python` kernel；Notebook 本身不会执行 `pip install` 或 `conda install`。

`.ipynb` 只描述 cells 与 kernel，不应自行安装环境。scKG 先从已登记 Runtime Pack 中解析兼容 Python；已存在时直接复用，只有确实缺失时才提示独立安装审批。首次进入 Jupyter 时确认已预选的 `scKG Doublet Python` 即可开始逐格运行。

“其他打开方式与下载”提供完整 ZIP bundle，包含 `analysis_preview.ipynb`、`representative_preview.h5ad`、参数、合同和 manifest。不要只把 `.ipynb` 单独移动到 Downloads，否则相对路径中的 Preview 数据会丢失。Cursor 若显示原始 JSON，表示当前没有启用 Notebook renderer；优先使用浏览器 JupyterLab。

## 从聊天进入

1. 在 `Research Workspace` 中提问：`请为 10x PBMC 生成一个经过 smoke 测试、可复制运行的 doublet detection workflow。`
2. 在回答下方找到“从对话继续到数据验证”。
3. 第一次体验点击“用模拟数据在 JupyterLab 试跑”；需要自己的数据时点击“关联我的 .h5ad”。
4. 新页面顶部应显示来源问题、`doublet_detection` 和 `Scrublet`。若任务或工具不一致，返回聊天重新发起任务。

只有 Agent 已识别为 `PLAN`、任务属于正式支持的 Doublet Detection，并选择资格化 Scrublet workflow 时才显示这两个动作。普通原理问答、Top-k caveat、长尾工具问题和未支持任务不会启动 Stepwise。聊天只创建结构化 handoff；登记数据、生成 Notebook、启动 JupyterLab 和执行 cell 都保留明确用户动作。

## 八个步骤

| 步骤 | 用户动作 | 系统保证 |
| --- | --- | --- |
| Register data | 选择已批准目录中的 `.h5ad` | 只登记 hash 和脱敏路径，不复制原始数据 |
| Inspect matrix state | 授权只读画像并生成 DataProfile | 检查 cells、genes、matrix state 与 count source |
| Build Preview | 选择细胞预算并构建代表性子集 | 固定 seed、保存 hash、原文件不修改 |
| Review parameters and code | 检查参数，确认后生成 Notebook | 参数来自 Scrublet ToolContract，编译不执行 |
| Approve exact step | 粘贴精确确认文本；若旧临时资格过期则同时重新签发当前作用域 | capability 与 execution approval 分开存档，审批只用一次 |
| Run fixed wrapper | 勾选 Preview 边界并执行当前 Scrublet 步骤 | 只调用 allowlisted wrapper，`shell=False` |
| Validate artifacts | 等待统一 Validator 完成 | 检查输出、cell 数、score、hash、runtime 与 memory |
| Review result | 阅读图、限制和下一步 | authority 固定为 `preview_engineering_metric` |

## 参数变化

- 初始值来自版本化 Scrublet 0.2.3 ToolContract，不是 LLM 临时猜测。ToolContract 的来源 dossier 包含官方 README 与已审核论文/source text，但不应把每个默认值都描述成“论文直接给出的最佳参数”。
- Notebook 的 parameter provenance 表会区分合同默认、用户确认的默认值和用户覆盖值。比如把 `sim_doublet_ratio` 从合同默认 `2.0` 改成 `1.75` 后会标记为 `user_confirmed_override`。
- `expected_doublet_rate=0.1` 只是合同默认，真实 10x 数据必须按每个 capture 的上样量、回收细胞数和预期 multiplet burden 重新确认。
- 参数输入框只是草案；点击“确认参数并生成/重建 Notebook”后才提交。
- 任一参数变化会显示 change table，并使旧 Notebook、旧审批和当前结果失效。
- 旧结果仍保留在 Runs & Results 供审计，但不再代表当前参数。
- 重新运行必须重建 Notebook，并创建新的 plan-specific approval。

## Notebook 信任边界

- 系统生成的维护者 cell 带 source digest，状态为 `VERIFIED`。
- 用户修改维护者 cell 后状态为 `MODIFIED`；新增 cell 为 `UNTRACKED`。
- 修改后的 Notebook 可以下载和自行研究，但 scKG 不会把它当作在线执行源。
- 页面“执行当前 Scrublet 步骤”始终调用固定 wrapper，而不是 Jupyter 内任意代码。

## DataProfile 与 Notebook 在做什么

DataProfile 是只读的确定性输入检查，不是科学分析结果。它检查 `X`、`raw.X` 和 `layers/*`，识别 raw counts、log-normalized 或 scaled 状态；Scrublet 只接受非负 raw count matrix，因此系统会优先选择合法 `layers['counts']`，无法确定时直接阻断。它同时记录 cells、genes、batch candidates、稀疏性和大致内存需求，避免把错误矩阵静默送入算法。

Notebook 随后按固定教程顺序：读取受控 Preview -> 验证 preview/count-source metadata -> 展示 UMI counts 与 detected genes 输入 QC -> 加载合同参数 -> 分开初始化和运行 Scrublet -> 校验 score/label 数量、有限值与范围 -> 写出 TSV、参数和 warning -> 展示 score distribution、ranked score、predicted calls 与 score manifold。内置 `representative_preview.h5ad` 是固定 seed 的合成工程数据；用户数据场景中的同名文件则是从已登记数据构建的代表性子集，原文件不会被修改。

## 常见阻断

| 页面提示 | 含义 | 处理方式 |
| --- | --- | --- |
| `execution_policy_disabled` | 默认全局策略关闭 | 粘贴确认文本并点击“重新启用并批准这一次 Preview” |
| `local_user_not_allowlisted` | 当前 artifact 尚无临时本地能力 | 同一按钮只签发当前数据、Scrublet 与环境的 30 分钟单次资格 |
| `local_user_allowance_expired` | 旧的临时资格已过期 | 使用新的精确确认重新签发；不需要重建数据或 Notebook |
| `artifact/tool pair not allowed` | 旧资格属于另一数据或工具环境 | 重新核对当前 fingerprint 后签发当前作用域，旧资格不会被复用 |
| `execution_approval_missing` | 尚未批准当前参数与环境组合 | 复制页面确认文本并创建一次性审批 |
| `approval scope/fingerprint mismatch` | 页面持有旧参数或旧 Preview 的审批 | 直接确认当前 Preview；系统撤销旧审批并创建当前 scope 的新审批，不需要返回重做 |
| `parameter_patch_not_committed` | 参数草案与 Notebook 不一致 | 按页面提示更新 Notebook |
| Notebook 模板已更新 | 当前 session 中仍引用旧模板 artifact | 点击“更新 Notebook（包含新版诊断图）” |
| Notebook untrusted | Notebook cell 被修改或新增 | 从 Notebook 步骤重新生成 |
| Cursor 显示 JSON | 编辑器没有使用 Jupyter Notebook renderer | 使用页面的本地 JupyterLab，或在编辑器中启用 Jupyter 扩展 |
| Notebook 找不到 `representative_preview.h5ad` | 只移动了 `.ipynb`，没有携带配套 Preview | 下载完整 Notebook ZIP，并保持文件在同一目录 |
| Jupyter kernel 缺失 | 当前 Runtime Pack 不可用或指纹失效 | 回到 Runtime Packs 检查 `doublet-python`；Notebook 不会自行安装依赖 |
| unresolved count source | 无法确认 raw counts | 修复数据，提供合法 `layers['counts']`、`X` 或 `raw.X` |

## 验收时应该看到

成功 Preview 显示：

```text
fixed wrapper executed = true
run_tool = COMPLETED
validate_outputs = COMPLETED
validation passed = true
source unchanged = true
original data copied = false
scientific claim allowed = false
```

完整 hash、审批指纹、checkpoint 和 ValidationResult 收在高级详情；普通用户默认只看当前步骤、下一动作、结果图和限制。
