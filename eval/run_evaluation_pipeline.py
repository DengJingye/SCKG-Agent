from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evaluation_models import EvaluationSignal, EvaluationSuite, JudgeRuntimeConfig
from eval.evaluation_pipeline import EvaluationPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the unified scKG evaluation pipeline.")
    parser.add_argument("--suite", choices=[item.value for item in EvaluationSuite], required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--baseline-experiment", type=Path)
    parser.add_argument("--authorize-outbound", action="store_true")
    parser.add_argument("--external-confirmation", default="")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--hidden-confirmation", default="")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-workflow-smokes", action="store_true")
    parser.add_argument("--judge-provider", default="")
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--judge-api-base", default="")
    parser.add_argument("--judge-prompt-digest", default="")
    parser.add_argument("--judge-calibration-cases", type=int, default=0)
    parser.add_argument("--judge-calibration-accuracy", type=float)
    parser.add_argument("--judge-calibration-kappa", type=float)
    args = parser.parse_args()

    judge = None
    if args.judge_provider or args.judge_model:
        judge = JudgeRuntimeConfig(
            provider=args.judge_provider,
            model=args.judge_model,
            api_base=args.judge_api_base,
            prompt_digest=args.judge_prompt_digest,
            calibration_case_count=args.judge_calibration_cases,
            calibration_accuracy=args.judge_calibration_accuracy,
            calibration_kappa=args.judge_calibration_kappa,
        )
    pipeline = EvaluationPipeline(
        output_root=args.output_root or PROJECT_ROOT / ".sckg_exec/evaluations"
    )
    output, gate = pipeline.run(
        suite=EvaluationSuite(args.suite),
        authorize_outbound=args.authorize_outbound,
        external_confirmation=args.external_confirmation,
        include_hidden=args.include_hidden,
        hidden_confirmation=args.hidden_confirmation,
        judge_config=judge,
        baseline_experiment=args.baseline_experiment,
        skip_pytest=args.skip_pytest,
        run_workflow_smokes=not args.skip_workflow_smokes,
    )
    print(
        json.dumps(
            {
                "experiment": str(output),
                "suite": args.suite,
                "release_gate": gate.status,
                "blockers": gate.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if gate.status == EvaluationSignal.PASSED else 2


if __name__ == "__main__":
    raise SystemExit(main())
