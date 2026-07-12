# scKG-Agent 2.0 执行环境资格审查报告

日期：2026-07-10  
Phase：Phase 0  
结论：`scRNAseq = import_qualified candidate`，不是 execution-enabled runtime  

## 1. 主机

```text
OS: macOS 14.6 (Build 23G80)
Architecture: arm64
Shell: zsh
Repository: /Users/lris/Desktop/scKG_agent/SCKG-Agent
Control command Python: /opt/anaconda3/bin/python 3.12.2 (base)
```

实际命令：

```bash
uname -m
sw_vers
which python
python --version
conda env list
```

`conda env list` 确认 `sckg_env` 与 `scRNAseq` 均真实存在。沙箱内 Conda 的 CPU 探测打印了 `sysctl ... Operation not permitted`，但环境列表和后续 `conda run` 均可用；该提示不是 Python package import failure。

## 2. 固定缓存配置

所有候选 worker smoke 使用：

```bash
NUMBA_CACHE_DIR=/tmp/sckg_numba_cache
MPLCONFIGDIR=/tmp/sckg_mpl_cache
XDG_CACHE_HOME=/tmp/sckg_xdg_cache
```

这些目录可写，用于避免把 NumPy/Numba/Matplotlib cache 权限问题误判为包问题。Phase 3 必须改为每个 run 独立 cache directory；当前 `/tmp` 配置只用于资格审查。

## 3. 控制平面 `sckg_env`

### 3.1 版本

```text
Python 3.10.20
streamlit 1.56.0
langgraph 1.1.6
neo4j 6.1.0
pydantic 2.12.5
numpy 2.2.6
pandas 2.3.3
```

### 3.2 成功命令

```bash
env NUMBA_CACHE_DIR=/tmp/sckg_numba_cache \
    MPLCONFIGDIR=/tmp/sckg_mpl_cache \
    XDG_CACHE_HOME=/tmp/sckg_xdg_cache \
    conda run -n sckg_env python -c \
    'import sys,streamlit,langgraph,neo4j,pydantic; ...'
```

结果：控制平面核心包导入成功，可用于 UI、LangGraph、Neo4j 与 Pydantic orchestration。

额外开发环境检查：

```bash
env NUMBA_CACHE_DIR=/tmp/sckg_numba_cache \
    MPLCONFIGDIR=/tmp/sckg_mpl_cache \
    XDG_CACHE_HOME=/tmp/sckg_xdg_cache \
    conda run -n sckg_env python -m pytest
```

结果：

```text
/opt/anaconda3/envs/sckg_env/bin/python: No module named pytest
```

因此 `sckg_env` 的 runtime imports 可用，但当前不是完整 development/test environment。没有自动安装 pytest。

### 3.3 失败命令与解释

```bash
conda run -n sckg_env python -c 'import sys,numpy,pandas,scipy'
```

结果：

```text
ModuleNotFoundError: No module named 'scipy'
```

```bash
conda run -n sckg_env python -c 'import anndata,scanpy,scrublet'
```

结果：

```text
ModuleNotFoundError: No module named 'anndata'
```

裁决：`sckg_env` 是可用的控制平面环境，但不是当前执行 worker。没有自动安装任何依赖。

## 4. 执行候选 `scRNAseq`

### 4.1 版本

```text
Python 3.12.2
numpy 2.2.6
pandas 2.3.1
scipy 1.16.0
anndata 0.11.4
scanpy 1.11.2
scrublet 0.2.3
scikit-learn 1.7.0
psutil 7.0.0
```

### 4.2 可复现命令

```bash
env NUMBA_CACHE_DIR=/tmp/sckg_numba_cache \
    MPLCONFIGDIR=/tmp/sckg_mpl_cache \
    XDG_CACHE_HOME=/tmp/sckg_xdg_cache \
    conda run -n scRNAseq python -c \
    'import sys,numpy,pandas,scipy,anndata,scanpy,scrublet,importlib.metadata as m;
     print("python="+sys.version.split()[0]);
     print("numpy="+numpy.__version__);
     print("pandas="+pandas.__version__);
     print("scipy="+scipy.__version__);
     print("anndata="+anndata.__version__);
     print("scanpy="+scanpy.__version__);
     print("scrublet="+m.version("scrublet"))'
```

该完整命令完成两次，均返回 exit code 0 和相同版本。额外的 `sklearn/psutil` smoke 也返回 exit code 0。

### 4.3 资格裁决

通过：

- 环境真实存在；
- Python 可启动；
- 基础科学包可导入；
- AnnData/Scanpy/Scrublet 可导入；
- 版本可读取；
- 固定可写 cache 下结果可重复。

未验证：

- 读取 `.h5ad`；
- Scrublet 初始化或真实分析；
- wrapper request/schema；
- input/output compatibility；
- artifact、hash、stdout/stderr；
- timeout/process tree；
- runtime/memory；
- 多 seed/config；
- scientific metrics。

因此环境状态只能是：

```text
available_candidate
import_qualified
```

不得写成：

```text
integration_tested
execution_gate_passed
enabled_for_execution
```

## 5. Neo4j 辅助连通性

沙箱内由于 DNS 限制，`Neo4jClient` 尝试 Aura 后降级到 `offline_graph`。在允许网络访问的只读复核中：

```text
provider=neo4j
RETURN 1 AS ok -> [{'ok': 1}]
```

未执行任何写操作。该结果证明当前 `.env` 的 Neo4j 连接配置可用，不证明图谱 schema、evidence quality 或所有业务 Cypher 正确。

## 6. Phase 1 复现要求

Phase 1 的 EnvironmentRegistry 应保存：

- environment name；
- Python/package versions；
- cache policy；
- qualification timestamp；
- import smoke command/result；
- integration status，初始必须为 false；
- `enabled_for_execution=false`；
- 与 ToolContract runtime version 的匹配状态。
