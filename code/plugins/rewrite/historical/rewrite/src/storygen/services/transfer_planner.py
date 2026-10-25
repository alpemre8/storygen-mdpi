"""Deterministic structural-transfer planner for Sprint 4.

The planner turns two chart-selected intervals into a control plan. It does not
call an LLM, rewrite text, create a knowledge graph, or mutate the screenplay.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from storygen.schemas.transfer import SceneRewriteDirective, TransferPlan
from storygen.services.chart_data_service import CHART_FEATURES, resolve_default_feature_path

PLANNER_VERSION = "sprint4.transfer_planner.v1"

DEFAULT_SELECTED_FEATURES: list[str] = [
    "scene_length_score",
    "dialogue_ratio",
    "action_ratio",
    "character_density",
    "emotion_intensity",
    "tension_score",
    "semantic_novelty_score",
    "plot_movement_score",
]

PRESERVATION_CONSTRAINTS: list[str] = [
    "Preserve source character identities, names, and core relationships.",
    "Preserve the selected source interval's basic scene order and continuity.",
    "Preserve each source scene's main setting unless a later rewrite step explicitly validates a safe change.",
    "Preserve the source interval's core events and scene outcomes.",
    "Adapt only macro structure: pacing, dialogue/action balance, interaction density, emotion, tension, novelty, and plot movement.",
    "Do not introduce unrelated subplots, new major characters, or knowledge-graph-only details in Sprint 4.",
]

_FEATURE_LABELS: dict[str, str] = {
    "scene_length_score": "pacing / scene length",
    "dialogue_ratio": "dialogue density",
    "action_ratio": "visual action emphasis",
    "character_density": "character interaction density",
    "emotion_intensity": "emotional intensity",
    "tension_score": "tension",
    "semantic_novelty_score": "new information / novelty",
    "plot_movement_score": "plot movement",
    "llm_pacing_score": "LLM-estimated pacing",
    "llm_emotion_intensity_score": "LLM-estimated emotional intensity",
    "llm_dialogue_density_score": "LLM-estimated dialogue density",
    "llm_action_density_score": "LLM-estimated action density",
    "llm_character_interaction_score": "LLM-estimated character interaction",
}

_INCREASE_ACTIONS: dict[str, str] = {
    "scene_length_score": "expand pacing and give the beat more space",
    "dialogue_ratio": "increase dialogue density",
    "action_ratio": "increase visual action emphasis",
    "character_density": "broaden character interaction density",
    "emotion_intensity": "intensify emotional expression",
    "tension_score": "increase tension",
    "semantic_novelty_score": "introduce more meaningful new information",
    "plot_movement_score": "strengthen plot movement",
    "llm_pacing_score": "increase LLM-estimated pacing intensity",
    "llm_emotion_intensity_score": "increase LLM-estimated emotional intensity",
    "llm_dialogue_density_score": "increase dialogue density through more spoken exchanges and interaction beats",
    "llm_action_density_score": "increase physical action, movement, and externally visible event progression",
    "llm_character_interaction_score": "increase character-to-character interaction and relational exchange",
}

_DECREASE_ACTIONS: dict[str, str] = {
    "scene_length_score": "compress pacing and reduce scene length",
    "dialogue_ratio": "reduce explanatory dialogue density",
    "action_ratio": "reduce visual action emphasis",
    "character_density": "narrow character interaction density",
    "emotion_intensity": "soften emotional expression",
    "tension_score": "reduce immediate tension",
    "semantic_novelty_score": "limit new information and keep the beat familiar",
    "plot_movement_score": "soften plot movement",
    "llm_pacing_score": "decrease LLM-estimated pacing intensity",
    "llm_emotion_intensity_score": "decrease LLM-estimated emotional intensity",
    "llm_dialogue_density_score": "decrease dialogue density and rely more on concise non-verbal beats",
    "llm_action_density_score": "decrease physical action and keep event progression quieter",
    "llm_character_interaction_score": "decrease character-to-character interaction while preserving continuity",
}

_MAINTAIN_ACTIONS: dict[str, str] = {
    "scene_length_score": "maintain the current pacing scale",
    "dialogue_ratio": "maintain the current dialogue balance",
    "action_ratio": "maintain the current action balance",
    "character_density": "maintain the current interaction density",
    "emotion_intensity": "maintain the current emotional intensity",
    "tension_score": "maintain the current tension level",
    "semantic_novelty_score": "maintain the current novelty level",
    "plot_movement_score": "maintain the current plot movement level",
    "llm_pacing_score": "maintain the current LLM-estimated pacing level",
    "llm_emotion_intensity_score": "maintain the current LLM-estimated emotional intensity",
    "llm_dialogue_density_score": "maintain the current dialogue density",
    "llm_action_density_score": "maintain the current action density",
    "llm_character_interaction_score": "maintain the current character interaction density",
}


class TransferPlannerError(ValueError):
    """Raised when a transfer request cannot produce a valid plan."""


def load_feature_records(path: str | Path | None = None) -> tuple[list[dict[str, Any]], Path]:
    """Load extracted scene feature records from JSON."""

    feature_path = Path(path) if path is not None else resolve_default_feature_path()
    try:
        payload = json.loads(feature_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TransferPlannerError(f"Feature file does not exist: {feature_path}") from exc
    except json.JSONDecodeError as exc:
        raise TransferPlannerError(f"Invalid feature JSON: {feature_path}") from exc

    if not isinstance(payload, list):
        raise TransferPlannerError(f"Feature file must contain a JSON array: {feature_path}")

    records = [record for record in payload if isinstance(record, dict)]
    if not records:
        raise TransferPlannerError(f"Feature file contains no scene records: {feature_path}")

    records.sort(key=lambda record: _as_int(record.get("scene_index"), default=0))
    return records, feature_path


def create_transfer_plan(
    records: list[dict[str, Any]],
    *,
    source_start_scene_id: str,
    source_end_scene_id: str,
    reference_start_scene_id: str,
    reference_end_scene_id: str,
    selected_features: Iterable[str] | None = None,
    feature_source_path: str | Path = "<memory>",
    run_id: str | None = None,
) -> TransferPlan:
    """Create a deterministic macro-structure transfer plan from one feature file."""

    return create_transfer_plan_from_records(
        source_records=records,
        reference_records=records,
        source_start_scene_id=source_start_scene_id,
        source_end_scene_id=source_end_scene_id,
        reference_start_scene_id=reference_start_scene_id,
        reference_end_scene_id=reference_end_scene_id,
        selected_features=selected_features,
        feature_source_path=feature_source_path,
        reference_feature_source_path=feature_source_path,
        run_id=run_id,
    )


def create_transfer_plan_from_records(
    *,
    source_records: list[dict[str, Any]],
    reference_records: list[dict[str, Any]],
    source_start_scene_id: str,
    source_end_scene_id: str,
    reference_start_scene_id: str,
    reference_end_scene_id: str,
    selected_features: Iterable[str] | None = None,
    feature_source_path: str | Path = "<memory>",
    reference_feature_source_path: str | Path | None = None,
    run_id: str | None = None,
) -> TransferPlan:
    """Create a plan where source and reference intervals may come from different films."""

    ordered_source = sorted(source_records, key=lambda record: _as_int(record.get("scene_index"), default=0))
    ordered_reference = sorted(reference_records, key=lambda record: _as_int(record.get("scene_index"), default=0))
    feature_names = normalize_selected_features(selected_features)
    source_interval = _slice_interval(ordered_source, source_start_scene_id, source_end_scene_id, label="source")
    reference_interval = _slice_interval(ordered_reference, reference_start_scene_id, reference_end_scene_id, label="reference")

    source_scene_ids = [_scene_id(record) for record in source_interval]
    reference_scene_ids = [_scene_id(record) for record in reference_interval]

    source_curve: dict[str, list[float]] = {}
    reference_curve: dict[str, list[float]] = {}
    target_curve: dict[str, list[float]] = {}

    for feature in feature_names:
        source_values = [_feature_value(record, feature) for record in source_interval]
        reference_values = [_feature_value(record, feature) for record in reference_interval]
        source_curve[feature] = source_values
        reference_curve[feature] = reference_values
        target_curve[feature] = resample_curve(reference_values, len(source_interval))

    resolved_run_id = run_id or _stable_run_id(
        source_scene_ids=source_scene_ids,
        reference_scene_ids=reference_scene_ids,
        selected_features=feature_names,
        source_path=str(feature_source_path),
        reference_path=str(reference_feature_source_path or feature_source_path),
    )

    directives = [
        _build_scene_directive(record, index, feature_names, source_curve, target_curve)
        for index, record in enumerate(source_interval)
    ]

    return TransferPlan(
        run_id=resolved_run_id,
        feature_source_path=str(feature_source_path),
        reference_feature_source_path=str(reference_feature_source_path or feature_source_path),
        selected_features=feature_names,
        source_scene_ids=source_scene_ids,
        reference_scene_ids=reference_scene_ids,
        source_current_curve=source_curve,
        reference_curve=reference_curve,
        resampled_target_curve=target_curve,
        per_scene_target_values=directives,
        preservation_constraints=PRESERVATION_CONSTRAINTS,
        planner_version=PLANNER_VERSION,
    )


def create_transfer_plan_from_file(
    *,
    feature_path: str | Path | None,
    source_start_scene_id: str,
    source_end_scene_id: str,
    reference_start_scene_id: str,
    reference_end_scene_id: str,
    selected_features: Iterable[str] | None = None,
    run_id: str | None = None,
) -> TransferPlan:
    """Load one feature file and create a same-film transfer plan."""

    records, resolved_path = load_feature_records(feature_path)
    return create_transfer_plan(
        records,
        source_start_scene_id=source_start_scene_id,
        source_end_scene_id=source_end_scene_id,
        reference_start_scene_id=reference_start_scene_id,
        reference_end_scene_id=reference_end_scene_id,
        selected_features=selected_features,
        feature_source_path=resolved_path,
        run_id=run_id,
    )


def create_transfer_plan_from_feature_files(
    *,
    source_feature_path: str | Path,
    reference_feature_path: str | Path,
    source_start_scene_id: str,
    source_end_scene_id: str,
    reference_start_scene_id: str,
    reference_end_scene_id: str,
    selected_features: Iterable[str] | None = None,
    run_id: str | None = None,
) -> TransferPlan:
    """Load source/reference feature files and create a cross-film plan."""

    source_records, resolved_source_path = load_feature_records(source_feature_path)
    reference_records, resolved_reference_path = load_feature_records(reference_feature_path)
    return create_transfer_plan_from_records(
        source_records=source_records,
        reference_records=reference_records,
        source_start_scene_id=source_start_scene_id,
        source_end_scene_id=source_end_scene_id,
        reference_start_scene_id=reference_start_scene_id,
        reference_end_scene_id=reference_end_scene_id,
        selected_features=selected_features,
        feature_source_path=resolved_source_path,
        reference_feature_source_path=resolved_reference_path,
        run_id=run_id,
    )


def write_transfer_plan(plan: TransferPlan, output_path: str | Path) -> Path:
    """Write transfer plan JSON to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def normalize_selected_features(selected_features: Iterable[str] | None) -> list[str]:
    """Validate and normalize selected feature names."""

    if selected_features is None:
        candidates = DEFAULT_SELECTED_FEATURES
    else:
        candidates = [str(feature).strip() for feature in selected_features if str(feature).strip()]
        if not candidates:
            candidates = DEFAULT_SELECTED_FEATURES

    if len(candidates) == 1 and candidates[0].lower() in {"all", "macro", "core"}:
        candidates = DEFAULT_SELECTED_FEATURES

    allowed = set(CHART_FEATURES)
    normalized: list[str] = []
    invalid: list[str] = []
    for feature in candidates:
        if feature not in allowed:
            invalid.append(feature)
            continue
        if feature not in normalized:
            normalized.append(feature)

    if invalid:
        raise TransferPlannerError(
            f"Unsupported transfer feature(s): {', '.join(invalid)}. Allowed: {', '.join(CHART_FEATURES)}"
        )
    if not normalized:
        raise TransferPlannerError("No valid selected features were provided.")
    return normalized


def resample_curve(values: list[float], target_length: int) -> list[float]:
    """Linearly resample a curve to the target length."""

    if target_length <= 0:
        raise TransferPlannerError("Target curve length must be positive.")
    if not values:
        raise TransferPlannerError("Cannot resample an empty reference curve.")

    clean_values = [_clamp01(value) for value in values]
    if target_length == len(clean_values):
        return [_round(value) for value in clean_values]
    if len(clean_values) == 1:
        return [_round(clean_values[0]) for _ in range(target_length)]
    if target_length == 1:
        midpoint = (len(clean_values) - 1) / 2.0
        return [_round(_interpolate(clean_values, midpoint))]

    scale = (len(clean_values) - 1) / (target_length - 1)
    return [_round(_interpolate(clean_values, index * scale)) for index in range(target_length)]


def _slice_interval(records: list[dict[str, Any]], start_scene_id: str, end_scene_id: str, *, label: str) -> list[dict[str, Any]]:
    scene_to_index = {_scene_id(record): index for index, record in enumerate(records)}
    if start_scene_id not in scene_to_index:
        raise TransferPlannerError(f"Unknown {label} start scene id: {start_scene_id}")
    if end_scene_id not in scene_to_index:
        raise TransferPlannerError(f"Unknown {label} end scene id: {end_scene_id}")

    start_index = scene_to_index[start_scene_id]
    end_index = scene_to_index[end_scene_id]
    if end_index < start_index:
        raise TransferPlannerError(
            f"Invalid {label} interval: end scene {end_scene_id} comes before start scene {start_scene_id}"
        )
    return records[start_index : end_index + 1]


def _build_scene_directive(
    record: dict[str, Any],
    index: int,
    feature_names: list[str],
    source_curve: dict[str, list[float]],
    target_curve: dict[str, list[float]],
) -> SceneRewriteDirective:
    current_values = {feature: source_curve[feature][index] for feature in feature_names}
    targets = {feature: target_curve[feature][index] for feature in feature_names}
    deltas = {feature: _round(targets[feature] - current_values[feature]) for feature in feature_names}
    directive = _directive_sentence(deltas)

    return SceneRewriteDirective(
        scene_id=_scene_id(record),
        scene_index=_as_int(record.get("scene_index"), default=index + 1),
        title=str(record.get("title", "")),
        current_values=current_values,
        targets=targets,
        deltas=deltas,
        directive=directive,
    )


def _directive_sentence(deltas: dict[str, float]) -> str:
    actions: list[str] = []
    for feature, delta in deltas.items():
        if delta > 0:
            actions.append(_INCREASE_ACTIONS.get(feature, f"increase {_FEATURE_LABELS.get(feature, feature)}"))
        elif delta < 0:
            actions.append(_DECREASE_ACTIONS.get(feature, f"decrease {_FEATURE_LABELS.get(feature, feature)}"))
        else:
            actions.append(_MAINTAIN_ACTIONS.get(feature, f"maintain {_FEATURE_LABELS.get(feature, feature)}"))

    # Keep directives readable when all macro features are selected.
    prioritized = _dedupe(actions)[:5]
    body = "; ".join(prioritized)
    return f"{body}; preserve source characters, continuity, setting, core events, and scene outcome."


def _stable_run_id(*, source_scene_ids: list[str], reference_scene_ids: list[str], selected_features: list[str], source_path: str = "", reference_path: str = "") -> str:
    payload = json.dumps(
        {
            "source_scene_ids": source_scene_ids,
            "reference_scene_ids": reference_scene_ids,
            "selected_features": selected_features,
            "source_path": source_path,
            "reference_path": reference_path,
            "planner_version": PLANNER_VERSION,
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"transfer_{digest}"


def _feature_value(record: dict[str, Any], feature: str) -> float:
    return _round(_clamp01(_as_float(record.get(feature), default=0.0)))


def _scene_id(record: dict[str, Any]) -> str:
    scene_id = str(record.get("scene_id", "")).strip()
    if not scene_id:
        raise TransferPlannerError("Feature record is missing scene_id.")
    return scene_id


def _interpolate(values: list[float], position: float) -> float:
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _clamp01(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _round(value: float) -> float:
    return round(float(value), 6)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
