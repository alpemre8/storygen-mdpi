"""E01A bounded independent audit, reusing the canonical measurement assets.

Generation lineage stays Qwen; the audit measurement identity is separate.
This module never constructs TI/DA or launches/downloads a model.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

import httpx
import yaml

from storygen_measurement_core import MeasurementProtocol, CanonicalFeatureScorer
from storygen_measurement_core.client import build_request_payload
from storygen_measurement_core.preflight import assert_measurement_equal
from .io import read_json, write_json, sha256_json, sha256_bytes, load_script
from .precision import file_sha256, inspect_gguf, require_fp16, require_mistral_structure

PROFILE_ID = "e01-independent-fp16-v1"


def checked(ref: dict) -> Path:
    path = Path(ref["path"]).resolve()
    if not path.is_file() or file_sha256(path) != ref["sha256"]:
        raise ValueError(f"Missing/incompatible input artifact: {path}")
    return path


def reference(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": file_sha256(path)}


def load_profile(core: Path, path: Path, *, require_bound=False) -> MeasurementProtocol:
    protocol = MeasurementProtocol.load(core, path)
    original = MeasurementProtocol.load(core, "configs/feature_measurement_v1.yaml")
    protocol.validate_legacy_parity()
    if protocol.id != PROFILE_ID or protocol.config["measurement_protocol_version"] != "1.0.0":
        raise ValueError("Explicit independent measurement profile required")
    if protocol.config["instrument"] != original.config["instrument"] or protocol.instrument_hash != original.instrument_hash:
        raise ValueError("Unapproved instrument adaptation")
    model = protocol.model
    if model.get("family") != "mistral" or model.get("model_id") != "mistralai/Mistral-7B-Instruct-v0.3":
        raise ValueError("Wrong independent model/variant")
    if model.get("weight_precision") != "F16" or model.get("quantization") != "F16" or model.get("checkpoint_format") != "gguf":
        raise ValueError("Independent profile requires actual F16 GGUF weights")
    expected_decoding = dict(original.decoding)
    expected_decoding.update(timeout_seconds=180, concurrency=1, schema_retry_count=1)
    if protocol.decoding != expected_decoding:
        raise ValueError("Unapproved decoding configuration")
    if protocol.config.get("normalization") != {"clamp_values": False, "value_min": 0.0, "value_max": 1.0}:
        raise ValueError("Strict range rejection required")
    if protocol.config.get("failure_policy") != original.config["failure_policy"]:
        raise ValueError("Strict no-fallback failure policy required")
    qualification = protocol.config.get("qualification", {})
    if qualification.get("max_unique_scenes") != 20 or qualification.get("max_real_requests") != 40:
        raise ValueError("E01A request bounds must remain frozen")
    runtime = protocol.config["runtime"]
    if runtime != {"host": "127.0.0.1", "port": 8081, "device": "Vulkan0", "gpu_layers": 24,
                   "context_size": 8192, "parallel_slots": 1, "batch_size": 512, "ubatch_size": 128,
                   "threads": 6, "flash_attention": "on", "cache_type_k": "f16", "cache_type_v": "f16",
                   "jinja": True, "context_shift": False, "fit": "off", "timeout_seconds": 180}:
        raise ValueError("Runtime configuration changed; qualification profile revision required")
    if model.get("runtime_configuration_hash") != sha256_json(runtime) or model.get("qualification_policy_hash") != sha256_json(qualification):
        raise ValueError("Runtime/qualification configuration identity mismatch")
    if model.get("base_url") != "http://127.0.0.1:8081/v1":
        raise ValueError("Local qualification endpoint required")
    if require_bound and (model.get("binding_status") != "BOUND_PRECISION_VERIFIED" or
                          not re.fullmatch(r"sha256:[0-9a-f]{64}", str(model.get("model_sha256")))):
        raise ValueError("HUMAN_RUN_PENDING: FP16 checkpoint identity is unbound")
    return protocol


def launch_args(protocol: MeasurementProtocol) -> list[str]:
    r, m = protocol.config["runtime"], protocol.model
    return [m["server_binary"], "--model", m["checkpoint_path"], "--alias", m["alias"],
            "--device", r["device"], "--gpu-layers", str(r["gpu_layers"]),
            "--ctx-size", str(r["context_size"]), "--parallel", str(r["parallel_slots"]),
            "--batch-size", str(r["batch_size"]), "--ubatch-size", str(r["ubatch_size"]),
            "--threads", str(r["threads"]), "--flash-attn", r["flash_attention"],
            "--cache-type-k", r["cache_type_k"], "--cache-type-v", r["cache_type_v"],
            "--jinja", "--no-context-shift", "--fit", r["fit"], "--host", r["host"],
            "--port", str(r["port"]), "--timeout", str(r["timeout_seconds"]), "--metrics"]


def verify_checkpoint(protocol: MeasurementProtocol) -> dict:
    evidence = inspect_gguf(protocol.model["checkpoint_path"])
    require_fp16(evidence, family=protocol.model["family"], model_id=protocol.model["model_id"])
    require_mistral_structure(evidence)
    if evidence["sha256"] != protocol.model["model_sha256"]:
        raise ValueError("Exact checkpoint SHA256 mismatch")
    return evidence


def _backend_version(server_binary: str, expected_commit: str) -> str:
    result = subprocess.run([server_binary, "--version"], check=True, capture_output=True, text=True)
    version = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if expected_commit[:9] not in version:
        raise ValueError("Backend build commit mismatch")
    return version


def bind_checkpoint(core: Path, template: Path, model_file: Path, destination: Path) -> dict:
    protocol = load_profile(core, template)
    evidence = inspect_gguf(model_file)
    require_fp16(evidence, family=protocol.model["family"], model_id=protocol.model["model_id"])
    require_mistral_structure(evidence)
    cfg = yaml.safe_load(protocol.config_path.read_text())
    cfg["model"].update(checkpoint_path=str(model_file.resolve()), model_sha256=evidence["sha256"],
                        binding_status="BOUND_PRECISION_VERIFIED",
                        tokenizer_chat_template_sha256=sha256_bytes(evidence["metadata"]["tokenizer.chat_template"].encode()))
    for name in ("server_binary", "vulkan_library"):
        if file_sha256(cfg["model"][name]) != cfg["model"][name + "_sha256"]:
            raise ValueError("Backend build bytes changed; explicit profile revision required")
    version = _backend_version(cfg["model"]["server_binary"], cfg["model"]["llama_cpp_commit"])
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "bound_profile.yaml"
    if target.exists():
        raise FileExistsError("Bound profile already exists; preserve its identity")
    target.write_text(yaml.safe_dump(cfg, sort_keys=False))
    bound = load_profile(core, target, require_bound=True)
    write_json(destination / "precision_verification.json", evidence)
    write_json(destination / "measurement_profile.json", bound.manifest())
    write_json(destination / "server_configuration.json", {"status": "PLANNED_NOT_LIVE_VERIFIED", "argv": launch_args(bound),
               "measurement": bound.manifest(), "backend_version": version})
    return {"profile": str(target), "protocol_hash": bound.protocol_hash, "model_sha256": evidence["sha256"],
            "launch_argv": launch_args(bound)}


def _verify_chat_template(live_template: str, embedded_sha256: str) -> dict:
    live_sha256 = sha256_bytes(live_template.encode())
    compatibility_exception = None
    if live_sha256 != embedded_sha256:
        if (embedded_sha256 != "e16746b40344d6c5b5265988e0328a0bf7277be86f1c335156eae07e29c82826"
                or live_sha256 != "cafb64e0e9e5fd2503054b3479593fae39cbdfd52338ce8af9bb4664a8eb05bd"
                or sha256_bytes((live_template + "\n").encode()) != embedded_sha256):
            raise ValueError("Live template differs from the verified embedded template")
        compatibility_exception = "verified_embedded_template_has_one_additional_trailing_LF"
    return {"embedded_template_sha256": embedded_sha256, "live_template_sha256": live_sha256,
            "compatibility_exception": compatibility_exception}


def verify_live_runtime(protocol: MeasurementProtocol) -> dict:
    """A served alias alone is insufficient: bind API to an exact local process."""
    for key in ("server_binary", "vulkan_library"):
        if file_sha256(protocol.model[key]) != protocol.model[key + "_sha256"]:
            raise ValueError("Backend binary/library identity mismatch")
    expected = launch_args(protocol)
    matches = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
            if args and Path(args[0]).resolve() == Path(expected[0]).resolve() and args[1:] == expected[1:]:
                if (proc / "exe").resolve() != Path(expected[0]).resolve():
                    raise ValueError("Live executable identity mismatch")
                env = (proc / "environ").read_bytes().split(b"\0")
                if any(e.startswith(b"LLAMA_ARG_") for e in env):
                    raise ValueError("Unrecorded LLAMA_ARG runtime environment overrides")
                matches.append(int(proc.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if len(matches) != 1:
        raise ValueError("HUMAN_RUN_PENDING: exactly one server with the frozen launch arguments must be running")
    base = protocol.model["base_url"].removesuffix("/v1")
    with httpx.Client(timeout=10) as client:
        health = client.get(base + "/health"); health.raise_for_status()
        response = client.get(base + "/props"); response.raise_for_status(); props = response.json()
        models = client.get(base + "/v1/models"); models.raise_for_status()
    if protocol.model["alias"] not in [m["id"] for m in models.json()["data"]]:
        raise ValueError("Wrong live model alias")
    if Path(props["model_path"]).resolve() != Path(protocol.model["checkpoint_path"]).resolve():
        raise ValueError("Wrong live checkpoint path")
    if props["total_slots"] != 1 or props["default_generation_settings"]["n_ctx"] != 8192:
        raise ValueError("Live slots/context mismatch")
    template_verification = _verify_chat_template(
        props["chat_template"], protocol.model.get("tokenizer_chat_template_sha256"))
    if protocol.model["llama_cpp_commit"][:9] not in json.dumps(props["build_info"]):
        raise ValueError("Live backend build mismatch")
    return {"verified": True, "pid": matches[0], "argv": expected, "props": props,
            "template_verification": template_verification,
            "observed_at": datetime.now(timezone.utc).isoformat()}


class StrictIndependentScorer(CanonicalFeatureScorer):
    """Reuse canonical prompt rendering; reject every schema violation."""
    def score_scene(self, **kwargs):
        raise ValueError("Independent scoring requires the bounded audit runner and its lineage checks")

    def _parse(self, text: str) -> dict[str, float]:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Duplicate JSON key")
                result[key] = value
            return result
        obj = json.loads(text, object_pairs_hook=pairs)
        if not isinstance(obj, dict) or set(obj) != {"features"}:
            raise ValueError("Exact nested features root required")
        values = obj["features"]
        if not isinstance(values, dict) or set(values) != set(self.protocol.features):
            raise ValueError("Exactly five feature keys required")
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
            raise ValueError("Finite numeric feature values in [0,1] required")
        return {key: round(float(values[key]), 6) for key in self.protocol.features}


def prepare_input_contract(analysis_plan: Path, original_input_root: Path) -> dict:
    """Explicit hash-bound migrated paths from the verified P01B plan."""
    plan = read_json(analysis_plan)
    checked(plan["taskset"])
    manifest = read_json(checked(plan["reference_feature_set"]))
    films = {}
    root = Path(plan["reference_feature_set"]["path"]).parent
    for film in manifest["films"]:
        fid = film["film_id"]
        mp = root / "films" / fid / "measurement_manifest.json"
        measurement = read_json(mp)
        # An explicit migrated owner path, verified against the frozen hash.
        script = original_input_root / "films" / fid / "script.json"
        if file_sha256(script) != measurement["script_sha256"]:
            raise ValueError("Canonical script SHA differs from frozen film measurement")
        films[fid] = {"script": reference(script), "measurement_manifest": reference(mp)}
    runs = [run for run in plan["runs"] if run["display_model"] in {"Gemma-3-12B", "Qwen2.5-7B"}]
    for run in runs:
        checked(run["rewrite_manifest"]); checked(run["records"])
    return {"contract_id": "storygen.independent-audit-inputs", "contract_version": "1.0",
            "analysis_plan": reference(analysis_plan), "taskset": plan["taskset"],
            "generation_feature_set": plan["reference_feature_set"], "films": films,
            "runs": runs, "scope": "E01A inventory and bounded qualification only"}


def load_catalog(contract: dict) -> dict:
    if contract.get("contract_id") != "storygen.independent-audit-inputs" or contract.get("contract_version") != "1.0":
        raise ValueError("Independent input contract required")
    taskset = read_json(checked(contract["taskset"]))
    fs = read_json(checked(contract["generation_feature_set"]))
    if fs.get("contract_id") != "storygen.feature-set" or str(fs.get("contract_version")) != "1.4" or fs.get("attestation_verified") is not True:
        raise ValueError("Verified original generation FeatureSet required")
    if taskset.get("feature_set_manifest_sha256") != contract["generation_feature_set"]["sha256"]:
        raise ValueError("Taskset generation FeatureSet mismatch")
    tasks = {task["task_id"]: task for task in taskset["tasks"]}
    if len(tasks) != len(taskset["tasks"]):
        raise ValueError("Duplicate task IDs")
    scenes = {}
    for fid, entry in contract["films"].items():
        script = checked(entry["script"])
        film_manifest = read_json(checked(entry["measurement_manifest"]))
        if film_manifest["film_id"] != fid or film_manifest["script_sha256"] != entry["script"]["sha256"]:
            raise ValueError("Film/script lineage mismatch")
        assert_measurement_equal(fs["measurement"], film_manifest["measurement"])
        _, normalized = load_script(script)
        if len({s["scene_id"] for s in normalized}) != len(normalized):
            raise ValueError("Duplicate normalized scene IDs")
        scenes[fid] = {s["scene_id"]: s for s in normalized}
    for task in tasks.values():
        for role in ("source", "reference"):
            fid = task[role + "_film_id"]
            ids = task[role + "_scene_ids"]
            if len(set(ids)) != len(ids) or any(sid not in scenes.get(fid, {}) for sid in ids):
                raise ValueError("Missing/duplicate task scene IDs")
    runs = {}
    for run in contract["runs"]:
        rm = checked(run["rewrite_manifest"]); manifest = read_json(rm)
        if manifest.get("contract_id") != "storygen.rewrite-run" or str(manifest.get("contract_version")) != "1.3":
            raise ValueError("Frozen rewrite-run/1.3 required")
        assert_measurement_equal(fs["measurement"], manifest["feature_set_manifest"]["measurement"], label="generation lineage")
        if manifest["feature_set_manifest"]["sha256"] != contract["generation_feature_set"]["sha256"]:
            raise ValueError("Rewrite generation FeatureSet mismatch")
        records = [json.loads(line) for line in checked(run["records"]).read_text().splitlines() if line.strip()]
        by_task = {r["task_id"]: r for r in records}
        if len(records) != len(tasks) or set(by_task) != set(tasks):
            raise ValueError("Original evaluation population mismatch")
        valid, failures = {}, []
        for tid, task in tasks.items():
            record = by_task[tid]
            if record.get("method") != run["condition"] or record.get("rewrite_model") != run["model"]:
                raise ValueError("Original evaluation model/condition mismatch")
            if not record.get("metric_eligible"):
                failures.append({"task_id": tid, "reason": record.get("ineligible_reason")})
                continue
            directory = rm.parent / "tasks" / tid
            refs = {name: reference(directory / name) for name in
                    ("task.json", "phase_status.json", "transfer_plan.json", "rewritten_scenes.json")}
            rt, status, transfer = [read_json(checked(refs[name])) for name in
                                    ("task.json", "phase_status.json", "transfer_plan.json")]
            identity = ("task_id", "base_interval_id", "source_film_id", "reference_film_id", "source_scene_ids", "reference_scene_ids", "selected_features")
            if any(rt.get(k) != task.get(k) for k in identity):
                raise ValueError("Frozen rewrite task identity mismatch")
            if status.get("rewrite_completed") is not True or status.get("source_scene_ids") != task["source_scene_ids"]:
                raise ValueError("Frozen successful rewrite status mismatch")
            if transfer.get("source_scene_ids") != task["source_scene_ids"] or transfer.get("reference_scene_ids") != task["reference_scene_ids"]:
                raise ValueError("Frozen alignment window mismatch")
            rows = read_json(checked(refs["rewritten_scenes.json"]))["rewritten_scenes"]
            if [row.get("scene_id") for row in rows] != task["source_scene_ids"] or any(not str(row.get("content", "")).strip() for row in rows):
                raise ValueError("Rewrite scene identity/order/text mismatch")
            valid[tid] = {"rows": rows, "refs": refs}
        key = (run["display_model"], run["condition"])
        if key in runs:
            raise ValueError("Duplicate model/condition run")
        runs[key] = {"run": run, "valid": valid, "failures": failures}
    return {"tasks": tasks, "scenes": scenes, "runs": runs, "generation_measurement": fs["measurement"]}


def scene_record(contract: dict, catalog: dict, task: dict, role: str, index: int,
                 rewrite_model: str = "Gemma-3-12B") -> dict:
    rewritten = role in {"DP-v1", "CG-v1"}
    fid = task["source_film_id" if rewritten else role + "_film_id"]
    sid = task["source_scene_ids" if rewritten else role + "_scene_ids"][index]
    if rewritten:
        run = catalog["runs"][(rewrite_model, role)]
        data = run["valid"][task["task_id"]]
        row = data["rows"][index]
        pointer = data["refs"]["rewritten_scenes.json"]
        title, text = str(row.get("title") or ""), str(row["content"])
        lineage = {"rewrite_model": rewrite_model, "condition": role, "task_id": task["task_id"],
                   "rewrite_manifest": run["run"]["rewrite_manifest"], "task_artifacts": data["refs"]}
        kind = "rewritten"
    else:
        row = catalog["scenes"][fid][sid]
        pointer = contract["films"][fid]["script"]
        title, text = row["title"], row["text"]
        lineage = {"film_measurement_manifest": contract["films"][fid]["measurement_manifest"]}
        kind = "original"
    record = {"kind": kind, "film_id": fid, "scene_id": sid, "input_artifact": pointer,
              "title_sha256": sha256_bytes(title.encode()), "text_sha256": sha256_bytes(text.encode()),
              "lineage": lineage}
    record["input_id"] = sha256_json(record)
    record["links"] = [{"task_id": task["task_id"], "base_interval_id": task["base_interval_id"],
                        "selected_features": task["selected_features"], "role": role, "position": index}]
    return record


def select_smoke(contract: dict, catalog: dict) -> dict:
    """First successful task, then first new film/base/feature; endpoints only."""
    selected, films, bases, features = [], set(), set(), set()
    for tid, task in sorted(catalog["tasks"].items()):
        if any(tid not in catalog["runs"][("Gemma-3-12B", c)]["valid"] for c in ("DP-v1", "CG-v1")):
            continue
        if selected and (task["source_film_id"] in films or task["base_interval_id"] in bases or tuple(task["selected_features"]) in features):
            continue
        selected.append(task); films.add(task["source_film_id"]); bases.add(task["base_interval_id"]); features.add(tuple(task["selected_features"]))
        if len(selected) == 2:
            break
    if len(selected) != 2:
        raise ValueError("Representative matched qualification population unavailable")
    records = {}
    for task in selected:
        for endpoint in (0, -1):
            for role in ("source", "reference", "DP-v1", "CG-v1"):
                count = len(task["reference_scene_ids"] if role == "reference" else task["source_scene_ids"])
                record = scene_record(contract, catalog, task, role, 0 if endpoint == 0 else count - 1)
                if record["input_id"] in records:
                    records[record["input_id"]]["links"].extend(record["links"])
                else:
                    records[record["input_id"]] = record
    return {"contract_id": "storygen.e01a-smoke-selection", "contract_version": "1.0",
            "selection_rule": "lexicographic-first-valid; second distinct source film/base/feature; first and last matched positions",
            "task_ids": [t["task_id"] for t in selected], "base_interval_ids": sorted(bases),
            "selected_before_inference": True, "max_real_requests": 40, "records": list(records.values())}


def resolve_scene(record: dict) -> tuple[str, str]:
    path = checked(record["input_artifact"])
    if record["kind"] == "original":
        _, rows = load_script(path)
        rows = [r for r in rows if r["scene_id"] == record["scene_id"]]
        title, text = (rows[0]["title"], rows[0]["text"]) if len(rows) == 1 else (None, None)
    elif record["kind"] == "rewritten":
        rows = [r for r in read_json(path)["rewritten_scenes"] if r["scene_id"] == record["scene_id"]]
        title, text = (str(rows[0].get("title") or ""), str(rows[0]["content"])) if len(rows) == 1 else (None, None)
    else:
        raise ValueError("Invalid scene source type")
    if text is None or sha256_bytes(title.encode()) != record["title_sha256"] or sha256_bytes(text.encode()) != record["text_sha256"]:
        raise ValueError("Selected scene identity/content mismatch")
    return title, text


def validate_selection(contract: dict, selection: dict, catalog: dict) -> None:
    expected = select_smoke(contract, catalog)
    if selection != expected:
        raise ValueError("Smoke selection does not match the frozen deterministic task linkage")
    if not 0 < len(selection["records"]) <= 20 or selection["max_real_requests"] != 40:
        raise ValueError("E01A bounded selection required")
    for record in selection["records"]:
        resolve_scene(record)


def duration(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600); m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def validate_cached_row(row: dict, *, protocol: MeasurementProtocol, record: dict, request_hash: str) -> None:
    assert_measurement_equal(protocol.manifest(), row["measurement"], label="independent cache")
    if row["measurement"] != protocol.manifest():
        raise ValueError("Cached measurement manifest has inconsistent identity fields")
    if row["input"] != record or row["request_payload_sha256"] != request_hash or row["status"] != "measured":
        raise ValueError("Stale/incompatible scene cache")
    if StrictIndependentScorer(protocol, use_cache=False)._parse(row["response_text"]) != row["features"]:
        raise ValueError("Cached features differ from validated raw response")


def run_smoke(*, core: Path, profile: Path, input_contract: Path, selection_path: Path,
              output: Path, dry_run=False, execute_inference=False, resume=False) -> dict:
    # Inference always requires explicit authorization, even for Python callers.
    dry_run = dry_run or not execute_inference
    protocol = load_profile(core, profile, require_bound=not dry_run)
    contract, selection = read_json(input_contract), read_json(selection_path)
    catalog = load_catalog(contract); validate_selection(contract, selection, catalog)
    binding = {"measurement": protocol.manifest(), "profile": reference(protocol.config_path),
               "inputs": reference(input_contract), "selection": reference(selection_path),
               "implementation": [reference(Path(__file__)), reference(Path(__file__).with_name("precision.py")),
                    reference(Path(__file__).with_name("io.py")),
                    *[reference(core / "src/storygen_measurement_core" / name)
                      for name in ("protocol.py", "scorer.py", "client.py")]]}
    if dry_run:
        return {"status": "DRY_RUN_VALIDATED", "real_requests": 0, "unique_scenes": len(selection["records"]),
                "maximum_requests_with_schema_retry": 2 * len(selection["records"]), "binding": binding}
    # Validate every prerequisite before creating an output or making a request.
    precision = verify_checkpoint(protocol)
    runtime = verify_live_runtime(protocol)
    if output.exists() and not resume:
        raise FileExistsError("Output exists; --resume is required, no overwrite is supported")
    if resume and output.exists() and read_json(output / "execution_binding.json") != binding:
        raise ValueError("Stale/incompatible resume binding")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "execution_binding.json", binding)
    write_json(output / "precision_verification.json", precision)
    write_json(output / "runtime_identity.json", runtime)
    scorer = StrictIndependentScorer(protocol, use_cache=False)
    completed = successes = failures = calls = cached = 0
    started = time.monotonic(); results = []
    prior_path = output / "request_ledger.json"
    ledger = read_json(prior_path) if prior_path.exists() else []
    if ledger and not resume:
        raise ValueError("Existing request ledger requires resume")
    calls = len(ledger)
    if calls > 40:
        raise ValueError("Historical ledger exceeds the bounded request budget")

    def progress(current):
        elapsed = time.monotonic() - started
        rate = (completed - cached) / elapsed if completed > cached and elapsed > 0 else 0
        eta = duration((len(selection["records"]) - completed) / rate) if rate else "unavailable"
        row = {"total_requests": len(selection["records"]), "maximum_real_requests": 40,
               "completed": completed, "successful": successes, "failed": failures,
               "real_requests": calls, "cache_hits": cached, "current": current,
               "elapsed": duration(elapsed), "eta": eta, "throughput_scenes_per_second": rate}
        write_json(output / "progress.json", row)
        print(json.dumps(row), file=sys.stderr, flush=True)

    with httpx.Client(timeout=180) as client:
        base = protocol.model["base_url"].removesuffix("/v1")
        # Template and token budget checks use no generation. Check all scenes
        # before the first generation; no truncation or changed system prompt.
        payloads = {}
        for record in selection["records"]:
            title, text = resolve_scene(record)
            prompt = scorer._render(record["film_id"], record["scene_id"], title, text)
            payload = build_request_payload(prompt=prompt, model=protocol.model["alias"], schema=protocol.schema,
                      decoding=protocol.decoding, system_instruction=protocol.system_instruction,
                      response_schema_name=protocol.response_schema_name)
            target = output / "records" / (record["input_id"].split(":")[1] + ".json")
            if target.exists():
                validate_cached_row(read_json(target), protocol=protocol, record=record, request_hash=sha256_json(payload))
            formatted = client.post(base + "/apply-template", json={"messages": payload["messages"]})
            formatted.raise_for_status()
            tokenized = client.post(base + "/tokenize", json={"content": formatted.json()["prompt"], "add_special": True})
            tokenized.raise_for_status()
            count = len(tokenized.json()["tokens"])
            if count + 256 > protocol.config["runtime"]["context_size"]:
                raise ValueError("Context incompatibility: complete scene plus output does not fit; no truncation permitted")
            payloads[record["input_id"]] = (payload, count)
        progress("preflight complete")
        for record in selection["records"]:
            target = output / "records" / (record["input_id"].split(":")[1] + ".json")
            payload, input_tokens = payloads[record["input_id"]]
            request_hash = sha256_json(payload)
            if target.exists():
                row = read_json(target)
                validate_cached_row(row, protocol=protocol, record=record, request_hash=request_hash)
                results.append(row); completed += 1; successes += 1; cached += 1
                progress(record["input_id"]); continue
            prior_attempts = [entry for entry in ledger if entry["input_id"] == record["input_id"]]
            if prior_attempts:
                raise ValueError("Interrupted/failed request has no validated cache; preserve evidence and stop")
            row = {"input": record, "measurement": protocol.manifest(), "request_payload_sha256": request_hash,
                   "input_tokens_preflight": input_tokens, "attempts": [], "features": None,
                   "status": "measurement_ineligible", "heuristic_fallback_used": False}
            for attempt in range(2):
                if calls >= 40:
                    raise ValueError("Hard cumulative 40-request limit reached")
                calls += 1
                reservation = {"input_id": record["input_id"], "attempt": attempt + 1, "state": "reserved_before_request"}
                ledger.append(reservation); write_json(prior_path, ledger)
                progress(record["input_id"] + f" request attempt {attempt + 1}")
                request_started = time.monotonic(); error = None; category = None
                raw = None; usage = None
                try:
                    response = client.post(protocol.model["base_url"] + "/chat/completions", json=payload)
                    response.raise_for_status(); data = response.json()
                    raw = data["choices"][0]["message"]["content"]
                    row["response_text"] = raw
                    usage = data.get("usage"); row["usage"] = usage
                    try:
                        row["features"] = scorer._parse(raw)
                        if data["choices"][0].get("finish_reason") == "length":
                            raise ValueError("Output token limit reached")
                        row["status"] = "measured"
                    except (ValueError, TypeError) as exc:
                        row["features"] = None
                        category = "schema_invalid"; error = type(exc).__name__
                except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                    category = "runtime_or_api_failure"; error = type(exc).__name__
                elapsed = time.monotonic() - request_started
                detail = {"attempt": attempt + 1, "elapsed_seconds": elapsed, "category": category,
                          "error_class": error, "valid": row["status"] == "measured", "usage": usage,
                          "response_text": raw, "request_payload_sha256": request_hash}
                row["attempts"].append(detail); reservation.update(state="completed", **detail)
                write_json(prior_path, ledger)
                if row["status"] == "measured" or category == "runtime_or_api_failure":
                    break
                progress(record["input_id"] + " schema retry pending")
            row["retry_count"] = len(row["attempts"]) - 1
            write_json(target, row); results.append(row); completed += 1
            if row["status"] == "measured":
                successes += 1
            else:
                failures += 1
            progress(record["input_id"])
            if failures:
                break
    manifest = {"contract_id": "storygen.independent-audit-feature-set", "contract_version": "1.0",
                "feature_set_id": "e01a_" + protocol.protocol_hash.split(":")[1][:16], "scope": "qualification_sample_only",
                "measurement": protocol.manifest(), "generation_measurement": catalog["generation_measurement"],
                "binding": binding, "runtime": runtime, "source_types": ["original_source", "original_reference", "rewritten"],
                "scene_count": len(selection["records"]), "completed": completed, "successes": successes,
                "failures": failures, "real_requests": calls, "cache_hits": cached,
                "valid_real_requests": sum(bool(entry.get("valid")) for entry in ledger),
                "records": [reference(output / "records" / (r["input"]["input_id"].split(":")[1] + ".json")) for r in results],
                "qualified": completed == successes == len(selection["records"]) and failures == 0}
    write_json(output / "feature_set_manifest.json", manifest)
    if not manifest["qualified"]:
        raise RuntimeError("Smoke failed; evidence retained and execution stopped")
    return manifest


def validate_results(output: Path, core: Path) -> dict:
    """Validate a small completed FeatureSet from frozen pointers, offline."""
    manifest = read_json(output / "feature_set_manifest.json")
    if manifest.get("contract_id") != "storygen.independent-audit-feature-set" or manifest.get("contract_version") != "1.0" or manifest.get("scope") != "qualification_sample_only":
        raise ValueError("Bounded independent qualification FeatureSet required")
    binding = read_json(output / "execution_binding.json")
    if manifest.get("binding") != binding:
        raise ValueError("FeatureSet execution binding mismatch")
    for ref in binding["implementation"]:
        checked(ref)
    protocol = load_profile(core, checked(binding["profile"]), require_bound=True)
    if binding["measurement"] != protocol.manifest() or manifest["measurement"] != protocol.manifest():
        raise ValueError("FeatureSet model/protocol identity mismatch")
    checked(binding["inputs"])
    selection = read_json(checked(binding["selection"]))
    expected = {r["input_id"]: r for r in selection["records"]}
    if not 0 < len(expected) <= 20:
        raise ValueError("Invalid qualification scene population")
    seen = set()
    scorer = StrictIndependentScorer(protocol, use_cache=False)
    for ref in manifest["records"]:
        row = read_json(checked(ref)); record = row["input"]
        if record["input_id"] not in expected or record["input_id"] in seen:
            raise ValueError("Missing/duplicate/relinked measurement")
        title, text = resolve_scene(expected[record["input_id"]])
        payload = build_request_payload(prompt=scorer._render(record["film_id"], record["scene_id"], title, text),
                  model=protocol.model["alias"], schema=protocol.schema, decoding=protocol.decoding,
                  system_instruction=protocol.system_instruction, response_schema_name=protocol.response_schema_name)
        validate_cached_row(row, protocol=protocol, record=expected[record["input_id"]], request_hash=sha256_json(payload))
        seen.add(record["input_id"])
    ledger = read_json(output / "request_ledger.json")
    if len(ledger) > 40 or manifest["real_requests"] != len(ledger):
        raise ValueError("Request accounting/budget mismatch")
    if not manifest.get("qualified") or seen != set(expected) or manifest["successes"] != len(seen) or manifest["failures"] != 0:
        raise ValueError("Incomplete qualification FeatureSet")
    return {"valid": True, "scene_count": len(seen), "real_requests": len(ledger),
            "model_sha256": protocol.model["model_sha256"], "protocol_hash": protocol.protocol_hash,
            "scope": "bounded_feature_set_validation_only", "new_inference_requests": 0}
