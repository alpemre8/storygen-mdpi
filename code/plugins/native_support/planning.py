"""Offline inspection of exact historical recipes using consolidated Git/data only.

This module never executes a recipe's returned stage commands. Network and non-Git
subprocesses are denied while loading/validating the historical planning code.
"""

from contextlib import contextmanager
from pathlib import Path
import csv
import gzip
import importlib.util
import socket
import subprocess
import sys
import uuid

from storygen_platform.engine.common import StoryGenError, file_sha, read, write_json, utc

# Derived, process-local optimization only: bytes are hashed at least once and any
# file identity/size/ctime/mtime change invalidates the cache. Never a science record.
_FILE_HASH_CACHE = {}


def cached_native_hash(original):
    def checked(path):
        p = Path(path).resolve()
        before = p.stat()
        key = (
            str(p),
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if key not in _FILE_HASH_CACHE:
            result = original(p)
            after = p.stat()
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise StoryGenError("Native input changed while hashing: " + str(p))
            _FILE_HASH_CACHE[key] = result
        return _FILE_HASH_CACHE[key]

    return checked


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


@contextmanager
def offline_planning():
    original_popen = subprocess.Popen
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_connection = socket.create_connection

    def deny_network(*args, **kwargs):
        raise StoryGenError("Offline native planning forbids network/model requests")

    def guarded_popen(command, *args, **kwargs):
        if not isinstance(command, (list, tuple)) or not command or Path(command[0]).name != "git":
            raise StoryGenError(
                "Offline native planning permits Git subprocesses only; stage commands are not executed"
            )
        return original_popen(command, *args, **kwargs)

    subprocess.Popen = guarded_popen
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    try:
        yield
    finally:
        subprocess.Popen = original_popen
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.create_connection = original_connection


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def source_snapshot(root, depot, repo_id, commit):
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise StoryGenError("Exact original source commit required for native planning")
    target = Path(depot) / ".native-sources" / repo_id / commit
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "--detach", str(target), commit],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    if git(target, "rev-parse", "HEAD") != commit or git(target, "status", "--porcelain"):
        raise StoryGenError("Historical source worktree differs from its original commit")
    return target


def input_references(root, depot, expected_hashes):
    """Resolve exact copied bytes even when old path spelling is no longer usable."""
    inventory = Path(root) / "docs/migration/ARTIFACT_INVENTORY.csv"
    opener = (
        inventory.open
        if inventory.exists()
        else lambda **kw: gzip.open(str(inventory) + ".gz", "rt", **kw)
    )
    candidates = {}
    with opener(newline="") as stream:
        for row in csv.DictReader(stream):
            if row["sha256"] not in expected_hashes:
                continue
            base = depot if row["target_repo"] == "storygen-depot" else root
            target = Path(base) / row["target_path"]
            candidates.setdefault(row["sha256"], []).append((target, row))
    return candidates


def resolve_configuration(root, depot, home, options):
    source = home / "src/assets/native_configuration.json"
    if not source.is_file():
        raise StoryGenError("Native configuration is not a published hashed central asset")
    config = read(source)
    profile = None
    if options.get("full_population", True):
        strategy = options.get("strategy")
        profile_name = {
            "DP-v1": "research.dp.profile.json",
            "CG-v1": "research.cg.profile.json",
            None: "research.profile.json",
        }.get(strategy)
        if profile_name and (home / profile_name).exists():
            profile = read(home / profile_name)
            if profile["purpose"] != "RESEARCH" or not profile["complete_film_population"]:
                raise StoryGenError(
                    "Full population profile has no authoritative complete-film declaration"
                )
            config["purpose"] = "RESEARCH"
            config["manage_servers"] = False
            config.pop("verification_task_ids", None)
            if "scene_selection" in config.get("inputs", {}):
                raise StoryGenError(
                    "Full original population cannot silently inherit a scene selector"
                )
            if strategy:
                if profile["strategy"] != strategy or profile["task_count"] != 240:
                    raise StoryGenError(
                        "Historical full TasksetV5 profile changed its condition/population"
                    )
                config["strategy"] = strategy
            lock = read(
                Path(root) / "legacy/central/src/storygen_experiment/research_inputs.lock.json"
            )
            config["inputs"] = {
                name: {"path": ref["relative_path"], "sha256": ref["sha256"]}
                for name, ref in lock["files"].items()
                if name != "canonical_server_manifest"
            }
            server = lock["files"]["canonical_server_manifest"]
            names = (
                ["rewrite_server_manifest", "measurement_server_manifest"]
                if strategy
                else ["server_manifest"]
            )
            config["inputs"].update(
                {
                    name: {"path": server["relative_path"], "sha256": server["sha256"]}
                    for name in names
                }
            )
    requested = {ref["sha256"].removeprefix("sha256:") for ref in config.get("inputs", {}).values()}
    candidates = input_references(root, depot, requested)
    mappings = []
    for name, ref in config.get("inputs", {}).items():
        if any(
            marker in (name + " " + ref["path"]).lower()
            for marker in ["sealed_holdout", "sealed-holdout"]
        ):
            raise StoryGenError("Sealed holdout inputs cannot be opened by native planning")
        expected = ref["sha256"].removeprefix("sha256:")
        available = candidates.get(expected, [])
        # Prefer matching source basenames; exact content identity remains mandatory.
        available.sort(key=lambda pair: (pair[0].name != Path(ref["path"]).name, len(str(pair[0]))))
        chosen = next(
            ((p, r) for p, r in available if p.is_file() and file_sha(p) == expected), None
        )
        if chosen is None:
            raise StoryGenError(
                f"Missing copied exact native input {name}: {ref['path']} ({expected})"
            )
        path, row = chosen
        storage_uri = (
            ("depot:" + path.relative_to(depot).as_posix())
            if path.is_relative_to(depot)
            else ("code:" + path.relative_to(root).as_posix())
        )
        mappings.append(
            {
                "storage_uri": storage_uri,
                "name": name,
                "original_path": ref["path"],
                "resolved_path": str(path.resolve()),
                "sha256": expected,
                "source_repo": row["source_repo"],
                "source_path": row["source_path"],
                "source_commit": row["source_commit"],
            }
        )
        ref["path"] = str(path.resolve())
    # Directory moves are technical bindings. Preserve source files and all schema/target fields.
    repositories = read(Path(root) / "docs/migration/inventory.json")["repositories"]
    aliases = []
    for repo in repositories:
        if repo["kind"] != "depot":
            continue
        target = Path(depot) / "migration/sources" / repo["name"]
        aliases.extend(
            [
                (repo["path"], str(target)),
                (str(Path(repo["path"]).parent.parent / repo["name"]), str(target)),
            ]
        )
    for key, value in list(config.items()):
        if (
            isinstance(value, str)
            and Path(value).is_absolute()
            and key not in {"model_file", "backend_root"}
        ):
            for old, new in sorted(aliases, key=lambda pair: -len(pair[0])):
                if value == old or value.startswith(old + "/"):
                    config[key] = new + value[len(old) :]
                    break
    config["source_roots"] = {
        r: str(Path(root).resolve())
        for r in [
            "storygen-rewrite",
            "storygen-feature-extraction",
            "storygen-evaluation",
            "storygen-naturalness",
        ]
    }
    config["backend_root"] = str((Path(root).parent / "llama.cpp").resolve())
    return config, mappings, profile


def inspect(definition, root, depot, options=None):
    root, depot = Path(root).resolve(), Path(depot).resolve()
    options = options or {}
    unknown = set(options) - {"strategy", "full_population"}
    if unknown:
        raise StoryGenError("Unknown native planning parameters: " + repr(sorted(unknown)))
    if options.get("strategy") not in {None, "DP-v1", "CG-v1"}:
        raise StoryGenError("Native strategy must be DP-v1 or CG-v1")
    if not isinstance(options.get("full_population", True), bool):
        raise StoryGenError("full_population must be an explicit Boolean")
    original = definition.get("historical", {}).get("original_manifest")
    if not original or not original.get("historical_delegation"):
        raise StoryGenError(
            "No exact published native delegate exists; experiment-owned/local engine migration needs its own contract adapter"
        )
    owner = original["historical_delegation"]
    home = root / definition["historical"]["source_path"]
    central_lock = read(home / "dependencies.lock.yaml")
    from storygen_platform.engine.common import contained

    for relative, expected in central_lock["owner_assets"].items():
        asset = contained(home, relative)
        if not asset.is_file() or file_sha(asset) != expected.removeprefix("sha256:"):
            raise StoryGenError("Copied historical owner asset drift: " + relative)
    profiles = [home / "research.dp.profile.json", home / "research.cg.profile.json"]
    if (
        options.get("full_population", True)
        and options.get("strategy") is None
        and all(p.is_file() for p in profiles)
    ):
        variants = {
            read(p)["strategy"]: inspect(
                definition, root, depot, {**options, "strategy": read(p)["strategy"]}
            )
            for p in profiles
        }
        counts = {v["full_population_profile"]["task_count"] for v in variants.values()}
        if len(counts) != 1:
            raise StoryGenError("Native condition profiles disagree on the frozen task population")
        count = counts.pop()
        return {
            "status": "NATIVE_FULL_CONDITION_PLANS_VERIFIED_INFERENCE_UNVERIFIED",
            "experiment_id": definition["experiment_id"],
            "plans": variants,
            "distinct_tasks": count,
            "task_condition_observations": count * len(variants),
            "inference_performed": False,
            "server_started": False,
            "qualification": "Full original conditions; same task IDs, not a new taskset population",
        }
    config, mappings, full_profile = resolve_configuration(root, depot, home, options)
    preflight_id = "PF-" + uuid.uuid4().hex
    destination = depot / "preflights" / definition["experiment_id"] / preflight_id
    destination.mkdir(parents=True, exist_ok=False)
    run_id = "NATIVE-PLAN-" + uuid.uuid4().hex
    with offline_planning():
        owner_source = source_snapshot(root, depot, owner["owner_repo"], owner["source_commit"])
        runner = owner_source / owner["public_runner"]
        envelope = module(
            owner_source / "components/execution/v4/envelope.py",
            "_sg_native_inspect_" + preflight_id,
        )

        class Rebound(envelope.Context):
            def root(self, repo_id):
                return destination / "proposed_run" / repo_id

            def output(self, repo_id, stage):
                return destination / "proposed_run" / "stages" / stage / repo_id

        context = Rebound(
            runner,
            config,
            run_id,
            depot / "migration/sources",
            depot / ".native-sources/locked-providers",
        )
        context.runtime.sha256_file = cached_native_hash(context.runtime.sha256_file)
        context.resolve(materialize=True)
        recipe = module(runner.parent / "src/protocol.py", "_sg_native_recipe_" + preflight_id)
        plan = envelope.validate_plan(context, recipe.plan(context))
        for stage in plan:
            if stage.get("server_profile"):
                # Merely inspecting a plan never attests or starts its backend.
                config["manage_servers"] = False
        envelope.doctor(context, plan)
    central_pipeline = read(home / "pipeline.yaml")
    selected = [
        n["adapter"]["native_stage"]
        for n in central_pipeline["stages"]
        if n["adapter"]["kind"] == "m13_stage"
    ]
    extra = [
        n["stage_id"] for n in central_pipeline["stages"] if n["adapter"]["kind"] != "m13_stage"
    ]
    native_ids = {n["stage_id"] for n in plan}
    if set(selected) - native_ids:
        raise StoryGenError("Central wrapper requests a stage absent from its exact native recipe")
    code_files = []
    for stage in plan:
        argv = stage["command"]
        if len(argv) > 1 and Path(argv[1]).is_file():
            script = Path(argv[1]).resolve()
            candidates = [
                (repo, source, binding["commit"])
                for repo, source in context.providers.items()
                for binding in context.lock["source_repositories"]
                if binding["repo_id"] == repo and script.is_relative_to(source)
            ]
            if script.is_relative_to(owner_source):
                uri = (
                    "git:"
                    + owner["source_commit"]
                    + ":"
                    + script.relative_to(owner_source).as_posix()
                )
            elif candidates:
                repo, source, commit = candidates[0]
                uri = "git:" + commit + ":" + script.relative_to(source).as_posix()
            else:
                raise StoryGenError("Native script is not in its exact source snapshots")
            code_files.append(
                {
                    "stage_id": stage["stage_id"],
                    "git_uri": uri,
                    "resolved_path": str(script),
                    "sha256": file_sha(script),
                }
            )
    instrument_files = []
    for component in context.lock["components"]:
        source = context.providers[component["repo_id"]]
        commit = next(
            b["commit"]
            for b in context.lock["source_repositories"]
            if b["repo_id"] == component["repo_id"]
        )
        for relative in component["paths"]:
            for instrument in sorted((source / relative).rglob("*")):
                if (
                    instrument.is_file()
                    and instrument.suffix in {".txt", ".json", ".yaml", ".yml", ".j2"}
                    and set(instrument.parts) & {"prompts", "schemas", "configs", "config"}
                ):
                    instrument_files.append(
                        {
                            "component_id": component["component_id"],
                            "git_uri": "git:"
                            + commit
                            + ":"
                            + instrument.relative_to(source).as_posix(),
                            "resolved_path": str(instrument),
                            "sha256": file_sha(instrument),
                        }
                    )
    result = {
        "stage_coverage": {
            "central_selected_native_stages": selected,
            "central_non_native_stages": extra,
            "native_recipe_stages": sorted(native_ids),
            "central_classification": original["science"]["classification"],
        },
        "native_dependency_lock": context.lock,
        "code_files": code_files,
        "instrument_files": instrument_files,
        "authoritative_resolution": "Storage-relative/Git URIs plus immutable hashes; absolute paths are execution facts only",
        "status": "NATIVE_PLAN_VERIFIED_INFERENCE_UNVERIFIED",
        "experiment_id": definition["experiment_id"],
        "preflight_id": preflight_id,
        "created_utc": utc(),
        "inference_performed": False,
        "server_started": False,
        "recipe": owner,
        "recipe_sha256": file_sha(runner.parent / "src/protocol.py"),
        "native_protocol_id": context.manifest["protocol_id"],
        "native_lock_sha256": file_sha(context.lock_path),
        "configuration": config,
        "input_mappings": mappings,
        "full_population_profile": full_profile,
        "proposed_run_id": run_id,
        "native_plan": plan,
        "source_commits": context.lock["source_repositories"],
        "qualification": "Exact native planning and local dependency checks only. Returned stage commands were NEVER executed. No native scientific run or equivalence claim.",
    }
    write_json(destination / "native_plan.json", result)
    return result
