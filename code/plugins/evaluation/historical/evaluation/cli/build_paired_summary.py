from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]

from storygen_evaluation.analysis import paired_summary
from tools.depot_paths import owned_output_path
from storygen_evaluation.provenance import load_artifact_overrides

parser = argparse.ArgumentParser(description="Build the Paper-22 within-model DP-v1/CG-v1 paired summary: coverage, Target Improvement and Directional Accuracy only.")
parser.add_argument("--dp-run", required=True)
parser.add_argument("--cg-run", required=True)
parser.add_argument("--taskset-runtime", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--model-id")
parser.add_argument("--artifact-paths", type=Path, help="JSON map of recorded artifact file paths to explicit hash-checked local files")
args = parser.parse_args()
artifact_paths = load_artifact_overrides(args.artifact_paths)

resolve = lambda value: (PROJECT / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
output = owned_output_path(args.output)
if "evv2_4" not in output.name:
    raise SystemExit("Output artifact name must contain evv2_4")

print(json.dumps(paired_summary(resolve(args.dp_run), resolve(args.cg_run), resolve(args.taskset_runtime), output, args.model_id, artifact_paths=artifact_paths), indent=2))
