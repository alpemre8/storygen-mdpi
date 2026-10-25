"""Stable tables, publication figures and computed narrative; no model access."""

from pathlib import Path
from statistics import mean
import csv
import json
import math
from common import (
    FEATURES,
    SHORT,
    MODELS,
    LABELS,
    CONDITIONS,
    IDENTITY,
    EPSILON,
    SEED,
    REPLICATIONS,
    sha,
    write,
)

TABLES = (
    ("01_COVERAGE.csv", "coverage"),
    ("02_SCENE_FEATURE_DIFF.csv", "scenes"),
    ("03_TASK_FEATURE_DIFF.csv", "tasks"),
    ("04_FEATURE_INTERACTION_MATRIX.csv", "matrices"),
    ("05_NON_TARGET_DRIFT.csv", "drift"),
    ("06_DP_CG_COMPARISON.csv", "paired"),
    ("07_MODEL_COMPARISON.csv", "models"),
    ("08_EXCLUSIONS.csv", "exclusions"),
    ("09_DIRECTION_DISTRIBUTION.csv", "directions"),
    ("10_GLOBAL_COMMON_COMPARISON.csv", "global_common"),
)

LIMITATIONS = """These are changes measured by the canonical Qwen2.5-7B instrument. Feature constructs and human agreement are not independently validated. Qwen2.5 rewrites share a model family/checkpoint with the extractor. Historical clamped measurements cannot recover unclamped predictions.

Feature drift is not content damage, semantic preservation, screenplay quality, or an externally defined violation. High target change does not establish target-guidance success. Correlated narrative properties may move together; no causal independence is established.

DP-v1 and CG-v1 prompts may differ beyond numerical guidance. Their differences are descriptive; E04 is the separate matched-prompt experiment. Previous E05 semantic judge outcomes are not used.

Missingness can select the available-case population. Global matched-common results use the newly calculated complete intersection across eight combinations, not the historical 186-task set. Poor-coverage models remain visible.

Scenes nest within tasks and five tasks share each base. The base-interval cluster bootstrap resamples clusters with all their eligible tasks; within paired comparisons it resamples paired differences, hence the same bases in both conditions. Overlapping bases and film dependence remain. Only ten films exist; no film-cluster sensitivity or independent-scene significance test is reported. Percentile CIs are descriptive and withheld below eight eligible bases.
"""


def columns(rows, fallback=IDENTITY):
    keys = {k for r in rows for k in r}
    first = [k for k in IDENTITY if k in keys]
    return first + sorted(keys - set(first)) if keys else list(fallback)


def csv_table(path, rows, fieldnames=None):
    fields = fieldnames or columns(rows)

    def cell(value):
        if value is None:
            return "NA"
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Nonfinite CSV output")
            return format(value, ".17f")
        if isinstance(value, (list, dict)):
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        return value

    with Path(path).open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: cell(row.get(k)) for k in fields})


def plots(output, data):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        return dict(status="OPTIONAL_DEPENDENCY_UNAVAILABLE", reason=str(exc), files=[])
    plt.rcParams.update({"font.size": 10, "pdf.fonttype": 42, "savefig.dpi": 300})
    files = []

    def save(fig, name):
        for extension in ("png", "pdf"):
            path = output / (name + "." + extension)
            if path.exists():
                raise FileExistsError(path)
            fig.savefig(path, bbox_inches="tight")
            files.append(path.name)
        plt.close(fig)

    full = [
        r
        for r in data["matrices"]
        if r["scope"] == "FULL_AVAILABLE_CASE" and r["target_direction"] == "ALL"
    ]
    for statistic, number, palette, low, high in [
        ("mean_absolute_change", 1, "viridis", 0, 1),
        ("mean_signed_change", 2, "RdBu_r", -1, 1),
    ]:
        for model, label in zip(MODELS, LABELS, strict=True):
            for condition in CONDITIONS:
                subset = [
                    r
                    for r in full
                    if r["model"] == model
                    and r["condition"] == condition
                    and r["statistic"] == statistic
                ]
                arr = np.full((5, 5), np.nan)
                for r in subset:
                    if r["mean"] is not None:
                        arr[
                            FEATURES.index(r["target_feature"]),
                            FEATURES.index(r["measured_feature"]),
                        ] = r["mean"]
                fig, ax = plt.subplots(figsize=(6.4, 5.4), layout="constrained")
                cmap = plt.get_cmap(palette).copy()
                cmap.set_bad("#cccccc")
                im = ax.imshow(
                    np.ma.masked_invalid(arr), cmap=cmap, vmin=low, vmax=high
                )
                for i in range(5):
                    for j in range(5):
                        ax.text(
                            j,
                            i,
                            "NA" if np.isnan(arr[i, j]) else f"{arr[i, j]:.3f}",
                            ha="center",
                            va="center",
                            fontsize=9,
                            color="black"
                            if np.isnan(arr[i, j])
                            or (
                                statistic == "mean_signed_change"
                                and abs(arr[i, j]) < 0.5
                            )
                            or (statistic == "mean_absolute_change" and arr[i, j] > 0.5)
                            else "white",
                        )
                counts = {r["target_feature"]: r["n_tasks"] for r in subset}
                ax.set_xticks(range(5), SHORT, rotation=30, ha="right")
                ax.set_yticks(
                    range(5),
                    [
                        f"{s} (n={counts.get(f, 0)})"
                        for f, s in zip(FEATURES, SHORT, strict=True)
                    ],
                )
                ax.set(
                    xlabel="Measured feature",
                    ylabel="Controlled feature",
                    title=f"{label} · {condition}\n{statistic.replace('_', ' ')}",
                )
                fig.colorbar(im, ax=ax, label="Qwen score difference (score units)")
                save(fig, f"FIGURE_{number}_{model}_{condition}")

    def metric(model, condition, name):
        return next(
            r
            for r in data["models"]
            if r["model"] == model
            and r["condition"] == condition
            and r["metric"] == name
        )

    x = np.arange(4)
    fig, ax = plt.subplots(figsize=(8.5, 4.2), layout="constrained")
    for j, condition in enumerate(CONDITIONS):
        rows = [metric(m, condition, "mean_absolute_non_target_drift") for m in MODELS]
        positions = x + (j - 0.5) * 0.32
        values = [r["mean"] if r["mean"] is not None else np.nan for r in rows]
        ax.bar(positions, values, width=0.30, label=condition)
        for pos, row in zip(positions, rows, strict=True):
            if row["ci95_low"] is not None:
                ax.vlines(
                    pos, row["ci95_low"], row["ci95_high"], color="black", linewidth=1
                )
            if row["mean"] is None:
                ax.text(pos, 0.02, "NA", ha="center")
    ax.set_xticks(x, LABELS)
    ax.set(
        ylabel="Mean absolute non-target drift",
        ylim=(0, 1),
        title="Full available-case task means; base-cluster 95% CIs where defined",
    )
    ax.legend()
    save(fig, "FIGURE_3_NON_TARGET_DRIFT")
    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    positions = np.arange(8)
    for shift, key, label in [
        (-0.17, "mean_absolute_target_change", "Target"),
        (0.17, "mean_absolute_non_target_drift", "Four non-targets"),
    ]:
        values = [metric(m, c, key)["mean"] for m in MODELS for c in CONDITIONS]
        ax.bar(
            positions + shift,
            [v if v is not None else np.nan for v in values],
            width=0.32,
            label=label,
        )
        for p, v in zip(positions + shift, values, strict=True):
            if v is None:
                ax.text(p, 0.02, "NA", ha="center")
    ax.set_xticks(
        positions,
        [f"{m}\n{c}" for m in LABELS for c in CONDITIONS],
        rotation=20,
        ha="right",
    )
    ax.set(
        ylabel="Mean absolute score change",
        ylim=(0, 1),
        title="Target and non-target changes · full available-case",
    )
    ax.legend()
    save(fig, "FIGURE_4_TARGET_NON_TARGET")
    fig, axes = plt.subplots(
        2, 4, figsize=(15, 7), sharex=True, sharey=True, layout="constrained"
    )
    for j, condition in enumerate(CONDITIONS):
        for i, (model, label) in enumerate(zip(MODELS, LABELS, strict=True)):
            ax, bottom = axes[j, i], np.zeros(5)
            for change, color in [
                ("increase", "#287a9f"),
                ("decrease", "#ca6c38"),
                ("unchanged", "#b9b9b9"),
            ]:
                values = []
                for feature in FEATURES:
                    cells = [
                        r
                        for r in full
                        if r["model"] == model
                        and r["condition"] == condition
                        and r["target_feature"] == feature
                        and r["measured_feature"] != feature
                        and r["statistic"] == change + "_percentage"
                        and r["mean"] is not None
                    ]
                    values.append(mean(r["mean"] for r in cells) if cells else np.nan)
                ax.bar(np.arange(5), values, bottom=bottom, color=color, label=change)
                bottom += np.nan_to_num(values)
            for pos, value in enumerate(bottom):
                if value == 0:
                    ax.text(pos, 5, "NA", ha="center")
            ax.set(title=f"{label} · {condition}", ylim=(0, 100), xlim=(-0.6, 4.6))
            ax.set_xticks(range(5), SHORT, rotation=35, ha="right")
    axes[0, 0].set_ylabel("Non-target change (%)")
    axes[1, 0].set_ylabel("Non-target change (%)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=9)
    fig.suptitle("Scene-change directions by controlled feature; equal task weights")
    save(fig, "FIGURE_5_CHANGE_DIRECTIONS")
    return dict(status="GENERATED", files=files)


def markdown_table(rows, fields):
    def display(v):
        return "NA" if v is None else f"{v:.6f}" if isinstance(v, float) else str(v)

    return (
        "| "
        + " | ".join(fields)
        + " |\n|"
        + "|".join(["---"] * len(fields))
        + "|\n"
        + "\n".join(
            "| " + " | ".join(display(r.get(k)) for k in fields) + " |" for r in rows
        )
    )


def render(output, data):
    output = Path(output)
    for filename, key in TABLES:
        csv_table(output / filename, data[key])
    for statistic in (
        "mean_signed_change",
        "mean_absolute_change",
        "increase_percentage",
        "decrease_percentage",
        "unchanged_percentage",
    ):
        csv_table(
            output / ("04_MATRIX_" + statistic.upper() + ".csv"),
            [r for r in data["matrices"] if r["statistic"] == statistic],
        )
    figure_result = plots(output, data)
    summary = dict(
        schema_version="e05.feature-diff.summary/1.0",
        protocol_id="E05_4_FEATURE_DIFF_V1",
        implementation_ready=True,
        input_bindings_ready=True,
        real_analysis_complete=True,
        scientific_validity_verified=False,
        population_tasks=len(data["tasks"]),
        global_common_task_count=len(data["common_task_ids"]),
        global_common_task_ids=data["common_task_ids"],
        coverage=data["coverage"],
        model_comparison=data["models"],
        global_common_comparison=data["global_common"],
        figures=figure_result,
        zero_epsilon=EPSILON,
        bootstrap_seed=SEED,
        bootstrap_replications=REPLICATIONS,
        llm_inference=False,
    )
    write(output / "scientific_summary.json", summary)
    write(output / "input_provenance.json", data["provenance"])
    overall = [
        r for r in data["drift"] if r["group_by"] == "overall" and r["mean"] is not None
    ]
    extrema = ""
    if overall:
        largest, smallest = (
            max(overall, key=lambda r: r["mean"]),
            min(overall, key=lambda r: r["mean"]),
        )
        extrema = f"Largest observed model-condition mean non-target drift: {largest['model']} {largest['condition']} ({largest['mean']:.6f}). Smallest: {smallest['model']} {smallest['condition']} ({smallest['mean']:.6f})."
    individual = [
        r for r in data["tasks"] if r["mean_absolute_non_target_drift"] is not None
    ]
    if individual:
        for label, fn in [("Largest", max), ("Smallest", min)]:
            row = fn(individual, key=lambda r: r["mean_absolute_non_target_drift"])
            extrema += f"\n\n{label} observed task drift: {row['model']} {row['condition']} {row['task_id']} = {row['mean_absolute_non_target_drift']:.6f}."
    frequency = []
    for feature, short in zip(FEATURES, SHORT, strict=True):
        eligible = [t for t in individual if t["target_feature"] != feature]
        for change in ("increase", "decrease"):
            if eligible:
                frequency.append(
                    dict(
                        feature=feature,
                        change=change,
                        scene_count=sum(t[f"{short}_{change}_count"] for t in eligible),
                        equal_task_rate=mean(
                            t[f"{short}_{change}_rate"] for t in eligible
                        ),
                    )
                )
    for change in ("increase", "decrease"):
        subset = [r for r in frequency if r["change"] == change]
        if subset:
            winner = max(subset, key=lambda r: r["equal_task_rate"])
            extrema += f"\n\nMost frequent non-target {change} by equal-task rate: {winner['feature']} ({winner['equal_task_rate']:.6f}; {winner['scene_count']} scene-task occurrences). Reused scenes are not independent."
    comparison = [
        r
        for r in data["models"]
        if r["metric"]
        in ("mean_absolute_non_target_drift", "mean_absolute_target_change")
    ]
    paired = [
        r
        for r in data["paired"]
        if r["record_type"] == "SUMMARY" and r["target_feature"] == "ALL"
    ]
    changes = []
    for row in comparison:
        common = next(
            r
            for r in data["global_common"]
            if r["model"] == row["model"]
            and r["condition"] == row["condition"]
            and r["metric"] == row["metric"]
        )
        changes.append(
            dict(
                model=row["model"],
                condition=row["condition"],
                metric=row["metric"],
                available_mean=row["mean"],
                common_mean=common["mean"],
                common_minus_available=common["mean"] - row["mean"]
                if common["mean"] is not None and row["mean"] is not None
                else None,
            )
        )
    interactions = []
    for model in MODELS:
        for condition in CONDITIONS:
            cells = [
                r
                for r in data["matrices"]
                if r["scope"] == "FULL_AVAILABLE_CASE"
                and r["target_direction"] == "ALL"
                and r["statistic"] == "mean_absolute_change"
                and not r["is_target"]
                and r["model"] == model
                and r["condition"] == condition
                and r["mean"] is not None
            ]
            if cells:
                winner = max(cells, key=lambda r: r["mean"])
                interactions.append(
                    {
                        k: winner[k]
                        for k in (
                            "model",
                            "condition",
                            "target_feature",
                            "measured_feature",
                            "n_tasks",
                            "mean",
                        )
                    }
                )
    reason_counts = {}
    for exclusion in data["exclusions"]:
        if exclusion["level"] == "TASK":
            reason_counts[exclusion["status"]] = (
                reason_counts.get(exclusion["status"], 0) + 1
            )
    text = "# E05-4-FEATURE-DIFF\n\n"
    text += "## Research question\n\nWhen one target feature is modified, how do all five measured features change, especially the four non-target features?\n\n"
    text += "## Historical provenance and population\n\nFrozen TasksetV5: 240 tasks, 48 bases, ten source films, five controlled features, four models × two conditions = 1920 attempted task records and 16000 scene slots. Exact artifact hashes, checkpoint, measurement configuration and repository commits are in input_provenance.json. No new measurement or rewrite was performed.\n\n"
    text += (
        "## Coverage\n\n"
        + markdown_table(
            data["coverage"],
            [
                "model",
                "condition",
                "planned_tasks",
                "available_rewrite_tasks",
                "available_reanalysis_tasks",
                "complete_measurement_tasks",
                "partial_measurement_tasks",
                "missing_tasks",
                "invalid_tasks",
            ],
        )
        + "\n\n"
    )
    text += "## Metric definitions\n\nDelta = AFTER − BEFORE. Absolute change = abs(delta). Non-target drift = sum of absolute changes over all 4*n non-target scene-feature points divided by 4*n. Complete tasks only. Matrices average within tasks, then across tasks with equal task weights. Direction uses epsilon 1e-12; stored deltas are unchanged. Scores and changes use score units; rates are fractions; matrix percentages use percent.\n\n"
    text += (
        "## Overall feature changes and non-target drift\n\n"
        + markdown_table(
            comparison,
            [
                "model",
                "condition",
                "metric",
                "n_tasks",
                "mean",
                "median",
                "standard_deviation",
                "ci95_low",
                "ci95_high",
            ],
        )
        + "\n\n"
        + (extrema or "No complete measurable tasks; extrema are undefined.")
        + "\n\n"
    )
    text += "## Five-by-five interaction analysis\n\nRows control one feature; columns measure each feature. Diagonal and off-diagonal cells remain separate. Figure 1 and the mean-absolute matrix are primary; Figure 2 uses a separate signed scale. NA cells are gray. Numeric tables contain all five statistics, explicit task counts and scene coverage for all eight combinations and the global intersection.\n\n"
    text += (
        "Largest off-diagonal mean absolute cell in each model-condition (descriptive):\n\n"
        + markdown_table(
            interactions,
            [
                "model",
                "condition",
                "target_feature",
                "measured_feature",
                "n_tasks",
                "mean",
            ],
        )
        + "\n\n"
    )
    if figure_result["status"] == "GENERATED":
        text += (
            "Primary absolute interaction heatmaps:\n\n"
            + "\n".join(
                f"- [{label} {condition}](FIGURE_1_{model}_{condition}.png)"
                for model, label in zip(MODELS, LABELS, strict=True)
                for condition in CONDITIONS
            )
            + "\n\n"
        )
    else:
        text += (
            "Plot dependency blocker: "
            + figure_result.get("reason", "unavailable")
            + ". Numerical tables remain available.\n\n"
        )
    text += (
        "## DP-v1 versus CG-v1\n\nPaired differences are CG minus DP within identical complete task IDs and intervals.\n\n"
        + markdown_table(
            paired,
            [
                "model",
                "metric",
                "dp_total_measurable_tasks",
                "cg_total_measurable_tasks",
                "jointly_measurable_tasks",
                "n_tasks",
                "mean",
                "median",
                "ci95_low",
                "ci95_high",
            ],
        )
        + "\n\nCell differences are restricted to each task’s controlled-feature row. The CSV includes individual differences and their distribution.\n\n"
    )
    text += (
        f"## Four-model comparisons and available-case sensitivity\n\nThe actual all-eight complete intersection contains {len(data['common_task_ids'])} tasks. It is calculated afresh; no historical 186-task set is substituted. Global-common minus available-case means:\n\n"
        + markdown_table(
            changes,
            [
                "model",
                "condition",
                "metric",
                "available_mean",
                "common_mean",
                "common_minus_available",
            ],
        )
        + "\n\n"
    )
    text += "## Increase/decrease stratification\n\nHistorical directions are scene-level INCREASE, DECREASE or MAINTAIN, read from exact archived planner deltas. Heterogeneous tasks are MIXED. Matrices include separate scene-direction strata with within-task denominators; opposite signed changes can cancel while absolute change remains positive. 09_DIRECTION_DISTRIBUTION.csv preserves per-task controlled/measured-feature counts and rates.\n\n"
    text += "## Missingness and exclusions\n\n08_EXCLUSIONS.csv accounts for every omitted task and scene with an explicit reason. Partial tasks contribute diagnostic scene rows but no complete-task metric. Missing values are NA in CSV and null in JSON. Broken hashes/lineage/population/instrument bindings fail preflight rather than becoming historical model failure.\n\n"
    text += (
        "Task exclusions by classification: "
        + json.dumps(reason_counts, sort_keys=True)
        + ".\n\n"
    )
    text += "## Uncertainty and sensitivity\n\nTask SD/quantiles are descriptive. Fixed-seed (250504) base-interval percentile bootstrap uses 2000 replications where at least eight bases are eligible. Paired differences retain matched resampling. See each summary’s CI limitation and eligible-cluster count.\n\n"
    text += (
        "## Methodological limitations\n\n"
        + LIMITATIONS
        + "\n## Reviewer 1, Comment 6 coverage\n\nThe off-diagonal matrices, drift distributions, direction strata and matched comparisons quantify movement of the four non-target measured features. They do not establish semantic preservation or require non-target scores to remain fixed.\n"
    )
    (output / "E05_4_FEATURE_DIFF_REPORT.md").write_text(text)
    (output / "E05_4_FEATURE_DIFF_LIMITATIONS.md").write_text(
        "# Methodological limitations\n\n" + LIMITATIONS
    )
    dictionary = "# Technical protocol and data dictionary\n\nE05_4_FEATURE_DIFF_V1 / 1.0.0. PREPARE → VALIDATE → ANALYZE → REPORT.\n\n"
    dictionary += "Original float values and deltas are retained at JSON double precision in the immutable ANALYZE artifact analysis.json. CSV floats use fixed 17 decimal places; NA means undefined/missing, never zero. Lists use compact JSON. Columns follow identity fields then alphabetical order; rows follow fixed model, condition, feature and sorted-task traversal. scene_order is one-based within the frozen interval; scene_id and film identify the scene independently.\n\n"
    dictionary += (
        "Identity: model/condition/task_id/base_interval_id/source_film_id/target_feature/target_direction/interval_length. Canonical feature keys: "
        + ", ".join(FEATURES)
        + ". Short CSV suffixes map in that order to "
        + ", ".join(SHORT)
        + ".\n\n"
    )
    dictionary += "before_*/after_*: [0,1] score units. delta_*: after-before in [-1,1]. abs_delta_*: absolute score difference [0,1]. mean_*/median_*: within-task scene summaries. *_count/n_tasks/*_tasks/*_scenes/*_pairs/*_slots: integer counts. *_rate: fraction [0,1]. *_percentage: percent [0,100]. mean/median/standard_deviation/minimum/maximum/q*: distribution of equal-weight task metrics in score units, except matrix percentages. ci95_*: base-cluster percentile interval in metric units; bootstrap_seed/replications/eligible_clusters identify estimation. task_ids/base_interval_ids/source_film_ids retain exact aggregate membership.\n\n"
    dictionary += "scope separates FULL_AVAILABLE_CASE and GLOBAL_MATCHED_COMMON. statistic selects five separate matrix datasets. target_direction=ALL pools complete tasks; INCREASE/DECREASE/MAINTAIN matrix strata average only scenes with that archived directive within each task. is_target identifies diagonal. pair_status distinguishes VALID/MISSING/INVALID slots; status distinguishes COMPLETE/PARTIAL and explicit failures. expected=valid+missing+invalid for scene pairs; planned=complete+partial+missing+invalid for tasks.\n\n"
    dictionary += "Paired CSV: SUMMARY describes the distribution; TASK_DIFFERENCE gives dp_value, cg_value and difference=CG-DP. n_tasks on a SUMMARY is the metric-specific paired count; jointly_measurable_tasks is the model-level intersection. Matrix task differences exist only in the task’s controlled row. Uncertainty below eight bases is undefined. Non-target drift group_by selects overall, controlled/measured feature, direction, length, film or individual-task distributions.\n\n"
    for filename, key in TABLES:
        dictionary += (
            f"## {filename}\n\nColumns: " + ", ".join(columns(data[key])) + ".\n\n"
        )
    dictionary += "Plot status: " + json.dumps(figure_result) + "\n"
    (output / "E05_4_FEATURE_DIFF_TECHNICAL.md").write_text(dictionary)
    artifacts = [
        dict(path=str(p.relative_to(output)), sha256=sha(p), bytes=p.stat().st_size)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    ]
    write(
        output / "artifact_manifest.json",
        dict(
            schema_version="e05.feature-diff.artifacts/1.0",
            artifacts=artifacts,
            seal="Central run_manifest.json and integrity/SEALED.json are authoritative; this manifest excludes itself",
        ),
    )
    return summary
