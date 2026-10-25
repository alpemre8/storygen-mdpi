from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib, json

def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

def sha256_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def prompt_provenance(block_root: Path, strategy: str) -> dict[str, Any]:
    if strategy == "DP-v1":
        user = block_root / "prompts/direct_prompt_per_scene_prompt_v1.json"
        system = block_root / "prompts/direct_prompt_system_v1.txt"
        method = block_root / "configs/methods/direct_prompt_v1.yaml"
    elif strategy == "CG-v1":
        user = block_root / "prompts/curve_guided_per_scene_prompt_v1.json"
        system = block_root / "prompts/curve_guided_system_v1.txt"
        method = block_root / "configs/methods/curve_guided_v1.yaml"
    elif strategy == "NG-v0":
        user = block_root / "prompts/no_guidance_per_scene_prompt_v0.json"
        system = block_root / "prompts/no_guidance_system_v0.txt"
        method = block_root / "configs/methods/no_guidance_v0.yaml"
    else:
        raise ValueError(f"Unsupported prompt contract: {strategy}")
    repair = block_root / "prompts/repair_per_scene_prompt_v1.json"
    files = {
        "user_prompt": {"path": str(user), "sha256": sha256_file(user)},
        "system_prompt": {"path": str(system), "sha256": sha256_file(system)},
        "repair_prompt": {"path": str(repair), "sha256": sha256_file(repair)},
        "method_config": {"path": str(method), "sha256": sha256_file(method)},
    }
    policy = {
        "prompt_contract_id": strategy,
        "reference_film_identity_exposed": False,
        "reference_scene_identity_exposed": False,
        "cg_only_adds_current_target_delta": strategy == "CG-v1",
    }
    if strategy == "NG-v0":
        policy.update(selected_feature_names_exposed=False, directions_exposed=False,
                      numeric_controls_exposed=False, source_only=True)
    return {**files, "information_policy": policy, "information_policy_sha256": sha256_json(policy), "prompt_bundle_sha256": sha256_json({k: v["sha256"] for k, v in files.items()} | {"information_policy": policy})}

def recursive_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(str(k))
            keys |= recursive_keys(v)
    elif isinstance(value, list):
        for v in value:
            keys |= recursive_keys(v)
    return keys
