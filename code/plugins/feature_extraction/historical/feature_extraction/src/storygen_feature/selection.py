"""Explicit scene subsets; text and original scene indexes are never rewritten."""
from pathlib import Path

from .io import read_json, sha256_file


def load_selection(path: Path, films: list[str]) -> dict:
    selection = read_json(path)
    if selection.get("contract_id") != "storygen.scene-selection" or selection.get("contract_version") != "1.0":
        raise ValueError("storygen.scene-selection/1.0 required")
    entries = selection.get("films")
    if not isinstance(entries, dict) or set(entries) != set(films):
        raise ValueError("Scene selection must cover exactly the film set")
    return entries


def select_scenes(entry: dict, script: Path, scenes: list[dict]) -> list[dict]:
    if entry.get("script_sha256") != sha256_file(script):
        raise ValueError("Scene selection script SHA256 mismatch")
    ids = entry.get("scene_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Scene selection requires nonempty unique scene IDs")
    selected = [s for s in scenes if s["scene_id"] in set(ids)]
    if [s["scene_id"] for s in selected] != ids:
        raise ValueError("Scene selection IDs must exist in original script order")
    return selected
