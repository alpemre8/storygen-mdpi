"""Small deterministic, text-free E06 contracts. No inference dependencies."""

from dataclasses import dataclass
from pathlib import Path
import csv
import hashlib
import json
import math
import statistics
import unicodedata

FEATURES = {
    "pacing": "llm_pacing_score",
    "dialogue_density": "llm_dialogue_density_score",
    "action_density": "llm_action_density_score",
    "character_interaction": "llm_character_interaction_score",
    "emotion_intensity": "llm_emotion_intensity_score",
}
CONDITIONS = ("DP-v1", "CG-v1")
TOLERANCES = (0.0, 0.025, 0.05, 0.1)
THRESHOLDS = (0.0, 0.001, 0.01, 0.025, 0.05)
DIRECTIONS = ((-1, "DECREASE"), (0, "MAINTAIN"), (1, "INCREASE"))
MODULES = ("A01", "A02", "A03", "A04", "A05", "A06", "A07")


def sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError("Nonfinite JSON: " + x)
        ),
    )


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def csv_write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ["status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: json.dumps(v, sort_keys=True)
                    if isinstance(v, (dict, list))
                    else v
                    for k, v in row.items()
                }
            )


def index(rows, key="task_id"):
    result = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value or value in result:
            raise ValueError("Missing/duplicate identity: " + str(value))
        result[value] = row
    return result


def average(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def ratio(a, b):
    return a / b if b else None


def describe(xs):
    xs = sorted(xs)
    if any(not math.isfinite(x) for x in xs):
        raise ValueError("Nonfinite numerical result")

    def quantile(p):
        x = (len(xs) - 1) * p
        lo, hi = math.floor(x), math.ceil(x)
        return xs[lo] + (xs[hi] - xs[lo]) * (x - lo) if xs else None

    return dict(
        n=len(xs),
        mean=average(xs),
        median=quantile(0.5),
        sd=statistics.stdev(xs) if len(xs) > 1 else None,
        minimum=min(xs) if xs else None,
        maximum=max(xs) if xs else None,
        q05=quantile(0.05),
        q25=quantile(0.25),
        q75=quantile(0.75),
        q95=quantile(0.95),
    )


def words(text):
    """NFC normalization, Unicode whitespace-delimited nonempty tokens."""
    if not isinstance(text, str):
        return None
    return len(unicodedata.normalize("NFC", text).split())


@dataclass
class Dataset:
    tasks: list
    records: dict
    models: list
    provenance: dict
    validation: dict
    kind: str = "REAL"

    def rows(self, model, condition):
        return [self.records[model, condition][t["task_id"]] for t in self.tasks]

    def common(self):
        return [
            t["task_id"]
            for t in self.tasks
            if all(
                self.records[m, c][t["task_id"]]["eligible"]
                for m in self.models
                for c in CONDITIONS
            )
        ]
