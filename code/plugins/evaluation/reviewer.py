"""Relocatable binding of the original frozen A01–A10 reviewer pipeline."""

from pathlib import Path
import importlib.util
from storygen_platform.engine.common import file_sha, read, StoryGenError, write_json
from storygen_platform.engine.science_io import science_scope, invoke, persist_native_artifacts


def execute(inputs, context, *, preflight=False):
    root = Path(__file__).resolve().parents[2]
    request = inputs["request"]
    for name in ("plan", "tests"):
        if file_sha(request[name]["path"]) != request[name]["sha256"].removeprefix("sha256:"):
            raise StoryGenError("Original reviewer immutable input changed: " + name)
    spec = importlib.util.spec_from_file_location(
        "_sg_reviewer_relocation", Path(__file__).with_name("relocation.py")
    )
    relocation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relocation)
    locations = relocation.Locations(root, context.depot_root)
    receipt = read(request["tests"]["path"])
    for key in ("junit", "log"):
        receipt[key]["path"] = locations.relocate(receipt[key]["path"])
    for source in receipt["tested_source_files"]:
        source["path"] = locations.relocate(source["path"])
    derived = Path(context.artifact_directory) / "relocated_historical_test_receipt.json"
    write_json(
        derived,
        {
            **receipt,
            "relocation_parent": request["tests"],
            "qualification": "Historical test receipt only; current migration tests are separate evidence",
        },
    )
    roots = {"storygen_evaluation": root / "plugins/evaluation/historical/evaluation/src"}
    try:
        with science_scope(roots, context=context), relocation.resolver_scope(locations):
            from storygen_evaluation.provenance import load_artifact_overrides

            original_plan = read(request["plan"]["path"])
            overrides_file = locations.relocate(original_plan["artifact_overrides"]["path"])
            overrides = load_artifact_overrides(Path(overrides_file))
            tests = invoke(
                "storygen_evaluation.reviewer.pipeline:validate_test_receipt",
                {"path": derived},
                roots=roots,
                context=context,
            )
            if preflight:
                # Full strict canonical loader, no bootstrap/analysis and no inference.
                dataset = invoke(
                    "storygen_evaluation.reviewer.loader:load_dataset",
                    {"plan_path": Path(request["plan"]["path"]), "artifact_paths": overrides},
                    roots=roots,
                    context=context,
                )
                value = {
                    "status": "INPUTS_VERIFIED",
                    "validation": dataset.validation,
                    "models": dataset.models,
                    "task_count": len(dataset.tasks),
                    "historical_tests": {k: tests[k] for k in ["passed", "failed", "skipped"]},
                }
            else:
                value = invoke(
                    "storygen_evaluation.reviewer.pipeline:run_pipeline",
                    {
                        "plan_path": Path(request["plan"]["path"]),
                        "output": Path(context.artifact_directory) / "reviewer",
                        "artifact_paths": overrides,
                        "tests": tests,
                        "command": "storygen analyze reviewer_analysis (original frozen P01B protocol)",
                    },
                    roots=roots,
                    context=context,
                )
    finally:
        artifacts = persist_native_artifacts(context)
    result = {
        "result": {
            "value": value,
            "native_artifacts": artifacts,
            "callable": "storygen_evaluation.reviewer.pipeline:run_pipeline"
            if not preflight
            else "storygen_evaluation.reviewer.loader:load_dataset",
        }
    }
    if not preflight:
        status = read(Path(context.artifact_directory) / "reviewer/ANALYSIS_STATUS.json")
        result["native_checks"] = {
            "checks": [
                {"name": key, "status": row["status"]} for key, row in status["analyses"].items()
            ],
            "source_sha256": file_sha(
                Path(context.artifact_directory) / "reviewer/ANALYSIS_STATUS.json"
            ),
        }
    return result
