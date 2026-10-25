from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
CORE = PROJECT / "measurement"
sys.path[:0] = [str(PROJECT), str(ROOT / "src"), str(CORE / "src")]

from storygen_feature.rewritten import extract_rewritten_feature_set
from tools.depot_paths import owned_output_path

parser = argparse.ArgumentParser(
    description="Run Feature Extraction V1.4 on rewritten scenes using the canonical Measurement implementation."
)
parser.add_argument("--protocol", default="configs/feature_measurement_v1.yaml")
parser.add_argument("--remeasure-existing-rewrites", action="store_true",
                    help="Preserve generation measurement provenance while measuring with another model and the identical method")
parser.add_argument("--allow-server-queuing", action="store_true",
                    help="Explicitly allow fewer backend slots than client workers; retain protocol runtime minima")
parser.add_argument("--rewrite-run", required=True)
parser.add_argument("--reference-feature-set-manifest", required=True)
parser.add_argument("--taskset-runtime", required=True)
parser.add_argument("--feature-set-id", required=True)
parser.add_argument("--output-root", required=True)
parser.add_argument("--model-file", required=True)
parser.add_argument("--server-manifest", required=True)
parser.add_argument("--concurrency", type=int, default=8)
parser.add_argument("--overwrite", action="store_true")
parser.add_argument("--resume", action="store_true")
parser.add_argument("--retry-failed-only", action="store_true")
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--progress", choices=["always", "auto", "never"], default="always")
args = parser.parse_args()

if "fev1_4" not in args.feature_set_id:
    raise SystemExit("--feature-set-id must encode fev1_4")


def resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT / path).resolve()


result = extract_rewritten_feature_set(
    project_root=PROJECT,
    core_root=CORE,
    protocol_path=Path(args.protocol),
    remeasure_existing_rewrites=args.remeasure_existing_rewrites,
    rewrite_run=resolve(args.rewrite_run),
    reference_feature_set_manifest=resolve(args.reference_feature_set_manifest),
    taskset_runtime=resolve(args.taskset_runtime),
    feature_set_id=args.feature_set_id,
    output_root=owned_output_path(args.output_root),
    model_file=resolve(args.model_file),
    server_manifest=resolve(args.server_manifest),
    overwrite=args.overwrite,
    resume=args.resume,
    retry_failed_only=args.retry_failed_only,
    dry_run=args.dry_run,
    progress_mode=args.progress,
    concurrency=args.concurrency,
    allow_server_queuing=args.allow_server_queuing,
)
print(json.dumps(result, indent=2))
