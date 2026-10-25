"""Actual original TasksetV5 builder and validator, retained without algorithm edits."""

from pathlib import Path
from storygen_platform.engine.science_io import science_scope, invoke, persist_native_artifacts
from storygen_platform.engine.common import StoryGenError, file_sha, read


def execute(capability, inputs, context):
    root = Path(__file__).resolve().parents[2]
    roots = {"storygen_taskset": root / "plugins/rewrite/historical/taskset/src"}
    request = dict(inputs["request"])
    if capability == "build_taskset_runtime":
        parameters = {
            k: Path(request[k])
            for k in ["film_set_path", "input_root", "feature_set_manifest", "feature_set_root"]
        }
        parameters["output_root"] = Path(context.artifact_directory)
        with science_scope(roots, context=context):
            value = invoke(
                "storygen_taskset.builder:build_taskset_runtime",
                parameters,
                roots=roots,
                context=context,
            )
        artifacts = persist_native_artifacts(context)
        context.store.events.append(
            "NATIVE_ARTIFACTS_PERSISTED",
            stage_id=context.node["id"],
            unit_id=context.unit_id,
            attempt_id=context.attempt_id,
            artifacts=artifacts,
            lock_hash=context.lock_hash,
        )
        path = Path(value["output"])
        return {
            "taskset": {
                "path": str(path),
                "sha256": file_sha(path),
                "task_count": value["task_count"],
                "base_interval_count": value["base_interval_count"],
                "structure_sha256": value["validation"]["structure_sha256"],
                "validation": value["validation"],
                "native_artifacts": artifacts,
            }
        }
    if capability == "bind_taskset_runtime":
        from storygen_platform.engine.science_io import invoke_file

        path = Path(request["path"])
        if file_sha(path) != request["sha256"]:
            raise StoryGenError("Taskset artifact hash changed")
        selected = [t["task_id"] for t in context.unit_members]
        complete = len(selected) == request["task_count"]
        if not complete and context.mode != "dev":
            raise StoryGenError("Official TasksetV5 cannot select a verification subset")
        output = Path(context.artifact_directory) / "taskset_runtime.json"
        value = invoke_file(
            root / "plugins/rewrite/historical/components/tasksetv5/v1/bind_runtime.py",
            "bind",
            {
                "parent": path,
                "output": output,
                "selected_ids": None if complete else selected,
                "purpose": "RESEARCH" if complete else "MIGRATION_VERIFICATION",
            },
            context=context,
        )
        artifacts = persist_native_artifacts(context)
        return {
            "taskset": {
                "path": str(output),
                "sha256": file_sha(output),
                "task_count": len(value["tasks"]),
                "base_interval_count": len(value["base_intervals"]),
                "structure_sha256": value["structure_sha256"],
                "validation": {
                    "valid": True,
                    "canonical_parent": value["migration_binding"]["canonical_parent"],
                    "full_benchmark": value["migration_binding"]["full_benchmark"],
                },
                "native_artifacts": artifacts,
            }
        }
    if capability == "verify_taskset":
        path = Path(request["path"])
        if file_sha(path) != request["sha256"]:
            raise StoryGenError("Taskset artifact hash changed")
        with science_scope(roots, context=context):
            result = invoke(
                "storygen_taskset.builder:verify_taskset",
                {"payload": read(path)},
                roots=roots,
                context=context,
            )
        if not result["valid"]:
            raise StoryGenError(
                "Original TasksetV5 validator rejected input: " + repr(result["errors"])
            )
        return {"taskset": request}
    raise StoryGenError("Unknown Taskset capability: " + capability)
