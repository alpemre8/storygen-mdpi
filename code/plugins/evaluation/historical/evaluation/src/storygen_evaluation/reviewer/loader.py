"""Explicit frozen input plan, hash checking, and one text-free canonical view."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
import re

from ..io import read_json, read_jsonl, sha256_file
from ..metrics import evaluate_task, signum
from ..provenance import ArtifactResolver, same_provenance, structure_sha
from . import ANALYZER_VERSION, FEATURES, CONDITIONS, BlockedAnalysis
from .statistics import keyed_vectors, length_ratio

APPROVED_SHA = "sha256:9faa70fab3461aae3b59122eb3b35df43392246a76c48bd2ff37d9471f6ad032"
STRUCTURE_SHA = "sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb"


@dataclass
class Dataset:
    tasks: list[dict]
    records: dict[tuple[str, str], dict[str, dict]]
    pairs: dict[str, list[str]]
    common: list[str]
    models: list[str]
    plan: dict
    provenance: dict
    validation: dict
    approved: dict

    def rows(self, model, condition, ids=None):
        index = self.records[(model, condition)]
        return [index[t] for t in (ids if ids is not None else [t["task_id"] for t in self.tasks])]


def assert_labels(manifest, model, condition):
    if manifest.get("contract_id") != "storygen.evaluation-run" or str(manifest.get("contract_version")) != "2.4":
        raise RuntimeError("Original Evaluation 2.4 manifest required")
    if manifest.get("rewrite_model") != model or manifest.get("method") != condition:
        raise RuntimeError("Wrong model/condition in analysis input")


def normalized_script(raw):
    # Exact existing Feature IO normalization convention, without importing a
    # separate owner or emitting original content. Zero text is handled by A08.
    scenes = raw.get("scenes") if isinstance(raw, dict) else raw
    if not isinstance(scenes, list):
        raise BlockedAnalysis("Unsupported original script shape")
    result = {}
    for i, row in enumerate(scenes, 1):
        value = row.get("scene_id", row.get("_id", row.get("id")))
        if isinstance(value, str):
            value = value.strip()
            match = re.search(r"(\d+)$", value)
            sid = f"scene_{int(match.group(1)):03d}" if value.startswith("scene_") and match else f"scene_{int(value):03d}" if value.isdigit() else value or f"scene_{i:03d}"
        elif isinstance(value, int):
            sid = f"scene_{value + 1:03d}"
        else:
            sid = f"scene_{i:03d}"
        if sid in result:
            raise RuntimeError("Duplicate normalized original scene ID")
        result[sid] = str(row.get("text") or row.get("content") or row.get("body") or "").strip()
    return result


def failure_classification(failure):
    """Categorize recorded error wording, without exporting response content."""
    message = str(failure.get("error") or "").lower()
    categories = (("plan_like", "reported_plan_like_output"),
                  ("plan-like", "reported_plan_like_output"),
                  ("empty", "reported_empty_output"),
                  ("json", "reported_json_parse_or_schema_error"),
                  ("scene_coverage", "reported_scene_coverage_error"),
                  ("scene id", "reported_scene_identity_error"),
                  ("timeout", "reported_timeout"))
    category = next((label for marker,label in categories if marker in message), "other_recorded_rewrite_error")
    scene = re.search(r"scene_\d+",message)
    return dict(root_cause_type=failure.get("root_cause_type"),stage=failure.get("stage"),
                reported_error_category=category,reported_failed_scene_id=scene.group(0) if scene else None)


def load_dataset(plan_path: Path, artifact_paths=None) -> Dataset:
    plan = read_json(plan_path)
    if plan.get("contract") != "storygen.reviewer-analysis-plan/1.0" or plan.get("analyzer_version") != ANALYZER_VERSION:
        raise RuntimeError("Unknown frozen reviewer plan")
    settings = plan.get("diagnostic_settings")
    if settings != dict(resamples=10000, seed=42, confidence=.95, rng="numpy.random.default_rng/PCG64",
                        percentile="linear", epsilon=[0, .01, .05, .1], tau=[0, .05, .1, .2],
                        endpoint_atol=1e-12, min_clusters=2):
        raise RuntimeError("Reviewer protocol settings drift")
    resolver = ArtifactResolver(artifact_paths)
    files = {}
    def track(path):
        path = Path(path).resolve()
        if path.is_file() and str(path) not in files:
            files[str(path)] = sha256_file(path)
        return path
    def read(path):
        return read_json(track(path))
    def bound(ref):
        return track(resolver.reference(ref))
    approved_path = bound(plan["approved_a6_protocol"])
    if sha256_file(approved_path) != APPROVED_SHA:
        raise RuntimeError("Author-approved A6 protocol bytes changed")
    approved = read(approved_path)
    for source in approved["implementation"]["source_files"]:
        path = approved_path.parents[2] / source["repository_relative_path"]
        if sha256_file(path) != source["sha256"]:
            raise RuntimeError("Frozen Evaluation implementation changed")
    gate = read(bound(plan["p01a_gate"]))
    if gate.get("status") != "PASS" or gate.get("historical_execution_provenance") != "UNVERIFIED":
        raise RuntimeError("P01A PASS/historical provenance prerequisite failed")
    for key in ("p00_facts", "specification", "artifact_overrides", "reviewer_letter", "manuscript_text_control"):
        bound(plan[key])
    runtime_path, fs_path = bound(plan["taskset"]), bound(plan["reference_feature_set"])
    if sha256_file(runtime_path) != approved["taskset"]["sha256"]:
        raise RuntimeError("Nonfrozen taskset supplied")
    if sha256_file(fs_path) != approved["reference_feature_set"]["manifest_sha256"]:
        raise RuntimeError("Nonfrozen original FeatureSet supplied")
    runtime, fs = read(runtime_path), read(fs_path)
    tasks = runtime["tasks"]
    if len(tasks) != 240 or structure_sha(tasks) != STRUCTURE_SHA:
        raise RuntimeError("TasksetV5 structure/count contradiction")
    manifests = []
    models = [m["model_id"] for m in approved["models"]]
    if len(plan["runs"]) != 8 or {(r["model"], r["condition"]) for r in plan["runs"]} != {(m, c) for m in models for c in CONDITIONS}:
        raise RuntimeError("Exactly the original eight conditions are required")
    for run in plan["runs"]:
        manifest = read(bound(run["evaluation_manifest"]))
        assert_labels(manifest, run["model"], run["condition"])
        frozen = next(s for s in approved["evaluation_sources"] if (s["model"], s["method"]) == (run["model"], run["condition"]))
        if run["evaluation_manifest"]["sha256"] != frozen["manifest_sha256"] or run["records"]["sha256"] != frozen["records_sha256"]:
            raise RuntimeError("Original evaluation input hash contradiction")
        bound(run["records"])
        bound(run["rewrite_manifest"])
        bound(run["reanalysis_manifest"])
        if manifest["reanalysis_run"]["manifest_sha256"] != run["reanalysis_manifest"]["sha256"]:
            raise RuntimeError("Evaluation/reanalysis plan lineage mismatch")
        reanalysis = read(bound(run["reanalysis_manifest"]))
        if reanalysis["source_rewrite_run"]["manifest_sha256"] != run["rewrite_manifest"]["sha256"]:
            raise RuntimeError("Reanalysis/rewrite plan lineage mismatch")
        manifests.append(manifest)
    # Reuse repaired deep provenance, full B/T lineage and text-copy validation.
    same_provenance(manifests, runtime_path, artifact_paths)
    films = sorted({t[f"{side}_film_id"] for t in tasks for side in ("source", "reference")})
    source_rows, original_text, script_paths = {}, {}, {}
    optional_blockers = []
    scene_n = 0
    for film in films:
        root = fs_path.parent / "films" / film
        rows = read(root / "scene_features_llm.json")
        ids = [r["scene_id"] for r in rows]
        vectors = keyed_vectors(rows, ids, str(root / "scene_features_llm.json"))
        if len(set(ids)) != len(ids) or any(r["measurement_status"] != "measured" for r in rows):
            raise RuntimeError("Original feature scene identity/status contradiction")
        source_rows[film] = dict(zip(ids, vectors))
        scene_n += len(ids)
        status = read(root / "measurement_manifest.json")
        task = next(t for t in tasks if t["source_film_id"] == film)
        script = Path(resolver.overrides.get(task["source_script_path"],task["source_script_path"])).expanduser().resolve()
        script_paths[film] = str(script)
        if not script.is_file():
            original_text[film] = None
            optional_blockers.append(f"A08 missing original script: {script}")
        else:
            script = resolver.file(task["source_script_path"], status["script_sha256"])
            original_text[film] = normalized_script(read(script))
            if list(original_text[film]) != ids:
                raise RuntimeError("Original text/measurement scene order contradiction")
    if len(films) != 10 or scene_n != 938:
        raise RuntimeError("Frozen corpus size contradiction")
    canonical_tasks, task_index = [], {}
    for task in tasks:
        ids = task["source_scene_ids"]
        feature = next(f for f, k in FEATURES.items() if k == task["selected_features"][0])
        if len(ids) not in (5, 8, 12) or len(ids) != len(task["reference_scene_ids"]):
            raise RuntimeError("Frozen interval length contradiction")
        source = [source_rows[task["source_film_id"]][sid] for sid in ids]
        target = [source_rows[task["reference_film_id"]][sid][feature] for sid in task["reference_scene_ids"]]
        public = {k: task[k] for k in ("task_id", "base_interval_id", "source_film_id", "reference_film_id", "source_scene_ids", "reference_scene_ids")}
        public.update(selected_feature=feature, interval_length=len(ids), B=[v[feature] for v in source],
                      T=target, source_five=source, original_text_pointer=script_paths[task["source_film_id"]])
        canonical_tasks.append(public)
        task_index[task["task_id"]] = public
    records, exact_count, measured_count, after_n = {}, 0, 0, 0
    after_off_grid = []
    for run, manifest in zip(plan["runs"], manifests):
        model, condition = run["model"], run["condition"]
        ra_path = bound(run["reanalysis_manifest"])
        rw_path = bound(run["rewrite_manifest"])
        ra = read(ra_path)
        rows = read_jsonl(bound(run["records"]))
        if [r["task_id"] for r in rows] != [t["task_id"] for t in tasks]:
            raise RuntimeError("Original evaluation record IDs/order contradiction")
        records[(model, condition)] = {}
        for task, frozen_record in zip(tasks, rows):
            tid = task["task_id"]
            root, rwroot = ra_path.parent / "tasks" / tid, rw_path.parent / "tasks" / tid
            replay = evaluate_task(task, root, fs["measurement"], condition, model)
            if replay != frozen_record:
                raise RuntimeError(f"Original scientific record changed on replay: {model} {condition} {tid}")
            exact_count += 1
            plan_data = read(rwroot / "transfer_plan.json")
            key = task["selected_features"][0]
            public = dict(task_index[tid])
            if public["B"] != plan_data["source_current_curve"][key] or public["T"] != plan_data["resampled_target_curve"][key]:
                raise RuntimeError("Canonical B/T cross-condition contradiction")
            measurable = frozen_record["metric_eligible"]
            public.update(model=model, condition=condition, attempted=True, measurable=measurable,
                          failure_reason=frozen_record["ineligible_reason"], A=None, after_five=None,
                          dB=frozen_record["before_target_mae"], dA=frozen_record["after_target_mae"],
                          TI=frozen_record["target_improved"], DA=frozen_record["directional_accuracy"],
                          text_ratios=None, rewrite_text_pointer=None, reported_warning_count=None,
                          failure_detail=None,
                          provenance={"evaluation_records":run["records"], "rewrite_manifest":run["rewrite_manifest"],
                                      "reanalysis_manifest":run["reanalysis_manifest"], "plan":str(rwroot / "transfer_plan.json")})
            for filename in ("transfer_plan.json", "measurement_status.json", "reanalysis_failure.json", "rewritten_scene_features.json", "rewritten_scenes.json"):
                track(root / filename)
            for filename in ("rewrite_failure.json", "phase_status.json"):
                track(rwroot / filename)
            if not measurable and (rwroot / "rewrite_failure.json").is_file():
                public["failure_detail"] = failure_classification(read(rwroot / "rewrite_failure.json"))
            if measurable:
                measured_count += 1
                try:
                    raw_after = read(root / "rewritten_scene_features.json")
                    if any(r.get("film_id") != task["source_film_id"] or r.get("measurement_protocol_hash") != fs["measurement"]["protocol_hash"] for r in raw_after):
                        raise RuntimeError("After-feature film/measurement row lineage contradiction")
                    after = keyed_vectors(raw_after, public["source_scene_ids"], str(root / "rewritten_scene_features.json"))
                    after_off_grid += [dict(model=model,condition=condition,task_id=tid,scene_id=sid,feature=f,value=v)
                                       for sid,row in zip(public["source_scene_ids"],after) for f,v in row.items()
                                       if abs(v*10-round(v*10))>1e-12]
                    public["after_five"] = after
                    public["A"] = [v[public["selected_feature"]] for v in after]
                except BlockedAnalysis as exc:
                    # Selected A remains available from the metric-eligible rows;
                    # only the required off-target diagnostic is blocked.
                    raw = read(root / "rewritten_scene_features.json")
                    public["A"] = [r[key] for r in raw]
                    optional_blockers.append(str(exc))
                after_n += len(public["A"])
                rewrite = read(root / "rewritten_scenes.json")["rewritten_scenes"]
                if [r["scene_id"] for r in rewrite] != public["source_scene_ids"]:
                    raise RuntimeError("Rewritten text scene join contradiction")
                public["rewrite_text_pointer"] = str(root / "rewritten_scenes.json")
                track(rwroot / "rewritten_scenes.json")
                try:
                    public["text_ratios"] = [{"scene_id":r["scene_id"], **length_ratio(original_text[task["source_film_id"]][r["scene_id"]], r["content"])} for r in rewrite]
                except (KeyError, TypeError) as exc:
                    optional_blockers.append(f"A08 missing original text {task['source_film_id']} {exc}")
                summary_path = rwroot / "rewrite_summary.json"
                if summary_path.exists():
                    summary = read(summary_path)
                    # Only numerical counts exported; raw warning messages stay inputs.
                    public["reported_warning_count"] = len(summary.get("validation_warnings", []))
                    for sid in public["source_scene_ids"]:
                        scene_summary = rwroot / "per_scene" / sid / "scene_summary.json"
                        if scene_summary.exists():
                            public["reported_warning_count"] += len(read(scene_summary).get("warnings", []))
            elif any(public[k] is not None for k in ("A", "after_five", "TI", "DA")):
                raise RuntimeError("Failed attempt has imputed measurement")
            records[(model, condition)][tid] = public
    pairs = {m: [t["task_id"] for t in tasks if all(records[(m, c)][t["task_id"]]["measurable"] for c in CONDITIONS)] for m in models}
    common = [t["task_id"] for t in tasks if all(records[(m, c)][t["task_id"]]["measurable"] for m in models for c in CONDITIONS)]
    if (exact_count, measured_count, len(common)) != (1920, 1852, 186):
        raise RuntimeError("Frozen eligibility counts contradiction")
    for model in approved["models"]:
        if pairs[model["model_id"]] != model["paired_task_ids"]:
            raise RuntimeError("Frozen ordered paired population contradiction")
    controls = {entry["model"]: read(bound(entry["summary"])) for entry in plan["paired_controls"]}
    for model in models:
        control = controls[model]
        if pairs[model] != control["pair_task_ids"]:
            raise RuntimeError("Original Table7 population changed")
        for condition, prefix in zip(CONDITIONS, ("dp", "cg")):
            selected = [records[(model, condition)][tid] for tid in pairs[model]]
            for name, field in (("TI", "target_improvement"), ("DA", "directional_accuracy")):
                value = sum(float(r[name]) for r in selected) / len(selected)
                if value != control[f"{prefix}_{field}"]:
                    raise RuntimeError("Original Table7 numerical contradiction")
    cross = read(bound(plan["cross_control"]))
    if cross["global_common_task_ids"] != common:
        raise RuntimeError("Original Table6 common IDs changed")
    for control in cross["condition_summary"]:
        selected = [records[(control["model"], control["method"])][tid] for tid in common]
        for name, field in (("TI", "target_improvement"), ("DA", "directional_accuracy")):
            if sum(float(r[name]) for r in selected) / len(selected) != control[field]:
                raise RuntimeError("Original Table6 numerical contradiction")
    source_off_grid = [dict(film_id=film,scene_id=sid,feature=f,value=v)
                       for film,rows in source_rows.items() for sid,row in rows.items() for f,v in row.items()
                       if abs(v*10-round(v*10))>1e-12]
    table8_path = bound(plan["gemma_table8_control"])
    with table8_path.open(newline="") as stream:
        table8 = list(csv.DictReader(stream))
    validation = dict(original_records_exact_equal=exact_count, attempts_n=exact_count, measurable_n=measured_count,
                      failed_n=exact_count-measured_count, after_scene_n=after_n, source_film_n=len(films), original_scene_n=scene_n,
                      paired_n={m:len(ids) for m,ids in pairs.items()}, common_n=len(common),
                      structure_sha256=STRUCTURE_SHA, original_table7_exact=True, cross_control=cross,
                      table8_control=table8, optional_input_blockers=optional_blockers)
    validation["effective_grid_diagnostic"] = dict(original_feature_points_n=scene_n*5,
        original_off_tenth_grid_n=len(source_off_grid),after_feature_points_n=after_n*5,
        after_off_tenth_grid_n=len(after_off_grid),original_off_grid_records=source_off_grid,
        after_off_grid_records=after_off_grid,policy="Effective grid is descriptive; preserve every raw finite [0,1] score without quantization")
    for m in models:
        for c in CONDITIONS:
            for tid, row in records[(m, c)].items():
                row["population_membership"] = {"model_pair":tid in pairs[m], "global_common":tid in common, "all_attempt":True}
    provenance = dict(analyzer_version=ANALYZER_VERSION, approved_a6_protocol_sha256=APPROVED_SHA,
                      historical_execution_provenance="UNVERIFIED", input_plan_sha256=sha256_file(plan_path),
                      input_files=[dict(path=p,sha256=s) for p,s in sorted(files.items())], resolved_references=resolver.evidence)
    return Dataset(canonical_tasks, records, pairs, common, models, plan, provenance, validation, approved)
