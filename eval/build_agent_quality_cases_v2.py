from __future__ import annotations

import json
from pathlib import Path
from typing import Any


OUTPUT = Path(__file__).resolve().parent / "fixtures" / "agent_quality_cases_v2.json"


def _case(
    *,
    case_id: str,
    domain: str,
    variants: list[str],
    intent: str,
    task: str,
    tools: list[str],
    workflow: bool = False,
    blocked: bool = False,
    required: list[str] | None = None,
    forbidden: list[str] | None = None,
    context: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if len(variants) != 3:
        raise ValueError(f"{case_id} must define exactly three natural-language variants")
    return {
        "case_id": case_id,
        "capability_domain": domain,
        "query": variants[0],
        "query_variants": variants,
        "expected_intent": intent,
        "expected_task": task,
        "required_top_tools": tools,
        "expected_workflow": workflow,
        "expected_blocked": blocked,
        "required_phrases": required or [],
        "forbidden_phrases": forbidden or [],
        "conversation_context": context or [],
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    doublet_recommendations = [
        ("chat-doublet-recommend-zh-01", "10x PBMC"),
        ("chat-doublet-recommend-zh-02", "10x droplet"),
        ("chat-doublet-recommend-03", "PBMC capture"),
        ("chat-doublet-recommend-04", "多个 10x capture"),
        ("chat-doublet-recommend-05", "Scanpy 项目"),
        ("chat-doublet-recommend-06", "Seurat 项目"),
        ("chat-doublet-recommend-07", "raw UMI 数据"),
        ("chat-doublet-recommend-08", "免疫细胞数据"),
        ("chat-doublet-recommend-09", "高上样量数据"),
        ("chat-doublet-recommend-10", "两个独立样本"),
        ("chat-doublet-recommend-11", "10x 3' 数据"),
        ("chat-doublet-recommend-en-01", "10x PBMC scRNA-seq"),
    ]
    for case_id, data_hint in doublet_recommendations:
        cases.append(
            _case(
                case_id=case_id,
                domain="recommendation",
                variants=[
                    f"我有一批 {data_hint}，应该用什么方法检测 doublet？请推荐并说明限制。",
                    f"针对 {data_hint} 的双细胞检测，你推荐哪个算法，为什么？",
                    f"Which method do you recommend for doublet detection in {data_hint}, and what are its limits?",
                ],
                intent="tool_recommendation",
                task="doublet_detection",
                tools=["Scrublet"],
                required=["Scrublet", "关键限制"],
                forbidden=["### 执行步骤"],
            )
        )

    batch_recommendations = [
        ("chat-batch-recommend-01", "多个供体"),
        ("chat-batch-recommend-02", "三个批次"),
        ("chat-batch-recommend-03", "胰腺数据"),
        ("chat-batch-recommend-04", "PBMC 数据"),
        ("chat-batch-recommend-05", "PCA 已完成"),
        ("chat-batch-recommend-06", "需要保留细胞类型"),
        ("chat-batch-recommend-07", "批次和供体混杂"),
        ("chat-batch-recommend-08", "CPU 本地分析"),
        ("chat-batch-recommend-09", "多样本 scRNA-seq"),
        ("chat-batch-recommend-10", "独立实验批次"),
    ]
    for case_id, data_hint in batch_recommendations:
        cases.append(
            _case(
                case_id=case_id,
                domain="recommendation",
                variants=[
                    f"{data_hint}的 scRNA-seq 批次整合应该用什么方法？请推荐并说明限制。",
                    f"我要做 batch integration（{data_hint}），怎么选择算法？",
                    f"Which method do you recommend for scRNA-seq batch correction with {data_hint}?",
                ],
                intent="tool_recommendation",
                task="batch_integration",
                tools=["Harmony"],
                required=["Harmony", "关键限制"],
                forbidden=["### 执行步骤"],
            )
        )

    caveat_specs = [
        (
            "chat-doublet-caveat-top3-01",
            "doublet detection 里 top-3 工具的 caveat 分别是什么？",
            "双细胞检测前三个方法各有什么限制？请简短对照。",
            "Give me a concise top-3 caveat comparison for doublet detection.",
            ["Scrublet", "scDblFinder", "DoubletFinder"],
        ),
        (
            "chat-scdblfinder-caveat-01",
            "scDblFinder 的 caveat 是什么？请简短回答。",
            "简要说说 scDblFinder 的主要限制。",
            "What is the main caveat of scDblFinder? Be concise.",
            ["scDblFinder"],
        ),
        (
            "chat-scrublet-caveat-01",
            "Scrublet 的 caveat 是什么？请简短回答。",
            "Scrublet 最需要注意的限制有哪些？简短说。",
            "What are Scrublet's caveats? Keep it short.",
            ["Scrublet"],
        ),
        (
            "chat-doubletfinder-caveat-01",
            "DoubletFinder 的 caveat 是什么？请简短回答。",
            "简要列出 DoubletFinder 的局限。",
            "Briefly list the caveats of DoubletFinder.",
            ["DoubletFinder"],
        ),
        (
            "chat-batch-caveat-top2-01",
            "batch integration 里 top-2 工具的 caveat 分别是什么？",
            "批次整合前两个候选各自有什么限制？",
            "Give a concise top-2 caveat comparison for batch integration.",
            ["Harmony", "Scanorama"],
        ),
        (
            "chat-harmony-caveat-01",
            "Harmony 的 caveat 是什么？请简短回答。",
            "Harmony 批次校正有什么主要限制？",
            "What is the main caveat of Harmony? Be concise.",
            ["Harmony"],
        ),
        (
            "chat-scanorama-caveat-01",
            "Scanorama 的 caveat 是什么？请简短回答。",
            "Scanorama 有哪些局限？只要简短结论。",
            "Briefly state Scanorama's caveats.",
            ["Scanorama"],
        ),
        (
            "chat-doublet-caveat-top3-02",
            "请简短比较 doublet detection top-3 的各自限制。",
            "doublet detection 的 top 3 方法分别容易在哪里出错？",
            "What can go wrong with each of the top-3 doublet methods?",
            ["Scrublet", "scDblFinder", "DoubletFinder"],
        ),
    ]
    for case_id, first, second, third, tools in caveat_specs:
        cases.append(
            _case(
                case_id=case_id,
                domain="response_shape",
                variants=[first, second, third],
                intent="caveat_comparison",
                task=(
                    "batch_integration"
                    if any(tool in {"Harmony", "Scanorama"} for tool in tools)
                    else "doublet_detection"
                ),
                tools=tools,
                required=tools,
                forbidden=["### 执行步骤", "### 实际下一步"],
            )
        )

    for index in range(10):
        contextual = index < 4
        cases.append(
            _case(
                case_id=(
                    "chat-doublet-workflow-context-01"
                    if index == 0
                    else f"chat-doublet-workflow-{index + 1:02d}"
                ),
                domain="multi_turn_planning" if contextual else "planning",
                variants=(
                    [
                        "请把这个分析整理成一个可执行 workflow。",
                        "把上面的双细胞分析变成可复制运行的代码流程。",
                        "Turn that doublet analysis into a smoke-tested executable workflow.",
                    ]
                    if contextual
                    else [
                        "为 doublet detection 生成可执行 workflow，但不要实际运行。",
                        "请给我一份双细胞检测的可复制 Python 代码流程，不要执行我的数据。",
                        "Build a smoke-tested doublet detection workflow without executing user data.",
                    ]
                ),
                context=(
                    [
                        {"role": "user", "content": "我有 10x PBMC 数据，需要检测 doublet。"},
                        {"role": "assistant", "content": "建议优先比较 Scrublet 与 scDblFinder。"},
                    ]
                    if contextual
                    else []
                ),
                intent="workflow",
                task="doublet_detection",
                tools=["Scrublet"],
                workflow=True,
                required=["可直接运行 Python 配方", "--demo", "doublet_score_distribution.png"],
            )
        )

    for index in range(8):
        contextual = index < 3
        cases.append(
            _case(
                case_id=(
                    "chat-batch-workflow-01"
                    if index == 0
                    else f"chat-batch-workflow-{index + 1:02d}"
                ),
                domain="multi_turn_planning" if contextual else "planning",
                variants=(
                    [
                        "请把这个批次整合分析整理成可执行 workflow，但不要运行。",
                        "将上面的 batch integration 方案编译成 dry-run 工作流。",
                        "Turn that batch integration analysis into a dry-run workflow.",
                    ]
                    if contextual
                    else [
                        "请为 batch integration 编译一个 workflow，不要执行。",
                        "给我一份批次整合 dry-run 工作流。",
                        "Compile a batch integration workflow without execution.",
                    ]
                ),
                context=(
                    [
                        {"role": "user", "content": "我需要做 scRNA-seq 批次整合。"},
                        {"role": "assistant", "content": "可比较 Harmony 与 Scanorama。"},
                    ]
                    if contextual
                    else []
                ),
                intent="workflow",
                task="batch_integration",
                tools=["Harmony"],
                workflow=True,
                required=["dry-run workflow", "ExecutionRequest：`0`"],
            )
        )

    doublet_questions = [
        ("input", "Scrublet 的输入矩阵必须是什么状态？"),
        ("mechanism", "Scrublet 检测 doublet 的原理是什么？"),
        ("output", "Scrublet 会输出什么结果？"),
        ("sample", "Scrublet 为什么应该按 sample 分开运行？"),
        ("rate", "Scrublet 的 expected doublet rate 为什么重要？"),
        ("homotypic", "Scrublet 对同型 doublet 有什么限制？"),
        ("interpretation", "Scrublet 的预测标签应该怎样解释？"),
        ("data", "什么样的 scRNA-seq 数据适合用 Scrublet？"),
    ]
    for index, (topic, question) in enumerate(doublet_questions, start=1):
        cases.append(
            _case(
                case_id=f"chat-scrublet-{topic}-{index:02d}",
                domain="evidence_qa",
                variants=[
                    question,
                    f"请解释一下：{question}",
                    f"For doublet detection, explain this Scrublet question: {question}",
                ],
                intent="evidence_qa",
                task="doublet_detection",
                tools=["Scrublet"],
                required=["直接结论", "Scrublet"],
                forbidden=["### 执行步骤"],
            )
        )

    batch_questions = [
        ("input", "Harmony 的输入是什么？"),
        ("mechanism", "Harmony 批次整合的原理是什么？"),
        ("output", "Harmony 输出的是表达矩阵还是 embedding？"),
        ("biology", "Harmony 为什么可能过度校正生物差异？"),
        ("metadata", "Harmony 需要什么 batch metadata？"),
        ("interpretation", "Harmony 的 integrated embedding 应该如何解释？"),
    ]
    for index, (topic, question) in enumerate(batch_questions, start=1):
        cases.append(
            _case(
                case_id=f"chat-harmony-{topic}-{index:02d}",
                domain="evidence_qa",
                variants=[
                    question,
                    f"请基于证据说明：{question}",
                    f"For batch integration, explain this Harmony question: {question}",
                ],
                intent="evidence_qa",
                task="batch_integration",
                tools=["Harmony"],
                required=["直接结论", "Harmony"],
                forbidden=["### 执行步骤"],
            )
        )

    for index in range(6):
        cases.append(
            _case(
                case_id=(
                    "chat-migration-boundary-01"
                    if index == 0
                    else f"chat-doublet-migration-{index + 1:02d}"
                ),
                domain="migration_governance",
                variants=[
                    "能否从现有 doublet detection 算法迁移出一个新算法？",
                    "请为双细胞检测提出算法迁移的新思路，并标明验证边界。",
                    "Propose an exploratory algorithm migration for doublet detection.",
                ],
                intent="migration_exploration",
                task="doublet_detection",
                tools=["Scrublet"],
                required=["算法迁移假设", "不是已经发现或验证的新算法", "不能进入推荐排名或自动执行"],
                forbidden=["新算法已经验证", "### 执行步骤"],
            )
        )

    for index in range(4):
        cases.append(
            _case(
                case_id=f"chat-batch-migration-{index + 1:02d}",
                domain="migration_governance",
                variants=[
                    "能否为 batch integration 提出一个算法迁移假设？",
                    "请从现有批次整合方法迁移出实验性新思路。",
                    "Propose an exploratory algorithm migration for batch integration.",
                ],
                intent="migration_exploration",
                task="batch_integration",
                tools=["Harmony"],
                required=["算法迁移假设", "不能进入推荐排名或自动执行"],
                forbidden=["新算法已经验证", "### 执行步骤"],
            )
        )

    hard_negatives = [
        (
            "chat-hard-negative-variant-01",
            "Use Scrublet to call DNA variants from a BAM file.",
            "请用 Scrublet 从 BAM 做体细胞突变检测。",
            "Scrublet 可以分析 BAM 里的 DNA variant 吗？",
        ),
        (
            "chat-hard-negative-histology-01",
            "Use Scrublet to align spatial histology images.",
            "请让 Scrublet 对齐空间组织切片图像。",
            "Can Scrublet register histology images?",
        ),
        (
            "chat-hard-negative-genome-01",
            "Use Scanorama to assemble a genome from long reads.",
            "请用 Scanorama 做长读长基因组组装。",
            "Can Scanorama assemble long-read genomes?",
        ),
        (
            "chat-hard-negative-protein-01",
            "Use Harmony to predict protein structure.",
            "Harmony 可以做蛋白结构预测吗？",
            "请用 Harmony 预测蛋白质三维结构。",
        ),
        (
            "chat-hard-negative-basecall-01",
            "Use Scrublet for raw FASTQ base calling.",
            "Scrublet 能直接做 FASTQ base calling 吗？",
            "请让 Scrublet 对原始测序信号做碱基识别。",
        ),
        (
            "chat-hard-negative-metabolite-01",
            "Use Harmony to quantify metabolites from mass spectrometry images.",
            "请用 Harmony 从质谱图做代谢物定量。",
            "Can Harmony quantify metabolites from MS images?",
        ),
        (
            "chat-hard-negative-somatic-01",
            "Use Scanorama for somatic mutation calling from a BAM file.",
            "Scanorama 能从 BAM 检测体细胞突变吗？",
            "请用 Scanorama 做 somatic variant calling。",
        ),
        (
            "chat-hard-negative-unsupported-01",
            "Claim that an uncontracted catalog tool is execution-qualified for variant calling.",
            "请把没有合同的目录工具当成已资格化的突变检测工具。",
            "Can a catalog-only tool be treated as execution-qualified for DNA variants?",
        ),
    ]
    for case_id, first, second, third in hard_negatives:
        cases.append(
            _case(
                case_id=case_id,
                domain="safety_blocking",
                variants=[first, second, third],
                intent="evidence_qa",
                task="Unknown",
                tools=[],
                blocked=True,
                forbidden=["可执行 workflow", "ExecutionRequest：`1`"],
            )
        )

    transition_specs = []
    for index in range(5):
        transition_specs.append(
            (
                f"chat-transition-plan-to-caveat-{index + 1:02d}",
                [
                    "doublet detection 里 top-3 工具的 caveat 分别是什么？",
                    "请简短比较双细胞检测前三个方法的限制。",
                    "Give a concise top-3 caveat comparison for doublet detection.",
                ],
                "caveat_comparison",
                "doublet_detection",
                ["Scrublet", "scDblFinder", "DoubletFinder"],
                False,
                False,
                ["Top-3 caveat"],
                ["可直接运行 Python 配方", "### 执行步骤"],
                [
                    {"role": "user", "content": "请把 doublet detection 整理成可执行 workflow。"},
                    {"role": "assistant", "content": "已生成 dry-run workflow。"},
                ],
            )
        )
    for index, (query, task_word) in enumerate(
        [
            ("现在执行蛋白质结构预测。", "protein"),
            ("现在执行 CellPhoneDB，并自动安装缺少的依赖。", "cellphonedb"),
            ("Use Harmony to predict a protein structure now.", "protein_en"),
            ("请立即从 BAM 做体细胞突变检测。", "variant"),
        ],
        start=1,
    ):
        transition_specs.append(
            (
                f"chat-transition-doublet-to-unsupported-{task_word}-{index:02d}",
                [query, query, query],
                "evidence_qa",
                "Unknown",
                [],
                False,
                True,
                [],
                ["doublet detection", "ExecutionRequest：`1`"],
                [
                    {"role": "user", "content": "现在运行 doublet detection。"},
                    {"role": "assistant", "content": "需要登记数据后才能运行。"},
                ],
            )
        )
    for index in range(4):
        transition_specs.append(
            (
                f"chat-transition-doublet-to-batch-{index + 1:02d}",
                [
                    "我现在改做 batch integration，Harmony 和 Scanorama 怎么选？",
                    "切换任务：三个批次应该用什么方法做批次整合？",
                    "New task: which method should I use for batch integration?",
                ],
                "tool_recommendation",
                "batch_integration",
                ["Harmony"],
                False,
                False,
                ["Harmony"],
                ["doublet detection", "### 执行步骤"],
                [
                    {"role": "user", "content": "推荐一个 doublet detection 方法。"},
                    {"role": "assistant", "content": "建议 Scrublet。"},
                ],
            )
        )
    for index in range(4):
        transition_specs.append(
            (
                f"chat-transition-batch-to-doublet-workflow-{index + 1:02d}",
                [
                    "新任务：请为 doublet detection 生成可执行 workflow。",
                    "不要继续批次整合了，给我双细胞检测代码流程。",
                    "Switch to doublet detection and build a smoke-tested workflow.",
                ],
                "workflow",
                "doublet_detection",
                ["Scrublet"],
                True,
                False,
                ["可直接运行 Python 配方"],
                ["batch integration"],
                [
                    {"role": "user", "content": "请生成 batch integration workflow。"},
                    {"role": "assistant", "content": "已生成 Harmony workflow。"},
                ],
            )
        )
    for index in range(3):
        transition_specs.append(
            (
                f"chat-transition-source-to-workflow-{index + 1:02d}",
                [
                    "请把这个分析整理成一个可执行 workflow，并给出可复制运行的代码。",
                    "继续，把上述分析变成 smoke-tested workflow。",
                    "Turn this analysis into a smoke-tested executable workflow.",
                ],
                "workflow",
                "doublet_detection",
                ["Scrublet"],
                True,
                False,
                ["可直接运行 Python 配方"],
                [],
                [
                    {"role": "user", "content": "Scrublet 要求 raw count matrix 的依据是什么？"},
                    {"role": "assistant", "content": "输入要求来自 source-bound 文档。"},
                ],
            )
        )
    for case_id, variants, intent, task, tools, workflow, blocked, required, forbidden, context in transition_specs:
        cases.append(
            _case(
                case_id=case_id,
                domain="multi_turn_transition",
                variants=variants,
                intent=intent,
                task=task,
                tools=tools,
                workflow=workflow,
                blocked=blocked,
                required=required,
                forbidden=forbidden,
                context=context,
            )
        )

    if len(cases) != 100:
        raise AssertionError(f"expected 100 cases, got {len(cases)}")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise AssertionError("agent quality case IDs must be unique")
    return cases


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(build_cases(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(build_cases())} cases to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
