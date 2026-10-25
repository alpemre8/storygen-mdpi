"""Create a fresh operational binding of an unchanged archived scientific protocol."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

REPOS = ('storygen-rewrite', 'storygen-feature-extraction', 'storygen-evaluation')
METADATA = ('P01.json', 'FROZEN_SELECTION.json', 'ELIGIBILITY_LEDGER.json', 'SAMPLE_BALANCE_REPORT.json',
            'SOURCE_BINDINGS.json', 'REWRITE_BINDINGS.json', 'CONFLICT_CASE.json', 'AUDIT_MANIFEST.json',
            'SEQUENTIAL_MANIFEST.json', 'B1_ANCHOR_MANIFEST.json', 'PREPARATION_RECEIPT.json')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def rebase_protected(protected, original_workspace, provider_workspace):
    result = {}
    for recorded, expected in protected.items():
        path = Path(recorded)
        for repo in REPOS:
            original = Path(original_workspace) / repo
            if path.is_relative_to(original):
                path = Path(provider_workspace) / repo / path.relative_to(original)
                break
        result[str(path)] = expected
    return result


def fresh_binding(parent_path, run_root, provider_workspace, producer_roots):
    parent_path, run_root = Path(parent_path), Path(run_root)
    parent = json.loads(parent_path.read_text())
    original = json.loads(parent_path.read_text())
    if run_root.exists():
        raise FileExistsError('Protocol binding already exists: ' + str(run_root))
    run_root.mkdir(parents=True, exist_ok=False)
    (run_root / 'runtime').mkdir()
    for name in METADATA:
        path = parent_path.parent / name
        if path.is_file():
            shutil.copy2(path, run_root / name)
    # These are exact frozen input records, not prior generated results.
    for directory in ['inputs', 'manifests']:
        source_inputs = parent_path.parent / directory
        if source_inputs.exists():
            shutil.copytree(source_inputs, run_root / directory, symlinks=False)
    old_roots = original['roots']
    new_roots = {key: str(Path(producer_roots[repo]) / 'raw/protocol')
                 for key, repo in [('rewrite', REPOS[0]), ('feature', REPOS[1]), ('evaluation', REPOS[2])]
                 if key in old_roots}

    def output_path(value):
        if isinstance(value, str):
            path = Path(value)
            if path.is_absolute():
                for key, old in old_roots.items():
                    if path.is_relative_to(Path(old)):
                        return str(Path(new_roots[key]) / path.relative_to(old))
        elif isinstance(value, list):
            return [output_path(item) for item in value]
        elif isinstance(value, dict):
            return {key: output_path(item) for key, item in value.items()}
        return value

    parent['workspace'] = str(Path(provider_workspace).resolve())
    parent['roots'] = new_roots
    for key in ('rewrite_output', 'measurement_output', 'evaluation_output', 'executions'):
        if key in parent:
            parent[key] = output_path(parent[key])
    parent['protected'] = rebase_protected(original.get('protected', {}), original['workspace'], provider_workspace)
    changed = {key for key in original if parent[key] != original[key]}
    allowed = {'workspace', 'roots', 'protected', 'rewrite_output', 'measurement_output', 'evaluation_output', 'executions'}
    if not changed <= allowed:
        raise RuntimeError('Scientific configuration field changed: ' + repr(changed - allowed))
    # Execution dictionaries must retain every repetition/condition/seed and filename.
    if 'executions' in original:
        def shapes(value):
            if isinstance(value, dict):
                return {key: shapes(item) for key, item in value.items()}
            if isinstance(value, list):
                return [shapes(item) for item in value]
            if isinstance(value, str) and Path(value).is_absolute():
                return ('PATH_BASENAME', Path(value).name)
            return value
        if shapes(parent['executions']) != shapes(original['executions']):
            raise RuntimeError('Execution schedule changed while rebinding outputs')
    copied_inputs = {str(p.relative_to(run_root)): sha(p) for p in run_root.rglob('*') if p.is_file()}
    write(run_root / 'MIGRATION_BINDING.json', dict(
        parent_config=dict(path=str(parent_path.resolve()), sha256=sha(parent_path)),
        changed_operational_fields=sorted(changed), scientific_fields_unchanged=True,
        source_commits=parent['source_commits'], producer_roots=producer_roots, copied_frozen_inputs=copied_inputs,
        policy='No old run is mutated. Archived scientific inputs/seeds/prompts/denominators stay fixed.'))
    write(run_root / 'CONFIG.json', parent)
    (run_root / 'CONFIG.sha256').write_text(sha(run_root / 'CONFIG.json') + '\n')
    return parent


def install_owned_server_record(protocol_root, key, live_path, *, mode=None):
    """Use only a real owned-server receipt; the frozen API checks /proc and port."""
    record = json.loads(Path(live_path).read_text())
    profile = record['profile']
    if Path('/proc', str(record['pid']), 'cmdline').read_bytes().rstrip(b'\0').split(b'\0') != [s.encode() for s in record['command']]:
        raise RuntimeError('Owned server receipt does not identify the current exact process')
    value = dict(pid=record['pid'], command=record['command'])
    if mode:
        value['mode'] = mode
    path = Path(protocol_root) / 'runtime' / ('SERVER_' + key.upper() + '.json')
    if path.exists():
        old = json.loads(path.read_text())
        if old.get('pid') != value['pid'] or old.get('command') != value['command']:
            raise RuntimeError('Protocol refuses to reseal a changed server process')
    else:
        write(path, value)
