"""E04-only bindings. Canonical engines, scheduler, transport and repair unchanged.

Both arms enter the same canonical curve-guided engine branch; only its prompt
builder/system and experiment-specific provenance checks are scoped overrides.
Historical DP/CG/NG calls outside this context retain their original bindings.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import threading
from unittest.mock import patch
import numpy as np
from .provenance import sha256_json
from .repeatability import payload_for, SELECTION_FIELDS
from storygen.services import per_scene_rewrite_engine as engine
from storygen.services.rewrite_engine import _truncate_scene_text
from storygen.schemas.transfer import TransferPlan
from storygen.services.transfer_planner import _round as canonical_numeric_precision

CONDITIONS=('MP-DIR-v1','MP-NUM-v1')
SELECTION_SEED=4204
PROTOCOL='E04.seed.v1'
ALLOWED_PATHS=[f'feature_guidance.numeric_guidance.{k}' for k in ('current','target','delta')]
ASSETS=Path(__file__).resolve().parents[3]/'prompts'


def select_tasks(tasks):
    metadata=[{k:t[k] for k in SELECTION_FIELDS} for t in tasks]
    groups=defaultdict(list)
    for t in metadata:groups[t['base_interval_id']].append(t)
    features=sorted({t['selected_features'][0] for t in metadata})
    if len(metadata)!=240 or len(groups)!=48 or len(features)!=5 or any(len(g)!=5 or {t['selected_features'][0] for t in g}!=set(features) for g in groups.values()):
        raise RuntimeError('E04 requires exactly 48 bases with all five single-feature tasks')
    for base,g in groups.items():
        for field in ('source_film_id','interval_type','source_scene_ids'):
            if any(t[field]!=g[0][field] for t in g):raise RuntimeError('E04 inconsistent source interval metadata')
    rng=np.random.default_rng(SELECTION_SEED);bases=sorted(groups);rng.shuffle(bases);rng.shuffle(features)
    # 96 cyclic feature labels => 20/19/19/19/19; consecutive pairs differ.
    chosen=[next(t for t in groups[b] if t['selected_features']==[features[(2*i+j)%5]]) for i,b in enumerate(bases) for j in range(2)]
    chosen.sort(key=lambda t:t['task_id'])
    if sorted(Counter(t['selected_features'][0] for t in chosen).values())!=[19,19,19,19,20] or Counter(t['interval_type'] for t in chosen)!={'short':32,'medium':32,'long':32} or len({t['source_film_id'] for t in chosen})!=10 or sum(len(t['source_scene_ids']) for t in chosen)!=800:
        raise RuntimeError('E04 selection feature/length/film/scene constraints conflict')
    return chosen


def request_seed(task_id,scene_id,attempt):
    raw=f'{PROTOCOL}|{task_id}|{scene_id}|{attempt}'
    return 1+int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8],'big')%2147483646


def system():return (ASSETS/'matched_prompt_system_e04_v1.txt').read_text()


def render(condition,*,scene,directive,plan,scene_position_index,scene_count,max_scene_chars,**_):
    if condition not in CONDITIONS or len(plan.selected_features)!=1 or directive.scene_id!=scene.scene_id:
        raise RuntimeError('E04 single-feature scene identity mismatch')
    feature=plan.selected_features[0]
    if any(set(v)!={feature} for v in (directive.current_values,directive.targets,directive.deltas)):
        raise RuntimeError('E04 frozen numeric package feature mismatch')
    i=plan.source_scene_ids.index(scene.scene_id)
    current,target,delta=(v[feature] for v in (directive.current_values,directive.targets,directive.deltas))
    if current!=plan.source_current_curve[feature][i] or target!=plan.resampled_target_curve[feature][i] or delta!=canonical_numeric_precision(target-current):
        raise RuntimeError('E04 frozen plan numeric consistency mismatch')
    if any(ch.isdigit() for ch in directive.directive) or 'reference' in directive.directive.lower():
        raise RuntimeError('E04 direction directive contains numeric/reference metadata')
    content,truncated=_truncate_scene_text(scene.content,max_scene_chars=max_scene_chars)
    payload=json.loads((ASSETS/'matched_prompt_user_e04_v1.json').read_text())
    replacements={'__FEATURE__':feature,'__DIRECTION__':directive.directive,'__CURRENT__':current if condition==CONDITIONS[1] else None,
        '__TARGET__':target if condition==CONDITIONS[1] else None,'__DELTA__':delta if condition==CONDITIONS[1] else None,
        '__SOURCE_SCENE__':dict(scene_id=scene.scene_id,title=scene.title,scene_index=scene.scene_index,content=content),
        '__CONTEXT__':dict(source_interval_scene_ids=plan.source_scene_ids,zero_based_index=scene_position_index,scene_count=scene_count,was_truncated=truncated),
        '__PRESERVATION__':plan.preservation_constraints,'__SCENE_ID__':scene.scene_id}
    payload=engine._fill_rewrite_prompt_template(payload,replacements)
    return json.dumps(payload,ensure_ascii=False,indent=2)


def normalized_request(payload):
    copy=json.loads(json.dumps(payload))
    if len(copy['messages'])!=2 or [m['role'] for m in copy['messages']]!=['system','user']:
        raise RuntimeError('E04 requires shared system/user roles')
    user=json.loads(copy['messages'][1]['content'])
    if copy['messages'][1]['content']!=json.dumps(user,ensure_ascii=False,indent=2):
        raise RuntimeError('E04 user serialization differs outside allowed numeric values')
    if set(user['feature_guidance']['numeric_guidance'])!={'current','target','delta'}:
        raise RuntimeError('E04 numeric field structure changed')
    for k in ('current','target','delta'):user['feature_guidance']['numeric_guidance'][k]=None
    copy['messages'][1]['content']=json.dumps(user,ensure_ascii=False,indent=2)
    return copy


def compare_pair(a,b):
    if normalized_request(a)!=normalized_request(b):raise RuntimeError('Unexpected E04 model-facing difference')
    if any(x is not None for x in json.loads(a['messages'][1]['content'])['feature_guidance']['numeric_guidance'].values()):
        raise RuntimeError('MP-DIR numeric values must be null')
    if any(type(x) not in (int,float) for x in json.loads(b['messages'][1]['content'])['feature_guidance']['numeric_guidance'].values()):
        raise RuntimeError('MP-NUM numeric values must come from frozen plan')
    return dict(dir_prompt_sha256=sha256_json(a['messages']),num_prompt_sha256=sha256_json(b['messages']),
        matched_template_sha256=sha256_json(normalized_request(a)),allowed_numeric_diff_paths=ALLOWED_PATHS,all_other_fields_equal=True)


def prompt_provenance(*_):
    files={k:ASSETS/name for k,name in [('system_prompt','matched_prompt_system_e04_v1.txt'),('user_prompt','matched_prompt_user_e04_v1.json'),('repair_prompt','repair_per_scene_prompt_v1.json')]}
    result={k:dict(path=str(p),sha256='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for k,p in files.items()}
    result['prompt_bundle_sha256']=sha256_json(result);result['contract_id']='E04.matched-prompt.v1';return result


class SeededClient:
    def __init__(self,delegate,*,config,condition,context,output,abort):
        self.delegate=delegate;self.config=config;self.condition=condition;self.context=context;self.output=output;self.abort=abort
        self.tasks={t['task_id']:t for t in json.loads(Path(config['tasksets'][condition]).read_text())['tasks']}
        self.primary={(p['task_id'],p['scene_id']):p for p in json.loads(Path(config['primary_requests']).read_text()) if p['condition']==condition}
        self.count=Counter();self.lock=threading.Lock();output.mkdir(parents=True,exist_ok=True);self.audit=(output/'E04_REQUESTS.jsonl').open('x')
    def generate(self,prompt,model,**kwargs):
        if self.abort.is_set():raise RuntimeError('E04 stopped after provenance failure')
        tid=self.context.task_id;sid=kwargs['request_metadata']['scene_id'];task=self.tasks[tid]
        with self.lock:self.count[tid,sid]+=1;attempt=self.count[tid,sid]
        payload=payload_for(prompt,model,**kwargs)
        if attempt>2 or (attempt==1 and sha256_json(payload)!=self.primary[tid,sid]['request_contract_hash']):
            self.abort.set();raise RuntimeError('E04 frozen primary request or bounded repair mismatch')
        seed=request_seed(tid,sid,attempt);kwargs['options']={**kwargs.get('options',{}),'seed':seed}
        p=self.primary[tid,sid]
        record=dict(experiment_id=self.config['experiment_id'],condition=self.condition,task_id=tid,base_interval_id=task['base_interval_id'],
            feature=task['selected_features'][0],scene_id=sid,attempt=attempt,source_scene_hash=p['source_scene_hash'],target_plan_hash=p['target_plan_hash'],
            prompt_hash=sha256_json(payload['messages']),sampling_seed=seed,request_sha256=sha256_json({**payload,'seed':seed}),
            model_checkpoint_sha256=self.config['models']['gemma']['sha256'],generation_settings=kwargs['options'],
            output_path=str(self.output/'tasks'/tid/'per_scene'/sid),output_hash=None,completion_status='REQUEST_STARTED',failure_reason=None)
        self.log(record)
        try:response=self.delegate.generate(prompt,model,**kwargs)
        except Exception as exc:
            self.log({**record,'completion_status':'TRANSPORT_FAILED','failure_reason':str(exc)});raise
        self.log({**record,'completion_status':'RESPONSE_RECEIVED','output_hash':'sha256:'+hashlib.sha256(response.encode()).hexdigest()})
        return response
    def log(self,r):
        with self.lock:self.audit.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n');self.audit.flush()
    def close(self):
        try:self.delegate.close()
        finally:self.audit.close()


@contextmanager
def runner_bindings(*,runner,config,condition,output,client_factory=None):
    from storygen_feature.progress import ProgressReporter
    canonical_client=client_factory or runner.VLLMClient;canonical_engine=runner.run_per_scene_rewrite_from_files
    context=threading.local();abort=threading.Event()
    expected_requests={(p['task_id'],p['scene_id']):p for p in json.loads(Path(config['primary_requests']).read_text()) if p['condition']==condition}
    def factory(**kwargs):return SeededClient(canonical_client(**kwargs),config=config,condition=condition,context=context,output=output,abort=abort)
    def frozen_plan(**kwargs):return TransferPlan.model_validate(json.loads((Path(config['frozen_plans'])/'tasks'/kwargs['run_id']/'transfer_plan.json').read_text()))
    def call_engine(**kwargs):
        context.task_id=Path(kwargs['plan_path']).parent.name
        if json.loads(Path(kwargs['plan_path']).read_text())!=frozen_plan(run_id=context.task_id).model_dump(mode='json'):
            abort.set();raise RuntimeError('E04 frozen transfer plan changed')
        return canonical_engine(**kwargs)
    def check(task_dir,strategy):
        for path in task_dir.glob('per_scene/*/rewrite_request.json'):
            r=json.loads(path.read_text());p=expected_requests[task_dir.name,r['expected_scene_id']]
            actual=payload_for(r['user_instruction'],r['model'],system=r['system_instruction'],format_schema=r['format_schema'],format_json=r['format_json'],options={'temperature':r['temperature'],'max_tokens':r['rewrite_max_tokens']})
            if sha256_json(actual)!=p['request_contract_hash']:abort.set();raise RuntimeError('E04 saved request differs from frozen model-facing contract')
    class Progress:
        def __init__(self,total):self.r=ProgressReporter(label=f'E04 | {condition} | GENERATION',total=total,mode='always')
        def tick(self,label):
            tid,sid=label.split('/');p=output/'tasks'/tid/'per_scene'/sid/'scene_summary.json'
            self.r.request_finished(label,successful=p.is_file() and json.loads(p.read_text()).get('succeeded') is True)
        def finish(self):self.r.finish()
    with ExitStack() as stack:
        for obj,name,value in [(runner,'VLLMClient',factory),(runner,'Progress',Progress),(runner,'run_per_scene_rewrite_from_files',call_engine),
            (runner,'create_transfer_plan_from_feature_files',frozen_plan),(runner,'prompt_provenance',prompt_provenance),(runner,'_forbid_prompt',check),
            (engine,'_prompt_profile',lambda strategy:'E04.matched-prompt.v1'),(engine,'build_per_scene_rewrite_prompt',lambda **kw:render(condition,**kw)),(engine,'_per_scene_system_instruction',lambda **kw:system())]:
            stack.enter_context(patch.object(obj,name,value))
        yield abort
