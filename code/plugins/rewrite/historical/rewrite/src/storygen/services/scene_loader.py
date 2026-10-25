"""Load and normalize scene records from the project screenplay JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from storygen.schemas.scene import ParsedScene, RawScene


class SceneLoadError(ValueError):
    """Raised when an input screenplay JSON cannot be loaded as scene records."""


def _normalize_scene_id(index: int) -> str:
    return f"scene_{index:03d}"


def load_raw_scene_records(path: str | Path) -> list[RawScene]:
    """Load raw scene records while preserving source order and raw text.

    Expected input shape is a JSON array whose records include at least:
    `_id`, `title`, and `content`.
    """

    input_path = Path(path)
    if not input_path.exists():
        raise SceneLoadError(f"Input file does not exist: {input_path}")

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SceneLoadError(f"Invalid JSON in {input_path}: {exc}") from exc

    if not isinstance(payload, list):
        raise SceneLoadError("Input screenplay JSON must be a list of scene records.")

    records: list[RawScene] = []
    for i, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise SceneLoadError(f"Scene record at index {i} is not an object.")
        try:
            records.append(RawScene.model_validate(item))
        except Exception as exc:  # pydantic raises ValidationError, keep message concise.
            raise SceneLoadError(f"Invalid scene record at index {i}: {exc}") from exc

    return records


def normalize_scenes(records: Iterable[RawScene]) -> list[ParsedScene]:
    """Assign stable normalized scene ids without changing scene order or content."""

    parsed: list[ParsedScene] = []
    for index, record in enumerate(records, start=1):
        parsed.append(
            ParsedScene(
                scene_id=_normalize_scene_id(index),
                source_id=record.source_id,
                scene_index=index,
                title=record.title.strip(),
                subtitle=record.subtitle.strip(),
                content=record.content,
            )
        )
    return parsed


def load_scenes(path: str | Path) -> list[ParsedScene]:
    """Load and normalize scenes from a screenplay JSON file."""

    return normalize_scenes(load_raw_scene_records(path))
