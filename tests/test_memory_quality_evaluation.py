from eval.memory_quality_evaluation import (
    MemoryQualityEvaluator,
    build_default_memory_cases,
)


def test_memory_quality_bank_has_30_governed_cases():
    cases = build_default_memory_cases()

    assert len(cases) == 30
    assert len({case.case_id for case in cases}) == 30
    assert {
        "explicit_roundtrip",
        "inferred_pending",
        "inferred_confirm",
        "user_isolation",
        "conflict_boundary",
        "deletion",
        "episodic_roundtrip",
        "skill_deduplication",
        "export_authority",
    } == {case.category for case in cases}


def test_memory_quality_gate_preserves_isolation_and_evidence_boundary():
    results, summary = MemoryQualityEvaluator().evaluate(build_default_memory_cases())

    assert len(results) == 30
    assert summary.passed_count == 30
    assert summary.scientific_authority_violation_count == 0
    assert summary.user_isolation_violation_count == 0
    assert summary.release_gate_passed is True
