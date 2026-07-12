# scKG-Agent 2.0 测试基线

日期：2026-07-10  
Phase：Phase 0  
工作目录：`/Users/lris/Desktop/scKG_agent/SCKG-Agent`  

## 1. 基线命令

```bash
python -m pytest
```

使用仓库默认 pytest discovery；仓库没有 `pytest.ini`、`pyproject.toml` 或 `setup.cfg` 测试配置。

## 2. 运行环境

```text
platform: darwin
architecture: arm64
Python: 3.12.2
pytest: 7.4.4
pluggy: 1.0.0
rootdir: /Users/lris/Desktop/scKG_agent/SCKG-Agent
plugins: langsmith 0.3.45, anyio 4.2.0
```

## 3. 结果

### 3.1 修改前基线

```text
collected: 38
passed: 38
failed: 0
skipped: 0
xfailed/xpassed: 0
test time: 7.21s
command wall time: 8.59s
warnings: 1
```

失败测试：无。  
失败原因：不适用。  
为建立基线而做的测试修复：无。

### 3.2 Phase 0 修改后完整回归

同一命令再次运行：

```text
collected: 38
passed: 38
failed: 0
skipped: 0
test time: 3.32s
command wall time: 4.49s
warnings: 1
```

最终基线以本次结果为准。测试集合没有变化。

### 3.3 `sckg_env` 交叉检查

```bash
env NUMBA_CACHE_DIR=/tmp/sckg_numba_cache \
    MPLCONFIGDIR=/tmp/sckg_mpl_cache \
    XDG_CACHE_HOME=/tmp/sckg_xdg_cache \
    conda run -n sckg_env python -m pytest
```

结果：exit code 1，`No module named pytest`。这不是测试失败，而是候选控制平面环境缺少 test runner。没有自动安装依赖；当前正式基线使用 base Python 3.12.2。

## 4. 测试分布

| 测试文件 | 数量 | 主要证明范围 |
| --- | ---: | --- |
| `test_algorithm_representation_v2.py` | 3 | source metadata、legacy 降权、coverage penalty |
| `test_core_tool_source_manifest.py` | 3 | README source manifest/fetch helper |
| `test_dashboard_services.py` | 5 | trace/KG summary、coverage/registry/demo loading |
| `test_decision_workflow_demo.py` | 1 | plan-only demo boundary |
| `test_doublet_recovery_demo.py` | 6 | metadata/PDF candidate 与 filename 防错 |
| `test_literature_source_coverage.py` | 3 | short text、bad DOI override、extract failure 分类 |
| `test_pdf_download_candidates.py` | 1 | bad candidate quarantine |
| `test_pdf_ingest.py` | 2 | recursive discovery 与 quarantine skip |
| `test_reflection_memory.py` | 1 | private memory 不获科学权威 |
| `test_source_registry.py` | 4 | source-level 去重、mismatch、extract repair |
| `test_subagent_runtime.py` | 1 | subagent 默认关闭且只读 |
| `test_trace_context.py` | 1 | JSONL trace 与 stage 顺序 |
| `test_workflow_decision.py` | 3 | plan-only response、missing retrieval、task inference |
| `test_workflow_eval.py` | 4 | workflow eval、synonym、zero value、evidence boundary |

## 5. Warning

```text
UserWarning: Field "model_name" has conflict with protected namespace "model_".
```

来源：Pydantic 2.x model field discovery。当前不影响测试结果。Phase 1 新建 canonical models 时不应复制这个命名问题；旧模型可在独立兼容改动中处理，不能为消除 warning 放宽 schema。

## 6. 基线所证明的内容

- 当前 source registry/PDF 防错逻辑通过既有测试；
- retrieval-only 与 formal evidence boundary 的关键回归通过；
- plan-only workflow demo 能保持不可执行边界；
- trace、dashboard service、private memory 和 disabled subagent 的基础行为通过；
- Algorithm Representation v2 不会把 legacy embedding 提升为主推荐证据。

## 7. 基线没有证明的内容

- `agent/workflow.py` 完整 LangGraph 在线/离线运行；
- `core.agent_runtime.ToolExecutor` 的所有预算与异常路径；
- live Neo4j business queries；
- LLM provider 与在线 prompt 行为；
- MCDM、report auditor 的完整主链；
- AnnData 读取和 matrix state 判断；
- Scrublet 真实执行；
- LocalControlledExecutor、Validator、Repair、artifact hash 或复现包；
- 任何生物学准确率或科学有效性。

## 8. Phase 0 最小代码修改回归

Phase 0 只修正旧架构诊断标签：

```text
recursive_centralized_parent_agent
-> bounded_centralized_parent_agent
```

涉及 `agent/traced_runner.py`、`engine/workflow_decision.py`、`app.py` 和相关 docstring。该修改只改变 trace/UI 的架构文字，不改变路由、证据、排序或执行行为。

最终完整回归为 38 passed、0 failed、0 skipped、1 warning，3.32s。
