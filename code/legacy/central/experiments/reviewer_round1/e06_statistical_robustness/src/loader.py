"""Explicit hash-bound historical loader; preflight never computes outcomes."""

from pathlib import Path
import math
import json
import re
from common import CONDITIONS, FEATURES, Dataset, index, read, sha, words
from storygen_evaluation.metrics import evaluate_task, mae, directional_accuracy, signum
from storygen_evaluation.provenance import ArtifactResolver, same_provenance, _resample


class Inputs:
    def __init__(self, binding):
        self.binding_path = Path(binding).resolve()
        self.binding = read(self.binding_path)
        if self.binding.get("contract") != "storygen.e06.binding/1.0":
            raise ValueError("E06 binding contract required")
        self.files = {str(self.binding_path): sha(self.binding_path)}
        self.absent = set()
        self.resolver = ArtifactResolver()
        overrides = self.bound(self.binding["artifact_overrides"])
        self.resolver = ArtifactResolver(self.get(overrides))
        for path in self.resolver.overrides.values():
            self.track(path)

    def track(self, path):
        path = Path(path).resolve()
        if path.is_file():
            digest = sha(path)
            if str(path) in self.files and self.files[str(path)] != digest:
                raise ValueError("Input changed during read: " + str(path))
            self.files[str(path)] = digest
        else:
            self.absent.add(str(path))
        return path

    def get(self, path):
        return read(self.track(path))

    def bound(self, ref):
        path = self.resolver.file(ref["path"], ref["sha256"])
        return self.track(path)

    def unchanged(self):
        return all(
            Path(p).is_file() and sha(p) == h for p, h in self.files.items()
        ) and all(not Path(p).exists() for p in self.absent)


def preflight(binding, progress=lambda *args: None):
    """Metadata, hashes, IDs and artifact existence only. No metric replay."""
    inputs = Inputs(binding)
    b = inputs.binding
    kind = b.get("dataset_kind")
    if kind not in ("REAL", "SYNTHETIC"):
        raise ValueError("Explicit REAL or SYNTHETIC input identity required")
    if kind == "REAL":
        authority = read(Path(__file__).parents[1] / "historical_binding.json")
        for key in ("taskset", "reference_feature_set"):
            if b[key]["sha256"] != authority[key]["sha256"]:
                raise ValueError(
                    "Real E06 requires the frozen historical input identities"
                )
        if b["models"] != authority["models"] or b["expected"] != authority["expected"]:
            raise ValueError("Real benchmark population/expectation drift")
        original = {(r["model"], r["condition"]): r for r in authority["runs"]}
        for r in b["runs"]:
            locked = original.get((r["model"], r["condition"]), {})
            for key in (
                "evaluation_manifest",
                "records",
                "rewrite_manifest",
                "reanalysis_manifest",
            ):
                if r[key]["sha256"] != locked.get(key, {}).get("sha256"):
                    raise ValueError("Unapproved historical observation binding")
    task_path = inputs.bound(b["taskset"])
    fs_path = inputs.bound(b["reference_feature_set"])
    runtime, _fs = inputs.get(task_path), inputs.get(fs_path)
    tasks = runtime["tasks"]
    index(tasks)
    if len(tasks) != b["expected"]["tasks"]:
        raise ValueError("Frozen task count discrepancy")
    expected_pairs = {(m, c) for m in b["models"] for c in CONDITIONS}
    if (
        len(b["runs"]) != len(expected_pairs)
        or {(r["model"], r["condition"]) for r in b["runs"]} != expected_pairs
    ):
        raise ValueError("Incomplete or duplicate model-condition bindings")
    inventory = []
    missing = []
    for i, run in enumerate(b["runs"], 1):
        paths = {
            k: inputs.bound(run[k])
            for k in (
                "evaluation_manifest",
                "records",
                "rewrite_manifest",
                "reanalysis_manifest",
            )
        }
        manifest = inputs.get(paths["evaluation_manifest"])
        if (
            manifest.get("rewrite_model") != run["model"]
            or manifest.get("method") != run["condition"]
        ):
            raise ValueError("Model-condition provenance contradiction")
        ra = inputs.get(paths["reanalysis_manifest"])
        rw = inputs.get(paths["rewrite_manifest"])
        # Snapshot every manifest/runtime reference the canonical lineage validator
        # may read. Deliberately exclude server/model/checkpoint references.
        for document in (manifest, ra, rw):
            for key in (
                "taskset",
                "feature_set_manifest",
                "reference_feature_set_manifest",
                "source_feature_set_manifest",
                "source_rewrite_run",
                "reanalysis_run",
            ):
                reference = document.get(key)
                if reference:
                    filename = {
                        "source_rewrite_run": "rewrite_run_manifest.json",
                        "reanalysis_run": "reanalysis_manifest.json",
                    }.get(key)
                    inputs.track(inputs.resolver.reference(reference, filename))
        if manifest["reanalysis_run"]["manifest_sha256"] != sha(
            paths["reanalysis_manifest"]
        ) or ra["source_rewrite_run"]["manifest_sha256"] != sha(
            paths["rewrite_manifest"]
        ):
            raise ValueError("Bound evaluation/reanalysis/rewrite lineage mismatch")
        inventory.append(
            dict(
                model=run["model"],
                condition=run["condition"],
                **{k: str(v) for k, v in paths.items()},
            )
        )
        progress("preflight", "P00", i, len(b["runs"]))
    # Discover all files the canonical validator/evaluator and text diagnostic read.
    for film in sorted(
        {t[f"{s}_film_id"] for t in tasks for s in ("source", "reference")}
    ):
        for name in ("scene_features_llm.json", "measurement_manifest.json"):
            p = inputs.track(fs_path.parent / "films" / film / name)
            if not p.is_file():
                missing.append(str(p))
    source_scripts = set()
    for t in tasks:
        p = Path(
            inputs.resolver.overrides.get(
                t["source_script_path"], t["source_script_path"]
            )
        )
        inputs.track(p)
        source_scripts.add(str(p.resolve()))
        for side in ("source", "reference"):
            recorded = t[f"{side}_feature_path"]
            inputs.track(inputs.resolver.overrides.get(recorded, recorded))
    for run, row in zip(b["runs"], inventory):
        rw = Path(row["rewrite_manifest"]).parent
        ra = Path(row["reanalysis_manifest"]).parent
        for t in tasks:
            for root, names in (
                (
                    ra,
                    (
                        "transfer_plan.json",
                        "rewritten_scenes.json",
                        "rewritten_scene_features.json",
                        "measurement_status.json",
                        "reanalysis_failure.json",
                    ),
                ),
                (
                    rw,
                    (
                        "transfer_plan.json",
                        "rewritten_scenes.json",
                        "rewrite_failure.json",
                        "phase_status.json",
                        "rewrite_request.json",
                    ),
                ),
            ):
                for name in names:
                    inputs.track(root / "tasks" / t["task_id"] / name)
            for sid in t["source_scene_ids"]:
                inputs.track(
                    rw
                    / "tasks"
                    / t["task_id"]
                    / "per_scene"
                    / sid
                    / "rewrite_request.json"
                )
    missing_scripts = sorted(p for p in source_scripts if not Path(p).is_file())
    return inputs, dict(
        status="MISSING_INPUT" if missing else "PREFLIGHT_READY",
        missing=missing,
        modules={
            m: "REAL_COMPATIBILITY_UNVERIFIED"
            for m in ("A01", "A02", "A03", "A04", "A05", "A06", "A07")
        },
        taskset=str(task_path),
        reference_feature_set=str(fs_path),
        runs=inventory,
        scientific_results="NOT_COMPUTED",
        dataset_kind=kind,
        source_scripts=sorted(source_scripts),
        missing_source_scripts=missing_scripts,
        length_input_availability="MISSING_INPUT"
        if missing_scripts
        else "CANDIDATES_LOCATED_ALIGNMENT_UNVERIFIED",
        input_files=len(inputs.files),
        note="Missing optional per-task artifacts may be historical failures; eligibility is determined only during human execution.",
    )


def source_index(raw):
    rows = raw.get("scenes") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("Unsupported source script")
    result = {}
    for row in rows:
        value = row.get("scene_id", row.get("_id", row.get("id")))
        if isinstance(value, int) and not isinstance(value, bool):
            sid = f"scene_{value + 1:03d}"  # frozen Feature IO zero-based integer _id
        elif isinstance(value, str) and re.fullmatch(r"scene_\d+", value.strip()):
            sid = f"scene_{int(value.strip().split('_')[-1]):03d}"
        elif isinstance(value, str) and value.isdigit():
            sid = f"scene_{int(value):03d}"
        elif isinstance(value, str) and value.strip():
            sid = value.strip()
        else:
            raise ValueError("Source scene has no authoritative ID")
        if sid in result:
            raise ValueError("Duplicate source scene ID")
        text = row.get("text") or row.get("content") or row.get("body")
        result[sid] = text.strip() if isinstance(text, str) else None
    return result


def text_pairs(task, rwroot, original, inputs, model=None, condition=None):
    """Count privately; never return screenplay content. Keep both denominators."""
    path = rwroot / "rewritten_scenes.json"
    try:
        rewritten = index(inputs.get(path)["rewritten_scenes"], "scene_id")
    except FileNotFoundError:
        rewritten = {}
    if set(rewritten) - set(task["scene_ids"]):
        raise ValueError("Unexpected rewrite scene identity")
    result = []
    for pos, sid in enumerate(task["scene_ids"]):
        full = original.get(sid) if original else None
        after = rewritten.get(sid, {}).get("content")
        request = rwroot / "per_scene" / sid / "rewrite_request.json"
        presented, truncation, request_status = None, None, "MISSING_REQUEST"
        if request.is_file():
            raw = inputs.get(request)
            if raw.get("expected_scene_id") != sid:
                raise ValueError("Request scene identity mismatch")
            if model is not None and raw.get("model") != model:
                raise ValueError("Request model identity mismatch")
            strategy = {"DP-v1": "direct_prompt", "CG-v1": "curve_guided"}.get(
                condition
            )
            if strategy is not None and raw.get("prompt_strategy") != strategy:
                raise ValueError("Request prompting condition mismatch")
            try:
                prompt = json.loads(raw["user_instruction"])
                scene = prompt["source_scene"]
                if (
                    scene["scene_id"] != sid
                    or prompt["source_interval_scene_ids"] != task["scene_ids"]
                ):
                    raise ValueError("Presented source scene/task identity mismatch")
                if prompt.get("source_film_id") != task["screenplay_id"]:
                    raise ValueError("Presented source screenplay mismatch")
                presented = scene["content"]
                truncation = scene["was_truncated"]
                if not isinstance(presented, str) or not isinstance(truncation, bool):
                    raise ValueError("Invalid source request content contract")
                if full is not None and not truncation and presented != full:
                    raise ValueError("Untruncated source text differs from archive")
                request_status = "VERIFIED_REQUEST"
            except (KeyError, json.JSONDecodeError):
                request_status = "UNSUPPORTED_REQUEST"
        for basis, before in (
            ("full_archived_source", full),
            ("model_presented_source", presented),
        ):
            sw, aw = words(before), words(after)
            status = (
                "VALID"
                if sw is not None and sw > 0 and aw is not None and aw > 0
                else (
                    "ZERO_SOURCE"
                    if sw == 0
                    else "EMPTY_REWRITE"
                    if aw == 0
                    else "MISSING_TEXT"
                )
            )
            result.append(
                dict(
                    scene_id=sid,
                    scene_position=pos,
                    source_basis=basis,
                    source_words=sw,
                    rewrite_words=aw,
                    length_ratio=aw / sw if status == "VALID" else None,
                    status=status,
                    was_truncated=truncation,
                    request_status=request_status,
                    source_text_reference=task["source_text_reference"],
                    rewritten_text_reference=str(path),
                    request_reference=str(request),
                )
            )
    return result


def failure_category(frozen, rwroot, raroot):
    if frozen and frozen["metric_eligible"]:
        return "successful_and_measured"
    reason = str((frozen or {}).get("ineligible_reason") or "")
    if (rwroot / "rewrite_failure.json").exists() or "missing_rewrite_task" in reason:
        return "generation_failure"
    if (raroot / "reanalysis_failure.json").exists() or reason.startswith(
        "reanalysis:"
    ):
        return "measurement_failure"
    if frozen is None or "missing" in reason:
        return "missing_historical_artifact"
    return "invalid_or_incompatible_record"


def finite_curve(values, n):
    if len(values) != n or any(
        isinstance(x, bool)
        or not isinstance(x, (int, float))
        or not math.isfinite(x)
        or not 0 <= x <= 1
        for x in values
    ):
        raise ValueError("Invalid canonical feature curve")
    return values


def load(binding, progress=lambda *args: None):
    inputs, inventory = preflight(binding, progress)
    if inventory["status"] == "MISSING_INPUT":
        raise FileNotFoundError("Required original features unavailable")
    b = inputs.binding
    task_path, fs_path = (
        Path(inventory["taskset"]),
        Path(inventory["reference_feature_set"]),
    )
    raw_tasks, fs = inputs.get(task_path)["tasks"], inputs.get(fs_path)
    manifests = [inputs.get(inputs.bound(r["evaluation_manifest"])) for r in b["runs"]]
    # Reuse frozen source/target, measurement-space, text-copy and cross-run lineage checks.
    same_provenance(manifests, task_path, inputs.resolver.overrides)
    features, scripts = {}, {}
    for film in sorted(
        {t[f"{s}_film_id"] for t in raw_tasks for s in ("source", "reference")}
    ):
        root = fs_path.parent / "films" / film
        features[film] = index(inputs.get(root / "scene_features_llm.json"), "scene_id")
        t = next((t for t in raw_tasks if t["source_film_id"] == film), None)
        if t:
            sp = Path(
                inputs.resolver.overrides.get(
                    t["source_script_path"], t["source_script_path"]
                )
            )
            meta = inputs.get(root / "measurement_manifest.json")
            if sp.is_file():
                expected = meta.get("script_sha256") or meta.get("script_hash")
                if not expected or sha(sp) != expected:
                    raise ValueError("Unverified original script identity")
                scripts[film] = source_index(inputs.get(sp))
            else:
                scripts[film] = None
    tasks = []
    for t in raw_tasks:
        key = t["selected_features"][0]
        feature = next(k for k, v in FEATURES.items() if v == key)
        n = len(t["source_scene_ids"])
        before = finite_curve(
            [features[t["source_film_id"]][sid][key] for sid in t["source_scene_ids"]],
            n,
        )
        target = _resample(
            [
                features[t["reference_film_id"]][sid][key]
                for sid in t["reference_scene_ids"]
            ],
            n,
        )
        tasks.append(
            dict(
                task_id=t["task_id"],
                base_interval_id=t["base_interval_id"],
                screenplay_id=t["source_film_id"],
                reference_screenplay_id=t["reference_film_id"],
                feature=feature,
                interval_length=n,
                scene_ids=t["source_scene_ids"],
                reference_scene_ids=t["reference_scene_ids"],
                reference_feature_values=[
                    features[t["reference_film_id"]][sid][key]
                    for sid in t["reference_scene_ids"]
                ],
                B=before,
                T=target,
                requested_directions=[signum(t - b) for b, t in zip(before, target)],
                source_text_reference=inputs.resolver.overrides.get(
                    t["source_script_path"], t["source_script_path"]
                ),
            )
        )
    tasks = sorted(tasks, key=lambda t: t["task_id"])
    raw_index = index(raw_tasks)
    records = {}
    mismatch = []
    for run in b["runs"]:
        model, condition = run["model"], run["condition"]
        rp = inputs.bound(run["records"])
        frozen = index(
            [json.loads(line) for line in rp.read_text().splitlines() if line.strip()]
        )
        if set(frozen) - set(raw_index):
            raise ValueError("Unplanned historical task record")
        rwroot = inputs.bound(run["rewrite_manifest"]).parent
        raroot = inputs.bound(run["reanalysis_manifest"]).parent
        records[model, condition] = {}
        for i, t in enumerate(tasks, 1):
            tid = t["task_id"]
            raw = raw_index[tid]
            old = frozen.get(tid)
            rw, ra = rwroot / "tasks" / tid, raroot / "tasks" / tid
            if old and (old["rewrite_model"] != model or old["method"] != condition):
                raise ValueError("Historical record model-condition mismatch")
            replay = evaluate_task(raw, ra, fs["measurement"], condition, model)
            if old is None or replay != old:
                mismatch.append(
                    dict(
                        model=model,
                        condition=condition,
                        task_id=tid,
                        reason="missing_record"
                        if old is None
                        else "canonical_replay_mismatch",
                    )
                )
            eligible = bool(old and old["metric_eligible"] and replay == old)
            row = dict(
                t,
                model=model,
                condition=condition,
                eligible=eligible,
                A=None,
                TI=None,
                DA=None,
                dB=None,
                dA=None,
                G=None,
                generation_status="recorded_rewrite"
                if (rw / "rewritten_scenes.json").is_file()
                else "unavailable",
                measurement_status="measured"
                if eligible
                else "unavailable_or_ineligible",
                failure_classification="invalid_or_incompatible_record"
                if old and old["metric_eligible"] and not eligible
                else failure_category(old, rw, ra),
                original_status=(old or {}).get("ineligible_reason"),
                evaluation_records=str(rp),
                text_pairs=text_pairs(
                    t, rw, scripts.get(t["screenplay_id"]), inputs, model, condition
                ),
            )
            if eligible:
                after_rows = index(
                    inputs.get(ra / "rewritten_scene_features.json"), "scene_id"
                )
                after = finite_curve(
                    [
                        after_rows[sid][raw["selected_features"][0]]
                        for sid in t["scene_ids"]
                    ],
                    t["interval_length"],
                )
                # transfer_plan supplies the exact historical numerical precision.
                plan = inputs.get(ra / "transfer_plan.json")
                key = raw["selected_features"][0]
                if (
                    plan["source_current_curve"][key] != t["B"]
                    or plan["resampled_target_curve"][key] != t["T"]
                ):
                    raise ValueError("B/T precision or provenance mismatch")
                db, da = mae(t["B"], t["T"]), mae(after, t["T"])
                if (db, da, da < db, directional_accuracy(t["B"], t["T"], after)) != (
                    old["before_target_mae"],
                    old["after_target_mae"],
                    old["target_improved"],
                    old["directional_accuracy"],
                ):
                    raise ValueError("Canonical numerical reproduction mismatch")
                row.update(
                    A=after,
                    dB=db,
                    dA=da,
                    TI=int(da < db),
                    DA=old["directional_accuracy"],
                    G=db - da,
                )
            records[model, condition][tid] = row
            progress("canonical_load", f"{model}/{condition}", i, len(tasks))
    ds = Dataset(
        tasks,
        records,
        b["models"],
        dict(
            input_files=inputs.files,
            absent_inputs=sorted(inputs.absent),
            resolved_references=inputs.resolver.evidence,
            binding=str(inputs.binding_path),
        ),
        dict(
            replay_mismatches=mismatch,
            expected=b["expected"],
            inputs_unchanged=inputs.unchanged(),
        ),
        b["dataset_kind"],
    )
    return ds, inputs, inventory
