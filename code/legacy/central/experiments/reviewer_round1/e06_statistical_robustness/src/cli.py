"""Researcher CLI: inventory/preflight are metadata-only; real run is explicit."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
from common import read
from loader import preflight
from pipeline import run
from reporting import report

HOME = Path(__file__).resolve().parent.parent
DEFAULT_BINDING = HOME / "historical_binding.json"
DEFAULT_DEPOT = (
    HOME.parents[3]
    / "storygen-experiment-depot/experiments/reviewer_round1/e06_statistical_robustness/runs"
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="E06_V1 deterministic analysis, no inference. Real analysis reserved for the human researcher."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("inventory", "preflight"):
        p = sub.add_parser(command)
        p.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    for command in ("dry-run", "run"):
        p = sub.add_parser(command)
        p.add_argument("--output", type=Path)
        p.add_argument(
            "--pdf",
            action="store_true",
            help="Use existing local IEEEtran/LaTeX only; never install",
        )
        if command == "run":
            p.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
            p.add_argument(
                "--human-run",
                action="store_true",
                required=True,
                help="Researcher explicitly starts the real analysis",
            )
    p = sub.add_parser("status")
    p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("report")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help="Fresh report directory")
    p.add_argument("--pdf", action="store_true")
    args = parser.parse_args(argv)
    if args.command in ("inventory", "preflight"):
        try:
            inputs, value = preflight(args.binding)
        except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
            missing = isinstance(exc, FileNotFoundError) or str(exc).startswith(
                "Unresolved artifact:"
            )
            print(
                json.dumps(
                    dict(
                        status="MISSING_INPUT" if missing else "INVALID_INPUT",
                        error_type=type(exc).__name__,
                        scientific_results="NOT_COMPUTED",
                        binding=str(args.binding),
                    ),
                    indent=2,
                )
            )
            return 2
        value["input_immutability"] = "PASS" if inputs.unchanged() else "FAIL"
        print(json.dumps(value, indent=2))
        return 0 if value["status"] == "PREFLIGHT_READY" else 2
    if args.command == "status":
        if not (args.run / "E06_STATUS.json").is_file():
            print(
                json.dumps(
                    dict(status={"status": "NOT_STARTED"}, progress=None), indent=2
                )
            )
            return 0
        print(
            json.dumps(
                dict(
                    status=read(args.run / "E06_STATUS.json"),
                    progress=read(args.run / "08_logs/PROGRESS.json")
                    if (args.run / "08_logs/PROGRESS.json").is_file()
                    else None,
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "report":
        print(json.dumps(report(args.run, args.output, args.pdf), indent=2))
        return 0
    output = args.output or DEFAULT_DEPOT / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + (
            "__SYNTHETIC_DRY_RUN"
            if args.command == "dry-run"
            else "__e06_full_analysis"
        )
    )
    if args.command == "run" and not output.resolve().is_relative_to(
        DEFAULT_DEPOT.resolve()
    ):
        parser.error(
            "Real runs must remain inside the central E06 depot: " + str(DEFAULT_DEPOT)
        )
    result = run(
        output, getattr(args, "binding", None), args.command == "dry-run", args.pdf
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
