from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .io import read_json, sha256_file, write_csv, write_json, write_jsonl
from .metrics import evaluate_task, measurement_identity
from .provenance import ArtifactResolver, validate_reference, validate_runtime, validate_source, validate_curves

BLOCK_VERSION = "2.4.1"
EVALUATION_CONTRACT_VERSION = "2.4"
EVALUATION_PROTOCOL_ID = "evaluation-v2.4-paper22"


def evaluate_run(
    *,
    taskset_runtime: Path,
    feature_set_manifest: Path,
    reanalysis_run: Path,
    output: Path,
    method: str,
    model: str,
    overwrite: bool = False,
    artifact_paths=None,
):

    taskset = read_json(taskset_runtime)
    feature_manifest = read_json(feature_set_manifest)
    reanalysis_manifest_path = reanalysis_run / "reanalysis_manifest.json"
    reanalysis_manifest = read_json(reanalysis_manifest_path)
    if reanalysis_manifest.get("contract_id") != "storygen.reanalysis-run" or str(reanalysis_manifest.get("contract_version")) != "1.1":
        raise RuntimeError("storygen.reanalysis-run/1.1 is required")
    if method not in {"DP-v1", "CG-v1"}:
        raise RuntimeError("Evaluation V2.4 accepts only DP-v1 or CG-v1")

    expected_measurement = feature_manifest.get("measurement") or {}
    if not expected_measurement:
        raise RuntimeError("Feature-set manifest does not contain canonical measurement identity")

    tasks = taskset.get("tasks") or []
    if not tasks:
        raise RuntimeError("Frozen taskset is empty")

    validate_reference(feature_manifest)
    resolver = ArtifactResolver(artifact_paths)
    validate_runtime(taskset, feature_manifest, feature_set_manifest, resolver)
    rewrite_root = validate_source(
        reanalysis_manifest, taskset_runtime, feature_set_manifest, feature_manifest, method, model, resolver,
        historical=True,
    )
    validate_curves(tasks, reanalysis_run, rewrite_root, feature_set_manifest, feature_manifest, resolver)

    if output.exists():
        if not overwrite:
            raise FileExistsError(output)
        shutil.rmtree(output)
    output.mkdir(parents=True)

    records = []
    for task in tasks:
        record = evaluate_task(
            task,
            reanalysis_run / "tasks" / task["task_id"],
            expected_measurement,
            method,
            model,
        )
        records.append(record)
        write_json(output / "tasks" / task["task_id"] / "evaluation_task_record.json", record)

    eligible_n = sum(bool(row.get("metric_eligible")) for row in records)
    summary = {
        "evaluation_protocol_id": EVALUATION_PROTOCOL_ID,
        "evaluation_block_version": BLOCK_VERSION,
        "frozen_task_n": len(tasks),
        "metric_eligible_n": eligible_n,
        "metric_ineligible_n": len(tasks) - eligible_n,
        "coverage_rate": eligible_n / len(tasks),
    }
    write_jsonl(output / "evaluation_task_records.jsonl", records)
    write_csv(output / "evaluation_task_records.csv", records)
    write_json(output / "evaluation_run_summary.json", summary)

    manifest = {
        "contract_id": "storygen.evaluation-run",
        "contract_version": EVALUATION_CONTRACT_VERSION,
        "block_version": BLOCK_VERSION,
        "evaluation_protocol_id": EVALUATION_PROTOCOL_ID,
        "taskset": {
            "path": str(taskset_runtime),
            "sha256": sha256_file(taskset_runtime),
            "task_count": len(tasks),
        },
        "feature_set_manifest": {
            "path": str(feature_set_manifest),
            "sha256": sha256_file(feature_set_manifest),
        },
        "measurement_identity": measurement_identity(expected_measurement),
        "reanalysis_run": {
            "path": str(reanalysis_run),
            "manifest_sha256": sha256_file(reanalysis_manifest_path),
        },
        "method": method,
        "rewrite_model": model,
        "integrity_validation": {"revision": "P01A", "resolved_artifacts": resolver.evidence},
        "benchmark_metrics": ["Target Improvement", "Directional Accuracy"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "evaluation_run_manifest.json", manifest)
    return {"manifest": manifest, "summary": summary}
