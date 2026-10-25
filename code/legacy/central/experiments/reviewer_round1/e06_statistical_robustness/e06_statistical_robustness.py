"""Isolated source runtime with immutable owned/provider source verification."""

from pathlib import Path
import hashlib
import json
import os
import sys

HOME = Path(__file__).resolve().parent
REPO = HOME.parents[2]


def main():
    lock = json.loads((HOME / "dependencies.lock.yaml").read_text())
    for rel, digest in lock["owner_assets"].items():
        if "sha256:" + hashlib.sha256((HOME / rel).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Locked E06 source changed: " + rel)
    providers = json.loads((HOME / "provider_sources.json").read_text())
    for rel, digest in providers["files"].items():
        if (
            "sha256:" + hashlib.sha256((REPO.parent / rel).read_bytes()).hexdigest()
            != digest
        ):
            raise RuntimeError("Canonical evaluation source changed: " + rel)
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(
        PYTHONPATH=str(REPO.parent / "storygen-evaluation/evaluation/src"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    os.execve(
        sys.executable, [sys.executable, str(HOME / "src/cli.py"), *sys.argv[1:]], env
    )


if __name__ == "__main__":
    main()
