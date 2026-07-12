# scKG-Agent 2.0 执行安全模型

版本：0.2  
状态：Phase 0 current-state threat model；`LocalControlledExecutor` not implemented  
适用范围：当前控制平面，以及未来 `LocalControlledExecutor` 的最低安全要求  
主规约：`docs/DEV_SPEC_2.0.md`  

> Phase 3 的执行器提供应用层控制，不提供操作系统级 sandbox。只有容器或独立受限 worker 落地并验收后，系统才可以声明 OS-level isolation。

## 0. 当前真实实现

Phase 0 没有 `execution/`、`contracts/`、`LocalControlledExecutor`、wrapper allowlist、job manager、process-tree cleanup 或 execution run directory。当前没有任何可供用户授权的真实生信执行入口。

现有 `core.agent_runtime.ToolExecutor` 只提供：

- 注册 Python 函数；
- 可选 Pydantic 参数校验；
- tool-call 次数预算；
- 重复 fingerprint 阻断；
- 函数结果和 latency trace。

它不提供：

- shell/argv 执行控制；
- 文件路径隔离；
- timeout 和进程树终止；
- Conda/R/Python worker 环境选择；
- 文件 hash 和 artifact manifest；
- memory/network/filesystem isolation。

因此当前安全声明只能是：

```text
no external bioinformatics execution surface implemented
offline/online Agent function calls are application code in the control process
ToolExecutor != LocalControlledExecutor
no sandbox is implemented
```

现有 Agent/RAG 路径仍可能调用 Neo4j、LLM 或 embedding API，取决于 `.env` 与 offline flags；这与未来 execution worker 的“wrapper 不主动联网”不是同一个网络边界。

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

## 2. Phase 3 目标能力（当前尚未实现）

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

以下是 `LocalControlledExecutor` 的目标要求。Phase 0 当前没有 approved input root 或 `.sckg_exec` enforcement。

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

## 5. Command 策略

当前控制平面没有用户可调用的外部生信 command API。以下规则在 Phase 3 实现时成为强制 gate。

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

---

## 6. Process 生命周期

本节当前为 design requirement；尚无实现或测试结果。

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

这些是未来 controlled executor 的验收测试。Phase 0 的 38 个测试没有执行这些 case，不得标记为通过。

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

Phase 3 只支持：

```text
single-user local trusted-wrapper execution
```

不支持：

```text
untrusted multi-user execution
public internet execution API
arbitrary uploaded code
remote package installation
```

达到容器隔离、鉴权、job quota、network policy 和审计要求后，才能讨论组内多用户执行服务。

---

## 12. 当前能防御与不能防御

### 当前能防御

- `ToolExecutor` 对同一 node/tool/args fingerprint 的重复调用；
- `ToolExecutor` 的 tool-call 迭代预算；
- 未注册 Python tool name；
- 已接 Pydantic input model 的类型错误；
- evidence gate 对 retrieval-only/frozen evidence 的主推荐越权；
- Subagent 默认关闭，输出不能修改 formal evidence 或 recommendation rank。

### 当前不能防御

- 任意第三方 Python 函数在控制进程内的文件、网络或系统行为；
- 用户路径 traversal 或 symlink escape，因为 execution path policy 尚不存在；
- 外部进程 timeout、child process leak、CPU/memory/disk exhaustion；
- 操作系统级文件系统和网络隔离；
- 恶意/被污染 package；
- 多租户身份、job ownership、quota 和数据隔离。

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
