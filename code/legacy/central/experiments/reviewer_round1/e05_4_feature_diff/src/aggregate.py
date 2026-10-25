"""Equal-task summaries, exact intersections, deterministic base cluster bootstrap."""

from collections import defaultdict
from statistics import mean, median, stdev
import numpy as np
from common import CONDITIONS, FEATURES, MODELS, REPLICATIONS, SEED, SHORT

PRIMARY = (
    "mean_absolute_non_target_drift",
    "mean_absolute_target_change",
    "mean_signed_target_change",
)


def trace(rows):
    return dict(
        task_ids=sorted({r["task_id"] for r in rows}),
        base_interval_ids=sorted({r["base_interval_id"] for r in rows}),
        source_film_ids=sorted({r["source_film_id"] for r in rows}),
    )


def describe(rows, metric, *, replications=REPLICATIONS):
    rows = sorted(
        (r for r in rows if r.get(metric) is not None),
        key=lambda r: (r["base_interval_id"], r["task_id"]),
    )
    values = [r[metric] for r in rows]
    clusters = defaultdict(list)
    for r in rows:
        clusters[r["base_interval_id"]].append(r[metric])
    result = dict(
        n_tasks=len(rows),
        mean=mean(values) if values else None,
        median=median(values) if values else None,
        standard_deviation=stdev(values) if len(values) > 1 else None,
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        q025=float(np.quantile(values, 0.025)) if values else None,
        q25=float(np.quantile(values, 0.25)) if values else None,
        q75=float(np.quantile(values, 0.75)) if values else None,
        q975=float(np.quantile(values, 0.975)) if values else None,
        eligible_clusters=len(clusters),
        bootstrap_replications=0,
        bootstrap_seed=SEED,
        ci95_low=None,
        ci95_high=None,
        ci_limitation=None,
        **trace(rows),
    )
    if len(clusters) < 8:
        result["ci_limitation"] = (
            "Fewer than eight eligible base intervals; CI withheld"
        )
    elif replications:
        groups = [clusters[k] for k in sorted(clusters)]
        sums = np.array([sum(g) for g in groups])
        counts = np.array([len(g) for g in groups])
        draws = np.random.default_rng(SEED).integers(
            len(groups), size=(replications, len(groups))
        )
        estimators = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
        result.update(
            ci95_low=float(np.quantile(estimators, 0.025)),
            ci95_high=float(np.quantile(estimators, 0.975)),
            bootstrap_replications=replications,
            ci_limitation="Descriptive base-cluster percentile CI; overlapping bases/film dependence remain",
        )
    else:
        result["ci_limitation"] = "Bootstrap disabled for this descriptive summary"
    return result


def coverage(tasks):
    rows = []
    for model in MODELS:
        for condition in CONDITIONS:
            group = [
                t for t in tasks if t["model"] == model and t["condition"] == condition
            ]
            rows.append(
                dict(
                    model=model,
                    condition=condition,
                    planned_tasks=len(group),
                    available_rewrite_tasks=sum(t["available_rewrite"] for t in group),
                    available_reanalysis_tasks=sum(
                        t["available_reanalysis"] for t in group
                    ),
                    complete_measurement_tasks=sum(
                        t["status"] == "COMPLETE" for t in group
                    ),
                    partial_measurement_tasks=sum(
                        t["status"] == "PARTIAL" for t in group
                    ),
                    missing_tasks=sum(t["status"].startswith("MISSING") for t in group),
                    invalid_tasks=sum(
                        t["status"] not in ("COMPLETE", "PARTIAL")
                        and not t["status"].startswith("MISSING")
                        for t in group
                    ),
                    expected_scene_slots=sum(t["expected_scenes"] for t in group),
                    valid_scene_pairs=sum(t["valid_scenes"] for t in group),
                    missing_scene_pairs=sum(t["missing_scenes"] for t in group),
                    invalid_scene_pairs=sum(t["invalid_scenes"] for t in group),
                    **trace(group),
                )
            )
    return rows


def common_ids(tasks):
    sets = [
        {
            t["task_id"]
            for t in tasks
            if t["model"] == m and t["condition"] == c and t["status"] == "COMPLETE"
        }
        for m in MODELS
        for c in CONDITIONS
    ]
    return set.intersection(*sets)


def matrices(tasks, scope="FULL_AVAILABLE_CASE"):
    rows = []
    for model in MODELS:
        for condition in CONDITIONS:
            for target in FEATURES:
                planned = [
                    t
                    for t in tasks
                    if t["model"] == model
                    and t["condition"] == condition
                    and t["target_feature"] == target
                ]
                complete = [t for t in planned if t["status"] == "COMPLETE"]
                for measured, short in zip(FEATURES, SHORT, strict=True):
                    for direction in ("ALL", "INCREASE", "DECREASE", "MAINTAIN"):
                        metrics = {
                            "mean_signed_change": f"mean_signed_{short}"
                            if direction == "ALL"
                            else f"{short}_{direction}_signed",
                            "mean_absolute_change": f"mean_absolute_{short}"
                            if direction == "ALL"
                            else f"{short}_{direction}_absolute",
                        }
                        metrics.update(
                            {
                                change.lower()
                                + "_percentage": f"{short}_{change.lower()}_rate"
                                if direction == "ALL"
                                else f"{short}_{direction}_{change}_rate"
                                for change in ("INCREASE", "DECREASE", "UNCHANGED")
                            }
                        )
                        for name, key in metrics.items():
                            eligible = [t for t in complete if t[key] is not None]
                            stats = describe(eligible, key, replications=0)
                            if name.endswith("_percentage"):
                                for k in (
                                    "mean",
                                    "median",
                                    "standard_deviation",
                                    "minimum",
                                    "maximum",
                                    "q025",
                                    "q25",
                                    "q75",
                                    "q975",
                                ):
                                    if stats[k] is not None:
                                        stats[k] *= 100
                            rows.append(
                                dict(
                                    scope=scope,
                                    model=model,
                                    condition=condition,
                                    target_feature=target,
                                    measured_feature=measured,
                                    target_direction=direction,
                                    is_target=target == measured,
                                    statistic=name,
                                    planned_tasks=len(planned),
                                    expected_scene_slots=sum(
                                        t["expected_scenes"] for t in planned
                                    ),
                                    valid_scene_pairs=sum(
                                        t["valid_scenes"] for t in planned
                                    ),
                                    eligible_scene_pairs=sum(
                                        t["valid_scenes"]
                                        if direction == "ALL"
                                        else t[f"{short}_{direction}_n"]
                                        for t in eligible
                                    ),
                                    **stats,
                                )
                            )
    return rows


def drift(tasks):
    rows = []
    for model in MODELS:
        for condition in CONDITIONS:
            complete = [
                t
                for t in tasks
                if t["model"] == model
                and t["condition"] == condition
                and t["status"] == "COMPLETE"
            ]
            groups = [("overall", "ALL", complete, "mean_absolute_non_target_drift")]
            for field in (
                "target_feature",
                "target_direction",
                "interval_length",
                "source_film_id",
            ):
                for value in sorted({t[field] for t in tasks}, key=str):
                    groups.append(
                        (
                            field,
                            str(value),
                            [t for t in complete if t[field] == value],
                            "mean_absolute_non_target_drift",
                        )
                    )
            for d in ("INCREASE", "DECREASE", "MAINTAIN"):
                groups.append(
                    (
                        "scene_target_direction",
                        d,
                        [t for t in complete if t[f"non_target_drift_{d}"] is not None],
                        f"non_target_drift_{d}",
                    )
                )
            for feature, short in zip(FEATURES, SHORT, strict=True):
                groups.append(
                    (
                        "measured_feature",
                        feature,
                        [t for t in complete if t["target_feature"] != feature],
                        f"mean_absolute_{short}",
                    )
                )
            for field, value, group, metric in groups:
                rows.append(
                    dict(
                        model=model,
                        condition=condition,
                        group_by=field,
                        group=value,
                        metric=metric,
                        large_change_rate=mean(
                            t[f"non_target_large_change_rate_{value}"]
                            if field == "scene_target_direction"
                            else t["non_target_large_change_rate"]
                            if field != "measured_feature"
                            else t[f"{SHORT[FEATURES.index(value)]}_large_change_rate"]
                            for t in group
                        )
                        if group
                        else None,
                        **describe(group, metric),
                    )
                )
            for task in complete:
                rows.append(
                    dict(
                        model=model,
                        condition=condition,
                        group_by="task_id",
                        group=task["task_id"],
                        metric="mean_absolute_non_target_drift",
                        large_change_rate=task["non_target_large_change_rate"],
                        **describe(
                            [task], "mean_absolute_non_target_drift", replications=0
                        ),
                    )
                )
    return rows


def paired(tasks):
    rows = []
    for model in MODELS:
        by_condition = {
            c: {
                t["task_id"]: t
                for t in tasks
                if t["model"] == model
                and t["condition"] == c
                and t["status"] == "COMPLETE"
            }
            for c in CONDITIONS
        }
        dp, cg = (by_condition[c] for c in CONDITIONS)
        joint = sorted(dp.keys() & cg.keys())
        groups = [("ALL", m, joint) for m in PRIMARY[:2]]
        for target in FEATURES:
            ids = [i for i in joint if dp[i]["target_feature"] == target]
            for short in SHORT:
                groups.extend(
                    (target, f"mean_{kind}_{short}", ids)
                    for kind in ("absolute", "signed")
                )
        for target, metric, ids in groups:
            differences = []
            for tid in ids:
                a, b = dp[tid], cg[tid]
                if any(
                    a[k] != b[k]
                    for k in (
                        "base_interval_id",
                        "source_film_id",
                        "target_feature",
                        "interval_length",
                        "target_direction",
                    )
                ):
                    raise ValueError("IDENTITY_MISMATCH in DP/CG pair")
                differences.append(
                    dict(
                        task_id=tid,
                        base_interval_id=a["base_interval_id"],
                        source_film_id=a["source_film_id"],
                        value=b[metric] - a[metric],
                        dp_value=a[metric],
                        cg_value=b[metric],
                    )
                )
            shared = dict(
                model=model,
                target_feature=target,
                metric=metric,
                dp_total_measurable_tasks=len(dp),
                cg_total_measurable_tasks=len(cg),
                jointly_measurable_tasks=len(joint),
            )
            rows.append(
                dict(
                    **shared,
                    record_type="SUMMARY",
                    task_id=None,
                    base_interval_id=None,
                    source_film_id=None,
                    dp_value=None,
                    cg_value=None,
                    difference=None,
                    **describe(differences, "value"),
                )
            )
            for d in differences:
                rows.append(
                    dict(
                        **shared,
                        record_type="TASK_DIFFERENCE",
                        task_id=d["task_id"],
                        base_interval_id=d["base_interval_id"],
                        source_film_id=d["source_film_id"],
                        dp_value=d["dp_value"],
                        cg_value=d["cg_value"],
                        difference=d["value"],
                        n_tasks=1,
                        **trace([d]),
                    )
                )
    return rows


def model_comparison(tasks, scope):
    rows = []
    metrics = PRIMARY + tuple(
        f"mean_{kind}_{s}" for s in SHORT for kind in ("absolute", "signed")
    )
    for model in MODELS:
        for condition in CONDITIONS:
            group = [
                t
                for t in tasks
                if t["model"] == model
                and t["condition"] == condition
                and t["status"] == "COMPLETE"
            ]
            for metric in metrics:
                rows.append(
                    dict(
                        scope=scope,
                        model=model,
                        condition=condition,
                        metric=metric,
                        **describe(group, metric),
                    )
                )
    return rows


def directions(tasks):
    rows = []
    for t in tasks:
        for feature, short in zip(FEATURES, SHORT, strict=True):
            for d in ("INCREASE", "DECREASE", "UNCHANGED"):
                rows.append(
                    dict(
                        **{
                            k: t[k]
                            for k in (
                                "model",
                                "condition",
                                "task_id",
                                "base_interval_id",
                                "source_film_id",
                                "target_feature",
                                "target_direction",
                                "status",
                            )
                        },
                        measured_feature=feature,
                        is_target=t["target_feature"] == feature,
                        change_direction=d,
                        count=t[f"{short}_{d.lower()}_count"],
                        rate=t[f"{short}_{d.lower()}_rate"],
                        expected_scenes=t["expected_scenes"],
                        valid_scenes=t["valid_scenes"],
                    )
                )
    return rows


def aggregate(validated, scene_rows, task_rows):
    common = common_ids(task_rows)
    common_tasks = [t for t in task_rows if t["task_id"] in common]
    return dict(
        schema_version="e05.feature-diff.analysis/1.0",
        coverage=coverage(task_rows),
        scenes=scene_rows,
        tasks=task_rows,
        matrices=matrices(task_rows) + matrices(common_tasks, "GLOBAL_MATCHED_COMMON"),
        drift=drift(task_rows),
        paired=paired(task_rows),
        models=model_comparison(task_rows, "FULL_AVAILABLE_CASE"),
        global_common=model_comparison(common_tasks, "GLOBAL_MATCHED_COMMON"),
        common_task_ids=sorted(common),
        exclusions=validated["exclusions"],
        directions=directions(task_rows),
        provenance=validated["provenance"],
    )
