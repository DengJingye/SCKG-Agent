"""Run the published workflow engineering checks under the existing supervisor.

No provider requests or scientific fitting are part of this test selection.
Settings and credential removal are not an operating-system network sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_workbench_acceptance import child_environment, junit_result, run_process


ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/test_workbench_workflow_chat.py",
    "tests/test_workbench_workflow_missing_contract.py",
    "tests/test_workbench_model_capabilities.py",
    "tests/test_workbench_model_diagnostics.py",
    "tests/test_workbench_model_wire_integration.py",
    "tests/test_workbench_model_capabilities_ui.py",
    "tests/test_workbench_models.py",
    "tests/test_workbench_worker.py",
    "tests/test_workbench_evidence_answers.py",
    "tests/test_workbench_ui.py::test_empty_workspace_and_all_seven_pages_do_not_acquire_or_call_models",
    "tests/test_workbench_ui.py::test_connection_profile_and_session_unlock_are_real_but_do_not_call_models",
    "tests/test_workbench_workflow_chat_ui.py",
    "tests/test_workbench_workflow_inputs.py",
    "tests/test_workbench_workflow_inputs_ui.py",
    "tests/test_workbench_agent_loop.py",
    "tests/test_workbench_workflow_demo.py",
    "tests/test_workbench_source_selector_ui.py",
    "tests/test_workbench_acceptance_runner.py",
)


def hashes():
    files = {ROOT / "workbench_app.py", Path(__file__).resolve(),
             ROOT / "scripts/run_workbench_acceptance.py",
             ROOT / "scripts/bootstrap_workflow_demo.py",
             ROOT / "scripts/bootstrap_method_demo.py",
             ROOT / "scripts/verify_annotation_stage.py"}
    for directory in ("sckg_workbench", "core", "engine", "execution", "eval", "tests"):
        files.update((ROOT / directory).rglob("*.py"))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files) if path.is_file()}


def main(argv=None, *, tests=TESTS):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new output directory; existing results are never overwritten")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    python = args.python.expanduser().absolute()
    if output.exists() or output.is_symlink():
        parser.error("output must not exist; choose a new result directory")
    if not python.is_file() or not os.access(python, os.X_OK):
        parser.error("Python must be an existing executable")
    for selector in tests:
        if not (ROOT / selector.partition("::")[0]).is_file():
            parser.error("required test file missing: " + selector)
    before = hashes()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="isolated-", dir=output) as temporary:
        env, removed = child_environment(Path(temporary), None)
        command = [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   *tests, "--junitxml=" + str(output / "junit.xml")]
        result = run_process(command, cwd=ROOT, env=env, log=output / "output.log",
                             wall_seconds=120, max_rss_bytes=1536 * 1024 * 1024)
    result["junit"] = junit_result(output / "junit.xml", tests)
    result.update(schema="published-workflow-engineering-checks-v1",
                  source_hashes=before, source_hashes_unchanged=hashes() == before,
                  credential_variable_names_removed=removed,
                  configured_provider_requests=0, configured_scientific_fits=0,
                  scope="Engineering fixtures, source and receipt integrity, UI components, "
                        "demo creation, and real tiny process supervision; not native model "
                        "completion, scientific accuracy, semantic gold or OS sandbox qualification.")
    passed = bool(result["process_ok"] and result["junit"]["ok"]
                  and result["junit"]["skipped"] == 0 and result["source_hashes_unchanged"])
    result["passed"] = passed
    with (output / "receipt.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in (
        "passed", "returncode", "seconds", "peak_rss_bytes", "resource_stop",
        "cleanup", "source_hashes_unchanged", "junit")}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
