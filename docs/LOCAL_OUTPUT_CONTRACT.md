# 显式输出接口与完整本地合同

开发流程对话可显式选择 `json_object_canonical_v1`。实际接口使用 `response_format={"type":"json_object"}`，完整的 `explicit_missing_v2` JSON Schema 作为系统消息一并发送，并在本地逐项验证。格式选择在提交前固定；HTTP 错误、输出不合法或接口声明不符时停止，没有自动换格式或修复调用。

这解决的是接口格式与应用输出合同耦合的问题。JSON 字符串合法不等于符合应用合同，更不证明科学判断正确。[DeepSeek 官方 JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)提供了 JSON 对象格式及提示要求，也提示可能返回空内容；该文档不能证明第三方兼容网关具备同样能力，或解释历史 HTTP 400 的具体原因。

## 使用与身份

Python 调用示意（仍需真实 profile、明确授权和预算）：

```python
result = models.invoke(
    profile_id, logical_messages,
    outbound_authorized=True, budget=budget,
    response_format={"type": "json_object"},
    validation_format=complete_strict_json_schema_format,
)
```

流程对话提交的 `workflow_options` 在原目录 ID、hash 外增加 `wire_mode="json_object_canonical_v1"`。未提供该字段时保留原 JSON Schema 接口及历史记录形状；不会根据模型名称或一次失败替用户切换。

工作台中先启用“开发流程对话：按来源检查输入”，再在“流程输出格式”显式选择“JSON 对象 + 完整本地合同”。默认仍为 JSON Schema，刷新不会发送请求。

完整 schema 保留 action enum、字段类型、长度、引用和 missing 跨字段约束。`not_supplied.p` 必须为空；已有原话但尚未独立验证的项目使用不同状态。规范 JSON、完整 schema、类型合同、原用户引文、来源身份、路线绑定及动作预算依次校验，任何一层失败都不能执行后续工具。

私有 `model_request` 同时保存实际 `payload` 和 `local_validation_format`；回执增加 `local_validation_format_hash`。实际请求 hash 包含系统消息中完整 schema 的字节。只读重放重新构建这两种身份，并核对原始输出，不能只检查 JSON 对象格式。该接线目前用于开发流程对话；其他 evidence 回答接口没有全局切换到新模式。

新模式的输入门在解锁凭据前计算完整最终请求，包括模型名、选项、完整系统消息、输出上限及 stream 字段。这个 UTF-8 字节加 256 的容量代理不是实测 tokens。每次请求仍受输出、时间和费用规则约束；旧模式的历史估计保留。系统消息模板是 v1 合同的一部分，未来修改须保留旧版重放路径。

## 验收

```sh
.venv-workbench/bin/python -I -B scripts/verify_output_contract_stage.py --output ./output-contract-check01
```

输出目录必须不存在。该入口复用既有串行监督器，新增合同和原回归分为两个串行测试通道，每个仍限 120 秒、1.5 GiB；只有两者通过且源码快照相同才汇总通过。合成 transport 不调用 provider、不拟合科学模型。检查包括完整合同不被 JSON 对象格式削弱、原始错误与回执保留、预算前置、声明格式检查、第三次调用只能结束、身份篡改拒绝和零调用重放。

真实接口资格与离线工程测试分别报告。一次真实流程完成也只说明该配置下的单例交互，不能视为知识增益、语义金标或市场 agent 对比结果。

历史V2真实记录：原 W02、全新会话，冻结最多 3 次调用。实际 1 次返回 `deepseek-v4-pro-ga-260813`、`finish_reason=stop`，报告 5,536 输入和 806 输出 tokens（合计 6,342），金额未知。完整 schema 拒绝最终回答中的两个长 candidate ID：它们不符合 E 编号格式和长度限制。另观察到 evaluate 动作同时填写 answer；提示和适配器要求其为空，初始 schema 尚未编码此阶段关联，不能把它混称为本次 schema 的直接报错。没有运行工具，原生旅程失败、界面不可用，剩余两次额度关闭。旧 HTTP 400 的原因仍未知。下一版需显式编码阶段条件；不能以放宽别名或自动修复绕过验收。

V3后续记录：新表单显式绑定阶段合同，原W02的新独立单例已以2次请求完成检查→回答及保存轮次重放；V2失败和未用额度仍关闭。阶段约束、兼容性及单例边界见[阶段合同](WORKFLOW_PHASE_CONTRACT.md)。
