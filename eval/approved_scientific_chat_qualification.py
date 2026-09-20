"""Six synthetic ASK turns for approved-v2 integration; never Agent Gain."""
import argparse
from pathlib import Path
from eval.research_chat_qualification import run

JOURNEYS = {
    "hvg_followup": [
        "Scanpy 1.11.2 的 highly_variable_genes：flavor=seurat_v3 应输入 counts 还是 logarithmized 数据？请给出条件和原文依据。",
        "那改成 flavor=seurat 呢？输入要求是否变化？请更新引用。",
    ],
    "scrublet_caution": ["Scrublet 如果缺失 parent singlet state，是否属于硬性输入要求、必须禁止运行？还是 detectability caution？请结合原文解释。"],
    "cellrank_causal": ["在 scRNA-seq 中，CellRank 找到的 putative lineage driver 能直接称为 causal driver 吗？请解释因果边界并给证据。"],
    "outside_kg": ["在单细胞 RNA-seq 中，如何用 causal forest 估计药物处理对细胞状态的异质性效应？如果当前 Scientific KG 不覆盖，请明确区分模型通识。"],
    "pca_conditions": ["Scanpy 1.11.2 PCA：chunked=true；chunked=false 且 zero_center=true；zero_center=false，分别能作什么结论？请保留完整条件。"],
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--journey", action="append", choices=tuple(JOURNEYS))
    args = parser.parse_args()
    run(args.output, profile="scientific_kg", only=args.journey, journeys=JOURNEYS)
