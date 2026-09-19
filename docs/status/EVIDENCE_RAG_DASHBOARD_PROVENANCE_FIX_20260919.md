# Evidence & RAG 数据来源与展示边界修复

本次仅修改 dashboard 的只读投影、来源标注及状态解释。入口仍为 `app.py` 的 Evidence & RAG；数据读取与渲染分别位于 `observability/dashboard/evidence_data.py`、`evidence_panel.py`。未改动原有检索、索引、科学知识、gold、scorer 或历史实验结果；未运行 benchmark；未 commit/push。工作区其他已有修改保留。

## 字段来源表

路径均相对本仓库。S 为用户在页面选定的索引目录：`data/indexes` 或 `data/indexes/retrieval_foundation_v1`。不会向其他 snapshot 回退取数。

| 区域 / 字段 | 实际来源文件 / 字段 | 统计与边界 |
|---|---|---|
| Snapshot 身份 | `S/evidence_index_manifest.json` 的 `build_id`、`generated_at` | 不推断缺失时间；缺失 ID 为 UNKNOWN。生成时间超过 30 天显示 STALE，代表展示提示，不判断科学有效性。 |
| 唯一 Evidence Chunks | `S/evidence_chunks.jsonl` 的 `chunk_id` | 完整读入后按唯一 ID 计数；重复/非法 ID、内容哈希或 manifest 不符时 UNKNOWN。 |
| Dense Vectors | `S/evidence_vector_metadata.json` 的 `chunk_ids`、`shape`、`build_id`；`S/evidence_vectors.npy` | 所有 ID 必须在同目录 chunks 解析，shape、矩阵形状、build 一致。声明 artifact SHA 的快照同时校验 SHA。失败显示 UNKNOWN 及具体原因。 |
| 逐工具 vector_count | 同上 metadata.chunk_ids 与同快照 chunk.tool_names / tool_name | 每个工具计关联 vector chunk ID 的集合交集；共享 chunk 对每个关联工具分别计数，逐工具和可超过唯一 chunk 数。未使用旧 algorithm audit 的 0。 |
| source_chunk_count | `S/evidence_chunks.jsonl` 的 `source_bound`、`chunk_text`、`source_id`、`retrieval_status`、工具关联 | 明确 source_bound、非空文本、有 source_id 且非 catalog_only 的关联 chunk；仅来源存在，不是科学正确性或完整性。 |
| Core 分母 / 名单 | `engine/source_corpus_v2.py::CORE_TOOLS` | 现有代码静态参考名单 16 工具。页面明示其来源，作为同一固定集合比较不同快照。 |
| 旧 Qualified 分母 / 名单 | `engine/source_corpus_v2.py::QUALIFIED_TOOLS` | Scrublet、scDblFinder、Harmony、Scanorama；静态旧标签，未附逐工具资格证明。当前 execution qualification 为 NOT_MEASURED。 |
| 有可用来源关联的工具数 X/Y | 上述同快照可用 chunk 的工具集合 × 固定名单 | 分子为至少一个可用来源关联的名单内工具数；分母为名单工具数。缺少 chunk/关联/名单不能显示伪造 100%。 |
| 历史实验指标 | `data/evaluation/retrieval_eval_v2/summary.json::profiles[profile]` | 保留原字段、数值、状态和文件；2026-08-04 的 96-case 旧工程回归，绝不改称当前科学问答准确率 / 新 Hit@10。 |
| 历史正负例分母 | 同 campaign 的 `cases_<profile>.jsonl::status` | 完整 96 行中 retrieved=88，blocked_as_required=8。缺文件/不完整/未知状态时 UNKNOWN，不从当前 gold 补算。 |
| 历史评分解释 | `eval/retrieval_evaluation.py` 的 gold 构建与 `evaluate_profile` | gold 源于已有 chunks/tags；部分 expected tools/tasks 传入请求；宽泛 source/tool 匹配。正例指标以 88 例取均值，false support 以 8 个 must_block 负例为分母。 |
| 开发 campaign | `eval_v2/*retrieval*dev/report.json`，同目录 pre_run_manifest / manifest / run_started / run_completed | 通过 campaign 选择；展示原指标名、分子/分母与原报告。实验绑定 snapshot 身份独立于页面资产选择。COMPLETE 只表示运行完成。无 run ID 时 UNKNOWN，不把目录名冒充 run ID。 |
| 作废状态 | `docs/status/RETRIEVAL_BENCHMARK_V1_1_DEV_INVALIDATION.md` | v1.1 的 INVALID 明显展示，保留旧 COMPLETE 原值供追溯，不采纳为正式结论。 |
| Source audit 总数与分项 | `data/evidence_candidates/source_registry.tsv` 的唯一 source_id、source_status | 历史已登记集合：20 = 17 source_text_available + 2 pdf_extraction_failed + 1 source_metadata_mismatch；额外/未知状态单列且纳入等式。不是当前全库测量。 |
| 历史汇总一致性 | `source_acquisition_summary.json`、`source_extraction_summary.json` | 与 registry 比较，不一致报警，不以汇总覆盖记录。 |
| 错误 DOI/source、恢复动作 | `source_validation_report.tsv` | 完整保留 source_status、validation_status、问题、动作、DOI、标题、路径等；失败与 mismatch 默认可见。 |
| 文献关联行 | `core_literature_source_coverage.tsv` | tool-record-level；同一个 source 可能对应 CellTypist/SingleR 等多条记录，不能当作不同来源。 |
| Quarantine 候选行 | `pdf_candidate_registry.tsv::quarantine` | 2 条候选登记行，不是 2 个唯一 source 或 2 个 chunk。 |
| Quarantine 来源组 | `source_quarantine_v2.json::records` | 1 个登记来源组，关联 2 个 tool-record；保留错误 DOI、实际解析标题和隔离原因。 |
| 每文件 provenance | 实际读取文件的绝对路径、SHA-256、mtime；JSON 原有 generated_at/completed_at/created_at、build_id/run_id | mtime 不当生成时间，SHA 不当 run ID；未记录一律 UNKNOWN。当前查看时间不冒充新审计时间。 |

## 空值语义

- `validation_issue` / `candidate_issue` / `quality_flags` 的 none/空白：无登记问题，不代表校验通过。
- `recommended_action` / `action` 的显式字符串 `none`：无需处理（登记为 none）；Python/JSON null 或空白：UNKNOWN，是否需要处理未知。
- `validation_status` / `review_status` 空白：NOT_MEASURED，未登记校验结果。
- 文件路径空白：UNKNOWN，未登记文件；notes 空白：无备注。
- 开发指标分母为 0：N/A，不显示 0% 或 100%；其他未测指标：NOT_MEASURED。
- 可读取的完整登记集合才允许数值 0。只读展示不重新核验已登记“文本可用”的本地文件。

## 验证

`python -m pytest -q tests/test_evidence_dashboard.py tests/test_dashboard_services.py`：31 passed，4.82 秒；2 条现有 protobuf 弃用警告。全部新测试以临时 fixture 运行，无检索或科学执行。

覆盖：两快照往返选择不串数；共享 chunk 去重；缺失/不可读/损坏 metadata；未知/重复 vector ID；shape、build、矩阵不符；缺 chunk/tool/source 元数据；哈希不符；历史身份、原值及作废记录保留；source 分项与总数解释及旧 summary 冲突；不同空值语义；Streamlit 真正渲染与选择器切换。

额外只读 AppTest：真实数据的 5 个 campaign 均能渲染，v1.1 显示 INVALID；foundation snapshot 800/790 渲染正确。`py_compile` 与 `git diff --check` 通过。

真实浏览器：既有 `http://127.0.0.1:8501` 的 Evidence & RAG 页面；默认 snapshot 783/773、foundation 800/790；历史 96-case/88 正例/8 负例；审计 20=17+2+1，quarantine 1 组/2 候选行。截图位于工作区上级 `ui-review-evidence-rag-20260919`。

301 个受保护文件（索引、候选知识/来源、旧实验、eval_v2、旧 gold/scorer）修改前后 SHA-256 完全一致。没有补文献、重建索引、调整检索或重跑实验。现有 8501 服务继续运行，刷新页面即可，无需新命令。
