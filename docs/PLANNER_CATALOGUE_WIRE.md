# 查询规划词表：无损编码与真实调用资格

状态日期：2026-10-18。完整词表在原输入上限内已可发送，随后4次真实规划与只读检索检查完成；这解决了本轮工程阻断，尚未证明检索相关性或知识增益。四道题均为已暴露开发题，没有独立留出确认。

## 改动与兼容

`plan_evidence_queries(..., catalogue_encoding="columnar_v1")` 显式选择新编码。它把模型可见的 `available_term_catalog` 从重复键的对象列表改为 `schema_version`、`fields`、`rows` 封装，并追加读取说明；每行保留原label、完整term_hints及顺序。严格本地解码必须恢复完整原条目，不能删词、摘要或截断。

服务端保留完整原生catalogue、220个已发布单元的原hash、来源及用途验证。词表有172个词面条目、原生上下文8,447字节；这些是检索元数据，不是把220份完整证据塞入模型。存储的run保留原生材料，新编码显式绑定请求与重放。默认及显式 `literal_v1`、缺编码字段的旧run维持旧行为；未知编码或缺catalogue的columnar请求提前拒绝。普通聊天的 `shared_text_v1` 与本次规划接口分开，普通聊天默认和UI没有因此切换为columnar。

本次只改 `evidence_wire.py` 与 `retrieval_planning.py` 两个产品模块，并加入一个独立合同测试文件；没有重写检索器、调整知识release或重建安装包。

## 八份完整请求的零API资格

固定原四题、完整问题、空数据画像profile、原schema、原172条词表、M0与预算，只改词表表示和对应读取说明。

| 开发题号 | literal完整输入代理 | columnar完整输入代理 | 减少 |
| --- | ---: | ---: | ---: |
| row4 | 17,088 | 13,254 | 3,834 |
| row5 | 17,122 | 13,288 | 3,834 |
| row6 | 18,426 | 14,592 | 3,834 |
| row7 | 17,194 | 13,360 | 3,834 |

四个literal完整body与旧封存基线完全一致；四个columnar解码后完整材料相等。literal四题均超原16,000上限，columnar四题均在限内。这里的计数是完整本地构造body的 **UTF-8字节＋256代理**，不是tokenizer、实际provider token数、价格或压缩后科学质量。原生catalogue上限仍为14,000字节。八body观察耗时21.9871秒，采样进程树峰值111,673,344字节，0 provider调用。

## 实际验证与4次规划

| 本轮定向测试选择 | 实际通过 | 耗时 | 采样峰值字节 |
| --- | ---: | ---: | ---: |
| `test_workbench_catalogue_wire.py` | 40 | 11.9939秒 | 131,121,152 |
| `test_workbench_evidence_wire.py` | 10 | 6.8478秒 | 158,777,344 |
| `test_workbench_grounded_chat.py` | 18 | 13.1049秒 | 136,151,040 |
| `test_workbench_chat_grounded.py` | 18 | 23.6787秒 | 140,034,048 |

共86项，零失败、错误或跳过；四通道串行，各限60秒/512MiB，复用已有宿主。覆盖可逆Unicode/顺序、坏结构拒绝、真实ModelService的合成transport、原生catalogue来源绑定、旧请求重放及篡改、未知编码和预算边界。合成transport不是实际provider或科学金标。86是本轮相关选择，不与历史78、649等相加，也不是全仓库回归或live browser验收。

已有开发环境可直接复跑相同四文件的合同测试；下面不重跑私人研究材料、资源监督或已关闭的真实账户：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv-workbench/bin/python -m pytest -q tests/test_workbench_catalogue_wire.py tests/test_workbench_evidence_wire.py tests/test_workbench_grounded_chat.py tests/test_workbench_chat_grounded.py
```

随后新独立账户只执行4次 `columnar_v1` 规划，每题一次；没有最终回答、selector、judge、训练或科学拟合。M0为 `deepseek-v4-pro`、temperature=0、reasoning=none；实际四次均返回 `deepseek-v4-pro-ga-260813`，接口没有可控模型seed。每次输入代理16,000、输出1,536、60秒；总预留上限70,144，SDK和格式重试均为0，整包480秒/512MiB。

| 题号 | 实际报告tokens | queries / evidence_checks | 只读top5完整来源解析 |
| --- | ---: | ---: | --- |
| row4 | 3,600 | 3 / 4 | 5项通过身份核对 |
| row5 | 3,612 | 3 / 4 | 5项通过身份核对 |
| row6 | 3,899 | 3 / 4 | 5项通过身份核对 |
| row7 | 3,739 | 4 / 7 | 5项通过身份核对 |

账户4次dispatch、14,850已报告tokens，usage未知0、未归档dispatch 0，金额未知；输入代理与输出预留合计60,638，二者不与实际tokens混算。监督耗时111.8416秒、采样峰值347,947,008字节，未超资源门，账户已关闭且不发第5次。原quota保持关闭，0拟合/新环境/生产写入。

实际出站body与资格材料绑定，本地schema及原话跨度检查通过；调用后使用真实原生检索并只读resolve排名前5个完整来源。171次排名单元出现和20次top5出现的hash身份核对通过，不代表171个不同单元或20条相关证据。完整远程JSON-schema强制能力仍未确证。

row7的4个queries和7个evidence_checks符合未改的硬schema上限4/8，但超过提示的软性精简建议3/4。原输出保留，不能称所有提示要求均已遵从。

## 仍未解决的内容问题

静态AI开发检查看到：规划查询主要采用疾病、组织和细胞词；实际top5多为CITE-seq、质量控制、Cell Ranger ARC和ATAC等条目。来源资格和hash正确，不能代替当前RNA任务的适用性、流程覆盖或语义支持。此观察不是盲评、precision、专家金标或科学错误率，也没有同预算对照证明新规划改善了相关性。

代码与实际trace另有机械断点：原问题总作为第一检索分支，FTS只取各查询前40词并OR匹配，round-robin先合入第一分支首项；四题实际首位均来自该分支。`evidence_checks`只被记录为`not_evaluated`，没有驱动额外搜索或完成验证。这些是数据流观察，不是语义相关性分数。调整分支合并属于独立检索干预，不能与补新知识一起改后统称知识增益。

下一步把**任务→分析家族→输入→验证**连成有来源、带条件的流程知识：先深入供体/条件RNA统计设计，明确样本与供体、配对、设计可估计性、混杂限制和产物验收；直接来源声明与开发解释分开，候选不自动发布。再冻结独立任务、单变量干预、预算与评分，测关键条件覆盖和真实决策。G2、完整G3、G4和整体G5仍未完成。

本页只公开脱敏指标及[证据SHA摘要](validation/planner-catalogue-wire-20261018.json)。不附私人题目、模型原回答、DB、凭据或来源全文；本次未重建安装包，旧已关闭研究账户不随文档复跑。
