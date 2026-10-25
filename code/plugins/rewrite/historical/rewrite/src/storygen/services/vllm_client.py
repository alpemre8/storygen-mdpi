"""OpenAI-compatible HTTP client for local model services.

The historical class name is retained for compatibility, but the transport is
backend-neutral and is exercised against both vLLM and llama.cpp servers. The
client deliberately uses non-streaming responses so Python token-event overhead
does not compete with batched local inference.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import TracebackType
from typing import Any

import httpx

DEFAULT_VLLM_BASE_URL = "http://127.0.0.1:8000/v1"
_TELEMETRY_LOCKS: dict[str, threading.Lock] = {}
_TELEMETRY_LOCKS_GUARD = threading.Lock()


class VLLMClientError(RuntimeError):
    """Raised when the local OpenAI-compatible inference service cannot satisfy a request."""


@dataclass(frozen=True, slots=True)
class VLLMGenerationResult:
    """One non-streaming generation response with request-level measurements."""

    text: str
    request_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    response_id: str | None
    served_model: str | None
    queue_wait_seconds: float = 0.0
    http_request_seconds: float = 0.0
    server_cache_tokens: int | None = None
    server_prompt_tokens: int | None = None
    server_prompt_seconds: float | None = None
    server_prompt_tokens_per_second: float | None = None
    server_predicted_tokens: int | None = None
    server_predicted_seconds: float | None = None
    server_predicted_tokens_per_second: float | None = None

    @property
    def completion_tokens_per_second(self) -> float | None:
        """Client end-to-end completion throughput, including queue wait."""

        if self.completion_tokens is None or self.request_seconds <= 0:
            return None
        return self.completion_tokens / self.request_seconds

    @property
    def completion_tokens_per_second_http(self) -> float | None:
        """Completion throughput measured over the HTTP/server interval only."""

        if self.completion_tokens is None or self.http_request_seconds <= 0:
            return None
        return self.completion_tokens / self.http_request_seconds


@dataclass(slots=True)
class VLLMClient:
    """Minimal persistent client for a local OpenAI-compatible inference server.

    ``base_url`` may be supplied either as ``http://host:port`` or with the
    OpenAI prefix ``http://host:port/v1``. No cloud service is contacted.
    """

    base_url: str = DEFAULT_VLLM_BASE_URL
    timeout_seconds: float = 180.0
    api_key: str | None = None
    transport: httpx.BaseTransport | None = None
    max_in_flight: int | None = None
    max_connections: int | None = None
    max_keepalive_connections: int | None = None
    keepalive_expiry_seconds: float = 60.0
    telemetry_jsonl: str | Path | None = None
    _http_client: httpx.Client = field(init=False, repr=False)
    _request_gate: threading.BoundedSemaphore = field(init=False, repr=False)
    _closed: bool = field(init=False, default=False, repr=False)
    _telemetry_path: Path | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.base_url = _normalize_base_url(self.base_url)
        if self.api_key is None:
            self.api_key = os.getenv("VLLM_API_KEY") or None
        resolved_in_flight = (
            _positive_int(self.max_in_flight)
            or _positive_int(os.getenv("STORYGEN_VLLM_MAX_IN_FLIGHT"))
            or 32
        )
        resolved_connections = (
            _positive_int(self.max_connections)
            or _positive_int(os.getenv("STORYGEN_VLLM_HTTP_MAX_CONNECTIONS"))
            or max(16, resolved_in_flight * 2)
        )
        resolved_keepalive = (
            _positive_int(self.max_keepalive_connections)
            or _positive_int(os.getenv("STORYGEN_VLLM_HTTP_MAX_KEEPALIVE"))
            or max(8, min(resolved_connections, resolved_in_flight * 2))
        )
        telemetry_value = self.telemetry_jsonl or os.getenv("STORYGEN_VLLM_TELEMETRY_JSONL")
        if telemetry_value:
            self._telemetry_path = Path(str(telemetry_value)).expanduser()
            self._telemetry_path.parent.mkdir(parents=True, exist_ok=True)

        self.max_in_flight = resolved_in_flight
        self.max_connections = resolved_connections
        self.max_keepalive_connections = resolved_keepalive
        self._request_gate = threading.BoundedSemaphore(resolved_in_flight)
        self._http_client = httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
            headers=self._headers(),
            limits=httpx.Limits(
                max_connections=resolved_connections,
                max_keepalive_connections=resolved_keepalive,
                keepalive_expiry=max(1.0, float(self.keepalive_expiry_seconds)),
            ),
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def server_root_url(self, path: str = "") -> str:
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        return f"{root.rstrip('/')}/{path.lstrip('/')}" if path else root.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def close(self) -> None:
        """Close the persistent HTTP connection pool owned by this client."""

        if self._closed:
            return
        self._closed = True
        self._http_client.close()

    def __enter__(self) -> VLLMClient:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise VLLMClientError("local inference client connection pool is already closed.")

    @contextmanager
    def _request_slot(self):
        """Bound in-flight requests and report process-side queue wait time."""

        self._ensure_open()
        queue_started = perf_counter()
        self._request_gate.acquire()
        queue_wait_seconds = perf_counter() - queue_started
        try:
            yield max(0.0, queue_wait_seconds)
        finally:
            self._request_gate.release()

    def list_models(self) -> list[str]:
        """Return model aliases currently served by the local inference server."""

        try:
            with self._request_slot():
                response = self._http_client.get(self._url("models"))
                _raise_for_status(response, operation="list models")
                payload = response.json()
        except VLLMClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VLLMClientError(
                f"Could not reach the local inference server at {self.base_url}. Start the vLLM or llama.cpp server "
                "in its separate virtual environment before running the project."
            ) from exc

        names: list[str] = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                names.append(item["id"])
        return names

    def is_available(self) -> bool:
        try:
            self.list_models()
        except VLLMClientError:
            return False
        return True

    def ensure_model_available(self, model: str) -> None:
        names = self.list_models()
        if model not in names:
            raise VLLMClientError(
                f"The inference server is reachable at {self.base_url}, but model alias `{model}` is not served. "
                f"Available aliases: {', '.join(names) if names else '(none)'}."
            )

    def metrics_text(self) -> str:
        """Return the current Prometheus metrics payload from ``/metrics``."""

        try:
            with self._request_slot():
                response = self._http_client.get(self.server_root_url("metrics"))
                _raise_for_status(response, operation="read metrics")
                return response.text
        except VLLMClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VLLMClientError(f"Could not read inference-server metrics: {exc}") from exc

    def embed(self, text: str, model: str) -> list[float]:
        return self.embed_many([text], model=model)[0]

    def embed_many(self, texts: list[str], model: str) -> list[list[float]]:
        inputs = [str(text or " ") for text in texts]
        if not inputs:
            return []
        payload = {"model": model, "input": inputs}
        try:
            with self._request_slot():
                response = self._http_client.post(self._url("embeddings"), json=payload)
                _raise_for_status(response, operation=f"embedding with `{model}`")
                data = response.json()
        except VLLMClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VLLMClientError(f"vLLM embedding failed for model `{model}`: {exc}") from exc

        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != len(inputs):
            raise VLLMClientError(
                f"vLLM embedding response count mismatch: expected {len(inputs)}, got "
                f"{len(rows) if isinstance(rows, list) else 'invalid'}"
            )
        ordered = sorted(rows, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
        vectors: list[list[float]] = []
        for row in ordered:
            vector = row.get("embedding") if isinstance(row, dict) else None
            if not isinstance(vector, list) or not all(isinstance(value, int | float) for value in vector):
                raise VLLMClientError("vLLM embedding response did not contain numeric vectors.")
            vectors.append([float(value) for value in vector])
        return vectors

    def generate(
        self,
        prompt: str,
        model: str,
        *,
        system: str | None = None,
        format_json: bool = False,
        format_schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        request_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate one non-streaming completion and return assistant text."""

        return self.generate_detailed(
            prompt,
            model,
            system=system,
            format_json=format_json,
            format_schema=format_schema,
            options=options,
            request_metadata=request_metadata,
        ).text

    def generate_detailed(
        self,
        prompt: str,
        model: str,
        *,
        system: str | None = None,
        format_json: bool = False,
        format_schema: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        request_metadata: dict[str, Any] | None = None,
    ) -> VLLMGenerationResult:
        """Generate one completion and retain OpenAI usage/finish metadata."""

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise VLLMClientError("Local generation prompt is empty.")

        request_options = dict(options or {})
        payload: dict[str, Any] = {
            "model": model,
            "messages": _messages(
                system=system,
                prompt=clean_prompt,
                model=model,
                structured=bool(format_schema or format_json),
            ),
            "stream": False,
        }
        payload.update(_translate_options(request_options))

        if format_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "storygen_response",
                    "strict": True,
                    "schema": format_schema,
                },
            }
        elif format_json:
            payload["response_format"] = {"type": "json_object"}

        if _is_qwen3_family(model) and (format_schema is not None or format_json):
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        started = perf_counter()
        queue_wait_seconds = 0.0
        http_request_seconds = 0.0
        try:
            with self._request_slot() as queue_wait_seconds:
                http_started = perf_counter()
                try:
                    response = self._http_client.post(self._url("chat/completions"), json=payload)
                    http_request_seconds = perf_counter() - http_started
                except Exception:
                    http_request_seconds = perf_counter() - http_started
                    raise
                _raise_for_status(response, operation=f"generation with `{model}`")
                data = response.json()
            elapsed = perf_counter() - started
            result = _generation_result(
                data,
                elapsed=elapsed,
                queue_wait_seconds=queue_wait_seconds,
                http_request_seconds=http_request_seconds,
            )
            if not result.text.strip():
                raise VLLMClientError(f"The local inference server returned empty assistant content for model `{model}`.")
            self._write_telemetry(
                status="ok",
                model=model,
                prompt=clean_prompt,
                system=system,
                format_mode="json_schema" if format_schema is not None else "json_object" if format_json else "text",
                options=request_options,
                result=result,
                request_metadata=request_metadata,
                error=None,
            )
            return result
        except VLLMClientError as exc:
            elapsed = perf_counter() - started
            self._write_telemetry(
                status="error",
                model=model,
                prompt=clean_prompt,
                system=system,
                format_mode="json_schema" if format_schema is not None else "json_object" if format_json else "text",
                options=request_options,
                result=None,
                request_metadata=request_metadata,
                error=str(exc),
                request_seconds=elapsed,
                queue_wait_seconds=queue_wait_seconds,
                http_request_seconds=http_request_seconds,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            elapsed = perf_counter() - started
            wrapped = VLLMClientError(f"Local inference generation failed for model `{model}`: {exc}")
            self._write_telemetry(
                status="error",
                model=model,
                prompt=clean_prompt,
                system=system,
                format_mode="json_schema" if format_schema is not None else "json_object" if format_json else "text",
                options=request_options,
                result=None,
                request_metadata=request_metadata,
                error=str(wrapped),
                request_seconds=elapsed,
                queue_wait_seconds=queue_wait_seconds,
                http_request_seconds=http_request_seconds,
            )
            raise wrapped from exc

    def _write_telemetry(
        self,
        *,
        status: str,
        model: str,
        prompt: str,
        system: str | None,
        format_mode: str,
        options: dict[str, Any],
        result: VLLMGenerationResult | None,
        request_metadata: dict[str, Any] | None,
        error: str | None,
        request_seconds: float | None = None,
        queue_wait_seconds: float | None = None,
        http_request_seconds: float | None = None,
    ) -> None:
        path = self._telemetry_path
        if path is None:
            return
        elapsed = result.request_seconds if result is not None else float(request_seconds or 0.0)
        record = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "base_url": self.base_url,
            "model": model,
            "format_mode": format_mode,
            "temperature": options.get("temperature"),
            "max_tokens": options.get("max_tokens"),
            "prompt_chars": len(prompt),
            "system_chars": len(str(system or "")),
            "output_chars": len(result.text) if result is not None else None,
            "request_seconds": elapsed,
            "queue_wait_seconds": (
                result.queue_wait_seconds if result is not None else float(queue_wait_seconds or 0.0)
            ),
            "http_request_seconds": (
                result.http_request_seconds if result is not None else float(http_request_seconds or 0.0)
            ),
            "prompt_tokens": result.prompt_tokens if result is not None else None,
            "completion_tokens": result.completion_tokens if result is not None else None,
            "total_tokens": result.total_tokens if result is not None else None,
            "completion_tokens_per_second_e2e": (
                result.completion_tokens_per_second if result is not None else None
            ),
            "completion_tokens_per_second_http": (
                result.completion_tokens_per_second_http if result is not None else None
            ),
            "server_cache_tokens": result.server_cache_tokens if result is not None else None,
            "server_prompt_tokens": result.server_prompt_tokens if result is not None else None,
            "server_prompt_seconds": result.server_prompt_seconds if result is not None else None,
            "server_prompt_tokens_per_second": (
                result.server_prompt_tokens_per_second if result is not None else None
            ),
            "server_predicted_tokens": result.server_predicted_tokens if result is not None else None,
            "server_predicted_seconds": result.server_predicted_seconds if result is not None else None,
            "server_predicted_tokens_per_second": (
                result.server_predicted_tokens_per_second if result is not None else None
            ),
            "finish_reason": result.finish_reason if result is not None else None,
            "response_id": result.response_id if result is not None else None,
            "served_model": result.served_model if result is not None else None,
            "request_metadata": dict(request_metadata or {}),
            "error": error,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        lock = _telemetry_lock(path)
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)


def _telemetry_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _TELEMETRY_LOCKS_GUARD:
        lock = _TELEMETRY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _TELEMETRY_LOCKS[key] = lock
        return lock


def _normalize_base_url(value: str) -> str:
    base = str(value or DEFAULT_VLLM_BASE_URL).strip().rstrip("/")
    if not base:
        base = DEFAULT_VLLM_BASE_URL
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _messages(*, system: str | None, prompt: str, model: str, structured: bool) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    system_text = str(system or "").strip()
    if _is_qwen3_family(model) and structured:
        system_text = f"/no_think\n{system_text}".strip()
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": prompt})
    return messages


def _translate_options(options: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    direct_keys = {
        "temperature",
        "top_p",
        "top_k",
        "min_p",
        "seed",
        "stop",
        "presence_penalty",
        "frequency_penalty",
        "repetition_penalty",
        "ignore_eos",
    }
    for key in direct_keys:
        if key in options and options[key] is not None:
            translated[key] = options[key]

    if options.get("max_tokens") is not None:
        translated["max_tokens"] = int(options["max_tokens"])

    if options.get("repeat_penalty") is not None and "repetition_penalty" not in translated:
        translated["repetition_penalty"] = float(options["repeat_penalty"])
    return translated


def _generation_result(
    payload: Any,
    *,
    elapsed: float,
    queue_wait_seconds: float = 0.0,
    http_request_seconds: float = 0.0,
) -> VLLMGenerationResult:
    content = _completion_content(payload)
    usage = payload.get("usage") if isinstance(payload, dict) else None
    timings = payload.get("timings") if isinstance(payload, dict) else None
    choice = None
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]

    server_prompt_tokens = _optional_int(timings.get("prompt_n")) if isinstance(timings, dict) else None
    server_prompt_seconds = _milliseconds_to_seconds(timings.get("prompt_ms")) if isinstance(timings, dict) else None
    server_predicted_tokens = _optional_int(timings.get("predicted_n")) if isinstance(timings, dict) else None
    server_predicted_seconds = (
        _milliseconds_to_seconds(timings.get("predicted_ms")) if isinstance(timings, dict) else None
    )
    return VLLMGenerationResult(
        text=content,
        request_seconds=max(0.0, float(elapsed)),
        prompt_tokens=_optional_int(usage.get("prompt_tokens")) if isinstance(usage, dict) else None,
        completion_tokens=_optional_int(usage.get("completion_tokens")) if isinstance(usage, dict) else None,
        total_tokens=_optional_int(usage.get("total_tokens")) if isinstance(usage, dict) else None,
        finish_reason=str(choice.get("finish_reason")) if isinstance(choice, dict) and choice.get("finish_reason") is not None else None,
        response_id=str(payload.get("id")) if isinstance(payload, dict) and payload.get("id") is not None else None,
        served_model=str(payload.get("model")) if isinstance(payload, dict) and payload.get("model") is not None else None,
        queue_wait_seconds=max(0.0, float(queue_wait_seconds)),
        http_request_seconds=max(0.0, float(http_request_seconds)),
        server_cache_tokens=_optional_int(timings.get("cache_n")) if isinstance(timings, dict) else None,
        server_prompt_tokens=server_prompt_tokens,
        server_prompt_seconds=server_prompt_seconds,
        server_prompt_tokens_per_second=_timing_rate(
            timings.get("prompt_per_second") if isinstance(timings, dict) else None,
            tokens=server_prompt_tokens,
            seconds=server_prompt_seconds,
        ),
        server_predicted_tokens=server_predicted_tokens,
        server_predicted_seconds=server_predicted_seconds,
        server_predicted_tokens_per_second=_timing_rate(
            timings.get("predicted_per_second") if isinstance(timings, dict) else None,
            tokens=server_predicted_tokens,
            seconds=server_predicted_seconds,
        ),
    )


def _completion_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise VLLMClientError("Inference response root was not a JSON object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise VLLMClientError(f"Inference response did not contain choices: {_compact_payload(payload)}")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise VLLMClientError(f"Inference response did not contain an assistant message: {_compact_payload(payload)}")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
    if response.is_success:
        return
    detail = response.text.strip()
    if len(detail) > 2000:
        detail = detail[:2000] + "..."
    raise VLLMClientError(
        f"Inference server {operation} failed with HTTP {response.status_code}: {detail or response.reason_phrase}"
    )


def _compact_payload(payload: Any) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = repr(payload)
    return text[:1000]


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0.0 else None


def _milliseconds_to_seconds(value: Any) -> float | None:
    milliseconds = _optional_float(value)
    return milliseconds / 1000.0 if milliseconds is not None else None


def _timing_rate(value: Any, *, tokens: int | None, seconds: float | None) -> float | None:
    reported = _optional_float(value)
    if reported is not None:
        return reported
    if tokens is None or seconds is None or seconds <= 0:
        return None
    return tokens / seconds


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_qwen3_family(model: str) -> bool:
    name = str(model or "").lower().replace("_", "").replace("-", "")
    return "qwen3" in name
