from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, read_jsonl, sha256_file, write_csv, write_json
from .provenance import same_provenance

PAIR_CONTRACT_ID = "storygen.paired-summary"
CROSS_CONTRACT_ID = "storygen.cross-model-summary"
CONTRACT_VERSION = "2.4"
BLOCK_VERSION = "2.4.1"


def _eval_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path / "evaluation_run_manifest.json")
    if manifest.get("contract_id") != "storygen.evaluation-run" or str(manifest.get("contract_version")) != "2.4":
        raise RuntimeError(f"Evaluation V2.4 artifact required: {path}")
    return manifest


_same_provenance = same_provenance


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(row[key]) for row in rows
        if row.get(key) is not None
        and isinstance(row.get(key), (int, float))
        and not isinstance(row.get(key), bool)
        and math.isfinite(float(row[key]))
    ]
    return sum(values) / len(values) if values else None


def _ti(rows: list[dict[str, Any]]) -> float | None:
    return sum(bool(row.get("target_improved")) for row in rows) / len(rows) if rows else None


def _paired_rows(task_ids: list[str], dp: dict[str, dict], cg: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    return [dp[task_id] for task_id in task_ids], [cg[task_id] for task_id in task_ids]


def _summary_row(group_key: str, group_value: Any, task_ids: list[str], dp: dict[str, dict], cg: dict[str, dict]) -> dict[str, Any]:
    dp_rows, cg_rows = _paired_rows(task_ids, dp, cg)
    return {
        group_key: group_value,
        "pair_n": len(task_ids),
        "dp_target_improvement": _ti(dp_rows),
        "cg_target_improvement": _ti(cg_rows),
        "dp_directional_accuracy": _mean(dp_rows, "directional_accuracy"),
        "cg_directional_accuracy": _mean(cg_rows, "directional_accuracy"),
    }


def paired_summary(dp_run: Path, cg_run: Path, taskset: Path, output: Path, model_id: str | None = None, *, artifact_paths=None):
    dp_manifest = _eval_manifest(dp_run)
    cg_manifest = _eval_manifest(cg_run)
    _same_provenance([dp_manifest, cg_manifest], taskset, artifact_paths)
    if dp_manifest.get("method") != "DP-v1" or cg_manifest.get("method") != "CG-v1":
        raise RuntimeError("Paired summary requires DP-v1 then CG-v1 evaluation artifacts")
    if dp_manifest.get("rewrite_model") != cg_manifest.get("rewrite_model"):
        raise RuntimeError("DP and CG evaluation artifacts must use the same rewrite model")
    resolved_model = model_id or str(dp_manifest.get("rewrite_model"))
    if model_id is not None and model_id != dp_manifest.get("rewrite_model"):
        raise RuntimeError("--model-id does not match evaluation manifest rewrite_model")

    tasks = read_json(taskset).get("tasks") or []
    frozen_ids = [task["task_id"] for task in tasks]
    task_by_id = {task["task_id"]: task for task in tasks}
    dp_rows = read_jsonl(dp_run / "evaluation_task_records.jsonl")
    cg_rows = read_jsonl(cg_run / "evaluation_task_records.jsonl")
    dp = {row["task_id"]: row for row in dp_rows}
    cg = {row["task_id"]: row for row in cg_rows}
    if set(dp) != set(frozen_ids) or set(cg) != set(frozen_ids):
        raise RuntimeError("Evaluation task records must exactly match the frozen taskset IDs")

    pair_ids = [task_id for task_id in frozen_ids if dp[task_id].get("metric_eligible") and cg[task_id].get("metric_eligible")]
    pair_dp, pair_cg = _paired_rows(pair_ids, dp, cg)
    summary = {
        "contract_id": PAIR_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "rewrite_model": resolved_model,
        "frozen_task_n": len(frozen_ids),
        "dp_valid_n": sum(bool(dp[task_id].get("metric_eligible")) for task_id in frozen_ids),
        "cg_valid_n": sum(bool(cg[task_id].get("metric_eligible")) for task_id in frozen_ids),
        "pair_n": len(pair_ids),
        "dp_target_improvement": _ti(pair_dp),
        "cg_target_improvement": _ti(pair_cg),
        "dp_directional_accuracy": _mean(pair_dp, "directional_accuracy"),
        "cg_directional_accuracy": _mean(pair_cg, "directional_accuracy"),
        "pair_task_ids": pair_ids,
    }

    feature_groups: dict[Any, list[str]] = {}
    interval_groups: dict[Any, list[str]] = {}
    for task_id in pair_ids:
        task = task_by_id[task_id]
        feature = (task.get("selected_features") or [task.get("feature_axis")])[0]
        feature_groups.setdefault(feature, []).append(task_id)
        interval_groups.setdefault(task.get("interval_type"), []).append(task_id)
    feature_rows = [_summary_row("feature", feature, ids, dp, cg) for feature, ids in feature_groups.items()]
    interval_rows = [_summary_row("interval_type", interval, ids, dp, cg) for interval, ids in interval_groups.items()]

    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "paired_summary.json", summary)
    write_csv(output / "paired_feature_summary.csv", feature_rows)
    write_csv(output / "paired_interval_summary.csv", interval_rows)
    manifest = {
        "contract_id": PAIR_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "rewrite_model": resolved_model,
        "dp_evaluation": {"path": str(dp_run), "manifest_sha256": sha256_file(dp_run / "evaluation_run_manifest.json")},
        "cg_evaluation": {"path": str(cg_run), "manifest_sha256": sha256_file(cg_run / "evaluation_run_manifest.json")},
        "taskset": {"path": str(taskset), "sha256": sha256_file(taskset)},
        "measurement_identity": dp_manifest.get("measurement_identity"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "paired_summary_manifest.json", manifest)
    return summary


def cross_model_summary(entries: list[tuple[str, Path, Path]], taskset: Path, output: Path, analysis_set_id: str, *, artifact_paths=None):
    if len(entries) < 2:
        raise RuntimeError("At least two model pairs are required for cross-model analysis")
    labels = [label for label, _, _ in entries]
    if len(labels) != len(set(labels)):
        raise RuntimeError("Model labels in --model-pair must be unique")

    tasks = read_json(taskset).get("tasks") or []
    frozen_ids = [task["task_id"] for task in tasks]
    loaded: dict[tuple[str, str], dict[str, dict]] = {}
    manifests: list[dict] = []
    sources: list[dict] = []

    for label, dp_path, cg_path in entries:
        dp_manifest = _eval_manifest(dp_path)
        cg_manifest = _eval_manifest(cg_path)
        manifests.extend([dp_manifest, cg_manifest])
        if dp_manifest.get("method") != "DP-v1" or cg_manifest.get("method") != "CG-v1":
            raise RuntimeError(f"{label}: expected DP-v1 and CG-v1 artifacts")
        if dp_manifest.get("rewrite_model") != cg_manifest.get("rewrite_model"):
            raise RuntimeError(f"{label}: DP/CG rewrite-model mismatch")
        loaded[(label, "DP-v1")] = {row["task_id"]: row for row in read_jsonl(dp_path / "evaluation_task_records.jsonl")}
        loaded[(label, "CG-v1")] = {row["task_id"]: row for row in read_jsonl(cg_path / "evaluation_task_records.jsonl")}
        sources.extend([
            {"model": label, "method": "DP-v1", "path": str(dp_path), "manifest_sha256": sha256_file(dp_path / "evaluation_run_manifest.json")},
            {"model": label, "method": "CG-v1", "path": str(cg_path), "manifest_sha256": sha256_file(cg_path / "evaluation_run_manifest.json")},
        ])
    _same_provenance(manifests, taskset, artifact_paths)

    expected = set(frozen_ids)
    for key, rows in loaded.items():
        if set(rows) != expected:
            raise RuntimeError(f"{key}: evaluation IDs do not exactly match frozen taskset")

    common_ids = [task_id for task_id in frozen_ids if all(rows[task_id].get("metric_eligible") for rows in loaded.values())]
    condition_rows = []
    for label, _, _ in entries:
        for method in ("DP-v1", "CG-v1"):
            rows = [loaded[(label, method)][task_id] for task_id in common_ids]
            condition_rows.append({
                "model": label,
                "method": method,
                "task_n": len(common_ids),
                "target_improvement": _ti(rows),
                "directional_accuracy": _mean(rows, "directional_accuracy"),
            })

    result = {
        "contract_id": CROSS_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "analysis_set_id": analysis_set_id,
        "model_count": len(entries),
        "models": labels,
        "global_common_task_n": len(common_ids),
        "global_common_task_ids": common_ids,
        "condition_summary": condition_rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "cross_model_summary.json", result)
    write_csv(output / "cross_model_condition_summary.csv", condition_rows)
    write_json(output / "global_common_task_ids.json", {"analysis_set_id": analysis_set_id, "task_ids": common_ids})
    write_json(output / "cross_model_summary_manifest.json", {
        "contract_id": CROSS_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "analysis_set_id": analysis_set_id,
        "model_count": len(entries),
        "models": labels,
        "taskset": {"path": str(taskset), "sha256": sha256_file(taskset)},
        "measurement_identity": manifests[0].get("measurement_identity") if manifests else None,
        "evaluation_artifacts": sources,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return result
