from pathlib import Path
import sys, argparse, json
ROOT=Path(__file__).resolve().parents[1]; PROJECT=ROOT.parent; CORE=PROJECT/'measurement'; sys.path[:0]=[str(PROJECT),str(ROOT/'src'),str(CORE/'src')]
from storygen_feature.extractor import extract_feature_set
from tools.depot_paths import owned_output_path
p=argparse.ArgumentParser(description='Run Feature Extraction V1.4 using explicit input and output roots.')
p.add_argument('--protocol',default='configs/feature_measurement_v1.yaml',help='Measurement config, relative to measurement/ or absolute; Qwen remains the default')
p.add_argument('--allow-server-queuing',action='store_true',help='Explicitly allow fewer backend slots than client workers; retain protocol runtime minima')
p.add_argument('--film-set',required=True)
p.add_argument('--scene-selection',help='Explicit storygen.scene-selection/1.0 manifest; preserve original text/order/indexes')
p.add_argument('--input-root',required=True,help='Root containing films/<film_id>/script.json; normally <runs-root>/_inputs')
p.add_argument('--feature-set-id',required=True)
p.add_argument('--output-root',required=True,help='Feature-owned output root; normally $STORYGEN_FEATURE_DEPOT_ROOT/runs/feature_extraction')
p.add_argument('--model-file',required=True); p.add_argument('--server-manifest',required=True); p.add_argument('--concurrency',type=int,default=8); p.add_argument('--resume',action='store_true'); p.add_argument('--overwrite-stale',action='store_true'); p.add_argument('--dry-run',action='store_true'); p.add_argument('--progress',choices=['always','auto','never'],default='always'); a=p.parse_args()
if 'fev1_4' not in a.feature_set_id: raise SystemExit('--feature-set-id must encode fev1_4')
r=lambda x:(PROJECT/Path(x)).resolve() if not Path(x).is_absolute() else Path(x).resolve()
print(json.dumps(extract_feature_set(project_root=PROJECT,block_root=ROOT,core_root=CORE,protocol_path=Path(a.protocol),film_set_path=r(a.film_set),input_root=r(a.input_root),feature_set_id=a.feature_set_id,output_root=owned_output_path(a.output_root),model_file=r(a.model_file),server_manifest=r(a.server_manifest),resume=a.resume,overwrite_stale=a.overwrite_stale,dry_run=a.dry_run,progress_mode=a.progress,concurrency=a.concurrency,allow_server_queuing=a.allow_server_queuing,scene_selection_path=r(a.scene_selection) if a.scene_selection else None),indent=2))
