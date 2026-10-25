from pathlib import Path
import argparse, json, sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]
from storygen_taskset import build_taskset_runtime
from tools.depot_paths import owned_output_path

p = argparse.ArgumentParser(description="Build the canonical TasksetV5 runtime from a verified Feature Extraction V1.4 artifact. No LLM calls are made.")
p.add_argument("--film-set", required=True)
p.add_argument("--input-root", required=True, help="Root containing films/<film_id>/script.json")
p.add_argument("--feature-set-manifest", required=True)
p.add_argument("--feature-set-root", required=True)
p.add_argument("--output-root", required=True, help="Rewrite-owned runtime root, normally $STORYGEN_REWRITE_DEPOT_ROOT/runs/tasksets")
p.add_argument("--overwrite", action="store_true")
a = p.parse_args()
print(json.dumps(build_taskset_runtime(
    film_set_path=Path(a.film_set), input_root=Path(a.input_root),
    feature_set_manifest=Path(a.feature_set_manifest), feature_set_root=Path(a.feature_set_root),
    output_root=owned_output_path(a.output_root), overwrite=a.overwrite,
), indent=2))
