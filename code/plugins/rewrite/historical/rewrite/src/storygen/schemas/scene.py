"""Pydantic schemas for scene loading and Sprint 1 feature extraction."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawScene(BaseModel):
    """Raw scene record loaded from `data/script.json` without mutating the text."""

    model_config = ConfigDict(extra="allow")

    source_id: int | str = Field(alias="_id")
    title: str
    subtitle: str = ""
    content: str

    @field_validator("title", "subtitle", "content", mode="before")
    @classmethod
    def coerce_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)


class ParsedScene(BaseModel):
    """Scene record after stable id normalization."""

    scene_id: str
    source_id: int | str
    scene_index: int
    title: str
    subtitle: str = ""
    content: str


class HeadingInfo(BaseModel):
    """Structured parse of a screenplay-style scene heading."""

    raw_title: str
    cleaned_title: str
    int_ext: str | None = None
    location: str | None = None
    time_of_day: str | None = None


class DialogueParse(BaseModel):
    """Transparent dialogue/action split produced by heuristic parsing."""

    speakers: list[str]
    dialogue_turn_count: int
    dialogue_word_count: int
    action_word_count: int
    dialogue_lines: list[str]
    action_lines: list[str]


class SceneFeature(BaseModel):
    """Chart-facing scene feature record.

    Sprint 1 fields are deterministic text-structure features. Sprint 2 adds
    local model/lexicon-assisted macro features while keeping all Sprint 1
    fields backward-compatible.
    """

    scene_id: str
    source_id: int | str
    scene_index: int
    position: float
    title: str
    subtitle: str = ""
    int_ext: str | None = None
    location: str | None = None
    time_of_day: str | None = None
    word_count: int
    sentence_count: int
    avg_sentence_length: float
    dialogue_word_count: int
    action_word_count: int
    dialogue_ratio: float
    action_ratio: float
    speaker_count: int
    dialogue_turn_count: int
    character_density: float
    scene_length_score: float
    sentiment_score: float = 0.0
    emotion_intensity: float = 0.0
    tension_score: float = 0.0
    dominant_emotion: str = "neutral"
    conflict_lexicon_hits: int = 0
    urgency_marker_count: int = 0
    semantic_novelty_score: float = 0.0
    plot_movement_score: float = 0.0
    location_change_score: float = 0.0
    new_speaker_score: float = 0.0
    embedding_ref: str | None = None
    embedding_backend: str | None = None
    embedding_model: str | None = None
    analysis_level: str = "deterministic"
    classifier_available: bool = False
    classifier_warnings: list[str] = Field(default_factory=list)
    classifier_emotion_label: str | None = None
    classifier_emotion_score: float | None = None
    classifier_sentiment_label: str | None = None
    classifier_sentiment_score: float | None = None
    scene_function_label: str | None = None
    scene_function_score: float | None = None
    scene_risk_label: str | None = None
    scene_risk_score: float | None = None
    classifier_tension_score: float | None = None
    hybrid_tension_score: float | None = None
    hybrid_emotion_intensity: float | None = None
