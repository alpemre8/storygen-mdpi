from pathlib import Path
import argparse, json, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storygen_taskset import verify_taskset
p=argparse.ArgumentParser(); p.add_argument("--taskset", required=True); a=p.parse_args()
payload=json.loads(Path(a.taskset).read_text(encoding="utf-8")); result=verify_taskset(payload, require_paths=True)
print(json.dumps(result, indent=2)); raise SystemExit(0 if result["valid"] else 2)
