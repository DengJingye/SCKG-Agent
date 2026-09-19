# Midterm screenshot index

截图包共 6 张。产品截图来自 2026-09-19 保存的真实 UI 资产；当前 Raw/Processed replay 的最新终态由 `CURRENT_VERSION_PBMC3K_REPLAY_V2.md` 与机器清单补充。每张图都只允许使用下表中的声明。

| # | 场景 | 文件 | 证据类型 | 允许声明 | 禁止夸大 |
|---:|---|---|---|---|---|
| 1 | ASK / PLAN handoff | `docs/assets/midterm_freeze_v1_1/01_ask_plan_handoff.png` | 保存的真实 Research UI；local deterministic | Research 可识别 PLAN 意图并把已绑定数据交给 Stepwise；执行未请求 | 不声明真实 LLM 生成或 Notebook 已执行 |
| 2 | PLAN Raw | `docs/assets/midterm_freeze_v1_1/02_plan_raw_profile.png` | 真实上传与 DataProfile/WorkflowPlan UI；同日开发验收 | Raw 2700 × 32738，真实 SHA 绑定，11-step plan，ExecutionRequest 0 | 不把 compile 当 execute；不声称 annotation 完成 |
| 3 | Processed reuse | `docs/assets/midterm_freeze_v1_1/03_processed_reuse.png` | 真实上传与 DataProfile UI；同日开发验收 | Processed 2638 × 1838；识别已有状态并最小补步 | 不声称“最新 marker revision”已结构化绑定 |
| 4 | RUN / UMAP | `docs/assets/midterm_freeze_v1_1/04_run_raw_umap.png` | 先前真实 Jupyter replay 截图；当前 replay 已重新生成同类 5 PNG | Raw 数值 pipeline 可执行并产生 UMAP；当前 replay 为 18/18 code cells、5 PNG | 截图中的旧 notebook id 不能当当前 run id；不声称 cell type annotation 完成 |
| 5 | Retrieval ablation | `docs/assets/midterm_freeze_v1_1/05_retrieval_ablation.png` | Dashboard 开发 campaign | 可展示 BM25/Dense/Hybrid/Scientific KG profiles 及原始分子分母 | `COMPLETE` 只表示开发运行结束，不代表独立 holdout 或最优模型 |
| 6 | Evidence provenance | `docs/assets/midterm_freeze_v1_1/06_evidence_provenance.png` | Dashboard source audit | 20 source records = 17 text available + 2 extraction failed + 1 metadata mismatch；来源和异常可追踪 | 不声称 100% 科学验证；metadata mismatch 不得并入有效证据 |

共同 provenance：代码基线 `02d4c131c8180ed163105b1388ea9d3318c85d21`，dirty worktree。#2、#3、#5、#6 是 2026-09-19 当前 sprint 保存资产；#1、#4 是保存的真实产品证据，current replay 通过最新 JSON、Notebook 与图文件重新验证，不把旧截图 id 伪装成当前 run。

当前 replay 的可直接引用图文件：

- Raw UMAP：`.sckg_exec/research-workspace/local-user/capability-notebooks/.sckg_notebook_artifacts/scanpy_core-9e76f6b3d974/05_umap_clusters_and_batch.png`
- Raw marker：`.sckg_exec/research-workspace/local-user/capability-notebooks/.sckg_notebook_artifacts/scanpy_core-9e76f6b3d974/04_ranked_marker_genes.png`
- Processed reused UMAP：`.sckg_exec/research-workspace/local-user/capability-notebooks/.sckg_notebook_artifacts/scanpy_core-5129135809c4/existing_umap.png`
