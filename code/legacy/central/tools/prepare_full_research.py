"""Offline helper; uses the existing experiment runners, never executes them."""
from pathlib import Path
import os
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
    os.execve(sys.executable, [sys.executable, "-m",
              "storygen_experiment.research_readiness", *sys.argv[1:]], env)
