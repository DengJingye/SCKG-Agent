# scKG-Agent Figures

This directory stores version-controlled figure sources and exported assets.

## Figure Set

| Figure | Source | Purpose |
| --- | --- | --- |
| Figure 1 | `scKG_current_agent_orchestration.dot` | Current centralized StateGraph orchestration, Graphviz draft. |
| Figure 2 | `scKG_target_hybrid_agent_architecture.dot` | Target governed hybrid scientific agent architecture, Graphviz draft. |
| Figure 3 | `scKG_hybrid_kg_rag_flow.dot` | Evidence-governed Hybrid KG-RAG / GraphRAG flow, Graphviz draft. |
| Figure 1 publication | `scKG_current_agent_orchestration_publication.svg` | Polished Python/matplotlib version for manuals and paper drafts. |
| Figure 2 publication | `scKG_target_hybrid_agent_architecture_publication.svg` | Polished Python/matplotlib version for manuals and paper drafts. |
| Figure 3 publication | `scKG_hybrid_kg_rag_flow_publication.svg` | Polished Python/matplotlib version for manuals and paper drafts. |

## Rendering

```bash
cd /Users/lris/Desktop/scKG_agent/SCKG-Agent
bash docs/figures/render_figures.sh
```

The script exports `.svg`, `.pdf`, and `.png` files when Graphviz is available.

For the publication-style versions:

```bash
cd /Users/lris/Desktop/scKG_agent/SCKG-Agent
bash docs/figures/render_publication_figures.sh
```

The publication renderer follows the local Nature-style figure workflow:

- Python/matplotlib backend;
- white background;
- restrained palette;
- editable SVG text;
- SVG/PDF/PNG export bundle.

## Design Notes

- Keep `.dot` files as the editable source of truth.
- Use `*_publication.svg` as the preferred manual/paper draft asset.
- Use `.svg` for manuals, web docs, and Illustrator refinement.
- Use `.pdf` for manuscript submission or LaTeX.
- Use `.png` for quick previews and slides.
- Keep labels short and mostly English for paper readiness and font stability.

## Chinese Captions

Figure 1: 当前 scKG-Agent 编排图。该图展示当前系统是一个中心化 `StateGraph` 工作流，包含意图解析、硬约束检索、证据门控、MCDM 排序、迁移假设、报告生成和语义审计。

Figure 2: 目标混合型科研 Agent 架构图。该图展示未来系统应采用中心化治理加专职 agent / typed tools / MCP tools 的混合架构，而不是去中心化多 Agent。

Figure 3: 证据治理型 Hybrid KG-RAG 流程图。该图展示 formal evidence、KG、BM25、dense retrieval、RRF、治理精排、EvidenceContextPack、MCDM 和 semantic auditor 之间的关系。
