from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from .io import read_json, sha256_file, sha256_json, sha256_bytes

@dataclass(frozen=True)
class MeasurementProtocol:
    block_root: Path
    config_path: Path
    config: dict[str, Any]
    prompt_path: Path
    schema_path: Path
    prompt_text: str
    schema: dict[str, Any]
    prompt_hash: str
    schema_hash: str
    system_instruction: str
    system_hash: str
    response_schema_name: str
    request_contract: dict[str, Any]
    request_contract_hash: str
    decoding_hash: str
    instrument_hash: str
    protocol_hash: str

    @classmethod
    def load(cls, block_root: str | Path, config_path: str | Path) -> "MeasurementProtocol":
        root = Path(block_root).resolve()
        cp = Path(config_path)
        if not cp.is_absolute():
            cp = (root / cp).resolve()
        cfg = yaml.safe_load(cp.read_text(encoding="utf-8")) or {}
        inst = cfg["instrument"]
        pp = (root / inst["prompt_path"]).resolve()
        sp = (root / inst["schema_path"]).resolve()
        prompt = pp.read_text(encoding="utf-8")
        schema = read_json(sp)
        system = str(inst.get("system_instruction") or "").strip()
        if not system:
            raise ValueError("instrument.system_instruction is required")
        response_schema_name = str(inst.get("response_schema_name") or "").strip()
        if not response_schema_name:
            raise ValueError("instrument.response_schema_name is required")
        decoding = dict(cfg.get("decoding") or {})
        ph = sha256_file(pp)
        sh = sha256_file(sp)
        sysh = sha256_bytes(system.encode("utf-8"))
        dh = sha256_json(decoding)
        request_contract = {
            "request_contract_id": inst.get("request_contract_id"),
            "endpoint": inst.get("endpoint"),
            "message_order": list(inst.get("message_order") or []),
            "system_instruction_hash": sysh,
            "response_schema_name": response_schema_name,
            "structured_output": inst.get("structured_output"),
            "stream": False,
            "explicit_decoding_fields": sorted(k for k, v in decoding.items() if v is not None and k not in {"timeout_seconds", "concurrency", "schema_retry_count"}),
        }
        rch = sha256_json(request_contract)
        instrument_identity = {
            "prompt_id": inst.get("prompt_id"),
            "prompt_hash": ph,
            "schema_id": inst.get("schema_id"),
            "schema_hash": sh,
            "system_instruction_id": inst.get("system_instruction_id"),
            "system_instruction_hash": sysh,
            "request_contract_hash": rch,
            "features": list(inst.get("features") or []),
            "legacy_feature_keys": dict(inst.get("legacy_feature_keys") or {}),
        }
        ih = sha256_json(instrument_identity)
        protocol_identity = {
            "measurement_protocol_id": cfg["measurement_protocol_id"],
            "measurement_protocol_version": cfg["measurement_protocol_version"],
            "model": cfg.get("model", {}),
            "instrument_hash": ih,
            "decoding_hash": dh,
            "normalization": cfg.get("normalization", {}),
            "failure_policy": cfg.get("failure_policy", {}),
        }
        return cls(root, cp, cfg, pp, sp, prompt, schema, ph, sh, system, sysh, response_schema_name, request_contract, rch, dh, ih, sha256_json(protocol_identity))

    @property
    def id(self) -> str:
        return str(self.config["measurement_protocol_id"])

    @property
    def features(self) -> list[str]:
        return [str(x) for x in self.config["instrument"]["features"]]

    @property
    def legacy_keys(self) -> dict[str, str]:
        return {str(k): str(v) for k, v in self.config["instrument"]["legacy_feature_keys"].items()}

    @property
    def decoding(self) -> dict[str, Any]:
        return dict(self.config.get("decoding") or {})

    @property
    def model(self) -> dict[str, Any]:
        return dict(self.config.get("model") or {})

    def validate_legacy_parity(self) -> dict[str, Any]:
        expected = dict(self.config.get("legacy_parity") or {})
        checks = {
            "prompt_hash": self.prompt_hash == expected.get("expected_prompt_sha256"),
            "schema_hash": self.schema_hash == expected.get("expected_schema_sha256"),
            "system_instruction": self.system_instruction == expected.get("expected_system_instruction"),
            "response_schema_name": self.response_schema_name == expected.get("expected_response_schema_name"),
            "endpoint": self.request_contract.get("endpoint") == expected.get("expected_endpoint"),
            "message_order": self.request_contract.get("message_order") == expected.get("expected_message_order"),
            "temperature": self.decoding.get("temperature") == 0.0,
            "max_tokens": self.decoding.get("max_tokens") == 256,
            "heuristic_fallback": (self.config.get("failure_policy") or {}).get("heuristic_fallback") is False,
        }
        failed = [k for k, ok in checks.items() if not ok]
        if failed:
            raise ValueError("Legacy measurement request parity failed: " + ", ".join(failed))
        return {"verified": True, "checks": checks, "source_implementation": expected.get("source_implementation")}

    def manifest(self) -> dict[str, Any]:
        return {
            "measurement_protocol_id": self.id,
            "measurement_protocol_version": self.config["measurement_protocol_version"],
            "protocol_hash": self.protocol_hash,
            "instrument_hash": self.instrument_hash,
            "prompt_id": self.config["instrument"]["prompt_id"],
            "prompt_hash": self.prompt_hash,
            "schema_id": self.config["instrument"]["schema_id"],
            "schema_hash": self.schema_hash,
            "system_instruction_id": self.config["instrument"].get("system_instruction_id"),
            "system_instruction_hash": self.system_hash,
            "response_schema_name": self.response_schema_name,
            "request_contract": self.request_contract,
            "request_contract_hash": self.request_contract_hash,
            "decoding": self.decoding,
            "decoding_hash": self.decoding_hash,
            "model": self.model,
            "normalization": self.config.get("normalization", {}),
            "failure_policy": self.config.get("failure_policy", {}),
        }
