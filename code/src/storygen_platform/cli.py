"""The unified, no-inference-by-default StoryGen command line."""

from pathlib import Path
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from .engine.common import StoryGenError, digest, file_sha, read
from .engine.plugins import Registry
from .engine import dag, execution, scientific
from .engine.artifacts import RunStore

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def display(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False))


def duration(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"


def find_run(depot, run_id):
    from .engine.common import identifier

    identifier(run_id)
    found = [
        p
        for namespace in ("experiments", "analyses")
        for p in Path(depot).glob(f"{namespace}/*/runs/{run_id}/run.lock.json")
    ]
    if len(found) != 1:
        raise StoryGenError(
            f"Expected one run {run_id}; found {len(found)}; specify a globally unique ID"
        )
    return found[0].parent


def status_run(path):
    path = Path(path)
    lock = read(path / "run.lock.json")
    if lock["lock_sha256"] != digest(lock["identity"]):
        raise StoryGenError("Run lock checksum mismatch")
    store = RunStore(path)
    store.validate_logs()
    accepted = store.committed(lock["lock_sha256"])
    events = store.events.scan()
    start = datetime.datetime.fromisoformat(lock["created_utc"])
    assessment = next((e for e in reversed(events) if e["kind"] == "ASSESSMENT"), None)
    last_kind = events[-1]["kind"] if events else "ALLOCATED"
    terminal = assessment is not None and last_kind == "ASSESSMENT"
    end = (
        datetime.datetime.fromisoformat(assessment["utc"])
        if terminal
        else datetime.datetime.now(datetime.timezone.utc)
    )
    elapsed = (end - start).total_seconds()
    summary = read(path / assessment["evaluation"]) if terminal else None
    unit_plan = lock["identity"].get("unit_plan", {})
    expected = sum(len(v) for v in unit_plan.values())
    commits = [e for e in events if e["kind"] == "COMMITTED"]
    eta = "UNKNOWN"
    if terminal:
        eta = "00:00:00"
    elif len(commits) >= 3 and expected:
        # Estimate only within the current stage; later stages may use different models.
        stage = next((e["stage_id"] for e in reversed(events) if e.get("stage_id")), None)
        restarted = max(
            (i for i, e in enumerate(events) if e["kind"] in {"RUN_STARTED", "RESUMED"}), default=0
        )
        recent = events[restarted:]
        stage_commits = [e for e in recent if e["kind"] == "COMMITTED" and e["stage_id"] == stage]
        if len(stage_commits) >= 3:
            times = [datetime.datetime.fromisoformat(e["utc"]) for e in stage_commits]
            observed = (times[-1] - times[0]).total_seconds() / (len(times) - 1)
            eta = duration(observed * max(0, len(unit_plan.get(stage, [])) - len(stage_commits)))
    return {
        "expected_units": expected,
        "eta_scope": "current stage only; later model stages are unknown",
        "run_id": path.name,
        "experiment_id": lock["identity"]["experiment_id"],
        "stage": events[-1].get("stage_id", last_kind) if events else "ALLOCATED",
        "completed_units": len(accepted),
        "failed_attempts": sum(
            e["kind"] in {"FAILED", "VALIDATION_FAILED", "TRANSPORT_FAILED"} for e in events
        ),
        "elapsed": duration(elapsed),
        "eta": eta,
        "conditions": lock["identity"]["conditions"],
        "execution_status": summary["execution_status"] if summary else last_kind,
        "last_diagnostic": next((e.get("error") for e in reversed(events) if e.get("error")), None),
    }


def pin_foreground(root, depot, argv):
    """Exec from an exact detached source worktree before user-triggered execution."""
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if os.environ.get("STORYGEN_PINNED_COMMIT") == commit:
        return
    dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    if dirty.strip():
        raise StoryGenError("Commit source changes before starting a pinned foreground run")
    target = Path(depot) / ".run-sources" / commit
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "--quiet", "--detach", str(target), commit],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    pinned_head = subprocess.check_output(
        ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
    ).strip()
    if (
        pinned_head != commit
        or subprocess.check_output(
            ["git", "-C", str(target), "status", "--porcelain"], text=True
        ).strip()
    ):
        raise StoryGenError("Pinned source worktree changed; do not resume with drift")
    new_argv = list(argv)
    for option in ["--root", "--depot"]:
        if option in new_argv:
            i = new_argv.index(option)
            del new_argv[i : i + 2]
    args = [
        sys.executable,
        str(target / "bin/storygen"),
        "--root",
        str(target),
        "--depot",
        str(depot),
        *new_argv,
    ]
    os.execve(sys.executable, args, {**os.environ, "STORYGEN_PINNED_COMMIT": commit})


def parser():
    p = argparse.ArgumentParser(
        prog="storygen", description="StoryGen: immutable experiments, explicit scientific evidence"
    )
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--depot", type=Path, default=None)
    p.add_argument("--plugin-root", action="append", type=Path, default=[])
    sub = p.add_subparsers(dest="command", required=True)
    from .e01_b import add_parser as add_e01_b_parser

    add_e01_b_parser(sub)
    sub.add_parser("list")
    analyses = sub.add_parser("analyses")
    analyses.add_argument("action", choices=["list"])
    plug = sub.add_parser("plugins")
    plug.add_argument("action", choices=["list"])
    for cmd in ["inspect", "graph", "plan", "preflight", "approve", "run", "runs"]:
        c = sub.add_parser(cmd)
        c.add_argument("experiment", **({"nargs": "?"} if cmd == "runs" else {}))
        c.add_argument("--catalog", choices=["experiments", "analyses"], default="experiments")
        if cmd == "runs":
            c.add_argument("--historical", action="store_true")
        if cmd == "plan":
            c.add_argument("--parameter", action="append", default=[])
        if cmd == "graph":
            c.add_argument("--run")
            c.add_argument("--details", action="store_true")
        if cmd in {"preflight", "approve", "run"}:
            c.add_argument("--profile", type=Path)
        if cmd in {"preflight", "run"}:
            c.add_argument(
                "--stage", action="append", help="Explicit stage subset (DEV execution only)"
            )
            c.add_argument(
                "--source", action="append", default=[], metavar="STAGE.PORT=RUN_ID@DEPOT_PATH"
            )
        if cmd == "approve":
            c.add_argument("--evidence", type=Path, required=True)
        if cmd == "run":
            c.add_argument("--mode", choices=["dev", "scientific"], required=True)
            c.add_argument("--run-id")
            c.add_argument("--task-id", action="append")
            c.add_argument("--queue", action="store_true")
            c.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("resume")
    c.add_argument("run_id")
    c.add_argument("--queue", action="store_true")
    c = sub.add_parser("watch")
    c.add_argument("run_id")
    c.add_argument("--once", action="store_true")
    c.add_argument("--interval", type=float, default=2)
    c = sub.add_parser("status")
    c.add_argument("run_id", nargs="?")
    c = sub.add_parser("analyze")
    c.add_argument("analysis")
    c.add_argument("--source", action="append", required=True, type=Path)
    c.add_argument("--analysis-run-id")
    c = sub.add_parser(
        "historical", help="Hash-checked imported artifacts and recorded lineage; no inference"
    )
    c.add_argument(
        "action", choices=["inspect", "artifacts", "resolve", "verify", "lineage", "audit"]
    )
    c.add_argument("run_id", nargs="?")
    c.add_argument("--path", help="Exact depot-relative artifact path")
    c.add_argument("--role")
    c = sub.add_parser("report")
    c.add_argument("identity")
    c.add_argument("--run", required=True)
    c.add_argument("--format", choices=["ieee"], default="ieee")
    c.add_argument("--pdf", action="store_true")
    c = sub.add_parser("backup")
    c.add_argument("run_id")
    c.add_argument("--publish", action="store_true")
    c = sub.add_parser("recover-tail")
    c.add_argument("run_id")
    return p


def main(argv=None):
    original = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(original)
    root = args.root.resolve()
    depot = (args.depot or root.parent / "storygen-depot").resolve()
    try:
        registry = Registry([root / "plugins", *args.plugin_root])
        cmd = args.command
        if cmd == "e01-b":
            from .e01_b import dispatch

            return dispatch(args, root, depot, registry, original)
        elif cmd == "list":
            results = []
            for path in sorted((root / "experiments").glob("*/experiment.yaml")):
                m = read(path)
                results.append(
                    {
                        k: m.get(k)
                        for k in ["experiment_id", "display_name", "readiness", "description"]
                    }
                )
            display(results)
        elif cmd == "analyses":
            display([read(path) for path in sorted((root / "analyses").glob("*/analysis.yaml"))])
        elif cmd == "plugins":
            display(
                [
                    {**v.pin(), "state": v.state, "capabilities": list(v.manifest["capabilities"])}
                    for v in registry.providers.values()
                ]
            )
        elif cmd == "historical":
            from .historical import HistoricalCatalog

            catalog = HistoricalCatalog(depot)
            if args.action == "audit":
                display(
                    {
                        "runs": catalog.list(),
                        "unresolved_relations": catalog.index["unresolved_relations"],
                    }
                )
            elif args.action == "inspect":
                value = catalog.select(args.run_id)
                display({k: v for k, v in value.items() if k != "artifacts"})
            elif args.action == "artifacts":
                from dataclasses import asdict

                display([asdict(a) for a in catalog.artifacts(args.run_id, role=args.role)])
            elif args.action == "resolve":
                if not args.path:
                    raise StoryGenError("historical resolve requires an exact --path")
                ref = catalog.artifact(args.run_id, args.path)
                display(
                    {
                        "verified_path": str(ref.resolve(depot)),
                        "sha256": ref.sha256,
                        "bytes": ref.bytes,
                        "origin": ref.origin,
                        "run_id": ref.run_id,
                    }
                )
            elif args.action == "verify":
                display(
                    {"run_id": args.run_id, "verified": catalog.verify(args.run_id, role=args.role)}
                )
            else:
                display(catalog.lineage(args.run_id))
        elif cmd in {"inspect", "graph", "plan", "preflight", "approve", "run", "runs"}:
            key = args.experiment
            if (
                cmd == "runs"
                and args.historical
                and (depot / "migration/HISTORICAL_ARTIFACT_CATALOG.json").exists()
            ):
                from .historical import HistoricalCatalog

                display(
                    {
                        "experiment_id": key,
                        "historical_runs": HistoricalCatalog(depot).list(key),
                        "qualification": "HISTORICAL_IMPORTED; verified receipts/manifests; verify for all bytes",
                    }
                )
                return 0
            if key is None:
                raise StoryGenError("runs requires an experiment unless --historical is selected")
            home, definition, pipeline = execution.experiment(root, key, catalog=args.catalog)
            if cmd == "inspect":
                display({"experiment": definition, "pipeline": pipeline})
            elif cmd == "plan":
                inspection = definition.get("inspection")
                if inspection == {"type": "active_pipeline"}:
                    if args.parameter:
                        raise StoryGenError(
                            "Active scientific pipeline has no plan-time protocol overrides"
                        )
                    from .engine.inspection import describe

                    display(describe(root, depot, home, definition, pipeline, registry))
                elif inspection is None:
                    display(
                        {
                            "status": "DAG_VALID_NATIVE_BINDING_PENDING",
                            "nodes": dag.plan(pipeline, registry),
                            "qualification": "No verified native inspector is registered for this definition",
                        }
                    )
                else:
                    options = {}
                    for assignment in args.parameter:
                        if "=" not in assignment:
                            raise StoryGenError("Plan parameter must be NAME=VALUE")
                        name, value = assignment.split("=", 1)
                        if name in options:
                            raise StoryGenError("Duplicate plan parameter: " + name)
                        try:
                            options[name] = json.loads(value)
                        except json.JSONDecodeError:
                            options[name] = value
                    provider = registry.get(inspection["provider"], inspection["version"])
                    spec = provider.capability(inspection["capability"])
                    if spec["nature"] != "deterministic" or spec["resources"].get("gpu"):
                        raise StoryGenError(
                            "Read-only plan inspection cannot allocate inference resources"
                        )
                    from types import SimpleNamespace

                    context = SimpleNamespace(
                        operation="INSPECT_NO_INFERENCE",
                        code_root=root,
                        depot_root=depot,
                        configuration=options,
                    )
                    display(
                        provider.load()(
                            inspection["capability"], {"definition": definition}, context
                        )["plan"]
                    )
            elif cmd == "graph":
                nodes = dag.plan(pipeline, registry)
                result = {"experiment_id": key, "nodes": nodes, "files": []}
                if args.details:
                    if definition.get("inspection") == {"type": "active_pipeline"}:
                        from .engine.inspection import describe

                        result["resolved_pipeline"] = describe(
                            root, depot, home, definition, pipeline, registry
                        )
                    result["files"] = [
                        {"path": str(home / n), "sha256": file_sha(home / n)}
                        for n in ["experiment.yaml", "pipeline.yaml"]
                    ]
                    for n in nodes:
                        provider = registry.get(n["provider"])
                        result["files"].append(
                            {
                                "stage": n["id"],
                                "adapter": str(provider.adapter_path),
                                "sha256": file_sha(provider.adapter_path),
                                "provider": provider.pin(),
                            }
                        )
                    result["instruments"] = definition["instruments"]
                    result["historical"] = definition.get("historical")
                if args.run:
                    if args.run.startswith("H-"):
                        from .historical import HistoricalCatalog

                        historical = HistoricalCatalog(depot).lineage(args.run)
                        if historical["run"]["experiment"] != key:
                            raise StoryGenError(
                                "Selected historical run belongs to another experiment"
                            )
                        result["historical_source"] = historical
                        display(result)
                        return 0
                    run_path = find_run(depot, args.run)
                    lock = read(run_path / "run.lock.json")
                    if lock["identity"]["experiment_id"] != key:
                        raise StoryGenError("Selected run belongs to a different experiment")
                    result["run_lock"] = lock
                    result["events"] = RunStore(run_path).events.scan()
                display(result)
            elif cmd == "runs" and args.historical:
                historical_index = read(depot / "migration/HISTORICAL_RUN_INDEX.json")
                display(
                    {
                        "experiment_id": key,
                        "historical_runs": [
                            r for r in historical_index["runs"] if r["experiment_id"] == key
                        ],
                        "qualification": historical_index["scope"],
                    }
                )
            elif cmd == "runs":
                display(
                    [
                        status_run(p.parent)
                        for p in sorted(
                            (depot / args.catalog / key / "runs").glob("*/run.lock.json")
                        )
                    ]
                )
            else:
                profile = read(args.profile.resolve()) if args.profile else {"roles": {}}
                selection_args = {}
                if cmd in {"preflight", "run"} and (args.stage or args.source):
                    sources = {}
                    for source in args.source:
                        if "=" not in source or "@" not in source:
                            raise StoryGenError("--source requires STAGE.PORT=RUN_ID@DEPOT_PATH")
                        port, reference = source.split("=", 1)
                        if "." not in port or port in sources:
                            raise StoryGenError("Select each stage input port exactly once")
                        sources[port] = reference
                    selection_args = {"selected_stages": args.stage, "historical_sources": sources}
                context = execution.preflight(
                    root,
                    depot,
                    registry,
                    key,
                    profile,
                    require_approval=cmd != "approve",
                    catalog=args.catalog,
                    **selection_args,
                )
                if cmd == "approve":
                    display(
                        scientific.approval(depot, context["implementation"], read(args.evidence))
                    )
                elif cmd == "preflight" or args.dry_run:
                    display(
                        {
                            "status": "PREFLIGHT_READY",
                            "inference_performed": False,
                            "experiment_id": key,
                            "task_count": len(context["tasks"]),
                            "implementation": context["implementation"],
                            "resolved_conditions": context["resolved"],
                            "historical_sources": context.get("historical_sources", {}),
                            "selected_stages": [n["id"] for n in context["nodes"]],
                        }
                    )
                else:
                    pin_foreground(root, depot, original)
                    path, result = execution.run(
                        root,
                        depot,
                        registry,
                        key,
                        profile,
                        mode=args.mode,
                        run_id=args.run_id,
                        task_ids=args.task_id,
                        queue=args.queue,
                        catalog=args.catalog,
                        **selection_args,
                    )
                    from .backup import backup

                    result = {**result, "path": str(path), "backup_preflight": backup(depot, path)}
                    display(result)
        elif cmd == "resume":
            if args.run_id.startswith("H-"):
                raise StoryGenError(
                    "Historical imports cannot resume; select their artifacts as explicit inputs"
                )
            path = find_run(depot, args.run_id)
            lock = read(path / "run.lock.json")
            identity = lock["identity"]
            pin_foreground(root, depot, original)
            path, result = execution.run(
                root,
                depot,
                registry,
                identity["experiment_id"],
                identity["profile"],
                mode=identity["mode"],
                run_id=args.run_id,
                resume=True,
                task_ids=identity["exposed_task_ids"] or None,
                queue=args.queue,
                catalog=identity.get("catalog", "experiments"),
                **(
                    {
                        "selected_stages": identity.get("selected_stages"),
                        "historical_sources": identity["historical_sources"],
                    }
                    if "historical_sources" in identity
                    else {}
                ),
            )
            display({"path": str(path), **result})
        elif cmd == "status":
            display(
                status_run(find_run(depot, args.run_id))
                if args.run_id
                else [
                    status_run(p.parent)
                    for p in sorted(
                        p
                        for namespace in ("experiments", "analyses")
                        for p in depot.glob(f"{namespace}/*/runs/*/run.lock.json")
                    )
                ]
            )
        elif cmd == "watch":
            if args.interval <= 0:
                raise StoryGenError("Watch interval must be positive")
            while True:
                result = status_run(find_run(depot, args.run_id))
                display(result)
                if args.once or result["execution_status"] in {
                    "COMPLETE",
                    "PARTIAL",
                    "FAILED",
                    "INTERRUPTED",
                }:
                    break
                time.sleep(args.interval)
        elif cmd == "analyze":
            from .analysis import analyze

            method = read(root / "analyses" / args.analysis / "analysis.yaml")
            if method["method"] == "plugin-pipeline/1":
                pin_foreground(root, depot, original)
            path, result = analyze(root, depot, args.analysis, args.source, args.analysis_run_id)
            display({"path": str(path), **result})
        elif cmd == "report":
            if args.run.startswith("H-"):
                from .historical import HistoricalCatalog

                catalog = HistoricalCatalog(depot)
                if catalog.select(args.run)["experiment"] != args.identity:
                    raise StoryGenError("Historical report experiment/run identity mismatch")
                display(
                    {
                        "origin": "HISTORICAL_IMPORTED",
                        "reports": catalog.verify(args.run, role="report"),
                        "recomputed": False,
                    }
                )
                return 0
            from .reporting import render

            run_path = (
                find_run(depot, args.run)
                if (root / "experiments" / args.identity).exists()
                else depot / "analyses" / args.identity / "runs" / args.run
            )
            if (run_path / "run.lock.json").exists():
                lock = read(run_path / "run.lock.json")
                if lock["identity"]["experiment_id"] != args.identity:
                    raise StoryGenError("Report experiment/run identity mismatch")
                evidence = sorted(run_path.glob("evaluations/*.json"))[-1]
            else:
                evidence = run_path / "results.json"
            path, result = render(evidence, depot / "reports", pdf=args.pdf)
            display({"path": str(path), **result})
        elif cmd == "backup":
            from .backup import backup

            if args.publish:
                backup(depot, depot, publish=True)
            display(backup(depot, find_run(depot, args.run_id), publish=args.publish))
        elif cmd == "recover-tail":
            path = find_run(depot, args.run_id)
            store = RunStore(path)
            from .engine.artifacts import Journal, CorruptLog

            with store.writer():
                recovered = []
                for journal_path in [path / "events.jsonl", *path.glob("stages/*/*.jsonl")]:
                    journal = Journal(journal_path)
                    try:
                        journal.scan()
                    except CorruptLog:
                        recovered.append(str(journal.quarantine_tail()))
                display(
                    {"quarantines": recovered, "status": "REQUIRES_INTEGRITY_CHECK_BEFORE_RESUME"}
                )
        return 0
    except (
        StoryGenError,
        FileNotFoundError,
        FileExistsError,
        KeyError,
        IndexError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"storygen: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("storygen: interrupted; committed events remain recoverable", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
