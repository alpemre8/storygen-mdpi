from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from storygen_evaluation.paper_ready import validate_bundle

parser = argparse.ArgumentParser(description="Validate an Evaluation V2.4 Paper-22-ready bundle, including hashes and canonical scope/layout checks.")
parser.add_argument("--bundle", required=True)
args = parser.parse_args()
resolve = lambda value: (PROJECT / Path(value)).resolve() if not Path(value).is_absolute() else Path(value).resolve()
result = validate_bundle(resolve(args.bundle))
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["valid"] else 2)
