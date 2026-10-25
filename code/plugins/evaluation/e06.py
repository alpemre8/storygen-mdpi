"""Original E06 descriptive pipeline, including A01–A07 and V01–V15, unchanged."""

from pathlib import Path
import importlib.util
from storygen_platform.engine.common import read, file_sha, StoryGenError
from storygen_platform.engine.science_io import (
    science_scope,
    standalone_scope,
    invoke_file,
    persist_native_artifacts,
)


def execute(inputs, context, *, operation="run"):
    root = Path(__file__).resolve().parents[2]
    home = root / "legacy/central/experiments/reviewer_round1/e06_statistical_robustness"
    request = inputs["request"]
    if hasattr(context, "unit_members") and len(context.unit_members) != 240:
        raise StoryGenError("Original E06 requires all 240 frozen tasks; subsets are forbidden")
    binding = Path(request["binding"])
    if file_sha(binding) != request["sha256"].removeprefix("sha256:"):
        raise StoryGenError("E06 immutable binding changed")
    if request.get("synthetic", False):
        raise StoryGenError("Synthetic science is available only through the original test fixture")
    spec = importlib.util.spec_from_file_location(
        "_sg_evaluation_relocation", Path(__file__).with_name("relocation.py")
    )
    relocation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relocation)
    locations = relocation.Locations(root, context.depot_root)
    output = Path(context.artifact_directory) / "e06"
    try:
        with science_scope(
            {"storygen_evaluation": root / "plugins/evaluation/historical/evaluation/src"},
            context=context,
        ):
            with relocation.resolver_scope(locations), standalone_scope(home / "src"):
                if operation == "preflight":
                    inputs, inventory = invoke_file(
                        home / "src/loader.py", "preflight", {"binding": binding}, context=context
                    )
                    value = {**inventory, "input_immutability": inputs.unchanged()}
                else:
                    value = invoke_file(
                        home / "src/pipeline.py",
                        "run",
                        {"root": output, "binding": binding, "compile_pdf": False},
                        context=context,
                    )
                    value["native_validation"] = read(output / "E06_VALIDATION.json")
                    value["native_summary"] = read(output / "E06_RESULTS_SUMMARY.json")
    finally:
        artifacts = persist_native_artifacts(context)
    result = {
        "result": {"value": value, "native_artifacts": artifacts, "callable": "E06_V1:" + operation}
    }
    if operation == "run":
        result["native_checks"] = {
            "checks": [
                {"name": key, "status": check["status"]}
                for key, check in value["native_validation"]["checks"].items()
            ],
            "source_sha256": file_sha(output / "E06_VALIDATION.json"),
        }
    return result
