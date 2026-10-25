"""The seven E06 diagnostics. Tasks, never scenes, weight primary estimates."""

from collections import Counter
import math
from common import (
    CONDITIONS,
    DIRECTIONS,
    FEATURES,
    THRESHOLDS,
    TOLERANCES,
    average,
    describe,
    ratio,
)
from storygen_evaluation.metrics import signum


NAMES = {
    "A01": "Maintain Tolerance Sweep",
    "A02": "Trivial Direction Baselines",
    "A03": "Failure-Aware All-Attempt Directional Accuracy",
    "A04": "Excluded-Task Characterization",
    "A05": "All-Model Feature-Level TI/DA",
    "A06": "Output/Input Length Ratios",
    "A07": "Small-Improvement Sensitivity",
}


def directions(row):
    return [signum(t - b) for b, t in zip(row["B"], row["T"])]


def hits(row, tolerance):
    if not row["eligible"]:
        return None
    return [
        int(abs(a - b) <= tolerance) if d == 0 else int(signum(a - b) == d)
        for b, a, d in zip(row["B"], row["A"], directions(row))
    ]


def attempt_summary(rows):
    valid = [r for r in rows if r["eligible"]]
    n, v = len(rows), len(valid)
    da, ti = sum(r["DA"] for r in valid), sum(r["TI"] for r in valid)
    conditional = ratio(da, v)
    all_attempt = ratio(da, n)
    return dict(
        planned_tasks=n,
        valid_tasks=v,
        missing_tasks=n - v,
        coverage_pct=100 * v / n if n else None,
        conditional_DA=conditional,
        all_attempt_DA=all_attempt,
        DA_reduction_pp=100 * (conditional - all_attempt) if v else None,
        conditional_TI=ratio(ti, v),
        all_attempt_TI=ratio(ti, n),
        mean_dB=average(r["dB"] for r in valid),
        mean_dA=average(r["dA"] for r in valid),
        mean_signed_gain=average(r["G"] for r in valid),
        failures=dict(
            sorted(
                Counter(
                    r["failure_classification"] for r in rows if not r["eligible"]
                ).items()
            )
        ),
    )


def bundle(tables, status="COMPLETE", **extra):
    return dict(status=status, tables=tables, **extra)


def a01(ds):
    results, breakdown, llama = [], [], []
    for model in ds.models:
        for condition in CONDITIONS:
            valid = [r for r in ds.rows(model, condition) if r["eligible"]]
            for tau in TOLERANCES:
                da = average(average(hits(r, tau)) for r in valid)
                canonical = average(r["DA"] for r in valid)
                point_counts = Counter(d for r in valid for d in directions(r))
                by_direction = []
                for d, label in DIRECTIONS:
                    total = point_counts[d]
                    correct = sum(
                        h
                        for r in valid
                        for h, desired in zip(hits(r, tau), directions(r))
                        if desired == d
                    )
                    # Sum direction-specific hits/L within each task, divided by task N.
                    contribution = average(
                        sum(h for h, s in zip(hits(r, tau), directions(r)) if s == d)
                        / r["interval_length"]
                        for r in valid
                    )
                    row = dict(
                        model=model,
                        condition=condition,
                        tolerance=tau,
                        direction=label,
                        valid_tasks=len(valid),
                        scene_positions=total,
                        correct_positions=correct,
                        scene_accuracy=ratio(correct, total),
                        task_macro_contribution=contribution,
                    )
                    breakdown.append(row)
                    by_direction.append(row)
                results.append(
                    dict(
                        model=model,
                        condition=condition,
                        tolerance=tau,
                        valid_tasks=len(valid),
                        canonical_DA=canonical,
                        tolerance_adjusted_DA=da,
                        DA_change_pp=100 * (da - canonical) if da is not None else None,
                        maintain_points=point_counts[0],
                        maintain_accuracy=by_direction[1]["scene_accuracy"],
                        increase_accuracy=by_direction[2]["scene_accuracy"],
                        decrease_accuracy=by_direction[0]["scene_accuracy"],
                    )
                )
        if "llama" in model.lower():
            paired = [
                tid
                for tid in ds.records[model, CONDITIONS[0]]
                if all(ds.records[model, c][tid]["eligible"] for c in CONDITIONS)
            ]
            populations = {
                "condition_conditional": {
                    c: [r["task_id"] for r in ds.rows(model, c) if r["eligible"]]
                    for c in CONDITIONS
                },
                "within_model_paired": {c: sorted(paired) for c in CONDITIONS},
                "global_common": {c: ds.common() for c in CONDITIONS},
            }
            for population, by_condition in populations.items():
                for tau in TOLERANCES:
                    for d, label in DIRECTIONS:
                        contributions = {
                            c: average(
                                sum(
                                    h
                                    for h, s in zip(
                                        hits(ds.records[model, c][tid], tau),
                                        directions(ds.records[model, c][tid]),
                                    )
                                    if s == d
                                )
                                / ds.records[model, c][tid]["interval_length"]
                                for tid in sorted(by_condition[c])
                            )
                            for c in CONDITIONS
                        }
                        defined = all(v is not None for v in contributions.values())
                        llama.append(
                            dict(
                                model=model,
                                population=population,
                                paired_tasks=len(paired)
                                if population == "within_model_paired"
                                else None,
                                DP_tasks=len(by_condition["DP-v1"]),
                                CG_tasks=len(by_condition["CG-v1"]),
                                tolerance=tau,
                                direction=label,
                                DP_contribution=contributions["DP-v1"],
                                CG_contribution=contributions["CG-v1"],
                                CG_minus_DP_contribution_pp=100
                                * (contributions["CG-v1"] - contributions["DP-v1"])
                                if defined
                                else None,
                            )
                        )
    return bundle(
        {
            "A01_RESULTS.csv": results,
            "A01_DIRECTION_BREAKDOWN.csv": breakdown,
            "A01_LLAMA_MAINTAIN_ANALYSIS.csv": llama,
        },
        llama_contrast_status="AVAILABLE"
        if llama and any(r["paired_tasks"] for r in llama)
        else "MISSING_COMPATIBLE_PAIRED_RECORDS",
        denominator="Measured tasks per condition; Llama decomposition labels condition-conditional, within-model paired and global-common populations separately; direction contributions sum to the corresponding task-macro DA contrast.",
    )


def a02(ds):
    baseline, distribution, features = [], [], []
    for feature in [None, *FEATURES]:
        tasks = [t for t in ds.tasks if feature is None or t["feature"] == feature]
        signs = [directions(t) for t in tasks]
        points = sum(map(len, signs))
        for d, label in DIRECTIONS:
            count = sum(s.count(d) for s in signs)
            row = dict(
                feature=feature or "ALL",
                policy="ALWAYS_" + label,
                task_definitions=len(tasks),
                scene_positions=points,
                task_macro_DA=average(s.count(d) / len(s) for s in signs),
                target_direction_count=count,
                scene_pooled_proportion=ratio(count, points),
            )
            (baseline if feature is None else features).append(row)
            if feature is None:
                distribution.append(
                    {
                        k: v
                        for k, v in dict(row, direction=label).items()
                        if k not in ("policy", "task_macro_DA")
                    }
                )
    comparison = [
        dict(model=m, condition=c, **attempt_summary(ds.rows(m, c)))
        for m in ds.models
        for c in CONDITIONS
    ]
    return bundle(
        {
            "A02_BASELINE_RESULTS.csv": baseline,
            "A02_DIRECTION_DISTRIBUTION.csv": distribution,
            "A02_FEATURE_BREAKDOWN.csv": features,
            "A02_MODEL_DA_COMPARISON.csv": comparison,
        },
        denominator="All frozen task definitions; scene-pooled target directions are separately labeled. No TI is defined for direction policies.",
    )


def failure_ledger(ds):
    return [
        dict(
            model=m,
            condition=c,
            task_id=r["task_id"],
            feature=r["feature"],
            base_interval_id=r["base_interval_id"],
            failure_classification=r["failure_classification"],
            original_status=r["original_status"],
            generation_status=r["generation_status"],
            measurement_status=r["measurement_status"],
        )
        for m in ds.models
        for c in CONDITIONS
        for r in ds.rows(m, c)
        if not r["eligible"]
    ]


def a03(ds):
    return bundle(
        {
            "A03_ALL_ATTEMPT_DA.csv": [
                dict(model=m, condition=c, **attempt_summary(ds.rows(m, c)))
                for m in ds.models
                for c in CONDITIONS
            ],
            "A03_FAILURE_LEDGER.csv": failure_ledger(ds),
        },
        denominator="Conditional: measured tasks; all-attempt: every planned task, failures contribute zero DA/TI without imputed distances.",
    )


def a04(ds):
    common = set(ds.common())
    excluded = [t for t in ds.tasks if t["task_id"] not in common]

    def public(t):
        return dict(
            task_id=t["task_id"],
            base_interval_id=t["base_interval_id"],
            screenplay_id=t["screenplay_id"],
            feature=t["feature"],
            interval_length=t["interval_length"],
            direction_summary="MIXED"
            if len(set(directions(t))) > 1
            else dict(DIRECTIONS)[directions(t)[0]],
        )

    def breakdown(key):
        return [
            dict(
                group_key=key,
                group_value=str(value),
                planned_unique_tasks=sum(t[key] == value for t in ds.tasks),
                excluded_unique_tasks=sum(t[key] == value for t in excluded),
                common_unique_tasks=sum(
                    t[key] == value and t["task_id"] in common for t in ds.tasks
                ),
            )
            for value in sorted({t[key] for t in ds.tasks})
        ]

    direction_rows = [
        dict(
            population=pop,
            direction=label,
            unique_tasks=len(tasks),
            scene_positions=sum(directions(t).count(d) for t in tasks),
            tasks_containing_direction=sum(d in directions(t) for t in tasks),
            mixed_direction_tasks=sum(len(set(directions(t))) > 1 for t in tasks),
        )
        for pop, tasks in (
            ("excluded", excluded),
            ("global_common", [t for t in ds.tasks if t["task_id"] in common]),
        )
        for d, label in DIRECTIONS
    ]
    return bundle(
        {
            "A04_GLOBAL_COMMON_TASKS.csv": [
                public(t) for t in ds.tasks if t["task_id"] in common
            ],
            "A04_EXCLUDED_TASKS.csv": [public(t) for t in excluded],
            "A04_MISSING_OBSERVATIONS.csv": failure_ledger(ds),
            "A04_FEATURE_BREAKDOWN.csv": breakdown("feature"),
            "A04_LENGTH_BREAKDOWN.csv": breakdown("interval_length"),
            "A04_SCREENPLAY_BREAKDOWN.csv": breakdown("screenplay_id"),
            "A04_DIRECTION_BREAKDOWN.csv": direction_rows,
            "A04_SCENE_DIRECTIONS.csv": [
                dict(
                    task_id=t["task_id"],
                    scene_id=sid,
                    scene_position=pos,
                    requested_direction=dict(DIRECTIONS)[d],
                )
                for t in excluded
                for pos, (sid, d) in enumerate(zip(t["scene_ids"], directions(t)))
            ],
        },
        global_common_task_ids=sorted(common),
        excluded_unique_tasks=len(excluded),
        missing_observations=len(failure_ledger(ds)),
        denominator="Unique excluded tasks and missing model-condition-task observations are distinct populations; mixed task directions retain scene labels.",
    )


def a05(ds):
    rows = [
        dict(
            model=m,
            condition=c,
            feature=f,
            **attempt_summary([r for r in ds.rows(m, c) if r["feature"] == f]),
        )
        for m in ds.models
        for c in CONDITIONS
        for f in FEATURES
    ]

    def matrix(field):
        return [
            dict(
                model=m,
                condition=c,
                metric=field,
                **{
                    r["feature"]: r[field]
                    for r in rows
                    if r["model"] == m and r["condition"] == c
                },
            )
            for m in ds.models
            for c in CONDITIONS
        ]

    # Descriptive contrasts use identical paired task IDs for every feature.
    contrasts = []
    for m in ds.models:
        for f in FEATURES:
            tids = [
                t["task_id"]
                for t in ds.tasks
                if t["feature"] == f
                and all(ds.records[m, c][t["task_id"]]["eligible"] for c in CONDITIONS)
            ]
            contrasts.append(
                dict(
                    model=m,
                    feature=f,
                    population="within_model_feature_paired",
                    paired_tasks=len(tids),
                    **{
                        "CG_minus_DP_" + metric: average(
                            ds.records[m, "CG-v1"][tid][metric]
                            - ds.records[m, "DP-v1"][tid][metric]
                            for tid in tids
                        )
                        for metric in ("TI", "DA")
                    },
                )
            )
    return bundle(
        {
            "A05_FEATURE_LEVEL_RESULTS.csv": rows,
            "A05_TI_MATRIX.csv": matrix("conditional_TI"),
            "A05_DA_MATRIX.csv": matrix("conditional_DA"),
            "A05_ALL_ATTEMPT_MATRIX.csv": matrix("all_attempt_TI")
            + matrix("all_attempt_DA"),
            "A05_DP_CG_COMPARISONS.csv": contrasts,
        },
        denominator="Planned feature tasks for all-attempt; eligible feature tasks for conditional metrics. Historical prompting packages do not isolate numerical guidance causally.",
    )


def a06(ds):
    scenes, tasks = [], []
    for m in ds.models:
        for c in CONDITIONS:
            for r in ds.rows(m, c):
                for pair in r["text_pairs"]:
                    scenes.append(
                        dict(
                            model=m,
                            condition=c,
                            task_id=r["task_id"],
                            screenplay_id=r["screenplay_id"],
                            base_interval_id=r["base_interval_id"],
                            interval_length=r["interval_length"],
                            **pair,
                        )
                    )
                for basis in ("full_archived_source", "model_presented_source"):
                    pairs = [p for p in r["text_pairs"] if p["source_basis"] == basis]
                    valid = len(pairs) == r["interval_length"] and all(
                        p["status"] == "VALID" for p in pairs
                    )
                    sw = sum(p["source_words"] or 0 for p in pairs)
                    aw = sum(p["rewrite_words"] or 0 for p in pairs)
                    tasks.append(
                        dict(
                            model=m,
                            condition=c,
                            task_id=r["task_id"],
                            interval_length=r["interval_length"],
                            source_basis=basis,
                            status="VALID" if valid else "MISSING_INPUT",
                            source_words=sw if valid else None,
                            rewrite_words=aw if valid else None,
                            length_ratio=aw / sw if valid else None,
                            valid_scene_pairs=sum(
                                p["status"] == "VALID" for p in pairs
                            ),
                            missing_or_invalid_scene_pairs=r["interval_length"]
                            - sum(p["status"] == "VALID" for p in pairs),
                        )
                    )

    def summarize(rows):
        ratios = [r["length_ratio"] for r in rows if r["status"] == "VALID"]
        return dict(
            planned_tasks=len(rows),
            valid_tasks=len(ratios),
            missing_tasks=len(rows) - len(ratios),
            **describe(ratios),
            shortened_proportion=average(x < 1 for x in ratios),
            lengthened_proportion=average(x > 1 for x in ratios),
        )

    summary = [
        dict(
            model=m,
            condition=c,
            source_basis=b,
            **summarize(
                [
                    r
                    for r in tasks
                    if (r["model"], r["condition"], r["source_basis"]) == (m, c, b)
                ]
            ),
        )
        for m in ds.models
        for c in CONDITIONS
        for b in ("full_archived_source", "model_presented_source")
    ]
    lengths = [
        dict(
            model=m,
            condition=c,
            source_basis=b,
            interval_length=length,
            **summarize(
                [
                    r
                    for r in tasks
                    if (
                        r["model"],
                        r["condition"],
                        r["source_basis"],
                        r["interval_length"],
                    )
                    == (m, c, b, length)
                ]
            ),
        )
        for m in ds.models
        for c in CONDITIONS
        for b in ("full_archived_source", "model_presented_source")
        for length in sorted({t["interval_length"] for t in ds.tasks})
    ]
    scene_summary = [
        dict(
            model=m,
            condition=c,
            source_basis=b,
            **describe(
                [
                    r["length_ratio"]
                    for r in scenes
                    if (r["model"], r["condition"], r["source_basis"]) == (m, c, b)
                    and r["status"] == "VALID"
                ]
            ),
        )
        for m in ds.models
        for c in CONDITIONS
        for b in ("full_archived_source", "model_presented_source")
    ]
    contrasts = []
    for m in ds.models:
        for basis in ("full_archived_source", "model_presented_source"):
            valid = {
                c: {
                    r["task_id"]: r
                    for r in tasks
                    if (r["model"], r["condition"], r["source_basis"], r["status"])
                    == (m, c, basis, "VALID")
                }
                for c in CONDITIONS
            }
            ids = sorted(set(valid["DP-v1"]) & set(valid["CG-v1"]))
            contrasts.append(
                dict(
                    model=m,
                    source_basis=basis,
                    paired_tasks=len(ids),
                    CG_minus_DP_mean_ratio=average(
                        valid["CG-v1"][tid]["length_ratio"]
                        - valid["DP-v1"][tid]["length_ratio"]
                        for tid in ids
                    ),
                )
            )
    # Historical generation failures do not invalidate A06; missing text in a generated
    # rewrite does. All failed/missing text pairs still appear in the ledger.
    generated = {
        (m, c, r["task_id"])
        for m in ds.models
        for c in CONDITIONS
        for r in ds.rows(m, c)
        if r["generation_status"] == "recorded_rewrite"
    }
    blocked = any(
        r["status"] != "VALID"
        and (r["model"], r["condition"], r["task_id"]) in generated
        for r in tasks
    )
    status = (
        "MISSING_INPUT"
        if blocked or not any(r["status"] == "VALID" for r in tasks)
        else "COMPLETE"
    )
    return bundle(
        {
            "A06_TASK_LENGTH_RATIOS.csv": tasks,
            "A06_SCENE_LENGTH_RATIOS.csv": scenes,
            "A06_MODEL_CONDITION_SUMMARY.csv": summary,
            "A06_LENGTH_BREAKDOWN.csv": lengths,
            "A06_SCENE_DISTRIBUTION.csv": scene_summary,
            "A06_DP_CG_COMPARISONS.csv": contrasts,
        },
        status,
        unique_source_scenes=len({(r["screenplay_id"], r["scene_id"]) for r in scenes}),
        primary_source_basis="full_archived_source",
        valid_matched_scene_pairs=sum(
            r["status"] == "VALID" and r["source_basis"] == "full_archived_source"
            for r in scenes
        ),
        missing_text_pairs=sum(
            r["status"] != "VALID" and r["source_basis"] == "full_archived_source"
            for r in scenes
        ),
        pair_counts_by_source_basis={
            b: dict(
                valid=sum(
                    r["status"] == "VALID" and r["source_basis"] == b for r in scenes
                ),
                missing_or_invalid=sum(
                    r["status"] != "VALID" and r["source_basis"] == b for r in scenes
                ),
            )
            for b in ("full_archived_source", "model_presented_source")
        },
        denominator="Task ratio=sum(rewrite words)/sum(source words), then task-macro; full archived and model-presented bases never mixed. Scene-position ratios are descriptive. NFC whitespace word counts.",
        limitation="Length preservation does not prove semantic preservation, event preservation, or screenplay quality.",
    )


def a07(ds):
    results, distribution = [], []
    for m in ds.models:
        for c in CONDITIONS:
            rows = ds.rows(m, c)
            valid = [r for r in rows if r["eligible"]]
            gains = [r["G"] for r in valid]
            canonical = average(r["TI"] for r in valid)
            distribution.append(
                dict(
                    model=m,
                    condition=c,
                    **describe(gains),
                    negative=sum(g < 0 for g in gains),
                    zero=sum(g == 0 for g in gains),
                    positive=sum(g > 0 for g in gains),
                )
            )
            for eps in THRESHOLDS:
                successes = sum(g > eps for g in gains)
                adjusted = ratio(successes, len(valid))
                results.append(
                    dict(
                        model=m,
                        condition=c,
                        epsilon=eps,
                        valid_tasks=len(valid),
                        planned_tasks=len(rows),
                        canonical_TI=canonical,
                        threshold_adjusted_TI=adjusted,
                        all_attempt_threshold_TI=ratio(successes, len(rows)),
                        all_attempt_canonical_TI=ratio(
                            sum(r["TI"] for r in valid), len(rows)
                        ),
                        TI_reduction_pp=100 * (canonical - adjusted)
                        if canonical is not None
                        else None,
                        all_attempt_TI_reduction_pp=100
                        * (sum(r["TI"] for r in valid) - successes)
                        / len(rows)
                        if rows
                        else None,
                        very_small_positive_gain_tasks=sum(0 < g <= eps for g in gains),
                    )
                )
    return bundle(
        {
            "A07_THRESHOLD_RESULTS.csv": results,
            "A07_GAIN_DISTRIBUTION.csv": distribution,
        },
        denominator="Conditional: eligible measured tasks; all-attempt: all planned tasks, failures remain zero. Strict G>epsilon on unrounded floats; thresholds have no independently validated perceptual meaning.",
    )


ANALYSES = dict(zip(NAMES, (a01, a02, a03, a04, a05, a06, a07)))


def validate(ds, results, unchanged=True):
    """Independent cross-module checks; failure blocks a COMPLETE experiment."""
    checks = {}

    def check(key, ok, detail):
        checks[key] = dict(status="PASS" if ok else "FAIL", detail=detail)

    expected = ds.validation.get("expected", {})
    ids = [t["task_id"] for t in ds.tasks]
    design_ok = True
    if "base_intervals" in expected:
        design_ok = all(
            {t["feature"] for t in ds.tasks if t["base_interval_id"] == bid}
            == set(FEATURES)
            and sum(t["base_interval_id"] == bid for t in ds.tasks) == len(FEATURES)
            for bid in {t["base_interval_id"] for t in ds.tasks}
        )
    check(
        "V01",
        len(ids) == len(set(ids))
        and len(ids) == expected.get("tasks", len(ids))
        and design_ok,
        "Frozen task identities, one task per feature/base interval and design counts",
    )
    observed = {
        m: {c: sum(r["eligible"] for r in ds.rows(m, c)) for c in CONDITIONS}
        for m in ds.models
    }
    expected_counts = expected.get("valid_counts", observed)
    structure_ok = len({t["base_interval_id"] for t in ds.tasks}) == expected.get(
        "base_intervals", len({t["base_interval_id"] for t in ds.tasks})
    )
    structure_ok &= len({t["screenplay_id"] for t in ds.tasks}) == expected.get(
        "screenplays", len({t["screenplay_id"] for t in ds.tasks})
    )
    check(
        "V02",
        observed == expected_counts
        and not ds.validation.get("replay_mismatches")
        and structure_ok,
        dict(
            observed=observed,
            expected=expected_counts,
            replay_mismatches=ds.validation.get("replay_mismatches", []),
        ),
    )
    all_rows = [r for m in ds.models for c in CONDITIONS for r in ds.rows(m, c)]
    check(
        "V03",
        all(average(hits(r, 0)) == r["DA"] for r in all_rows if r["eligible"])
        and all(
            row["canonical_DA"] == row["tolerance_adjusted_DA"]
            for row in results["A01"]["tables"]["A01_RESULTS.csv"]
            if row["tolerance"] == 0
        ),
        "Tolerance zero exactly reproduces canonical DA per task",
    )
    check(
        "V04",
        all(int(r["G"] > 0) == r["TI"] for r in all_rows if r["eligible"])
        and all(
            row["canonical_TI"] == row["threshold_adjusted_TI"]
            for row in results["A07"]["tables"]["A07_THRESHOLD_RESULTS.csv"]
            if row["epsilon"] == 0
        ),
        "Threshold zero exactly reproduces canonical TI per task",
    )

    def tables(a, n):
        return results[a]["tables"][n]

    feature_rows = tables("A05", "A05_FEATURE_LEVEL_RESULTS.csv")
    agreement = True
    for row in tables("A03", "A03_ALL_ATTEMPT_DA.csv"):
        subset = [
            f
            for f in feature_rows
            if (f["model"], f["condition"]) == (row["model"], row["condition"])
        ]
        weighted = (
            sum(
                f["all_attempt_DA"] * f["planned_tasks"]
                for f in subset
                if f["planned_tasks"]
            )
            / row["planned_tasks"]
        )
        agreement &= math.isclose(
            weighted, row["all_attempt_DA"], rel_tol=0, abs_tol=1e-14
        )
    check(
        "V05",
        agreement,
        "Feature groups aggregated by actual planned task weights; 1e-14 summation-only tolerance",
    )
    ledger = tables("A03", "A03_FAILURE_LEDGER.csv")
    missing = tables("A04", "A04_MISSING_OBSERVATIONS.csv")
    check(
        "V06",
        ledger == missing
        and sum(r["missing_tasks"] for r in tables("A03", "A03_ALL_ATTEMPT_DA.csv"))
        == len(missing),
        "Missing observation reconciliation",
    )
    common = ds.common()
    reported = [r["task_id"] for r in tables("A04", "A04_GLOBAL_COMMON_TASKS.csv")]
    check(
        "V07",
        common == reported
        and common == results["A04"]["global_common_task_ids"]
        and len(common) == expected.get("global_common", len(common)),
        dict(derived_common_n=len(common), expected_n=expected.get("global_common")),
    )
    check(
        "V08",
        all(
            r["planned_tasks"] == r["valid_tasks"] + r["missing_tasks"]
            for a, n in (
                ("A03", "A03_ALL_ATTEMPT_DA.csv"),
                ("A05", "A05_FEATURE_LEVEL_RESULTS.csv"),
            )
            for r in tables(a, n)
        ),
        "Conditional/all-attempt denominators explicit and exhaustive",
    )

    def finite(x):
        if isinstance(x, float):
            return math.isfinite(x)
        if isinstance(x, dict):
            return all(finite(v) for v in x.values())
        if isinstance(x, list):
            return all(finite(v) for v in x)
        return True

    check(
        "V09",
        finite(results),
        "Finite numbers; undefined quantities are null with zero counts",
    )
    check(
        "V10",
        all(
            all(r[k] is None for k in ("TI", "DA", "A", "dB", "dA", "G"))
            for r in all_rows
            if not r["eligible"]
        ),
        "Ineligible observations contain no imputed metric values",
    )
    check(
        "V11",
        all(
            [p["scene_id"] for p in r["text_pairs"] if p["source_basis"] == b]
            == r["scene_ids"]
            for r in all_rows
            for b in ("full_archived_source", "model_presented_source")
        )
        and all(
            p["source_words"] > 0
            and p["rewrite_words"] > 0
            and p["length_ratio"] == p["rewrite_words"] / p["source_words"]
            for r in all_rows
            for p in r["text_pairs"]
            if p["status"] == "VALID"
        )
        and results["A06"]["status"] == "COMPLETE",
        "Source/request/rewrite identity alignment; unavailable text prevents full completion",
    )
    check(
        "V12",
        unchanged and ds.validation.get("inputs_unchanged", True),
        "All consumed inputs and recorded absences unchanged",
    )
    checks["V13"] = dict(
        status="DEFERRED",
        detail="Pipeline must verify every persisted JSON/CSV cell before report generation",
    )
    checks["V14"] = dict(
        status="DEFERRED",
        detail="Pipeline must record the actual dependency/source audit",
    )
    check(
        "V15",
        set(results) == set(ANALYSES)
        and all(r["status"] == "COMPLETE" for r in results.values()),
        {a: r["status"] for a, r in results.items()},
    )
    return dict(
        status="PASS"
        if all(v["status"] == "PASS" for v in checks.values())
        else "FAIL",
        checks=checks,
    )
