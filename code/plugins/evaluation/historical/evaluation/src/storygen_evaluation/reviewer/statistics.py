"""New diagnostic estimands, explicitly separate from canonical TI/DA."""
from __future__ import annotations

from collections import defaultdict
import math
import unicodedata
import numpy as np

from ..metrics import directional_accuracy, signum
from . import ENDPOINT_ATOL, FEATURES, BlockedAnalysis


def average(values):
    values = [float(x) for x in values if x is not None]
    return sum(values) / len(values) if values else None


def distribution(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return {"n": 0, **{k: None for k in ("mean", "median", "min", "max", "q05", "q25", "q75", "q95")}}
    if not all(math.isfinite(x) for x in values):
        raise RuntimeError("Nonfinite diagnostic value")
    q = np.percentile(values, [5, 25, 50, 75, 95], method="linear").tolist()
    return dict(n=len(values), mean=average(values), median=q[2], min=min(values),
                max=max(values), q05=q[0], q25=q[1], q75=q[3], q95=q[4])


def distance(record):
    if not record["measurable"]:
        return {k: None for k in ("dB", "dA", "G", "absolute_G", "relative_G", "TI")}
    db, da = record["dB"], record["dA"]
    gain = db - da
    return dict(dB=db, dA=da, G=gain, absolute_G=abs(gain),
                relative_G=gain / db if db > 0 else None, TI=record["TI"])


def snap_endpoint(value, endpoints):
    # Diagnostic endpoints only: never called by canonical TI/DA or exact signs.
    return next((e for e in endpoints if abs(value - e) <= ENDPOINT_ATOL), value)


def gain_bin(gain):
    if gain <= 0:
        return "tie" if gain == 0 else "worse"
    x = snap_endpoint(gain, (.01, .05, .10))
    return "(0,.01]" if x <= .01 else "(.01,.05]" if x <= .05 else "(.05,.10]" if x <= .10 else ">.10"


def directions(task):
    return [signum(t - b) for b, t in zip(task["B"], task["T"])]


def tolerance_hits(record, tau):
    if not record["measurable"]:
        return None
    hits = []
    for b, t, a in zip(record["B"], record["T"], record["A"]):
        target = signum(t - b)
        if target == 0 and tau > 0:
            correct = abs(a - b) <= tau + ENDPOINT_ATOL
        else:
            correct = signum(a - b) == target
        hits.append(int(correct))
    if tau == 0 and average(hits) != directional_accuracy(record["B"], record["T"], record["A"]):
        raise RuntimeError("Maintain tolerance zero changed canonical DA")
    return hits


def analytic_floor(tasks):
    signs = [directions(t) for t in tasks]
    points = sum(map(len, signs))
    result = []
    for label, direction in (("increase", 1), ("maintain", 0), ("decrease", -1)):
        count = sum(s.count(direction) for s in signs)
        result.append(dict(policy="always_" + label, direction=label, tasks_n=len(tasks),
                           points_n=points, direction_points=count,
                           micro_DA=count / points if points else None,
                           macro_DA=average([s.count(direction) / len(s) for s in signs])))
    return result


def all_attempt(records):
    measured = [r for r in records if r["measurable"]]
    n = len(records)
    return dict(attempted_n=n, measurable_n=len(measured), failed_n=n - len(measured),
                coverage=len(measured) / n if n else None,
                conditional_TI=average([r["TI"] for r in measured]),
                conditional_DA=average([r["DA"] for r in measured]),
                ATI=sum(float(r["TI"]) for r in measured) / n if n else None,
                ADA_all=sum(r["DA"] for r in measured) / n if n else None)


def keyed_vectors(rows, scene_ids, label):
    if not isinstance(rows, list):
        raise BlockedAnalysis(f"Missing five-feature row list: {label}")
    if [r.get("scene_id") for r in rows] != scene_ids:
        raise RuntimeError(f"Five-feature scene ID/order mismatch: {label}")
    vectors = []
    for row in rows:
        vector = {}
        for axis, key in FEATURES.items():
            value = row.get(key)
            if value is None:
                raise BlockedAnalysis(f"Missing required off-target key {key}: {label} scene {row['scene_id']}")
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise RuntimeError(f"Invalid five-feature measurement: {label} {key}")
            vector[axis] = float(value)
        vectors.append(vector)
    return vectors


def off_target(record):
    if record.get("after_five") is None or record.get("source_five") is None:
        raise BlockedAnalysis(f"Missing five-feature vectors: {record.get('task_id')}")
    if len(record["source_five"]) != len(record["after_five"]) or not record["source_five"]:
        raise RuntimeError("Off-target source/after scene count mismatch")
    if any(set(v)!=set(FEATURES) for v in [*record["source_five"],*record["after_five"]]):
        raise BlockedAnalysis(f"Incomplete five-feature vector: {record.get('task_id')}")
    others = [f for f in FEATURES if f != record["selected_feature"]]
    signed = {f: [a[f] - b[f] for b, a in zip(record["source_five"], record["after_five"])] for f in others}
    values = [abs(x) for f in others for x in signed[f]]
    return {"mean_absolute_drift": average(values), "max_absolute_drift": max(values),
            "fraction_ge_0_1": average([x >= .1 - ENDPOINT_ATOL for x in values]),
            "fraction_ge_0_2": average([x >= .2 - ENDPOINT_ATOL for x in values]),
            "off_target_points_n": len(values), "signed": {f: average(signed[f]) for f in others},
            "absolute": {f: average([abs(x) for x in signed[f]]) for f in others}}


def text_counts(text):
    normalized = " ".join(unicodedata.normalize("NFC", str(text)).split())
    return dict(words=len(normalized.split()) if normalized else 0, characters=len(normalized))


def length_ratio(original, rewritten):
    a, b = text_counts(original), text_counts(rewritten)
    return {"original_words": a["words"], "rewritten_words": b["words"],
            "original_characters": a["characters"], "rewritten_characters": b["characters"],
            "word_ratio": b["words"] / a["words"] if a["words"] else None,
            "character_ratio": b["characters"] / a["characters"] if a["characters"] else None,
            "zero_original": a["words"] == 0, "empty_rewrite": b["words"] == 0}


def bootstrap(values, clusters, protocol_id, resamples=10000):
    """Draw represented clusters, retaining each cluster's task count as weight."""
    if len(values) != len(clusters) or any(not math.isfinite(float(v)) for v in values):
        raise RuntimeError("Invalid bootstrap values/clusters")
    groups = defaultdict(list)
    for value, key in zip(values, clusters):
        groups[str(key)].append(float(value))
    ids = sorted(groups)
    sizes = [len(groups[k]) for k in ids]
    result = dict(protocol_id=protocol_id, task_n=len(values), cluster_n=len(ids),
                  cluster_ids=ids, cluster_sizes=sizes, point=average(values), ci95=None,
                  ci_reason=None, seed=42, resamples=resamples, rng="NumPy PCG64/default_rng",
                  percentile="linear", estimator="sampled task sum / sampled task count",
                  small_cluster_warning=len(ids) < 10)
    if len(ids) < 2:
        result["ci_reason"] = "fewer_than_two_represented_clusters"
        return result
    if max(values) == min(values):
        result["ci_reason"] = "constant_task_deltas_degenerate_bootstrap"
        return result
    sums = np.array([sum(groups[k]) for k in ids])
    n = np.array(sizes)
    draws = np.random.default_rng(42).integers(0, len(ids), size=(resamples, len(ids)))
    samples = sums[draws].sum(axis=1) / n[draws].sum(axis=1)
    if float(np.ptp(samples)) == 0:
        result["ci_reason"] = "degenerate_resample_distribution"
    else:
        result["ci95"] = np.percentile(samples, [2.5, 97.5], method="linear").tolist()
    return result


def window_key(task):
    return task["source_film_id"] + ":" + ",".join(task["source_scene_ids"])


def overlap_components(tasks):
    windows = {window_key(t): t for t in tasks}
    parents = {key: key for key in windows}
    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    ordered = sorted(windows)
    for i, key in enumerate(ordered):
        a = windows[key]
        for other in ordered[:i]:
            b = windows[other]
            if a["source_film_id"] == b["source_film_id"] and set(a["source_scene_ids"]) & set(b["source_scene_ids"]):
                ra, rb = find(key), find(other)
                parents[max(ra, rb)] = min(ra, rb)
    return {t["task_id"]: find(window_key(t)) for t in tasks}
