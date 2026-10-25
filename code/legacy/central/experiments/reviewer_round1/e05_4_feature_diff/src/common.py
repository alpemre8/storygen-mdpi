"""E05_4_FEATURE_DIFF_V1 numerical and serialization contracts (1.0.0)."""

from pathlib import Path
import hashlib
import json
import math

VERSION = "1.0.0"
FEATURES = (
    "llm_pacing_score",
    "llm_dialogue_density_score",
    "llm_action_density_score",
    "llm_character_interaction_score",
    "llm_emotion_intensity_score",
)
SHORT = ("pacing", "dialogue", "action", "character", "emotion")
MODELS = ("qwen25_7b", "llama31_8b", "qwen35_9b", "gemma3_12b")
LABELS = ("Qwen2.5-7B", "Llama-3.1-8B", "Qwen3.5-9B", "Gemma-3-12B")
CONDITIONS = ("DP-v1", "CG-v1")
EPSILON = 1e-12
SEED = 250504
REPLICATIONS = 2000
IDENTITY = (
    "model",
    "condition",
    "task_id",
    "base_interval_id",
    "source_film_id",
    "target_feature",
    "target_direction",
    "interval_length",
)
TASK_FIELDS = (
    "task_id",
    "base_interval_id",
    "source_film_id",
    "reference_film_id",
    "source_scene_ids",
    "reference_scene_ids",
    "selected_features",
)


class BindingError(ValueError):
    """Broken experiment binding: never a normal historical failure."""


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise BindingError("Duplicate JSON key: " + k)
            result[k] = v
        return result

    def finite_float(token):
        value = float(token)
        return value if math.isfinite(value) else {"invalid_numeric_token": token}

    # Transport malformed numeric tokens as explicit invalid markers, never scores.
    # VALIDATE rejects them; PREPARE can still write standards-compliant JSON.
    return json.loads(
        Path(path).read_text(),
        object_pairs_hook=unique,
        parse_float=finite_float,
        parse_constant=lambda token: {"invalid_numeric_token": token},
    )


def write(path, value):
    # All owned scientific output is create-only, even inside an unsealed run.
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def direction(delta):
    return (
        "INCREASE"
        if delta > EPSILON
        else "DECREASE"
        if delta < -EPSILON
        else "UNCHANGED"
    )


def target_direction(delta):
    # Historical transfer_planner.v1 uses exact sign, not the outcome epsilon.
    return "INCREASE" if delta > 0 else "DECREASE" if delta < 0 else "MAINTAIN"


def same_task(left, right):
    return all(left.get(k) == right.get(k) for k in TASK_FIELDS)


def rewrite_identity(refs):
    # Frozen feature-extraction io.sha256_json format, data identity only.
    value = {
        name: refs[key]["sha256"]
        for name, key in [
            ("rewritten_scenes.json", "rewrite"),
            ("transfer_plan.json", "plan"),
        ]
        if refs[key]["sha256"] is not None
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
