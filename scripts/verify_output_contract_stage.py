"""Verify explicit wire/local contracts with the existing bounded supervisor."""
from pathlib import Path
import argparse
import importlib.util
import json


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
    # The previous regression already takes about 106 seconds in the installed
    # host. Keep its 120-second ceiling; new tests have a separate serial lane.
    for name,tests in (('contracts',('tests/test_workbench_workflow_phase_contract.py',
                                   'tests/test_workbench_local_output_contract.py')),
                       ('regression',stage.TESTS)):
        options=['--output',str(output/name)]
        if args.python:
            options += ['--python',str(args.python)]
        code=stage.main(options,tests=tests)
        receipt=json.loads((output/name/'receipt.json').read_text())
        receipts.append(receipt)
        if code:
            return code
    combined={'schema':'explicit-local-output-contract-two-serial-lanes-v1',
        'passed':all(r['passed'] for r in receipts) and
                 receipts[0]['source_hashes']==receipts[1]['source_hashes'],
        'tests':sum(r['junit']['tests'] for r in receipts),
        'lanes':['contracts','regression'],'wall_limit_seconds_per_lane':120,
        'max_rss_bytes':1536*1024*1024,'provider_requests':0,'fits':0}
    with (output/'receipt.json').open('x') as stream:
        json.dump(combined,stream,indent=2);stream.write('\n')
    return 0 if combined['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
