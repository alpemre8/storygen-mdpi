"""Thin binding to unchanged M13 recipe plans, provider resolution and server lifecycle."""

from pathlib import Path
import importlib.util
import json
import os
import subprocess
import sys
from storygen_experiment import contracts, runtime


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Native:
    def __init__(self, context, key):
        self.central = context
        self.key = key
        binding = context["lock"]["delegates"][key]
        reference = next(
            (
                r
                for r in context["lock"]["providers"]
                if r["repo_id"] == binding["repo_id"]
                and r["commit"] == binding["commit"]
            ),
            None,
        )
        if reference is None:
            raise ValueError("Native delegate has no exact provider binding")
        root = context["provider_versions"][
            binding["repo_id"] + "@" + binding["commit"]
        ]
        runner = contracts.contained(root, binding["runner"])
        home = runner.parent
        if (
            runtime.sha(home / "experiment.yaml") != binding["experiment_sha256"]
            or runtime.sha(home / "dependencies.lock.yaml")
            != binding["dependency_lock_sha256"]
        ):
            raise RuntimeError("Frozen native metadata drift")
        self.native_manifest = json.loads((home / "experiment.yaml").read_text())
        if context["manifest"]["historical_delegation"]:
            contracts.historical_delegate(
                context["manifest"]["historical_delegation"],
                self.native_manifest,
                binding["commit"],
            )
        config_path = context["bound_inputs"][key + "_configuration"]
        config = json.loads(config_path.read_text())
        if config["purpose"] != context["config"]["purpose"]:
            raise ValueError("Native/central run purpose differs")
        discovery = load(
            root / "components/architecture/v2/registry.py", "m13_discovery_" + key
        )
        blockers = discovery.runtime_blockers(self.native_manifest, config_path)
        if blockers:
            raise RuntimeError("; ".join(blockers))
        self.envelope = load(
            root / "components/execution/v4/envelope.py", "m13_native_envelope_" + key
        )
        selected = [
            s
            for s in context["stages"]
            if s["adapter"]["kind"] == "m13_stage" and s["adapter"]["delegate"] == key
        ]
        if not selected:
            raise ValueError("Empty native delegate")
        first = selected[0]["stage_id"]
        base = context["root"]
        mapping = {s["adapter"]["native_stage"]: s["stage_id"] for s in selected}
        if len(mapping) != len(selected):
            raise ValueError("Native stage duplicated inside a delegate")

        class Rebound(self.envelope.Context):
            def root(self, repo):
                if repo not in self.envelope_repos:
                    raise ValueError("Unknown native provider")
                return contracts.contained(
                    base, "stages/" + first + "/native_workspace/" + key + "/" + repo
                )

            def output(self, repo, stage):
                return contracts.contained(
                    base, "stages/" + mapping.get(stage, stage) + "/raw/data"
                )

        self.context = Rebound(
            runner,
            config,
            context["run_id"] + "_" + key,
            context["workspace"],
            context["cache"] / "native-science",
        )
        self.context.envelope_repos = self.envelope.a.REPOS
        self.context.resolve(materialize=True)
        for reference in self.context.lock["source_repositories"]:
            context["resolved_providers"].append(
                dict(
                    **reference,
                    execution_root=str(self.context.providers[reference["repo_id"]]),
                    selection="NATIVE_FROZEN_SCIENCE",
                    delegate=key,
                )
            )
        for name, ref in config.get("inputs", {}).items():
            context["resolved_inputs"].append(
                dict(
                    name=key + "." + name,
                    contract="M13_NATIVE_INPUT",
                    path=self.context.input(name),
                    declared_path=ref["path"],
                    sha256=ref["sha256"],
                )
            )
        recipe = load(home / "src/protocol.py", "m13_recipe_" + key)
        self.plan = self.envelope.validate_plan(self.context, recipe.plan(self.context))
        self.by_id = {s["stage_id"]: s for s in self.plan}
        for stage in selected:
            native = self.by_id.get(stage["adapter"]["native_stage"])
            if not native or native["provider_repo"] != stage["provider"]:
                raise ValueError("Central/native stage provider mismatch")
            native_dep = next(
                s
                for s in self.native_manifest["stages"]
                if s["stage_id"] == stage["adapter"]["native_stage"]
            )["depends_on"]
            if any(
                d in mapping and mapping[d] not in stage["depends_on"]
                for d in native_dep
            ):
                raise ValueError("Central DAG omits frozen native dependency")
        from .profile_checks import doctor

        profile_check = doctor(self.envelope, self.context, self.plan)
        self.provider_paths = []
        modules = {}
        for repo, path in self.context.providers.items():
            for rel, module in {
                "storygen-rewrite": [
                    ("rewrite/src", "storygen"),
                    ("taskset/src", "storygen_taskset"),
                ],
                "storygen-feature-extraction": [
                    ("measurement/src", "storygen_measurement_core"),
                    ("feature_extraction/src", "storygen_feature"),
                ],
                "storygen-evaluation": [("evaluation/src", "storygen_evaluation")],
                "storygen-naturalness": [("src", "storygen_naturalness")],
            }[repo]:
                if (path / rel).is_dir():
                    self.provider_paths.append(str(path / rel))
                    modules[module] = str(path)
        env = runtime.clean_env()
        env["PYTHONPATH"] = os.pathsep.join(self.provider_paths)
        probe = (
            "import importlib.util,json; print(json.dumps({m:importlib.util.find_spec(m).origin for m in "
            + repr(list(modules))
            + "}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        origins = json.loads(result.stdout)
        for module, path in origins.items():
            if not Path(path).resolve().is_relative_to(Path(modules[module]).resolve()):
                raise RuntimeError(
                    "Installed package would shadow frozen provider: " + module
                )
        self.servers = load(
            root / "components/execution/v4/servers.py", "m13_server_lifecycle_" + key
        ).Servers(self.context)
        self.started = False
        producers = sorted(
            {s["provider_repo"] for s in self.plan}
            | {self.native_manifest["owner_repo"]}
        )
        self.roots = {repo: str(self.context.root(repo)) for repo in producers}
        self.metadata = dict(
            delegate=key,
            native_owner=self.native_manifest["owner_repo"],
            native_experiment=self.native_manifest["experiment_id"],
            native_protocol=self.native_manifest["protocol_id"],
            native_run_id=self.context.run_id,
            recipe_source_commit=binding["commit"],
            recipe_runner_sha256=runtime.sha(runner),
            recipe_sha256=runtime.sha(home / "src/protocol.py"),
            native_dependency_lock=self.context.lock,
            configuration=config,
            executable_plan=self.plan,
            import_origins=origins,
            output_roots=self.roots,
            output_mode="DIRECT_REBOUND_NATIVE_PLAN__ORIGINAL_SCIENCE_UNCHANGED",
            shared_staging_policy="Unsealed protocol working files are registered at final seal; stable declared stage receipts remain separately bound",
        )
        self.metadata["profile_preflight"] = profile_check
        context.setdefault("native_metadata", []).append(self.metadata)
        context.setdefault("output_ownership", []).extend(
            dict(
                relative_prefix=str(Path(path).relative_to(context["root"])),
                producer=repo,
            )
            for repo, path in self.roots.items()
        )

    def start(self):
        if self.started:
            return
        for path in self.roots.values():
            for rel in ["inputs", "logs"]:
                (Path(path) / rel).mkdir(parents=True, exist_ok=False)
        owner = Path(self.roots[self.native_manifest["owner_repo"]])
        runtime.exclusive_json(owner / "inputs/producer_roots.json", self.roots)
        runtime.exclusive_json(owner / "inputs/native_context.json", self.metadata)
        self.started = True

    def environment(self):
        env = runtime.clean_env()
        env["PYTHONPATH"] = os.pathsep.join(self.provider_paths)
        for repo, name in {
            "storygen-rewrite": "STORYGEN_REWRITE_DEPOT_ROOT",
            "storygen-feature-extraction": "STORYGEN_FEATURE_DEPOT_ROOT",
            "storygen-evaluation": "STORYGEN_EVALUATION_DEPOT_ROOT",
            "storygen-naturalness": "STORYGEN_NATURALNESS_DEPOT_ROOT",
        }.items():
            env[name] = str(self.central["root"])
        temp = self.central["root"] / "inputs/tmp"
        temp.mkdir(exist_ok=True)
        env["TMPDIR"] = str(temp)
        return env

    def execute(self, stage, run_command):
        self.start()
        native = self.by_id[stage["adapter"]["native_stage"]]
        if native.get("server_profile") and self.context.config.get(
            "manage_servers", False
        ):
            self.servers.ensure(native["server_profile"])
        result = run_command(
            self.central,
            stage,
            native["command"],
            self.context.source(native["provider_repo"]),
            self.environment(),
        )
        output = self.context.output(native["provider_repo"], native["stage_id"])
        files = []
        for path in sorted(output.rglob("*")):
            if path.is_symlink():
                raise RuntimeError("Native scientific output contains a symlink")
            if path.is_file():
                files.append(
                    dict(
                        path=str(path.relative_to(self.central["root"])),
                        sha256=runtime.sha(path),
                        bytes=path.stat().st_size,
                    )
                )
        if not files:
            raise RuntimeError("Native stage produced no scientific artifacts")
        receipt = dict(
            status="COMPLETE",
            native_stage_id=native["stage_id"],
            native_owner=self.native_manifest["owner_repo"],
            native_protocol_id=self.native_manifest["protocol_id"],
            native_recipe_commit=self.metadata["recipe_source_commit"],
            command_sha256=runtime.canonical(native["command"]),
            outputs=files,
            scientific_validity="UNVERIFIED",
        )
        runtime.exclusive_json(
            self.central["root"] / "stages" / stage["stage_id"] / "raw/result.json",
            receipt,
        )
        return {**result, "native": receipt, "output_mode": "DIRECT_CENTRAL_RUN"}

    def stop(self):
        self.servers.stop()
