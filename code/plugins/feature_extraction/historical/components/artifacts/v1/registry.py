"""Create-only experiment runs, immutable producer references, and legacy locators v1."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
REPOS = ('storygen-rewrite', 'storygen-feature-extraction', 'storygen-evaluation', 'storygen-naturalness')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = load(ROOT / 'components/runtime/v1/runtime.py', 'artifact_runtime_v1')
contracts = load(ROOT / 'contracts/v1/validate.py', 'artifact_contracts_v1')


def depot_map(workspace, overrides=None):
    workspace = Path(workspace)
    result = {}
    for repo in REPOS:
        path = Path((overrides or {}).get(repo + '-depot', workspace / (repo + '-depot'))).expanduser().resolve()
        manifest = path / 'DEPOT_MANIFEST.json'
        if not manifest.is_file() or json.loads(manifest.read_text()).get('depot_id') != repo + '-depot':
            raise ValueError('Depot identity mismatch: ' + str(path))
        result[repo + '-depot'] = path
    return result


def run_root(depot, group, experiment, run_id):
    for value in [group, experiment, run_id]:
        runtime.identifier(value)
    return runtime.contained(depot, f'experiments/{group}/{experiment}/runs/{run_id}')


def resolve(reference, depots, *, require_sealed=False):
    contracts.validate('artifact_ref', reference)
    address = reference['locator']
    root_id = address['root_id']
    if root_id != reference['producer_repo'] + '-depot' or root_id not in depots:
        raise ValueError('Artifact producer/depot identity mismatch')
    parts = Path(address['relative_path']).parts
    if len(parts) < 6 or parts[0] != 'experiments' or parts[3] != 'runs':
        raise ValueError('New artifact requires the versioned experiment run namespace; use legacy locator for history')
    if parts[2] != reference['producer_experiment'] or parts[4] != reference['producer_run_id']:
        raise ValueError('Artifact run/experiment locator mismatch')
    expected = run_root(depots[root_id], parts[1], reference['producer_experiment'], reference['producer_run_id'])
    path = runtime.contained(depots[root_id], address['relative_path'])
    if not path.is_file() or runtime.sha256_file(path) != reference['sha256']:
        raise RuntimeError('Artifact missing or SHA mismatch: ' + str(path))
    if parts[0] == 'experiments':
        if not path.is_relative_to(expected):
            raise ValueError('Artifact run/experiment locator mismatch')
        seal = expected / 'SEALED.json'
        if require_sealed and not seal.is_file():
            raise RuntimeError('Artifact run has no immutable seal')
        if seal.is_file():
            manifest = expected / 'run_manifest.json'
            if runtime.sha256_file(manifest) != json.loads(seal.read_text())['manifest_sha256']:
                raise RuntimeError('Sealed run manifest changed')
            record = json.loads(manifest.read_text())
            contracts.validate('run_manifest', record)
            if (record['experiment_id'], record['run_id'], record['protocol_id'], record['group_id']) != (reference['producer_experiment'], reference['producer_run_id'], reference['protocol_id'], parts[1]):
                raise RuntimeError('Sealed producer identity mismatch')
            listed = record['artifacts'] + record['exact_input_bindings']
            if not any(item == reference for item in listed):
                raise RuntimeError('Artifact is not listed by its sealed producer manifest')
    return path


class RunStore:
    def __init__(self, depot, *, owner_repo, producer_repo, group, experiment, protocol, run_id, purpose,
                 lock_sha256, parent_run_ids=None):
        if owner_repo not in REPOS or producer_repo not in REPOS:
            raise ValueError('Unknown source owner/producer')
        if purpose not in {'RESEARCH', 'MIGRATION_VERIFICATION', 'SYNTHETIC_TEST'}:
            raise ValueError('Explicit run purpose required')
        self.depot = Path(depot).resolve()
        identity = json.loads((self.depot / 'DEPOT_MANIFEST.json').read_text())
        if identity['depot_id'] != producer_repo + '-depot':
            raise ValueError('Wrong producer depot')
        self.root = run_root(self.depot, group, experiment, run_id)
        self.producer = producer_repo
        self.manifest = dict(schema_version='1.0', run_id=run_id, experiment_id=experiment, group_id=group,
            owner_repo=owner_repo, protocol_id=protocol, run_revision='1', purpose=purpose,
            exact_input_bindings=[], started_utc=runtime.utc(), finished_utc=None, execution_status='RUNNING',
            contract_status='UNVERIFIED', scientific_validity='UNVERIFIED', artifacts=[],
            parent_run_ids=parent_run_ids or [], code_environment=dict(lock_sha256=lock_sha256, python=sys.version.split()[0]),
            stage_receipts=[])
        contracts.validate('run_manifest', self.manifest)

    def create(self, exact_configuration):
        self.root.mkdir(parents=True, exist_ok=False)
        for part in ['inputs', 'raw', 'logs', 'tables', 'reports', 'stage_receipts']:
            (self.root / part).mkdir()
        runtime.exclusive_json(self.root / 'RUN_STARTED.json', self.manifest)
        path = self.write_json('inputs/exact_configuration.json', exact_configuration)
        self.manifest['exact_input_bindings'].append(self.reference(path, 'exact_configuration', 'storygen.run-configuration/1.0'))
        return self

    def writable(self, relative):
        if (self.root / 'SEALED.json').exists() or (self.root / 'run_manifest.json').exists():
            raise RuntimeError('Run is terminal; immutable write refused')
        if not (self.root / 'RUN_STARTED.json').is_file():
            raise RuntimeError('Run must be exclusively reserved before writes')
        return runtime.contained(self.root, relative)

    def write_json(self, relative, value):
        path = self.writable(relative)
        runtime.exclusive_json(path, value)
        return path

    def reference(self, path, role, schema_id):
        path = Path(path).absolute()
        if not path.is_relative_to(self.root):
            raise ValueError('Producer cannot register an artifact outside its own new run')
        path = runtime.contained(self.root, str(path.relative_to(self.root)))
        value = dict(producer_repo=self.producer, producer_experiment=self.manifest['experiment_id'],
            protocol_id=self.manifest['protocol_id'], producer_run_id=self.manifest['run_id'],
            artifact_role=role, sha256=runtime.sha256_file(path), schema_id=schema_id,
            locator=dict(root_id=self.producer + '-depot', relative_path=str(path.relative_to(self.depot))))
        return contracts.validate('artifact_ref', value)

    def register(self, relative, *, role, schema_id):
        path = self.writable(relative)
        reference = self.reference(path, role, schema_id)
        if any(item['locator'] == reference['locator'] for item in self.manifest['artifacts']):
            raise ValueError('Duplicate authoritative artifact registration')
        self.manifest['artifacts'].append(reference)
        return reference

    def seal(self, *, failed=False):
        self.writable('run_manifest.json')
        for reference in self.manifest['exact_input_bindings'] + self.manifest['artifacts']:
            path = runtime.contained(self.depot, reference['locator']['relative_path'])
            if runtime.sha256_file(path) != reference['sha256']:
                raise RuntimeError('Artifact changed before sealing: ' + str(path))
        self.manifest.update(finished_utc=runtime.utc(), execution_status='FAILED' if failed else 'COMPLETE',
                             contract_status='INVALID' if failed else 'VALID')
        contracts.validate('run_manifest', self.manifest)
        runtime.exclusive_json(self.root / 'run_manifest.json', self.manifest)
        runtime.exclusive_json(self.root / 'SEALED.json', dict(status=self.manifest['execution_status'],
            manifest_sha256=runtime.sha256_file(self.root / 'run_manifest.json'), finished_utc=self.manifest['finished_utc']))
        return self.manifest


def index_sealed(depot):
    """One create-only catalog entry per manifest; an existing identity must match."""
    depot = Path(depot).resolve()
    identity = json.loads((depot / 'DEPOT_MANIFEST.json').read_text())['depot_id']
    count = 0
    for seal in sorted((depot / 'experiments').glob('*/*/runs/*/SEALED.json')):
        root = seal.parent
        manifest = root / 'run_manifest.json'
        value = json.loads(manifest.read_text())
        contracts.validate('run_manifest', value)
        expected = json.loads(seal.read_text())['manifest_sha256']
        if runtime.sha256_file(manifest) != expected:
            raise RuntimeError('Cannot index changed sealed run: ' + str(root))
        if root != run_root(depot, value['group_id'], value['experiment_id'], value['run_id']):
            raise ValueError('Manifest does not describe its run namespace')
        for reference in value['artifacts'] + value['exact_input_bindings']:
            if reference['locator']['root_id'] == identity:
                resolve(reference, {identity: depot}, require_sealed=True)
        entry = dict(schema_version='1.0', group_id=value['group_id'], experiment_id=value['experiment_id'],
            run_id=value['run_id'], purpose=value['purpose'], execution_status=value['execution_status'],
            scientific_validity=value['scientific_validity'], producer_depot=identity,
            manifest_relative_path=str(manifest.relative_to(depot)), manifest_sha256=expected)
        key = runtime.canonical_sha256(entry).removeprefix('sha256:')
        destination = depot / 'catalogs/experiment_architecture_v1/runs' / (key + '.json')
        if destination.exists():
            if json.loads(destination.read_text()) != entry:
                raise RuntimeError('Immutable catalog identity collision')
        else:
            runtime.exclusive_json(destination, entry)
        count += 1
    return count


def resolve_legacy(locator, depots):
    required = {'depot_id', 'relative_path', 'sha256', 'artifact_role'}
    if set(locator) != required or locator['depot_id'] not in depots:
        raise ValueError('Exact versioned legacy locator required')
    path = runtime.contained(depots[locator['depot_id']], locator['relative_path'])
    if not path.is_file() or runtime.sha256_file(path) != locator['sha256']:
        raise RuntimeError('Historical artifact missing or hash changed')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'projects')
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('resolve'); p.add_argument('reference', type=Path); p.add_argument('--require-sealed', action='store_true')
    p = sub.add_parser('legacy'); p.add_argument('locator', type=Path)
    sub.add_parser('index')
    args = parser.parse_args(argv)
    depots = depot_map(args.workspace)
    if args.action == 'index':
        result = {name: index_sealed(path) for name, path in depots.items()}
    elif args.action == 'resolve':
        result = dict(path=str(resolve(json.loads(args.reference.read_text()), depots, require_sealed=args.require_sealed)))
    else:
        result = dict(path=str(resolve_legacy(json.loads(args.locator.read_text()), depots)))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
