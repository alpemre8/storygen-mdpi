"""Owner-depot artifact registry v2; v1 distributed references remain readable."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('artifacts_v1_dependency', ROOT / 'components/artifacts/v1/registry.py')
v1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v1)
runtime, contracts, REPOS = v1.runtime, v1.contracts, v1.REPOS
load, depot_map, run_root = v1.load, v1.depot_map, v1.run_root
POLICY = 'storygen.owner-depot/2.0'


def resolve_legacy(locator, depots):
    if runtime.relative_path(locator['relative_path']).parts[0] in {'experiments', 'catalogs'}:
        raise ValueError('New experiment artifacts require registered sealed refs; legacy cannot bypass a seal')
    return v1.resolve_legacy(locator, depots)


def producer_path(owner, producer, relative):
    parts = runtime.relative_path(relative).parts
    if producer == owner:
        if parts[0] == 'providers': raise ValueError('Owner cannot claim a companion provider output')
    elif len(parts) < 3 or parts[:2] != ('providers', producer):
        raise ValueError('Companion artifacts must identify their producer beneath the owner run')


def resolve(reference, depots, *, require_sealed=False):
    contracts.validate('artifact_ref', reference)
    address = reference['locator']; root_id = address['root_id']
    if root_id not in depots: raise ValueError('Unknown storage depot identity')
    owner = root_id.removesuffix('-depot')
    if owner not in REPOS: raise ValueError('Unknown storage owner')
    parts = runtime.relative_path(address['relative_path']).parts
    if len(parts) < 6 or parts[0] != 'experiments' or parts[3] != 'runs' or parts[2] != reference['producer_experiment'] or parts[4] != reference['producer_run_id']:
        raise ValueError('Artifact experiment/run locator mismatch')
    root = run_root(depots[root_id], parts[1], parts[2], parts[4])
    policy_path = runtime.contained(root, 'inputs/storage_policy.json')
    if not policy_path.exists(): return v1.resolve(reference, depots, require_sealed=require_sealed)
    policy = json.loads(policy_path.read_text())
    if policy != dict(version=POLICY, owner_repo=owner, output_policy='ONE_OWNER_RUN_ROOT'):
        raise ValueError('Storage policy differs from owner depot identity')
    producer_path(owner, reference['producer_repo'], str(Path(*parts[5:])))
    path = runtime.contained(depots[root_id], address['relative_path'])
    if not path.is_file() or runtime.sha256_file(path) != reference['sha256']:
        raise RuntimeError('Artifact missing or SHA mismatch: ' + str(path))
    seal = runtime.contained(root, 'SEALED.json')
    if require_sealed and not seal.is_file(): raise RuntimeError('Owner run has no immutable seal')
    if seal.is_file():
        manifest = runtime.contained(root, 'run_manifest.json')
        if runtime.sha256_file(manifest) != json.loads(seal.read_text())['manifest_sha256']:
            raise RuntimeError('Sealed owner run manifest changed')
        record = contracts.validate('run_manifest', json.loads(manifest.read_text()))
        if (record['owner_repo'], record['group_id'], record['experiment_id'], record['run_id'], record['protocol_id']) != (owner, parts[1], parts[2], parts[4], reference['protocol_id']):
            raise ValueError('Sealed owner/experiment/protocol identity mismatch')
        listed = record['artifacts'] + record['exact_input_bindings']
        if reference not in listed: raise RuntimeError('Artifact is not registered by its owner manifest')
        policy_ref = next((item for item in listed if item['locator']['root_id'] == root_id and item['locator']['relative_path'] == str(policy_path.relative_to(depots[root_id]))), None)
        if not policy_ref or policy_ref['sha256'] != runtime.sha256_file(policy_path):
            raise RuntimeError('Owner storage policy was not sealed or changed')
    return path


class RunStore(v1.RunStore):
    def __init__(self, depot, *, owner_repo, **kwargs):
        producer = kwargs.pop('producer_repo', owner_repo)
        if producer != owner_repo: raise ValueError('Only the primary owner can reserve an owner-depot run')
        super().__init__(depot, owner_repo=owner_repo, producer_repo=owner_repo, **kwargs)

    def create(self, exact_configuration):
        super().create(exact_configuration)
        path = self.write_json('inputs/storage_policy.json', dict(version=POLICY, owner_repo=self.producer, output_policy='ONE_OWNER_RUN_ROOT'))
        self.manifest['exact_input_bindings'].append(self.reference(path, 'storage_policy', POLICY))
        return self

    def reference(self, path, role, schema_id, *, producer_repo=None):
        producer = producer_repo or self.producer
        if producer not in REPOS: raise ValueError('Unknown scientific producer')
        path = Path(path).absolute()
        if not path.is_relative_to(self.root): raise ValueError('Artifact escapes owner run')
        producer_path(self.producer, producer, str(path.relative_to(self.root)))
        value = super().reference(path, role, schema_id)
        value['producer_repo'] = producer
        return contracts.validate('artifact_ref', value)

    def register(self, relative, *, role, schema_id, producer_repo=None):
        path = self.writable(relative)
        reference = self.reference(path, role, schema_id, producer_repo=producer_repo)
        if any(item['locator'] == reference['locator'] for item in self.manifest['artifacts']):
            raise ValueError('Duplicate authoritative artifact registration')
        self.manifest['artifacts'].append(reference)
        return reference


def index_sealed(depot):
    depot = Path(depot).resolve()
    identity = json.loads((depot / 'DEPOT_MANIFEST.json').read_text())['depot_id']; count = 0
    for seal in sorted((depot / 'experiments').glob('*/*/runs/*/SEALED.json')):
        root = seal.parent; manifest = root / 'run_manifest.json'
        value = contracts.validate('run_manifest', json.loads(manifest.read_text()))
        digest = runtime.sha256_file(manifest)
        if digest != json.loads(seal.read_text())['manifest_sha256']: raise RuntimeError('Sealed manifest changed')
        if root != run_root(depot, value['group_id'], value['experiment_id'], value['run_id']): raise ValueError('Run locator mismatch')
        for ref in value['artifacts'] + value['exact_input_bindings']:
            if ref['locator']['root_id'] == identity: resolve(ref, {identity: depot}, require_sealed=True)
        entry = dict(version='storygen.run-catalog/2.0', owner_repo=value['owner_repo'], storage_depot=identity,
            experiment_id=value['experiment_id'], group_id=value['group_id'], run_id=value['run_id'], purpose=value['purpose'],
            execution_status=value['execution_status'], scientific_validity=value['scientific_validity'],
            manifest_relative_path=str(manifest.relative_to(depot)), manifest_sha256=digest)
        path = depot / 'catalogs/experiment_architecture_v2/runs' / (runtime.canonical_sha256(entry).removeprefix('sha256:') + '.json')
        if path.exists():
            if json.loads(path.read_text()) != entry: raise RuntimeError('Catalog collision')
        else: runtime.exclusive_json(path, entry)
        count += 1
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'projects')
    sub = parser.add_subparsers(dest='action', required=True)
    p=sub.add_parser('resolve');p.add_argument('reference',type=Path);p.add_argument('--require-sealed',action='store_true')
    p=sub.add_parser('legacy');p.add_argument('locator',type=Path)
    sub.add_parser('index');args=parser.parse_args(argv);depots=depot_map(args.workspace)
    if args.action == 'index': result={key:index_sealed(path) for key,path in depots.items()}
    elif args.action == 'legacy': result=dict(path=str(resolve_legacy(json.loads(args.locator.read_text()),depots)))
    else: result=dict(path=str(resolve(json.loads(args.reference.read_text()),depots,require_sealed=args.require_sealed)))
    print(json.dumps(result,indent=2));return 0

if __name__ == '__main__': raise SystemExit(main())
