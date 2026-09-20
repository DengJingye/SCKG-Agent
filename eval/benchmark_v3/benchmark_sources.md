# scKG-Agent V3 Benchmark Sources

Status: Phase 1 survey and source registry, updated 2026-09-20.

This document inventories benchmark construction patterns and potential question
sources. It does not define a DEV, evaluation, hidden, or Gold set. Public forum
questions and benchmark tasks are raw source material only; they must not be
treated as scientific answer Gold without independent adjudication.

## 1. Survey method and scope

The survey prioritizes primary papers, official benchmark repositories, and
official project documentation. A benchmark is included when it informs at
least one of the following:

- authentic computational-biology or scientific-analysis task construction;
- controlled execution and artifact-based scoring;
- knowledge/retrieval ablations;
- partial-credit or failure-localization methods;
- contamination, split, or reproducibility controls.

Leaderboard values are deliberately omitted. Before any benchmark is imported
or rerun, its exact dataset release, license, container image, evaluator version,
and task digest must be frozen separately.

## 2. Benchmark survey

### 2.1 Directly relevant agent benchmarks

| Benchmark | Task construction and source data | Metrics/evaluation | Reported comparison or ablation | Failure attribution and scKG relevance |
| --- | --- | --- | --- | --- |
| [BixBench](https://github.com/Future-House/BixBench) | Computational-biology questions derived from published Jupyter notebooks and associated data capsules; agentic tasks require dataset exploration, Python/R/Bash execution, and scientific interpretation. The current official repository describes 205 questions from 60 notebooks. | Exact match for MCQ; LLM-based grading for open answers; agent trajectories and replicated runs are retained by the harness. | Agentic versus zero-shot; open answer versus MCQ; with/without image support; refusal option; multiple replicas and majority vote. | Strong source for `paper-notebook` questions and long-horizon execution shapes. Official aggregate grading does not by itself isolate scKG retrieval, scope, evidence, or state failures, so scKG must retain its own trace-grounded attribution. |
| [ScienceAgentBench](https://github.com/OSU-NLP-Group/ScienceAgentBench) ([paper](https://arxiv.org/abs/2410.05080)) | 102 data-driven scientific tasks extracted from 44 peer-reviewed papers in four disciplines and reviewed by subject-matter experts. Every task targets a self-contained Python program. | Valid execution, task-specific success, code quality, cost, and saved execution artifacts; the official repository provides a containerized harness and a verified dataset release. | Direct prompting, self-debug, and OpenHands CodeAct; with/without expert-provided knowledge; repeated attempts. | Separates execution from result success and cost, but its failure categories are coarser than scKG stages. Useful for controlled program artifacts and a knowledge-availability ablation, not as real-user question Gold. |
| [DiscoveryBench](https://github.com/allenai/discoverybench) ([paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/0d70af566e69f1dfb687791ecf955e28-Paper-Conference.pdf)) | Real and synthetic datasets paired with a discovery goal; solving requires statistical analysis plus semantic reasoning. Gold hypotheses and workflows are represented separately. | Faceted open-answer evaluation compares predicted hypotheses/workflows with their Gold counterparts, enabling partial rather than all-or-nothing scoring. | Coder versus ReAct-style agents; optional domain knowledge and workflow tags; real versus synthetic task slices. | The facet design is useful for separating evidence, scope, synthesis, and planning. The benchmark still does not provide scKG-native source authority or controlled-execution governance. |
| [CORE-Bench](https://github.com/siegelz/core-bench) ([paper](https://openreview.net/pdf?id=BsMMc4MEGS)) | 270 computational-reproducibility tasks from 90 papers across computer science, social science, and medicine. Agents navigate author repositories, install dependencies, run code, and answer result questions in isolated environments. | Accuracy at three difficulty levels, with language-only and vision-language tasks; official harness records reproducible container/VM runs. | Easy/medium/hard information and execution conditions; general-purpose versus task-specific agent; different base models. | Difficulty tiers reveal whether failure occurs before execution or after result production, but not a full root-cause stage. Useful for environment freezing, artifact replay, and reproducibility boundaries. |
| [PaperBench](https://openai.com/index/paperbench/) ([official repository](https://github.com/openai/frontier-evals/tree/main/project/paperbench)) | End-to-end replication of 20 ICML 2024 papers from the paper and approved assets; original code locations are blacklisted. Author-developed hierarchical rubrics decompose replication requirements. | Rollout, clean-container reproduction, and rubric grading are separate phases; hierarchical partial credit covers code development, execution, and result analysis. Judge quality is tested separately by JudgeEval. | Agent/scaffold and model comparisons; per-paper rubric breakdowns. | Strong precedent for hiding rubrics from the agent, replaying in a clean environment, and separating build/execution/result failures. It is outside bioinformatics and too long-horizon to use directly as the V3 question bank. |

### 2.2 Component and capability benchmarks

| Benchmark | Task construction and source data | Metrics/evaluation | Reported comparison or ablation | Failure attribution and scKG relevance |
| --- | --- | --- | --- | --- |
| [LAB-Bench](https://github.com/Future-House/LAB-Bench) ([paper](https://arxiv.org/abs/2407.10362)) | Practical biology research capabilities across literature, databases, figures, tables, protocols, sequences, and cloning. The public repository exposes about 80% and retains a private subset for contamination monitoring. | Accuracy, precision, and coverage overall and per subset; questions are multiple choice and can include an insufficient-information option. | Multiple provider/model agent configurations and task-subset slices. | Useful for refusal/coverage and biology capability strata. It does not test long-horizon stateful execution or evidence-governed synthesis. |
| [BioCoder](https://github.com/gersteinlab/biocoder) ([paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11211839/)) | Bioinformatics functions and methods extracted from real GitHub projects plus Rosalind problems; surrounding package, class, and global context is preserved. | Pass@k backed by manual tests, unit tests, and fuzz testing. | Model comparisons and context-sensitive code-generation settings. | Useful for deterministic execution validation and realistic code context. It is a code-completion benchmark, not a retrieval/evidence/planning benchmark. |
| [SciCode](https://github.com/scicode-bench/SciCode) ([paper](https://arxiv.org/abs/2407.13168)) | Scientist-curated research coding problems decomposed into subproblems across scientific domains, with annotated background, solutions, and tests. | Main-problem and subproblem resolve rates through executable tests. | With/without scientist background; full problem versus decomposed subproblems; model comparisons. | Decomposition provides useful planning diagnostics. It does not preserve real-user provenance and does not distinguish knowledge retrieval from synthesis unless the harness is extended. |

## 3. Patterns adopted for scKG V3

The survey supports the following Phase 1 design choices:

1. Preserve the source and task-construction lineage before any labels are added.
2. Keep raw question collection separate from candidate scenario generation and
   expert Gold adjudication.
3. Freeze corpus, model, prompt, contract, environment, and evaluator versions
   before a comparison.
4. Use paired inputs and shared budgets for LLM, RAG, Legacy KG, and Scientific
   KG v2 comparisons.
5. Score retrieval, source authority, synthesis, planning, and execution with
   their own applicable denominators; do not replace missing measurements with
   zero or a synthetic score.
6. Preserve trajectories and artifacts so an aggregate failure can be assigned
   to its earliest supported stage.
7. Treat refusal/clarification and out-of-knowledge behavior as first-class
   outcomes rather than forcing every question to have an answer.

These choices extend, rather than replace, the existing contracts in
`core/evaluation_models.py`, `core/open_world_evaluation_models.py`,
`eval/evaluation_evaluators.py`, and `docs/eval/RESEARCH_EVAL_PROTOCOL.md`.

## 4. Real-world question source registry

No source below is authorized for batch collection by this document. A future
collector must first record the source-specific access decision in
`license_or_access_policy`, use the most conservative permitted storage mode,
and obey robots rules, API terms, response headers, and removal requests.

| Source | Question origin | Intended seed signal | Preferred access path | License/access status for Phase 1 | Priority and caveats |
| --- | --- | --- | --- | --- | --- |
| [scverse Discourse](https://discourse.scverse.org/) | `real-user` | Scanpy/anndata/scverse usage questions, state mismatches, errors, and workflow uncertainty. Scanpy's [community guide](https://scanpy.readthedocs.io/en/latest/community.html) explicitly directs usage questions to Discourse. | Official Discourse JSON/RSS endpoints when permitted; canonical topic URL retained. | Registry only. Policy and redistribution review required before storing bodies; default to title/metadata until reviewed. | P0. High relevance, but a thread is context rather than a single Gold answer. Replies may conflict or become stale. |
| [Scanpy GitHub issues](https://github.com/scverse/scanpy/issues) | `real-user` | Bug reports, documentation gaps, feature requests, version-specific failures. The official community guide distinguishes these from general usage questions. | GitHub REST Issues API; exclude pull requests; retain repository, issue number, state, timestamps, and canonical URL. | Public API metadata is accessible subject to [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api); content storage and reuse still require per-record policy capture. | P0. Do not treat maintainer discussion or issue closure as scientific Gold. |
| [Seurat repository/issues](https://github.com/satijalab/seurat/issues) and [official site](https://satijalab.org/seurat/) | `real-user` | R/Seurat workflow, object-state, integration, visualization, and version migration problems. | GitHub REST Issues API plus official documentation links for provenance; exclude pull requests. | Registry only; GitHub policy applies. | P0. Preserve Seurat/package version because older object/API behavior is common. |
| [Biostars](https://www.biostars.org/) | `real-user` | Broad, naturally phrased bioinformatics troubleshooting, method choice, and ambiguous experimental questions. | Manual discovery first; automated endpoint only after terms/robots/license review. | Access-policy review pending. Store URL and metadata only until an explicit policy decision exists. | P1. Very broad domain and variable answer quality; high PII and stale-version risk. |
| [Bioconductor Support](https://support.bioconductor.org/) | `real-user` | Package-specific R/Bioconductor questions, reproducibility, statistical scope, and versioned failures. The site exposes RSS/API links and a user agreement. | Official RSS/API if policy review permits; otherwise manual canonical URLs. | Access-policy and user-agreement review pending; no batch access in Phase 1. | P1. Strong expert replies, but accepted/high-vote replies still are not answer Gold. Spam and package-version drift require filtering. |
| Approved method GitHub issue trackers | `real-user` | Long-tail method-specific failures and capability boundaries for methods represented in the governed tool registry. | GitHub REST Issues API from an explicit repository allowlist; exclude pull requests, security reports, and bot-only issues. | Same GitHub policy capture as above; no broad GitHub search scrape. | P1. Start only after method identity is matched to the canonical tool registry. Activity is not recommendation-grade scientific evidence. |
| Published notebooks and paper supplements represented by BixBench, ScienceAgentBench, CORE-Bench, or a reviewed local source | `paper-notebook` | Reproducible analysis goals, expected artifacts, and long-horizon task structure. | Versioned benchmark release or paper repository, never an unfrozen web copy. | Import only under the upstream license and with release/digest capture. | P1 for scenario design. Not a real-user distribution and never automatically Gold. |
| Local deterministic safety, state, and contract probes | `controlled-probe` | Coverage of authorization, malformed state, evidence leakage, out-of-scope execution, and hard negatives. | Reviewed local fixtures under version control. | Project-owned; record generator/version and reviewer. | P0 for coverage gaps, but must be reported separately from real-user questions. |

## 5. Source acceptance gate

A source may progress from registry entry to a collection pilot only when all of
the following are recorded:

- stable source name and canonical entry point;
- access method and applicable policy/terms URL;
- permitted storage granularity (`metadata_only`, `title_only`, `excerpt`, or
  `full_text`);
- rate-limit and retry behavior where an API is used;
- PII/redaction procedure and author-handle policy;
- version/time fields needed to interpret the question;
- removal/tombstone procedure;
- a small manual sample showing that the source contributes in-scope questions.

If any item is unresolved, the source remains `registry_only`. Phase 1 performs
no batch retrieval and creates no DEV or Gold labels.
