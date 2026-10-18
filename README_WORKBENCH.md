# scKG Workbench：可追溯科研 Agent 开发版

本入口是单细胞多组学 Agent 的**源码开发快照**。目标是把连续对话、带原文依据的流程知识、受限工具调用和独立产物验收接成可复查的产品。旧 `app.py` 与原 README 保留为历史入口；当前工作台入口为 `workbench_app.py`。

## 当前可以体验什么

- 持久多轮对话、显式模型连接、调用预算、幂等提交、后台状态及取消；刷新不会自动发送问题。
- 原始来源与解析版本、精确引用跨度、候选与正式知识分离、用途与暂停检查、可追溯证据回答。
- 开发态流程输入检查：区分“声明具备／明确缺少／尚不清楚”；自然语言提取绑定原用户轮次、原话、来源和真实调用回执。
- 可选的模型输出格式及完整格式哈希限制、调用前只读检查、私有请求快照与安全错误分类；声明不等于远程支持证明。
- 有界 agent 循环、完整上下文容量预检、可逆文本共享、失败记录及只读重放校验。可复用的任务、科学执行和产物验证组件随源码提供。

开发态模型提取不是独立测量或领域专家审核。科学流程目录仍不完整；引文匹配不证明语义正确。此公开快照不附研究数据库、模型权重、科研运行环境或论文全文。当前 Scrublet 合同缺少另行取得的来源文件和本地环境时，会保留阻断状态；单独安装科学运行环境也不能绕过来源门。不能由源码发布推断科学分析已可运行。

## 安装与启动

本阶段针对 Python 3.12、POSIX/macOS 进程控制；Windows 尚未验收。复用已有合格环境即可，无需重复安装。macOS 14+ ARM64 新环境可使用完整版本与哈希锁：

```bash
python3.12 -m venv .venv-workbench
.venv-workbench/bin/python -I -m pip install --only-binary=:all: --require-hashes --no-deps -r release/locks/workbench-dev-osx-arm64-py312.requirements.lock --report install-workbench01.json
.venv-workbench/bin/python -I -B scripts/verify_g0.py --python .venv-workbench/bin/python --output validation-run-g0-01
.venv-workbench/bin/python -m streamlit run workbench_app.py --server.address 127.0.0.1
```

目录和安装/验收报告使用全新名称，保留既有结果。完整锁仅适用于上述目标平台，不包含拟合工具环境；原 requirements-workbench 分层文件仍用于直接依赖说明和其他平台的独立资格验证。验收入口会检查内存余量，资源不足时记录待资源并停止。详情及CI范围见[plan_v1/G0交付与验收](docs/PLAN_V1_G0.md)。启动空工作台不需要 API key；发送模型请求前，在“设置”中自行配置真实 provider、profile 和预算。凭据留在本地，不能提交到 Git。

### 独立合成演示：先体验三态与来源检查

以下目录必须新建或完全为空，初始化不会采用已有台账：

```bash
.venv-workbench/bin/python -I -B scripts/bootstrap_workflow_demo.py --workspace "$HOME/sckg-workflow-demo01"
SCKG_WORKBENCH_HOME="$HOME/sckg-workflow-demo01" .venv-workbench/bin/python -m streamlit run workbench_app.py --server.address 127.0.0.1
```

打开“知识库”中的“流程输入检查（开发预览）”，可测试 3 条虚构路线。演示记录全部标明 synthetic，含示例 true、false 和未提供状态；没有人工审核、正式发布、模型回执或科学成绩。

若配置了真实模型，可在“研究台”的对话设置中启用“开发流程对话：按来源检查输入”，使用演示目录内 `workflow_demo_examples.json` 的问题。模型调用需自行设置预算；容量不足会在发送前阻断，不能自动加预算。默认开发模式最多 3 次模型请求、2 次只读检查，不执行分析。

### 方法配置与适用条件：零API演示

新增独立[方法决策预览](docs/METHOD_DECISION_PREVIEW.md)，可检查选项开关、数值边界、相互冲突的报告及替代路线。用全新的合成目录体验：

```sh
.venv-workbench/bin/python -I -B scripts/bootstrap_method_demo.py --workspace "$HOME/sckg-method-demo01"
SCKG_WORKBENCH_HOME="$HOME/sckg-method-demo01" .venv-workbench/bin/python -m streamlit run workbench_app.py --server.address 127.0.0.1
```

打开“知识库”→“方法配置与适用条件（开发预览）”。演示明确虚构，不配置模型，不建立科学结论；原三路线演示继续保留。相关验收入口为 `scripts/verify_annotation_stage.py`，实际安装宿主主/公开工作区各179项通过，见[阶段记录](docs/WORKBENCH_VALIDATION.md#来源条件接入方法配置)。

### 预测产物的分数定义

新增[只读预测解释](docs/PREDICTION_SCORE_CONTEXT.md)：显式绑定已有文件和来源定义，保留实际版本、预测模式及标签列的未知，不把参数请求当成已执行。该开发入口需单独配置目录与产物快照；不会自动预测或创建科学结果。实际来源与历史A1文件身份检查、完整页面和主/公开各214项相关回归已通过；A1精确版本语义仍待确认。

### 显式 JSON 对象接口与完整本地合同

开发流程对话可在“流程输出格式”中显式选择 JSON 对象接口，完整 schema 仍发送并独立验证；预算计入最终请求，不自动更换接口或格式。见[使用与边界](docs/LOCAL_OUTPUT_CONTRACT.md)。当前新表单绑定[V4报告绑定与输入状态](docs/WORKFLOW_REPORT_PRESENCE.md)，并显式启用[原预算内一次最终格式修复](docs/WORKFLOW_FORMAT_REPAIR.md)。前一已封存的52模块格式修复阶段中，独立真实单例自然遇到摘要331字符超过180限制，以第三次、也是最后一次请求重生成74字符摘要，完整校验及只读重放通过。报告22,668 tokens，金额未知；不运行分析。此历史资格不作为当前53模块新原生运行结果。旧V4摘要206字符的失败和旧V2/V3结果全部保留，历史请求不补修复策略。原话绑定、单例恢复与来源精确引用均不证明科学语义或知识增益。

## 可重跑验收

前一普通聊天[无损证据共享编码阶段](docs/CHAT_EVIDENCE_ENCODING.md)：默认 API 与旧请求保留 literal，新 UI 普通提交显式 shared。相同四题 R 输入在原32,768上限内的容量准备从3/4变为4/4，B/R共8个输入均通过零API资格；这不是任务完成率或知识增益。该阶段主/公开副本各78项相关定向检查通过，实际JUnit身份一致、当时53产品模块字节相同；非全量回归或live browser人工验收。该工程与容量资格范围0 provider请求、拟合、新环境、生产写入或人审，后续真实16次调用另计。复跑三个串行通道：

```bash
.venv-workbench/bin/python -I -B scripts/verify_chat_evidence_stage.py --output ./chat-evidence-validation01
```

每通道限120秒/1.5GiB，输出目录必须不存在；详细容量、原row7失败和检索相关性限制见上述说明。

```bash
.venv-workbench/bin/python -I -B scripts/verify_workflow_stage.py --output ./validation-run01
```

该入口复用既有进程监督器，串行运行明确列出的流程、对话、合成演示和资源清理测试；总墙钟上限 120 秒、采样父子进程 RSS 上限 1.5 GiB、科学计算单线程。输出目录必须不存在。`receipt.json`、JUnit 和日志共同决定通过，退出码或进程存在不能单独算成功。测试使用明确标记的内存 transport，配置为零 provider 请求、零科学拟合；离线设置不是操作系统网络沙箱。

已安装 Streamlit 1.56 的环境还可执行完整工作台界面探针：

```bash
.venv-workbench/bin/python -I -B scripts/smoke_workbench_ui.py --workspace "$HOME/sckg-ui-smoke01" --output ./ui-smoke01.json
```

这检查真实 AppTest 页面和开发输入表单，不是浏览器截图、真实模型或科学评测。最新验证范围、失败记录和资源数字见 [阶段验收记录](docs/WORKBENCH_VALIDATION.md)。

## 开发目标与成果边界

[开发手册](docs/WORKBENCH_DEVELOPMENT.md) 给出短期、中期、长期目标及逐步验收：先打通可靠交互，再验证知识是否改善具体科学决策，最后做固定协议的确认评测和外部 agent 对照（包括 Genpilot）。

默认采用一个主 agent、明确工具合同及独立验证器。多 agent 作为有明确分工和成本收益的实验选项；增加角色数量本身不是亮点。可展示的求职成果应来自实际日志、测试、产物和消融结果。可展示前一52模块封存阶段的一次真实预算内最终格式恢复、普通聊天同包无损容量修复，以及最新规划词表的86项定向检查和4次真实规划资格；这些阶段分别计数，没有证据支持“优于市场 agent”或“知识库带来科学提升 X%”。

[普通主聊天真实B/R开发对照](docs/MAIN_CHAT_RAG_DEVELOPMENT.md)已用独立16次调用结束并关闭账户：8份生成有效，8次评分仅4次有效，另4次因辅助理由超过160字符未评分。只有row7可配对，B/R均6/12；不能由此宣称四题零增益或比较不同分母均值。报告65,945 tokens、金额未知，0拟合/生产写入/新环境。后续[零API评分与检索诊断](docs/MAIN_CHAT_DIAGNOSTICS.md)已完成：事后匹配B20/29、R21/29，等题权差+4.1667个百分点，原v1及NA保留；这是探索性敏感性而非科学增益。查询×索引机制探针的简单改动未启用默认。同事实F/S、完整工具agent及外部原生比较继续分轨。

最新[规划词表无损编码](docs/PLANNER_CATALOGUE_WIRE.md)为显式 `columnar_v1`，默认literal和普通聊天未切换。完整220单元的172条原生词表，在同一16,000输入代理上限内四题由均超限变为均合格；八body零API观察及86项定向检查通过。新独立4次真实planner-only和只读检索/top5来源解析完成，报告14,850 tokens、金额未知，111.8416秒/347,947,008字节峰值，账户关闭。没有最终回答、selector、judge或拟合；远程schema强制能力未确证。查询仍偏疾病/组织/细胞词、top5多为CITE-seq/QC/ARC/ATAC，不能据此称相关性或科学增益。下一步围绕“任务→分析家族→输入→验证”补有来源的流程知识，并冻结独立任务对照；G2、完整G3、G4和整体G5仍未完成，安装包未重建。

注释知识的具体补充与未知项见[流程候选说明](docs/ANNOTATION_WORKFLOW_CANDIDATES.md)；最终主/公开分支各464项工程验收和零API导入结果见[阶段记录](docs/WORKBENCH_VALIDATION.md#调用前格式限制与注释候选导入)。候选内容未升级正式推荐。
