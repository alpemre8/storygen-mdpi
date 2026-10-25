"""Maintain only E05 feature diff owned locks using central hash and contract APIs.

Run after deliberate owned source/protocol edits, before committing. Never alters
historical providers. Existing creation receipt is preserved; refresh is recorded
in an implementation lock receipt. This does not qualify scientific results.
"""

from pathlib import Path
import json
import os
import sys

if __name__ == "__main__" and os.environ.get("E05FD_LOCK_ENV") != "1":
    home = Path(__file__).resolve().parent
    repo = home.parents[2]
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(
        PYTHONPATH=str(repo / "src"), PYTHONDONTWRITEBYTECODE="1", E05FD_LOCK_ENV="1"
    )
    os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve())], env)

from storygen_experiment import runtime, contracts

if __name__ == "__main__":
    home = Path(__file__).resolve().parent
    lock = json.loads((home / "dependencies.lock.yaml").read_text())
    assets = {
        str(p.relative_to(home)): runtime.sha(p)
        for p in home.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and (
            p.suffix in (".py", ".md")
            or str(p.relative_to(home)).startswith("src/")
            or p.name
            in (
                "experiment.yaml",
                "pipeline.yaml",
                "run.example.json",
                "e05-feature-diff",
            )
        )
    }
    lock["owner_assets"] = dict(sorted(assets.items()))
    contracts.validate("dependency_lock", lock)
    runtime.atomic_json(home / "dependencies.lock.yaml", lock)
    runtime.atomic_json(
        home / "implementation_lock_receipt.json",
        dict(
            experiment_id=home.name,
            protocol_id="E05_4_FEATURE_DIFF_V1",
            source_assets=lock["owner_assets"],
            mechanism="Central runtime.sha / runtime.atomic_json / contracts.validate; creator receipt preserved",
        ),
    )
    print(json.dumps(dict(owned_assets=len(assets), status="LOCKED")))
