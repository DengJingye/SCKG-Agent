# Midterm P0 + C6 + C8 freeze v1.1

Portable manifest：`data/evaluation/midterm_freeze_v1_1/manifest.json`

Pre-freeze HEAD：`02d4c131c8180ed163105b1388ea9d3318c85d21`

Scope：P0、C6、C8

本 freeze 只复制并脱敏已完成的事实源，不重新运行 C6，不修改 retrieval SUT、Scientific KG、corpus、gold、weights 或治理配置。原始本地 audit/development 目录保持未跟踪且未改写；`.h5ad`、model binary、runtime cache 和 secret 均不进入提交。

冻结内容包括：真实数据输入闭环、当前 PBMC replay、36-case Agent selection、Metrics Snapshot v2、6 张截图、C6 固定消融引用与 C8 Dashboard provenance 统计。Raw/Processed replay 的 annotation terminal 继续报告 `BLOCKED`，没有改写成成功。

验证记录：focused tests 189 passed；final core revalidation 56 passed；源 artifact integrity 8/8；`git diff --check` PASS。

首次 portable harness v1 因仓库外 Dashboard source 的相对路径计算失败而保留为 `data/evaluation/midterm_freeze_v1/INVALID.json`。v1.1 只修复路径身份序列化，未改变科学结果。
