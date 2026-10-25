"""Strict identities and explicit, hash-checked historical path overrides.

No depot scanning or frozen manifest rewriting is performed here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from .io import read_json, sha256_file
from .metrics import MEASUREMENT_IDENTITY_KEYS, measurement_identity


def required_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value):
        raise RuntimeError(f"Missing or invalid SHA-256 identity: {label}")
    return "sha256:" + value.removeprefix("sha256:")


def required_measurement(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict):
        raise RuntimeError("Missing measurement identity")
    result = {}
    for key in (*MEASUREMENT_IDENTITY_KEYS, "model_sha256"):
        value = identity.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Missing measurement identity: {key}")
        result[key] = required_sha(value, key) if key.endswith("hash") or key == "model_sha256" else value
    return result


def reference_identity(manifest: dict) -> str:
    refs = [manifest[key] for key in ("feature_set_manifest", "reference_feature_set_manifest") if key in manifest]
    if not refs:
        raise RuntimeError("Missing reference FeatureSet identity")
    if any(not isinstance(ref, dict) for ref in refs):
        raise RuntimeError("Invalid reference FeatureSet identity")
    hashes = {required_sha(ref.get("sha256"), "reference FeatureSet") for ref in refs}
    if len(hashes) != 1:
        raise RuntimeError("Conflicting reference FeatureSet identities")
    return hashes.pop()


class ArtifactResolver:
    def __init__(self, overrides: Mapping[str, str | Path] | None = None):
        self.overrides = dict(overrides or {})
        if any(not isinstance(k, str) or not isinstance(v, (str, Path)) for k, v in self.overrides.items()):
            raise RuntimeError("Artifact overrides must map each recorded path to one explicit path; ambiguous matches are forbidden")
        self.evidence: list[dict[str, str]] = []

    def file(self, recorded: Any, expected: Any) -> Path:
        expected = required_sha(expected, "artifact content")
        if not isinstance(recorded, str) or not recorded:
            raise RuntimeError("Missing artifact path")
        path = Path(self.overrides.get(recorded, recorded)).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"Unresolved artifact: {recorded}; supply an explicit path override")
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"Artifact SHA-256 mismatch: {recorded} -> {path}")
        item = {"recorded_path": recorded, "resolved_path": str(path), "sha256": actual}
        if item not in self.evidence:
            self.evidence.append(item)
        return path

    def reference(self, ref: dict, filename: str | None = None) -> Path:
        recorded = ref.get("path")
        if filename and isinstance(recorded, str):
            recorded = str(Path(recorded) / filename)
        return self.file(recorded, ref.get("sha256") or ref.get("manifest_sha256"))


def load_artifact_overrides(path: Path | None) -> dict[str, str]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError(f"Ambiguous duplicate artifact override: {key}")
            result[key] = value
        return result
    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique) if path else {}
    if not isinstance(result, dict):
        raise RuntimeError("Artifact overrides must be a JSON object")
    ArtifactResolver(result)
    return result


def same_provenance(manifests: list[dict], taskset: Path | None = None, artifact_paths=None) -> None:
    if not manifests:
        raise RuntimeError("No evaluation provenance supplied")
    tasksets = {required_sha(m.get("taskset", {}).get("sha256"), "taskset") for m in manifests}
    features = {reference_identity(m) for m in manifests}
    measurements = {json.dumps(required_measurement(m.get("measurement_identity")), sort_keys=True) for m in manifests}
    if len(tasksets) != 1:
        raise RuntimeError("Evaluation artifacts do not share the same frozen taskset SHA-256")
    if len(features) != 1:
        raise RuntimeError("Evaluation artifacts do not share the same reference FeatureSet SHA-256")
    if len(measurements) != 1:
        raise RuntimeError("Evaluation artifacts do not share the same measurement identity")
    if taskset is not None and sha256_file(taskset) != next(iter(tasksets)):
        raise RuntimeError("Supplied taskset/runtime identity differs from evaluation artifacts")
    resolver = ArtifactResolver(artifact_paths)
    for m in manifests:
        reference_path = None
        for key in ("feature_set_manifest", "reference_feature_set_manifest"):
            ref = m.get(key)
            if ref and ref.get("path"):
                reference_path = resolver.reference(ref)
                original = read_json(reference_path)
                validate_reference(original)
                if required_measurement(measurement_identity(original["measurement"])) != required_measurement(m["measurement_identity"]):
                    raise RuntimeError("Evaluation measurement identity differs from reference FeatureSet")
        for key, filename, historical in (("candidate_feature_set", "feature_set_manifest.json", False),
                                           ("reanalysis_run", "reanalysis_manifest.json", True)):
            if taskset is None or key not in m:
                continue
            if reference_path is None:
                raise RuntimeError("Source lineage requires an explicit reference FeatureSet path")
            candidate_path = resolver.reference(m[key], filename)
            candidate = read_json(candidate_path)
            if historical:
                if candidate.get("contract_id") != "storygen.reanalysis-run" or str(candidate.get("contract_version")) != "1.1":
                    raise RuntimeError("Source reanalysis contract mismatch")
            elif candidate.get("contract_id") != "storygen.feature-set" or str(candidate.get("contract_version")) != "1.4" or (candidate.get("source") or {}).get("type") != "rewritten":
                raise RuntimeError("Source candidate FeatureSet contract mismatch")
            validate_runtime(read_json(taskset), original, reference_path, resolver)
            rewrite = validate_source(candidate, taskset, reference_path, original,
                                      m.get("method"), m.get("rewrite_model"), resolver, historical=historical)
            validate_curves(read_json(taskset)["tasks"], candidate_path.parent, rewrite,
                            reference_path, original, resolver)


# Identical to the Taskset owner's frozen structure projection; ordered tasks matter.
STRUCTURE_FIELDS = (
    "task_id", "source_film_id", "reference_film_id", "source_scene_ids",
    "reference_scene_ids", "selected_features", "variant", "interval_type", "base_interval_id", "pair_key", "feature_axis",
)


def structure_sha(tasks: list[dict]) -> str:
    raw = json.dumps([{key: t.get(key) for key in STRUCTURE_FIELDS} for t in tasks], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def validate_reference(manifest: dict) -> None:
    if manifest.get("contract_id") != "storygen.feature-set" or str(manifest.get("contract_version")) != "1.4":
        raise RuntimeError("Reference storygen.feature-set/1.4 is required")
    if (manifest.get("source") or {}).get("type", "original") != "original":
        raise RuntimeError("Reference FeatureSet must contain original measurements")
    required_measurement(measurement_identity(manifest.get("measurement") or {}))
    if (manifest["measurement"].get("failure_policy") or {}).get("heuristic_fallback") is not False:
        raise RuntimeError("Reference measurement must forbid heuristic fallback")
    if "attestation_verified" in manifest and manifest["attestation_verified"] is not True:
        raise RuntimeError("Reference FeatureSet attestation is not verified")


def validate_runtime(taskset: dict, reference: dict, reference_path: Path, resolver: ArtifactResolver) -> None:
    tasks = taskset.get("tasks") or []
    ids = [t.get("task_id") for t in tasks]
    if not ids or any(not x for x in ids) or len(set(ids)) != len(ids):
        raise RuntimeError("Frozen taskset must have nonempty unique task IDs")
    if taskset.get("structure_sha256") and required_sha(taskset["structure_sha256"], "task structure") != structure_sha(tasks):
        raise RuntimeError("Frozen taskset structure SHA-256 mismatch")
    if taskset.get("feature_set_id") != reference.get("feature_set_id") or not reference.get("feature_set_id"):
        raise RuntimeError("Taskset/reference FeatureSet identity mismatch")
    expected = sha256_file(reference_path)
    if required_sha(taskset.get("feature_set_manifest_sha256"), "taskset reference") != expected:
        raise RuntimeError("Taskset/reference FeatureSet hash mismatch")
    resolver.file(taskset.get("feature_set_manifest"), expected)
    for t in tasks:
        if t.get("runtime_feature_set_id") != reference["feature_set_id"] or t.get("runtime_measurement_protocol_hash") != reference["measurement"]["protocol_hash"]:
            raise RuntimeError(f"Task/reference measurement lineage mismatch: {t['task_id']}")
        for side in ("source", "reference"):
            film = t.get(f"{side}_film_id")
            if not isinstance(film, str) or Path(film).name != film:
                raise RuntimeError("Invalid task film identity")
            canonical = reference_path.parent / "films" / film / "scene_features_llm.json"
            resolver.file(t.get(f"{side}_feature_path"), sha256_file(canonical))


def validate_taskset_link(ref: dict, runtime_path: Path, reference: dict, reference_path: Path,
                          resolver: ArtifactResolver, *, allow_legacy: bool = False) -> None:
    original_path = resolver.reference(ref)
    original = read_json(original_path)
    current = read_json(runtime_path)
    validate_runtime(original, reference, reference_path, resolver)
    if sha256_file(original_path) != sha256_file(runtime_path):
        if not allow_legacy or structure_sha(original["tasks"]) != structure_sha(current["tasks"]):
            raise RuntimeError("Source taskset/runtime identity mismatch")
        # Earlier runtimes have different metadata and migrated paths. Equality of
        # the ordered structure PLUS independently verified reference bindings is required.
    if ref.get("task_count", len(original["tasks"])) != len(current["tasks"]):
        raise RuntimeError("Source taskset task count mismatch")


def validate_source(candidate: dict, runtime_path: Path, reference_path: Path, reference: dict,
                    method: str, model: str, resolver: ArtifactResolver, *, historical: bool) -> Path:
    identity = required_measurement(measurement_identity(reference["measurement"]))
    if required_measurement(measurement_identity(candidate.get("measurement") or {})) != identity:
        raise RuntimeError("Candidate/reference measurement identity mismatch")
    if not historical and candidate.get("measurement") != reference["measurement"]:
        raise RuntimeError("Candidate/reference full measurement contract mismatch")
    if (candidate["measurement"].get("failure_policy") or {}).get("heuristic_fallback") is not False:
        raise RuntimeError("Candidate measurement must forbid heuristic fallback")
    source = candidate if historical else candidate.get("source") or {}
    fs_ref = source.get("source_feature_set_manifest") if historical else source.get("reference_feature_set")
    if not isinstance(fs_ref, dict) or required_sha(fs_ref.get("sha256") or fs_ref.get("manifest_sha256"), "candidate reference") != sha256_file(reference_path):
        raise RuntimeError("Candidate/reference FeatureSet lineage mismatch")
    resolver.reference(fs_ref)
    validate_taskset_link(candidate.get("taskset") or {}, runtime_path, reference, reference_path, resolver, allow_legacy=historical)
    rw_ref = source.get("source_rewrite_run") if historical else source.get("rewrite_run")
    rw_path = resolver.reference(rw_ref or {}, "rewrite_run_manifest.json")
    rw = read_json(rw_path)
    if rw.get("contract_id") != "storygen.rewrite-run" or str(rw.get("contract_version")) != "1.3":
        raise RuntimeError("Source storygen.rewrite-run/1.3 is required")
    if rw.get("prompt_contract_id") != method or (rw.get("model") or {}).get("served_alias") != model:
        raise RuntimeError("Source rewrite method/model lineage mismatch")
    fs_ref = rw.get("feature_set_manifest") or {}
    if required_sha(fs_ref.get("sha256"), "rewrite reference") != sha256_file(reference_path):
        raise RuntimeError("Source rewrite/reference FeatureSet lineage mismatch")
    resolver.reference(fs_ref)
    if required_measurement(measurement_identity(fs_ref.get("measurement") or {})) != identity:
        raise RuntimeError("Source rewrite/reference measurement lineage mismatch")
    validate_taskset_link(rw.get("taskset") or {}, runtime_path, reference, reference_path, resolver, allow_legacy=True)
    return rw_path.parent


def validate_curves(tasks: list[dict], candidate_root: Path, rewrite_root: Path,
                    reference_path: Path, reference: dict, resolver: ArtifactResolver) -> None:
    rows_by_film = {}
    protocol = required_measurement(measurement_identity(reference["measurement"]))
    for t in tasks:
        curves = []
        feature = (t.get("selected_features") or [t.get("feature_axis")])[0]
        for side in ("source", "reference"):
            film = t.get(f"{side}_film_id")
            if not isinstance(film, str) or Path(film).name != film:
                raise RuntimeError("Invalid task film identity")
            root = reference_path.parent / "films" / film
            path = root / "scene_features_llm.json"
            if film not in rows_by_film:
                status = read_json(root / "measurement_manifest.json")
                if required_measurement(measurement_identity(status.get("measurement") or {})) != protocol:
                    raise RuntimeError("Film/reference measurement identity mismatch")
                rows = read_json(path)
                index = {r["scene_id"]: r for r in rows}
                if len(index) != len(rows):
                    raise RuntimeError("Duplicate reference measurement scene IDs")
                rows_by_film[film] = index
            if side == "source":
                status = read_json(root / "measurement_manifest.json")
                if status.get("script_hash"):
                    resolver.file(t.get("source_script_path"), status["script_hash"])
            resolver.file(t.get(f"{side}_feature_path"), sha256_file(path))
            try:
                values = [rows_by_film[film][sid][feature] for sid in t[f"{side}_scene_ids"]]
            except KeyError as exc:
                raise RuntimeError(f"Missing reference feature/scene: {t['task_id']}") from exc
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
                raise RuntimeError("Invalid canonical B/T measurement values")
            curves.append([round(float(v), 6) for v in values])
        before, target_raw = curves
        if not before or not target_raw:
            raise RuntimeError("Empty task B/T selection")
        target = _resample(target_raw, len(before))
        for task_root in {rewrite_root / "tasks" / t["task_id"], candidate_root / "tasks" / t["task_id"]}:
            path = task_root / "transfer_plan.json"
            if not path.exists():
                continue  # Missing/failed tasks retain the original metric eligibility policy.
            plan = read_json(path)
            for key in ("source_scene_ids", "reference_scene_ids", "selected_features"):
                if plan.get(key) != t.get(key):
                    raise RuntimeError(f"Candidate B/T selection lineage mismatch: {t['task_id']} {key}")
            for key, values in (("source_current_curve", before), ("reference_curve", target_raw), ("resampled_target_curve", target)):
                if (plan.get(key) or {}).get(feature) != values:
                    raise RuntimeError(f"Candidate B/T curve lineage mismatch: {t['task_id']} {key}")
            for key, side in (("feature_source_path", "source"), ("reference_feature_source_path", "reference")):
                canonical = reference_path.parent / "films" / t[f"{side}_film_id"] / "scene_features_llm.json"
                resolver.file(plan.get(key), sha256_file(canonical))
        candidate_text = candidate_root / "tasks" / t["task_id"] / "rewritten_scenes.json"
        source_text = rewrite_root / "tasks" / t["task_id"] / "rewritten_scenes.json"
        if candidate_text.exists() and (not source_text.exists() or sha256_file(candidate_text) != sha256_file(source_text)):
            raise RuntimeError(f"Candidate/source rewritten text lineage mismatch: {t['task_id']}")


def _resample(values: list[float], n: int) -> list[float]:
    # Frozen transfer planner v1: linear interpolation, midpoint for n=1, six decimals.
    def at(position):
        lo, hi = math.floor(position), math.ceil(position)
        weight = position - lo
        return round(values[lo] * (1 - weight) + values[hi] * weight, 6)
    if n == len(values):
        return values[:]
    if len(values) == 1:
        return values * n
    if n == 1:
        return [at((len(values) - 1) / 2)]
    return [at(i * (len(values) - 1) / (n - 1)) for i in range(n)]
