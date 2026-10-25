"""Read-only address binding for the original E03 controls used by DP48.

The original generation/seed and metric comparators still run. Immutable old
JSON bytes stay untouched; only declared file locators are resolved in memory.
"""

from pathlib import Path
from contextlib import contextmanager, ExitStack
import importlib
import subprocess
import sys
from storygen_platform.engine.common import read, file_sha, write_json, StoryGenError

ROOT = Path(__file__).resolve().parents[2]
OWNERS = {
    "storygen-rewrite",
    "storygen-rewrite-depot",
    "storygen-feature-extraction",
    "storygen-feature-extraction-depot",
    "storygen-evaluation",
    "storygen-evaluation-depot",
    "story_generation",
    "story_generation_blocks_versions",
}
FIELDS = {
    "path",
    "root",
    "generation",
    "reanalysis",
    "rewrite_output",
    "measurement_output",
    "evaluation_output",
    "mapping",
    "base_runtime",
    "bound_taskset",
    "hidden_plans",
    "primary_requests",
    "frozen_plans",
    "records",
    "bindings",
    "text_diagnostics",
    "CG-v1",
    "DP-v1",
    "MP-DIR-v1",
    "MP-NUM-v1",
}


def map_path(path, locations):
    value = Path(path)
    return (
        Path(locations.relocate(str(value)))
        if any(owner in value.parts for owner in OWNERS)
        else value
    )


def normalize(value, locations, field=None):
    if isinstance(value, list):
        return [normalize(v, locations, field) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            mapped = (
                str(map_path(key, locations))
                if key.startswith("/") and any(owner in Path(key).parts for owner in OWNERS)
                else key
            )
            result[mapped] = normalize(item, locations, key)
        return result
    if (
        isinstance(value, str)
        and value.startswith("/")
        and (field in FIELDS or str(field).endswith(("_path", "_root", "_manifest", "_output")))
    ):
        return str(map_path(value, locations))
    return value


@contextmanager
def lookup_scope(locations, technical_paths):
    # Import before collecting aliases: these functions share the original IO
    # module but several import its public functions directly.
    for name in [
        "storygen_evaluation.dp48_extension",
        "storygen_evaluation.repeatability",
        "storygen_protocol_science.repetition_api",
    ]:
        importlib.import_module(name)
    modules = [
        m
        for name, m in list(sys.modules.items())
        if name.startswith(
            ("storygen_evaluation.", "storygen_protocol_science.", "storygen.rewrite_v1_3.")
        )
    ]
    saved = []
    with ExitStack() as scope:
        for module in modules:
            if hasattr(module, "Path"):
                scope.enter_context(technical_paths(module, {}, locations))
            for name in ["read_json", "read", "sha256_file", "sha"]:
                function = getattr(module, name, None)
                if not callable(function):
                    continue
                saved.append((module, name, function))

                def bound(
                    path,
                    *args,
                    _original=function,
                    _normalize=name in ["read_json", "read"],
                    **kwargs,
                ):
                    value = _original(map_path(path, locations), *args, **kwargs)
                    return normalize(value, locations) if _normalize else value

                setattr(module, name, bound)
        try:
            yield
        finally:
            for module, name, function in reversed(saved):
                setattr(module, name, function)


def verify_original(original, before, *, context, locations, technical_paths):
    original = map_path(original, locations)
    config_path = original / "CONFIG.json"
    expected = before["original_config_sha256"].removeprefix("sha256:")
    if (
        file_sha(config_path) != expected
        or (original / "CONFIG.sha256").read_text().strip().removeprefix("sha256:") != expected
    ):
        raise StoryGenError("Original E03 configuration seal changed")
    if map_path(before["original_root"], locations) != original:
        raise StoryGenError("Original E03 root differs from frozen DP48 dependency")
    raw = read(config_path)
    refs = []
    for owner, commit in raw["source_commits"].items():
        subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "-e", commit + "^{commit}"])
        refs.append({"owner": owner, "commit": commit, "historical_commit_object": "PRESERVED"})
    with lookup_scope(locations, technical_paths):
        original_config = normalize(raw, locations)
        technical = importlib.import_module("storygen_protocol_science.technical")
        repetition = importlib.import_module("storygen_protocol_science.repetition_api")
        seeds = importlib.import_module("storygen.rewrite_v1_3.repeatability")
        for stage in ("GENERATE_CG", "GENERATE_DP", "VALIDATE_GENERATION", "REANALYZE", "EVALUATE"):
            technical.require_stage(original, stage)
        repetition.validate_generation(original_config)
        schedule = read(original / "manifests/REQUEST_SEEDS.json")
        if (
            original_config["seed_schedule"] != seeds.SEED_SCHEDULE
            or schedule["schedule"] != seeds.SEED_SCHEDULE
        ):
            raise StoryGenError("Original E03 seed schedule differs")
        for row in schedule["requests"]:
            for attempt, key in [(1, "primary_seed"), (2, "repair_seed")]:
                if row[key] != seeds.request_seed(
                    row["condition"], row["repetition_id"], row["task_id"], row["scene_id"], attempt
                ):
                    raise StoryGenError("Original E03 request seed derivation differs")
        result = importlib.import_module(
            "storygen_evaluation.dp48_extension"
        ).verify_original_records(original_config)
    proof = {
        "original_config_sha256": expected,
        "source_commits": refs,
        "native_scientific_verification": result,
        "retained_historical_protected_entries": len(before["protected"]),
        "technical_policy": "Original stage artifact seals, seeds, generation and metric comparators executed; old five-repo working-tree/cache inventory retained unchanged as historical provenance. New engine locks its exact current implementation.",
    }
    write_json(Path(context.artifact_directory) / "PRIOR_E03_BINDING_PROOF.json", proof)
    return original_config, result
