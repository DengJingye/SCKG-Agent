# plan_v1/G0：当前快照的交付与工程验收

本页对应2026-10-18开发手册的 G0，和旧 `WORKBENCH_DEVELOPMENT.md` 的关卡编号分开管理。历史验收保持原有版本和范围。

本次从 `codex/workbench-workflow-provenance` 的 `3d6c49142f392a850ba19783b3a3d948fb91dfe4` 开始。旧科研分支为 `a3cb79fa9f78d578f819c8711708dcf8c1b2c9eb`；两者 ahead 13 / behind 29。优先复用当前工作台、任务台账与既有进程监督器，不整体合并旧科研分支。

## 本次补齐的交付入口

1. `release/locks/workbench-osx-arm64-py312.requirements.lock`：55项产品依赖的完整锁，复用现有开发交付资产，原字节 SHA256 为 `0b5af7b59a9a49347679a3faa7a1a431b023ab6aeae7b3339cd2a23d352b3f05`。
2. `release/locks/workbench-dev-osx-arm64-py312.requirements.lock`：复用产品锁，再加入 pytest、pluggy、iniconfig。合计58项，不重复定义已在产品锁中的 packaging。
3. `scripts/verify_g0.py`：顺序执行依赖合同、轻量 smoke、当前工作台全部测试文件、完整页面 AppTest；复用已有监督器、JUnit解释器、依赖检查器和UI探针。
4. `.github/workflows/workbench-g0.yml`：在 macOS ARM64 的全新虚拟环境安装锁定依赖并运行上述检查，失败时也上传日志和收据。

依赖锁目前限定 CPython 3.12、macOS 14+、ARM64。NumPy的已冻结wheel要求 macOS 14+；不把这份哈希锁作为 Linux、Windows或Intel Mac的通用安装文件。科学拟合环境仍是单独的 runtime pack，不在这份产品锁中。

## 本地执行

复用已合格环境时不必重复安装。需要验证全新安装时，使用全新目录：

```sh
python3.12 -m venv .venv-workbench
.venv-workbench/bin/python -I -m pip install \
  --only-binary=:all: --require-hashes --no-deps \
  -r release/locks/workbench-dev-osx-arm64-py312.requirements.lock \
  --report install-workbench01.json
.venv-workbench/bin/python -I -B scripts/verify_g0.py \
  --python .venv-workbench/bin/python --output validation-run-g0-01
```

环境目录、安装报告和验收输出请选未使用的名称；保留原失败记录。安装后启动仍是：

```sh
.venv-workbench/bin/python -m streamlit run workbench_app.py --server.address 127.0.0.1
```

启动空工作台不需要模型凭据。该流程不会安装科学拟合环境、获取论文全文、调用模型或自动发布知识。

## 收据怎样判定

新入口使用严格门槛：每个选中的测试文件必须实际产生用例，失败、错误或任何跳过都不能通过；程序退出0但缺少JUnit/报告也不能通过。依赖检查必须同时有隔离/版本、实际导入探针和 pip check 成功证据。UI必须完成页面检查、无渲染错误，并保持只读交互阶段的工作区内容不变。

旧验收入口保留原有可选跳过语义，新入口不会改写历史结果。新增测试专门覆盖“成功退出但无报告”“报告自称成功但缺少证据”“部分跳过”“资源不足”和“重复输出目录”等失败场景。

每个运行通道限120秒、父子进程组采样RSS限1.5 GiB；开始下一通道前重新读取可用内存，要求额外保留 `max(2 GiB, 总内存的25%)`，并计入256 MiB监督器余量。资源不足返回3并保存 `deferred_resource`，不当作产品测试失败或通过。失败返回1，通过返回0。RSS采样与应用离线配置不等于操作系统硬隔离。

`receipt.json` 保存基线提交、工作区改动状态、相关源码/合同/锁文件哈希、每个通道命令和资源、退出码及实际JUnit计数；同一运行前后源码必须一致。工作区有未提交改动时，提交SHA只是基线，具体受测内容以哈希清单为准。

即使该入口通过，也只表示当前工程选择与AppTest通过。它不会单独把完整 G0 标成通过：仍需确认新安装的实际来源/报告、目标系统启动、CI实际运行和历史报告索引。AppTest不替代真实浏览器旅程；科学执行与科学质量属于后续关卡。

## CI范围

使用只读仓库权限，不保留checkout凭据；安装阶段固定版本、wheel类型和哈希；整个任务15分钟上限；完整结果目录在失败时仍上传，保存14天。不会使用生产凭据、修改知识库或运行真实科学任务。

runner选择依据[GitHub官方运行器说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。两个官方Action固定到已核验的Node24提交：[checkout v5.0.0](https://github.com/actions/checkout/tree/08c6903cd8c0fde910a37f88322edcfb5dd907a8)、[upload-artifact v6.0.0](https://github.com/actions/upload-artifact/tree/b7c566a772e6b6bfb58ed0dc250532a479d7789f)。本地配置校验通过不代表GitHub上的任务已经执行。

首次CI在准备Python阶段失败：[运行39125057954](https://github.com/DengJingye/SCKG-Agent/actions/runs/39125057954)。官方setup-python版本清单没有3.12.13的darwin/arm64构建，因此该次没有执行产品测试。后续复用既有Micromamba 2.8.1归档SHA256和17项显式bootstrap锁，继续使用与本机相同的Python 3.12.13；不改Python版本以取得通过。bootstrap锁原字节SHA256为 `e390621d620fdfea6b20bf9ad3894beac03c3c6bd714fc3007e01fe36f444cfb`，包使用原显式URL及MD5、TLS下载；这不是给conda包新增SHA256或签名认证。证据目录提前建立，Python准备失败时仍保留任务状态和安装日志。

## 保留的边界

- 当前实际wrapper仍只有Scrublet；注册名不等于已实现方法。
- Scrublet仍是≤25 MiB、≤1,000细胞、≤10,000基因的工程预览；原数据、来源门和产物验收不变。
- 不迁移旧评测成绩、不调整实验预算、不扩大科学适用范围、不引入新Agent框架。
- 本轮没有把候选知识升级为人工审核或正式发布状态。
