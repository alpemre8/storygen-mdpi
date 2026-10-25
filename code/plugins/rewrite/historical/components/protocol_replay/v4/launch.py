"""Run a versioned scientific API with normal imports from exact frozen providers."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--backend-root', type=Path, required=True)
    parser.add_argument('--module', required=True)
    parser.add_argument('--action', required=True)
    parser.add_argument('--protocol-root', type=Path, required=True)
    parser.add_argument('--parent-config', type=Path, required=True)
    parser.add_argument('--producer-roots', type=Path, required=True)
    parser.add_argument('--receipt-dir', type=Path, required=True)
    parser.add_argument('--live-server-record', type=Path)
    parser.add_argument('--server-key')
    parser.add_argument('--server-mode')
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    manifest = json.loads((args.bundle / 'ORIGINS.json').read_text())
    import hashlib
    for relative, expected in manifest['files'].items():
        actual = 'sha256:' + hashlib.sha256((args.bundle / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError('Versioned protocol API changed: ' + relative)
    paths = [args.bundle, Path(__file__).parent,
             workspace / 'storygen-rewrite/rewrite/src', workspace / 'storygen-rewrite/taskset/src',
             workspace / 'storygen-feature-extraction/measurement/src',
             workspace / 'storygen-feature-extraction/feature_extraction/src',
             workspace / 'storygen-evaluation/evaluation/src']
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONHOME', 'PYTHONPATH'}}
    env.update(PYTHONPATH=os.pathsep.join(map(str, paths)), PYTHONDONTWRITEBYTECODE='1',
               STORYGEN_PROTOCOL_WORKSPACE=str(workspace), STORYGEN_PROTOCOL_BACKEND_ROOT=str(args.backend_root.resolve()))
    command = [sys.executable, '-m', 'storygen_protocol_science.driver', '--module', args.module,
               '--action', args.action, '--protocol-root', str(args.protocol_root),
               '--parent-config', str(args.parent_config), '--producer-roots', str(args.producer_roots),
               '--receipt-dir', str(args.receipt_dir)]
    for key in ['live_server_record', 'server_key', 'server_mode']:
        value = getattr(args, key)
        if value:
            command += ['--' + key.replace('_', '-'), str(value)]
    subprocess.run(command, env=env, check=True)


if __name__ == '__main__':
    main()
