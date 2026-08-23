# scKG-Agent 2.0 执行安全模型

版本：0.4
状态：Phase 6 local trusted-wrapper model；Mac Beta clean-prefix release candidate
适用范围：当前本地控制平面、`LocalControlledExecutor` 与 Runtime Pack provisioning
主规约：`docs/DEV_SPEC_2.0.md`

> Phase 3 的执行器提供应用层控制，不提供操作系统级 sandbox。只有容器或独立受限 worker 落地并验收后，系统才可以声明 OS-level isolation。

## 0. 当前真实实现

当前已实现 `ToolContract`、wrapper allowlist、`LocalControlledExecutor`、fixed argv + `shell=False`、approved roots、run ownership、timeout/process-tree cleanup、artifact hash、Validator、bounded Repair、数据授权、plan-specific approval、取消和 retention audit。Scrublet、scDblFinder、Harmony 与 Scanorama 只有在固定 contract/environment pair 下具备条件资格；全局 `ExecutionPolicy` 默认仍为 `disabled`。

2026-07-18 新增 Runtime Pack control plane：

- 三个 task-family manifest 与 checksum 固定 lock；
- 缺环境路由到 `WAITING_ENVIRONMENT_APPROVAL`，不创建 `ExecutionRequest`；
- 环境 plan/approval 一次性、可撤销、过期并绑定 manifest digest；
- 安装命令来自 registry 固定 argv，用户与 LLM 不能提供 executable、shell command、channel 或 lock path；
- 环境安装 approval 不能复用为数据 execution approval；
- Runtime Pack 位于 `SCKG_HOME`，用户数据和 run/package 使用独立 workspace。

2026-07-19 clean-prefix 验收补充：控制平面由固定 Micromamba 2.8.1 archive SHA256、minimal explicit conda lock 和 hash-complete pip lock 重建，不依赖用户预装 Anaconda。安装脚本只有维护者固定 argv，未提供确认参数时不创建安装目录。三个 Runtime Pack 已在当前 Mac 禁止 legacy fallback 后完成真实安装、import smoke、卸载和重建；第二台干净机器复验仍未完成。

当前安全声明是：

```text
single-user / allowlisted-local-user trusted-wrapper execution
application-level path, process, approval and artifact controls
LocalControlledExecutor != OS sandbox
network_not_os_isolated
```

Agent/RAG 外发采用 `STRICT_OFFLINE / LOCAL_HYBRID / CLOUD_ASSISTED` gate。默认 `LOCAL_HYBRID` 且外部网络许可为 false；外部模型调用必须有脱敏 disclosure 和会话授权。矩阵、barcode、完整路径和上传文件正文禁止进入 payload，audit 只保存 hash。但是第三方 native worker 仍未由操作系统强制禁网，因此不能声称“绝无数据泄露”。

---

## 1. 信任边界

可信：

- 项目维护者审核过的 wrapper；
- 锁定版本的 execution environment；
- registry 中的 command builder；
- Pydantic/JSON validated ExecutionRequest；
- 本地单用户授权。

不可信：

- 用户输入文本；
- 用户提供的路径；
- LLM 生成的 command 或参数；
- 未注册 Python/R module；
- 下载后未审核的 package；
- 第三方库内部行为；
- 外部网络响应。

---

## 2. 已实现的应用层执行控制

- wrapper allowlist；
- structured request；
- argv list 与 `shell=False`；
- 参数 schema 和范围校验；
- approved input roots；
- fixed run directory；
- explicit output allowlist；
- timeout；
- process-tree termination；
- stdout/stderr/exit code；
- environment/version capture；
- file hash；
- peak-memory monitoring；
- residual process detection；
- trace and audit。

---

## 3. Phase 3 即使完成后仍不能保证什么

- 阻止第三方库读取任意本地可读文件；
- 阻止恶意 package；
- kernel/system-call isolation；
- 强制 CPU quota；
- 强制 memory limit；
- 系统级网络隔离；
- 防止 wrapper bug 进行任意 Python 文件操作；
- 支持不可信多租户。

因此：

```text
LocalControlledExecutor != SandboxExecutor
memory monitoring != memory enforcement
shell=False != process isolation
```

---

## 4. 路径策略

`DataRegistry`、`UserWorkspaceService` 与 `LocalControlledExecutor` 已执行 approved input root、ownership 和 `.sckg_exec` enforcement。

ExecutionRequest 只保存 artifact ID，不直接信任用户路径。控制平面必须：

1. 将输入解析到 approved input root；
2. 使用 `Path.resolve()`；
3. 验证 resolved path 仍位于允许 root；
4. 拒绝 symlink escape；
5. 将 probe 输出写入当前 run directory；
6. 不覆盖输入文件；
7. output path 由 executor 构造，不由 LLM 构造。

默认可写范围：

```text
.sckg_exec/runs/<run_id>/
```

---

## 5. Command 与环境安装策略

当前没有匿名、远程或公共 command API。以下规则是现行强制 gate。

禁止：

- `shell=True`；
- `bash -c` / `zsh -c`；
- 用户提供 executable；
- 用户提供完整 argv；
- eval/exec 动态执行代码；
- 自动 pip/conda/BiocManager 安装；
- LLM 生成临时代码后直接运行。

允许：

- registry 中固定 executable；
- registry 构造 argv；
- contract validated parameters；
- 固定 module entrypoint。

Runtime Pack provisioning 是“自动安装依赖”禁令的唯一受控例外，但必须同时满足：维护者版本化 manifest、detached signature、lock SHA256、lock URL host allowlist、空间与平台 gate、显式环境审批、`shell=False` 和 import smoke。它不接受 LLM 或用户拼接安装命令。控制平面 bootstrap 是发布方固定、digest 校验的本地安装脚本，只接受 `--accept-reviewed-install`，不能安装任意 channel/package。

---

## 6. Process 生命周期

本节已由 `LocalControlledExecutor` 和 cancellation tests 实现应用层控制；CPU/RAM hard enforcement 仍未实现。

Executor 必须：

- 创建独立 process group；
- 保存 PID/PGID；
- timeout 时先发送 graceful termination；
- grace period 后终止完整 process tree；
- 检查残留子进程；
- 将 cleanup 结果写入 ExecutionRun；
- 不因 timeout 删除 stderr 和失败 artifact。

macOS 和 Linux 的 process-tree 行为必须分别测试。

---

## 7. 资源模型

Phase 3：

| 资源 | 能力 |
| --- | --- |
| wall time | hard timeout |
| memory | psutil monitoring / soft budget |
| CPU | observation only |
| disk | application-level output directory |
| network | wrapper policy only |

超过 soft memory budget 时：

- 标记 warning 或 failure；
- 后续 run 可缩小 probe；
- 不声称进程在超过阈值瞬间被 OS 强制终止。

未来 Linux/container worker：

- cgroup memory limit；
- CPU quota；
- read-only root filesystem；
- mounted input/output；
- network disabled by default；
- non-root user；
- seccomp/AppArmor where available。

---

## 8. 网络策略

Phase 3 wrapper 设计上不需要网络。运行前后不主动下载包、模型或数据。

由于本地进程没有系统级网络隔离，界面和文档必须显示：

```text
network_not_os_isolated
```

多用户部署前必须迁移到可禁网的 worker。

---

## 9. 临时文件与失败保留

成功 run：

- 删除明确标记为 disposable 的大型中间文件；
- 保留 manifest、logs、metrics 和必要 artifact。

失败 run：

- 默认保留 stdout、stderr、request、contract snapshot 和 failure metadata；
- 临时数据按 privacy policy 和用户选择清理；
- cleanup action 写入 trace；
- 不自动删除用户输入。

---

## 10. 安全测试

现有回归已覆盖 executor、authorization、approval、ownership、cancellation、repair budget、Runtime Pack approval/digest 与 release privacy。容器级 isolation case 尚未通过，不得混入应用层验收结论。

至少覆盖：

- unknown wrapper；
- shell metacharacters in user text；
- path traversal；
- symlink escape；
- output path escape；
- invalid parameter type/range；
- timeout child process；
- residual process detection；
- missing dependency；
- package/network request attempt；
- unauthorized execution；
- repeated request fingerprint。

验收硬门槛：

```text
unauthorized execution = 0
path escape = 0
unknown wrapper execution = 0
repair budget violation = 0
```

---

## 11. 部署声明

当前只支持：

```text
single-user local trusted-wrapper execution
```

不支持：

```text
untrusted multi-user execution
public internet execution API
arbitrary uploaded code
unreviewed or user-defined package installation
```

达到容器隔离、鉴权、job quota、network policy 和审计要求后，才能讨论组内多用户执行服务。

---

## 12. 当前能防御与不能防御

### 当前能防御

- 未知 wrapper、固定 argv 外的 executable 和 shell command；
- input/output path traversal、symlink escape 与 cross-user artifact/run/package 访问；
- 未授权、审批 scope 不匹配、过期、撤销和 replay；
- timeout、process-tree cancellation 与有界 repair budget；
- Runtime Pack 未审批安装、manifest/lock digest 改变、平台/空间不满足；
- `STRICT_OFFLINE` 外部调用和 LOCAL_HYBRID 未授权外发；
- evidence gate 对 retrieval-only/frozen evidence 的主推荐越权；
- Subagent 默认关闭，输出不能修改 formal evidence 或 recommendation rank。

### 当前不能防御

- 审核过的第三方 Python/R package 在 native worker 权限内的未知行为；
- CPU/memory/disk 的 OS-level hard enforcement；
- 操作系统级文件系统和网络隔离；
- 恶意/被污染 package；
- 不可信远程多租户和公共服务隔离。

## 13. 多用户服务前的强制补项

1. LocalControlledExecutor 与 wrapper allowlist 全量安全测试；
2. authentication、authorization、job ownership 和 explicit approval；
3. 容器或独立 Linux worker；
4. read-only root filesystem、mounted input/output 和 non-root user；
5. network disabled by default 或可审计 network policy；
6. CPU/memory/disk quota；
7. secrets 不进入 run artifacts；
8. cancellation、timeout、process-tree cleanup 和 residual process audit；
9. privacy/retention policy；
10. 独立安全评审和 abuse tests。

在这些条件完成前，只能声明 `single-user local trusted-wrapper` 目标，不能开放公共 execution API。

## 14. Docker、轻量部署与生成代码边界

Docker/OCI 的价值是环境可复现、文件系统/网络/资源边界和跨机器分发，不等于安装体积天然更小。镜像层可复用并按任务下载，但 Python/R 生信依赖仍占磁盘；产品必须继续采用轻量控制平面加按需 Runtime Pack/OCI image，而不是把全部工具塞进一个镜像。

当前 Agent 的代码运行能力严格限定为：生成或读取受控 synthetic fixture，调用 allowlist 中维护者审核的固定 wrapper，并经过 contract、approval、executor 和 validator。当前**不执行 LLM 任意生成的 Python、R 或 shell 代码**，`LocalControlledExecutor` 也不能改名为 sandbox。

Research Chat 可以展示维护者版本化且 smoke-tested 的 `WorkflowCodeBundle`，供用户在自己的受控环境中复现。该导出脚本不等于产品内执行：它不能创建 `ExecutionRequest`、不能继承环境安装 approval、不能访问已登记 artifact，也不能被 LLM 动态改写后自动送入 `LocalControlledExecutor`。外部 DeepSeek 只参与用户显式授权后的文本综合，workflow recipe 选择、digest 和 smoke 状态均由本地确定性服务提供。

未来只有实现独立 Container Runner 后，才能评估受限生成代码执行。最低边界为：

```text
固定 image digest + non-root
read-only input + isolated writable output
network=none
CPU/RAM/disk/time/process limits
no host socket / no arbitrary mount / no package install
explicit plan-specific approval
stdout/stderr/artifact hash/lineage audit
cancel + process-tree cleanup
```

即使本地部署也不能宣称绝对无泄露：外部 LLM、远程 embedding、远程 Neo4j、允许联网的依赖或用户主动共享目录仍可能外发信息。只有 `STRICT_OFFLINE`、系统级禁网和隔离 runner 同时成立时，才可给出更强的本地隐私声明。
