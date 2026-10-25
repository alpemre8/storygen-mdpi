"""Schemas for Sprint 9 local LLM-assisted scene analysis."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SceneFunctionLabel = Literal[
    "setup",
    "development",
    "conflict",
    "discovery",
    "complication",
    "turning_point",
    "resolution",
    "transition",
    "unknown",
]

RiskLabel = Literal["low_risk", "medium_risk", "high_risk", "unknown"]

ALLOWED_SCENE_FUNCTION_LABELS = {
    "setup",
    "development",
    "conflict",
    "discovery",
    "complication",
    "turning_point",
    "resolution",
    "transition",
    "unknown",
}

ALLOWED_RISK_LABELS = {"low_risk", "medium_risk", "high_risk", "unknown"}

ALLOWED_EMOTION_LABELS = {
    "anger",
    "disgust",
    "fear",
    "joy",
    "neutral",
    "sadness",
    "surprise",
    "unknown",
}


class LLMSceneAnalysis(BaseModel):
    """One structured local LLM scene-analysis record."""

    scene_id: str
    pacing_score: float = Field(ge=0.0, le=1.0)
    tension_score: float = Field(ge=0.0, le=1.0)
    dialogue_density_score: float = Field(ge=0.0, le=1.0)
    action_density_score: float = Field(ge=0.0, le=1.0)
    emotion_intensity_score: float = Field(ge=0.0, le=1.0)
    plot_movement_score: float = Field(ge=0.0, le=1.0)
    character_interaction_score: float = Field(ge=0.0, le=1.0)
    dominant_emotion: str = "unknown"
    scene_function: SceneFunctionLabel = "unknown"
    risk_label: RiskLabel = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator(
        "pacing_score",
        "tension_score",
        "dialogue_density_score",
        "action_density_score",
        "emotion_intensity_score",
        "plot_movement_score",
        "character_interaction_score",
        "confidence",
        mode="before",
    )
    @classmethod
    def clamp_numeric(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return round(max(0.0, min(1.0, number)), 6)

    @field_validator("dominant_emotion", mode="before")
    @classmethod
    def normalize_emotion(cls, value: Any) -> str:
        label = str(value or "unknown").strip().lower().replace(" ", "_")
        aliases = {"happy": "joy", "happiness": "joy", "angry": "anger", "sad": "sadness"}
        label = aliases.get(label, label)
        return label if label in ALLOWED_EMOTION_LABELS else "unknown"

    @field_validator("scene_function", mode="before")
    @classmethod
    def normalize_scene_function(cls, value: Any) -> str:
        label = str(value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")
        return label if label in ALLOWED_SCENE_FUNCTION_LABELS else "unknown"

    @field_validator("risk_label", mode="before")
    @classmethod
    def normalize_risk_label(cls, value: Any) -> str:
        label = str(value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {"low": "low_risk", "medium": "medium_risk", "high": "high_risk"}
        label = aliases.get(label, label)
        return label if label in ALLOWED_RISK_LABELS else "unknown"

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str:
        return str(value or "").strip()[:800]


class LLMAnalysisRequest(BaseModel):
    """Controls for Level 3 LLM-assisted analysis."""

    make_active: bool = True
    model: str = "qwen2.5-7b-q4"
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_scene_chars: int = Field(default=5000, ge=500, le=20000)
    use_cache: bool = True
    strict: bool = False
    generation_concurrency: int = Field(default=4, ge=1, le=64)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    timeout_seconds: float = Field(default=180.0, gt=0.0, le=7200.0)


class LLMAnalysisResponse(BaseModel):
    """Summary returned after Level 3 analysis."""

    film_id: str
    analysis_level: str = "llm"
    model: str
    scene_count: int
    analyzed_scene_count: int
    cached_scene_count: int
    features_path: str
    active_features_path: str | None = None
    llm_analysis_path: str
    cache_path: str
    report_path: str
    warnings: list[str] = Field(default_factory=list)


class FullAnalysisRequest(BaseModel):
    """Controls for hybrid full analysis from the UI."""

    make_active: bool = True
    run_basic_first: bool = True
    run_classifier: bool = True
    run_llm: bool = True
    embedding_backend: str = "hash"
    embedding_model: str = "deterministic-hash-256"
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str = "qwen2.5-7b-q4"
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_scene_chars: int = Field(default=5000, ge=500, le=20000)
    use_cache: bool = True
    strict_llm: bool = False
    strict_classifier: bool = False
    classifier_local_files_only: bool | None = None
    llm_concurrency: int = Field(default=4, ge=1, le=64)
    llm_max_tokens: int = Field(default=1024, ge=1, le=32768)
    llm_timeout_seconds: float = Field(default=180.0, gt=0.0, le=7200.0)


class FullAnalysisResponse(BaseModel):
    """Summary returned after hybrid full analysis."""

    film_id: str
    analysis_level: str = "hybrid_full"
    scene_count: int
    features_path: str
    active_features_path: str
    report_path: str
    basic_ran: bool = False
    classifier_ran: bool = False
    llm_ran: bool = False
    warnings: list[str] = Field(default_factory=list)
