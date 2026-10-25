from pathlib import Path
import sys, argparse, json
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]
from storygen.rewrite_v1_3.importer import import_legacy_dp_run
from tools.depot_paths import owned_output_path
p = argparse.ArgumentParser(description="Strictly import a historical DP-v1 run into rewrite-run/1.3.")
p.add_argument("--legacy-run", required=True)
p.add_argument("--taskset", required=True)
p.add_argument("--feature-set-manifest", required=True)
p.add_argument("--run-id", required=True)
p.add_argument("--model", required=True)
p.add_argument("--model-file", required=True)
p.add_argument("--quantization", required=True)
p.add_argument("--server-manifest", required=True)
p.add_argument("--output-root", required=True)
p.add_argument("--max-tasks", type=int)
p.add_argument("--overwrite", action="store_true")
a = p.parse_args()
if 'rwv1_3' not in a.run_id:
    raise SystemExit('--run-id must encode rwv1_3 under the flat runs layout')
def r(x):
    q = Path(x)
    return q.resolve() if q.is_absolute() else (PROJECT / q).resolve()
print(json.dumps(import_legacy_dp_run(project_root=PROJECT, block_root=ROOT, legacy_run=r(a.legacy_run), taskset_path=r(a.taskset), feature_set_manifest=r(a.feature_set_manifest), output_root=owned_output_path(a.output_root), run_id=a.run_id, model_alias=a.model, model_file=r(a.model_file), quantization=a.quantization, server_manifest=r(a.server_manifest), overwrite=a.overwrite, max_tasks=a.max_tasks), indent=2))
