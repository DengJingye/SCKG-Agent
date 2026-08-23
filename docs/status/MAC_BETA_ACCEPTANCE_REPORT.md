# Mac Apple Silicon Beta 验收报告

日期：2026-07-19
状态：`RELEASE_CANDIDATE`
范围：当前 Apple Silicon Mac 的隔离 clean-prefix 演练，不等同于第二台干净机器验收

## 1. 验收结论

在全新 `SCKG_HOME`、禁止 legacy Conda fallback 的条件下，以下链路已真实通过：

```text
pinned Micromamba bootstrap
-> control-plane conda/pip lock
-> STRICT_OFFLINE cold start
-> three signed Runtime Packs
-> import smoke
-> remove
-> rebuild from lock
-> release/privacy audit
```

技术 gate 已通过，但仍缺第二台干净 Apple Silicon Mac 的独立复验，因此不能标记 `clean_machine_accepted`。

## 2. 控制平面

- Micromamba：`2.8.1`，固定版本 URL 与 SHA256；不使用 `latest`。
- Python：`3.12.13`，由 explicit conda lock 重建。
- Python 依赖：87 个锁定组件，pip 安装使用 `--require-hashes --no-deps`。
- 首次控制平面加核心发布内容：`815,732,184 bytes`，低于 1 GiB gate。
- 冷启动：无 Runtime Pack、无 Neo4j、无外部模型时通过。
- 冷启动能力：1,847 工具本地图谱、sparse retrieval、AnnData profile、dry-run plan。
- 外部网络调用：0；`ExecutionRequest`：0。

## 3. Runtime Pack 实测

| Pack | 首次安装 | 缓存增长 | 安装逻辑大小 | 卸载后重建 | 最终状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| `doublet-python` | 115.68 s | 1,071,531,822 B | 814,096,612 B | 35.19 s | ready |
| `doublet-r` | 71.26 s | 1,786,955,557 B | 1,403,661,803 B | 34.87 s | ready |
| `batch-cpu` | 46.56 s | 增量 140,593 B | 815,237,203 B | 39.26 s | ready |

`batch-cpu` 复用了前序 Pack 的 Conda cache，因此其增量缓存不能解释为独立冷下载大小。首次尝试因原 pip lock 未显式包含 Scanorama 的 `intervaltree` 等依赖而失败；失败记录和日志保留。修复后的 `2026.07.2` manifest 已补齐 `fbpca/geosketch/intervaltree/sortedcontainers`、更新 lock SHA256 并重新使用维护者 Ed25519 key 签名，随后安装和重建通过。

## 4. 发布审计

- ZIP：`3,731,162 bytes`。
- 解压前候选文件内容：`33,327,037 bytes`。
- 文件：159。
- SBOM 锁定组件：481。
- release privacy issues：0。
- 不包含 dataset、`.sckg_exec`、PDF、`.env`、私钥、legacy embedding 或完整本地路径。
- bootstrap/launcher 在 ZIP 中保留可执行权限。

## 5. 未通过项

1. 尚未在第二台干净 Apple Silicon Mac 独立安装并复验。
2. 真实组内试用人数仍为 0，Phase 6 仍是 `PHASE6_TRIAL_READY`。
3. Native Trusted Runner 仍为 `network_not_os_isolated`。
4. Annotation、Container Runner、WSL2 和 MCP 均未因本次演练而提前启动。

完整机器级 JSON、安装 stdout/stderr、失败 lineage 和逐次 telemetry 保存在本地 `.sckg_exec/acceptance/`，不进入发布包。
