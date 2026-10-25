from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]

from storygen_evaluation.feature_sets import evaluate_feature_sets
from storygen_evaluation.run import evaluate_run
from tools.depot_paths import owned_output_path
from storygen_evaluation.provenance import load_artifact_overrides

parser = argparse.ArgumentParser(description="Evaluate original and rewritten FeatureSets under unchanged Evaluation V2.4 metrics.")
parser.add_argument("--taskset-runtime", required=True)
parser.add_argument("--feature-set-manifest", required=True)
candidate = parser.add_mutually_exclusive_group(required=True)
candidate.add_argument("--candidate-feature-set", help="Rewritten storygen.feature-set/1.4 directory")
candidate.add_argument("--reanalysis-run", help="Historical storygen.reanalysis-run/1.1 directory (read compatibility only)")
parser.add_argument("--output-run-id", required=True)
parser.add_argument("--output-root", required=True)
parser.add_argument("--method", choices=["DP-v1", "CG-v1"], required=True)
parser.add_argument("--rewrite-model", required=True)
parser.add_argument("--overwrite", action="store_true")
parser.add_argument("--artifact-paths", type=Path, help="JSON map of recorded artifact file paths to explicit hash-checked local files")
args = parser.parse_args()
artifact_paths = load_artifact_overrides(args.artifact_paths)

resolve = lambda value: (PROJECT / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
if "evv2_4" not in args.output_run_id:
    raise SystemExit("--output-run-id must contain evv2_4")

output = owned_output_path(args.output_root) / args.output_run_id
if args.candidate_feature_set:
    result = evaluate_feature_sets(
        taskset_runtime=resolve(args.taskset_runtime),
        reference_feature_set_manifest=resolve(args.feature_set_manifest),
        candidate_feature_set=resolve(args.candidate_feature_set),
        output=output,
        method=args.method,
        model=args.rewrite_model,
        overwrite=args.overwrite,
        artifact_paths=artifact_paths,
    )
else:
    result = evaluate_run(
        taskset_runtime=resolve(args.taskset_runtime),
        feature_set_manifest=resolve(args.feature_set_manifest),
        reanalysis_run=resolve(args.reanalysis_run),
        output=output,
        method=args.method,
        model=args.rewrite_model,
        overwrite=args.overwrite,
        artifact_paths=artifact_paths,
    )
print(json.dumps(result, indent=2))
