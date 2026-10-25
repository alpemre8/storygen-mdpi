"""Project-specific inference telemetry and replay data helpers."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_METRIC_LINE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|NaN|Inf|-Inf)$"
)

VLLM_METRIC_SUFFIXES = (
    "num_requests_running",
    "num_requests_waiting",
    "kv_cache_usage_perc",
    "prefix_cache_queries",
    "prefix_cache_hits",
    "prompt_tokens_total",
    "generation_tokens_total",
    "num_preemptions_total",
    "request_success_total",
)

LLAMACPP_METRIC_NAMES = {
    "llamacpp:prompt_tokens_total",
    "llamacpp:prompt_seconds_total",
    "llamacpp:prompt_tokens_seconds",
    "llamacpp:tokens_predicted_total",
    "llamacpp:tokens_predicted_seconds_total",
    "llamacpp:predicted_tokens_seconds",
    "llamacpp:requests_processing",
    "llamacpp:requests_deferred",
    "llamacpp:n_tokens_max",
    "llamacpp:n_decode_total",
    "llamacpp:n_busy_slots_per_decode",
}


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """One immutable rewrite request loaded from a historical run artifact."""

    request_path: Path
    task_id: str
    scene_id: str
    model: str
    system_instruction: str
    user_instruction: str
    format_schema: dict[str, Any] | None
    format_json: bool
    temperature: float
    max_tokens: int


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """One replay request result used for aggregate throughput analysis."""

    request_path: str
    task_id: str
    scene_id: str
    status: str
    request_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None
    output_chars: int | None
    schema_valid: bool
    scene_id_matches: bool
    error: str | None
    queue_wait_seconds: float = 0.0
    http_request_seconds: float = 0.0
    server_cache_tokens: int | None = None
    server_prompt_tokens: int | None = None
    server_prompt_seconds: float | None = None
    server_prompt_tokens_per_second: float | None = None
    server_predicted_tokens: int | None = None
    server_predicted_seconds: float | None = None
    server_predicted_tokens_per_second: float | None = None


def collect_rewrite_requests(root: str | Path) -> list[ReplayRequest]:
    """Load deterministic per-scene rewrite request artifacts below ``root``."""

    base = Path(root).expanduser().resolve()
    if not base.exists():
        raise FileNotFoundError(f"Rewrite request root does not exist: {base}")
    paths = sorted(base.rglob("rewrite_request.json"))
    requests: list[ReplayRequest] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        scene_id = str(payload.get("expected_scene_id") or path.parent.name).strip()
        task_id = _task_id_from_path(path)
        schema = payload.get("format_schema")
        requests.append(
            ReplayRequest(
                request_path=path,
                task_id=task_id,
                scene_id=scene_id,
                model=str(payload.get("model") or "").strip(),
                system_instruction=str(payload.get("system_instruction") or ""),
                user_instruction=str(payload.get("user_instruction") or ""),
                format_schema=dict(schema) if isinstance(schema, dict) else None,
                format_json=bool(payload.get("format_json", schema is None)),
                temperature=float(payload.get("temperature", 0.0)),
                max_tokens=int(payload.get("rewrite_max_tokens") or 4096),
            )
        )
    return requests


def parse_prometheus_metrics(text: str) -> dict[str, float]:
    """Parse capacity metrics exposed by vLLM or llama.cpp servers."""

    output: dict[str, float] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name not in LLAMACPP_METRIC_NAMES and not any(
            name.endswith(suffix) for suffix in VLLM_METRIC_SUFFIXES
        ):
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        output[name] = output.get(name, 0.0) + value
    return output


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Return a linearly interpolated percentile for a finite sequence."""

    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return None
    q = min(1.0, max(0.0, float(quantile)))
    if len(finite) == 1:
        return finite[0]
    position = q * (len(finite) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return finite[lower]
    fraction = position - lower
    return finite[lower] * (1.0 - fraction) + finite[upper] * fraction


def summarize_replay_results(
    results: Iterable[ReplayResult],
    *,
    wall_seconds: float,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an answer-first replay throughput and validity summary."""

    rows = list(results)
    succeeded = [row for row in rows if row.status == "ok"]
    durations = [row.request_seconds for row in succeeded]
    queue_waits = [row.queue_wait_seconds for row in succeeded]
    http_durations = [row.http_request_seconds for row in succeeded]
    total_prompt_tokens = sum(row.prompt_tokens or 0 for row in succeeded)
    total_completion_tokens = sum(row.completion_tokens or 0 for row in succeeded)
    positive_wall = max(float(wall_seconds), 1e-9)
    valid_count = sum(row.schema_valid and row.scene_id_matches for row in succeeded)
    native_prompt_rows = [
        row
        for row in succeeded
        if row.server_prompt_tokens is not None
        and row.server_prompt_seconds is not None
        and row.server_prompt_seconds > 0
    ]
    native_predicted_rows = [
        row
        for row in succeeded
        if row.server_predicted_tokens is not None
        and row.server_predicted_seconds is not None
        and row.server_predicted_seconds > 0
    ]
    return {
        "profile": dict(profile or {}),
        "request_count": len(rows),
        "success_count": len(succeeded),
        "failure_count": len(rows) - len(succeeded),
        "schema_and_scene_id_valid_count": valid_count,
        "schema_and_scene_id_valid_rate": valid_count / len(succeeded) if succeeded else 0.0,
        "wall_seconds": float(wall_seconds),
        "scenes_per_minute": len(succeeded) * 60.0 / positive_wall,
        "aggregate_prompt_tokens_per_second": total_prompt_tokens / positive_wall,
        "aggregate_completion_tokens_per_second": total_completion_tokens / positive_wall,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "latency_seconds": _duration_summary(durations),
        "client_queue_wait_seconds": _duration_summary(queue_waits),
        "http_request_seconds": _duration_summary(http_durations),
        "server_native_timings": {
            "available_count": max(len(native_prompt_rows), len(native_predicted_rows)),
            "prompt": _native_timing_summary(
                native_prompt_rows,
                token_attr="server_prompt_tokens",
                seconds_attr="server_prompt_seconds",
                rate_attr="server_prompt_tokens_per_second",
            ),
            "predicted": _native_timing_summary(
                native_predicted_rows,
                token_attr="server_predicted_tokens",
                seconds_attr="server_predicted_seconds",
                rate_attr="server_predicted_tokens_per_second",
            ),
        },
        "finish_reasons": _counts(row.finish_reason or "unknown" for row in succeeded),
        "errors": [
            {
                "task_id": row.task_id,
                "scene_id": row.scene_id,
                "request_path": row.request_path,
                "error": row.error,
            }
            for row in rows
            if row.status != "ok"
        ],
    }


def summarize_metric_snapshots(
    before: Mapping[str, float] | None,
    after: Mapping[str, float] | None,
) -> dict[str, Any]:
    """Summarize server metrics captured immediately before and after a replay."""

    start = dict(before or {})
    end = dict(after or {})
    counters: dict[str, float] = {}
    gauges: dict[str, float] = {}
    for name, value in sorted(end.items()):
        if name.endswith("_total"):
            counters[name] = value - start.get(name, 0.0)
        else:
            gauges[name] = value

    derived: dict[str, float] = {}
    prompt_tokens = counters.get("llamacpp:prompt_tokens_total")
    prompt_seconds = counters.get("llamacpp:prompt_seconds_total")
    if prompt_tokens is not None and prompt_seconds is not None and prompt_seconds > 0:
        derived["llamacpp:prompt_tokens_per_second_from_delta"] = prompt_tokens / prompt_seconds
    predicted_tokens = counters.get("llamacpp:tokens_predicted_total")
    predicted_seconds = counters.get("llamacpp:tokens_predicted_seconds_total")
    if predicted_tokens is not None and predicted_seconds is not None and predicted_seconds > 0:
        derived["llamacpp:predicted_tokens_per_second_from_delta"] = predicted_tokens / predicted_seconds

    return {
        "available": bool(start or end),
        "before": start,
        "after": end,
        "counter_deltas": counters,
        "final_gauges": gauges,
        "derived": derived,
    }


def _duration_summary(values: Sequence[float]) -> dict[str, float | None]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return {
        "mean": sum(finite) / len(finite) if finite else None,
        "p50": percentile(finite, 0.50),
        "p95": percentile(finite, 0.95),
        "max": max(finite) if finite else None,
        "sum": sum(finite) if finite else 0.0,
    }


def _native_timing_summary(
    rows: Sequence[ReplayResult],
    *,
    token_attr: str,
    seconds_attr: str,
    rate_attr: str,
) -> dict[str, Any]:
    tokens = [int(getattr(row, token_attr) or 0) for row in rows]
    seconds = [float(getattr(row, seconds_attr) or 0.0) for row in rows]
    reported_rates = [
        float(value)
        for row in rows
        if (value := getattr(row, rate_attr)) is not None and math.isfinite(float(value))
    ]
    total_tokens = sum(tokens)
    total_seconds = sum(seconds)
    return {
        "count": len(rows),
        "total_tokens": total_tokens,
        "summed_request_seconds": total_seconds,
        "weighted_tokens_per_second": total_tokens / total_seconds if total_seconds > 0 else None,
        "reported_tokens_per_second": _duration_summary(reported_rates),
    }


def _counts(values: Iterable[str]) -> dict[str, int]:
    output: dict[str, int] = {}
    for value in values:
        output[value] = output.get(value, 0) + 1
    return dict(sorted(output.items()))


def _task_id_from_path(path: Path) -> str:
    parts = path.parts
    try:
        task_index = parts.index("tasks") + 1
    except ValueError:
        return path.parents[2].name if len(path.parents) > 2 else "unknown"
    return parts[task_index] if task_index < len(parts) else "unknown"
