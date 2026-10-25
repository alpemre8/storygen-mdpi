"""P01B only: original frozen inputs -> A01–A10 -> isolated reviewer depot."""
from pathlib import Path
import argparse
import json
import shlex
import sys

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
sys.path[:0]=[str(PROJECT),str(ROOT/"src")]

from tools.depot_paths import owned_output_path
from storygen_evaluation.provenance import load_artifact_overrides
from storygen_evaluation.reviewer.pipeline import run_pipeline, validate_test_receipt


def main():
    parser=argparse.ArgumentParser(description="Finite sequential P01B deterministic reviewer analyses A01-A10. No inference; original inputs are hash checked; existing outputs cannot be overwritten.")
    parser.add_argument("--analysis-plan",type=Path,required=True,help="Explicit frozen storygen.reviewer-analysis-plan/1.0 JSON derived from verified P00/P01A")
    parser.add_argument("--output-dir",type=Path,required=True,help="NEW directory under reviewer_round1/P01B_deterministic in the Evaluation depot")
    parser.add_argument("--artifact-paths",type=Path,help="P01A verified explicit recorded-file to local-file overrides")
    parser.add_argument("--test-results",type=Path,required=True,help="JSON receipt for completed existing/new regression tests")
    args=parser.parse_args()
    output=owned_output_path(args.output_dir)
    if output.parent.name!="P01B_deterministic" or output.parent.parent.name!="reviewer_round1":
        parser.error("Output must be a NEW reviewer_round1/P01B_deterministic/<run-id> directory")
    plan=args.analysis_plan.expanduser().resolve()
    tests=validate_test_receipt(args.test_results)
    command="cd "+shlex.quote(str(PROJECT))+"\nPYTHONDONTWRITEBYTECODE=1 python3 -B "+shlex.join(["evaluation/cli/run_reviewer_analyses.py",*sys.argv[1:]])
    status=run_pipeline(plan,output,load_artifact_overrides(args.artifact_paths),tests,command)
    return 0 if status["phase_status"]=="PASS" else 2


if __name__=="__main__":
    raise SystemExit(main())
