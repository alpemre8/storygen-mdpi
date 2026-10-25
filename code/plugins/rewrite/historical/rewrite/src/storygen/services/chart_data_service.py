"""Chart data loading helpers for line-chart feature endpoints.

The service reads already extracted feature JSON. Chart endpoints must not
trigger model inference, embedding generation, or rewrite actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from storygen.schemas.chart import ChartDataset, ChartPoint, FeatureCatalog

DEFAULT_FEATURE_PATHS = [
    Path("data/features/scene_features.json"),
    Path(".artifacts/features/scene_features_sprint2.json"),
    Path(".artifacts/features/scene_features_sprint1.json"),
]

BASE_CHART_FEATURES: list[str] = [
    "scene_length_score",
    "dialogue_ratio",
    "action_ratio",
    "character_density",
    "emotion_intensity",
    "tension_score",
    "semantic_novelty_score",
    "plot_movement_score",
]

LEVEL2_CHART_FEATURES: list[str] = [
    "hybrid_tension_score",
    "hybrid_emotion_intensity",
    "classifier_tension_score",
    "classifier_emotion_score",
    "classifier_sentiment_score",
    "scene_function_score",
    "scene_risk_score",
]

LEVEL3_CHART_FEATURES: list[str] = [
    "llm_pacing_score",
    "llm_tension_score",
    "llm_dialogue_density_score",
    "llm_action_density_score",
    "llm_emotion_intensity_score",
    "llm_plot_movement_score",
    "llm_character_interaction_score",
    "llm_confidence",
]

FINAL_CHART_FEATURES: list[str] = [
    "final_pacing_score",
    "final_tension_score",
    "final_dialogue_ratio",
    "final_action_ratio",
    "final_emotion_intensity",
    "final_plot_movement_score",
    "final_character_density",
]

CHART_FEATURES: list[str] = BASE_CHART_FEATURES + LEVEL2_CHART_FEATURES + LEVEL3_CHART_FEATURES + FINAL_CHART_FEATURES

FEATURE_LABELS: dict[str, str] = {
    "scene_length_score": "Pacing / Scene Length",
    "dialogue_ratio": "Dialogue Ratio",
    "action_ratio": "Action Ratio",
    "character_density": "Character Density",
    "emotion_intensity": "Emotion Intensity",
    "tension_score": "Tension Score",
    "semantic_novelty_score": "Semantic Novelty",
    "plot_movement_score": "Plot Movement",
    "hybrid_tension_score": "Hybrid Tension",
    "hybrid_emotion_intensity": "Hybrid Emotion Intensity",
    "classifier_tension_score": "Classifier Tension",
    "classifier_emotion_score": "Classifier Emotion Confidence",
    "classifier_sentiment_score": "Classifier Sentiment Confidence",
    "scene_function_score": "Scene Function Confidence",
    "scene_risk_score": "Scene Risk Confidence",
    "llm_pacing_score": "LLM Pacing",
    "llm_tension_score": "LLM Tension",
    "llm_dialogue_density_score": "LLM Dialogue Density",
    "llm_action_density_score": "LLM Action Density",
    "llm_emotion_intensity_score": "LLM Emotion Intensity",
    "llm_plot_movement_score": "LLM Plot Movement",
    "llm_character_interaction_score": "LLM Character Interaction",
    "llm_confidence": "LLM Confidence",
    "final_pacing_score": "Final Pacing",
    "final_tension_score": "Final Tension",
    "final_dialogue_ratio": "Final Dialogue Ratio",
    "final_action_ratio": "Final Action Ratio",
    "final_emotion_intensity": "Final Emotion Intensity",
    "final_plot_movement_score": "Final Plot Movement",
    "final_character_density": "Final Character Density",
}


def get_feature_catalog() -> FeatureCatalog:
    return FeatureCatalog(
        default_feature="tension_score",
        features=CHART_FEATURES,
        labels=FEATURE_LABELS,
    )


def resolve_default_feature_path() -> Path:
    for candidate in DEFAULT_FEATURE_PATHS:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(path) for path in DEFAULT_FEATURE_PATHS)
    raise FileNotFoundError(f"No extracted feature file found. Searched: {searched}")


def load_chart_dataset(
    path: str | Path | None = None,
    *,
    script_id: str = "default",
    script_label: str = "Default Script",
) -> ChartDataset:
    feature_path = Path(path) if path is not None else resolve_default_feature_path()
    raw_records = _load_records(feature_path)
    points = [_record_to_chart_point(record) for record in raw_records]
    points.sort(key=lambda point: point.scene_index)

    available_features = _available_features(raw_records)
    return ChartDataset(
        script_id=script_id,
        script_label=script_label,
        source_path=str(feature_path),
        features=available_features,
        points=points,
    )


def _available_features(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return BASE_CHART_FEATURES
    available: list[str] = []
    for feature in CHART_FEATURES:
        if any(record.get(feature) is not None for record in records):
            available.append(feature)
    return available or BASE_CHART_FEATURES


def _load_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid feature JSON: {path}") from exc

    if not isinstance(payload, list):
        raise ValueError(f"Feature file must contain a JSON array: {path}")
    return [record for record in payload if isinstance(record, dict)]


def _record_to_chart_point(record: dict[str, Any]) -> ChartPoint:
    return ChartPoint(
        scene_id=str(record.get("scene_id", "")),
        scene_index=_as_int(record.get("scene_index"), default=0),
        position=_as_float(record.get("position")),
        title=str(record.get("title", "")),
        location=_optional_str(record.get("location")),
        time_of_day=_optional_str(record.get("time_of_day")),
        word_count=_as_int(record.get("word_count"), default=0),
        scene_length_score=_as_float(record.get("scene_length_score")),
        dialogue_ratio=_as_float(record.get("dialogue_ratio")),
        action_ratio=_as_float(record.get("action_ratio")),
        character_density=_as_float(record.get("character_density")),
        emotion_intensity=_as_float(record.get("emotion_intensity")),
        tension_score=_as_float(record.get("tension_score")),
        semantic_novelty_score=_as_float(record.get("semantic_novelty_score")),
        plot_movement_score=_as_float(record.get("plot_movement_score")),
        hybrid_tension_score=_optional_float(record.get("hybrid_tension_score")),
        hybrid_emotion_intensity=_optional_float(record.get("hybrid_emotion_intensity")),
        classifier_tension_score=_optional_float(record.get("classifier_tension_score")),
        classifier_emotion_score=_optional_float(record.get("classifier_emotion_score")),
        classifier_sentiment_score=_optional_float(record.get("classifier_sentiment_score")),
        scene_function_score=_optional_float(record.get("scene_function_score")),
        scene_risk_score=_optional_float(record.get("scene_risk_score")),
        llm_pacing_score=_optional_float(record.get("llm_pacing_score")),
        llm_tension_score=_optional_float(record.get("llm_tension_score")),
        llm_dialogue_density_score=_optional_float(record.get("llm_dialogue_density_score")),
        llm_action_density_score=_optional_float(record.get("llm_action_density_score")),
        llm_emotion_intensity_score=_optional_float(record.get("llm_emotion_intensity_score")),
        llm_plot_movement_score=_optional_float(record.get("llm_plot_movement_score")),
        llm_character_interaction_score=_optional_float(record.get("llm_character_interaction_score")),
        llm_confidence=_optional_float(record.get("llm_confidence")),
        final_pacing_score=_optional_float(record.get("final_pacing_score")),
        final_tension_score=_optional_float(record.get("final_tension_score")),
        final_dialogue_ratio=_optional_float(record.get("final_dialogue_ratio")),
        final_action_ratio=_optional_float(record.get("final_action_ratio")),
        final_emotion_intensity=_optional_float(record.get("final_emotion_intensity")),
        final_plot_movement_score=_optional_float(record.get("final_plot_movement_score")),
        final_character_density=_optional_float(record.get("final_character_density")),
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
