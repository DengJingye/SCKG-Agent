"""DEV harness contracts, not model/scientific outcome tests."""
import json

import pytest

from eval.benchmark_v3.dev_pilot import BASE, isolation, read_rows, render_input, sha, write


def test_frozen_transport_preserves_each_condition_without_answer_injection():
    cases = read_rows(BASE / "development_scenarios.jsonl")
    fixtures = json.loads((BASE / "development_fixtures.json").read_text())
    for case in cases:
        rendered = render_input(case, fixtures)
        assert rendered.startswith(case["input"]["query"])
        for key, value in case["input"]["conditions"].items():
            assert f"{key}={value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}" in rendered
        assert "expected_fact" not in rendered and "reference_claims" not in rendered
    w2 = next(c for c in cases if c["scenario_id"] == "dev-W02")
    assert "gene_a" in render_input(w2, fixtures)


@pytest.mark.parametrize("lane,backend,allowed", [("llm_only", "legacy", False),
    ("llm_only", "approved", False), ("generic_rag", "approved", False),
    ("legacy_kg", "approved", False), ("scientific_kg", "legacy", False),
    ("scientific_kg", "approved", True), ("generic_rag", "legacy", True), ("legacy_kg", "legacy", True)])
def test_backend_isolation(lane, backend, allowed):
    assert isolation(lane, [{"backend": backend, "request": {"enable_dense": False, "use_kg": False,
        "use_scientific_evidence": False}}], {})["pass"] == allowed


def test_generic_rag_flags_and_llm_reference_leak_are_rejected():
    assert not isolation("generic_rag", [{"backend": "legacy", "request": {"use_kg": True}}], {})["pass"]
    assert not isolation("generic_rag", [{"backend": "legacy", "request": {"use_scientific_evidence": True}}], {})["pass"]
    assert not isolation("llm_only", [], {"references": [{"chunk_id": "leak"}]})["pass"]


def test_attempts_are_write_once(tmp_path):
    target = tmp_path / "receipt.json"
    write(target, {"result": "failed"})
    with pytest.raises(FileExistsError):
        write(target, {"result": "passed"})
    assert json.loads(target.read_text())["result"] == "failed"


def test_manifest_is_56_units_one_repeat_and_inputs_equal_across_lanes():
    output = BASE / "dev_pilot_20260921"
    if not (output / "manifest.json").exists():
        pytest.skip("run not initialized")
    manifest = json.loads((output / "manifest.json").read_text())
    schedule = manifest["schedule"]
    assert len(schedule) == len({r["run_id"] for r in schedule}) == 56
    assert {r["repetition"] for r in schedule} == {0}
    for case_id in {r["case_id"] for r in schedule}:
        assert len({r["input_sha256"] for r in schedule if r["case_id"] == case_id}) == 1
    assert manifest["scenario_file_sha256"] == sha((BASE / "development_scenarios.jsonl").read_bytes())
