from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BLOCK_VERSION = "1.0.0"
CONTRACT_ID = "storygen.taskset-runtime"
CONTRACT_VERSION = "1.0"
TASKSET_ID = "tasksetv5"
BUILDER_ID = "taskset_v5_evalv3_builder.v3_240_balanced_sml"
CANONICAL_STRUCTURE_SHA256 = "sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb"

EXPECTED_FILMS = [
    "chasing_amy",
    "ghostbusters_ii",
    "the_private_life_of_sherlock_holmes",
    "dog_day_afternoon",
    "apocalypse_now",
    "drag_me_to_hell",
    "up_2009",
    "darkman",
    "do_the_right_thing",
    "the_white_ribbon",
]

UNORDERED_PAIRS = [
    ("chasing_amy", "do_the_right_thing"),
    ("chasing_amy", "dog_day_afternoon"),
    ("chasing_amy", "up_2009"),
    ("ghostbusters_ii", "drag_me_to_hell"),
    ("ghostbusters_ii", "darkman"),
    ("ghostbusters_ii", "up_2009"),
    ("the_private_life_of_sherlock_holmes", "dog_day_afternoon"),
    ("the_private_life_of_sherlock_holmes", "the_white_ribbon"),
    ("dog_day_afternoon", "do_the_right_thing"),
    ("apocalypse_now", "darkman"),
    ("apocalypse_now", "the_white_ribbon"),
    ("apocalypse_now", "drag_me_to_hell"),
]

INTERVALS = {
    "short_cross": {"slot_id": "S_short_cross", "interval_type": "short", "length": 5, "source_anchor": 0.28, "reference_anchor": 0.62},
    "medium_cross": {"slot_id": "M_medium_cross", "interval_type": "medium", "length": 8, "source_anchor": 0.72, "reference_anchor": 0.34},
    "long_cross": {"slot_id": "L_long_cross", "interval_type": "long", "length": 12, "source_anchor": 0.18, "reference_anchor": 0.78},
}
ROTATION = [
    ("short_cross", "medium_cross"),
    ("short_cross", "long_cross"),
    ("medium_cross", "long_cross"),
]
FEATURES = [
    {"variant": "PACE_ONLY", "feature": "llm_pacing_score", "feature_axis": "pacing", "display": "LLM pacing"},
    {"variant": "EMOTION_ONLY", "feature": "llm_emotion_intensity_score", "feature_axis": "emotion_intensity", "display": "LLM emotion intensity"},
    {"variant": "DIALOGUE_ONLY", "feature": "llm_dialogue_density_score", "feature_axis": "dialogue_density", "display": "LLM dialogue density"},
    {"variant": "ACTION_ONLY", "feature": "llm_action_density_score", "feature_axis": "action_density", "display": "LLM action density"},
    {"variant": "CHARACTER_ONLY", "feature": "llm_character_interaction_score", "feature_axis": "character_interaction", "display": "LLM character interaction"},
]
STRUCTURE_FIELDS = [
    "task_id", "base_interval_id", "source_film_id", "reference_film_id",
    "source_scene_ids", "reference_scene_ids", "selected_features", "variant",
    "interval_type", "pair_key", "feature_axis",
]


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _feature(record: dict[str, Any], name: str) -> float:
    return _clamp(_as_float(record.get(name)))


def _interpolate(values: list[float], position: float) -> float:
    lo, hi = int(math.floor(position)), int(math.ceil(position))
    if lo == hi:
        return values[lo]
    frac = position - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def _resample(values: list[float], n: int) -> list[float]:
    values = [_clamp(x) for x in values]
    if not values or n <= 0:
        return []
    if len(values) == n:
        return [round(x, 6) for x in values]
    if len(values) == 1:
        return [round(values[0], 6)] * n
    if n == 1:
        return [round(_interpolate(values, (len(values) - 1) / 2.0), 6)]
    scale = (len(values) - 1) / (n - 1)
    return [round(_interpolate(values, i * scale), 6) for i in range(n)]


def _difficulty(src: list[dict[str, Any]], ref: list[dict[str, Any]], feature: str) -> float:
    a = [_feature(x, feature) for x in src]
    b = _resample([_feature(x, feature) for x in ref], len(a))
    return round(sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a), 6)


def _bucket(score: float) -> str:
    if score < 0.15:
        return "low"
    if score < 0.40:
        return "medium"
    return "high"


def _pair_jitter(source: str, reference: str, slot_id: str) -> int:
    raw = hashlib.sha256(f"{source}->{reference}:{slot_id}".encode("utf-8")).hexdigest()
    return int(raw[:8], 16) % 5 - 2


def _window(records: list[dict[str, Any]], length: int, anchor: float, jitter: int) -> list[dict[str, Any]]:
    if len(records) < length:
        raise RuntimeError(f"Cannot choose {length}-scene interval from {len(records)} scenes")
    max_start = len(records) - length
    start = int(round(max_start * max(0.0, min(1.0, anchor)))) + jitter
    start = max(0, min(max_start, start))
    return records[start:start + length]


def _load_features(feature_root: Path, film_id: str) -> list[dict[str, Any]]:
    path = feature_root / "films" / film_id / "scene_features_llm.json"
    payload = _json(path)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"Invalid feature file: {path}")
    rows = [dict(x) for x in payload if isinstance(x, dict)]
    rows.sort(key=lambda x: int(x.get("scene_index") or 0))
    return rows


def structure_sha256(tasks: list[dict[str, Any]]) -> str:
    projection = [{key: task.get(key) for key in STRUCTURE_FIELDS} for task in tasks]
    raw = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_taskset(payload: dict[str, Any], *, require_paths: bool = True) -> dict[str, Any]:
    tasks = payload.get("tasks") or []
    errors: list[str] = []
    variants = Counter(str(x.get("variant")) for x in tasks)
    intervals = Counter(str(x.get("interval_type")) for x in tasks)
    pairs = Counter(str(x.get("pair_key")) for x in tasks)
    base_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        base_groups[str(task.get("base_interval_id") or "")].append(task)

    checks = {
        "contract": payload.get("contract_id") == CONTRACT_ID and str(payload.get("contract_version")) == CONTRACT_VERSION,
        "taskset_id": payload.get("base_taskset_id") == TASKSET_ID,
        "task_count": len(tasks) == 240,
        "unique_task_ids": len({str(x.get("task_id")) for x in tasks}) == 240,
        "base_interval_count": len(base_groups) == 48,
        "directed_pair_count": len(pairs) == 24 and all(v == 10 for v in pairs.values()),
        "feature_balance": all(variants.get(x["variant"], 0) == 48 for x in FEATURES),
        "interval_balance": all(intervals.get(k, 0) == 80 for k in ("short", "medium", "long")),
        "base_has_five_features": all(len(v) == 5 for v in base_groups.values()),
        "canonical_structure": structure_sha256(tasks) == CANONICAL_STRUCTURE_SHA256,
    }
    if require_paths:
        checks["all_paths_exist"] = all(
            Path(str(task.get(key))).is_file()
            for task in tasks
            for key in ("source_script_path", "source_feature_path", "reference_feature_path")
        )
    for name, ok in checks.items():
        if not ok:
            errors.append(name)
    return {"valid": not errors, "errors": errors, "checks": checks, "structure_sha256": structure_sha256(tasks)}


def build_taskset_runtime(*, film_set_path: Path, input_root: Path, feature_set_manifest: Path, feature_set_root: Path, output_root: Path, overwrite: bool = False) -> dict[str, Any]:
    film_set_path = film_set_path.resolve()
    input_root = input_root.resolve()
    feature_set_manifest = feature_set_manifest.resolve()
    feature_set_root = feature_set_root.resolve()
    output_root = output_root.resolve()

    film_set = yaml.safe_load(film_set_path.read_text(encoding="utf-8")) or {}
    films = [str(x) for x in film_set.get("films", [])]
    if films != EXPECTED_FILMS:
        raise RuntimeError(f"TasksetV5 requires locked film order: {EXPECTED_FILMS}; found={films}")
    manifest = _json(feature_set_manifest)
    if manifest.get("contract_id") != "storygen.feature-set" or str(manifest.get("contract_version")) != "1.4":
        raise RuntimeError("storygen.feature-set/1.4 manifest required")
    feature_set_id = str(manifest.get("feature_set_id") or "").strip()
    if not feature_set_id:
        raise RuntimeError("feature_set_id missing")

    records = {film: _load_features(feature_set_root, film) for film in films}
    for film in films:
        script = input_root / "films" / film / "script.json"
        if not script.is_file():
            raise RuntimeError(f"Missing script input: {script}")

    directed: list[tuple[str, str]] = []
    for a, b in UNORDERED_PAIRS:
        directed.extend([(a, b), (b, a)])

    tasks: list[dict[str, Any]] = []
    base_intervals: list[dict[str, Any]] = []
    task_index = 1
    base_index = 1
    for pair_index, (source, reference) in enumerate(directed):
        for slot_key in ROTATION[pair_index % len(ROTATION)]:
            slot = INTERVALS[slot_key]
            src = _window(records[source], slot["length"], slot["source_anchor"], _pair_jitter(source, reference, slot["slot_id"]))
            ref = _window(records[reference], slot["length"], slot["reference_anchor"], _pair_jitter(reference, source, slot["slot_id"]))
            source_ids = [str(x["scene_id"]) for x in src]
            reference_ids = [str(x["scene_id"]) for x in ref]
            base_id = f"v5_B{base_index:04d}"
            base_intervals.append({
                "base_interval_id": base_id,
                "source_film_id": source,
                "reference_film_id": reference,
                "pair_key": f"{source}->{reference}",
                "slot_id": slot["slot_id"],
                "interval_type": slot["interval_type"],
                "source_scene_ids": source_ids,
                "reference_scene_ids": reference_ids,
            })
            diffs = [_difficulty(src, ref, spec["feature"]) for spec in FEATURES]
            base_difficulty = round(sum(diffs) / len(diffs), 6)
            for spec, difficulty in zip(FEATURES, diffs, strict=True):
                task = {
                    "task_id": f"v5_T{task_index:04d}",
                    "source_film_id": source,
                    "reference_film_id": reference,
                    "source_script_path": str((input_root / "films" / source / "script.json").resolve()),
                    "source_feature_path": str((feature_set_root / "films" / source / "scene_features_llm.json").resolve()),
                    "reference_feature_path": str((feature_set_root / "films" / reference / "scene_features_llm.json").resolve()),
                    "source_start_scene_id": source_ids[0],
                    "source_end_scene_id": source_ids[-1],
                    "reference_start_scene_id": reference_ids[0],
                    "reference_end_scene_id": reference_ids[-1],
                    "source_scene_ids": source_ids,
                    "reference_scene_ids": reference_ids,
                    "selected_features": [spec["feature"]],
                    "variant": spec["variant"],
                    "interval_type": slot["interval_type"],
                    "difficulty_score": difficulty,
                    "difficulty_bucket": _bucket(difficulty),
                    "taskset_version": "v5",
                    "source_scene_count": len(source_ids),
                    "reference_scene_count": len(reference_ids),
                    "feature_count": 1,
                    "pair_key": f"{source}->{reference}",
                    "expected_generation_mode": "per_scene_json",
                    "base_interval_id": base_id,
                    "v5_origin": "cost_controlled_10film_sparse_pair_protocol_v3_240_balanced_sml",
                    "v5_pair_policy": "12_unordered_pairs_bidirectional",
                    "v5_interval_policy": "two_interval_slots_per_directed_pair_rotated_short_medium_long",
                    "v5_tasks_per_directed_pair": 10,
                    "v5_tasks_per_base_interval": 5,
                    "feature_axis": spec["feature_axis"],
                    "feature_display_name": spec["display"],
                    "base_interval_difficulty_score": base_difficulty,
                    "base_interval_difficulty_bucket": _bucket(base_difficulty),
                    "feature_specific_difficulty_score": difficulty,
                    "feature_specific_difficulty_bucket": _bucket(difficulty),
                    "all_5_removed": True,
                    "runtime_feature_extraction_signature": manifest.get("measurement", {}).get("measurement_protocol_id"),
                    "runtime_feature_set_id": feature_set_id,
                    "runtime_measurement_protocol_hash": manifest.get("measurement", {}).get("protocol_hash"),
                }
                tasks.append(task)
                task_index += 1
            base_index += 1

    runtime_id = f"{TASKSET_ID}__{feature_set_id}"
    output = output_root / "taskset_v5" / "runtimes" / feature_set_id
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"Taskset runtime exists: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)
    payload = {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "taskset_id": runtime_id,
        "base_taskset_id": TASKSET_ID,
        "taskset_version": "v5_runtime",
        "builder_id": BUILDER_ID,
        "feature_set_id": feature_set_id,
        "feature_extraction_signature": manifest.get("measurement", {}).get("measurement_protocol_id"),
        "feature_set_manifest": str(feature_set_manifest),
        "feature_set_manifest_sha256": _sha(feature_set_manifest),
        "film_set": {"path": str(film_set_path), "id": film_set.get("film_set_id")},
        "input_root": str(input_root),
        "structure_sha256": structure_sha256(tasks),
        "created_at_utc": _utc(),
        "base_intervals": base_intervals,
        "tasks": tasks,
    }
    verification = verify_taskset(payload, require_paths=True)
    if not verification["valid"]:
        raise RuntimeError(f"Taskset verification failed: {verification['errors']}")
    _write_json(output / "taskset_runtime.json", payload)
    _write_json(output / "validation_report.json", verification)
    _write_json(output / "base_intervals.json", base_intervals)
    return {"output": str(output / "taskset_runtime.json"), "validation": verification, "task_count": len(tasks), "base_interval_count": len(base_intervals), "feature_set_id": feature_set_id}
