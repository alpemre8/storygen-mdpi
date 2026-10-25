"""Strict protected-file verification with explicit immutable Git source locators."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def verified_source(path, expected, policy):
    """Only explicitly listed source roots/commits qualify; data files never do."""
    path = Path(path)
    for repo_id, row in policy.items():
        root = Path(row['root'])
        if not path.is_relative_to(root):
            continue
        relative = str(path.relative_to(root))
        for commit in row['commits']:
            result = subprocess.run(['git', '-C', str(root), 'show', commit + ':' + relative], capture_output=True)
            if result.returncode == 0 and digest(result.stdout) == expected:
                return dict(recorded_path=str(path), source_repo=repo_id, commit=commit,
                            repository_relative_path=relative, sha256=expected)
        raise RuntimeError('No declared immutable source revision has the protected SHA: ' + str(path))
    raise RuntimeError('Frozen/protected artifact changed: ' + str(path))


def verify_files(protected):
    policy_path = Path(__file__).with_name('SOURCE_BINDINGS.json')
    policy = json.loads(policy_path.read_text())
    resolved = []
    for path, expected in protected.items():
        if Path(path).is_file() and file_digest(path) == expected:
            continue
        resolved.append(verified_source(path, expected, policy))
    evidence = os.environ.get('STORYGEN_SOURCE_LOCATOR_RECEIPT')
    if resolved and evidence:
        path = Path(evidence)
        prior = json.loads(path.read_text()) if path.is_file() else []
        known = {(r['recorded_path'], r['sha256']) for r in prior}
        prior += [r for r in resolved if (r['recorded_path'], r['sha256']) not in known]
        # This is operational locator evidence, never a scientific score or frozen input.
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(prior, indent=2) + '\n')
        os.replace(temporary, path)
    return resolved
