"""Structured output normalization for local rewrite responses.

Sprint 13 centralizes deterministic repair for local LLM outputs. The
normalizer is deliberately conservative: it accepts common schema aliases, but
it rejects outputs that cannot be safely interpreted as final rewritten scene
text for the selected source scene(s).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from storygen.schemas.rewrite import RewriteOutput, RewrittenScene

NORMALIZER_VERSION = "v3"

_CONTENT_ALIASES = (
    "content",
    "modifiedContent",
    "modified_content",
    "rewrittenContent",
    "rewritten_content",
    "rewritten_text",
    "text",
    "body",
    "description",
)
_SCENE_ID_ALIASES = ("scene_id", "sceneId", "sceneID", "id", "scene_number", "scene_num")
_ROOT_LIST_ALIASES = (
    "rewritten_scenes",
    "scenes",
    "scene",
    "revised_scenes",
    "revisedScenes",
    "rewrites",
    "rewrittenScenes",
    "rewritten_scenes_output",
)
_REJECT_ROOT_KEYS = ("chapters", "document", "system")
_PLAN_ONLY_KEYS = ("transformation", "action", "dialogue", "dialogue_patch", "edits", "operations")
_ANALYSIS_KEYS = ("analysis", "reasoning", "notes", "plan", "outline")


class RewriteOutputNormalizationError(ValueError):
    """Raised when a local rewrite response cannot be safely normalized."""


@dataclass(slots=True)
class NormalizedRewriteResult:
    """Normalized rewrite output plus audit metadata."""

    output: RewriteOutput
    repaired: bool
    raw_response_shape: str
    normalization_actions: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    rejected_reason: str | None = None
    scene_coverage_exact: bool | None = None


def normalize_rewrite_raw_text(
    raw_text: str,
    *,
    mode: str,
    expected_scene_id: str | None = None,
    expected_scene_ids: list[str] | None = None,
    original_content_by_id: dict[str, str] | None = None,
    strict_final_content: bool = True,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
) -> NormalizedRewriteResult:
    """Parse and normalize raw local-model text into ``RewriteOutput``.

    ``mode='task'`` expects an interval-level ``rewritten_scenes`` list.
    ``mode='per_scene'`` expects exactly one scene and may deterministically
    assign ``expected_scene_id`` when the call was scoped to one source scene.
    """

    text = str(raw_text or "").strip()
    if not text:
        raise RewriteOutputNormalizationError("empty_response")

    candidates = _json_candidates(text)
    errors: list[str] = []
    for candidate_index, candidate in enumerate(candidates):
        try:
            payload = json.loads(candidate)
            result = normalize_rewrite_payload(
                payload,
                mode=mode,
                expected_scene_id=expected_scene_id,
                expected_scene_ids=expected_scene_ids,
                original_content_by_id=original_content_by_id,
                strict_final_content=strict_final_content,
                min_rewrite_char_ratio=min_rewrite_char_ratio,
                max_rewrite_char_ratio=max_rewrite_char_ratio,
            )
            if candidate_index > 0:
                result.repaired = True
                result.normalization_actions.append("extracted_json_candidate")
            return result
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    raise RewriteOutputNormalizationError(" | ".join(errors))


def normalize_rewrite_payload(
    payload: Any,
    *,
    mode: str,
    expected_scene_id: str | None = None,
    expected_scene_ids: list[str] | None = None,
    original_content_by_id: dict[str, str] | None = None,
    strict_final_content: bool = True,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
) -> NormalizedRewriteResult:
    """Normalize already-decoded local rewrite JSON."""

    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"task", "per_scene"}:
        raise RewriteOutputNormalizationError(f"unsupported_mode:{mode}")
    if normalized_mode == "per_scene" and not expected_scene_id:
        raise RewriteOutputNormalizationError("per_scene_mode_requires_expected_scene_id")

    actions: list[str] = []
    validation_warnings: list[str] = []
    raw_shape = _shape_name(payload)
    scenes_payload, extraction_actions, root_shape = _extract_scene_payloads(
        payload,
        mode=normalized_mode,
        expected_scene_id=expected_scene_id,
    )
    actions.extend(extraction_actions)
    if root_shape:
        raw_shape = root_shape

    if normalized_mode == "per_scene" and len(scenes_payload) != 1:
        raise RewriteOutputNormalizationError(f"Expected one rewritten scene, got {len(scenes_payload)}")

    normalized_scenes: list[dict[str, Any]] = []
    for index, scene_payload in enumerate(scenes_payload):
        scene, scene_actions = _normalize_one_scene_payload(
            scene_payload,
            mode=normalized_mode,
            expected_scene_id=expected_scene_id,
            expected_scene_ids=expected_scene_ids,
        )
        actions.extend(scene_actions)
        validation_warnings.extend(
            _validate_final_scene_content(
                scene,
                original_content_by_id=original_content_by_id or {},
                strict_final_content=strict_final_content,
                min_rewrite_char_ratio=min_rewrite_char_ratio,
                max_rewrite_char_ratio=max_rewrite_char_ratio,
            )
        )
        normalized_scenes.append(scene)

    if normalized_mode == "task":
        normalized_scenes, coverage_actions, coverage_exact = _validate_task_coverage(
            normalized_scenes,
            expected_scene_ids=expected_scene_ids or [],
        )
        actions.extend(coverage_actions)
    else:
        coverage_exact = True
        if expected_scene_id:
            returned_id = str(normalized_scenes[0].get("scene_id") or "").strip()
            if returned_id != expected_scene_id:
                actions.append("assigned_expected_scene_id")
                normalized_scenes[0]["scene_id"] = expected_scene_id

    try:
        output = RewriteOutput.model_validate({"rewritten_scenes": normalized_scenes})
    except Exception as exc:  # noqa: BLE001
        raise RewriteOutputNormalizationError(str(exc)) from exc

    return NormalizedRewriteResult(
        output=output,
        repaired=bool(actions),
        raw_response_shape=raw_shape,
        normalization_actions=_dedupe(actions),
        validation_warnings=_dedupe(validation_warnings),
        scene_coverage_exact=coverage_exact,
    )


def normalize_scene_id_token(value: Any) -> str:
    """Normalize common scene-id shapes into ``scene_000`` style when possible."""

    text = str(value or "").strip()
    if not text:
        return text
    if re.fullmatch(r"scene_\d+", text, flags=re.IGNORECASE):
        return f"scene_{int(text.split('_')[-1]):03d}"
    if re.fullmatch(r"\d+", text):
        return f"scene_{int(text):03d}"
    match = re.search(r"scene\D*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"scene_{int(match.group(1)):03d}"
    return text


def _extract_scene_payloads(payload: Any, *, mode: str, expected_scene_id: str | None) -> tuple[list[dict[str, Any]], list[str], str]:
    actions: list[str] = []
    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            raise RewriteOutputNormalizationError("list_contains_non_object_items")
        actions.append("list_root_to_rewritten_scenes")
        return [dict(item) for item in payload], actions, "list_root"

    if not isinstance(payload, dict):
        raise RewriteOutputNormalizationError("root_not_json_object_or_list")

    if any(key in payload for key in _REJECT_ROOT_KEYS):
        reject_keys = [key for key in _REJECT_ROOT_KEYS if key in payload]
        raise RewriteOutputNormalizationError(f"rejected_whole_document_shape:{','.join(reject_keys)}")

    for root_key in _ROOT_LIST_ALIASES:
        if root_key not in payload:
            continue
        value = payload[root_key]
        if isinstance(value, list):
            if not all(isinstance(item, dict) for item in value):
                raise RewriteOutputNormalizationError(f"{root_key}_contains_non_object_items")
            if root_key != "rewritten_scenes":
                actions.append(f"{root_key}_to_rewritten_scenes")
            return [dict(item) for item in value], actions, f"{root_key}_list_alias"
        if isinstance(value, dict):
            if root_key != "rewritten_scenes":
                actions.append(f"{root_key}_object_to_scene")
            return [dict(value)], actions, f"{root_key}_object_alias"
        raise RewriteOutputNormalizationError(f"{root_key}_has_invalid_value")

    keyed_scene_values = [(key, value) for key, value in payload.items() if isinstance(value, dict) and _looks_like_scene_key(key)]
    if keyed_scene_values and len(keyed_scene_values) == len(payload):
        scenes: list[dict[str, Any]] = []
        for key, value in keyed_scene_values:
            scene = dict(value)
            scene.setdefault("scene_id", key)
            scenes.append(scene)
        actions.append("keyed_scene_map_to_rewritten_scenes")
        return scenes, actions, "keyed_scene_map"

    if _looks_like_single_scene(payload):
        return [dict(payload)], actions, "single_scene_object"

    if mode == "per_scene" and expected_scene_id and _has_content_alias(payload):
        scene = dict(payload)
        scene.setdefault("scene_id", expected_scene_id)
        actions.append("per_scene_content_object_to_scene")
        return [scene], actions, "per_scene_content_object"

    if any(key in payload for key in _ANALYSIS_KEYS):
        raise RewriteOutputNormalizationError("analysis_or_plan_only_output")
    raise RewriteOutputNormalizationError("could_not_identify_rewritten_scene_payload")


def _normalize_one_scene_payload(
    payload: dict[str, Any],
    *,
    mode: str,
    expected_scene_id: str | None,
    expected_scene_ids: list[str] | None,
) -> tuple[dict[str, Any], list[str]]:
    actions: list[str] = []
    scene = dict(payload)

    scene_id_value = None
    for alias in _SCENE_ID_ALIASES:
        if alias in scene and str(scene.get(alias) or "").strip():
            scene_id_value = scene.get(alias)
            if alias != "scene_id":
                actions.append(f"{alias}_to_scene_id")
            break

    if mode == "per_scene" and expected_scene_id:
        normalized_returned_id = normalize_scene_id_token(scene_id_value) if scene_id_value else ""
        if scene_id_value and normalized_returned_id != expected_scene_id:
            actions.append("ignored_returned_scene_id")
        elif not scene_id_value:
            actions.append("assigned_expected_scene_id")
        scene["scene_id"] = expected_scene_id
    else:
        normalized_id = normalize_scene_id_token(scene_id_value)
        if not normalized_id:
            raise RewriteOutputNormalizationError("empty_scene_id")
        if expected_scene_ids is not None and normalized_id not in set(expected_scene_ids):
            # Keep the id; task-level coverage validation will report outside interval.
            pass
        if normalized_id != scene.get("scene_id"):
            actions.append("normalized_scene_id")
        scene["scene_id"] = normalized_id

    if not str(scene.get("title") or "").strip():
        title = scene.get("heading") or scene.get("name") or ""
        if str(title or "").strip():
            scene["title"] = str(title).strip()
            actions.append("heading_to_title")
        else:
            scene["title"] = ""

    content, content_action = _extract_final_content(scene)
    if not content:
        if _is_transformation_only(scene):
            raise RewriteOutputNormalizationError("transformation_only_output")
        if _is_dialogue_only(scene):
            raise RewriteOutputNormalizationError("dialogue_only_without_full_scene_content")
        raise RewriteOutputNormalizationError("missing_content_field")
    scene["content"] = content
    if content_action:
        actions.append(content_action)

    if not str(scene.get("change_summary") or "").strip():
        summary = scene.get("summary") or scene.get("change") or ""
        if str(summary or "").strip():
            scene["change_summary"] = str(summary).strip()
            actions.append("summary_to_change_summary")
        else:
            scene["change_summary"] = ""

    return {
        "scene_id": scene["scene_id"],
        "title": str(scene.get("title") or "").strip(),
        "content": scene["content"],
        "change_summary": str(scene.get("change_summary") or "").strip(),
    }, actions


def _extract_final_content(scene: dict[str, Any]) -> tuple[str, str | None]:
    selected = ""
    selected_alias: str | None = None
    for alias in _CONTENT_ALIASES:
        value = scene.get(alias)
        if isinstance(value, str) and value.strip():
            selected = value.strip()
            selected_alias = alias
            break

    if selected and isinstance(scene.get("transformation"), dict):
        transformation = scene["transformation"]
        extra_parts: list[str] = []
        action = transformation.get("action")
        if isinstance(action, str) and action.strip():
            extra_parts.append(action.strip())
        dialogue = transformation.get("dialogue")
        if isinstance(dialogue, list):
            for turn in dialogue:
                if isinstance(turn, dict):
                    character = str(turn.get("character") or "").strip()
                    line = str(turn.get("line") or "").strip()
                    if character and line:
                        extra_parts.append(f"{character}: {line}")
                    elif line:
                        extra_parts.append(line)
                elif isinstance(turn, str) and turn.strip():
                    extra_parts.append(turn.strip())
        if extra_parts:
            selected = selected + "\n" + "\n".join(extra_parts)

    if selected:
        action = None if selected_alias == "content" else f"{selected_alias}_to_content"
        return selected, action
    return "", None

def _validate_final_scene_content(
    scene: dict[str, Any],
    *,
    original_content_by_id: dict[str, str],
    strict_final_content: bool,
    min_rewrite_char_ratio: float,
    max_rewrite_char_ratio: float,
) -> list[str]:
    """Validate hard content contract and return diagnostic-only warnings.

    Hard failures stay limited to missing/empty final scene text and analysis/plan-like
    content. Length drift remains measurable, so it is recorded as a warning rather
    than rejected as a task failure.
    """

    warnings: list[str] = []
    content = str(scene.get("content") or "").strip()
    if not content:
        raise RewriteOutputNormalizationError("empty_content")
    if strict_final_content and _looks_like_plan_text(content):
        raise RewriteOutputNormalizationError("content_looks_like_plan_not_final_scene")

    scene_id = str(scene.get("scene_id") or "").strip()
    original = str(original_content_by_id.get(scene_id) or "")
    if not original:
        return warnings
    original_len = len(original.strip())
    content_len = len(content)
    if original_len < 80:
        return warnings
    ratio = content_len / max(original_len, 1)
    if ratio < max(0.0, float(min_rewrite_char_ratio)):
        warnings.append(f"{scene_id}:content_too_short_ratio:{ratio:.3f}")
    if float(max_rewrite_char_ratio) > 0 and ratio > float(max_rewrite_char_ratio):
        warnings.append(f"{scene_id}:content_too_long_ratio:{ratio:.3f}")
    return warnings


def _validate_task_coverage(scenes: list[dict[str, Any]], *, expected_scene_ids: list[str]) -> tuple[list[dict[str, Any]], list[str], bool]:
    if not expected_scene_ids:
        return scenes, [], None
    actions: list[str] = []
    seen: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for scene in scenes:
        scene_id = str(scene.get("scene_id") or "").strip()
        if scene_id in seen:
            duplicates.append(scene_id)
        else:
            seen[scene_id] = scene
    if duplicates:
        raise RewriteOutputNormalizationError(f"duplicate_scene_ids:{','.join(sorted(set(duplicates)))}")
    outside = [scene_id for scene_id in seen if scene_id not in expected_scene_ids]
    missing = [scene_id for scene_id in expected_scene_ids if scene_id not in seen]
    if outside:
        raise RewriteOutputNormalizationError(f"outside_interval_scenes:{','.join(outside)}")
    if missing:
        raise RewriteOutputNormalizationError(f"omitted_selected_scenes:{','.join(missing)}")
    ordered = [seen[scene_id] for scene_id in expected_scene_ids]
    if [scene.get("scene_id") for scene in scenes] != expected_scene_ids:
        actions.append("ordered_scenes_to_expected_interval")
    return ordered, actions, True


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    fenced = _strip_code_fence(text)
    if fenced != text:
        candidates.append(fenced)
    extracted = _extract_first_json_object(text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)
    return candidates


def _strip_code_fence(text: str) -> str:
    pattern = r"^```(?:json)?\s*(.*?)\s*```$"
    match = re.match(pattern, text.strip(), flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return text
    return match.group(1).strip()


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _looks_like_scene_key(key: Any) -> bool:
    text = str(key or "").strip()
    return bool(text) and (text.isdigit() or text.lower().startswith("scene"))


def _looks_like_single_scene(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in (*_SCENE_ID_ALIASES, *_CONTENT_ALIASES))


def _has_content_alias(payload: dict[str, Any]) -> bool:
    return any(isinstance(payload.get(key), str) and payload.get(key).strip() for key in _CONTENT_ALIASES)


def _is_transformation_only(scene: dict[str, Any]) -> bool:
    return any(key in scene for key in ("transformation", "action")) and not _has_content_alias(scene)


def _is_dialogue_only(scene: dict[str, Any]) -> bool:
    return "dialogue" in scene and not _has_content_alias(scene)


def _looks_like_plan_text(content: str) -> bool:
    lowered = content.strip().lower()
    plan_markers = (
        "add dialogue",
        "add a reaction shot",
        "transformation:",
        "action:",
        "change the scene by",
        "rewrite plan",
        "the scene should",
        "modify the scene",
    )
    return any(marker in lowered for marker in plan_markers)


def _shape_name(payload: Any) -> str:
    if isinstance(payload, list):
        return "list_root"
    if isinstance(payload, dict):
        keys = list(payload.keys())
        if not keys:
            return "empty_object"
        first = keys[0]
        if all(_looks_like_scene_key(key) for key in keys):
            return "keyed_scene_map"
        return f"object:{first}"
    return type(payload).__name__


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output
