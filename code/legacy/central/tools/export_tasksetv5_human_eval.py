#!/usr/bin/env python3
"""Focused, local-only historical TasksetV5 export. Python standard library only.

No inference, network, experiment replay, or historical source mutation.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
from decimal import Decimal
from pathlib import Path
import random
import shutil
import sys
import tempfile
import zipfile

NAME = 'tasksetv5_human_eval_3films_25pairs_v1'
ZIP = 'TASKSETV5_HUMAN_EVAL_SOURCE.zip'
TASK_HASH = 'f0efdf862a5a1c999220a86a04676f8bb846b9b3191635e0b15a79a3fa341912'
OLD_HASH = 'df31bd4b75648ab172b74fcc2c89c9a2b20cd8a88c1bf922597738e494e19730'
FEATURES = {
    'llm_pacing_score': 'Pacing',
    'llm_dialogue_density_score': 'Dialogue Density',
    'llm_action_density_score': 'Action Density',
    'llm_character_interaction_score': 'Character Interaction',
    'llm_emotion_intensity_score': 'Emotion Intensity',
}
GATES = [
    'Historical TasksetV5 identity verified', 'Three distinct film IDs', 'Exactly 3 tasks',
    'Interval lengths exactly 5, 8, 12', 'Exactly 25 original scenes',
    'Exactly 25 Gemma rewritten scenes', 'Exactly 25 scene pairs', 'No missing screenplay text',
    'Original/rewrite alignment valid', 'Gemma CG-v1 identity verified',
    'Original Qwen measurements verified', 'Rewrite Qwen reanalysis verified',
    'All five features present for every scene', 'All numerical values valid',
    'Target curve provenance verified', 'Selected historical evaluation records verified',
    'No fabricated records', 'Human review files contain no Qwen scores',
    'Exported ZIP content matches staging manifest', 'Source files remain unchanged',
]
IDENTITY_KEYS = ['measurement_protocol_id', 'measurement_protocol_version', 'protocol_hash',
                 'instrument_hash', 'prompt_hash', 'schema_hash', 'system_instruction_hash',
                 'request_contract_hash', 'decoding_hash']
SEMANTIC_KEYS = ['task_id', 'base_interval_id', 'source_film_id', 'reference_film_id',
                 'source_scene_ids', 'reference_scene_ids', 'selected_features', 'interval_type']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rewrite_artifact_hash(task_dir):
    """Historical _rewrite_hash: canonical hash of two file-digest strings."""
    hashes = {name: 'sha256:' + sha(Path(task_dir) / name)
              for name in ('rewritten_scenes.json', 'transfer_plan.json')}
    return 'sha256:' + hashlib.sha256(json.dumps(hashes, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def loads(text):
    return json.loads(text, parse_float=Decimal,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def read(path):
    return loads(Path(path).read_text(encoding='utf-8'))


def encode(value, level=0):
    """Emit source decimal numbers without float conversion, rounding, or stringification."""
    if isinstance(value, Decimal):
        require(value.is_finite(), 'Non-finite decimal')
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join('\n' + '  ' * (level + 1) + json.dumps(k, ensure_ascii=False)
                              + ': ' + encode(v, level + 1) for k, v in value.items()) + ('\n' + '  ' * level if value else '') + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join('\n' + '  ' * (level + 1) + encode(v, level + 1) for v in value) + ('\n' + '  ' * level if value else '') + ']'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode(value) + '\n', encoding='utf-8')


def index(rows, key='scene_id'):
    require(isinstance(rows, list), 'Expected list of records')
    result = {r[key]: r for r in rows}
    require(len(result) == len(rows), f'Duplicate {key}')
    return result


def source_index(raw):
    rows = raw['scenes'] if isinstance(raw, dict) else raw
    mapped = []
    for row in rows:
        sid = row.get('scene_id', row.get('_id', row.get('id')))
        if isinstance(sid, int) and not isinstance(sid, bool):
            sid = f'scene_{sid + 1:03d}'
        require(isinstance(sid, str), 'Missing explicit historical source ID')
        mapped.append(dict(scene_id=sid, raw=row))
    return index(mapped)


def text(row):
    for key in ['text', 'content', 'body']:
        if key in row and isinstance(row[key], str) and row[key]:
            return row[key]
    raise ValueError('Missing screenplay text')


def numeric(value):
    return not isinstance(value, bool) and isinstance(value, (int, Decimal)) and Decimal(value).is_finite() and 0 <= value <= 1


def csv_write(path, rows):
    require(bool(rows), 'Empty CSV')
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: '' if v is None else encode(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def rating_fields():
    return [f'{side} {label}' for side in ['Original', 'Rewrite'] for label in FEATURES.values()]


class Sources:
    def __init__(self):
        self.hashes = {}
        self.cache = {}

    def load(self, path):
        p = Path(path).resolve(strict=True)
        if p not in self.cache:
            self.hashes[str(p)] = sha(p)
            self.cache[p] = read(p)
        return self.cache[p]

    def bound(self, ref):
        p = Path(ref['path']).resolve(strict=True)
        if p.suffix == '.jsonl':
            self.track_bytes(p)
        else:
            self.load(p)
        require(sha(p) == ref['sha256'].removeprefix('sha256:'), f'Bound source hash mismatch: {p}')
        return p

    def track_bytes(self, path):
        p = Path(path).resolve(strict=True)
        digest = sha(p)
        require(str(p) not in self.hashes or self.hashes[str(p)] == digest,
                f'Source changed during extraction: {p}')
        self.hashes[str(p)] = digest
        return p

    def unchanged(self):
        return all(Path(p).is_file() and sha(p) == h for p, h in self.hashes.items())


def select(candidates):
    groups = [[c for c in candidates if c['length'] == n] for n in (5, 8, 12)]
    triples = [tuple(x['task_id'] for x in triple) for triple in itertools.product(*groups)
               if len({x['film_id'] for x in triple}) == 3]
    require(triples, 'No eligible three-film combination for lengths 5/8/12')
    by_id = index(candidates, 'task_id')
    maximum = max(len({by_id[t]['target_feature'] for t in triple}) for triple in triples)
    preferred = [triple for triple in triples if len({by_id[t]['target_feature'] for t in triple}) == maximum]
    chosen_index = random.Random(1701).randrange(len(preferred))
    return preferred[chosen_index], dict(distinct_film_combinations=len(triples),
        maximum_distinct_target_features=maximum, preferred_combinations=len(preferred), selected_index=chosen_index)


def build(workspace, output):
    require(not output.exists(), f'Create-only export already exists: {output}')
    src = Sources()
    code_root = workspace / 'storygen-experiment'
    binding_path = code_root / 'experiments/reviewer_round1/e06_statistical_robustness/historical_binding.json'
    binding = src.load(binding_path)
    run = next(r for r in binding['runs'] if r['model'] == 'gemma3-12b-it-gguf' and r['condition'] == 'CG-v1')
    paths = {k: src.bound(ref) for k, ref in run.items() if isinstance(ref, dict) and 'path' in ref}
    paths['taskset'] = src.bound(binding['taskset'])
    paths['feature_set'] = src.bound(binding['reference_feature_set'])
    overrides = src.load(src.bound(binding['artifact_overrides']))
    ts, fs = src.load(paths['taskset']), src.load(paths['feature_set'])
    require(sha(paths['taskset']) == TASK_HASH and len(ts['tasks']) == 240, 'Incorrect historical TasksetV5')
    rw, ra, ev = [src.load(paths[k]) for k in ['rewrite_manifest', 'reanalysis_manifest', 'evaluation_manifest']]
    require(rw['prompt_contract_id'] == ev['method'] == 'CG-v1', 'Wrong rewriting condition')
    require(rw['model']['served_alias'] == ev['rewrite_model'] == 'gemma3-12b-it-gguf', 'Wrong rewriting model')
    require(rw['model']['quantization'] == 'Q4_K_M', 'Wrong Gemma quantization')
    require(rw['model']['file_sha256'] == 'sha256:fc57f67efa46d711c346e587cbef7d049e95f3df8db2eb2271153343ef0acc7b', 'Wrong Gemma checkpoint')
    measurement = fs['measurement']
    require(measurement == ra['measurement'] == rw['feature_set_manifest']['measurement'], 'Incompatible measurement contracts')
    require(measurement['model']['alias'] == 'qwen2.5-7b-q4' and measurement['model']['quantization'] == 'Q4_K_M', 'Wrong Qwen model')
    require(measurement['model']['model_sha256'] == 'sha256:65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423', 'Wrong Qwen checkpoint')
    require(ev['taskset']['sha256'] == 'sha256:' + TASK_HASH, 'Evaluation taskset mismatch')
    require(ev['feature_set_manifest']['sha256'] == 'sha256:' + sha(paths['feature_set']), 'Evaluation FeatureSet mismatch')
    require(ev['reanalysis_run']['manifest_sha256'] == 'sha256:' + sha(paths['reanalysis_manifest']), 'Evaluation/reanalysis lineage mismatch')
    require(ra['source_rewrite_run']['manifest_sha256'] == 'sha256:' + sha(paths['rewrite_manifest']), 'Reanalysis/rewrite lineage mismatch')
    require(ra['source_feature_set_manifest']['sha256'] == 'sha256:' + sha(paths['feature_set']), 'Reanalysis FeatureSet mismatch')
    for key in IDENTITY_KEYS:
        require(ev['measurement_identity'][key] == measurement[key], f'Evaluation instrument mismatch: {key}')
    require(ev['measurement_identity']['model_sha256'] == measurement['model']['model_sha256'], 'Evaluation Qwen mismatch')
    old_ref = rw['taskset']
    old_path = Path(overrides.get(old_ref['path'], old_ref['path']))
    old = src.load(old_path)
    require(sha(old_path) == OLD_HASH and rw['taskset']['sha256'] == ra['taskset']['sha256'] == 'sha256:' + OLD_HASH, 'Unverified generation taskset')
    old_tasks = index(old['tasks'], 'task_id')
    require(set(old_tasks) == {t['task_id'] for t in ts['tasks']}, 'Runtime task inventory drift')
    for t in ts['tasks']:
        require(all(t[k] == old_tasks[t['task_id']][k] for k in SEMANTIC_KEYS), f'Task semantic drift: {t["task_id"]}')
    records_path = paths['records']
    src.track_bytes(records_path)
    records = index([loads(line) for line in records_path.read_text().splitlines() if line.strip()], 'task_id')
    require(set(records) == set(old_tasks), 'Incomplete historical evaluation inventory')
    prompt_path = workspace / 'storygen-feature-extraction/measurement/prompts/legacy_feature_prompt_v1.txt'
    schema_path = workspace / 'storygen-feature-extraction/measurement/schemas/narrative_feature_schema_v1.json'
    io_path = workspace / 'storygen-feature-extraction/measurement/src/storygen_measurement_core/io.py'
    rewrite_io_path = workspace / 'storygen-feature-extraction/feature_extraction/src/storygen_feature/rewritten.py'
    for path, key in [(prompt_path, 'prompt_hash'), (schema_path, 'schema_hash')]:
        src.track_bytes(path)
        require('sha256:' + sha(path) == measurement[key], f'Historical rubric hash mismatch: {path}')
    src.track_bytes(io_path)
    src.track_bytes(rewrite_io_path)
    film_data = {}
    for film in sorted({t[f'{side}_film_id'] for t in ts['tasks'] for side in ['source', 'reference']}):
        root = paths['feature_set'].parent / 'films' / film
        feats_path, meta_path = root / 'scene_features_llm.json', root / 'measurement_manifest.json'
        feats, meta = src.load(feats_path), src.load(meta_path)
        require(meta['measurement'] == measurement and meta['film_id'] == film, f'Original film measurement mismatch: {film}')
        task = next(t for t in ts['tasks'] if t['source_film_id'] == film)
        script_path = Path(overrides.get(task['source_script_path'], task['source_script_path']))
        script = src.load(script_path)
        require(meta['script_sha256'] == 'sha256:' + sha(script_path), f'Original screenplay hash mismatch: {film}')
        film_data[film] = dict(features=index(feats), scenes=source_index(script), script_path=script_path,
                               features_path=feats_path, meta_path=meta_path, meta=meta)
    inventory, valid_data = [], {}
    for t in sorted(ts['tasks'], key=lambda t: t['task_id']):
        tid, ids = t['task_id'], t['source_scene_ids']
        entry = dict(task_id=tid, film_id=t['source_film_id'], length=len(ids), target_feature=t['selected_features'][0], reasons=[])
        try:
            require(len(ids) in (5, 8, 12), 'unsupported_interval_length')
            require(len(set(ids)) == len(ids), 'duplicate_task_scene_identifier')
            numbers = [int(s.removeprefix('scene_')) for s in ids]
            require(numbers == list(range(numbers[0], numbers[0] + len(ids))), 'nonconsecutive_interval')
            rec = records[tid]
            require(rec['metric_eligible'] is True and rec['ineligible_reason'] is None, f'historical_evaluation_ineligible:{rec["ineligible_reason"]}')
            require(rec['rewrite_model'] == 'gemma3-12b-it-gguf' and rec['method'] == 'CG-v1', 'record_identity_mismatch')
            require(rec['base_interval_id'] == t['base_interval_id'] and rec['feature'] == t['selected_features'][0], 'evaluation_task_mismatch')
            rroot = paths['rewrite_manifest'].parent / 'tasks' / tid
            aroot = paths['reanalysis_manifest'].parent / 'tasks' / tid
            rp, ap = rroot / 'rewritten_scenes.json', aroot / 'rewritten_scenes.json'
            rewrites, copied = src.load(rp), src.load(ap)
            require(sha(rp) == sha(ap) and rewrites == copied, 'rewrite_reanalysis_text_copy_mismatch')
            plan, plan_copy = src.load(rroot / 'transfer_plan.json'), src.load(aroot / 'transfer_plan.json')
            require(plan == plan_copy and sha(rroot / 'transfer_plan.json') == sha(aroot / 'transfer_plan.json'), 'transfer_plan_copy_mismatch')
            phase, status = src.load(rroot / 'phase_status.json'), src.load(aroot / 'measurement_status.json')
            req = src.load(rroot / 'rewrite_request.json')
            require(phase['task_id'] == tid and phase['rewrite_completed'] is True and phase['prompt_contract_id'] == 'CG-v1', 'invalid_rewrite_phase')
            require(phase['source_scene_ids'] == ids and phase['prompt_bundle_sha256'] == rw['prompt_provenance']['prompt_bundle_sha256'], 'phase_scene_or_prompt_mismatch')
            require(req['run_id'] == tid and req['model'] == 'gemma3-12b-it-gguf' and req['prompt_profile'] == 'CG-v1' and req['source_scene_ids'] == ids, 'rewrite_request_identity_mismatch')
            require(status['status'] == 'measured' and status['contract_equality_verified'] is True and status['measurement'] == status['source_feature_measurement'] == measurement, 'incompatible_task_measurement')
            require(status['source_rewrite_artifact_sha256'] == rewrite_artifact_hash(rroot) and status['scene_ids'] == ids, 'reanalysis_artifact_mismatch')
            require(plan['run_id'] == tid and plan['source_scene_ids'] == ids and plan['reference_scene_ids'] == t['reference_scene_ids'] and plan['selected_features'] == t['selected_features'], 'plan_task_mismatch')
            after = src.load(aroot / 'rewritten_scene_features.json')
            ri, ai = index(rewrites['rewritten_scenes']), index(after)
            require(set(ri) == set(ai) == set(ids), 'incomplete_or_extra_scene_mapping')
            source = film_data[t['source_film_id']]
            reference = film_data[t['reference_film_id']]
            require([r['scene_id'] for r in rewrites['rewritten_scenes']] == ids, 'rewrite_scene_order_mismatch')
            require([r['scene_id'] for r in after] == ids, 'measurement_scene_order_mismatch')
            require([r['scene_id'] for r in plan['per_scene_target_values']] == ids, 'plan_scene_order_mismatch')
            feature = t['selected_features'][0]
            B = [source['features'][sid][feature] for sid in ids]
            T = [reference['features'][sid][feature] for sid in t['reference_scene_ids']]
            require(len(T) == len(ids) and T == plan['reference_curve'][feature] == plan['resampled_target_curve'][feature], 'target_curve_mismatch')
            require(B == plan['source_current_curve'][feature], 'original_curve_mismatch')
            truncations = []
            for pos, sid in enumerate(ids):
                original, before, rewrite, after_row = source['scenes'][sid]['raw'], source['features'][sid], ri[sid], ai[sid]
                require(text(original).strip() and text(rewrite).strip(), 'empty_scene_text')
                require(before['film_id'] == after_row['film_id'] == t['source_film_id'], 'wrong_feature_film')
                require(before['measurement_status'] == 'measured', 'original_not_measured')
                require(before['measurement_protocol_hash'] == after_row['measurement_protocol_hash'] == measurement['protocol_hash'], 'scene_measurement_protocol_mismatch')
                for k in ['prompt_hash', 'schema_hash', 'system_instruction_hash', 'request_contract_hash', 'decoding_hash']:
                    require(after_row[k] == measurement[k], f'after_instrument_mismatch:{k}')
                require(all(numeric(before[k]) and numeric(after_row[k]) for k in FEATURES), 'missing_or_invalid_feature')
                target = plan['per_scene_target_values'][pos]
                require(target['current_values'][feature] == B[pos] and target['targets'][feature] == T[pos], 'per_scene_target_mismatch')
                request_path = rroot / 'per_scene' / sid / 'rewrite_request.json'
                request = src.load(request_path)
                require(request['model'] == 'gemma3-12b-it-gguf' and request['prompt_profile'] == 'CG-v1' and request['expected_scene_id'] == sid, 'per_scene_request_identity_mismatch')
                prompt = loads(request['user_instruction'])
                require(prompt['source_film_id'] == t['source_film_id'] and prompt['source_interval_scene_ids'] == ids and prompt['source_scene']['scene_id'] == sid, 'per_scene_source_mapping_mismatch')
                require(prompt['source_scene']['title'] == before['title'] and rewrite['title'] == after_row['title'], 'scene_title_mapping_mismatch')
                was_truncated = prompt['source_scene']['was_truncated']
                require(isinstance(was_truncated, bool), 'missing_truncation_provenance')
                if not was_truncated:
                    require(prompt['source_scene']['content'] == text(original).strip(), 'untruncated_request_text_mismatch')
                truncations.append(was_truncated)
            entry['eligible'] = True
            valid_data[tid] = dict(task=t, rroot=rroot, aroot=aroot, plan=plan, status=status, rewrites=ri,
                                   after=ai, record=rec, truncations=truncations)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            entry['eligible'] = False
            entry['reasons'].append(str(exc))
        inventory.append(entry)
    candidates = [e for e in inventory if e['eligible']]
    require(candidates, 'No eligible historical candidates: ' + str({reason: sum(reason in e['reasons'] for e in inventory) for e in inventory for reason in e['reasons']}))
    chosen, selection_stats = select(candidates)
    print('CANDIDATES', {n: sum(c['length'] == n for c in candidates) for n in (5, 8, 12)}, flush=True)
    print('SELECTED', chosen, flush=True)
    # No output is created before the complete inventory and deterministic selection pass.
    output.mkdir(parents=True)
    for name in ['01_dataset', '02_qwen_reference', '03_original_sources', '04_gemma_sources',
                 '05_measurement_sources', '06_provenance', '07_reports', '08_blind_review']:
        (output / name).mkdir()
    evidence = output / '06_provenance/evidence'
    copies = []
    def copy(path, relative):
        path = src.track_bytes(path)
        dest = evidence / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        copies.append(dict(source_path=str(path), export_path=str(dest.relative_to(output)), sha256=sha(path)))
    for key, path in paths.items():
        copy(path, key + path.suffix)
    copy(binding_path, 'historical_binding.json')
    copy(old_path, 'generation_taskset_runtime.json')
    copy(prompt_path, 'legacy_feature_prompt_v1.txt')
    copy(schema_path, 'narrative_feature_schema_v1.json')
    copy(io_path, 'historical_measurement_io.py')
    copy(rewrite_io_path, 'historical_reanalysis_artifact_binding.py')
    pairs, qrows, originals, rewrites_out, before_out, after_out, blind, selected, curves = [], [], [], [], [], [], [], [], []
    for task_label, tid in zip('ABC', chosen):
        data = valid_data[tid]
        t, plan = data['task'], data['plan']
        film, ids, feature = t['source_film_id'], t['source_scene_ids'], t['selected_features'][0]
        source, reference = film_data[film], film_data[t['reference_film_id']]
        copy(source['meta_path'], f'{tid}/original_measurement_manifest.json')
        copy(reference['meta_path'], f'{tid}/target_measurement_manifest.json')
        target_records = [reference['features'][s] for s in t['reference_scene_ids']]
        write(evidence / tid / 'target_feature_rows.json', target_records)
        for root_key in ['rroot', 'aroot']:
            names = ['transfer_plan.json', 'rewritten_scenes.json', 'phase_status.json', 'rewrite_request.json'] if root_key == 'rroot' else ['transfer_plan.json', 'rewritten_scenes.json', 'rewritten_scene_features.json', 'measurement_status.json']
            for name in names:
                copy(data[root_key] / name, f'{tid}/{root_key}/{name}')
        B = plan['source_current_curve'][feature]
        T = plan['resampled_target_curve'][feature]
        A = [data['after'][sid][feature] for sid in ids]
        curves.append(dict(task_id=tid, film_id=film, target_feature=feature, scene_ids=ids,
                           reference_film_id=t['reference_film_id'], reference_scene_ids=t['reference_scene_ids'],
                           B=B, T=T, A=A, historical_transfer_plan=plan))
        selected.append(dict(task_label=task_label, task_id=tid, film_id=film, interval_length=len(ids),
                             target_feature=feature, target_feature_label=FEATURES[feature], scene_ids=ids,
                             historical_task=t, generation_historical_task=old_tasks[tid], historical_evaluation=data['record'],
                             model_presented_source_truncated=data['truncations']))
        for pos, sid in enumerate(ids, 1):
            original = source['scenes'][sid]['raw']
            rewrite = data['rewrites'][sid]
            before, after = source['features'][sid], data['after'][sid]
            pair_id = 'HE-' + hashlib.sha256(f'1701|{tid}|{sid}'.encode()).hexdigest()[:12]
            before_values, after_values = [{k: row[k] for k in FEATURES} for row in [before, after]]
            deltas = {k: Decimal(after[k]) - Decimal(before[k]) for k in FEATURES}
            refs = dict(original_script=str(source['script_path'].resolve()),
                        original_features=str(source['features_path'].resolve()),
                        rewrite=str((data['rroot'] / 'rewritten_scenes.json').resolve()),
                        reanalysis=str((data['aroot'] / 'rewritten_scene_features.json').resolve()),
                        transfer_plan=str((data['rroot'] / 'transfer_plan.json').resolve()),
                        taskset=str(paths['taskset']), evaluation=str(records_path))
            pair = dict(pair_id=pair_id, task_id=tid, film_id=film, original_scene_id=sid, rewritten_scene_id=sid,
                        original_raw_scene_id=original.get('scene_id', original.get('_id', original.get('id'))),
                        scene_position=pos, original_title=original.get('title', original.get('scene_heading', '')),
                        rewrite_title=rewrite['title'], original_text=text(original), rewrite_text=text(rewrite),
                        original_qwen=before_values, rewrite_qwen=after_values, delta=deltas,
                        target_feature=feature, target_value=T[pos - 1], source_references=refs,
                        model_presented_source_truncated=data['truncations'][pos - 1])
            pairs.append(pair)
            originals.append(dict(pair_id=pair_id, task_id=tid, film_id=film, scene_id=sid, source_reference=refs['original_script'], source_record=original))
            rewrites_out.append(dict(pair_id=pair_id, task_id=tid, film_id=film, scene_id=sid, source_reference=refs['rewrite'], source_record=rewrite))
            before_out.append(dict(pair_id=pair_id, task_id=tid, source_reference=refs['original_features'], source_record=before))
            after_out.append(dict(pair_id=pair_id, task_id=tid, source_reference=refs['reanalysis'], source_record=after))
            item = dict(pair_id=pair_id, film=film, task_id=tid, scene_position=pos,
                        original_scene_title=pair['original_title'], gemma_rewritten_scene_title=pair['rewrite_title'],
                        original_scene_text=text(original), gemma_rewritten_scene_text=text(rewrite))
            item.update({k: None for k in rating_fields()})
            blind.append(item)
            for k in FEATURES:
                qrows.append(dict(pair_id=pair_id, task_id=tid, film_id=film, scene_position=pos,
                                  original_scene_id=sid, rewritten_scene_id=sid, feature=k, feature_label=FEATURES[k],
                                  Original_Qwen=before[k], Rewrite_Qwen=after[k], Delta=deltas[k],
                                  Target_Value=T[pos - 1] if k == feature else None, is_target_feature=k == feature))
            copy(data['rroot'] / 'per_scene' / sid / 'rewrite_request.json', f'{tid}/per_scene/{sid}_request.json')
    write(output / '01_dataset/human_evaluation_dataset.json', dict(dataset_id=NAME, scene_pairs=pairs))
    csv_write(output / '01_dataset/human_evaluation_dataset.csv', pairs)
    write(output / '02_qwen_reference/qwen_feature_reference.json', qrows)
    csv_write(output / '02_qwen_reference/qwen_feature_reference.csv', qrows)
    write(output / '02_qwen_reference/target_curves.json', curves)
    write(output / '03_original_sources/selected_original_scenes.json', originals)
    write(output / '04_gemma_sources/selected_gemma_rewrites.json', rewrites_out)
    write(output / '05_measurement_sources/selected_original_qwen_features.json', before_out)
    write(output / '05_measurement_sources/selected_rewrite_qwen_features.json', after_out)
    write(output / '06_provenance/selected_tasks.json', selected)
    protocol = dict(seed=1701, inventory_size=len(inventory), eligible_count=len(candidates),
                    candidate_counts={str(n): sum(c['length'] == n for c in candidates) for n in (5, 8, 12)},
                    exclusion_policy='First failing mandatory eligibility criterion per task, recorded without relaxation.',
                    criteria=['Historical evaluation metric_eligible=true (no threshold on TI, DA, gain, difficulty, or target value)',
                              'Complete original/rewrite texts and five compatible historical Qwen features',
                              'Verified explicit film/task/scene IDs, ordering, contracts, hashes and target curves',
                              'Exactly 5, 8 or 12 consecutive scenes; distinct source films across selected tasks'],
                    algorithm='Sort eligible tasks lexicographically by task_id. Enumerate product(groups[5], groups[8], groups[12]); retain distinct source films. Retain combinations maximizing distinct target features. Select random.Random(1701).randrange(len(preferred)). No evaluation outcome values enter selection.',
                    **selection_stats, selected_task_ids=list(chosen), inventory=inventory)
    write(output / '06_provenance/selection_protocol.json', protocol)
    write(output / '06_provenance/model_metadata.json', dict(gemma=rw, original_qwen=fs, rewrite_qwen=ra, evaluation=ev,
          compatibility=dict(exact_measurement_contract_equality=True, all_240_task_semantic_keys_equal=SEMANTIC_KEYS,
                             canonical_taskset_sha256=TASK_HASH, generation_taskset_sha256=OLD_HASH)))
    random.Random(1701).shuffle(blind)
    write(output / '08_blind_review/human_review_items.json', blind)
    csv_write(output / '08_blind_review/human_review_items.csv', blind)
    instructions = '''# Human review instructions

Human evaluation has NOT YET BEEN PERFORMED. All rating fields are empty.
Rate each original and rewritten scene independently on the historical continuous 0.0–1.0 scale.
Preserve the provided text; leave a rating empty when you cannot assess it. Do not infer missing scores.
Read only this directory during rating. Do not open the reference, provenance, or report directories until ratings are locked.
The JSON null and CSV empty cells are uncollected ratings, never zero scores.
Scene headings are preserved in separate title fields; body text and its line breaks remain unchanged.

The following definitions are transcribed from the hash-verified historical feature prompt:

- Pacing: narrative speed, event progression, momentum.
- Dialogue Density: proportion and importance of spoken dialogue.
- Action Density: physical action, external events, movement, confrontation, or concrete incident density.
- Character Interaction: density and centrality of character-to-character exchange, conflict, cooperation, or relational movement.
- Emotion Intensity: affective intensity, tension, distress, intimacy, anger, fear, joy, or dramatic emotional charge.

The historical instrument provides no validated human anchors, intermediate examples, rater calibration,
inter-rater reliability procedure, or human-study protocol. This adaptation has not been validated as a human rubric.
No new anchors are supplied. The scene presentation identifies original and rewrite as requested; blinding is
limited to model measurements, numerical targets, and evaluation outcomes. Film/task labels remain visible.
Only distribute this directory to raters. The complete ZIP contains unblinded reference material.
The 25 anonymous pair IDs are stable and item order is shuffled with seed 1701.
Screenplay rights remain with their original holders. Use only within authorized private research.
'''
    (output / '08_blind_review/HUMAN_REVIEW_INSTRUCTIONS.md').write_text(instructions, encoding='utf-8')
    dictionary = '''# Data dictionary

This is an extraction/preparation dataset, not human-study results.

| Field or file | Meaning |
|---|---|
| pair_id | HE- plus first 12 hex characters of SHA256(1701\u007ctask_id\u007cscene_id); stable join key across all outputs |
| task_id / film_id | Original historical task identifier / source film identifier |
| original_scene_id / rewritten_scene_id | Historical normalized scene identifier, explicit ID join |
| original_raw_scene_id | Unmodified screenplay identifier; integer `_id` is zero-based |
| scene_position | One-based order in the selected source interval |
| original_text / rewrite_text | Full unmodified source string; UTF-8 and embedded newlines preserved |
| original_title / rewrite_title | Separate unmodified title fields; not concatenated into text |
| original_qwen / rewrite_qwen | Five original canonical historical feature values, continuous 0–1 |
| delta / Delta | Exact decimal subtraction rewrite minus original; computed, never a new measurement |
| target_feature / target_value | Historical selected axis and per-scene target from transfer plan |
| source_references | Resolved source paths, supplemented by source manifest hashes and exported evidence |
| source_record | Selected source object including its original identifiers and measurement provenance |
| B / T / A | Original measurements / historical target curve / rewritten-scene reanalysis, in scene_ids order |
| Target_Value | Numeric only for the task target feature, null/empty for the other four axes |
| model_presented_source_truncated | Historical rewrite request flag; export always keeps full archived original text |
| historical_evaluation | Unmodified historical eligibility, target_improved (TI boolean), directional_accuracy (DA), before/after target MAE |
| Original/Rewrite rating fields | Empty future human assessments; JSON null or CSV empty, never generated scores |
| SHA256SUMS | Hashes all ZIP payload files except itself; ZIP and external receipt excluded to avoid circular hashing |
| artifact_manifest.json | Payload inventory excluding itself, SHA256SUMS, ZIP and external receipt |
| EXPORT_RECEIPT.json | External post-ZIP receipt: archive hash/size, actual extracted comparison and current-source validation |

Features are `llm_pacing_score`, `llm_dialogue_density_score`, `llm_action_density_score`,
`llm_character_interaction_score`, and `llm_emotion_intensity_score`. Definitions are in the review instructions
and the exact historical prompt. JSON numbers use decimal parsing/emission without rounding or normalization.
CSV nested objects use valid JSON in quoted cells; use a CSV reader, not line splitting. CSV text cells may span lines.
The reference CSV is long form: 125 feature rows, containing 125 before and 125 after values plus 125 deltas.
The dataset CSV is wide form: 25 scene-pair rows. Null target values mean not the target axis, not unavailable measurements.

Source archive evidence includes both full historical 240-task runtimes to verify their exact SHA-256 identities.
Only selected screenplay objects are included; full film screenplay collections are not copied.
The source manifest covers files read across the complete candidate inventory; only selected source artifacts are packaged.
Checksums establish reproducible byte identity, not independent scientific or human validation.
'''
    (output / '07_reports/DATA_DICTIONARY.md').write_text(dictionary, encoding='utf-8')
    storage = '''# Storage authorization and rights

The operator explicitly authorized this selected historical export, including scene texts and model outputs,
to be committed and pushed to the existing private storygen-experiment-depot repository.
This is a narrow exception to the depot's default metadata-only policy, limited to
exports/tasksetv5_human_eval_3films_25pairs_v1/ and its self-contained ZIP.
The source implementation belongs in storygen-experiment. No model weights, credentials,
unselected film collections, or unrelated experiment archives are included.

The operator described both repositories as personal private research storage; their PRIVATE visibility
was verified before backup. Repository visibility must remain private. This authorization does not grant
copyright, public redistribution rights, or permission to change historical experiment records.
Original screenplay rights and restrictions remain with their holders. No source license or human-study
approval is invented. Distribute only the blind-review directory to authorized human raters; the full
archive contains unblinded scores and targets. Verify remote commit status separately from dataset gates.
'''
    (output / '06_provenance/STORAGE_AND_RIGHTS.md').write_text(storage, encoding='utf-8')
    report = ['# TasksetV5 human-evaluation source dataset', '',
              'Status: historical dataset extraction and preparation only. Human evaluation NOT YET PERFORMED. LLM inference NOT EXECUTED.', '',
              '## Overview and provenance', '',
              'Three distinct source films; three tasks; intervals 5/8/12; 25 original scenes; 25 Gemma rewrites; 50 scene texts; 25 scene pairs; 125 original and 125 rewrite Qwen feature values.', '',
              f'The E06 historical binding pins the canonical 240-task runtime SHA-256 `{TASK_HASH}`. This is not the M16 migration-verification taskset.', '',
              f'Generation and reanalysis manifests reference an earlier runtime SHA-256 `{OLD_HASH}`. All 240 task IDs, base interval IDs, source/reference films, scene IDs, selected axes and interval types are equal. Path fields, taskset version and difficulty metadata differ. Both exact runtimes are included; no identity equivalence is claimed for their bytes or difficulty values. Targets are taken from the original historical transfer plans and verified against reference Qwen rows, not reconstructed from difficulty fields.', '',
              'Gemma-3-12B-IT GGUF Q4_K_M, alias `gemma3-12b-it-gguf`, condition CG-v1, rewrite protocol v1.3. Model SHA-256 `fc57f67efa46d711c346e587cbef7d049e95f3df8db2eb2271153343ef0acc7b`. The manifest records llama.cpp Vulkan and four slots with 12288 context per slot, temperature 0.2 and max_tokens 4096. A legacy request field says generation_engine=vllm; backend identity here follows the hash-bound run/server manifest, while the original request field is retained as a historical metadata limitation.', '',
              'Both feature stages use Qwen2.5-7B-Instruct GGUF Q4_K_M, alias `qwen2.5-7b-q4`, model SHA-256 `65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423`. Feature measurement protocol v1.1.0, feature extraction v1.4.0, reanalysis v1.1.0. The complete measurement contracts are equal: instrument, prompt, schema, system instruction, request, decoding and model. Temperature 0, max_tokens 256, concurrency 8; llama.cpp commit `1425386fd996511e1f3295e7366c38289a92a271`, context per slot 12288. Historical normalization clamps to 0–1; this export applies no additional normalization.', '',
              '## Deterministic selection', '',
              f'Entire inventory: 240 tasks. Eligible: {len(candidates)}. Counts by length: {protocol["candidate_counts"]}. Excluded: {len(inventory)-len(candidates)}. First blocking reasons for every excluded task appear in selection_protocol.json.', '',
              protocol['algorithm'], '', f'Combination counts and sampled index: {selection_stats}.', '',
              '## Selected tasks', '', '| Task | Film | Length | Scenes | Target feature | Historical TI | Historical DA |', '|---|---|---:|---|---|---|---|']
    for s in selected:
        rec = s['historical_evaluation']
        report.append(f'| {s["task_id"]} | {s["film_id"]} | {s["interval_length"]} | {s["scene_ids"][0]}–{s["scene_ids"][-1]} | {s["target_feature_label"]} | {rec["target_improved"]} | {rec["directional_accuracy"]} |')
    report += ['', '## Alignment and complete pair inventory', '',
               'Explicit scene IDs join source, rewrite, transfer-plan and reanalysis rows. Original screenplay integer `_id` maps to scene_(id+1) using the historical measurement IO convention; raw IDs are retained. File hashes bind source screenplays to per-film original measurement manifests, and reanalysis status hashes bind exact rewritten text copies. No scene is split, merged, trimmed or summarized by this export. Scene headings remain separate fields.', '',
               '| Pair ID | Task | Film | Position | Original ID | Rewrite ID |', '|---|---|---|---:|---|---|']
    for p in pairs:
        report.append(f'| {p["pair_id"]} | {p["task_id"]} | {p["film_id"]} | {p["scene_position"]} | {p["original_scene_id"]} | {p["rewritten_scene_id"]} |')
    for s in selected:
        report += ['', f'## Feature comparison: {s["task_id"]} — {s["film_id"]}', '',
                   f'Target feature: **{s["target_feature_label"]}**. All values below are unrounded source decimals. Delta is deterministic rewrite minus original.', '',
                   '| Scene | Feature | Original_Qwen | Rewrite_Qwen | Delta | Target_Value |', '|---|---|---:|---:|---:|---:|']
        for q in qrows:
            if q['task_id'] == s['task_id']:
                report.append(f'| {q["original_scene_id"]} | {q["feature_label"]} | {q["Original_Qwen"]} | {q["Rewrite_Qwen"]} | {q["Delta"]} | {q["Target_Value"] if q["Target_Value"] is not None else ""} |')
    truncated = sum(p['model_presented_source_truncated'] for p in pairs)
    report += ['', '## Limitations and rights', '',
               f'Historical rewrite requests mark {truncated} of the 25 selected source scenes as truncated before generation. Full archived original texts are preserved in the dataset; request provenance is packaged. The historical IO strips boundary whitespace for measurement/model presentation; this export preserves the raw screenplay string. No new feature measurements or human scores are generated. Historical metric eligibility is technical evidence, not proof of content preservation, model validity or successful human validation.', '',
               'This is a deterministic small sample restricted to successful, fully measured historical Gemma outputs. It does not represent failed generations, all films, all axes equally, or a completed study. Original/rewrite labels and film/task identities are visible in review files; blinding covers scores, targets and outcomes only. The complete archive is unblinded and must not be given to raters. Human anchors and reliability procedures were not present in the historical rubric; the supplied adaptation is unvalidated.', '',
               'Screenplay copyright and distribution rights remain with the original holders. The source scene objects and prompt metadata are retained without inventing a license. No rights transfer or public distribution permission is asserted. Store this export only in the operator-authorized private research repositories. Existing historical scientific records are never overwritten.', '',
               '## Reproduction and inspection', '',
               'Python standard library only; no installs, downloads, inference server or experiment runner required.', '',
               '```bash', 'python tools/export_tasksetv5_human_eval.py --workspace /home/alp-emre/projects/01-Storygen-area --output /absolute/new/export/directory',
               'python 06_provenance/export_tasksetv5_human_eval.py --verify /absolute/export/directory',
               'python 06_provenance/export_tasksetv5_human_eval.py --verify /absolute/export/directory --check-sources', '```', '',
               'The first command is run from storygen-experiment and creates a new directory only. Selection seed is 1701. The packaged verifier works after extraction without the original repositories; --check-sources additionally checks every locally read historical file against its initial digest. Source paths are historical provenance and need not exist on a recipient machine.', '',
               'SHA256SUMS covers the complete payload except itself. artifact_manifest.json lists payload content hashes and sizes, excluding its own hash and checksums to avoid circularity. The ZIP includes both manifest and checksums. The external EXPORT_RECEIPT.json records the final ZIP hash/size and extracted verification. The in-ZIP validation report records actual preliminary packaging verification; a final packaging verification checks the final report and all final payload bytes.']
    (output / '07_reports/DATASET_REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    shutil.copyfile(Path(__file__), output / '06_provenance/export_tasksetv5_human_eval.py')
    source_manifest = dict(files=[dict(path=p, sha256=h, size_bytes=Path(p).stat().st_size) for p, h in sorted(src.hashes.items())],
                           exact_copies=copies, selected_source_objects='03_original_sources, 04_gemma_sources, 05_measurement_sources and selected target rows',
                           excluded_from_export='Unselected screenplay scene texts and unrelated experiment outputs',
                           historical_files_modified=False)
    write(output / '06_provenance/source_manifest.json', source_manifest)
    require(src.unchanged(), 'Historical source changed during extraction')
    # First actual archive is tested before the in-archive G19 statement is written.
    (output / '07_reports/VALIDATION_REPORT.md').write_text('# Validation report\n\nPackaging verification pending.\n', encoding='utf-8')
    package(output)
    first = verify(output, check_sources=True)
    require(all(g['status'] == 'PASS' for g in first['gates']), 'Initial mandatory validation failed')
    lines = ['# Validation report', '', 'All 20 mandatory gates PASS after deterministic validation and actual ZIP extraction comparison.', '',
             '| Gate | Requirement | Result |', '|---|---|---|']
    lines += [f'| {g["gate"]} | {g["description"]} | {g["status"]} |' for g in first['gates']]
    lines += ['', 'G01 checks the exact full canonical runtime hash and 240-task population. G10–G12 check model identities, exact measurement contracts, selected requests and artifact hashes. G15 checks B/T/A against selected plans and original reference rows. G17 compares all exported scene/measurement objects with packaged source evidence and initial source digests. G18 uses an exact allowlist of human item fields and verifies all ratings remain empty. G19 validates ZIP CRC, exact archive entry inventory, manifest hashes/sizes, SHA256SUMS and actual extracted bytes. G20 checks every source file consumed during inventory and extraction against its initial hash.', '',
              'The final archive is rebuilt to include this report, then independently verified again. EXPORT_RECEIPT.json outside the archive contains the final archive hash and final verification results. No checksum contains itself and no archive contains itself. No scientific experiment or human evaluation was executed.']
    (output / '07_reports/VALIDATION_REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    package(output)
    result = verify(output, check_sources=True)
    require(all(g['status'] == 'PASS' for g in result['gates']), 'Final mandatory validation failed')
    result.update(zip_path=str((output / ZIP).resolve()), zip_size_bytes=(output / ZIP).stat().st_size,
                  zip_sha256=sha(output / ZIP), selected_tasks=selected, status='DATASET_EXTRACTION_COMPLETE',
                  human_evaluation='NOT YET PERFORMED', llm_inference='NOT EXECUTED')
    write(output / 'EXPORT_RECEIPT.json', result)
    print(encode({k: v for k, v in result.items() if k != 'selected_tasks'}))


def payload_files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and p.name not in {ZIP, 'EXPORT_RECEIPT.json'} and '__pycache__' not in p.parts)


def package(root):
    manifest_path = root / '06_provenance/artifact_manifest.json'
    sums_path = root / '06_provenance/SHA256SUMS'
    entries = [dict(path=str(p.relative_to(root)), size_bytes=p.stat().st_size, sha256=sha(p))
               for p in payload_files(root) if p not in [manifest_path, sums_path]]
    write(manifest_path, dict(exclusions=['06_provenance/artifact_manifest.json', '06_provenance/SHA256SUMS', ZIP, 'EXPORT_RECEIPT.json'], files=entries))
    sums_path.write_text(''.join(f'{sha(p)}  {p.relative_to(root)}\n' for p in payload_files(root) if p != sums_path), encoding='utf-8')
    with zipfile.ZipFile(root / ZIP, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in payload_files(root):
            info = zipfile.ZipInfo(str(p.relative_to(root)), date_time=(2026, 10, 20, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def verify(root, check_sources=False):
    """Independently inspect exported objects and actual extracted ZIP; never write data."""
    root = Path(root).resolve()
    results = []
    def gate(number, fn):
        try:
            fn()
            results.append(dict(gate=f'G{number:02d}', description=GATES[number - 1], status='PASS'))
        except Exception as exc:
            results.append(dict(gate=f'G{number:02d}', description=GATES[number - 1], status='FAIL', reason=str(exc)))
    def check(ok, message='Validation assertion failed'):
        require(ok, message)
    evdir = root / '06_provenance/evidence'
    ts = read(evdir / 'taskset.json')
    pairs = read(root / '01_dataset/human_evaluation_dataset.json')['scene_pairs']
    selected = read(root / '06_provenance/selected_tasks.json')
    models = read(root / '06_provenance/model_metadata.json')
    before = read(root / '05_measurement_sources/selected_original_qwen_features.json')
    after = read(root / '05_measurement_sources/selected_rewrite_qwen_features.json')
    originals = read(root / '03_original_sources/selected_original_scenes.json')
    rewrites = read(root / '04_gemma_sources/selected_gemma_rewrites.json')
    curves = read(root / '02_qwen_reference/target_curves.json')
    source_manifest = read(root / '06_provenance/source_manifest.json')
    rows = read(root / '02_qwen_reference/qwen_feature_reference.json')
    bytask = index(ts['tasks'], 'task_id')
    bindex, aindex, oindex, rindex = [index(x, 'pair_id') for x in [before, after, originals, rewrites]]
    gate(1, lambda: check(sha(evdir / 'taskset.json') == TASK_HASH and len(bytask) == 240))
    gate(2, lambda: check(len({s['film_id'] for s in selected}) == 3))
    gate(3, lambda: check(len(selected) == len({s['task_id'] for s in selected}) == 3))
    gate(4, lambda: check([s['interval_length'] for s in selected] == [5, 8, 12]))
    gate(5, lambda: check(len(originals) == 25 and len(oindex) == 25))
    gate(6, lambda: check(len(rewrites) == 25 and len(rindex) == 25))
    gate(7, lambda: check(len(pairs) == len({p['pair_id'] for p in pairs}) == 25))
    gate(8, lambda: check(all(isinstance(p[k], str) and p[k].strip() for p in pairs for k in ['original_text', 'rewrite_text'])))
    def alignment():
        for s in selected:
            t = bytask[s['task_id']]
            pp = [p for p in pairs if p['task_id'] == s['task_id']]
            check([p['original_scene_id'] for p in pp] == [p['rewritten_scene_id'] for p in pp] == t['source_scene_ids'])
            check([p['scene_position'] for p in pp] == list(range(1, len(pp) + 1)))
            check(all(p['film_id'] == t['source_film_id'] for p in pp))
            ns = [int(x.split('_')[1]) for x in t['source_scene_ids']]
            check(ns == list(range(ns[0], ns[0] + len(ns))))
            for p in pp:
                raw = oindex[p['pair_id']]['source_record']
                rawid = raw.get('scene_id', raw.get('_id', raw.get('id')))
                check((f'scene_{rawid+1:03d}' if isinstance(rawid, int) else rawid) == p['original_scene_id'])
                check(p['original_raw_scene_id'] == rawid)
    gate(9, alignment)
    def gemma():
        m = models['gemma']
        check(m == read(evdir / 'rewrite_manifest.json'))
        check(m['prompt_contract_id'] == 'CG-v1' and m['model']['served_alias'] == 'gemma3-12b-it-gguf' and m['model']['quantization'] == 'Q4_K_M')
        check(m['model']['file_sha256'] == 'sha256:fc57f67efa46d711c346e587cbef7d049e95f3df8db2eb2271153343ef0acc7b')
        for s in selected:
            path = evdir / s['task_id']
            check(read(path / 'rroot/phase_status.json')['rewrite_completed'] is True)
            request = read(path / 'rroot/rewrite_request.json')
            check(request['run_id'] == s['task_id'] and request['prompt_profile'] == 'CG-v1' and request['model'] == 'gemma3-12b-it-gguf')
            for sid in s['scene_ids']:
                req = read(path / f'per_scene/{sid}_request.json')
                prompt = loads(req['user_instruction'])
                check(req['expected_scene_id'] == sid and req['model'] == 'gemma3-12b-it-gguf' and req['prompt_profile'] == 'CG-v1')
                check(prompt['source_scene']['scene_id'] == sid and prompt['source_film_id'] == s['film_id'] and prompt['source_interval_scene_ids'] == s['scene_ids'])
    gate(10, gemma)
    def original_measurement():
        m = models['original_qwen']['measurement']
        check(models['original_qwen'] == read(evdir / 'feature_set.json'))
        check(m['model']['alias'] == 'qwen2.5-7b-q4' and m['model']['quantization'] == 'Q4_K_M')
        check(m['model']['model_sha256'] == 'sha256:65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423')
        check('sha256:' + sha(evdir / 'legacy_feature_prompt_v1.txt') == m['prompt_hash'])
        check('sha256:' + sha(evdir / 'narrative_feature_schema_v1.json') == m['schema_hash'])
        for s in selected:
            meta = read(evdir / s['task_id'] / 'original_measurement_manifest.json')
            check(meta['measurement'] == m and meta['film_id'] == s['film_id'])
            for row in before:
                if row['task_id'] == s['task_id']:
                    r = row['source_record']
                    check(r['measurement_status'] == 'measured' and r['film_id'] == s['film_id'] and r['measurement_protocol_hash'] == m['protocol_hash'])
    gate(11, original_measurement)
    def reanalysis():
        ra = models['rewrite_qwen']
        check(ra == read(evdir / 'reanalysis_manifest.json'))
        check(ra['measurement'] == models['original_qwen']['measurement'])
        check(ra['source_rewrite_run']['manifest_sha256'] == 'sha256:' + sha(evdir / 'rewrite_manifest.json'))
        for s in selected:
            path = evdir / s['task_id']
            status = read(path / 'aroot/measurement_status.json')
            check(status['status'] == 'measured' and status['contract_equality_verified'] is True)
            check(status['measurement'] == status['source_feature_measurement'] == ra['measurement'])
            check(status['source_rewrite_artifact_sha256'] == rewrite_artifact_hash(path / 'rroot'))
            check(sha(path / 'rroot/rewritten_scenes.json') == sha(path / 'aroot/rewritten_scenes.json'))
            raw = index(read(path / 'aroot/rewritten_scene_features.json'))
            for row in after:
                if row['task_id'] == s['task_id']:
                    check(row['source_record'] == raw[row['source_record']['scene_id']])
    gate(12, reanalysis)
    gate(13, lambda: check(all(set(p[k]) == set(FEATURES) for p in pairs for k in ['original_qwen', 'rewrite_qwen', 'delta'])))
    def numbers():
        check(len(rows) == 125)
        for p in pairs:
            feature_rows = [row for row in rows if row['pair_id'] == p['pair_id']]
            check(len(feature_rows) == 5 and {row['feature'] for row in feature_rows} == set(FEATURES))
            for k in FEATURES:
                check(numeric(p['original_qwen'][k]) and numeric(p['rewrite_qwen'][k]))
                check(p['delta'][k] == Decimal(p['rewrite_qwen'][k]) - Decimal(p['original_qwen'][k]))
            check(numeric(p['target_value']))
        for row in rows:
            p = next(p for p in pairs if p['pair_id'] == row['pair_id'])
            k = row['feature']
            check(row['Original_Qwen'] == p['original_qwen'][k] and row['Rewrite_Qwen'] == p['rewrite_qwen'][k] and row['Delta'] == p['delta'][k])
            check(row['Target_Value'] == (p['target_value'] if k == p['target_feature'] else None))
    gate(14, numbers)
    def targets():
        old = read(evdir / 'generation_taskset_runtime.json')
        check(sha(evdir / 'generation_taskset_runtime.json') == OLD_HASH)
        oldtasks = index(old['tasks'], 'task_id')
        check(set(oldtasks) == set(bytask))
        for tid, task in bytask.items():
            check(all(task[k] == oldtasks[tid][k] for k in SEMANTIC_KEYS))
        for c in curves:
            tid = c['task_id']
            t = bytask[tid]
            plan = read(evdir / tid / 'rroot/transfer_plan.json')
            check(plan == read(evdir / tid / 'aroot/transfer_plan.json') == c['historical_transfer_plan'])
            check(plan['run_id'] == tid and plan['source_scene_ids'] == t['source_scene_ids'] and plan['reference_scene_ids'] == t['reference_scene_ids'])
            feature = t['selected_features'][0]
            pp = [p for p in pairs if p['task_id'] == tid]
            refs = index(read(evdir / tid / 'target_feature_rows.json'))
            check(c['B'] == plan['source_current_curve'][feature] == [p['original_qwen'][feature] for p in pp])
            check(c['T'] == plan['resampled_target_curve'][feature] == [refs[s][feature] for s in t['reference_scene_ids']] == [p['target_value'] for p in pp])
            check(c['A'] == [p['rewrite_qwen'][feature] for p in pp])
    gate(15, targets)
    def evaluation():
        records = index([loads(line) for line in (evdir / 'records.jsonl').read_text().splitlines() if line.strip()], 'task_id')
        ev = read(evdir / 'evaluation_manifest.json')
        check(ev == models['evaluation'] and ev['taskset']['sha256'] == 'sha256:' + TASK_HASH)
        check(ev['reanalysis_run']['manifest_sha256'] == 'sha256:' + sha(evdir / 'reanalysis_manifest.json'))
        for s in selected:
            rec = records[s['task_id']]
            check(rec == s['historical_evaluation'] and rec['metric_eligible'] is True and rec['ineligible_reason'] is None)
            check(rec['feature'] == s['target_feature'] and rec['method'] == 'CG-v1' and rec['rewrite_model'] == 'gemma3-12b-it-gguf')
    gate(16, evaluation)
    def faithful():
        for copy in source_manifest['exact_copies']:
            check(sha(root / copy['export_path']) == copy['sha256'])
        for p in pairs:
            pid = p['pair_id']
            check(p['original_text'] == text(oindex[pid]['source_record']) and p['rewrite_text'] == text(rindex[pid]['source_record']))
            check(all(p['original_qwen'][k] == bindex[pid]['source_record'][k] and p['rewrite_qwen'][k] == aindex[pid]['source_record'][k] for k in FEATURES))
            rewrite = index(read(evdir / p['task_id'] / 'rroot/rewritten_scenes.json')['rewritten_scenes'])[p['rewritten_scene_id']]
            check(rewrite == rindex[pid]['source_record'])
            if check_sources:
                actual_original = source_index(read(p['source_references']['original_script']))[p['original_scene_id']]['raw']
                actual_before = index(read(p['source_references']['original_features']))[p['original_scene_id']]
                actual_after = index(read(p['source_references']['reanalysis']))[p['rewritten_scene_id']]
                check(oindex[pid]['source_record'] == actual_original, 'Original screenplay source object mismatch')
                check(bindex[pid]['source_record'] == actual_before, 'Original measurement source object mismatch')
                check(aindex[pid]['source_record'] == actual_after, 'Rewrite measurement source object mismatch')
        protocol = read(root / '06_provenance/selection_protocol.json')
        selected_ids, stats = select([x for x in protocol['inventory'] if x['eligible']])
        check(list(selected_ids) == protocol['selected_task_ids'] == [s['task_id'] for s in selected])
        check(all(protocol[k] == v for k, v in stats.items()))
        # Parse CSV correctly, including multiline screenplay fields, and compare all JSON fields.
        for csvpath, expected in [('01_dataset/human_evaluation_dataset.csv', pairs), ('02_qwen_reference/qwen_feature_reference.csv', rows)]:
            with (root / csvpath).open(encoding='utf-8', newline='') as stream:
                actual = list(csv.DictReader(stream))
            check(len(actual) == len(expected))
            for a, e in zip(actual, expected):
                check(set(a) == set(e))
                for k, v in e.items():
                    target = '' if v is None else encode(v) if isinstance(v, (dict, list)) else str(v)
                    check(a[k] == target, f'CSV round-trip mismatch {csvpath}:{k}')
    gate(17, faithful)
    def blindness():
        items = read(root / '08_blind_review/human_review_items.json')
        allowed = {'pair_id', 'film', 'task_id', 'scene_position', 'original_scene_title',
                   'gemma_rewritten_scene_title', 'original_scene_text', 'gemma_rewritten_scene_text', *rating_fields()}
        check(len(items) == 25 and len({i['pair_id'] for i in items}) == 25)
        for i in items:
            check(set(i) == allowed and all(i[k] is None for k in rating_fields()))
            p = next(p for p in pairs if p['pair_id'] == i['pair_id'])
            check(i['original_scene_text'] == p['original_text'] and i['gemma_rewritten_scene_text'] == p['rewrite_text'])
            check(i['original_scene_title'] == p['original_title'] and i['gemma_rewritten_scene_title'] == p['rewrite_title'])
            check(i['film'] == p['film_id'] and i['task_id'] == p['task_id'] and i['scene_position'] == p['scene_position'])
        with (root / '08_blind_review/human_review_items.csv').open(encoding='utf-8', newline='') as f:
            csvitems = list(csv.DictReader(f))
        check(len(csvitems) == len(items))
        for c, i in zip(csvitems, items):
            check(set(c) == allowed)
            check(all(c[k] == ('' if v is None else str(v)) for k, v in i.items()))
        check({p.name for p in (root / '08_blind_review').iterdir()} == {'human_review_items.json', 'human_review_items.csv', 'HUMAN_REVIEW_INSTRUCTIONS.md'})
    gate(18, blindness)
    def archive():
        manifest = read(root / '06_provenance/artifact_manifest.json')
        listed = {e['path']: e for e in manifest['files']}
        excluded = {'06_provenance/artifact_manifest.json', '06_provenance/SHA256SUMS'}
        actual = {str(p.relative_to(root)) for p in payload_files(root)}
        check(set(listed) | excluded == actual)
        for rel, e in listed.items():
            check(sha(root / rel) == e['sha256'] and (root / rel).stat().st_size == e['size_bytes'], f'Manifest mismatch: {rel}')
        for rel in actual:
            if rel.endswith('.json'):
                read(root / rel)
        sums = {}
        for line in (root / '06_provenance/SHA256SUMS').read_text().splitlines():
            digest, rel = line.split('  ', 1)
            check(rel not in sums)
            sums[rel] = digest
            check(sha(root / rel) == digest, f'Checksum mismatch: {rel}')
        check(set(sums) == actual - {'06_provenance/SHA256SUMS'})
        with zipfile.ZipFile(root / ZIP) as z:
            check(z.testzip() is None, 'ZIP CRC failure')
            check(len(z.namelist()) == len(set(z.namelist())) and set(z.namelist()) == actual, 'ZIP inventory mismatch')
            check(all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist()))
            with tempfile.TemporaryDirectory(prefix='tasksetv5-zip-verify-') as tmp:
                z.extractall(tmp)
                check(all(sha(Path(tmp) / rel) == sha(root / rel) for rel in actual), 'Extracted ZIP differs from staging')
    gate(19, archive)
    def sources():
        if check_sources:
            for e in source_manifest['files']:
                check(Path(e['path']).is_file() and sha(e['path']) == e['sha256'], f'Historical source changed: {e["path"]}')
        else:
            check(source_manifest['historical_files_modified'] is False)
            check(bool(source_manifest['files']))
    gate(20, sources)
    return dict(gates=results, source_check='CURRENT_LOCAL_HASHES_VERIFIED' if check_sources else 'EXTRACTION_ATTESTATION_ONLY; use --check-sources for current files',
                counts=dict(films=len({s['film_id'] for s in selected}), tasks=len(selected), original_scenes=len(originals),
                            rewrite_scenes=len(rewrites), scene_pairs=len(pairs), original_qwen_values=len(before)*5, rewrite_qwen_values=len(after)*5))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path('/home/alp-emre/projects/01-Storygen-area'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--check-sources', action='store_true')
    args = parser.parse_args()
    if args.verify:
        result = verify(args.verify, args.check_sources)
        print(encode(result))
        return 0 if all(g['status'] == 'PASS' for g in result['gates']) else 1
    output = args.output or args.workspace / 'storygen-experiment-depot/exports' / NAME
    build(args.workspace.resolve(), output.resolve())
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'DATASET_EXTRACTION_FAILED: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
