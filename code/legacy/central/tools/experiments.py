"""Run the local source package without installing or modifying the user environment."""

from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
env["PYTHONPATH"] = str(ROOT / "src")
env["PYTHONDONTWRITEBYTECODE"] = "1"
if __name__ == "__main__":
    os.execve(
        sys.executable,
        [sys.executable, "-m", "storygen_experiment.cli", *sys.argv[1:]],
        env,
    )
