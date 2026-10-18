"""Serial ordinary-chat evidence encoding checks with the existing supervisor."""
from pathlib import Path
import argparse
import importlib.util
import json


def verification_lanes():
    return (
        ('wire', ('tests/test_workbench_evidence_wire.py',)),
        ('ordinary', ('tests/test_workbench_chat.py', 'tests/test_workbench_chat_grounded.py',
            'tests/test_workbench_chat_background.py')),
        ('modes-ui', (
            'tests/test_workbench_ui.py::test_empty_library_chat_preserves_two_turn_history_and_rerun_does_not_send',
            'tests/test_workbench_ui.py::test_new_chat_isolates_context_and_history_switch_does_not_invoke',
            'tests/test_workbench_ui.py::test_chat_knowledge_is_optional_and_suspended_source_invalidates_display_without_resend',
            'tests/test_workbench_ui.py::test_analysis_chat_requires_explicit_dataset_context_and_keeps_prose_separate_from_execution',
            'tests/test_workbench_ui.py::test_readonly_result_ui_requires_explicit_choice_and_sends_without_execution_options',
            'tests/test_workbench_grounded_ui.py::test_grounded_mode_is_explicit_and_default_chat_send_remains_ordinary',
            'tests/test_workbench_grounded_ui.py::test_grounded_mode_is_excluded_from_analysis_and_result_read_requests',
            'tests/test_workbench_workflow_format_repair_ui.py::test_real_ui_submission_persists_policy_in_request_hash_then_refuses_launch',
            'tests/test_workbench_agent_loop.py::test_ordinary_chat_retains_exactly_one_attempt_without_tools',
            'tests/test_workbench_program_chat.py::test_ordinary_chat_and_fixed_profile_modes_keep_existing_protocol',
            'tests/test_workbench_result_followup.py::test_readonly_followup_uses_server_binding_and_aggregates_without_execution',
            'tests/test_workbench_workflow_legacy_phase_replay.py')))


def main(argv=None):
    spec = importlib.util.spec_from_file_location('_existing_evidence_stage_common',
        Path(__file__).with_name('verify_workflow_stage.py'))
    common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path)
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        parser.error('output must be a fresh directory')
    output.mkdir(parents=True)
    receipts = []
    for name, tests in verification_lanes():
        options = ['--output', str(output / name)]
        if args.python:
            options += ['--python', str(args.python)]
        code = common.main(options, tests=tests)
        receipts.append(json.loads((output / name / 'receipt.json').read_text()))
        if code:
            return code
    combined = {'schema': 'ordinary-chat-evidence-serial-lanes-v1',
        'passed': all(r['passed'] for r in receipts) and
            all(r['source_hashes'] == receipts[0]['source_hashes'] for r in receipts),
        'tests': sum(r['junit']['tests'] for r in receipts),
        'lanes': [name for name, _ in verification_lanes()],
        'selectors': {name: list(tests) for name, tests in verification_lanes()},
        'provider_requests': 0, 'scientific_fits': 0,
        'wall_seconds_per_lane': 120, 'max_rss_bytes': 1610612736}
    with (output / 'receipt.json').open('x') as stream:
        json.dump(combined, stream, indent=2); stream.write('\n')
    return 0 if combined['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
