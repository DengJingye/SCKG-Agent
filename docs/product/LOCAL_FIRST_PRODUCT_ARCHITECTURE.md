# scKG Local Research Workbench

状态：Mac Apple Silicon Beta release candidate（当前机器 clean-prefix passed；第二台干净 Mac pending）
更新时间：2026-07-19
主规约：`docs/DEV_SPEC_2.0.md`

## 1. 产品定义

scKG-Agent 的首个落地产品是本地优先的研究工作台，而不是携带全部生信依赖的在线聊天站或巨型安装包：

```text
轻量本地控制平面
+ 本地 Catalog/Decision Graph 与 sparse RAG
+ 按任务族安装的 Runtime Pack
+ 环境安装审批与数据执行审批
+ 可选外部 LLM
+ 未来可选只读 MCP
```

浏览 1,847 个工具不要求安装 1,847 个环境。大多数工具保持 `catalog_only` 或 `planning_only`；只有维护者完成 contract、wrapper、环境和验证闭环的固定组合才能进入 Runtime Pack 和 execution allowlist。

## 2. 四类资产

| 资产 | 默认位置 | 是否进入 Git/发布包 |
| --- | --- | --- |
| 控制平面代码、schema、manifest、lock | 仓库/核心发布包 | 是 |
| 压缩 KG、受控 chunk、contract/index | 核心发布包 | 是 |
| Runtime Pack 与 package cache | `~/.sckg/` 或 `SCKG_HOME` | 否 |
| 用户数据、run、dataset、package | 用户 workspace / `.sckg_exec/` | 否 |

当前 release manifest 的候选核心内容为 33,327,037 bytes，ZIP 为 3,731,162 bytes；`.sckg_exec/`、scientific pilot 数据集、PDF、历史 run、`.env` 与 legacy algorithm embedding 均被排除。固定 control-plane bootstrap 首次占用加核心内容为 815,732,184 bytes，低于 1 GiB gate；核心发布上限固定为 500 MiB。

## 3. Runtime Pack

当前三个 versioned pack：

| pack | 任务族 | 工具 | Mac legacy environment |
| --- | --- | --- | --- |
| `doublet-python` | Doublet Detection | Scrublet 0.2.3 | `scRNAseq` |
| `doublet-r` | Doublet Detection | scDblFinder 1.24.0 | `scDblFinder-R` |
| `batch-cpu` | Batch Integration | Harmony 2.0.0、Scanorama 1.7.4 | `sckg-batch-cpu` |

每个 manifest 绑定平台、架构、工具、环境、固定 wrapper、explicit conda lock、可选 pip lock、SHA256、下载/安装估算、channel、license、安装域名、运行网络策略和 qualification 状态。manifest 还必须通过仓库内维护者 Ed25519 公钥验证 detached signature；本机私钥位于 `~/.sckg/maintainer-keys/`，不进入 Git 或发布包。现有 Conda 环境通过 compatibility resolver 复用；新机器安装到 `~/.sckg/runtime-packs/`，不修改仓库。

安装状态机：

```text
MISSING
-> WAITING_ENVIRONMENT_APPROVAL
-> INSTALLING
-> VERIFYING
-> READY
-> WAITING_EXECUTION_APPROVAL
-> RUNNING
```

用户只能批准维护者版本化 manifest。LLM、聊天输入和 UI 都不能提交 executable、shell command、channel、lock 路径或输出目录。manifest digest、空间、平台或 import smoke 不满足时保持 blocked。

环境审批与执行审批完全独立。安装成功不授予数据读取权；执行仍绑定 `user + artifact + plan + contract + environment + parameter_hash + expiration`。

## 4. 本地隐私

三档模式：

```text
STRICT_OFFLINE
LOCAL_HYBRID（默认）
CLOUD_ASSISTED（显式选择）
```

默认情况下，DataProfiler、Router、ToolContract、Approval、Validator、KG 与 sparse retrieval 在本地运行，外部网络许可为 false。使用外部模型前必须产生脱敏 disclosure，并取得本次或本会话授权；audit 只记录 disclosure hash、字段名、大小和删减项，不保存外发明文。

以下内容禁止进入外部模型 payload：表达矩阵、barcode/cell ID、完整路径、artifact path 和上传文件正文。核心代码不能宣称“本地部署绝无泄露”：当前 Native Trusted Runner 是应用层受控进程，不是 OS sandbox，也没有强制系统禁网。

## 5. 使用入口

```bash
python -m cli.sckg doctor
python -m cli.sckg packs list
python -m cli.sckg launch
```

CLI 与 Streamlit `Runtime Packs` 页面调用同一个 registry、approval service 和 manager。页面渲染不安装环境；安装必须先生成 plan，再输入 digest 绑定的确认文本。

发布检查：

```bash
python scripts/build_local_release.py --check
python scripts/build_local_release.py
```

## 6. 平台顺序

1. Mac Apple Silicon Beta：当前 Release Candidate；本机 clean-prefix install/remove/rebuild 已通过，第二台干净 Mac 复验待完成；Native Trusted Runner 明确 `network_not_os_isolated`。
2. Windows WSL2：尚未实现；使用 Linux worker，不维护原生 Windows R/Python 生信环境。
3. Linux/HPC：尚未实现；复用 `linux-64` lock，后续适配 OCI/Apptainer/Slurm worker。

容器 runner 未实现。只有完成只读输入挂载、独立输出、非 root、`network=none` 和 CPU/RAM/disk/timeout enforcement 后，才能声明 OS-level isolation。

## 7. MCP 边界

MCP 是可选接口，不是产品本体，当前尚未实现。正式 Phase 7 首版只允许只读 stdio capability：catalog 查询、evidence 搜索、contract 读取、已登记 artifact 画像、dry-run plan 和 execution status。任何 execution request 仍必须回到本地工作台完成 plan-specific approval。

禁止暴露：`run_shell`、`execute_code`、`install_package`、formal evidence 写入和 trusted graph 写入。

## 8. 下一验收

- 已完成：在当前 Mac 的隔离 `SCKG_HOME` 中，无 Runtime Pack、Neo4j 和外部模型完成 KG/sparse RAG/profile/dry-run cold smoke；
- 已完成：固定 Micromamba/control-plane lock，以及三个 Pack 的 install/import/remove/rebuild；
- 已完成：可配置 `SCKG_HOME`、6 GiB gate、SBOM/license inventory 与 release privacy audit；
- 待完成：在第二台干净 Apple Silicon Mac 对同一 release archive 独立复验；
- 待完成：3 至 5 位真实组内试用。两项完成前不加入 annotation pack，不提前实现 WSL2、容器或 MCP。
