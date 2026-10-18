"""Verify workflow contracts and related regressions in serial bounded lanes."""
from pathlib import Path
import argparse
import importlib.util
import json


CONTRACT_TESTS = (
    'tests/test_workbench_workflow_phase_contract.py',
    'tests/test_workbench_local_output_contract.py',
    'tests/test_workbench_workflow_legacy_phase_replay.py',
    'tests/test_workbench_workflow_report_presence.py',
    'tests/test_workbench_workflow_report_presence_ui.py',
)

# These existing file groups previously completed the entire legacy selection
# as two bounded 232-case lanes. Retain the original selector order and require
# every current selector to occur exactly once; case counts come from JUnit.
REGRESSION_A_FILES = frozenset((
    'tests/test_workbench_model_capabilities.py',
    'tests/test_workbench_model_wire_integration.py',
    'tests/test_workbench_model_capabilities_ui.py',
    'tests/test_workbench_worker.py',
    'tests/test_workbench_evidence_answers.py',
    'tests/test_workbench_ui.py',
    'tests/test_workbench_agent_loop.py',
    'tests/test_workbench_source_selector_ui.py',
    'tests/test_workbench_acceptance_runner.py',
))


def verification_lanes(legacy_tests):
    legacy_tests = tuple(legacy_tests)
    if len(legacy_tests) != len(set(legacy_tests)):
        raise ValueError('Duplicate legacy selectors are not a valid regression denominator')
    first = tuple(s for s in legacy_tests if s.partition('::')[0] in REGRESSION_A_FILES)
    second = tuple(s for s in legacy_tests if s.partition('::')[0] not in REGRESSION_A_FILES)
    if not first or not second or set(first) & set(second) or set(first + second) != set(legacy_tests):
        raise ValueError('Both disjoint regression lanes must cover the complete legacy selection')
    return (('contracts', CONTRACT_TESTS), ('regression-a', first), ('regression-b', second))


def main(argv=None):
    source = Path(__file__).resolve().with_name('verify_workflow_stage.py')
    spec = importlib.util.spec_from_file_location('_reused_output_contract_stage', source)
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--python',type=Path)
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        parser.error('output must not exist')
    output.mkdir(parents=True,exist_ok=False)
    receipts=[]
    lanes = verification_lanes(stage.TESTS)
    for name, tests in lanes:
        options=['--output',str(output/name)]
        if args.python:
            options += ['--python',str(args.python)]
        code=stage.main(options,tests=tests)
        receipt=json.loads((output/name/'receipt.json').read_text())
        receipts.append(receipt)
        if code:
            return code
    combined={'schema':'workflow-contract-three-serial-lanes-v2',
        'passed':all(r['passed'] for r in receipts) and
                 all(r['source_hashes'] == receipts[0]['source_hashes'] for r in receipts),
        'tests':sum(r['junit']['tests'] for r in receipts),
        'lanes':[name for name, _ in lanes],
        'selectors':{name:list(tests) for name, tests in lanes},
        'wall_limit_seconds_per_lane':120,
        'max_rss_bytes':1536*1024*1024,'provider_requests':0,'fits':0}
    with (output/'receipt.json').open('x') as stream:
        json.dump(combined,stream,indent=2);stream.write('\n')
    return 0 if combined['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
