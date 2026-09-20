# DEV pilot run — 2026-09-21

状态：`DEV_COMPLETE_REQUIRES_00_RESULT_REVIEW`。14 个已批准场景、4 lane、1 repetition，
56 个调度单元全部有回执；52 completed、4 not_run。13 个场景实际调用产品，W01 只做资格检查。
completed 表示产品返回输出，不等于科学正确或 workflow 成功。

本报告的科学评分是 **AI-assisted DEV 初评，待00结果复核**，不是人类评分、不伪装成两人审核、
不是独立校准 LLM judge。00 已批准题目和边界，并豁免本次 DEV 的双人审核；
正式 evaluation/Gold 的双人要求未改变。没有生成 Gold、正式 evaluation split 或额外题目。
旧 `scoring_protocol.md` 的“尚未授权运行”属于此前状态，本轮授权仅由最新00指令和本目录 manifest 覆盖；
没有新增 taxonomy、track 或评分 framework。

## 冻结与运行

- Benchmark worktree：`feature/evaluation-benchmark-v3`，运行前 HEAD `bf73ba04c6d827770c56a07029379040bf82335b`。
- 实际07 runtime：临时 detached worktree `/private/tmp/sckg-dev-pilot.uih3q9/runtime`，
  commit `5aaaf78d1fff31b7ccdda5d8a91f2ce9b8ff89ee`；运行前后 tracked code/corpora 无改动。
- Approved Scientific KG SHA256：`06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`。
  121 approved statements、166 separate caution contexts；held scVelo 不在 allowlist。
- Provider：`api.deepseek.com`；请求与116次实际响应均报告 `deepseek-v4-pro`。
  这是provider model alias，不是不可变权重指纹。configured `network_verified=false` 是静态检查值，
  本轮实际116次完成响应另外证明服务可达。
- 每个单元独立进程、独立 conversation、空历史、相同原始条件；调度 seed `20260921`，
  每场景 lane 顺序随机，最多4并发。K01a首批四次 smoke 已计入56，不额外重复。
- 保留07原始 provider参数、prompt、工具选择与后处理；provider seed 未设置，不声称确定性。
  无请求重试、无差答案重跑；0 provider failure，116 calls＝52 routing +48 synthesis +16 support_check。
- 环境无可选 `langgraph`，使用冻结07内置 `deterministic_graph` 调度相同业务节点；没有安装替换runtime。
- Planner / ToolContracts / guards / validation / approval 均为 shared infrastructure；本报告不把其行为算 KG coverage。
- 原题、fixture、KG/RAG corpus哈希未改变。公共问题来源和新增构题条件均继承原 provenance。
  输入渲染只添加原条件的 `key=value` 和 W02 原fixture，不注入答案/评分标准。

## 分 track 结果

| lane | K 条件正确 | K 条件对成对通过 | O triage | W02 产物审查 | W01 |
| --- | ---: | ---: | ---: | ---: | --- |
| llm_only | 4/8 | 2/4 families | 3/4 | 0/1 | not_run |
| generic_rag | 2/8 | 0/4 families | 3/4 | 0/1 | not_run |
| legacy_kg | 2/8 | 1/4 families | 2/4 | 0/1 | not_run |
| scientific_kg | 4/8 | 1/4 families | 3/4 | 0/1 | not_run |

不合成加权总分。W not_run 不作为0加入成功率分母。
K 成对通过核对条件正确性，不以答案文字不同判通过。
本组公开开发题、小样本、单次重复不能证明/否定广泛科研增益，也不能隔离图结构的因果贡献。

| scenario | llm_only | generic_rag | legacy_kg | scientific_kg |
| --- | --- | --- | --- | --- |
| dev-K01-hvg-input-a | PASS | FAIL | PASS | PASS |
| dev-K01-hvg-input-b | PASS | PASS | PASS | PASS |
| dev-K02-pca-chunked-a | PASS | FAIL | FAIL | FAIL |
| dev-K02-pca-chunked-b | PASS | FAIL | FAIL | PASS |
| dev-K03-reference-annotation-a | FAIL | PASS | FAIL | FAIL |
| dev-K03-reference-annotation-b | FAIL | FAIL | FAIL | PASS |
| dev-K04-evidence-version-a | FAIL | FAIL | FAIL | FAIL |
| dev-K04-evidence-version-b | FAIL | FAIL | FAIL | FAIL |
| dev-O01 | FAIL | PASS | PASS | FAIL |
| dev-O02 | PASS | PASS | PASS | PASS |
| dev-O03 | PASS | FAIL | FAIL | PASS |
| dev-O04 | PASS | PASS | FAIL | PASS |
| dev-W01 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| dev-W02 | FAIL | FAIL | FAIL | FAIL |

### W 的明确边界

W01 `reason=shared_execution_interface_unavailable`：冻结 wrapper 固定
`sc.pp.highly_variable_genes(..., flavor="seurat")`，renderer不暴露 `seurat_v3`。
本题需要共享支持的 `seurat_v3` 路径，不能用任意Python执行接口绕过。
代码片段与文件哈希在 `preflight.json`。这不是声称所有Scanpy执行都不可用。

W02提供三个输入gene ID、header-only `genes.tsv`、exit0、repair未审批。
四lane均未回答内容验证，而路由至workflow或unsupported_action并停止。
停止未授权执行是正确的；失败在于漏答已可审查的产物问题，不把它算成执行器跑错。
实际 `execution_request_count=0`、无execution run/artifact；不存在偷偷执行或伪造修复。

## 评分与归因审核

`reviews.jsonl` 对每份实际终答绑定SHA256、逐项布尔检查、精确摘录、理由；
原始 `review_notes.jsonl`、一致性更正 `review_amendments.json` 均保留。
初评使用去除lane字段的随机blind IDs；答案内部仍可能透露来源身份，且后续trace归因需揭示lane，
不能声称实现了独立、完全双盲评审。没有以来源引用缺失惩罚LLM-only的正确性。

O只评有用triage、必要澄清、有界假设、无根据确定诊断。
索引检查/条件性假设未命中GitHub真实根因不是失败；两条过严初评已透明更正。
明确虚构API建议或把未验证机制说成确定事实仍失败。K04正确询问installed version本身不算失败；
未解释版本证据边界、偏题或后处理丢失澄清才记录相应缺项。

29 个任务失败中，14 个标注重大科学错误/无依据确定性；其余是遗漏、偏题或未完成任务。
归因 revision 2 proposals：`routing=4`、`validation-governance=6`、`evidence=1`、`unresolved=18`。
每条绑定原始输入、实际prompt/provider响应、最终输出或trace，并保存证据文件SHA256。
`FailureAttribution` 只承载已提出明确阶段的记录，unresolved保留sidecar、不硬写成retrieval。

- **治理链6条**：包括原始正确counts/条件事实被support_check删除；K04b三lane出现
  `AnswerContractViolation / invalid_clarification`，原始针对性版本澄清被fallback替代。
  这是对前后日志的定位，不保证原始回答本来全部正确，也不主张将caution升级为approved assertion。
- **路由4条**：W02内容审查转成workflow/unsupported_action，随后未进入产物验证。
- **evidence1条**：SingleR-a scientific lane将caution作无提醒限定的正向断言，precheck按合约拦截。
  初稿误归治理，实际call-03输入已没有该段，不能把正确权限拦截当治理错误。
- **unresolved18条**：看得到科学条件错误或漏答，但没有足够证据证明是corpus gap、
  retrieval/context筛选还是模型组合问题。没有凭单次检索失败重标coverage。
  其中5条O初稿标synthesis；修订为“observed_stage=synthesis、主根因unresolved”，
  因未证明正确必要事实已送达模型，严格保留冻结归因门槛。任务分数不变。

独立核对所用版本化来源仅用于检查评分，不送回任何lane、不更新corpus：
[Scanpy 1.11.2 PCA源码](https://github.com/scverse/scanpy/blob/1.11.2/src/scanpy/preprocessing/_pca/__init__.py)
用于核对chunked分支、TruncatedSVD solver传递和mask_var布尔选择；
[Scanpy 1.11.2 QC源码](https://github.com/scverse/scanpy/blob/1.11.2/src/scanpy/preprocessing/_qc.py)
用于核对use_raw选矩阵与var注释使用的位置；
[Seurat v5.3.0源码](https://github.com/satijalab/seurat/blob/v5.3.0/R/differential_expression.R)
用于核对PrepSCTFindMarkers签名和已有模型校正。未据此认定未知installed version的实际issue根因。

证据可靠性与回答正确性分开：本轮保留07所有claim/authority/support-check日志，
它们是产品自审而非独立科学评分；没有把产品自己的 `passed` 当作本次task pass。
没有额外发布未经专家校准的citation精确率或source-bound综合分。

## 实际成本与动态检索

| lane | calls | input tokens | output tokens | 每单元平均服务延迟 |
| --- | ---: | ---: | ---: | ---: |
| llm_only | 25 | 43,109 | 8,657 | 7.007 s |
| generic_rag | 28 | 46,896 | 8,709 | 7.208 s |
| legacy_kg | 30 | 62,408 | 8,690 | 8.120 s |
| scientific_kg | 33 | 247,338 | 10,275 | 8.571 s |

均为13个completed单元，包含routing/synthesis/support calls；延迟是service.run实测，
不含worker启动/加载。所有call的provider usage可得。context-only token不可得，记null，
不能将整次prompt tokens冒充证据tokens。费用金额未估算。
实际top_k有3/4/5/12、include_catalog有true/false，详见 `postrun_verification.final.json`；
没有把fallback配置假装成所有调用的实际参数。

## 工程问题与验证

发现1类runtime receipt bug，影响Legacy的13条run：incoming请求中的
`use_scientific_evidence=false` 被误命名为effective，但实际backend在调用前已改成true。
独立backend capture一直正确。`runtime_receipt.corrected.json` 仅从捕获的真实请求更正；
原receipt原样保留，`receipt_correction.json` 绑定两者和捕获记录的哈希。
`receipt_for()`优先读更正版。没有改provider参数/输出，没有额外调用或重跑。

额外postrun检查开发中曾把非空handoff对象误当执行；已改为核对
execution_request_count/run_id/artifact_id/status。实际全部0请求，不影响运行或评分。

第2类修正是failure-attribution：6条初稿把下游发生位置或正确拦截过早标作主根因。
`attribution_amendments.json`保存原因，`result_index.json`指向最终 `.final.json`。
旧summary/scoring/attribution及逐run评分sidecar全部保留为revision 1；
归因以final文件为准，所有科学task分数逐条不变，未为表现差的lane改评分门槛。

- 74项pytest通过：覆盖frozen输入、隔离、write-once、receipt更正、逐项评分聚合、
  正确澄清/空产物/重大错误、答案摘录绑定、held排除、原有8种coverage及unknown/NA边界。
- 全56份canonical receipts通过JSON schema/native run模型、实际messages/response/output/hash核对。
- 原始来源文件、approved evidence链、Legacy/RAG corpus、runtime tracked files重新验证。
- 逐call provider/model/usage/预算、每lane13 completed+1 not_run、0执行请求均通过。
- 已对运行产物扫描已配置凭据值，无泄漏；不提交env文件。
- 原始runtime产物checksum清单见 `runtime_artifact_inventory.json`。
- 评分与归因的PASS只表示工程完整性和显式可复核标注，不等于00已通过科学结果。

没有修改05/06/07、题目、KG/RAG、产品prompt、安全组件；没有扩seed、机制实验、诊断重放、
Gold或正式evaluation；不push。当前不自动进入evaluation freeze，下一步交00审核这些结果与W适用范围。

## 复核入口与命令（全部离线）

`result_index.json`为最终版本入口；`summary.final.json`汇总；
`scoring_results.final.json`逐条评分；`failure_attribution.final.json`归因；
`runs/<case>--<lane>--r0/` 保存实际provider请求/响应、prompt/context、trace、产品终答和receipt。
每条输出/失败不会被后续重跑覆盖。本次运行模型输出只用于DEV，不能回流成Gold。

```bash
cd /Users/lris/Desktop/scKG_agent/SCKG-Agent-eval-v3
/opt/anaconda3/bin/python -m pytest eval/benchmark_v3/test_dev_pilot.py eval/benchmark_v3/test_dev_scoring.py eval/benchmark_v3/test_review_infrastructure.py -q
/opt/anaconda3/bin/python -m eval.benchmark_v3.dev_scoring validate --output eval/benchmark_v3/dev_pilot_20260921 --expected 56
/opt/anaconda3/bin/python -m eval.benchmark_v3.verify_dev_pilot --output eval/benchmark_v3/dev_pilot_20260921 --runtime /private/tmp/sckg-dev-pilot.uih3q9/runtime
git diff --check
```

不得直接重跑`initialize/run`覆盖本目录。临时runtime若日后不存在，应从指定commit另建detached worktree，
仅用于离线验证；任何下一轮provider运行仍需授权并使用新的experiment/output目录。
