import ast
from pathlib import Path

import pytest

from execution.wrappers.scdblfinder import (
    build_rscript_argv,
    validate_parameters,
)


def test_scdblfinder_adapter_validates_contract_parameters():
    values = validate_parameters({"dbr": 0.08, "n_cores": 2, "random_state": 7})
    assert values["dbr"] == 0.08
    assert values["n_cores"] == 2
    with pytest.raises(ValueError, match="unknown"):
        validate_parameters({"command": "system('bad')"})
    with pytest.raises(ValueError, match="outside"):
        validate_parameters({"dbr": 0.9})
    with pytest.raises(ValueError, match="remain false"):
        validate_parameters({"clusters": True})


def test_scdblfinder_adapter_builds_fixed_rscript_argv():
    rscript = Path("/fixed/env/bin/Rscript")
    argv = build_rscript_argv("r_request.json", rscript_path=rscript)
    assert argv[0] == str(rscript)
    assert argv[-1] == "r_request.json"
    assert Path(argv[1]).name == "scdblfinder.R"
    with pytest.raises(ValueError, match="fixed"):
        build_rscript_argv("../../request.json", rscript_path=rscript)
    with pytest.raises(ValueError, match="absolute"):
        build_rscript_argv("r_request.json", rscript_path=Path("Rscript"))


def test_scdblfinder_wrappers_forbid_dynamic_code_and_installation():
    python_path = Path("execution/wrappers/scdblfinder.py")
    tree = ast.parse(python_path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not {
        node.func.id
        for node in calls
        if isinstance(node.func, ast.Name)
    }.intersection({"eval", "exec"})
    subprocess_runs = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "run"
    ]
    assert len(subprocess_runs) == 1
    assert any(
        keyword.arg == "shell"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in subprocess_runs[0].keywords
    )

    r_text = Path("execution/wrappers/scdblfinder.R").read_text(encoding="utf-8")
    for forbidden in ("install.packages", "BiocManager::install", "system(", "eval(", "parse("):
        assert forbidden not in r_text
    assert "scDblFinder::scDblFinder" in r_text
    assert "BiocParallel::SerialParam" in r_text
