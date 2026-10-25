from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .io import append_jsonl
from .progress import ProgressReporter
from storygen_measurement_core import CanonicalFeatureScorer, MeasurementResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SceneJob:
    job_id: str
    group_id: str
    film_id: str
    scene_id: str
    scene_title: str
    scene_text: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneJobResult:
    job: SceneJob
    measurement: MeasurementResult
    submitted_at: str
    started_at: str
    finished_at: str
    queue_wait_seconds: float
    elapsed_seconds: float


def round_robin_jobs(jobs: Iterable[SceneJob]) -> list[SceneJob]:
    """Interleave scenes across films/tasks instead of draining one group first."""
    groups: OrderedDict[str, deque[SceneJob]] = OrderedDict()
    for job in jobs:
        groups.setdefault(job.group_id, deque()).append(job)
    ordered: list[SceneJob] = []
    while groups:
        empty: list[str] = []
        for group_id, queue in groups.items():
            if queue:
                ordered.append(queue.popleft())
            if not queue:
                empty.append(group_id)
        for group_id in empty:
            groups.pop(group_id, None)
    return ordered


class GlobalSceneScheduler:
    """One global scene queue shared by every film or rewrite task.

    The executor has exactly ``concurrency`` workers. Jobs are submitted in
    round-robin group order, so a long film/task cannot monopolize all slots.
    """

    def __init__(
        self,
        *,
        scorer: CanonicalFeatureScorer,
        concurrency: int,
        label: str,
        progress_mode: str = "auto",
        telemetry_path: str | Path | None = None,
    ) -> None:
        self.scorer = scorer
        self.concurrency = max(1, int(concurrency))
        self.label = label
        self.progress_mode = progress_mode
        self.telemetry_path = Path(telemetry_path) if telemetry_path else None
        self._active = 0
        self._peak_active = 0
        self._active_lock = threading.Lock()

    def run(self, jobs: Iterable[SceneJob]) -> tuple[list[SceneJobResult], dict[str, Any]]:
        ordered = round_robin_jobs(jobs)
        reporter = ProgressReporter(
            label=self.label,
            total=len(ordered),
            mode=self.progress_mode,
        )
        if self.telemetry_path:
            self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            self.telemetry_path.unlink(missing_ok=True)

        submitted_monotonic: dict[str, float] = {}
        submitted_wall: dict[str, str] = {}
        results: list[SceneJobResult] = []
        failures = 0
        cached = 0

        def worker(job: SceneJob) -> SceneJobResult:
            start_mono = time.monotonic()
            start_wall = _utc_now()
            queue_wait = max(0.0, start_mono - submitted_monotonic[job.job_id])
            with self._active_lock:
                self._active += 1
                self._peak_active = max(self._peak_active, self._active)
            reporter.request_started(f"{job.group_id}/{job.scene_id}")
            successful = False
            try:
                try:
                    measurement = self.scorer.score_scene(
                        film_id=job.film_id,
                        scene_id=job.scene_id,
                        scene_title=job.scene_title,
                        scene_text=job.scene_text,
                    )
                except Exception as exc:
                    key = self.scorer._key(
                        job.film_id, job.scene_id, job.scene_title, job.scene_text
                    )
                    measurement = MeasurementResult(
                        status="measurement_ineligible",
                        features=None,
                        attempts=0,
                        response_text=None,
                        cache_key=key,
                        error=f"Unhandled scheduler worker error: {exc}",
                        provenance={
                            **self.scorer.protocol.manifest(),
                            "film_id": job.film_id,
                            "scene_id": job.scene_id,
                            "scene_title": job.scene_title,
                        },
                        cache_hit=False,
                    )
                successful = measurement.status == "measured"
            finally:
                with self._active_lock:
                    self._active = max(0, self._active - 1)
                reporter.request_finished(f"{job.group_id}/{job.scene_id}", successful=successful)
            finish_mono = time.monotonic()
            finish_wall = _utc_now()
            return SceneJobResult(
                job=job,
                measurement=measurement,
                submitted_at=submitted_wall[job.job_id],
                started_at=start_wall,
                finished_at=finish_wall,
                queue_wait_seconds=queue_wait,
                elapsed_seconds=max(0.0, finish_mono - start_mono),
            )

        started = time.monotonic()
        try:
            with ThreadPoolExecutor(
                max_workers=self.concurrency,
                thread_name_prefix="feature-scene",
            ) as executor:
                futures: dict[Future[SceneJobResult], SceneJob] = {}
                for job in ordered:
                    submitted_monotonic[job.job_id] = time.monotonic()
                    submitted_wall[job.job_id] = _utc_now()
                    futures[executor.submit(worker, job)] = job

                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    if result.measurement.status != "measured":
                        failures += 1
                    if result.measurement.cache_hit:
                        cached += 1
                    if self.telemetry_path:
                        append_jsonl(
                            self.telemetry_path,
                            {
                                "job_id": result.job.job_id,
                                "group_id": result.job.group_id,
                                "film_id": result.job.film_id,
                                "scene_id": result.job.scene_id,
                                "submitted_at": result.submitted_at,
                                "started_at": result.started_at,
                                "finished_at": result.finished_at,
                                "queue_wait_seconds": round(result.queue_wait_seconds, 6),
                                "elapsed_seconds": round(result.elapsed_seconds, 6),
                                "status": result.measurement.status,
                                "attempts": result.measurement.attempts,
                                "cache_hit": result.measurement.cache_hit,
                                "error": result.measurement.error,
                            },
                        )
        finally:
            reporter.finish()
            self.scorer.flush_cache()

        elapsed = max(0.0, time.monotonic() - started)
        results.sort(key=lambda item: item.job.job_id)
        summary = {
            "scheduler": "global-scene-round-robin-v1",
            "job_count": len(ordered),
            "concurrency": self.concurrency,
            "peak_active_requests": self._peak_active,
            "measurement_failures": failures,
            "cache_hits": cached,
            "elapsed_seconds": round(elapsed, 6),
            "throughput_scenes_per_second": round(len(ordered) / elapsed, 6) if elapsed else None,
            "telemetry_path": str(self.telemetry_path) if self.telemetry_path else None,
        }
        return results, summary
