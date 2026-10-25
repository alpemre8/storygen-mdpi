"""Per-scene local rewrite engine for legacy metric evaluation.

Sprint 12 changes the experiment execution protocol from interval-level JSON
completion to one local-model call per selected source scene. The task-level
artifacts remain compatible with the existing re-analysis and metric pipeline:
all validated per-scene outputs are aggregated into the existing
``rewritten_scenes.json`` shape.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from storygen.schemas.rewrite import RewriteOutput, RewriteRunResult, RewriteSummary, RewrittenScene
from storygen.schemas.scene import ParsedScene
from storygen.schemas.transfer import SceneRewriteDirective, TransferPlan
from storygen.services.vllm_client import VLLMClient, VLLMClientError
from storygen.services.rewrite_engine import (
    DEFAULT_MODEL,
    DEFAULT_VLLM_BASE_URL,
    DEFAULT_SCHEMA_RETRY_COUNT,
    LocalGenerationClient,
    RewriteEngineError,
    _truncate_for_prompt,
    _truncate_scene_text,
    build_rewrite_request_payload,
    load_selected_scenes,
    load_transfer_plan,
    write_json,
)
from storygen.services.rewrite_output_normalizer import NORMALIZER_VERSION, normalize_rewrite_raw_text

PER_SCENE_REWRITE_ENGINE_VERSION = "local.per_scene_rewrite_engine.v1_1_nometa"
PROMPT_STRATEGY_CURVE_GUIDED = "curve_guided"
PROMPT_STRATEGY_DIRECT_PROMPT = "direct_prompt"
PROMPT_STRATEGY_NO_GUIDANCE = "no_guidance"
PROMPT_STRATEGIES = {PROMPT_STRATEGY_CURVE_GUIDED, PROMPT_STRATEGY_DIRECT_PROMPT, PROMPT_STRATEGY_NO_GUIDANCE}
PROMPT_VERSION_V1 = "v1"
PROMPT_VERSION_V2 = "v2"
PROMPT_VERSIONS = {PROMPT_VERSION_V1, "v0"}
OUTPUT_CONTRACT_STRUCTURED_JSON = "structured_json"
OUTPUT_CONTRACT_CONTENT_ONLY = "content_only"
REWRITE_FORMAT_MODE_SCHEMA = "schema"
REWRITE_FORMAT_MODE_JSON = "json"
REWRITE_FORMAT_MODE_CONTENT_ONLY = "content_only"
REWRITE_FORMAT_MODES = {REWRITE_FORMAT_MODE_SCHEMA, REWRITE_FORMAT_MODE_JSON, REWRITE_FORMAT_MODE_CONTENT_ONLY}
REWRITE_PROMPT_TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "prompts"
REPAIR_PER_SCENE_TEMPLATE = "repair_per_scene_prompt_v1.json"
_PROMPT_ASSETS: dict[tuple[str, str], dict[str, str]] = {
    (PROMPT_STRATEGY_NO_GUIDANCE, "v0"): {
        "system": "no_guidance_system_v0.txt",
        "user": "no_guidance_per_scene_prompt_v0.json",
        "output_contract": OUTPUT_CONTRACT_STRUCTURED_JSON,
    },
    (PROMPT_STRATEGY_CURVE_GUIDED, PROMPT_VERSION_V1): {
        "system": "curve_guided_system_v1.txt",
        "user": "curve_guided_per_scene_prompt_v1.json",
        "output_contract": OUTPUT_CONTRACT_STRUCTURED_JSON,
    },
    (PROMPT_STRATEGY_DIRECT_PROMPT, PROMPT_VERSION_V1): {
        "system": "direct_prompt_system_v1.txt",
        "user": "direct_prompt_per_scene_prompt_v1.json",
        "output_contract": OUTPUT_CONTRACT_STRUCTURED_JSON,
    },
}
_REWRITE_PROMPT_TEMPLATE_CACHE: dict[str, Any] = {}

ONE_SCENE_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scene_id", "title", "content", "change_summary"],
    "properties": {
        "scene_id": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string", "minLength": 1},
        "change_summary": {"type": "string"},
    },
}


def one_scene_rewrite_schema_for(expected_scene_id: str | None = None) -> dict[str, Any]:
    """Return the one-scene schema, optionally locking scene_id to one exact value.

    Patch 010 keeps schema-constrained decoding for Gemma but removes the loose
    ``scene_id: string`` hole that allowed outputs such as ``scene_123``. vLLM
    accepts OpenAI-compatible JSON-schema response formats; when enum support is available, this
    makes the first field deterministic instead of relying only on prompt text.
    """

    schema = json.loads(json.dumps(ONE_SCENE_REWRITE_SCHEMA))
    scene_id = str(expected_scene_id or "").strip()
    if scene_id:
        schema["properties"]["scene_id"] = {"type": "string", "enum": [scene_id]}
    return schema


_DIRECT_FEATURE_LABELS: dict[str, str] = {
    "scene_length_score": "pacing / scene length",
    "dialogue_ratio": "dialogue density",
    "action_ratio": "visual action emphasis",
    "character_density": "character interaction density",
    "emotion_intensity": "emotional intensity",
    "tension_score": "tension",
    "semantic_novelty_score": "new information / novelty",
    "plot_movement_score": "plot movement",
    "llm_pacing_score": "LLM pacing",
    "llm_emotion_intensity_score": "LLM emotional intensity",
}


def run_per_scene_rewrite_from_files(
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
    allow_partial_task_output: bool = False,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    strict_final_content: bool = True,
    prompt_strategy: str = PROMPT_STRATEGY_CURVE_GUIDED,
    prompt_version: str = PROMPT_VERSION_V1,
    rewrite_timeout_seconds: float = 180.0,
    rewrite_format_mode: str = REWRITE_FORMAT_MODE_SCHEMA,
    rewrite_max_tokens: int | None = 4096,
    rewrite_max_output_chars: int | None = None,
    generation_concurrency: int = 4,
    progress_callback: Callable[[str], None] | None = None,
) -> RewriteRunResult:
    """Rewrite selected source scenes one scene at a time.

    The model is never asked to emit an interval-level list. Each successful
    scene response is assigned the expected source scene id deterministically,
    then all scenes are aggregated into the normal ``RewriteOutput`` contract.
    """

    prompt_strategy = _normalize_prompt_strategy(prompt_strategy)
    prompt_version = _normalize_prompt_version(prompt_version)
    rewrite_format_mode = _normalize_rewrite_format_mode(rewrite_format_mode)
    output_contract = _validate_prompt_output_contract(
        prompt_strategy=prompt_strategy,
        prompt_version=prompt_version,
        rewrite_format_mode=rewrite_format_mode,
        schema_retry_count=schema_retry_count,
    )

    plan_file = Path(plan_path)
    script_file = Path(script_path)
    plan = load_transfer_plan(plan_file)
    scenes = load_selected_scenes(script_file, plan.source_scene_ids)
    run_dir = plan_file.parent
    output_file = Path(output_path) if output_path is not None else run_dir / "rewritten_scenes.json"
    request_file = run_dir / "rewrite_request.json"
    raw_response_file = run_dir / "rewrite_response_raw.txt"
    summary_file = run_dir / "rewrite_summary.json"
    per_scene_dir = run_dir / "per_scene"
    per_scene_dir.mkdir(parents=True, exist_ok=True)

    aggregate_payload = build_rewrite_request_payload(
        plan=plan,
        scenes=scenes,
        plan_path=plan_file,
        script_path=script_file,
        model=model,
        temperature=temperature,
        max_scene_chars=max_scene_chars,
    )
    aggregate_request = {
        "generation_mode": "per_scene_json",
        "prompt_strategy": prompt_strategy,
        "prompt_version": prompt_version,
        "prompt_profile": _prompt_profile(prompt_strategy),
        "information_policy": {
            "reference_film_identity_exposed": False,
            "reference_scene_identity_exposed": False,
            "cg_only_adds_current_target_delta": prompt_strategy == PROMPT_STRATEGY_CURVE_GUIDED,
        },
        "model_output_contract": output_contract,
        "engine_version": PER_SCENE_REWRITE_ENGINE_VERSION,
        "run_id": plan.run_id,
        "model": model,
        "script_path": str(script_file),
        "plan_path": str(plan_file),
        "selected_features": plan.selected_features,
        "source_scene_ids": plan.source_scene_ids,
        "preservation_constraints": plan.preservation_constraints,
        "schema_retry_count": schema_retry_count,
        "allow_partial_task_output": allow_partial_task_output,
        "normalizer_version": NORMALIZER_VERSION,
        "min_rewrite_char_ratio": min_rewrite_char_ratio,
        "max_rewrite_char_ratio": max_rewrite_char_ratio,
        "strict_final_content": strict_final_content,
        "one_scene_rewrite_schema": ONE_SCENE_REWRITE_SCHEMA,
        "scene_id_locked_schema_available": True,
        "rewrite_timeout_seconds": rewrite_timeout_seconds,
        "rewrite_format_mode": rewrite_format_mode,
        "rewrite_max_tokens": _positive_int(rewrite_max_tokens),
        "rewrite_max_output_chars": _positive_int(rewrite_max_output_chars),
        "post_generation_json_guard_enabled": output_contract == OUTPUT_CONTRACT_STRUCTURED_JSON,
        "content_only_extractor_enabled": output_contract == OUTPUT_CONTRACT_CONTENT_ONLY,
        "generation_engine": "vllm",
        "vllm_base_url": vllm_base_url,
        "generation_concurrency_requested": max(1, int(generation_concurrency)),
        "per_scene_artifact_root": str(per_scene_dir),
        "direct_prompt_baseline_note": (
            "When prompt_strategy=direct_prompt, the transfer plan is retained for hidden evaluation, "
            "but the model prompt receives only a natural-language rewrite instruction and no numeric "
            "reference curve, target values, or per-scene deltas."
        ),
    }
    write_json(request_file, aggregate_request)

    llm_client = client or VLLMClient(base_url=vllm_base_url, timeout_seconds=float(rewrite_timeout_seconds))
    directive_by_id = {directive.scene_id: directive for directive in plan.per_scene_target_values}
    rewritten: list[RewrittenScene] = []
    validation_warnings: list[str] = []
    failures: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    total_attempts = 0
    repaired_count = 0

    requested_concurrency = max(1, int(generation_concurrency))
    effective_concurrency = min(requested_concurrency, max(1, len(scenes)))
    aggregate_request["generation_concurrency_effective"] = effective_concurrency
    write_json(request_file, aggregate_request)

    def run_scene_job(scene_index: int, scene: ParsedScene) -> dict[str, Any]:
        try:
            directive = directive_by_id.get(scene.scene_id)
            if directive is None:
                raise RewriteEngineError(f"Transfer plan missing per-scene directive for {scene.scene_id}")
            return _run_one_scene(
                scene=scene,
                directive=directive,
                plan=plan,
                scene_position_index=scene_index,
                scene_count=len(scenes),
                scene_dir=per_scene_dir / scene.scene_id,
                model=model,
                temperature=temperature,
                max_scene_chars=max_scene_chars,
                client=llm_client,
                schema_retry_count=schema_retry_count,
                min_rewrite_char_ratio=min_rewrite_char_ratio,
                max_rewrite_char_ratio=max_rewrite_char_ratio,
                strict_final_content=strict_final_content,
                prompt_strategy=prompt_strategy,
                prompt_version=prompt_version,
                rewrite_format_mode=rewrite_format_mode,
                rewrite_max_tokens=rewrite_max_tokens,
                rewrite_max_output_chars=rewrite_max_output_chars,
            )
        finally:
            if progress_callback is not None:
                try:
                    progress_callback(scene.scene_id)
                except Exception:
                    # Progress reporting must never fail an inference job.
                    pass

    if effective_concurrency == 1:
        scene_results = [run_scene_job(index, scene) for index, scene in enumerate(scenes)]
    else:
        with ThreadPoolExecutor(
            max_workers=effective_concurrency,
            thread_name_prefix="storygen-vllm-rewrite",
        ) as executor:
            futures = [executor.submit(run_scene_job, index, scene) for index, scene in enumerate(scenes)]
            # Resolve in source order so aggregation and artifact references remain
            # deterministic even though HTTP requests finish out of order.
            scene_results = [future.result() for future in futures]

    for scene, scene_result in zip(scenes, scene_results, strict=True):
        total_attempts += int(scene_result["attempt_count"])
        raw_responses.append({"scene_id": scene.scene_id, "raw_response_path": scene_result["raw_response_path"]})
        if scene_result["succeeded"]:
            rewritten.append(scene_result["rewritten_scene"])
            validation_warnings.extend(scene_result.get("warnings", []))
            if scene_result.get("response_was_repaired"):
                repaired_count += 1
            continue

        failure = {
            "scene_id": scene.scene_id,
            "error_message": scene_result.get("error_message", "unknown per-scene rewrite failure"),
            "scene_summary_path": scene_result.get("scene_summary_path"),
        }
        failures.append(failure)

    if failures and not allow_partial_task_output:
        first = failures[0]
        raise RewriteEngineError(
            f"Per-scene rewrite failed for {first['scene_id']}: {first['error_message']}"
        )
    if failures:
        validation_warnings.append(
            f"partial_task_output_enabled: {len(failures)} of {len(scenes)} selected scenes failed; paper metrics should exclude this task."
        )
    if not rewritten:
        raise RewriteEngineError("Per-scene rewrite produced no valid rewritten scenes.")

    rewritten_by_id = {scene.scene_id: scene for scene in rewritten}
    missing = [scene.scene_id for scene in scenes if scene.scene_id not in rewritten_by_id]
    if missing and not allow_partial_task_output:
        raise RewriteEngineError(f"Per-scene aggregation missing selected scenes: {', '.join(missing)}")

    ordered_output = RewriteOutput(
        rewritten_scenes=[rewritten_by_id[scene.scene_id] for scene in scenes if scene.scene_id in rewritten_by_id]
    )
    write_json(output_file, ordered_output.model_dump(mode="json"))
    write_json(
        raw_response_file,
        {
            "generation_mode": "per_scene_json",
            "prompt_strategy": prompt_strategy,
            "prompt_version": prompt_version,
            "model_output_contract": output_contract,
            "engine_version": PER_SCENE_REWRITE_ENGINE_VERSION,
            "scene_raw_responses": raw_responses,
            "failed_scenes": failures,
        },
    )

    summary = RewriteSummary(
        run_id=plan.run_id,
        model=model,
        scene_count=len(ordered_output.rewritten_scenes),
        source_scene_ids=plan.source_scene_ids,
        output_path=str(output_file),
        request_path=str(request_file),
        raw_response_path=str(raw_response_file),
        summary_path=str(summary_file),
        response_was_repaired=repaired_count > 0,
        generation_attempt_count=total_attempts,
        schema_retry_count=max(0, total_attempts - len(scenes)),
        validation_warnings=validation_warnings,
        generation_mode="per_scene_json",
        normalizer_version=NORMALIZER_VERSION,
        raw_response_shape="per_scene_aggregate",
        normalization_actions=[],
        rejected_reason=None,
        scene_coverage_exact=(not failures and len(ordered_output.rewritten_scenes) == len(scenes)),
    )
    write_json(
        summary_file,
        {
            **summary.model_dump(mode="json"),
            "generation_mode": "per_scene_json",
            "prompt_strategy": prompt_strategy,
            "prompt_version": prompt_version,
            "model_output_contract": output_contract,
            "engine_version": PER_SCENE_REWRITE_ENGINE_VERSION,
            "failed_scene_count": len(failures),
            "failed_scenes": failures,
            "allow_partial_task_output": allow_partial_task_output,
            "generation_engine": "vllm",
            "vllm_base_url": vllm_base_url,
            "generation_concurrency_requested": requested_concurrency,
            "generation_concurrency_effective": effective_concurrency,
            "rewrite_max_tokens": _positive_int(rewrite_max_tokens),
        },
    )

    return RewriteRunResult(
        output=ordered_output,
        summary=summary,
        request_payload=aggregate_payload,
        raw_response_text=json.dumps(raw_responses, ensure_ascii=False),
    )


def _run_one_scene(
    *,
    scene: ParsedScene,
    directive: SceneRewriteDirective,
    plan: TransferPlan,
    scene_position_index: int,
    scene_count: int,
    scene_dir: Path,
    model: str,
    temperature: float,
    max_scene_chars: int,
    client: LocalGenerationClient,
    schema_retry_count: int,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    strict_final_content: bool = True,
    prompt_strategy: str = PROMPT_STRATEGY_CURVE_GUIDED,
    prompt_version: str = PROMPT_VERSION_V1,
    rewrite_format_mode: str = REWRITE_FORMAT_MODE_SCHEMA,
    rewrite_max_tokens: int | None = None,
    rewrite_max_output_chars: int | None = None,
) -> dict[str, Any]:
    scene_dir.mkdir(parents=True, exist_ok=True)
    prompt_strategy = _normalize_prompt_strategy(prompt_strategy)
    prompt_version = _normalize_prompt_version(prompt_version)
    rewrite_format_mode = _normalize_rewrite_format_mode(rewrite_format_mode)
    output_contract = _validate_prompt_output_contract(
        prompt_strategy=prompt_strategy,
        prompt_version=prompt_version,
        rewrite_format_mode=rewrite_format_mode,
        schema_retry_count=schema_retry_count,
    )

    if prompt_strategy == PROMPT_STRATEGY_NO_GUIDANCE:
        prompt = build_per_scene_no_guidance_prompt(
            scene=scene, scene_position_index=scene_position_index,
            scene_count=scene_count, max_scene_chars=max_scene_chars,
        )
        system = str(_load_rewrite_prompt_template(_resolve_prompt_assets(prompt_strategy, prompt_version)["system"]))
    elif prompt_strategy == PROMPT_STRATEGY_DIRECT_PROMPT:
        prompt = build_per_scene_direct_prompt(
            scene=scene,
            directive=directive,
            plan=plan,
            scene_position_index=scene_position_index,
            scene_count=scene_count,
            max_scene_chars=max_scene_chars,
            prompt_version=prompt_version,
        )
        system = _per_scene_direct_system_instruction(prompt_version=prompt_version)
    else:
        prompt = build_per_scene_rewrite_prompt(
            scene=scene,
            directive=directive,
            plan=plan,
            scene_position_index=scene_position_index,
            scene_count=scene_count,
            max_scene_chars=max_scene_chars,
            prompt_version=prompt_version,
        )
        system = _per_scene_system_instruction(prompt_version=prompt_version)

    request_payload = {
        "generation_mode": "per_scene_json",
        "prompt_strategy": prompt_strategy,
        "prompt_version": prompt_version,
        "prompt_profile": _prompt_profile(prompt_strategy),
        "information_policy": {
            "reference_film_identity_exposed": False,
            "reference_scene_identity_exposed": False,
            "cg_only_adds_current_target_delta": prompt_strategy == PROMPT_STRATEGY_CURVE_GUIDED,
        },
        "model_output_contract": output_contract,
        "engine_version": PER_SCENE_REWRITE_ENGINE_VERSION,
        "expected_scene_id": scene.scene_id,
        "model": model,
        "temperature": temperature,
        "system_instruction": system,
        "user_instruction": prompt,
        "format_schema": one_scene_rewrite_schema_for(scene.scene_id)
        if rewrite_format_mode == REWRITE_FORMAT_MODE_SCHEMA
        else None,
        "format_json": rewrite_format_mode == REWRITE_FORMAT_MODE_JSON,
        "rewrite_format_mode": rewrite_format_mode,
        "rewrite_max_tokens": _positive_int(rewrite_max_tokens),
        "rewrite_max_output_chars": _positive_int(rewrite_max_output_chars),
        "post_generation_json_guard_enabled": output_contract == OUTPUT_CONTRACT_STRUCTURED_JSON,
        "content_only_extractor_enabled": output_contract == OUTPUT_CONTRACT_CONTENT_ONLY,
    }
    write_json(scene_dir / "rewrite_request.json", request_payload)
    base_prompt = prompt

    max_attempts = (
        1
        if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY
        else max(1, int(schema_retry_count) + 1)
    )
    raw_response = ""
    last_error: Exception | None = None
    warnings: list[str] = []
    response_was_repaired = False

    for attempt_index in range(max_attempts):
        try:
            raw_response = _generate_scene_non_streaming(
                client=client,
                prompt=prompt,
                model=model,
                system=system,
                temperature=temperature,
                expected_scene_id=scene.scene_id,
                rewrite_format_mode=rewrite_format_mode,
                output_contract=output_contract,
                rewrite_max_tokens=rewrite_max_tokens,
                rewrite_max_output_chars=rewrite_max_output_chars,
            )
        except RunawayRewriteError as exc:
            raw_response = exc.raw_response
            last_error = RewriteEngineError(str(exc))
            _write_attempt_raw(scene_dir, attempt_index + 1, raw_response)
            if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY or attempt_index >= max_attempts - 1:
                break
            repair_mode = _repair_failure_mode(raw_response, f"post_generation_guard: {exc}", scene.scene_id)
            prompt = _per_scene_repair_prompt(
                expected_scene_id=scene.scene_id,
                expected_scene_title=scene.title,
                original_prompt=base_prompt,
                raw_response=raw_response,
                error_message=f"post_generation_guard: {exc}",
                attempt_number=attempt_index + 2,
                max_attempts=max_attempts,
                repair_mode=repair_mode,
            )
            write_json(
                scene_dir / f"rewrite_repair_request_attempt_{attempt_index + 2}.json",
                {
                    "attempt_number": attempt_index + 2,
                    "max_attempts": max_attempts,
                    "error_message": f"post_generation_guard: {exc}",
                    "format_schema": one_scene_rewrite_schema_for(scene.scene_id)
                    if rewrite_format_mode == REWRITE_FORMAT_MODE_SCHEMA
                    else None,
                    "format_json": rewrite_format_mode == REWRITE_FORMAT_MODE_JSON,
                    "rewrite_format_mode": rewrite_format_mode,
                    "prompt": prompt,
                    "repair_mode": repair_mode,
                    "previous_invalid_response_policy": _previous_invalid_response_policy(raw_response, repair_mode),
                },
            )
            continue
        except VLLMClientError as exc:
            last_error = RewriteEngineError(str(exc))
            break
        except Exception as exc:  # noqa: BLE001
            last_error = RewriteEngineError(f"Local per-scene rewrite generation failed: {exc}")
            break

        _write_attempt_raw(scene_dir, attempt_index + 1, raw_response)

        try:
            rewritten_scene, parse_repaired, parse_warnings, normalization_metadata = parse_per_scene_output(
                raw_response,
                expected_scene=scene,
                output_contract=output_contract,
                strict_final_content=strict_final_content,
                min_rewrite_char_ratio=min_rewrite_char_ratio,
                max_rewrite_char_ratio=max_rewrite_char_ratio,
                return_metadata=True,
            )
            warnings.extend(parse_warnings)
            response_was_repaired = bool(parse_repaired or attempt_index > 0)
            if attempt_index > 0:
                warnings.append(
                    f"{scene.scene_id}: per-scene output passed after retry {attempt_index + 1}/{max_attempts}."
                )
            summary = {
                "scene_id": scene.scene_id,
                "succeeded": True,
                "prompt_strategy": prompt_strategy,
                "prompt_version": prompt_version,
                "model_output_contract": output_contract,
                "attempt_count": attempt_index + 1,
                "response_was_repaired": response_was_repaired,
                "warnings": warnings,
                "normalizer_version": normalization_metadata.get("normalizer_version"),
                "raw_response_shape": normalization_metadata.get("raw_response_shape"),
                "normalization_actions": normalization_metadata.get("normalization_actions", []),
                "rejected_reason": normalization_metadata.get("rejected_reason"),
                "scene_coverage_exact": normalization_metadata.get("scene_coverage_exact"),
                "raw_response_path": str(scene_dir / "rewrite_response_raw.txt"),
                "rewritten_scene_path": str(scene_dir / "rewritten_scene.json"),
                "scene_summary_path": str(scene_dir / "scene_summary.json"),
            }
            write_json(scene_dir / "rewritten_scene.json", rewritten_scene.model_dump(mode="json"))
            write_json(scene_dir / "scene_summary.json", summary)
            return {**summary, "rewritten_scene": rewritten_scene}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY or attempt_index >= max_attempts - 1:
                break
            repair_mode = _repair_failure_mode(raw_response, str(exc), scene.scene_id)
            prompt = _per_scene_repair_prompt(
                expected_scene_id=scene.scene_id,
                expected_scene_title=scene.title,
                original_prompt=base_prompt,
                raw_response=raw_response,
                error_message=str(exc),
                attempt_number=attempt_index + 2,
                max_attempts=max_attempts,
                repair_mode=repair_mode,
            )
            write_json(
                scene_dir / f"rewrite_repair_request_attempt_{attempt_index + 2}.json",
                {
                    "attempt_number": attempt_index + 2,
                    "max_attempts": max_attempts,
                    "error_message": str(exc),
                    "format_schema": one_scene_rewrite_schema_for(scene.scene_id)
                    if rewrite_format_mode == REWRITE_FORMAT_MODE_SCHEMA
                    else None,
                    "format_json": rewrite_format_mode == REWRITE_FORMAT_MODE_JSON,
                    "rewrite_format_mode": rewrite_format_mode,
                    "prompt": prompt,
                    "repair_mode": repair_mode,
                    "previous_invalid_response_policy": _previous_invalid_response_policy(raw_response, repair_mode),
                },
            )

    summary = {
        "scene_id": scene.scene_id,
        "succeeded": False,
        "prompt_strategy": prompt_strategy,
        "prompt_version": prompt_version,
        "prompt_profile": _prompt_profile(prompt_strategy),
        "information_policy": {
            "reference_film_identity_exposed": False,
            "reference_scene_identity_exposed": False,
            "cg_only_adds_current_target_delta": prompt_strategy == PROMPT_STRATEGY_CURVE_GUIDED,
        },
        "model_output_contract": output_contract,
        "attempt_count": max_attempts,
        "response_was_repaired": response_was_repaired,
        "error_message": str(last_error) if last_error is not None else "Unknown per-scene rewrite validation failure.",
        "normalizer_version": (
            "content_only_extractor.v1"
            if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY
            else NORMALIZER_VERSION
        ),
        "raw_response_path": str(scene_dir / "rewrite_response_raw.txt"),
        "scene_summary_path": str(scene_dir / "scene_summary.json"),
    }
    write_json(scene_dir / "scene_summary.json", summary)
    return summary


class RunawayRewriteError(RewriteEngineError):
    """Raised when a completed non-streaming response shows recursive JSON degeneration."""

    def __init__(self, message: str, *, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


def _generate_scene_non_streaming(
    *,
    client: LocalGenerationClient,
    prompt: str,
    model: str,
    system: str,
    temperature: float,
    expected_scene_id: str,
    rewrite_format_mode: str,
    output_contract: str,
    rewrite_max_tokens: int | None,
    rewrite_max_output_chars: int | None,
) -> str:
    """Generate one scene without streaming and apply the contract-specific guard."""

    rewrite_format_mode = _normalize_rewrite_format_mode(rewrite_format_mode)
    options: dict[str, Any] = {"temperature": temperature}
    max_tokens = _positive_int(rewrite_max_tokens)
    if max_tokens is not None:
        options["max_tokens"] = max_tokens

    format_schema = (
        one_scene_rewrite_schema_for(expected_scene_id)
        if rewrite_format_mode == REWRITE_FORMAT_MODE_SCHEMA
        else None
    )
    format_json = rewrite_format_mode == REWRITE_FORMAT_MODE_JSON
    try:
        raw_response = client.generate(
            prompt,
            model,
            system=system,
            format_schema=format_schema,
            format_json=format_json,
            options=options,
            request_metadata={
                "stage": "rewrite",
                "scene_id": expected_scene_id,
                "attempt_kind": "primary_or_repair",
                "model_output_contract": output_contract,
            },
        )
    except TypeError:
        raw_response = client.generate(
            prompt,
            model,
            system=system,
            format_schema=format_schema,
            format_json=format_json,
            options=options,
        )

    if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY:
        reason = _detect_runaway_content(
            raw_response,
            expected_scene_id=expected_scene_id,
            max_output_chars=_positive_int(rewrite_max_output_chars),
        )
    else:
        reason = _detect_runaway_json(
            raw_response,
            expected_scene_id=expected_scene_id,
            max_output_chars=_positive_int(rewrite_max_output_chars),
        )
    if reason:
        raise RunawayRewriteError(
            f"runaway rewrite generation rejected for {expected_scene_id}: {reason}",
            raw_response=raw_response,
        )
    return raw_response


def _detect_runaway_json(
    current: str,
    *,
    expected_scene_id: str,
    max_output_chars: int | None = None,
) -> str | None:
    """Detect known recursive/wrong-root patterns after a non-streaming response."""

    if max_output_chars is not None and len(current) > max_output_chars:
        return f"output exceeded max_output_chars={max_output_chars}"

    root_key = _first_json_root_key(current)
    if root_key and root_key in _FORBIDDEN_ROOT_KEYS:
        return f"forbidden root key detected: {root_key}"

    first_scene_id = _first_json_scene_id(current)
    if first_scene_id and expected_scene_id and first_scene_id != expected_scene_id:
        return f"wrong first scene_id: expected {expected_scene_id}, got {first_scene_id}"

    scene_key_count = current.count('"scene_id"') + current.count('\\"scene_id\\"')
    content_key_count = current.count('"content"') + current.count('\\"content\\"')
    title_key_count = current.count('"title"') + current.count('\\"title\\"')
    if scene_key_count >= 8 and content_key_count >= 6:
        return f"recursive JSON pattern detected: scene_id_count={scene_key_count}, content_count={content_key_count}"
    if current.count('"scene_id": "scene_123"') + current.count('\\"scene_id\\": \\"scene_123\\"') >= 3:
        return "recursive placeholder scene_123 pattern detected"
    if current.count('"title": "Revised Scene"') + current.count('\\"title\\": \\"Revised Scene\\"') >= 3:
        return "recursive Revised Scene placeholder pattern detected"
    if re.search(r'"content"\s*:\s*\{', current):
        return "content field became a nested JSON object"
    if re.search(r'"content"\s*:\s*"\s*\{\s*\\n?\s*\\?"scene_id\\?"', current):
        return "content field began with an embedded JSON scene object"
    if title_key_count >= 8 and content_key_count >= 8:
        return f"recursive title/content nesting detected: title_count={title_key_count}, content_count={content_key_count}"
    return None


def _first_json_scene_id(text: str) -> str | None:
    match = re.search(r'"scene_id"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1).strip()
    match = re.search(r'\\"scene_id\\"\s*:\s*\\"([^\\"]+)\\"', text)
    if match:
        return match.group(1).strip()
    return None


def _write_attempt_raw(scene_dir: Path, attempt_number: int, raw_response: str) -> None:
    text = str(raw_response or "")
    (scene_dir / f"rewrite_response_attempt_{attempt_number}.txt").write_text(text, encoding="utf-8")
    (scene_dir / "rewrite_response_raw.txt").write_text(text, encoding="utf-8")


def _positive_int(value: int | None) -> int | None:
    try:
        if value is None:
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_rewrite_format_mode(value: str | None) -> str:
    mode = str(value or REWRITE_FORMAT_MODE_SCHEMA).strip().lower().replace("-", "_")
    aliases = {
        "schema": REWRITE_FORMAT_MODE_SCHEMA,
        "format_schema": REWRITE_FORMAT_MODE_SCHEMA,
        "json_schema": REWRITE_FORMAT_MODE_SCHEMA,
        "json": REWRITE_FORMAT_MODE_JSON,
        "format_json": REWRITE_FORMAT_MODE_JSON,
        "content": REWRITE_FORMAT_MODE_CONTENT_ONLY,
        "content_only": REWRITE_FORMAT_MODE_CONTENT_ONLY,
        "text": REWRITE_FORMAT_MODE_CONTENT_ONLY,
    }
    if mode not in aliases:
        raise RewriteEngineError(
            f"Unsupported rewrite format mode: {value}. Expected schema, json, or content_only."
        )
    return aliases[mode]


def _normalize_prompt_version(value: str | None) -> str:
    version = str(value or PROMPT_VERSION_V1).strip().lower().replace("-", "")
    aliases = {"1": PROMPT_VERSION_V1, "v1": PROMPT_VERSION_V1, "0": "v0", "v0": "v0"}
    if version not in aliases:
        raise RewriteEngineError(f"Unsupported prompt version: {value}. Use v1 for DP/CG or v0 for NG.")
    return aliases[version]


def _resolve_prompt_assets(prompt_strategy: str, prompt_version: str) -> dict[str, str]:
    key = (_normalize_prompt_strategy(prompt_strategy), _normalize_prompt_version(prompt_version))
    assets = _PROMPT_ASSETS.get(key)
    if assets is None:
        raise RewriteEngineError(
            f"No rewrite prompt assets registered for strategy={key[0]} version={key[1]}"
        )
    return assets


def _validate_prompt_output_contract(
    *,
    prompt_strategy: str,
    prompt_version: str,
    rewrite_format_mode: str,
    schema_retry_count: int,
) -> str:
    assets = _resolve_prompt_assets(prompt_strategy, prompt_version)
    output_contract = assets["output_contract"]
    if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY:
        if rewrite_format_mode != REWRITE_FORMAT_MODE_CONTENT_ONLY:
            raise RewriteEngineError("Prompt v2 requires rewrite_format_mode=content_only")
        if int(schema_retry_count) != 0:
            raise RewriteEngineError("Prompt v2 content-only generation requires schema_retry_count=0")
    elif rewrite_format_mode == REWRITE_FORMAT_MODE_CONTENT_ONLY:
        raise RewriteEngineError("rewrite_format_mode=content_only requires prompt_version=v2")
    return output_contract


def _detect_runaway_content(
    current: str,
    *,
    expected_scene_id: str,
    max_output_chars: int | None = None,
) -> str | None:
    text = str(current or "")
    if max_output_chars is not None and len(text) > max_output_chars:
        return f"output_chars={len(text)} exceeds max_output_chars={max_output_chars}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 12:
        counts: dict[str, int] = {}
        for line in lines:
            if len(line) < 12:
                continue
            counts[line] = counts.get(line, 0) + 1
        if counts:
            line, count = max(counts.items(), key=lambda item: item[1])
            if count >= 8 or count / len(lines) >= 0.5:
                return f"runaway_repeated_line count={count} line={line[:80]!r}"
    words = text.split()
    if len(words) >= 240:
        tail = " ".join(words[-80:])
        if tail and text.count(tail) >= 3:
            return "runaway_repeated_tail_block"
    return None


REPAIR_MODE_SCHEMA_CONTRACT = "schema_contract_repair"
REPAIR_MODE_FRESH_IDENTITY_RETRY = "fresh_identity_retry"

_FORBIDDEN_ROOT_KEYS = {
    "model_response",
    "response",
    "model_name",
    "temperature",
    "top_p",
    "max_tokens",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "scene",
    "action",
    "dialogue",
    "dialogues",
    "rewritten_scenes",
    "scenes",
}


def _repair_failure_mode(raw_response: str, error_message: str, expected_scene_id: str) -> str:
    text = str(raw_response or "")
    err = str(error_message or "").lower()
    first_scene_id = _first_json_scene_id(text)
    if first_scene_id and first_scene_id != expected_scene_id:
        return REPAIR_MODE_FRESH_IDENTITY_RETRY
    if "wrong first scene_id" in err or "runaway_generation_aborted" in err:
        return REPAIR_MODE_FRESH_IDENTITY_RETRY
    if _looks_like_runaway_json(text) or _looks_like_wrong_root_wrapper(text):
        return REPAIR_MODE_FRESH_IDENTITY_RETRY
    if "model_response" in text[:800] or "gpt-4" in text[:800] or '"content"' in text[:200] and re.search(r'"content"\s*:\s*\{', text[:800]):
        return REPAIR_MODE_FRESH_IDENTITY_RETRY
    return REPAIR_MODE_SCHEMA_CONTRACT


def _previous_invalid_response_policy(raw_response: str, repair_mode: str) -> str:
    if repair_mode == REPAIR_MODE_FRESH_IDENTITY_RETRY:
        return "omitted_for_fresh_identity_retry"
    if _looks_like_runaway_json(raw_response) or _looks_like_wrong_root_wrapper(raw_response):
        return "omitted_for_runaway_or_wrong_root"
    return "truncated_4000_chars"


def _previous_invalid_response_for_prompt(raw_response: str, policy: str) -> str:
    if policy.startswith("omitted_"):
        return f"[{policy}: previous invalid raw output intentionally omitted]"
    return _truncate_for_prompt(raw_response, max_chars=4000)


def _repair_error_diagnostic(raw_response: str, error_message: str, expected_scene_id: str) -> dict[str, Any]:
    text = str(raw_response or "")
    first_scene_id = _first_json_scene_id(text)
    root_key = _first_json_root_key(text)
    return {
        "error_message": str(error_message or ""),
        "expected_scene_id": expected_scene_id,
        "first_scene_id_seen": first_scene_id,
        "wrong_scene_id_seen": bool(first_scene_id and first_scene_id != expected_scene_id),
        "first_root_key_seen": root_key,
        "forbidden_root_key_seen": root_key in _FORBIDDEN_ROOT_KEYS if root_key else False,
        "runaway_json_detected": _looks_like_runaway_json(text),
        "wrong_root_wrapper_detected": _looks_like_wrong_root_wrapper(text),
        "raw_response_chars": len(text),
    }


def _looks_like_runaway_json(raw_response: str) -> bool:
    text = str(raw_response or "")
    scene_key_count = text.count('"scene_id"') + text.count('\\"scene_id\\"')
    content_key_count = text.count('"content"') + text.count('\\"content\\"')
    if scene_key_count >= 8 and content_key_count >= 6:
        return True
    if re.search(r'"content"\s*:\s*\{', text):
        return True
    if re.search(r'"content"\s*:\s*"\s*\{\s*\\?n?\s*\\?"scene_id\\?"', text):
        return True
    return False


def _looks_like_wrong_root_wrapper(raw_response: str) -> bool:
    root_key = _first_json_root_key(raw_response)
    return bool(root_key and root_key in _FORBIDDEN_ROOT_KEYS)


def _first_json_root_key(text: str) -> str | None:
    match = re.search(r'^\s*\{\s*"([^"{}]+)"\s*:', str(text or ""))
    if match:
        return match.group(1).strip()
    match = re.search(r'^\s*\{\s*\\"([^\\"]+)\\"\s*:', str(text or ""))
    if match:
        return match.group(1).strip()
    return None


def _load_rewrite_prompt_template(filename: str) -> Any:
    path = REWRITE_PROMPT_TEMPLATE_ROOT / filename
    cache_key = str(path)
    if cache_key not in _REWRITE_PROMPT_TEMPLATE_CACHE:
        if not path.exists():
            raise RewriteEngineError(f"Missing rewrite prompt template: {path}")
        if path.suffix == ".json":
            _REWRITE_PROMPT_TEMPLATE_CACHE[cache_key] = json.loads(path.read_text(encoding="utf-8"))
        else:
            _REWRITE_PROMPT_TEMPLATE_CACHE[cache_key] = path.read_text(encoding="utf-8").strip()
    return _REWRITE_PROMPT_TEMPLATE_CACHE[cache_key]


def _fill_rewrite_prompt_template(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        rendered = value
        for token, replacement in replacements.items():
            if token not in rendered:
                continue
            if isinstance(replacement, str):
                replacement_text = replacement
            else:
                replacement_text = json.dumps(replacement, ensure_ascii=False)
            rendered = rendered.replace(token, replacement_text)
        return rendered
    if isinstance(value, list):
        return [_fill_rewrite_prompt_template(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _fill_rewrite_prompt_template(item, replacements) for key, item in value.items()}
    return value


def _render_rewrite_prompt_template(filename: str, replacements: dict[str, Any]) -> dict[str, Any]:
    template = _load_rewrite_prompt_template(filename)
    if not isinstance(template, dict):
        raise RewriteEngineError(f"Rewrite prompt template must be a JSON object: {filename}")
    rendered = _fill_rewrite_prompt_template(template, replacements)
    if not isinstance(rendered, dict):
        raise RewriteEngineError(f"Rendered rewrite prompt template must be a JSON object: {filename}")
    return rendered


def _render_rewrite_text_template(filename: str, replacements: dict[str, Any]) -> str:
    template = _load_rewrite_prompt_template(filename)
    if not isinstance(template, str):
        raise RewriteEngineError(f"Rewrite text prompt template must be plain text: {filename}")
    rendered = _fill_rewrite_prompt_template(template, replacements)
    if not isinstance(rendered, str):
        raise RewriteEngineError(f"Rendered rewrite text prompt template must be plain text: {filename}")
    return rendered.strip()


def build_per_scene_rewrite_prompt(
    *,
    scene: ParsedScene,
    directive: SceneRewriteDirective,
    plan: TransferPlan,
    scene_position_index: int,
    scene_count: int,
    max_scene_chars: int,
    prompt_version: str = PROMPT_VERSION_V1,
) -> str:
    """Build a curve-guided one-scene request from versioned prompt assets."""

    prompt_version = _normalize_prompt_version(prompt_version)
    assets = _resolve_prompt_assets(PROMPT_STRATEGY_CURVE_GUIDED, prompt_version)
    content, was_truncated = _truncate_scene_text(scene.content, max_scene_chars=max_scene_chars)
    replacements = {
        "__SCENE_ID__": scene.scene_id,
        "__SCENE_TITLE__": scene.title,
        "__SCENE_INDEX__": scene.scene_index,
        "__SCENE_CONTENT__": content,
        "__WAS_TRUNCATED__": was_truncated,
        "__SOURCE_FILM_ID__": _film_id_from_path(plan.feature_source_path),
        "__REFERENCE_FILM_ID__": _film_id_from_path(plan.reference_feature_source_path),
        "__SELECTED_FEATURES__": plan.selected_features,
        "__SOURCE_INTERVAL_SCENE_IDS__": plan.source_scene_ids,
        "__REFERENCE_INTERVAL_SCENE_IDS__": plan.reference_scene_ids,
        "__ZERO_BASED_INDEX__": scene_position_index,
        "__ONE_BASED_INDEX__": scene_position_index + 1,
        "__SCENE_COUNT__": scene_count,
        "__SCENE_SPECIFIC_DIRECTIVE__": directive.model_dump(mode="json"),
    }
    if assets["output_contract"] == OUTPUT_CONTRACT_CONTENT_ONLY:
        return _render_rewrite_text_template(assets["user"], replacements)
    payload = _render_rewrite_prompt_template(assets["user"], replacements)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_per_scene_direct_prompt(
    *,
    scene: ParsedScene,
    directive: SceneRewriteDirective,
    plan: TransferPlan,
    scene_position_index: int,
    scene_count: int,
    max_scene_chars: int,
    prompt_version: str = PROMPT_VERSION_V1,
) -> str:
    """Build the direct baseline while keeping hidden numeric targets invisible."""

    prompt_version = _normalize_prompt_version(prompt_version)
    assets = _resolve_prompt_assets(PROMPT_STRATEGY_DIRECT_PROMPT, prompt_version)
    content, was_truncated = _truncate_scene_text(scene.content, max_scene_chars=max_scene_chars)
    selected_aspects = [_direct_feature_label(feature) for feature in plan.selected_features]
    replacements = {
        "__SCENE_ID__": scene.scene_id,
        "__SCENE_TITLE__": scene.title,
        "__SCENE_INDEX__": scene.scene_index,
        "__SCENE_CONTENT__": content,
        "__WAS_TRUNCATED__": was_truncated,
        "__SOURCE_FILM_ID__": _film_id_from_path(plan.feature_source_path),
        "__SELECTED_REWRITE_ASPECTS__": selected_aspects,
        "__SOURCE_INTERVAL_SCENE_IDS__": plan.source_scene_ids,
        "__ZERO_BASED_INDEX__": scene_position_index,
        "__ONE_BASED_INDEX__": scene_position_index + 1,
        "__SCENE_COUNT__": scene_count,
        "__DIRECT_REWRITE_INSTRUCTION__": directive.directive,
    }
    if assets["output_contract"] == OUTPUT_CONTRACT_CONTENT_ONLY:
        return _render_rewrite_text_template(assets["user"], replacements)
    payload = _render_rewrite_prompt_template(assets["user"], replacements)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_per_scene_no_guidance_prompt(
    *, scene: ParsedScene, scene_position_index: int, scene_count: int,
    max_scene_chars: int = 12000,
) -> str:
    """Source-only projection: target plans and directives cannot enter this API.

    Keep the canonical text limit, output contract and repair path. Scene text
    itself may contain any words; tests check hidden-control independence rather
    than censoring the screenplay's vocabulary.
    """
    content, truncated = _truncate_scene_text(scene.content, max_scene_chars=max_scene_chars)
    payload = _render_rewrite_prompt_template("no_guidance_per_scene_prompt_v0.json", {
        "__SCENE_ID__": scene.scene_id, "__SCENE_TITLE__": scene.title,
        "__SCENE_INDEX__": scene.scene_index, "__SCENE_CONTENT__": content,
        "__WAS_TRUNCATED__": truncated, "__ONE_BASED_INDEX__": scene_position_index + 1,
        "__SCENE_COUNT__": scene_count,
    })
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _prompt_profile(strategy: str) -> str:
    return {PROMPT_STRATEGY_DIRECT_PROMPT: "DP-v1", PROMPT_STRATEGY_CURVE_GUIDED: "CG-v1",
            PROMPT_STRATEGY_NO_GUIDANCE: "NG-v0"}[strategy]


def parse_per_scene_rewrite_output(
    raw_text: str,
    *,
    expected_scene: ParsedScene,
    strict_final_content: bool = True,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    return_metadata: bool = False,
) -> tuple[RewrittenScene, bool, list[str]] | tuple[RewrittenScene, bool, list[str], dict[str, Any]]:
    """Parse the v1 structured-JSON one-scene contract."""

    try:
        normalized = normalize_rewrite_raw_text(
            raw_text,
            mode="per_scene",
            expected_scene_id=expected_scene.scene_id,
            original_content_by_id={expected_scene.scene_id: expected_scene.content},
            strict_final_content=strict_final_content,
            min_rewrite_char_ratio=min_rewrite_char_ratio,
            max_rewrite_char_ratio=max_rewrite_char_ratio,
        )
    except Exception as exc:  # noqa: BLE001
        raise RewriteEngineError(f"Could not parse local model response as one-scene JSON: {exc}") from exc

    scene = normalized.output.rewritten_scenes[0]
    warnings = [f"{expected_scene.scene_id}: {action}" for action in normalized.normalization_actions]
    warnings.extend(str(item) for item in normalized.validation_warnings)
    if len(scene.content.split()) < 5:
        warnings.append(f"{expected_scene.scene_id}: rewritten content is very short.")
    metadata = {
        "normalizer_version": NORMALIZER_VERSION,
        "raw_response_shape": normalized.raw_response_shape,
        "normalization_actions": normalized.normalization_actions,
        "validation_warnings": normalized.validation_warnings,
        "rejected_reason": normalized.rejected_reason,
        "scene_coverage_exact": normalized.scene_coverage_exact,
        "model_output_contract": OUTPUT_CONTRACT_STRUCTURED_JSON,
    }
    if return_metadata:
        return scene, normalized.repaired, warnings, metadata
    return scene, normalized.repaired, warnings


def parse_per_scene_output(
    raw_text: str,
    *,
    expected_scene: ParsedScene,
    output_contract: str,
    strict_final_content: bool = True,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    return_metadata: bool = False,
) -> tuple[RewrittenScene, bool, list[str]] | tuple[RewrittenScene, bool, list[str], dict[str, Any]]:
    """Dispatch one-scene parsing by the model-visible output contract."""

    if output_contract == OUTPUT_CONTRACT_CONTENT_ONLY:
        return parse_per_scene_content_output(
            raw_text,
            expected_scene=expected_scene,
            strict_final_content=strict_final_content,
            min_rewrite_char_ratio=min_rewrite_char_ratio,
            max_rewrite_char_ratio=max_rewrite_char_ratio,
            return_metadata=return_metadata,
        )
    return parse_per_scene_rewrite_output(
        raw_text,
        expected_scene=expected_scene,
        strict_final_content=strict_final_content,
        min_rewrite_char_ratio=min_rewrite_char_ratio,
        max_rewrite_char_ratio=max_rewrite_char_ratio,
        return_metadata=return_metadata,
    )


def parse_per_scene_content_output(
    raw_text: str,
    *,
    expected_scene: ParsedScene,
    strict_final_content: bool = True,
    min_rewrite_char_ratio: float = 0.35,
    max_rewrite_char_ratio: float = 3.0,
    return_metadata: bool = False,
) -> tuple[RewrittenScene, bool, list[str]] | tuple[RewrittenScene, bool, list[str], dict[str, Any]]:
    """Package a v2 content-only scene into the stable internal JSON contract."""

    content, extraction_mode, actions = _extract_content_only_text(raw_text)
    if not content.strip():
        raise RewriteEngineError(f"Content-only rewrite was empty for {expected_scene.scene_id}")
    if strict_final_content and _looks_like_analysis_only(content):
        raise RewriteEngineError(
            f"Content-only rewrite contained analysis/plan text instead of a final scene for {expected_scene.scene_id}"
        )
    repetition_reason = _detect_runaway_content(content, expected_scene_id=expected_scene.scene_id)
    if repetition_reason:
        raise RewriteEngineError(
            f"Content-only rewrite rejected for {expected_scene.scene_id}: {repetition_reason}"
        )

    original_chars = max(1, len(expected_scene.content.strip()))
    ratio = len(content.strip()) / original_chars
    if min_rewrite_char_ratio and ratio < float(min_rewrite_char_ratio):
        raise RewriteEngineError(
            f"Content-only rewrite for {expected_scene.scene_id} is too short: ratio={ratio:.3f}, "
            f"minimum={float(min_rewrite_char_ratio):.3f}"
        )
    if max_rewrite_char_ratio and ratio > float(max_rewrite_char_ratio):
        raise RewriteEngineError(
            f"Content-only rewrite for {expected_scene.scene_id} is too long: ratio={ratio:.3f}, "
            f"maximum={float(max_rewrite_char_ratio):.3f}"
        )

    scene = RewrittenScene(
        scene_id=expected_scene.scene_id,
        title=expected_scene.title,
        content=content,
        change_summary="",
    )
    warnings = [f"{expected_scene.scene_id}: {action}" for action in actions]
    if len(scene.content.split()) < 5:
        warnings.append(f"{expected_scene.scene_id}: rewritten content is very short.")
    metadata = {
        "normalizer_version": "content_only_extractor.v1",
        "raw_response_shape": extraction_mode,
        "normalization_actions": actions,
        "validation_warnings": warnings,
        "rejected_reason": None,
        "scene_coverage_exact": True,
        "model_output_contract": OUTPUT_CONTRACT_CONTENT_ONLY,
        "system_assigned_scene_id": True,
        "system_assigned_title": True,
    }
    if return_metadata:
        return scene, bool(actions), warnings, metadata
    return scene, bool(actions), warnings


def _extract_content_only_text(raw_text: str) -> tuple[str, str, list[str]]:
    text = str(raw_text or "").strip()
    actions: list[str] = []
    extraction_mode = "raw_text"
    fence = re.fullmatch(
        r"```(?:screenplay|text|markdown)?\s*\n?(.*?)\n?```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fence:
        text = fence.group(1).strip()
        actions.append("removed_single_outer_code_fence")
        extraction_mode = "fenced_text"

    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    if payload is not None:
        candidate = _content_from_json_fallback(payload)
        if candidate is not None:
            text = candidate.strip()
            actions.append("extracted_content_from_unrequested_json_wrapper")
            extraction_mode = "json_fallback"

    prefix = re.match(
        r"^\s*(?:here(?:'s| is)\s+the\s+rewritten\s+scene|rewritten\s+scene)\s*:\s*",
        text,
        flags=re.IGNORECASE,
    )
    if prefix:
        text = text[prefix.end():].lstrip()
        actions.append("removed_rewritten_scene_preamble")
    return text.strip(), extraction_mode, actions


def _content_from_json_fallback(payload: Any) -> str | None:
    if isinstance(payload, list) and len(payload) == 1:
        return _content_from_json_fallback(payload[0])
    if not isinstance(payload, dict):
        return None
    for key in ("content", "rewritten_text", "modifiedContent", "description"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("scene", "rewritten_scene"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _content_from_json_fallback(value)
            if nested:
                return nested
    for key in ("rewritten_scenes", "scenes", "revised_scenes", "rewrites"):
        value = payload.get(key)
        if isinstance(value, list) and len(value) == 1:
            nested = _content_from_json_fallback(value[0])
            if nested:
                return nested
    dict_values = [value for value in payload.values() if isinstance(value, dict)]
    if len(dict_values) == 1:
        return _content_from_json_fallback(dict_values[0])
    return None


def _looks_like_analysis_only(content: str) -> bool:
    text = str(content or "").strip()
    first = text[:240].lower()
    analysis_prefixes = (
        "analysis:",
        "rewrite plan:",
        "plan:",
        "changes made:",
        "explanation:",
        "i will rewrite",
        "to rewrite this scene",
    )
    if not any(first.startswith(prefix) for prefix in analysis_prefixes):
        return False
    screenplay_cues = re.search(
        r"(?mi)^\s*(?:INT\.|EXT\.|INT/EXT\.|I/E\.|[A-Z][A-Z0-9 .'-]{2,}:)\s*",
        text,
    )
    return screenplay_cues is None


def _extract_single_scene_payload(payload: Any, *, expected_scene_id: str) -> tuple[dict[str, Any], bool, list[str]]:
    repaired = False
    warnings: list[str] = []
    if isinstance(payload, list):
        if len(payload) != 1:
            raise RewriteEngineError(f"Expected one rewritten scene for {expected_scene_id}, got list of {len(payload)} scenes.")
        if not isinstance(payload[0], dict):
            raise RewriteEngineError(f"Expected one JSON object for {expected_scene_id}.")
        return dict(payload[0]), True, [f"{expected_scene_id}: normalized single-item list response."]

    if not isinstance(payload, dict):
        raise RewriteEngineError(f"Expected one JSON object for {expected_scene_id}.")

    for list_key in ("rewritten_scenes", "scenes", "revised_scenes", "rewrites"):
        if list_key in payload:
            value = payload[list_key]
            if isinstance(value, list):
                if len(value) != 1:
                    raise RewriteEngineError(f"Expected one rewritten scene for {expected_scene_id}, got {len(value)} items under {list_key}.")
                if not isinstance(value[0], dict):
                    raise RewriteEngineError(f"Expected one scene object under {list_key} for {expected_scene_id}.")
                warnings.append(f"{expected_scene_id}: normalized root key {list_key!r} to one scene object.")
                return dict(value[0]), True, warnings
            if isinstance(value, dict):
                warnings.append(f"{expected_scene_id}: normalized root key {list_key!r} object to one scene object.")
                return dict(value), True, warnings
            raise RewriteEngineError(f"Root key {list_key} did not contain a scene object for {expected_scene_id}.")

    if "scene" in payload:
        value = payload["scene"]
        if isinstance(value, dict):
            warnings.append(f"{expected_scene_id}: normalized root key 'scene' to one scene object.")
            return dict(value), True, warnings
        raise RewriteEngineError(f"Root key scene did not contain an object for {expected_scene_id}.")

    # Local models often return {"scene_024": {"content": "..."}} or {"024": {...}}.
    dict_scene_values = [(key, value) for key, value in payload.items() if isinstance(value, dict)]
    if dict_scene_values and all(_looks_like_scene_key(key) for key, _ in dict_scene_values):
        if len(dict_scene_values) != 1:
            raise RewriteEngineError(f"Expected one keyed scene for {expected_scene_id}, got {len(dict_scene_values)} keyed scenes.")
        key, value = dict_scene_values[0]
        scene_payload = dict(value)
        scene_payload.setdefault("scene_id", key)
        warnings.append(f"{expected_scene_id}: normalized keyed scene object {key!r}.")
        return scene_payload, True, warnings

    if any(key in payload for key in ("scene_id", "sceneId", "id", "scene_number", "content", "modifiedContent", "rewritten_text", "description")):
        return dict(payload), False, warnings

    raise RewriteEngineError(f"Could not identify a single rewritten scene object for {expected_scene_id}.")


def _per_scene_system_instruction(*, prompt_version: str = PROMPT_VERSION_V1) -> str:
    assets = _resolve_prompt_assets(PROMPT_STRATEGY_CURVE_GUIDED, prompt_version)
    return str(_load_rewrite_prompt_template(assets["system"]))


def _per_scene_direct_system_instruction(*, prompt_version: str = PROMPT_VERSION_V1) -> str:
    assets = _resolve_prompt_assets(PROMPT_STRATEGY_DIRECT_PROMPT, prompt_version)
    return str(_load_rewrite_prompt_template(assets["system"]))


def _per_scene_repair_prompt(
    *,
    expected_scene_id: str,
    expected_scene_title: str,
    original_prompt: str,
    raw_response: str,
    error_message: str,
    attempt_number: int,
    max_attempts: int,
    repair_mode: str,
) -> str:
    previous_response_policy = _previous_invalid_response_policy(raw_response, repair_mode)
    previous_response = _previous_invalid_response_for_prompt(raw_response, previous_response_policy)
    payload = _render_rewrite_prompt_template(
        REPAIR_PER_SCENE_TEMPLATE,
        {
            "__EXPECTED_SCENE_ID__": expected_scene_id,
            "__EXPECTED_SCENE_TITLE__": expected_scene_title,
            "__ATTEMPT_NUMBER__": attempt_number,
            "__MAX_ATTEMPTS__": max_attempts,
            "__ERROR_MESSAGE__": error_message,
            "__REPAIR_MODE__": repair_mode,
            "__ERROR_DIAGNOSTIC__": _repair_error_diagnostic(raw_response, error_message, expected_scene_id),
            "__PREVIOUS_INVALID_RESPONSE_POLICY__": previous_response_policy,
            "__ORIGINAL_ONE_SCENE_REQUEST__": json.loads(original_prompt),
            "__PREVIOUS_INVALID_RESPONSE__": previous_response,
        },
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_prompt_strategy(value: str) -> str:
    strategy = str(value or PROMPT_STRATEGY_CURVE_GUIDED).strip().lower().replace("-", "_")
    aliases = {
        "curve": PROMPT_STRATEGY_CURVE_GUIDED,
        "curve_guided": PROMPT_STRATEGY_CURVE_GUIDED,
        "feature_curve": PROMPT_STRATEGY_CURVE_GUIDED,
        "feature_curve_guided": PROMPT_STRATEGY_CURVE_GUIDED,
        "direct": PROMPT_STRATEGY_DIRECT_PROMPT,
        "direct_prompt": PROMPT_STRATEGY_DIRECT_PROMPT,
        "direct_prompting": PROMPT_STRATEGY_DIRECT_PROMPT,
        "no_guidance": PROMPT_STRATEGY_NO_GUIDANCE,
        "ng_v0": PROMPT_STRATEGY_NO_GUIDANCE,
    }
    if strategy not in aliases:
        raise RewriteEngineError(
            f"Unsupported prompt strategy: {value}. Expected curve_guided or direct_prompt."
        )
    return aliases[strategy]


def _direct_feature_label(feature: str) -> str:
    return _DIRECT_FEATURE_LABELS.get(feature, str(feature))


def _looks_like_scene_key(key: Any) -> bool:
    text = str(key or "")
    return text.isdigit() or text.lower().startswith("scene")


def _film_id_from_path(path_value: Any) -> str | None:
    if not path_value:
        return None
    parts = Path(str(path_value)).parts
    if "films" in parts:
        index = parts.index("films")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None
