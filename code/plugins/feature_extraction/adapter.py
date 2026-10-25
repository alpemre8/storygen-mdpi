"""Call the retained canonical/independent feature extraction implementations."""

from pathlib import Path
from storygen_platform.engine.common import StoryGenError
from storygen_platform.engine.science_io import call_declared

SOURCES = {
    "storygen_feature": "plugins/feature_extraction/historical/feature_extraction/src",
    "storygen_measurement_core": "plugins/feature_extraction/historical/measurement/src",
}
CALLS = {
    "extract_feature_set": (
        "storygen_feature.extractor:extract_feature_set",
        (
            "film_set_path",
            "input_root",
            "model_file",
            "server_manifest",
            "protocol_path",
            "scene_selection_path",
        ),
    ),
    "extract_rewritten_feature_set": (
        "storygen_feature.rewritten:extract_rewritten_feature_set",
        (
            "rewrite_run",
            "reference_feature_set_manifest",
            "taskset_runtime",
            "model_file",
            "server_manifest",
            "protocol_path",
        ),
    ),
    "run_reliability": (
        "storygen_feature.reliability:run_reliability",
        ("scene_manifest", "output", "model_file", "server_manifest"),
    ),
    "attest_existing_feature_set": (
        "storygen_feature.attestation:attest_existing_feature_set",
        (
            "feature_store_root",
            "legacy_feature_set_manifest",
            "legacy_feature_store_manifest",
            "film_set_path",
            "registry_path",
            "model_file",
            "server_manifest",
            "output_dir",
        ),
    ),
    "qualify_independent": ("storygen_feature.independent:run_smoke", ()),
}


def execute(capability, inputs, context):
    if capability in {"e01_independent_preflight", "e01_independent_qualify"}:
        import importlib.util

        if (
            capability == "e01_independent_qualify"
            and inputs["preparation"]["value"]["status"] != "DRY_RUN_VALIDATED"
        ):
            raise StoryGenError("Original independent E01 input preparation must pass first")
        spec = importlib.util.spec_from_file_location(
            "_sg_native_e01", Path(__file__).with_name("e01.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.independent(
            inputs, context, dry_run=capability == "e01_independent_preflight"
        )
    if capability == "e01_canonical_remeasure":
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_sg_native_e01", Path(__file__).with_name("e01.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.canonical(inputs, context)
    if capability == "reliability_frozen":
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_sg_native_reliability", Path(__file__).with_name("reliability.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.execute(inputs, context)
    root = Path(__file__).resolve().parents[2]
    if capability == "extract_original":
        return extract_original(inputs, context)
    if capability == "remeasure_frozen_rewrite":
        return remeasure_frozen(inputs, context)
    if capability not in CALLS:
        raise StoryGenError("Native capability binding not yet compiled: " + capability)
    entry, paths = CALLS[capability]
    params = dict(inputs["request"])
    supplied = {}
    fe = root / "plugins/feature_extraction/historical"
    core = fe / "measurement"
    if capability in {"extract_feature_set", "extract_rewritten_feature_set"}:
        supplied = {
            "project_root": fe,
            "core_root": core,
            "output_root": Path(context.artifact_directory),
        }
        if capability == "extract_feature_set":
            supplied["block_root"] = fe / "feature_extraction"
    return call_declared(
        root, SOURCES, entry, params, context=context, path_parameters=paths, supplied=supplied
    )


def remeasure_frozen(inputs, context):
    from storygen_platform.engine.common import file_sha, read

    root = Path(__file__).resolve().parents[2]
    fe = root / "plugins/feature_extraction/historical"
    runtime, reference, rewrite = (inputs[k] for k in ["taskset", "reference", "rewrite"])
    for ref in [runtime, reference, rewrite]:
        if file_sha(ref["path"]) != ref["sha256"]:
            raise StoryGenError("Native immutable input changed")
    actual = context.profile["roles"][context.node["model_role"]]
    profile = read(
        root / "plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json"
    )["measurement"]
    if (
        actual["sha256"] != profile["model_sha256"].removeprefix("sha256:")
        or actual["identity"] != profile["model_alias"]
    ):
        raise StoryGenError("Canonical measurement model replacement refused")
    server = Path(context.artifact_directory) / "canonical_server.json"
    server.write_text(__import__("json").dumps(profile, indent=2) + "\n")
    feature_id = "fs_fev1_4_" + context.store.root.name + "_" + rewrite["strategy"]
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_sg_historical_lookup", root / "plugins/native_support/historical_lookup.py"
    )
    lookup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lookup)
    result = call_declared(
        root,
        SOURCES,
        CALLS["extract_rewritten_feature_set"][0],
        {
            "rewrite_run": Path(rewrite["path"]).parent,
            "reference_feature_set_manifest": Path(reference["path"]),
            "taskset_runtime": Path(runtime["path"]),
            "feature_set_id": feature_id,
            "model_file": Path(actual["model_path"]),
            "server_manifest": server,
            "protocol_path": Path("configs/feature_measurement_v1.yaml"),
            "concurrency": 8,
            "progress_mode": "never",
        },
        context=context,
        lookup_scope=lookup.for_context(context, "measurement"),
        supplied={
            "project_root": fe,
            "core_root": fe / "measurement",
            "output_root": Path(context.artifact_directory),
        },
    )["result"]
    path = Path(context.artifact_directory) / feature_id / "feature_set_manifest.json"
    return {
        "features": {
            "path": str(path),
            "sha256": file_sha(path),
            "strategy": rewrite["strategy"],
            "model": rewrite["model"],
            "native_artifacts": result["native_artifacts"],
            "summary": result["value"],
        }
    }


def extract_original(inputs, context):
    import json
    from collections import defaultdict
    from storygen_platform.engine.common import read, file_sha
    from storygen_platform.engine.science_io import science_scope

    root = Path(__file__).resolve().parents[2]
    fe = root / "plugins/feature_extraction/historical"
    request = dict(inputs["dataset"])
    actual = context.profile["roles"][context.node["model_role"]]
    profile = read(
        root / "plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json"
    )["measurement"]
    if (
        actual["sha256"] != profile["model_sha256"].removeprefix("sha256:")
        or actual["identity"] != profile["model_alias"]
    ):
        raise StoryGenError(
            "Original Feature Extraction must keep its canonical measurement identity"
        )
    server = Path(context.artifact_directory) / "canonical_server.json"
    server.write_text(json.dumps(profile, indent=2) + "\n")
    parameters = {
        "film_set_path": Path(request["film_set_path"]),
        "input_root": Path(request["input_root"]),
        "feature_set_id": "fs_mc1_1_fev1_4_" + context.store.root.name,
        "model_file": Path(actual["model_path"]),
        "server_manifest": server,
        "protocol_path": Path("configs/feature_measurement_v1.yaml"),
        "concurrency": 8,
        "progress_mode": "never",
    }
    if context.mode == "dev" and len(context.unit_members) != 938:
        grouped = defaultdict(list)
        for item in context.unit_members:
            grouped[item["film_id"]].append(item)
        selected = {}
        with science_scope({n: root / p for n, p in SOURCES.items()}):
            from storygen_feature.io import load_script

            for film, members in grouped.items():
                script = Path(request["input_root"]) / "films" / film / "script.json"
                _, scenes = load_script(script)
                ids = [
                    scenes[m["scene_ordinal"]]["scene_id"]
                    for m in sorted(members, key=lambda t: t["scene_ordinal"])
                ]
                selected[film] = {"script_sha256": "sha256:" + file_sha(script), "scene_ids": ids}
        films = read(parameters["film_set_path"])["films"]
        subset = Path(context.artifact_directory) / "DEV_FILM_SET.json"
        subset.write_text(
            json.dumps(
                {
                    "films": [f for f in films if f in selected],
                    "purpose": "DEV_EXPOSURE_ONLY",
                    "canonical_film_set": {
                        "path": str(parameters["film_set_path"]),
                        "sha256": file_sha(parameters["film_set_path"]),
                    },
                },
                indent=2,
            )
            + "\n"
        )
        selection = Path(context.artifact_directory) / "DEV_SCENE_SELECTION.json"
        selection.write_text(
            json.dumps(
                {
                    "contract_id": "storygen.scene-selection",
                    "contract_version": "1.0",
                    "films": selected,
                },
                indent=2,
            )
            + "\n"
        )
        parameters.update(film_set_path=subset, scene_selection_path=selection)
    result = call_declared(
        root,
        SOURCES,
        CALLS["extract_feature_set"][0],
        parameters,
        context=context,
        supplied={
            "project_root": fe,
            "block_root": fe / "feature_extraction",
            "core_root": fe / "measurement",
            "output_root": Path(context.artifact_directory),
        },
    )["result"]
    manifest = (
        Path(context.artifact_directory)
        / parameters["feature_set_id"]
        / "feature_set_manifest.json"
    )
    return {
        "reference": {"path": str(manifest), "sha256": file_sha(manifest)},
        "extraction": result,
    }


def preflight_native(capability, *, node, profile, definition):
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    path = root / "plugins/native_support/runtime_binding.py"
    spec = importlib.util.spec_from_file_location("_sg_native_runtime_binding", path)
    binding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(binding)
    return binding.qualify(root, profile["roles"][node["model_role"]], kind="measurement")


def preflight_e01(capability, *, node, profile, definition):
    import importlib.util
    from storygen_platform.engine.common import read, file_sha

    root = Path(__file__).resolve().parents[2]
    path = root / "plugins/native_support/runtime_binding.py"
    spec = importlib.util.spec_from_file_location("_sg_e01_binding", path)
    binding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(binding)
    source = (
        root
        / "plugins/feature_extraction/historical/components/measurement/e01_canonical_runtime/v1/server_profile.json"
    )
    return binding.qualify_exact(
        root, profile["roles"][node["model_role"]], read(source), source_identity=file_sha(source)
    )
