"""Reusable analysis methods pin each concrete input selection immutably."""

from pathlib import Path
import uuid
from .engine.artifacts import RunStore
from .engine.common import (
    StoryGenError,
    contained,
    digest,
    ensure_directory,
    file_sha,
    read,
    utc,
    write_json,
    identifier,
)


def lookup(value, dotted):
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            raise StoryGenError(f"Comparability evidence missing: {dotted}")
        value = value[key]
    return value


def implementation_identity():
    package = Path(__file__).resolve().parent
    files = {
        name: file_sha(package / name)
        for name in ("analysis.py", "engine/artifacts.py", "engine/common.py")
    }
    return {"files": files, "sha256": digest(files), "scientific_approval": "PENDING"}


def analyze(root, depot, analysis_id, source_roots, analysis_run_id=None):
    method_home = contained(Path(root) / "analyses", identifier(analysis_id))
    method = read(method_home / "analysis.yaml")
    if method["method"] == "plugin-pipeline/1":
        from .engine.execution import run
        from .engine.plugins import Registry

        expected = {}
        for source in method["sources"]:
            path = contained(depot, source["relative_path"])
            if file_sha(path / source["manifest_name"]) != source["manifest_sha256"]:
                raise StoryGenError("Frozen analysis source manifest changed")
            expected[str(path)] = source
        selected = []
        for path in source_roots:
            if str(path).startswith("H-"):
                from .historical import HistoricalCatalog

                catalog = HistoricalCatalog(depot)
                receipt = catalog.select(str(path))
                if receipt["qualification"] == "ENGINEERING_OR_TEST":
                    raise StoryGenError("Engineering fixtures are not scientific analysis sources")
                catalog.verify(str(path))
                selected.append(str(contained(depot, receipt["active_resolved_root"]).resolve()))
            else:
                selected.append(str(Path(path).resolve()))
        if len(set(selected)) != len(selected) or set(selected) != set(expected):
            raise StoryGenError(
                "Analysis requires exactly its explicitly pinned source run selection"
            )
        return run(
            root,
            depot,
            Registry([Path(root) / "plugins"]),
            analysis_id,
            {"roles": {}},
            run_id=analysis_run_id,
            catalog="analyses",
        )
    if method["method"] != "matched-existing-output/1":
        raise StoryGenError("Unsupported analysis method; add a versioned method implementation")
    if len(source_roots) < 2:
        raise StoryGenError(
            "Analysis requires at least two explicit source run roots; latest is forbidden"
        )
    sources, values, conditions = [], [], []
    for source in source_roots:
        source = Path(source).resolve()
        if not source.is_relative_to(Path(depot).resolve() / "experiments"):
            raise StoryGenError("Analysis source must be a pinned run under this depot")
        lock_path = source / "run.lock.json"
        lock = read(lock_path)
        identity = lock["identity"]
        if digest(identity) != lock["lock_sha256"]:
            raise StoryGenError("Source run lock checksum mismatch")
        evaluations = sorted(source.glob("evaluations/*.json"))
        if not evaluations:
            raise StoryGenError("Source has no finalized/partial evaluation")
        last = read(evaluations[-1])
        if last["execution_status"] != "COMPLETE" and not method["allow_partial"]:
            raise StoryGenError("Method forbids partial source coverage")
        store = RunStore(source)
        store.validate_logs()
        committed = store.committed(lock["lock_sha256"])
        selected = {
            unit: value[method["output_port"]]
            for (stage, unit), value in committed.items()
            if stage == method["stage_id"]
        }
        if not selected:
            raise StoryGenError("Selected source stage/output has no genuine committed records")
        sources.append(
            {
                "experiment_id": identity["experiment_id"],
                "run_id": identity["run_id"],
                "run_lock_sha256": file_sha(lock_path),
                "evaluation_sha256": file_sha(evaluations[-1]),
                "events_sha256": file_sha(source / "events.jsonl"),
                "source_relative": source.relative_to(Path(depot).resolve()).as_posix(),
                "available_units": sorted(selected),
                "task_population": last["task_population"],
                "development_exposure": identity["exposed_task_ids"],
            }
        )
        conditions.append(identity)
        values.append(selected)
    if len({(s["experiment_id"], s["run_id"]) for s in sources}) != len(sources):
        raise StoryGenError("Duplicate source run selection")
    for path in method["comparability_paths"]:
        found = [lookup(c, path) for c in conditions]
        if any(value != found[0] for value in found[1:]):
            raise StoryGenError(f"BLOCKED incomparable sources: {path}")
    common = sorted(set.intersection(*(set(v) for v in values)))
    if not common:
        raise StoryGenError("BLOCKED: source runs have no valid matched task intersection")
    method_hash = file_sha(method_home / "analysis.yaml")
    frozen = Path(depot) / "analysis_methods" / analysis_id / "lock.json"
    if frozen.exists():
        if read(frozen)["method_sha256"] != method_hash:
            raise StoryGenError("Frozen analysis method changed; define a new method ID")
    else:
        write_json(frozen, {"method_sha256": method_hash, "method": method, "created_utc": utc()})
    run_id = identifier(analysis_run_id or ("AR-" + uuid.uuid4().hex))
    target = Path(depot) / "analyses" / analysis_id / "runs" / run_id
    ensure_directory(target.parent)
    target.mkdir(exist_ok=False)
    implementation = implementation_identity()
    # Different quantizations/conditions stay explicit strata, never pooled silently.
    strata = {}
    runtime_strata = {}
    for i, condition in enumerate(conditions):
        key = digest(condition["conditions"])
        strata.setdefault(key, {"conditions": condition["conditions"], "source_indexes": []})[
            "source_indexes"
        ].append(i)
        profile = condition["profile"]
        runtime_strata.setdefault(digest(profile), {"profile": profile, "source_indexes": []})[
            "source_indexes"
        ].append(i)
    result = {
        "analysis_id": analysis_id,
        "analysis_run_id": run_id,
        "method_sha256": method_hash,
        "implementation": implementation,
        "sources": sources,
        "matched_units": common,
        "excluded_units": [sorted(set(v) - set(common)) for v in values],
        "coverage": [
            {
                "observed_units": len(v),
                "matched_units": len(common),
                "source_population": s["task_population"],
            }
            for v, s in zip(values, sources)
        ],
        "strata": strata,
        "runtime_strata": runtime_strata,
        "rows": [{"unit_id": uid, "source_values": [v[uid] for v in values]} for uid in common],
        "selection_limitation": "Matched subset only; no claim of whole-population inference; DEV exposure retained",
        "created_utc": utc(),
        "scientific_results_verified": False,
    }
    write_json(
        target / "analysis.lock.json",
        {
            "method": method,
            "method_sha256": method_hash,
            "implementation": implementation,
            "sources": sources,
        },
    )
    write_json(target / "results.json", result)
    return target, result
