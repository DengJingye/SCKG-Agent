from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import pandas as pd

from core.execution_models import ExecutionRun
from execution.annotation_scientific_dataset import (
    Zheng68KDatasetService,
    build_label_mapping,
)
from execution.annotation_scientific_evaluator import AnnotationScientificEvaluator
from tests.annotation_helpers import build_reference
from tests.test_annotation_scientific_dataset import _write_dataset


def test_annotation_scientific_evaluator_reports_metrics_and_bootstrap(tmp_path):
    dataset_path = _write_dataset(tmp_path / "zheng68k.h5ad")
    reference = build_reference(tmp_path / "reference")
    mapping = build_label_mapping(
        mapping_id="zheng68k-to-sckg-v1",
        version="1.0",
        mapping={
            "B cells": "B_cell",
            "T cells": "T_cell",
            "NK cells": "NK_cell",
            "Monocytes": "Monocyte",
        },
    )
    service = Zheng68KDatasetService()
    dataset = service.validate(
        dataset_path=dataset_path,
        label_key="source_cell_type",
        source_url="https://example.invalid/zheng68k",
        license_name="test fixture only",
    )
    split = service.split(
        dataset_manifest=dataset,
        label_mapping=mapping,
        reference=reference,
        output_dir=tmp_path / "split",
    )
    evaluation = ad.read_h5ad(split.evaluation.path)
    predictions_path = tmp_path / "predicted_labels.tsv"
    predicted = evaluation.obs["ground_truth_cell_type"].astype(str).copy()
    predicted.iloc[0] = "unknown"
    pd.DataFrame(
        {
            "cell_id": evaluation.obs_names.astype(str),
            "predicted_label": predicted.to_numpy(),
            "unknown": predicted.eq("unknown").to_numpy(),
        }
    ).to_csv(predictions_path, sep="\t", index=False)
    run = _scientific_run(split.evaluation.path)

    result = AnnotationScientificEvaluator().evaluate(
        run=run,
        split=split.evaluation,
        predictions_path=predictions_path,
        bootstrap_iterations=50,
        bootstrap_seed=12,
    )

    assert result.metric_authority == "scientific_pilot_metric"
    assert 0.0 < result.metrics["macro_f1"] < 1.0
    assert 0.0 < result.metrics["balanced_accuracy"] < 1.0
    assert result.metrics["unknown_rate"] == 1 / split.evaluation.n_cells
    assert result.bootstrap_ci["macro_f1"].bootstrap_iterations == 50
    assert result.per_class_metrics["B_cell"]["support"] > 0
    assert sum(
        sum(row.values()) for row in result.confusion_matrix.values()
    ) == split.evaluation.n_cells


def _scientific_run(input_path):
    now = datetime.now(timezone.utc)
    return ExecutionRun(
        request_id="annotation-scientific-request",
        run_id="annotation-scientific-run",
        trace_id="annotation-scientific-trace",
        plan_id="annotation-scientific-plan",
        step_id="annotation-scientific-step",
        wrapper_id="celltypist_v1_7_1",
        tool_name="CellTypist",
        tool_version="1.7.1",
        environment_id="annotation-python",
        command_argv_redacted=["python", "-m", "execution.wrappers.celltypist"],
        parameters={"model": "celltypist-immune-all-low-v1"},
        input_hash=hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
        start_time=now,
        end_time=now,
        runtime_seconds=1.2,
        peak_memory_mb=120.0,
        exit_code=0,
        stdout_path="stdout.log",
        stderr_path="stderr.log",
        status="succeeded",
        fixture_id="Zheng68K-evaluation",
        synthetic_fixture=False,
        public_dataset=True,
        execution_purpose="scientific_pilot",
    )
