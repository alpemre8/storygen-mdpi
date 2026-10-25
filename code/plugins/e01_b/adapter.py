"""E01-B data plumbing; the original scorer, scheduler and TI/DA stay unchanged."""

from dataclasses import asdict
from pathlib import Path
import threading

from storygen_platform.engine.common import StoryGenError, read, file_sha, digest, write_json
from storygen_platform.engine.science_io import science_scope, persist_native_artifacts


def load(name):
    import importlib.util

    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_sg_e01_b_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def roots(root):
    return {
        "storygen_feature": root / "plugins/feature_extraction/historical/feature_extraction/src",
        "storygen_measurement_core": root / "plugins/feature_extraction/historical/measurement/src",
        "storygen_evaluation": root / "plugins/evaluation/historical/evaluation/src",
    }


def protocol(root):
    from storygen_measurement_core import MeasurementProtocol

    core = root / "plugins/feature_extraction/historical/measurement"
    qwen = MeasurementProtocol.load(core, "configs/feature_measurement_v1.yaml")
    mistral = MeasurementProtocol.load(
        core, root / "plugins/e01_b/feature_measurement_mistral_q4_v1.yaml"
    )
    if {k: v for k, v in qwen.config.items() if k != "model"} != {
        k: v for k, v in mistral.config.items() if k != "model"
    }:
        raise StoryGenError("E01-B may change only the measurement model")
    mistral.validate_legacy_parity()
    return mistral


def preflight_native(capability, *, node, profile, definition):
    root = Path(__file__).resolve().parents[2]
    with science_scope(roots(root)):
        p = protocol(root)
        from storygen_feature.precision import inspect_gguf, require_mistral_structure

        role = profile["roles"][node["model_role"]]
        if (
            role["sha256"] != p.model["model_sha256"].removeprefix("sha256:")
            or role["identity"] != p.model["alias"]
        ):
            raise StoryGenError("E01-B Mistral protocol/profile mismatch")
        evidence = inspect_gguf(role["model_path"], hash_file=False)
        require_mistral_structure(evidence)
        if (
            evidence["metadata"].get("general.file_type") != 15
            or "Q4_K" not in evidence["tensor_types"]
        ):
            raise StoryGenError("E01-B requires the actual Mistral Q4_K_M checkpoint")
        template = evidence["metadata"].get("tokenizer.chat_template")
        if not isinstance(template, str) or not template.strip():
            raise StoryGenError("Mistral embedded chat template required")
    source = read(root / "runtime_profiles/ComputerA.vulkan.yaml")["roles"]["measurement"]
    original, current = source["command"], role["command"]
    permitted = {original.index("--model") + 1, original.index("--alias") + 1}
    if len(original) != len(current) or any(
        a != b for i, (a, b) in enumerate(zip(original, current)) if i not in permitted
    ):
        raise StoryGenError("E01-B server settings must match original Qwen argv exactly")
    if source["executable_sha256"] != role["executable_sha256"]:
        raise StoryGenError("E01-B must use the original verified llama.cpp binary")


def execute(capability, inputs, context):
    if capability != "measure":
        raise StoryGenError("Unknown E01-B capability")
    root = Path(__file__).resolve().parents[2]
    io = load("inputs")
    path = Path(inputs["manifest"]["path"])
    if file_sha(path) != inputs["manifest"]["sha256"]:
        raise StoryGenError("E01-B input manifest hash changed")
    plan = read(path)
    phase = context.configuration["phase"]
    io.validate(plan, context.depot_root, phase)
    if {t["task_id"] for t in context.unit_members} != {t["task_id"] for t in plan["tasks"]}:
        raise StoryGenError("E01-B requires the complete frozen task population")
    output = Path(context.artifact_directory)
    with science_scope(roots(root), context=context):
        from storygen_feature.io import load_script
        from storygen_feature.scheduler import SceneJob, GlobalSceneScheduler
        from storygen_measurement_core import CanonicalFeatureScorer, MeasurementResult
        from storygen_measurement_core.client import OpenAICompatibleClient

        p = protocol(root)
        needed = {}
        for task in plan["tasks"]:
            for side in ("source", "reference"):
                needed.setdefault(task[side + "_film_id"], set()).update(task[side + "_scene_ids"])
        jobs = []
        for film, ids in sorted(needed.items()):
            _, scenes = load_script(io.checked(context.depot_root, plan["scripts"][film]))
            selected = [s for s in scenes if s["scene_id"] in ids]
            if len(selected) != len(ids):
                raise StoryGenError("Missing original source/reference scene")
            for scene in selected:
                jobs.append(
                    SceneJob(
                        "original:" + film + ":" + scene["scene_id"],
                        "original:" + film,
                        film,
                        scene["scene_id"],
                        scene["title"],
                        scene["text"],
                    )
                )
        for key in io.PHASES[phase]:
            group = plan["groups"][key]
            for task in plan["tasks"]:
                artifacts = group["task_artifacts"][task["task_id"]]
                if task["task_id"] in group["missing_rewrites"]:
                    continue
                scenes = read(io.checked(context.depot_root, artifacts["rewritten_scenes.json"]))[
                    "rewritten_scenes"
                ]
                for scene in scenes:
                    jobs.append(
                        SceneJob(
                            key + ":" + task["task_id"] + ":" + scene["scene_id"],
                            key + ":" + task["task_id"],
                            task["source_film_id"],
                            scene["scene_id"],
                            str(scene.get("title") or ""),
                            str(scene["content"]),
                        )
                    )

        checkpoint = context.store.root / "e01_b_checkpoints"
        checkpoint.mkdir(exist_ok=True)
        progress_path = context.store.root / "e01_b_progress.json"
        progress_lock = threading.Lock()
        completed = 0
        reused = 0
        import time

        started_at = time.monotonic()
        write_json(
            progress_path,
            {"completed": 0, "total": len(jobs), "reused": 0, "elapsed_seconds": 0},
            exclusive=False,
        )
        references = {}

        # Explicit per-scene durable records complement the unchanged native cache.
        # A started request without a result is ambiguous and requires a NEW run.
        class DurableScorer:
            def __init__(self, native):
                self.native = native
                self.protocol = native.protocol

            def _key(self, *args):
                return self.native._key(*args)

            def score_scene(self, **kw):
                nonlocal completed, reused
                identity = {"lock_sha256": context.lock_hash, "protocol": p.manifest(), **kw}
                key = digest(identity)
                record = checkpoint / (key + ".json")
                started = checkpoint / (key + ".started.json")
                # Identical scientific inputs may be shared across task jobs.
                guard = scene_locks[key]
                with guard:
                    if record.exists():
                        saved = read(record)
                        if saved["identity"] != identity or saved["sha256"] != digest(
                            saved["result"]
                        ):
                            raise StoryGenError("E01-B checkpoint identity/content changed")
                        result = MeasurementResult(**saved["result"])
                        resumed = True
                    else:
                        if started.exists():
                            raise StoryGenError(
                                "Ambiguous interrupted E01-B request; preserve this run and choose a NEW run ID"
                            )
                        write_json(started, {"identity": identity})
                        result = self.native.score_scene(**kw)
                        resumed = False
                        value = asdict(result)
                        write_json(
                            record, {"identity": identity, "result": value, "sha256": digest(value)}
                        )
                    with progress_lock:
                        references[key] = {"path": str(record), "sha256": file_sha(record)}
                        completed += 1
                        reused += int(resumed)
                        write_json(
                            progress_path,
                            {
                                "completed": completed,
                                "total": len(jobs),
                                "reused": reused,
                                "elapsed_seconds": time.monotonic() - started_at,
                            },
                            exclusive=False,
                        )
                    return result

            def flush_cache(self):
                self.native.flush_cache()

        # Native parser/retry/normalization and round-robin scheduler are reused.
        with OpenAICompatibleClient(
            p.model["base_url"], p.decoding["timeout_seconds"], 8
        ) as client:
            native = CanonicalFeatureScorer(p, client=client, use_cache=True)
            scene_locks = {
                digest(
                    {
                        "lock_sha256": context.lock_hash,
                        "protocol": p.manifest(),
                        "film_id": j.film_id,
                        "scene_id": j.scene_id,
                        "scene_title": j.scene_title,
                        "scene_text": j.scene_text,
                    }
                ): threading.Lock()
                for j in jobs
            }
            # Integrity errors must stop the stage, not become scheduler failures.
            for job in jobs:
                identity = {
                    "lock_sha256": context.lock_hash,
                    "protocol": p.manifest(),
                    "film_id": job.film_id,
                    "scene_id": job.scene_id,
                    "scene_title": job.scene_title,
                    "scene_text": job.scene_text,
                }
                key = digest(identity)
                record = checkpoint / (key + ".json")
                if record.exists():
                    saved = read(record)
                    if saved["identity"] != identity or saved["sha256"] != digest(saved["result"]):
                        raise StoryGenError("E01-B checkpoint identity/content changed")
                elif (checkpoint / (key + ".started.json")).exists():
                    raise StoryGenError("Ambiguous interrupted E01-B request; choose a NEW run ID")
            values, scheduling = GlobalSceneScheduler(
                scorer=DurableScorer(native),
                concurrency=8,
                label="E01-" + phase,
                progress_mode="never",
                telemetry_path=output / "telemetry.jsonl",
            ).run(jobs)
        by_job = {v.job.job_id: v for v in values}
        if context.raw_count == 0 and references:
            context.record_raw(
                {
                    "kind": "E01_B_VALIDATED_CHECKPOINT_REUSE",
                    "inference_performed": False,
                    "protocol_hash": p.protocol_hash,
                    "checkpoints": list(references.values()),
                    "original_attempt_raw_records": "preserved in this same run's stages/measure/raw.jsonl",
                }
            )
        originals = {}
        for film, ids in sorted(needed.items()):
            rows = []
            for sid in sorted(ids):
                item = by_job["original:" + film + ":" + sid]
                result = item.measurement
                row = {
                    "scene_id": sid,
                    "status": result.status,
                    "measurement_protocol_hash": p.protocol_hash,
                }
                if result.features:
                    row.update({p.legacy_keys[f]: result.features[f] for f in p.features})
                rows.append(row)
            originals[film] = rows
            write_json(output / "originals" / film / "scene_features_llm.json", rows)
        write_json(
            output / "originals/feature_set_manifest.json",
            {
                "contract_id": "storygen.feature-set",
                "contract_version": "1.4",
                "source": {
                    "type": "original",
                    "input_manifest_sha256": inputs["manifest"]["sha256"],
                },
                "measurement": p.manifest(),
            },
        )
        eligible = {t["task_id"] for t in plan["tasks"]}
        science = load("science")
        for key in io.PHASES[phase]:
            group = plan["groups"][key]
            task_records = []
            for task in plan["tasks"]:
                tid = task["task_id"]
                if tid in group["missing_rewrites"]:
                    task_records.append(
                        science.failure(task, "rewrite:historical_generation_incomplete", group)
                    )
                    continue
                target = output / key / "tasks" / tid
                target.mkdir(parents=True)
                artifacts = group["task_artifacts"][tid]
                import shutil

                shutil.copyfile(
                    io.checked(context.depot_root, artifacts["rewritten_scenes.json"]),
                    target / "rewritten_scenes.json",
                )
                measurements = [
                    by_job[key + ":" + tid + ":" + sid].measurement
                    for sid in task["source_scene_ids"]
                ]
                rows = []
                for sid, measured in zip(task["source_scene_ids"], measurements):
                    row = {"scene_id": sid}
                    if measured.features:
                        row.update({p.legacy_keys[f]: measured.features[f] for f in p.features})
                    rows.append(row)
                write_json(target / "rewritten_scene_features.json", rows)
                write_json(target / "measurement_records.json", [asdict(m) for m in measurements])
                write_json(
                    target / "measurement_status.json",
                    {
                        "status": "measured"
                        if all(m.status == "measured" for m in measurements)
                        else "measurement_ineligible",
                        "measurement": p.manifest(),
                        "generation_transfer_plan": artifacts["transfer_plan.json"],
                    },
                )
                try:
                    new_plan = science.evaluation_plan(
                        task,
                        originals[task["source_film_id"]],
                        originals[task["reference_film_id"]],
                        p.protocol_hash,
                    )
                    new_plan["generation_transfer_plan"] = artifacts["transfer_plan.json"]
                    write_json(target / "transfer_plan.json", new_plan)
                    row = science.evaluate(task, target, p.manifest(), group)
                except (KeyError, ValueError) as exc:
                    row = science.failure(
                        task, "independent_original_measurement:" + str(exc), group
                    )
                task_records.append(row)
            write_json(output / key / "evaluation_task_records.json", task_records)
            write_json(
                output / key / "feature_set_manifest.json",
                {
                    "contract_id": "storygen.feature-set",
                    "contract_version": "1.4",
                    "source": {"type": "rewritten", "rewrite_manifest": group["rewrite_manifest"]},
                    "measurement": p.manifest(),
                },
            )
            eligible.intersection_update(r["task_id"] for r in task_records if r["metric_eligible"])
        write_json(
            output / "PROVENANCE.json",
            {
                "phase": phase,
                "inputs": inputs["manifest"],
                "measurement": p.manifest(),
                "scheduler": scheduling,
                "checkpoint_references": list(references.values()),
                "generation_targets_unchanged": True,
            },
        )
    artifacts = persist_native_artifacts(context)
    return {
        "result": {"phase": phase, "path": str(output), "native_artifacts": artifacts},
        "observations": {
            "population_unit_ids": [t["task_id"] for t in plan["tasks"]],
            "eligible_unit_ids": sorted(eligible),
            "source_records_sha256": file_sha(output / "PROVENANCE.json"),
        },
    }
