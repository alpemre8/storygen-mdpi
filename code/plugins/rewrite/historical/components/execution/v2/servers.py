"""Owned local llama.cpp lifecycle; exact frozen profile and model bindings only."""
import json
import os
from pathlib import Path
import subprocess
import time

import httpx


class Servers:
    def __init__(self, context):
        self.context = context
        self.active = None
        self.identity = None

    def ensure(self, reference_name):
        c = self.context
        profile = json.loads(Path(c.input(reference_name)).read_text())
        identity = c.runtime.canonical_sha256(profile)
        if self.active is not None and identity == self.identity:
            if self.active.process.poll() is not None:
                raise RuntimeError('Owned persistent server exited unexpectedly')
            return
        self.stop()
        if profile['llama_cpp_commit'] != c.lock['runtime_profile']['backend_commit']:
            raise RuntimeError('Server profile backend commit mismatch')
        model = next((m for m in c.lock['models'] if Path(m['path']).resolve() == Path(profile['model_path']).resolve()), None)
        if not model or model['sha256'].removeprefix('sha256:') != profile['model_sha256'].removeprefix('sha256:'):
            raise RuntimeError('Server model identity is not in the experiment lock')
        if model['alias'] != profile['model_alias']:
            raise RuntimeError('Server model alias differs from lock')
        binary = Path(profile['server_binary'])
        version = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True)
        if profile['llama_cpp_commit'][:9] not in version.stdout + version.stderr:
            raise RuntimeError('Server binary build mismatch')
        legacy = c.runtime.load_module(c.repo / 'components/runtime/v1/legacy_technical.py', 'server_command_v1')
        command = legacy.server_command(profile)
        if str(profile['port']) != '8080' or profile['host'] != '127.0.0.1':
            raise RuntimeError('Frozen server command v1 requires localhost:8080; use a separate runtime version for another profile')
        env = {k: v for k, v in os.environ.items() if not k.startswith('LLAMA_ARG_')}
        env['LD_LIBRARY_PATH'] = str(binary.parent)
        log = c.root(c.manifest['owner_repo']) / ('logs/server_' + identity[-12:] + '.log')
        self.active = c.runtime.OwnedProcess(command, log, env=env, port=profile['port'])
        self.active.start(); self.identity = identity
        deadline = time.monotonic() + 120
        try:
            while time.monotonic() < deadline:
                if self.active.process.poll() is not None:
                    raise RuntimeError('Owned server failed to start; log: ' + str(log))
                try:
                    response = httpx.get(profile['base_url'].removesuffix('/v1') + '/health', timeout=1)
                    if response.status_code == 200:
                        props = httpx.get(profile['base_url'].removesuffix('/v1') + '/props', timeout=10).json()
                        if (props['model_alias'] != profile['model_alias'] or
                            Path(props['model_path']).resolve() != Path(profile['model_path']).resolve() or
                            props['total_slots'] != profile['parallel_slots'] or
                            props['default_generation_settings']['n_ctx'] != profile['context_per_slot']):
                            raise RuntimeError('Owned live server identity differs from frozen profile')
                        c.runtime.exclusive_json(c.root(c.manifest['owner_repo']) / ('inputs/live_server_' + identity[-12:] + '.json'),
                            dict(profile=profile, props=props, pid=self.active.process.pid, command=command))
                        return
                except (httpx.TransportError, json.JSONDecodeError):
                    pass
                time.sleep(0.25)
            raise TimeoutError('Owned server startup exceeded 120 seconds; exact profile remains unchanged')
        except BaseException:
            self.stop(); raise

    def stop(self):
        if self.active is not None:
            self.active.stop()
            self.active, self.identity = None, None
