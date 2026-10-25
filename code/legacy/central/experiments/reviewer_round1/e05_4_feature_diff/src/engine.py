"""Four deterministic responsibilities. This module cannot execute inference."""

from pathlib import Path
from collections import Counter
import argparse
import json
import time
from common import read, write
from bindings import prepare, resolve
from validate import validate
from analyze import calculate
from aggregate import aggregate
from report import render


def elapsed(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "stage", choices=("binding-check", "prepare", "validate", "analyze", "report")
    )
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.stage == "binding-check":
        binding, tasks, _ = resolve(args.input, sample_only=True)
        counts = []
        for c in binding["combinations"]:
            counts.append(
                dict(
                    model=c["model"],
                    condition=c["condition"],
                    planned_tasks=240,
                    available_rewrite_tasks=sum(
                        v["rewrite"]["sha256"] is not None for v in c["tasks"].values()
                    ),
                    available_reanalysis_tasks=sum(
                        v["after"]["sha256"] is not None for v in c["tasks"].values()
                    ),
                    historical_rewrite_completed=c["historical_rewrite_completed"],
                    historical_reanalysis_completed=c[
                        "historical_reanalysis_completed"
                    ],
                )
            )
        print(
            json.dumps(
                dict(
                    status="INPUT_BINDINGS_READY",
                    validation_scope="Global manifests, full frozen task definitions, original films, one archived task per combination; no real feature differences calculated",
                    planned_records=len(tasks) * 8,
                    planned_scene_slots=16000,
                    coverage_inventory=counts,
                )
            )
        )
        return
    if args.output is None:
        p.error("--output required for central stages")
    started = time.monotonic()
    if args.stage == "prepare":
        write(args.output / "prepared.json", prepare(args.input))
    elif args.stage == "validate":

        def progress(tasks):
            if len(tasks) % 40 == 0 or len(tasks) == 1920:
                counts = Counter(t["status"] for t in tasks)
                spent = time.monotonic() - started
                print(
                    json.dumps(
                        dict(
                            combinations=8,
                            planned_tasks=1920,
                            processed_tasks=len(tasks),
                            complete_tasks=counts["COMPLETE"],
                            partial_tasks=counts["PARTIAL"],
                            missing_tasks=sum(
                                n for s, n in counts.items() if s.startswith("MISSING")
                            ),
                            invalid_tasks=sum(
                                n
                                for s, n in counts.items()
                                if s not in ("COMPLETE", "PARTIAL")
                                and not s.startswith("MISSING")
                            ),
                            elapsed=elapsed(spent),
                            ETA=elapsed(spent / len(tasks) * (1920 - len(tasks))),
                        ),
                        sort_keys=True,
                    ),
                    flush=True,
                )

        write(args.output / "validated.json", validate(read(args.input), progress))
    elif args.stage == "analyze":
        source = read(args.input)
        scenes, tasks = calculate(source)
        write(args.output / "analysis.json", aggregate(source, scenes, tasks))
    else:
        render(args.output, read(args.input))


if __name__ == "__main__":
    main()
