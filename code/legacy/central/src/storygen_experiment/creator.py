"""Create one central independent experiment without touching another protocol."""

from pathlib import Path
import argparse
import ast
import fcntl
import importlib.metadata
import json
import os
import sys
from packaging.requirements import Requirement
from storygen_experiment import ROOT, contracts, registry, runtime, references


def package_closure(names):
    seen = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        canonical = importlib.metadata.distribution(name).metadata["Name"]
        if canonical in seen:
            continue
        direct = importlib.metadata.distribution(name).read_text("direct_url.json")
        if direct and json.loads(direct).get("dir_info", {}).get("editable"):
            raise ValueError("Mutable editable environment dependency: " + name)
        seen.add(canonical)
        for requirement in importlib.metadata.requires(canonical) or []:
            value = Requirement(requirement)
            if value.marker is None or value.marker.evaluate({"extra": ""}):
                pending.append(value.name)
    return seen


def create(spec, *, repo=ROOT, depot=None):
    spec, selected = references.expand(spec)
    root = Path(repo).resolve()
    depot = Path(depot or root.parent / "storygen-experiment-depot")
    manifest = spec["experiment"]
    definition = spec["pipeline"]
    contracts.experiment(manifest, definition)
    key = manifest["experiment_id"]
    directory = depot / ".locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (key + ".lock")).open("a+b") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        try:
            if any(
                v["manifest"]["experiment_id"] == key for v in registry.discover(root)
            ):
                raise FileExistsError("Experiment ID already exists")
            home = root / "experiments" / manifest["group_id"] / key
            if home.exists():
                raise FileExistsError("Experiment directory already exists")
            engines = spec.get("engine_sources", {})
            imports = set()
            own_modules = {Path(p).stem for p in engines}
            for rel, text in engines.items():
                contracts.relative(rel)
                if not rel.startswith("src/"):
                    raise ValueError("Experimental code must be inside owned src/")
                tree = ast.parse(text, filename=rel)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "sys"
                        and node.attr == "path"
                    ):
                        raise ValueError("Mutable sys.path is forbidden")
                    names = (
                        [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or ""]
                        if isinstance(node, ast.ImportFrom)
                        else []
                    )
                    if any(
                        n == "experiments"
                        or n.startswith(("experiments.", "storygen_protocol_science"))
                        for n in names
                    ):
                        raise ValueError("Private experiment imports are forbidden")
                    for name in names:
                        if (
                            name.split(".")[0] in references.PROJECT_MODULES
                            and not references.module_allowed(name, selected)
                        ):
                            raise ValueError(
                                "Undeclared frozen project import: " + name
                            )
                        imports.add(name.split(".")[0])
                    if isinstance(node, ast.Call) and (
                        (
                            isinstance(node.func, ast.Name)
                            and node.func.id == "__import__"
                        )
                        or (
                            isinstance(node.func, ast.Attribute)
                            and node.func.attr == "import_module"
                        )
                    ):
                        raise ValueError(
                            "Dynamic imports require a promoted explicit public component interface"
                        )
            distributions = importlib.metadata.packages_distributions()
            extras = set(spec.get("environment_packages", []))
            for name in imports - set(sys.stdlib_module_names) - own_modules - {""}:
                if name in references.PROJECT_MODULES:
                    continue
                packages = distributions.get(name, [])
                if len(packages) != 1:
                    raise ValueError(
                        "Missing or ambiguous installed import dependency: " + name
                    )
                extras.add(packages[0])
            for stage in definition["stages"]:
                if (
                    stage["adapter"]["kind"] == "local_engine"
                    and stage["adapter"]["engine"] not in engines
                ):
                    raise ValueError("Own engine source must be supplied")
            environment = runtime.environment_lock(
                package_closure(["PyYAML", "jsonschema", "packaging", *extras])
            )
            for rel, value in spec.get("scientific_assets", {}).items():
                contracts.relative(rel)
                if not isinstance(value, str):
                    runtime.encode(value)
            home.mkdir(parents=True, exist_ok=False)
            (home / "src").mkdir()
            (home / "tests").mkdir()
            for rel, text in engines.items():
                path = contracts.contained(home, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            for rel, value in spec.get("scientific_assets", {}).items():
                path = contracts.contained(home, "src/assets/" + rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    value
                    if isinstance(value, str)
                    else json.dumps(value, indent=2) + "\n"
                )
            runner = '''"""Primary central runner; scientific stages are version-locked by the protocol."""\nfrom pathlib import Path\nimport os,sys\nROOT=Path(__file__).resolve().parents[3]\nif __name__=='__main__':\n args=sys.argv[1:] or ['plan']\n tail=args if args[0] in {'--help','-h'} else [args[0],EXPERIMENT_ID,*args[1:]]\n os.execve(sys.executable,[sys.executable,str(ROOT/'tools/experiments.py'),*tail],dict(os.environ))\n'''.replace(
                "EXPERIMENT_ID", repr(key)
            )
            (home / (key + ".py")).write_text(runner)
            (home / "pipeline.yaml").write_bytes(runtime.encode(definition))
            (home / "README.md").write_text(
                "# "
                + key
                + "\n\n"
                + manifest["science"]["question"]
                + "\n\nProtocol: "
                + manifest["protocol_id"]
                + " / "
                + manifest["protocol_version"]
                + ". Scientific validity is UNVERIFIED until qualified separately.\n\nUse `python "
                + key
                + ".py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.\n\nPipeline: "
                + " → ".join(s["stage_id"] for s in definition["stages"])
                + ". Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.\n"
            )
            config = spec.get(
                "run_configuration", {"purpose": "SYNTHETIC_TEST", "inputs": {}}
            )
            (home / "run.example.json").write_bytes(runtime.encode(config))
            # Publish the discoverable manifest last; lock all actual runner/pipeline/science bytes.
            manifest_payload = runtime.encode(manifest)
            (home / "experiment.pending.json").write_bytes(manifest_payload)
            assets = {
                str(p.relative_to(home)): runtime.sha(p)
                for p in home.rglob("*")
                if p.is_file()
                and (
                    p.suffix == ".py"
                    or str(p.relative_to(home)).startswith("src/")
                    or p.name == "pipeline.yaml"
                )
            }
            assets["experiment.yaml"] = (
                "sha256:" + __import__("hashlib").sha256(manifest_payload).hexdigest()
            )
            dependencies = spec.get("dependencies", {})
            lock = dict(
                schema_version="storygen.central-lock/1.0",
                experiment_id=key,
                owner_assets=assets,
                providers=dependencies.get("providers", []),
                delegates=dependencies.get("delegates", {}),
                environment=environment,
                models=dependencies.get("models", []),
                backend_files=dependencies.get("backend_files", []),
            )
            contracts.validate("dependency_lock", lock)
            (home / "dependencies.lock.yaml").write_bytes(runtime.encode(lock))
            os.rename(home / "experiment.pending.json", home / "experiment.yaml")
            (home / "tests/test_protocol.py").write_text(
                '''"""Protocol conformance; scientific acceptance needs the declared domain validators."""\nfrom pathlib import Path\nfrom storygen_experiment import contracts,registry\ndef test_independent_protocol_and_exact_owned_sources():\n home=Path(__file__).resolve().parents[1]\n value=registry.locked(home.name,home.parents[2])\n assert value['manifest']['science']['acceptance_criteria']\n assert contracts.experiment(value['manifest'],value['pipeline'])\n'''
            )
            runtime.atomic_json(
                home / "creation_receipt.json",
                dict(
                    experiment_id=key,
                    owner="storygen-experiment",
                    created_utc=runtime.utc(),
                    old_experiment_edits=False,
                    source_assets=assets,
                ),
            )
            registry.update_catalog(root, depot)
            return home
        finally:
            fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


def template(key, group, kind, question=None):
    science = dict(
        question=question
        or "Can this explicit engineering fixture execute with exact sources and a sealed central output?",
        hypotheses=["Declared output contract and immutable provenance hold"],
        independent_variables=["Explicit engineering composition only"],
        controls=[
            "Frozen reference estimator"
            if kind == "public_reference"
            else "No model or scientific estimator"
        ],
        population="One declared engineering fixture",
        unit_of_analysis="Pipeline stage",
        metrics=["Execution, schema and artifact integrity"],
        acceptance_criteria=[
            "Declared JSON output validates and the run seals without errors"
        ],
        limitations=[
            "Engineering fixture only; scientific validity remains UNVERIFIED"
        ],
        classification="verification_only"
        if kind == "public_reference"
        else "synthetic_only",
    )
    manifest = dict(
        schema_version="storygen.central-experiment/1.0",
        experiment_id=key,
        group_id=group,
        protocol_id=key.upper() + "_V1",
        protocol_version="1.0.0",
        runner=key + ".py",
        pipeline="pipeline.yaml",
        science=science,
        component_reuse=[],
        historical_delegation=None,
    )
    stage = dict(
        stage_id="measure" if kind == "public_reference" else "custom",
        provider="storygen-evaluation"
        if kind == "public_reference"
        else "experiment-local",
        depends_on=[],
        inputs=[],
        outputs=[
            dict(
                role="result",
                contract="verification.scalar/1.0",
                path="result.json",
                schema={"type": "number"},
            )
        ],
        adapter={},
        parameters={},
        resources=dict(profile="deterministic", work_units=1),
    )
    spec = dict(
        experiment=manifest,
        pipeline=dict(
            schema_version="storygen.central-pipeline/1.0",
            experiment_id=key,
            inputs=[],
            stages=[stage],
        ),
        run_configuration=dict(
            purpose="MIGRATION_VERIFICATION"
            if kind == "public_reference"
            else "SYNTHETIC_TEST",
            inputs={},
        ),
    )
    if kind == "public_reference":
        component = "storygen.evaluation/2.4.1"
        manifest["component_reuse"] = [
            dict(
                component=component,
                rationale="Unchanged public MAE estimator on a numeric fixture isolates orchestration from scientific implementation",
                altered=False,
            )
        ]
        stage["adapter"] = dict(
            kind="public_call",
            component=component,
            module="storygen_evaluation.metrics",
            function="mae",
            arguments=dict(a=[0, 1], b=[1, 0]),
        )
    else:
        manifest["component_reuse"] = [
            dict(
                component="experiment.owned_fixture/0.1.0",
                rationale="New local synthetic fixture code; no frozen component is edited",
                altered=True,
            )
        ]
        stage["adapter"] = dict(
            kind="local_engine",
            engine="src/engine.py",
            version="0.1.0",
            arguments=[{"output": True}],
        )
        spec["engine_sources"] = {
            "src/engine.py": "from pathlib import Path\nimport json,sys\n(Path(sys.argv[1])/'result.json').write_text(json.dumps(1)+'\\n')\n"
        }
    return spec


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        epilog="Generate a template, edit scientific question/controls/DAG/acceptance, then create once. Frozen components are selected by exact version and must have explicit reuse rationale.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--spec", type=Path)
    mode.add_argument("--template", choices=["local_engine", "public_reference"])
    mode.add_argument("--list-components", action="store_true")
    p.add_argument("--experiment-id", default="my_experiment")
    p.add_argument("--group", default="future_research")
    p.add_argument("--question")
    p.add_argument("--output", type=Path)
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--depot", type=Path)
    args = p.parse_args(argv)
    try:
        if args.list_components:
            print(
                json.dumps(
                    {
                        k: {
                            field: v.get(field)
                            for field in [
                                "source",
                                "python_modules",
                                "interfaces",
                                "dependencies",
                                "compatibility_policy",
                            ]
                        }
                        for k, v in references.catalog()["components"].items()
                    },
                    indent=2,
                )
            )
            return 0
        if args.template:
            value = template(
                args.experiment_id, args.group, args.template, args.question
            )
            contracts.experiment(value["experiment"], value["pipeline"])
            if args.output:
                runtime.exclusive_json(args.output, value)
                print(
                    json.dumps(
                        dict(status="TEMPLATE_WRITTEN", path=str(args.output.resolve()))
                    )
                )
            else:
                print(json.dumps(value, indent=2))
            return 0
        home = create(registry.read(args.spec), repo=args.repo, depot=args.depot)
        print(
            json.dumps(dict(status="CREATED", experiment_directory=str(home)), indent=2)
        )
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="REJECTED", error=repr(exc)), indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
