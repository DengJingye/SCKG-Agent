# scKG-Agent V3 Benchmark Sources

Status: Phase 1.1 survey, Phase 2 pilot source registry, and Phase 2.1 bounded
paper/notebook source review, updated 2026-09-21.

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
| [Benchmarking LLM-based agents for single-cell omics analysis](https://link.springer.com/article/10.1186/s13059-026-03998-z) ([official code](https://github.com/lyyang01/bioagent-benchmark)) | 50 representative tasks, each pairing a core single-cell analysis tool, a real-world public dataset, a prompt, a reference script, and reference outputs; task types span scRNA-seq, spatial, ATAC, perturbation, and multi-omics workflows. | 17 component metrics plus a weighted total score across program synthesis, collaboration/execution, knowledge integration, and completion; logs and final outputs feed automated evaluation, with AST/ROUGE, execution-grounded checks, LLM judges, and selected manual checks. | Prompt tiers, alternate datasets, repeated runs, and removal of retrieval, planning, reflection, or workflow-control modules. | Fourteen log-derived error types are grouped into system design, collaboration/scheduling, environment/input, and core module/model capability. Three LLMs vote on log evidence and experts verify a 10% sample. This is the closest surveyed precedent for single-cell module ablation and trace-grounded failure attribution, but its error taxonomy is not a substitute for scKG's stage boundaries. |
| [BioAgent Bench](https://arxiv.org/abs/2601.21800) ([official task repository](https://github.com/bioagent-bench/bioagent-bench), [official experiment repository](https://github.com/bioagent-bench/bioagent-experiments)) | Ten manually curated, end-to-end bioinformatics pipelines with prompts, inputs/reference data, expected artifacts, reference implementations, and resource bounds; domains include RNA-seq, variant calling, metagenomics, and single-cell analysis. | An LLM grader reports steps completed/required, final artifact reached, task-specific result match, and GIAB F1 where applicable; completion rate is primary, while repeated-run output stability uses Jaccard/Pearson. | Multiple model+harness systems; explicit plan-only assessment; four-run stability; prompt bloat, corrupted input, and decoy-input perturbations. No reported component-removal ablation in the inspected release. | Trace inspection distinguishes corruption detection, unsafe continuation, decoy use, shallow filename selection, error loops, and premature termination. It is strong for execution/artifact and robustness testing, but comprehensive expert adjudication and a frozen stage-level failure taxonomy are not provided. |
| [PromptBio-Bench](https://www.biorxiv.org/content/10.64898/2026.05.05.723092v2) ([official evaluator](https://github.com/PromptBio/promptbio-bench), [official task release](https://huggingface.co/datasets/promptbio-ai/promptbio-bench-data)) | Version 2 contains 244 expert-designed and validated task capsules: 131 bioinformatics and 113 data-science tasks, each with prompt, domain-format inputs, an expert reference answer, and an evaluation guide; difficulty is assigned by repeated three-model voting. | File validation followed by format-specific exact/approximate/summary/functional/semantic comparison; task score is the mean file similarity in `[0,1]`, failed/missing/unparseable output scores zero, and runtime/token cost are retained. | Agent comparisons and low/medium/high difficulty slices under a single-pass protocol. The inspected release reports neither controlled robustness perturbations nor module ablations. | Strong precedent for heterogeneous artifact scoring and explicit expert reference files. Failure analysis is chiefly completion/accuracy by task and difficulty; no stage-level root-cause attribution is released. Public tasks/reference artifacts make contamination accounting necessary for reuse. |
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

### 2.3 Phase 1.1 audit matrix for the three requested benchmarks

The matrix distinguishes an explicitly reported control from an absence in the
inspected paper/repository release. “Not reported” must not be read as evidence
that a control was not used internally.

| Audit dimension | Genome Biology 2026 single-cell benchmark | BioAgent Bench | PromptBio-Bench v2 |
| --- | --- | --- | --- |
| Task construction | 50 tool-centered analysis tasks with standardized prompts, public datasets, scripts, and reference outputs. | Ten manually curated end-to-end pipelines selected for common workflows and bounded to under four hours/48 GB. | 244 expert-designed/validated task capsules across bioinformatics and data science; prompts emulate platform requests without dictating tools unless required. |
| Real / synthetic data | Main tasks use real-world public single-cell datasets; robustness adds alternate real datasets. No synthetic main-task stratum is reported. | Mixed: real/public biological datasets and consensus truth where available, plus a simulated RNA-seq task; perturbations and some decoys are synthetic. | Input files are curated to represent real-world analyses, but the inspected release does not publish a real-versus-synthetic input census. |
| Evaluation metrics | 17 metrics plus weighted total across four capability dimensions; includes plan/code quality, time/interaction, RAG trigger/retrieval, completion, and result consistency/biological checks. | Step completion rate; final artifact reached; rubric-based result match; GIAB F1; repeated-run Jaccard/Pearson; plan score. | Completion, normalized file similarity/accuracy, wall time, and token use; exact, approximate, summary, functional, correlation/set/distance, and LLM semantic strategies. |
| Execution/artifact scoring | Full execution logs and final computational/visual outputs; AST/ROUGE plus preprocessing re-execution and selected binary manual checks. | Sandboxed hashed run directories; intermediate/final artifacts and paths supplied to an LLM grader; four tasks additionally have binary-verifiable outputs. | Validates existence, magic-byte/format compliance, and parsability before per-format artifact comparison; multi-file score is an unweighted mean. |
| Robustness tests | Three prompt-detail tiers, alternate datasets for 13 task/tool categories, and multiple runs under the same evaluation metrics. | Multiple trials plus prompt bloat, corrupted inputs, and decoy files; perturbation behavior is manually inspected. | Difficulty stratification is reported, but evaluation is single pass; the paper explicitly lists replicate and interactive testing as future work. No controlled perturbation suite is reported. |
| Module ablation | Disables retrieval, planning, reflection, and workflow control, subject to framework applicability. | No component-removal study is reported; the plan-only analysis is a capability comparison, not a module ablation. | No module ablation is reported; agent defaults are compared without task-specific customization. |
| Failure attribution | Fourteen types from logs, grouped into four higher-level families; interrupted runs are rerun before classification. | Manual trace analysis identifies perturbation-specific behaviors; no exhaustive fixed stage taxonomy. | Failure heatmaps and completion/accuracy gaps by task/difficulty; no root-cause stage attribution. |
| Human/expert adjudication | Expert scoring contributes 20% to RAG-trigger accuracy on 13 tasks; selected checks combine manual+LLM review; experts verify a random 10% of LLM-voted failure labels. | The task suite is manually curated and perturbation traces are manually inspected; the paper says comprehensive domain-expert manual grading was impractical and uses GPT-5.1 as the principal grader. | Experts design/validate tasks and produce references; text/image LLM-judge outputs receive expert review, while the paper notes a need for expanded review in ambiguous cases. |
| Contamination control | No benchmark-exposure or verbatim-overlap control is reported in the inspected article/repository. Public prompts, data, code, and results require an external exposure ledger for reuse. | No explicit pretraining contamination control is reported; tasks and resources are publicly released, and experimental agents have internet access. | No explicit memorization/contamination experiment is reported. Public release includes prompts, inputs, expert answers, and scripts, so future reuse must record exposure and transformation distance. |

Implications for V3 are deliberately narrow: borrow execution-grounded checks,
controlled perturbations, module ablations, expert spot checks, and format-aware
artifact comparison. Do not import any benchmark task as Gold, and attach
`public_exposure`, `verbatim_overlap`, `transformation_distance`, and
`memorization_risk` to any transformed public candidate.

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

No source below is authorized for bulk collection by this document. The only
current collection authorization is the bounded Phase 2 pilot in
`policy_decisions.md`: one official GitHub API page for each of the two
allowlisted repositories plus project-owned controlled probes. A collector must
record the source-specific access decision in
`license_or_access_policy`, use the most conservative permitted storage mode,
and obey robots rules, API terms, response headers, and removal requests.

| Source | Question origin | Intended seed signal | Preferred access path | Current license/access status | Priority and caveats |
| --- | --- | --- | --- | --- | --- |
| [scverse Discourse](https://discourse.scverse.org/) | `real-user` | Scanpy/anndata/scverse usage questions, state mismatches, errors, and workflow uncertainty. Scanpy's [community guide](https://scanpy.readthedocs.io/en/latest/community.html) explicitly directs usage questions to Discourse. | None for this pilot. | `prohibited` for automated pilot collection: the reviewed [Terms of Service](https://discourse.scverse.org/tos) prohibit automated forum access except public-search-engine indexing. No JSON/RSS request is made. | P0 relevance, policy-blocked. Reconsider only after explicit written authorization or a terms change. Replies remain context, never automatic Gold. |
| [Scanpy GitHub issues](https://github.com/scverse/scanpy/issues) | `real-user` | Bug reports, documentation gaps, feature requests, version-specific failures. The official community guide distinguishes these from general usage questions. | Official GitHub REST `List repository issues`; exclude pull requests/bots and never request comments. | `reviewed` for this pilot under the [GitHub API Terms](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms), [Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies), and [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api). Store title plus non-personal issue metadata only. | P0 pilot allowlist. Do not treat maintainer discussion, labels, closure, or issue state as scientific Gold. |
| [Seurat repository/issues](https://github.com/satijalab/seurat/issues) and [official site](https://satijalab.org/seurat/) | `real-user` | R/Seurat workflow, object-state, integration, visualization, and version migration problems. | Official GitHub REST `List repository issues`; exclude pull requests/bots and never request comments. | `reviewed` for the same title-only GitHub pilot profile as Scanpy. | P0 pilot allowlist. Preserve repository timestamps and any version visible in the title; issue state or maintainer replies are not Gold. |
| [Biostars](https://www.biostars.org/) | `real-user` | Broad, naturally phrased bioinformatics troubleshooting, method choice, and ambiguous experimental questions. | Manual discovery first; automated endpoint only after terms/robots/license review. | Access-policy review pending. Store URL and metadata only until an explicit policy decision exists. | P1. Very broad domain and variable answer quality; high PII and stale-version risk. |
| [Bioconductor Support](https://support.bioconductor.org/) | `real-user` | Package-specific R/Bioconductor questions, reproducibility, statistical scope, and versioned failures. The site exposes RSS/API links and a user agreement. | Official RSS/API if policy review permits; otherwise manual canonical URLs. | Access-policy and user-agreement review pending; no batch access in Phase 1. | P1. Strong expert replies, but accepted/high-vote replies still are not answer Gold. Spam and package-version drift require filtering. |
| Approved method GitHub issue trackers | `real-user` | Long-tail method-specific failures and capability boundaries for methods represented in the governed tool registry. | GitHub REST Issues API from an explicit repository allowlist; exclude pull requests, security reports, and bot-only issues. | Same GitHub policy capture as above; no broad GitHub search scrape. | P1. Start only after method identity is matched to the canonical tool registry. Activity is not recommendation-grade scientific evidence. |
| [BixBench official dataset](https://huggingface.co/datasets/futurehouse/BixBench) | `paper-notebook` | Hypothesis-driven computational-biology result questions grounded in published notebook capsules. | Pinned public Hugging Face dataset revision; retain only a bounded task-text excerpt and non-answer provenance. | `reviewed` for the bounded Phase 2.1 pilot: dataset card declares `Apache-2.0`; frozen revision `f8cc3bdcc6357c88b8c3648306522b9c422dc95a`. | Four raw seeds only. Do not retain `ideal`, `result`, `answer`, distractors, capsule data, or use upstream scoring as scKG Gold. |
| [ScienceAgentBench official dataset](https://huggingface.co/datasets/osunlp/ScienceAgentBench) | `paper-notebook` | Data-driven scientific program tasks with explicit output-artifact requirements. | Pinned public verified annotation release through the official Hugging Face dataset viewer. | `reviewed` for the bounded Phase 2.1 pilot: dataset card declares `CC-BY-4.0`; frozen revision `9c6e96c9e74572e979b0930ee735041cef528cb7`. | Four raw seeds only. Store the public task instruction with attribution; do not download or redistribute protected benchmark artifacts, Gold programs, domain knowledge, results, or rubrics. |
| Other published notebooks and paper supplements represented by CORE-Bench or a reviewed local source | `paper-notebook` | Reproducible analysis goals, expected artifacts, and long-horizon task structure. | Versioned benchmark release or paper repository, never an unfrozen web copy. | Registry only until source-specific license, artifact reuse, and storage review is complete. | P1 for scenario design. Not a real-user distribution and never automatically Gold. |
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

If any item is unresolved, the source remains `registry_only`. The current
pilot performs only the two reviewed GitHub calls documented in its manifest;
it creates no DEV or Gold labels.

For Phase 2.1, the existing 48-seed pilot is not expanded by another issue
collection. Eight paper/notebook records are a separate bounded source pilot in
`paper_notebook_seeds_pilot.jsonl`. Its revisions, licenses, retained fields,
and exclusions are frozen in `paper_notebook_collection_manifest.json`.
