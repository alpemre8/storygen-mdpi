"""Local-only rewrite engine for Sprint 5.

This module converts a deterministic transfer plan into an internal prompt,
sends it to a local vLLM-served model, validates the model's JSON response, and saves
all reproducibility artifacts. It never calls a cloud API and never rewrites
scenes outside the selected source interval.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from storygen.schemas.rewrite import (
    RewriteOutput,
    RewriteRequestPayload,
    RewriteRunResult,
    RewriteSummary,
    RewrittenScene,
    SourceSceneForRewrite,
)
from storygen.schemas.scene import ParsedScene
from storygen.schemas.transfer import TransferPlan
from storygen.services.vllm_client import DEFAULT_VLLM_BASE_URL, VLLMClient, VLLMClientError
from storygen.services.rewrite_output_normalizer import (
    NORMALIZER_VERSION,
    normalize_rewrite_raw_text,
    normalize_scene_id_token,
)
from storygen.services.scene_loader import SceneLoadError, load_scenes

REWRITE_ENGINE_VERSION = "sprint13.rewrite_engine.v3_normalizer"
DEFAULT_MODEL = "qwen2.5-7b-q4"
DEFAULT_SCHEMA_RETRY_COUNT = 3


class RewriteEngineError(RuntimeError):
    """Raised when local rewrite execution cannot be completed safely."""


class LocalGenerationClient(Protocol):
    """Protocol used to inject a fake client in tests without reaching vLLM."""

    def generate(
        self,
        prompt: str,
        model: str,
        *,
        system: str | None = None,
        format_json: bool = False,
        format_schema: dict[str, object] | None = None,
        options: dict[str, object] | None = None,
        request_metadata: dict[str, object] | None = None,
    ) -> str:
        """Return model text."""


def run_rewrite_from_files(
    *,
    plan_path: str | Path,
    script_path: str | Path,
    output_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    vllm_base_url: str = DEFAULT_VLLM_BASE_URL,
    temperature: float = 0.2,
    max_scene_chars: int = 12000,
    client: LocalGenerationClient | None = None,
    schema_retry_count: int = DEFAULT_SCHEMA_RETRY_COUNT,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    strict_final_content: bool = True,
    rewrite_timeout_seconds: float = 180.0,
    max_tokens: int = 4096,
) -> RewriteRunResult:
    """Run a local rewrite from a saved transfer plan and script file.

    The first local-model response is still treated as the primary artifact. If
    it violates the output contract, the engine performs a bounded local repair
    retry that asks the same model to re-emit only contract-compliant JSON. The
    runner still rejects incomplete scene coverage, so repaired output cannot
    silently become a partial experiment result.
    """

    plan_file = Path(plan_path)
    script_file = Path(script_path)
    plan = load_transfer_plan(plan_file)
    scenes = load_selected_scenes(script_file, plan.source_scene_ids)
    run_dir = plan_file.parent
    output_file = Path(output_path) if output_path is not None else run_dir / "rewritten_scenes.json"
    request_file = run_dir / "rewrite_request.json"
    raw_response_file = run_dir / "rewrite_response_raw.txt"
    summary_file = run_dir / "rewrite_summary.json"

    request_payload = build_rewrite_request_payload(
        plan=plan,
        scenes=scenes,
        plan_path=plan_file,
        script_path=script_file,
        model=model,
        temperature=temperature,
        max_scene_chars=max_scene_chars,
        max_tokens=max_tokens,
    )
    write_json(request_file, request_payload.model_dump(mode="json"))

    llm_client = client or VLLMClient(base_url=vllm_base_url, timeout_seconds=float(rewrite_timeout_seconds))
    output: RewriteOutput | None = None
    warnings: list[str] = []
    raw_response = ""
    was_repaired = False
    last_error: Exception | None = None
    normalization_metadata: dict[str, Any] = {
        "normalizer_version": NORMALIZER_VERSION,
        "raw_response_shape": None,
        "normalization_actions": [],
        "validation_warnings": [],
        "rejected_reason": None,
        "scene_coverage_exact": None,
    }
    prompt = request_payload.user_instruction
    max_attempts = max(1, int(schema_retry_count) + 1)

    for attempt_index in range(max_attempts):
        try:
            raw_response = llm_client.generate(
                prompt,
                model,
                system=request_payload.system_instruction,
                format_json=True,
                options={"temperature": temperature, "max_tokens": max_tokens},
                request_metadata={"stage": "rewrite", "task_id": plan.run_id, "attempt": attempt_index + 1},
            )
        except VLLMClientError as exc:
            raise RewriteEngineError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise RewriteEngineError(f"Local rewrite generation failed: {exc}") from exc

        attempt_file = run_dir / f"rewrite_response_attempt_{attempt_index + 1}.txt"
        attempt_file.write_text(raw_response, encoding="utf-8")
        raw_response_file.write_text(raw_response, encoding="utf-8")

        try:
            parsed, parse_repaired, normalization_metadata = parse_rewrite_output(
                raw_response,
                expected_scene_ids=plan.source_scene_ids,
                original_content_by_id={scene.scene_id: scene.content for scene in scenes},
                strict_final_content=strict_final_content,
                min_rewrite_char_ratio=min_rewrite_char_ratio,
                max_rewrite_char_ratio=max_rewrite_char_ratio,
                return_metadata=True,
            )
            warnings.extend(str(item) for item in normalization_metadata.get("validation_warnings", []) or [])
            aligned, alignment_warnings = validate_and_align_rewrite_output(parsed, scenes=scenes, plan=plan)
            output = aligned
            was_repaired = bool(parse_repaired or attempt_index > 0)
            warnings.extend(alignment_warnings)
            if attempt_index > 0:
                warnings.append(f"Model output passed after schema repair retry {attempt_index + 1}/{max_attempts}.")
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt_index >= max_attempts - 1:
                break
            prompt = _repair_instruction(
                request_payload=request_payload,
                raw_response=raw_response,
                error_message=str(exc),
                attempt_number=attempt_index + 2,
                max_attempts=max_attempts,
            )
            write_json(
                run_dir / f"rewrite_repair_request_attempt_{attempt_index + 2}.json",
                {
                    "attempt_number": attempt_index + 2,
                    "max_attempts": max_attempts,
                    "error_message": str(exc),
                    "prompt": prompt,
                },
            )

    if output is None:
        raise RewriteEngineError(str(last_error) if last_error is not None else "Local rewrite output could not be validated.")

    write_json(output_file, output.model_dump(mode="json"))
    summary = RewriteSummary(
        run_id=plan.run_id,
        model=model,
        scene_count=len(output.rewritten_scenes),
        source_scene_ids=plan.source_scene_ids,
        output_path=str(output_file),
        request_path=str(request_file),
        raw_response_path=str(raw_response_file),
        summary_path=str(summary_file),
        response_was_repaired=was_repaired,
        generation_attempt_count=min(max_attempts, 1 + sum(1 for item in warnings if "schema repair retry" in item)),
        schema_retry_count=max(0, min(max_attempts - 1, sum(1 for item in warnings if "schema repair retry" in item))),
        validation_warnings=warnings,
        generation_mode="interval_json",
        normalizer_version=normalization_metadata.get("normalizer_version", NORMALIZER_VERSION),
        raw_response_shape=normalization_metadata.get("raw_response_shape"),
        normalization_actions=normalization_metadata.get("normalization_actions", []),
        rejected_reason=normalization_metadata.get("rejected_reason"),
        scene_coverage_exact=normalization_metadata.get("scene_coverage_exact"),
    )
    write_json(summary_file, summary.model_dump(mode="json"))

    return RewriteRunResult(
        output=output,
        summary=summary,
        request_payload=request_payload,
        raw_response_text=raw_response,
    )


def load_transfer_plan(path: str | Path) -> TransferPlan:
    """Load a Sprint 4 transfer plan."""

    plan_path = Path(path)
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RewriteEngineError(f"Transfer plan does not exist: {plan_path}") from exc
    except json.JSONDecodeError as exc:
        raise RewriteEngineError(f"Invalid transfer plan JSON: {plan_path}") from exc

    try:
        return TransferPlan.model_validate(payload)
    except ValidationError as exc:
        raise RewriteEngineError(f"Transfer plan failed schema validation: {exc}") from exc


def load_selected_scenes(script_path: str | Path, scene_ids: list[str]) -> list[ParsedScene]:
    """Load only the source interval scenes listed in the transfer plan."""

    try:
        scenes = load_scenes(script_path)
    except SceneLoadError as exc:
        raise RewriteEngineError(str(exc)) from exc

    by_id = {scene.scene_id: scene for scene in scenes}
    missing = [scene_id for scene_id in scene_ids if scene_id not in by_id]
    if missing:
        raise RewriteEngineError(f"Script is missing selected scene ids: {', '.join(missing)}")
    return [by_id[scene_id] for scene_id in scene_ids]


def build_rewrite_request_payload(
    *,
    plan: TransferPlan,
    scenes: list[ParsedScene],
    plan_path: str | Path,
    script_path: str | Path,
    model: str,
    temperature: float,
    max_scene_chars: int,
    max_tokens: int = 4096,
) -> RewriteRequestPayload:
    """Build the internal prompt package used by the local LLM."""

    source_scenes: list[SourceSceneForRewrite] = []
    for scene in scenes:
        content, was_truncated = _truncate_scene_text(scene.content, max_scene_chars=max_scene_chars)
        source_scenes.append(
            SourceSceneForRewrite(
                scene_id=scene.scene_id,
                scene_index=scene.scene_index,
                title=scene.title,
                content=content,
                was_truncated=was_truncated,
            )
        )

    directives = [directive.model_dump(mode="json") for directive in plan.per_scene_target_values]
    system_instruction = _system_instruction()
    user_instruction = _user_instruction(
        plan=plan,
        source_scenes=source_scenes,
        directives=directives,
    )

    return RewriteRequestPayload(
        run_id=plan.run_id,
        model=model,
        script_path=str(script_path),
        plan_path=str(plan_path),
        selected_features=plan.selected_features,
        source_scene_ids=plan.source_scene_ids,
        reference_scene_ids=plan.reference_scene_ids,
        preservation_constraints=plan.preservation_constraints,
        source_scenes=source_scenes,
        per_scene_directives=directives,
        system_instruction=system_instruction,
        user_instruction=user_instruction,
        generation_options={
            "temperature": temperature,
            "max_tokens": max_tokens,
            "format": "json_schema",
            "generation_engine": "vllm",
            "engine_version": REWRITE_ENGINE_VERSION,
            "schema_retry_count": DEFAULT_SCHEMA_RETRY_COUNT,
        },
    )


def parse_rewrite_output(
    raw_text: str,
    *,
    expected_scene_ids: list[str] | None = None,
    original_content_by_id: dict[str, str] | None = None,
    strict_final_content: bool = True,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    return_metadata: bool = False,
) -> tuple[RewriteOutput, bool] | tuple[RewriteOutput, bool, dict[str, Any]]:
    """Parse model JSON with Sprint 13 deterministic output normalization."""

    try:
        normalized = normalize_rewrite_raw_text(
            raw_text,
            mode="task",
            expected_scene_ids=expected_scene_ids,
            original_content_by_id=original_content_by_id,
            strict_final_content=strict_final_content,
            min_rewrite_char_ratio=min_rewrite_char_ratio,
            max_rewrite_char_ratio=max_rewrite_char_ratio,
        )
    except Exception as exc:  # noqa: BLE001
        raise RewriteEngineError(f"Could not parse local model response as RewriteOutput JSON: {exc}") from exc

    metadata = {
        "normalizer_version": NORMALIZER_VERSION,
        "raw_response_shape": normalized.raw_response_shape,
        "normalization_actions": normalized.normalization_actions,
        "validation_warnings": normalized.validation_warnings,
        "rejected_reason": normalized.rejected_reason,
        "scene_coverage_exact": normalized.scene_coverage_exact,
    }
    if return_metadata:
        return normalized.output, normalized.repaired, metadata
    return normalized.output, normalized.repaired

def validate_and_align_rewrite_output(
    output: RewriteOutput,
    *,
    scenes: list[ParsedScene],
    plan: TransferPlan,
) -> tuple[RewriteOutput, list[str]]:
    """Ensure output rewrites exactly the selected source interval."""

    expected_ids = [scene.scene_id for scene in scenes]
    scene_by_id = {scene.scene_id: scene for scene in scenes}
    warnings: list[str] = []
    rewritten_by_id: dict[str, RewrittenScene] = {}
    duplicate_ids: list[str] = []

    for scene in output.rewritten_scenes:
        normalized_id = _normalize_scene_id_token(scene.scene_id)
        if normalized_id != scene.scene_id:
            warnings.append(f"{scene.scene_id}: normalized returned scene id to {normalized_id}")
        if normalized_id in rewritten_by_id:
            duplicate_ids.append(normalized_id)
            continue
        rewritten_by_id[normalized_id] = RewrittenScene(
            scene_id=normalized_id,
            title=scene.title,
            content=scene.content,
            change_summary=scene.change_summary,
        )

    if duplicate_ids:
        raise RewriteEngineError(f"Local model returned duplicate selected scenes: {', '.join(sorted(set(duplicate_ids)))}")

    actual_ids = list(rewritten_by_id)
    unexpected = [scene_id for scene_id in actual_ids if scene_id not in scene_by_id]
    missing = [scene_id for scene_id in expected_ids if scene_id not in rewritten_by_id]
    if unexpected:
        raise RewriteEngineError(f"Local model rewrote scenes outside selected interval: {', '.join(unexpected)}")
    if missing:
        raise RewriteEngineError(f"Local model omitted selected scenes: {', '.join(missing)}")

    aligned: list[RewrittenScene] = []
    for scene_id in expected_ids:
        original = scene_by_id[scene_id]
        rewritten = rewritten_by_id[scene_id]
        title = rewritten.title.strip() or original.title
        if title != original.title:
            warnings.append(f"{scene_id}: model changed title; preserved returned title for review")
        if len(rewritten.content.split()) < 5:
            warnings.append(f"{scene_id}: rewritten content is very short")
        aligned.append(
            RewrittenScene(
                scene_id=scene_id,
                title=title,
                content=rewritten.content,
                change_summary=rewritten.change_summary or "Local rewrite applied from transfer plan.",
            )
        )

    if plan.source_scene_ids != expected_ids:
        warnings.append("Selected scene order differed from plan order; output was aligned to script order")

    return RewriteOutput(rewritten_scenes=aligned), warnings


def write_json(path: str | Path, payload: object) -> Path:
    """Write JSON with stable indentation."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _system_instruction() -> str:
    return (
        "You are a local-only screenplay rewrite engine. Rewrite only the selected source scenes according to "
        "the provided structural transfer plan. Preserve source character identities, continuity, setting, scene "
        "order, and core event outcomes unless a directive explicitly requires a macro-level rhythm change. "
        "Return one valid JSON object only. The root key must be exactly rewritten_scenes. Do not use keys named "
        "scenes, scene, source, transformation, or dialogue as the final structure. Do not include markdown, comments, "
        "or prose outside JSON."
    )


def _user_instruction(
    *,
    plan: TransferPlan,
    source_scenes: list[SourceSceneForRewrite],
    directives: list[dict[str, object]],
) -> str:
    expected_scene_template = [
        {
            "scene_id": scene_id,
            "title": "use the matching source scene title unless a minimal title correction is unavoidable",
            "content": "complete rewritten screenplay text for this exact scene id",
            "change_summary": "one short sentence describing the applied feature-curve rewrite",
        }
        for scene_id in plan.source_scene_ids
    ]
    payload = {
        "task": "rewrite_selected_source_interval_using_numeric_feature_targets",
        "critical_output_contract": {
            "root_key": "rewritten_scenes",
            "must_return_scene_count": len(plan.source_scene_ids),
            "required_scene_ids_in_this_exact_order": plan.source_scene_ids,
            "forbidden_final_keys": ["scenes", "scene", "source", "transformation", "dialogue"],
            "required_json_shape": {"rewritten_scenes": expected_scene_template},
        },
        "hard_rules": [
            "Return valid JSON only: no markdown, no explanation, no code fence.",
            "The root JSON key must be exactly rewritten_scenes.",
            "Return exactly one object per source_scene_id and preserve the exact scene_id string.",
            "Do not return partial scenes; if there are 8 source_scene_ids, return 8 rewritten scene objects.",
            "Do not output a transformation plan, action list, or dialogue patch. Output complete rewritten scene text in content.",
            "Do not add scene ids outside the selected source interval.",
            "Preserve source characters, relationships, setting, and event outcome.",
            "Adapt only pacing, scene length, dialogue/action balance, character interaction density, emotion intensity, and dramatic rhythm.",
        ],
        "run_id": plan.run_id,
        "selected_features": plan.selected_features,
        "source_scene_ids": plan.source_scene_ids,
        "preservation_constraints": plan.preservation_constraints,
        "per_scene_directives": directives,
        "source_scenes": [scene.model_dump(mode="json") for scene in source_scenes],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _repair_instruction(
    *,
    request_payload: RewriteRequestPayload,
    raw_response: str,
    error_message: str,
    attempt_number: int,
    max_attempts: int,
) -> str:
    """Ask the local model to repair only its JSON contract, not change the task."""

    expected_scene_template = [
        {
            "scene_id": scene_id,
            "title": "preserve source title",
            "content": "complete rewritten screenplay text for this scene",
            "change_summary": "short summary",
        }
        for scene_id in request_payload.source_scene_ids
    ]
    payload = {
        "task": "repair_invalid_local_rewrite_output",
        "attempt_number": attempt_number,
        "max_attempts": max_attempts,
        "validation_error_to_fix": error_message,
        "non_negotiable_contract": {
            "root_key": "rewritten_scenes",
            "must_return_scene_count": len(request_payload.source_scene_ids),
            "required_scene_ids_in_this_exact_order": request_payload.source_scene_ids,
            "required_json_shape": {"rewritten_scenes": expected_scene_template},
            "forbidden_final_keys": ["scenes", "scene", "source", "transformation", "dialogue"],
        },
        "instructions": [
            "Return only one valid JSON object.",
            "Use the exact scene ids listed above, no numeric-only ids.",
            "Do not omit any selected source scene.",
            "Do not explain the repair.",
            "Use complete rewritten scene text in each content field, not a plan or patch description.",
        ],
        "original_rewrite_request": json.loads(request_payload.user_instruction),
        "previous_invalid_response": _truncate_for_prompt(raw_response, max_chars=12000),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_rewrite_payload(payload: Any) -> tuple[dict[str, Any], bool]:
    """Normalize common local-LLM schema deviations into RewriteOutput shape."""

    repaired = False
    if isinstance(payload, list):
        payload = {"rewritten_scenes": payload}
        repaired = True
    elif isinstance(payload, dict):
        if "rewritten_scenes" not in payload:
            for alias in ("scenes", "scene", "rewrites", "rewrittenScenes", "rewritten_scenes_output"):
                if alias in payload:
                    value = payload[alias]
                    payload = {"rewritten_scenes": value if isinstance(value, list) else [value]}
                    repaired = True
                    break
    if not isinstance(payload, dict):
        return {"rewritten_scenes": payload}, True

    scenes = payload.get("rewritten_scenes")
    if isinstance(scenes, dict):
        scenes = [scenes]
        repaired = True
    if not isinstance(scenes, list):
        return payload, repaired

    normalized_scenes: list[Any] = []
    for item in scenes:
        if not isinstance(item, dict):
            normalized_scenes.append(item)
            continue
        normalized, item_repaired = _normalize_rewritten_scene_payload(item)
        repaired = repaired or item_repaired
        normalized_scenes.append(normalized)
    return {"rewritten_scenes": normalized_scenes}, repaired


def _normalize_rewritten_scene_payload(item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    repaired = False
    scene = dict(item)
    scene_id = (
        scene.get("scene_id")
        or scene.get("sceneId")
        or scene.get("sceneID")
        or scene.get("id")
        or scene.get("scene_number")
        or scene.get("scene_num")
    )
    normalized_id = _normalize_scene_id_token(scene_id)
    if normalized_id != scene.get("scene_id"):
        scene["scene_id"] = normalized_id
        repaired = True

    if not scene.get("title"):
        title = scene.get("heading") or scene.get("name") or ""
        if title:
            scene["title"] = title
            repaired = True

    if not scene.get("content"):
        content = _content_from_nonstandard_scene(scene)
        if content:
            scene["content"] = content
            repaired = True

    if not scene.get("change_summary"):
        summary = scene.get("summary") or scene.get("change") or scene.get("action") or ""
        if summary:
            scene["change_summary"] = str(summary)
            repaired = True
    return scene, repaired


def _content_from_nonstandard_scene(scene: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("content", "modifiedContent", "modified_content", "rewrittenContent", "rewritten_content", "rewritten_text", "text", "body", "description"):
        value = scene.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            break

    transformation = scene.get("transformation")
    if isinstance(transformation, dict):
        action = transformation.get("action")
        if isinstance(action, str) and action.strip():
            parts.append(action.strip())
        dialogue = transformation.get("dialogue")
        if isinstance(dialogue, list):
            for turn in dialogue:
                if isinstance(turn, dict):
                    character = str(turn.get("character") or "").strip()
                    line = str(turn.get("line") or "").strip()
                    if character and line:
                        parts.append(f"{character}: {line}")
                    elif line:
                        parts.append(line)
                elif isinstance(turn, str) and turn.strip():
                    parts.append(turn.strip())
    return "\n".join(parts).strip()


def _normalize_scene_id_token(value: Any) -> str:
    return normalize_scene_id_token(value)


def _truncate_scene_text(content: str, *, max_scene_chars: int) -> tuple[str, bool]:
    text = str(content or "")
    if len(text) <= max_scene_chars:
        return text, False
    marker = "\n[TRUNCATED FOR LOCAL CONTEXT WINDOW; preserve visible continuity.]"
    return text[: max(0, max_scene_chars - len(marker))].rstrip() + marker, True


def _truncate_for_prompt(text: str, *, max_chars: int) -> str:
    raw = str(text or "")
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars].rstrip() + "\n[TRUNCATED PREVIOUS INVALID RESPONSE]"


def _strip_code_fence(text: str) -> str:
    pattern = r"^```(?:json)?\s*(.*?)\s*```$"
    match = re.match(pattern, text.strip(), flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return text
    return match.group(1).strip()


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from noisy model text."""

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
