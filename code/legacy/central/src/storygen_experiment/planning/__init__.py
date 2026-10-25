"""Plan exact sources, bindings and DAG edges before reserving a run."""

from pathlib import Path
from storygen_experiment import ROOT, contracts, runtime, registry
from storygen_experiment.artifact_store import checked_depot, run_root


def runner_identity(root):
    root = Path(root)
    files = {
        str(p.relative_to(root)): runtime.sha(p)
        for folder in ["src", "tools"]
        for p in (root / folder).rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"} and "__pycache__" not in p.parts
    }
    try:
        head = runtime.git(root, "rev-parse", "HEAD")
        dirty = runtime.git(root, "status", "--porcelain")
    except Exception:
        head = None
        dirty = "UNCOMMITTED_REPOSITORY"
    return dict(git_sha=head, dirty_status=dirty, files=files)


def resolve_inputs(definition, config):
    refs = config.get("inputs", {})
    bound = {}
    provenance = []
    required = {v["name"]: v for v in definition["inputs"]}
    if set(refs) != set(required):
        raise ValueError("Exact declared inputs required: " + repr(sorted(required)))
    for key, value in refs.items():
        path = contracts.checked_file(value, required[key]["schema"])
        bound[key] = path
        provenance.append(
            dict(
                name=key,
                contract=required[key]["contract"],
                path=str(path),
                declared_path=value["path"],
                sha256=value["sha256"],
                **({"origin": value["origin"]} if "origin" in value else {}),
            )
        )
    return bound, provenance


def plan(key, config, run_id, *, repo=ROOT, workspace=None, depot=None, cache=None):
    repo = Path(repo).resolve()
    workspace = Path(workspace or repo.parent).resolve()
    depot = checked_depot(depot or workspace / "storygen-experiment-depot")
    cache = Path(cache or Path.home() / ".cache/storygen-experiment/providers")
    value = registry.locked(key, repo)
    manifest = value["manifest"]
    definition = value["pipeline"]
    lock = value["lock"]
    root = run_root(depot, manifest["group_id"], key, run_id)
    if root.exists():
        raise FileExistsError("Run ID already allocated; use a fresh successor")
    purpose = config.get("purpose")
    if purpose not in {"SYNTHETIC_TEST", "MIGRATION_VERIFICATION", "RESEARCH"}:
        raise ValueError("Explicit run purpose required")
    if (
        manifest["science"]["classification"] == "synthetic_only"
        and purpose != "SYNTHETIC_TEST"
    ):
        raise ValueError("Synthetic engine cannot impersonate research/inference")
    if (
        manifest["science"]["classification"] == "verification_only"
        and purpose == "RESEARCH"
    ):
        raise ValueError("Verification protocol is not a research benchmark")
    bound, inputs = resolve_inputs(definition, config)
    providers = {}
    provider_versions = {}
    provenance = []
    for reference in lock["providers"]:
        path, identity = runtime.pin_provider(reference, workspace, cache)
        providers[reference["repo_id"]] = path
        provider_versions[reference["repo_id"] + "@" + reference["commit"]] = path
        provenance.append(identity)
    runner = dict(
        framework=runner_identity(ROOT), experiment_repository=runner_identity(repo)
    )
    if purpose == "RESEARCH":
        for identity in runner.values():
            if identity["git_sha"] is None or any(
                line
                and not line.endswith("EXPERIMENTS.md")
                and not line[3:].startswith("docs/")
                for line in identity["dirty_status"].splitlines()
            ):
                raise RuntimeError("Commit exact sources before RESEARCH")
    for ref in lock["models"]:
        if runtime.sha(ref["path"]) != ref["sha256"]:
            raise RuntimeError("Model digest mismatch")
    for ref in lock["backend_files"]:
        if runtime.sha(ref["path"]) != ref["sha256"]:
            raise RuntimeError("Backend binary/library digest mismatch")
    stages = contracts.experiment(manifest, definition)
    return dict(
        repo=repo,
        workspace=workspace,
        depot=depot,
        cache=cache,
        root=root,
        manifest=manifest,
        definition=definition,
        lock=lock,
        home=value["home"],
        stages=stages,
        config=config,
        run_id=run_id,
        bound_inputs=bound,
        providers=providers,
        provider_versions=provider_versions,
        resolved_inputs=inputs,
        resolved_providers=provenance,
        runner=runner,
    )


def frozen_lock(c):
    return dict(
        schema_version="storygen.central-execution-lock/1.0",
        run_id=c["run_id"],
        experiment=c["manifest"],
        pipeline=c["definition"],
        dependency_lock=c["lock"],
        configuration=c["config"],
        configuration_sha256=runtime.canonical(c["config"]),
        pipeline_sha256=runtime.canonical(c["definition"]),
        runner=c["runner"],
        resolved_providers=c["resolved_providers"],
        resolved_inputs=c["resolved_inputs"],
        native_execution_contexts=c.get("native_metadata", []),
        reference_components=c.get("reference_metadata", {}),
        output_ownership=c.get("output_ownership", []),
    )
