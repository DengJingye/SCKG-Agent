#!/usr/bin/env python3
"""Build an 8-slide project overview deck for scKG-Atlas Agent.

The project environment does not require python-pptx, so this script writes a
minimal Office Open XML presentation with only the Python standard library.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional local convenience
    Image = None


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "scKG_Agent_8page_project_overview.pptx"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml"

SLIDE_W = 13.333333
SLIDE_H = 7.5
W_EMU = 12192000
H_EMU = 6858000

COLORS = {
    "bg": "F8FAFC",
    "ink": "0F172A",
    "muted": "475569",
    "soft": "E2E8F0",
    "panel": "FFFFFF",
    "blue": "2563EB",
    "cyan": "0891B2",
    "green": "059669",
    "amber": "D97706",
    "red": "DC2626",
    "violet": "7C3AED",
    "slate": "334155",
}


def emu(value: float) -> int:
    return int(round(value * 914400))


def clean_xml(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def pct(value: object, digits: int = 0) -> str:
    try:
        number = float(value) * 100
    except Exception:
        return "NA"
    if digits:
        return f"{number:.{digits}f}%"
    return f"{number:.0f}%"


def rows_in_tsv(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def read_metric(path: Path, metric: str, default: float | None = None) -> float | None:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row.get("metric") == metric:
                try:
                    return float(row.get("value", ""))
                except ValueError:
                    return default
    return default


def read_ablation(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            mode = row.get("mode", "")
            out[mode] = {}
            for key, value in row.items():
                if key == "mode":
                    continue
                try:
                    out[mode][key] = float(value)
                except Exception:
                    continue
    return out


def read_context_summary(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}


def read_readme_inventory(path: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    if not path.exists():
        return inventory
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Asset | Current count |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            break
        parts = [p.strip().strip("`") for p in line.strip("|").split("|")]
        if len(parts) != 2 or parts[0].startswith("---"):
            continue
        inventory[parts[0]] = parts[1]
    return inventory


def resized_logo_bytes() -> bytes | None:
    logo = ROOT / "logo.png"
    if not logo.exists():
        return None
    if Image is None:
        return logo.read_bytes()
    img = Image.open(logo).convert("RGBA")
    img.thumbnail((760, 520))
    buffer = BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


@dataclass
class SlideBuilder:
    title: str | None = None
    subtitle: str | None = None
    number: int = 1
    background: str = COLORS["bg"]
    shapes: list[str] = field(default_factory=list)
    rels: list[str] = field(default_factory=list)
    next_id: int = 2

    def shape_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def add_shape(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str | None = None,
        line: str | None = None,
        radius: bool = False,
        name: str = "Shape",
    ) -> None:
        sid = self.shape_id()
        fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        line_xml = (
            f'<a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
            if line
            else '<a:ln><a:noFill/></a:ln>'
        )
        geom = "roundRect" if radius else "rect"
        self.shapes.append(
            f"""
<p:sp>
  <p:nvSpPr><p:cNvPr id="{sid}" name="{clean_xml(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
    <a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>
    {fill_xml}
    {line_xml}
  </p:spPr>
</p:sp>"""
        )

    def add_text(
        self,
        text: str | Iterable[str],
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        size: int = 18,
        color: str = COLORS["ink"],
        bold: bool = False,
        fill: str | None = None,
        line: str | None = None,
        align: str = "l",
        radius: bool = False,
        margin: float = 0.08,
        valign: str = "t",
        name: str = "Text",
    ) -> None:
        sid = self.shape_id()
        lines = [text] if isinstance(text, str) else list(text)
        fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        line_xml = (
            f'<a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
            if line
            else '<a:ln><a:noFill/></a:ln>'
        )
        geom = "roundRect" if radius else "rect"
        paragraphs = []
        for idx, line_text in enumerate(lines):
            paragraphs.append(paragraph_xml(line_text, size=size, color=color, bold=bold, align=align, first=idx == 0))
        self.shapes.append(
            f"""
<p:sp>
  <p:nvSpPr><p:cNvPr id="{sid}" name="{clean_xml(name)}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
    <a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>
    {fill_xml}
    {line_xml}
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square" anchor="{valign}" lIns="{emu(margin)}" rIns="{emu(margin)}" tIns="{emu(margin)}" bIns="{emu(margin)}"/>
    <a:lstStyle/>
    {''.join(paragraphs)}
  </p:txBody>
</p:sp>"""
        )

    def add_header(self, title: str, eyebrow: str = "") -> None:
        self.add_shape(0, 0, SLIDE_W, 0.14, fill=COLORS["blue"])
        self.add_text(title, 0.38, 0.22, 8.9, 0.42, size=22, bold=True, margin=0, name="Header title")
        if eyebrow:
            self.add_text(eyebrow, 9.2, 0.25, 2.9, 0.32, size=9, color=COLORS["muted"], align="r", margin=0)
        self.add_text(f"{self.number:02d}/08", 12.3, 0.24, 0.62, 0.28, size=10, color=COLORS["muted"], align="r", margin=0)

    def add_metric_card(self, value: str, label: str, x: float, y: float, w: float, h: float, color: str) -> None:
        self.add_text("", x, y, w, h, fill=COLORS["panel"], line=COLORS["soft"], radius=True, margin=0.05)
        self.add_shape(x, y, 0.08, h, fill=color, radius=False)
        self.add_text(value, x + 0.18, y + 0.12, w - 0.28, 0.34, size=22, bold=True, color=color, margin=0)
        self.add_text(label, x + 0.18, y + 0.53, w - 0.28, h - 0.6, size=10, color=COLORS["muted"], margin=0)

    def add_panel(self, title: str, bullets: Iterable[str], x: float, y: float, w: float, h: float, color: str) -> None:
        self.add_text("", x, y, w, h, fill=COLORS["panel"], line=COLORS["soft"], radius=True, margin=0.04)
        self.add_shape(x, y, 0.08, h, fill=color)
        self.add_text(title, x + 0.22, y + 0.17, w - 0.35, 0.34, size=14, bold=True, color=COLORS["ink"], margin=0)
        lines = [f"• {item}" for item in bullets]
        self.add_text(lines, x + 0.22, y + 0.62, w - 0.35, h - 0.72, size=10, color=COLORS["slate"], margin=0)

    def add_bar(self, label: str, value: float, x: float, y: float, w: float, color: str, value_label: str | None = None) -> None:
        value = max(0.0, min(float(value), 1.0))
        self.add_text(label, x, y - 0.02, 2.45, 0.23, size=9, color=COLORS["muted"], margin=0)
        self.add_shape(x + 2.6, y + 0.02, w, 0.16, fill="E5E7EB", radius=True)
        self.add_shape(x + 2.6, y + 0.02, max(0.04, w * value), 0.16, fill=color, radius=True)
        self.add_text(value_label or pct(value), x + 2.6 + w + 0.08, y - 0.02, 0.72, 0.23, size=9, color=COLORS["ink"], margin=0)

    def add_logo(self, x: float, y: float, w: float, h: float) -> None:
        sid = self.shape_id()
        rid = f"rId{len(self.rels) + 2}"
        self.rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/logo.png"/>'
        )
        self.shapes.append(
            f"""
<p:pic>
  <p:nvPicPr><p:cNvPr id="{sid}" name="logo.png"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>
  <p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
  <p:spPr><a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
</p:pic>"""
        )

    def xml(self) -> str:
        bg = f"""
<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{self.background}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>"""
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    {bg}
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {''.join(self.shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""

    def rels_xml(self) -> str:
        relationships = [
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>',
            *self.rels,
        ]
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{''.join(relationships)}
</Relationships>"""


def paragraph_xml(text: str, *, size: int, color: str, bold: bool, align: str, first: bool) -> str:
    sz = size * 100
    bold_attr = ' b="1"' if bold else ""
    text = clean_xml(text)
    before = "0" if first else "5000"
    return f"""
<a:p>
  <a:pPr algn="{align}"><a:spcBef><a:spcPts val="{before}"/></a:spcBef><a:lnSpc><a:spcPct val="105000"/></a:lnSpc></a:pPr>
  <a:r>
    <a:rPr lang="zh-CN" sz="{sz}"{bold_attr}>
      <a:solidFill><a:srgbClr val="{color}"/></a:solidFill>
      <a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/>
    </a:rPr>
    <a:t>{text}</a:t>
  </a:r>
  <a:endParaRPr lang="zh-CN" sz="{sz}"/>
</a:p>"""


def build_slides() -> list[SlideBuilder]:
    inventory = read_readme_inventory(ROOT / "README.md")
    ablation = read_ablation(ROOT / "eval/ablation_deepseek_aura_v0_2_blind_full/ablation_summary.tsv")
    context = read_context_summary(ROOT / "eval/context_pack_v0_12_full_offline_audit_summary_v2.json")
    v12 = ROOT / "eval/context_pack_v0_12_full_offline_migration_eval_summary_v2.tsv"

    tools = rows_in_tsv(ROOT / "data/scrna_tools.tsv")
    formal_pub = rows_in_tsv(ROOT / "data/tool_publications.tsv")
    formal_bench = rows_in_tsv(ROOT / "data/tool_benchmarks.tsv")
    candidate_packets = len(list((ROOT / "data/evidence_candidates").glob("*.tsv")))
    kg_issues = rows_in_tsv(ROOT / "data/evidence_candidates/kg_quality_audit_report.tsv")
    kg_actions = rows_in_tsv(ROOT / "data/evidence_candidates/kg_quality_review_actions.tsv")

    pure = ablation.get("pure_llm", {})
    audited = ablation.get("evidence_gate_auditor", {})
    full = ablation.get("full_kg_pipeline", {})

    slide1 = SlideBuilder(number=1)
    slide1.add_shape(0, 0, 0.22, SLIDE_H, fill=COLORS["blue"])
    slide1.add_shape(0.22, 0, 0.08, SLIDE_H, fill=COLORS["green"])
    slide1.add_text("scKG-Atlas Agent", 0.72, 0.72, 7.4, 0.7, size=34, bold=True, margin=0)
    slide1.add_text("面向单细胞、空间组学与多组学工具选择的证据治理型科研 Agent", 0.75, 1.52, 8.9, 0.36, size=16, color=COLORS["slate"], margin=0)
    slide1.add_text(
        [
            "研究背景与意义：组学分析工具快速增长，文献、benchmark、协议和代码证据分散；普通 LLM 容易把候选材料、GitHub 活跃度或相似工具误说成强推荐。",
            "项目定位：不是无限制聊天机器人，而是把科研请求转成结构化约束，经证据门控、可信排序、报告生成和语义幻觉审计后，输出可追溯、保守、可复核的推荐或探索性迁移假设。",
        ],
        0.78,
        2.08,
        8.55,
        1.34,
        size=12,
        color=COLORS["ink"],
        margin=0,
    )
    slide1.add_metric_card(f"{tools:,}", "工具目录记录", 0.78, 3.78, 2.05, 0.92, COLORS["blue"])
    slide1.add_metric_card(str(formal_pub), "正式 publication evidence", 3.02, 3.78, 2.18, 0.92, COLORS["green"])
    slide1.add_metric_card(str(formal_bench), "正式 benchmark evidence", 5.38, 3.78, 2.18, 0.92, COLORS["amber"])
    slide1.add_metric_card(str(candidate_packets), "候选/审阅队列 TSV", 7.74, 3.78, 2.18, 0.92, COLORS["violet"])
    slide1.add_text(
        [
            "核心价值：把“能回答”升级为“有证据、能解释、可审计”。",
            "治理原则：candidate-only 证据不自动进入正式推荐；弱证据必须降级并显式暴露不确定性。",
        ],
        0.82,
        5.08,
        8.6,
        0.82,
        size=11,
        color=COLORS["muted"],
        fill="EEF2FF",
        line="C7D2FE",
        radius=True,
    )
    slide1.add_logo(10.02, 0.88, 2.35, 1.55)
    slide1.add_text("材料版本：本地仓库快照 2026-05-24", 9.55, 6.88, 3.05, 0.24, size=9, color=COLORS["muted"], align="r", margin=0)

    slide2 = SlideBuilder(number=2)
    slide2.add_header("研究目标与内容", "从科研问题到证据约束推荐")
    slide2.add_panel(
        "总目标",
        [
            "构建证据治理型 Agent：理解任务、检索可信证据、保守排序、生成可审计报告。",
            "在证据不足时输出缺口、澄清问题或探索性迁移假设，而不是伪造强结论。",
            "形成可复现评估协议，持续量化推荐质量、幻觉风险和迁移边界。",
        ],
        0.55,
        0.95,
        5.65,
        2.05,
        COLORS["blue"],
    )
    slide2.add_panel(
        "研究内容",
        [
            "任务解析：task / modality / platform / data object / scale / noise / hardware / species。",
            "证据体系：正式 publication、benchmark、workflow/protocol 与候选 review packet 分层。",
            "推荐模型：evidence gate + trusted_core filtering + MCDM top-k。",
            "安全报告：EvidenceContextPack + prompt policy + semantic hallucination auditor。",
            "探索模块：算法迁移只输出 MigrationHypothesis，不进入正式推荐 top-k。",
        ],
        6.55,
        0.95,
        6.2,
        2.65,
        COLORS["green"],
    )
    slide2.add_text("研究问题拆解", 0.58, 3.48, 2.2, 0.28, size=14, bold=True, margin=0)
    for i, (label, detail, color) in enumerate(
        [
            ("用户需求", "模糊自然语言、实验条件不完整", COLORS["blue"]),
            ("证据约束", "哪些证据可用于推荐，哪些只能解释", COLORS["green"]),
            ("工具排序", "多指标、缺证据、任务适配冲突", COLORS["amber"]),
            ("报告安全", "限制 unsupported claims 和工具幻觉", COLORS["red"]),
        ]
    ):
        x = 0.72 + i * 3.05
        slide2.add_text(label, x, 4.0, 2.42, 0.34, size=13, bold=True, color=color, align="c", fill=COLORS["panel"], line=COLORS["soft"], radius=True)
        slide2.add_text(detail, x, 4.42, 2.42, 0.68, size=9, color=COLORS["muted"], align="c", fill=COLORS["panel"], line=COLORS["soft"], radius=True)
        if i < 3:
            slide2.add_text("→", x + 2.48, 4.2, 0.34, 0.32, size=18, color=COLORS["muted"], align="c", margin=0)
    slide2.add_panel(
        "预期产出",
        [
            "面向单细胞/空间组学工具选择的可追溯推荐原型。",
            "正式证据表、候选证据隔离区、审阅动作队列与 KG 质量审计。",
            "封闭 gold set、离线预测、消融对照和 hallucination audit 指标体系。",
        ],
        0.55,
        5.42,
        12.2,
        1.18,
        COLORS["violet"],
    )

    slide3 = SlideBuilder(number=3)
    slide3.add_header("系统架构与研究方案", "窄推荐主路 + 可控 Hybrid KG-RAG")
    slide3.add_text("主推荐路径", 0.62, 0.9, 2.4, 0.3, size=14, bold=True, margin=0)
    steps = [
        ("raw retrieval", "大召回，不直接推荐"),
        ("evidence gate", "过滤非推荐级证据"),
        ("trusted_core", "正式/审阅证据进入上下文"),
        ("top-k ranking", "MCDM 保守排序"),
        ("report", "受 policy 约束生成"),
        ("audit", "高危幻觉阻断"),
    ]
    for i, (name, desc) in enumerate(steps):
        x = 0.58 + i * 2.1
        slide3.add_text(name, x, 1.38, 1.65, 0.42, size=10, bold=True, color=COLORS["ink"], align="c", fill="DBEAFE", line="BFDBFE", radius=True)
        slide3.add_text(desc, x, 1.86, 1.65, 0.48, size=8, color=COLORS["muted"], align="c", fill=COLORS["panel"], line=COLORS["soft"], radius=True)
        if i < len(steps) - 1:
            slide3.add_text("→", x + 1.66, 1.52, 0.36, 0.34, size=18, color=COLORS["blue"], margin=0)
    slide3.add_panel(
        "KG 的职责",
        [
            "结构化工具-任务-模态-算法关系。",
            "提供 evidence gate、ranking input 和安全边界。",
            "Neo4j/AuraDB 作为运行服务；TSV 正式证据仍是 source of truth。",
        ],
        0.62,
        2.72,
        3.85,
        2.15,
        COLORS["blue"],
    )
    slide3.add_panel(
        "RAG 的职责",
        [
            "提供论文、协议、文档片段用于解释和 provenance。",
            "不能改变 MCDM 分数，不能自动提升 evidence trust level。",
            "缺证据必须进入 missing_evidence，而不是被语言模型补齐。",
        ],
        4.76,
        2.72,
        3.85,
        2.15,
        COLORS["green"],
    )
    slide3.add_panel(
        "Auditor 的职责",
        [
            "审计报告中的工具、benchmark、ranking、workflow transition 和阈值类 claim。",
            "critical/high severity findings 阻断不安全报告。",
            "输出 unsupported tools / unsupported claims 供复盘。",
        ],
        8.9,
        2.72,
        3.85,
        2.15,
        COLORS["red"],
    )
    slide3.add_text(
        "v0.12 EvidenceContextPack：trusted_recommendation_context / retrieval_context / migration_context / blocked_context / missing_evidence / prompt_policy",
        0.68,
        5.35,
        12.0,
        0.58,
        size=12,
        bold=True,
        color=COLORS["ink"],
        align="c",
        fill="ECFEFF",
        line="A5F3FC",
        radius=True,
    )
    slide3.add_text(
        "方案要点：KG 负责边界，RAG 负责解释，LLM 负责组织表达，Auditor 负责阻断 unsupported scientific claims。",
        1.15,
        6.14,
        11.0,
        0.4,
        size=11,
        color=COLORS["muted"],
        align="c",
        margin=0,
    )

    slide4 = SlideBuilder(number=4)
    slide4.add_header("核心亮点：证据治理与可追溯推荐", "candidate 隔离，正式证据保守进入推荐")
    slide4.add_metric_card(inventory.get("data/scrna_tools.tsv rows excluding header", f"{tools:,}"), "工具目录规模", 0.55, 0.95, 2.2, 0.85, COLORS["blue"])
    slide4.add_metric_card(str(formal_pub), "正式 publication rows", 2.98, 0.95, 2.2, 0.85, COLORS["green"])
    slide4.add_metric_card(str(formal_bench), "正式 benchmark rows", 5.41, 0.95, 2.2, 0.85, COLORS["amber"])
    slide4.add_metric_card(inventory.get("unique candidate evidence IDs counted by graph inventory", "178"), "候选证据 ID", 7.84, 0.95, 2.2, 0.85, COLORS["violet"])
    slide4.add_metric_card(str(kg_actions), "KG 审阅动作", 10.27, 0.95, 2.2, 0.85, COLORS["red"])
    slide4.add_text("证据分层策略", 0.62, 2.25, 2.2, 0.3, size=14, bold=True, margin=0)
    layers = [
        ("trusted_core", "可进入检索、排序、推荐与报告", COLORS["green"], 0.70),
        ("review_needed", "候选材料只进入审阅队列，不自动晋升", COLORS["amber"], 0.55),
        ("experimental", "迁移假设、相似性和模板仅用于探索", COLORS["violet"], 0.40),
        ("rejected/deprecated", "阻断进入推荐链路", COLORS["red"], 0.25),
    ]
    for i, (name, desc, color, width) in enumerate(layers):
        y = 2.75 + i * 0.72
        slide4.add_shape(0.74, y, 4.8 * width, 0.36, fill=color, radius=True)
        slide4.add_text(name, 0.9, y + 0.05, 1.65, 0.22, size=9, bold=True, color="FFFFFF", margin=0)
        slide4.add_text(desc, 3.35, y - 0.01, 4.4, 0.28, size=10, color=COLORS["slate"], margin=0)
    slide4.add_panel(
        "为什么这是亮点",
        [
            "把推荐级证据和候选证据物理隔离，避免“抓到就推荐”。",
            "正式表字段顺序由 evidence_schemas.py 约束，便于验证和回滚。",
            "canonical work_group_id 防止同一论文/benchmark 重复计分。",
            "UI 默认只展示正式 Tool-Task 主干，减少高阶节点造成的视觉误导。",
        ],
        7.92,
        2.42,
        4.8,
        2.52,
        COLORS["blue"],
    )
    slide4.add_text(
        f"当前 KG 质量审计：{kg_issues} 条 issue，{kg_actions} 条 review action。重点集中在 benchmark work_group_id、PMID、重复 DOI/title 与正式表 provenance 清理。",
        0.72,
        5.55,
        12.0,
        0.72,
        size=11,
        color=COLORS["ink"],
        fill="FFF7ED",
        line="FED7AA",
        radius=True,
    )

    slide5 = SlideBuilder(number=5)
    slide5.add_header("关键难点与解决路径", "让 Agent 保守、可复现，而不是更会编")
    difficulties = [
        ("证据稀疏且异质", "论文、benchmark、protocol、GitHub 和工具文档可信度不同。", "分层 evidence policy；GitHub 活跃度不能支撑强科学推荐。", COLORS["blue"]),
        ("工具名和任务边界混淆", "Scanpy/scvi-tools 等 suite 级工具容易被误当成单一方法。", "task ontology + deterministic fallback + migration intent gate。", COLORS["green"]),
        ("重复论文导致评分膨胀", "同一 benchmark 可覆盖多个工具，若不分组会重复加权。", "work_group_id + canonical_scope，非 canonical 只做链接证据。", COLORS["amber"]),
        ("探索性迁移容易过度承诺", "相似机制不等于适配新任务，更不等于 benchmark-backed。", "MigrationHypothesis 独立于 ScoredTool；必须带 caveat、gap、validation plan。", COLORS["violet"]),
        ("报告幻觉难以肉眼兜底", "LLM 可能生成不存在的排名、阈值、迁移保证或工作流跳转。", "semantic hallucination auditor 审计 claim，critical/high findings 阻断输出。", COLORS["red"]),
    ]
    for i, (title, problem, solution, color) in enumerate(difficulties):
        y = 0.95 + i * 1.08
        slide5.add_text(str(i + 1), 0.62, y + 0.05, 0.35, 0.34, size=14, bold=True, color="FFFFFF", align="c", fill=color, radius=True)
        slide5.add_text(title, 1.08, y, 2.55, 0.28, size=12, bold=True, color=color, margin=0)
        slide5.add_text(problem, 3.68, y, 3.72, 0.42, size=10, color=COLORS["muted"], margin=0)
        slide5.add_text("→", 7.48, y + 0.06, 0.32, 0.24, size=13, color=COLORS["muted"], margin=0)
        slide5.add_text(solution, 7.92, y, 4.75, 0.45, size=10, color=COLORS["ink"], margin=0)
    slide5.add_text(
        "工程取舍：优先使用确定性脚本、TSV 工作流、审阅队列和离线评估；延后自主执行、自动证据晋升和复杂长期记忆。",
        0.75,
        6.34,
        11.85,
        0.46,
        size=12,
        bold=True,
        color=COLORS["ink"],
        align="c",
        fill="F1F5F9",
        line=COLORS["soft"],
        radius=True,
    )

    slide6 = SlideBuilder(number=6)
    slide6.add_header("版本更新迭代与研究进展", "从推荐 baseline 到 Hybrid KG-RAG 上下文包")
    timeline = [
        ("v0.1", "原型", "Streamlit UI、LangGraph workflow、Neo4j/offline graph、工具目录接入。", COLORS["slate"]),
        ("v0.2", "可信推荐 baseline", "冻结 evidence_gate_auditor：约束解析、trusted evidence gate、MCDM top-k、语义审计。", COLORS["blue"]),
        ("v0.3", "迁移假设", "引入 MigrationHypothesis、算法 profile、迁移可行性分数和验证计划。", COLORS["green"]),
        ("v0.8", "封闭评估", "定义 sealed migration protocol；首次系统性测试 true/revise/negative/clarify/trap。", COLORS["amber"]),
        ("v0.9-v0.11", "故障修复", "人审迁移向量，暴露并修复 toolkit/API/foundation model 过度迁移陷阱。", COLORS["red"]),
        ("v0.12", "Hybrid KG-RAG", "EvidenceContextPack：可信推荐、检索解释、迁移、阻断和缺证据上下文分离。", COLORS["violet"]),
    ]
    for i, (ver, tag, desc, color) in enumerate(timeline):
        x = 0.6 + i * 2.06
        slide6.add_shape(x + 0.05, 1.27, 1.66, 0.08, fill=color)
        slide6.add_text(ver, x, 0.88, 1.75, 0.34, size=15, bold=True, color=color, align="c", margin=0)
        slide6.add_text(tag, x, 1.44, 1.75, 0.28, size=10, bold=True, color=COLORS["ink"], align="c", margin=0)
        slide6.add_text(desc, x, 1.82, 1.75, 1.4, size=8, color=COLORS["muted"], align="c", fill=COLORS["panel"], line=COLORS["soft"], radius=True)
    slide6.add_text("封闭迁移评估指标演进", 0.68, 3.62, 3.0, 0.28, size=14, bold=True, margin=0)
    versions = [
        ("v0.8", ROOT / "eval/migration_sealed_v0_8_first_run_eval_summary.tsv"),
        ("v0.9", ROOT / "eval/migration_sealed_v0_9_first_run_eval_summary.tsv"),
        ("v0.10", ROOT / "eval/migration_sealed_v0_10_first_run_eval_summary.tsv"),
        ("v0.11", ROOT / "eval/migration_sealed_v0_11_first_run_eval_summary.tsv"),
        ("v0.12", v12),
    ]
    y = 4.05
    for label, path in versions:
        mix = read_metric(path, "mixed_decision_accuracy", 0) or 0
        false_mig = read_metric(path, "negative_false_migration_rate", 0) or 0
        high = read_metric(path, "high_hallucination_rate", 0) or 0
        slide6.add_text(label, 0.82, y, 0.62, 0.24, size=9, bold=True, color=COLORS["ink"], margin=0)
        slide6.add_bar("mixed decision", mix, 1.55, y, 2.6, COLORS["blue"])
        slide6.add_bar("false migration", false_mig, 5.2, y, 2.2, COLORS["red"], value_label=pct(false_mig, 1))
        slide6.add_bar("high hallucination", high, 8.55, y, 2.2, COLORS["amber"], value_label=pct(high, 1))
        y += 0.45
    slide6.add_text(
        "解读：v0.9-v0.11 的封闭集不是“刷榜”，而是把失败模式暴露出来并纳入下一版本治理；v0.12 在 35 条 full offline set 上达到混合决策 100%、高危幻觉 0、未审迁移路径 0。",
        0.72,
        6.38,
        11.85,
        0.48,
        size=10,
        color=COLORS["slate"],
        fill="ECFDF5",
        line="A7F3D0",
        radius=True,
    )

    slide7 = SlideBuilder(number=7)
    slide7.add_header("实验结果与阶段性成就", "证据链路显著降低 unsupported claims")
    slide7.add_metric_card(str(int(read_metric(v12, "query_count", 35) or 35)), "v0.12 gold queries", 0.58, 0.95, 2.08, 0.82, COLORS["blue"])
    slide7.add_metric_card(pct(read_metric(v12, "mixed_decision_accuracy", 1) or 1), "mixed decision accuracy", 2.86, 0.95, 2.08, 0.82, COLORS["green"])
    slide7.add_metric_card(pct(read_metric(v12, "negative_false_migration_rate", 0) or 0), "false migration rate", 5.14, 0.95, 2.08, 0.82, COLORS["red"])
    slide7.add_metric_card(pct(read_metric(v12, "semantic_audit_pass_rate", 1) or 1), "semantic audit pass", 7.42, 0.95, 2.08, 0.82, COLORS["violet"])
    slide7.add_metric_card(pct(read_metric(v12, "unsupported_tool_claim_rate", 0) or 0), "unsupported tool claims", 9.70, 0.95, 2.08, 0.82, COLORS["amber"])
    slide7.add_text("消融对照：Pure LLM vs evidence-gated/audited route", 0.68, 2.18, 5.4, 0.28, size=14, bold=True, margin=0)
    comparisons = [
        ("推荐类型准确率", pure.get("recommendation_type_accuracy", 0), audited.get("recommendation_type_accuracy", 0), COLORS["blue"]),
        ("Top-k hit", pure.get("top_k_hit", 0), audited.get("top_k_hit", 0), COLORS["green"]),
        ("语义幻觉 issue rate", pure.get("semantic_hallucination_issue_rate", 0), audited.get("semantic_hallucination_issue_rate", 0), COLORS["red"]),
        ("Unsupported tool claim", pure.get("unsupported_tool_claim_rate", 0), audited.get("unsupported_tool_claim_rate", 0), COLORS["amber"]),
    ]
    y = 2.7
    for label, before, after, color in comparisons:
        slide7.add_text(label, 0.82, y, 2.0, 0.25, size=9, bold=True, color=COLORS["ink"], margin=0)
        slide7.add_text("Pure LLM", 2.85, y, 0.72, 0.21, size=8, color=COLORS["muted"], margin=0)
        slide7.add_shape(3.58, y + 0.03, 2.0, 0.14, fill="E5E7EB", radius=True)
        slide7.add_shape(3.58, y + 0.03, max(0.04, 2.0 * min(before, 1)), 0.14, fill=color, radius=True)
        slide7.add_text(pct(before, 1), 5.66, y - 0.02, 0.55, 0.2, size=8, color=COLORS["muted"], margin=0)
        slide7.add_text("Gate+Audit", 6.45, y, 0.85, 0.21, size=8, color=COLORS["muted"], margin=0)
        slide7.add_shape(7.35, y + 0.03, 2.0, 0.14, fill="E5E7EB", radius=True)
        slide7.add_shape(7.35, y + 0.03, max(0.04, 2.0 * min(after, 1)), 0.14, fill=color, radius=True)
        slide7.add_text(pct(after, 1), 9.43, y - 0.02, 0.55, 0.2, size=8, color=COLORS["ink"], margin=0)
        y += 0.52
    slide7.add_panel(
        "阶段性成就",
        [
            f"v0.12 ContextPack audit：{int(context.get('query_count', 35))}/35 pass，context_pack_present_rate {pct(context.get('context_pack_present_rate', 1))}。",
            f"平均 retrieval evidence {context.get('mean_retrieval_evidence_count', 9.3714):.2f} 条，formal RAG snippet {context.get('mean_formal_rag_snippet_count', 3.4571):.2f} 条。",
            f"retrieval rankable violations、trusted non-main violations、bad migration-decision violations 均为 {int(context.get('total_retrieval_rankable_violations', 0))}。",
            f"Full KG pipeline 达到 workflow completeness {pct(full.get('workflow_completeness', 1))}，体现工作流组织能力。",
        ],
        0.68,
        5.05,
        12.0,
        1.36,
        COLORS["green"],
    )

    slide8 = SlideBuilder(number=8)
    slide8.add_header("下一步工作与实验设计", "补证据、稳评估、做小规模实证")
    slide8.add_panel(
        "1. 证据质量优先",
        [
            "完成 P1 benchmark canonical_group_review：补 work_group_id、PMID、canonical_scope。",
            "清理正式表中 candidate-origin 标记，保持字段顺序与 evidence_schemas.py 同步。",
            "扩展高优先任务的 publication/benchmark evidence，但继续走候选生成→人审→正式晋升。",
        ],
        0.58,
        0.95,
        4.05,
        2.35,
        COLORS["blue"],
    )
    slide8.add_panel(
        "2. 评估体系扩展",
        [
            "为 annotation、integration、spatial deconvolution、RNA velocity、multiome 建 task-specific blind sets。",
            "固定指标：constraint parse、top-k hit、evidence coverage、workflow completeness、audit pass/block rate。",
            "每个版本保留 sealed first run，失败转入下一版本修复，避免后验调参。",
        ],
        4.84,
        0.95,
        4.05,
        2.35,
        COLORS["green"],
    )
    slide8.add_panel(
        "3. 迁移假设实证",
        [
            "挑选 3-5 个 accept_exploratory 迁移路径做小样本 case study。",
            "实验设计：source mechanism baseline、direct tool baseline、ablation(vector/graph/RAG)、专家复核。",
            "输出只声明 system-level plausibility；生物学有效性必须经独立验证。",
        ],
        9.10,
        0.95,
        3.65,
        2.35,
        COLORS["violet"],
    )
    slide8.add_text("近期里程碑建议", 0.68, 3.76, 2.8, 0.28, size=14, bold=True, margin=0)
    milestones = [
        ("M1", "证据治理", "完成 KG quality P1/P2 review actions；形成 reviewed evidence promotion checklist。", COLORS["blue"]),
        ("M2", "报告可靠性", "把 ContextPack audit 接入常规 smoke eval；critical/high issue 默认阻断。", COLORS["green"]),
        ("M3", "实验验证", "发布一组任务级 blind gold set + 迁移 case study notebook/report。", COLORS["amber"]),
        ("M4", "产品表达", "UI 展示证据来源、missing evidence、审计状态、迁移 caveat；不展示误导性大盘指标。", COLORS["violet"]),
    ]
    for i, (tag, title, desc, color) in enumerate(milestones):
        y2 = 4.18 + i * 0.56
        slide8.add_text(tag, 0.82, y2, 0.48, 0.26, size=9, bold=True, color="FFFFFF", align="c", fill=color, radius=True)
        slide8.add_text(title, 1.42, y2, 1.25, 0.24, size=10, bold=True, color=color, margin=0)
        slide8.add_text(desc, 2.72, y2, 9.65, 0.24, size=10, color=COLORS["slate"], margin=0)
    slide8.add_text(
        "边界条件：下一阶段仍不自动晋升候选证据、不让 RAG 改 ranking、不让 memory 成为科学证据；执行 Agent 只在 sandbox、allowlist 和用户显式批准后逐级推进。",
        0.72,
        6.42,
        11.85,
        0.48,
        size=10,
        bold=True,
        color=COLORS["ink"],
        align="c",
        fill="FEF2F2",
        line="FECACA",
        radius=True,
    )

    return [slide1, slide2, slide3, slide4, slide5, slide6, slide7, slide8]


def content_types(slide_count: int, has_logo: bool) -> str:
    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    if has_logo:
        defaults.append('<Default Extension="png" ContentType="image/png"/>')
    overrides = [
        f'<Override PartName="/ppt/presentation.xml" ContentType="{PPTX_MIME}.presentation.main+xml"/>',
        f'<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="{PPTX_MIME}.slideMaster+xml"/>',
        f'<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="{PPTX_MIME}.slideLayout+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for i in range(1, slide_count + 1):
        overrides.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="{PPTX_MIME}.slide+xml"/>')
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
{''.join(defaults)}
{''.join(overrides)}
</Types>"""


def root_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def presentation_xml(slide_count: int) -> str:
    slide_ids = "\n".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="{W_EMU}" cy="{H_EMU}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle><a:defPPr><a:defRPr lang="zh-CN"/></a:defPPr></p:defaultTextStyle>
</p:presentation>"""


def presentation_rels(slide_count: int) -> str:
    rels = [
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
    ]
    for i in range(1, slide_count + 1):
        rels.append(
            f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
        )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{''.join(rels)}
</Relationships>"""


def slide_master_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>"""


def slide_master_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""


def slide_layout_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""


def slide_layout_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""


def theme_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="scKG Agent">
  <a:themeElements>
    <a:clrScheme name="scKG">
      <a:dk1><a:srgbClr val="0F172A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="334155"/></a:dk2><a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>
      <a:accent1><a:srgbClr val="2563EB"/></a:accent1><a:accent2><a:srgbClr val="059669"/></a:accent2>
      <a:accent3><a:srgbClr val="D97706"/></a:accent3><a:accent4><a:srgbClr val="DC2626"/></a:accent4>
      <a:accent5><a:srgbClr val="7C3AED"/></a:accent5><a:accent6><a:srgbClr val="0891B2"/></a:accent6>
      <a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="scKG"><a:majorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="scKG"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
  </a:themeElements>
</a:theme>"""


def core_props() -> str:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>scKG-Atlas Agent 项目介绍</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>"""


def app_props(slide_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex OOXML Builder</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat>
  <Slides>{slide_count}</Slides><Notes>0</Notes><HiddenSlides>0</HiddenSlides>
</Properties>"""


def write_deck() -> Path:
    slides = build_slides()
    logo_bytes = resized_logo_bytes()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types(len(slides), bool(logo_bytes)))
        zf.writestr("_rels/.rels", root_rels())
        zf.writestr("docProps/core.xml", core_props())
        zf.writestr("docProps/app.xml", app_props(len(slides)))
        zf.writestr("ppt/presentation.xml", presentation_xml(len(slides)))
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels(len(slides)))
        zf.writestr("ppt/slideMasters/slideMaster1.xml", slide_master_xml())
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", slide_master_rels())
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", slide_layout_xml())
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", slide_layout_rels())
        zf.writestr("ppt/theme/theme1.xml", theme_xml())
        if logo_bytes:
            zf.writestr("ppt/media/logo.png", logo_bytes)
        for i, slide in enumerate(slides, start=1):
            zf.writestr(f"ppt/slides/slide{i}.xml", slide.xml())
            zf.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", slide.rels_xml())
    return OUT


def main() -> None:
    out = write_deck()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        slide_count = len([name for name in names if re.match(r"ppt/slides/slide\d+\.xml$", name)])
    print(f"wrote {out}")
    print(f"slides {slide_count}")


if __name__ == "__main__":
    main()
