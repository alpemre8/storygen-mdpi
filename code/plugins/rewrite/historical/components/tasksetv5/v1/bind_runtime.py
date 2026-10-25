"""Technical reference binding / declared verification subset; never changes task fields."""
import argparse
import hashlib
import json
from pathlib import Path


CANONICAL = 'sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb'
FIELDS = ('task_id', 'source_film_id', 'reference_film_id', 'source_scene_ids', 'reference_scene_ids',
          'selected_features', 'variant', 'interval_type', 'base_interval_id', 'pair_key', 'feature_axis')


def sha(path):
    return 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def structure(tasks):
    projection = [{key: task.get(key) for key in FIELDS} for task in tasks]
    return 'sha256:' + hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def bind(parent, output, selected_ids=None, *, purpose):
    payload = json.loads(Path(parent).read_text())
    if len(payload['tasks']) != 240 or len(payload['base_intervals']) != 48 or structure(payload['tasks']) != CANONICAL:
        raise RuntimeError('Parent must be the full canonical 48/240 TasksetV5 structure')
    reference = Path(payload['feature_set_manifest'])
    checked = set()
    for task in payload['tasks']:
        if task['source_script_path'] in checked:
            continue
        measurement = reference.parent / 'films' / task['source_film_id'] / 'measurement_manifest.json'
        if json.loads(measurement.read_text())['script_sha256'] != sha(task['source_script_path']):
            raise RuntimeError('Original script differs from its frozen measurement binding')
        checked.add(task['source_script_path'])
    if selected_ids:
        if purpose != 'MIGRATION_VERIFICATION':
            raise ValueError('Bounded subsets are allowed only for explicit migration verification')
        ids = set(selected_ids)
        if len(ids) != len(selected_ids) or not ids <= {task['task_id'] for task in payload['tasks']}:
            raise ValueError('Verification task IDs must be unique and present in frozen parent')
        # Retain parent ordering and every scientific field, including complete scene intervals.
        payload['tasks'] = [task for task in payload['tasks'] if task['task_id'] in ids]
        bases = {task['base_interval_id'] for task in payload['tasks']}
        payload['base_intervals'] = [base for base in payload['base_intervals'] if base['base_interval_id'] in bases]
    payload['structure_sha256'] = structure(payload['tasks'])
    payload['migration_binding'] = dict(purpose=purpose, canonical_parent=dict(path=str(Path(parent).resolve()), sha256=sha(parent)),
        canonical_structure_sha256=CANONICAL, task_ids=[task['task_id'] for task in payload['tasks']],
        full_benchmark=len(payload['tasks']) == 240, scientific_fields_modified=False)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--purpose', choices=['RESEARCH', 'MIGRATION_VERIFICATION'], required=True)
    parser.add_argument('--task-id', action='append')
    args = parser.parse_args()
    bind(args.parent, args.output, args.task_id, purpose=args.purpose)
