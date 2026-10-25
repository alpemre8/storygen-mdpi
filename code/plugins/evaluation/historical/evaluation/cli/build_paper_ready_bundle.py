from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path[:0] = [str(PROJECT), str(ROOT / "src")]

from storygen_evaluation.paper_ready import build_paper_ready
from tools.depot_paths import owned_output_path

parser = argparse.ArgumentParser(description="Validate and package precomputed Evaluation V2.4 artifacts into the Paper-22-ready Tables 6-10 ZIP.")
parser.add_argument("--plan", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--overwrite", action="store_true")
args = parser.parse_args()

resolve = lambda value: (PROJECT / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
print(json.dumps(build_paper_ready(PROJECT, resolve(args.plan), owned_output_path(args.output), args.overwrite), indent=2))
