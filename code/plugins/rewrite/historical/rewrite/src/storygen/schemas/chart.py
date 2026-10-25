"""Schemas for chart-facing feature endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChartPoint(BaseModel):
    """Single scene point shown in the line-chart UI."""

    scene_id: str
    scene_index: int
    position: float
    title: str
    location: str | None = None
    time_of_day: str | None = None
    word_count: int
    scene_length_score: float
    dialogue_ratio: float
    action_ratio: float
    character_density: float
    emotion_intensity: float
    tension_score: float
    semantic_novelty_score: float
    plot_movement_score: float
    hybrid_tension_score: float | None = None
    hybrid_emotion_intensity: float | None = None
    classifier_tension_score: float | None = None
    classifier_emotion_score: float | None = None
    classifier_sentiment_score: float | None = None
    scene_function_score: float | None = None
    scene_risk_score: float | None = None
    llm_pacing_score: float | None = None
    llm_tension_score: float | None = None
    llm_dialogue_density_score: float | None = None
    llm_action_density_score: float | None = None
    llm_emotion_intensity_score: float | None = None
    llm_plot_movement_score: float | None = None
    llm_character_interaction_score: float | None = None
    llm_confidence: float | None = None
    final_pacing_score: float | None = None
    final_tension_score: float | None = None
    final_dialogue_ratio: float | None = None
    final_action_ratio: float | None = None
    final_emotion_intensity: float | None = None
    final_plot_movement_score: float | None = None
    final_character_density: float | None = None


class ChartDataset(BaseModel):
    """Chart-ready screenplay feature payload."""

    script_id: str = "default"
    script_label: str = "Default Script"
    source_path: str
    features: list[str] = Field(default_factory=list)
    points: list[ChartPoint] = Field(default_factory=list)


class FeatureCatalog(BaseModel):
    """Available feature curves for the line-chart UI."""

    default_feature: str
    features: list[str]
    labels: dict[str, str]
