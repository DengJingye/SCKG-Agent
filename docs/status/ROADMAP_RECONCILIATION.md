# Roadmap Reconciliation

| 原始 Phase | 实际完成内容 | 完成状态 | 偏离原因 | 仍缺内容 | 下一合法阶段 |
| --- | --- | --- | --- | --- | --- |
| Phase 0 | 规约、评测协议、安全基线和环境审查 | completed | 无 | 动态文档需随实现维护 | Phase 1 |
| Phase 1 | Execution models、AnnDataProfiler、Scrublet contract、environment registry | completed | 无 | 无 | Phase 2 |
| Phase 2 | dry-run plan compiler、deterministic Router | completed | Execution RAG gold eval 未与编译器同步完成 | execution-oriented RAG 统一评测 | Phase 3A-E |
| Phase 3A-E | Scrublet wrapper、Executor、Validator、多配置工程评估、Level 2 package | completed | 工程资格拆成 3A 与 3A-E 实施，但仍属于原 Phase 3A-E | 无 | Phase 3A-S / Phase 3B / Phase 4 |
| Phase 3A-S | GSE108313 HTO 正交标签 scientific pilot | completed_as_pilot | 只使用一个公开数据集 | 多数据集 external evaluation | Phase 3B / Phase 6 evaluation |
| Phase 3B | Scrublet + scDblFinder 双工具闭环、跨工具 Pareto、同 split scientific pilot | completed | 实施时曾称 Phase 5A/5B/5C，现归回原 Phase 3B | 更广外部科学验证 | Phase 4 / Phase 6 evaluation |
| Phase 4 | Orchestrator、bounded Repair Loop、CandidateEvaluation、Decision Engine、repair lineage | completed | 实施时细分 qualification/engineering/scientific 子步骤 | 更完整 repair gold set 与 baseline | Phase 6；Phase 5 为独立分支 |
| Phase 5 | Harmony 2.0.0 + Scanorama 1.7.4 独立 CPU 环境、contract/wrapper/Validator、12+2 engineering qualification、scIB pancreas scientific pilot、跨工具 Pareto、Level 2 package 与 ActionBundle 晋升 | completed | Phase 6 无真实试用参与者时恢复原 Phase 5 工程主线；未改 Phase 编号 | 多数据集 external evaluation；用户执行仍由全局 disabled policy 阻断 | Phase 6 真实组内试用 |
| Phase 6 | 统一授权、plan-specific approval、ownership、受限本地执行、取消、Streamlit UI、双轨 baseline、trace/demo/failure queue 与匿名 telemetry | trial_ready | 授权和本地执行先于统一 baseline 落地；现已完成工程收口 | 3 至 5 人真实组内试用与关键 blocker 复核 | Phase 6 |
| Phase 7 | Phase 7 服务化/MCP 尚未开始 | not_started | 本地权限和评测尚未完成稳定验收 | service API、read-only MCP、worker/job queue、部署安全 gate | Phase 7（仅在 Phase 6 稳定后） |
| 非正式 Phase：Release Hardening | Release Hardening 不是新的正式 Phase | not_a_formal_phase | 只能作为现有 Phase 的发布验收活动 | 按目标 Phase 记录回归、文档、打包和发布检查 | 不得创建新正式 Phase |
