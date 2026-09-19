"""Evidence & RAG UI; all measurements are read-only artifact projections."""
from pathlib import Path

import streamlit as st

from observability.dashboard.evidence_data import (
    EvidenceDashboardData, UNKNOWN, NOT_MEASURED, display_rows, read_artifact,
)


def _provenance(entries: list[dict], label: str) -> None:
    first = entries[0]
    st.caption(f"来源：{first['file']}  ·  生成时间：{first['generated_at']}  ·  "
               f"build ID：{first['build_id']}  ·  run ID：{first['run_id']}")
    st.caption(f"时间状态：{first['freshness']}。缺失身份明确记为 UNKNOWN；文件 mtime 仅为修改时间，SHA-256 仅为内容身份，均不冒充生成时间或 run ID。")
    with st.expander(f"{label} · 全部字段来源与文件身份"):
        st.dataframe(entries, use_container_width=True, hide_index=True)


def _table(rows, **kwargs):
    if rows:
        st.dataframe(display_rows(rows), use_container_width=True, hide_index=True, **kwargs)
    else:
        st.caption("无登记行" if rows == [] else "UNKNOWN · 文件缺失或不可读")


def _percent(value):
    return f"{value:.1%}" if isinstance(value, (int, float)) else NOT_MEASURED


def render_evidence_panel(root: Path, data_dir: Path | None = None) -> None:
    service = EvidenceDashboardData(root, data_dir)
    st.caption("只读文件统计 · 不触发检索、索引构建或实验。UNKNOWN = 无法判断；NOT_MEASURED = 未统计/未执行；0 仅表示已读取完整集合后的零计数。")
    st.markdown("### 1 · 当前所选知识 / 索引快照")
    snapshots = service.snapshots()
    selected = st.selectbox("资产 snapshot", list(snapshots), key="evidence_snapshot")
    snapshot = service.snapshot(snapshots[selected])
    st.caption("“当前所选”仅指本页选择，不代表生产检索路由或最新科学知识。STALE 按生成时间超过 30 天标记；未记录时间则为 UNKNOWN。")
    _provenance(snapshot["provenance"], "Snapshot")
    cols = st.columns(2)
    cols[0].metric("唯一 Evidence Chunks · chunk-level", snapshot["chunk_count"])
    cols[1].metric("Dense Vectors · 同快照 ID 关联", snapshot["vector_count"])
    st.caption(f"Vector IDs：{snapshot['vector_id_status']}。每个工具按关联 chunk_id 去重；共享 chunk 在各关联工具下分别计数，因此逐工具之和可超过唯一 chunk 数。")
    for error in snapshot["errors"]:
        st.warning(error)
    st.markdown(f"**Core 参考名单：有可用来源关联的工具数 {snapshot['coverage']['CORE_TOOLS']}**")
    st.markdown(f"**旧 Qualified 参考名单：有可用来源关联的工具数 {snapshot['coverage']['QUALIFIED_TOOLS']}**")
    st.caption("分子：所选快照中有 source_bound、非空文本、source_id 且非 catalog_only chunk 的工具数；分母：以下固定参考名单的工具数。这是来源关联存在率，不是科学知识完整率，也不是当前 execution qualification。")
    st.caption("名单 / 旧资格标签来源：engine/source_corpus_v2.py 的 CORE_TOOLS / QUALIFIED_TOOLS。仅为代码静态分组，未附逐工具资格证明；当前执行资格 NOT_MEASURED。未用旧 coverage JSON 的百分比或旧 audit 的 vector 0。")
    with st.expander("参考工具名单与逐工具统计", expanded=True):
        st.write("Core：" + ", ".join(snapshot["cohorts"].get("CORE_TOOLS", [])))
        st.write("旧 Qualified：" + ", ".join(snapshot["cohorts"].get("QUALIFIED_TOOLS", [])))
        _table(snapshot["rows"], height=230)

    st.markdown("### 2 · 按 campaign 选择的历史 / 开发实验")
    campaigns = service.campaigns()
    selected_campaign = st.selectbox("实验 campaign（独立于资产 snapshot）", list(campaigns), key="evidence_campaign")
    campaign = service.campaign(campaigns[selected_campaign])
    report = campaign["report"]
    st.warning(f"{campaign['kind']} · {campaign['boundary']}")
    _provenance(campaign["provenance"], "Campaign")
    if campaign["invalidation"]:
        st.error("INVALID · 本 campaign 有作废记录。原 COMPLETE 仅为运行完成；指标只作诊断观察，不接受为正式结论。")
        with st.expander("作废原因与原始记录", expanded=True):
            st.markdown(campaign["invalidation"])
    if campaign["legacy"]:
        st.markdown("旧评测 gold 由已有 chunk/tag 构建；部分预期工具及任务作为请求条件。评分采用宽泛 tool/source 匹配，非严格科学证据答案判分。")
        profiles = report.get("profiles") or {}
        profile = st.selectbox("历史 profile", list(profiles) or [UNKNOWN], index=list(profiles).index("kg_bm25") if "kg_bm25" in profiles else 0)
        metrics = profiles.get(profile) or {}
        cases_path = campaigns[selected_campaign].parent / f"cases_{profile}.jsonl"
        cases, cases_info = read_artifact(cases_path, "jsonl")
        cases_valid = cases is not None and len(cases) == report.get("case_count") and all(r.get("status") in {"retrieved", "blocked_as_required"} for r in cases)
        positive = sum(r["status"] == "retrieved" for r in cases) if cases_valid else UNKNOWN
        negative = sum(r["status"] == "blocked_as_required" for r in cases) if cases_valid else UNKNOWN
        if not cases_valid:
            st.warning("历史分母 UNKNOWN · case 文件缺失、状态缺失或行数不匹配；不从当前 gold 补算。")
        cols = st.columns(4)
        cols[0].metric("历史 Cases", report.get("case_count", UNKNOWN))
        cols[1].metric("旧 recall_at_10 · 工具召回", _percent(metrics.get("recall_at_10")))
        cols[2].metric("旧 precision_at_10 · 来源匹配", _percent(metrics.get("precision_at_10")))
        cols[3].metric("历史 false_support_rate", _percent(metrics.get("false_support_rate")))
        st.caption(f"正例 {positive}：每例预期工具召回比例 / 返回 context 命中比例后取均值；MRR 与 span 指标同样仅覆盖正例。负例 {negative}：false support 以 must_block 负例数为分母。不会将原 99.6% 改称新 Hit@10。")
        st.caption(f"分母来源：{cases_info['file']} · SHA-256 {cases_info['sha256']}；gold 来源：{report.get('gold_path', UNKNOWN)}；语义来源：eval/retrieval_evaluation.py::evaluate_profile。")
        st.caption(f"原 profile status：{metrics.get('status', UNKNOWN)}（仅旧工程门槛）；RAGAS：{metrics.get('ragas_status', NOT_MEASURED)}。")
        with st.expander("原始历史指标（保留原字段与数值）"):
            st.json(metrics)
            st.dataframe([cases_info], use_container_width=True, hide_index=True)
    else:
        identity = report.get("snapshot_identity") or report.get("dense_index_identity") or {}
        st.caption(f"实验绑定的索引 build ID：{identity.get('build_id') or UNKNOWN}（来自所选 report 的 snapshot_identity / dense_index_identity；不继承区域 1）")
        st.caption(f"原报告状态：{report.get('status', UNKNOWN)}。COMPLETE 仅表示该开发实验执行结束，不表示科学优越性、独立 holdout 资格或当前执行资格。")
        if report.get("interpretation_boundary"):
            st.info(report["interpretation_boundary"])
        st.json({key: report[key] for key in ("snapshot_identity", "dense_index_identity", "kg_snapshot_identity", "boundaries", "query_counts") if key in report}, expanded=False)
        aggregate = report.get("aggregate_metrics")
        if isinstance(aggregate, dict) and aggregate:
            profile = st.selectbox("开发 profile", list(aggregate))
            metric_rows = []
            for cohort, values in aggregate[profile].items():
                if not isinstance(values, dict):
                    continue
                for metric, value in values.items():
                    if isinstance(value, dict):
                        denominator = value.get("denominator")
                        shown = "N/A · denominator=0" if denominator == 0 else value.get("rate", NOT_MEASURED)
                        metric_rows.append({"cohort": cohort, "原 metric": metric, "value": shown,
                                            "numerator": value.get("numerator", UNKNOWN), "denominator": denominator if denominator is not None else UNKNOWN})
                    else:
                        metric_rows.append({"cohort": cohort, "原 metric": metric, "value": value if value is not None else NOT_MEASURED,
                                            "numerator": "N/A · scalar", "denominator": "见原 scorer / cohort"})
            _table(metric_rows, height=300)
        with st.expander("原报告（含失败与边界，不改变评分）"):
            st.json(report)

    st.markdown("### 3 · 来源恢复与异常队列")
    audit = service.source_audit()
    st.warning("已登记的历史 source audit 集合；独立于上方 snapshot。未重新下载、抽取或校验本地文本，不代表当前全部知识库。")
    _provenance(audit["provenance"], "Source audit")
    counts = audit["counts"]
    cols = st.columns(4)
    cols[0].metric("Source records · source-level", audit["total"])
    for col, (status, label) in zip(cols[1:], [("source_text_available", "Text available"), ("pdf_extraction_failed", "Extraction failed"), ("source_metadata_mismatch", "Metadata mismatch")]):
        col.metric(label, counts.get(status, 0) if counts is not None else UNKNOWN)
    if counts is not None:
        st.markdown(f"**{audit['total']} records = " + " + ".join(f"{count} {status}" for status, count in sorted(counts.items())) + "**")
        st.caption("分项按唯一 source_id 的 source_status 互斥计数，包含所有未知/其他状态；总和必须解释总数。")
    for error in audit["errors"]:
        st.error(error)
    st.caption("source-level 按 source_id 去重；下表文献行是 tool-record-level，同一 source 可关联多个工具记录；向量/chunk 统计仅在区域 1。")
    candidates = audit["candidates"]
    quarantine_count = sum(str(r.get("quarantine", "")).lower() == "true" for r in candidates) if candidates is not None and all("quarantine" in r for r in candidates) else UNKNOWN
    st.write(f"Quarantine：{audit['quarantine_source_groups']} 个登记来源组；{quarantine_count} 条候选登记行。")
    _table(audit["validation"], height=240)
    with st.expander("完整 source registry / tool-record 文献登记 / quarantine", expanded=False):
        st.markdown("**Source registry（含文本可用与失败）**")
        _table(audit["registry"])
        st.markdown("**Paper / Benchmark · tool-record-level（历史登记行）**")
        _table(audit["literature"])
        st.markdown("**Candidate registry（含 quarantine）**")
        _table(candidates)
        st.markdown("**Source quarantine 原始登记**")
        st.json(audit["quarantine"] if audit["quarantine"] is not None else {"status": UNKNOWN})
    st.caption("none / 空白按字段解释：issue = 无登记问题；action = 无登记处理动作；validation = NOT_MEASURED；文件路径 = UNKNOWN。缺文本、校验未执行或无法判断，均不表示通过。科学证据晋升与 execution qualification 均未在此测量。")
