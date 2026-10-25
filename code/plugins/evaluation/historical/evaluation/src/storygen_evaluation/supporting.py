from __future__ import annotations

import math
import platform
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, read_jsonl, sha256_file, write_csv, write_json
from .provenance import same_provenance, required_sha, required_measurement

SUPPORT_CONTRACT_ID = "storygen.supporting-analysis"
CONTRACT_VERSION = "2.4"
BLOCK_VERSION = "2.4.1"

PAPER22_EXPECTED = {
    "rewrite_model": "gemma3-12b-it-gguf",
    "pair_n": 237,
    "cluster_n": 48,
    "resamples": 10_000,
    "seed": 42,
    "target_improvement": {
        "dp": 0.8776,
        "cg": 0.9325,
        "difference_pp": 5.49,
        "ci95_pp": [1.26, 9.75],
    },
    "directional_accuracy": {
        "dp": 0.7195,
        "cg": 0.7354,
        "difference_pp": 1.60,
        "ci95_pp": [-0.39, 3.55],
    },
}


def _eval_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path / "evaluation_run_manifest.json")
    if manifest.get("contract_id") != "storygen.evaluation-run" or str(manifest.get("contract_version")) != "2.4":
        raise RuntimeError(f"Evaluation V2.4 artifact required: {path}")
    return manifest


_same_provenance = same_provenance


def _mean_numeric(rows: list[dict[str, Any]], key: str) -> float:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"Expected finite numeric {key!r} in paired eligible row")
        number = float(value)
        if not math.isfinite(number):
            raise RuntimeError(f"Expected finite numeric {key!r} in paired eligible row")
        values.append(number)
    if not values:
        raise RuntimeError("Cannot aggregate an empty paired population")
    return sum(values) / len(values)


def _ti(rows: list[dict[str, Any]]) -> float:
    if not rows:
        raise RuntimeError("Cannot aggregate an empty paired population")
    return sum(bool(row.get("target_improved")) for row in rows) / len(rows)


def _percentile(values: list[float], probability: float) -> float:
    """NumPy-style linear percentile without adding NumPy as an Evaluation dependency."""
    if not values:
        raise RuntimeError("Cannot calculate percentile of an empty sample")
    if not 0.0 <= probability <= 1.0:
        raise ValueError(probability)
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _metric_values(task_ids: list[str], rows: dict[str, dict[str, Any]]) -> tuple[float, float]:
    selected = [rows[task_id] for task_id in task_ids]
    return _ti(selected), _mean_numeric(selected, "directional_accuracy")


def _round_pp(value: float) -> float:
    return round(value * 100.0, 2)


def cluster_bootstrap_paired(
    *,
    dp_run: Path,
    cg_run: Path,
    taskset_runtime: Path,
    resamples: int = 10_000,
    seed: int = 42,
    confidence_level: float = 0.95,
    model_id: str | None = None,
    rng_engine: str = "python-mt19937",
    artifact_paths=None,
) -> dict[str, Any]:
    if resamples < 1:
        raise ValueError("resamples must be >= 1")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")

    dp_manifest = _eval_manifest(dp_run)
    cg_manifest = _eval_manifest(cg_run)
    _same_provenance([dp_manifest, cg_manifest], taskset_runtime, artifact_paths)
    if dp_manifest.get("method") != "DP-v1" or cg_manifest.get("method") != "CG-v1":
        raise RuntimeError("Supporting bootstrap requires DP-v1 then CG-v1 evaluation artifacts")
    if dp_manifest.get("rewrite_model") != cg_manifest.get("rewrite_model"):
        raise RuntimeError("DP and CG evaluation artifacts must use the same rewrite model")
    resolved_model = str(dp_manifest.get("rewrite_model"))
    if model_id is not None and model_id != resolved_model:
        raise RuntimeError("--model-id does not match evaluation manifest rewrite_model")

    tasks = read_json(taskset_runtime).get("tasks") or []
    if not tasks:
        raise RuntimeError("Frozen taskset is empty")
    frozen_ids = [str(task["task_id"]) for task in tasks]
    task_by_id = {str(task["task_id"]): task for task in tasks}

    dp_rows = {str(row["task_id"]): row for row in read_jsonl(dp_run / "evaluation_task_records.jsonl")}
    cg_rows = {str(row["task_id"]): row for row in read_jsonl(cg_run / "evaluation_task_records.jsonl")}
    expected = set(frozen_ids)
    if set(dp_rows) != expected or set(cg_rows) != expected:
        raise RuntimeError("Evaluation task records must exactly match the frozen taskset IDs")

    pair_ids = [task_id for task_id in frozen_ids if dp_rows[task_id].get("metric_eligible") and cg_rows[task_id].get("metric_eligible")]
    if not pair_ids:
        raise RuntimeError("No mutually measurable DP-v1/CG-v1 tasks")

    clusters: dict[str, list[str]] = defaultdict(list)
    cluster_order: list[str] = []
    for task_id in pair_ids:
        task_cluster = str(task_by_id[task_id].get("base_interval_id") or "")
        record_cluster_dp = str(dp_rows[task_id].get("base_interval_id") or "")
        record_cluster_cg = str(cg_rows[task_id].get("base_interval_id") or "")
        if not task_cluster:
            raise RuntimeError(f"Missing base_interval_id for {task_id}")
        if record_cluster_dp != task_cluster or record_cluster_cg != task_cluster:
            raise RuntimeError(f"base_interval_id mismatch for {task_id}")
        if task_cluster not in clusters:
            cluster_order.append(task_cluster)
        clusters[task_cluster].append(task_id)

    dp_ti, dp_da = _metric_values(pair_ids, dp_rows)
    cg_ti, cg_da = _metric_values(pair_ids, cg_rows)
    point_ti_diff = cg_ti - dp_ti
    point_da_diff = cg_da - dp_da

    if rng_engine not in {"python-mt19937", "numpy-pcg64"}:
        raise ValueError(f"Unknown bootstrap RNG procedure: {rng_engine}")
    if rng_engine == "numpy-pcg64":
        # Recovered table_a6_bootstrap.py procedure. Explicit opt-in preserves
        # the historical supporting-analysis MT19937 calculation and its lock.
        import numpy as np

        cluster_order = sorted(clusters)
        cluster_n = len(cluster_order)
        n = np.array([len(clusters[c]) for c in cluster_order], dtype=np.int64)
        sums = {}
        for label, rows in (("dp", dp_rows), ("cg", cg_rows)):
            sums[label] = np.array([
                [sum(float(rows[t][key]) for t in clusters[c]) for c in cluster_order]
                for key in ("target_improved", "directional_accuracy")
            ], dtype=np.float64)
        generator = np.random.Generator(np.random.PCG64(seed))
        samples = np.empty((resamples, 2), dtype=np.float64)
        for i in range(resamples):
            counts = np.bincount(generator.integers(0, cluster_n, size=cluster_n), minlength=cluster_n).astype(np.float64)
            for metric in range(2):
                samples[i, metric] = 100.0 * float(counts @ (sums["cg"][metric] - sums["dp"][metric])) / float(counts @ n)
        alpha_percent = (1.0 - confidence_level) * 50.0
        intervals = np.percentile(samples, [alpha_percent, 100.0 - alpha_percent], axis=0, method="linear") / 100.0
        ti_ci, da_ci = intervals[:, 0].tolist(), intervals[:, 1].tolist()
    else:
        rng = random.Random(seed)
        ti_differences: list[float] = []
        da_differences: list[float] = []
        cluster_n = len(cluster_order)
        for _ in range(resamples):
            sampled_ids: list[str] = []
            for _draw in range(cluster_n):
                cluster_id = cluster_order[rng.randrange(cluster_n)]
                sampled_ids.extend(clusters[cluster_id])
            sample_dp_ti, sample_dp_da = _metric_values(sampled_ids, dp_rows)
            sample_cg_ti, sample_cg_da = _metric_values(sampled_ids, cg_rows)
            ti_differences.append(sample_cg_ti - sample_dp_ti)
            da_differences.append(sample_cg_da - sample_dp_da)

        alpha = (1.0 - confidence_level) / 2.0
        ti_ci = [_percentile(ti_differences, alpha), _percentile(ti_differences, 1.0 - alpha)]
        da_ci = [_percentile(da_differences, alpha), _percentile(da_differences, 1.0 - alpha)]
    return {
        "contract_id": SUPPORT_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "analysis": "base_interval_clustered_paired_bootstrap",
        "rewrite_model": resolved_model,
        "pair_n": len(pair_ids),
        "cluster_n": cluster_n,
        "cluster_key": "base_interval_id",
        "resamples": resamples,
        "seed": seed,
        "rng": "numpy.random.Generator/PCG64" if rng_engine == "numpy-pcg64" else "python.random.Random/MT19937",
        "confidence_level": confidence_level,
        "interval_method": "percentile_linear",
        "aggregation": "task_macro_with_cluster_resampling",
        "target_improvement": {
            "dp": dp_ti,
            "cg": cg_ti,
            "difference": point_ti_diff,
            "difference_pp": _round_pp(point_ti_diff),
            "ci": ti_ci,
            "ci_pp": [_round_pp(ti_ci[0]), _round_pp(ti_ci[1])],
        },
        "directional_accuracy": {
            "dp": dp_da,
            "cg": cg_da,
            "difference": point_da_diff,
            "difference_pp": _round_pp(point_da_diff),
            "ci": da_ci,
            "ci_pp": [_round_pp(da_ci[0]), _round_pp(da_ci[1])],
        },
        "pair_task_ids": pair_ids,
        "cluster_ids": cluster_order,
    }


def paired_point_differences(entries: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    taskset_shas: set[str] = set()
    measurement_identities: set[str] = set()
    for model, path in entries:
        if model in seen:
            raise RuntimeError(f"Duplicate paired-summary model: {model}")
        seen.add(model)
        manifest = read_json(path / "paired_summary_manifest.json")
        summary = read_json(path / "paired_summary.json")
        if manifest.get("contract_id") != "storygen.paired-summary" or str(manifest.get("contract_version")) != "2.4":
            raise RuntimeError(f"Paired Summary V2.4 artifact required: {path}")
        if str(manifest.get("rewrite_model")) != model or str(summary.get("rewrite_model")) != model:
            raise RuntimeError(f"Paired-summary model identity mismatch: {model}")
        taskset_shas.add(required_sha(manifest.get("taskset", {}).get("sha256"), "paired taskset"))
        measurement_identities.add(str(sorted(required_measurement(manifest.get("measurement_identity")).items())))
        dp_ti = float(summary["dp_target_improvement"])
        cg_ti = float(summary["cg_target_improvement"])
        dp_da = float(summary["dp_directional_accuracy"])
        cg_da = float(summary["cg_directional_accuracy"])
        rows.append({
            "model": model,
            "pair_n": int(summary["pair_n"]),
            "delta_ti_pp": _round_pp(cg_ti - dp_ti),
            "delta_da_pp": _round_pp(cg_da - dp_da),
        })
    if len(taskset_shas) > 1:
        raise RuntimeError("Paired summaries do not share the same frozen taskset")
    if len(measurement_identities) > 1:
        raise RuntimeError("Paired summaries do not share the same measurement identity")
    return rows


def paper22_validation(result: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, actual: Any, expected: Any) -> None:
        checks.append({"check": name, "passed": bool(ok), "actual": actual, "expected": expected})

    expected = PAPER22_EXPECTED
    check("rewrite_model", result.get("rewrite_model") == expected["rewrite_model"], result.get("rewrite_model"), expected["rewrite_model"])
    check("pair_n", result.get("pair_n") == expected["pair_n"], result.get("pair_n"), expected["pair_n"])
    check("cluster_n", result.get("cluster_n") == expected["cluster_n"], result.get("cluster_n"), expected["cluster_n"])
    check("resamples", result.get("resamples") == expected["resamples"], result.get("resamples"), expected["resamples"])
    check("seed", result.get("seed") == expected["seed"], result.get("seed"), expected["seed"])

    for metric in ("target_improvement", "directional_accuracy"):
        actual = result[metric]
        exp = expected[metric]
        check(f"{metric}:dp", round(float(actual["dp"]), 4) == exp["dp"], round(float(actual["dp"]), 4), exp["dp"])
        check(f"{metric}:cg", round(float(actual["cg"]), 4) == exp["cg"], round(float(actual["cg"]), 4), exp["cg"])
        check(f"{metric}:difference_pp", round(float(actual["difference_pp"]), 2) == exp["difference_pp"], round(float(actual["difference_pp"]), 2), exp["difference_pp"])
        check(f"{metric}:ci95_pp", [round(float(x), 2) for x in actual["ci_pp"]] == exp["ci95_pp"], [round(float(x), 2) for x in actual["ci_pp"]], exp["ci95_pp"])

    return {
        "valid": all(item["passed"] for item in checks),
        "paper22_frozen_values_checked": True,
        "checks": checks,
    }


def build_supporting_analysis(
    *,
    dp_run: Path,
    cg_run: Path,
    taskset_runtime: Path,
    output: Path,
    paired_entries: list[tuple[str, Path]] | None = None,
    resamples: int = 10_000,
    seed: int = 42,
    confidence_level: float = 0.95,
    model_id: str | None = None,
    paper22_lock: bool = False,
    rng_engine: str = "python-mt19937",
    artifact_paths=None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    bootstrap = cluster_bootstrap_paired(
        dp_run=dp_run,
        cg_run=cg_run,
        taskset_runtime=taskset_runtime,
        resamples=resamples,
        seed=seed,
        confidence_level=confidence_level,
        model_id=model_id,
        rng_engine=rng_engine,
        artifact_paths=artifact_paths,
    )
    write_json(output / "cluster_bootstrap.json", bootstrap)
    write_csv(output / "cluster_bootstrap.csv", [
        {
            "metric": "Target Improvement",
            "dp": bootstrap["target_improvement"]["dp"],
            "cg": bootstrap["target_improvement"]["cg"],
            "cg_minus_dp_pp": bootstrap["target_improvement"]["difference_pp"],
            "ci_lower_pp": bootstrap["target_improvement"]["ci_pp"][0],
            "ci_upper_pp": bootstrap["target_improvement"]["ci_pp"][1],
        },
        {
            "metric": "Directional Accuracy",
            "dp": bootstrap["directional_accuracy"]["dp"],
            "cg": bootstrap["directional_accuracy"]["cg"],
            "cg_minus_dp_pp": bootstrap["directional_accuracy"]["difference_pp"],
            "ci_lower_pp": bootstrap["directional_accuracy"]["ci_pp"][0],
            "ci_upper_pp": bootstrap["directional_accuracy"]["ci_pp"][1],
        },
    ])

    paired_rows: list[dict[str, Any]] = []
    if paired_entries:
        paired_rows = paired_point_differences(paired_entries)
        write_json(output / "within_model_differences.json", {
            "contract_id": SUPPORT_CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "block_version": BLOCK_VERSION,
            "analysis": "within_model_paired_point_differences",
            "rows": paired_rows,
        })
        write_csv(output / "within_model_differences.csv", paired_rows)

    validation = paper22_validation(bootstrap) if paper22_lock else {
        "valid": True,
        "paper22_frozen_values_checked": False,
        "checks": [],
    }
    validation["primary_tables_affected"] = False
    validation["paper_ready_bundle_modified"] = False
    write_json(output / "VALIDATION_REPORT.json", validation)

    runtime = {"python": platform.python_version()}
    if rng_engine == "numpy-pcg64":
        import numpy as np
        runtime["numpy"] = np.__version__
    manifest = {
        "contract_id": SUPPORT_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "taskset": {"path": str(taskset_runtime), "sha256": sha256_file(taskset_runtime)},
        "dp_evaluation": {"path": str(dp_run), "manifest_sha256": sha256_file(dp_run / "evaluation_run_manifest.json"), "records_sha256": sha256_file(dp_run / "evaluation_task_records.jsonl")},
        "cg_evaluation": {"path": str(cg_run), "manifest_sha256": sha256_file(cg_run / "evaluation_run_manifest.json"), "records_sha256": sha256_file(cg_run / "evaluation_task_records.jsonl")},
        "paired_summaries": [
            {"model": model, "path": str(path), "manifest_sha256": sha256_file(path / "paired_summary_manifest.json")}
            for model, path in (paired_entries or [])
        ],
        "bootstrap": {
            "cluster_key": "base_interval_id",
            "resamples": resamples,
            "seed": seed,
            "confidence_level": confidence_level,
            "rng": bootstrap["rng"],
            "cluster_ids": bootstrap["cluster_ids"],
            "rng_engine": rng_engine,
            "runtime": runtime,
            "cluster_order": "sorted_base_interval_ids" if rng_engine == "numpy-pcg64" else "first_paired_task_occurrence",
            "interval_method": "percentile_linear",
        },
        "paper22_lock": paper22_lock,
        "primary_tables_affected": False,
    }
    write_json(output / "MANIFEST.json", manifest)

    return {
        "supporting_analysis": True,
        "output": str(output),
        "bootstrap": bootstrap,
        "within_model_differences": paired_rows,
        "validation": validation,
    }
