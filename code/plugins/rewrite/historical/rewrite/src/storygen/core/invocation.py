"""Reproducible command-invocation metadata for artifact and run manifests."""

from __future__ import annotations

import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PARENT_INVOCATION_ENV = "STORYGEN_PARENT_INVOCATION_JSON"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def capture_invocation(
    *,
    resolved_parameters: Mapping[str, Any] | None = None,
    argv: Sequence[str] | None = None,
    cwd: str | Path | None = None,
    source: str = "direct_cli",
    parent_invocation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture the exact executable/argv plus fully resolved CLI parameters."""

    raw_argv = list(argv) if argv is not None else [sys.executable, *sys.argv]
    if argv is None and raw_argv and raw_argv[0] != sys.executable:
        raw_argv.insert(0, sys.executable)
    invocation = {
        "captured_at_utc": utc_now(),
        "source": source,
        "cwd": str(Path(cwd or os.getcwd()).resolve()),
        "executable": str(Path(raw_argv[0]).resolve()) if raw_argv else sys.executable,
        "argv": [str(item) for item in raw_argv],
        "command_line": shlex.join([str(item) for item in raw_argv]),
        "resolved_parameters": _json_safe(dict(resolved_parameters or {})),
    }
    if parent_invocation:
        invocation["parent_invocation"] = _json_safe(dict(parent_invocation))
    return invocation


def invocation_from_environment() -> dict[str, Any] | None:
    raw = os.environ.get(PARENT_INVOCATION_ENV)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "source": "invalid_parent_invocation_environment",
            "raw_value": raw,
        }
    return payload if isinstance(payload, dict) else None


def invocation_environment(invocation: Mapping[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env[PARENT_INVOCATION_ENV] = json.dumps(_json_safe(dict(invocation)), ensure_ascii=False)
    return env
