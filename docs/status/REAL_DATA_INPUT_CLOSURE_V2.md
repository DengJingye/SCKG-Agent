# Real-data input closure v2

portable 事实源：`data/evaluation/midterm_freeze_v1_1/p0/real_data_input_closure.json`

运行分类：`CURRENT_MEASURED`

真实 Raw PBMC3k（2700 × 32738）和 Processed PBMC3k（2638 × 1838）均走过 `upload bytes -> content-addressed private copy -> DataRegistry -> DataProfile -> RepresentationLedger -> WorkflowPlan -> Notebook compile`。同名文件按内容哈希区分，A→B→A 回切保持数据、plan 与 Notebook 隔离；新会话不继承旧 binding，进程重启后只能通过显式选择恢复。

| PASS 条件 | 结果 |
|---|---:|
| `INPUT_BINDING_CORRECT` | true |
| `CROSS_SESSION_LEAKAGE` | 0 |
| `SYNTHETIC_FALLBACK_WITHOUT_EXPLICIT_USER_CHOICE` | 0 |
| 同名不同内容 | pass |
| A→B→A | pass |
| 空会话保持 unbound | pass |
| 重启后显式选择 | pass |

多文件上传时 UI 必须显式选择一个 `.h5ad`，未选择时禁用 unbound submission；对应当前测试 `test_multiple_uploads_require_explicit_choice_and_disable_unbound_submission` 已包含在 189/189 focused pass。该项是代码路径验证，本轮没有再保存一次“同时选择两个文件”的浏览器截图。

原始源文件只读，Raw 与 Processed 的源文件 SHA-256 分别为 `89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1` 和 `0db367b991dd95809732b218539ede489bea99113807f62ebd7ccc970025fe38`；上传副本逐字节哈希一致。
