# 流程对话：报告绑定与输入状态

`report_presence_v4` 沿用一个主 agent、现有只读工具和阶段合同，区分本次检查的报告绑定与输入是否具备。没有增加模型请求上限、执行权限或 agent 角色。

| 本次检查结果 | 可以表达的含义 | 追问类别 |
| --- | --- | --- |
| 所需输入没有对应原话绑定 | 本次检查未绑定该项报告；模型可能漏抽取 | 兼容类别 `not_supplied`，`p=[]` |
| 有原用户原话绑定，提取值为 null | 有相关原话，但提取含义或输入状态仍待澄清 | `independent_verification_missing`，覆盖对应 P |
| 提取为 true 或 false | 模型解释用户声明具备或缺少该项 | 保留原 `reported_met` / `reported_unmet`；不等于独立验证 |

“未绑定”不能改写成“用户从没说过”。提到 h5ad 不能证明表达谱可用；提到 spliced/unspliced layer 也不能证明其生成方法、观测语义或有效性。原话绑定检查出处，不判断模型理解是否正确。

## 绑定与输出约束

V4在工具与最终回答中重新核对原始用户轮次、全文哈希、Unicode跨度、报告指针和值、P顺序、实际evaluate请求、模型回执及输出哈希。不能只凭P编号、`report_present=true`或一个null字段声称存在有效原话绑定。

`unknown_requirements` 保留为输入状态未知的总览。新增 `unreported_requirements` 表示本次检查无绑定报告的所选输入，`bound_unknown_requirements` 列出有绑定但状态未知的P。提取完整性与科学含义继续标为未建立。

有未绑定项时至少需要一项 `not_supplied`，没有未绑定项时禁止使用这一类别。每个绑定的null P须由 `independent_verification_missing` 覆盖；只填写来源证据缺口不能替代输入澄清。现有 `not_supplied p=[]` 无法逐项验证自由文本所指的输入，因此混合缺口时仍需另行评估追问含义。

首次仍只能检查，`answer=null`；工具后才允许结束，结束须空routes/reports和完整回答。来源条件、未知项、E别名、预算和本地校验继续保留。该版本不授权分析、文件或云任务执行。

## 兼容与界面

新研究台流程请求显式选择V4，并绑定后续的[一次最终格式修复策略](WORKFLOW_FORMAT_REPAIR.md)。V4程序调用没有该policy时保持原行为；未指定版本的旧程序调用继续使用V2。已有V1、V2和V3按原合同重放，不迁移或润色旧回答。

输入检查服务的新版本 `reported_input_state_v2` 使用 `workflow-reported-input-review-v2`，将unknown理由表述为“输入状态未确认”。默认服务调用继续返回旧v1；新预览显式选择v2，并把版本计入刷新指纹。

结构化表单的null仅表示已提交一个未知状态，不声称有自然语言原话。模型提取的null与未绑定项分别展示；历史v1检查的文字保持原样。

## 本阶段实际结果

主工作区130项合同/界面检查与两组232项旧回归通过，另13项调用保护及6项历史真实重放观察通过。旧V3成功、旧V2失败均按原状态保留，没有追加模型调用。

该阶段未启用修复策略的独立W02真实单例失败：实际2次请求、1次只读工具，报告12,477 tokens，金额未知。第二响应是合法JSON，但 `answer.d` 为206个Unicode字符，超过原180限制；完整本地校验拒绝，该轮回答不可用，剩下一次额度关闭。未经修改的raw missing项用了P1/P2的独立核验类别，没有not_supplied；这只是原输出观察，不能称该轮已通过完整finish、语义验收或知识增益。

后续独立协议已实现总调用上限内最多一次明确格式修复，并完成一次真实恢复；原阶段失败、原文及回执仍封存，不截短旧回答救分、不放宽原字段，也不重开这次额度。用量未知、来源变动与身份不符仍停止；金额未知按已授权的调用数和token限额控制，如实记录。具体当前结果见[修复策略](WORKFLOW_FORMAT_REPAIR.md)，源码尚未重建部署归档。

公开副本、完整UI及实际范围见[阶段摘要](validation/workflow-report-presence-20261018.json)与[验证记录](WORKBENCH_VALIDATION.md)。开发检查使用既有安装环境和串行有界入口：

```sh
python -I -B scripts/verify_output_contract_stage.py --output ./report-presence-check01
```

输出目录必须不存在。入口将合同检查和完整旧选择分为三个串行通道，每个仍限120秒/1.5GiB；不请求模型或做科学拟合。真实模型交互、科学增益与外部系统比较分别记录。
