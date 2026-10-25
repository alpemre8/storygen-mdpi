"""Offline research configuration preparation; never launches an experiment or server.

Only the existing historical runtime is supported. Unsupported portable bindings
fail explicitly until the frozen native identity contract has been resolved.
"""

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
import uuid

from storygen_experiment import ROOT, contracts, registry, runtime
from storygen_experiment.artifact_store import checked_depot

INPUT_LOCK = Path(__file__).with_name("research_inputs.lock.json")
GROUPS = {"original_feature_extraction": "measurement", "tasksetv5_main": "tasksetv5"}


def fresh_id(experiment, machine):
    if experiment not in GROUPS:
        raise ValueError("Only the two existing research identities are supported")
    contracts.identifier(machine)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{experiment}__{machine}__{stamp}__{uuid.uuid4().hex}"


def checked_inventory(workspace):
    workspace = Path(workspace).resolve()
    lock = json.loads(INPUT_LOCK.read_text())
    bindings = {}
    for name, ref in lock["files"].items():
        path = contracts.contained(workspace, ref["relative_path"])
        contracts.checked_file({"path": str(path), "sha256": ref["sha256"]})
        bindings[name] = {"path": str(path), "sha256": ref["sha256"]}
    return lock, bindings


def prepare(experiment, workspace, destination, machine_id, *, strategy=None):
    """Prepare a full-population historical configuration, without a readiness claim."""
    if experiment not in GROUPS:
        raise ValueError("Unsupported experiment")
    if experiment == "tasksetv5_main" and strategy not in {"DP-v1", "CG-v1"}:
        raise ValueError("TasksetV5 requires explicit DP-v1 or CG-v1")
    if experiment == "original_feature_extraction" and strategy is not None:
        raise ValueError("Original measurement has no rewriting strategy")
    workspace = Path(workspace).resolve()
    depot = checked_depot(workspace / "storygen-experiment-depot")
    destination = Path(destination).resolve()
    if not destination.is_relative_to(depot / "local"):
        raise ValueError("Prepared local configurations must belong to the central depot/local")
    lock, bindings = checked_inventory(workspace)
    value = registry.locked(experiment)
    profile_name = {None: "research.profile.json", "DP-v1": "research.dp.profile.json",
                    "CG-v1": "research.cg.profile.json"}[strategy]
    profile_path = value["home"] / profile_name
    profile = registry.read(profile_path)
    if (profile["purpose"] != "RESEARCH" or profile["experiment_id"] != experiment
            or profile["strategy"] != strategy or profile["complete_film_population"] is not True
            or profile["task_count"] != (240 if strategy else None)
            or profile["measurement_model"] != "qwen2.5-7b-q4"
            or profile["manage_servers"] is not False):
        raise ValueError("Full research profile changes the frozen design or runtime role")
    native = registry.read(value["home"] / "src/assets/native_configuration.json")
    native.update(purpose="RESEARCH", manage_servers=False,
                  input_root=str(workspace / lock["input_root"]))
    native["execution_conditions"] = dict(machine_id=machine_id,
        machine_profile="historical-amd-vulkan", model_profile="qwen2.5-7b-q4",
        operating_system=platform.platform(), python_version=sys.version,
        gpu_identity="UNATTESTED", server_identity="UNATTESTED")
    native.pop("verification_task_ids", None)
    if "scene_selection" in native.get("inputs", {}):
        raise ValueError("Full original research cannot inherit a scene subset")
    # Original frozen server bytes are available in the current source checkout;
    # no unverified historical worktree fallback is used.
    server = bindings.pop("canonical_server_manifest")
    native["inputs"] = bindings
    if experiment == "tasksetv5_main":
        native["strategy"] = strategy
        native["inputs"].update(rewrite_server_manifest=server,
                                 measurement_server_manifest=server)
    else:
        native["inputs"]["server_manifest"] = server
    # All original input/FeatureSet files become explicit hashed native inputs,
    # checked again by the unchanged native Context.resolve before execution.
    run_id = fresh_id(experiment, machine_id)
    destination.mkdir(parents=True, exist_ok=False)
    native_path = destination / "native.research.json"
    runtime.exclusive_json(native_path, native)
    config = {"purpose": "RESEARCH", "inputs": {"native_configuration": {
        "path": str(native_path), "sha256": runtime.sha(native_path)}}}
    runtime.exclusive_json(destination / "run.research.json", config)
    receipt = dict(status="CONFIGURATION_PREPARED__READINESS_BLOCKED", experiment_id=experiment,
                   machine_id=machine_id, run_id=run_id, strategy=strategy,
                   input_inventory_sha256=runtime.sha(INPUT_LOCK),
                   research_run_profile_sha256=runtime.sha(profile_path),
                   scene_count=sum(x["scene_count"] for x in lock["films"]),
                   planned_task_count=240 if strategy else None,
                   selected_model="qwen2.5-7b-q4", backend="llama.cpp Vulkan",
                   model_configuration="Historical exact paths and hashes remain mandatory",
                   output_directory=str(depot / "experiments" / GROUPS[experiment] /
                                        experiment / "runs" / run_id),
                   config=str(destination / "run.research.json"),
                   real_inference_performed=False,
                   blocker="Portable runtime binding and external-server attestation are not implemented; see docs/FULL_RESEARCH_READINESS_REPORT.md")
    runtime.exclusive_json(destination / "preparation.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT.parent)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check-inputs")
    new = sub.add_parser("new-run-id")
    new.add_argument("experiment", choices=GROUPS)
    new.add_argument("--machine-id", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("experiment", choices=GROUPS)
    prep.add_argument("--machine-id", required=True)
    prep.add_argument("--strategy", choices=["DP-v1", "CG-v1"])
    prep.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "new-run-id":
            print(fresh_id(args.experiment, args.machine_id))
            return 0
        if args.action == "check-inputs":
            lock, bound = checked_inventory(args.workspace)
            result = dict(status="INPUT_HASHES_VALID__RUNTIME_NOT_ATTESTED",
                          file_count=len(bound), films=lock["films"],
                          total_scenes=sum(x["scene_count"] for x in lock["films"]),
                          feature_set_id=lock["feature_set_id"])
        else:
            result = prepare(args.experiment, args.workspace, args.destination,
                             args.machine_id, strategy=args.strategy)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="BLOCKED", error=str(exc)), indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
