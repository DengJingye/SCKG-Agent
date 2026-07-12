import ast
from pathlib import Path

import pytest

from execution.wrappers.scrublet import validate_parameters


def test_scrublet_wrapper_parameter_contract():
    values = validate_parameters({"expected_doublet_rate": 0.08, "random_state": 7})
    assert values["expected_doublet_rate"] == 0.08
    assert values["random_state"] == 7

    with pytest.raises(ValueError, match="unknown"):
        validate_parameters({"shell": "rm -rf"})
    with pytest.raises(ValueError, match="outside"):
        validate_parameters({"expected_doublet_rate": 2.0})
    with pytest.raises(ValueError, match="numeric"):
        validate_parameters({"expected_doublet_rate": "; touch escaped"})


def test_scrublet_wrapper_has_fixed_non_shell_entrypoint():
    wrapper_path = Path("execution/wrappers/scrublet.py")
    tree = ast.parse(wrapper_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "subprocess" not in imported
    assert "requests" not in imported
    assert not {"eval", "exec"}.intersection(called_names)
