"""T03 repeated-generation adapter; delegates frozen metrics and bootstrap."""
from collections import Counter
from itertools import combinations
import csv
import json
from pathlib import Path
import statistics

from .io import read_json, sha256_file, write_json
from .metrics import evaluate_task, failure_record, exact_measurement
from .provenance import (validate_reference, validate_runtime, validate_source,
                         validate_curves, ArtifactResolver, structure_sha)
from .reviewer.statistics import average, distribution, all_attempt, bootstrap, keyed_vectors


def sd(values):
    values = [v for v in values if v is not None]
    return statistics.stdev(values) if len(values) > 1 else None


def compact(record, *, condition, repetition, status):
    eligible = record['metric_eligible']
    db, da = record['before_target_mae'], record['after_target_mae']
    return dict(task_id=record['task_id'], base_interval_id=record['base_interval_id'],
        feature=record['feature'], interval_type=record['interval_type'],
        condition=condition, repetition_id=repetition, status=status, measurable=eligible,
        failure_reason=record['ineligible_reason'], TI=float(record['target_improved']) if eligible else None,
        DA=record['directional_accuracy'] if eligible else None, dB=db if eligible else None,
        dA=da if eligible else None, G=db-da if eligible else None)


def summarize(records):
    measured = [r for r in records if r['measurable']]
    result = all_attempt(records)
    result.update({key: average([r[key] for r in measured]) for key in ('dB', 'dA', 'G')})
    result.update({status + '_n': sum(r['status'] == status for r in records)
                   for status in ('GENERATION_FAILED', 'REANALYSIS_FAILED', 'INELIGIBLE')})
    return result


def analysis(records, cg_ids, dp_ids, *, resamples=10000):
    """Full planned ledger required; paired uncertainty retains all repeats per base."""
    expected = {(c, rep, tid) for c, ids in [('CG-v1', cg_ids), ('DP-v1', dp_ids)]
                for rep in range(1, 6) for tid in ids}
    keys = [(r['condition'], r['repetition_id'], r['task_id']) for r in records]
    if len(keys) != len(expected) or set(keys) != expected or not set(dp_ids) <= set(cg_ids):
        raise RuntimeError('E03 planned task/condition/repetition ledger mismatch')
    for condition, ids in [('CG-v1', cg_ids), ('DP-v1', dp_ids)]:
        for tid in ids:
            same = [r for r in records if r['condition'] == condition and r['task_id'] == tid]
            if len({r['base_interval_id'] for r in same}) != 1 or not same[0]['base_interval_id']:
                raise RuntimeError('E03 base cluster identity mismatch')
    per_rep = []
    for population, condition, ids in [('E03-A', 'CG-v1', cg_ids),
            ('E03-B', 'CG-v1', dp_ids), ('E03-B', 'DP-v1', dp_ids)]:
        for rep in range(1, 6):
            subset = [r for r in records if r['condition'] == condition and r['repetition_id'] == rep and r['task_id'] in ids]
            per_rep.append(dict(population=population, condition=condition, repetition_id=rep, **summarize(subset)))
    repeat_summary = []
    for population, condition in [('E03-A', 'CG-v1'), ('E03-B', 'CG-v1'), ('E03-B', 'DP-v1')]:
        rows = [r for r in per_rep if r['population'] == population and r['condition'] == condition]
        for metric in ('conditional_TI', 'conditional_DA', 'ATI', 'ADA_all', 'G', 'dB', 'dA'):
            values = [r[metric] for r in rows]
            repeat_summary.append(dict(population=population, condition=condition, metric=metric,
                repetitions_planned=5, repetitions_defined=sum(v is not None for v in values),
                mean=average(values), SD_sample_ddof1=sd(values)))
    by_key = {(r['condition'], r['repetition_id'], r['task_id']): r for r in records}
    paired, paired_reps = [], []
    for rep in range(1, 6):
        all_pairs = [(by_key['CG-v1', rep, tid], by_key['DP-v1', rep, tid]) for tid in dp_ids]
        paired_reps.append(dict(repetition_id=rep, planned_pairs_n=len(dp_ids),
            paired_measurable_n=sum(a['measurable'] and b['measurable'] for a, b in all_pairs)))
    confidence = []
    for metric in ('TI', 'DA', 'G'):
        for population in ('paired_measurable', 'all_attempts'):
            if population == 'all_attempts' and metric == 'G':
                continue  # No invented distance gains for unavailable rewrites.
            deltas, bases, rep_means = [], [], []
            for rep in range(1, 6):
                rep_deltas = []
                for tid in dp_ids:
                    a, b = by_key['CG-v1', rep, tid], by_key['DP-v1', rep, tid]
                    if a['base_interval_id'] != b['base_interval_id']:
                        raise RuntimeError('E03 paired cluster mismatch')
                    if population == 'paired_measurable' and not (a['measurable'] and b['measurable']):
                        continue
                    value = ((a[metric] if a['measurable'] else 0.0) -
                             (b[metric] if b['measurable'] else 0.0))
                    deltas.append(value); bases.append(a['base_interval_id']); rep_deltas.append(value)
                rep_means.append(average(rep_deltas))
            estimate = bootstrap(deltas, bases, 'E03.matched12.CG-minus-DP.clustered/1.0', resamples=resamples)
            paired.append(dict(metric=metric, population=population, direction='CG minus DP',
                planned_pairs_n=5*len(dp_ids), available_pairs_n=len(deltas),
                mean_over_observations=average(deltas), mean_over_defined_repetition_means=average(rep_means),
                SD_of_repetition_means_ddof1=sd(rep_means), **estimate))
    for metric in ('TI', 'DA', 'G'):
        for population in ('measurable_only', 'all_attempts'):
            if metric == 'G' and population == 'all_attempts':
                continue
            rows = [r for r in records if r['condition'] == 'CG-v1' and
                    (population == 'all_attempts' or r['measurable'])]
            values = [r[metric] if r['measurable'] else 0.0 for r in rows]
            confidence.append(dict(population='E03-A.'+population, metric=metric,
                **bootstrap(values, [r['base_interval_id'] for r in rows],
                            'E03.CG48.clustered-repeated-observation-mean/1.0', resamples=resamples)))
    stability, histogram = [], []
    for condition, ids in [('CG-v1', cg_ids), ('DP-v1', dp_ids)]:
        counts = Counter()
        for tid in ids:
            rows = [by_key[condition, rep, tid] for rep in range(1, 6)]
            success = sum(r['TI'] == 1 for r in rows)
            counts[success] += 1
            stability.append(dict(condition=condition, task_id=tid, base_interval_id=rows[0]['base_interval_id'],
                TI_successes=success, repetitions_planned=5, TI_success_frequency=success/5,
                DA_mean_measurable=average([r['DA'] for r in rows]), DA_SD_measurable_ddof1=sd([r['DA'] for r in rows]),
                gain_distribution_measurable=distribution([r['G'] for r in rows]), **summarize(rows)))
        histogram.extend(dict(condition=condition, TI_successes_out_of_5=i, task_count=counts[i]) for i in range(6))
    return dict(per_repetition=per_rep, across_repetitions=repeat_summary, paired_comparisons=paired,
                paired_repetition_coverage=paired_reps, confidence=confidence, stability=stability, TI_histogram=histogram)


def table(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fields); writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                         for k, v in r.items()} for r in rows)
    with Path(path).with_suffix('.md').open('x') as handle:
        handle.write('| ' + ' | '.join(fields) + ' |\n|' + '|'.join('---' for _ in fields) + '|\n')
        for row in rows:
            handle.write('| ' + ' | '.join(str(row.get(k, '')).replace('|', '/') for k in fields) + ' |\n')


def prepare_tables(output, selections):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    fields = ('measurable_n', 'conditional_TI', 'conditional_DA', 'ATI', 'ADA_all',
              'dB', 'dA', 'G', 'GENERATION_FAILED_n', 'REANALYSIS_FAILED_n', 'INELIGIBLE_n')
    for label, conditions in [('T03_A', [('CG-v1',48)]), ('T03_B', [('CG-v1',12),('DP-v1',12)])]:
        table(output/(label+'.csv'), [dict(condition=c, repetition_id=rep, attempted_n=n,
              **{k:'NOT_RUN' for k in fields}) for c,n in conditions for rep in range(1,6)])
    table(output/'T03_C.csv', [dict(condition=c, task_id=tid, repetitions_planned=5,
            TI_successes='NOT_RUN', TI_success_frequency='NOT_RUN', DA_mean='NOT_RUN', DA_SD='NOT_RUN',
            gain_distribution='NOT_RUN', failures='NOT_RUN', identical_output_pairs='NOT_RUN')
            for c,ids in selections.items() for tid in ids])
    table(output/'T03_REPEAT_SUMMARY.csv', [dict(population=p, condition=c, metric=m, mean='NOT_RUN',SD='NOT_RUN')
          for p,c in [('E03-A','CG-v1'),('E03-B','CG-v1'),('E03-B','DP-v1')]
          for m in ('conditional_TI','conditional_DA','ATI','ADA_all','G')])
    table(output/'T03_UNCERTAINTY.csv', [dict(population=p, metric=m, estimate='NOT_RUN',ci95='NOT_RUN')
          for p in ('E03-A.CG48','E03-B.paired12') for m in ('TI','DA','G')])
    table(output/'T03_TI_HISTOGRAM.csv', [dict(condition=c,TI_successes_out_of_5=i,task_count='NOT_RUN')
          for c in selections for i in range(6)])
    table(output/'T03_B_PAIRED.csv', [dict(metric=m,population=p,CG_minus_DP='NOT_RUN',SD='NOT_RUN',ci95='NOT_RUN')
          for m in ('TI','DA','G') for p in ('paired_measurable','all_attempts')
          if not (m=='G' and p=='all_attempts')])


def evaluate(config):
    """Offline author command after generation validation and Qwen completion."""
    from hashlib import sha256
    reference_path = Path(config['reference']['path']); reference = read_json(reference_path)
    validate_reference(reference)
    records, bindings, texts = [], [], []
    for condition, executions in config['executions'].items():
        runtime = Path(config['tasksets'][condition]); taskset = read_json(runtime)
        validate_runtime(taskset, reference, reference_path, ArtifactResolver())
        if structure_sha(taskset['tasks']) != config['selection']['conditions'][condition]['projection_structure_sha256']:
            raise RuntimeError('E03 selected projection structure changed')
        for execution in executions:
            rep = execution['repetition_id']; rewrite = Path(execution['generation']); candidate = Path(execution['reanalysis'])
            cm = read_json(candidate/'feature_set_manifest.json')
            resolved = validate_source(cm, runtime, reference_path, reference, condition,
                                      config['gemma_server']['model_alias'], ArtifactResolver(), historical=False)
            if resolved != rewrite:
                raise RuntimeError('E03 reanalysis bound to wrong condition/repetition')
            validate_curves(taskset['tasks'], candidate, rewrite, reference_path, reference, ArtifactResolver())
            for task in taskset['tasks']:
                tid = task['task_id']; source = rewrite/'tasks'/tid; measured = candidate/'tasks'/tid
                phase = source/'phase_status.json'; status = measured/'measurement_status.json'
                if not phase.is_file() or read_json(phase).get('rewrite_completed') is not True:
                    canonical = failure_record(task, 'rewrite:generation_failed', condition, config['gemma_server']['model_alias'])
                    state = 'GENERATION_FAILED'
                elif not status.is_file() or read_json(status).get('status') != 'measured':
                    canonical = failure_record(task, 'reanalysis:measurement_failed', condition, config['gemma_server']['model_alias'])
                    state = 'REANALYSIS_FAILED'
                else:
                    ms = read_json(status)
                    hashes = {name:sha256_file(source/name) for name in ('rewritten_scenes.json','transfer_plan.json')}
                    expected = 'sha256:'+sha256(json.dumps(hashes, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()).hexdigest()
                    if ms.get('source_rewrite_artifact_sha256') != expected or ms.get('contract_equality_verified') is not True or ms['measurement'] != config['measurement'] or ms['scene_ids'] != task['source_scene_ids']:
                        raise RuntimeError('E03 per-task measurement/text/protocol binding mismatch')
                    features = read_json(measured/'rewritten_scene_features.json'); measurements = read_json(measured/'measurement_records.json')
                    keyed_vectors(features, task['source_scene_ids'], tid)
                    if [m['scene_id'] for m in measurements] != task['source_scene_ids']:
                        raise RuntimeError('E03 measurement record identity/order mismatch')
                    from .reviewer import FEATURES
                    for row, m in zip(features, measurements):
                        if m['status'] != 'measured' or exact_measurement(config['measurement'], m['provenance']):
                            raise RuntimeError('E03 measurement record protocol mismatch')
                        if any(row[key] != m['features'][key.removeprefix('llm_').removesuffix('_score')] for key in FEATURES.values()):
                            raise RuntimeError('E03 measurement record/feature row disagreement')
                    canonical = evaluate_task(task, measured, reference['measurement'], condition, config['gemma_server']['model_alias'])
                    state = 'SUCCESS' if canonical['metric_eligible'] else 'INELIGIBLE'
                record = compact(canonical, condition=condition, repetition=rep, status=state); records.append(record)
                binding = dict(condition=condition, task_id=tid, base_interval_id=task['base_interval_id'],
                    repetition_id=rep, status=state, scene_ids=task['source_scene_ids'],
                    source_feature_path=task['source_feature_path'], source_feature_sha256=sha256_file(task['source_feature_path']),
                    reference_feature_path=task['reference_feature_path'], reference_feature_sha256=sha256_file(task['reference_feature_path']),
                    rewrite_task_path=str(source), measurement_task_path=str(measured),
                    artifacts={str(p):sha256_file(p) for p in [source/'transfer_plan.json',source/'rewritten_scenes.json',
                        measured/'measurement_records.json',measured/'rewritten_scene_features.json',status] if p.is_file()})
                bindings.append(binding)
                if phase.is_file() and read_json(phase).get('rewrite_completed') is True:
                    scenes = read_json(source/'rewritten_scenes.json')['rewritten_scenes']
                    content = '\n'.join(s['content'] for s in scenes)
                    exact = json.dumps([(s['scene_id'],s['content']) for s in scenes], ensure_ascii=False, separators=(',',':'))
                    texts.append(dict(condition=condition, task_id=tid, repetition_id=rep,
                        text_hash='sha256:'+sha256(exact.encode()).hexdigest(), content=content))
    ids = {c: config['selection']['conditions'][c]['task_ids'] for c in config['executions']}
    result = analysis(records, ids['CG-v1'], ids['DP-v1'])
    text_rows = []
    for condition, selected in ids.items():
        for tid in selected:
            outputs = [r for r in texts if r['condition'] == condition and r['task_id'] == tid]
            pairs = list(combinations(outputs, 2)); similarities=[]
            for a,b in pairs:
                x,y=set(a['content'].casefold().split()),set(b['content'].casefold().split())
                similarities.append(len(x&y)/len(x|y) if x|y else 1.0)
            text_rows.append(dict(condition=condition, task_id=tid, available_outputs=len(outputs),
                compared_pairs=len(pairs), identical_pairs=sum(a['text_hash']==b['text_hash'] for a,b in pairs),
                unique_output_hashes=len({r['text_hash'] for r in outputs}),
                mean_pairwise_token_set_Jaccard=average(similarities),
                character_length_distribution=distribution([len(r['content']) for r in outputs]),
                output_hashes=[dict(repetition_id=r['repetition_id'],sha256=r['text_hash']) for r in outputs]))
    output=Path(config['evaluation_output']); output.mkdir(parents=True, exist_ok=False)
    write_json(output/'TASK_RECORDS.json', records); write_json(output/'ARTIFACT_BINDINGS.json',bindings)
    for name, rows in result.items():
        write_json(output/(name.upper()+'.json'),rows)
        table(output/(name.upper()+'.csv'),rows)
    table(output/'T03_A.csv',[r for r in result['per_repetition'] if r['population']=='E03-A'])
    table(output/'T03_B.csv',[r for r in result['per_repetition'] if r['population']=='E03-B'])
    table(output/'T03_C.csv',result['stability'])
    table(output/'T03_B_PAIRED.csv',result['paired_comparisons'])
    table(output/'TEXT_VARIABILITY.csv',text_rows)
    write_json(output/'EVALUATION_MANIFEST.json',dict(experiment_id=config['experiment_id'],
        status='EVALUATED', scientific_pass_claimed=False, planned_executions=len(records),
        selection=config['selection'], reference=config['reference'], measurement=config['measurement'],
        source_commits=config['source_commits'], statuses=dict(Counter(r['status'] for r in records)),
        estimands={'SD':'sample SD (ddof=1) across five defined repetition means; report defined count',
          'conditional_TI_DA':'canonical task-macro TI/DA among measurable tasks per repetition',
          'ATI_ADA_all':'failures zero; denominator all 48 CG or 12 matched tasks per repetition',
          'G':'signed canonical source-target MAE minus rewrite-target MAE; measurable only',
          'paired':'CG minus DP on same 12 tasks/repetitions; paired measurable and all-attempt TI/DA separated',
          'CI':'10,000 PCG64(default_rng(42)) base-interval cluster draws, 95% percentile linear; retain all available repetitions per drawn base. Observation-weighted pooled mean, distinct from unweighted repetition means.',
          'limits':'48 CG/12 paired represented bases at most; unavailable paired measurements reduce represented clusters. Repetition SD is descriptive, not an uncertainty interval. Film overlap may limit independence; no p-values.'}))
    return output
