"""Technical ownership/runtime helpers; no scientific computation."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
import subprocess
import tempfile
from storygen_experiment.contracts import contained as contained
from storygen_experiment.contracts import relative as relative
from storygen_experiment.contracts import identifier as identifier


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def encode(value):
    return (
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()


def exclusive(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path)
    finally:
        Path(tmp).unlink()


def exclusive_json(path, value):
    exclusive(path, encode(value))
    return Path(path)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def identity(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        return dict(
            pid=pid,
            start_ticks=Path(f"/proc/{pid}/stat")
            .read_text()
            .rsplit(")", 1)[1]
            .split()[19],
            boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        )
    except (FileNotFoundError, ProcessLookupError):
        return None


def clean_env():
    return {
        **{
            k: v
            for k, v in os.environ.items()
            if k not in {"PYTHONHOME", "PYTHONPATH"} and not k.startswith("STORYGEN_")
        },
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def environment_lock(packages):
    import sys

    value = dict(
        python=sys.version.split()[0],
        packages={p: importlib.metadata.version(p) for p in sorted(packages)},
    )
    return {**value, "sha256": canonical(value)}


def check_environment(lock):
    import sys

    if sys.version.split()[0] != lock["python"]:
        raise RuntimeError("Python version drift")
    for package, version in lock["packages"].items():
        if importlib.metadata.version(package) != version:
            raise RuntimeError("Package version drift: " + package)
    if canonical({k: lock[k] for k in ["python", "packages"]}) != lock["sha256"]:
        raise RuntimeError("Environment digest drift")


def source_tree(root):
    names = (
        subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
        .decode()
        .split("\0")
    )
    return canonical({name: sha(Path(root) / name) for name in names if name})


def pin_provider(reference, workspace, cache):
    import fcntl

    directory = Path(cache) / reference["repo_id"]
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (reference["commit"] + ".lock")).open("a+b") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        try:
            return _pin_provider(reference, workspace, cache)
        finally:
            fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


def _pin_provider(reference, workspace, cache):
    repo = reference["repo_id"]
    commit = reference["commit"]
    root = Path(workspace) / repo
    target = Path(cache) / repo / commit
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "worktree",
                "add",
                "--detach",
                str(target),
                commit,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    if (
        git(target, "rev-parse", "HEAD") != commit
        or source_tree(target) != reference["tree_sha256"]
    ):
        raise RuntimeError("Pinned provider source drift: " + repo)
    extra = (
        subprocess.check_output(
            ["git", "-C", str(target), "ls-files", "--others", "-z"]
        )
        .decode()
        .split("\0")
    )
    if [
        p
        for p in extra
        if p
        and not any(v in {"__pycache__", ".pytest_cache"} for v in Path(p).parts)
        and not p.endswith(".pyc")
    ]:
        raise RuntimeError("Untracked provider shadowing")
    for component in reference["components"]:
        if content_digest(target, component["paths"]) != component["sha256"]:
            raise RuntimeError(
                "Frozen component content drift: " + component["component_id"]
            )
    installed = dict(
        root=str(root.resolve()),
        head=git(root, "rev-parse", "HEAD"),
        dirty=git(root, "status", "--porcelain"),
    )
    return target, dict(
        repo_id=repo,
        commit=commit,
        tree_sha256=reference["tree_sha256"],
        execution_root=str(target),
        current_checkout=installed,
        selection="PINNED_COMMITTED_PROVIDER",
    )


def content_digest(root, paths):
    root = Path(root).resolve()
    values = {}
    for rel in paths:
        path = contained(root, rel)
        if not path.exists():
            raise FileNotFoundError(path)
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        for item in candidates:
            if item.is_symlink():
                raise ValueError("Source component includes a symlink")
            if (
                not item.is_file()
                or any(
                    v in {"__pycache__", ".pytest_cache", ".git"}
                    for v in item.relative_to(root).parts
                )
                or item.suffix == ".pyc"
            ):
                continue
            values[str(item.relative_to(root))] = sha(item)
    if not values:
        raise ValueError("Empty component identity")
    return canonical(values)


def committed_tree(root, commit):
    entries = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "-rz", "--full-tree", commit]
    ).split(b"\0")
    values = {}
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        for entry in entries:
            if not entry:
                continue
            meta, name = entry.split(b"\t", 1)
            mode, kind, oid = meta.split()
            if kind != b"blob":
                raise ValueError(
                    "Submodule identity needs explicit independent binding"
                )
            process.stdin.write(oid + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            size = int(header[2])
            payload = process.stdout.read(size)
            assert process.stdout.read(1) == b"\n"
            values[name.decode()] = "sha256:" + hashlib.sha256(payload).hexdigest()
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait(timeout=10)
    return canonical(values)


def run_command(context, stage, command, cwd, env):
    import signal
    import time

    root = context["root"]
    key = stage["stage_id"]
    log = root / "logs" / (key + ".log")
    if not isinstance(command, list) or any(
        not isinstance(x, str) or "\x00" in x for x in command
    ):
        raise ValueError("Structured executable argv required")
    runtime_identity = dict(
        command=command,
        cwd=str(cwd),
        environment_provider_path=env.get("PYTHONPATH"),
        started_utc=utc(),
    )
    exclusive_json(root / "stages" / key / "parsed/command.json", runtime_identity)
    with log.open("xb") as stream:
        from storygen_experiment import ROOT
        import sys

        child_env = {
            **env,
            "STORYGEN_EXECUTION_PYTHONPATH": env.get("PYTHONPATH", ""),
            "PYTHONPATH": str(ROOT / "src"),
        }
        temp = root / "inputs/tmp"
        temp.mkdir(exist_ok=True)
        cache = root / "inputs/runtime_cache"
        cache.mkdir(exist_ok=True)
        child_env.update(
            TMPDIR=str(temp), XDG_CACHE_HOME=str(cache), PYTHONDONTWRITEBYTECODE="1"
        )
        wrapped = [
            sys.executable,
            "-m",
            "storygen_experiment.runtime.child",
            "--root",
            str(root),
            "--",
            *command,
        ]
        process = subprocess.Popen(
            wrapped,
            cwd=cwd,
            env=child_env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        exclusive_json(
            root / "stages" / key / "parsed/process.json",
            dict(identity=identity(process.pid), owned_process_group=process.pid),
        )
        try:
            while process.poll() is None:
                progress = context.get("progress_tracker")
                if progress:
                    progress.update(key)
                time.sleep(0.5)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=15)
            raise
    return dict(
        returncode=process.returncode,
        command_sha256=canonical(command),
        log=str(log.relative_to(root)),
    )
