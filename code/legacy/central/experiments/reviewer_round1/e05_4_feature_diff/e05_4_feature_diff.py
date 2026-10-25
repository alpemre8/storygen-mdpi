"""Repository-local public runner over central immutable execution."""

from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import signal
import subprocess
import sys
import time
import uuid

HOME = Path(__file__).resolve().parent
ROOT = HOME.parents[2]
KEY = "e05_4_feature_diff"
RUNS = (
    ROOT.parent / "storygen-experiment-depot/experiments/reviewer_round1" / KEY / "runs"
)
BANNER = """====================================================
                 E05-4-FEATURE-DIFF
====================================================

MODE: DETERMINISTIC
LLM INFERENCE: DISABLED
NEW REWRITE: DISABLED"""


def select_run(run_id):
    if run_id:
        if not run_id.replace("_", "").replace("-", "").replace(
            ".", ""
        ).isalnum() or run_id in (".", ".."):
            raise ValueError("Invalid run ID")
        return run_id
    candidates = sorted(p.name for p in RUNS.glob("*") if p.is_dir())
    if len(candidates) != 1:
        raise ValueError(
            "Specify --run-id: selection requires exactly one existing run"
        )
    return candidates[0]


def central(action, run_id, config=None):
    args = [
        sys.executable,
        str(ROOT / "tools/experiments.py"),
        action,
        KEY,
        "--run-id",
        run_id,
    ]
    if config is not None:
        args += ["--config", str(config)]
    return args


def compact_preflight(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    try:
        value = json.loads(result.stdout)
        if value.get("status") == "PLAN_READY":
            value = {
                **{
                    k: value[k]
                    for k in ("status", "run_id", "artifact_directory", "checks")
                },
                "stages": [s["stage_id"] for s in value["stages"]],
            }
        print(json.dumps(value, indent=2), flush=True)
    except ValueError:
        print(result.stdout, end="", flush=True)
    return result.returncode


def stream_run(command, run_root):
    if run_root.exists():
        raise FileExistsError("Immutable run already allocated; select a fresh ID")
    process = subprocess.Popen(command)
    offsets = {}

    def logs():
        for path in sorted((run_root / "logs").glob("*.log")):
            with path.open() as stream:
                stream.seek(offsets.get(path, 0))
                text = stream.read()
                offsets[path] = stream.tell()
            if text:
                print(text, end="", flush=True)

    try:
        while process.poll() is None:
            logs()
            time.sleep(0.2)
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        process.wait()
    finally:
        logs()
    return process.returncode


def main(argv=None):
    print(BANNER, flush=True)
    p = argparse.ArgumentParser(
        description="Bounded deterministic historical analysis. One terminal; no server."
    )
    p.add_argument(
        "command", choices=("preflight", "run", "status", "report", "verify")
    )
    p.add_argument("--run-id")
    args = p.parse_args(argv)
    config = HOME / "run.example.json"
    if args.command in ("preflight", "run"):
        run_id = (
            select_run(args.run_id)
            if args.run_id
            else "e05fd_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")
            + uuid.uuid4().hex[:8]
        )
        print(
            "MODEL-CONDITION COMBINATIONS: 8\nPLANNED TASKS: 1920\nPROCESSED TASKS: 0\nCOMPLETE TASKS: NOT ASSESSED\nPARTIAL TASKS: NOT ASSESSED\nMISSING TASKS: NOT ASSESSED\nELAPSED: 00:00:00\nETA: UNKNOWN (no observed throughput)",
            flush=True,
        )
        checked = subprocess.run(
            [
                sys.executable,
                str(HOME / "src/engine.py"),
                "binding-check",
                "--input",
                str(HOME / "src/assets/bindings.json"),
            ]
        )
        if checked.returncode:
            return checked.returncode
        print("RUN ID: " + run_id, flush=True)
        command = central(args.command, run_id, config)
        if args.command == "run":
            return stream_run(command, RUNS / run_id)
        return compact_preflight(command)
    run_id = select_run(args.run_id)
    if args.command == "report":
        checked = subprocess.run(central("verify", run_id))
        if checked.returncode:
            return checked.returncode
        output = RUNS / run_id / "stages/report/raw"
        report = output / "E05_4_FEATURE_DIFF_REPORT.md"
        if not report.is_file():
            raise FileNotFoundError("No completed report in this run")
        manifest = json.loads((RUNS / run_id / "run_manifest.json").read_text())
        if (
            manifest["execution_status"] != "COMPLETE"
            or manifest["contract_status"] != "VALID"
        ):
            raise ValueError(
                "A complete contract-valid run is required for report selection"
            )
        print(report)
        return 0
    result = subprocess.run(central(args.command, run_id)).returncode
    if args.command == "status":
        progress = None
        for path in sorted((RUNS / run_id / "logs").glob("*.log")):
            for line in path.read_text().splitlines():
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict) and "processed_tasks" in value:
                    progress = value
        print(
            json.dumps(
                progress
                or dict(
                    combinations=8,
                    planned_tasks=1920,
                    processed_tasks=0,
                    complete_tasks=None,
                    partial_tasks=None,
                    missing_tasks=None,
                    elapsed="00:00:00",
                    ETA="UNKNOWN",
                )
            ),
            flush=True,
        )
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(json.dumps(dict(status="REJECTED", reason=str(exc))), file=sys.stderr)
        raise SystemExit(2)
