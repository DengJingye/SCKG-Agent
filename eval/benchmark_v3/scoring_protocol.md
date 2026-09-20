# V3 评分规约与运行门槛（供 00 审核）

状态：工程实现/审核规约 ready；科学答案、评分阈值、运行预算未获裁决。
本轮只生成 14 个 development 意向草稿。不是正式 DEV/Gold 数据集；不执行 lane 或 Agent Gain。

## 1. 研究问题与冻结设计

主问题：相同模型和任务条件下，Approved Scientific KG 是否提高条件正确的科研判断和证据可靠性？
产品收益、机制收益和适用边界分开报告。四条正式 lane 只用
`5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee` 的实现和真实 corpus。
共享 Planner / ToolContracts / guards / validation / approval 不构成 KG 独有知识。

目标 50 场景、34 家族：K 16 家族×2条件=32，O 12，W 6。
先审 K8/O4/W2（10 个家族）；未创建的 evaluation 为 K24/O8/W4（24 家族）。
K 四类各4家族：输入/方法、版本/条件、多知识组合、证据/结论强度。
W 最终3题科学决策敏感、3题共享执行可靠性对照，不把后一组收益归因于 KG。
不纳入 BBBC/DAVIS 等超出四 lane 共同能力的任务。

development 的 4 个 K 家族源自已公开讨论的例子；全部禁止进入 evaluation。
现有全部候选也保守视为已暴露开发材料。origin、track、coverage、failure stage 独立存储。
本轮不重新挖问题、不继承公共 benchmark 答案、不按 07 表现选题。

## 2. 人工审核与 Gold 隔离

`development_review_packet.md` 是审核入口，JSONL 是机器可读输入。
每题原始文字、provenance、增删上下文、构造的科学条件、歧义和污染风险并列。
新增版本/矩阵/物种/参数属于作者构造，不是用户事实。

两名独立审核者分别填写（不先看另一个人的结论）：

1. 任务是否有明确目标；科学必要事实、用户上下文/运行状态、任务结果是否分开。
2. 版本化官方文档/原始文献/独立实验的精确来源 span、许可、内容哈希和条件边界。
3. 关键事实、可接受结论、必要澄清、过度澄清、禁止结论；W 的约束、轨迹、产物和容差。
4. 场景和 source/family/近重复/论文/notebook 组键；暴露和 memorization 风险。
5. 署名、日期、依据；分歧由独立 00 裁决。08 不替人签署或裁定科研正确性。

`human_review.reference_claims` 当前为空。只有审核后才映射成 `ReferenceClaim`；
来源不是 KG 自己或模型输出。可填写引用 URL 不等于已有 Gold；独立精确 span 尚待冻结。
coverage 只描述 frozen consumer 的知识可用性，不证明其内容是真实世界答案。
人工评分时隐藏 lane 名、系统自称和答案顺序；保留评分所需的证据但不伪造出处。

## 3. Coverage 审核机制

撤回旧脚本固定写出的20个 `000`，以及更早的 ToolContract `100`。
历史保存在 `810ed0853c763c0a497f74100f7bb8d47ed2e4e8`，当前记录清楚标为 withdrawn/unknown。
raw seeds、原 provenance 和 clustering 不变。不得把撤回理解为证明知识库覆盖或不覆盖。

每个必要科学事实×V2/Legacy/RAG独立审核，程序只做搜索清单：

- `present`：可见 record ID、evidence ID、可逐字定位的 excerpt、scope/版本、适用与蕴含理由。
- `absent`：完整搜索范围、至少两个 query variants、inventory digest、相关结果逐项不足理由；无相关结果显式 `[]`。
- `unknown`：未审核、资料不足、分歧未裁决；无 signature，不能填000。
- `not_applicable`：审核确认纯运行时任务且科学事实集为空；无 signature，不能填000。

`coverage_review.py` 校验 fact/input/snapshot digests、引用 ID、原文、权限和两人复核。
相同审核者不能投两票；分歧需另一个 `role=00-adjudicator` 的裁决。
这些是结构检查，不会自动判断人的真实身份、负搜索完整性或科学蕴含，仍需00审查。
所有 critical facts 均完成审核后，按每源是否满足全部关键事实汇总 `111…000`。
非关键事实仍逐格保留；缺少用户版本/数据、未知计算结果不是科学事实 absent 的依据。

Approved consumer 只允许121条 approved statements 的 DIRECT_SUPPORT 证据链。
held scVelo 不在 allowlist；166 caution contexts 可提供限制背景，但不能证明正向科学断言。
ToolContracts、执行规则等 shared runtime 不得充当任何知识位。
Legacy/RAG inventory 同时登记800 evidence chunks、1847 catalog chunks；其中10个被治理隔离的
formal chunks 不能作 present 支持。catalog 仅可用于 discovery metadata，不能越权支持推荐/执行。
Legacy 另含25个现有 candidate claim records；不升级其 trust。工具图仅过滤候选。
单次 top-k 命中/失败不作 coverage 判决；检索遗漏与 corpus gap 分开。

审核文件应另存，不能直接编辑会重建的 `_template.jsonl`。
使用 `audit_scenario()` 读取副本里的两人 reviews 并派生状态；不得手改 status 来绕过判定。

## 4. 分 track 评分，不合成单一分数

以下是待00确认的判分规约，不是本轮已经校准的科学 evaluator。

| Track | 主指标和必要通过条件 | 单独报告 |
| --- | --- | --- |
| K | 条件正确任务通过率：核心问题被解决、全部关键条件满足、无重大科学错误 | 关键事实召回；错误条件适用率；条件变体成对通过率 |
| O | 合适且有用的响应率：解决可回答部分或给出必要而有针对性的澄清/排查，不作无依据确定诊断 | 可回答问题解决率；必要澄清；过度拒答/澄清；无支持确定结论 |
| W | 独立验证的任务成功率：有效计划/约束、产物内容、科学有效性、干净重跑均通过 | 知识决策组/共享运行组；计划、状态、执行、产物验证各自失败率 |

K `pass` 不以引用样式为必要条件；LLM-only 正确回答可得正确性分。
重大错误（关键输入不适用、越过方法条件、无依据确定结论）使任务失败，不以次要正确点抵消。
成对通过是两题都对且针对单一条件作出正确决策；不能用答案字符串不同判通过。
关键事实召回的 denominator 是事先审核的关键事实，不是输出越长越有利。
错误适用率的 denominator 是所有预先标记有条件适用挑战的场景，另报未作决策/澄清，防止拒答逃避。

O 必须事先审核哪些字段真正必要，为什么。只说“请提供更多信息”不算有用；
索取完整患者数据、所有工程文件等非必要信息不得得分。缺信息不强行要求根因答案。
如果可由现有输入解决，反复索要无关信息属于过度澄清。四个当前 O 草稿是明确的 triage 任务；
后续8题应独立加入可回答场景，不能从本组估计完整真实用户分布。

W 不能仅检查进程0/文件存在。预先冻结：输入哈希、环境/依赖、计划约束、输出 schema、
feature/cell 对齐、数值容差、非空/唯一性、科学参考脚本和干净重跑检查。
synthetic fixture 仅工程 smoke；不提供真实生物学效度。四条 lane 不共享执行接口则全组 not_run。

证据可靠性另报：claim-level支持、scope、citation/来源绑定、错误升级 caution/held。
source-bound 指标只用于适用任务/声明，llm_only 不因无引用自动判科学错误。
`not_applicable`/`not_run` 保留，不填零。回答分母、citation分母、workflow分母分别公布。
每 lane 同时报总延迟、每次 provider call（包括 support checker）、token 和失败/超时率。
token 缺失是 unavailable，不是0；本轮没有运行这些指标。

## 5. 评分校准门槛

00 完成14题审核后，构造至少以下成对样例：正确、科学错误、漏关键条件、错引用、
不必要拒答、必要且有用的澄清、退出0但空产物、产物存在但身份错配、正确安全停止。
预先写明 expected signal，再检查 evaluator，不用模型输出反向改题。
本轮 synthetic tests 只测试审核/数据/manifest 边界，不声称完成科学 scorer 校准。
若使用 LLM judge，沿用 `JudgeRuntimeConfig` 独立性和校准门槛：至少20人工样本、
accuracy>=0.80、kappa>=0.70；不能把07自身 support checker 当独立 judge。

## 6. 产品比较和机制对照

产品比较沿用四条 lane 的原 corpus、prompt、后处理；不是只有图结构不同的实验。
同模型/版本、输入/状态/上下文、总资源上限、次数。禁止偷偷替换RAG或扩大Legacy。
静态 manifest 保存 fallback 与动态 tool-call/supplemental 分支；真正每次 request 和最终
模型消息/证据必须按 `runtime_receipt.schema.json` 留档并哈希，不能用静态配置冒充观察。
system/user rendered prompt、完整 evidence、模型实际版本、调用/输出/用量、排除记录均需留档。
本仓库当前仅提供 receipt 合约，未向07注入采集器。正式运行前需单独验证 eval harness 能捕获这些内容。

机制实验仅 K、仅评测 harness：

1. 同证据结构化/无损文本：在看 lane 输出前冻结独立审核的 evidence set，
   两组条目、关系含义、出处、版本、条件、caution权威完全相同；只改变表达。
   共用 synthesis prompt、模型、输出预算、验证。双向核对 facts/edges/qualifiers 不丢失；
   context 必须整包容纳，不能一组被截断。分别记录 token，不假设两种表达等 token。
2. 显式 scope 过滤 on/off：另一单变量对照，关闭过滤但保留原条件文字和证据权威；
   不同时换表示，不关闭任何执行安全组件。重点看错误适用，而非只看回答率。

两项单列结果，不替换正式 generic_rag、不混入四 lane 成绩。实现和运行均在审核授权之后。

## 7. 失败归因与统计

保留九阶段：routing / state / retrieval / scope / evidence / synthesis /
planning / execution / validation-governance。
沿用 `FailureAttribution` native stage，再加报告层映射；不改生产 trace。

| 报告标签 | 必需证据 |
| --- | --- |
| retrieval | 该 lane 冻结源中存在适用必要证据，但 request/returned/final context trace 证明遗漏 |
| scope | 实际证据、用户条件和应用结论不匹配；或错误排除适用证据 |
| evidence | 被引用 span 不支持、越权升级、来源链失效，有具体 claim/span ID |
| synthesis | 合适证据已送模型但结论/组合错误，有最终上下文及输出 |
| routing / state | 路由选择或状态检查的 trace 与事先审核目标/实际状态矛盾 |
| planning / execution | 计划约束/工具调用/错误日志和失败产物定位到相应阶段 |
| validation-governance | 产物不合格却通过验证、权限/治理决策错误的检查证据 |

coverage_gap、correct_clarification、correct_stop、unresolved 单独记，不硬塞成阶段失败。
阶段顺序不自动等于因果；主根因须证据支持，允许并发/下游症状及待裁决。
仅重放该 lane 原本可获得的正确证据用于诊断，另建 run/attempt ID；不覆盖主实验失败。

审核后冻结36 evaluation 场景。按 family/source-thread/近重复/论文/notebook 的连通组划分，
不能只检查单个id；同家族条件变体不能跨 split。公开曝光、原始答案可见、改写距离持续记录。
正式运行还需显式授权：4 lanes×3次，固定调度seed、随机交错、独立会话，W每次独立fixture副本。
provider不支持seed则记录null，不声称确定性；失败全部保留，重跑新attempt关联旧attempt。

先在每家族内平均重复与条件变体，再计算D-RAG、D-Legacy配对差值；D-LLM补充。
按track做家族级配对bootstrap（保留重复/变体的相关性），预先固定resampling seed/次数与区间规则。
缺失/未运行分母和原因必须可见，失败/超时不可悄悄剔除；成功率分母包含已启动的失败尝试。
coverage subgroup只用审核完成的exact signatures，unknown/NA另报，不强制八格平衡。
50场景是pilot，不足以证明广泛科研增益；正式样本量由pilot方差及预定最小意义收益确定。

## 8. 复用与边界

`core/evaluation_models.py` 不变：审核前是 sidecar；审核后用 EvaluationCase / ReferenceClaim /
ExpectedTrajectory / ExperimentManifest / EvaluationRunRecord / EvaluatorResult / FailureAttribution。
`core/open_world_evaluation_models.py` 不变：O可映射 official_issue；需要CLARIFY/BLOCK时先审核
expected_blockers，不把 `gold_status=none` 塞进不支持它的生产 enum。
`eval/evaluation_evaluators.py` 不变：复用已有claim/trajectory/trace/result约束，新增评分需校准后接入。
`docs/eval/RESEARCH_EVAL_PROTOCOL.md` v0.6 的旧A/B baseline是历史实验；本V3用07四lane定义，
不是修改旧实验历史，也不把旧 protocol 中不同的 ToolContract 条件搬来造成混淆。

方法参考：[ScienceAgentBench](https://github.com/OSU-NLP-Group/ScienceAgentBench) 的独立任务与产物评分，
[Genome Biology 2026](https://link.springer.com/article/10.1186/s13059-026-03998-z) 的模块对照与日志归因。
只借方法，不继承题目答案或其 aggregate score。
