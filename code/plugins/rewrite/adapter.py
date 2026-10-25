"""Retained rewriting algorithms; no reimplementation of scientific methods."""

from pathlib import Path
from storygen_platform.engine.common import StoryGenError
from storygen_platform.engine.science_io import call_declared

SOURCES = {
    "storygen": "plugins/rewrite/historical/rewrite/src",
    "storygen_feature": "plugins/feature_extraction/historical/feature_extraction/src",
    "storygen_measurement_core": "plugins/feature_extraction/historical/measurement/src",
    "storygen_evaluation": "plugins/evaluation/historical/evaluation/src",
}
CALLS = {
    "run_taskset": (
        "storygen.rewrite_v1_3.runner:run_taskset",
        ("taskset_path", "feature_set_manifest", "model_file", "server_manifest"),
    ),
    "run_no_guidance": ("storygen.rewrite_v1_3.no_guidance:run_ng", ()),
    "matched_prompt_compare": ("storygen.rewrite_v1_3.matched_prompt:compare_pair", ()),
    "repeatability_select": ("storygen.rewrite_v1_3.repeatability:select_tasks", ()),
}


def execute(capability, inputs, context):
    root = Path(__file__).resolve().parents[2]
    if (
        capability.startswith("reviewer_")
        or "__" in capability
        and capability.split("__", 1)[0]
        in {"e03_repeatability", "e03_dp48_extension", "e04_matched_prompt"}
    ):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_sg_reviewer_protocols", Path(__file__).with_name("protocols.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stage = capability.removeprefix("reviewer_")
        if "__" in capability:
            protocol, stage = capability.split("__", 1)
            if context.configuration.get("protocol") != protocol:
                raise StoryGenError("Reviewer capability and frozen protocol differ")
        return module.execute(stage, inputs, context)
    if capability == "rewrite_frozen_taskset":
        return frozen_taskset(inputs, context)
    if capability not in CALLS:
        raise StoryGenError("Native capability binding not yet compiled: " + capability)
    entry, paths = CALLS[capability]
    supplied = {}
    if capability == "run_taskset":
        supplied = {
            "project_root": root / "plugins/rewrite/historical",
            "output_root": Path(context.artifact_directory),
        }
    return call_declared(
        root,
        SOURCES,
        entry,
        inputs["request"],
        context=context,
        path_parameters=paths,
        supplied=supplied,
    )


def frozen_taskset(inputs, context):
    """One original full-taskset DP/CG call; whole-stage checkpoint declared."""
    from storygen_platform.engine.common import read, file_sha

    root = Path(__file__).resolve().parents[2]
    taskset = inputs["taskset"]
    reference = inputs["reference"]
    for ref in [taskset, reference]:
        if file_sha(ref["path"]) != ref["sha256"]:
            raise StoryGenError("Native immutable input changed")
    role = context.node["model_role"]
    actual = context.profile["roles"][role]
    frozen = read(root / "plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json")
    profiles = [
        p
        for p in frozen["rewrite"]
        if p["model_sha256"].removeprefix("sha256:") == actual["sha256"]
        and p["quantization"] == actual["quantization"]
        and p["model_alias"] == actual["identity"]
    ]
    if len(profiles) != 1:
        raise StoryGenError("Rewrite runtime has no exact original TasksetV5 profile")
    profile = profiles[0]
    server = Path(context.artifact_directory) / "canonical_server.json"
    server.write_text(__import__("json").dumps(profile, indent=2) + "\n")
    strategy = context.configuration["strategy"]
    if strategy not in {"DP-v1", "CG-v1"}:
        raise StoryGenError("Original DP-v1/CG-v1 strategy required")
    params = context.resolved[role]["parameters"]
    if params.get("temperature") != 0.2 or params.get("max_tokens") != 4096:
        raise StoryGenError("Original TasksetV5 rewrite decoding differs")
    run_id = "tasksetv5_rwv1_3_" + context.store.root.name + "_" + strategy
    result = call_declared(
        root,
        SOURCES,
        CALLS["run_taskset"][0],
        {
            "taskset_path": Path(taskset["path"]),
            "feature_set_manifest": Path(reference["path"]),
            "run_id": run_id,
            "model": profile["model_alias"],
            "model_file": Path(actual["model_path"]),
            "quantization": profile["quantization"],
            "server_manifest": server,
            "strategy": strategy,
            "base_url": profile["base_url"],
            "temperature": 0.2,
            "schema_retry_count": 1,
            "max_tokens": 4096,
            "concurrency": profile["parallel_slots"],
            "timeout": profile["timeout_seconds"],
        },
        context=context,
        supplied={
            "project_root": root / "plugins/rewrite/historical",
            "output_root": Path(context.artifact_directory),
        },
    )["result"]
    path = Path(context.artifact_directory) / run_id / "rewrite_run_manifest.json"
    return {
        "rewrite": {
            "path": str(path),
            "sha256": file_sha(path),
            "strategy": strategy,
            "model": profile["model_alias"],
            "native_artifacts": result["native_artifacts"],
            "summary": result["value"],
        }
    }


def preflight_native(capability, *, node, profile, definition):
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    path = root / "plugins/native_support/runtime_binding.py"
    spec = importlib.util.spec_from_file_location("_sg_native_runtime_binding", path)
    binding = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(binding)
    return binding.qualify(
        root,
        profile["roles"][node["model_role"]],
        kind="measurement"
        if capability == "reviewer_remeasure" or capability.endswith("__remeasure")
        else "rewrite",
    )
