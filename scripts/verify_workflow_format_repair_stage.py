"""Serial checks for the opt-in final-format repair and unchanged workflow lanes."""
from pathlib import Path
import argparse
import importlib.util
import json


FORMAT_TESTS = (
    ('format-core', ('tests/test_workbench_workflow_format_repair.py',)),
    ('format-ui', ('tests/test_workbench_workflow_format_repair_ui.py',)),
)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def verification_lanes(legacy_tests):
    previous = module(Path(__file__).with_name('verify_output_contract_stage.py'),
                      '_reused_workflow_contract_lanes')
    return (*FORMAT_TESTS, *previous.verification_lanes(legacy_tests))


def main(argv=None):
    common = module(Path(__file__).with_name('verify_workflow_stage.py'),
                    '_reused_bounded_workflow_verifier')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--python', type=Path)
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        parser.error('output must not exist')
    output.mkdir(parents=True, exist_ok=False)
    lanes, receipts = verification_lanes(common.TESTS), []
    for name, tests in lanes:
        options = ['--output', str(output / name)]
        if args.python:
            options += ['--python', str(args.python)]
        code = common.main(options, tests=tests)
        receipts.append(json.loads((output / name / 'receipt.json').read_text()))
        if code:
            return code
    combined = {'schema': 'workflow-final-format-repair-serial-lanes-v1',
        'passed': all(r['passed'] for r in receipts) and
                  all(r['source_hashes'] == receipts[0]['source_hashes'] for r in receipts),
        'tests': sum(r['junit']['tests'] for r in receipts),
        'lanes': [name for name, _ in lanes],
        'selectors': {name: list(tests) for name, tests in lanes},
        'wall_limit_seconds_per_lane': 120, 'max_rss_bytes': 1536 * 1024 * 1024,
        'provider_requests': 0, 'fits': 0}
    with (output / 'receipt.json').open('x') as stream:
        json.dump(combined, stream, indent=2)
        stream.write('\n')
    return 0 if combined['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
