"""Schemas for Sprint 6 rewrite re-analysis, metrics, and export."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeRewriteRequest(BaseModel):
    """API request for re-analyzing a completed rewrite run.

    If the active transfer feature is an ``llm_*`` or ``final_*`` curve, the
    re-analysis step must also score the rewritten selected scenes with the
    local LLM. Otherwise the deterministic re-analysis output cannot contain
    the selected LLM feature needed for before/reference/after metrics.
    """

    run_dir: str = Field(..., min_length=1)
    script_path: str = Field(default="data/script.json", min_length=1)
    embedding_backend: str = Field(default="hash", min_length=1)
    embedding_model: str = Field(default="deterministic-hash-256", min_length=1)

    run_llm_for_llm_features: bool = True
    llm_model: str = Field(default="qwen2.5-7b-q4", min_length=1)
    vllm_base_url: str = Field(default="http://127.0.0.1:8000/v1", min_length=1)
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_scene_chars: int = Field(default=5000, ge=500, le=20000)
    use_cache: bool = True
    strict_llm: bool = False
    llm_concurrency: int = Field(default=4, ge=1, le=64)
    llm_max_tokens: int = Field(default=1024, ge=1, le=32768)
    llm_timeout_seconds: float = Field(default=180.0, gt=0.0, le=7200.0)


class FeatureMetric(BaseModel):
    """Curve-comparison metrics for one selected feature."""

    feature: str
    target_values: list[float]
    rewritten_values: list[float]
    before_values: list[float]
    mae: float
    rmse: float
    correlation: float | None = None
    dtw_distance: float
    before_target_mae: float | None = None
    improvement_over_before: float | None = None


class PreservationChecks(BaseModel):
    """Deterministic safety checks for selected rewrite interval."""

    scene_ids_preserved: bool
    selected_interval_boundaries_preserved: bool
    title_continuity_preserved: bool
    character_names_preserved: bool
    missing_scene_ids: list[str] = Field(default_factory=list)
    extra_scene_ids: list[str] = Field(default_factory=list)
    changed_titles: list[str] = Field(default_factory=list)
    missing_characters_by_scene: dict[str, list[str]] = Field(default_factory=dict)


class TransferMetrics(BaseModel):
    """Full Sprint 6 metric payload saved to transfer_metrics.json."""

    run_id: str
    selected_features: list[str]
    source_scene_ids: list[str]
    reference_scene_ids: list[str]
    feature_metrics: list[FeatureMetric]
    preservation_checks: PreservationChecks
    aggregate_mae: float
    aggregate_rmse: float
    aggregate_dtw_distance: float
    metrics_version: str = "sprint6.metrics.v1"


class ReanalysisSummary(BaseModel):
    """Compact response returned to CLI/API/UI after re-analysis."""

    run_id: str
    scene_count: int
    selected_scene_count: int
    rewritten_features_path: str
    transfer_metrics_path: str
    script_rewritten_path: str
    export_path: str
    aggregate_mae: float
    aggregate_rmse: float
    preservation_passed: bool


class ComparisonChartPoint(BaseModel):
    """One point in the before/target/after comparison chart."""

    scene_id: str
    scene_index: int
    title: str
    before: float
    target: float
    after: float


class BeforeAfterChartDataset(BaseModel):
    """UI-facing before/reference/after curve data for one run and feature."""

    run_id: str
    feature: str
    source_scene_ids: list[str]
    points: list[ComparisonChartPoint]


class AcceptRewriteRequest(BaseModel):
    """Explicit accept request for a completed rewrite run."""

    run_dir: str = Field(..., min_length=1)


class RevertRewriteRequest(BaseModel):
    """Explicit revert request for a completed rewrite run."""

    run_dir: str = Field(..., min_length=1)
