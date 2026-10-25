"""Relocatable output adapter for the exact frozen P01B API; no metric changes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

COMMIT = '95ca1c7beb1af1186a0e97972a1af1f43cd62dd3'
CODE = '''
from pathlib import Path
import sys
from storygen_evaluation.reviewer.pipeline import run_pipeline, validate_test_receipt
from storygen_evaluation.provenance import load_artifact_overrides
plan, output, tests, overrides = sys.argv[1:]
status = run_pipeline(Path(plan), Path(output), load_artifact_overrides(Path(overrides) if overrides else None),
                      validate_test_receipt(Path(tests)), 'locked storygen.reviewer-analysis API adapter')
raise SystemExit(0 if status['phase_status']=='PASS' else 2)
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider-root', type=Path, required=True)
    parser.add_argument('--analysis-plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--test-results', type=Path, required=True)
    parser.add_argument('--artifact-paths', type=Path)
    args = parser.parse_args(argv)
    provider = args.provider_root.resolve()
    commit = subprocess.check_output(['git', '-C', str(provider), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != COMMIT:
        raise RuntimeError('Exact frozen evaluation provider commit required')
    if args.output.exists():
        raise FileExistsError(args.output)
    env = dict(os.environ, PYTHONPATH=str(provider / 'evaluation/src'), PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, '-c', CODE, str(args.analysis_plan.resolve()), str(args.output.resolve()),
               str(args.test_results.resolve()), str(args.artifact_paths.resolve()) if args.artifact_paths else '']
    subprocess.run(command, env=env, cwd=provider, check=True)


if __name__ == '__main__':
    main()
