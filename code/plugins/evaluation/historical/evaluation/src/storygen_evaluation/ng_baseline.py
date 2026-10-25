"""Additive NG-v0 adapter. Canonical TI/DA and clustered statistics stay unchanged."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from pathlib import Path
import csv
import json
import shutil

from .io import read_json, sha256_file
from .metrics import evaluate_task, failure_record, exact_measurement
from .provenance import structure_sha, validate_curves, ArtifactResolver
from .reviewer.statistics import average, all_attempt, bootstrap, distance, keyed_vectors

METRICS = ('TI', 'DA', 'dB', 'dA', 'G', 'absolute_G', 'ATI', 'ADA_all')


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def write_table(path, rows):
    with Path(path).open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    headers = list(rows[0])
    Path(path).with_suffix('.md').write_text('| ' + ' | '.join(headers) + ' |\n| ' + ' | '.join(['---'] * len(headers)) + ' |\n' +
        ''.join('| ' + ' | '.join(str(row[h]) for h in headers) + ' |\n' for row in rows))


def prepare_tables(output):
    """Templates only: no historical or new scientific results are computed."""
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    rows = [dict(condition=condition, population='matched_NG_DP_CG_measurable',
                 attempted_n=240, measurable_n='NOT_RUN', matched_n='NOT_RUN',
                 **{metric: 'NOT_RUN' for metric in METRICS}, ci95='NOT_RUN')
            for condition in ('NG-v0', 'DP-v1', 'CG-v1')]
    write_table(output / 'T02.csv', rows)
    write_table(output / 'A03_NG_v0.csv', [rows[0]])
    write_json(output / 'STATUS.json', dict(status='HUMAN_RUN_PENDING', scientific_status='NOT_RUN'))


def compact(record):
    eligible = record['metric_eligible']
    db, da = record['before_target_mae'], record['after_target_mae']
    result = dict(**record, measurable=eligible, TI=int(record['target_improved']) if eligible else None,
                  DA=record['directional_accuracy'], dB=db, dA=da)
    result.update(distance(result))
    return result


def summarize(records, matched_ids):
    """Original tasks are the units; each CI resamples base intervals."""
    rows, confidence = [], []
    features = ['ALL', *sorted({r['feature'] for r in records})]
    for feature in features:
        selected = [r for r in records if feature == 'ALL' or r['feature'] == feature]
        for population in ('all_attempts', 'conditional_measurable', 'matched_NG_DP_CG_measurable'):
            subset = (selected if population == 'all_attempts' else
                      [r for r in selected if r['measurable'] and
                       (population != 'matched_NG_DP_CG_measurable' or r['task_id'] in matched_ids)])
            measured = [r for r in subset if r['measurable']]
            totals = all_attempt(subset)
            row = dict(condition=records[0]['method'], feature=feature, population=population,
                attempted_n=len(selected), measurable_n=sum(r['measurable'] for r in selected),
                population_n=len(subset), metric_n=len(measured), cluster_n=len({r['base_interval_id'] for r in subset}),
                failed_n=totals['failed_n'], **{m: average([r[m] for r in measured]) for m in METRICS[:6]},
                ATI=totals['ATI'] if population=='all_attempts' else None,
                ADA_all=totals['ADA_all'] if population=='all_attempts' else None)
            rows.append(row)
            for metric in METRICS:
                if metric in ('ATI','ADA_all') and population!='all_attempts':
                    continue
                ci_records = subset if metric in ('ATI', 'ADA_all') else measured
                key = {'ATI':'TI', 'ADA_all':'DA'}.get(metric, metric)
                values = [float(r[key]) if r['measurable'] else 0.0 for r in ci_records]
                estimate = bootstrap(values, [r['base_interval_id'] for r in ci_records],
                                     'E02-MIN.NG-v0.clustered-task-mean/1.0')
                confidence.append(dict(condition=row['condition'], feature=feature, population=population,
                                       metric=metric, **estimate))
    return rows, confidence


def evaluate_ng(config):
    """Author-run Stage D only, after Stage A/C completion and frozen preflight."""
    output = Path(config['evaluation_output']); output.mkdir(parents=True, exist_ok=False)
    tasks = read_json(config['bound_taskset'])['tasks']
    if structure_sha(tasks) != config['structure_sha256']:
        raise RuntimeError('Frozen task identity/order mismatch')
    mapping = read_json(config['mapping'])['units']
    bases = {tid: unit['base_interval_id'] for unit in mapping for tid in unit['task_ids']}
    reference = read_json(config['reference']['path'])
    rewrite = Path(config['rewrite_output']); candidate = Path(config['measurement_output'])
    rw = read_json(rewrite / 'rewrite_run_manifest.json')
    cm = read_json(candidate / 'feature_set_manifest.json')
    if rw['prompt_contract_id'] != 'NG-v0' or rw['generation_unit'] != 'base_interval_id':
        raise RuntimeError('NG generation identity mismatch')
    if rw['mapping_sha256'] != sha256_file(config['mapping']) or rw['frozen_evaluation_taskset'] != config['frozen_taskset']:
        raise RuntimeError('NG mapping/frozen task lineage mismatch')
    if rw['feature_set_manifest']['sha256'] != config['reference']['sha256']:
        raise RuntimeError('NG original Qwen reference mismatch')
    if cm['source']['rewrite_run']['manifest_sha256'] != sha256_file(rewrite / 'rewrite_run_manifest.json'):
        raise RuntimeError('NG measurement rewrite lineage mismatch')
    if cm['source']['reference_feature_set']['manifest_sha256'] != config['reference']['sha256']:
        raise RuntimeError('NG measurement reference lineage mismatch')
    if exact_measurement(reference['measurement'], cm['measurement']):
        raise RuntimeError('NG measurement identity mismatch')
    if cm['measurement'] != config['measurement'] or cm['taskset']['sha256'] != sha256_file(config['base_runtime']):
        raise RuntimeError('NG measurement protocol/base projection mismatch')
    views = output / 'task_views'; views.mkdir()
    source_views = output / 'source_views'; source_views.mkdir()
    records = []
    for task in tasks:
        base = bases[task['task_id']]; source = rewrite / 'tasks' / base; measured = candidate / 'tasks' / base
        view = views / 'tasks' / task['task_id']; view.mkdir(parents=True)
        source_view = source_views / 'tasks' / task['task_id']; source_view.mkdir(parents=True)
        shutil.copy2(Path(config['hidden_plans']) / task['task_id'] / 'transfer_plan.json', view / 'transfer_plan.json')
        (source_view / 'transfer_plan.json').symlink_to((Path(config['hidden_plans']) / task['task_id'] / 'transfer_plan.json').resolve())
        if (source / 'rewritten_scenes.json').is_file():
            (source_view / 'rewritten_scenes.json').symlink_to((source / 'rewritten_scenes.json').resolve())
        if not (source / 'phase_status.json').is_file() or read_json(source / 'phase_status.json').get('rewrite_completed') is not True:
            record = failure_record(task, 'rewrite:base_interval_failed', 'NG-v0', config['gemma_server']['model_alias'])
        elif not (measured / 'measurement_status.json').is_file():
            reason = 'reanalysis:base_interval_failed'
            fail = measured / 'feature_extraction_failure.json'
            if fail.is_file():
                reason += ':' + str(read_json(fail).get('root_cause_type'))
            record = failure_record(task, reason, 'NG-v0', config['gemma_server']['model_alias'])
        else:
            status = read_json(measured / 'measurement_status.json')
            from hashlib import sha256
            hashes = {n: sha256_file(source/n) for n in ('rewritten_scenes.json','transfer_plan.json')}
            expected = 'sha256:' + sha256(json.dumps(hashes, sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            if status.get('source_rewrite_artifact_sha256') != expected or status.get('contract_equality_verified') is not True:
                raise RuntimeError('NG per-base measurement text lineage mismatch')
            if status['measurement'] != config['measurement']:
                raise RuntimeError('NG per-base measurement protocol mismatch')
            if status.get('scene_ids') != task['source_scene_ids']:
                raise RuntimeError('NG per-base measurement scene coverage mismatch')
            rows = read_json(measured/'rewritten_scene_features.json')
            keyed_vectors(rows, task['source_scene_ids'], base)
            measurement_records = read_json(measured/'measurement_records.json')
            if [r.get('scene_id') for r in measurement_records] != task['source_scene_ids']:
                raise RuntimeError('NG measurement record coverage mismatch')
            for row, record in zip(rows,measurement_records):
                if record.get('status') != 'measured' or exact_measurement(config['measurement'],record.get('provenance') or {}):
                    raise RuntimeError('NG measurement record provenance mismatch')
                from .reviewer import FEATURES
                if any(row[key] != record['features'].get(key.removeprefix('llm_').removesuffix('_score'))
                       for key in FEATURES.values()):
                    raise RuntimeError('NG measurement row differs from canonical scorer record')
            if sha256_file(source/'rewritten_scenes.json') != sha256_file(measured/'rewritten_scenes.json'):
                raise RuntimeError('NG measured text differs from generation')
            for name in ('rewritten_scenes.json', 'measurement_status.json', 'rewritten_scene_features.json'):
                (view / name).symlink_to((measured / name).resolve())
            record = evaluate_task(task, view, reference['measurement'], 'NG-v0', config['gemma_server']['model_alias'])
        records.append(compact(record))
    # Validate canonical B/T curves without rewriting any historical artifact.
    validate_curves(tasks, views, source_views, Path(config['reference']['path']),
                    reference, ArtifactResolver())
    conditions = {'NG-v0': records}
    for control in config['controls']:
        old = [json.loads(line) for line in Path(control['records']['path']).read_text().splitlines() if line.strip()]
        if {r['task_id'] for r in old} != {t['task_id'] for t in tasks} or len(old) != 240:
            raise RuntimeError('Historical task population mismatch')
        if any(r['method'] != control['condition'] or r['rewrite_model'] != config['gemma_server']['model_alias'] for r in old):
            raise RuntimeError('Historical method/model mismatch')
        conditions[control['condition']] = [compact(r) for r in old]
    matched = set.intersection(*[{r['task_id'] for r in rows if r['measurable']} for rows in conditions.values()])
    rows, confidence = [], []
    for condition in conditions:
        summary, ci = summarize(conditions[condition], matched); rows.extend(summary); confidence.extend(ci)
    paired = []
    for left, right in combinations(conditions, 2):
        a, b = ({r['task_id']:r for r in conditions[c]} for c in (left,right))
        ids = [t['task_id'] for t in tasks if t['task_id'] in matched]
        for metric in ('TI', 'DA', 'dB', 'dA', 'G', 'absolute_G'):
            paired.append(dict(left=left, right=right, metric=metric, population='matched_NG_DP_CG_measurable',
                **bootstrap([a[i][metric]-b[i][metric] for i in ids], [a[i]['base_interval_id'] for i in ids],
                            'E02-MIN.NG-v0.paired-cluster-difference/1.0')))
    write_table(output / 'T02.csv', rows)
    write_table(output / 'A03_NG_v0.csv', [r for r in rows if r['condition']=='NG-v0'])
    write_json(output / 'CONFIDENCE_INTERVALS.json', confidence)
    write_json(output / 'PAIRED_COMPARISONS.json', paired)
    write_json(output / 'FAILURES.json', {c:dict(Counter(r['ineligible_reason'] for r in rs if not r['measurable'])) for c,rs in conditions.items()})
    write_json(output / 'MATCHED_TASK_IDS.json', sorted(matched))
    write_json(output / 'NG_TASK_RECORDS.json', records)
    write_json(output / 'EVALUATION_MANIFEST.json', dict(status='EVALUATED', scientific_pass_claimed=False,
        frozen_taskset=config['frozen_taskset'], mapping_sha256=sha256_file(config['mapping']),
        reference=config['reference'], measurement_identity=config['measurement'],
        rewrite_manifest_sha256=sha256_file(rewrite/'rewrite_run_manifest.json'),
        measurement_manifest_sha256=sha256_file(candidate/'feature_set_manifest.json'), controls=config['controls'],
        matched_n=len(matched), attempted_tasks_per_condition=240, generation_units=48,
        definitions={'TI':'strict dA < dB', 'DA':'exact sign(A-B) == sign(T-B), including zero',
                     'G':'dB-dA (signed improvement in absolute MAE units)', 'absolute_G':'abs(dB-dA)',
                     'ATI':'sum measurable TI / attempted population (240 overall; 48 within feature), failures zero',
                     'ADA_all':'sum measurable macro DA / attempted population (240 overall; 48 within feature), failures zero',
                     'A03_NG_v0':'Empirical NG supplement only; historical analytic A03 remains unchanged.'}))
    return output
