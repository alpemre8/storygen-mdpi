"""Terminal local-preservation receipt; depot publication is always forbidden."""

from pathlib import Path
from .engine.common import StoryGenError, read, utc


def backup(depot, run_root, *, publish=False):
    # The operator's local-only rule is unconditional, including previously cleared prefixes.
    # Keep this ahead of all filesystem/run checks and all subprocess/network paths.
    if publish:
        raise StoryGenError("LOCAL_ONLY_NOT_REMOTE_BACKED_UP: depot remote publication is forbidden")
    depot, run_root = Path(depot).resolve(), Path(run_root).resolve()
    if not run_root.is_relative_to(depot / "experiments"):
        raise StoryGenError("Backup requires a run under this depot")
    records = sorted(run_root.glob("evaluations/*.json"))
    if not records or read(records[-1])["execution_status"] not in {
        "COMPLETE",
        "PARTIAL",
        "FAILED",
    }:
        raise StoryGenError("Please finalize the run first; local-only backup checks require a terminal assessment")
    oversized = [
        str(p.relative_to(depot))
        for p in run_root.rglob("*")
        if p.is_file() and p.stat().st_size >= 100 * 1024**2
    ]
    receipt = {
        "utc": utc(),
        "run": str(run_root.relative_to(depot)),
        "status": "LOCAL_ONLY_NOT_REMOTE_BACKED_UP",
        "remote_backup": "LOCAL_ONLY_NOT_REMOTE_BACKED_UP",
        "local_git_commit": "NOT_PERFORMED_BY_PREFLIGHT",
        "oversized": oversized,
        "files": sum(p.is_file() for p in run_root.rglob("*")),
    }
    return receipt
