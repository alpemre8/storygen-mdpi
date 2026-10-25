"""Exact original E01 canonical and independent measurement; no regeneration of rewrites."""

from pathlib import Path
import importlib.util
import json
from storygen_platform.engine.common import file_sha, read, StoryGenError
from storygen_platform.engine.science_io import call_declared


def helper(root, name):
    path = root / "plugins/native_support" / (name + ".py")
    spec = importlib.util.spec_from_file_location("_sg_native_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(inputs, context):
    root = Path(__file__).resolve().parents[2]
    fe = root / "plugins/feature_extraction/historical"
    request = inputs["request"]
    for name in ["reference", "taskset", "rewrite"]:
        if file_sha(request[name]["path"]) != request[name]["sha256"]:
            raise StoryGenError("E01 immutable native input changed: " + name)
    locations = helper(root, "locations").Locations(root, context.depot_root)
    runtime = read(request["taskset"]["path"])
    for task in runtime["tasks"]:
        for key in ("source_script_path", "source_feature_path", "reference_feature_path"):
            if key in task:
                task[key] = locations.relocate(task[key])
    bound = Path(context.artifact_directory) / "BOUND_NATIVE_RUNTIME.json"
    bound.write_text(json.dumps(runtime, indent=2) + "\n")
    role = context.profile["roles"][context.node["model_role"]]
    strategy = context.configuration["strategy"]
    output_id = "fs_e01_" + context.store.root.name + "_" + strategy
    result = call_declared(
        root,
        {
            "storygen_feature": "plugins/feature_extraction/historical/feature_extraction/src",
            "storygen_measurement_core": "plugins/feature_extraction/historical/measurement/src",
        },
        "storygen_feature.rewritten:extract_rewritten_feature_set",
        {
            "project_root": fe,
            "core_root": fe / "measurement",
            "protocol_path": Path("configs/feature_measurement_mistral_f16_v1.yaml"),
            "rewrite_run": Path(request["rewrite"]["path"]).parent,
            "reference_feature_set_manifest": Path(request["reference"]["path"]),
            "taskset_runtime": bound,
            "feature_set_id": output_id,
            "output_root": Path(context.artifact_directory),
            "model_file": Path(role["model_path"]),
            "server_manifest": fe
            / "components/measurement/e01_canonical_runtime/v1/server_profile.json",
            "concurrency": 1,
            "remeasure_existing_rewrites": True,
            "progress_mode": "never",
        },
        context=context,
    )["result"]
    output = Path(context.artifact_directory) / output_id
    eligible = []
    for task in runtime["tasks"]:
        status = read(output / "tasks" / task["task_id"] / "measurement_status.json")
        if status["status"] == "measured" and status["contract_equality_verified"] is True:
            eligible.append(task["task_id"])
    return {
        "result": {
            **result,
            "parent_runtime": request["taskset"],
            "bound_runtime_sha256": file_sha(bound),
        },
        "observations": {
            "population_unit_ids": [t["task_id"] for t in runtime["tasks"]],
            "eligible_unit_ids": eligible,
            "source_records_sha256": file_sha(output / "feature_set_manifest.json"),
        },
    }


def independent(inputs, context, *, dry_run=False):
    """Original qualifier with explicit physical reference and owned argv bindings."""
    from storygen_platform.engine.science_io import (
        science_scope,
        invoke,
        persist_native_artifacts,
        invoke_file,
    )

    root = Path(__file__).resolve().parents[2]
    fe = root / "plugins/feature_extraction/historical"
    request = inputs["request"]
    for ref in request.values():
        if file_sha(ref["path"]) != ref["sha256"]:
            raise StoryGenError("E01 independent immutable instrument changed")
    locations = helper(root, "locations").Locations(root, context.depot_root)
    frozen_selection = read(request["selection"]["path"])
    canonical = {}

    def collect(value):
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                actual = locations.relocate(value["path"])
                if actual in canonical and canonical[actual] != value:
                    raise StoryGenError("Ambiguous E01 frozen logical reference")
                canonical[actual] = value
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(frozen_selection)
    roots = {
        "storygen_feature": fe / "feature_extraction/src",
        "storygen_measurement_core": fe / "measurement/src",
    }
    resolved = {}
    output = Path(context.artifact_directory) / "independent"
    try:
        with science_scope(roots, context=context):
            import storygen_feature.independent as original

            checked, reference, launch, template = (
                original.checked,
                original.reference,
                original.launch_args,
                original._verify_chat_template,
            )

            def bound_checked(ref):
                owned = Path(ref["path"]).resolve()
                physical = (
                    str(owned)
                    if owned.is_relative_to(Path(context.artifact_directory).resolve())
                    else locations.relocate(ref["path"])
                )
                result = checked({**ref, "path": physical})
                resolved[(ref["path"], str(result))] = ref["sha256"]
                return result

            def logical_reference(path):
                physical = str(Path(path).resolve())
                if physical in canonical:
                    bound_checked(canonical[physical])
                    return dict(canonical[physical])
                return reference(path)

            def owned_launch(protocol):
                command = launch(protocol)
                return [command[0], "--offline", *command[1:]]

            def exact_template(live_template, embedded_sha256):
                return invoke_file(
                    fe / "components/measurement/e01_runtime/v2/template_identity.py",
                    "compare",
                    {"live_template": live_template, "embedded_sha256": embedded_sha256},
                    context=context,
                )

            (
                original.checked,
                original.reference,
                original.launch_args,
                original._verify_chat_template,
            ) = bound_checked, logical_reference, owned_launch, exact_template
            try:
                value = invoke(
                    "storygen_feature.independent:run_smoke",
                    {
                        "core": fe / "measurement",
                        "profile": Path(request["profile"]["path"]),
                        "input_contract": Path(request["input_contract"]["path"]),
                        "selection_path": Path(request["selection"]["path"]),
                        "output": output,
                        "dry_run": dry_run,
                        "execute_inference": not dry_run,
                        "resume": False,
                    },
                    roots=roots,
                    context=context,
                )
                if not dry_run:
                    validation = invoke(
                        "storygen_feature.independent:validate_results",
                        {"output": output, "core": fe / "measurement"},
                        roots=roots,
                        context=context,
                    )
            finally:
                (
                    original.checked,
                    original.reference,
                    original.launch_args,
                    original._verify_chat_template,
                ) = checked, reference, launch, template
    finally:
        binding = {
            "version": "storygen.e01-owned-location-binding/3",
            "changes": [
                "Physical input lookup retains each exact frozen SHA and logical input_id",
                "Original launch argv gains offline flag; all scientific/runtime settings retained",
                "Exact historical template-identity/v2 LF comparator reused",
            ],
            "parents": request,
            "references": [
                {"recorded_path": old, "resolved_path": new, "sha256": sha}
                for (old, new), sha in sorted(resolved.items())
            ],
        }
        (Path(context.artifact_directory) / "E01_TECHNICAL_BINDING.json").write_text(
            json.dumps(binding, indent=2) + "\n"
        )
        artifacts = persist_native_artifacts(context)
    result = {
        "result": {
            "value": value,
            "native_artifacts": artifacts,
            "callable": "storygen_feature.independent:run_smoke",
        }
    }
    if not dry_run:
        result["native_checks"] = {
            "checks": [
                {
                    "name": "original_independent_validate_results",
                    "status": "PASS" if validation["valid"] else "FAIL",
                }
            ],
            "source_sha256": file_sha(output / "feature_set_manifest.json"),
        }
    return result
