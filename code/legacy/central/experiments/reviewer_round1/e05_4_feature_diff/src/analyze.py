"""AFTER - BEFORE; complete intervals alone define task statistics."""

from collections import defaultdict
from statistics import mean, median
from common import EPSILON, FEATURES, SHORT, direction


def calculate(validated):
    scene_rows, grouped = [], defaultdict(list)
    for slot in validated["slots"]:
        row = {k: v for k, v in slot.items() if k not in ("before", "after")}
        row["non_target_features"] = [f for f in FEATURES if f != row["target_feature"]]
        for feature, short in zip(FEATURES, SHORT, strict=True):
            before = slot["before"][feature] if slot["pair_status"] == "VALID" else None
            after = slot["after"][feature] if slot["pair_status"] == "VALID" else None
            delta = after - before if before is not None else None
            row.update(
                {
                    f"before_{short}": before,
                    f"after_{short}": after,
                    f"delta_{short}": delta,
                    f"abs_delta_{short}": abs(delta) if delta is not None else None,
                }
            )
        scene_rows.append(row)
        grouped[(row["model"], row["condition"], row["task_id"])].append(row)
    task_rows = []
    for task in validated["tasks"]:
        row = dict(task)
        scenes = grouped[(task["model"], task["condition"], task["task_id"])]
        complete = task["status"] == "COMPLETE"
        for feature, short in zip(FEATURES, SHORT, strict=True):
            values = [s[f"delta_{short}"] for s in scenes] if complete else []
            absolute = [abs(v) for v in values]
            for name, value in [
                ("mean_signed", mean(values) if values else None),
                ("mean_absolute", mean(absolute) if values else None),
                ("median_signed", median(values) if values else None),
                ("median_absolute", median(absolute) if values else None),
            ]:
                row[f"{name}_{short}"] = value
            for label in ("INCREASE", "DECREASE", "UNCHANGED"):
                count = sum(direction(v) == label for v in values) if values else None
                row[f"{short}_{label.lower()}_count"] = count
                row[f"{short}_{label.lower()}_rate"] = (
                    count / len(values) if values else None
                )
            row[f"{short}_large_change_rate"] = (
                mean(abs(v) >= 0.20 for v in values) if values else None
            )
            # A direction slice is a within-task scene mean; tasks stay equally weighted.
            for target in ("INCREASE", "DECREASE", "MAINTAIN"):
                subset = (
                    [
                        s[f"delta_{short}"]
                        for s in scenes
                        if s["scene_target_direction"] == target
                    ]
                    if complete
                    else []
                )
                row[f"{short}_{target}_n"] = len(subset)
                row[f"{short}_{target}_signed"] = mean(subset) if subset else None
                row[f"{short}_{target}_absolute"] = (
                    mean(abs(v) for v in subset) if subset else None
                )
                for change in ("INCREASE", "DECREASE", "UNCHANGED"):
                    row[f"{short}_{target}_{change}_rate"] = (
                        mean(direction(v) == change for v in subset) if subset else None
                    )
        target = SHORT[FEATURES.index(task["target_feature"])]
        non_target = [
            s
            for f, s in zip(FEATURES, SHORT, strict=True)
            if f != task["target_feature"]
        ]
        row["mean_signed_target_change"] = row[f"mean_signed_{target}"]
        row["mean_absolute_target_change"] = row[f"mean_absolute_{target}"]
        row["mean_absolute_non_target_drift"] = (
            mean(row[f"mean_absolute_{s}"] for s in non_target) if complete else None
        )
        row["non_target_large_change_rate"] = (
            mean(row[f"{s}_large_change_rate"] for s in non_target)
            if complete
            else None
        )
        for d in ("INCREASE", "DECREASE", "MAINTAIN"):
            eligible = [row[f"{s}_{d}_absolute"] for s in non_target]
            subset = (
                [scene for scene in scenes if scene["scene_target_direction"] == d]
                if complete
                else []
            )
            row[f"non_target_drift_{d}"] = mean(eligible) if subset else None
            row[f"non_target_large_change_rate_{d}"] = (
                mean(
                    abs(scene[f"delta_{s}"]) >= 0.20
                    for scene in subset
                    for s in non_target
                )
                if subset
                else None
            )
        row["zero_epsilon"] = EPSILON
        task_rows.append(row)
    return scene_rows, task_rows
