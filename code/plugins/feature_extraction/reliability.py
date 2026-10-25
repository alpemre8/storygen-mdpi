"""Exact canonical 100-scene/five-repeat reliability protocol; location binding only."""

from pathlib import Path
import json
import importlib.util
from storygen_platform.engine.common import file_sha, read, StoryGenError
from storygen_platform.engine.science_io import call_declared


def execute(inputs, context):
    root = Path(__file__).resolve().parents[2]
    request = inputs["sample"]
    if file_sha(request["path"]) != request["sha256"]:
        raise StoryGenError("Frozen reliability scene sample changed")
    original = read(request["path"])
    spec = importlib.util.spec_from_file_location(
        "_sg_reliability_locations", root / "plugins/native_support/locations.py"
    )
    locations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(locations)
    resolver = locations.Locations(root, context.depot_root)
    relocated = [{**row, "script_path": resolver.relocate(row["script_path"])} for row in original]
    if hasattr(context, "unit_members") and {t["task_id"] for t in context.unit_members} != {
        r["film_id"] + "-" + r["scene_id"] for r in original
    }:
        raise StoryGenError("Canonical reliability sample cannot be reduced or substituted")
    sample = Path(context.artifact_directory) / "RELOCATED_SCENE_SAMPLE.json"
    sample.write_text(json.dumps(relocated, indent=2) + "\n")
    role = context.profile["roles"][context.node["model_role"]]
    canonical = read(
        root / "plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json"
    )["measurement"]
    server = Path(context.artifact_directory) / "CANONICAL_SERVER.json"
    server.write_text(json.dumps(canonical, indent=2) + "\n")
    output = Path(context.artifact_directory) / "reliability.json"
    result = call_declared(
        root,
        {
            "storygen_feature": "plugins/feature_extraction/historical/feature_extraction/src",
            "storygen_measurement_core": "plugins/feature_extraction/historical/measurement/src",
        },
        "storygen_feature.reliability:run_reliability",
        {
            "project_root": root / "plugins/feature_extraction/historical",
            "block_root": root / "plugins/feature_extraction/historical/measurement",
            "protocol_path": Path("configs/feature_measurement_v1.yaml"),
            "scene_manifest": sample,
            "output": output,
            "repeats": 5,
            "seed": 42,
            "progress_mode": "never",
            "concurrency": 8,
            "model_file": Path(role["model_path"]),
            "server_manifest": server,
            "allow_noncanonical_sample": False,
        },
        context=context,
    )["result"]
    value = result["value"]
    eligible = []
    for row in original:
        matches = [
            r
            for r in value["rows"]
            if r["film_id"] == row["film_id"] and r["scene_id"] == row["scene_id"]
        ]
        if len(matches) == 5 and all(r["status"] == "measured" for r in matches):
            eligible.append(row["film_id"] + "-" + row["scene_id"])
    return {
        "result": {**result, "input_parent": request},
        "observations": {
            "population_unit_ids": [r["film_id"] + "-" + r["scene_id"] for r in original],
            "eligible_unit_ids": eligible,
            "source_records_sha256": file_sha(output),
        },
    }
