from pathlib import Path
import sys,argparse,json
ROOT=Path(__file__).resolve().parents[1];PROJECT=ROOT.parent;CORE=PROJECT/'measurement';sys.path[:0]=[str(PROJECT),str(ROOT/'src'),str(CORE/'src')]
from storygen_feature.reliability import run_reliability
from tools.depot_paths import owned_output_path
p=argparse.ArgumentParser();p.add_argument('--scene-manifest',required=True);p.add_argument('--output',required=True);p.add_argument('--model-file',required=True);p.add_argument('--server-manifest',required=True);p.add_argument('--repeats',type=int,default=5);p.add_argument('--concurrency',type=int,default=8);p.add_argument('--seed',type=int,default=42);p.add_argument('--allow-noncanonical-sample',action='store_true');a=p.parse_args();r=lambda x:(PROJECT/Path(x)).resolve() if not Path(x).is_absolute() else Path(x).resolve()
print(json.dumps(run_reliability(project_root=PROJECT,block_root=CORE,protocol_path=Path('configs/feature_measurement_v1.yaml'),scene_manifest=r(a.scene_manifest),output=owned_output_path(a.output),repeats=a.repeats,seed=a.seed,concurrency=a.concurrency,model_file=r(a.model_file),server_manifest=r(a.server_manifest),allow_noncanonical_sample=a.allow_noncanonical_sample),indent=2))
