"""Small synthetic fixture only: unequal lengths, mixed signs, one failed cell."""

from common import Dataset, CONDITIONS, FEATURES
from storygen_evaluation.metrics import directional_accuracy, mae


def fixture():
    tasks = []
    models = ["fixture-model", "fixture-llama"]
    for i, feature in enumerate(FEATURES):
        n = 2 if i % 2 == 0 else 3
        tasks.append(
            dict(
                task_id=f"SYNTHETIC_T{i + 1}",
                base_interval_id=f"SYNTHETIC_B{i + 1}",
                screenplay_id="SYNTHETIC_SCREENPLAY",
                reference_screenplay_id="SYNTHETIC_REFERENCE",
                feature=feature,
                interval_length=n,
                scene_ids=[f"scene_{j}" for j in range(n)],
                reference_scene_ids=[f"ref_{j}" for j in range(n)],
                B=[0.5] * n,
                T=[0.5, 0.8, 0.2][:n],
                source_text_reference="fixture://source",
            )
        )
    records = {}
    for m in models:
        for c in CONDITIONS:
            rows = {}
            for i, t in enumerate(tasks):
                eligible = not (m == models[-1] and c == "CG-v1" and i == 0)
                after = (
                    [0.5, 0.7, 0.3][: t["interval_length"]]
                    if c == "DP-v1"
                    else [0.525, 0.75, 0.25][: t["interval_length"]]
                )
                db, da = mae(t["B"], t["T"]), mae(after, t["T"])
                pairs = [
                    dict(
                        scene_id=sid,
                        scene_position=j,
                        source_basis=b,
                        source_words=2,
                        rewrite_words=3,
                        length_ratio=1.5,
                        status="VALID",
                        was_truncated=False,
                        request_status="VERIFIED_REQUEST",
                        source_text_reference="fixture://source",
                        rewritten_text_reference="fixture://rewrite",
                        request_reference="fixture://request",
                    )
                    for j, sid in enumerate(t["scene_ids"])
                    for b in ("full_archived_source", "model_presented_source")
                ]
                rows[t["task_id"]] = dict(
                    t,
                    model=m,
                    condition=c,
                    eligible=eligible,
                    A=after if eligible else None,
                    TI=int(da < db) if eligible else None,
                    DA=directional_accuracy(t["B"], t["T"], after)
                    if eligible
                    else None,
                    dB=db if eligible else None,
                    dA=da if eligible else None,
                    G=db - da if eligible else None,
                    failure_classification="successful_and_measured"
                    if eligible
                    else "measurement_failure",
                    original_status=None
                    if eligible
                    else "reanalysis:synthetic_failure",
                    generation_status="recorded_rewrite",
                    measurement_status="measured" if eligible else "failed",
                    evaluation_records="fixture://ledger",
                    text_pairs=pairs,
                )
            records[m, c] = rows
    return Dataset(
        tasks,
        records,
        models,
        dict(input_files={}, absent_inputs=[]),
        dict(
            expected=dict(tasks=5, global_common=4),
            inputs_unchanged=True,
            replay_mismatches=[],
        ),
        "SYNTHETIC",
    )
