#!/usr/bin/env python3
"""Check user-supplied screenplay files locally; no download, mutation or inference."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def check(root):
    registry = json.loads((ROOT / 'sources/sources.json').read_text())
    results = []
    root = root.resolve()
    for source in registry['inputs']:
        relative = Path(source['local_path']).relative_to('local-inputs')
        path = (root / relative).resolve()
        row = {'film_id': source['film_id'], 'path': str(path)}
        expected = source['historical_input']
        if not path.is_relative_to(root):
            row['status'] = 'PATH_ESCAPES_INPUT_ROOT'
        elif not path.is_file():
            row['status'] = 'MISSING'
        else:
            raw = path.read_bytes()
            row['sha256'] = hashlib.sha256(raw).hexdigest()
            row['expected_sha256'] = expected['sha256']
            try:
                scenes = json.loads(raw)
                valid = isinstance(scenes, list) and len(scenes) == expected['scene_count']
                if valid:
                    for index, scene in enumerate(scenes):
                        valid = (isinstance(scene, dict)
                                 and type(scene.get('_id')) is int
                                 and scene['_id'] == index
                                 and all(isinstance(scene.get(key), str)
                                         for key in ('title', 'subtitle', 'content')))
                        if not valid:
                            break
                row['expected_scene_count'] = expected['scene_count']
                row['scene_count'] = len(scenes) if isinstance(scenes, list) else None
                row['structure_matches_historical_contract'] = valid
                row['status'] = ('MATCH' if valid and row['sha256'] == expected['sha256']
                                 else 'HASH_MISMATCH' if valid else 'STRUCTURE_MISMATCH')
            except (UnicodeError, ValueError):
                row['status'] = 'INVALID_JSON'
        results.append(row)
    ok = all(row['status'] == 'MATCH' for row in results)
    return {'status': 'PASS' if ok else 'MISSING_OR_CHANGED_INPUTS',
            'matched_files': sum(row['status'] == 'MATCH' for row in results),
            'expected_files': len(results), 'network_requests': 0,
            'inference_requests': 0, 'inputs_modified': False, 'files': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / 'local-inputs',
                        help='Local input directory containing films/<film_id>/script.json')
    args = parser.parse_args()
    report = check(args.root)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
