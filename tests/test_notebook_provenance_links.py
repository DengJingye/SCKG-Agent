from execution.capability_notebook import _parameter_provenance_lines


def test_registered_web_parameter_source_is_clickable():
    source = "https://scanpy.readthedocs.io/en/1.11.x/api/generated/scanpy.pp.neighbors.html"
    lines = _parameter_provenance_lines([{
        "parameter_name": "n_neighbors", "value_or_range": 15,
        "origin_type": "package_default", "source_id": source,
    }])
    assert lines == [f"- `n_neighbors=15` — `package_default` from [参数来源原文](<{source}>)"]


def test_internal_contract_identity_is_not_invented_as_a_web_source():
    lines = _parameter_provenance_lines([{
        "parameter_name": "seed", "value_or_range": 0,
        "origin_type": "project_profile", "source_id": "contract:scanpy_core",
        "policy_rule_id": "stable-seed",
    }])
    assert "from `contract:scanpy_core`" in lines[0]
    assert "rule `stable-seed`" in lines[0]
    assert "原文" not in lines[0]


def test_malformed_or_non_web_source_does_not_become_a_link():
    for source in ("javascript:alert(1)", "https://example.org/a>\ninvalid"):
        lines = _parameter_provenance_lines([{
            "parameter_name": "seed", "value_or_range": 0, "source_id": source,
        }])
        assert "[参数来源原文]" not in lines[0]
