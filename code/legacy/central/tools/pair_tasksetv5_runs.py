"""Pair immutable full DP/CG runs; preserve native records and failure denominators."""
import argparse
import json
import os
from pathlib import Path
import sys


def pair(dp, cg, output):
    from storygen_experiment import runtime, research_readiness
    from storygen_experiment.verification import verify_run
    roots = [Path(dp).resolve(), Path(cg).resolve()]
    records = []
    identities = []
    for root, strategy in zip(roots, ("DP-v1", "CG-v1"), strict=True):
        verification = verify_run(root)
        manifest = json.loads((root / "run_manifest.json").read_text())
        lock = json.loads((root / "run.lock.json").read_text())
        if (manifest["experiment_id"] != "tasksetv5_main" or manifest["purpose"] != "RESEARCH"
                or manifest["execution_status"] != "COMPLETE"):
            raise ValueError("Only complete RESEARCH TasksetV5 runs can form a full pairing")
        native = next(n for n in lock["native_execution_contexts"] if n["native_protocol"] == "TASKSETV5_MAIN_V1")
        config = native["configuration"]
        if config["strategy"] != strategy or config.get("verification_task_ids"):
            raise ValueError("Wrong condition or a verification subset")
        bound_files = list((root / "stages/bind_runtime/raw/data").rglob("taskset_runtime.json"))
        if len(bound_files) != 1:
            raise ValueError("Exactly one bound native runtime required")
        tasks = json.loads(bound_files[0].read_text())["tasks"]
        expected_ids = {f"v5_T{i:04d}" for i in range(1, 241)}
        if len(tasks) != 240 or {t["task_id"] for t in tasks} != expected_ids:
            raise ValueError("A full condition must bind all 240 unique tasks")
        observation, = verification["native_observations"]
        evaluations = observation["evaluation_task_records"]
        if len(evaluations) != 240 or {r["task_id"] for r in evaluations} != expected_ids:
            raise ValueError("Missing/duplicate native evaluation records; no observations manufactured")
        scientific_inputs = {k: v["sha256"] for k, v in config["inputs"].items()
                             if k in json.loads(research_readiness.INPUT_LOCK.read_text())["files"]}
        frozen_inputs = {k: v["sha256"] for k, v in json.loads(research_readiness.INPUT_LOCK.read_text())["files"].items()
                         if k != "canonical_server_manifest"}
        if scientific_inputs != frozen_inputs:
            raise ValueError("Every frozen script/reference/input binding is required for pairing")
        profiles = {role: json.loads(Path(config["inputs"][role]["path"]).read_text())
                    for role in ("rewrite_server_manifest", "measurement_server_manifest")}
        # Compare every scientific task field; only physical file locators may differ.
        population = [{k: v for k, v in task.items() if not k.endswith("_path")} for task in tasks]
        identities.append(dict(population=runtime.canonical(population), inputs=scientific_inputs,
            model_conditions={role: {k: p[k] for k in ("model_alias", "model_sha256", "quantization")}
                              for role, p in profiles.items()}))
        records.append(dict(run_id=manifest["run_id"], manifest_sha256=runtime.sha(root / "run_manifest.json"),
            execution_lock_sha256=runtime.sha(root / "run.lock.json"),
            evaluations={r["task_id"]: r for r in evaluations}))
    if identities[0] != identities[1]:
        raise ValueError("Different frozen populations, inputs or model conditions")
    if roots[0] == roots[1]:
        raise ValueError("Two independent condition runs are required")
    output = Path(output).resolve()
    depot = roots[0].parents[4]
    if not output.is_relative_to(depot / "exports/tasksetv5_pairings"):
        raise ValueError("Pairing output must be in central depot/exports/tasksetv5_pairings")
    result = dict(schema_version="storygen.tasksetv5-condition-pairing/1.0", experiment_id="tasksetv5_main",
        unique_task_n=240, planned_task_condition_n=480, scientific_validity="UNVERIFIED",
        native_metrics_recalculated=False, immutable_run_references=[{k: v for k, v in r.items() if k != "evaluations"} for r in records],
        pairs=[dict(task_id=key, dp=records[0]["evaluations"][key], cg=records[1]["evaluations"][key])
               for key in sorted(records[0]["evaluations"])])
    runtime.exclusive_json(output, result)
    return dict(status="PAIRED_NATIVE_RECORDS", output=str(output), sha256=runtime.sha(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dp-run", required=True, type=Path)
    parser.add_argument("--cg-run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(pair(args.dp_run, args.cg_run, args.output), indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="BLOCKED", error=str(exc)), indent=2))
        return 2


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if os.environ.get("STORYGEN_PAIR_CHILD") != "1":
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update(PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1", STORYGEN_PAIR_CHILD="1")
        os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env)
    raise SystemExit(main())
