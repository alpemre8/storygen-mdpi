from pathlib import Path
import sys, json, argparse
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from storygen_measurement_core import MeasurementProtocol, validate_runtime_identity
p = argparse.ArgumentParser()
p.add_argument("--protocol", default="configs/feature_measurement_v1.yaml")
p.add_argument("--model-file", required=True)
p.add_argument("--server-manifest", required=True)
p.add_argument("--concurrency", type=int, default=8)
p.add_argument("--live", action="store_true")
p.add_argument("--allow-server-queuing", action="store_true")
a = p.parse_args()
protocol = MeasurementProtocol.load(ROOT, a.protocol)
print(json.dumps({"legacy_request_parity": protocol.validate_legacy_parity(), "measurement": protocol.manifest(), "runtime": validate_runtime_identity(protocol, model_file=a.model_file, server_manifest=a.server_manifest, require_slots=a.concurrency, require_live_server=a.live, allow_server_queuing=a.allow_server_queuing)}, indent=2))
