"""Deterministic reviewer statistics from recorded E01-B scores only."""

from pathlib import Path
import csv
import importlib.util
import math
import statistics

import numpy as np
from scipy.stats import spearmanr

from storygen_platform.engine.common import StoryGenError, file_sha

FEATURES = (
    "llm_pacing_score",
    "llm_dialogue_density_score",
    "llm_action_density_score",
    "llm_character_interaction_score",
    "llm_emotion_intensity_score",
)


def load(name):
    spec = importlib.util.spec_from_file_location(
        "_sg_e01_b_reviewer_" + name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def matched(datasets, tasks):
    expected = {t["task_id"] for t in tasks}
    maps = [{r["task_id"]: r for r in rows} for rows in datasets]
    if any(len(m) != len(rows) or set(m) != expected for m, rows in zip(maps, datasets)):
        raise StoryGenError("Reviewer task populations differ or contain duplicates")
    selected = [t for t in tasks if all(m[t["task_id"]]["metric_eligible"] for m in maps)]
    exclusions = [
        {
            "task_id": t["task_id"],
            "ineligible_cells": [
                {"cell_index": i, "reason": m[t["task_id"]].get("ineligible_reason")}
                for i, m in enumerate(maps)
                if not m[t["task_id"]]["metric_eligible"]
            ],
        }
        for t in tasks
        if t not in selected
    ]
    return (
        selected,
        maps,
        {
            "attempted_n": len(tasks),
            "matched_n": len(selected),
            "task_ids": [t["task_id"] for t in selected],
            "cluster_n": len({t["base_interval_id"] for t in selected}),
            "cluster_ids": sorted({t["base_interval_id"] for t in selected}),
            "exclusions": exclusions,
        },
    )


def task_statistics(plan, datasets):
    from storygen_evaluation.reviewer.statistics import bootstrap

    gains, agreement, drops, populations = [], [], [], []
    tasks = plan["tasks"]
    for (key, extractor, precision), rows in sorted(datasets.items()):
        if extractor != "Mistral-7B":
            continue
        selected, maps, population = matched([rows], tasks)
        values = [
            maps[0][t["task_id"]]["before_target_mae"] - maps[0][t["task_id"]]["after_target_mae"]
            for t in selected
        ]
        gains.append(
            {
                "group": key,
                "extractor": extractor,
                "precision": precision,
                **population,
                "estimate": bootstrap(
                    values,
                    [t["base_interval_id"] for t in selected],
                    "e01-b-gain-" + key + "-" + precision,
                ),
            }
        )
        selected, maps, population = matched([datasets[(key, "Qwen2.5-7B", "Q4_K_M")], rows], tasks)
        populations.append(
            {
                "contrast": key + "_M" + precision + "_minus_Q",
                **population,
                "cell_order": [
                    key + " / Qwen2.5-7B / Q4_K_M",
                    key + " / Mistral-7B / " + precision,
                ],
            }
        )
        counts = {"both_pass": 0, "both_fail": 0, "qwen_only_pass": 0, "mistral_only_pass": 0}
        for task in selected:
            q, m = [bool(a[task["task_id"]]["target_improved"]) for a in maps]
            label = (
                ("both_pass" if q else "both_fail")
                if q == m
                else ("qwen_only_pass" if q else "mistral_only_pass")
            )
            counts[label] += 1
        agreement.append(
            {
                "group": key,
                "precision": precision,
                **population,
                **counts,
                "agreement": (
                    (counts["both_pass"] + counts["both_fail"]) / len(selected)
                    if selected
                    else None
                ),
            }
        )
    for condition in ("dp", "cg"):
        cells = [
            (model + "_" + condition, extractor, "Q4_K_M")
            for model in ("qwen", "gemma")
            for extractor in ("Qwen2.5-7B", "Mistral-7B")
        ]
        selected, maps, population = matched([datasets[c] for c in cells], tasks)
        values = []
        for task in selected:
            q_q, q_m, g_q, g_m = [float(m[task["task_id"]]["target_improved"]) for m in maps]
            values.append(100 * ((q_q - q_m) - (g_q - g_m)))
        drops.append(
            {
                "condition": condition.upper() + "-v1",
                **population,
                "cell_order": [" / ".join(c) for c in cells],
                "direction": "(Qwen rewrite: Qwen - Mistral Q4) - (Gemma rewrite: Qwen - Mistral Q4)",
                "estimate": bootstrap(
                    values,
                    [t["base_interval_id"] for t in selected],
                    "e01-b-ti-drop-difference-" + condition,
                ),
            }
        )
    for model in ("qwen", "gemma"):
        for extractor in ("Qwen2.5-7B", "Mistral-7B"):
            cells = [(model + "_" + c, extractor, "Q4_K_M") for c in ("dp", "cg")]
            _, _, population = matched([datasets[c] for c in cells], tasks)
            populations.append(
                {
                    "contrast": model + "_" + extractor + "_CG_minus_DP",
                    **population,
                    "cell_order": [" / ".join(c) for c in cells],
                }
            )
    return {
        "gain_intervals": gains,
        "ti_agreement": agreement,
        "drop_differences": drops,
        "paired_populations": populations,
    }


def valid(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def score_agreement(x, y):
    """Two-way random-effects, absolute-agreement, single-measure ICC(2,1)."""
    if len(x) != len(y) or not all(valid(v) for v in [*x, *y]):
        raise StoryGenError("Invalid paired agreement scores")
    n = len(x)
    result = {
        "n_pairs": n,
        "spearman_rho": None,
        "spearman_reason": None,
        "icc_2_1": None,
        "icc_reason": None,
        "mean_absolute_difference": statistics.mean(abs(a - b) for a, b in zip(x, y))
        if n
        else None,
    }
    if n < 2:
        result.update(spearman_reason="fewer_than_two_pairs", icc_reason="fewer_than_two_pairs")
        return result
    if len(set(x)) == 1 or len(set(y)) == 1:
        result["spearman_reason"] = "constant_score_vector"
    else:
        result["spearman_rho"] = float(spearmanr(x, y).statistic)
    matrix = np.array([x, y], dtype=float).T
    grand = matrix.mean()
    rows, columns = matrix.mean(axis=1), matrix.mean(axis=0)
    ms_rows = 2 * np.square(rows - grand).sum() / (n - 1)
    ms_columns = n * np.square(columns - grand).sum()
    residual = matrix - rows[:, None] - columns[None, :] + grand
    ms_error = np.square(residual).sum() / (n - 1)
    denominator = ms_rows + ms_error + 2 * (ms_columns - ms_error) / n
    if abs(denominator) < 1e-15:
        result["icc_reason"] = "zero_anova_denominator"
    else:
        result["icc_2_1"] = float((ms_rows - ms_error) / denominator)
    return result


def scene_agreement(left, right, feature):
    all_ids = set(left) | set(right)
    paired = sorted(set(left) & set(right))
    usable = [i for i in paired if valid(left[i].get(feature)) and valid(right[i].get(feature))]
    return {
        **score_agreement([left[i][feature] for i in usable], [right[i][feature] for i in usable]),
        "scene_population_n": len(all_ids),
        "qwen_only_scene_n": len(set(left) - set(right)),
        "mistral_only_scene_n": len(set(right) - set(left)),
        "invalid_pair_n": len(paired) - len(usable),
        "excluded_scene_ids": [list(i) for i in sorted(all_ids - set(usable))],
    }


def curve_agreement(tasks, left, right, feature):
    from storygen_evaluation.provenance import _resample
    from storygen_evaluation.metrics import signum

    bases = {}
    for task in tasks:
        base = task["base_interval_id"]
        if base in bases:
            old = bases[base]
            if any(
                old[k] != task[k]
                for k in (
                    "source_film_id",
                    "source_scene_ids",
                    "reference_film_id",
                    "reference_scene_ids",
                )
            ):
                raise StoryGenError(
                    "Base interval source/reference identity changed across features"
                )
        bases[base] = task
    correlations, undefined, unavailable = [], [], []
    hits, total, direction_unavailable = 0, 0, 0
    for base, task in sorted(bases.items()):
        curves = []
        for data in (left, right):
            curves.append(
                [
                    [
                        data.get((task[side + "_film_id"], sid), {}).get(feature)
                        for sid in task[side + "_scene_ids"]
                    ]
                    for side in ("source", "reference")
                ]
            )
        (q_b, q_t), (m_b, m_t) = curves
        if all(valid(v) for v in q_b + m_b):
            value = score_agreement(q_b, m_b)["spearman_rho"]
            if value is None:
                undefined.append(base)
            else:
                correlations.append(value)
        else:
            unavailable.append(base)
        if not all(valid(v) for v in q_t + m_t):
            direction_unavailable += len(q_b)
            continue
        q_target = _resample([round(float(v), 6) for v in q_t], len(q_b))
        m_target = _resample([round(float(v), 6) for v in m_t], len(m_b))
        for qb, qt, mb, mt in zip(q_b, q_target, m_b, m_target):
            if not valid(qb) or not valid(mb):
                direction_unavailable += 1
                continue
            hits += signum(qt - round(float(qb), 6)) == signum(mt - round(float(mb), 6))
            total += 1
    return {
        "base_interval_n": len(bases),
        "source_curve_valid_n": len(correlations),
        "source_curve_constant_n": len(undefined),
        "source_curve_unavailable_n": len(unavailable),
        "source_curve_constant_base_ids": undefined,
        "source_curve_unavailable_base_ids": unavailable,
        "median_source_curve_spearman": statistics.median(correlations) if correlations else None,
        "source_curve_reason": None if correlations else "no_defined_source_curve_correlations",
        "same_target_direction": hits / total if total else None,
        "direction_match_n": hits,
        "direction_point_n": total,
        "direction_unavailable_n": direction_unavailable,
    }


def analyze(root, depot, plan, datasets, sources):
    io = load("inputs")
    scores = load("reviewer_inputs").load(root, depot, plan, sources, io)
    result = task_statistics(plan, datasets)
    rows = []
    for phase in io.PHASES:
        for feature in FEATURES:
            rows.append(
                {
                    "population": "original",
                    "phase": phase,
                    "group": "",
                    "precision": "Q4_K_M",
                    "feature": feature,
                    **scene_agreement(scores["q_original"], scores["original"][phase], feature),
                    **curve_agreement(
                        plan["tasks"], scores["q_original"], scores["original"][phase], feature
                    ),
                }
            )
        for key in io.PHASES[phase]:
            left, right = {}, {}
            for task in plan["tasks"]:
                tid = task["task_id"]
                for target, source in ((left, scores["q_after"]), (right, scores["after"])):
                    target.update(
                        {
                            (key, tid, task["source_film_id"], sid): row
                            for sid, row in source[key][tid].items()
                        }
                    )
            selected, _, eligible = matched(
                [
                    datasets[(key, "Qwen2.5-7B", "Q4_K_M")],
                    datasets[(key, "Mistral-7B", "Q4_K_M")],
                ],
                plan["tasks"],
            )
            for feature in FEATURES:
                rows.append(
                    {
                        "population": "rewritten",
                        "phase": phase,
                        "group": key,
                        "precision": "Q4_K_M",
                        "feature": feature,
                        **scene_agreement(left, right, feature),
                        "ti_matched_task_n": eligible["matched_n"],
                        "ti_matched_scene_n": sum(len(t["source_scene_ids"]) for t in selected),
                        "scene_eligibility": "all paired valid scores; not filtered by task TI eligibility",
                    }
                )
    return {
        "contract": "storygen.e01-b-reviewer-analysis/1",
        **result,
        "extractor_agreement": rows,
        "score_inputs": scores["inputs"],
        "implementation_sha256": {
            name: file_sha(Path(__file__).with_name(name))
            for name in ("reviewer.py", "reviewer_inputs.py", "report.py", "science.py")
        },
        "methods": {
            "bootstrap": "Original E01: represented base_interval_id clusters, 10000 draws, PCG64 seed42, linear percentile 95%; task-weighted mean",
            "icc": "ICC(2,1): two-way random-effects absolute agreement, single measurement; negative values retained",
            "originals": "Each phase separately; unique film_id/scene_id within phase, never pooled across phases",
            "rewrites": "Group/task_id/source_film_id/scene_id, valid paired scores independently of TI eligibility",
            "source_curves": "Each base interval once per feature and phase; median defined Spearman coefficients",
            "target_direction": "Native _resample and signum, six-decimal original values; source and reference use each extractor's own scores",
        },
        "inference_performed": False,
    }


def export(destination, result, contrasts):
    """Human-readable tables plus flat numerical CSVs; full populations stay in JSON."""

    def flat_estimate(estimate):
        ci = estimate["ci95"]
        return {
            "point": estimate["point"],
            "ci95_low": ci[0] if ci else None,
            "ci95_high": ci[1] if ci else None,
            "ci_reason": estimate["ci_reason"],
        }

    def write_csv(name, rows):
        fields = list(dict.fromkeys(k for r in rows for k in r))
        with (destination / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    paired = [
        {
            "contrast": c["contrast"],
            "metric": metric,
            "matched_n": c["matched_n"],
            "cluster_n": estimate["cluster_n"],
            **flat_estimate(estimate),
        }
        for c in contrasts
        for metric, estimate in c["ci"].items()
    ]
    paired += [
        {
            "contrast": "qwen_minus_gemma_TI_drop_" + c["condition"],
            "metric": "TI_pp",
            "matched_n": c["matched_n"],
            "cluster_n": c["cluster_n"],
            **flat_estimate(c["estimate"]),
        }
        for c in result["drop_differences"]
    ]
    gains = [
        {
            "group": c["group"],
            "precision": c["precision"],
            "matched_n": c["matched_n"],
            "cluster_n": c["cluster_n"],
            **flat_estimate(c["estimate"]),
        }
        for c in result["gain_intervals"]
    ]
    agreement = [
        {k: v for k, v in c.items() if k not in {"task_ids", "cluster_ids", "exclusions"}}
        for c in result["ti_agreement"]
    ]
    scores = [
        {k: v for k, v in c.items() if not isinstance(v, list)}
        for c in result["extractor_agreement"]
    ]
    write_csv("paired_contrasts.csv", paired)
    write_csv("gain_intervals.csv", gains)
    write_csv("ti_agreement.csv", agreement)
    write_csv("extractor_agreement.csv", scores)

    def cell(value):
        return "NA" if value is None else f"{value:.6f}" if isinstance(value, float) else str(value)

    def table(title, records, columns):
        return [
            "",
            "### " + title,
            "",
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *["| " + " | ".join(cell(r.get(c)) for c in columns) + " |" for r in records],
        ]

    lines = [
        "",
        "## Reviewer analysis (offline)",
        "",
        "All statistics use recorded scores. TI/DA contrasts are percentage points; gain and score differences remain on the 0–1 score scale.",
        "Conditional table N and paired matched N are different populations. Exact task IDs, exclusions, cluster identities, method details and score-source hashes are in comparison.json.",
        "Bootstrap: 48 represented base-interval clusters for these runs, 10,000 draws, PCG64 seed42, 95% linear percentile; task-weighted means.",
    ]
    lines += table(
        "Paired contrasts and difference of TI drops",
        paired,
        [
            "contrast",
            "metric",
            "matched_n",
            "cluster_n",
            "point",
            "ci95_low",
            "ci95_high",
            "ci_reason",
        ],
    )
    lines += [
        "",
        "TI drop difference = (Qwen rewrites: Qwen − Mistral Q4) − (Gemma rewrites: Qwen − Mistral Q4), on the four-cell common task intersection. Positive means a larger drop for Qwen rewrites.",
    ]
    lines += table(
        "Mistral mean gain: own confidence intervals",
        gains,
        [
            "group",
            "precision",
            "matched_n",
            "cluster_n",
            "point",
            "ci95_low",
            "ci95_high",
            "ci_reason",
        ],
    )
    lines += table(
        "Task-level TI decision agreement",
        agreement,
        [
            "group",
            "precision",
            "matched_n",
            "both_pass",
            "both_fail",
            "qwen_only_pass",
            "mistral_only_pass",
            "agreement",
        ],
    )
    lines += [
        "",
        "Agreement is a fraction. Historical 73.11% refers to FP16; Q4 is calculated separately.",
    ]
    lines += table(
        "Table 11b: per-dimension extractor agreement",
        scores,
        [
            "population",
            "phase",
            "group",
            "feature",
            "n_pairs",
            "spearman_rho",
            "icc_2_1",
            "mean_absolute_difference",
            "spearman_reason",
            "icc_reason",
        ],
    )
    original = [c for c in scores if c["population"] == "original"]
    lines += table(
        "Source-curve and implied target-direction agreement",
        original,
        [
            "phase",
            "feature",
            "base_interval_n",
            "source_curve_valid_n",
            "median_source_curve_spearman",
            "same_target_direction",
            "direction_match_n",
            "direction_point_n",
            "direction_unavailable_n",
        ],
    )
    lines += [
        "",
        "Original phases each contain the same scene identities, measured separately; they are not pooled. Rewritten score agreement includes all valid paired scene scores, independently of TI eligibility. Source curves count each base interval once per feature; constant curves have undefined Spearman and are excluded only from the median (IDs and counts in JSON).",
        "Undefined statistics are NA with reasons; negative ICC values are retained. No extractor is treated as ground truth. Historical FP16 runtime differs from Q4; precision contrasts remain descriptive.",
    ]
    return lines
