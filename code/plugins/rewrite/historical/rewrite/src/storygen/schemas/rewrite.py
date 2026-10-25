"""Schemas for Sprint 5 local rewrite execution.

The public request shape remains button/selection based: users do not provide a
free-form prompt. The backend builds the internal prompt from an existing
transfer plan and the selected source scenes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class RewriteRunRequest(BaseModel):
    """API-facing request for running a local rewrite from a transfer plan."""

    plan_path: str = Field(..., min_length=1)
    script_path: str = Field(default="data/script.json", min_length=1)
    output_path: str | None = None
    model: str = Field(default="qwen2.5-7b-q4", min_length=1)
    vllm_base_url: str = Field(default="http://127.0.0.1:8000/v1", min_length=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_scene_chars: int = Field(default=12000, ge=1000, le=50000)
    generation_concurrency: int = Field(default=4, ge=1, le=64)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    timeout_seconds: float = Field(default=600.0, gt=0.0, le=7200.0)


class SourceSceneForRewrite(BaseModel):
    """A selected source scene passed into the internal rewrite request."""

    scene_id: str
    scene_index: int
    title: str
    content: str
    was_truncated: bool = False


class RewriteRequestPayload(BaseModel):
    """Serializable internal prompt package saved for reproducibility."""

    run_id: str
    model: str
    script_path: str
    plan_path: str
    selected_features: list[str]
    source_scene_ids: list[str]
    reference_scene_ids: list[str]
    preservation_constraints: list[str]
    source_scenes: list[SourceSceneForRewrite]
    per_scene_directives: list[dict[str, Any]]
    system_instruction: str
    user_instruction: str
    generation_options: dict[str, Any]


class RewrittenScene(BaseModel):
    """One rewritten scene returned by the local LLM."""

    scene_id: str = Field(..., min_length=1)
    title: str = ""
    content: str = Field(..., min_length=1)
    change_summary: str = ""

    @field_validator("scene_id", "title", "content", "change_summary", mode="before")
    @classmethod
    def coerce_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()


class RewriteOutput(BaseModel):
    """Strict JSON output expected from the local LLM."""

    rewritten_scenes: list[RewrittenScene] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_unique_scene_ids(self) -> "RewriteOutput":
        scene_ids = [scene.scene_id for scene in self.rewritten_scenes]
        duplicates = sorted({scene_id for scene_id in scene_ids if scene_ids.count(scene_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate rewritten scene ids: {', '.join(duplicates)}")
        return self


class RewriteSummary(BaseModel):
    """Compact run summary returned to CLI/API/UI."""

    run_id: str
    model: str
    scene_count: int
    source_scene_ids: list[str]
    output_path: str
    request_path: str
    raw_response_path: str
    summary_path: str
    response_was_repaired: bool = False
    generation_attempt_count: int = 1
    schema_retry_count: int = 0
    validation_warnings: list[str] = Field(default_factory=list)
    generation_mode: str = "interval_json"
    normalizer_version: str | None = None
    raw_response_shape: str | None = None
    normalization_actions: list[str] = Field(default_factory=list)
    rejected_reason: str | None = None
    scene_coverage_exact: bool | None = None


class RewriteRunResult(BaseModel):
    """In-memory result used by the rewrite engine."""

    output: RewriteOutput
    summary: RewriteSummary
    request_payload: RewriteRequestPayload
    raw_response_text: str
