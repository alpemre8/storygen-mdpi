from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storygen_measurement_core import CanonicalFeatureScorer, MeasurementProtocol, validate_runtime_identity
from storygen_measurement_core.client import OpenAICompatibleClient
from storygen_measurement_core.preflight import assert_measurement_equal

from .io import load_script, materialize_rewritten_script, read_json, sha256_file, sha256_json, write_json
from .scheduler import GlobalSceneScheduler, SceneJob

OUTPUT_FILES = (
    "measurement_records.json",
    "rewritten_scene_features.json",
    "script_rewritten.json",
    "measurement_status.json",
    "feature_extraction_failure.json",
)


def _rewrite_hash(task_dir: Path) -> str:
    return sha256_json(
        {
            name: sha256_file(task_dir / name)
            for name in ("rewritten_scenes.json", "transfer_plan.json")
            if (task_dir / name).is_file()
        }
    )


def _resume_valid(
    task_dir: Path,
    *,
    protocol: MeasurementProtocol,
    source_task_dir: Path,
    expected_scene_ids: list[str],
) -> bool:
    try:
        status = read_json(task_dir / "measurement_status.json")
        if status.get("status") != "measured" or status.get("contract_equality_verified") is not True:
            return False
        assert_measurement_equal(protocol.manifest(), status.get("measurement") or {}, label="resume measurement")
        if status.get("source_rewrite_artifact_sha256") != _rewrite_hash(source_task_dir):
            return False
        rows = read_json(task_dir / "rewritten_scene_features.json")
        records = read_json(task_dir / "measurement_records.json")
        if [str(row.get("scene_id")) for row in rows] != expected_scene_ids:
            return False
        if [str(row.get("scene_id")) for row in records] != expected_scene_ids:
            return False
        return all(row.get("status") == "measured" for row in records)
    except Exception:
        return False


def _clear_outputs(task_dir: Path) -> None:
    for name in OUTPUT_FILES:
        path = task_dir / name
        if path.is_file():
            path.unlink()


def extract_rewritten_feature_set(
    *,
    project_root: Path,
    core_root: Path,
    protocol_path: Path,
    rewrite_run: Path,
    reference_feature_set_manifest: Path,
    taskset_runtime: Path,
    feature_set_id: str,
    output_root: Path,
    model_file: Path,
    server_manifest: Path,
    overwrite: bool = False,
    resume: bool = False,
    retry_failed_only: bool = False,
    dry_run: bool = False,
    progress_mode: str = "always",
    concurrency: int = 8,
    remeasure_existing_rewrites: bool = False,
    allow_server_queuing: bool = False,
) -> dict[str, Any]:
    """Measure rewritten scenes through the canonical Feature Extraction path.

    This function adapts Rewrite's task-oriented artifact layout into the same
    Measurement protocol, scorer, scheduler, legacy feature keys, and failure
    policy used for original-scene Feature Extraction.
    """

    if overwrite and resume:
        raise ValueError("--overwrite and --resume are mutually exclusive")
    if retry_failed_only:
        resume = True

    protocol = MeasurementProtocol.load(core_root, protocol_path)
    output = output_root / feature_set_id
    if (output / "feature_set_manifest.json").is_file():
        assert_measurement_equal(protocol.manifest(), read_json(output / "feature_set_manifest.json")["measurement"],
                                 label="existing output measurement")
    for status in output.glob("tasks/*/measurement_status.json"):
        assert_measurement_equal(protocol.manifest(), read_json(status)["measurement"], label="existing task measurement")
    if output.exists():
        if overwrite:
            shutil.rmtree(output)
        elif not resume:
            raise FileExistsError(f"Output exists: {output}; use --resume or --overwrite")
    output.mkdir(parents=True, exist_ok=True)
    (output / "tasks").mkdir(exist_ok=True)

    runtime = validate_runtime_identity(
        protocol,
        model_file=model_file,
        server_manifest=server_manifest,
        require_slots=concurrency,
        allow_server_queuing=allow_server_queuing,
    )
    reference_manifest = read_json(reference_feature_set_manifest)
    if (
        reference_manifest.get("contract_id") != "storygen.feature-set"
        or str(reference_manifest.get("contract_version")) != "1.4"
        or reference_manifest.get("attestation_verified") is not True
    ):
        raise RuntimeError("verified reference feature-set/1.4 manifest required")
    assert_measurement_equal(
        protocol.manifest(),
        reference_manifest.get("measurement", {}),
        label="source/reference feature-set",
    )

    rewrite_manifest_path = rewrite_run / "rewrite_run_manifest.json"
    rewrite_manifest = read_json(rewrite_manifest_path)
    if rewrite_manifest.get("contract_id") != "storygen.rewrite-run" or str(rewrite_manifest.get("contract_version")) != "1.3":
        raise RuntimeError("storygen.rewrite-run/1.3 required")
    generation_measurement = (rewrite_manifest.get("feature_set_manifest") or {}).get("measurement", {})
    if remeasure_existing_rewrites:
        # Existing rewrite text retains its generation lineage. Only the model
        # may differ; source/reference and rewritten scores share the new model.
        assert_measurement_equal(
            MeasurementProtocol.load(core_root, "configs/feature_measurement_v1.yaml").manifest(),
            generation_measurement, label="original generation feature-set")
        method_fields = ("measurement_protocol_id", "measurement_protocol_version", "instrument_hash",
                         "prompt_hash", "schema_hash", "system_instruction_hash", "request_contract_hash",
                         "decoding_hash", "decoding", "normalization", "failure_policy")
        expected = protocol.manifest()
        if any(generation_measurement.get(key) != expected.get(key) for key in method_fields):
            raise RuntimeError("Existing rewrite generation measurement method differs")
    else:
        assert_measurement_equal(reference_manifest["measurement"], generation_measurement,
                                 label="rewrite feature-set measurement")

    taskset = read_json(taskset_runtime)
    tasks = {str(task["task_id"]): task for task in taskset["tasks"]}
    states: dict[str, dict[str, Any]] = {}
    jobs: list[SceneJob] = []
    prepare_failures: list[dict[str, Any]] = []
    skipped_valid: list[str] = []
    retried_tasks: list[str] = []

    for order, (task_id, task) in enumerate(tasks.items()):
        source = rewrite_run / "tasks" / task_id
        target = output / "tasks" / task_id
        target.mkdir(exist_ok=True)
        expected = [str(scene_id) for scene_id in task["source_scene_ids"]]
        if resume and _resume_valid(
            target,
            protocol=protocol,
            source_task_dir=source,
            expected_scene_ids=expected,
        ):
            skipped_valid.append(task_id)
            continue
        if resume:
            retried_tasks.append(task_id)
            _clear_outputs(target)
        for name in ("task.json", "transfer_plan.json", "rewritten_scenes.json", "rewrite_summary.json", "phase_status.json"):
            if (source / name).exists():
                shutil.copy2(source / name, target / name)
        try:
            if not (source / "rewritten_scenes.json").is_file():
                raise RuntimeError("missing_rewrite_task")
            rewritten = read_json(source / "rewritten_scenes.json")
            scenes = rewritten.get("rewritten_scenes", [])
            returned = [str(scene.get("scene_id")) for scene in scenes]
            if returned != expected:
                raise RuntimeError("exact_scene_order_mismatch")
            raw, original = load_script(project_root / task["source_script_path"])
            by_id = {str(scene["scene_id"]): scene for scene in scenes}
            states[task_id] = {
                "order": order,
                "task": task,
                "destination": target,
                "source": source,
                "scenes": scenes,
                "by_id": by_id,
                "raw": raw,
                "original": original,
                "results": {},
            }
            for index, scene_id in enumerate(expected):
                scene = by_id[scene_id]
                jobs.append(
                    SceneJob(
                        f"{order:06d}:{index:04d}:{task_id}:{scene_id}",
                        task_id,
                        task["source_film_id"],
                        scene_id,
                        str(scene.get("title") or ""),
                        str(scene.get("content") or ""),
                        {"offset": index},
                    )
                )
        except Exception as exc:
            failure = {
                "task_id": task_id,
                "stage": "prepare",
                "root_cause_type": type(exc).__name__,
                "root_cause": str(exc),
            }
            prepare_failures.append(failure)
            write_json(target / "feature_extraction_failure.json", failure)

    if dry_run:
        return {
            "dry_run": True,
            "source_type": "rewritten",
            "feature_set_id": feature_set_id,
            "tasks_total": len(tasks),
            "tasks_skipped_valid_resume": len(skipped_valid),
            "tasks_to_process": len(states),
            "scene_jobs": len(jobs),
            "prepare_failures": prepare_failures,
        }

    scheduler_summary: dict[str, Any] = {"job_count": 0, "concurrency": concurrency}
    if jobs:
        with OpenAICompatibleClient(
            protocol.model["base_url"],
            float(protocol.decoding.get("timeout_seconds", 600)),
            concurrency,
        ) as client:
            scorer = CanonicalFeatureScorer(
                protocol,
                client=client,
                cache_path=output / "measurement_cache_v4.json",
                use_cache=True,
            )
            scheduled, scheduler_summary = GlobalSceneScheduler(
                scorer=scorer,
                concurrency=concurrency,
                label=f"feature-extraction {feature_set_id}",
                progress_mode=progress_mode,
                telemetry_path=output / "telemetry/extraction_requests.jsonl",
            ).run(jobs)
        for item in scheduled:
            states[item.job.group_id]["results"][item.job.scene_id] = item

    failures = list(prepare_failures)
    completed = 0
    for task_id, state in sorted(states.items(), key=lambda item: item[1]["order"]):
        rows = []
        records = []
        invalid = []
        for scene_id in state["task"]["source_scene_ids"]:
            item = state["results"].get(scene_id)
            if not item or item.measurement.status != "measured":
                invalid.append(
                    {
                        "scene_id": scene_id,
                        "root_cause_type": "measurement_request_failed",
                        "root_cause": None if not item else item.measurement.error,
                    }
                )
                continue
            measurement = item.measurement
            row = {
                "film_id": state["task"]["source_film_id"],
                "scene_id": scene_id,
                "title": str(state["by_id"][scene_id].get("title") or ""),
                "measurement_protocol_id": protocol.id,
                "measurement_protocol_hash": protocol.protocol_hash,
                "prompt_hash": protocol.prompt_hash,
                "schema_hash": protocol.schema_hash,
                "system_instruction_hash": protocol.system_hash,
                "request_contract_hash": protocol.request_contract_hash,
                "decoding_hash": protocol.decoding_hash,
            }
            for feature, key in protocol.legacy_keys.items():
                row[key] = measurement.features[feature]
            rows.append(row)
            records.append(
                {
                    "scene_id": scene_id,
                    "status": measurement.status,
                    "attempts": measurement.attempts,
                    "features": measurement.features,
                    "error": measurement.error,
                    "provenance": measurement.provenance,
                    "queue_wait_seconds": item.queue_wait_seconds,
                    "elapsed_seconds": item.elapsed_seconds,
                }
            )
        write_json(state["destination"] / "measurement_records.json", records)
        if invalid:
            failure = {
                "task_id": task_id,
                "stage": "measurement",
                "root_cause_type": "measurement_ineligible",
                "root_cause": "one_or_more_scenes_failed",
                "invalid_scenes": invalid,
            }
            failures.append(failure)
            write_json(state["destination"] / "feature_extraction_failure.json", failure)
            continue
        write_json(state["destination"] / "rewritten_scene_features.json", rows)
        write_json(
            state["destination"] / "script_rewritten.json",
            materialize_rewritten_script(state["raw"], state["original"], state["scenes"]),
        )
        write_json(
            state["destination"] / "measurement_status.json",
            {
                "status": "measured",
                "source_type": "rewritten",
                "measurement": protocol.manifest(),
                "source_feature_measurement": reference_manifest["measurement"],
                "generation_feature_measurement": generation_measurement,
                "remeasure_existing_rewrites": remeasure_existing_rewrites,
                "contract_equality_verified": True,
                "source_rewrite_artifact_sha256": _rewrite_hash(state["source"]),
                "scene_ids": list(state["task"]["source_scene_ids"]),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        completed += 1

    manifest = {
        "contract_id": "storygen.feature-set",
        "contract_version": "1.4",
        "block_version": "1.4.1",
        "feature_set_id": feature_set_id,
        "source": {
            "type": "rewritten",
            "rewrite_run": {
                "path": str(rewrite_run),
                "manifest_sha256": sha256_file(rewrite_manifest_path),
            },
            "reference_feature_set": {
                "path": str(reference_feature_set_manifest),
                "manifest_sha256": sha256_file(reference_feature_set_manifest),
            },
        },
        "measurement": protocol.manifest(),
        "generation_feature_measurement": generation_measurement,
        "remeasure_existing_rewrites": remeasure_existing_rewrites,
        "runtime_identity": runtime,
        "taskset": {
            "path": str(taskset_runtime),
            "sha256": sha256_file(taskset_runtime),
            "task_count": len(tasks),
        },
        "resume": {
            "enabled": resume,
            "retry_failed_only": retry_failed_only,
            "tasks_skipped_valid": len(skipped_valid),
            "skipped_task_ids": skipped_valid,
            "tasks_retried": len(retried_tasks),
            "retried_task_ids": retried_tasks,
        },
        "tasks_total": len(tasks),
        "tasks_completed": completed + len(skipped_valid),
        "tasks_failed": len(failures),
        "failures": failures,
        "scheduler": scheduler_summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "feature_set_manifest.json", manifest)
    if failures:
        raise RuntimeError(f"{len(failures)} rewritten Feature Extraction tasks failed; valid artifacts were preserved")
    return manifest
