# scKG-Agent 2.0 科研评测协议

版本：0.2  
状态：Phase 0 protocol skeleton completed；execution experiments not started  
主规约：`docs/DEV_SPEC_2.0.md`  

> 本协议定义研究假设、评测轨道、数据隔离、指标和可声明结论。任何为提高结果而改变数据拆分、阈值或排除规则的行为，必须先更新协议并记录版本。

---

## 1. 研究假设

### H1：DataProfiler + ToolContract 减少无效工作流

主要指标：

- critical input error recall；
- parameter legality；
- I/O compatibility；
- invalid execution blocking rate；
- false blocking rate。

### H2：Execution-oriented KG-RAG 提高执行知识召回

主要指标：

- parameter source recall；
- input requirement recall；
- failure mode recall；
- metric definition recall；
- source span hit rate；
- context precision/recall。

### H3：执行反馈提高任务完成与复现

主要指标：

- executable rate；
- required artifact completion；
- failure detection；
- rerun success；
- unsupported repair rate；
- unsafe action rate。

### H4：Probe 可辅助配置选择，但外推有限

主要问题：

- configuration ranking 是否跨 seed 稳定；
- development probe 的配置是否在 evaluation probe 保持优势；
- synthetic 排名是否与正交标签数据一致；
- probe 排名是否能预测更大数据表现。

### H5：受控 Agent 的安全与灵活性权衡

主要指标：

- task completion；
- invalid action；
- tool calls；
- runtime；
- repair success；
- unsupported scientific claim。

---

## 2. 双轨 Baseline

下表定义目标评测组，不表示这些系统当前都已实现。Phase 0 的实际状态是：Track A 已有 1.x plan-only prototype 和小规模自建 workflow eval；Track B 全部是 `design_only/not_implemented`，不得产生执行性能结论。

### Track A：Planning / Knowledge

| 系统 | Knowledge | Matrix Profile | ToolContract |
| --- | --- | --- | --- |
| LLM-only | model knowledge | text summary | no |
| Ordinary RAG | document chunks | text summary | no |
| KG-RAG | KG + governed chunks | yes | no |
| KG-RAG + ToolContract | KG + governed chunks | yes | yes |

比较：

- tool recall；
- workflow step recall；
- parameter legality；
- parameter provenance coverage；
- input/output compatibility；
- unsupported claims；
- invalid plan blocking。

### Track B：Execution / Repair

| 系统 | Execution | Repair |
| --- | --- | --- |
| Expert static script | reviewed fixed script | none |
| One-shot LLM-generated code | one generated program | none |
| Contract-constrained execution | allowlisted wrapper | none |
| Contract-constrained execution + repair | allowlisted wrapper | bounded deterministic policy |

比较：

- executable rate；
- artifact completion；
- error detection；
- repair success；
- invalid repair；
- runtime；
- peak-memory observation；
- reproducibility level；
- unsafe action。

公平性与安全约束：

- Expert static script 和 contract routes 使用相同数据、资源预算和 metric implementation；
- LLM baseline 的 model、temperature、prompt 和 token budget 必须冻结；
- `One-shot LLM-generated code` 在没有容器/独立隔离 worker 时不得真实运行任意代码；
- Phase 3 本地评测可将该 baseline 限制为静态检查，或让 LLM 只选择同一 registry 的 wrapper/参数；
- 不同能力的 baseline 只比较共同拥有的指标。

### Agentic Ablation

```text
fixed deterministic workflow
vs
Parent Agent dynamic routing
```

相同输入、工具、contract 和预算下比较动态请求信息、停止、继续和 repair 路由的收益与协调成本。

---

## 3. Doublet 数据层级

### 3.1 Engineering Fixture

用途：

- wrapper smoke；
- artifact/trace/metric pipeline；
- configuration sensitivity；
- seed stability；
- security and timeout tests。

允许 synthetic labels，但结果必须标记 `synthetic_engineering_metric`。

### 3.2 Scientific Pilot Dataset

至少选择一个具有正交 doublet 标签的公开数据集。可接受标签来源：

- cell hashing；
- genotype demultiplexing；
- experimental mixture；
- 其他与 Scrublet 模拟机制独立的实验标签。

数据集进入协议前必须记录：

- canonical name 和 source URL/DOI；
- license 和下载方式；
- label generation method；
- singlet/doublet 数量；
- platform、species 和 sample scope；
- preprocessing；
- exclusion criteria；
- known label noise；
- local file hash。

当前具体数据集：`TBD after Phase 0 source review`。

---

## 4. 防循环验证

Scrublet 的方法假设包含 synthetic doublet simulation。外部 Probe Builder 生成的简单 count-sum doublets 不能作为唯一科学评价。

强制措施：

1. Probe Builder 与 Scrublet wrapper 独立实现；
2. 记录 generation algorithm/version；
3. 分别生成 homotypic 与 heterotypic probes；
4. synthetic 只验收工程闭环和内部敏感性；
5. 真实科学结论来自正交标签数据；
6. synthetic 与正交标签结论不一致时，以外部标签结果为主要结论并报告差异。

---

## 5. 参数搜索与数据隔离

每个 experiment 划分：

```text
development：选择配置、threshold 或 search range
evaluation：冻结配置后报告最终性能
```

禁止：

- 在 evaluation set 上选配置；
- 报告参与参数选择的数据上的最佳指标作为最终性能；
- 看到 evaluation 结果后静默修改排除规则；
- 在不同 baseline 间使用不同资源预算却不报告。

Synthetic probe 的 development/evaluation 必须使用不同 pairing、seed 和 labels。

数据不足时允许 nested resampling，但结论标记为 internal validation。

threshold 来源固定枚举：

```text
tool_default
expected_doublet_rate
development_probe_tuned
user_override
```

---

## 6. 指标与统计

### 6.1 Classification

- AUROC；
- AUPRC；
- precision；
- recall；
- F1；
- top-k recall。

类别不平衡时 AUPRC 为主要指标，AUROC 为辅助指标。

### 6.2 Engineering

- run success；
- artifact completion；
- schema validity；
- runtime；
- peak-memory observation；
- timeout cleanup；
- process leak count；
- reproducibility level。

### 6.3 Stability

- seed-to-seed metric variance；
- configuration rank correlation；
- subsample rank consistency；
- threshold sensitivity。

### 6.4 Uncertainty

只有重复运行或 resampling 足够时输出区间。必须同时记录：

- resampling unit；
- repeat count；
- confidence interval method；
- random seed；
- whether observations are independent。

不输出无定义的“推荐可信度百分比”。

---

## 7. 允许声明的结论

Engineering Fixture 可声明：

```text
wrapper 可执行
artifact 完整
配置敏感性
seed stability
metric reproducibility
```

不可声明：

```text
真实 doublet 检测准确率
该工具对所有 scRNA-seq 最优
synthetic 排名可直接外推真实数据
```

Scientific Pilot 可在数据集 scope 内声明比较结果，但必须显示标签来源、数据范围、不确定性和外推限制。

---

## 8. 评测产物

每次 frozen evaluation 输出：

```text
eval/execution/<protocol_version>/
  dataset_manifest.json
  split_manifest.json
  baseline_configs/
  predictions_or_calls/
  run_manifest.jsonl
  metrics_per_run.tsv
  metrics_summary.json
  statistical_report.md
  failure_queue.tsv
  claim_boundary.md
```

不得覆盖旧 protocol 的 frozen artifacts。

---

## 9. Artifact-grounded Evaluation

执行类指标必须由结构化 artifact 计算，不能只读取 Agent 自述或 LLM judge。

| 声明 | 最低 artifact |
| --- | --- |
| plan 合法 | RequirementSpec、DataProfile、ToolContract snapshot、WorkflowPlan |
| 工具执行成功 | ExecutionRequest、exit code、stdout/stderr、版本、output manifest |
| artifact 完整 | ArtifactSpec 校验结果、文件 hash、shape/schema |
| 参数可追踪 | ParameterProvenance、contract version、source span 或 policy rule |
| 修复成功 | failed run、RepairProposal、RepairAction、new run、re-validation |
| 可复现 | environment snapshot、input hash、rerun command、rerun result |
| 推荐/决策 | CandidateEvaluation 列表、Pareto frontier、preference、elimination reasons |

LLM judge 只允许评价可读性、解释完整性或错误分类候选，不能覆盖 artifact-grounded pass/fail。

当前 1.x `workflow_eval_v0_1` 的 `pass_rate=1.0` 只验证 8 条自建场景的 plan shape、候选召回和 evidence boundary；它不是 execution 或 biological correctness 指标。

---

## 10. Development / Evaluation 防泄漏

### 10.1 数据与 case 隔离

- planning prompt、contract、repair rule 和 threshold 只能用 development cases 调整；
- evaluation case 的输入、标签和预期失败类型在冻结后不能用于继续调规则；
- source document 可以同时服务检索，但 evaluation gold answer 和人工判定不能进入 RAG index；
- 同一 biological sample 的衍生对象不得跨 development/evaluation，除非协议明确采用 group-aware split；
- synthetic pairing、random seed 和 threshold selection 必须分离；
- 每次 frozen run 保存 protocol version、Git commit、worktree state 和 configuration snapshot。

### 10.2 旧 artifact 使用边界

- `eval/` 中历史 recommendation/migration 结果只能做 Track A regression；
- `data/scKG_embeddings_backup.jsonl` 只能做 legacy recall baseline；
- review packet、AI review 和 source chunks 不能作为 evaluation gold label；
- formal evidence promotion 不能在看到 frozen evaluation 结果后静默修改。

### 10.3 泄漏检查

至少记录：

```text
case_id overlap
source_id overlap policy
sample/donor overlap
prompt/contract version
threshold provenance
evaluation-after-tuning count
candidate leakage count
```

任何未解释的 evaluation label leakage 都使该次结果无效。

---

## 11. 当前 Baseline 实现状态

| Baseline | Phase 0 状态 | 当前可报告内容 |
| --- | --- | --- |
| 1.x deterministic workflow template | implemented prototype | plan shape、candidate recall、boundary |
| 1.x KG/evidence-gated recommendation | partially_implemented | 旧 eval regression，非 execution |
| ordinary document RAG | partially_implemented fallback | retrieval context，不支持参数执行 |
| execution-oriented KG-RAG | design/partial retrieval | execution claims 尚未建 gold set |
| Expert static Scrublet script | not_implemented | 无 |
| One-shot LLM code baseline | design_only | 无；无隔离时不得运行任意代码 |
| Contract-constrained execution | not_implemented | 无 |
| Contract-constrained repair | not_implemented | 无 |
| Parent Agent dynamic execution routing | not_implemented | 无 |

---

## 12. Phase 0 未决项

以下内容必须保持 TODO，不能在没有 source review 和预注册前编造：

- `TODO-DATASET-1`：选择至少一个带正交 doublet 标签的公开数据集；
- `TODO-LICENSE-1`：确认数据 license、下载与再分发边界；
- `TODO-SPLIT-1`：确定 donor/sample-aware development/evaluation split；
- `TODO-STAT-1`：根据样本和重复结构选择 bootstrap unit、CI 方法和最小重复数；
- `TODO-BASELINE-1`：定义 expert static Scrublet script 的固定参数与 provenance；
- `TODO-AGENT-1`：定义固定 workflow 与 Parent dynamic routing 的等预算比较；
- `TODO-ROBUSTNESS-1`：冻结 invalid input、timeout、missing artifact 和 dependency error perturbation set；
- `TODO-COST-1`：统一 wall time、tool-call、token/API cost 和 peak-memory observation 记录方式。

这些 TODO 不阻止 Phase 1 schema/profiler 开发，但阻止 Phase 3A-S scientific validation 和正式科研结论。
