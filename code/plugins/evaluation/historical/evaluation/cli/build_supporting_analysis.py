from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]

from storygen_evaluation.supporting import build_supporting_analysis
from tools.depot_paths import owned_output_path
from storygen_evaluation.provenance import load_artifact_overrides

parser = argparse.ArgumentParser(
    description=(
        "Build deterministic Paper-22 supporting analysis from existing Evaluation V2.4 artifacts: "
        "base-interval-clustered Gemma paired bootstrap and optional within-model CG-DP point differences. "
        "No LLM inference and no Tables 6-10 changes."
    )
)
parser.add_argument("--dp-run", required=True, help="DP-v1 Evaluation V2.4 artifact directory for the bootstrap model")
parser.add_argument("--cg-run", required=True, help="CG-v1 Evaluation V2.4 artifact directory for the bootstrap model")
parser.add_argument("--taskset-runtime", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--model-id")
parser.add_argument("--paired-summary", nargs=2, action="append", metavar=("MODEL_ID", "PATH"), default=[])
parser.add_argument("--bootstrap-resamples", type=int, default=10000)
parser.add_argument("--rng-engine", choices=["python-mt19937", "numpy-pcg64"], default="python-mt19937", help="Explicit bootstrap procedure; numpy-pcg64 reproduces manuscript Table A6")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--confidence-level", type=float, default=0.95)
parser.add_argument(
    "--paper22-lock",
    action="store_true",
    help="Validate the rounded Gemma Paper-22 S6 values and fail if the supporting result does not reproduce them.",
)
parser.add_argument("--artifact-paths", type=Path, help="JSON map of recorded artifact file paths to explicit hash-checked local files")
args = parser.parse_args()
artifact_paths = load_artifact_overrides(args.artifact_paths)

resolve = lambda value: (PROJECT / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
output = owned_output_path(args.output)
if "evv2_4" not in output.name:
    raise SystemExit("Output artifact name must contain evv2_4")

result = build_supporting_analysis(
    dp_run=resolve(args.dp_run),
    cg_run=resolve(args.cg_run),
    taskset_runtime=resolve(args.taskset_runtime),
    output=output,
    paired_entries=[(model, resolve(path)) for model, path in args.paired_summary],
    resamples=args.bootstrap_resamples,
    seed=args.seed,
    confidence_level=args.confidence_level,
    model_id=args.model_id,
    paper22_lock=args.paper22_lock,
    rng_engine=args.rng_engine,
    artifact_paths=artifact_paths,
)
print(json.dumps(result, indent=2))
if args.paper22_lock and not result["validation"]["valid"]:
    raise SystemExit(2)
