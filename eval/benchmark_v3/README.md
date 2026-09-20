# V3 evaluation：当前交付与复现

当前状态：**READY_FOR_00_REVIEW**。仅完成离线纠错、14题审核草稿、评分规约和运行合约。
没有 Gold、正式 evaluation split、LLM回答、lane运行或Agent Gain；没有更改05/06/07。

## 审核入口

- `development_review_packet.md`：K8/O4/W2，10个家族；原始来源与新增上下文并排。
- `development_scenarios.jsonl`：机器可读草稿；origin、track、coverage、split分别存储。
- `development_coverage_review_template.jsonl`：45个科学事实×知识源待审格子，不是45个新问题。
- `coverage_review.py` / `review_coverage.py`：搜索与人工判定隔离、支持ID与excerpt校验、两人审核聚合。
- `scoring_protocol.md`：评分分母、模型映射、失败归因、机制对照和后续授权门槛。
- `run_manifest.json` / `evaluation_lane_manifest.json`：未运行计划和静态冻结的07实现。
- `runtime_receipt.schema.json`：以后每次真实调用的完整prompt/evidence/request/usage留档合约。

## 纠错声明

旧 Phase2.2 脚本固定产生的20个 `000` 全部撤回，当前20条均为unknown。
这不是“知识库无覆盖”的结论。更早来自ToolContract的`100`同样无效。
旧报告/结果可在commit `810ed0853c763c0a497f74100f7bb8d47ed2e4e8` 查验。
所有原始56条seed（48原pilot+8 paper/notebook）和原clustering保持不变。
`run_candidate_audit.py` 的历史生成入口已禁用，以免覆盖修正后的资料；不删除采集成果。

实际request有动态top_k、search_catalog和supplemental路径。RAG/Legacy inventory包含
800 evidence + 1847可条件检索catalog；10个quarantined formal chunks不能作present支持。
catalog只支持自身权限内的discovery metadata，不是独立全文或执行证据。
Approved KG hash仍为 `06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4`。

## 离线命令

在本worktree根目录运行（不联网、不跑模型或单细胞计算）：

```bash
/opt/anaconda3/bin/python eval/benchmark_v3/run_lane_alignment_audit.py
/opt/anaconda3/bin/python -m eval.benchmark_v3.build_development_review
/opt/anaconda3/bin/python -m eval.benchmark_v3.build_development_review --check
/opt/anaconda3/bin/python -m eval.benchmark_v3.review_coverage --scenarios eval/benchmark_v3/development_scenarios.jsonl --reviews eval/benchmark_v3/development_coverage_review_template.jsonl
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/anaconda3/bin/python -m pytest -q eval/benchmark_v3/test_review_infrastructure.py tests/test_evaluation_models.py tests/test_open_world_evaluation.py tests/test_evaluation_evaluators.py
git diff --check
```

前两个命令只重建本目录内列明的派生文件；历史原件可用git恢复。
`--check`只读校验。模板重建会清空模板中的人工编辑，所以审核必须另存副本。
`review_coverage --output NEW_PATH`只创建新报告，不覆盖已有审核成果。

每个coverage cell的`reviews`分别由两人填写：`reviewer_id/reviewed_at/status/rationale`。
present的`supports`每项需`record_id/evidence_id/excerpt/scope_and_version/applicability_reason/entailment_reason`；
absent的`negative_search`需`search_scope/query_variants/record_inventory_digest/related_results/insufficiency_reason`。
related_results每项需`record_id/insufficiency_reason`；无相关结果填[]。
分歧用独立第三人的`resolution`，除上述字段外需`role=00-adjudicator`。
细胞级的存储status无效，工具只从reviews重算；scenario需求拆分审核后才把
`requirements_review_status`设为adjudicated。没有通过这个门槛，summary仍unknown。
科学参考答案和Gold审核另走`human_review`，覆盖审核不能自动升级为Gold。

## 未完成且有意设置的门槛

00需组织双人科学审核、冻结独立来源span/环境和W参考结果，裁定条件对与O澄清清单。
之后才校准科学评分器、构造剩余36题、审split、冻结模型/预算、实现并验收运行receipt采集，
以及同证据/关闭显式scope过滤的评测专用机制对照。模型、预算和授权未指定时不自行选择并开跑。
当前synthetic测试通过只说明工程边界正常，不说明科学评分器已校准或KG已有收益。
