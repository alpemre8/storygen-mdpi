"""Locked execution envelope v2: optional owned persistent local server lifecycle."""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import yaml


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self, runner, config, run_id, workspace, cache):
        self.runner = Path(runner).resolve()
        self.repo = self.runner.parents[3]
        self.home = self.runner.parent
        self.runtime = load(self.repo / 'components/runtime/v1/runtime.py', 'execution_runtime_v1')
        self.contracts = load(self.repo / 'contracts/v1/validate.py', 'execution_contracts_v1')
        self.manifest = self.contracts.validate('experiment', yaml.safe_load((self.home / 'experiment.yaml').read_text()))
        self.lock_path = self.home / 'dependencies.lock.yaml'
        self.lock = self.contracts.validate('dependency_lock', yaml.safe_load(self.lock_path.read_text()))
        if self.lock['experiment_id'] != self.manifest['experiment_id']:
            raise ValueError('Experiment and lock identity differ')
        self.config = config
        self.run_id = self.runtime.identifier(run_id)
        self.workspace, self.cache = Path(workspace).resolve(), Path(cache).resolve()
        self.providers = {}

    def input(self, name):
        ref = self.config['inputs'][name]
        path = Path(ref['path']).expanduser().resolve()
        if self.runtime.sha256_file(path) != ref['sha256']:
            raise RuntimeError('Input SHA mismatch: ' + name)
        return str(path)

    def source(self, repo_id):
        return self.providers.get(repo_id, Path(self.config.get('source_roots', {}).get(repo_id, self.workspace / repo_id)))

    def root(self, repo_id):
        depot = Path(self.config.get('depot_roots', {}).get(repo_id, self.workspace / (repo_id + '-depot'))).expanduser().resolve()
        if not (depot / 'DEPOT_MANIFEST.json').is_file():
            raise ValueError('Explicit valid owned depot required: ' + str(depot))
        if json.loads((depot / 'DEPOT_MANIFEST.json').read_text()).get('depot_id') != repo_id + '-depot':
            raise ValueError('Depot producer identity mismatch: ' + str(depot))
        return self.runtime.contained(depot, f"experiments/{self.manifest['group_id']}/{self.manifest['experiment_id']}/runs/{self.run_id}")

    def output(self, repo_id, stage):
        return self.root(repo_id) / 'raw' / self.runtime.identifier(stage)

    def command(self, repo_id, script, *args):
        return [sys.executable, str(self.source(repo_id) / self.runtime.relative_path(script)), *map(str, args)]

    def resolve(self, *, materialize=False):
        env = self.lock['environment']
        if sys.version.split()[0] != env['python']:
            raise RuntimeError('Python version differs from experiment lock')
        for package, version in env['packages'].items():
            if importlib.metadata.version(package) != version:
                raise RuntimeError('Environment package version mismatch: ' + package)
        identity = dict(python=env['python'], packages=env['packages'])
        if self.runtime.canonical_sha256(identity) != env['sha256']:
            raise RuntimeError('Environment lock content mismatch')
        for binding in self.lock['source_repositories']:
            repo_id, commit = binding['repo_id'], binding['commit']
            source = Path(self.config.get('source_roots', {}).get(repo_id, self.workspace / repo_id)).expanduser().resolve()
            head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            if head != commit:
                target = self.cache / repo_id / commit
                if not target.exists():
                    if not materialize:
                        raise RuntimeError('Exact provider checkout required; preflight materializes: ' + str(target))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(['git', '-C', str(source), 'worktree', 'add', '--detach', str(target), commit], check=True)
                source = target
            actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            if actual != commit:
                raise RuntimeError('Provider commit mismatch: ' + repo_id)
            names = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z']).decode().split('\0')
            tree = {name: self.runtime.sha256_file(source / name) for name in names if name}
            if self.runtime.canonical_sha256(tree) != binding['tree_sha256']:
                raise RuntimeError('Provider source tree changed: ' + repo_id)
            self.providers[repo_id] = source
        for component in self.lock['components']:
            root = self.providers[component['repo_id']]
            if self.runtime.content_digest(root, component['paths']) != component['sha256']:
                raise RuntimeError('Frozen component content mismatch: ' + component['component_id'])
        for asset in self.lock['assets']:
            root = self.repo if asset['root_id'] == 'owner' else self.providers.get(asset['root_id'], self.workspace / asset['root_id'])
            path = root / asset['path']
            if self.runtime.sha256_file(path) != asset['sha256']:
                raise RuntimeError('Frozen asset changed: ' + str(path))
        for name in self.config.get('inputs', {}):
            self.input(name)
        models = {str(Path(m['path']).expanduser().resolve()): m for m in self.lock['models']}
        selected = []
        if 'model_file' in self.config:
            selected.append(str(Path(self.config['model_file']).expanduser().resolve()))
        for role in ['profile', 'server_manifest', 'rewrite_server_manifest', 'measurement_server_manifest']:
            if role in self.config.get('inputs', {}):
                value = yaml.safe_load(Path(self.input(role)).read_text())
                model = value.get('model', value)
                path = model.get('checkpoint_path') or model.get('model_path')
                if path:
                    selected.append(str(Path(path).expanduser().resolve()))
        for path in set(selected):
            if path not in models:
                raise RuntimeError('Model is not declared in the experiment lock: ' + path)
            if self.runtime.sha256_file(path) != models[path]['sha256']:
                raise RuntimeError('Exact checkpoint SHA mismatch: ' + path)
        if self.lock['models'] and not selected:
            raise RuntimeError('Run configuration did not bind its exact locked model')
        if self.lock['models']:
            backend = Path(self.config.get('backend_root', self.workspace / 'llama.cpp'))
            commit = subprocess.check_output(['git', '-C', str(backend), 'rev-parse', 'HEAD'], text=True).strip()
            if commit != self.lock['runtime_profile']['backend_commit']:
                raise RuntimeError('Backend source/build identity differs from the frozen profile')
        return self.providers


def validate_plan(context, plan):
    expected = {s['stage_id']: s for s in context.manifest['stages']}
    seen = set()
    for stage in plan:
        key = stage['stage_id']
        if key not in expected or key in seen:
            raise ValueError('Unknown or duplicate executable stage: ' + key)
        if stage['provider_repo'] != expected[key]['provider_repo'] or not set(expected[key]['depends_on']) <= seen:
            raise ValueError('Stage provider/order differs from experiment manifest')
        command = stage['command']
        if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
            raise ValueError('Executable argv required, no shell commands')
        if any(flag in command for flag in ['--overwrite', '--overwrite-stale', '--resume', '--retry-failed-only']):
            raise ValueError('Historical overwrite/resume flags forbidden in new runs')
        seen.add(key)
    if seen != set(expected):
        raise ValueError('Executable plan omitted required stages')
    return plan


def artifact(context, repo_id, path, role):
    root = context.root(repo_id)
    return dict(producer_repo=repo_id, producer_experiment=context.manifest['experiment_id'],
                protocol_id=context.manifest['protocol_id'], producer_run_id=context.run_id,
                artifact_role=role, sha256=context.runtime.sha256_file(path), schema_id='storygen.file/1.0',
                locator=dict(root_id=repo_id + '-depot', relative_path=str(path.relative_to(root.parents[4]))))


def run(context, plan):
    r = context.runtime
    providers = sorted({stage['provider_repo'] for stage in plan} | {context.manifest['owner_repo']})
    for repo_id in providers:
        if context.root(repo_id).exists():
            raise FileExistsError('Run ID already reserved: ' + str(context.root(repo_id)))
    started = r.utc()
    manifests = {}
    for repo_id in providers:
        root = context.root(repo_id)
        root.mkdir(parents=True, exist_ok=False)
        for name in ['stage_receipts', 'inputs', 'raw', 'logs', 'tables', 'reports']:
            (root / name).mkdir()
        r.exclusive_json(root / 'inputs/exact_configuration.json', context.config)
        r.exclusive_json(root / 'inputs/dependency_lock.json', context.lock)
        files = [context.runner, context.home / 'experiment.yaml', context.home / 'src/protocol.py',
                 context.repo / 'components/execution/v2/envelope.py']
        owner_code = dict(source_commit=subprocess.check_output(['git', '-C', str(context.repo), 'rev-parse', 'HEAD'], text=True).strip(),
                          files={str(path.relative_to(context.repo)): r.sha256_file(path) for path in files})
        r.exclusive_json(root / 'inputs/owner_code.json', owner_code)
        manifests[repo_id] = dict(schema_version='1.0', run_id=context.run_id,
            experiment_id=context.manifest['experiment_id'], group_id=context.manifest['group_id'],
            owner_repo=context.manifest['owner_repo'], protocol_id=context.manifest['protocol_id'],
            run_revision='1', purpose=context.config['purpose'], exact_input_bindings=[artifact(context, repo_id, root / 'inputs/exact_configuration.json', 'exact_configuration')],
            started_utc=started, finished_utc=None, execution_status='RUNNING', contract_status='UNVERIFIED',
            scientific_validity='UNVERIFIED', artifacts=[], parent_run_ids=context.config.get('parent_run_ids', []),
            code_environment=dict(lock_sha256=r.sha256_file(context.lock_path), python=sys.version.split()[0]), stage_receipts=[])
        manifests[repo_id]['exact_input_bindings'].append(artifact(context, repo_id, root / 'inputs/owner_code.json', 'owner_code_identity'))
        r.exclusive_json(root / 'RUN_STARTED.json', manifests[repo_id])
    progress = r.Progress(len(plan))
    error = None
    servers = load(context.repo / 'components/execution/v2/servers.py', 'owned_servers_v2').Servers(context)
    try:
        for stage in plan:
            repo_id, stage_id = stage['provider_repo'], stage['stage_id']
            root = context.root(repo_id)
            began = time.monotonic()
            receipt = dict(schema_version='1.0', run_id=context.run_id,
                experiment_id=context.manifest['experiment_id'], stage_id=stage_id, provider_repo=repo_id,
                status='RUNNING', started_utc=r.utc(), finished_utc=None,
                input_sha256=r.canonical_sha256(context.config), outputs=[], command=stage['command'],
                elapsed_seconds=0, error=None)
            r.exclusive_json(root / ('stage_receipts/' + stage_id + '_started.json'), receipt)
            try:
                if stage.get('server_profile') and context.config.get('manage_servers', False):
                    servers.ensure(stage['server_profile'])
                env = {k: v for k, v in os.environ.items() if not k.startswith('STORYGEN_') and k not in {'PYTHONPATH', 'PYTHONHOME'}}
                for owner in providers:
                    key = {'storygen-rewrite': 'STORYGEN_REWRITE_DEPOT_ROOT', 'storygen-feature-extraction': 'STORYGEN_FEATURE_DEPOT_ROOT', 'storygen-evaluation': 'STORYGEN_EVALUATION_DEPOT_ROOT', 'storygen-naturalness': 'STORYGEN_NATURALNESS_DEPOT_ROOT'}[owner]
                    env[key] = str(context.root(owner).parents[4])
                with (root / ('logs/' + stage_id + '.log')).open('xb') as log:
                    subprocess.run(stage['command'], cwd=context.source(repo_id), env=env,
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                outputs = [p for p in context.output(repo_id, stage_id).rglob('*') if p.is_file()]
                if not outputs:
                    raise RuntimeError('Scientific stage produced no output artifacts: ' + stage_id)
                receipt['outputs'] = [artifact(context, repo_id, p, stage_id) for p in sorted(outputs)]
                receipt['status'] = 'COMPLETE'
                manifests[repo_id]['artifacts'].extend(receipt['outputs'])
            except BaseException as exc:
                receipt.update(status='FAILED', error=repr(exc))
                receipt['outputs'] = [artifact(context, repo_id, p, 'failed_partial_output')
                    for p in sorted(context.output(repo_id, stage_id).rglob('*')) if p.is_file()]
                manifests[repo_id]['artifacts'].extend(receipt['outputs'])
                raise
            finally:
                receipt.update(finished_utc=r.utc(), elapsed_seconds=time.monotonic() - began)
                context.contracts.validate('stage_receipt', receipt)
                path = root / ('stage_receipts/' + stage_id + '.json')
                r.exclusive_json(path, receipt)
                manifests[repo_id]['stage_receipts'].append(str(path.relative_to(root)))
            progress.tick(stage_id)
    except BaseException as exc:
        error = exc
        raise
    finally:
        servers.stop()
        for repo_id, manifest in manifests.items():
            root = context.root(repo_id)
            manifest.update(finished_utc=r.utc(), execution_status='FAILED' if error else 'COMPLETE',
                            contract_status='INVALID' if error else 'VALID')
            context.contracts.validate('run_manifest', manifest)
            r.exclusive_json(root / 'run_manifest.json', manifest)
            r.exclusive_json(root / 'SEALED.json', dict(status=manifest['execution_status'],
                manifest_sha256=r.sha256_file(root / 'run_manifest.json'), finished_utc=manifest['finished_utc']))
    return manifests


def owner_main(runner, adapter_path, argv=None):
    parser = argparse.ArgumentParser(description='Version-locked experiment owner; fresh run IDs only.')
    parser.add_argument('action', choices=['plan', 'preflight', 'run', 'status'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--run-id', default='plan_only')
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'projects')
    parser.add_argument('--provider-cache', type=Path, default=Path.home() / '.cache/storygen/frozen-providers')
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text()) if args.config else {}
    context = Context(runner, config, args.run_id, args.workspace, args.provider_cache)
    adapter = load(adapter_path, 'owner_protocol_' + context.manifest['experiment_id'])
    if args.action == 'status':
        path = context.root(context.manifest['owner_repo']) / 'run_manifest.json'
        if not path.is_file():
            raise FileNotFoundError('No completed or failed run manifest: ' + str(path))
        result = json.loads(path.read_text())
    elif not config:
        if args.action != 'plan':
            parser.error('--config with exact input bindings is required')
        result = dict(status='BINDING_REQUIRED', experiment=context.manifest, required_configuration=adapter.REQUIRED_CONFIG)
    else:
        if config.get('purpose') not in {'RESEARCH', 'MIGRATION_VERIFICATION', 'SYNTHETIC_TEST'}:
            raise ValueError('Explicit run purpose required')
        context.resolve(materialize=args.action in {'preflight', 'run'})
        plan = validate_plan(context, adapter.plan(context))
        result = dict(status='PLAN_READY', run_id=context.run_id, stages=plan)
        if args.action == 'run':
            if args.run_id == 'plan_only':
                raise ValueError('--run-id must explicitly identify a fresh run')
            result = run(context, plan)
    print(json.dumps(result, indent=2))
    return 0
