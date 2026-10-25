"""Central contracts v1; additive to, and never a reinterpretation of M13 schemas."""

from pathlib import Path
import json
import re
from jsonschema import Draft202012Validator

SCHEMAS = Path(__file__).resolve().parent


def validate(kind, value):
    schema = json.loads((SCHEMAS / (kind + ".schema.json")).read_text())
    Draft202012Validator(schema).validate(value)
    return value


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Invalid relative path")
    path = Path(value)
    if path.is_absolute() or any(x in {"", ".", ".."} for x in value.split("/")):
        raise ValueError("Unsafe relative path")
    return path


def identifier(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
        or value in {".", ".."}
    ):
        raise ValueError("Invalid run ID")
    return value


def contained(root, value):
    root = Path(root).resolve()
    rel = relative(value)
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlink inside owned namespace")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Output escapes run root")
    return path


def pipeline(value):
    validate("pipeline", value)
    nodes = {s["stage_id"]: s for s in value["stages"]}
    if len(nodes) != len(value["stages"]):
        raise ValueError("Duplicate DAG stage")
    external = {r["name"]: r for r in value["inputs"]}
    if len(external) != len(value["inputs"]):
        raise ValueError("Duplicate input")
    seen = set()
    ordered = []
    ancestors = {}
    while len(seen) < len(nodes):
        ready = [
            key
            for key, s in nodes.items()
            if key not in seen and set(s["depends_on"]) <= seen
        ]
        if not ready:
            raise ValueError("DAG has a cycle or missing dependency")
        for key in ready:
            s = nodes[key]
            deps = s["depends_on"]
            ancestors[key] = set(deps)
            for d in deps:
                ancestors[key] |= ancestors[d]
            roles = {r["role"]: r for r in s["outputs"]}
            if len(roles) != len(s["outputs"]):
                raise ValueError("Duplicate output role")
            for output in roles.values():
                relative(output["path"])
                Draft202012Validator.check_schema(output["schema"])
            if len({r["name"] for r in s["inputs"]}) != len(s["inputs"]):
                raise ValueError("Duplicate stage input")
            for binding in s["inputs"]:
                ref = binding["binding"]
                if "input" in ref:
                    actual = external[ref["input"]]["contract"]
                else:
                    if ref["stage"] not in ancestors[key]:
                        raise ValueError(
                            "Artifact does not follow declared DAG ancestor"
                        )
                    source = {r["role"]: r for r in nodes[ref["stage"]]["outputs"]}
                    actual = source[ref["output"]]["contract"]
                if actual != binding["contract"]:
                    raise ValueError("Incompatible artifact contract")
            adapter = s["adapter"]
            if adapter["kind"] == "local_engine":
                relative(adapter["engine"])
            if adapter["kind"] == "frozen_cli":
                relative(adapter["script"])

            def check_argument(arg, public=False):
                if public and isinstance(arg, list):
                    for v in arg:
                        check_argument(v, True)
                    return
                if isinstance(arg, str) and (
                    arg
                    in {
                        "--overwrite",
                        "--resume",
                        "--overwrite-stale",
                        "--retry-failed-only",
                    }
                    or arg.startswith("/")
                ):
                    raise ValueError("Unsafe or unbound literal argv")
                if isinstance(arg, dict):
                    if "input" in arg:
                        if not any(
                            b["binding"] == {"input": arg["input"]} for b in s["inputs"]
                        ):
                            raise ValueError(
                                "Argument input lacks a declared stage contract"
                            )
                        allowed = (
                            {"input", "pointer", "as"}
                            if public
                            else {"input", "parent"}
                        )
                        if "parent" in arg and arg["parent"] is not True:
                            raise ValueError(
                                "Only one sealed manifest parent directory may be bound"
                            )
                    elif "stage" in arg:
                        ref = {k: arg[k] for k in ["stage", "output"]}
                        if arg["stage"] not in ancestors[key] or not any(
                            b["binding"] == ref for b in s["inputs"]
                        ):
                            raise ValueError(
                                "Argument is not bound to a declared ancestor artifact"
                            )
                        allowed = (
                            {"stage", "output", "pointer", "as"}
                            if public
                            else {"stage", "output"}
                        )
                    elif "asset" in arg:
                        relative(arg["asset"])
                        allowed = {"asset", "pointer", "as"} if public else {"asset"}
                    elif arg == {"output": True} or (
                        not public
                        and (arg == {"run_id": True} or set(arg) == {"config"})
                    ):
                        return
                    elif public:
                        for value in arg.values():
                            check_argument(value, True)
                        return
                    else:
                        raise ValueError("Unknown typed argument")
                    if not set(arg) <= allowed:
                        raise ValueError("Unknown typed reference fields")
                    if "pointer" in arg and (
                        not isinstance(arg["pointer"], str)
                        or arg["pointer"]
                        and not arg["pointer"].startswith("/")
                    ):
                        raise ValueError("Invalid JSON pointer")
                    if "as" in arg and (arg["as"] != "path" or "pointer" in arg):
                        raise ValueError("Invalid path argument conversion")

            arguments = adapter.get("arguments", [])
            if adapter["kind"] == "public_call":
                for argument in arguments.values():
                    check_argument(argument, True)
            else:
                for argument in arguments:
                    check_argument(argument)
            seen.add(key)
            ordered.append(s)
    return ordered


def experiment(value, definition):
    validate("experiment", value)
    if value["experiment_id"] != definition["experiment_id"]:
        raise ValueError("Experiment/pipeline identity mismatch")
    if relative(value["runner"]).name != value["experiment_id"] + ".py":
        raise ValueError("Matching primary runner required")
    ordered = pipeline(definition)
    if (
        any(s["adapter"]["kind"] == "synthetic" for s in ordered)
        and value["science"]["classification"] != "synthetic_only"
    ):
        raise ValueError("Synthetic execution cannot impersonate science")
    if value["science"]["classification"] != "research" and any(
        r["altered"] and not r["rationale"] for r in value["component_reuse"]
    ):
        raise ValueError("An override needs scientific justification")
    return ordered


def checked_file(reference, schema=None):
    import hashlib

    if not isinstance(reference, dict) or not {"path", "sha256"} <= set(reference):
        raise ValueError("Exact file binding required")
    path = Path(reference["path"]).expanduser().resolve()
    actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != reference["sha256"]:
        raise ValueError("Input artifact SHA mismatch")
    if "origin" in reference:
        origin = reference["origin"]
        if (
            set(origin) != {"kind", "run_root", "manifest_sha256", "artifact_id"}
            or origin["kind"] != "central"
        ):
            raise ValueError("Unsupported artifact origin binding")
        from storygen_experiment.artifact_store import verify

        root = Path(origin["run_root"]).resolve()
        verified = verify(root)
        if verified["execution_status"] != "COMPLETE":
            raise ValueError("Only complete sealed upstream runs are accepted")
        if (
            "sha256:"
            + hashlib.sha256((root / "run_manifest.json").read_bytes()).hexdigest()
            != origin["manifest_sha256"]
        ):
            raise ValueError("Upstream manifest identity mismatch")
        manifest = json.loads((root / "run_manifest.json").read_text())
        matches = [
            a
            for a in manifest["artifacts"]
            if a["artifact_id"] == origin["artifact_id"]
        ]
        if (
            len(matches) != 1
            or contained(root, matches[0]["relative_path"]).resolve() != path
            or matches[0]["sha256"] != actual
        ):
            raise ValueError("Artifact is not a declared member of the upstream seal")
    if schema is not None:
        Draft202012Validator(schema).validate(json.loads(path.read_text()))
    return path


def dependency_lock(value, manifest, root):
    import hashlib

    validate("dependency_lock", value)
    if value["experiment_id"] != manifest["experiment_id"]:
        raise ValueError("Lock identity differs")
    for rel, digest in value["owner_assets"].items():
        path = contained(root, rel)
        if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Locked owner source changed")
    return value


def historical_delegate(declaration, observed, commit):
    expected = (
        observed["owner_repo"],
        observed["experiment_id"],
        observed["protocol_id"],
        commit,
        observed["public_runner"],
    )
    actual = tuple(
        declaration[k]
        for k in [
            "owner_repo",
            "experiment_id",
            "protocol_id",
            "source_commit",
            "public_runner",
        ]
    )
    if actual != expected:
        raise ValueError("Historical owner/protocol/revision identity mismatch")
    return declaration
