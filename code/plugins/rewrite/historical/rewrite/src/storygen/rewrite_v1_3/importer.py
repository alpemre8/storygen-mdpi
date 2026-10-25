from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json, shutil
from .taskset import load_taskset
from .provenance import prompt_provenance, recursive_keys, sha256_file

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _model_preflight(model_file: Path, server_manifest: Path, model_alias: str, quantization: str, concurrency: int = 4) -> dict[str, Any]:
    if not model_file.is_file() or not server_manifest.is_file():
        raise FileNotFoundError("model file or server manifest missing")
    sm = read_json(server_manifest)
    actual = sha256_file(model_file)
    served = str(sm.get("model_sha256") or "")
    served = served if served.startswith("sha256:") else "sha256:" + served
    if served != actual:
        raise RuntimeError("Server/model SHA mismatch")
    if str(sm.get("model_alias") or "") != model_alias:
        raise RuntimeError("Server alias mismatch")
    if str(sm.get("quantization") or "") != quantization:
        raise RuntimeError("Server quantization mismatch")
    if int(sm.get("parallel_slots", 0)) < concurrency:
        raise RuntimeError("Insufficient server parallel slots")
    if int(sm.get("context_per_slot", 0)) < 8192:
        raise RuntimeError("context_per_slot must be at least 8192")
    return {"content": sm, "path": str(server_manifest), "sha256": sha256_file(server_manifest), "model_sha256": actual}

def import_legacy_dp_run(*, project_root: Path, block_root: Path, legacy_run: Path, taskset_path: Path, feature_set_manifest: Path, output_root: Path, run_id: str, model_alias: str, model_file: Path, quantization: str, server_manifest: Path, overwrite: bool = False, max_tasks: int | None = None) -> dict[str, Any]:
    taskset = load_taskset(taskset_path)
    tasks = taskset.tasks[:max_tasks or len(taskset.tasks)]
    fsm = read_json(feature_set_manifest)
    if fsm.get("contract_id") != "storygen.feature-set" or str(fsm.get("contract_version")) != "1.4" or fsm.get("attestation_verified") is not True:
        raise RuntimeError("verified feature-set/1.4 manifest required")
    runtime = _model_preflight(model_file, server_manifest, model_alias, quantization)
    provenance = prompt_provenance(block_root, "DP-v1")
    expected_system = Path(provenance["system_prompt"]["path"]).read_text(encoding="utf-8").strip()
    output = output_root / run_id
    if output.exists():
        if not overwrite:
            raise FileExistsError(output)
        shutil.rmtree(output)
    (output / "tasks").mkdir(parents=True)
    failures = []
    imported = []
    for task in tasks:
        source = legacy_run / "tasks" / task.task_id
        target = output / "tasks" / task.task_id
        target.mkdir(parents=True)
        try:
            rewritten_path = source / "rewritten_scenes.json"
            if not rewritten_path.is_file():
                raise RuntimeError("missing rewritten_scenes.json")
            rewritten = read_json(rewritten_path)
            returned = [str(x.get("scene_id")) for x in rewritten.get("rewritten_scenes", [])]
            if returned != task.source_scene_ids:
                raise RuntimeError(f"exact scene order mismatch: {returned}")
            request_hashes = []
            for sid in task.source_scene_ids:
                request_path = source / "per_scene" / sid / "rewrite_request.json"
                if not request_path.is_file():
                    raise RuntimeError(f"missing strict request artifact for {sid}")
                req = read_json(request_path)
                if str(req.get("prompt_strategy")) != "direct_prompt" or str(req.get("prompt_version")) != "v1":
                    raise RuntimeError(f"{sid}: not a direct_prompt v1 request")
                if str(req.get("system_instruction") or "").strip() != expected_system:
                    raise RuntimeError(f"{sid}: DP-v1 system instruction mismatch")
                if str(req.get("expected_scene_id") or "") != sid:
                    raise RuntimeError(f"{sid}: expected_scene_id mismatch")
                try:
                    user = json.loads(str(req.get("user_instruction") or ""))
                except Exception as exc:
                    raise RuntimeError(f"{sid}: user instruction is not JSON: {exc}") from exc
                template_id = str((user.get("prompt_template") or {}).get("id") or "")
                if template_id != "direct_prompt_per_scene_prompt_v1":
                    raise RuntimeError(f"{sid}: direct prompt template ID mismatch: {template_id}")
                keys = recursive_keys(user)
                forbidden = {"reference_film_id", "reference_interval_scene_ids", "current_values", "targets", "deltas", "target_values"}
                leaked = sorted(keys & forbidden)
                if leaked:
                    raise RuntimeError(f"{sid}: non-DP information leaked: {leaked}")
                request_hashes.append({"scene_id": sid, "path": str(request_path), "sha256": sha256_file(request_path)})
            for item in source.iterdir():
                dst = target / item.name
                if item.is_dir():
                    shutil.copytree(item, dst)
                elif item.is_file():
                    shutil.copy2(item, dst)
            if not (target / "task.json").exists():
                write_json(target / "task.json", task.model_dump(mode="json"))
            status = {"task_id": task.task_id, "rewrite_completed": True, "prompt_contract_id": "DP-v1", "origin": "legacy_verified_import", "source_scene_ids": task.source_scene_ids, "prompt_bundle_sha256": provenance["prompt_bundle_sha256"], "request_artifacts": request_hashes, "created_at": datetime.now(timezone.utc).isoformat()}
            write_json(target / "phase_status.json", status)
            imported.append(task.task_id)
        except Exception as exc:
            failure = {"task_id": task.task_id, "stage": "legacy_dp_import", "root_cause_type": type(exc).__name__, "error": str(exc)}
            failures.append(failure)
            write_json(target / "rewrite_failure.json", failure)
    manifest = {
        "contract_id": "storygen.rewrite-run",
        "contract_version": "1.3",
        "block_version": "1.3.1",
        "rewrite_protocol_id": "rewrite-v1.3",
        "prompt_contract_id": "DP-v1",
        "origin": "legacy_verified_import",
        "source_legacy_run": {"path": str(legacy_run)},
        "prompt_provenance": provenance,
        "information_policy": provenance["information_policy"],
        "model": {"served_alias": model_alias, "exact_file": str(model_file), "file_sha256": runtime["model_sha256"], "quantization": quantization},
        "server_manifest": runtime,
        "feature_set_manifest": {"path": str(feature_set_manifest), "sha256": sha256_file(feature_set_manifest), "measurement": fsm.get("measurement")},
        "taskset": {"path": str(taskset_path), "sha256": sha256_file(taskset_path), "task_count": len(tasks)},
        "tasks_completed": len(imported),
        "tasks_failed": len(failures),
        "failures": failures,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "legacy_dp_import_report.json", {"verified": not failures, "imported_task_ids": imported, "failures": failures})
    write_json(output / "rewrite_run_manifest.json", manifest)
    if failures:
        raise RuntimeError(f"{len(failures)} legacy DP tasks failed strict import; artifacts preserved")
    return manifest
