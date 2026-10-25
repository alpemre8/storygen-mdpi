from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json, math, yaml

from storygen_measurement_core import MeasurementProtocol, validate_runtime_identity
from storygen_measurement_core.io import sha256_file
from .io import load_script, write_json

class AttestationError(RuntimeError):
    pass

def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

def _normal_hash(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value if value.startswith("sha256:") else "sha256:" + value

def _require_equal(label: str, actual: Any, expected: Any, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label}: expected={expected!r} actual={actual!r}")

def attest_existing_feature_set(*, project_root: Path, core_root: Path, protocol_path: Path, feature_set_id: str, feature_store_root: Path, legacy_feature_set_manifest: Path, legacy_feature_store_manifest: Path, film_set_path: Path, registry_path: Path, model_file: Path, server_manifest: Path, output_dir: Path) -> dict[str, Any]:
    protocol = MeasurementProtocol.load(core_root, protocol_path)
    parity = protocol.validate_legacy_parity()
    runtime = validate_runtime_identity(protocol, model_file=model_file, server_manifest=server_manifest, require_slots=8)
    legacy_set = _load_yaml(legacy_feature_set_manifest)
    legacy_store = _load_yaml(legacy_feature_store_manifest)
    film_set = _load_yaml(film_set_path)
    registry = _load_yaml(registry_path)
    errors: list[str] = []
    checks: dict[str, Any] = {}

    _require_equal("feature_set_id", legacy_set.get("feature_set_id"), feature_set_id, errors)
    _require_equal("feature extraction signature", legacy_set.get("feature_extraction_signature"), "qwen25_7b_gguf_q4km_feature_v1", errors)
    _require_equal("store signature", legacy_store.get("feature_extraction_signature"), "qwen25_7b_gguf_q4km_feature_v1", errors)
    model = legacy_set.get("model") or legacy_store.get("model") or {}
    _require_equal("legacy model alias", model.get("name"), protocol.model.get("alias"), errors)
    _require_equal("legacy quantization", model.get("quantization"), protocol.model.get("quantization"), errors)
    _require_equal("legacy temperature", float(model.get("temperature", -1)), float(protocol.decoding.get("temperature")), errors)
    _require_equal("legacy max_tokens", int(model.get("max_tokens", -1)), int(protocol.decoding.get("max_tokens")), errors)
    _require_equal("legacy endpoint", model.get("endpoint"), "/v1/chat/completions", errors)
    prompt = legacy_store.get("prompt") or {}
    schema = legacy_store.get("schema") or {}
    _require_equal("legacy prompt id", prompt.get("template_id"), protocol.config["instrument"].get("prompt_id"), errors)
    _require_equal("legacy schema id", schema.get("schema_id"), protocol.config["instrument"].get("schema_id"), errors)
    _require_equal("legacy feature keys", schema.get("legacy_source_feature_keys"), protocol.legacy_keys, errors)
    if _normal_hash(runtime["model_sha256"]) != _normal_hash(protocol.model.get("model_sha256")):
        errors.append("runtime model SHA does not match canonical measurement model")

    films = [str(x) for x in film_set.get("films", [])]
    if len(films) != 10 or len(set(films)) != 10:
        errors.append(f"canonical film set must contain 10 unique films; got {len(films)}")
    legacy_films = legacy_set.get("films") or {}
    store_film_rows = {str(x.get("film_id")): x for x in (legacy_store.get("films") or []) if isinstance(x, dict)}
    result_films = []
    total_scenes = 0
    for film_id in films:
        reg = (registry.get("films") or {}).get(film_id)
        if not isinstance(reg, dict):
            errors.append(f"registry missing film {film_id}")
            continue
        script = (project_root / reg["script_path"]).resolve()
        if not script.is_file():
            errors.append(f"script missing for {film_id}: {script}")
            continue
        script_hash = sha256_file(script)
        expected_script_hash = _normal_hash(reg.get("script_hash"))
        if script_hash != expected_script_hash:
            errors.append(f"registry script hash mismatch for {film_id}")
        _, scenes = load_script(script)
        expected_ids = [str(x["scene_id"]) for x in scenes]
        if int(reg.get("scene_count", -1)) != len(scenes):
            errors.append(f"registry scene count mismatch for {film_id}")
        legacy_row = legacy_films.get(film_id) or {}
        if _normal_hash(legacy_row.get("script_hash")) != script_hash:
            errors.append(f"legacy feature-set script hash mismatch for {film_id}")
        if int(legacy_row.get("scene_count", -1)) != len(scenes):
            errors.append(f"legacy feature-set scene count mismatch for {film_id}")
        if int((store_film_rows.get(film_id) or {}).get("scene_count", -1)) != len(scenes):
            errors.append(f"legacy feature-store scene count mismatch for {film_id}")
        feature_file = feature_store_root / "films" / film_id / "scene_features_llm.json"
        if not feature_file.is_file():
            errors.append(f"feature file missing for {film_id}")
            continue
        try:
            rows = json.loads(feature_file.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid feature JSON for {film_id}: {exc}")
            continue
        if not isinstance(rows, list):
            errors.append(f"feature file is not a list for {film_id}")
            continue
        ids = [str(x.get("scene_id")) for x in rows if isinstance(x, dict)]
        if ids != expected_ids:
            errors.append(f"feature scene IDs/order mismatch for {film_id}")
        duplicates = [k for k, v in Counter(ids).items() if v > 1]
        if duplicates:
            errors.append(f"duplicate feature scene IDs for {film_id}: {duplicates[:5]}")
        invalid_values = []
        for row in rows:
            if not isinstance(row, dict):
                invalid_values.append("non-object-row")
                continue
            for key in protocol.legacy_keys.values():
                value = row.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                    invalid_values.append(f"{row.get('scene_id')}:{key}")
        if invalid_values:
            errors.append(f"invalid feature values for {film_id}: {invalid_values[:8]}")
        total_scenes += len(rows)
        result_films.append({
            "film_id": film_id,
            "scene_count": len(rows),
            "script_path": str(script),
            "script_sha256": script_hash,
            "feature_file": str(feature_file),
            "feature_file_sha256": sha256_file(feature_file),
            "scene_identity_verified": ids == expected_ids,
            "feature_values_verified": not invalid_values,
        })
    if total_scenes != 938:
        errors.append(f"canonical feature store must contain 938 scenes; got {total_scenes}")
    checks.update({
        "legacy_request_parity": parity,
        "film_count": len(result_films),
        "scene_count": total_scenes,
        "all_script_hashes_verified": not any("script hash mismatch" in e for e in errors),
        "all_scene_identities_verified": all(x["scene_identity_verified"] for x in result_films),
        "all_feature_values_verified": all(x["feature_values_verified"] for x in result_films),
    })
    report = {
        "attestation_id": "existing-feature-set-attestation-v1.4",
        "verified": not errors,
        "errors": errors,
        "checks": checks,
        "legacy_feature_set_manifest": {"path": str(legacy_feature_set_manifest), "sha256": sha256_file(legacy_feature_set_manifest)},
        "legacy_feature_store_manifest": {"path": str(legacy_feature_store_manifest), "sha256": sha256_file(legacy_feature_store_manifest)},
        "film_set": {"path": str(film_set_path), "sha256": sha256_file(film_set_path)},
        "registry": {"path": str(registry_path), "sha256": sha256_file(registry_path)},
        "films": result_films,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "attestation_report.json", report)
    if errors:
        raise AttestationError(f"Feature-set attestation failed with {len(errors)} error(s); see {output_dir / 'attestation_report.json'}")
    manifest = {
        "contract_id": "storygen.feature-set",
        "contract_version": "1.4",
        "block_version": "1.4.1",
        "feature_set_id": feature_set_id,
        "attestation_only": True,
        "attestation_verified": True,
        "measurement": protocol.manifest(),
        "runtime_identity": runtime,
        "feature_store_root": str(feature_store_root),
        "legacy_provenance": report,
        "films": result_films,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / "feature_set_manifest.json", manifest)
    return manifest
