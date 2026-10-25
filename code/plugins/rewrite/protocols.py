"""Technical binding of frozen reviewer protocols to the single active engine.

Original algorithms, selections, seeds and prompts stay in their owned historical
packages. Fresh stage outputs live under the current attempt; earlier artifacts
are read-only inputs. No original repository is a runtime dependency.
"""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import importlib
import importlib.util
import os
from storygen_platform.engine.common import read, write_json, file_sha, StoryGenError
from storygen_platform.engine.science_io import (
    science_scope,
    invoke,
    persist_native_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "storygen": ROOT / "plugins/rewrite/historical/rewrite/src",
    "storygen_feature": ROOT / "plugins/feature_extraction/historical/feature_extraction/src",
    "storygen_measurement_core": ROOT / "plugins/feature_extraction/historical/measurement/src",
    "storygen_evaluation": ROOT / "plugins/evaluation/historical/evaluation/src",
}


def locations(context):
    spec = importlib.util.spec_from_file_location(
        "_sg_protocol_locations", ROOT / "plugins/native_support/locations.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Locations(ROOT, context.depot_root, owned_roots=(context.store.root,))


def checked(ref):
    path = Path(ref["path"])
    if file_sha(path) != ref["sha256"].removeprefix("sha256:"):
        raise StoryGenError("Frozen reviewer protocol input changed: " + str(path))
    return path


def prepare(request, context):
    """Materialize a technical input snapshot, never copy any previous inference."""
    parent = checked(request)
    original = read(parent)
    loc = locations(context)
    target = Path(context.artifact_directory) / "protocol"
    target.mkdir()
    data = deepcopy(original)
    runtime_files = {r["path"] for r in original.get("models", {}).values()}
    runtime_files.update(
        original[k]["server_binary"] for k in ("gemma_server", "qwen_server") if k in original
    )
    runtime_files.update(
        original[k]["llama_cpp_root"]
        for k in ("gemma_server", "qwen_server")
        if k in original and "llama_cpp_root" in original[k]
    )
    logical_root = original["roots"]["rewrite"]
    prefixes = {logical_root + "/inputs": target / "inputs"}
    if original.get("hidden_plans"):
        prefixes[original["hidden_plans"]] = target / "hidden_plans/tasks"
    copied = []
    consumed = {}

    def verify_task_sources(payload):
        if not isinstance(payload, dict):
            return
        for task in payload.get("tasks", []):
            if not isinstance(task, dict):
                continue
            for key in ("source_script_path", "source_feature_path", "reference_feature_path"):
                recorded = task.get(key)
                if not recorded or recorded in consumed:
                    continue
                expected = original.get("protected", {}).get(recorded)
                actual = Path(loc.relocate(recorded))
                if expected is None or file_sha(actual) != expected.removeprefix("sha256:"):
                    raise StoryGenError("Frozen task source missing/changed: " + str(recorded))
                consumed[recorded] = {"resolved": str(actual), "sha256": expected}

    def relocate(value, field=None):
        if isinstance(value, list):
            return [relocate(v, field) for v in value]
        if isinstance(value, dict):
            return {k: relocate(v, k) for k, v in value.items()}
        if isinstance(value, str) and value.startswith("/"):
            # Request text, HTTP routes and historical command strings are not
            # file references, even when their text starts with a slash.
            path_fields = {
                "path",
                "file",
                "workspace",
                "rewrite",
                "feature",
                "evaluation",
                "generation",
                "reanalysis",
                "mapping",
                "base_runtime",
                "bound_taskset",
                "hidden_plans",
                "primary_requests",
                "frozen_plans",
                "records",
                "bindings",
                "text_diagnostics",
                "CG-v1",
                "DP-v1",
                "MP-DIR-v1",
                "MP-NUM-v1",
            }
            if field not in path_fields and not str(field).endswith(
                ("_path", "_root", "_manifest", "_output")
            ):
                return value
            if value in runtime_files or value == original["workspace"]:
                return value
            for old, new in sorted(prefixes.items(), key=lambda item: -len(item[0])):
                if value == old or value.startswith(old + "/"):
                    return str(new / Path(value).relative_to(old))
            return loc.relocate(value)
        return value

    for old, new in prefixes.items():
        source = Path(loc.relocate(old))
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            destination = new / path.relative_to(source)
            recorded = str(Path(old) / path.relative_to(source))
            expected = original.get("protected", {}).get(recorded)
            if expected is None or file_sha(path) != expected.removeprefix("sha256:"):
                raise StoryGenError("Original frozen protocol input missing/changed: " + recorded)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".json":
                payload = read(path)
                verify_task_sources(payload)
                write_json(destination, relocate(payload))
            else:
                destination.write_bytes(path.read_bytes())
            copied.append(
                {
                    "source": str(path),
                    "source_sha256": file_sha(path),
                    "resolved": str(destination),
                    "resolved_sha256": file_sha(destination),
                }
            )
    # E04 records the hash of the entire plan including physical locators. Only
    # those locator-derived hashes change; native prompt/seed hashes stay exact.
    primary = Path(relocate(original.get("primary_requests", ""), "primary_requests"))
    if primary.is_file():
        rows = read(primary)
        for row in rows:
            if "target_plan_hash" in row:
                plan = (
                    Path(relocate(original["frozen_plans"], "frozen_plans"))
                    / "tasks"
                    / row["task_id"]
                    / "transfer_plan.json"
                )
                row["target_plan_hash"] = "sha256:" + file_sha(plan)
        write_json(primary, rows, exclusive=False)
    # Protected was an old five-repo write-protection inventory, often including
    # caches and server logs. It remains verbatim in the parent. The new engine
    # seals its actual code closure and consumed immutable data independently.
    data = {k: relocate(v, k) for k, v in original.items() if k != "protected"}
    for name in ("reference", "frozen_taskset"):
        if name in data:
            checked(data[name])
    data["roots"] = {k: str(target / "outputs" / k) for k in original["roots"]}
    for directory in data["roots"].values():
        Path(directory).mkdir(parents=True)
    data["migration_binding"] = {
        "version": "reviewer-two-repo-location/1",
        "parent": request,
        "original_protected_entries": len(original.get("protected", {})),
        "copied_inputs": copied,
        "consumed_task_sources": consumed,
        "source_commits": original["source_commits"],
        "policy": "Original scientific values and request bodies retained; physical paths and owned output locations change under a new implementation lock",
    }
    if "experiment_id" in data:
        data["migration_binding"]["original_native_run_label"] = data["experiment_id"]
        data["experiment_id"] = context.store.root.name
    if data.get("contract") == "storygen.E04/1.0":
        from storygen.rewrite_v1_3.matched_prompt import prompt_provenance

        current = prompt_provenance()
        for name, ref in original["prompt_provenance"].items():
            if isinstance(ref, dict) and "sha256" in ref:
                if ref["sha256"] != current[name]["sha256"]:
                    raise StoryGenError("Original E04 prompt bytes changed")
        data["prompt_provenance"] = current
    return data


@contextmanager
def native_bundle(key, context):
    bundle = ROOT / "plugins/rewrite/historical/components/reviewer_protocols" / key / "v1"
    old_env = {
        k: os.environ.get(k)
        for k in ("STORYGEN_PROTOCOL_WORKSPACE", "STORYGEN_PROTOCOL_BACKEND_ROOT")
    }
    os.environ["STORYGEN_PROTOCOL_WORKSPACE"] = str(ROOT.parent)
    os.environ["STORYGEN_PROTOCOL_BACKEND_ROOT"] = str(
        Path(context.profile.get("roles", {}).get("rewriter", {}).get("executable", ROOT)).parents[
            2
        ]
    )
    try:
        role = context.profile.get("roles", {}).get(context.node.get("model_role"))
        endpoints = {}
        if role and role.get("native_profile", {}).get("base_url"):
            endpoints[role["native_profile"]["base_url"]] = (
                f"http://{role['host']}:{role['port']}/v1"
            )
            endpoints[role["native_profile"]["base_url"].removesuffix("/v1")] = (
                f"http://{role['host']}:{role['port']}"
            )
        with science_scope(
            {**SOURCES, "storygen_protocol_science": bundle}, context=context, endpoints=endpoints
        ):
            binding = importlib.import_module("storygen_protocol_science.bindings")
            binding.REWRITE = ROOT / "plugins/rewrite/historical"

            def bound_imports(workspace):
                for name, path in SOURCES.items():
                    module = importlib.import_module(name)
                    if not Path(module.__file__).resolve().is_relative_to(path):
                        raise StoryGenError(
                            "Scientific import escaped its exact owned provider: " + name
                        )

            binding.imports = bound_imports
            spec = importlib.util.spec_from_file_location(
                "_sg_protocol_resolver", ROOT / "plugins/evaluation/relocation.py"
            )
            relocation = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(relocation)
            with relocation.resolver_scope(locations(context)):
                yield bundle
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def owned_live(config, context, key):
    """Keep the original /proc, live props and (where present) port-owner checks."""
    module = importlib.import_module("storygen_protocol_science.technical")
    manager = getattr(context, "managed_runtime", None)
    if manager is None or manager.process is None or manager.process.poll() is not None:
        raise StoryGenError("Reviewer inference requires the foreground owned runtime manager")
    cfg = context.profile["roles"][context.node["model_role"]]
    original_command = module.server_command
    module.server_command = lambda server: cfg["command"]
    directory = Path(config["roots"]["rewrite"]) / "runtime"
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / ("SERVER_" + key.upper() + ".json")
    write_json(
        record,
        {"pid": manager.process.pid, "command": cfg["command"], "owner": context.store.root.name},
        exclusive=False,
    )
    try:
        yield module
    finally:
        module.server_command = original_command


def execute(stage, inputs, context):
    request = inputs["request"]
    key = context.configuration["protocol"]
    if key in {"e03_repeatability", "e03_dp48_extension", "e04_matched_prompt"}:
        return execute_repeated(stage, inputs, context)
    output = Path(context.artifact_directory)
    try:
        with native_bundle(key, context):
            config = prepare(request, context) if stage == "prepare" else read(checked(request))
            if key != "e02_no_guidance":
                raise StoryGenError("Reviewer protocol stage has not yet been compiled: " + key)
            from storygen_evaluation.provenance import (
                structure_sha,
                validate_reference,
                validate_runtime,
                validate_curves,
                ArtifactResolver,
            )
            from storygen.rewrite_v1_3.no_guidance import group_tasks

            if stage == "prepare" or stage == "preflight":
                tasks = read(config["bound_taskset"])["tasks"]
                reference = read(config["reference"]["path"])
                validate_reference(reference)
                validate_runtime(
                    read(config["bound_taskset"]),
                    reference,
                    Path(config["reference"]["path"]),
                    ArtifactResolver(),
                )
                paths = {t["source_script_path"]: Path(t["source_script_path"]) for t in tasks}
                units = group_tasks(tasks, paths)
                if structure_sha(tasks) != config["structure_sha256"] or len(units) != 48:
                    raise StoryGenError("Original E02 full population or base projection changed")
                from storygen_measurement_core import MeasurementProtocol
                from storygen_measurement_core.preflight import assert_measurement_equal

                protocol = MeasurementProtocol.load(
                    ROOT / "plugins/feature_extraction/historical/measurement",
                    "configs/feature_measurement_v1.yaml",
                )
                assert_measurement_equal(reference["measurement"], protocol.manifest())
                if config["measurement"] != protocol.manifest():
                    raise StoryGenError("Original E02 full measurement instrument changed")
                if units != read(config["mapping"])["units"]:
                    raise StoryGenError("Original E02 source-only mapping changed")
                validate_curves(
                    tasks,
                    Path(config["hidden_plans"]).parent,
                    Path(config["hidden_plans"]).parent,
                    Path(config["reference"]["path"]),
                    reference,
                    ArtifactResolver(),
                )
                # Every copied source has its exact original digest in the stage receipt.
                for control in config["controls"]:
                    for field in (
                        "rewrite_manifest",
                        "reanalysis_manifest",
                        "records",
                        "evaluation_manifest",
                    ):
                        checked(control[field])
                config["migration_binding"]["native_preflight"] = {
                    "tasks": len(tasks),
                    "base_intervals": len(units),
                    "scene_positions": sum(u["scene_positions"] for u in units),
                }
            elif stage == "generate":
                config["rewrite_output"] = str(output / "NG-v0")
                config["roots"] = {**config["roots"], "rewrite": str(output)}
                with owned_live(config, context, "gemma") as technical:
                    technical.live_runtime(config, "gemma")
                    from storygen.services.rewrite_engine import load_selected_scenes
                    from storygen.services.per_scene_rewrite_engine import (
                        build_per_scene_no_guidance_prompt,
                        one_scene_rewrite_schema_for,
                    )
                    from storygen.services.vllm_client import _messages

                    system = (
                        ROOT
                        / "plugins/rewrite/historical/rewrite/prompts/no_guidance_system_v0.txt"
                    ).read_text()
                    payloads = []
                    for unit in read(config["mapping"])["units"]:
                        scenes = load_selected_scenes(
                            unit["source_script_path"], unit["source_scene_ids"]
                        )
                        for i, scene in enumerate(scenes):
                            user = build_per_scene_no_guidance_prompt(
                                scene=scene, scene_position_index=i, scene_count=len(scenes)
                            )
                            payloads.append(
                                {
                                    "model": config["gemma_server"]["model_alias"],
                                    "stream": False,
                                    "temperature": 0.2,
                                    "max_tokens": 4096,
                                    "messages": _messages(
                                        system=system,
                                        prompt=user,
                                        model=config["gemma_server"]["model_alias"],
                                        structured=True,
                                    ),
                                    "response_format": {
                                        "type": "json_schema",
                                        "json_schema": {
                                            "name": "storygen_response",
                                            "strict": True,
                                            "schema": one_scene_rewrite_schema_for(scene.scene_id),
                                        },
                                    },
                                }
                            )
                    technical.context_check(
                        config["gemma_server"]["base_url"].removesuffix("/v1"),
                        payloads,
                        4096,
                        12288,
                    )
                    invoke(
                        "storygen.rewrite_v1_3.no_guidance:run_ng",
                        {"config": config},
                        roots=SOURCES,
                        context=context,
                    )
            elif stage == "remeasure":
                config["measurement_output"] = str(output / "ng_v0_fev1_4")
                config["roots"] = {**config["roots"], "rewrite": str(output)}
                with owned_live(config, context, "qwen") as technical:
                    technical.live_runtime(config, "qwen")
                    from storygen_measurement_core import (
                        MeasurementProtocol,
                        CanonicalFeatureScorer,
                    )
                    from storygen_measurement_core.client import build_request_payload
                    from storygen_measurement_core.preflight import validate_runtime_identity

                    core = ROOT / "plugins/feature_extraction/historical/measurement"
                    protocol = MeasurementProtocol.load(core, "configs/feature_measurement_v1.yaml")
                    validate_runtime_identity(
                        protocol,
                        model_file=config["models"]["qwen"]["path"],
                        server_manifest=config["qwen_manifest"],
                        require_slots=8,
                        require_live_server=True,
                    )
                    scorer = CanonicalFeatureScorer(protocol, use_cache=False)
                    payloads = []
                    for task in config["base_tasks"]:
                        path = (
                            Path(config["rewrite_output"])
                            / "tasks"
                            / task["task_id"]
                            / "rewritten_scenes.json"
                        )
                        if path.is_file():
                            for scene in read(path)["rewritten_scenes"]:
                                payloads.append(
                                    build_request_payload(
                                        prompt=scorer._render(
                                            task["source_film_id"],
                                            scene["scene_id"],
                                            scene["title"],
                                            scene["content"],
                                        ),
                                        model=protocol.model["alias"],
                                        schema=protocol.schema,
                                        decoding=protocol.decoding,
                                        system_instruction=protocol.system_instruction,
                                        response_schema_name=protocol.response_schema_name,
                                    )
                                )
                    technical.context_check(
                        config["qwen_server"]["base_url"].removesuffix("/v1"), payloads, 256, 12288
                    )
                    try:
                        invoke(
                            "storygen_feature.rewritten:extract_rewritten_feature_set",
                            {
                                "project_root": core.parent,
                                "core_root": core,
                                "protocol_path": Path("configs/feature_measurement_v1.yaml"),
                                "rewrite_run": Path(config["rewrite_output"]),
                                "reference_feature_set_manifest": Path(config["reference"]["path"]),
                                "taskset_runtime": Path(config["base_runtime"]),
                                "feature_set_id": "ng_v0_fev1_4",
                                "output_root": output,
                                "model_file": Path(config["models"]["qwen"]["path"]),
                                "server_manifest": Path(config["qwen_manifest"]),
                                "concurrency": 8,
                                "progress_mode": "never",
                            },
                            roots=SOURCES,
                            context=context,
                        )
                    except RuntimeError:
                        if not (
                            Path(config["measurement_output"]) / "feature_set_manifest.json"
                        ).is_file():
                            raise
            elif stage == "evaluate":
                config["evaluation_output"] = str(output / "evaluation")
                try:
                    invoke(
                        "storygen_evaluation.ng_baseline:evaluate_ng",
                        {"config": config},
                        roots=SOURCES,
                        context=context,
                    )
                finally:
                    # The original evaluator writes task/source views as links.
                    # Store portable exact-byte views; never weaken the engine's
                    # symlink rejection or allow links to another run/original repo.
                    spec = importlib.util.spec_from_file_location(
                        "_sg_native_views", ROOT / "plugins/native_support/artifacts.py"
                    )
                    materializer = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(materializer)
                    materializer.materialize_owned_views(context)
            else:
                raise StoryGenError("Unknown reviewer protocol stage")
            path = output / "PROTOCOL_CONFIG.json"
            write_json(path, config)
    finally:
        artifacts = persist_native_artifacts(context)
    return {"result": {"path": str(path), "sha256": file_sha(path), "native_artifacts": artifacts}}


def execute_repeated(stage, inputs, context):
    key = context.configuration["protocol"]
    try:
        with native_bundle(key, context) as bundle:
            config = (
                prepare(inputs["request"], context)
                if stage == "prepare"
                else read(checked(inputs["request"]))
            )
            spec = importlib.util.spec_from_file_location(
                "_sg_repeated_protocols", Path(__file__).with_name("repeated_protocols.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            config = module.execute_bound(
                key,
                stage,
                config,
                context,
                locations=locations(context),
                owned_live=owned_live,
                sources={**SOURCES, "storygen_protocol_science": bundle},
            )
            path = Path(context.artifact_directory) / "PROTOCOL_CONFIG.json"
            write_json(path, config)
    finally:
        artifacts = persist_native_artifacts(context)
    return {"result": {"path": str(path), "sha256": file_sha(path), "native_artifacts": artifacts}}
