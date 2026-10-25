from __future__ import annotations
from pathlib import Path
from typing import Any
import httpx
from .io import read_json, sha256_file
from .protocol import MeasurementProtocol

class ContractMismatchError(RuntimeError):
    pass

def _normal_hash(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value if value.startswith("sha256:") else "sha256:" + value

def validate_runtime_identity(protocol: MeasurementProtocol, *, model_file: str | Path, server_manifest: str | Path, require_slots: int | None = None, require_live_server: bool = False, allow_server_queuing: bool = False) -> dict[str, Any]:
    protocol.validate_legacy_parity()
    model_path = Path(model_file).resolve()
    server_path = Path(server_manifest).resolve()
    if not model_path.is_file():
        raise ContractMismatchError(f"Model file missing: {model_path}")
    if not server_path.is_file():
        raise ContractMismatchError(f"Server manifest missing: {server_path}")
    actual = sha256_file(model_path)
    expected = _normal_hash(protocol.model.get("model_sha256"))
    if expected and actual != expected:
        raise ContractMismatchError(f"Model SHA256 mismatch: expected={expected} actual={actual}")
    server = read_json(server_path)
    served_hash = _normal_hash(server.get("model_sha256"))
    if served_hash != actual:
        raise ContractMismatchError(f"Server/model SHA256 mismatch: server={served_hash} local={actual}")
    alias = str(protocol.model.get("alias") or "")
    if str(server.get("model_alias") or "") != alias:
        raise ContractMismatchError(f"Server alias mismatch: expected={alias} actual={server.get('model_alias')}")
    expected_commit = str(protocol.model.get("llama_cpp_commit") or "")
    if expected_commit and str(server.get("llama_cpp_commit") or "") != expected_commit:
        raise ContractMismatchError("llama.cpp commit mismatch")
    expected_quant = str(protocol.model.get("quantization") or "")
    if expected_quant and str(server.get("quantization") or "") != expected_quant:
        raise ContractMismatchError("Server quantization mismatch")
    req = dict(protocol.config.get("runtime_requirements") or {})
    required_slots = max(0 if allow_server_queuing else int(require_slots or 0), int(req.get("minimum_parallel_slots") or 0))
    if int(server.get("parallel_slots", 0)) < required_slots:
        raise ContractMismatchError(f"Server has {server.get('parallel_slots')} slots; {required_slots} required")
    if int(server.get("context_per_slot", 0)) < int(req.get("minimum_context_per_slot") or 0):
        raise ContractMismatchError("Insufficient context_per_slot")
    for key in ("kv_unified", "continuous_batching", "flash_attention"):
        if key in req and bool(server.get(key)) is not bool(req[key]):
            raise ContractMismatchError(f"Server {key} mismatch")
    if int(server.get("batch_size", 0)) < int(req.get("minimum_batch_size") or 0):
        raise ContractMismatchError("Insufficient batch_size")
    if int(server.get("ubatch_size", 0)) < int(req.get("minimum_ubatch_size") or 0):
        raise ContractMismatchError("Insufficient ubatch_size")
    live = None
    if require_live_server:
        base = str(protocol.model.get("base_url") or "").rstrip("/")
        try:
            r = httpx.get(base + "/models", timeout=10)
            r.raise_for_status()
            data = r.json()
            ids = [str(x.get("id")) for x in data.get("data", []) if isinstance(x, dict)]
            if alias not in ids:
                raise ContractMismatchError(f"Live server does not expose model alias {alias!r}; got {ids}")
            live = {"models": ids}
        except ContractMismatchError:
            raise
        except Exception as exc:
            raise ContractMismatchError(f"Live server preflight failed: {exc}") from exc
    return {
        "model_file": str(model_path),
        "model_sha256": actual,
        "server_manifest": str(server_path),
        "server_manifest_sha256": sha256_file(server_path),
        "server": server,
        "live_server": live,
        "client_concurrency": require_slots,
        "server_parallel_slots": int(server.get("parallel_slots", 0)),
        "server_side_queuing": bool(allow_server_queuing and int(require_slots or 0) > int(server.get("parallel_slots", 0))),
    }

def assert_measurement_equal(expected: dict[str, Any], actual: dict[str, Any], *, label: str = "measurement") -> None:
    fields = (
        "measurement_protocol_id", "measurement_protocol_version", "protocol_hash", "instrument_hash",
        "prompt_hash", "schema_hash", "system_instruction_hash", "request_contract_hash", "decoding_hash",
    )
    mismatches = [f"{k}: expected={expected.get(k)!r} actual={actual.get(k)!r}" for k in fields if expected.get(k) != actual.get(k)]
    em = _normal_hash((expected.get("model") or {}).get("model_sha256"))
    am = _normal_hash((actual.get("model") or {}).get("model_sha256"))
    if em != am:
        mismatches.append(f"model_sha256: expected={em!r} actual={am!r}")
    if (actual.get("failure_policy") or {}).get("heuristic_fallback") is not False:
        mismatches.append("heuristic_fallback must be false")
    if mismatches:
        raise ContractMismatchError(label + " mismatch: " + "; ".join(mismatches))
