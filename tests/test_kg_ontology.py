from core.kg_ontology import (
    infer_algorithm_families,
    normalize_language_values,
    normalize_modality,
    normalize_platform_values,
    normalize_task,
    task_parent,
)


def test_task_aliases_collapse_to_stable_ontology_ids():
    assert normalize_task("Cell Type Identification").canonical_id == "cell_type_annotation"
    assert normalize_task("Cell-type Classification").canonical_id == "cell_type_annotation"
    assert normalize_task("差异表达分析").canonical_id == "differential_expression"
    assert normalize_task("Pseudotime Analysis").canonical_id == "trajectory_inference"
    assert task_parent("rna_velocity") == "trajectory_inference"


def test_modality_and_language_aliases_are_normalized():
    assert normalize_modality("single-cell RNA-seq").canonical_id == "scrna_seq"
    assert normalize_modality("Multiome (RNA+ATAC)").canonical_id == "multiome"
    languages = normalize_language_values("R/C++/Python")
    assert [(item.canonical_id, item.label) for item in languages] == [
        ("r", "R"),
        ("cpp", "C++"),
        ("python", "Python"),
    ]
    plus_languages = normalize_language_values("Python + R + C++")
    assert [item.canonical_id for item in plus_languages] == ["python", "r", "cpp"]
    platforms = normalize_platform_values("Python/Docker/Virtualbox")
    assert [(node_type, item.canonical_id) for node_type, item in platforms] == [
        ("Language", "python"),
        ("RuntimePlatform", "docker"),
        ("RuntimePlatform", "virtualbox"),
    ]


def test_algorithm_family_inference_is_deterministic_and_bounded():
    text = "A variational autoencoder with a graph neural network and Bayesian regression."
    first = infer_algorithm_families(text)
    second = infer_algorithm_families(text)

    assert first == second
    assert [item.canonical_id for item in first] == [
        "graph_neural_network",
        "variational_autoencoder",
        "bayesian_model",
        "regression",
    ]
    assert len(first) <= 5
