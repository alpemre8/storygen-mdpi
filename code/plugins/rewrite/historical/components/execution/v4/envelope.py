"""Locked execution v4: frozen DAGs, explicit artifact edges, failure retention and doctor."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import yaml

# Versioned technical dependency, never a historical experiment's private module.
import importlib.util

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value

ROOT = Path(__file__).resolve().parents[3]
base = load(ROOT / 'components/execution/v3/envelope.py', 'execution_v3_dependency')
a = load(ROOT / 'components/artifacts/v2/registry.py', 'execution_artifacts_v2')


class Context(base.Context):
    def depot(self, repo_id):
        path = Path(self.config.get('depot_roots', {}).get(repo_id, self.workspace / (repo_id + '-depot'))).expanduser().resolve()
        if json.loads((path / 'DEPOT_MANIFEST.json').read_text()).get('depot_id') != repo_id + '-depot':
            raise ValueError('Depot identity mismatch: ' + str(path))
        return path

    def root(self, repo_id):
        if repo_id not in a.REPOS: raise ValueError('Unknown source provider')
        owner = self.manifest['owner_repo']
        canonical = self.runtime.contained(self.depot(owner), f"experiments/{self.manifest['group_id']}/{self.manifest['experiment_id']}/runs/{self.run_id}")
        return canonical if repo_id == owner else self.runtime.contained(canonical, 'providers/' + repo_id)

    def resolve(self, *, materialize=False):
        result = super().resolve(materialize=materialize)
        for repo, source in result.items():
            extra = subprocess.check_output(['git', '-C', str(source), 'ls-files', '--others', '-z']).decode().split('\0')
            forbidden = [name for name in extra if name and not any(part in {'__pycache__', '.pytest_cache'} for part in Path(name).parts) and not name.endswith('.pyc')]
            if forbidden:
                raise RuntimeError('Untracked provider content could shadow frozen code: ' + repo + ': ' + repr(forbidden[:5]))
        for item in self.lock['runtime_profile'].get('backend_files', []):
            path = Path(item['path']).expanduser().resolve()
            if self.runtime.sha256_file(path) != item['sha256']:
                raise RuntimeError('Backend executable/library SHA mismatch: ' + str(path))
        for ref in self.config.get('artifact_inputs', []):
            a.resolve(ref, depot_bindings(self), require_sealed=True)
        return result


def depot_bindings(c):
    return {repo + '-depot': c.depot(repo) for repo in a.REPOS}


def validate_plan(c, plan):
    base.validate_plan(c, plan)
    for stage in plan:
        for arg in stage['command']:
            if '\x00' in arg:
                raise ValueError('NUL in executable argv')
    return plan


def process_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        raw = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, start_ticks=raw[19], boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    except (FileNotFoundError, ProcessLookupError):
        return None


def exclusive_bytes(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.publish-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.link(name, path)
    finally:
        Path(name).unlink()


def frozen_plan(c, plan):
    previous = {}
    dependencies = {s['stage_id']: s['depends_on'] for s in c.manifest['stages']}
    jobs = []
    for stage in plan:
        binding = dict(stage=stage, upstream_jobs=[previous[key] for key in dependencies[stage['stage_id']]],
                       lock_sha256=c.runtime.sha256_file(c.lock_path), configuration_sha256=c.runtime.canonical_sha256(c.config))
        job = dict(**binding, job_id=c.runtime.canonical_sha256(binding))
        jobs.append(job); previous[stage['stage_id']] = job['job_id']
    return dict(version='storygen.execution-plan/1.0', run_id=c.run_id, owner_repo=c.manifest['owner_repo'],
                experiment_id=c.manifest['experiment_id'], jobs=jobs)


def run(c, plan):
    plan = validate_plan(c, plan); r = c.runtime
    owner = c.manifest['owner_repo']; root = c.root(owner)
    providers = sorted({s['provider_repo'] for s in plan} | {owner})
    depots = depot_bindings(c)
    if root.exists(): raise FileExistsError('Run ID already reserved; retain it and use a fresh successor: ' + str(root))
    graph = frozen_plan(c, plan); outputs = {}; error = None
    store = a.RunStore(c.depot(owner), owner_repo=owner, group=c.manifest['group_id'], experiment=c.manifest['experiment_id'],
        protocol=c.manifest['protocol_id'], run_id=c.run_id, purpose=c.config['purpose'], lock_sha256=r.sha256_file(c.lock_path),
        parent_run_ids=c.config.get('parent_run_ids', [])).create(c.config)
    exclusive_bytes(store.writable('inputs/dependencies.lock.yaml'), c.lock_path.read_bytes())
    for repo in providers:
        if repo != owner:
            for name in ['raw', 'tables', 'reports']:
                r.contained(root, str(c.root(repo).relative_to(root) / name)).mkdir(parents=True, exist_ok=False)
    store.write_json('inputs/producer_roots.json', {repo: str(c.root(repo)) for repo in providers})
    store.write_json('inputs/execution_plan.json', graph)
    store.write_json('inputs/owner_process.json', process_identity())
    store.write_json('inputs/environment.json', dict(python=sys.version, executable=str(Path(sys.executable).resolve()),
        locked_environment=c.lock['environment'], backend_files=c.lock['runtime_profile'].get('backend_files', []),
        source_providers={k: str(v) for k, v in c.providers.items()}))
    owner_files = [c.runner, c.home / 'experiment.yaml', c.home / 'src/protocol.py']
    for folder in ['components/execution/v3', 'components/execution/v4', 'components/artifacts/v1', 'components/artifacts/v2', 'components/runtime/v1']:
        owner_files += list((c.repo / folder).glob('*.py'))
    owner_files += [c.repo / 'contracts/v1/validate.py']
    store.write_json('inputs/owner_code.json', dict(source_commit=subprocess.check_output(['git', '-C', str(c.repo), 'rev-parse', 'HEAD'], text=True).strip(),
        files={str(path.relative_to(c.repo)): r.sha256_file(path) for path in owner_files}))
    known_inputs = {v['locator']['relative_path'] for v in store.manifest['exact_input_bindings']}
    for path in sorted((root / 'inputs').iterdir()):
        if path.is_file() and str(path.relative_to(store.depot)) not in known_inputs:
            store.manifest['exact_input_bindings'].append(store.reference(path, 'exact_execution_input', 'storygen.file/1.0'))
    store.manifest['exact_input_bindings'].extend(c.config.get('artifact_inputs', []))
    progress = r.Progress(len(plan))
    servers = load(c.repo / 'components/execution/v4/servers.py', 'owned_servers_v4').Servers(c)
    dependencies = {s['stage_id']: s['depends_on'] for s in c.manifest['stages']}
    try:
        for stage, job in zip(plan, graph['jobs'], strict=True):
            repo, key = stage['provider_repo'], stage['stage_id']
            upstream = [ref for dep in dependencies[key] for ref in outputs[dep]]
            bound = dict(job_id=job['job_id'], exact_configuration_sha256=r.canonical_sha256(c.config), upstream_artifacts=upstream)
            input_path = store.write_json('inputs/stages/' + key + '.json', bound)
            store.manifest['exact_input_bindings'].append(store.reference(input_path, 'stage_input_binding', 'storygen.stage-inputs/1.0'))
            began = time.monotonic()
            receipt = dict(schema_version='1.0', run_id=c.run_id, experiment_id=c.manifest['experiment_id'],
                stage_id=key, provider_repo=repo, status='RUNNING', started_utc=r.utc(), finished_utc=None,
                input_sha256=r.canonical_sha256(bound), outputs=[], command=stage['command'], elapsed_seconds=0, error=None)
            store.write_json('stage_receipts/' + key + '_started.json', receipt)
            try:
                for name in c.config.get('inputs', {}): c.input(name)
                for ref in upstream:
                    a.resolve(ref, depots)
                    if ref not in store.manifest['exact_input_bindings']: store.manifest['exact_input_bindings'].append(ref)
                if stage.get('server_profile') and c.config.get('manage_servers', False): servers.ensure(stage['server_profile'])
                env = {k: v for k, v in os.environ.items() if not k.startswith('STORYGEN_') and k not in {'PYTHONPATH', 'PYTHONHOME'}}
                env['PYTHONDONTWRITEBYTECODE'] = '1'
                # Original path guards accept explicit per-process roots. All redirects stay below the sole owner run.
                for provider in providers:
                    env[{'storygen-rewrite': 'STORYGEN_REWRITE_DEPOT_ROOT', 'storygen-feature-extraction': 'STORYGEN_FEATURE_DEPOT_ROOT', 'storygen-evaluation': 'STORYGEN_EVALUATION_DEPOT_ROOT', 'storygen-naturalness': 'STORYGEN_NATURALNESS_DEPOT_ROOT'}[provider]] = str(c.root(provider))
                with store.writable('logs/' + key + '.log').open('xb') as log:
                    subprocess.run(stage['command'], cwd=c.source(repo), env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
                files = sorted(p for p in c.output(repo, key).rglob('*') if p.is_file())
                if not files: raise RuntimeError('Stage produced no output artifacts: ' + key)
                receipt['outputs'] = [store.register(str(p.relative_to(root)), role=key, schema_id='storygen.file/1.0', producer_repo=repo) for p in files]
                receipt['status'] = 'COMPLETE'; outputs[key] = receipt['outputs']
            except BaseException as exc:
                receipt.update(status='FAILED', error=repr(exc))
                known = {v['locator']['relative_path'] for v in store.manifest['artifacts']}
                for path in sorted(c.output(repo, key).rglob('*')):
                    if path.is_file() and str(path.relative_to(store.depot)) not in known:
                        receipt['outputs'].append(store.register(str(path.relative_to(root)), role='failed_partial_output', schema_id='storygen.file/1.0', producer_repo=repo))
                raise
            finally:
                receipt.update(finished_utc=r.utc(), elapsed_seconds=time.monotonic() - began)
                c.contracts.validate('stage_receipt', receipt)
                path = store.write_json('stage_receipts/' + key + '.json', receipt)
                store.manifest['stage_receipts'].append(str(path.relative_to(root)))
            progress.tick(key)
    except BaseException as exc:
        error = exc
        raise
    finally:
        try: servers.stop()
        except BaseException as stop_error: error = error or stop_error
        known = {v['locator']['relative_path'] for v in store.manifest['artifacts']}
        for folder in ['raw', 'providers', 'tables', 'reports', 'stage_receipts']:
            for path in sorted((root / folder).rglob('*')):
                if path.is_file() and str(path.relative_to(store.depot)) not in known:
                    parts = path.relative_to(root).parts
                    producer = parts[1] if parts[0] == 'providers' else owner
                    store.register(str(path.relative_to(root)), role='run_output_or_receipt', schema_id='storygen.file/1.0', producer_repo=producer)
                    known.add(str(path.relative_to(store.depot)))
        known_inputs = {v['locator']['relative_path'] for v in store.manifest['exact_input_bindings']}
        for path in sorted((root / 'inputs').rglob('*')):
            if path.is_file() and str(path.relative_to(store.depot)) not in known_inputs:
                store.manifest['exact_input_bindings'].append(store.reference(path, 'execution_input_or_runtime_record', 'storygen.file/1.0'))
        integrity_errors = []
        for ref in store.manifest['exact_input_bindings'] + store.manifest['artifacts']:
            try: a.resolve(ref, depots)
            except Exception as integrity_error: integrity_errors.append(repr(integrity_error))
        if integrity_errors:
            error = error or RuntimeError('Artifact integrity failure before seal')
            path = store.write_json('reports/INTEGRITY_FAILURE.json', dict(status='FAILED', errors=integrity_errors))
            store.register(str(path.relative_to(root)), role='integrity_failure', schema_id='storygen.integrity-failure/1.0')
        store.manifest.update(finished_utc=r.utc(), execution_status='FAILED' if error else 'COMPLETE', contract_status='INVALID' if error else 'VALID')
        c.contracts.validate('run_manifest', store.manifest)
        r.exclusive_json(root / 'run_manifest.json', store.manifest)
        r.exclusive_json(root / 'SEALED.json', dict(status=store.manifest['execution_status'], manifest_sha256=r.sha256_file(root / 'run_manifest.json'), finished_utc=store.manifest['finished_utc']))
        if error and sys.exc_info()[0] is None: raise error
    return {owner: store.manifest}


def status(c):
    root = c.root(c.manifest['owner_repo']); manifest = root / 'run_manifest.json'
    if manifest.is_file():
        seal = root / 'SEALED.json'
        if not seal.is_file() or json.loads(seal.read_text())['manifest_sha256'] != c.runtime.sha256_file(manifest):
            raise RuntimeError('Terminal manifest is unsealed or changed')
        value = c.contracts.validate('run_manifest', json.loads(manifest.read_text()))
        for ref in value['artifacts'] + value['exact_input_bindings']:
            a.resolve(ref, depot_bindings(c), require_sealed=True)
        return dict(status='PASS' if value['execution_status'] == 'COMPLETE' else 'FAILED', run_manifest=value)
    if not (root / 'RUN_STARTED.json').exists(): return dict(status='NOT_RUN', run_id=c.run_id)
    process_path = root / 'inputs/owner_process.json'
    saved = json.loads(process_path.read_text()) if process_path.is_file() else None
    alive = saved and process_identity(saved['pid']) == saved
    return dict(status='RUNNING' if alive else 'HUMAN_OR_RUNTIME_BLOCKED', run_id=c.run_id,
                detail='Owner process is live' if alive else 'Interrupted incomplete run retained; use fresh run ID and parent_run_ids')


def doctor(c, plan):
    for repo in {s['provider_repo'] for s in plan} | {c.manifest['owner_repo']}:
        root = c.root(repo)
        if root.exists(): raise FileExistsError('Run ID already exists: ' + str(root))
        parent = root.parent
        while not parent.exists(): parent = parent.parent
        if not os.access(parent, os.W_OK): raise PermissionError('Output root is not writable: ' + str(parent))
    ports = set()
    if c.config.get('manage_servers', False):
        for stage in plan:
            if not stage.get('server_profile'): continue
            profile = json.loads(Path(c.input(stage['server_profile'])).read_text())
            if c.runtime.canonical_sha256(profile) not in c.lock['scientific_invariants'].get('allowed_server_profile_sha256', []):
                raise RuntimeError('Server profile is not locked')
            if profile['total_context_size'] != profile['parallel_slots'] * profile['context_per_slot']:
                raise RuntimeError('Profile context/slots budget mismatch')
            ports.add((profile['host'], profile['port']))
        for host, port in ports: c.runtime.assert_port_available(port, host)
    return dict(status='PLAN_READY', run_id=c.run_id, stages=plan, frozen_plan=frozen_plan(c, plan),
                checks=['source commits and trees', 'component and input hashes', 'environment closure', 'selected model SHA', 'backend binary/library SHA', 'profile/port/context', 'fresh writable output roots'])


def owner_main(runner, adapter_path, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'doctor', 'preflight', 'run', 'status'])
    parser.add_argument('--config', type=Path); parser.add_argument('--run-id', default='plan_only')
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'projects')
    parser.add_argument('--provider-cache', type=Path, default=Path.home() / '.cache/storygen/frozen-providers')
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text()) if args.config else {}
    c = Context(runner, config, args.run_id, args.workspace, args.provider_cache)
    adapter = load(adapter_path, 'owner_protocol_' + c.manifest['experiment_id'])
    try:
        if args.action == 'status': result = status(c)
        elif not config:
            result = dict(status='HUMAN_OR_RUNTIME_BLOCKED', detail='Exact input bindings required', experiment=c.manifest, required_configuration=adapter.REQUIRED_CONFIG)
            if args.action not in {'plan', 'doctor'}: parser.error('--config required')
        else:
            if config.get('purpose') not in {'RESEARCH', 'MIGRATION_VERIFICATION', 'SYNTHETIC_TEST'}: raise ValueError('Explicit run purpose required')
            c.resolve(materialize=args.action != 'plan')
            plan = validate_plan(c, adapter.plan(c))
            result = doctor(c, plan)
            if args.action == 'run':
                if args.run_id == 'plan_only': raise ValueError('Explicit fresh --run-id required')
                result = run(c, plan)
    except Exception as exc:
        print(json.dumps(dict(status='FAILED' if args.action == 'run' else 'HUMAN_OR_RUNTIME_BLOCKED', error=repr(exc)), indent=2))
        return 1
    print(json.dumps(result, indent=2)); return 0
