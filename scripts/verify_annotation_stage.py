"""Run bounded source/condition/UI regressions, reusing the workflow supervisor."""
from pathlib import Path
import importlib.util

TESTS = (
    'tests/test_workbench_prediction_semantics.py',
    'tests/test_workbench_method_demo.py',
    'tests/test_workbench_workflow_demo.py',
    'tests/test_workbench_workflow_methods.py',
    'tests/test_workbench_workflow_methods_ui.py',
    'tests/test_workbench_workflow_inputs.py',
    'tests/test_workbench_workflow_inputs_ui.py',
    'tests/test_workbench_workflow_chat.py',
    'tests/test_workbench_workflow_missing_contract.py',
    'tests/test_workbench_workflow_chat_ui.py',
    'tests/test_workbench_ui.py::test_empty_workspace_and_all_seven_pages_do_not_acquire_or_call_models',
    'tests/test_workbench_ui.py::test_connection_profile_and_session_unlock_are_real_but_do_not_call_models',
    'tests/test_workbench_acceptance_runner.py',
)


def main(argv=None):
    source = Path(__file__).resolve().with_name('verify_workflow_stage.py')
    spec = importlib.util.spec_from_file_location('_reused_workflow_stage', source)
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    return stage.main(argv, tests=TESTS)


if __name__ == '__main__':
    raise SystemExit(main())
