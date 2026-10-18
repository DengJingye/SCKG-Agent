# 预测产物与分数定义：开发预览

本功能把来源定义连到**显式选定的已有产物快照**，核对运行身份、文件哈希、表头及有限元数据，再显示适用或尚未确认的来源条款。它不执行预测，不解析每细胞分数或标签，不读取真值，不评价准确率，也不更改分数。

## 知识内容与实际导入

复用已有CellTypist1.7.1 wheel归档和下载收据，核对models.py、classifier.py、annotate.py的原字节；本阶段没有重抓远端标签。先准备真实外部会话输入，再独立提取和开发AI复核，实际导入6个候选、13属性、20个Unicode精确锚点。5条直接来源断言和1条数学synthesis分别保存。8个passages对应11块，1 linked、10 partial；块链接不代表抽取完整率。旧交付及术语修订均保留，重复导入不增记录。

| 条款 | 必须保留的条件 |
| --- | --- |
| scores与raw probability matrix | decision_function后逐项expit，不据此认定经验校准 |
| 行和 | 一般多列不要求和为1；一维分数扩展为[-s,s]有互补例外，数学恒等不等于浮点逐比特保证 |
| best match | 按argmax选择；该分支忽略p_thres，后续投票另判 |
| prob match | 严格大于阈值；可能Unassigned或多标签，默认0.5不代表已校准阈值 |
| 默认conf_score | to_adata指定分支取行最大值，不能通称最终标签正确概率 |
| voting confidence | 插入开启且对应列存在；命中实际类列取该列，否则fallback最大值；不是投票比例。请求投票但细胞数≤50时可提前返回 |

这些候选及旧方法目录已合入同一个35候选开发工作区；普通推荐、人工审核及release仍为0。源码依据能说明数值定义，不能证明其在目标数据上的校准、最佳阈值或生物学正确率。

## 接口及边界

`prediction_semantics.py`复用既有Ledger、候选hash、原文锚点与暂停检查。独立`prediction_semantics_catalog`通过record/hash绑定包版本、来源metadata与条款；仅行和条款允许显式synthesis，旧输入检查仍只接受source_assertion。假说不能混入。

`prediction_artifact_binding`是开发者快照，明确不是执行验收。文件只能是工作区相对路径，使用无跟随、非阻塞描述符打开并要求普通文件；有界JSON/表头解析，完整分数字节流式哈希两次。默认JSON64KiB、manifest512KiB、score64MiB、header4096字节；身份读取共享15秒deadline，来源检查复用现有合同。外层实际验证另受120秒/1.5GiB监督；这些机制不等于操作系统沙箱。

必须匹配原manifest中的run/slot和文件SHA；文件、来源或目录变化后旧解释隐藏。缺实际版本、模式或所选标签列时保持unknown，不用文件名、现在的环境或计划协议补齐。投票写入前提只有明确True才满足，缺失/非法值不升级。数值同名类别不会被单凭名称误认成scalar字段。

界面位置为“知识库”→“预测产物分数定义（开发预览）”，仅已配置独立目录时出现，还需显式勾选。普通安装和旧合成方法演示不会凭空生成科学产物；该入口目前未开放为模型自动执行工具。原Scrublet结果路径和输入/聊天目录保留。

## 已有真实产物的观察

对原冻结manifest下A1的只读副本，文件身份与表头核验通过；完整分数字节仅用于哈希，0逐行解析。原metadata没有实际运行版本、预测mode或实际label_column，故6条精确版本条款均保留条件参考，状态为`identity_valid_semantics_unresolved`。计划要求1.7.1不能代替实际记录；raw calibration声明也不能代替校准测量。没有修改原产物或补写旧成功。

这暴露了需要修复的**生产者记录缺口**：下一项应在新的运行版本记录实际tool_version、mode、selected_label_column、分数角色和对应代码/产物hash，并重新验收；不能回填旧结果。之后才把该解释工具接入完整原生agent旅程。

## 验收与下一关

```sh
python -I -B scripts/verify_annotation_stage.py --output ./prediction-context-validation01
```

使用已有合格开发环境；输出目录必须新建。主/公开工作区各214项通过，含35项新预测解释回归；实际来源和A1完整页面、两次刷新、文件变动与来源暂停失效均通过。8个新工程反例修前2通过/6失败，修后8通过/0失败；原两项测试fixture错误也保留。具体资源、哈希与范围见[阶段记录](WORKBENCH_VALIDATION.md#预测分数知识连接已有产物)。

接下来优先补生产者元数据及独立wire/canonical合同的原生接口资格。新包必须预冻总调用/token/时间/内存和停止规则，旧HTTP400包不重开，不自动fallback。取得资格后再做同事实知识消融与共同任务外部agent比较，包含Genpilot；工程通过不是科学优势证明。
