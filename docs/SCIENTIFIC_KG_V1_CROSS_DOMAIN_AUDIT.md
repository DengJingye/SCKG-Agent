## 1. Overall architecture/content verdict

**v1.1 架构方向成立；当前 expansion 是有价值的候选底稿，但尚不足以作为驱动 Scientific Action Space 的首个正式 Scientific KG。建议保持冻结，暂不整体推广。**

审计对象为 `ecd9e0f`，工作区保持 clean。

当前深度明显不均衡：

| 维度 | 实际状态 | 判断 |
|---|---|---|
| 生态覆盖 | 19 个 ecosystem，10 个能力族标签 | 广度成立，规划能力覆盖被高估 |
| 操作深度 | 12 个 OperatorRevision，仅分布在 7 个 ecosystem | 其余 12 个缺少可用于规划的操作模型 |
| 版本 | Scanpy 5 个 operator 固定为 1.11.2；外部 7 个均为 unresolved source snapshot | 外部实现不能直接成为版本确定的行动选项 |
| 科学知识 | 92 claims，其中 27 条复用 Scanpy | 数量不足以反映各领域深度 |
| 参数与限制 | 6 条参数、5 条限制 claim | 相对于 19 个生态过于稀疏 |
| ReferenceArtifact | 0 | 注释与参考依赖分析缺少核心决策对象 |
| 比较证据 | BenchmarkStudy、EmpiricalResult 均为 0 | 无法支持有证据的性能优选 |
| 风险 | 当前队列覆盖新增 65 claims，其中 26 条 R3 | 不是完整候选集的风险分布 |

关键判断是：**目前能描述许多软件“做什么”，但尚不能可靠回答“给定这些数据状态，具体哪个操作现在适用、还缺什么、会产生什么”。**

## 2. Coverage blind spots

19 个生态有代表性，但选择明显受现有 corpus 可用内容影响。生成器主要引用本地固定 evidence IDs；32 个外部 evidence references 中，26 个来自 README，3 个来自 publication TSV。工具数量与易取得的概述材料联系较强，与科学决策的重要性不完全对应。

主要盲点：

- **基础分析前后段缺失。** Scanpy 已有 HVG/PCA/neighbors/UMAP/Leiden，却缺 QC、过滤、归一化、log transformation、marker testing 等候选操作。当前五步不能形成完整的 raw-counts 分析路径。
- **实验设计驱动的 differential analysis 缺失。** tradeSeq 不能代表所有差异分析。需要区分 cluster marker、条件间 differential expression、differential abundance，以及 cell 与 donor/sample 的统计单位。优先增加 pseudobulk＋edgeR 路径，而不是继续增加整合方法。[Bioconductor 多样本分析](https://www.bioconductor.org/books/3.21/OSCA.multisample/multi-sample-comparisons.html)
- **常规 pseudotime 路径不足。** 有 WOT/moscot/scVelo/CellRank，却没有一个清晰建模的普通表达状态→lineage/pseudotime 路径。Slingshot 是适合补齐这一缺口的候选。[Slingshot 官方说明](https://www.bioconductor.org/packages/release/bioc/manuals/slingshot/man/slingshot.pdf)
- **多组学主要停留在名称和概述。** totalVI、MultiVI 有 Method identity，但没有对应操作和约束。RNA＋protein、RNA＋ATAC、样本级 multi-view factor analysis 尚未形成独立决策路径。
- **染色质分析缺失。** 没有系统表达 fragments、peak matrix、genome assembly、TF-IDF/LSI、motif references。若 v1 声称支持 RNA＋ATAC 规划，应补 Signac 或同类的一条限定路径。[Signac 官方介绍](https://satijalab.org/signac/)
- **调控网络覆盖失真。** MIMOSCA 的 perturbation-analysis 概述不能代表一般 GRN inference。pySCENIC 所需 TF list、motif ranking database、motif-to-TF mapping，恰好能检验现有 ReferenceArtifact 架构是否完整落地。[pySCENIC 官方要求](https://pyscenic.readthedocs.io/en/stable/installation.html)

相反，doublet detection 已有三个方法，trajectory/transport 有多个生态；在核心统计设计与基础处理尚浅时，这种分布不够均衡。

## 3. Systematic modeling problems

**第一，类型分开了，但粒度仍不一致。** Scanpy 被拆成具体操作和方法；`method:seurat_analysis` 仍是“分析框架”，scVI/totalVI/MultiVI 则是模型方法。框架、任务族、算法和实现入口不能因为都放进 `Method` 就获得同等规划语义。训练型模型还需要区分数据注册、训练、推断和产物读取，不能用一个宽泛 operator 代替生命周期。

**第二，部分 ports 从方法叙述直接提升成 API 输入。** 例如 DoubletFinder 的候选输入只表达 PCA coordinates，但所引用 README 明确描述的是已处理的 Seurat 对象及其他要求。SingleR 的方法论文能支持参考相关性原理，却不足以单独固定某个包版本的 API 契约。这是普遍的“方法需要什么”与“具体调用接收什么”混淆。

**第三，Scope 有结构，但填充仍过于模板化。**

- 20/31 scopes 为 `partially_known`。
- 新增 scope 普遍使用 cell observation unit、空版本和空 study-design constraints。
- Seurat 的 multiomics capability 使用了 quality-control/RNA scope。
- MOFA 输入允许 sample，但 scope 固定为 cell。
- 多模态列表放在 `all_of` scope 中，缺少明确的可选组合，存在把“支持这些模态”误解释为“必须同时具备这些模态”的风险。

`partially_known` 能表达未知，却不能消除已经填错的约束。

**第四，Representation 仍有跨领域合并。** `multiomics_matrices` 没有 component 定义与跨模态 observation mapping；`pseudotime_lineages` 合并了时间值和 lineage weights；`transition_matrix` 同时容纳概率与 affinity。这些差异会直接影响输入兼容性，不能只依赖自由文本解释。

**第五，ReferenceArtifact 边界未落地。** 表达矩阵是 representation；注释 atlas、classifier、标签体系及版本是 reference identity。当前 annotation/reference signatures 主要作为矩阵类型出现，缺少物种、基因命名、标签空间、模型版本和跨参考映射的约束。

**第六，关系与端点的完整性被结构测试高估。**

- 6 个 `parameter:*` 和 5 个 `limitation:*` object ID 在 candidate bundle 内没有实体定义。
- 未见为这些端点登记外部解析契约。
- 新增两个 `CAN_FEED` 保留了端口和 claim premises，但仅使用目标 Scanpy scope；尚不足以证明双方版本、观察值对齐、容器转换和表示条件的交集。
- 冻结规范的关系词汇能够覆盖各领域；当前数据主要使用 `supports_task/requires/produces`，没有充分实现参数、参考、兼容维度、条件要求和比较关系。

**第七，provenance 与风险报告不能等同于语义通过。**

`source_bound=true` 证明有来源关联，不证明该来源支持全部命题。三个 publication TSV span 实际包含标题和目录标签，不能作为丰富操作语义的证据。

生成器还将 `unsupported_candidate_relation` 直接写为 `passed=True, count=0`；这是声明，不是完成语义审查后的测量结果。当前 26 条 R3 只覆盖新增 claims，没有完整纳入原 Scanpy claims、6 条 `CAN_FEED` 的风险处置。8 条 `partial_support` 也需要区分项目 profile 和上游证据不足，不能统一当成待补引用。

这些问题符合 v1.1 已有约束，**不需要重设计架构，需要让构造流程真正执行架构要求。**

## 4. Priority additions/deepening

建议按科学决策依赖推进：

| 优先级 | 深化或新增内容 | 完成后应具备的能力 |
|---|---|---|
| P0 | 类型端点、claim-specific scope、版本身份、完整风险登记、真实语义质量检查 | 候选事实能被安全解释，不因结构合法而误入行动空间 |
| P1 | Scanpy 完整基础链；Seurat 一个受限的对应处理链 | 从原始/已处理状态判断 reuse、缺失处理与后续分析 |
| P1 | Harmony、scVI；保留 Scanorama 已有候选 | 区分 corrected embedding、corrected expression、latent model，避免错误互换 |
| P1 | Scrublet＋SoupX；CellTypist＋SingleR | 区分 doublet/ambient RNA，并表达模型式与参考表达式注释的不同要求 |
| P1 | Pseudobulk aggregation＋edgeR | 将 donor/sample、design、contrast 和重复结构带入差异分析 |
| P2 | Slingshot；scVelo→CellRank 的限定链 | 分开 pseudotime、velocity、transition kernel 与 fate probability |
| P2 | scvi-tools 的 totalVI；MOFA2 | 建立 RNA/protein 与多视图 factor-analysis 两类不同多组学语义 |
| P2 | pySCENIC 的限定路径 | 建立 reference-dependent GRN 推断，明确结果属于推断证据 |
| P3 | Signac 或其他一个染色质路径 | 在明确支持 RNA＋ATAC 时补齐 genome/peak/fragment 语义 |

totalVI 的 RNA/protein 模型适合作为首条多模态路径；无需同时展开全部 scvi-tools 模型。[totalVI 官方模型说明](https://docs.scvi-tools.org/en/latest/user_guide/models/totalvi.html)

每条路径的建设单位应是“任务＋适用范围＋操作依赖闭包”，并允许缺失部分明确阻断，而不是要求每个工具填满相同关系矩阵。

## 5. What should explicitly be deferred

- **WOT、moscot、MIMOSCA、cell2location 的全面展开**：保留候选与 gaps，暂不让它们承担对应领域已经具备规划能力的证明。
- **重复方法的全面覆盖**：DoubletFinder/scDblFinder、更多 integration 算法可后续扩展；优先保证至少一条可信路径和必要替代选项。
- **所有物种、组织、平台、版本的覆盖**：推广有明确范围的子集即可，范围外保持 unknown。
- **全量参数与普遍性能排名**：先覆盖影响输入、输出、方法选择及科学解释的参数。缺少 EmpiricalResult 时可以列举适用选项，但不能声称有证据的性能优胜。
- **SCENIC+ 全面多组学调控、全部 ATAC 方法**：作为后续扩展，不必阻塞限定 RNA/protein 的首版。
- **运行环境和 ToolContract 的全面 qualification**：缺失绑定可以阻断 execution eligibility，不应自动阻断独立成立的科学知识推广。

应从**首版行动候选集合**排除概述型、端点未解析、关键 scope 不明或证据不足的关系；保留其历史候选记录，不删除冻结 baseline。

## 6. Minimum candidate subset for a convincing Scientific KG v1

建议以约 **14 个生态的限定操作切片**为目标：

**Scanpy、Seurat、Harmony、scvi-tools、Scrublet、SoupX、CellTypist、SingleR、edgeR、Slingshot、scVelo、CellRank、MOFA2、pySCENIC。**

这个子集应证明以下能力，而不是达到某个节点数量：

1. 从 raw counts 或 processed representations 构建基础分析路径，正确保留可复用结果。
2. 根据输入状态区分整合方法，并准确表达其输出是否能供下游使用。
3. 区分污染处理、doublet detection 与 annotation，正确处理参考依赖。
4. 区分 marker discovery 与有重复实验设计的差异检验。
5. 区分 pseudotime、velocity 和 fate mapping 的输入假设及产物。
6. 至少完成一条明确模态组合的多组学路径，以及一条有参考版本约束的调控推断路径。

推广前，每条路径必须具备：可解析身份与端点、完整关键 ports、适用范围、直接证据、风险合规审阅和保留条件的派生关系。缺少输入时能解释缺口，不能因粗粒度类型相同就判定兼容。

**当前 candidate 中没有已经完成这些审阅要求的正式推广子集。最值得作为建设起点的是 Scanpy 基础链及其 integration、doublet、annotation 分支；随后补齐统计设计和多模态路径。**
