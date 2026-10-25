from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from storygen_measurement_core.client import OpenAICompatibleClient
from .io import load_script, write_json
from storygen_measurement_core import MeasurementProtocol, CanonicalFeatureScorer, validate_runtime_identity
from .scheduler import GlobalSceneScheduler, SceneJob


def icc_3_1(matrix):
    """Two-way mixed-effects, consistency, single-measure ICC(3,1)."""
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
        return None
    subject_count, repeat_count = values.shape
    subject_means = values.mean(axis=1)
    grand_mean = values.mean()
    ms_subject = (
        repeat_count
        * np.sum((subject_means - grand_mean) ** 2)
        / (subject_count - 1)
    )
    residual = (
        values
        - subject_means[:, None]
        - values.mean(axis=0)[None, :]
        + grand_mean
    )
    ms_error = np.sum(residual**2) / (
        (subject_count - 1) * (repeat_count - 1)
    )
    denominator = ms_subject + (repeat_count - 1) * ms_error
    return float((ms_subject - ms_error) / denominator) if denominator else 1.0


def run_reliability(
    *,
    project_root: Path,
    block_root: Path,
    protocol_path: Path,
    scene_manifest: Path,
    output: Path,
    repeats: int = 5,
    seed: int = 42,
    progress_mode: str = "always",
    concurrency: int | None = None,
    model_file: Path | None = None,
    server_manifest: Path | None = None,
    allow_noncanonical_sample: bool = False,
) -> dict[str, Any]:
    protocol = MeasurementProtocol.load(block_root, protocol_path)
    if model_file is None or server_manifest is None: raise ValueError("model_file and server_manifest are required")
    runtime_identity=validate_runtime_identity(protocol,model_file=model_file,server_manifest=server_manifest,require_slots=concurrency or 8)
    items = json.loads(scene_manifest.read_text(encoding="utf-8"))
    unique={(str(x.get("film_id")),str(x.get("scene_id"))) for x in items}
    films={str(x.get("film_id")) for x in items}
    if not allow_noncanonical_sample:
        counts={}
        for item in items: counts[str(item.get("film_id"))]=counts.get(str(item.get("film_id")),0)+1
        if len(items)!=100 or len(unique)!=100 or len(films)!=10 or repeats!=5 or set(counts.values())!={10}:
            raise ValueError("Canonical reliability requires 100 unique scenes, exactly 10 scenes per film across 10 films, and 5 repeats")
    runtime_concurrency = max(
        1,
        int(concurrency if concurrency is not None else protocol.decoding.get("concurrency", 8)),
    )

    jobs: list[SceneJob] = []
    shuffled_items = list(items)
    random.Random(seed).shuffle(shuffled_items)
    for scene_order, item in enumerate(shuffled_items):
        _, scenes = load_script(project_root / item["script_path"])
        by_id = {scene["scene_id"]: scene for scene in scenes}
        scene = by_id[item["scene_id"]]
        group_id = f"{item['film_id']}:{scene['scene_id']}"
        repeat_order = list(range(repeats))
        random.Random(f"{seed}:{group_id}").shuffle(repeat_order)
        for repeat in repeat_order:
            jobs.append(
                SceneJob(
                    job_id=f"{scene_order:05d}:{repeat:03d}:{group_id}",
                    group_id=group_id,
                    film_id=item["film_id"],
                    scene_id=scene["scene_id"],
                    scene_title=scene["title"],
                    scene_text=scene["text"],
                    payload={"repeat": repeat},
                )
            )

    decoding = protocol.decoding
    with OpenAICompatibleClient(
        protocol.model["base_url"],
        float(decoding.get("timeout_seconds", 600)),
        runtime_concurrency,
    ) as client:
        scorer = CanonicalFeatureScorer(protocol, client=client, use_cache=False)
        scheduler = GlobalSceneScheduler(
            scorer=scorer,
            concurrency=runtime_concurrency,
            label="measurement-reliability",
            progress_mode=progress_mode,
            telemetry_path=output.parent / f"{output.stem}_requests.jsonl",
        )
        scheduled_results, scheduler_summary = scheduler.run(jobs)

    rows = []
    for item in scheduled_results:
        result = item.measurement
        rows.append(
            {
                "film_id": item.job.film_id,
                "scene_id": item.job.scene_id,
                "repeat": int(item.job.payload["repeat"]),
                "status": result.status,
                "features": result.features,
                "error": result.error,
                "queue_wait_seconds": round(item.queue_wait_seconds, 6),
                "elapsed_seconds": round(item.elapsed_seconds, 6),
            }
        )

    valid = [row for row in rows if row["status"] == "measured"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in valid:
        groups.setdefault((row["film_id"], row["scene_id"]), []).append(row)
    for values in groups.values():
        values.sort(key=lambda row: row["repeat"])

    per_feature: dict[str, Any] = {}
    for feature in protocol.features:
        deviations: list[float] = []
        exact = 0
        total = 0
        first: list[float] = []
        second: list[float] = []
        complete: list[list[float]] = []

        for values in groups.values():
            scores = [row["features"][feature] for row in values]
            mean_score = float(np.mean(scores))
            deviations.extend(abs(score - mean_score) for score in scores)
            exact += int(len(set(scores)) == 1)
            total += 1
            if len(scores) >= 2:
                first.append(scores[0])
                second.append(scores[1])
            if len(scores) == repeats:
                complete.append(scores)

        rho = None
        if len(first) >= 2:
            statistic = spearmanr(first, second).statistic
            rho = float(statistic) if np.isfinite(statistic) else None
        per_feature[feature] = {
            "exact_scene_agreement_rate": exact / max(total, 1),
            "mean_absolute_repeated_score_deviation": (
                float(np.mean(deviations)) if deviations else None
            ),
            "maximum_observed_deviation": (
                float(max(deviations)) if deviations else None
            ),
            "repeat1_repeat2_spearman": rho,
            "icc_3_1_consistency_single": icc_3_1(complete),
        }

    result = {
        "block_version": "1.4.1",
        "measurement": protocol.manifest(),
        "runtime_identity": runtime_identity,
        "scene_count": len(items),
        "repeats": repeats,
        "request_count": len(rows),
        "valid_count": len(valid),
        "schema_failure_rate": 1 - len(valid) / max(len(rows), 1),
        "scheduler": scheduler_summary,
        "per_feature": per_feature,
        "rows": rows,
    }
    write_json(output, result)
    return result
