"""Scientific definitions, independent implementation approvals, and immutable snapshots."""

from pathlib import Path
import importlib.metadata
import platform
import subprocess
from .common import (
    StoryGenError,
    contained,
    digest,
    file_sha,
    read,
    tree_hash,
    utc,
    write_json,
    durable_write,
)


def implementation(root, registry, pipeline):
    root = Path(root)
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except subprocess.CalledProcessError:
        commit = "UNCOMMITTED"
    return {
        "engine_sha256": tree_hash(root / "src/storygen_platform", {".py"}),
        "engine_commit": commit,
        "providers": registry.pins(pipeline),
        "python": platform.python_version(),
        "dependencies": {
            n: importlib.metadata.version(n) for n in ["PyYAML", "jsonschema", "httpx"]
        },
    }


def validate_definition(definition):
    if definition.get("schema_version") != "storygen.experiment/1":
        raise StoryGenError("Unsupported experiment schema version")
    from .common import identifier

    identifier(definition["experiment_id"])
    for key in [
        "display_name",
        "description",
        "purpose",
        "population",
        "model_roles",
        "conditions",
        "gates",
        "retries",
        "instruments",
        "planned_analyses",
        "readiness",
    ]:
        if key not in definition:
            raise StoryGenError(f"Experiment missing {key}")
    if not isinstance(definition["gates"], list) or not definition["gates"]:
        raise StoryGenError("Explicit scientific gates are required")
    gate_names = [identifier(gate.get("name")) for gate in definition["gates"]]
    if len(set(gate_names)) != len(gate_names):
        raise StoryGenError("Scientific gate names must be unique")
    for gate in definition["gates"]:
        if type(gate.get("value")) not in {int, float}:
            raise StoryGenError("Scientific gate thresholds must be explicit numbers, not booleans")
        if gate["predicate"] not in {"coverage", "min_valid", "max_errors"}:
            raise StoryGenError(f"Undefined scientific gate: {gate}")
        if gate["predicate"] == "coverage" and not 0 <= gate["value"] <= 1:
            raise StoryGenError("Invalid coverage gate")
        if gate["predicate"] != "coverage" and (
            not isinstance(gate["value"], int) or gate["value"] < 0
        ):
            raise StoryGenError("Invalid integer gate threshold")
    retries = definition["retries"]
    for key in ["transport", "scientific"]:
        if not isinstance(retries.get(key), int) or retries[key] < 0 or retries[key] > 100:
            raise StoryGenError(f"Frozen {key} retry limit required")
    if retries["scientific"] and not retries.get("repair_instrument"):
        raise StoryGenError("Scientific retries require an exact frozen repair instrument")
    if retries["scientific"]:
        reference = retries["repair_instrument"]
        matches = [
            item
            for item in definition["instruments"]
            if reference in {item["path"], item.get("instrument_id")}
        ]
        if len(matches) != 1 or not matches[0].get("snapshot", True):
            raise StoryGenError("Scientific retries require a unique snapshotted repair instrument")
    for role, spec in definition["model_roles"].items():
        if spec["policy"] not in {"FIXED", "VARIABLE"} or not spec["allowed"]:
            raise StoryGenError(f"Invalid role policy {role}")
        if spec["policy"] == "FIXED" and len(spec["allowed"]) != 1:
            raise StoryGenError(f"FIXED role must have one identity: {role}")
    return definition


def resolve_conditions(definition, profile):
    result = {}
    for role, spec in definition["model_roles"].items():
        if role not in profile.get("roles", {}):
            raise StoryGenError(
                f"Missing runtime model role {role}; configure profile.roles.{role}"
            )
        actual = profile["roles"][role]
        scientific = {k: actual.get(k) for k in ["model_id", "sha256", "quantization"]}
        if scientific not in spec["allowed"]:
            raise StoryGenError(f"Forbidden model/weight/quantization replacement for {role}")
        planned = spec.get("planned_model_ids")
        result[role] = {"model": scientific, "parameters": {}}
        if planned is not None:
            if not isinstance(planned, list) or not set(planned) <= {
                v["model_id"] for v in spec["allowed"]
            }:
                raise StoryGenError(
                    "Planned model IDs must be an explicit subset of allowed model identities"
                )
            result[role]["comparison_origin"] = (
                "PREPLANNED" if scientific["model_id"] in planned else "EXPLORATORY"
            )

        for name, condition in definition["conditions"].get(role, {}).items():
            value = actual.get("parameters", {}).get(name, condition.get("value"))
            if condition["policy"] == "FIXED":
                if value != condition["value"]:
                    raise StoryGenError(f"Fixed scientific parameter override: {role}.{name}")
            elif condition["policy"] == "VARIABLE":
                if value not in condition["allowed"]:
                    raise StoryGenError(f"Unapproved scientific parameter: {role}.{name}")
            else:
                raise StoryGenError(f"Unknown parameter policy: {role}.{name}")
            result[role]["parameters"][name] = value
        unknown = set(actual.get("parameters", {})) - set(definition["conditions"].get(role, {}))
        if unknown:
            raise StoryGenError(f"Undeclared scientific parameters in {role}: {sorted(unknown)}")
    return result


def resolve_instruments(root, home, definition, depot):
    values = []
    for instrument in definition["instruments"]:
        base = {"experiment": home, "code": root, "depot": depot}.get(instrument["root"])
        if base is None:
            raise StoryGenError("Unknown instrument root")
        path = contained(base, instrument["path"])
        if not path.is_file():
            raise StoryGenError(f"Missing scientific instrument: {path}")
        actual = file_sha(path)
        if actual != instrument["sha256"]:
            raise StoryGenError(f"Scientific instrument hash drift: {instrument['path']}")
        values.append({**instrument, "resolved_path": str(path)})
    return values


def snapshot(home, definition, pipeline, instruments):
    files = {n: file_sha(Path(home) / n) for n in ["experiment.yaml", "pipeline.yaml"]}
    return {
        "definition": definition,
        "pipeline": pipeline,
        "files": files,
        "instruments": [{k: v for k, v in x.items() if k != "resolved_path"} for x in instruments],
    }


def freeze(depot, home, protocol, instruments):
    target = Path(depot) / "scientific_locks" / protocol["definition"]["experiment_id"]
    if target.exists():
        lock = read(target / "lock.json")
        if lock["protocol_sha256"] != digest(protocol):
            raise StoryGenError("Frozen scientific definition changed; create a new experiment ID")
        for name, expected in lock["snapshot_files"].items():
            if file_sha(contained(target, name)) != expected:
                raise StoryGenError("Immutable scientific snapshot corrupted")
        return lock
    import tempfile
    import os
    import shutil

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".freeze-", dir=target.parent))
    try:
        snapshots = {}
        for name in ["experiment.yaml", "pipeline.yaml"]:
            raw = (Path(home) / name).read_bytes()
            durable_write(temp / name, raw)
            snapshots[name] = file_sha(temp / name)
        for i, item in enumerate(instruments):
            source = Path(item["resolved_path"])
            if item.get("snapshot", True):
                if source.stat().st_size > 2 * 1024 * 1024:
                    raise StoryGenError("Large instrument must be pinned by reference, not copied")
                name = f"instruments/{i}-{source.name}"
                durable_write(temp / name, source.read_bytes())
                snapshots[name] = file_sha(temp / name)
        lock = {
            "created_utc": utc(),
            "origin": "NATIVE_NEW_DEFINITION",
            "protocol_sha256": digest(protocol),
            "protocol": protocol,
            "snapshot_files": snapshots,
        }
        write_json(temp / "lock.json", lock)
        try:
            os.rename(temp, target)
        except OSError:
            if not target.exists():
                raise
            other = read(target / "lock.json")
            if other != lock and other["protocol_sha256"] != lock["protocol_sha256"]:
                raise StoryGenError("Concurrent conflicting scientific freeze") from None
            return other
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return lock
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def approval(depot, impl, evidence=None):
    path = Path(depot) / "implementation_approvals" / (digest(impl) + ".json")
    if evidence is not None:
        if not evidence.get("tests") or evidence.get("code_verified") is not True:
            raise StoryGenError(
                "Implementation approval requires explicit deterministic test evidence"
            )
        if path.exists():
            raise StoryGenError("Approval already exists; immutable approval cannot be replaced")
        write_json(path, {"implementation": impl, "evidence": evidence, "approved_utc": utc()})
    if not path.exists() or read(path)["implementation"] != impl:
        raise StoryGenError(
            f"Unapproved engine/plugin combination {digest(impl)}; record tested approval first"
        )
    return read(path)


def gates(definition, completed, total, errors):
    observations = {
        "coverage": completed / total if total else 0,
        "min_valid": completed,
        "max_errors": errors,
    }
    checks = []
    for gate in definition["gates"]:
        pred = gate["predicate"]
        value = observations[pred]
        passed = value <= gate["value"] if pred == "max_errors" else value >= gate["value"]
        checks.append({**gate, "observed": value, "status": "PASS" if passed else "FAIL"})
    return {
        "status": "PASS" if checks and all(c["status"] == "PASS" for c in checks) else "FAIL",
        "checks": checks,
        "valid": completed,
        "total": total,
        "errors": errors,
    }
