from __future__ import annotations
from typing import Any
import httpx

class LocalModelError(RuntimeError):
    pass

def build_request_payload(*, prompt: str, model: str, schema: dict[str, Any], decoding: dict[str, Any], system_instruction: str, response_schema_name: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": response_schema_name, "strict": True, "schema": schema},
        },
    }
    for key in ("temperature", "max_tokens", "top_p", "top_k", "min_p", "seed", "stop"):
        if decoding.get(key) is not None:
            payload[key] = decoding[key]
    if decoding.get("repeat_penalty") is not None:
        payload["repetition_penalty"] = decoding["repeat_penalty"]
    return payload

class OpenAICompatibleClient:
    def __init__(self, base_url: str, timeout_seconds: float = 600, max_connections: int = 32):
        base = base_url.rstrip("/")
        self.base_url = base if base.endswith("/v1") else base + "/v1"
        self.client = httpx.Client(timeout=timeout_seconds, limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections))

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def generate(self, *, prompt: str, model: str, schema: dict[str, Any], decoding: dict[str, Any], system_instruction: str, response_schema_name: str) -> str:
        payload = build_request_payload(prompt=prompt, model=model, schema=schema, decoding=decoding, system_instruction=system_instruction, response_schema_name=response_schema_name)
        try:
            response = self.client.post(self.base_url + "/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise LocalModelError("Empty assistant content")
            return text.strip()
        except Exception as exc:
            if isinstance(exc, LocalModelError):
                raise
            raise LocalModelError(f"Local measurement request failed: {exc}") from exc
