"""Strict experiment discovery; one matching central primary per protocol."""

from pathlib import Path
import yaml
from storygen_experiment import ROOT
from storygen_experiment import contracts, runtime


def read(path):
    return yaml.safe_load(Path(path).read_text())


def discover(root=ROOT):
    root = Path(root).resolve()
    values = []
    ids = set()
    for path in sorted((root / "experiments").glob("*/*/experiment.yaml")):
        manifest = contracts.validate("experiment", read(path))
        key = manifest["experiment_id"]
        if key in ids:
            raise ValueError("Duplicate global central experiment ID")
        if path.parent != root / "experiments" / manifest["group_id"] / key:
            raise ValueError("Experiment directory identity mismatch")
        if (
            manifest["runner"] != key + ".py"
            or not (path.parent / manifest["runner"]).is_file()
        ):
            raise ValueError("Missing matching primary runner")
        definition = read(path.parent / "pipeline.yaml")
        contracts.experiment(manifest, definition)
        values.append(dict(manifest=manifest, pipeline=definition, home=path.parent))
        ids.add(key)
    return values


def get(key, root=ROOT):
    for value in discover(root):
        if value["manifest"]["experiment_id"] == key:
            return value
    raise ValueError("Unknown central experiment: " + key)


def locked(key, root=ROOT):
    value = get(key, root)
    p = value["home"] / "dependencies.lock.yaml"
    lock = read(p)
    contracts.dependency_lock(lock, value["manifest"], value["home"])
    runtime.check_environment(lock["environment"])
    return {**value, "lock": lock, "lock_path": p}


def catalog(root, depot):
    root = Path(root)
    lines = [
        "# Experiments",
        "",
        "Central protocols delegate or compose frozen scientific engines. Execution completion does not establish scientific validity.",
        "",
    ]
    for value in discover(root):
        m = value["manifest"]
        path = value["home"].relative_to(root)
        runs = []
        for p in (
            Path(depot) / "experiments" / m["group_id"] / m["experiment_id"] / "runs"
        ).glob("*/run_manifest.json"):
            v = read(p)
            seal = p.parent / "integrity/SEALED.json"
            if not seal.is_file() or read(seal)["manifest_sha256"] != runtime.sha(p):
                raise RuntimeError("Changed/unsealed catalog manifest")
            runs.append(v["purpose"] + ":" + v["execution_status"])
        counts = {key: runs.count(key) for key in sorted(set(runs))}
        label = ", ".join(str(n) + " " + s for s, n in counts.items()) or "none"
        native = m.get("historical_delegation")
        native_text = (
            " Native authority: `"
            + native["owner_repo"]
            + "/"
            + native["public_runner"]
            + "` at `"
            + native["source_commit"]
            + "`; historical locator: `"
            + str(
                root.parent
                / (native["owner_repo"] + "-depot")
                / Path(native["public_runner"]).parent
                / "runs"
            )
            + "` (read-only)."
            if native
            else ""
        )
        lines.append(
            f"- [{m['experiment_id']}]({path}/{m['runner']}) — {m['science']['question']} Pipeline: {' → '.join(s['stage_id'] for s in value['pipeline']['stages'])}. [Protocol]({path}/README.md) · [locks]({path}/dependencies.lock.yaml). Runs: {label}. Scientific validity: UNVERIFIED.{native_text}"
        )
    lines += [
        "",
        "Use `python tools/experiments.py list|show|plan|doctor|preflight|run|status|verify`. Create with `python tools/new_experiment.py --spec SPEC.json`. Raw run bytes are local and not backed up by metadata Git.",
        "",
    ]
    return "\n".join(lines)


def update_catalog(root, depot):
    import fcntl
    import os
    import tempfile

    root = Path(root)
    directory = Path(depot) / ".locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "catalog.lock").open("a+b") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        try:
            text = catalog(root, depot)
            fd, name = tempfile.mkstemp(prefix=".catalog-", dir=root)
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, root / "EXPERIMENTS.md")
            finally:
                if Path(name).exists():
                    Path(name).unlink()
        finally:
            fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
    return text
