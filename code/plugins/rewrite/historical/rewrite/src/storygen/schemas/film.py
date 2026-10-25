"""Schemas for named film/script workspaces introduced in Sprint 7."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FilmRecord(BaseModel):
    """Metadata stored in each `data/films/<film_id>/film.json` file."""

    film_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    created_at: str
    updated_at: str
    script_path: str
    features_path: str
    scene_count: int = 0
    has_features: bool = False


class FilmUploadResponse(BaseModel):
    """Response returned after a successful `script.json` upload."""

    film: FilmRecord
    message: str = "Film workspace created."


class FilmListResponse(BaseModel):
    """Collection of known film workspaces."""

    films: list[FilmRecord] = Field(default_factory=list)


class FilmAnalyzeRequest(BaseModel):
    """Optional analysis controls for workspace feature extraction."""

    embedding_backend: str = "hash"
    embedding_model: str = "deterministic-hash-256"
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    allow_hash_fallback: bool = True

    @field_validator("embedding_backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        normalized = str(value or "hash").strip()
        allowed = {"auto", "vllm", "hash", "sentence-transformers"}
        if normalized not in allowed:
            raise ValueError(f"embedding_backend must be one of: {', '.join(sorted(allowed))}")
        return normalized


class ClassifierAnalysisRequest(BaseModel):
    """Controls for optional Level 2 local classifier analysis."""

    make_active: bool = True
    strict_model_loading: bool = False
    local_files_only: bool | None = None
    config_path: str = "configs/analysis_models.json"


class ClassifierAnalysisSummary(BaseModel):
    """Response returned after Level 2 classifier enrichment."""

    film_id: str
    analysis_level: str = "classifier"
    scene_count: int
    features_path: str
    active_features_path: str | None = None
    classifier_available: bool = False
    warnings: list[str] = Field(default_factory=list)


class FilmAnalysisStatusResponse(BaseModel):
    """Current analysis status for one film workspace."""

    film_id: str
    display_name: str
    scene_count: int
    has_features: bool
    features_path: str
    has_level2_features: bool = False
    level2_features_path: str | None = None
    has_llm_features: bool = False
    llm_features_path: str | None = None
    has_hybrid_features: bool = False
    hybrid_features_path: str | None = None
    analysis_status_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
