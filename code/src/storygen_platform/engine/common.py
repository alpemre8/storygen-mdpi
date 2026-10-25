from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import tempfile


class StoryGenError(ValueError):
    """An actionable protocol, integrity or configuration error."""


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise StoryGenError(f"Invalid stable identifier: {value!r}")
    return value


def contained(root, relative):
    root = Path(root).resolve()
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise StoryGenError(f"Storage-relative path required: {relative}")
    target = root / p
    if not target.resolve().is_relative_to(root):
        raise StoryGenError(f"Path escapes storage root: {relative}")
    return target


def read(path):
    import yaml

    payload = Path(path).read_text()
    try:
        # Native scientific artifacts are JSON. JSON permits literal C1 text
        # characters that YAML rejects; preserve the exact screenplay string.
        return json.loads(payload)
    except json.JSONDecodeError:
        return yaml.safe_load(payload)


def sync_directory(path):
    descriptor = os.open(Path(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory(path):
    path = Path(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in missing:
        sync_directory(created.parent)
    return path


def durable_write(path, payload, *, exclusive=True):
    path = Path(path)
    ensure_directory(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(tmp, path)
        else:
            os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def write_json(path, value, **kwargs):
    durable_write(path, canonical(value) + b"\n", **kwargs)


def tree_hash(root, suffixes=None):
    root = Path(root)
    values = {}
    for p in sorted(root.rglob("*")):
        if any(x in {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"} for x in p.parts):
            continue
        if p.is_symlink():
            raise StoryGenError(f"Symlink not allowed in pinned source: {p}")
        if p.is_file() and (suffixes is None or p.suffix in suffixes):
            values[p.relative_to(root).as_posix()] = file_sha(p)
    return digest(values)
