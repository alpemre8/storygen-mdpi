"""Owned technical bindings for the original E03/E04 protocol APIs."""

from pathlib import Path
from contextlib import contextmanager
import importlib
import importlib.util
from storygen_platform.engine.common import StoryGenError, read, file_sha
from storygen_platform.engine.science_io import invoke

ROOT = Path(__file__).resolve().parents[2]
APIS = {
    "e03_repeatability": "repetition_api",
    "e03_dp48_extension": "dp48_api",
    "e04_matched_prompt": "matched_prompt_api",
}


@contextmanager
def technical_paths(module, config, locations):
    """Resolve old logical workspace/owner paths directly to two active roots."""
    original = module.Path
    base = type(Path())

    class MappedPath(base):
        def __new__(cls, *parts):
            value = Path(*parts)
            if value.is_absolute() and any(
                owner in value.parts
                for owner in {
                    *locations.roots,
                    "story_generation",
                    "story_generation_blocks_versions",
                }
            ):
                value = Path(locations.relocate(str(value)))
            return super().__new__(cls, str(value))

        def __truediv__(self, other):
            return type(self)(Path(str(self)) / other)

    module.Path = MappedPath
    try:
        yield
    finally:
        module.Path = original


def execute_bound(key, stage, config, context, *, locations, owned_live, sources):
    api = importlib.import_module("storygen_protocol_science." + APIS[key])
    output = Path(context.artifact_directory)
    if stage == "prepare":
        first = next(iter(config["tasksets"].values()))
        protocol_root = Path(first).parents[1]
        config["migration_binding"]["protocol_root"] = str(protocol_root)
        parent_path = Path(config["migration_binding"]["parent"]["path"])
        parent = read(parent_path)
        names = ["P01.json"]
        if key == "e03_dp48_extension":
            names.extend(["manifests/BEFORE_CHANGES.json", "manifests/PLANNED_NEW_EXECUTIONS.json"])
        for name in names:
            source = parent_path.parent / name
            expected = parent["protected"].get(parent["roots"]["rewrite"] + "/" + name)
            if (
                not source.is_file()
                or expected is None
                or file_sha(source) != expected.removeprefix("sha256:")
            ):
                raise StoryGenError("Original protocol metadata missing/changed: " + name)
            (protocol_root / name).parent.mkdir(parents=True, exist_ok=True)
            (protocol_root / name).write_bytes(source.read_bytes())
    # Original load_config also checked obsolete five-repo working-tree states.
    # Exact new-run config/source/input locks now enforce that technical boundary;
    # the original scientific preflight below remains intact.
    old_load = getattr(api, "load_config", None)
    old_read = api.read
    old_sha = api.sha

    def mapped(path):
        value = Path(path)
        if any(
            owner in value.parts
            for owner in {*locations.roots, "story_generation", "story_generation_blocks_versions"}
        ):
            return Path(locations.relocate(str(value)))
        return value

    spec = importlib.util.spec_from_file_location(
        "_sg_prior_e03", Path(__file__).with_name("prior_e03.py")
    )
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    api.read = lambda path: prior.normalize(old_read(mapped(path)), locations)
    api.sha = lambda path: old_sha(mapped(path))
    if old_load is not None:
        api.load_config = lambda run: config
    if key == "e03_dp48_extension":
        old_extension = api.load_extension_config
        api.load_extension_config = lambda run: config
        old_verify = api.verify_original
        api.verify_original = lambda original, before: prior.verify_original(
            original, before, context=context, locations=locations, technical_paths=technical_paths
        )
    try:
        with technical_paths(api, config, locations):
            if stage in {"prepare", "preflight"}:
                protocol_root = Path(config["migration_binding"]["protocol_root"])
                invoke(
                    "storygen_protocol_science." + APIS[key] + ":preflight",
                    {"run": protocol_root},
                    roots=sources,
                    context=context,
                )
            elif stage == "generate":
                condition = context.configuration["condition"]
                executions = config["executions"][condition]
                for item in executions:
                    item["generation"] = str(
                        output / "generation" / condition / Path(item["generation"]).name
                    )
                config["roots"] = {**config["roots"], "rewrite": str(output)}
                with owned_live(config, context, "gemma"):
                    if key == "e03_dp48_extension":
                        invoke(
                            "storygen_protocol_science.dp48_api:generate_extension",
                            {"config": config},
                            roots=sources,
                            context=context,
                        )
                    else:
                        invoke(
                            "storygen_protocol_science." + APIS[key] + ":generation",
                            {
                                "config" if key == "e03_repeatability" else "c": config,
                                "condition": condition,
                            },
                            roots=sources,
                            context=context,
                        )
            elif stage == "validate_generation":
                invoke(
                    "storygen_protocol_science." + APIS[key] + ":validate_generation",
                    {"c" if key == "e04_matched_prompt" else "config": config},
                    roots=sources,
                    context=context,
                )
            elif stage == "remeasure":
                for condition, executions in config["executions"].items():
                    for item in executions:
                        # Keep the original feature-set identity, even though its
                        # physical run directory now belongs to this attempt.
                        item["reanalysis"] = str(
                            output / "features" / Path(item["reanalysis"]).name
                        )
                config["roots"] = {**config["roots"], "rewrite": str(output)}
                with owned_live(config, context, "qwen"):
                    entry = (
                        "storygen_protocol_science.dp48_api:reanalyze_extension"
                        if key == "e03_dp48_extension"
                        else "storygen_protocol_science.repetition_api:reanalysis"
                    )
                    # E04 reuses the original repetition remeasurement function.
                    target = importlib.import_module(entry.split(":")[0])
                    with technical_paths(target, config, locations):
                        invoke(entry, {"config": config}, roots=sources, context=context)
            elif stage == "evaluate":
                config["evaluation_output"] = str(output / "evaluation")
                entry = {
                    "e03_repeatability": "repeatability:evaluate",
                    "e03_dp48_extension": "dp48_extension:evaluate_extended",
                    "e04_matched_prompt": "matched_prompt:evaluate",
                }[key]
                invoke(
                    "storygen_evaluation." + entry,
                    {"config": config},
                    roots=sources,
                    context=context,
                )
            else:
                raise StoryGenError("Unknown original repeated protocol stage")
    finally:
        api.read, api.sha = old_read, old_sha
        if old_load is not None:
            api.load_config = old_load
        if key == "e03_dp48_extension":
            api.load_extension_config = old_extension
            api.verify_original = old_verify
    return config
