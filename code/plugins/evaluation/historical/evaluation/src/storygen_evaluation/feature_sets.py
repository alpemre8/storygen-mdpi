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


def evaluate_feature_sets(
    *,
    taskset_runtime: Path,
    reference_feature_set_manifest: Path,
    candidate_feature_set: Path,
    output: Path,
    method: str,
    model: str,
    overwrite: bool = False,
    artifact_paths=None,
):
    """Evaluate an original FeatureSet against a rewritten FeatureSet.

    Metric calculation is delegated unchanged to ``metrics.evaluate_task``.
    This function only resolves the new artifact interface and provenance.
    """

    taskset = read_json(taskset_runtime)
    reference_manifest = read_json(reference_feature_set_manifest)
    candidate_manifest_path = candidate_feature_set / "feature_set_manifest.json"
    candidate_manifest = read_json(candidate_manifest_path)
    if candidate_manifest.get("contract_id") != "storygen.feature-set" or str(candidate_manifest.get("contract_version")) != "1.4":
        raise RuntimeError("candidate storygen.feature-set/1.4 is required")
    if (candidate_manifest.get("source") or {}).get("type") != "rewritten":
        raise RuntimeError("candidate FeatureSet must declare source.type=rewritten")
    if method not in {"DP-v1", "CG-v1"}:
        raise RuntimeError("Evaluation V2.4 accepts only DP-v1 or CG-v1")

    expected_measurement = reference_manifest.get("measurement") or {}
    if not expected_measurement:
        raise RuntimeError("Reference FeatureSet manifest does not contain canonical measurement identity")
    if candidate_manifest.get("measurement") != expected_measurement:
        raise RuntimeError("Candidate FeatureSet measurement identity differs from reference FeatureSet")

    tasks = taskset.get("tasks") or []
    if not tasks:
        raise RuntimeError("Frozen taskset is empty")

    validate_reference(reference_manifest)
    resolver = ArtifactResolver(artifact_paths)
    validate_runtime(taskset, reference_manifest, reference_feature_set_manifest, resolver)
    rewrite_root = validate_source(
        candidate_manifest, taskset_runtime, reference_feature_set_manifest, reference_manifest, method, model, resolver,
        historical=False,
    )
    validate_curves(tasks, candidate_feature_set, rewrite_root, reference_feature_set_manifest, reference_manifest, resolver)

    if output.exists():
        if not overwrite:
            raise FileExistsError(output)
        shutil.rmtree(output)
    output.mkdir(parents=True)

    records = []
    for task in tasks:
        record = evaluate_task(
            task,
            candidate_feature_set / "tasks" / task["task_id"],
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
        "reference_feature_set_manifest": {
            "path": str(reference_feature_set_manifest),
            "sha256": sha256_file(reference_feature_set_manifest),
        },
        "candidate_feature_set": {
            "path": str(candidate_feature_set),
            "manifest_sha256": sha256_file(candidate_manifest_path),
            "feature_set_id": candidate_manifest.get("feature_set_id"),
            "source": candidate_manifest.get("source"),
        },
        "measurement_identity": measurement_identity(expected_measurement),
        "method": method,
        "rewrite_model": model,
        "integrity_validation": {"revision": "P01A", "resolved_artifacts": resolver.evidence},
        "benchmark_metrics": ["Target Improvement", "Directional Accuracy"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "evaluation_run_manifest.json", manifest)
    return {"manifest": manifest, "summary": summary}
