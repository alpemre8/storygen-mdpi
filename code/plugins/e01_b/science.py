"""Existing E01-MIN independent B/T alignment and canonical evaluation functions.

E01_MIN/.../EVALUATION_HANDOFF.py is the authoritative antecedent. This module
only binds its functions to the consolidated code/data paths and new model.
"""

import math


def evaluation_plan(task, source_rows, reference_rows, expected_protocol_hash):
    from storygen_evaluation.provenance import _resample

    feature = task["selected_features"][0]
    curves = []
    for rows, ids in (
        (source_rows, task["source_scene_ids"]),
        (reference_rows, task["reference_scene_ids"]),
    ):
        mapping = {row["scene_id"]: row for row in rows}
        if len(mapping) != len(rows):
            raise ValueError("Duplicate original measurement scene identity")
        selected = []
        for sid in ids:
            row = mapping[sid]
            if row.get("measurement_protocol_hash") != expected_protocol_hash:
                raise ValueError("Extractor B/T mixing rejected")
            value = row[feature]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid independent B/T measurement")
            selected.append(round(float(value), 6))
        curves.append(selected)
    before, raw_target = curves
    return {
        "source_scene_ids": task["source_scene_ids"],
        "reference_scene_ids": task["reference_scene_ids"],
        "selected_features": task["selected_features"],
        "source_current_curve": {feature: before},
        "reference_curve": {feature: raw_target},
        "resampled_target_curve": {feature: _resample(raw_target, len(before))},
        "evaluation_instrument_protocol_hash": expected_protocol_hash,
        "generation_targets_unchanged": True,
    }


def evaluate(task, directory, measurement, group):
    from storygen_evaluation.metrics import evaluate_task

    return evaluate_task(task, directory, measurement, group["condition"], group["alias"])


def failure(task, reason, group):
    from storygen_evaluation.metrics import failure_record

    return failure_record(task, reason, group["condition"], group["alias"])


def aggregate(records):
    from storygen_evaluation.reviewer.statistics import average

    measured = [r for r in records if r["metric_eligible"]]
    n = len(records)
    return {
        "attempted_n": n,
        "measurable_n": len(measured),
        "nonmeasurable_n": n - len(measured),
        "TI": average([r["target_improved"] for r in measured]),
        "DA": average([r["directional_accuracy"] for r in measured]),
        "before_target_distance": average([r["before_target_mae"] for r in measured]),
        "after_target_distance": average([r["after_target_mae"] for r in measured]),
        "mean_gain": average([r["before_target_mae"] - r["after_target_mae"] for r in measured]),
    }


def paired(left, right, tasks, label):
    from storygen_evaluation.reviewer.statistics import bootstrap

    expected = {t["task_id"] for t in tasks}
    a, b = ({r["task_id"]: r for r in rows} for rows in (left, right))
    if len(a) != len(left) or len(b) != len(right) or set(a) != expected or set(b) != expected:
        raise ValueError("Paired comparison task populations differ")
    selected = [
        t
        for t in tasks
        if a[t["task_id"]]["metric_eligible"] and b[t["task_id"]]["metric_eligible"]
    ]
    left_rows, right_rows = ([side[t["task_id"]] for t in selected] for side in (a, b))
    clusters = [t["base_interval_id"] for t in selected]
    delta = {
        "TI_pp": [
            100 * (float(y["target_improved"]) - float(x["target_improved"]))
            for x, y in zip(left_rows, right_rows)
        ],
        "DA_pp": [
            100 * (y["directional_accuracy"] - x["directional_accuracy"])
            for x, y in zip(left_rows, right_rows)
        ],
        "mean_gain": [
            (y["before_target_mae"] - y["after_target_mae"])
            - (x["before_target_mae"] - x["after_target_mae"])
            for x, y in zip(left_rows, right_rows)
        ],
    }
    return {
        "contrast": label,
        "direction": "right minus left",
        "attempted_n": len(tasks),
        "matched_n": len(selected),
        "task_ids": [t["task_id"] for t in selected],
        "left_on_matched": aggregate(left_rows),
        "right_on_matched": aggregate(right_rows),
        "ci": {k: bootstrap(v, clusters, "e01-b-" + label + "-" + k) for k, v in delta.items()},
    }
