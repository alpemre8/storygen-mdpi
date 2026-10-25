"""Explicit E01A profile CLI; original extraction entry points stay unchanged."""
from pathlib import Path
import argparse
import json
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
CORE = PROJECT / "measurement"
sys.path[:0] = [str(PROJECT), str(ROOT / "src"), str(CORE / "src")]

from storygen_feature.independent import (bind_checkpoint, prepare_input_contract, load_catalog,
                                        select_smoke, run_smoke, load_profile, launch_args, validate_results)
from storygen_feature.io import read_json, write_json
from tools.depot_paths import owned_output_path


def main():
    parser = argparse.ArgumentParser(description="E01A only: prepare, bind or run at most 20 scenes/40 requests. Never starts a server.")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Freeze verified pointers and deterministic sample; zero inference")
    prepare.add_argument("--analysis-plan", type=Path, required=True)
    prepare.add_argument("--original-input-root", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    bind = commands.add_parser("bind", help="Inspect/hash actual F16 weights and freeze a new bound profile; zero inference")
    bind.add_argument("--profile", type=Path, required=True)
    bind.add_argument("--model-file", type=Path, required=True)
    bind.add_argument("--output-dir", type=Path, required=True)
    launch = commands.add_parser("server-command", help="Print frozen valid server command; does not execute it")
    launch.add_argument("--profile", type=Path, required=True)
    run = commands.add_parser("smoke", help="Validate explicit profile and frozen scene sample, then run bounded qualification")
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--input-contract", type=Path, required=True)
    run.add_argument("--selection", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Offline validation only (the default)")
    mode.add_argument("--execute-inference", action="store_true", help="Explicitly authorize bounded real measurements on an already running verified server")
    run.add_argument("--resume", action="store_true")
    validate = commands.add_parser("validate-results", help="Check a completed bounded FeatureSet; never sends model requests")
    validate.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "server-command":
        protocol = load_profile(CORE, args.profile, require_bound=True)
        print(shlex.join(launch_args(protocol))); return
    output = owned_output_path(args.output_dir)
    if args.command == "prepare":
        if (output / "input_contract.json").exists() or (output / "scene_selection.json").exists():
            raise FileExistsError("Frozen inputs/selection already exist; no overwrite supported")
        contract = prepare_input_contract(args.analysis_plan, args.original_input_root)
        catalog = load_catalog(contract); selection = select_smoke(contract, catalog)
        write_json(output / "input_contract.json", contract)
        write_json(output / "scene_selection.json", selection)
        result = {"status": "PREPARED", "unique_scenes": len(selection["records"]), "real_requests": 0}
    elif args.command == "bind":
        result = bind_checkpoint(CORE, args.profile, args.model_file, output)
    elif args.command == "validate-results":
        result = validate_results(output, CORE)
    else:
        result = run_smoke(core=CORE, profile=args.profile, input_contract=args.input_contract,
                           selection_path=args.selection, output=output, dry_run=not args.execute_inference,
                           execute_inference=args.execute_inference, resume=args.resume)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
