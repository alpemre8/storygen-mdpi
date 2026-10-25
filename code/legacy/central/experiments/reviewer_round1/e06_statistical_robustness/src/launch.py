"""Optional central DAG adapter: deterministic E06 stage, explicit human request."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get("mode") not in ("dry-run", "run"):
        raise ValueError("Explicit dry-run or human run request required")
    runner = Path(__file__).resolve().parents[1] / "e06_statistical_robustness.py"
    command = [
        sys.executable,
        str(runner),
        config["mode"],
        "--output",
        str(args.output / "e06"),
    ]
    if config["mode"] == "run":
        if config.get("human_run") is not True:
            raise ValueError(
                "Real scientific execution is reserved for the human researcher"
            )
        command += ["--human-run", "--binding", config["binding"]]
    subprocess.run(command, check=True)
    status = json.loads((args.output / "e06/E06_STATUS.json").read_text())
    (args.output / "result.json").write_text(
        json.dumps(
            dict(
                status=status["status"],
                dataset_kind=status["dataset_kind"],
                inference_requests=0,
                scientific_validity="SCIENTIFIC_RESULTS_NOT_YET_VERIFIED",
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
