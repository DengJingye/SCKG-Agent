# Phase 6 答辩 Demo 指南

1. 保持默认 `ExecutionPolicy=disabled`，先运行 `python eval/run_phase6_baselines.py`。
2. 运行 `python scripts/run_phase6_defense_demo.py`。
3. 打开最新 `.sckg_exec/demos/phase6-defense-*/demo_summary.json`。
4. 展示 success case 的 profile、plan、approval、2 次执行、validation、decision 和 Level 2 package。
5. 展示 repair case 的原始失败、RepairProposal、参数变更、parent/new run lineage 和修复后 validation。
6. 展示 blocked case 的 approval parameter hash mismatch 与 `execution_request_count=0`。
7. 最后展示 `trace_audit.json`：适用 stage completeness 为 1.0，四项安全 violation 均为 0。

Demo 只使用 synthetic fixture，不调用外部 LLM/API，不执行新生成代码，也不证明真实生物学性能。
