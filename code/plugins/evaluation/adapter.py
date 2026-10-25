"""Delegate deterministic metrics to the exact preserved algorithm, without rewriting it."""

from pathlib import Path
import importlib.util
import importlib
import sys
from storygen_platform.engine.common import StoryGenError


def metrics_module():
    name = "_storygen_owned_evaluation"
    root = Path(__file__).parent / "historical/evaluation/src/storygen_evaluation"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, root / "__init__.py", submodule_search_locations=[str(root)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    return importlib.import_module(name + ".metrics")


def execute(capability, inputs, context):
    if capability.startswith("e05_diff_"):
        spec = importlib.util.spec_from_file_location(
            "_sg_native_feature_diff", Path(__file__).with_name("feature_diff.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.execute(capability.removeprefix("e05_diff_"), inputs, context)
    if capability in {"reviewer_preflight", "reviewer_run"}:
        spec = importlib.util.spec_from_file_location(
            "_sg_native_reviewer", Path(__file__).with_name("reviewer.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.execute(inputs, context, preflight=capability == "reviewer_preflight")
    if capability in {"e06_preflight", "e06_run"}:
        path = Path(__file__).with_name("e06.py")
        spec = importlib.util.spec_from_file_location("_sg_native_e06", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.execute(
            inputs, context, operation="preflight" if capability == "e06_preflight" else "run"
        )
    if capability == "evaluate_frozen_features":
        return evaluate_frozen(inputs, context)
    if capability == "native_mae":
        return {"score": metrics_module().mae(inputs["left"], inputs["right"])}
    if capability == "native_directional_accuracy":
        return {
            "score": metrics_module().directional_accuracy(
                inputs["before"], inputs["target"], inputs["after"]
            )
        }
    return scientific_call(capability, inputs, context)


SOURCES = {"storygen_evaluation": "plugins/evaluation/historical/evaluation/src"}
CALLS = {
    "evaluate_feature_sets": (
        "storygen_evaluation.feature_sets:evaluate_feature_sets",
        ("taskset_runtime", "reference_feature_set_manifest", "candidate_feature_set"),
    ),
    "evaluate_no_guidance": ("storygen_evaluation.ng_baseline:evaluate_ng", ()),
    "evaluate_dp48": ("storygen_evaluation.dp48_extension:evaluate_extended", ()),
    "evaluate_repeatability": ("storygen_evaluation.repeatability:evaluate", ()),
    "evaluate_matched_prompt": ("storygen_evaluation.matched_prompt:evaluate", ()),
    "evaluate_content_audit": ("storygen_evaluation.content_audit:evaluate", ()),
    "evaluate_sequential": ("storygen_evaluation.sequential_interval:evaluate", ()),
    "reviewer_analyses": (
        "storygen_evaluation.reviewer.pipeline:run_pipeline",
        ("plan_path", "output_dir"),
    ),
    "paired_summary": ("storygen_evaluation.analysis:paired_summary", ()),
    "cross_model_summary": ("storygen_evaluation.analysis:cross_model_summary", ()),
}


def scientific_call(capability, inputs, context):
    from storygen_platform.engine.science_io import call_declared

    if capability not in CALLS:
        raise StoryGenError("Native capability binding not yet compiled: " + capability)
    root = Path(__file__).resolve().parents[2]
    entry, paths = CALLS[capability]
    supplied = (
        {"output": Path(context.artifact_directory) / "evaluation"}
        if capability == "evaluate_feature_sets"
        else {}
    )
    return call_declared(
        root,
        SOURCES,
        entry,
        inputs["request"],
        context=context,
        path_parameters=paths,
        supplied=supplied,
    )


def evaluate_frozen(inputs, context):
    from storygen_platform.engine.common import file_sha
    from storygen_platform.engine.science_io import call_declared

    root = Path(__file__).resolve().parents[2]
    runtime, reference, features = (inputs[k] for k in ["taskset", "reference", "features"])
    for ref in [runtime, reference, features]:
        if file_sha(ref["path"]) != ref["sha256"]:
            raise StoryGenError("Native immutable input changed")
    spec = importlib.util.spec_from_file_location(
        "_sg_historical_lookup", root / "plugins/native_support/historical_lookup.py"
    )
    lookup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lookup)
    result = call_declared(
        root,
        SOURCES,
        CALLS["evaluate_feature_sets"][0],
        {
            "taskset_runtime": Path(runtime["path"]),
            "reference_feature_set_manifest": Path(reference["path"]),
            "candidate_feature_set": Path(features["path"]).parent,
            "method": features["strategy"],
            "model": features["model"],
        },
        context=context,
        lookup_scope=lookup.for_context(context, "evaluation"),
        supplied={"output": Path(context.artifact_directory) / "evaluation"},
    )["result"]
    manifest = Path(context.artifact_directory) / "evaluation/evaluation_run_manifest.json"
    import json

    records = [
        json.loads(line)
        for line in (manifest.parent / "evaluation_task_records.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return {
        "observations": {
            "population_unit_ids": [r["task_id"] for r in records],
            "eligible_unit_ids": [r["task_id"] for r in records if r["metric_eligible"]],
            "source_records_sha256": file_sha(manifest.parent / "evaluation_task_records.jsonl"),
        },
        "evaluation": {
            "path": str(manifest),
            "sha256": file_sha(manifest),
            "strategy": features["strategy"],
            "model": features["model"],
            "summary": result["value"]["summary"],
            "native_artifacts": result["native_artifacts"],
        },
    }
