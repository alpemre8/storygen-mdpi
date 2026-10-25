"""Validate identities, instruments and coverage independently of calculations."""

from collections import Counter
from common import (
    BindingError,
    FEATURES,
    IDENTITY,
    same_task,
    numeric,
    target_direction,
    rewrite_identity,
)


def index_rows(rows):
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("INVALID_MEASUREMENT: expected scene-record list")
    keys = [(r.get("film_id"), r.get("scene_id")) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("IDENTITY_MISMATCH: duplicate film/scene records")
    return dict(zip(keys, rows, strict=True))


def row_error(row, canonical, *, after):
    checks = {
        "measurement_protocol_id": "measurement_protocol_id",
        "measurement_protocol_hash": "protocol_hash",
    }
    if after:
        checks.update(
            {
                k: k
                for k in (
                    "prompt_hash",
                    "schema_hash",
                    "system_instruction_hash",
                    "request_contract_hash",
                    "decoding_hash",
                )
            }
        )
    if any(row.get(key) != canonical[value] for key, value in checks.items()):
        return "MEASUREMENT_MISMATCH"
    if row.get("measurement_status", "measured") != "measured":
        return "INVALID_MEASUREMENT"
    if any(not numeric(row.get(f)) for f in FEATURES):
        return "INVALID_MEASUREMENT"
    return None


def validate_record(record, originals, canonical):
    task, artifacts = record["task"], record["artifacts"]
    ids, film = task["source_scene_ids"], task["source_film_id"]
    feature = task["selected_features"][0]
    directions = ["UNAVAILABLE"] * len(ids)
    reason = None
    try:
        archived = artifacts["task"]
        if archived is None or not same_task(task, archived):
            raise ValueError("IDENTITY_MISMATCH: archived task differs")
        plan = artifacts["plan"]
        if (
            plan is None
            or plan["run_id"] != task["task_id"]
            or plan["source_scene_ids"] != ids
            or plan["selected_features"] != [feature]
            or plan["reference_scene_ids"] != task["reference_scene_ids"]
        ):
            raise ValueError("IDENTITY_MISMATCH: transfer plan differs")
        directives = plan["per_scene_target_values"]
        if [r["scene_id"] for r in directives] != ids:
            raise ValueError("IDENTITY_MISMATCH: directive identity/order")
        deltas = [r["deltas"][feature] for r in directives]
        if any(type(d) not in (int, float) or not -1 <= d <= 1 for d in deltas):
            raise ValueError("IDENTITY_MISMATCH: invalid archived target delta")
        directions = [target_direction(d) for d in deltas]
        phase = artifacts["phase"]
        if phase is not None and (
            phase["task_id"] != task["task_id"]
            or phase["source_scene_ids"] != ids
            or phase["prompt_contract_id"] != record["condition"]
        ):
            raise ValueError("IDENTITY_MISMATCH: rewrite status metadata")
        rewrite = artifacts["rewrite"]
        if rewrite is None:
            reason = "MISSING_REWRITE"
        elif (
            rewrite["scene_ids"] != ids
            or phase is None
            or phase.get("rewrite_completed") is not True
        ):
            raise ValueError("IDENTITY_MISMATCH: rewrite scenes/order/status")
        elif artifacts["after"] is None:
            reason = "MISSING_REANALYSIS"
        else:
            status = artifacts["measurement_status"]
            if (
                status is None
                or status.get("measurement") != canonical
                or status.get("source_feature_measurement") != canonical
                or status.get("contract_equality_verified") is not True
            ):
                raise ValueError("MEASUREMENT_MISMATCH: task instrument attestation")
            if (
                status.get("source_rewrite_artifact_sha256")
                != rewrite_identity(record["artifact_refs"])
                or status.get("scene_ids") != ids
            ):
                raise ValueError(
                    "IDENTITY_MISMATCH: reanalysis input artifact/scene lineage"
                )
            if status.get("status") not in ("measured", "measurement_ineligible"):
                raise ValueError("INVALID_MEASUREMENT: unrecognized measurement status")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        reason = (
            str(exc)
            if str(exc).startswith(
                ("IDENTITY_MISMATCH", "MEASUREMENT_MISMATCH", "INVALID_MEASUREMENT")
            )
            else "IDENTITY_MISMATCH: malformed historical metadata"
        )
    label = directions[0] if len(set(directions)) == 1 else "MIXED"
    identity = dict(
        model=record["model"],
        condition=record["condition"],
        task_id=task["task_id"],
        base_interval_id=task["base_interval_id"],
        source_film_id=film,
        target_feature=feature,
        target_direction=label,
        interval_length=len(ids),
    )
    slots = []
    before_index = after_index = {}
    if reason is None:
        try:
            before_index = index_rows(originals[film])
            rows = artifacts["after"]
            after_index = index_rows(rows)
            observed = [r["scene_id"] for r in rows]
            original_order = [
                r["scene_id"] for r in originals[film] if r.get("scene_id") in ids
            ]
            if original_order != [i for i in ids if i in original_order]:
                raise ValueError("IDENTITY_MISMATCH: source measurement order")
            if any(
                r.get("film_id") != film or r.get("scene_id") not in ids for r in rows
            ) or observed != [i for i in ids if i in observed]:
                raise ValueError(
                    "IDENTITY_MISMATCH: unexpected scene/film or wrong order"
                )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            reason = (
                str(exc)
                if str(exc).startswith(("IDENTITY_MISMATCH", "INVALID_MEASUREMENT"))
                else "IDENTITY_MISMATCH: malformed scene list"
            )
    for order, scene_id in enumerate(ids, 1):
        before, after = (
            before_index.get((film, scene_id)),
            after_index.get((film, scene_id)),
        )
        error = reason
        if error is None:
            if before is None:
                error = "INVALID_MEASUREMENT: missing original measurement"
            elif after is None:
                error = "MISSING_SCENE_MEASUREMENT"
            else:
                error = row_error(before, canonical, after=False) or row_error(
                    after, canonical, after=True
                )
                # Source scene_index is global film order, not local interval position.
                if (
                    not error
                    and "scene_index" in before
                    and "scene_index" in after
                    and before["scene_index"] != after["scene_index"]
                ):
                    error = "IDENTITY_MISMATCH: scene_index differs"
        kind = (
            "VALID"
            if error is None
            else "MISSING"
            if error.startswith("MISSING")
            else "INVALID"
        )
        slots.append(
            dict(
                **identity,
                scene_id=scene_id,
                scene_order=order,
                scene_target_direction=directions[order - 1],
                pair_status=kind,
                reason=error,
                before=before if kind == "VALID" else None,
                after=after if kind == "VALID" else None,
            )
        )
    counts = Counter(s["pair_status"] for s in slots)
    valid, missing, invalid = (counts[k] for k in ("VALID", "MISSING", "INVALID"))
    if valid == len(ids):
        status = "COMPLETE"
    elif valid:
        status = "PARTIAL"
    else:
        status = (reason or slots[0]["reason"]).split(":")[0]
    summary = dict(
        **identity,
        status=status,
        reason=reason
        or ("Incomplete scene measurements" if status == "PARTIAL" else None),
        expected_scenes=len(ids),
        valid_scenes=valid,
        missing_scenes=missing,
        invalid_scenes=invalid,
        available_rewrite=artifacts["rewrite"] is not None,
        available_reanalysis=artifacts["after"] is not None,
    )
    return summary, slots


def validate(prepared, progress=None):
    tasks, slots, exclusions = [], [], []
    canonical = prepared["binding"]["measurement"]
    seen = set()
    for record in prepared["records"]:
        key = (record["model"], record["condition"], record["task"]["task_id"])
        if key in seen:
            raise BindingError("Duplicate planned model-condition-task record")
        seen.add(key)
        task, scenes = validate_record(record, prepared["originals"], canonical)
        tasks.append(task)
        slots.extend(scenes)
        if task["status"] != "COMPLETE":
            exclusions.append(
                dict(
                    **{k: task[k] for k in IDENTITY},
                    scene_id=None,
                    level="TASK",
                    status=task["status"],
                    reason=task["reason"] or task["status"],
                )
            )
        for scene in scenes:
            if scene["pair_status"] != "VALID":
                exclusions.append(
                    dict(
                        **{k: scene[k] for k in IDENTITY},
                        scene_id=scene["scene_id"],
                        level="SCENE",
                        status=scene["pair_status"],
                        reason=scene["reason"],
                    )
                )
        if progress:
            progress(tasks)
    return dict(
        schema_version="e05.feature-diff.validated/1.0",
        tasks=tasks,
        slots=slots,
        exclusions=exclusions,
        provenance=prepared["binding"],
    )
