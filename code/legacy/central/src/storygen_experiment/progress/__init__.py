"""Observed work progress; ETA is UNKNOWN for unobserved resource classes."""

import json
import time
from storygen_experiment import runtime


def hms(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


class Progress:
    def __init__(
        self, root, experiment, run_id, stages, *, clock=time.monotonic, emit=True
    ):
        self.root, self.experiment, self.run_id, self.stages = (
            root,
            experiment,
            run_id,
            stages,
        )
        self.clock = clock
        self.start = clock()
        self.completed = 0
        self.done = set()
        self.samples = {}
        self.errors = 0
        self.emit = emit

    def key(self, s):
        return (s["adapter"]["kind"], s["provider"], s["resources"]["profile"])

    def update(self, current, status="RUNNING"):
        elapsed = self.clock() - self.start
        remaining = [s for s in self.stages if s["stage_id"] not in self.done]
        eta = "UNKNOWN"
        if status == "COMPLETE":
            eta = "00:00:00"
        elif remaining and all(self.key(s) in self.samples for s in remaining):
            eta = hms(
                sum(
                    self.samples[self.key(s)] * s["resources"]["work_units"]
                    for s in remaining
                )
            )
        value = dict(
            EXPERIMENT=self.experiment,
            RUN_ID=self.run_id,
            CURRENT_STAGE=current,
            COMPLETED_TASKS=self.completed,
            TOTAL_TASKS=sum(s["resources"]["work_units"] for s in self.stages),
            TASK_UNIT="declared pipeline work unit",
            ELAPSED_HHMMSS=hms(elapsed),
            ETA_HHMMSS=eta,
            ERROR_COUNT=self.errors,
            ARTIFACT_DIRECTORY=str(self.root),
            technical_status=status,
            utc=runtime.utc(),
        )
        runtime.atomic_json(self.root / "progress.json", value)
        with (self.root / "logs/progress.events.jsonl").open("a") as f:
            f.write(json.dumps(value) + "\n")
            f.flush()
        if self.emit:
            print(json.dumps(value), flush=True)
        return value

    def finish(self, stage, elapsed):
        self.done.add(stage["stage_id"])
        self.completed += stage["resources"]["work_units"]
        key = self.key(stage)
        sample = elapsed / stage["resources"]["work_units"]
        self.samples[key] = (
            sample if key not in self.samples else (self.samples[key] + sample) / 2
        )
