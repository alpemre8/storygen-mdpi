"""Check all sealed run bytes for private Git backup eligibility. No commit/push."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import os


def main():
    from storygen_experiment.artifact_store import checked_depot
    from storygen_experiment.verification import verify_run
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depot", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    try:
        depot = checked_depot(args.depot)
        root = args.run.resolve()
        relative = root.relative_to(depot)
        if len(relative.parts) != 5 or relative.parts[0] != "experiments" or relative.parts[3] != "runs":
            raise ValueError("Expected central experiment run directory")
        if tuple(relative.parts[1:3]) not in {("measurement", "original_feature_extraction"), ("tasksetv5", "tasksetv5_main")}:
            raise ValueError("Run is outside the authorized backup scope")
        verified = verify_run(root)
        names = []
        total = 0
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlink in backup")
            if not path.is_file():
                continue
            if (path.suffix.lower() in {".gguf", ".safetensors", ".pt", ".pth", ".ckpt", ".pem", ".key"}
                    or path.name.startswith(".env") or any(x in {".venv", "venv", "node_modules"} for x in path.parts)):
                raise ValueError("Forbidden backup file: " + str(path))
            if path.stat().st_size >= 95 * 1024 * 1024:
                raise ValueError("Large file requires explicit remote storage decision; LFS is not assumed: " + str(path))
            # Fail if any sealed artifact would disappear from a normal Git clone.
            result = subprocess.run(["git", "-C", str(depot), "check-ignore", "--no-index", "--quiet", str(path)], check=False)
            if result.returncode == 0:
                raise ValueError("Ignored sealed artifact: " + str(path))
            if result.returncode != 1:
                raise RuntimeError("Git ignore inspection failed")
            if path.suffix in {".json", ".jsonl", ".yaml", ".yml", ".txt", ".log", ".csv"}:
                text = path.read_text(errors="replace")
                if any(marker in text for marker in ("-----BEGIN PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----", "github_pat_")):
                    raise ValueError("Possible credential in backup: " + str(path))
            total += path.stat().st_size
            names.append(str(path.relative_to(depot)))
        print(json.dumps(dict(status="SEALED_BYTES_ELIGIBLE__REMOTE_BACKUP_NOT_YET_PROVEN",
            integrity=verified["integrity"], files=len(names), bytes=total,
            relative_run_root=str(relative), scientific_validity="UNVERIFIED"), indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="BLOCKED", error=str(exc)), indent=2))
        return 2


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if os.environ.get("STORYGEN_BACKUP_CHECK_CHILD") != "1":
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update(PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1", STORYGEN_BACKUP_CHECK_CHILD="1")
        os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env)
    raise SystemExit(main())
