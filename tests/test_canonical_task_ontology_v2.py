from core.canonical_task_ontology import (
    CANONICAL_TASKS,
    canonical_task_for_text,
    is_junk_task_label,
    task_workflow_edges,
)


def test_canonical_ontology_has_exactly_fifteen_semantic_tasks():
    task_ids = [task.task_id for task in CANONICAL_TASKS]

    assert len(task_ids) == 15
    assert len(set(task_ids)) == 15
    assert "doublet_detection" in task_ids
    assert "batch_integration" in task_ids
    assert "cell_type_annotation" in task_ids


def test_aliases_normalize_without_admitting_hash_labels():
    assert canonical_task_for_text("remove batch effects with Harmony").task_id == "batch_integration"
    assert canonical_task_for_text("细胞类型注释").task_id == "cell_type_annotation"
    assert is_junk_task_label("isoform_3_a6f4bc991d") is True
    assert is_junk_task_label("4cb729fda11e") is True
    assert is_junk_task_label("RNA velocity") is False


def test_workflow_relations_are_canonical_and_bidirectional():
    edges = set(task_workflow_edges())

    assert ("normalization", "batch_integration", "PRECEDES") in edges
    assert ("batch_integration", "normalization", "REQUIRES_OUTPUT_OF") in edges
    assert all(source != target for source, target, _ in edges)
