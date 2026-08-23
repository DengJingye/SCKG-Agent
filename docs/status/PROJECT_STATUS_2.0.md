# scKG-Agent 2.0 项目状态

更新时间：2026-08-14
当前正式 Phase：Phase 5（`completed`）；Phase 6 保持 `PHASE6_TRIAL_READY`
主规约：`docs/DEV_SPEC_2.0.md`
主规约版本：2.9.12-dev
作品集状态：`EVALUATION_PIPELINE_IMPLEMENTED / RESEARCH_CHAT_RELEASE_GATE_BLOCKED`
全局执行策略：`disabled`（默认）
科学验证：`scientific_pilot`

### 2026-08-14 Stepwise Tutorial Notebook v3 检查点

- Research Chat synthetic handoff 的 Streamlit widget-state 冲突已修复：artifact selection 在下一轮、selectbox 创建前应用。
- `notebook_shadow.py` 已纳入 backend cache identity，热更新后不会继续用旧 compiler；旧 Notebook digest 会显示明确更新动作。
- Scrublet Notebook 从大块代码拆为 21 个教程式 cells，并生成输入 QC、score/rank/call 与 manifold 三组内联诊断图。
- 定向回归=`27 passed`，fresh full regression=`505 passed, 6 warnings in 654.03s`；clean-kernel Notebook smoke 与浏览器 JupyterLab E2E 均通过，没有安装依赖、自动执行或创建 ExecutionRequest。

### 2026-08-13 Chat-Governed Stepwise Analysis 检查点

- Research Workspace 的 smoke-tested workflow 回答现在可生成受治理 `workspace_handoff`；只有 Doublet Detection + Scrublet 能进入 Stepwise Analysis。侧边栏不再提供脱离任务上下文的 Data & Preview 入口。
- Stepwise Analysis 固定显示来源对话、任务与工具，并按 data registration、profile、representative Preview、parameter review、Notebook、exact approval、fixed-wrapper execution、Validation 和 result review 推进。
- Preview 后不再自动生成 Notebook。用户确认的合同参数保存快照与 provenance；参数变化产生 patch，使旧 Notebook、approval 和 result stale，旧审批不能跨参数复用。
- Notebook Shadow 保存 task-context digest 和每个维护者 cell 的 source digest。修改维护者 cell 或新增自定义 cell 会降为 untrusted，并阻断 scKG 在线执行；在线按钮从不执行 Notebook 任意代码。
- 受控 Preview smoke 已验证固定 Scrublet wrapper 实际执行、120 cells、Validation passed、`run_tool -> validate_outputs` 事件完整、一次性 approval consumed、source unchanged、input not copied、scientific authority=false。
- 当前默认 `ExecutionPolicy=disabled`；本地 Preview capability 是当前 artifact、30 分钟、最多一次的临时能力启用，仍必须完成独立 execution approval。
- 最终 fresh full regression=`496 passed, 6 warnings`；Mainline Quality Gate=`6/6`，unauthorized ExecutionRequest=0、candidate/evidence leakage=0、双黄金 package integrity=true。桌面与 820px 浏览器验收通过，Streamlit health=`ok`，`git fsck` 与 `git diff --check` 均通过。
- 当前验收状态为 `P1_STEPWISE_SCRUBLET_VERIFIED`：只开放受治理的 Scrublet representative Preview；任意 Notebook 代码、全量科学结论和其他工具的 cell-level interactive execution 仍不属于当前能力。
- 2026-08-14 修复过期本地资格造成的审批死锁：当且仅当 blocker 全部可由当前 exact scope 重新签发解决时，确认按钮可同时创建 30 分钟单次 allowance 与一次性 approval；运行仍需第二个显式动作。execution/workspace/preview resource cache 现在绑定实现 digest，避免热更新后新 UI 复用旧 service instance。
- 上述修复后的 fresh full regression=`498 passed, 6 warnings`；Mainline=`6/6`，真实 Preview smoke、Git 完整性与本地服务健康检查全部通过。
- 操作手册：[`docs/demo/STEPWISE_ANALYSIS_GUIDE.md`](../demo/STEPWISE_ANALYSIS_GUIDE.md)；事故复盘：[`docs/status/ISSUE_RETROSPECTIVE_LOG.md`](ISSUE_RETROSPECTIVE_LOG.md)。

### 2026-08-14 Zero-install Scrublet Demo 检查点

- Runtime Packs 页面首先展示本机已就绪的 `doublet-python` 能力，而不是要求用户安装尚未资格化的 Annotation Pack。
- “直接体验 Scrublet Preview”生成或复用固定 `240 cells × 500 genes` synthetic AnnData；`X` 为 log1p 表达，`layers['counts']` 保存非负整数 counts，并明确 `scientific_claim_allowed=false`。
- 点击只登记当前本地 artifact、绑定 `doublet_detection + Scrublet` handoff 并进入 Stepwise Analysis；下载量为 `0 B`，不访问网络、不创建安装记录、不创建 ExecutionRequest，也不自动运行。
- 无兼容 Scrublet Runtime Pack 时入口保持 `BLOCKED`，不得把缺失环境伪装为零安装体验。
- fresh full regression=`501 passed, 6 warnings`；Mainline=`6/6`，真实 Preview smoke 与零安装入口定向回归均通过。
- Synthetic Demo 的运行区已收敛为“1. 确认并批准当前 Preview -> 2. 运行并验证 Preview”；Policy、fingerprint 和内部 blocker 默认隐藏。旧 approval scope/fingerprint 不匹配会要求并允许创建当前 scope 的新审批，不再出现 Approval 显示 READY 但按钮永久禁用的矛盾状态。
- Notebook 现为 Preview 默认交互入口：系统生成参数/运行/验证/绘图 cells 后，可一键在本机 Cursor 打开，自动提供 `sckg-doublet-python` kernelspec；用户可逐格运行和修改参数。受控 wrapper + approval + Validation 保留为折叠的可选审计路径。
- Interactive Notebook 改造后的 fresh full regression=`503 passed, 6 warnings`；clean-kernel smoke 与 launcher workspace/hash/trust 安全检查均通过。
- 交互主入口已从 Cursor CLI 改为 localhost JupyterLab：使用 base 中现有 Jupyter 控制面和 `doublet-python` Runtime Pack kernel，不自动安装、不自动执行。服务只监听 `127.0.0.1`，随机 token，root 限定当前 Notebook 文件夹，并启用 core mode 去除无关第三方扩展。
- Notebook 下载改为完整 ZIP，包含 `.ipynb`、`representative_preview.h5ad`、参数、合同与 manifest；解决单独下载 `.ipynb` 后相对数据路径失效的问题。Cursor raw JSON 仅作为 renderer 缺失提示，不再作为默认入口。
- Browser Jupyter 收口后的 fresh full regression=`505 passed, 6 warnings`；真实 Jupyter HTTP/Notebook E2E、clean-kernel Notebook smoke、bundle 完整性和页面零自动执行均通过。
- Notebook 诊断已从“只保存 PNG、界面只见表格”修复为内联结果表、score/threshold 分布和 singlet/doublet 数量图；clean-kernel smoke 同时校验 `.ipynb` 的真实 `image/png` output 与磁盘 artifact。DataProfile 作用和逐参数 provenance 已写入 Notebook，Scrublet numeric warnings 保存为审计 artifact。
- Research Chat 的资格化 workflow 现在提供两个上下文动作：“用模拟数据在 JupyterLab 试跑”与“关联我的 .h5ad”。聊天携带任务/工具/计划进入 Stepwise，但页面渲染不登记、不启动 Jupyter、不执行 cell；本地进程仍需用户明确点击。

### 2026-08-12 Research Workspace P1 Shadow 检查点

- 已审阅《scKG-Agent 后续更新规划计划手册 v1.0》。总体方向适配现有主线，但采用四项收束：复用 DataRegistry 而非新建 Path Registry；P1 不重建全局 ResearchState；Notebook 只允许维护者固定 StepTemplate；首个 Notebook 仅覆盖 Scrublet，跨语言与用户数据自动运行延后。
- 新增 backed/read-only `DataAssetProfile`：检查 `X/raw.X/layers`、结构字段、batch candidates、count source 与内存估算，仅抽取有界样本，记录 `full_matrix_materialized=false`。
- 新增固定 seed、可分层的 `RepresentativePreviewManifest`；原始 `.h5ad` hash 前后保持一致，Preview 复制到受控 workspace，`scientific_claim_allowed=false`。
- 新增由 Scrublet ToolContract 派生的 `StepContract` 与固定 `NotebookShadowCompiler`；Notebook 保存参数/来源/provenance/validation cells，编译阶段 `executed=false`、`ExecutionRequest=0`。
- `scripts/run_path_to_preview_notebook_smoke.py` 已在现有 `doublet-python` Runtime Pack 的独立 kernel 中真实执行 synthetic Preview，产出 `doublet_results.tsv`、参数快照和 doublet score 图；这只证明工程兼容，不是全量科学结论。
- Streamlit Research Workspace 增加薄层 Shadow 面板，可完成本地路径登记、profile 授权、backed profile、Preview 和 notebook 下载；页面渲染不自动画像、不执行工具。
- 完整 UI 状态推进测试首次发现嵌套 expander 崩溃，已改为 popover 并新增 path/register/authorize/profile/preview/notebook/download 端到端回归。修复后定向测试=`13 passed`，fresh full pytest=`464 passed`。全局 `ExecutionPolicy=disabled`；现有正式执行范围和 Phase 状态不变。

### 2026-08-12 Controlled Preview Runtime 检查点

- 新增 `PreviewRunPreparation / PreviewRunRequest / PreviewRunResult / ErrorContext`，Preview 审批精确绑定 artifact、Preview、Notebook、参数、合同、环境和用户，默认单次消费，replay 与合法参数变化均失效。
- `representative_preview` 作为独立 execution purpose 接入固定 Scrublet wrapper、`LocalControlledExecutor` 和统一 `DoubletValidator`；不再把用户 Preview 伪装成 synthetic qualification。Validator 不计算缺少 ground truth 的 F1/AUPRC，authority 固定为 `preview_engineering_metric`。
- Streamlit 增加 Controlled Preview Run 薄面板：默认只显示 policy/runtime/approval/blocker；明确确认和审批后才可运行，输出 score 表、诊断直方图、runtime、peak memory、Validation 与脱敏 ErrorContext。页面按钮从不执行可编辑 Notebook。
- 真实 Preview smoke：120 个代表性细胞，固定 Scrublet wrapper 实际执行，validation passed，直方图生成，source hash unchanged，approval consumption=1，scientific claim authority=false，原始数据未复制。
- fresh full pytest=`468 passed, 6 warnings`，耗时 `188.75s`；Mainline=`6/6`，unauthorized execution=0，candidate/evidence leakage=0；`git diff --check` 通过。全局默认 `ExecutionPolicy=disabled`，没有开放任意代码、全量用户数据或新工具。
- 已补齐 Preview 结果恢复：`PreviewResultStore` 保存 result JSON 与独立 SHA256，刷新或重启后可在 `Runs & Results` 按 owner 恢复 `COMPLETED/BLOCKED/FAILED`；读取时重验 result、artifact hash 与路径 containment，篡改产物不再展示。
- Preview 持久化与 UI 定向回归=`15 passed`，包含跨用户隔离、blocked terminal state、result/artifact 篡改、symlink escape、空历史和页面零执行副作用。fresh full pytest=`474 passed, 6 warnings`；Mainline=`6/6`；更新后的 Preview smoke 验证新 service 实例可恢复结果且 integrity valid。
- 新增 `PreviewLineageSnapshot + WorkspaceCheckpointService`：六段状态固定为 source/profile/preview/notebook/approval/result；源数据、Preview、参数/Notebook、StepTemplate/ToolContract、environment 和 result artifact 漂移均从最早节点确定性传播 `STALE`。已消费的成功 run approval 不误判，旧 lineage 结果降级为 STALE。
- Research Workspace 与 Runs & Results 均显示 checkpoint，提供显式 `Reset from <stage>` 只清理下游 session 引用，不自动 profile/approval/execution。真实 Preview smoke 的 checkpoint=`CURRENT`、checkpoint ExecutionRequest=0。
- checkpoint/stale 完成后的 fresh full pytest=`480 passed, 6 warnings`；Mainline=`6/6`；unauthorized ExecutionRequest=0、candidate/evidence leakage=0，`git diff --check` 通过。
- 新增确定性 `PreviewResultInterpreter + PreviewErrorIntelligence`：成功结果解释 Preview cell/call rate/score quantile/runtime/memory、参数作用与直方图读法；stale、policy/runtime/parameter/validation/integrity 失败按 stage 分类并指向显式恢复动作。解释不调用 LLM、不自动调参或重试，scientific authority 始终 false。
- Research Workspace 与 Runs & Results 默认展示“发生了什么、能说明什么、不能说明什么、下一步”；完整 Validation、lineage、hash 与 trace 继续隐藏在高级详情。
- fresh full pytest=`488 passed, 6 warnings`；Preview smoke 的 interpretation=`COMPLETED`、automatic actions=0、scientific authority=false；Mainline=`6/6`、unauthorized ExecutionRequest=0、candidate/evidence leakage=0。回归过程中发现并修复 Runtime Pack usage 原子写入竞态，已增加线程/跨进程测试。
- Notebook 修改后的 cell-level trust downgrade 已完成；scDblFinder 跨语言 Notebook 仍 deferred。当前状态是 `P1_STEPWISE_SCRUBLET_VERIFIED`，不是所有任务族的交互式 Notebook 已完成。

### 2026-08-04 Research Chat claim-aware 修复检查点

- 修复显式工具和任务串台：Scrublet 输入、Harmony 输入/输出、Scanorama 的 Scanpy 输出位置现在分别锁定正确工具、canonical task 与 claim type；普通交叉验证问题进入 GENERAL，不再检索随机单细胞工具。
- Hybrid Retrieval 增加 content-level tool attribution、claim-type compatibility、广义发现按工具限额和 unsupported-operation hard filter；共享 benchmark 的 source association 不再自动等价于正文支持某个工具。
- DeepSeek grounded synthesis 只接收经过 governed selection 的最小证据集，并把 requested tools/required claim types 作为 coverage contract；claim audit 会拒绝 input/output/failure/benchmark 与 citation 类型不匹配的回答。
- fresh full pytest=`453 passed`。96-case 中 `KG+BM25` Recall@10/Precision@10/MRR/span=`0.996212/0.931088/0.991477/1.0`，p95=`75.905 ms`；`KG+Hybrid+ToolContract` 为 `0.996212/0.929951/0.991477/1.0`，p95=`93.596 ms`；false-support 和 governance leakage 都为 0。
- 因 Dense 没有提高主要质量指标，当前 route policy 选择 `KG+BM25` 默认，Dense 仅在 ambiguous、migration 或 source coverage 不足时自适应升级。该结论是“Hybrid 能力存在但当前 corpus 无默认收益”，不是失败或强行切换。
- 统一 PR 评测除刻意跳过的 pytest 项外全部通过；fresh pytest 已独立通过。CLI 尚未解锁本地加密 DeepSeek 配置，因此 live DeepSeek 重放和独立 Judge 仍为 `not_run`，作品集状态继续 `RESEARCH_CHAT_RELEASE_GATE_BLOCKED`。

### 2026-08-04 评估驱动开发检查点

- 新增统一 `pr/nightly/release` 评测入口和不可变 experiment registry；Portfolio、Continuous Evaluation 与 Evaluation UI 优先读取同一实验，不再各自选择旧 summary。
- 建立 component/conversation/execution 三层版本化数据 schema；科学 answer gold 必须包含原子 claim、scope 与 source span。首批 8 条严格 case 是 schema seed，不代表开放世界题库规模已经充分。
- 新增 macro-F1/confusion、trajectory 工具/参数/顺序/禁止动作、atomic claim/citation、回答正文 hash、最早失败 stage、paired regression 和并列 release gate。
- 独立 Judge 必须与生成模型隔离并通过 20 条以上校准；当前未配置独立 Judge，因此 claim correctness/nightly semantic gate 保持 `not_run`，不会回退为 DeepSeek 自评。
- 首次编排诊断已生成完整七类 artifact，并按预期因跳过 pytest/workflow smoke 阻断。300-run 的 blocker correctness=`0.963333` 经复核属于旧 ASK gold 将“否定回答”误标为系统 BLOCKED，已降为兼容诊断；安全 gate 现只使用 action-specific gold。Research Chat 的开放答案与独立 Judge 仍未完成，因此 RC 继续保持 blocked。
- GitHub PR workflow 已增加无密钥、strict-offline 的确定性测试与 dataset audit；不触发 LLM、安装或科学执行。
- 最新完整 PR experiment 为 `.sckg_exec/evaluations/eval-pr-20260804T053805459139Z`：fresh pytest=`445 passed`，dataset/schema audit、安全 gate、96-case retrieval、package integrity、trace completeness 与两个 workflow smoke 均通过。Doublet/Batch smoke 已统一通过 Runtime Pack resolver 直接调用固定解释器，不再依赖控制面 Python 或 `conda run`。
- 该实验诚实返回 `BLOCKED`：`domain/intent/task macro-F1=0.555556/0.555556/0.333333`，citation precision/coverage=`0.083333/0.333333`。失败已归因到 gateway、intent_parse、retrieval 与 answer/citation stage；评测体系已验收，但 Research Chat 语义与引用质量未达到发布线。

### 2026-08-03 v2.8 开放世界可靠性检查点

- 自然问题 visible bank 已升级为三类独立 gold：`routing_gold=85`、`answer_gold=11`、`safety_gold=11`。安全请求不再用普通 intent 标签判分；无 source ID 的 route-only case 不再进入 citation/claim 指标。
- live evaluation panel 现固定为 28 条：24 条 evaluation + 4 条 answer gold。Safety gold 由零 provider-call 的确定性 lane 单独验收，不再消耗外部模型预算。此前 32-case 分层方案保留为历史记录，但在两阶段 LLM 工具链下会需要 224 次 provider call，超过本轮 200 次上限。
- Research Chat 新增 `ConversationTaskState`、独立 `ActionSafetyDecision/AnswerabilityDecision`、受 build ID 约束的跨轮状态和 `GroundedAnswerAuditV3`。V3 只报告 lexical/source/scope/numeric 结构支持；`semantic_claim_correctness` 未经独立 judge 时保持 `null`，不得再把词项重叠称为语义 entailment。
- 单细胞 ASK 已实现为 `DeepSeek semantic/tool plan -> read-only KG/RAG/Contract tools -> DeepSeek grounded synthesis -> claim audit`。通用 GENERAL 问答只调用一次 DeepSeek；单细胞 ASK 标准为两次 provider call；PLAN 只做一次语义解析并返回固定 smoke-tested bundle；Safety Precheck 在模型前阻断且 provider call=0。工具 registry 不暴露 shell、安装器、Executor 或 evidence 写入。
- Safety Precheck 已明确阻断 approval/ToolContract bypass、approval replay、自动安装、title-only benchmark、catalog-only promotion、memory-as-evidence、任意 shell 与路径/密钥访问；最新分层面板中 KG/RAG-only 的 action correctness 从旧误标下的 0.50 修复到 `1.0`，`ExecutionRequest=0`。
- 该历史检查点当时 fresh full pytest=`417 passed`；Mainline=`6/6`。未授权本轮 DeepSeek A/C/D/E 外发，因此四条外部路线真实状态为 `not_run`；hidden 24 条未运行。最新测试数与发布状态以上方 2026-08-04 评估驱动开发检查点为准。
- 最新 28-case 诚实本地基线为 `KG/RAG-only`：domain=`0.807692`、intent=`0.666667`、task=`0.9`、clarification=`1.0`、safety action=`1.0`、citation precision=`1.0`、structural support=`1.0`、unsupported claim=`0`、read-only tool success=`1.0`、unauthorized execution=`0`、candidate leakage=`0`、p95=`73.451 ms`。该结果证明工具、引用与治理层可用，但纯本地语言理解仍远未达到发布门槛。
- 当前不得恢复 Research Chat RC。解除条件仍是：显式授权完成 A/C/D/E 同题消融、独立 claim correctness 抽检、冻结最佳路线后仅运行一次 hidden。

## 1. 原始阶段映射

| 原始 Phase | 当前状态 | 实际内容 |
| --- | --- | --- |
| Phase 0 | completed | 规约、评测与安全基线建立 |
| Phase 1 | completed | execution models、AnnDataProfiler、首个 contract/environment registry |
| Phase 2 | completed | dry-run WorkflowPlan Compiler 与 deterministic Router |
| Phase 3A-E | completed | Scrublet synthetic engineering qualification、Validator、聚合与 Level 2 package |
| Phase 3A-S | completed as pilot | GSE108313 Cell Hashing PBMC 单数据集 scientific pilot |
| Phase 3B | completed | Scrublet 0.2.3 + scDblFinder 1.24.0 双工具受控执行、统一验证、跨工具 Pareto 与 scientific pilot |
| Phase 4 | completed | ExecutionOrchestrator、bounded RepairPolicy、CandidateEvaluation、Decision Engine 与 repair lineage |
| Phase 5 | completed | Harmony/Scanorama 双工具受控执行、工程资格、scIB pancreas scientific pilot、跨工具 Pareto、Level 2 package 与 ActionBundle 晋升 |
| Phase 6 | trial_ready | 授权、审批、ownership、受限本地执行、取消、复现包、Streamlit UI、双轨 baseline、答辩 Demo、trace audit、failure queue 与匿名 telemetry 已完成；真实组内试用尚未开始 |
| Phase 7 | not_started | FastAPI、MCP、远程 worker 和服务化均未开始 |

`Release Hardening` 不是新的正式 Phase；若开展，只能作为对应 Phase 的发布验收活动记录。

## 2. 当前真实能力

### 2.0 唯一 Agent 主链

- 唯一应用任务入口为 `ResearchChatService.run_request`，公共模式为 `ASK / PLAN / RUN`。
- 主 UI 已移除基于 `run_sckg_workflow_traced` import 状态的新旧链切换；`agent/workflow.py` 仅保留为历史 Track-A baseline。
- 高层应用图固定经过 Gateway、Requirement Parse、Action Retrieval、可选 Plan Compile、Deterministic Route 和 Answer/Execution Handoff。
- 当前 `sckg_env` 已安装并使用 LangGraph；若可选调度依赖不可用，确定性 scheduler 仍调用同一组节点函数，业务、证据与安全权限不变。
- `Research Workspace` 是唯一发起任务入口；`Runs & Results` 复用既有授权/执行后端；`Graph Explorer` 只负责知识与 Action Space 检查。
- 正式执行范围仍只有 Doublet Detection 与 Batch Integration。Harmony/Scanorama 已接回本地用户准备与验证路径，使用 `IntegrationValidator`，不会再误用 DoubletValidator。
- `RUN` 缺数据时返回可恢复的 WAITING；任务/合同本身不受支持时安全否决优先返回 BLOCKED；两者均保持 `ExecutionRequest=0`。

### 2.1 工具与科学试验

- Scrublet 0.2.3：contract、Python wrapper、`scRNAseq` 环境、Validator、engineering qualification 和 scientific pilot 已完成。
- scDblFinder 1.24.0：独立 R/Bioconductor 环境、Python/R wrapper、Validator、engineering qualification 和 scientific pilot 已完成。
- 两个工具已在相同 synthetic probe 和 GSE108313 固定 evaluation split 上进入 CandidateEvaluation/Pareto；不直接比较原始 doublet score。
- scientific pilot 只覆盖 GSE108313 PBMC，HTO 主要标记跨样本 multiplet，不支持“任一工具普遍最优”的声明。
- Batch Integration：Harmony 2.0.0 与 Scanorama 1.7.4 已固定在独立 `sckg-batch-cpu` 环境；contract、wrapper、统一 `IntegrationValidator`、12+2 engineering qualification、跨工具 Pareto 与 Level 2 package 已完成。
- scIB pancreas scientific pilot：16,382 cells、9 batches、14 cell types；固定 3,000 development / 3,000 evaluation split，cell overlap=0。10/10 真实运行和验证通过，500 次 bootstrap CI 已记录。
- evaluation 上 Harmony `theta=4.0`：mixing ASW 0.9117、biology conservation ASW 0.5849、runtime 1.72 s、peak memory 268.8 MB；Scanorama `approx=false`：0.8053、0.5478、2.83 s、456.1 MB。两者均在 Pareto frontier，本数据集 scoped 推荐 Harmony；不得外推为普遍最优。
- `TaskDataGate` 已将 Batch Integration 与 Doublet Detection 的数据资格分离：前者要求可解析 representation、batch key 和至少两个完整 batch，不要求 raw count source；可选 biology label 缺失时只允许明确降级。

### 2.2 执行、授权与 UI

- `DataRegistry`：只登记 artifact ID、redacted path、hash、owner、size、类型和时间；不复制输入。
- `ApprovalService`：数据授权与 execution approval 分离；approval 绑定 user、artifact、plan、tool/contract、environment 和 parameter hash，支持过期、撤销、消费与防重放。
- `UserWorkspaceService`：用户级 run/package ownership、取消与 retention audit 已实现。
- `LocalUserService`：复用现有 Executor、Validator、RepairPolicy、CandidateAggregator、Pareto 和 Packager，不复制执行链。
- Runtime Pack foundation：新增 `RuntimePackManifest/Registry/Manager/Resolver`、环境 plan/approval/record/probe、detached Ed25519 maintainer signature；现有 `scRNAseq`、`scDblFinder-R`、`sckg-batch-cpu` 被解析为 `doublet-python`、`doublet-r`、`batch-cpu` 三个 compatibility pack，四个 wrapper 已移除硬编码 Conda 根路径。
- Mac Beta clean-prefix：已在当前 Apple Silicon Mac 的全新 `SCKG_HOME` 中关闭 legacy fallback，使用固定 Micromamba 2.8.1 和独立 control-plane lock 完成冷启动；三个 Pack 均从签名 lock 安装、import smoke、卸载和重建成功。该结果是当前机器隔离演练，仍缺第二台干净 Mac 复验，状态保持 `RELEASE_CANDIDATE`。
- 环境安装 approval 与 execution approval 分离：缺环境时路由为 `WAITING_ENVIRONMENT_APPROVAL` 且 `ExecutionRequest=0`；manifest digest、lock SHA256、平台、磁盘配额、显式确认和 import smoke 任一失败都不能进入 ready。
- 本地产品入口：`python -m cli.sckg doctor/packs/launch` 与 Streamlit `Runtime Packs` 一级页面调用同一 application service；页面渲染不安装依赖，全局 policy 仍为 `disabled`。
- 隐私模式：`LOCAL_HYBRID` 默认、`STRICT_OFFLINE` 与显式 `CLOUD_ASSISTED` 已建模。外部模型默认无网络许可；矩阵、barcode、完整路径和上传文件正文从 outbound payload 删除，audit 只保存 disclosure hash 和字段摘要。
- Release manifest：候选 Mac ZIP 为 3,731,162 bytes，解压候选内容 33,327,037 bytes，控制平面首次占用加核心内容为 815,732,184 bytes；检查确认不包含 `.sckg_exec`、dataset、PDF、legacy embedding、`.env`、密钥或完整本地路径。SBOM 记录 481 个锁定组件，release privacy issues=0。
- Streamlit：已统一为紧凑本地工作台，核心导航先于最近对话；受限本地执行页面可查看 DataProfile、dry-run plan、blocker、fingerprint、run、Validation、Decision 和 package，页面渲染不会触发执行。
- Bounded Parent Agent：已将自然语言 gateway、governed GraphRAG、contract/environment、DataProfiler、dry-run planner 和 deterministic Router 接成统一 plan-first loop；UI 可试跑自然语言规划，但不能创建 ExecutionRequest。
- Action Space v1：Parent Agent 不再只消费工具候选，而是读取 contract-grounded `ActionBundle`；bundle 同时包含 Action、I/O、数据假设、参数、环境、失败模式、验证规则、reviewed know-how、source material 与 dataset-scoped evaluation，且不能授权执行。
- Phase 6 评估：旧双轨 harness 中 A2 冻结 workflow/RAG 基线与 B3/B4 成对执行/repair 基线已运行；A1/B1/B2 保持 `not_run` 或 `not_run_safety_boundary`。另新增 48 条 deterministic portfolio gold case，并在 16 条代表 case 上完成 A2 ordinary RAG、A3 KG-RAG、A4 KG-RAG + ToolContract 共 48 次 `deepseek-v4-pro` 同 case 调用。
- Portfolio v2 结果：A2/A3 tool recall 为 0.65625/0.78125；A4 raw proposal 的 tool recall 0.78125、blocker correctness 0.604167、I/O compatibility 0.416667、source coverage 0.9375，说明原始模型并不可靠。经过只读 ActionBundle、ToolContract 和 deterministic policy admission 后，A4 的 routing/tool/blocker/parameter/I-O/source/trace 均为 1.0，unauthorized execution 与 unsupported action 均为 0，hard gate 通过且 `a4_not_worse_than_a3=true`。该结论证明治理平面的价值，不代表 LLM 本身达到满分。
- Audited Parent Agent：统一 trace 已串联 Gateway、KG-RAG/ActionBundle、DataProfile、WorkflowPlan、Router、Approval、controlled execution、Validation/Repair、Decision 与 Package，并显式区分 proposal、knowledge、safety、execution、validation、packaging authority；LLM 不能覆盖确定性 veto。
- 答辩 Demo：旧 synthetic success/repair/approval-hash blocked bundle 继续通过；新 interview bundle 固定展示 Doublet Detection success、Batch Integration success、bounded repair 和 correctly blocked 四类案例，适用 trace stage completeness=1.0，blocked `ExecutionRequest=0`，package integrity 全部通过。
- Biomni 对照：已对官方 `snap-stanford/Biomni` 做只读 commit-level 审计并形成 Adopt/Adapt/Reject 矩阵；未安装其大型环境、未复制源码、未修改 execution allowlist。
- 组内试用：Defense Demo 已内置 Trial Task Runner，支持匿名 session、逐任务计时、help count、断点恢复、脱敏 notes、critical/safety error 和结构化 gate；维护者 Level 1/2 rehearsal 已通过且被明确排除，当前真实参与人数仍为 0。

### 2.3 Canonical Knowledge Snapshot、Source Corpus v2 与 Hybrid RAG

- 本地唯一事实源为 `data/canonical_knowledge/manifest.json`；每次构建生成 content-addressed snapshot ID，并将 Catalog Graph 和 Decision Graph 绑定到同一 `source_digest`，当前 `projection_drift_count=0`。Neo4j 是可选投影，不再是本地事实源。
- catalog 保留 1,847 条 source record；工具名大小写归一后形成 1,839 个 canonical Tool 节点。这是发现覆盖，不是 1,839 个已验证能力。
- canonical ontology 只保留 15 个 task family，junk/hash task=0。当前 Catalog Graph 为 `kg-v2.3.0-canonical`：7,537 nodes / 17,667 edges，dangling edge=0，unsupported capability edge=0。
- 图质量拆分报告：catalog connectivity=1.0，source-bound semantic coverage=0.008700，contract-qualified coverage=0.002175，formal evidence coverage=0。不再用“单连通分量”暗示科学语义完整。
- 四个 qualified tool（Scrublet、scDblFinder、Harmony、Scanorama）的 governed path coverage=1.0；全部拥有 ToolContract、Task、Environment、DatasetPilot 和 EvidenceSource 路径。
- Decision Graph 为 canonical snapshot 的受控投影：1,058 nodes / 1,318 edges，16 个 source-rich tool、4 个 decision-ready tool、3 个 Action 和 6 个 ActionBundle。Doublet Detection/Batch Integration 的 4 个 bundle 具备执行合同资格；Cell Type Annotation 的 2 个 bundle 仅为 planning-only。contract I/O coverage=1.0，hypothesis edge=0。
- Source Corpus v2 首批覆盖 16/16 核心工具，保存 37 个 source record 和 783 条 EvidenceChunkV2；所有 source chunk 都有 canonical task 与 section/source span，错误的 `bbad418`/PanomiR annotation 来源保持 quarantine。
- 本地 `BAAI/bge-m3` Model Pack 已安装并锁定 revision `cb1779f90b988b8deb01f9155c790ef9417d7648`；773 条 source-bound、非 catalog-only chunk 已生成 1,024 维归一化 NumPy index。模型与缓存位于 `SCKG_HOME/model_packs/`，不进入 Git；缺失或 digest/order 失配时自动回退 `KG + BM25`，不调用云 embedding。
- 96 条 source-bound gold query 六路线消融已完成。2026-07-27 fresh run 中，`KG + BM25` 为 Recall@10=0.931818、Precision@10=0.898620、MRR=0.980114、span=0.988636、false-support=0、p95=40.324 ms；`KG + Hybrid + ToolContract` 为 0.971591、0.912256、0.991477、1.0、0、p95=37.361 ms，parameter legality=1.0、governance leakage=0。
- 独立 BM25、Dense 和 BM25+Dense 均因 hard-negative false-support=0.125 未通过。governed Hybrid 同时提升四个主要指标且未破坏治理/延迟 gate，因此 route policy 当前默认 `KG + Hybrid + ToolContract`；该结论不是“向量天然优于图谱”，而是 KG hard filter 消除了 dense 的 false support。
- Research Chat 已接入 canonical task normalization、route-policy-controlled Hybrid RAG、source span、I/O compatibility、blocker 和 dry-run plan。LangGraph、dense、Neo4j 或外部模型缺失时使用 deterministic Parent Agent fallback，不再将缺模块异常显示给用户。
- Research Chat 已修复回答意图塌缩：方法推荐、明确 workflow、top-k caveat、证据问答和算法迁移分别使用独立输出协议；只有明确 workflow 请求才编译 dry-run plan。多轮 follow-up 可继承已确认任务，但 Parent Agent 不得把普通问答强制改成工作流。
- 2026-07-22 修复 follow-up 历史文本污染：追问只分类最新句子，上一轮 task 只通过 conversation context 继承；“Top-3 caveat -> 整理成可执行 workflow” 回归用例已固定。
- Research Chat 已实现受控外部 prose/semantic layer，并完成 `deepseek-v4-pro` 真实调用验收。最终 5-turn=5/5，20 case × 3=60/60 completed，所有硬性质量/治理 gate 通过。模型失败时仍显示 `DEGRADED LOCAL FALLBACK`；LLM 不生成 ExecutionRequest，也不能覆盖治理 gate。`.env` 可被验收进程显式读取，但 macOS dataless 文件仍可被系统回收；产品 UI 仍推荐使用 Settings 的本地加密保存/解锁。
- 2026-07-30 修复逐消息 AUTO 路由、显式任务切换和省略型追问继承：PLAN 不再粘住后续 ASK，蛋白质结构预测/CellPhoneDB 不再回退到 doublet detection。外部调用调度保证每轮最多一次 provider request：已知 ASK 使用 grounded prose，PLAN/RUN 或未知任务使用 semantic parse，随后由确定性 Planner/Router 决定生成或阻断。
- 2026-07-31 根据真实 UI 重放新增 domain gate：系统问题走本地 `SYSTEM_INFO`；普通非单细胞 ASK 走显式授权的通用 DeepSeek 层并跳过 scientific retrieval；只有单细胞任务/实体命中才进入 KG+RAG+Contract。越界 PLAN/RUN 直接 `UNSUPPORTED_ACTION`，候选与引用均为空、`ExecutionRequest=0`。此前“所有未知问题默认 EVIDENCE_QA”导致 Scrublet/cell2location 随机代答的路径已移除。
- 两个 `WorkflowCodeBundle` 已落地：Scrublet 配方支持 PBMC-like synthetic demo、用户 `.h5ad`、TSV/标注 h5ad/诊断图；Harmony 配方支持 405×320、3-batch synthetic demo，输出 integrated embedding、h5ad、before/after 图和 summary。两者均通过真实工具 smoke，属于 engineering recipe，不是普遍科学准确率声明。
- 用户主回答优先展示算法选择、适用条件、输入要求、限制和下一动作；source span 收敛为就近引用与末尾参考资料。迁移候选仅作为 `exploratory_hypothesis` 展示，不能进入执行、formal evidence 或科学结论。
- Memory 已统一到 `SCKG_HOME/state/workbench.sqlite3`，逻辑分离 explicit/pending preference、episodic run、reflection 和去重 skill candidate；支持确认、冲突处理、导出、删除和用户隔离，memory scientific authority 始终为 false。
- CellTypist 1.7.1 与 SingleR 2.14.0 已通过 24-case annotation retrieval admission，governed routes 均为 Recall/Precision/MRR/span=1、false-support=0；profiler、synthetic probe、固定 wrapper、共享 Validator、聚合/Pareto、Zheng68K manifest/split/evaluator 和受签名保护的 Runtime Pack 已实现。
- Annotation 仍是 `implemented_unqualified`：环境和 reference pack 未安装，Zheng68K 冻结 h5ad/manifest/label mapping/split 未登记，真实 2×3 qualification、scientific pilot 和复现包均未运行。二者保持 `environment_status=missing`、`execution_status=untested`、`scientific_validation_status=not_evaluated`、`enabled_for_execution=false`；Parent 返回 `CONTRACT_REVIEW`，`ExecutionRequest=0`。
- Graph Explorer 保留独立一级页面、拖拽、缩放、平移、搜索和分批展开；Chrome/Safari 的双击展开与节点拖拽使用相同事件模型，拖拽期间只更新几何位置，不重建 DOM。图坐标不表达流程顺序，顺序只认 `PRECEDES/REQUIRES_OUTPUT_OF` 和 WorkflowPlan DAG。

## 3. Execution Gate 与 Policy

四个受支持固定组合当前为：

```text
Scrublet 0.2.3 + scRNAseq
scDblFinder 1.24.0 + scDblFinder-R
Harmony 2.0.0 + sckg-batch-cpu
Scanorama 1.7.4 + sckg-batch-cpu
```

对应 contract/environment 均满足：

```text
source_review_status=reviewed
execution_critical_fields_reviewed=true
wrapper_status=smoke_passed
environment_status=smoke_passed
execution_status=integration_passed
scientific_validation_status=scientific_pilot
contract.enabled_for_execution=true
environment.enabled_for_execution=true
```

这些 flag 只表示该固定组合具备受控执行资格，不表示默认开放。真实本地用户执行还必须同时满足：

```text
ExecutionPolicy=allowlisted_local_users
local user allowlisted
registered artifact + valid data grant
unchanged dry-run plan
exact plan-specific approval + remaining use count
allowed tool/environment pair
execution gate allowed
```

全局 `ExecutionPolicy` 默认仍为 `disabled`；UI 无权修改策略。匿名、远程、公共 API、任意工具、任意环境和任意命令执行均未开放。

## 4. 测试与验收

v2.7.2 Research Chat open-world foundation fresh 完整回归（2026-07-31）：`398 passed`、6 个第三方 warning、无失败。Mainline Quality Gate 为 `6/6`；100-case × 3 的 300-run deterministic Agent Quality 中 task/intent/tool/response shape/blocker/workflow/source/compliance/trace/stability 均为 1.0，`governance_violation_rate=0`，最终重跑 p50=`37.372 ms`、p95=`154.791 ms`。真实参与人数仍为 0。

Agent Quality v2 当前使用 100 个 scenario、每个重复 3 次，共 300 次 deterministic run，其中包含 20 个多轮转移 case，覆盖推荐、原理、top-k caveat、workflow、显式任务切换、省略型追问、参数、结果图、失败模式、迁移和 hard negative。最新核心治理指标均为 1.0、`governance_violation_rate=0`、cascade root failure=0。历史结果中的 `hallucination_rate` 已降为兼容别名；该评测不包含逐 claim 科学事实判定。它仍是冻结场景工程回归，不等于开放世界科学正确率或真实 LLM 稳定性。

真实 LLM 验收采用严格的 `5-turn smoke -> 20 case × 3` 前置 gate。2026-07-30 首次运行中，5-turn 因 `llm_credentials_not_configured` 在网络调用前阻断，requested=5、attempted=0、completed=0；60-turn 随后因 `live_llm_smoke_gate_failed` 阻断，attempted=0。相关 artifact 位于 `.sckg_exec/evaluations/live-llm-smoke-20260730` 与 `.sckg_exec/evaluations/external-agent-stability-20260730`。不得将该结果描述为 DeepSeek 已验收。

2026-07-31 凭据阻断解除后重跑：`.sckg_exec/evaluations/live-llm-smoke-20260731` 记录 requested=5、attempted=5、completed=4、passed=3，grounded citation correctness=0.5。越界阻断、ExecutionRequest=0 和 candidate/evidence leakage=0 仍满足，但 5/5 前置 gate 未通过，因此 60-turn 仍不允许启动。

2026-07-31 最终修复后：5-turn artifact `.sckg_exec/evaluations/live-llm-smoke-20260731-r6-final` 为 5/5；60-turn artifact `.sckg_exec/evaluations/external-agent-stability-20260731-final` 为 requested/attempted/completed=`60/60/60`，failed=0。task、intent、tool、blocker、workflow、grounded citation、Top-k 和 explicit task switch 均为 1.0，unsupported claim、unauthorized ExecutionRequest 和 candidate/evidence leakage 均为 0，平均延迟 `3651.763 ms`。真实 LLM 服务 gate 已通过；Safari/Chrome 可视化重放仍待完成。

最新开放世界计划不能由上述历史 5/5 与 60/60 替代。现已建立 120 条来源独立自然问题，固定为 `72 development / 24 evaluation / 24 hidden`，并实现 A-E 五路线消融。32-case 首轮本地 `KG/RAG-only` 结果为 route accuracy=`0.34375`、task accuracy=`0.777778`、blocker correctness=`0.5625`，显示检索组件高分没有自动转化为开放问题回答能力。DeepSeek-only、DeepSeek+BM25、DeepSeek+KG Hybrid、DeepSeek+KG Hybrid+ToolContract 因当前 CLI 无法解锁已保存加密凭据而为 `not_run`；hidden 尚未运行。因此 Research Chat 当前状态为 `OPEN_WORLD_EVAL_PENDING`。

System Quality Gate v1 已真实串行执行 8 个既有入口并生成统一报告。六类 operational scenario 全部通过；Scrublet/scDblFinder fresh restricted-user smoke 共 4 次工具运行，工具成功率、Validation 通过率和 Candidate eligibility 均为 1.0。功能、安全、知识、复现、性能和审计六个工程维度通过；真实可用性因参与者为 0 保持 `partial/not_run`，变更风险因尚无冻结 system baseline 保持 `partial`。统一结论为 `engineering_gate_passed=true`、`phase6_complete_eligible=false`、`PHASE6_TRIAL_READY`。

Continuous Agent Evaluation v1 当前定义 51 项指标，44 项已测，release metric coverage=`39/42=92.86%`；effectiveness=`watch`、efficiency=`healthy`、stability=`healthy`、compliance=`watch`，zero-tolerance violation=0。相对 `rc-2.6.4` 记录 3 个效率趋势回归：Agent p50 `13.947 -> 47.382 ms`、retrieval p50 `8.6685 -> 12.826 ms`、retrieval p95 `24.876 -> 36.258 ms`；同时 Agent p95 `880.125 -> 159.751 ms`。当前值均满足 v2.7.1 硬阈值，但总体仍为 `WATCH`，不得自动冻结 `rc-2.7.1`。

本轮安全结果：unauthorized execution、path escape、approval replay violation、cross-user access 和 untrusted generated-code execution 均为 0；正确阻断案例 `ExecutionRequest=0`。知识结果：96-case 默认 governed Hybrid Recall@10=0.971591、Precision@10=0.912256、MRR=0.991477、source-span hit=1.0、false-support=0、governance leakage=0；RAGAS 仍为 `not_run`。本机 RC 性能记录为 Agent p50=21.419 ms/p95=69.840 ms，`KG + Hybrid + ToolContract` retrieval p50=8.823 ms/p95=24.406 ms；双工具 smoke 历史平均总 runtime=17.3842 s、peak memory max=1340.5 MB。

Mainline Quality Gate v1 的 6 个固定产品案例全部通过：ASK 不生成 plan、Top-3 caveat 数量正确、Doublet/Batch PLAN 均返回 smoke-tested code bundle、RUN 缺数据与不支持任务均正确阻断；intent/task correctness=1.0、parameter legality=1.0、critical blocker recall=1.0、unauthorized ExecutionRequest=0、candidate/evidence leakage=0，两个黄金 scientific package 的 manifest hash 均有效。

Phase 5 关键复现包：

```text
.sckg_exec/packages/phase5-batch-engineering-20260716T082929Z
.sckg_exec/packages/phase5-batch-scientific-20260716T083044Z
```

两个 package 均为 Level 2、完整且 manifest hash 有效。Harmony/Scanorama 固定 contract/environment execution gate 已通过；全局 policy 仍为 `disabled`，因此默认用户执行不可用。

Phase 6A/6B/6C smoke 均通过：

- Scrublet 与 scDblFinder 真实受控执行成功；
- approval 消费、防重放和参数变化失效通过；
- process-tree cancellation、跨用户隔离和路径脱敏通过；
- Level 2 package 完整且 manifest hash 有效；
- 输入 `.h5ad` 未复制到 package。

Phase 6 作品集产物：

```text
.sckg_exec/evaluations/portfolio-v2-full-20260717
.sckg_exec/evaluations/mainline-20260727T153016Z
.sckg_exec/demos/interview-20260727T153152179110
.sckg_exec/portfolio/rc-2.7.2-<timestamp>
```

Portfolio v2 的 48/48 模型调用均保存 provider/model/token/latency、raw response、admitted response 和字段级 governance intervention；因进程重启，48 条均记录为同 protocol 的 recovered new calls，而不是旧结果 replay。未提供冻结单价，因此 estimated cost 保持 `null`。最新 Interview bundle 从 `ResearchChatService.run_request` 统一入口生成 Doublet、Batch、bounded repair 和 correctly blocked 四类案例，trace completeness=1.0、blocked ExecutionRequest=0、全部 package integrity 有效、legacy workflow runtime 未使用；默认 policy=`disabled`，外部用户数据记录为 0，真实组内参与人数为 0。

Portfolio Acceptance v1 将全量 pytest、Mainline、96-case Retrieval、240-run Agent Quality、30-case Memory、Interview Demo、Git 完整性和 release/privacy scan 串成单一入口。最新 bundle 状态为 `RC_READY_FOR_USER_REVIEW`；具体时间戳、worktree digest 与 dirty-worktree 计数以包内 `portfolio_acceptance.json` 为准，避免文档回写导致 digest 自引用变化。Mainline `6/6`、Interview `4/4`、trace completeness=1.0、两个黄金 package integrity=1.0、release/portfolio privacy issue=0。外部 LLM 稳定性、RAGAS 与真实用户试用继续明确记录为 `not_run`。

仓库恢复阶段发现 517 个 tracked 文件曾被 macOS 标记为 dataless；当时已从本地 Git blob 恢复并逐项核对大小。2026-07-31 FileProvider 又将 `.git` pack、85 个 tracked 文件和 `.env` 回收为 dataless placeholder，导致 Git 对 pack 的 mmap 触发 `SIGBUS`。本轮已按 Git index OID 和 GitHub exact blob SHA 恢复当前 HEAD/index 所需的 91 个 blob，当前 `git status`、`git diff --check` 和 current-index object check 可用且 index missing=0；但旧提交历史仍缺被回收 pack 中的 parent/history objects，所以当前不能再声称 `git fsck --full` 通过。RC Gate 必须分别报告“当前工作树可验证”和“完整历史对象可验证”，不得把二者混为一项。

## 5. 当前 Blockers

1. Batch Integration scientific pilot 只覆盖 scIB pancreas/source PCA 与固定 3,000-cell evaluation 子集；仍缺多数据集 external evaluation，不能声称 Harmony 普遍优于 Scanorama。
2. Portfolio v2 的 admitted A4 已通过硬 gate，但 raw A4 仍只有 0.604167 blocker correctness、0.416667 I/O compatibility 和 0.6875 routing accuracy；确定性治理仍是必要条件。B1 独立 expert static script 仍缺冻结入口；B2 继续保持 `not_run_safety_boundary`。
3. Phase 6 尚无 3 至 5 位真实组内用户试用记录，因此不得标记 `PHASE6_COMPLETE`。
4. Streamlit 已有本地 UI，但实际使用前仍需维护者登记 artifact、配置 local user allowlist，并显式启用 `allowlisted_local_users`。
5. 只有应用层路径、进程和权限控制；没有 OS/container sandbox、系统级禁网或不可信多租户隔离。
6. 科学验证仍是单数据集 pilot，不满足多数据集 external evaluation。
7. Phase 7 服务化/MCP 尚未开始。
8. Source Corpus v2 只完成首批 16 个核心工具；source-bound coverage 仅 0.008700，formal evidence coverage 仍为 0。Catalog 其余长尾只能发现，不能被表述为有原文支持。
9. 现有 48-case portfolio bank 已包含 hard negatives 并完成同 case A2/A3/A4 对照，但仍是自建 deterministic 作品集评测；缺少重复调用、置信区间、完整 relevance judgments 和外部 benchmark，不能表述为统计显著的模型优越性。
10. Decision Graph 当前只有 4 个 execution-qualified contract、2 个 planning-only annotation contract 和 2 个 dataset pilot；严格执行边界仍限于 Doublet Detection 与 Batch Integration。
11. Action Space 已有 2 个 qualified Action、1 个 planning-only Action 和 6 个 ActionBundle，但尚未实现跨任务 DAG 组合执行；ActionBundle 仍只是受治理的规划上下文。
12. Biomni 的 action-space 广度尚未实现：当前只有 4 个 execution-qualified 工具，不能冒充通用生物医学自主研究 Agent；未来扩展必须保持按任务 qualification，而不是把全部目录工具和依赖一次性安装到本机。详细边界见 `docs/design/BIOMNI_ARCHITECTURE_COMPARISON.md`。
13. Runtime Pack 已在当前 Apple Silicon Mac 的隔离 clean-prefix 从 explicit lock 完成真实安装、卸载和重建，并记录实测大小/耗时；但尚无第二台干净 Apple Silicon Mac 的独立复验，因此只能标记 `RELEASE_CANDIDATE`。
14. Native Trusted Runner 仍是 `network_not_os_isolated`；Isolated Container Runner、Windows WSL2、Linux/HPC worker 与 read-only MCP 均未实现，不能提前声称跨平台或 OS-level isolation。
15. 本地 bge-m3 与 governed Hybrid 已通过本机消融，但 Model Pack 约 5.58 GB，尚未完成第二台机器重建验收；未来 corpus/revision 变化必须重建 index，不能把当前分数视为永久结论。
16. RAGAS evaluator 未安装或授权，当前为 `not_run`；它是辅助诊断，不是 formal evidence 或 execution gate。
17. Agent Quality v2 已扩至 240 次 deterministic run，但 16×3 外部模型稳定性评测因未获得本轮脱敏外发授权保持 `not_run`；人工正确性评分仍缺失。
18. 原生执行只允许维护者审核的固定 wrapper。Docker/OCI 隔离 runner 尚未实现，LLM 生成的任意 Python/R/shell 代码不得执行；当前只能生成 synthetic fixture 并调用 allowlist 中的受控分析路径。
19. System Quality Gate 的工程维度已通过；Continuous Agent Evaluation 的效能和合规仍为 `watch`，原因是真实参与者为 0、OS-level isolation 未实现、随机外部模型/RAGAS 未测，并已观察到 Agent p50 延迟回归。不能把当前报告写成 Phase 6 complete 或统计显著改进。
20. Annotation 安装前容量 gate 仍未通过：2026-07-28 RC 验收时可用空间约 6.1 GiB，只达到保留余量本身，尚未覆盖新增环境与 reference pack；没有为本次 RC 删除 dataset、run、package、manifest、SBOM 或 bge-m3。CellTypist model、SingleR immune reference 与 Zheng68K 冻结资产也尚未登记。
21. 开放世界 32-case 本地路线仍有明显 domain/task/blocker 错误；A/C/D/E 真实 DeepSeek 同题消融、paired delta、claim correctness 独立抽检和 24-case hidden 最终验收尚未完成。
22. 已保存的 `.env` 当前被 macOS 标为 dataless，安全 loader 不读取占位文件；加密 API 配置的 CLI 口令未提供。单次 materialized 配置连接诊断已成功，但完整开放世界外部消融必须等待凭据资产重新可读。
23. 当前 HEAD 和 Git index 已恢复为可检查状态，但完整历史 pack 仍是 dataless backup；`git fsck --full` 会报告旧 parent/history object 缺失。完成 RC 前必须重新获取历史 pack 或在独立 clone 中验证历史完整性，且不得用当前工作树检查结果冒充完整历史检查。

## 6. 当前收口动作

本轮不进入 Annotation、MCP、Container、WSL2 或更多工具。确定性执行后端保持可用，但 Research Chat 的下一合法动作是：在显式解锁加密配置后运行同一 32-case A/C/D/E 消融，先修复 evaluation split 失败，再冻结最佳路线并只运行一次 hidden。完成前不得恢复 `RC_READY_FOR_USER_REVIEW`。真实参与人数仍为 0，所以 Phase 6 不得标记 complete。
