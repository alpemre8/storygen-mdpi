from pathlib import Path
import sys, argparse, json
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
CORE = PROJECT / "measurement"
sys.path[:0] = [str(PROJECT), str(ROOT / "src"), str(CORE / "src")]
from storygen_feature.attestation import attest_existing_feature_set
from tools.depot_paths import owned_output_path

p = argparse.ArgumentParser(description="Strictly attest the frozen 10-film Qwen feature store against Measurement Core V1.1.")
p.add_argument("--feature-set-id", required=True)
p.add_argument("--feature-store-root", required=True)
p.add_argument("--legacy-feature-set-manifest", required=True)
p.add_argument("--legacy-feature-store-manifest", required=True)
p.add_argument("--film-set", required=True)
p.add_argument("--registry", required=True)
p.add_argument("--model-file", required=True)
p.add_argument("--server-manifest", required=True)
p.add_argument("--output-dir", required=True)
a = p.parse_args()

def r(x: str) -> Path:
    q = Path(x)
    return q.resolve() if q.is_absolute() else (PROJECT / q).resolve()

manifest = attest_existing_feature_set(project_root=PROJECT, core_root=CORE, protocol_path=Path("configs/feature_measurement_v1.yaml"), feature_set_id=a.feature_set_id, feature_store_root=r(a.feature_store_root), legacy_feature_set_manifest=r(a.legacy_feature_set_manifest), legacy_feature_store_manifest=r(a.legacy_feature_store_manifest), film_set_path=r(a.film_set), registry_path=r(a.registry), model_file=r(a.model_file), server_manifest=r(a.server_manifest), output_dir=owned_output_path(a.output_dir))
print(json.dumps(manifest, indent=2))
