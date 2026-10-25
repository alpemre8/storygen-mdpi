from __future__ import annotations
import json, yaml, shutil
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from storygen_measurement_core import MeasurementProtocol,CanonicalFeatureScorer,validate_runtime_identity
from storygen_measurement_core.preflight import assert_measurement_equal
from storygen_measurement_core.client import OpenAICompatibleClient
from .io import load_script,sha256_file,write_json,read_json
from .scheduler import GlobalSceneScheduler,SceneJob
from .selection import load_selection,select_scenes

def _resume_valid(film_dir:Path, *, protocol:MeasurementProtocol, script:Path, scene_count:int, selected_scene_ids=None, selection_sha256=None)->bool:
    out=film_dir/'scene_features.jsonl'; man=film_dir/'measurement_manifest.json'
    if not out.is_file() or not man.is_file(): return False
    try:
        m=read_json(man); assert_measurement_equal(protocol.manifest(),m['measurement'],label='resume measurement')
        if m.get('script_sha256')!=sha256_file(script) or int(m.get('scene_count',-1))!=scene_count: return False
        rows=[json.loads(x) for x in out.read_text().splitlines() if x.strip()]
        if selected_scene_ids is not None:
            if m.get('scene_selection_sha256')!=selection_sha256 or [r.get('scene_id') for r in rows]!=selected_scene_ids: return False
        return len(rows)==scene_count and all(r.get('measurement_status')=='measured' for r in rows)
    except Exception: return False

def extract_feature_set(*,project_root:Path,block_root:Path,core_root:Path,protocol_path:Path,film_set_path:Path,input_root:Path,feature_set_id:str,output_root:Path,model_file:Path,server_manifest:Path,resume=False,overwrite_stale=False,dry_run=False,progress_mode='always',concurrency=8,allow_server_queuing=False,scene_selection_path:Path|None=None)->dict[str,Any]:
    protocol=MeasurementProtocol.load(core_root,protocol_path); runtime=validate_runtime_identity(protocol,model_file=model_file,server_manifest=server_manifest,require_slots=concurrency,allow_server_queuing=allow_server_queuing)
    film_set=yaml.safe_load(film_set_path.read_text()) or {}; films=[str(x) for x in film_set.get('films',[])]
    selection=load_selection(scene_selection_path,films) if scene_selection_path else None
    selection_sha=sha256_file(scene_selection_path) if scene_selection_path else None
    root=output_root/feature_set_id
    if selection is not None and root.exists() and any(root.iterdir()) and not resume and not overwrite_stale:
        raise FileExistsError(f'Selected-scene output exists: {root}; fresh execution cannot reuse it')
    if (root/'feature_set_manifest.json').is_file():
        assert_measurement_equal(protocol.manifest(),read_json(root/'feature_set_manifest.json')['measurement'],label='existing output measurement')
    for manifest in root.glob('films/*/measurement_manifest.json'):
        assert_measurement_equal(protocol.manifest(),read_json(manifest)['measurement'],label='existing film measurement')
    root.mkdir(parents=True,exist_ok=True)
    contexts={};jobs=[];results=[]
    for fo,film_id in enumerate(films):
        script=(input_root/'films'/film_id/'script.json').resolve();raw,scenes=load_script(script);fd=root/'films'/film_id
        if selection is not None: scenes=select_scenes(selection[film_id],script,scenes)
        if resume and _resume_valid(fd,protocol=protocol,script=script,scene_count=len(scenes),selected_scene_ids=[s['scene_id'] for s in scenes] if selection is not None else None,selection_sha256=selection_sha):
            results.append({'film_id':film_id,'status':'skipped_valid_resume','scene_count':len(scenes)});continue
        if resume and fd.exists() and not overwrite_stale: raise RuntimeError(f'Stale/incompatible resume artifact: {fd}; use --overwrite-stale')
        if fd.exists() and overwrite_stale: shutil.rmtree(fd)
        contexts[film_id]={'order':fo,'script':script,'raw':raw,'scenes':scenes,'dir':fd,'rows':[None]*len(scenes),'failures':[]}
        for i,s in enumerate(scenes):jobs.append(SceneJob(f'{fo:04d}:{i:06d}:{film_id}:{s["scene_id"]}',film_id,film_id,s['scene_id'],s['title'],s['text'],{'offset':i}))
    if dry_run:return {'dry_run':True,'films':len(films),'jobs':len(jobs),'measurement':protocol.manifest(),'runtime':runtime}
    summary={'job_count':0,'concurrency':concurrency}
    if jobs:
      with OpenAICompatibleClient(protocol.model['base_url'],float(protocol.decoding.get('timeout_seconds',600)),concurrency) as client:
       scorer=CanonicalFeatureScorer(protocol,client=client,cache_path=root/'measurement_cache_v4.json',use_cache=True)
       scheduled,summary=GlobalSceneScheduler(scorer=scorer,concurrency=concurrency,label=f'feature-extraction {feature_set_id}',progress_mode=progress_mode,telemetry_path=root/'telemetry/extraction_requests.jsonl').run(jobs)
      for x in scheduled:
       c=contexts[x.job.group_id];i=int(x.job.payload['offset']);s=c['scenes'][i];m=x.measurement
       if m.status!='measured':c['failures'].append({'scene_id':s['scene_id'],'root_cause':m.error,'status':m.status})
       c['rows'][i]={'film_id':x.job.film_id,'scene_id':s['scene_id'],'scene_index':s['scene_index'],'title':s['title'],'features':m.features,'measurement_status':m.status,'measurement_provenance':m.provenance,'runtime':{'queue_wait_seconds':x.queue_wait_seconds,'elapsed_seconds':x.elapsed_seconds,'cache_hit':m.cache_hit}}
    total_fail=0
    for film_id,c in sorted(contexts.items(),key=lambda kv:kv[1]['order']):
      fd=c['dir'];fd.mkdir(parents=True);rows=c['rows'];total_fail+=len(c['failures'])
      with (fd/'scene_features.jsonl').open('w') as f:
       for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
      legacy=[]
      for r in rows:
       z={'film_id':film_id,'scene_id':r['scene_id'],'scene_index':r['scene_index'],'title':r['title'],'feature_set_id':feature_set_id,'feature_extraction_signature':protocol.id,'measurement_protocol_id':protocol.id,'measurement_protocol_hash':protocol.protocol_hash,'measurement_status':r['measurement_status']}
       if r['features']:
        for feature,key in protocol.legacy_keys.items():z[key]=r['features'][feature]
       legacy.append(z)
      write_json(fd/'scene_features_llm.json',legacy)
      if c['failures']:write_json(fd/'measurement_failures.json',c['failures'])
      write_json(fd/'measurement_manifest.json',{'contract_id':'storygen.film-measurement','contract_version':'1.4','measurement':protocol.manifest(),'runtime_identity':runtime,'film_id':film_id,'script_path':str(c['script']),'script_sha256':sha256_file(c['script']),'scene_count':len(rows),'measurement_failure_count':len(c['failures']),**({'scene_selection_sha256':selection_sha} if selection is not None else {})})
      results.append({'film_id':film_id,'status':'completed' if not c['failures'] else 'measurement_ineligible','scene_count':len(rows),'measurement_failure_count':len(c['failures'])})
    manifest={'contract_id':'storygen.feature-set','contract_version':'1.4','block_version':'1.4.1','feature_set_id':feature_set_id,'source':{'type':'original','film_set_path':str(film_set_path),'film_set_sha256':sha256_file(film_set_path),'input_root':str(input_root)},'attestation_only':False,'attestation_verified':total_fail==0,'direct_extraction_verification':{'measurement_core_version':protocol.manifest()['measurement_protocol_version'],'runtime_identity_validated':True,'measurement_failure_count':total_fail},'measurement':protocol.manifest(),'runtime_identity':runtime,'film_set_path':str(film_set_path),'films':results,'scheduler':summary,'created_at':datetime.now(timezone.utc).isoformat()}
    if selection is not None: manifest['source']['scene_selection']={'path':str(scene_selection_path),'sha256':selection_sha}
    write_json(root/'feature_set_manifest.json',manifest)
    if total_fail:raise RuntimeError(f'{total_fail} scenes measurement-ineligible; artifacts preserved')
    return manifest
