"""Central experiment discovery, exact planning, execution and artifact verification."""

from pathlib import Path
import argparse
import json
import time
from storygen_experiment import (
    ROOT,
    runtime,
    registry,
    planning,
    orchestration,
)
from storygen_experiment.artifact_store import run_root, status, recover
from storygen_experiment.verification import verify_run as verify


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--workspace", type=Path)
    p.add_argument("--depot", type=Path)
    p.add_argument("--cache", type=Path)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    s = sub.add_parser("catalog")
    s.add_argument("--check", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("experiment_id")
    for action in [
        "plan",
        "doctor",
        "preflight",
        "run",
        "status",
        "verify",
        "verify-storage",
        "artifacts",
        "recover",
        "resume",
        "watch",
    ]:
        s = sub.add_parser(action)
        s.add_argument("experiment_id")
        s.add_argument("--config", type=Path)
        s.add_argument("--run-id", default="plan_only")
        s.add_argument("--from-run")
        s.add_argument("--interval", type=float, default=2)
        if action in {"run", "resume"}:
            s.add_argument(
                "--full-manifest",
                action="store_true",
                help="Print the entire terminal manifest rather than the compact execution summary",
            )
    args = p.parse_args(argv)
    root = args.repo.resolve()
    workspace = (args.workspace or root.parent).resolve()
    depot = (args.depot or workspace / "storygen-experiment-depot").resolve()
    try:
        if args.action == "list":
            result = [
                dict(
                    **v["manifest"],
                    pipeline_stages=[s["stage_id"] for s in v["pipeline"]["stages"]],
                )
                for v in registry.discover(root)
            ]
        elif args.action == "catalog":
            text = registry.catalog(root, depot)
            path = root / "EXPERIMENTS.md"
            if args.check:
                if not path.exists() or path.read_text() != text:
                    raise ValueError("Catalog is stale")
            else:
                registry.update_catalog(root, depot)
            result = dict(catalog=str(path), sha256=runtime.canonical(text))
        else:
            value = registry.get(args.experiment_id, root)
            m = value["manifest"]
            path = run_root(
                depot,
                m["group_id"],
                m["experiment_id"],
                getattr(args, "run_id", "plan_only"),
            )
            if args.action == "show":
                result = dict(
                    experiment=m,
                    pipeline=value["pipeline"],
                    directory=str(value["home"]),
                )
            elif args.action in {
                "status",
                "verify",
                "verify-storage",
                "artifacts",
                "recover",
                "watch",
            }:
                if args.action == "watch":
                    while True:
                        result = status(path)
                        print(json.dumps(result), flush=True)
                        if result["execution_status"] != "RUNNING":
                            break
                        time.sleep(max(0.1, args.interval))
                elif args.action == "recover":
                    result = recover(path)
                elif args.action == "status":
                    result = status(path)
                else:
                    result = verify(path)
                    if args.action == "artifacts":
                        result["artifacts"] = json.loads(
                            (path / "run_manifest.json").read_text()
                        )["artifacts"]
                    if args.action == "verify-storage":
                        result.update(
                            raw_storage="LOCAL_NOT_BACKED_UP",
                            metadata_storage="GIT_SANITIZED_INDICES",
                            warning="Git metadata is not a backup of ignored raw scientific bytes",
                        )
            else:
                config = registry.read(args.config) if args.config else None
                if config is None:
                    result = dict(
                        status="BINDINGS_REQUIRED",
                        experiment=m,
                        required_inputs=value["pipeline"]["inputs"],
                        detail="No run/preflight readiness is claimed without exact configuration",
                    )
                    print(json.dumps(result, indent=2))
                    return 0 if args.action == "plan" else 2
                if args.action in {"run", "resume"} and args.run_id == "plan_only":
                    raise ValueError("Explicit fresh run ID required")
                if args.action == "resume":
                    if not args.from_run:
                        raise ValueError("Fresh successor requires --from-run")
                    parent = run_root(
                        depot, m["group_id"], m["experiment_id"], args.from_run
                    )
                    old = status(parent)
                    if old["execution_status"] == "RUNNING":
                        raise RuntimeError("Cannot resume a live run")
                    if old["execution_status"] == "INTERRUPTED_UNSEALED":
                        recover(parent)
                    verify(parent)
                    old_lock = json.loads((parent / "run.lock.json").read_text())

                    def base(value):
                        return {k: x for k, x in value.items() if k != "parent_run_ids"}

                    if runtime.canonical(
                        base(old_lock["configuration"])
                    ) != runtime.canonical(base(config)):
                        raise ValueError(
                            "Successor configuration mismatch; create a separate explicit protocol/run instead"
                        )
                    config = {
                        **config,
                        "parent_run_ids": [
                            *config.get("parent_run_ids", []),
                            args.from_run,
                        ],
                    }
                c = planning.plan(
                    args.experiment_id,
                    config,
                    args.run_id,
                    repo=root,
                    workspace=workspace,
                    depot=depot,
                    cache=args.cache,
                )
                if args.action in {"run", "resume"}:
                    result = orchestration.execute(c)
                    registry.update_catalog(root, depot)
                else:
                    from storygen_experiment import adapters

                    adapter_state = adapters.prepare(c)
                    adapters.stop(adapter_state)
                    result = dict(
                        status="PLAN_READY",
                        run_id=args.run_id,
                        artifact_directory=str(c["root"]),
                        stages=c["stages"],
                        resolved_providers=c["resolved_providers"],
                        checks=[
                            "contracts",
                            "source/component/environment/input/model hashes",
                            "fresh central run namespace",
                        ],
                    )
        if args.action in {"run", "resume"} and not args.full_manifest:
            result = {
                **{
                    key: result[key]
                    for key in [
                        "experiment_id",
                        "run_id",
                        "protocol_id",
                        "execution_status",
                        "contract_status",
                        "scientific_validity",
                        "purpose",
                    ]
                },
                "completed_stages": sum(
                    s["status"] == "COMPLETE" for s in result["stages"]
                ),
                "artifact_count": len(result["artifacts"]),
                "error_count": len(result["errors"]),
                "artifact_directory": str(path),
                "manifest": str(path / "run_manifest.json"),
                "storage": result["storage"],
            }
        print(json.dumps(result, indent=2))
        state = result.get("execution_status") if isinstance(result, dict) else None
        return (
            0 if state not in {"FAILED", "INTERRUPTED", "INTERRUPTED_UNSEALED"} else 1
        )
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps(dict(status="BLOCKED", error=repr(exc)), indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
