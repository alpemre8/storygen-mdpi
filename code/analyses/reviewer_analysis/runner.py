from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from storygen_platform.cli import main

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "inspect"
    args = [command, "reviewer_analysis", *sys.argv[2:]]
    if command != "analyze":
        args += ["--catalog", "analyses"]
    raise SystemExit(main(args))
