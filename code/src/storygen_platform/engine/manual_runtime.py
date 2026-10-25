"""Two-terminal sessions owned by StoryGen; never attach to an arbitrary listener."""

from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import time
import uuid

from .common import StoryGenError, digest, file_sha, identifier, read, utc, write_json
from .runtime import ServerManager, gpu_lease, process_identity, http_json


def session_path(depot, name):
    return Path(depot) / "experiments/e01_b/runtime" / (identifier(name) + ".json")


def source_commit(root):
    import subprocess

    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def serve(root, depot, profile, name):
    """Operator-only blocking server lifecycle. Both output streams go to a file."""
    path = session_path(depot, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".owner.lock").open("a+b") as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StoryGenError("Manual StoryGen server session already owned") from exc
        if path.exists():
            old = read(path)
            if process_identity(old["owner"]["pid"]) == old["owner"]:
                raise StoryGenError("Existing manual runtime owner is alive")
            archive = path.parent / "archive" / (name + "-" + uuid.uuid4().hex + ".json")
            write_json(archive, old)
        manager = ServerManager(profile, path.parent / "logs" / (name + "-" + uuid.uuid4().hex))
        coordination = profile["coordination_directory"]
        with gpu_lease(coordination, "manual:" + name):
            try:
                manager.switch("measurement")
                descriptor = {
                    "schema": "storygen.manual-runtime/1",
                    "session_id": name,
                    "owner": process_identity(os.getpid()),
                    "server": process_identity(manager.process.pid),
                    "profile_sha256": digest(profile),
                    "code_commit": source_commit(root),
                    "actual": manager.actual,
                    "started_utc": utc(),
                    "state": "READY",
                }
                write_json(path, descriptor, exclusive=False)
                while manager.process.poll() is None:
                    time.sleep(0.25)
                raise StoryGenError("Manual model server exited; inspect its server log")
            finally:
                if path.exists():
                    value = read(path)
                    value.update(state="STOPPED", stopped_utc=utc())
                    write_json(path, value, exclusive=False)
                manager.stop()


class AttachedServer:
    """Same engine interface as ServerManager, with ownership checked at attachment."""

    def __init__(self, root, depot, profile, name):
        self.root, self.profile = Path(root), profile
        self.path = session_path(depot, name)
        self.process = None
        self.actual = {}
        self.role = None

    def validate(self):
        if not self.path.is_file():
            raise StoryGenError("Start E01-B server in Terminal 1 first")
        value = read(self.path)
        if (
            value.get("schema") != "storygen.manual-runtime/1"
            or value.get("state") != "READY"
            or value["profile_sha256"] != digest(self.profile)
            or value["code_commit"] != source_commit(self.root)
        ):
            raise StoryGenError("Manual server session profile/code/state mismatch")
        for key in ("owner", "server"):
            if process_identity(value[key]["pid"]) != value[key]:
                raise StoryGenError("Manual server session process identity expired")
        pid = value["server"]["pid"]
        cfg = self.profile["roles"]["measurement"]
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
        if (
            argv != cfg["command"]
            or Path(f"/proc/{pid}/exe").resolve() != Path(cfg["executable"]).resolve()
        ):
            raise StoryGenError("Manual server executable/argv mismatch")
        status = Path(f"/proc/{pid}/status").read_text().splitlines()
        parent = next(int(line.split()[1]) for line in status if line.startswith("PPid:"))
        if parent != value["owner"]["pid"]:
            raise StoryGenError("Manual server is not a child of the recorded StoryGen owner")
        return value

    @contextmanager
    def lease(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".client.lock").open("a+b") as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StoryGenError("Manual server already has an experiment client") from exc
            self.validate()
            yield

    def switch(self, role):
        if role != "measurement":
            raise StoryGenError("Manual E01-B runtime supports only measurement")
        value = self.validate()
        cfg = self.profile["roles"][role]
        for path, sha in (("model_path", "sha256"), ("executable", "executable_sha256")):
            if file_sha(cfg[path]) != cfg[sha]:
                raise StoryGenError("Manual runtime file changed: " + path)
        base = f"http://{cfg['host']}:{cfg['port']}"
        http_json(base + "/health")
        models, props = http_json(base + "/v1/models"), http_json(base + "/props")
        if (
            cfg["identity"] not in {m["id"] for m in models.get("data", [])}
            or props.get("total_slots") != 8
            or props.get("default_generation_settings", {}).get("n_ctx") != 12288
            or Path(props.get("model_path", "")).resolve() != Path(cfg["model_path"]).resolve()
        ):
            raise StoryGenError("Manual live server identity/context/slots mismatch")
        self.actual[role] = {
            **value["actual"][role],
            "manual_session": str(self.path),
            "session_started_utc": value["started_utc"],
            "attached_utc": utc(),
        }
        self.role = role

    def stop(self):
        # Terminal 1 retains ownership and is the only process allowed to stop it.
        self.role = None
