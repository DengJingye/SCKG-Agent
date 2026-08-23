import numpy as np
import pandas as pd

from execution.integration_scientific_evaluator import bootstrap_integration_metrics


def test_integration_bootstrap_is_bounded_and_deterministic(tmp_path):
    rng = np.random.default_rng(3)
    rows = []
    for batch_index, batch in enumerate(("a", "b", "c")):
        for label_index, label in enumerate(("x", "y", "z")):
            values = rng.normal(size=(12, 4)) * 0.2
            values[:, label_index] += 3.0
            values[:, -1] += batch_index * 0.05
            for local_index, embedding in enumerate(values):
                rows.append(
                    {
                        "cell_id": f"{batch}-{label}-{local_index}",
                        "batch": batch,
                        "cell_type": label,
                        **{
                            f"integrated_{index + 1}": value
                            for index, value in enumerate(embedding)
                        },
                    }
                )
    path = tmp_path / "embedding.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)

    first = bootstrap_integration_metrics(path, iterations=50, seed=9)
    second = bootstrap_integration_metrics(path, iterations=50, seed=9)

    assert first == second
    for interval in first.values():
        assert 0.0 <= interval["lower"] <= interval["estimate"] <= interval["upper"] <= 1.0
        assert interval["bootstrap_iterations"] == 50


def test_integration_bootstrap_skips_group_with_undefined_batch_silhouette(tmp_path):
    rows = []
    for index in range(12):
        rows.append(
            {
                "cell_id": f"common-{index}",
                "batch": "a" if index < 6 else "b",
                "cell_type": "common",
                "integrated_1": float(index % 3),
                "integrated_2": float(index // 3),
            }
        )
    for index, batch in enumerate(("c", "d", "e", "f")):
        rows.append(
            {
                "cell_id": f"rare-{index}",
                "batch": batch,
                "cell_type": "rare",
                "integrated_1": 10.0 + index,
                "integrated_2": 10.0 - index,
            }
        )
    path = tmp_path / "embedding.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)

    result = bootstrap_integration_metrics(path, iterations=20, seed=7)

    assert result["batch_mixing_asw"]["bootstrap_iterations"] == 20
