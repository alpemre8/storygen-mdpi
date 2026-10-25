"""User-triggered owned server lifecycle and machine-local GPU serialization."""

from pathlib import Path
from contextlib import contextmanager
import fcntl
import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from .common import StoryGenError, file_sha, utc


class TransportError(StoryGenError):
    pass


def process_identity(pid):
    """PID-reuse-safe identity; no signaling or termination of other processes."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "pid": pid,
            "start_ticks": stat[19],
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        }
    except (FileNotFoundError, ProcessLookupError):
        return None


@contextmanager
def queue_state(directory):
    from .common import read, write_json

    path = directory / "gpu.queue.json"
    with (directory / "gpu.queue.lock").open("a+b") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        state = read(path) if path.exists() else {"next_ticket": 0, "waiting": []}
        state["waiting"] = [
            ticket
            for ticket in state["waiting"]
            if process_identity(ticket["process"]["pid"]) == ticket["process"]
        ]
        try:
            yield state
        finally:
            write_json(path, state, exclusive=False)


@contextmanager
def gpu_lease(directory, owner, *, wait=False, timeout=3600):
    """FIFO tickets plus an OS lease; dead waiters never block future work."""
    import uuid

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    identity = process_identity(os.getpid())
    if identity is None:
        raise StoryGenError("Cannot establish process identity for GPU coordination")
    with queue_state(directory) as queue:
        ticket = {
            "token": token,
            "order": queue["next_ticket"],
            "owner": owner,
            "process": identity,
            "queued_utc": utc(),
        }
        queue["next_ticket"] += 1
        queue["waiting"].append(ticket)
    acquired = False
    try:
        with (directory / "gpu.lock").open("a+b") as stream:
            start = time.monotonic()
            while True:
                with queue_state(directory) as queue:
                    if queue["waiting"] and queue["waiting"][0]["token"] == token:
                        try:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            acquired = True
                            queue["waiting"].pop(0)
                        except BlockingIOError:
                            acquired = False
                if acquired:
                    break
                if not wait or time.monotonic() - start >= timeout:
                    raise StoryGenError(
                        "GPU busy: another StoryGen job owns or is queued for this machine; retry with --queue"
                    )
                time.sleep(0.05)
            stream.seek(0)
            stream.truncate()
            stream.write(
                json.dumps(
                    {
                        "process": identity,
                        "owner": owner,
                        "ticket": ticket["order"],
                        "acquired_utc": utc(),
                    }
                ).encode()
            )
            stream.flush()
            os.fsync(stream.fileno())
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        with queue_state(directory) as queue:
            queue["waiting"] = [t for t in queue["waiting"] if t["token"] != token]


def verify_profile(profile, resolved, *, hash_files=True):
    for role in resolved:
        cfg = profile["roles"][role]
        for key, hash_key in [("model_path", "sha256"), ("executable", "executable_sha256")]:
            p = Path(cfg.get(key, ""))
            if not p.is_file():
                raise StoryGenError(
                    f"Missing {role}.{key}: {p}; configure an existing operator-installed file"
                )
            if not cfg.get(hash_key):
                raise StoryGenError(f"Missing verified {role}.{hash_key}")
            if hash_files and file_sha(p) != cfg[hash_key]:
                raise StoryGenError(f"{role}.{key} SHA-256 mismatch")
        if not os.access(cfg["executable"], os.X_OK):
            raise StoryGenError(f"Backend is not executable: {cfg['executable']}")
        command = cfg.get("command", [])
        if not command or Path(command[0]).resolve() != Path(cfg["executable"]).resolve():
            raise StoryGenError("Server argv must start with the verified executable")
        # Every command option must be attested; scientific flags cannot hide in free argv.
        if cfg.get("command_sha256") is None:
            raise StoryGenError(f"Missing reviewed command_sha256 for {role}")
        from .common import digest

        if digest(command) != cfg["command_sha256"]:
            raise StoryGenError(f"Unreviewed backend command changed: {role}")
        if not cfg.get("identity") or not cfg.get("backend"):
            raise StoryGenError("Explicit serving identity and backend required")
        if cfg.get("backend", "").startswith("llama.cpp"):

            def argument(*flags):
                positions = [i for i, token in enumerate(command) if token in flags]
                if len(positions) != 1 or positions[0] + 1 >= len(command):
                    raise StoryGenError(f"Exact single backend option required: {flags}")
                return command[positions[0] + 1]

            if Path(argument("--model", "-m")).resolve() != Path(cfg["model_path"]).resolve():
                raise StoryGenError("Server argv model differs from verified weight file")
            if argument("--alias") != cfg["identity"]:
                raise StoryGenError("Server argv alias differs from fixed serving identity")
            if (
                argument("--host") != cfg.get("host", "127.0.0.1")
                or int(argument("--port")) != cfg["port"]
            ):
                raise StoryGenError("Server argv endpoint differs from verified profile")
            if "--offline" not in command or set(command) & {
                "--hf-repo",
                "-hf",
                "--model-url",
                "-mu",
                "--lora",
                "--mmproj",
            }:
                raise StoryGenError(
                    "Offline local weights only; undeclared weight downloads/adapters forbidden"
                )
            total = int(argument("--ctx-size", "-c"))
            slots = int(argument("--parallel", "-np"))
            if slots < 1 or total % slots:
                raise StoryGenError("Invalid backend context/slot budget")
            declared = resolved[role]["parameters"]
            if "context_per_slot" in declared and total // slots != declared["context_per_slot"]:
                raise StoryGenError("Backend argv violates fixed context_per_slot")
            if "context_size" in declared and total != declared["context_size"]:
                raise StoryGenError("Backend argv violates fixed context_size")
            sampler_flags = {
                "--temp": "temperature",
                "--top-p": "top_p",
                "--top-k": "top_k",
                "--seed": "seed",
                "--min-p": "min_p",
                "--n-predict": "max_tokens",
            }
            for flag, parameter in sampler_flags.items():
                if flag in command and (
                    parameter not in declared or float(argument(flag)) != declared[parameter]
                ):
                    raise StoryGenError(f"Backend argv overrides scientific sampler {parameter}")
        if cfg.get("scientific_runtime", {}) != {
            k: v
            for k, v in resolved[role]["parameters"].items()
            if k in {"context_size", "context_per_slot"}
        }:
            raise StoryGenError(f"Scientific context/runtime settings mismatch: {role}")
    return True


def http_json(url, *, payload=None, timeout=5):
    headers = {"Content-Type": "application/json"}
    raw = json.dumps(payload).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=raw, headers=headers), timeout=timeout
        ) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise TransportError(str(exc)) from exc


class ServerManager:
    def __init__(self, profile, log_root):
        self.profile = profile
        self.log_root = Path(log_root)
        self.process = None
        self.role = None
        self.log = None
        self.actual = {}

    def switch(self, role):
        if role == self.role and self.process and self.process.poll() is None:
            return
        self.stop()
        cfg = self.profile["roles"][role]
        for path_key, hash_key in [("model_path", "sha256"), ("executable", "executable_sha256")]:
            if file_sha(cfg[path_key]) != cfg[hash_key]:
                raise StoryGenError(f"Runtime file changed after preflight: {role}.{path_key}")
        from .common import digest

        if digest(cfg["command"]) != cfg["command_sha256"]:
            raise StoryGenError("Runtime argv changed after preflight")
        host, port = cfg.get("host", "127.0.0.1"), cfg["port"]
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise StoryGenError("Owned server must listen on loopback")
        # Never attach to, replace, or kill a pre-existing listener.
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
            except OSError as exc:
                raise StoryGenError(
                    f"Port {port} already occupied; existing service is untouched"
                ) from exc
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.log = (self.log_root / (role + ".server.log")).open("ab")
        try:
            self.process = subprocess.Popen(
                cfg["command"],
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.role = role
            deadline = time.monotonic() + cfg.get("startup_timeout", 120)
            url = f"http://{host}:{port}"
            while True:
                if self.process.poll() is not None:
                    raise StoryGenError("Owned server exited before readiness; inspect server log")
                try:
                    http_json(url + "/health")
                    models = http_json(url + "/v1/models")
                    identities = {m["id"] for m in models.get("data", [])}
                    if cfg["identity"] not in identities:
                        raise StoryGenError(
                            f"Server model identity mismatch: expected {cfg['identity']}"
                        )
                    native = cfg.get("native_profile")
                    if native is not None:
                        props = http_json(url + "/props")
                        if (
                            props.get("model_alias") != cfg["identity"]
                            or Path(props.get("model_path", "")).resolve()
                            != Path(cfg["model_path"]).resolve()
                            or props.get("total_slots") != native["parallel_slots"]
                            or props.get("default_generation_settings", {}).get("n_ctx")
                            != native["context_per_slot"]
                        ):
                            raise StoryGenError(
                                "Owned native server properties differ from frozen instrument runtime"
                            )
                    self.actual[role] = {
                        "pid": self.process.pid,
                        "identity": cfg["identity"],
                        "model_sha256": file_sha(cfg["model_path"]),
                        "executable_sha256": file_sha(cfg["executable"]),
                        "command": cfg["command"],
                        "backend": cfg["backend"],
                        "ready_utc": utc(),
                    }
                    return
                except TransportError:
                    if time.monotonic() >= deadline:
                        raise StoryGenError("Server readiness timeout") from None
                    time.sleep(0.05)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            self.process = None
        self.role = None
        if self.log is not None:
            self.log.close()
            self.log = None
