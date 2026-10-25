"""Schemas for Sprint 4 deterministic transfer planning."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TransferPlanRequest(BaseModel):
    """API/CLI-facing transfer-planning request.

    The request is intentionally chart-selection based. It does not contain a
    user prompt and it does not request text generation.
    """

    source_start_scene_id: str = Field(..., min_length=1)
    source_end_scene_id: str = Field(..., min_length=1)
    reference_start_scene_id: str = Field(..., min_length=1)
    reference_end_scene_id: str = Field(..., min_length=1)
    selected_features: list[str] = Field(default_factory=list)
    feature_path: str | None = None
    source_feature_path: str | None = None
    reference_feature_path: str | None = None
    source_film_id: str | None = None
    reference_film_id: str | None = None
    output_path: str | None = None
    run_id: str | None = None

    @field_validator("selected_features", mode="before")
    @classmethod
    def normalize_features(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()]
        raise TypeError("selected_features must be a list or comma-separated string")


class TransferCurve(BaseModel):
    """A feature curve sampled over one interval."""

    feature: str
    scene_ids: list[str]
    values: list[float]


class SceneRewriteDirective(BaseModel):
    """Deterministic per-scene rewrite control record.

    Sprint 4 stops here: it only creates control instructions. Sprint 5 will
    pass these records to the local rewrite model.
    """

    scene_id: str
    scene_index: int
    title: str
    current_values: dict[str, float]
    targets: dict[str, float]
    deltas: dict[str, float]
    directive: str


class TransferPlan(BaseModel):
    """Deterministic structural-transfer plan."""

    run_id: str
    feature_source_path: str
    reference_feature_source_path: str | None = None
    selected_features: list[str]
    source_scene_ids: list[str]
    reference_scene_ids: list[str]
    source_current_curve: dict[str, list[float]]
    reference_curve: dict[str, list[float]]
    resampled_target_curve: dict[str, list[float]]
    per_scene_target_values: list[SceneRewriteDirective]
    preservation_constraints: list[str]
    planner_version: str = "sprint4.transfer_planner.v1"


class TransferPlanSummary(BaseModel):
    """Compact UI-facing plan summary."""

    run_id: str
    selected_features: list[str]
    source_scene_count: int
    reference_scene_count: int
    directive_count: int
    output_path: str | None = None
