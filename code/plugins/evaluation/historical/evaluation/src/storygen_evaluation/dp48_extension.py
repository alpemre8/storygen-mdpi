"""Additive E03 DP48 adapter. Original E03 code/data and statistical kernels stay frozen."""
from collections import Counter
import csv
import hashlib
from itertools import combinations
import json
from pathlib import Path

from .io import read_json, sha256_file, write_json
from .metrics import evaluate_task, failure_record, exact_measurement
from .provenance import (validate_reference, validate_runtime, validate_source,
                         validate_curves, ArtifactResolver, structure_sha)
from .repeatability import compact, analysis, table
from .reviewer import FEATURES
from .reviewer.statistics import average, distribution, bootstrap, keyed_vectors


def observation_key(row):
    return row['condition'], row['task_id'], row['repetition_id']


def verified_observations(config):
    """Read-only lineage/metric verification, usable for old or new observations.

    No inference, source/target regeneration or artifact rewriting. Canonical
    metrics are compared to immutable old records, not substituted for them.
    """
    reference_path=Path(config['reference']['path']); reference=read_json(reference_path)
    validate_reference(reference)
    records,bindings,texts=[],[],[]
    for condition,executions in config['executions'].items():
        runtime=Path(config['tasksets'][condition]);taskset=read_json(runtime)
        validate_runtime(taskset,reference,reference_path,ArtifactResolver())
        expected=config['selection']['conditions'][condition]['projection_structure_sha256']
        if structure_sha(taskset['tasks'])!=expected:raise RuntimeError('Selected projection structure mismatch')
        for execution in executions:
            rep=execution['repetition_id'];rewrite=Path(execution['generation']);candidate=Path(execution['reanalysis'])
            rw=read_json(rewrite/'rewrite_run_manifest.json');cm=read_json(candidate/'feature_set_manifest.json')
            resolved=validate_source(cm,runtime,reference_path,reference,condition,
                                     config['gemma_server']['model_alias'],ArtifactResolver(),historical=False)
            if resolved!=rewrite:raise RuntimeError('Condition/repetition rewrite binding mismatch')
            if rw['model']['file_sha256']!=config['models']['gemma']['sha256'] or rw['decoding']!=config['decoding']:
                raise RuntimeError('Generation checkpoint/decoding mismatch')
            if cm['tasks_total']!=len(taskset['tasks']) or cm['tasks_completed']+cm['tasks_failed']!=cm['tasks_total']:
                raise RuntimeError('Measurement manifest planned denominator mismatch')
            validate_curves(taskset['tasks'],candidate,rewrite,reference_path,reference,ArtifactResolver())
            for task in taskset['tasks']:
                tid=task['task_id'];source=rewrite/'tasks'/tid;measured=candidate/'tasks'/tid
                phase=source/'phase_status.json';status=measured/'measurement_status.json'
                if not phase.is_file() or read_json(phase).get('rewrite_completed') is not True:
                    if not (source/'rewrite_failure.json').is_file():raise RuntimeError('Generation failure lacks evidence')
                    canonical=failure_record(task,'rewrite:generation_failed',condition,config['gemma_server']['model_alias'])
                    state='GENERATION_FAILED'
                elif not status.is_file() or read_json(status).get('status')!='measured':
                    if not (measured/'feature_extraction_failure.json').is_file():raise RuntimeError('Measurement failure lacks evidence')
                    canonical=failure_record(task,'reanalysis:measurement_failed',condition,config['gemma_server']['model_alias'])
                    state='REANALYSIS_FAILED'
                else:
                    ms=read_json(status)
                    hashes={name:sha256_file(source/name) for name in ('rewritten_scenes.json','transfer_plan.json')}
                    exact='sha256:'+hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                    if ms.get('source_rewrite_artifact_sha256')!=exact or ms.get('contract_equality_verified') is not True or ms['measurement']!=config['measurement'] or ms['scene_ids']!=task['source_scene_ids']:
                        raise RuntimeError('Per-task measurement/text/protocol binding mismatch')
                    features=read_json(measured/'rewritten_scene_features.json');measurements=read_json(measured/'measurement_records.json')
                    keyed_vectors(features,task['source_scene_ids'],tid)
                    if [m['scene_id'] for m in measurements]!=task['source_scene_ids']:
                        raise RuntimeError('Measurement scene identity/order mismatch')
                    for row,m in zip(features,measurements):
                        if m['status']!='measured' or exact_measurement(config['measurement'],m['provenance']):
                            raise RuntimeError('Measurement record protocol mismatch')
                        if any(row[k]!=m['features'][k.removeprefix('llm_').removesuffix('_score')] for k in FEATURES.values()):
                            raise RuntimeError('Measurement record/feature disagreement')
                    canonical=evaluate_task(task,measured,reference['measurement'],condition,config['gemma_server']['model_alias'])
                    state='SUCCESS' if canonical['metric_eligible'] else 'INELIGIBLE'
                record=compact(canonical,condition=condition,repetition=rep,status=state);records.append(record)
                bindings.append(dict(condition=condition,task_id=tid,base_interval_id=task['base_interval_id'],
                    repetition_id=rep,status=state,scene_ids=task['source_scene_ids'],
                    source_feature_path=task['source_feature_path'],source_feature_sha256=sha256_file(task['source_feature_path']),
                    reference_feature_path=task['reference_feature_path'],reference_feature_sha256=sha256_file(task['reference_feature_path']),
                    rewrite_task_path=str(source),measurement_task_path=str(measured),
                    artifacts={str(p):sha256_file(p) for p in [source/'transfer_plan.json',source/'rewritten_scenes.json',
                        measured/'measurement_records.json',measured/'rewritten_scene_features.json',status] if p.is_file()}))
                if phase.is_file() and read_json(phase).get('rewrite_completed') is True:
                    scenes=read_json(source/'rewritten_scenes.json')['rewritten_scenes']
                    if [s['scene_id'] for s in scenes]!=task['source_scene_ids']:raise RuntimeError('Text scene order mismatch')
                    exact=json.dumps([(s['scene_id'],s['content']) for s in scenes],ensure_ascii=False,separators=(',',':'))
                    texts.append(dict(condition=condition,task_id=tid,repetition_id=rep,
                        text_hash='sha256:'+hashlib.sha256(exact.encode()).hexdigest(),content='\n'.join(s['content'] for s in scenes)))
    return records,bindings,texts


def verify_original_records(config):
    output=Path(config['evaluation_output']);manifest=read_json(output/'EVALUATION_MANIFEST.json')
    if manifest['status']!='EVALUATED' or manifest['planned_executions']!=300:
        raise RuntimeError('Original E03 evaluation not complete')
    original=read_json(output/'TASK_RECORDS.json');bindings=read_json(output/'ARTIFACT_BINDINGS.json')
    verified,actual_bindings,_=verified_observations(config)
    if original!=verified or bindings!=actual_bindings:
        raise RuntimeError('Original records/bindings differ from verified scientific artifacts')
    cg=config['selection']['conditions']['CG-v1']['task_ids'];dp=config['selection']['conditions']['DP-v1']['task_ids']
    expected={(c,tid,rep) for c,ids in [('CG-v1',cg),('DP-v1',dp)] for tid in ids for rep in range(1,6)}
    if len(original)!=300 or {observation_key(r) for r in original}!=expected:
        raise RuntimeError('Original observation population mismatch')
    return dict(status='VERIFIED',record_count=len(original),statuses=dict(Counter(r['status'] for r in original)),
        records=dict(path=str(output/'TASK_RECORDS.json'),sha256=sha256_file(output/'TASK_RECORDS.json')),
        bindings=dict(path=str(output/'ARTIFACT_BINDINGS.json'),sha256=sha256_file(output/'ARTIFACT_BINDINGS.json')))


def merge_records(old,new,cg_ids,original_dp_ids,extension_ids):
    """Append disjoint observations; return original dictionaries unchanged."""
    if len(cg_ids)!=48 or len(set(cg_ids))!=48 or len(original_dp_ids)!=12 or len(extension_ids)!=36:
        raise RuntimeError('DP48 population counts mismatch')
    if set(original_dp_ids)&set(extension_ids) or set(original_dp_ids)|set(extension_ids)!=set(cg_ids):
        raise RuntimeError('Final DP/CG task population mismatch')
    old_keys=[observation_key(r) for r in old];new_keys=[observation_key(r) for r in new]
    expected_old={(c,tid,rep) for c,ids in [('CG-v1',cg_ids),('DP-v1',original_dp_ids)] for tid in ids for rep in range(1,6)}
    expected_new={('DP-v1',tid,rep) for tid in extension_ids for rep in range(1,6)}
    if len(old)!=300 or set(old_keys)!=expected_old or len(new)!=180 or set(new_keys)!=expected_new or set(old_keys)&set(new_keys):
        raise RuntimeError('Old/new observation keys are missing, duplicated or overlapping')
    merged=old+new
    if len(merged)!=480:raise RuntimeError('Full planned denominator mismatch')
    return merged


def full48_analysis(old,new,cg_ids,original_dp_ids,extension_ids,*,resamples=10000):
    records=merge_records(old,new,cg_ids,original_dp_ids,extension_ids)
    if len({r['base_interval_id'] for r in records})!=48:
        raise RuntimeError('DP48 requires 48 distinct base clusters')
    result=analysis(records,cg_ids,cg_ids,resamples=resamples)
    # The original wrapper's historical matched12 protocol string is metadata
    # only. Its actual resampling/population is determined by the supplied IDs.
    for row in result['paired_comparisons']:
        row['protocol_id']='E03.DP48-extension.matched48.CG-minus-DP.clustered/1.0'
    for metric in ('TI','DA','G'):
        for population in ('measurable_only','all_attempts'):
            if metric=='G' and population=='all_attempts':continue
            rows=[r for r in records if r['condition']=='DP-v1' and (population=='all_attempts' or r['measurable'])]
            values=[r[metric] if r['measurable'] else 0.0 for r in rows]
            result['confidence'].append(dict(population='E03-DP48.'+population,metric=metric,
                **bootstrap(values,[r['base_interval_id'] for r in rows],
                    'E03.DP48.clustered-repeated-observation-mean/1.0',resamples=resamples)))
    return records,result


def text_diagnostics(texts,condition,ids):
    """Original E03 exact hashes, token-set Jaccard and character distributions."""
    rows=[]
    for tid in ids:
        outputs=[r for r in texts if r['condition']==condition and r['task_id']==tid]
        pairs=list(combinations(outputs,2));similarities=[]
        for a,b in pairs:
            x,y=set(a['content'].casefold().split()),set(b['content'].casefold().split())
            similarities.append(len(x&y)/len(x|y) if x|y else 1.0)
        rows.append(dict(condition=condition,task_id=tid,available_outputs=len(outputs),compared_pairs=len(pairs),
            identical_pairs=sum(a['text_hash']==b['text_hash'] for a,b in pairs),unique_output_hashes=len({r['text_hash'] for r in outputs}),
            mean_pairwise_token_set_Jaccard=average(similarities),character_length_distribution=distribution([len(r['content']) for r in outputs]),
            output_hashes=[dict(repetition_id=r['repetition_id'],sha256=r['text_hash']) for r in outputs]))
    return rows


def read_old_text_diagnostics(path):
    rows=[]
    with Path(path).open() as handle:
        for row in csv.DictReader(handle):
            for key in ('available_outputs','compared_pairs','identical_pairs','unique_output_hashes'):row[key]=int(row[key])
            row['mean_pairwise_token_set_Jaccard']=float(row['mean_pairwise_token_set_Jaccard']) if row['mean_pairwise_token_set_Jaccard'] else None
            for key in ('character_length_distribution','output_hashes'):row[key]=json.loads(row[key])
            rows.append(row)
    return rows


def prepare_tables(output,ids):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    metrics=('conditional_TI','conditional_DA','ATI','ADA_all','dB','dA','G','measurable_n',
             'GENERATION_FAILED_n','REANALYSIS_FAILED_n','INELIGIBLE_n')
    table(output/'T03_FULL48_REPEATS.csv',[dict(condition=c,repetition_id=rep,attempted_n=48,
        **{key:'NOT_RUN' for key in metrics}) for c in ('CG-v1','DP-v1') for rep in range(1,6)])
    table(output/'T03_FULL48_MEAN_SD.csv',[dict(condition=c,metric=m,mean='NOT_RUN',SD_sample_ddof1='NOT_RUN')
        for c in ('CG-v1','DP-v1') for m in ('conditional_TI','conditional_DA','ATI','ADA_all','G','dB','dA')])
    table(output/'T03_FULL48_PAIRED.csv',[dict(metric=m,population=p,planned_pairs=240,planned_base_clusters=48,
        CG_minus_DP='NOT_RUN',SD='NOT_RUN',ci95='NOT_RUN',paired_measurable_n='NOT_RUN')
        for m in ('TI','DA','G') for p in ('paired_measurable','all_attempts') if not(m=='G' and p=='all_attempts')])
    table(output/'T03_FULL48_TASK_STABILITY.csv',[dict(condition=c,task_id=tid,repetitions=5,
        TI_successes='NOT_RUN',TI_success_frequency='NOT_RUN',DA_mean='NOT_RUN',DA_SD='NOT_RUN',gain_distribution='NOT_RUN',failures='NOT_RUN')
        for c in ('CG-v1','DP-v1') for tid in ids])
    table(output/'T03_FULL48_TI_HISTOGRAM.csv',[dict(condition=c,TI_successes_out_of_5=i,task_count='NOT_RUN')
        for c in ('CG-v1','DP-v1') for i in range(6)])
    table(output/'T03_FULL48_CONFIDENCE.csv',[dict(condition=c,metric=m,population=p,point='NOT_RUN',ci95='NOT_RUN')
        for c in ('CG-v1','DP-v1') for m in ('TI','DA','G') for p in ('measurable_only','all_attempts') if not(m=='G' and p=='all_attempts')])
    table(output/'T03_FULL48_TEXT_VARIABILITY.csv',[dict(condition=c,task_id=tid,available_outputs='NOT_RUN',
        identical_pairs='NOT_RUN',mean_pairwise_token_set_Jaccard='NOT_RUN',character_length_distribution='NOT_RUN')
        for c in ('CG-v1','DP-v1') for tid in ids])


def scene_bindings(bindings):
    """Explicit hashes for each planned scene; missing/failing outputs stay unavailable."""
    rows=[]
    def digest(value):
        return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    for binding in bindings:
        rewrite=Path(binding['rewrite_task_path'])/'rewritten_scenes.json'
        measurements=Path(binding['measurement_task_path'])/'measurement_records.json'
        scenes=read_json(rewrite)['rewritten_scenes'] if rewrite.is_file() else []
        scores=read_json(measurements) if measurements.is_file() else []
        if binding['status']=='SUCCESS' and (not scenes or not scores):
            raise RuntimeError('Successful historical/new scene binding lacks artifacts')
        if len({r['scene_id'] for r in scenes})!=len(scenes) or len({r['scene_id'] for r in scores})!=len(scores):
            raise RuntimeError('Ambiguous scene binding')
        by_scene={r['scene_id']:r for r in scenes};by_score={r['scene_id']:r for r in scores}
        if not set(by_scene)<=set(binding['scene_ids']) or not set(by_score)<=set(binding['scene_ids']):
            raise RuntimeError('Scene binding outside planned task population')
        for sid in binding['scene_ids']:
            scene=by_scene.get(sid);measurement=by_score.get(sid)
            rows.append(dict(condition=binding['condition'],task_id=binding['task_id'],
                base_interval_id=binding['base_interval_id'],repetition_id=binding['repetition_id'],scene_id=sid,
                task_status=binding['status'],rewrite_output_path=str(rewrite),
                rewrite_output_hash=sha256_file(rewrite) if rewrite.is_file() else None,
                rewrite_scene_hash=digest(scene) if scene is not None else None,
                feature_measurement_path=str(measurements),
                feature_measurement_file_hash=sha256_file(measurements) if measurements.is_file() else None,
                feature_measurement_hash=digest(measurement) if measurement is not None else None,
                measurement_status=measurement['status'] if measurement is not None else 'UNAVAILABLE'))
    return rows


def evaluate_extended(config):
    history=config['history'];old=read_json(history['records']['path']);old_bindings=read_json(history['bindings']['path'])
    for key in ('records','bindings','text_diagnostics'):
        if sha256_file(history[key]['path'])!=history[key]['sha256']:raise RuntimeError('Immutable old evaluation checksum changed')
    new,bindings,texts=verified_observations(config)
    ids=config['populations'];records,result=full48_analysis(old,new,ids['CG-v1'],ids['DP-original-12'],ids['DP-extension-36'])
    text_rows=read_old_text_diagnostics(history['text_diagnostics']['path'])+text_diagnostics(texts,'DP-v1',ids['DP-extension-36'])
    if len(text_rows)!=96 or {(r['condition'],r['task_id']) for r in text_rows}!={(c,tid) for c in ('CG-v1','DP-v1') for tid in ids['CG-v1']}:
        raise RuntimeError('Text diagnostics population mismatch')
    output=Path(config['evaluation_output']);output.mkdir(parents=True,exist_ok=False)
    write_json(output/'TASK_RECORDS.json',records);write_json(output/'NEW_DP_RECORDS.json',new)
    write_json(output/'ARTIFACT_BINDINGS.json',old_bindings+bindings)
    per_scene=scene_bindings(old_bindings+bindings)
    if len(per_scene)!=4000:raise RuntimeError('Full48 planned scene binding count mismatch')
    write_json(output/'SCENE_BINDINGS.json',per_scene)
    old_keys={observation_key(r) for r in old}
    write_json(output/'OBSERVATION_ORIGINS.json',[dict(condition=r['condition'],task_id=r['task_id'],repetition_id=r['repetition_id'],
        origin='IMMUTABLE_ORIGINAL_E03' if observation_key(r) in old_keys else 'NEW_DP36_EXTENSION',status=r['status']) for r in records])
    for name,rows in result.items():write_json(output/(name.upper()+'.json'),rows)
    table(output/'T03_CG_FULL48.csv',[r for r in result['per_repetition'] if r['population']=='E03-A'])
    table(output/'T03_DP_FULL48.csv',[r for r in result['per_repetition'] if r['condition']=='DP-v1'])
    table(output/'T03_FULL48_REPEATS.csv',[r for r in result['per_repetition'] if r['population']=='E03-B'])
    table(output/'T03_FULL48_MEAN_SD.csv',[r for r in result['across_repetitions'] if r['population']=='E03-B'])
    table(output/'T03_FULL48_PAIRED.csv',result['paired_comparisons'])
    table(output/'T03_FULL48_PAIRED_COVERAGE.csv',result['paired_repetition_coverage'])
    table(output/'T03_FULL48_TASK_STABILITY.csv',result['stability'])
    table(output/'T03_FULL48_TI_HISTOGRAM.csv',result['TI_histogram'])
    table(output/'T03_FULL48_CONFIDENCE.csv',result['confidence'])
    table(output/'T03_FULL48_TEXT_VARIABILITY.csv',text_rows)
    table(output/'T03_FULL48_FAILURES.csv',[dict(condition=c,status=s,count=sum(r['condition']==c and r['status']==s for r in records))
        for c in ('CG-v1','DP-v1') for s in ('SUCCESS','GENERATION_FAILED','REANALYSIS_FAILED','INELIGIBLE')])
    write_json(output/'EVALUATION_MANIFEST.json',dict(status='EVALUATED',scientific_pass_claimed=False,
        planned_observations=480,planned_per_condition=240,distinct_base_intervals=48,
        reused_old_records=300,new_DP_records=180,history=history,source_commits=config['source_commits'],
        statuses=dict(Counter(r['status'] for r in records)),measurement=config['measurement'],reference=config['reference'],
        estimands={'TI_DA':'unchanged canonical task-macro metrics; conditional vs failure-zero ATI/ADA separately',
          'distance':'signed dB-dA among measurable observations only; no imputed failures',
          'paired':'strict task_id + repetition_id; CG minus DP on common 48 tasks; paired-measurable and all-attempt TI/DA separately',
          'SD':'sample SD ddof1 across defined repetition means; separate from uncertainty; defined count reported',
          'CI':'existing base_interval_id cluster bootstrap; retain all five planned repetitions/available measured rows within base; 10000 resamples, NumPy PCG64 default_rng(42), 95% percentile linear; pooled observation sum/count. 48 planned clusters; measurable represented count reported.',
          'limitations':'Overlap/film dependence and measurable missingness remain; controlled seeds do not guarantee hardware-independent bitwise output; no p-values or significance claims.'}))
    return output
