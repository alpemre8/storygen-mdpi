from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .io import read_json

PLAN_LIKE = (
    "rewrite plan",
    "the scene should",
    "modify the scene",
    "transformation:",
    "change the scene by",
)

MEASUREMENT_IDENTITY_KEYS = (
    "measurement_protocol_id",
    "measurement_protocol_version",
    "protocol_hash",
    "instrument_hash",
    "prompt_hash",
    "schema_hash",
    "system_instruction_hash",
    "request_contract_hash",
    "decoding_hash",
)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def mae(a: list[float], b: list[float]) -> float | None:
    if not a or len(a) != len(b):
        return None
    return mean([abs(x - y) for x, y in zip(a, b)])


def signum(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def directional_accuracy(before: list[float], target: list[float], after: list[float]) -> float | None:
    if not before or len(before) != len(target) or len(before) != len(after):
        return None
    hits = [int(signum(a - b) == signum(t - b)) for b, t, a in zip(before, target, after)]
    return sum(hits) / len(hits)


def measurement_identity(measurement: dict[str, Any]) -> dict[str, Any]:
    identity = {key: measurement.get(key) for key in MEASUREMENT_IDENTITY_KEYS}
    identity["model_sha256"] = (measurement.get("model") or {}).get("model_sha256")
    return identity


def exact_measurement(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    expected_identity = measurement_identity(expected)
    actual_identity = measurement_identity(actual)
    return [key for key, value in expected_identity.items() if value != actual_identity.get(key)]


def failure_record(task: dict[str, Any], reason: str, method: str, model: str) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "base_interval_id": task.get("base_interval_id"),
        "feature": (task.get("selected_features") or [task.get("feature_axis")])[0],
        "interval_type": task.get("interval_type"),
        "metric_eligible": False,
        "ineligible_reason": reason,
        "before_target_mae": None,
        "after_target_mae": None,
        "target_improved": None,
        "directional_accuracy": None,
        "method": method,
        "rewrite_model": model,
    }


def _normalized_reanalysis_failure(root: dict[str, Any]) -> str:
    root_cause = str(root.get("root_cause") or root.get("root_cause_type") or "failed")
    if root_cause == "missing_rewrite_task":
        return "rewrite:missing_rewrite_task"
    return f"reanalysis:{root_cause}"


def _finite_curve(values: Any) -> list[float] | None:
    if not isinstance(values, list):
        return None
    output: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        output.append(float(value))
    return output


def evaluate_task(
    task: dict[str, Any],
    task_dir: Path,
    expected_measurement: dict[str, Any],
    method: str,
    model: str,
) -> dict[str, Any]:
    if not task_dir.is_dir():
        return failure_record(task, "reanalysis:missing_run_task", method, model)

    try:
        rewrite = read_json(task_dir / "rewritten_scenes.json")
        measurement_status = read_json(task_dir / "measurement_status.json")
        features = read_json(task_dir / "rewritten_scene_features.json")
        plan = read_json(task_dir / "transfer_plan.json")
    except Exception:
        failure_path = task_dir / "reanalysis_failure.json"
        if failure_path.is_file():
            try:
                return failure_record(task, _normalized_reanalysis_failure(read_json(failure_path)), method, model)
            except Exception:
                pass
        return failure_record(task, "evaluation:missing_or_invalid_task_artifact", method, model)

    expected_scene_ids = [str(scene_id) for scene_id in task.get("source_scene_ids", [])]
    scenes = rewrite.get("rewritten_scenes", []) if isinstance(rewrite, dict) else []
    returned_scene_ids = [str(scene.get("scene_id")) for scene in scenes if isinstance(scene, dict)]
    reasons: list[str] = []

    if returned_scene_ids != expected_scene_ids:
        reasons.append("exact_scene_order_mismatch")
    if len(returned_scene_ids) != len(set(returned_scene_ids)):
        reasons.append("duplicate_scene_id")
    if len(scenes) != len(expected_scene_ids):
        reasons.append("scene_count_mismatch")
    if any(not str(scene.get("content") or "").strip() for scene in scenes if isinstance(scene, dict)):
        reasons.append("empty_final_content")
    if any(
        marker in str(scene.get("content") or "").lower()
        for scene in scenes if isinstance(scene, dict)
        for marker in PLAN_LIKE
    ):
        reasons.append("plan_like_output")

    actual_measurement = measurement_status.get("measurement", {}) if isinstance(measurement_status, dict) else {}
    if measurement_status.get("status") != "measured":
        reasons.append("invalid_or_missing_reanalysis")
    mismatches = exact_measurement(expected_measurement, actual_measurement)
    if mismatches:
        reasons.append("measurement_contract_mismatch:" + ",".join(mismatches))
    if (actual_measurement.get("failure_policy") or {}).get("heuristic_fallback") is not False:
        reasons.append("measurement_fallback_not_disabled")

    feature = (task.get("selected_features") or [task.get("feature_axis")])[0]
    feature_by_scene = {str(row.get("scene_id")): row for row in features if isinstance(row, dict)} if isinstance(features, list) else {}
    after: list[float] = []
    for scene_id in expected_scene_ids:
        value = feature_by_scene.get(scene_id, {}).get(feature)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            reasons.append("selected_feature_missing_or_nonfinite")
            break
        after.append(float(value))

    source_curves = plan.get("source_current_curve", {}) if isinstance(plan, dict) else {}
    target_curves = plan.get("resampled_target_curve", {}) if isinstance(plan, dict) else {}
    before = _finite_curve(source_curves.get(feature))
    target = _finite_curve(target_curves.get(feature))
    if before is None or target is None:
        reasons.append("before_or_target_missing_or_nonfinite")
        before = before or []
        target = target or []
    if len(after) != len(expected_scene_ids) or len(before) != len(expected_scene_ids) or len(target) != len(expected_scene_ids):
        reasons.append("curve_length_mismatch")

    if reasons:
        record = failure_record(task, ";".join(dict.fromkeys(reasons)), method, model)
        if before and target and len(before) == len(target):
            record["before_target_mae"] = mae(before, target)
        return record

    before_mae = mae(before, target)
    after_mae = mae(after, target)
    da = directional_accuracy(before, target, after)
    if before_mae is None or after_mae is None or da is None:
        return failure_record(task, "evaluation:metric_input_invalid", method, model)

    return {
        "task_id": task["task_id"],
        "base_interval_id": task.get("base_interval_id"),
        "feature": feature,
        "interval_type": task.get("interval_type"),
        "metric_eligible": True,
        "ineligible_reason": None,
        "before_target_mae": before_mae,
        "after_target_mae": after_mae,
        "target_improved": bool(after_mae < before_mae),
        "directional_accuracy": da,
        "method": method,
        "rewrite_model": model,
    }
