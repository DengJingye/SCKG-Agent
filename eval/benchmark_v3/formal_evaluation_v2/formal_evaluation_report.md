# scKG-Agent V3 formal evaluation v2 report

## Validity

Provider-clean, lane-isolated formal run: **True**. Failed provider calls: 0. Lane isolation: True; runtime receipts: True. The invalid v1 experiment is not pooled with this experiment.

## Dataset, review, freeze, and leakage

36 unchanged scenarios: K=24, O=8, W=4. Runtime `f3df9056364200fdc114d9cfd8d71fa76b915219`. Freeze manifest `7e6f4593b5218c5b5cb0d4770277277cc3b6af48cee487c8959097f47654ff6e`. Two isolated AI-assisted scenario reviews and a separate adjudication were reused byte-for-byte from the original freeze; answer scoring used two isolated lane-blind AI-assisted passes plus disagreement adjudication. No human review is claimed. DEV scenario, family, and source-thread exact-overlap gates passed before the original freeze. Public exposure remains recorded and transformation is not treated as decontamination.

## Absolute track results

| Lane | K condition-correct | O useful | W task success |
|---|---:|---:|---:|
| llm_only | 34.7% | 66.7% | 41.7% |
| generic_rag | 31.9% | 41.7% | 25.0% |
| legacy_kg | 36.1% | 33.3% | 41.7% |
| scientific_kg | 58.3% | 50.0% | 41.7% |

No cross-track composite score is calculated.

## K detail

| Lane | Fact recall | Scope error | Unsupported claim | Paired-condition pass |
|---|---:|---:|---:|---:|
| llm_only | 42.4% | 0.0% | 4.2% | 11.1% |
| generic_rag | 41.0% | 0.0% | 8.3% | 11.1% |
| legacy_kg | 41.7% | 0.0% | 4.2% | 16.7% |
| scientific_kg | 68.8% | 0.0% | 2.8% | 30.6% |

## O detail

| Lane | Targeted clarification | Answerable resolution | Over-refusal | Unsupported diagnosis |
|---|---:|---:|---:|---:|
| llm_only | 91.7% | 41.7% | 20.8% | 0.0% |
| generic_rag | 50.0% | 33.3% | 25.0% | 0.0% |
| legacy_kg | 33.3% | 33.3% | 50.0% | 0.0% |
| scientific_kg | 58.3% | 41.7% | 41.7% | 0.0% |

## W detail

| Lane | Plan | State | Artifact | Approval violation | Unauthorized execution |
|---|---:|---:|---:|---:|---:|
| llm_only | 41.7% | 41.7% | 41.7% | 0.0% | 0.0% |
| generic_rag | 25.0% | 33.3% | 25.0% | 0.0% | 0.0% |
| legacy_kg | 41.7% | 58.3% | 41.7% | 0.0% | 0.0% |
| scientific_kg | 41.7% | 58.3% | 41.7% | 0.0% | 0.0% |

## Track-specific paired contrasts

### K

- Scientific KG minus generic_rag: +0.264; bootstrap 95% CI [0.12499999999999997, 0.4027777777777778] across 12 families.
- Scientific KG minus legacy_kg: +0.222; bootstrap 95% CI [0.055555555555555546, 0.3888888888888889] across 12 families.
- Scientific KG minus llm_only: +0.236; bootstrap 95% CI [0.09722222222222224, 0.375] across 12 families.

### O

- Scientific KG minus generic_rag: +0.083; bootstrap 95% CI [-0.12499999999999999, 0.2916666666666667] across 8 families.
- Scientific KG minus legacy_kg: +0.167; bootstrap 95% CI [-0.16666666666666669, 0.5] across 8 families.
- Scientific KG minus llm_only: -0.167; bootstrap 95% CI [-0.45833333333333337, 0.08333333333333334] across 8 families.

### W

- Scientific KG minus generic_rag: +0.167; bootstrap 95% CI [0.0, 0.5] across 4 families.
- Scientific KG minus legacy_kg: +0.000; bootstrap 95% CI [-0.25, 0.25] across 4 families.
- Scientific KG minus llm_only: +0.000; bootstrap 95% CI [-0.25, 0.25] across 4 families.

## Coverage subgroups (K only)

```json
{
  "100": {
    "generic_rag": {
      "n": 66,
      "rate": 0.2727272727272727
    },
    "legacy_kg": {
      "n": 66,
      "rate": 0.3181818181818182
    },
    "llm_only": {
      "n": 66,
      "rate": 0.30303030303030304
    },
    "scientific_kg": {
      "n": 66,
      "rate": 0.5757575757575758
    }
  },
  "111": {
    "generic_rag": {
      "n": 6,
      "rate": 0.8333333333333334
    },
    "legacy_kg": {
      "n": 6,
      "rate": 0.8333333333333334
    },
    "llm_only": {
      "n": 6,
      "rate": 0.8333333333333334
    },
    "scientific_kg": {
      "n": 6,
      "rate": 0.6666666666666666
    }
  }
}
```

## Evidence, cost, and runtime

| Lane | Evidence reliability | Evidence n | Provider calls | Failed | Input tokens | Output tokens | Mean / median latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| llm_only | n/a | 0 | 145 | 0 | 295979 | 54595 | 4411.1 / 5200.3 |
| generic_rag | 36.0% | 25 | 129 | 0 | 257456 | 46495 | 3900.4 / 4535.4 |
| legacy_kg | 20.0% | 15 | 132 | 0 | 264336 | 48281 | 5018.7 / 5825.3 |
| scientific_kg | 98.1% | 54 | 172 | 0 | 716538 | 61465 | 5025.9 / 5973.1 |

Token totals are observed provider usage only; no token reduction is inferred from character counts. Monetary cost is not reported because a frozen provider price schedule was unavailable.

## Failure attribution

Attribution is evidence-bound; provider failure and insufficient diagnostic evidence remain `unresolved` rather than being forced into a downstream stage.

```json
{
  "by_lane": {
    "generic_rag": {
      "correct_clarification": 6,
      "correct_stop": 3,
      "coverage_gap": 47,
      "evidence": 6,
      "planning": 9,
      "routing": 1,
      "synthesis": 1,
      "unresolved": 8
    },
    "legacy_kg": {
      "correct_clarification": 4,
      "correct_stop": 5,
      "coverage_gap": 44,
      "evidence": 2,
      "planning": 7,
      "routing": 1,
      "synthesis": 1,
      "unresolved": 14
    },
    "llm_only": {
      "correct_clarification": 11,
      "correct_stop": 4,
      "planning": 7,
      "routing": 2,
      "unresolved": 53
    },
    "scientific_kg": {
      "correct_clarification": 7,
      "correct_stop": 5,
      "evidence": 1,
      "planning": 7,
      "retrieval": 2,
      "routing": 1,
      "synthesis": 26,
      "unresolved": 12
    }
  },
  "overall": {
    "correct_clarification": 28,
    "correct_stop": 17,
    "coverage_gap": 91,
    "evidence": 9,
    "planning": 30,
    "retrieval": 2,
    "routing": 5,
    "synthesis": 28,
    "unresolved": 87
  }
}
```

## Mechanically selected examples

### first lexicographic Scientific KG pass / RAG fail

- Scenario `eval-K02-scvi-count-input-a`, repetition 0: scientific_kg=PASS; generic_rag=FAIL.
- `scientific_kg` excerpt: "scVI 的输入要求是原始计数数据，模型内部包含归一化过程。[1] 你提供的：matrix_state=raw integer UMI counts。 scVI 支持批次整合任务，但该支持不构成任何比较性优势。[2] scVI 支持低维表示任务，但该支持不构成任何比较性优势。[3] 模型在批次注释可用时会以批次注释为条件；你提供的 batch_key=donor 可作为批次注释使用。[5] 你提供的：batch_key=donor。 模型通识（尚未核验） 当前本地证据未充分覆盖以下说明。 符合 scVI 对原始计数输入的要求。"
- `generic_rag` excerpt: "你提供的：batch_key=donor。 模型通识（尚未核验） 当前本地证据未充分覆盖以下说明。 scVI 的输入要求是原始整数 UMI 计数矩阵，因此你提供的 raw integer UMI counts 在数据类型上符合这一要求。 scVI 使用负二项分布建模，期望输入为未标准化的计数，因此不应预先进行 CPM、log 或 z-score 等标准化。 如果矩阵中存在非整数、负值或缺失值，scVI 会报错或产生错误结果；当前仅知道是原始整数 UMI 计数，未提供是否已过滤低质量细胞或基因。 scVI 通常需要选择高变基因作为输入特征，以减少噪声和计算量；未提供基因选择信息，因此无法判断当前矩阵是否已满足这一条件。"

### first lexicographic RAG pass / Scientific KG fail

- Scenario `eval-K07-wot-timecourse-b`, repetition 2: scientific_kg=FAIL; generic_rag=PASS.
- `scientific_kg` excerpt: "现有条件不足以唯一解析证据；请补充具体版本、方法变体或适用条件。"
- `generic_rag` excerpt: "你提供的：sampling=one terminal time point only。 模型通识（尚未核验） 当前本地证据未充分覆盖以下说明。 Waddington-OT 的核心用途是基于多个时间点的单细胞表达谱，通过最优传输推断细胞在时间点之间的祖先与后代关系。 因此无法直接进行跨时间点的来源与命运推断。 当前知识库中没有关于 Waddington-OT 输入要求或局限性的直接科学陈述，因此无法给出经过证据支持的适用性判断。"

## Scoring recovery audit

The historical HTTP 402 adjudication attempt remains preserved. After balance
was restored, recovery resumed at adjudication only; none of the 432 product
answers was rerun. The product-run tree retained SHA256
`a9a53ae83d105eede38cb681f1d98290d2961d1b865129c1f44524f2c0db0d9b`.

The two raw judge passes contained 864 rows: 800 were schema-valid and 64 had
schema defects. Twenty-four non-exact quote anchors were removed because they
were not literal substrings of the answer. All 64 otherwise invalid rows were
sent through the frozen adjudication rule rather than coerced. In total, 167
run judgments across 25 case packets were adjudicated. The recovery log records
zero scientific judgment fields edited without adjudication. Equivalent JSON
wrapper shapes returned by the provider were normalized without changing their
judgment contents.

## Limitations

This remains a 36-scenario pilot, not evidence of broad scientific-agent superiority. Scenario review and answer scoring are AI-assisted rather than two-human Gold adjudication. The answer judge uses the same configured provider family as the product runtime, although lane identities are hidden and two isolated passes plus adjudication are retained. Public O titles retain contamination risk, and exact coverage auditing may undercount semantically equivalent corpus content. Product-lane contrasts compare complete product lanes and do not isolate graph structure alone. Confidence intervals are descriptive with few independent families, especially O and W.

## Conclusion

The primary K contrast is Scientific KG minus Generic RAG +0.264 (95% CI [0.12499999999999997, 0.4027777777777778]) and minus Legacy KG +0.222 (95% CI [0.055555555555555546, 0.3888888888888889]). Track-specific O and W results are reported separately and are not used to manufacture an aggregate gain claim.
