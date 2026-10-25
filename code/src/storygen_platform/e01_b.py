"""Author-facing E01-B commands using the existing execution/approval engine."""

from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import importlib.util
import sys
import threading
import time
import traceback

from .engine import execution
from .engine.common import read, identifier, write_json

PHASES = ("B1", "B2", "B3")


def add_parser(sub):
    parser = sub.add_parser(
        "e01-b", help="Independent cross-model/precision measurement; real inference is author-run"
    )
    actions = parser.add_subparsers(dest="action", required=True)
    p = actions.add_parser("preflight", help="Offline only; no server/network/inference")
    p.add_argument("--phase", choices=PHASES)
    p.add_argument("--profile", type=Path)
    p = actions.add_parser("server", help="AUTHOR ONLY: start the original-config Mistral server")
    p.add_argument(
        "--phase",
        choices=PHASES,
        default="B1",
        help="Only validate this phase's inputs before starting; same server supports all phases",
    )
    p.add_argument("--profile", type=Path)
    p.add_argument("--session-id", default="e01-b-mistral-q4")
    p = actions.add_parser(
        "run", help="AUTHOR ONLY: feature extraction against the owned Terminal 1 session"
    )
    p.add_argument("--phase", choices=PHASES, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--session-id", default="e01-b-mistral-q4")
    p.add_argument("--profile", type=Path)
    p.add_argument("--resume", action="store_true")
    p = actions.add_parser(
        "report", help="Offline report from explicitly selected phase runs and historical controls"
    )
    p.add_argument("--report-id", required=True)
    p.add_argument(
        "--reviewer-analysis",
        action="store_true",
        help="Offline reviewer statistics and score agreement; requires B1, B2 and B3",
    )
    for phase in PHASES:
        p.add_argument("--" + phase.lower() + "-run")


def plugin(root, filename):
    spec = importlib.util.spec_from_file_location(
        "_sg_e01_b_cli_" + filename, root / "plugins/e01_b" / (filename + ".py")
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def duration(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"


class OneBar:
    def __init__(self, label, path, stream):
        self.label, self.path, self.stream = label, Path(path), stream
        self.stop_event = threading.Event()
        self.started = time.monotonic()
        self.completed = self.total = 0
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def render(self, *, final=False):
        observed = 0
        measured_elapsed = 0
        if self.path.exists():
            progress = read(self.path)
            self.completed, self.total = progress["completed"], progress["total"]
            observed = self.completed - progress.get("reused", 0)
            measured_elapsed = progress.get("elapsed_seconds", 0)
        elapsed = time.monotonic() - self.started
        eta = measured_elapsed * (self.total - self.completed) / observed if observed else 0
        percent = 100 * self.completed / self.total if self.total else 0
        filled = int(percent / 5)
        line = (
            f"{self.label} [{'█' * filled}{'░' * (20 - filled)}] {percent:.0f}% "
            f"({self.completed}/{self.total}) | Elapsed {duration(elapsed)} | ETA {duration(eta)}"
        )
        self.stream.write("\r" + line + ("\n" if final else ""))
        self.stream.flush()

    def watch(self):
        while not self.stop_event.wait(0.25):
            self.render()

    def __enter__(self):
        self.render()
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join()
        self.render(final=True)


def dispatch(args, root, depot, registry, original):
    from .cli import display, pin_foreground

    profile = (
        read(args.profile or root / "runtime_profiles/ComputerA.e01-b-mistral-q4.yaml")
        if args.action != "report"
        else None
    )
    plan_path = depot / "datasets/e01_b_cross_model_precision/inputs.json"
    if args.action in {"server", "run"}:
        pin_foreground(root, depot, original)
    if args.action in {"preflight", "server"}:
        validation = plugin(root, "inputs").validate(
            read(plan_path), depot, getattr(args, "phase", None)
        )
        checked = []
        for phase in [args.phase] if getattr(args, "phase", None) else PHASES:
            execution.preflight(
                root, depot, registry, "e01_" + phase.lower() + "_cross_model_precision", profile
            )
            checked.append(phase)
        if args.action == "preflight":
            display(
                {
                    **validation,
                    "technical_preflight": "PASS",
                    "implementation_approval": "PASS",
                    "phases": checked,
                    "server_started": False,
                    "network_used": False,
                }
            )
            return 0
        from .engine.manual_runtime import serve

        serve(root, depot, profile, args.session_id)
        return 0
    if args.action == "report":
        runs = {
            p: getattr(args, p.lower() + "_run")
            for p in PHASES
            if getattr(args, p.lower() + "_run")
        }
        display(
            plugin(root, "report").generate(
                root,
                depot,
                plan_path,
                runs,
                args.report_id,
                reviewer_analysis=args.reviewer_analysis,
            )
        )
        return 0
    run_id = identifier(args.run_id)
    key = "e01_" + args.phase.lower() + "_cross_model_precision"
    path = depot / "experiments" / key / "runs" / run_id
    logs = depot / "experiments/e01_b/logs"
    logs.mkdir(parents=True, exist_ok=True)
    # Capture every native/engine diagnostic. The saved original stream is used
    # exclusively by one progress renderer, including while inference is idle.
    stream = sys.stderr
    status = 2
    with (
        (logs / (run_id + ".log")).open("a") as log,
        OneBar("E01-" + args.phase, path / "e01_b_progress.json", stream),
    ):
        with redirect_stdout(log), redirect_stderr(log):
            try:
                _, result = execution.run(
                    root,
                    depot,
                    registry,
                    key,
                    profile,
                    mode="scientific",
                    run_id=run_id,
                    resume=args.resume,
                    manual_session=args.session_id,
                )
                write_json(logs / (run_id + ".result.json"), result, exclusive=False)
                status = 0 if result["execution_status"] == "COMPLETE" else 2
            except KeyboardInterrupt:
                traceback.print_exc(file=log)
                status = 130
            except Exception:
                traceback.print_exc(file=log)
                status = 2
    return status
