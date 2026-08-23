# scKG-Agent Figures

This directory stores version-controlled figure sources and exported assets.

## Figure Set

| Figure | Source | Purpose |
| --- | --- | --- |
| Authoritative product figure | `scKG_product_mainline_v2_7_2.dot` | Current ASK/PLAN/RUN product loop and deterministic safety boundary. |
| Historical Figure 1 | `scKG_current_agent_orchestration.dot` | Legacy recommendation-workflow architecture; not the current product entry. |
| Historical Figure 2 | `scKG_target_hybrid_agent_architecture.dot` | Earlier target design; retained for architecture-evolution discussion only. |
| Supporting Figure 3 | `scKG_hybrid_kg_rag_flow.dot` | Evidence-governed retrieval subsystem, not the whole product architecture. |

## Rendering

```bash
dot -Tsvg docs/figures/scKG_product_mainline_v2_7_2.dot -o docs/figures/scKG_product_mainline_v2_7_2.svg
dot -Tpng -Gdpi=180 docs/figures/scKG_product_mainline_v2_7_2.dot -o docs/figures/scKG_product_mainline_v2_7_2.png
dot -Tpdf docs/figures/scKG_product_mainline_v2_7_2.dot -o docs/figures/scKG_product_mainline_v2_7_2.pdf
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

## Chinese Caption

当前主图：scKG-Agent 2.7.2 的本地受治理科研闭环。自然语言目标和登记数据通过 ASK/PLAN/RUN 入口进入数据画像、Action Space、WorkflowPlan、确定性 Router 和逐请求审批；只有通过 gate 的请求才能进入固定 Python/R wrapper、Validator、有限 Repair、Pareto 与 Level 2 复现交付。LLM 只能提出候选或组织表达，不能覆盖证据、授权和执行边界。
