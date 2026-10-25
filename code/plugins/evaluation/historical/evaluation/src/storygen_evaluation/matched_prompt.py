"""T04 matched numeric-package analysis; unchanged canonical metric/CI kernels."""
from collections import Counter
from pathlib import Path
from .io import write_json
from .dp48_extension import verified_observations,scene_bindings
from .repeatability import table,summarize
from .reviewer.statistics import average,bootstrap

CONDITIONS=('MP-DIR-v1','MP-NUM-v1')
METRICS=('G','TI','DA','dB','dA')


def analysis(records,tasks,*,resamples=10000):
    ids=[t['task_id'] for t in tasks];by_task={t['task_id']:t for t in tasks}
    expected={(c,t) for c in CONDITIONS for t in ids};keys=[(r['condition'],r['task_id']) for r in records]
    if len(ids)!=96 or len(set(ids))!=96 or len(records)!=192 or set(keys)!=expected:
        raise RuntimeError('T04 requires exactly 96 strict task pairs')
    bases=Counter(t['base_interval_id'] for t in tasks)
    if len(bases)!=48 or set(bases.values())!={2}:raise RuntimeError('T04 requires 48 two-task clusters')
    by={(r['condition'],r['task_id']):r for r in records}
    for r in records:
        t=by_task[r['task_id']]
        if r['base_interval_id']!=t['base_interval_id'] or r['feature']!=t['selected_features'][0] or r['interval_type']!=t['interval_type']:
            raise RuntimeError('T04 record task/base/feature binding mismatch')
        if r['measurable'] and (any(r[k] is None for k in METRICS) or r['G']!=r['dB']-r['dA']):
            raise RuntimeError('T04 signed gain mismatch')
        if not r['measurable'] and any(r[k] is not None for k in METRICS):raise RuntimeError('T04 unavailable distances must remain missing')
    pairs=[(by[CONDITIONS[0],tid],by[CONDITIONS[1],tid]) for tid in ids]
    measured=[(a,b) for a,b in pairs if a['measurable'] and b['measurable']]
    if any(a['dB']!=b['dB'] for a,b in measured):raise RuntimeError('T04 paired source-target distance mismatch')
    summaries=[dict(condition=c,**summarize([r for r in records if r['condition']==c])) for c in CONDITIONS]
    result=[]
    for population,metric in [('paired_measurable',m) for m in METRICS]+[('all_attempts','TI'),('all_attempts','DA')]:
        rows=measured if population=='paired_measurable' else pairs
        av=[a[metric] if a['measurable'] else 0.0 for a,b in rows];bv=[b[metric] if b['measurable'] else 0.0 for a,b in rows]
        delta=[b-a for a,b in zip(av,bv)]
        estimate=bootstrap(delta,[a['base_interval_id'] for a,b in rows],'E04.MP-NUM-minus-MP-DIR.base-clustered/1.0',resamples=resamples)
        result.append(dict(Metric=metric,population=population,**{CONDITIONS[0]:average(av),CONDITIONS[1]:average(bv)},
            MP_NUM_minus_MP_DIR=average(delta),matched_denominator=len(rows),planned_pairs=96,**estimate))
    film=[]
    for metric in ('G','TI','DA'):
        delta=[b[metric]-a[metric] for a,b in measured]
        film.append(dict(metric=metric,label='EXPLORATORY source-film-clustered sensitivity; ten films maximum',
            **bootstrap(delta,[by_task[a['task_id']]['source_film_id'] for a,b in measured],'E04.exploratory.source-film/1.0',resamples=resamples)))
    subgroup=[]
    for field,values in [('feature',sorted({r['feature'] for r in records})),('interval_type',['short','medium','long'])]:
        for value in values:
            rows=[(a,b) for a,b in measured if a[field]==value]
            subgroup.append(dict(group=field,value=value,label='DESCRIPTIVE',planned_pairs=sum(t['selected_features'][0]==value if field=='feature' else t[field]==value for t in tasks),
                measurable_pairs=len(rows),DIR_G=average([a['G'] for a,b in rows]),NUM_G=average([b['G'] for a,b in rows]),Delta_G=average([b['G']-a['G'] for a,b in rows])))
    gains=[dict(task_id=a['task_id'],base_interval_id=a['base_interval_id'],feature=a['feature'],interval_type=a['interval_type'],
        DIR_status=a['status'],NUM_status=b['status'],paired_measurable=a['measurable'] and b['measurable'],
        DIR_G=a['G'],NUM_G=b['G'],Delta_G=b['G']-a['G'] if a['measurable'] and b['measurable'] else None,
        **{c+'_distance_change':('positive' if r['G']>0 else 'negative' if r['G']<0 else 'tied') if r['measurable'] else 'unavailable' for c,r in zip(CONDITIONS,(a,b))}) for a,b in pairs]
    failures=[r for r in records if not r['measurable']]
    return dict(T04=result,CONDITIONAL_AND_ALL_ATTEMPT=summaries,FEATURE_LENGTH=subgroup,TASK_GAINS=gains,FAILURES=failures,
        EXPLORATORY_FILM=film,COVERAGE=[dict(planned_pairs=96,measurable_pairs=len(measured),failed_or_ineligible_pairs=96-len(measured),planned_clusters=48,
        represented_measurable_clusters=len({a['base_interval_id'] for a,b in measured}))])


def prepare_tables(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    table(output/'T04_NOT_RUN.csv',[dict(Metric=m,population=p,**{c:'NOT_RUN' for c in CONDITIONS},MP_NUM_minus_MP_DIR='NOT_RUN',CI95='NOT_RUN',matched_denominator='NOT_RUN',planned_pairs=96)
        for p,m in [('paired_measurable',m) for m in METRICS]+[('all_attempts','TI'),('all_attempts','DA')]])


def evaluate(config):
    import json
    records,bindings,_=verified_observations(config)
    tasks=json.loads(Path(config['tasksets'][CONDITIONS[0]]).read_text())['tasks']
    other=json.loads(Path(config['tasksets'][CONDITIONS[1]]).read_text())['tasks']
    if tasks!=other:raise RuntimeError('T04 paired tasks/source/reference differ')
    result=analysis(records,tasks)
    output=Path(config['evaluation_output']);output.mkdir(parents=True,exist_ok=False)
    write_json(output/'TASK_RECORDS.json',records);write_json(output/'ARTIFACT_BINDINGS.json',bindings)
    write_json(output/'SCENE_BINDINGS.json',scene_bindings(bindings))
    for name,rows in result.items():
        write_json(output/(name+'.json'),rows)
        if rows:table(output/(name+'.csv'),rows)
    write_json(output/'EVALUATION_MANIFEST.json',dict(experiment_id=config['experiment_id'],status='EVALUATED',scientific_pass_claimed=False,
        planned_executions=192,conditions=CONDITIONS,source_commits=config['source_commits'],measurement=config['measurement'],selection=config['selection'],
        estimands=dict(primary='G = canonical before-target MAE minus after-target MAE; signed; MP-NUM minus MP-DIR actual paired task differences',
        weighting='task-macro pooled mean, two tasks retained per drawn base; available paired tasks determine represented cluster sizes',
        CI='canonical bootstrap: 10000 PCG64 default_rng(42), base_interval_id, percentile95 linear; constant/fewer than two clusters give canonical undefined CI reason',
        failure_policy='all 96 attempted tasks retained per condition; TI/DA zero for failures only in all-attempt estimands; never invent G/distance',
        limitations='joint current/target/delta package only; new matched prompts do not reproduce historical DP/CG. Qwen extractor dependence; no human preference/naturalness or extractor-independence claims. One realization per task/condition cannot estimate within-task variance. Matched seeds control variance without eliminating stochastic differences. Film sensitivity exploratory, ten films; subgroup results descriptive; no p-values; CI including zero does not prove equivalence.'),
        statuses=dict(Counter(r['status'] for r in records))))
    return output
