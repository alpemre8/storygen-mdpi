"""Experiment registry/catalog v1.0. Shared technical distribution; no science imports."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import yaml

GROUPS = {
    'tasksetv5': 'TasksetV5 Main',
    'reviewer_round1': 'Reviewer Round 1 (E01–E05)',
    'measurement': 'Feature Measurement and Reliability',
    'analysis': 'Research Analysis',
    'naturalness': 'Naturalness / GSRN (independent)',
}


def contracts(repo: Path):
    path = repo / 'contracts/v1/validate.py'
    spec = importlib.util.spec_from_file_location('storygen_contracts_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo_id(repo: Path) -> str:
    manifest = repo / 'REPOSITORY_MANIFEST.json'
    if manifest.is_file():
        return json.loads(manifest.read_text())['repository_id']
    raise ValueError('Repository identity manifest required: ' + str(repo))


def load_registry(repo: Path) -> list[dict]:
    """Declared candidates stay explicitly pending until their packaging phase."""
    repo = repo.resolve()
    validator = contracts(repo)
    owners = json.loads((repo / 'contracts/v1/owner_registry.json').read_text())['owners']
    validator.validate_owners(owners)
    local_id = repo_id(repo)
    result = {row['experiment_id']: dict(row, registry_status='REGISTERED_PENDING_PACKAGING',
              execution_status='UNKNOWN', scientific_validity='UNVERIFIED', manifest_path=None)
              for row in owners if row['owner_repo'] == local_id}
    paths = sorted((repo / 'experiments').glob('*/*/experiment.yaml'))
    for path in paths:
        value = yaml.safe_load(path.read_text())
        validator.validate('experiment', value)
        if value['owner_repo'] != local_id:
            raise ValueError('Support repository cannot claim another owner: ' + str(path))
        expected = repo / 'experiments' / value['group_id'] / value['experiment_id'] / 'experiment.yaml'
        if path != expected:
            raise ValueError('Manifest path does not match experiment identity: ' + str(path))
        key = value['experiment_id']
        if result.get(key, {}).get('manifest_path'):
            raise ValueError('Duplicate experiment manifest: ' + key)
        result[key] = dict(value, registry_status='PACKAGED', manifest_path=str(path.relative_to(repo)),
                           question=value['scientific_question'])
    return sorted(result.values(), key=lambda r: (list(GROUPS).index(r['group_id']) if r['group_id'] in GROUPS else len(GROUPS), r['group_id'], r['experiment_id']))


def show(repo: Path, experiment_id: str) -> dict:
    for row in load_registry(repo):
        if row['experiment_id'] == experiment_id:
            return row
    raise ValueError('Unknown local owner experiment: ' + experiment_id)


def doctor(repo: Path, experiment_id: str | None = None) -> dict:
    rows = [show(repo, experiment_id)] if experiment_id else load_registry(repo)
    checks = []
    for row in rows:
        errors = []
        if row['registry_status'] != 'PACKAGED':
            errors.append('Owner runner packaging is pending its migration phase')
        else:
            runner = repo / row['public_runner']
            lock = runner.parent / 'dependencies.lock.yaml'
            if not runner.is_file():
                errors.append('Missing primary runner')
            if not lock.is_file():
                errors.append('Missing dependency lock')
            else:
                value = yaml.safe_load(lock.read_text())
                contracts(repo).validate('dependency_lock', value)
                if value['experiment_id'] != row['experiment_id']:
                    errors.append('Lock experiment identity mismatch')
        checks.append(dict(experiment_id=row['experiment_id'], registry_status=row['registry_status'],
                           runnable=not errors, errors=errors))
    return dict(repository=repo_id(repo), ready=all(r['runnable'] for r in checks), experiments=checks)


def render_catalog(repo: Path) -> str:
    rows = load_registry(repo)
    lines = ['# Experiments', '',
             'Generated from versioned owner metadata. Execution status and scientific validity are separate.', '']
    for group in dict.fromkeys(row['group_id'] for row in rows):
        lines += ['## ' + GROUPS.get(group, group), '']
        for row in [r for r in rows if r['group_id'] == group]:
            key = row['experiment_id']
            if row['registry_status'] == 'PACKAGED' and (repo / row['public_runner']).is_file():
                link = f"[{key}]({row['public_runner']})"
                dependencies = '[locked dependencies](' + str(Path(row['public_runner']).parent / 'dependencies.lock.yaml') + ')'
                stages = ' → '.join(stage['stage_id'] for stage in row['stages'])
            else:
                entries = row.get('legacy_entrypoints', '').split('; ')
                existing = [p for p in entries if p and (repo / p).is_file()]
                link = f"[{key}]({existing[0]})" if existing else key
                dependencies = 'legacy protocol; owner packaging pending'
                stages = row.get('question', '')
            question = row.get('scientific_question') or row.get('question')
            lines.append(f"- {link} — {question} Owner: `{row['owner_repo']}`. Stages: {stages}. {dependencies}. Execution: **{row['execution_status']}**; science: **{row['scientific_validity']}**.")
        lines.append('')
    lines += ['Run `python tools/experiments.py list`, `show <id>`, or `doctor <id>`.', '']
    return '\n'.join(lines)


def main(argv=None, default_repo=None):
    parser = argparse.ArgumentParser(description='Discover experiment owners and exact protocol metadata.')
    parser.add_argument('--repo', type=Path, default=default_repo)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    p = sub.add_parser('show'); p.add_argument('experiment_id')
    p = sub.add_parser('doctor'); p.add_argument('experiment_id', nargs='?')
    p = sub.add_parser('catalog'); p.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if args.repo is None:
        parser.error('--repo is required')
    repo = args.repo.resolve()
    if args.action == 'list':
        result = load_registry(repo)
    elif args.action == 'show':
        result = show(repo, args.experiment_id)
    elif args.action == 'doctor':
        result = doctor(repo, args.experiment_id)
        print(json.dumps(result, indent=2)); return 0 if result['ready'] else 2
    else:
        output = repo / 'EXPERIMENTS.md'
        text = render_catalog(repo)
        if args.check:
            if not output.is_file() or output.read_text() != text:
                raise ValueError('Catalog is stale: ' + str(output))
        else:
            output.write_text(text)
        result = dict(catalog=str(output), sha256=hashlib.sha256(text.encode()).hexdigest())
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    sys.exit(main())
