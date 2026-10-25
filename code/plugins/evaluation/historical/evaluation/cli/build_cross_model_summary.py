from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]

from storygen_evaluation.analysis import cross_model_summary
from tools.depot_paths import owned_output_path
from storygen_evaluation.provenance import load_artifact_overrides

parser = argparse.ArgumentParser(description="Build the Paper-22 absolute cross-model TI/DA comparison on the all-condition global-common subset.")
parser.add_argument("--model-pair", nargs=3, action="append", metavar=("MODEL", "DP", "CG"), required=True)
parser.add_argument("--analysis-set-id", required=True)
parser.add_argument("--taskset-runtime", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--artifact-paths", type=Path, help="JSON map of recorded artifact file paths to explicit hash-checked local files")
args = parser.parse_args()
artifact_paths = load_artifact_overrides(args.artifact_paths)

resolve = lambda value: (PROJECT / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
output = owned_output_path(args.output)
if len(args.model_pair) < 2:
    raise SystemExit("At least two --model-pair entries are required")
if "evv2_4" not in output.name:
    raise SystemExit("Output artifact name must contain evv2_4")
entries = [(model, resolve(dp), resolve(cg)) for model, dp, cg in args.model_pair]
print(json.dumps(cross_model_summary(entries, resolve(args.taskset_runtime), output, args.analysis_set_id, artifact_paths=artifact_paths), indent=2))
