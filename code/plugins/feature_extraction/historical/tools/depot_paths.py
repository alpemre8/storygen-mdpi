from __future__ import annotations

import os
from pathlib import Path

ENVIRONMENT = "STORYGEN_FEATURE_DEPOT_ROOT"
DEFAULT_DEPOT = Path("~/projects/storygen-feature-extraction-depot").expanduser()


def depot_root() -> Path:
    return Path(os.environ.get(ENVIRONMENT, str(DEFAULT_DEPOT))).expanduser().resolve()


def owned_output_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    root = depot_root()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Feature Extraction output must be inside {root}: {path}") from exc
    return path
