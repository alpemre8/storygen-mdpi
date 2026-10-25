"""Original E05 four-feature-difference stages; only physical input lookup changes."""

from pathlib import Path
import importlib
import importlib.util
import jsonschema
from storygen_platform.engine.common import read, file_sha, write_json, StoryGenError
from storygen_platform.engine.science_io import (
    science_scope,
    standalone_scope,
    invoke_file,
    persist_native_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "legacy/central/experiments/reviewer_round1/e05_4_feature_diff"


def execute(stage, inputs, context):
    request = inputs["request"]
    if file_sha(request["path"]) != request["sha256"].removeprefix("sha256:"):
        raise StoryGenError("E05 feature-difference immutable input changed")
    spec = importlib.util.spec_from_file_location(
        "_sg_feature_diff_locations", ROOT / "plugins/native_support/locations.py"
    )
    locations_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(locations_module)
    locations = locations_module.Locations(ROOT, context.depot_root)
    outputs = {s["stage_id"]: s["outputs"][0] for s in read(HOME / "pipeline.yaml")["stages"]}
    output = Path(context.artifact_directory) / outputs[stage]["path"]
    try:
        with science_scope({}, context=context), standalone_scope(HOME / "src"):
            if stage == "prepare":
                module = importlib.import_module("bindings")
                original = module.load_ref

                def relocated(ref):
                    # Retain the original logical ref inside the scientific data.
                    # The native loader still checks exact SHA and absence rules.
                    return original({**ref, "path": locations.relocate(ref["path"])})

                module.load_ref = relocated
                try:
                    value = invoke_file(
                        HOME / "src/bindings.py",
                        "prepare",
                        {"path": Path(request["path"])},
                        context=context,
                        module=module,
                    )
                finally:
                    module.load_ref = original
            elif stage == "validate":
                value = invoke_file(
                    HOME / "src/validate.py",
                    "validate",
                    {"prepared": read(request["path"])},
                    context=context,
                )
            elif stage == "analyze":
                data = read(request["path"])
                scenes, tasks = invoke_file(
                    HOME / "src/analyze.py", "calculate", {"validated": data}, context=context
                )
                value = invoke_file(
                    HOME / "src/aggregate.py",
                    "aggregate",
                    {"validated": data, "scene_rows": scenes, "task_rows": tasks},
                    context=context,
                )
            elif stage == "report":
                value = invoke_file(
                    HOME / "src/report.py",
                    "render",
                    {"output": output.parent, "data": read(request["path"])},
                    context=context,
                )
            else:
                raise StoryGenError("Unknown original E05 feature-difference stage")
            jsonschema.validate(value, outputs[stage]["schema"])
            if stage != "report":
                write_json(output, value)
    finally:
        artifacts = persist_native_artifacts(context)
    result = {
        "result": {"path": str(output), "sha256": file_sha(output), "native_artifacts": artifacts}
    }
    if stage == "report":
        result["native_checks"] = {
            "checks": [
                {
                    "name": "original_input_bindings_ready",
                    "status": "PASS" if value["input_bindings_ready"] else "FAIL",
                },
                {
                    "name": "original_real_analysis_complete",
                    "status": "PASS" if value["real_analysis_complete"] else "FAIL",
                },
            ],
            "source_sha256": file_sha(output),
        }
    return result
