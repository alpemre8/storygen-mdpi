from __future__ import annotations
import json,shutil,time,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from .taskset import load_taskset,Task
from storygen.services.transfer_planner import create_transfer_plan_from_feature_files,write_transfer_plan
from storygen.services.per_scene_rewrite_engine import run_per_scene_rewrite_from_files
from storygen.services.vllm_client import VLLMClient
from .provenance import prompt_provenance, sha256_json

def write_json(p:Path,x:Any):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(p:Path):import hashlib;return 'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()
def _forbid_prompt(task_dir:Path, strategy:str):
 for p in task_dir.glob('per_scene/*/rewrite_request.json'):
  payload=json.loads(p.read_text())
  model_facing=(str(payload.get('system_instruction') or '')+'\n'+str(payload.get('user_instruction') or '')).lower()
  for marker in ('reference_film_id','reference_interval_scene_ids','reference scene ids','reference film id'):
   if marker in model_facing:raise RuntimeError(f'Forbidden metadata leaked into model-facing prompt: {marker} in {p}')
  expected='DP-v1' if strategy=='DP-v1' else 'CG-v1'
  if payload.get('prompt_profile')!=expected:raise RuntimeError(f'Prompt profile mismatch in {p}: expected {expected}')
  try:user=json.loads(str(payload.get('user_instruction') or ''))
  except Exception as exc:raise RuntimeError(f'User instruction is not JSON in {p}: {exc}') from exc
  keys=set()
  def walk(v):
   if isinstance(v,dict):
    for k,x in v.items():keys.add(str(k));walk(x)
   elif isinstance(v,list):
    for x in v:walk(x)
  walk(user)
  if strategy=='DP-v1' and keys & {'current_values','targets','deltas','target_values'}:raise RuntimeError(f'DP-v1 received numerical curve values in {p}')
  if strategy=='CG-v1' and not {'current_values','targets','deltas'}.issubset(keys):raise RuntimeError(f'CG-v1 missing B/T/delta values in {p}')
def _complete(td:Path)->bool:
 try:
  s=json.loads((td/'phase_status.json').read_text());r=json.loads((td/'rewritten_scenes.json').read_text());return s.get('rewrite_completed') is True and isinstance(r.get('rewritten_scenes'),list)
 except Exception:return False
class Progress:
 def __init__(self,total):self.total=total;self.done=0;self.lock=threading.Lock();self.start=time.time()
 def tick(self,label):
  with self.lock:
   self.done+=1;e=time.time()-self.start;rate=self.done/e if e else 0;eta=(self.total-self.done)/rate if rate else 0
   print(f'\rrewrite scenes {self.done}/{self.total} ({100*self.done/max(self.total,1):5.1f}%) elapsed={e:7.1f}s eta={eta:7.1f}s rate={rate:.3f}/s item={label}',end='',flush=True)
 def finish(self):print()
def run_taskset(*,project_root:Path,taskset_path:Path,feature_set_manifest:Path,output_root:Path,run_id:str,model:str,model_file:Path,quantization:str,server_manifest:Path,strategy:str,base_url:str,temperature=.2,schema_retry_count=1,max_tokens=4096,concurrency=4,timeout=600,max_tasks=None,resume=False,overwrite=False,dry_run=False)->dict[str,Any]:
 taskset=load_taskset(taskset_path);fsm=json.loads(feature_set_manifest.read_text());
 if fsm.get('contract_id')!='storygen.feature-set' or str(fsm.get('contract_version'))!='1.4':raise RuntimeError('feature-set/1.4 manifest required')
 if taskset.feature_set_id and fsm.get('feature_set_id')!=taskset.feature_set_id:raise RuntimeError('Taskset feature_set_id mismatch')
 sm=json.loads(server_manifest.read_text());actual=sha(model_file);served='sha256:'+str(sm.get('model_sha256','')).removeprefix('sha256:')
 if actual!=served:raise RuntimeError('Server/model SHA mismatch')
 if str(sm.get('model_alias') or '')!=model:raise RuntimeError('Server alias mismatch')
 if str(sm.get('quantization') or '')!=quantization:raise RuntimeError('Server quantization mismatch')
 if int(sm.get('parallel_slots',0))<concurrency:raise RuntimeError('Insufficient server parallel slots')
 if int(sm.get('context_per_slot',0))<8192:raise RuntimeError('context_per_slot must be at least 8192')
 if sm.get('continuous_batching') is not True:raise RuntimeError('continuous_batching must be enabled')
 provenance=prompt_provenance(Path(__file__).resolve().parents[3],strategy)
 run_dir=output_root/run_id
 if run_dir.exists() and overwrite:shutil.rmtree(run_dir)
 if run_dir.exists() and not resume:raise FileExistsError(run_dir)
 run_dir.mkdir(parents=True,exist_ok=True);tasks=taskset.tasks[:max_tasks or len(taskset.tasks)]
 if dry_run:return {'dry_run':True,'tasks':len(tasks),'strategy':strategy}
 total=sum(len(t.source_scene_ids) for t in tasks if not (resume and _complete(run_dir/'tasks'/t.task_id)));progress=Progress(total)
 client=VLLMClient(base_url=base_url,timeout_seconds=timeout,max_in_flight=concurrency)
 failures=[];completed=[]
 def one(task:Task):
  td=run_dir/'tasks'/task.task_id
  if resume and _complete(td):return {'task_id':task.task_id,'status':'skipped'}
  if td.exists():shutil.rmtree(td)
  td.mkdir(parents=True);write_json(td/'task.json',task.model_dump(mode='json'))
  try:
   plan=create_transfer_plan_from_feature_files(source_feature_path=project_root/task.source_feature_path,reference_feature_path=project_root/task.reference_feature_path,source_start_scene_id=task.source_start_scene_id,source_end_scene_id=task.source_end_scene_id,reference_start_scene_id=task.reference_start_scene_id,reference_end_scene_id=task.reference_end_scene_id,selected_features=task.selected_features,run_id=task.task_id);write_transfer_plan(plan,td/'transfer_plan.json')
   run_per_scene_rewrite_from_files(plan_path=td/'transfer_plan.json',script_path=project_root/task.source_script_path,output_path=td/'rewritten_scenes.json',model=model,vllm_base_url=base_url,temperature=temperature,client=client,schema_retry_count=schema_retry_count,allow_partial_task_output=False,prompt_strategy='direct_prompt' if strategy=='DP-v1' else 'curve_guided',prompt_version='v1',rewrite_timeout_seconds=timeout,rewrite_format_mode='schema',rewrite_max_tokens=max_tokens,generation_concurrency=1,progress_callback=lambda sid:progress.tick(f'{task.task_id}/{sid}'))
   _forbid_prompt(td,strategy)
   r=json.loads((td/'rewritten_scenes.json').read_text()).get('rewritten_scenes',[]);returned=[str(x.get('scene_id')) for x in r]
   if returned!=task.source_scene_ids:raise RuntimeError(f'Exact scene order mismatch: expected={task.source_scene_ids} returned={returned}')
   status={'task_id':task.task_id,'rewrite_completed':True,'prompt_contract_id':strategy,'prompt_bundle_sha256':provenance['prompt_bundle_sha256'],'source_scene_ids':task.source_scene_ids,'created_at':datetime.now(timezone.utc).isoformat()};write_json(td/'phase_status.json',status);return status
  except Exception as e:
   f={'task_id':task.task_id,'stage':'rewrite','root_cause_type':type(e).__name__,'error':str(e)};write_json(td/'rewrite_failure.json',f);return f
 try:
  workers=min(len(tasks),max(1,concurrency*2))
  with ThreadPoolExecutor(max_workers=workers) as ex:
   futs={ex.submit(one,t):t for t in tasks}
   for fut in as_completed(futs):
    x=fut.result();(completed if x.get('rewrite_completed') or x.get('status')=='skipped' else failures).append(x)
 finally:client.close();progress.finish()
 manifest={'contract_id':'storygen.rewrite-run','contract_version':'1.3','block_version':'1.3.1','rewrite_protocol_id':'rewrite-v1.3','prompt_contract_id':strategy,'prompt_provenance':provenance,'information_policy':{'reference_film_identity_exposed':False,'reference_scene_identity_exposed':False,'cg_only_adds_current_target_delta':strategy=='CG-v1'},'model':{'served_alias':model,'exact_file':str(model_file),'file_sha256':actual,'quantization':quantization},'server_manifest':{'path':str(server_manifest),'sha256':sha(server_manifest),'content':sm},'feature_set_manifest':{'path':str(feature_set_manifest),'sha256':sha(feature_set_manifest),'measurement':fsm.get('measurement')},'taskset':{'path':str(taskset_path),'sha256':sha(taskset_path),'task_count':len(tasks)},'decoding':{'temperature':temperature,'max_tokens':max_tokens,'schema_retry_count':schema_retry_count,'concurrency':concurrency,'timeout_seconds':timeout},'tasks_completed':len(completed),'tasks_failed':len(failures),'failures':failures,'created_at':datetime.now(timezone.utc).isoformat()};write_json(run_dir/'rewrite_run_manifest.json',manifest)
 if failures:raise RuntimeError(f'{len(failures)} rewrite tasks failed; artifacts preserved')
 return manifest
