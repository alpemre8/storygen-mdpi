"""Versioned technical IO, identity, progress and owned-process services v1.0."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return 'sha256:' + h.hexdigest()


def canonical_sha256(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                               ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def exclusive_json(path, value):
    """Publish complete bytes atomically; an existing destination is never replaced."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.publish-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json_bytes(value)); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink()
    return path


def checked_json(reference):
    path = Path(reference['path'])
    if sha256_file(path) != reference['sha256']:
        raise RuntimeError('Frozen SHA mismatch: ' + str(path))
    return json.loads(path.read_text())


def relative_path(value):
    path = Path(value)
    if not value or path.is_absolute() or '..' in path.parts or '\\' in str(value) or str(value) == '.':
        raise ValueError('Unsafe relative path: ' + str(value))
    return path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', value) or value in ('.', '..'):
        raise ValueError('Unsafe identifier: ' + str(value))
    return value


def contained(root, relative):
    root = Path(root).resolve()
    rel = relative_path(relative)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlink write path refused: ' + str(current))
    result = (root / rel).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Path escapes owned root')
    return result


def content_digest(root, paths):
    """Content identity of exact source trees; only interpreter/test caches excluded."""
    root = Path(root).resolve()
    result = {}
    for value in paths:
        item = contained(root, value)
        if not item.exists():
            raise FileNotFoundError(item)
        candidates = [item] if item.is_file() else sorted(item.rglob('*'))
        for path in candidates:
            if path.is_symlink():
                raise ValueError('Source lock cannot include a symlink: ' + str(path))
            if not path.is_file():
                continue
            if any(part in {'__pycache__', '.pytest_cache', '.git'} for part in path.relative_to(root).parts) or path.suffix == '.pyc':
                continue
            result[str(path.relative_to(root))] = sha256_file(path)
    if not result:
        raise ValueError('Empty component source identity')
    return canonical_sha256(result)


def load_module(path, name, expected_sha256=None):
    path = Path(path)
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise RuntimeError('Technical component SHA mismatch: ' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hms(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


class Progress:
    def __init__(self, total, *, clock=time.monotonic, emit=print):
        if total < 0:
            raise ValueError('Negative progress total')
        self.total, self.clock, self.emit = total, clock, emit
        self.start, self.completed = clock(), 0

    def tick(self, stage):
        if self.completed >= self.total:
            raise ValueError('Progress exceeded planned stage count')
        self.completed += 1
        elapsed = self.clock() - self.start
        eta = elapsed * (self.total - self.completed) / self.completed
        record = dict(stage=stage, completed=self.completed, total=self.total,
                      elapsed=hms(elapsed), eta=hms(eta))
        self.emit(json.dumps(record), flush=True)
        return record


def assert_port_available(port, host='127.0.0.1'):
    with socket.socket() as sock:
        sock.bind((host, port))


class OwnedProcess:
    """Only this object's own Popen child can be stopped; never a foreign PID."""
    def __init__(self, command, log_path, *, cwd=None, env=None, port=None):
        self.command, self.log_path = list(command), Path(log_path)
        self.cwd, self.env, self.port = cwd, env, port
        self.process = None
        self.log = None

    def start(self):
        if self.process is not None:
            raise RuntimeError('Process already started')
        if self.port is not None:
            assert_port_available(self.port)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open('xb')
        try:
            self.process = subprocess.Popen(self.command, stdout=self.log, stderr=subprocess.STDOUT,
                                            cwd=self.cwd, env=self.env)
        except BaseException:
            self.log.close(); raise
        return self.process

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=15)
        self.log.close()

    def __enter__(self):
        self.start(); return self

    def __exit__(self, *_):
        self.stop()
