"""Read-only, hash-bound historical inputs; no scientific engine imports."""

from pathlib import Path
import sys
import platform
from importlib.metadata import version
from validate import validate_record
from common import BindingError, CONDITIONS, FEATURES, MODELS, read, same_task, sha


def load_ref(ref):
    path = Path(ref["path"])
    if ref["sha256"] is None:
        if path.exists():
            raise BindingError(
                "Previously missing artifact appeared; explicit rebinding required: "
                + str(path)
            )
        return None
    if not path.is_file() or sha(path) != ref["sha256"]:
        raise BindingError("Missing/changed frozen artifact: " + str(path))
    value = read(path)
    if ref.get("mode") == "scene_ids_only":
        return {"scene_ids": [r["scene_id"] for r in value["rewritten_scenes"]]}
    return value


def population(runtime):
    tasks = runtime["tasks"]
    if len(tasks) != 240 or len({t["task_id"] for t in tasks}) != 240:
        raise BindingError("TasksetV5 must contain exactly 240 unique tasks")
    bases = {}
    for task in tasks:
        ids = task["source_scene_ids"]
        if (
            not ids
            or len(ids) != len(set(ids))
            or len(ids) != task["source_scene_count"]
        ):
            raise BindingError("Invalid frozen scene identity/count")
        selected = task["selected_features"]
        if len(selected) != 1 or selected[0] not in FEATURES:
            raise BindingError("Expected one of the frozen five features")
        bases.setdefault(task["base_interval_id"], []).append(task)
    if len(bases) != 48 or sum(len(t["source_scene_ids"]) for t in tasks) != 2000:
        raise BindingError("Expected 48 bases and 2000 scene slots")
    if len({t["source_film_id"] for t in tasks}) != 10:
        raise BindingError("Expected ten source films")
    for group in bases.values():
        if len(group) != 5 or {t["selected_features"][0] for t in group} != set(
            FEATURES
        ):
            raise BindingError("Each base must have all five controlled features")
        if any(
            (t["source_film_id"], t["source_scene_ids"])
            != (group[0]["source_film_id"], group[0]["source_scene_ids"])
            for t in group
        ):
            raise BindingError(
                "Base interval identity differs across controlled features"
            )
    return sorted(tasks, key=lambda t: t["task_id"])


def instrument(value, canonical):
    if value != canonical:
        raise BindingError(
            "MEASUREMENT_MISMATCH: historical measurement configurations differ"
        )


def resolve(path, *, sample_only=False):
    binding = read(path)
    if binding["schema_version"] != "e05.feature-diff.bindings/1.0":
        raise BindingError("Unsupported binding schema")
    tasks = population(load_ref(binding["taskset"]))
    old = population(load_ref(binding["rewrite_taskset"]))
    if any(not same_task(a, b) for a, b in zip(tasks, old, strict=True)):
        raise BindingError("Frozen and rewrite-time task/scene definitions differ")
    reference = load_ref(binding["reference"])
    canonical = reference["measurement"]
    if (
        canonical != binding["measurement"]
        or canonical["normalization"]["value_min"] != 0
        or canonical["normalization"]["value_max"] != 1
    ):
        raise BindingError("Invalid canonical instrument")
    if (
        canonical["model"]["model_sha256"]
        != "sha256:65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423"
    ):
        raise BindingError(
            "Expected canonical Qwen checkpoint; no alternate extractors"
        )
    if (
        load_ref(binding["taskset"])["feature_set_manifest_sha256"]
        != binding["reference"]["sha256"]
    ):
        raise BindingError("Frozen feature-set lineage mismatch")
    combinations = binding["combinations"]
    if [(c["model"], c["condition"]) for c in combinations] != [
        (m, c) for m in MODELS for c in CONDITIONS
    ]:
        raise BindingError("Expected all eight ordered model-condition combinations")
    originals = {}
    for film, refs in binding["films"].items():
        manifest = load_ref(refs["manifest"])
        instrument(manifest["measurement"], canonical)
        if manifest["film_id"] != film:
            raise BindingError("Original film manifest identity mismatch")
        originals[film] = load_ref(refs["features"])
    for combo in combinations:
        rewrite = load_ref(combo["rewrite_manifest"])
        rean = load_ref(combo["reanalysis_manifest"])
        instrument(rean["measurement"], canonical)
        instrument(rewrite["feature_set_manifest"]["measurement"], canonical)
        if (
            rewrite["contract_id"] != "storygen.rewrite-run"
            or rewrite["contract_version"] != "1.3"
            or rean["contract_id"] != "storygen.reanalysis-run"
            or rean["contract_version"] != "1.1"
        ):
            raise BindingError("Unsupported historical measurement/rewrite contract")
        if (
            rewrite["prompt_contract_id"] != combo["condition"]
            or rewrite["model"] != combo["rewrite_model"]
        ):
            raise BindingError("Wrong rewrite condition/model")
        if (
            rean["source_rewrite_run"]["manifest_sha256"]
            != combo["rewrite_manifest"]["sha256"]
        ):
            raise BindingError("Reanalysis points to a different rewrite run")
        if (
            rean["source_feature_set_manifest"]["sha256"]
            != binding["reference"]["sha256"]
            or rewrite["feature_set_manifest"]["sha256"]
            != binding["reference"]["sha256"]
        ):
            raise BindingError("Feature-set lineage mismatch")
        if any(
            v["taskset"]["sha256"] != binding["rewrite_taskset"]["sha256"]
            or v["taskset"]["task_count"] != 240
            for v in (rewrite, rean)
        ):
            raise BindingError("Rewrite taskset lineage mismatch")
        if set(combo["tasks"]) != {t["task_id"] for t in tasks}:
            raise BindingError("Planned task bindings incomplete")
        # Read-only preflight checks one task per combination plus manifest failure lists.
        available = [
            t
            for t in tasks
            if combo["tasks"][t["task_id"]]["after"]["sha256"] is not None
        ]
        check = [available[0] if available else tasks[0]] if sample_only else tasks
        for task in check:
            for ref in combo["tasks"][task["task_id"]].values():
                load_ref(ref)
            if sample_only:
                refs = combo["tasks"][task["task_id"]]
                summary, _ = validate_record(
                    dict(
                        model=combo["model"],
                        condition=combo["condition"],
                        task=task,
                        artifacts={k: load_ref(v) for k, v in refs.items()},
                        artifact_refs=refs,
                    ),
                    originals,
                    canonical,
                )
                if summary["status"] not in (
                    "COMPLETE",
                    "PARTIAL",
                    "MISSING_REWRITE",
                    "MISSING_REANALYSIS",
                ):
                    raise BindingError(
                        "Bounded sample validation failed: " + str(summary)
                    )
    return binding, tasks, originals


def prepare(path):
    binding, tasks, originals = resolve(path)
    binding["execution_metadata"] = dict(
        python=sys.version,
        platform=platform.platform(),
        packages={name: version(name) for name in ("numpy", "matplotlib")},
        selection="All 240 frozen tasks under all eight bound combinations; no success filter",
        zero_epsilon=1e-12,
        aggregation="Within task then equal task weight; complete tasks only",
        bootstrap_seed=250504,
        bootstrap_replications=2000,
        source_commit_evidence="Exact central source commit and installed package closure are additionally sealed in run.lock.json",
    )
    records = []
    for combo in binding["combinations"]:
        for task in tasks:
            refs = combo["tasks"][task["task_id"]]
            records.append(
                dict(
                    model=combo["model"],
                    condition=combo["condition"],
                    task=task,
                    artifacts={key: load_ref(ref) for key, ref in refs.items()},
                    artifact_refs=refs,
                )
            )
    return dict(
        schema_version="e05.feature-diff.prepared/1.0",
        binding=binding,
        tasks=tasks,
        originals=originals,
        records=records,
    )
