"""Read-only, hash-bound inputs for the author-requested E01-B continuation.

Only preparation discovers paths. Execution reads the frozen depot manifest.
Original E01/E01B-F16 artifacts are parents, never output namespaces.
"""

from pathlib import Path
import importlib.util
import json

from storygen_platform.engine.common import StoryGenError, contained, file_sha, read, digest
from storygen_platform.historical import HistoricalCatalog, restricted

PHASES = {"B1": ["qwen_dp", "qwen_cg"], "B2": ["gemma_cg"], "B3": ["gemma_dp"]}
ALIASES = {"qwen": "qwen2.5-7b-q4", "gemma": "gemma3-12b-it-gguf"}
NAMES = {"qwen": "Qwen2.5-7B", "gemma": "Gemma-3-12B"}


def module(root, name):
    path = Path(root) / "plugins" / name
    spec = importlib.util.spec_from_file_location("_sg_e01_b_" + path.stem, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def checked(depot, ref):
    path = contained(depot, ref["path"])
    if restricted(path) or not path.is_file() or file_sha(path) != ref["sha256"]:
        raise StoryGenError("E01-B immutable open input missing/changed: " + ref["path"])
    return path


def records(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return read(path)


def exact_ids(rows, tasks):
    if [r["task_id"] for r in rows] != [t["task_id"] for t in tasks]:
        raise StoryGenError("E01-B frozen task IDs/order differ")


def prepare(root, depot):
    """Build a new metadata-only manifest from independently imported hash receipts."""
    root, depot = Path(root), Path(depot)
    locations = module(root, "native_support/locations.py").Locations(root, depot)
    catalog = HistoricalCatalog(depot)
    expected = {}
    for row in catalog.index["runs"]:
        receipt = catalog.select(row["run_id"])
        for artifact in receipt["artifacts"]:
            if artifact.get("access") == "sealed" or artifact.get("sealed"):
                continue
            key = artifact["relative_path"]
            if key in expected and expected[key]["sha256"] != artifact["sha256"]:
                raise StoryGenError("Conflicting historical byte receipts")
            expected[key] = {
                "sha256": artifact["sha256"],
                "historical_run_id": row["run_id"],
                "receipt_sha256": row["receipt_sha256"],
            }

    def ref(path):
        path = Path(locations.relocate(str(path))).resolve()
        if restricted(path) or not path.is_relative_to(depot.resolve()):
            raise StoryGenError("E01-B input outside open unified depot")
        relative = path.relative_to(depot.resolve()).as_posix()
        item = expected.get(relative)
        if item is None or file_sha(path) != item["sha256"]:
            raise StoryGenError("Input lacks matching imported hash receipt: " + relative)
        return {"path": relative, **item}

    def one(pattern):
        matches = list(depot.glob(pattern))
        if len(matches) != 1:
            raise StoryGenError(f"Expected one historical input: {pattern}; found {len(matches)}")
        return matches[0]

    rewrite_base = "migration/sources/storygen-rewrite-depot/runs"
    runtime = one(
        rewrite_base + "/01b-taskset/taskset_v5/runtimes/*10_films_balanced_v1/taskset_runtime.json"
    )
    frozen = read(runtime)
    tasks = frozen["tasks"]
    if len(tasks) != 240 or len({t["base_interval_id"] for t in tasks}) != 48:
        raise StoryGenError("Expected original TasksetV5 240 tasks / 48 bases")
    reference = ref(frozen["feature_set_manifest"])
    plan = {
        "contract": "storygen.e01-b-inputs/1",
        "runtime": ref(runtime),
        "reference": reference,
        "tasks": tasks,
        "scripts": {},
        "groups": {},
        "phases": PHASES,
        "origin": "NEW_USER_AUTHORIZED_CONTINUATION_NO_NEW_REWRITES",
    }
    for task in tasks:
        for side in ("source", "reference"):
            film = task[side + "_film_id"]
            if film not in plan["scripts"]:
                plan["scripts"][film] = ref(
                    depot
                    / "migration/sources/storygen-feature-extraction-depot/runs/_inputs/films"
                    / film
                    / "script.json"
                )
    for model in ("qwen", "gemma"):
        key = "qwen25_7b" if model == "qwen" else "gemma3_12b"
        for condition in ("dp", "cg"):
            rewrite = one(
                rewrite_base
                + f"/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/*_{key}_q4km_full240_singlepass*_{condition}_v1_v1/rewrite_run_manifest.json"
            )
            evaluation = one(
                f"migration/sources/storygen-evaluation-depot/runs/04-evaluation/eval_evv2_4_{key}_q4km_{condition}_v1/evaluation_run_manifest.json"
            )
            manifest = read(rewrite)
            served = manifest.get("model", {}).get("served_alias")
            if served != ALIASES[model]:
                raise StoryGenError("Wrong original rewrite model: " + str(served))
            group = {
                "model": NAMES[model],
                "alias": ALIASES[model],
                "condition": condition.upper() + "-v1",
                "rewrite_manifest": ref(rewrite),
                "baseline_manifest": ref(evaluation),
                "baseline_records": ref(evaluation.parent / "evaluation_task_records.jsonl"),
                "task_artifacts": {},
                "missing_rewrites": [],
            }
            for task in tasks:
                tid = task["task_id"]
                directory = rewrite.parent / "tasks" / tid
                artifacts = {
                    name: ref(directory / name)
                    for name in (
                        "rewritten_scenes.json",
                        "transfer_plan.json",
                        "phase_status.json",
                        "rewrite_summary.json",
                        "task.json",
                    )
                    if (directory / name).is_file()
                }
                group["task_artifacts"][tid] = artifacts
                if not {"rewritten_scenes.json", "transfer_plan.json"} <= set(artifacts):
                    group["missing_rewrites"].append(tid)
            plan["groups"][model + "_" + condition] = group
    fp = one(
        "migration/sources/storygen-feature-extraction-depot/runs/reviewer_round1/E01_MIN_mistral_f16/*/reports/T01_AUTHOR_EVALUATION/PROVENANCE.json"
    )
    parent = fp.parents[2]
    originals = one(
        str(parent.relative_to(depot)) + "/feature_sets/*originals*/feature_set_manifest.json"
    )
    after = one(
        str(parent.relative_to(depot)) + "/feature_sets/*gemma_cg*/feature_set_manifest.json"
    )
    plan["fp16"] = {
        "provenance": ref(fp),
        "records": ref(fp.parent / "MISTRAL_TASK_RECORDS.json"),
        "summary": ref(fp.parent / "T01_SUMMARY.json"),
        "original_manifest": ref(originals),
        "after_manifest": ref(after),
    }
    # Preserve all F16 artifacts used to establish the imported comparison's identity.
    plan["fp16"]["measurement_files"] = [
        ref(p) for p in sorted(originals.parent.glob("films/*/scene_features_llm.json"))
    ]
    for task in tasks:
        directory = after.parent / "tasks" / task["task_id"]
        for name in (
            "measurement_status.json",
            "rewritten_scene_features.json",
            "rewritten_scenes.json",
        ):
            if (directory / name).is_file():
                plan["fp16"]["measurement_files"].append(ref(directory / name))
    return plan


def all_refs(value):
    if isinstance(value, dict):
        if {"path", "sha256"} <= set(value):
            yield value
        else:
            for item in value.values():
                yield from all_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_refs(item)


def validate(plan, depot, phase=None):
    if plan.get("contract") != "storygen.e01-b-inputs/1" or plan["phases"] != PHASES:
        raise StoryGenError("Unsupported E01-B input manifest")
    group_keys = PHASES[phase] if phase else list(plan["groups"])
    selected_inputs = {
        "runtime": plan["runtime"],
        "reference": plan["reference"],
        "scripts": plan["scripts"],
        "groups": {k: plan["groups"][k] for k in group_keys},
    }
    if phase is None:
        selected_inputs["fp16"] = plan["fp16"]
    refs = {r["path"]: r for r in all_refs(selected_inputs)}
    for ref in refs.values():
        checked(depot, ref)
    tasks = plan["tasks"]
    if tasks != read(checked(depot, plan["runtime"]))["tasks"]:
        raise StoryGenError("Taskset membership changed")
    reference = read(checked(depot, plan["reference"]))
    native_io = module(
        Path(__file__).resolve().parents[2],
        "feature_extraction/historical/feature_extraction/src/storygen_feature/io.py",
    )
    film_ids = {}
    original_jobs = set()
    for film, ref in plan["scripts"].items():
        _, scenes = native_io.load_script(checked(depot, ref))
        ids = [s["scene_id"] for s in scenes]
        if len(set(ids)) != len(ids):
            raise StoryGenError("Duplicate original scene identity: " + film)
        film_ids[film] = set(ids)
    for task in tasks:
        for side in ("source", "reference"):
            film, ids = task[side + "_film_id"], task[side + "_scene_ids"]
            if len(set(ids)) != len(ids) or not set(ids) <= film_ids[film]:
                raise StoryGenError("Original source/reference scene alignment invalid")
            original_jobs.update((film, sid) for sid in ids)
    result = {}
    for key in group_keys:
        group = plan["groups"][key]
        manifest = read(checked(depot, group["baseline_manifest"]))
        rows = records(checked(depot, group["baseline_records"]))
        exact_ids(rows, tasks)
        if (
            manifest["measurement_identity"]["protocol_hash"]
            != reference["measurement"]["protocol_hash"]
            or manifest["rewrite_model"] != group["alias"]
            or manifest["method"] != group["condition"]
            or manifest["taskset"]["sha256"].removeprefix("sha256:") != plan["runtime"]["sha256"]
            or manifest["feature_set_manifest"]["sha256"].removeprefix("sha256:")
            != plan["reference"]["sha256"]
        ):
            raise StoryGenError("Qwen control identity/taskset mismatch: " + key)
        rewrites = read(checked(depot, group["rewrite_manifest"]))
        if (
            rewrites["model"]["served_alias"] != group["alias"]
            or rewrites["feature_set_manifest"]["measurement"] != reference["measurement"]
        ):
            raise StoryGenError("Generation instrument/model mismatch: " + key)
        good = 0
        scene_jobs = 0
        for task in tasks:
            artifacts = group["task_artifacts"][task["task_id"]]
            missing = not {"rewritten_scenes.json", "transfer_plan.json"} <= set(artifacts)
            if missing != (task["task_id"] in group["missing_rewrites"]):
                raise StoryGenError("Historical missing-task ledger mismatch")
            if missing:
                continue
            scenes = read(checked(depot, artifacts["rewritten_scenes.json"]))["rewritten_scenes"]
            if (
                [str(s.get("scene_id")) for s in scenes] != task["source_scene_ids"]
                or len({s["scene_id"] for s in scenes}) != len(scenes)
                or any(not str(s.get("content") or "").strip() for s in scenes)
            ):
                raise StoryGenError(
                    "Rewritten scene alignment invalid: " + key + "/" + task["task_id"]
                )
            transfer = read(checked(depot, artifacts["transfer_plan.json"]))
            if any(
                transfer.get(k) != task[k]
                for k in ("source_scene_ids", "reference_scene_ids", "selected_features")
            ):
                raise StoryGenError("Historical generation target alignment mismatch")
            good += 1
            scene_jobs += len(scenes)
        result[key] = {
            "attempted_tasks": len(tasks),
            "existing_rewrites": good,
            "missing_rewrites": group["missing_rewrites"],
            "qwen_metric_eligible": sum(r["metric_eligible"] for r in rows),
            "rewritten_scene_jobs": scene_jobs,
        }
    result_header = {
        "status": "PASS",
        "inference_performed": False,
        "files_verified": len(refs),
        "manifest_sha256": digest(plan),
        "groups": result,
        "original_scene_jobs": len(original_jobs),
        "phase_scene_jobs": {
            p: len(original_jobs) + sum(result[k]["rewritten_scene_jobs"] for k in keys)
            for p, keys in PHASES.items()
            if set(keys) <= set(result)
        },
    }
    if phase is not None:
        return result_header
    fp = plan["fp16"]
    provenance = read(checked(depot, fp["provenance"]))
    original = read(checked(depot, fp["original_manifest"]))
    after = read(checked(depot, fp["after_manifest"]))
    exact_ids(records(checked(depot, fp["records"])), tasks)
    if (
        original["measurement"] != after["measurement"]
        or provenance["protocol"] != original["measurement"]
        or original["measurement"]["model"]["quantization"] != "F16"
        or provenance["mistral_original_manifest_sha256"].removeprefix("sha256:")
        != fp["original_manifest"]["sha256"]
        or provenance["mistral_rewrite_manifest_sha256"].removeprefix("sha256:")
        != fp["after_manifest"]["sha256"]
        or provenance["qwen_control"]["rewrite_manifest"]["sha256"].removeprefix("sha256:")
        != plan["groups"]["gemma_cg"]["rewrite_manifest"]["sha256"]
    ):
        raise StoryGenError("Historical FP16 comparison lineage mismatch")
    return {**result_header, "fp16_records": len(records(checked(depot, fp["records"])))}
