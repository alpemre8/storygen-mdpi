#!/usr/bin/env python3
"""CPU-only replay from released numeric observations; never performs inference."""
from pathlib import Path
from collections import defaultdict
import argparse, csv, gzip, hashlib, json, math, socket, sys

ROOT=Path(__file__).resolve().parents[1]
CODE=ROOT/'code'
sys.path[:0]=[str(CODE/'src'),str(CODE/'plugins/evaluation/historical/evaluation/src'),str(CODE/'plugins/feature_extraction/historical/feature_extraction/src'),str(CODE/'plugins/feature_extraction/historical/measurement/src')]
from storygen_platform.engine.science_io import standalone_scope

def no_network(*args,**kwargs):raise RuntimeError('Network connections are forbidden in numeric replay')
socket.socket.connect=no_network
socket.socket.connect_ex=no_network
socket.create_connection=no_network

def read(p):
    p=Path(p)
    return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def write(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
def csv_read(p):
    with Path(p).open(newline='') as f:return list(csv.DictReader(f))
def csv_write(p,rows):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def equal(a,b,where=''):
    if isinstance(a,(float,int)) and not isinstance(a,bool) and isinstance(b,(float,int)) and not isinstance(b,bool):
        if not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12):raise AssertionError((where,a,b))
    elif isinstance(a,dict) and isinstance(b,dict):
        if set(a)!=set(b):raise AssertionError((where,'keys',set(a)^set(b)))
        for k in a:equal(a[k],b[k],where+'/'+k)
    elif isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):raise AssertionError((where,'length',len(a),len(b)))
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,where+'/'+str(i))
    elif a!=b:raise AssertionError((where,a,b))
def cell(v):
    if v in ('','NA','None'):return None
    try:return json.loads(v)
    except (ValueError,TypeError):
        if v=='True':return True
        if v=='False':return False
        try:return float(v)
        except (TypeError,ValueError):return v
def compare_csv(actual,recorded,*,omit_references=False):
    a,b=csv_read(actual),csv_read(recorded)
    if omit_references:
        b=[{k:v for k,v in row.items() if not k.endswith('_reference')} for row in b]
    equal([{k:cell(v) for k,v in r.items()} for r in a],[{k:cell(v) for k,v in r.items()} for r in b],str(recorded.relative_to(ROOT)))
def one(pattern):
    found=list(ROOT.glob(pattern))
    if len(found)!=1:raise RuntimeError((pattern,'expected exactly one source',len(found)))
    return found[0]

def schemas():
    from jsonschema import Draft202012Validator
    schema=read(CODE/'plugins/feature_extraction/historical/measurement/schemas/narrative_feature_schema_v1.json')
    Draft202012Validator.check_schema(schema)
    validator=Draft202012Validator(schema)
    good={'features':{k:0.5 for k in schema['properties']['features']['required']}}
    validator.validate(good)
    bad=[good['features'],{'features':{**good['features'],'extra':0.5}},{'features':dict(list(good['features'].items())[:4])},{'features':{**good['features'],'pacing':1.1}},{**good,'extra':1}]
    for value in bad:
        if not list(validator.iter_errors(value)):raise AssertionError('Invalid response accepted')
    return dict(status='PASS',invalid_examples_rejected=len(bad),structure='one outer features object, exactly five inner keys')

def paper(out):
    from storygen_evaluation.paper_ready import TABLE8_FEATURE_ORDER,TABLE10_FEATURE_ORDER,FEATURE_DISPLAY,INTERVAL_ORDER,INTERVAL_DISPLAY
    rows={}
    for directory in sorted((ROOT/'data/benchmark').iterdir()):
        records=[json.loads(x) for x in (directory/'evaluation_task_records.jsonl').read_text().splitlines() if x.strip()]
        if len(records)!=240 or len({r['task_id'] for r in records})!=240:raise AssertionError('Benchmark task population')
        manifest=read(directory/'evaluation_run_manifest.json')
        rows[(manifest['rewrite_model'],manifest['method'])]={r['task_id']:r for r in records}
    models=[('qwen2.5-7b-q4','Qwen2.5-7B'),('llama3.1-8b-instruct-gguf','Llama-3.1-8B'),('qwen3.5-9b-gguf','Qwen3.5-9B'),('gemma3-12b-it-gguf','Gemma-3-12B')]
    ids=set(next(iter(rows.values())))
    common=sorted(t for t in ids if all(r[t]['metric_eligible'] for r in rows.values()))
    if len(common)!=186:raise AssertionError('Global common population changed')
    def pct(value):return f'{100*value:.2f}%'
    def metrics(model,condition,selected):
        r=[rows[model,condition][t] for t in selected]
        return sum(x['target_improved'] for x in r)/len(r),sum(x['directional_accuracy'] for x in r)/len(r)
    t6=[];t7=[]
    for model,label in models:
        for c in ['DP-v1','CG-v1']:
            ti,da=metrics(model,c,common);t6.append(dict(model=label,condition=c,target_improvement=pct(ti),directional_accuracy=pct(da)))
        pair=sorted(t for t in ids if all(rows[model,c][t]['metric_eligible'] for c in ['DP-v1','CG-v1']))
        dt,dd=metrics(model,'DP-v1',pair);ct,cd=metrics(model,'CG-v1',pair)
        t7.append(dict(model=label,dp_valid=sum(r['metric_eligible'] for r in rows[model,'DP-v1'].values()),cg_valid=sum(r['metric_eligible'] for r in rows[model,'CG-v1'].values()),pair_n=len(pair),dp_ti=pct(dt),cg_ti=pct(ct),dp_da=pct(dd),cg_da=pct(cd)))
    primary=models[-1][0];pair=sorted(t for t in ids if all(rows[primary,c][t]['metric_eligible'] for c in ['DP-v1','CG-v1']))
    tables={'table6_global_common.csv':t6,'table7_within_model_paired.csv':t7}
    for field,groups,filename in [('feature',TABLE8_FEATURE_ORDER,'table8_primary_by_feature.csv'),('interval_type',INTERVAL_ORDER,'table9_primary_by_length.csv')]:
        values=[]
        for group in groups:
            selected=[t for t in pair if rows[primary,'DP-v1'][t][field]==('llm_'+group+'_score' if field=='feature' else group)]
            dt,dd=metrics(primary,'DP-v1',selected);ct,cd=metrics(primary,'CG-v1',selected)
            values.append({('feature' if field=='feature' else 'interval'):(FEATURE_DISPLAY[group] if field=='feature' else INTERVAL_DISPLAY[group]),'pair_n':len(selected),'dp_ti':pct(dt),'cg_ti':pct(ct),'dp_da':pct(dd),'cg_da':pct(cd)})
        tables[filename]=values
    import numpy as np
    from scipy.stats import spearmanr
    from storygen_feature.reliability import icc_3_1
    recorded=read(ROOT/'data/measurement_reliability/recorded.json');groups=defaultdict(list)
    for r in recorded['rows']:
        if r['status']=='measured':groups[(r['film_id'],r['scene_id'])].append(r)
    for g in groups.values():g.sort(key=lambda r:r['repeat'])
    values=[]
    for feature in TABLE10_FEATURE_ORDER:
        scores=[[r['features'][feature] for r in g] for g in groups.values()]
        deviations=[abs(v-float(np.mean(g))) for g in scores for v in g]
        p=dict(exact_scene_agreement_rate=sum(len(set(g))==1 for g in scores)/len(scores),mean_absolute_repeated_score_deviation=float(np.mean(deviations)),maximum_observed_deviation=max(deviations),repeat1_repeat2_spearman=float(spearmanr([g[0] for g in scores],[g[1] for g in scores]).statistic),icc_3_1_consistency_single=icc_3_1(scores))
        equal(p,recorded['per_feature'][feature],'measurement reliability/'+feature)
        values.append(dict(feature=FEATURE_DISPLAY[feature],exact_5_repeat_agreement=f"{100*p['exact_scene_agreement_rate']:.0f}%",mean_abs_deviation=f"{p['mean_absolute_repeated_score_deviation']:.5f}",max_deviation=f"{p['maximum_observed_deviation']:.2f}",spearman_rho=f"{p['repeat1_repeat2_spearman']:.4f}",icc_3_1=f"{p['icc_3_1_consistency_single']:.4f}"))
    tables['table10_extractor_repeatability.csv']=values
    for name,values in tables.items():
        p=out/'paper'/name;csv_write(p,values);compare_csv(p,ROOT/'data/paper/tables'/name)
    return dict(status='PASS',tables=list(tables),global_common_tasks=len(common),reliability_requests=len(recorded['rows']))

def e06(out):
    home=CODE/'legacy/central/experiments/reviewer_round1/e06_statistical_robustness/src'
    raw=read(ROOT/'data/e06/numeric_dataset.json.gz')
    with standalone_scope(home):
        from common import Dataset,csv_write as native_csv
        from analyses import ANALYSES
        records=defaultdict(dict)
        from storygen_evaluation.metrics import mae,directional_accuracy
        for row in raw['records']:
            if row['eligible']:
                db,da=mae(row['B'],row['T']),mae(row['A'],row['T'])
                equal([db,da,int(da<db),directional_accuracy(row['B'],row['T'],row['A'])],[row['dB'],row['dA'],row['TI'],row['DA']],row['task_id'])
            records[row['model'],row['condition']][row['task_id']]=row
        ds=Dataset(raw['tasks'],dict(records),raw['models'],{},raw['validation'],'REAL')
        count=0
        for name,fn in ANALYSES.items():
            value=fn(ds)
            for filename,rows in value['tables'].items():
                p=out/'e06'/name/filename;p.parent.mkdir(parents=True,exist_ok=True);native_csv(p,rows)
                original=one('data/e06/recorded_tables/03_analyses/'+name+'/'+filename)
                compare_csv(p,original,omit_references=True);count+=1
    return dict(status='PASS',analyses=list(ANALYSES),tables=count,tasks=len(raw['tasks']),observations=len(raw['records']),comparison='Numeric values and labels; private file reference columns omitted')

def e05(out):
    home=CODE/'legacy/central/experiments/reviewer_round1/e05_4_feature_diff/src'
    with standalone_scope(home):
        from analyze import calculate
        from aggregate import aggregate
        from report import TABLES,csv_table
        raw=read(ROOT/'data/e05_4_feature_diff/validated_numeric.json.gz');raw['provenance']={'public_numeric_derivative':True}
        scenes,tasks=calculate(raw)
        result=aggregate(raw,scenes,tasks)
        for filename,key in TABLES:
            p=out/'e05_4_feature_diff'/filename;p.parent.mkdir(parents=True,exist_ok=True);csv_table(p,result[key])
            compare_csv(p,ROOT/'data/e05_4_feature_diff/recorded_tables'/filename)
    return dict(status='PASS',tables=len(TABLES),scene_slots=len(scenes),planned_tasks=len(tasks),bootstrap_replications=2000,seed=250504)

def reviewer(out):
    from storygen_evaluation import ng_baseline,repeatability,dp48_extension,matched_prompt
    result={}
    ng=one('data/reviewer/E02_MIN_ng_v0/**/NG_TASK_RECORDS.json');ids=read(ng.with_name('MATCHED_TASK_IDS.json'))
    table,confidence=ng_baseline.summarize(read(ng),ids)
    compare=read(ng.with_name('CONFIDENCE_INTERVALS.json'))
    # The original confidence file contains three method populations; select NG.
    expected=[r for r in compare if r['condition']=='NG-v0']
    equal(confidence,expected,'E02 confidence')
    expected_csv=[r for r in csv_read(ng.with_name('T02.csv')) if r['condition']=='NG-v0']
    csv_write(out/'e02/summary.csv',table)
    equal([{k:cell(v) for k,v in r.items()} for r in csv_read(out/'e02/summary.csv')],[{k:cell(v) for k,v in r.items()} for r in expected_csv],'E02 summary')
    result['E02']=dict(status='PASS',planned_tasks=len(read(ng)),confidence_intervals=len(confidence))
    for family in ['E03_generation_repeatability','E03_DP48_extension']:
        path=one('data/reviewer/'+family+'/**/TASK_RECORDS.json');rows=read(path)
        cg=sorted({r['task_id'] for r in rows if r['condition']=='CG-v1'});dp=sorted({r['task_id'] for r in rows if r['condition']=='DP-v1'})
        if family=='E03_DP48_extension':
            original=read(one('data/reviewer/E03_generation_repeatability/**/TASK_RECORDS.json'))
            new=read(path.with_name('NEW_DP_RECORDS.json'))
            dp_old=sorted({r['task_id'] for r in original if r['condition']=='DP-v1'})
            _,values=dp48_extension.full48_analysis(original,new,cg,dp_old,sorted(set(cg)-set(dp_old)))
        else:values=repeatability.analysis(rows,cg,dp)
        for key,name in [('per_repetition','PER_REPETITION.json'),('across_repetitions','ACROSS_REPETITIONS.json'),('paired_comparisons','PAIRED_COMPARISONS.json'),('confidence','CONFIDENCE.json'),('stability','STABILITY.json'),('TI_histogram','TI_HISTOGRAM.json')]:equal(values[key],read(path.with_name(name)),family+'/'+key)
        write(out/family/'analysis.json',values)
        result[family]=dict(status='PASS',observations=len(rows),bootstrap_replications=10000)
    path=one('data/reviewer/E04_matched_prompt/**/TASK_RECORDS.json');rows=read(path)
    tasks={t['task_id']:t for t in read(ROOT/'data/tasksetv5/taskset_runtime.json')['tasks']}
    selected=sorted({r['task_id'] for r in rows})
    values=matched_prompt.analysis(rows,[tasks[t] for t in selected])
    for key,value in values.items():equal(value,read(path.with_name(key+'.json')),'E04/'+key)
    write(out/'e04/analysis.json',values);result['E04']=dict(status='PASS',planned_pairs=len(selected),observations=len(rows),bootstrap_replications=10000)
    return result

def e01b(out):
    datasets=read(ROOT/'data/e01_b/task_records.json');recorded=read(ROOT/'data/e01_b/comparison.json')
    summary=[]
    for row in recorded['table']:
        rewrite={'Qwen2.5-7B':'qwen','Gemma-3-12B':'gemma'}[row['rewrite_model']]
        key=rewrite+'_'+('dp' if row['condition']=='DP-v1' else 'cg')+' / '+row['extractor']+' / '+row['precision']
        data=datasets[key];valid=[r for r in data if r['metric_eligible']]
        value=dict(attempted_n=len(data),measurable_n=len(valid),nonmeasurable_n=len(data)-len(valid),TI=sum(r['target_improved'] for r in valid)/len(valid),DA=sum(r['directional_accuracy'] for r in valid)/len(valid),before_target_distance=sum(r['before_target_mae'] for r in valid)/len(valid),after_target_distance=sum(r['after_target_mae'] for r in valid)/len(valid),mean_gain=sum(r['before_target_mae']-r['after_target_mae'] for r in valid)/len(valid))
        equal(value,{k:row[k] for k in value},key);summary.append(dict(cell=key,**value))
    write(out/'e01_b/recomputed_summary.json',summary)
    return dict(status='PASS',comparison_cells=len(summary),scope='TI, DA, distances, mean gain and exact coverage; recorded reviewer CIs are included separately')

def cases(out):
    ds=read(ROOT/'data/e06/numeric_dataset.json.gz')
    rows=sorted([r for r in ds['records'] if r['model']=='gemma3-12b-it-gguf' and r['condition']=='CG-v1' and r['eligible']],key=lambda r:(r['G'],r['task_id']))
    strongest=min(rows,key=lambda r:(-r['G'],r['task_id']))
    cases={label:{k:r[k] for k in ['task_id','base_interval_id','screenplay_id','feature','B','T','A','TI','DA','G']} for label,r in [('strongest_gain',strongest),('median_gain',rows[len(rows)//2]),('worst_gain',rows[0])]}
    write(out/'examples/three_numeric_cases.json',cases)
    return dict(status='PASS',selection='Gemma CG-v1 eligible tasks ranked by signed gain; lower task ID breaks ties; no assertion that these are manuscript Figure 3 panels',cases={k:v['task_id'] for k,v in cases.items()})

def verify():
    manifest=read(ROOT/'MANIFEST.sha256.json')
    present={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and not any(x in p.relative_to(ROOT).parts for x in {'.git','.venv','__pycache__','.pytest_cache','reproduced','.ruff_cache','local-inputs','external-inputs'}) and p.name!='MANIFEST.sha256.json'}
    equal(sorted(present),sorted(manifest),'full release file inventory')
    for rel,expected in manifest.items():
        p=ROOT/rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise AssertionError('Checksum mismatch: '+rel)
    scope=read(ROOT/'release-scope.json')
    actual=sorted(p.name for p in (CODE/'experiments').iterdir() if p.is_dir())
    equal(actual,sorted(scope['included_experiments']),'release experiment scope')
    for path in (CODE/'experiments').iterdir():
        if path.name in scope['excluded_experiments']:raise AssertionError('Excluded experiment included')
    return dict(status='PASS',verified_files=len(manifest),schemas=schemas(),included_experiments=actual)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['verify','reproduce']);parser.add_argument('--output',type=Path,default=ROOT/'reproduced')
    args=parser.parse_args()
    if args.command=='verify':print(json.dumps(verify(),indent=2));return
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'inference_requests':0,'network_connections':'forbidden','source':'Released numeric derivatives; historical results remain separate','schemas':schemas()}
    for name,fn in [('paper',paper),('e01_b',e01b),('reviewer_experiments',reviewer),('e05_4_feature_diff',e05),('e06',e06),('balanced_examples',cases)]:
        print('Replaying '+name,flush=True);report[name]=fn(out);print(name+': PASS',flush=True)
    write(out/'REPRODUCTION_REPORT.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
